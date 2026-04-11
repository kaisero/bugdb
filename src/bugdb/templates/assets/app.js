/**
 * BugDB - Client-side search and filter functionality.
 *
 * This file is wrapped in an IIFE so no declarations leak onto `window`.
 * All DOM rendering goes through `createElement` + `textContent` and
 * `addEventListener`; no `innerHTML` interpolation with vendor-sourced
 * data (see v1.0.3 frontend security review). Attribute-context XSS
 * was previously reachable via inline `onclick=` templates plus a
 * `textContent`-based `escapeHtml` that didn't escape quotes.
 */
(() => {
    'use strict';

    // =====================================================================
    // State
    // =====================================================================

    let allIssues = [];
    let filteredIssues = [];
    let currentFilters = {
        search: '',
        product: '',
        version: '',
        type: '',
    };
    let fixReleasesMap = {}; // Map of bug_id -> array of fix releases
    let knownIssuesMap = {}; // Map of bug_id -> array of known-in releases
    let releaseNotesData = null;

    // Pagination state
    let currentPage = 1;
    let pageSize = 50;

    // Versions that should not be displayed in issue cards (e.g. SaaS products)
    const HIDDEN_VERSIONS = new Set(['SaaS', 'Unknown']);

    const isHiddenVersion = (version) => HIDDEN_VERSIONS.has(version);

    // Autocomplete state
    let productOptions = [];
    let versionOptions = [];
    const typeOptions = [
        { id: 'known', name: 'Known Issues' },
        { id: 'addressed', name: 'Addressed Issues' },
    ];
    let highlightedProductIndex = -1;
    let highlightedVersionIndex = -1;
    let highlightedTypeIndex = -1;

    // DOM Elements — captured at IIFE eval time. The <script> tag is at
    // the end of <body> so the DOM is already parsed by the time this
    // runs; init() additionally waits for DOMContentLoaded before
    // touching state.
    const elements = {
        search: document.getElementById('search'),
        productFilter: document.getElementById('product-filter'),
        productDropdown: document.getElementById('product-dropdown'),
        versionFilter: document.getElementById('version-filter'),
        versionDropdown: document.getElementById('version-dropdown'),
        typeFilter: document.getElementById('type-filter'),
        typeDropdown: document.getElementById('type-dropdown'),
        results: document.getElementById('results'),
        resultsCount: document.getElementById('results-count'),
        resultsRange: document.getElementById('results-range'),
        pagination: document.getElementById('pagination'),
        pageSize: document.getElementById('page-size'),
        noResults: document.getElementById('no-results'),
        loading: document.getElementById('loading'),
        clearFilters: document.getElementById('clear-filters'),
        generatedDate: document.getElementById('generated-date'),
    };

    // =====================================================================
    // Helpers
    // =====================================================================

    // Attribute-safe HTML escape. The previous implementation used
    // `div.textContent = text; return div.innerHTML` which does NOT escape
    // single or double quotes — dangerous when interpolated into attribute
    // strings. This version is only kept around for the one case we still
    // need escaping for (aria-label templates that we build with
    // setAttribute, where the value is already safe — this function is
    // the defence-in-depth layer).
    const HTML_ESCAPE_MAP = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
        '/': '&#x2F;',
    };
    function escapeHtml(text) {
        if (text == null) return '';
        return String(text).replace(/[&<>"'/]/g, (ch) => HTML_ESCAPE_MAP[ch]);
    }

    // Small DOM builder. Every piece of text goes through textContent, not
    // innerHTML. Call sites read like JSX without the framework overhead.
    function el(tag, { className, text, children, onClick, attrs } = {}) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        if (children) {
            for (const child of children) {
                if (child != null) node.appendChild(child);
            }
        }
        if (onClick) node.addEventListener('click', onClick);
        if (attrs) {
            for (const [key, value] of Object.entries(attrs)) {
                if (value != null) node.setAttribute(key, value);
            }
        }
        return node;
    }

    // Remove every child of a node. Used to rebuild modal contents on
    // each open so we don't accumulate stale listeners / nodes.
    function clearChildren(node) {
        while (node.firstChild) node.removeChild(node.firstChild);
    }

    // Build an SVG icon from one or more path `d` strings. The path data
    // is hardcoded — never user-controlled — so building via
    // createElementNS is safe and avoids the innerHTML sink.
    const SVG_NS = 'http://www.w3.org/2000/svg';
    function createSvgIcon(paths, className = 'w-4 h-4') {
        const svg = document.createElementNS(SVG_NS, 'svg');
        svg.setAttribute('class', className);
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('viewBox', '0 0 24 24');
        const pathArray = Array.isArray(paths) ? paths : [paths];
        for (const d of pathArray) {
            const path = document.createElementNS(SVG_NS, 'path');
            path.setAttribute('stroke-linecap', 'round');
            path.setAttribute('stroke-linejoin', 'round');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('d', d);
            svg.appendChild(path);
        }
        return svg;
    }

    // Debounce helper (unchanged semantics, arrow form for brevity).
    function debounce(func, wait) {
        let timeout;
        return (...args) => {
            clearTimeout(timeout);
            timeout = setTimeout(() => func(...args), wait);
        };
    }

    // Minimal runtime validator for the data.json payload. Pydantic
    // enforces this server-side, but the file is fetched from a CDN at
    // runtime — any corruption or tampering between writer and reader
    // must not silently feed the render pipeline.
    function validateBugDatabase(data) {
        if (data === null || typeof data !== 'object') {
            throw new Error('data.json root is not an object');
        }
        if (!Array.isArray(data.products)) {
            throw new Error('data.json: products is not an array');
        }
        for (const product of data.products) {
            if (!product || typeof product !== 'object') {
                throw new Error('data.json contains a non-object product entry');
            }
            if (typeof product.id !== 'string' || typeof product.name !== 'string') {
                throw new Error('data.json product missing id/name strings');
            }
            if (!Array.isArray(product.versions)) {
                throw new Error(`data.json product ${product.id} has non-array versions`);
            }
        }
        return data;
    }

    // =====================================================================
    // Data transformation
    // =====================================================================

    function flattenIssues(data) {
        const issues = [];
        for (const product of data.products) {
            for (const version of product.versions) {
                for (const issue of version.known_issues || []) {
                    issues.push({
                        ...issue,
                        productId: product.id,
                        productName: product.name,
                        version: version.version,
                        releaseDate: version.release_date,
                        issueType: 'known',
                    });
                }
                for (const issue of version.addressed_issues || []) {
                    issues.push({
                        ...issue,
                        productId: product.id,
                        productName: product.name,
                        version: version.version,
                        releaseDate: version.release_date,
                        issueType: 'addressed',
                    });
                }
            }
        }
        return issues;
    }

    function buildFixReleasesMap(data) {
        const map = {};
        for (const product of data.products) {
            for (const version of product.versions) {
                for (const issue of version.addressed_issues || []) {
                    if (!map[issue.bug_id]) map[issue.bug_id] = [];
                    map[issue.bug_id].push({
                        productId: product.id,
                        productName: product.name,
                        version: version.version,
                        releaseDate: version.release_date,
                    });
                }
            }
        }
        for (const bugId in map) {
            map[bugId].sort((a, b) => compareVersions(b.version, a.version));
        }
        return map;
    }

    function buildKnownIssuesMap(data) {
        const map = {};
        for (const product of data.products) {
            for (const version of product.versions) {
                for (const issue of version.known_issues || []) {
                    if (!map[issue.bug_id]) map[issue.bug_id] = [];
                    map[issue.bug_id].push({
                        productId: product.id,
                        productName: product.name,
                        version: version.version,
                    });
                }
            }
        }
        for (const bugId in map) {
            map[bugId].sort((a, b) => compareVersions(b.version, a.version));
        }
        return map;
    }

    function shouldShowFixInfo(fixInfo) {
        if (!fixInfo) return false;
        const lowered = fixInfo.toLowerCase();
        return !lowered.includes('this issue is') &&
               !lowered.includes('resolved in') &&
               !lowered.includes('addressed in');
    }

    // Compare versions for sorting (handles 11.2.5, 2025.r5.0, SaaS, -h9 suffixes)
    function compareVersions(a, b) {
        if (a === 'SaaS') return 1;
        if (b === 'SaaS') return -1;
        if (a === 'Unknown') return -1;
        if (b === 'Unknown') return 1;

        const parseVersion = (v) => {
            const hotfixMatch = v.match(/^(.+?)-h(\d+)$/i);
            if (hotfixMatch) {
                return { base: hotfixMatch[1], hotfix: parseInt(hotfixMatch[2], 10) };
            }
            return { base: v, hotfix: 0 };
        };

        const parsedA = parseVersion(a);
        const parsedB = parseVersion(b);

        const normalizeBase = (base) =>
            base.replace(/r/gi, '.').split('.').filter((p) => p !== '');

        const partsA = normalizeBase(parsedA.base);
        const partsB = normalizeBase(parsedB.base);

        for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
            const numA = parseInt(partsA[i], 10) || 0;
            const numB = parseInt(partsB[i], 10) || 0;
            if (numA !== numB) return numA - numB;
        }

        return parsedA.hotfix - parsedB.hotfix;
    }

    function getFixReleasesForIssue(issue) {
        const fixes = fixReleasesMap[issue.bug_id] || [];
        return fixes.filter((fix) => fix.productId === issue.productId);
    }

    function getKnownReleasesForIssue(issue) {
        const knownReleases = knownIssuesMap[issue.bug_id] || [];
        return knownReleases.filter(
            (rel) => rel.productId === issue.productId && rel.version !== issue.version
        );
    }

    // =====================================================================
    // Filter state
    // =====================================================================

    function populateFilters(data) {
        productOptions = data.products.map((p) => ({ id: p.id, name: p.name }));
        updateVersionFilter(data);
    }

    function updateVersionFilter(data) {
        const selectedProduct = currentFilters.product;

        if (!selectedProduct) {
            elements.versionFilter.placeholder = 'Select a product first';
            elements.versionFilter.disabled = true;
            elements.versionFilter.value = '';
            versionOptions = [];
            return;
        }

        elements.versionFilter.disabled = false;
        elements.versionFilter.placeholder = 'All Versions';

        const versions = new Set();
        for (const product of data.products) {
            if (product.id === selectedProduct) {
                for (const version of product.versions) {
                    if (!isHiddenVersion(version.version)) {
                        versions.add(version.version);
                    }
                }
            }
        }

        versionOptions = Array.from(versions).sort((a, b) => {
            const partsA = a.split('.').map(Number);
            const partsB = b.split('.').map(Number);
            for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
                const numA = partsA[i] || 0;
                const numB = partsB[i] || 0;
                if (numA !== numB) return numB - numA;
            }
            return 0;
        });
    }

    function applyFilters() {
        filteredIssues = allIssues.filter((issue) => {
            if (currentFilters.search) {
                const searchLower = currentFilters.search.toLowerCase();
                const searchableText = [
                    issue.bug_id,
                    issue.description,
                    issue.symptoms,
                    issue.workaround,
                    ...(issue.affected_components || []),
                ]
                    .filter(Boolean)
                    .join(' ')
                    .toLowerCase();
                if (!searchableText.includes(searchLower)) return false;
            }

            if (currentFilters.product && issue.productId !== currentFilters.product) {
                return false;
            }
            if (currentFilters.version && issue.version !== currentFilters.version) {
                return false;
            }
            if (currentFilters.type && issue.issueType !== currentFilters.type) {
                return false;
            }
            return true;
        });

        renderResults();
    }

    // =====================================================================
    // Pagination
    // =====================================================================

    function getPaginationInfo() {
        const totalIssues = filteredIssues.length;
        const effectivePageSize = pageSize === 'all' ? totalIssues : pageSize;
        const totalPages =
            effectivePageSize > 0 ? Math.ceil(totalIssues / effectivePageSize) : 1;
        const startIndex = (currentPage - 1) * effectivePageSize;
        const endIndex = Math.min(startIndex + effectivePageSize, totalIssues);
        return { totalIssues, effectivePageSize, totalPages, startIndex, endIndex };
    }

    function renderResults() {
        clearChildren(elements.results);
        elements.resultsCount.textContent = filteredIssues.length;

        if (filteredIssues.length === 0) {
            elements.noResults.classList.remove('hidden');
            elements.pagination.classList.add('hidden');
            elements.resultsRange.textContent = '0';
            return;
        }

        elements.noResults.classList.add('hidden');

        const { totalIssues, totalPages, startIndex, endIndex } = getPaginationInfo();

        if (currentPage > totalPages) {
            currentPage = totalPages;
        }

        if (pageSize === 'all') {
            elements.resultsRange.textContent = totalIssues;
        } else {
            elements.resultsRange.textContent = `${startIndex + 1}-${endIndex}`;
        }

        // Batch appends via DocumentFragment to avoid per-card reflow.
        const pageIssues = filteredIssues.slice(startIndex, endIndex);
        const fragment = document.createDocumentFragment();
        for (const issue of pageIssues) {
            fragment.appendChild(createIssueCard(issue));
        }
        elements.results.appendChild(fragment);

        renderPagination(totalPages);
    }

    function renderPagination(totalPages) {
        clearChildren(elements.pagination);

        if (totalPages <= 1 || pageSize === 'all') {
            elements.pagination.classList.add('hidden');
            return;
        }

        elements.pagination.classList.remove('hidden');

        const disabledClass = 'bg-gray-100 text-gray-400 cursor-not-allowed';
        const enabledClass =
            'bg-white text-gray-700 hover:bg-gray-100 border border-gray-300';

        const prevBtn = el('button', {
            className: `px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                currentPage === 1 ? disabledClass : enabledClass
            }`,
            text: 'Previous',
            onClick: () => goToPage(currentPage - 1),
        });
        prevBtn.disabled = currentPage === 1;
        elements.pagination.appendChild(prevBtn);

        const pageNumbers = getPageNumbers(currentPage, totalPages);
        for (const pageNum of pageNumbers) {
            if (pageNum === '...') {
                elements.pagination.appendChild(
                    el('span', {
                        className: 'px-3 py-2 text-gray-500',
                        text: '...',
                    })
                );
            } else {
                const activeClass =
                    pageNum === currentPage
                        ? 'bg-pan-orange text-white'
                        : enabledClass;
                elements.pagination.appendChild(
                    el('button', {
                        className: `px-3 py-2 rounded-lg text-sm font-medium transition-colors ${activeClass}`,
                        text: String(pageNum),
                        onClick: () => goToPage(pageNum),
                    })
                );
            }
        }

        const nextBtn = el('button', {
            className: `px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                currentPage === totalPages ? disabledClass : enabledClass
            }`,
            text: 'Next',
            onClick: () => goToPage(currentPage + 1),
        });
        nextBtn.disabled = currentPage === totalPages;
        elements.pagination.appendChild(nextBtn);
    }

    function getPageNumbers(current, total) {
        if (total <= 7) {
            return Array.from({ length: total }, (_, i) => i + 1);
        }

        const pages = [1];

        if (current > 3) pages.push('...');

        const start = Math.max(2, current - 1);
        const end = Math.min(total - 1, current + 1);

        for (let i = start; i <= end; i++) {
            if (!pages.includes(i)) pages.push(i);
        }

        if (current < total - 2) pages.push('...');

        if (!pages.includes(total)) pages.push(total);

        return pages;
    }

    function goToPage(page) {
        const { totalPages } = getPaginationInfo();
        if (page < 1 || page > totalPages) return;

        currentPage = page;
        renderResults();

        elements.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // =====================================================================
    // Issue card rendering
    // =====================================================================

    function createIssueCard(issue) {
        const typeClass =
            issue.issueType === 'known'
                ? 'bg-amber-100 text-amber-800'
                : 'bg-emerald-100 text-emerald-800';
        const typeLabel = issue.issueType === 'known' ? 'Known Issue' : 'Addressed';

        const showVersion = !isHiddenVersion(issue.version);
        const productVersionText = showVersion
            ? `${issue.productName} ${issue.version}`
            : issue.productName;

        const fixReleases = getFixReleasesForIssue(issue);
        const hasFixAvailable = issue.issueType === 'known' && fixReleases.length > 0;

        const knownReleases = getKnownReleasesForIssue(issue);
        const hasOtherKnownReleases =
            issue.issueType === 'known' && knownReleases.length > 0;

        const showFixInfo = shouldShowFixInfo(issue.fix_info);

        // Header block: bug id + product/version caption
        const titleBlock = el('div', {
            children: [
                el('h3', {
                    className: 'text-lg font-semibold text-gray-900',
                    text: issue.bug_id,
                }),
                el('p', {
                    className: 'text-sm text-gray-500',
                    text: productVersionText,
                }),
            ],
        });

        // Badge row (affected components, fix info, fix-available button, type badge)
        const badges = el('div', { className: 'flex flex-wrap gap-2 items-center' });

        if (Array.isArray(issue.affected_components)) {
            for (const comp of issue.affected_components) {
                badges.appendChild(
                    el('span', {
                        className:
                            'px-3 py-1 rounded-full text-xs font-medium bg-violet-100 text-violet-800',
                        text: comp,
                    })
                );
            }
        }

        if (showFixInfo) {
            badges.appendChild(
                el('span', {
                    className:
                        'px-3 py-1 rounded-full text-xs font-medium bg-sky-100 text-sky-800',
                    text: issue.fix_info,
                })
            );
        }

        if (hasFixAvailable) {
            badges.appendChild(
                el('button', {
                    className:
                        'px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800 hover:bg-green-200 cursor-pointer transition-colors',
                    text: 'Fix Available',
                    attrs: {
                        type: 'button',
                        'aria-label': `View fix releases for ${escapeHtml(issue.bug_id)}`,
                    },
                    onClick: () => showFixModal(issue.bug_id, issue.productId),
                })
            );
        }

        if (issue.issueType === 'known' && hasOtherKnownReleases) {
            badges.appendChild(
                el('button', {
                    className: `px-3 py-1 rounded-full text-xs font-medium ${typeClass} hover:bg-amber-200 cursor-pointer transition-colors`,
                    text: typeLabel,
                    attrs: {
                        type: 'button',
                        'aria-label': `View other releases affected by ${escapeHtml(issue.bug_id)}`,
                    },
                    onClick: () =>
                        showKnownIssueModal(issue.bug_id, issue.productId, issue.version),
                })
            );
        } else {
            badges.appendChild(
                el('span', {
                    className: `px-3 py-1 rounded-full text-xs font-medium ${typeClass}`,
                    text: typeLabel,
                })
            );
        }

        const header = el('div', {
            className: 'flex flex-wrap items-start justify-between gap-4 mb-4',
            children: [titleBlock, badges],
        });

        const description = el('p', {
            className: 'text-gray-700 mb-4',
            text: issue.description,
        });

        const card = el('div', {
            className:
                'bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow',
            children: [header, description],
        });

        if (issue.symptoms) {
            card.appendChild(
                el('div', {
                    className: 'mb-3',
                    children: [
                        el('h4', {
                            className: 'text-sm font-semibold text-gray-600 mb-1',
                            text: 'Symptoms',
                        }),
                        el('p', {
                            className: 'text-sm text-gray-600',
                            text: issue.symptoms,
                        }),
                    ],
                })
            );
        }

        if (issue.workaround) {
            const iconContainer = el('span', {
                className:
                    'flex items-center justify-center w-6 h-6 bg-emerald-500 rounded-full',
            });
            iconContainer.appendChild(
                createSvgIcon(
                    'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z',
                    'w-4 h-4 text-white'
                )
            );

            const heading = el('div', {
                className: 'flex items-center gap-2 mb-2',
                children: [
                    iconContainer,
                    el('h4', {
                        className: 'text-sm font-semibold text-emerald-800',
                        text: 'Workaround',
                    }),
                ],
            });

            card.appendChild(
                el('div', {
                    className:
                        'mb-3 p-4 bg-gradient-to-r from-emerald-50 to-teal-50 border border-emerald-200 rounded-lg shadow-sm',
                    children: [
                        heading,
                        el('p', {
                            className: 'text-sm text-emerald-900 leading-relaxed',
                            text: issue.workaround,
                        }),
                    ],
                })
            );
        }

        return card;
    }

    // =====================================================================
    // Fix/Known-issue modal (shared renderer)
    // =====================================================================

    function renderReleaseListModal({ title, bugId, description, items, iconVariant }) {
        const modal = document.getElementById('fix-modal');
        const modalTitle = document.getElementById('modal-title');
        const modalBugId = document.getElementById('modal-bug-id');
        const modalDescription = document.getElementById('modal-description');
        const modalReleaseList = document.getElementById('modal-release-list');

        modalTitle.textContent = title;
        modalBugId.textContent = bugId;
        modalDescription.textContent = description;
        clearChildren(modalReleaseList);

        const iconBg = iconVariant === 'fix' ? 'bg-emerald-100' : 'bg-amber-100';
        const iconColor = iconVariant === 'fix' ? 'text-emerald-600' : 'text-amber-600';
        const iconPath =
            iconVariant === 'fix'
                ? 'M5 13l4 4L19 7'
                : 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z';

        for (const item of items) {
            const showVersion = !isHiddenVersion(item.version);
            const label = showVersion
                ? `${item.productName} ${item.version}`
                : item.productName;

            const iconSpan = el('span', {
                className: `flex items-center justify-center w-8 h-8 ${iconBg} rounded-full`,
            });
            iconSpan.appendChild(createSvgIcon(iconPath, `w-4 h-4 ${iconColor}`));

            modalReleaseList.appendChild(
                el('li', {
                    className:
                        'flex items-center py-3 px-4 hover:bg-gray-50 rounded-lg',
                    children: [
                        el('div', {
                            className: 'flex items-center gap-3',
                            children: [
                                iconSpan,
                                el('div', {
                                    className: 'font-medium text-gray-900',
                                    text: label,
                                }),
                            ],
                        }),
                    ],
                })
            );
        }

        modal.classList.remove('hidden');
        document.body.classList.add('modal-open');
    }

    function showFixModal(bugId, productId) {
        const fixes = (fixReleasesMap[bugId] || []).filter(
            (fix) => fix.productId === productId
        );
        if (fixes.length === 0) return;
        renderReleaseListModal({
            title: 'Fix Available',
            bugId,
            description: 'This issue has been fixed in the following releases:',
            items: fixes,
            iconVariant: 'fix',
        });
    }

    function showKnownIssueModal(bugId, productId, currentVersion) {
        const knownReleases = (knownIssuesMap[bugId] || []).filter(
            (rel) => rel.productId === productId && rel.version !== currentVersion
        );
        if (knownReleases.length === 0) return;
        renderReleaseListModal({
            title: 'Also Affected',
            bugId,
            description: 'This issue also affects the following releases:',
            items: knownReleases,
            iconVariant: 'known',
        });
    }

    function closeFixModal() {
        const modal = document.getElementById('fix-modal');
        modal.classList.add('hidden');
        document.body.classList.remove('modal-open');
    }

    function setupModalEventListeners() {
        const backdrop = document.getElementById('modal-backdrop');
        const closeBtn = document.getElementById('modal-close-btn');
        const closeFooterBtn = document.getElementById('modal-close-footer-btn');

        backdrop.addEventListener('click', closeFixModal);
        closeBtn.addEventListener('click', closeFixModal);
        closeFooterBtn.addEventListener('click', closeFixModal);
    }

    // =====================================================================
    // Release notes modal
    // =====================================================================

    async function loadReleaseNotes() {
        try {
            const response = await fetch('assets/release-notes.json');
            if (!response.ok) return null;
            return await response.json();
        } catch (error) {
            console.warn('Release notes unavailable:', error);
            return null;
        }
    }

    function getChangeTypeStyles(type) {
        switch (type) {
            case 'feature':
                return 'bg-emerald-100 text-emerald-800';
            case 'improvement':
                return 'bg-blue-100 text-blue-800';
            case 'fix':
                return 'bg-amber-100 text-amber-800';
            case 'breaking':
                return 'bg-red-100 text-red-800';
            default:
                return 'bg-gray-100 text-gray-800';
        }
    }

    // Maps a change type to one or more hardcoded SVG path-d strings.
    // Returns a fresh DOM node; never user-controlled input.
    const CHANGE_TYPE_ICONS = {
        feature: 'M12 6v6m0 0v6m0-6h6m-6 0H6',
        improvement: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6',
        fix: [
            'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z',
            'M15 12a3 3 0 11-6 0 3 3 0 016 0z',
        ],
        breaking:
            'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z',
    };
    function getChangeTypeIcon(type) {
        const paths = CHANGE_TYPE_ICONS[type];
        if (!paths) return null;
        return createSvgIcon(paths);
    }

    function getChangeTypeLabel(type) {
        switch (type) {
            case 'feature':
                return 'Feature';
            case 'improvement':
                return 'Improvement';
            case 'fix':
                return 'Fix';
            case 'breaking':
                return 'Breaking';
            default:
                return String(type || '');
        }
    }

    function showReleaseNotesModal() {
        if (
            !releaseNotesData ||
            !Array.isArray(releaseNotesData.releases) ||
            releaseNotesData.releases.length === 0
        ) {
            return;
        }

        const modal = document.getElementById('release-notes-modal');
        const modalBody = document.getElementById('release-notes-modal-body');
        clearChildren(modalBody);

        for (const release of releaseNotesData.releases) {
            const headingChildren = [
                el('h3', {
                    className: 'text-xl font-bold text-gray-900',
                    text: `v${release.version}`,
                }),
            ];
            if (release.title) {
                headingChildren.push(
                    el('span', { className: 'text-gray-500', text: '-' }),
                    el('span', { className: 'text-gray-600', text: release.title })
                );
            }

            const changeList = el('ul', { className: 'space-y-3' });
            if (Array.isArray(release.changes)) {
                for (const change of release.changes) {
                    const badge = el('span', {
                        className: `flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${getChangeTypeStyles(change.type)} shrink-0`,
                    });
                    const icon = getChangeTypeIcon(change.type);
                    if (icon) badge.appendChild(icon);
                    badge.appendChild(
                        document.createTextNode(getChangeTypeLabel(change.type))
                    );

                    changeList.appendChild(
                        el('li', {
                            className: 'flex items-start gap-3',
                            children: [
                                badge,
                                el('span', {
                                    className: 'text-gray-700',
                                    text: change.description,
                                }),
                            ],
                        })
                    );
                }
            }

            modalBody.appendChild(
                el('div', {
                    className: 'mb-8 last:mb-0',
                    children: [
                        el('div', {
                            className: 'flex items-center gap-3 mb-4',
                            children: headingChildren,
                        }),
                        el('p', {
                            className: 'text-sm text-gray-500 mb-4',
                            text: release.date,
                        }),
                        changeList,
                    ],
                })
            );
        }

        modal.classList.remove('hidden');
        document.body.classList.add('modal-open');
    }

    function closeReleaseNotesModal() {
        const modal = document.getElementById('release-notes-modal');
        modal.classList.add('hidden');
        document.body.classList.remove('modal-open');
    }

    function setupReleaseNotesModalEventListeners() {
        const backdrop = document.getElementById('release-notes-modal-backdrop');
        const closeBtn = document.getElementById('release-notes-modal-close-btn');
        const closeFooterBtn = document.getElementById(
            'release-notes-modal-close-footer-btn'
        );

        backdrop.addEventListener('click', closeReleaseNotesModal);
        closeBtn.addEventListener('click', closeReleaseNotesModal);
        closeFooterBtn.addEventListener('click', closeReleaseNotesModal);

        const releaseNotesLink = document.getElementById('release-notes-link');
        if (releaseNotesLink) {
            releaseNotesLink.addEventListener('click', (event) => {
                event.preventDefault();
                showReleaseNotesModal();
            });
        }
    }

    // Single document-level Escape handler shared by both modals.
    function setupGlobalKeydownHandler() {
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape') return;
            const fixModal = document.getElementById('fix-modal');
            const releaseNotesModal = document.getElementById('release-notes-modal');
            if (fixModal && !fixModal.classList.contains('hidden')) {
                closeFixModal();
            } else if (
                releaseNotesModal &&
                !releaseNotesModal.classList.contains('hidden')
            ) {
                closeReleaseNotesModal();
            }
        });
    }

    // =====================================================================
    // Autocomplete / filter wiring
    // =====================================================================

    function renderAutocompleteDropdown(
        dropdown,
        options,
        filterText,
        selectedValue,
        onSelect,
        highlightedIndex
    ) {
        clearChildren(dropdown);

        const filtered = options.filter((opt) => {
            const label = typeof opt === 'string' ? opt : opt.name;
            return label.toLowerCase().includes(filterText.toLowerCase());
        });

        if (filtered.length === 0) {
            dropdown.appendChild(
                el('div', {
                    className: 'autocomplete-no-results',
                    text: 'No matches found',
                })
            );
            return filtered;
        }

        filtered.forEach((opt, index) => {
            const value = typeof opt === 'string' ? opt : opt.id;
            const label = typeof opt === 'string' ? opt : opt.name;

            let className = 'autocomplete-option';
            if (value === selectedValue) className += ' selected';
            if (index === highlightedIndex) className += ' highlighted';

            const div = el('div', { className, text: label });
            div.dataset.value = value;
            div.addEventListener('mousedown', (e) => {
                e.preventDefault();
                onSelect(value, label);
            });
            dropdown.appendChild(div);
        });

        return filtered;
    }

    function showDropdown(dropdown) {
        dropdown.classList.remove('hidden');
    }

    function hideDropdown(dropdown) {
        dropdown.classList.add('hidden');
    }

    function clearFilters(data) {
        currentFilters = { search: '', product: '', version: '', type: '' };

        elements.search.value = '';
        elements.productFilter.value = '';
        elements.versionFilter.value = '';
        elements.typeFilter.value = '';

        currentPage = 1;
        pageSize = 50;
        elements.pageSize.value = '50';

        updateVersionFilter(data);

        hideDropdown(elements.productDropdown);
        hideDropdown(elements.versionDropdown);
        hideDropdown(elements.typeDropdown);

        applyFilters();
    }

    function setupEventListeners(data) {
        elements.search.addEventListener(
            'input',
            debounce((e) => {
                currentFilters.search = e.target.value;
                currentPage = 1;
                applyFilters();
            }, 300)
        );

        setupAutocomplete(
            elements.productFilter,
            elements.productDropdown,
            () => productOptions,
            () => currentFilters.product,
            (value, label) => {
                currentFilters.product = value;
                elements.productFilter.value = label;
                currentFilters.version = '';
                elements.versionFilter.value = '';
                updateVersionFilter(data);
                hideDropdown(elements.productDropdown);
                currentPage = 1;
                applyFilters();
            },
            () => highlightedProductIndex,
            (idx) => {
                highlightedProductIndex = idx;
            },
            () => {
                currentFilters.product = '';
                currentFilters.version = '';
                elements.versionFilter.value = '';
                updateVersionFilter(data);
                currentPage = 1;
                applyFilters();
            }
        );

        setupAutocomplete(
            elements.versionFilter,
            elements.versionDropdown,
            () => versionOptions,
            () => currentFilters.version,
            (value, label) => {
                currentFilters.version = value;
                elements.versionFilter.value = label;
                hideDropdown(elements.versionDropdown);
                currentPage = 1;
                applyFilters();
            },
            () => highlightedVersionIndex,
            (idx) => {
                highlightedVersionIndex = idx;
            },
            () => {
                currentFilters.version = '';
                currentPage = 1;
                applyFilters();
            }
        );

        setupAutocomplete(
            elements.typeFilter,
            elements.typeDropdown,
            () => typeOptions,
            () => currentFilters.type,
            (value, label) => {
                currentFilters.type = value;
                elements.typeFilter.value = label;
                hideDropdown(elements.typeDropdown);
                currentPage = 1;
                applyFilters();
            },
            () => highlightedTypeIndex,
            (idx) => {
                highlightedTypeIndex = idx;
            },
            () => {
                currentFilters.type = '';
                currentPage = 1;
                applyFilters();
            }
        );

        elements.pageSize.addEventListener('change', (e) => {
            const value = e.target.value;
            pageSize = value === 'all' ? 'all' : parseInt(value, 10);
            currentPage = 1;
            renderResults();
        });

        elements.clearFilters.addEventListener('click', () => clearFilters(data));

        document.addEventListener('click', (e) => {
            if (
                !elements.productFilter.contains(e.target) &&
                !elements.productDropdown.contains(e.target)
            ) {
                hideDropdown(elements.productDropdown);
            }
            if (
                !elements.versionFilter.contains(e.target) &&
                !elements.versionDropdown.contains(e.target)
            ) {
                hideDropdown(elements.versionDropdown);
            }
            if (
                !elements.typeFilter.contains(e.target) &&
                !elements.typeDropdown.contains(e.target)
            ) {
                hideDropdown(elements.typeDropdown);
            }
        });
    }

    function setupAutocomplete(
        input,
        dropdown,
        getOptions,
        getSelectedValue,
        onSelect,
        getHighlightedIndex,
        setHighlightedIndex,
        onClear
    ) {
        let lastFilteredOptions = [];

        const updateDropdown = () => {
            const options = getOptions();
            const filterText = input.value;
            lastFilteredOptions = renderAutocompleteDropdown(
                dropdown,
                options,
                filterText,
                getSelectedValue(),
                onSelect,
                getHighlightedIndex()
            );
        };

        input.addEventListener('focus', () => {
            if (input.disabled) return;
            setHighlightedIndex(-1);
            updateDropdown();
            showDropdown(dropdown);
        });

        input.addEventListener('blur', () => {
            setTimeout(() => {
                hideDropdown(dropdown);
                const options = getOptions();
                const inputValue = input.value.toLowerCase();
                const match = options.find((opt) => {
                    const label = typeof opt === 'string' ? opt : opt.name;
                    return label.toLowerCase() === inputValue;
                });
                if (!match && input.value !== '') {
                    const selectedValue = getSelectedValue();
                    if (selectedValue) {
                        const selectedOpt = options.find((opt) => {
                            const value = typeof opt === 'string' ? opt : opt.id;
                            return value === selectedValue;
                        });
                        if (selectedOpt) {
                            const label =
                                typeof selectedOpt === 'string'
                                    ? selectedOpt
                                    : selectedOpt.name;
                            input.value = label;
                        } else {
                            input.value = '';
                            onClear();
                        }
                    } else {
                        input.value = '';
                    }
                } else if (!match && input.value === '' && getSelectedValue()) {
                    onClear();
                }
            }, 150);
        });

        input.addEventListener('input', () => {
            setHighlightedIndex(-1);
            updateDropdown();
            showDropdown(dropdown);
        });

        input.addEventListener('keydown', (e) => {
            if (input.disabled) return;

            const options = lastFilteredOptions;
            const currentIndex = getHighlightedIndex();

            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    if (dropdown.classList.contains('hidden')) {
                        showDropdown(dropdown);
                        updateDropdown();
                    } else {
                        const nextIndex =
                            currentIndex < options.length - 1 ? currentIndex + 1 : 0;
                        setHighlightedIndex(nextIndex);
                        updateDropdown();
                        scrollToHighlighted(dropdown, nextIndex);
                    }
                    break;

                case 'ArrowUp':
                    e.preventDefault();
                    if (!dropdown.classList.contains('hidden')) {
                        const prevIndex =
                            currentIndex > 0 ? currentIndex - 1 : options.length - 1;
                        setHighlightedIndex(prevIndex);
                        updateDropdown();
                        scrollToHighlighted(dropdown, prevIndex);
                    }
                    break;

                case 'Enter':
                    e.preventDefault();
                    if (currentIndex >= 0 && currentIndex < options.length) {
                        const opt = options[currentIndex];
                        const value = typeof opt === 'string' ? opt : opt.id;
                        const label = typeof opt === 'string' ? opt : opt.name;
                        onSelect(value, label);
                    }
                    break;

                case 'Escape':
                    hideDropdown(dropdown);
                    input.blur();
                    break;

                case 'Tab':
                    hideDropdown(dropdown);
                    break;
            }
        });
    }

    function scrollToHighlighted(dropdown, index) {
        const items = dropdown.querySelectorAll('.autocomplete-option');
        if (items[index]) {
            items[index].scrollIntoView({ block: 'nearest' });
        }
    }

    // =====================================================================
    // Init
    // =====================================================================

    function renderFatalError(message) {
        clearChildren(elements.loading);
        const container = el('div', {
            className: 'text-red-600',
            children: [
                el('p', {
                    className: 'font-semibold',
                    text: 'Error loading bug database',
                }),
                el('p', {
                    className: 'text-sm mt-2',
                    text: message,
                }),
            ],
        });
        elements.loading.appendChild(container);
    }

    async function init() {
        try {
            const response = await fetch('assets/data.json');
            if (!response.ok) {
                throw new Error(`Failed to load bug database (HTTP ${response.status})`);
            }
            const contentType = response.headers.get('content-type') || '';
            if (!contentType.toLowerCase().includes('application/json')) {
                // Not fatal — some CDNs serve JSON as application/octet-stream.
                // Just warn so we notice in the console.
                console.warn(
                    `Unexpected content-type for data.json: ${contentType}`
                );
            }

            const rawData = await response.json();
            const data = validateBugDatabase(rawData);

            if (data.metadata && data.metadata.generated_at) {
                const date = new Date(data.metadata.generated_at);
                elements.generatedDate.textContent = Number.isNaN(date.getTime())
                    ? '-'
                    : date.toLocaleDateString();
            }

            fixReleasesMap = buildFixReleasesMap(data);
            knownIssuesMap = buildKnownIssuesMap(data);
            allIssues = flattenIssues(data);
            filteredIssues = [...allIssues];

            populateFilters(data);
            setupEventListeners(data);
            setupModalEventListeners();
            setupGlobalKeydownHandler();

            releaseNotesData = await loadReleaseNotes();
            if (
                releaseNotesData &&
                Array.isArray(releaseNotesData.releases) &&
                releaseNotesData.releases.length > 0
            ) {
                const releaseNotesLink = document.getElementById('release-notes-link');
                if (releaseNotesLink) {
                    releaseNotesLink.classList.remove('hidden');
                }
                setupReleaseNotesModalEventListeners();
            }

            elements.loading.classList.add('hidden');

            renderResults();
        } catch (error) {
            console.error('Error initializing BugDB:', error);
            renderFatalError(error && error.message ? error.message : String(error));
        }
    }

    document.addEventListener('DOMContentLoaded', init);
})();
