// Status Badge Generator
function getStatusBadge(lastSeen) {
    if (!lastSeen) return '<span class="badge badge-danger">🔴 Offline</span>';

    // Clean timestamp for parsing
    let ts = lastSeen;
    if (!ts.endsWith('Z') && !ts.includes('+')) ts += 'Z';

    const now = new Date();
    const then = new Date(ts);
    const diffMinutes = (now - then) / 60000;

    if (diffMinutes < 5) return '<span class="badge badge-success">🟢 Active</span>';
    if (diffMinutes < 60) return '<span class="badge badge-warning text-white">🟡 Idle</span>';
    return '<span class="badge badge-danger">🔴 Offline</span>';
}

// Relative Time Formatter
function relativeTime(timestamp) {
    if (!timestamp) return 'Never';
    if (typeof timestamp === 'string' && !timestamp.endsWith('Z') && !timestamp.includes('+')) {
        timestamp += 'Z';
    }
    const now = new Date();
    const then = new Date(timestamp);
    const diffSecs = Math.floor((now - then) / 1000);

    if (isNaN(diffSecs)) return timestamp;
    if (diffSecs < 60) return 'Just now';
    if (diffSecs < 3600) return `${Math.floor(diffSecs / 60)} mins ago`;
    if (diffSecs < 86400) return `${Math.floor(diffSecs / 3600)} hours ago`;
    return `${Math.floor(diffSecs / 86400)} days ago`;
}

// Alias for relativeTime (legacy/multi-format support)
function getRelativeTime(date) {
    return relativeTime(date);
}

// Export Table to CSV - Standard Utility
function exportTableToCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const rows = Array.from(table.rows);
    const csv = rows.map(row => {
        const cells = Array.from(row.querySelectorAll('th, td'));
        return cells.map(cell => {
            let text = cell.innerText.replace(/"/g, '""'); // Escape quotes
            return `"${text}"`;
        }).join(',');
    }).join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
}

// Fetch JSON with error handling
async function fetchJSON(url) {
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('Fetch error:', error);
        showToast('Error loading data: ' + error.message, 'danger');
        return null;
    }
}

// =============================================================================
// PERFORMANCE: Client-Side API Cache
// =============================================================================

const ApiCache = {
    _cache: new Map(),
    _pending: new Map(),  // For request deduplication
    _maxAge: 30000,  // 30 seconds default TTL

    // Get cached response or null
    get(key) {
        const entry = this._cache.get(key);
        if (!entry) return null;
        if (Date.now() > entry.expiry) {
            this._cache.delete(key);
            return null;
        }
        return entry.data;
    },

    // Cache response
    set(key, data, ttlMs = this._maxAge) {
        // Limit cache size
        if (this._cache.size > 100) {
            const oldest = this._cache.keys().next().value;
            this._cache.delete(oldest);
        }
        this._cache.set(key, { data, expiry: Date.now() + ttlMs });
    },

    // Clear all or by pattern
    clear(pattern = null) {
        if (!pattern) {
            this._cache.clear();
            return;
        }
        for (const key of this._cache.keys()) {
            if (key.includes(pattern)) this._cache.delete(key);
        }
    },

    // Get stats
    stats() {
        return { entries: this._cache.size, pending: this._pending.size };
    }
};

// Cached fetch with deduplication
async function fetchJSONCached(url, options = {}) {
    const ttl = options.ttl || 30000;  // 30s default
    const cacheKey = url;

    // Check cache first
    const cached = ApiCache.get(cacheKey);
    if (cached && !options.forceRefresh) {
        return cached;
    }

    // Deduplicate concurrent requests
    if (ApiCache._pending.has(cacheKey)) {
        return ApiCache._pending.get(cacheKey);
    }

    // Make request
    const promise = (async () => {
        try {
            const response = await fetch(url);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            // Cache successful response
            ApiCache.set(cacheKey, data, ttl);
            return data;
        } catch (error) {
            console.error('Fetch error:', error);
            showToast('Error loading data: ' + error.message, 'danger');
            return null;
        } finally {
            ApiCache._pending.delete(cacheKey);
        }
    })();

    ApiCache._pending.set(cacheKey, promise);
    return promise;
}

// Batch multiple API calls
async function fetchBatch(urls) {
    const results = await Promise.all(urls.map(url => fetchJSONCached(url)));
    return results;
}

// Lazy load with intersection observer
function lazyLoad(selector, loadFn) {
    const elements = document.querySelectorAll(selector);
    if (!elements.length) return;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                loadFn(entry.target);
                observer.unobserve(entry.target);
            }
        });
    }, { rootMargin: '100px' });

    elements.forEach(el => observer.observe(el));
}

// Modern Toast Notifications
function showToast(message, status = 'info') {
    const toast = document.createElement('div');
    toast.className = `badge badge-${status} fade-in`;
    toast.style.position = 'fixed';
    toast.style.bottom = '2rem';
    toast.style.right = '2rem';
    toast.style.padding = '1rem 1.5rem';
    toast.style.zIndex = '9999';
    toast.style.boxShadow = 'var(--shadow-lg)';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Debounce function for search inputs
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

// Sort Table
function sortTable(n) {
    var table, rows, switching, i, x, y, shouldSwitch, dir, switchcount = 0;
    table = document.querySelector(".data-table");
    if (!table) return;
    switching = true;
    dir = "asc";

    while (switching) {
        switching = false;
        rows = table.rows;

        for (i = 1; i < (rows.length - 1); i++) {
            shouldSwitch = false;
            x = rows[i].getElementsByTagName("TD")[n];
            y = rows[i + 1].getElementsByTagName("TD")[n];

            if (dir == "asc") {
                if (x.innerText.toLowerCase() > y.innerText.toLowerCase()) {
                    shouldSwitch = true;
                    break;
                }
            } else if (dir == "desc") {
                if (x.innerText.toLowerCase() < y.innerText.toLowerCase()) {
                    shouldSwitch = true;
                    break;
                }
            }
        }
        if (shouldSwitch) {
            rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
            switching = true;
            switchcount++;
        } else {
            if (switchcount == 0 && dir == "asc") {
                dir = "desc";
                switching = true;
            }
        }
    }
}
