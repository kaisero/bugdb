/**
 * BugDB - Client-side search and filter functionality
 */

// State
let allIssues = [];
let filteredIssues = [];
let currentFilters = {
    search: '',
    product: '',
    version: '',
    type: ''
};
let fixReleasesMap = {}; // Map of bug_id -> array of fix releases
let knownIssuesMap = {}; // Map of bug_id -> array of releases where issue is known

// Pagination state
const PAGE_SIZE_OPTIONS = [50, 100, 250, 'All'];
let currentPage = 1;
let pageSize = 50; // Default page size

// Versions that should not be displayed in issue cards (e.g., SaaS products)
const HIDDEN_VERSIONS = ['SaaS', 'Unknown'];

// DOM Elements
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
    schemaVersion: document.getElementById('schema-version')
};

// Autocomplete state
let productOptions = [];
let versionOptions = [];
const typeOptions = [
    { value: 'known', label: 'Known Issues' },
    { value: 'addressed', label: 'Addressed Issues' }
];
let highlightedProductIndex = -1;
let highlightedVersionIndex = -1;
let highlightedTypeIndex = -1;

// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Flatten issues from nested structure for easier searching
function flattenIssues(data) {
    const issues = [];

    for (const product of data.products) {
        for (const version of product.versions) {
            // Add known issues
            for (const issue of version.known_issues) {
                issues.push({
                    ...issue,
                    productId: product.id,
                    productName: product.name,
                    version: version.version,
                    releaseDate: version.release_date,
                    issueType: 'known'
                });
            }

            // Add addressed issues
            for (const issue of version.addressed_issues) {
                issues.push({
                    ...issue,
                    productId: product.id,
                    productName: product.name,
                    version: version.version,
                    releaseDate: version.release_date,
                    issueType: 'addressed'
                });
            }
        }
    }

    return issues;
}

// Build a map of bug_id -> releases where the bug is fixed
function buildFixReleasesMap(data) {
    const map = {};

    for (const product of data.products) {
        for (const version of product.versions) {
            // Each addressed issue represents a fix in this version
            for (const issue of version.addressed_issues) {
                if (!map[issue.bug_id]) {
                    map[issue.bug_id] = [];
                }
                map[issue.bug_id].push({
                    productId: product.id,
                    productName: product.name,
                    version: version.version,
                    releaseDate: version.release_date
                });
            }
        }
    }

    // Sort each bug's fix releases by version (latest first)
    for (const bugId in map) {
        map[bugId].sort((a, b) => compareVersions(b.version, a.version));
    }

    return map;
}

// Build a map of bug_id -> releases where the bug is a known issue
function buildKnownIssuesMap(data) {
    const map = {};

    for (const product of data.products) {
        for (const version of product.versions) {
            // Each known issue represents a release where the bug exists
            for (const issue of version.known_issues) {
                if (!map[issue.bug_id]) {
                    map[issue.bug_id] = [];
                }
                map[issue.bug_id].push({
                    productId: product.id,
                    productName: product.name,
                    version: version.version
                });
            }
        }
    }

    // Sort each bug's known releases by version (latest first)
    for (const bugId in map) {
        map[bugId].sort((a, b) => compareVersions(b.version, a.version));
    }

    return map;
}

// Check if fix_info should be displayed (hide if it contains certain phrases)
function shouldShowFixInfo(fixInfo) {
    if (!fixInfo) return false;
    const lowerFixInfo = fixInfo.toLowerCase();
    return !lowerFixInfo.includes('this issue is') &&
           !lowerFixInfo.includes('resolved in') &&
           !lowerFixInfo.includes('addressed in');
}

// Compare versions for sorting (handles 11.2.5, 2025.r5.0, SaaS, -h9 suffixes)
function compareVersions(a, b) {
    // Handle special cases
    if (a === 'SaaS') return 1;
    if (b === 'SaaS') return -1;
    if (a === 'Unknown') return -1;
    if (b === 'Unknown') return 1;

    // Extract base version and hotfix suffix
    const parseVersion = (v) => {
        const hotfixMatch = v.match(/^(.+?)-h(\d+)$/i);
        if (hotfixMatch) {
            return { base: hotfixMatch[1], hotfix: parseInt(hotfixMatch[2], 10) };
        }
        return { base: v, hotfix: 0 };
    };

    const parsedA = parseVersion(a);
    const parsedB = parseVersion(b);

    // Normalize version strings (handle 2025.r5.0 format)
    const normalizeBase = (base) => {
        return base.replace(/r/gi, '.').split('.').filter(p => p !== '');
    };

    const partsA = normalizeBase(parsedA.base);
    const partsB = normalizeBase(parsedB.base);

    // Compare each part numerically
    for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
        const numA = parseInt(partsA[i], 10) || 0;
        const numB = parseInt(partsB[i], 10) || 0;
        if (numA !== numB) return numA - numB;
    }

    // If base versions are equal, compare hotfix numbers
    return parsedA.hotfix - parsedB.hotfix;
}

// Get fix releases for an issue (filtered to same product)
function getFixReleasesForIssue(issue) {
    const fixes = fixReleasesMap[issue.bug_id] || [];
    // Filter to same product
    return fixes.filter(fix => fix.productId === issue.productId);
}

// Get known issue releases for an issue (filtered to same product, excluding current version)
function getKnownReleasesForIssue(issue) {
    const knownReleases = knownIssuesMap[issue.bug_id] || [];
    // Filter to same product and exclude the current version
    return knownReleases.filter(rel => rel.productId === issue.productId && rel.version !== issue.version);
}

// Populate filter dropdowns
function populateFilters(data) {
    // Store product options
    productOptions = data.products.map(p => ({ id: p.id, name: p.name }));

    // Initialize version filter as disabled
    updateVersionFilter(data);
}

// Render autocomplete dropdown
function renderAutocompleteDropdown(dropdown, options, filterText, selectedValue, onSelect, highlightedIndex) {
    dropdown.innerHTML = '';

    const filtered = options.filter(opt => {
        const label = typeof opt === 'string' ? opt : opt.name;
        return label.toLowerCase().includes(filterText.toLowerCase());
    });

    if (filtered.length === 0) {
        const noResults = document.createElement('div');
        noResults.className = 'autocomplete-no-results';
        noResults.textContent = 'No matches found';
        dropdown.appendChild(noResults);
        return filtered;
    }

    filtered.forEach((opt, index) => {
        const value = typeof opt === 'string' ? opt : opt.id;
        const label = typeof opt === 'string' ? opt : opt.name;

        const div = document.createElement('div');
        div.className = 'autocomplete-option';
        if (value === selectedValue) {
            div.className += ' selected';
        }
        if (index === highlightedIndex) {
            div.className += ' highlighted';
        }
        div.textContent = label;
        div.dataset.value = value;
        div.addEventListener('mousedown', (e) => {
            e.preventDefault();
            onSelect(value, label);
        });
        dropdown.appendChild(div);
    });

    return filtered;
}

// Show dropdown
function showDropdown(dropdown) {
    dropdown.classList.remove('hidden');
}

// Hide dropdown
function hideDropdown(dropdown) {
    dropdown.classList.add('hidden');
}

// Update version filter based on selected product
function updateVersionFilter(data) {
    const selectedProduct = currentFilters.product;

    // If no product is selected, disable version filter
    if (!selectedProduct) {
        elements.versionFilter.placeholder = 'Select a product first';
        elements.versionFilter.disabled = true;
        elements.versionFilter.value = '';
        versionOptions = [];
        return;
    }

    // Enable version filter and populate with product-specific versions
    elements.versionFilter.disabled = false;
    elements.versionFilter.placeholder = 'All Versions';

    const versions = new Set();

    for (const product of data.products) {
        if (product.id === selectedProduct) {
            for (const version of product.versions) {
                // Skip hidden versions (e.g., SaaS, Unknown)
                if (!HIDDEN_VERSIONS.includes(version.version)) {
                    versions.add(version.version);
                }
            }
        }
    }

    // Sort versions in descending order
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

// Apply filters to issues
function applyFilters() {
    filteredIssues = allIssues.filter(issue => {
        // Search filter
        if (currentFilters.search) {
            const searchLower = currentFilters.search.toLowerCase();
            const searchableText = [
                issue.bug_id,
                issue.description,
                issue.symptoms,
                issue.workaround,
                ...(issue.affected_components || [])
            ].filter(Boolean).join(' ').toLowerCase();

            if (!searchableText.includes(searchLower)) {
                return false;
            }
        }

        // Product filter
        if (currentFilters.product && issue.productId !== currentFilters.product) {
            return false;
        }

        // Version filter
        if (currentFilters.version && issue.version !== currentFilters.version) {
            return false;
        }

        // Type filter
        if (currentFilters.type && issue.issueType !== currentFilters.type) {
            return false;
        }

        return true;
    });

    renderResults();
}

// Calculate pagination values
function getPaginationInfo() {
    const totalIssues = filteredIssues.length;
    const effectivePageSize = pageSize === 'all' ? totalIssues : pageSize;
    const totalPages = effectivePageSize > 0 ? Math.ceil(totalIssues / effectivePageSize) : 1;
    const startIndex = (currentPage - 1) * effectivePageSize;
    const endIndex = Math.min(startIndex + effectivePageSize, totalIssues);

    return { totalIssues, effectivePageSize, totalPages, startIndex, endIndex };
}

// Render issue cards with pagination
function renderResults() {
    elements.results.innerHTML = '';
    elements.resultsCount.textContent = filteredIssues.length;

    if (filteredIssues.length === 0) {
        elements.noResults.classList.remove('hidden');
        elements.pagination.classList.add('hidden');
        elements.resultsRange.textContent = '0';
        return;
    }

    elements.noResults.classList.add('hidden');

    const { totalIssues, totalPages, startIndex, endIndex } = getPaginationInfo();

    // Ensure current page is valid
    if (currentPage > totalPages) {
        currentPage = totalPages;
    }

    // Update results range display
    if (pageSize === 'all') {
        elements.resultsRange.textContent = totalIssues;
    } else {
        elements.resultsRange.textContent = `${startIndex + 1}-${endIndex}`;
    }

    // Get issues for current page
    const pageIssues = filteredIssues.slice(startIndex, endIndex);

    // Render issue cards
    pageIssues.forEach(issue => {
        const card = createIssueCard(issue);
        elements.results.appendChild(card);
    });

    // Render pagination controls
    renderPagination(totalPages);
}

// Render pagination controls
function renderPagination(totalPages) {
    elements.pagination.innerHTML = '';

    // Hide pagination if only one page or showing all
    if (totalPages <= 1 || pageSize === 'all') {
        elements.pagination.classList.add('hidden');
        return;
    }

    elements.pagination.classList.remove('hidden');

    // Previous button
    const prevBtn = document.createElement('button');
    prevBtn.className = `px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
        currentPage === 1
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
            : 'bg-white text-gray-700 hover:bg-gray-100 border border-gray-300'
    }`;
    prevBtn.textContent = 'Previous';
    prevBtn.disabled = currentPage === 1;
    prevBtn.onclick = () => goToPage(currentPage - 1);
    elements.pagination.appendChild(prevBtn);

    // Page numbers
    const pageNumbers = getPageNumbers(currentPage, totalPages);
    pageNumbers.forEach(pageNum => {
        if (pageNum === '...') {
            const ellipsis = document.createElement('span');
            ellipsis.className = 'px-3 py-2 text-gray-500';
            ellipsis.textContent = '...';
            elements.pagination.appendChild(ellipsis);
        } else {
            const pageBtn = document.createElement('button');
            pageBtn.className = `px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                pageNum === currentPage
                    ? 'bg-pan-orange text-white'
                    : 'bg-white text-gray-700 hover:bg-gray-100 border border-gray-300'
            }`;
            pageBtn.textContent = pageNum;
            pageBtn.onclick = () => goToPage(pageNum);
            elements.pagination.appendChild(pageBtn);
        }
    });

    // Next button
    const nextBtn = document.createElement('button');
    nextBtn.className = `px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
        currentPage === totalPages
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
            : 'bg-white text-gray-700 hover:bg-gray-100 border border-gray-300'
    }`;
    nextBtn.textContent = 'Next';
    nextBtn.disabled = currentPage === totalPages;
    nextBtn.onclick = () => goToPage(currentPage + 1);
    elements.pagination.appendChild(nextBtn);
}

// Get page numbers to display (with ellipsis for many pages)
function getPageNumbers(current, total) {
    if (total <= 7) {
        return Array.from({ length: total }, (_, i) => i + 1);
    }

    const pages = [];

    // Always show first page
    pages.push(1);

    if (current > 3) {
        pages.push('...');
    }

    // Show pages around current
    const start = Math.max(2, current - 1);
    const end = Math.min(total - 1, current + 1);

    for (let i = start; i <= end; i++) {
        if (!pages.includes(i)) {
            pages.push(i);
        }
    }

    if (current < total - 2) {
        pages.push('...');
    }

    // Always show last page
    if (!pages.includes(total)) {
        pages.push(total);
    }

    return pages;
}

// Navigate to a specific page
function goToPage(page) {
    const { totalPages } = getPaginationInfo();
    if (page < 1 || page > totalPages) return;

    currentPage = page;
    renderResults();

    // Scroll to top of results
    elements.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Create issue card HTML
function createIssueCard(issue) {
    const card = document.createElement('div');
    card.className = 'bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow';

    const typeClass = issue.issueType === 'known'
        ? 'bg-amber-100 text-amber-800'
        : 'bg-emerald-100 text-emerald-800';
    const typeLabel = issue.issueType === 'known' ? 'Known Issue' : 'Addressed';

    // Only show version if it's not in the hidden versions list
    const showVersion = !HIDDEN_VERSIONS.includes(issue.version);
    const productVersionText = showVersion
        ? `${escapeHtml(issue.productName)} ${escapeHtml(issue.version)}`
        : escapeHtml(issue.productName);

    // Check if this known issue has available fixes
    const fixReleases = getFixReleasesForIssue(issue);
    const hasFixAvailable = issue.issueType === 'known' && fixReleases.length > 0;

    // Check if this known issue exists in other releases
    const knownReleases = getKnownReleasesForIssue(issue);
    const hasOtherKnownReleases = issue.issueType === 'known' && knownReleases.length > 0;

    // Determine if fix_info should be shown
    const showFixInfo = shouldShowFixInfo(issue.fix_info);

    // Build the type badge HTML
    let typeBadgeHtml;
    if (issue.issueType === 'known' && hasOtherKnownReleases) {
        typeBadgeHtml = `
            <button class="px-3 py-1 rounded-full text-xs font-medium ${typeClass} hover:bg-amber-200 cursor-pointer transition-colors"
                    onclick="showKnownIssueModal('${escapeHtml(issue.bug_id)}', '${escapeHtml(issue.productId)}', '${escapeHtml(issue.version)}')"
                    aria-label="View other releases affected by ${escapeHtml(issue.bug_id)}">
                ${typeLabel}
            </button>
        `;
    } else {
        typeBadgeHtml = `
            <span class="px-3 py-1 rounded-full text-xs font-medium ${typeClass}">
                ${typeLabel}
            </span>
        `;
    }

    card.innerHTML = `
        <div class="flex flex-wrap items-start justify-between gap-4 mb-4">
            <div>
                <h3 class="text-lg font-semibold text-gray-900">${escapeHtml(issue.bug_id)}</h3>
                <p class="text-sm text-gray-500">${productVersionText}</p>
            </div>
            <div class="flex flex-wrap gap-2 items-center">
                ${issue.affected_components && issue.affected_components.length > 0 ?
                    issue.affected_components.map(comp => `
                        <span class="px-3 py-1 rounded-full text-xs font-medium bg-violet-100 text-violet-800">
                            ${escapeHtml(comp)}
                        </span>
                    `).join('') : ''}
                ${showFixInfo ? `
                    <span class="px-3 py-1 rounded-full text-xs font-medium bg-sky-100 text-sky-800">
                        ${escapeHtml(issue.fix_info)}
                    </span>
                ` : ''}
                ${hasFixAvailable ? `
                    <button class="px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800 hover:bg-green-200 cursor-pointer transition-colors"
                            onclick="showFixModal('${escapeHtml(issue.bug_id)}', '${escapeHtml(issue.productId)}')"
                            aria-label="View fix releases for ${escapeHtml(issue.bug_id)}">
                        Fix Available
                    </button>
                ` : ''}
                ${typeBadgeHtml}
            </div>
        </div>

        <p class="text-gray-700 mb-4">${escapeHtml(issue.description)}</p>

        ${issue.symptoms ? `
            <div class="mb-3">
                <h4 class="text-sm font-semibold text-gray-600 mb-1">Symptoms</h4>
                <p class="text-sm text-gray-600">${escapeHtml(issue.symptoms)}</p>
            </div>
        ` : ''}

        ${issue.workaround ? `
            <div class="mb-3 p-4 bg-gradient-to-r from-emerald-50 to-teal-50 border border-emerald-200 rounded-lg shadow-sm">
                <div class="flex items-center gap-2 mb-2">
                    <span class="flex items-center justify-center w-6 h-6 bg-emerald-500 rounded-full">
                        <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                        </svg>
                    </span>
                    <h4 class="text-sm font-semibold text-emerald-800">Workaround</h4>
                </div>
                <p class="text-sm text-emerald-900 leading-relaxed">${escapeHtml(issue.workaround)}</p>
            </div>
        ` : ''}

    `;

    return card;
}

// Helper functions
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Modal functions
function showFixModal(bugId, productId) {
    const fixes = (fixReleasesMap[bugId] || []).filter(fix => fix.productId === productId);
    if (fixes.length === 0) return;

    const modal = document.getElementById('fix-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBugId = document.getElementById('modal-bug-id');
    const modalDescription = document.getElementById('modal-description');
    const modalReleaseList = document.getElementById('modal-release-list');

    modalTitle.textContent = 'Fix Available';
    modalBugId.textContent = bugId;
    modalDescription.textContent = 'This issue has been fixed in the following releases:';
    modalReleaseList.innerHTML = '';

    fixes.forEach(fix => {
        const li = document.createElement('li');
        li.className = 'flex items-center py-3 px-4 hover:bg-gray-50 rounded-lg';

        const showVersion = !HIDDEN_VERSIONS.includes(fix.version);
        const versionText = showVersion ? fix.version : '';

        li.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="flex items-center justify-center w-8 h-8 bg-emerald-100 rounded-full">
                    <svg class="w-4 h-4 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                    </svg>
                </span>
                <div class="font-medium text-gray-900">${escapeHtml(fix.productName)}${versionText ? ' ' + escapeHtml(versionText) : ''}</div>
            </div>
        `;
        modalReleaseList.appendChild(li);
    });

    modal.classList.remove('hidden');
    document.body.classList.add('modal-open');
}

function showKnownIssueModal(bugId, productId, currentVersion) {
    const knownReleases = (knownIssuesMap[bugId] || []).filter(rel => rel.productId === productId && rel.version !== currentVersion);
    if (knownReleases.length === 0) return;

    const modal = document.getElementById('fix-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBugId = document.getElementById('modal-bug-id');
    const modalDescription = document.getElementById('modal-description');
    const modalReleaseList = document.getElementById('modal-release-list');

    modalTitle.textContent = 'Also Affected';
    modalBugId.textContent = bugId;
    modalDescription.textContent = 'This issue also affects the following releases:';
    modalReleaseList.innerHTML = '';

    knownReleases.forEach(rel => {
        const li = document.createElement('li');
        li.className = 'flex items-center py-3 px-4 hover:bg-gray-50 rounded-lg';

        const showVersion = !HIDDEN_VERSIONS.includes(rel.version);
        const versionText = showVersion ? rel.version : '';

        li.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="flex items-center justify-center w-8 h-8 bg-amber-100 rounded-full">
                    <svg class="w-4 h-4 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                    </svg>
                </span>
                <div class="font-medium text-gray-900">${escapeHtml(rel.productName)}${versionText ? ' ' + escapeHtml(versionText) : ''}</div>
            </div>
        `;
        modalReleaseList.appendChild(li);
    });

    modal.classList.remove('hidden');
    document.body.classList.add('modal-open');
}

function closeFixModal() {
    const modal = document.getElementById('fix-modal');
    modal.classList.add('hidden');
    document.body.classList.remove('modal-open');
}

function setupModalEventListeners() {
    const modal = document.getElementById('fix-modal');
    const backdrop = document.getElementById('modal-backdrop');
    const closeBtn = document.getElementById('modal-close-btn');
    const closeFooterBtn = document.getElementById('modal-close-footer-btn');

    // Close on backdrop click
    backdrop.addEventListener('click', closeFixModal);

    // Close on X button click
    closeBtn.addEventListener('click', closeFixModal);

    // Close on footer Close button click
    closeFooterBtn.addEventListener('click', closeFixModal);

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            closeFixModal();
        }
    });
}

// Clear all filters
function clearFilters(data) {
    currentFilters = {
        search: '',
        product: '',
        version: '',
        type: ''
    };

    elements.search.value = '';
    elements.productFilter.value = '';
    elements.versionFilter.value = '';
    elements.typeFilter.value = '';

    // Reset pagination
    currentPage = 1;
    pageSize = 50;
    elements.pageSize.value = '50';

    // Reset version filter to disabled state
    updateVersionFilter(data);

    // Hide dropdowns
    hideDropdown(elements.productDropdown);
    hideDropdown(elements.versionDropdown);
    hideDropdown(elements.typeDropdown);

    applyFilters();
}

// Event listeners
function setupEventListeners(data) {
    // Search input with debouncing
    elements.search.addEventListener('input', debounce((e) => {
        currentFilters.search = e.target.value;
        currentPage = 1; // Reset to first page when search changes
        applyFilters();
    }, 300));

    // Product filter autocomplete
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
            currentPage = 1; // Reset to first page when filter changes
            applyFilters();
        },
        () => highlightedProductIndex,
        (idx) => { highlightedProductIndex = idx; },
        // Clear callback
        () => {
            currentFilters.product = '';
            currentFilters.version = '';
            elements.versionFilter.value = '';
            updateVersionFilter(data);
            currentPage = 1; // Reset to first page when filter changes
            applyFilters();
        }
    );

    // Version filter autocomplete
    setupAutocomplete(
        elements.versionFilter,
        elements.versionDropdown,
        () => versionOptions,
        () => currentFilters.version,
        (value, label) => {
            currentFilters.version = value;
            elements.versionFilter.value = label;
            hideDropdown(elements.versionDropdown);
            currentPage = 1; // Reset to first page when filter changes
            applyFilters();
        },
        () => highlightedVersionIndex,
        (idx) => { highlightedVersionIndex = idx; },
        // Clear callback
        () => {
            currentFilters.version = '';
            currentPage = 1; // Reset to first page when filter changes
            applyFilters();
        }
    );

    // Type filter autocomplete
    setupAutocomplete(
        elements.typeFilter,
        elements.typeDropdown,
        () => typeOptions,
        () => currentFilters.type,
        (value, label) => {
            currentFilters.type = value;
            elements.typeFilter.value = label;
            hideDropdown(elements.typeDropdown);
            currentPage = 1; // Reset to first page when filter changes
            applyFilters();
        },
        () => highlightedTypeIndex,
        (idx) => { highlightedTypeIndex = idx; },
        // Clear callback
        () => {
            currentFilters.type = '';
            currentPage = 1; // Reset to first page when filter changes
            applyFilters();
        }
    );

    // Page size selector
    elements.pageSize.addEventListener('change', (e) => {
        const value = e.target.value;
        pageSize = value === 'all' ? 'all' : parseInt(value, 10);
        currentPage = 1; // Reset to first page when page size changes
        renderResults();
    });

    // Clear filters button
    elements.clearFilters.addEventListener('click', () => clearFilters(data));

    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!elements.productFilter.contains(e.target) && !elements.productDropdown.contains(e.target)) {
            hideDropdown(elements.productDropdown);
        }
        if (!elements.versionFilter.contains(e.target) && !elements.versionDropdown.contains(e.target)) {
            hideDropdown(elements.versionDropdown);
        }
        if (!elements.typeFilter.contains(e.target) && !elements.typeDropdown.contains(e.target)) {
            hideDropdown(elements.typeDropdown);
        }
    });
}

// Setup autocomplete for an input element
function setupAutocomplete(input, dropdown, getOptions, getSelectedValue, onSelect, getHighlightedIndex, setHighlightedIndex, onClear) {
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

    // Focus: show dropdown
    input.addEventListener('focus', () => {
        if (input.disabled) return;
        setHighlightedIndex(-1);
        updateDropdown();
        showDropdown(dropdown);
    });

    // Blur: hide dropdown (with small delay for click handling)
    input.addEventListener('blur', () => {
        setTimeout(() => {
            hideDropdown(dropdown);
            // If no valid selection, clear the input
            const options = getOptions();
            const inputValue = input.value.toLowerCase();
            const match = options.find(opt => {
                const label = typeof opt === 'string' ? opt : opt.name;
                return label.toLowerCase() === inputValue;
            });
            if (!match && input.value !== '') {
                // Check if we had a prior selection that's still valid
                const selectedValue = getSelectedValue();
                if (selectedValue) {
                    const selectedOpt = options.find(opt => {
                        const value = typeof opt === 'string' ? opt : opt.id;
                        return value === selectedValue;
                    });
                    if (selectedOpt) {
                        const label = typeof selectedOpt === 'string' ? selectedOpt : selectedOpt.name;
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

    // Input: filter dropdown
    input.addEventListener('input', () => {
        setHighlightedIndex(-1);
        updateDropdown();
        showDropdown(dropdown);
    });

    // Keyboard navigation
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
                    const nextIndex = currentIndex < options.length - 1 ? currentIndex + 1 : 0;
                    setHighlightedIndex(nextIndex);
                    updateDropdown();
                    scrollToHighlighted(dropdown, nextIndex);
                }
                break;

            case 'ArrowUp':
                e.preventDefault();
                if (!dropdown.classList.contains('hidden')) {
                    const prevIndex = currentIndex > 0 ? currentIndex - 1 : options.length - 1;
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

// Scroll dropdown to keep highlighted item visible
function scrollToHighlighted(dropdown, index) {
    const items = dropdown.querySelectorAll('.autocomplete-option');
    if (items[index]) {
        items[index].scrollIntoView({ block: 'nearest' });
    }
}

// Initialize the application
async function init() {
    try {
        const response = await fetch('assets/data.json');
        if (!response.ok) {
            throw new Error('Failed to load bug database');
        }

        const data = await response.json();

        // Update metadata display
        if (data.metadata) {
            const date = new Date(data.metadata.generated_at);
            elements.generatedDate.textContent = date.toLocaleDateString();
            elements.schemaVersion.textContent = data.metadata.version;
        }

        // Build fix releases map (must be done before flattening issues)
        fixReleasesMap = buildFixReleasesMap(data);

        // Build known issues map
        knownIssuesMap = buildKnownIssuesMap(data);

        // Flatten issues for searching
        allIssues = flattenIssues(data);
        filteredIssues = [...allIssues];

        // Populate filters
        populateFilters(data);

        // Setup event listeners
        setupEventListeners(data);

        // Setup modal event listeners
        setupModalEventListeners();

        // Hide loading, show results
        elements.loading.classList.add('hidden');

        // Initial render
        renderResults();

    } catch (error) {
        console.error('Error initializing BugDB:', error);
        elements.loading.innerHTML = `
            <div class="text-red-600">
                <p class="font-semibold">Error loading bug database</p>
                <p class="text-sm mt-2">${escapeHtml(error.message)}</p>
            </div>
        `;
    }
}

// Start the application
document.addEventListener('DOMContentLoaded', init);
