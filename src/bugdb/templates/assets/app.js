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
    versionFilter: document.getElementById('version-filter'),
    typeFilter: document.getElementById('type-filter'),
    results: document.getElementById('results'),
    resultsCount: document.getElementById('results-count'),
    noResults: document.getElementById('no-results'),
    loading: document.getElementById('loading'),
    clearFilters: document.getElementById('clear-filters'),
    generatedDate: document.getElementById('generated-date'),
    schemaVersion: document.getElementById('schema-version')
};

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
    // Populate products
    const products = data.products.map(p => ({ id: p.id, name: p.name }));
    products.forEach(product => {
        const option = document.createElement('option');
        option.value = product.id;
        option.textContent = product.name;
        elements.productFilter.appendChild(option);
    });

    // Populate versions (will be updated based on product selection)
    updateVersionFilter(data);
}

// Update version filter based on selected product
function updateVersionFilter(data) {
    const selectedProduct = currentFilters.product;

    // If no product is selected, disable version filter
    if (!selectedProduct) {
        elements.versionFilter.innerHTML = '<option value="">Select a product first</option>';
        elements.versionFilter.disabled = true;
        return;
    }

    // Enable version filter and populate with product-specific versions
    elements.versionFilter.disabled = false;
    elements.versionFilter.innerHTML = '<option value="">All Versions</option>';

    const versions = new Set();

    for (const product of data.products) {
        if (product.id === selectedProduct) {
            for (const version of product.versions) {
                versions.add(version.version);
            }
        }
    }

    // Sort versions in descending order
    const sortedVersions = Array.from(versions).sort((a, b) => {
        const partsA = a.split('.').map(Number);
        const partsB = b.split('.').map(Number);
        for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
            const numA = partsA[i] || 0;
            const numB = partsB[i] || 0;
            if (numA !== numB) return numB - numA;
        }
        return 0;
    });

    sortedVersions.forEach(version => {
        const option = document.createElement('option');
        option.value = version;
        option.textContent = version;
        elements.versionFilter.appendChild(option);
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

    applyFilters();
}

// Event listeners
function setupEventListeners(data) {
    // Search input with debouncing
    elements.search.addEventListener('input', debounce((e) => {
        currentFilters.search = e.target.value;
        applyFilters();
    }, 300));

    // Product filter
    elements.productFilter.addEventListener('change', (e) => {
        currentFilters.product = e.target.value;
        currentFilters.version = ''; // Reset version when product changes
        updateVersionFilter(data);
        applyFilters();
    });

    // Version filter
    elements.versionFilter.addEventListener('change', (e) => {
        currentFilters.version = e.target.value;
        applyFilters();
    });

    // Type filter
    elements.typeFilter.addEventListener('change', (e) => {
        currentFilters.type = e.target.value;
        applyFilters();
    });

    // Clear filters button
    elements.clearFilters.addEventListener('click', () => clearFilters(data));
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
