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

// DOM Elements
const elements = {
    search: document.getElementById('search'),
    productFilter: document.getElementById('product-filter'),
    productDropdown: document.getElementById('product-dropdown'),
    versionFilter: document.getElementById('version-filter'),
    versionDropdown: document.getElementById('version-dropdown'),
    typeFilter: document.getElementById('type-filter'),
    results: document.getElementById('results'),
    resultsCount: document.getElementById('results-count'),
    noResults: document.getElementById('no-results'),
    loading: document.getElementById('loading'),
    clearFilters: document.getElementById('clear-filters'),
    generatedDate: document.getElementById('generated-date'),
    schemaVersion: document.getElementById('schema-version')
};

// Autocomplete state
let productOptions = [];
let versionOptions = [];
let highlightedProductIndex = -1;
let highlightedVersionIndex = -1;

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
                versions.add(version.version);
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

// Render issue cards
function renderResults() {
    elements.results.innerHTML = '';
    elements.resultsCount.textContent = filteredIssues.length;

    if (filteredIssues.length === 0) {
        elements.noResults.classList.remove('hidden');
        return;
    }

    elements.noResults.classList.add('hidden');

    filteredIssues.forEach(issue => {
        const card = createIssueCard(issue);
        elements.results.appendChild(card);
    });
}

// Create issue card HTML
function createIssueCard(issue) {
    const card = document.createElement('div');
    card.className = 'bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow';

    const typeClass = issue.issueType === 'known'
        ? 'bg-amber-100 text-amber-800'
        : 'bg-emerald-100 text-emerald-800';
    const typeLabel = issue.issueType === 'known' ? 'Known Issue' : 'Addressed';

    card.innerHTML = `
        <div class="flex flex-wrap items-start justify-between gap-4 mb-4">
            <div>
                <h3 class="text-lg font-semibold text-gray-900">${escapeHtml(issue.bug_id)}</h3>
                <p class="text-sm text-gray-500">${escapeHtml(issue.productName)} ${escapeHtml(issue.version)}</p>
            </div>
            <div class="flex flex-wrap gap-2 items-center">
                ${issue.affected_components && issue.affected_components.length > 0 ?
                    issue.affected_components.map(comp => `
                        <span class="px-3 py-1 rounded-full text-xs font-medium bg-violet-100 text-violet-800">
                            ${escapeHtml(comp)}
                        </span>
                    `).join('') : ''}
                ${issue.fix_info ? `
                    <span class="px-3 py-1 rounded-full text-xs font-medium bg-sky-100 text-sky-800">
                        ${escapeHtml(issue.fix_info)}
                    </span>
                ` : ''}
                <span class="px-3 py-1 rounded-full text-xs font-medium ${typeClass}">
                    ${typeLabel}
                </span>
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

    // Reset version filter to disabled state
    updateVersionFilter(data);

    // Hide dropdowns
    hideDropdown(elements.productDropdown);
    hideDropdown(elements.versionDropdown);

    applyFilters();
}

// Event listeners
function setupEventListeners(data) {
    // Search input with debouncing
    elements.search.addEventListener('input', debounce((e) => {
        currentFilters.search = e.target.value;
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
            applyFilters();
        },
        () => highlightedVersionIndex,
        (idx) => { highlightedVersionIndex = idx; },
        // Clear callback
        () => {
            currentFilters.version = '';
            applyFilters();
        }
    );

    // Type filter
    elements.typeFilter.addEventListener('change', (e) => {
        currentFilters.type = e.target.value;
        applyFilters();
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

        // Flatten issues for searching
        allIssues = flattenIssues(data);
        filteredIssues = [...allIssues];

        // Populate filters
        populateFilters(data);

        // Setup event listeners
        setupEventListeners(data);

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
