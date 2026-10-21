// Only accept an ISO date (YYYY-MM-DD); reject anything else.
function safeDateParam(v) {
    return /^\d{4}-\d{2}-\d{2}$/.test(v || "") ? v : "";
}
// Only accept a UUID agent id.
function safeAgentId(v) {
    return /^[0-9a-fA-F-]{36}$/.test(v || "") ? v : "";
}

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
        const response = await fetch(url, {
            credentials: 'same-origin'  // Include session cookies
        });
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
            const response = await fetch(url, {
                credentials: 'same-origin'  // Include session cookies
            });
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

// =============================================================================
// ACCESSIBILITY & INTERACTION: Date Input Picker Trigger
// =============================================================================
// Ensures clicking anywhere inside a date input (text area, calendar icon, or
// padded area) opens the native date picker popup, preserving keyboard accessibility.
(function initDateInputPickerInteraction() {
    if (typeof document === 'undefined') return;
    function openPicker(input) {
        if (!input || input.disabled || input.readOnly) return;
        if (typeof input.showPicker === 'function') {
            try {
                input.showPicker();
            } catch (err) {
                // Ignore if already open or disallowed by browser security policy
            }
        }
    }

    // Delegated click listener to support static and dynamically added date inputs
    document.addEventListener('click', function (e) {
        const dateInput = e.target && e.target.closest ? e.target.closest('input[type="date"]') : null;
        if (dateInput) {
            openPicker(dateInput);
        }
    });

    // Keyboard accessibility: Space or Enter on focused date input triggers picker
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
            const dateInput = e.target && e.target.closest ? e.target.closest('input[type="date"]') : null;
            if (dateInput && document.activeElement === dateInput) {
                openPicker(dateInput);
            }
        }
    });
})();

// =============================================================================
// GLOBAL ACCESSIBLE TOOLTIP STANDARD (SentinelEdge Tables & UI)
// =============================================================================
// Provides seamless, high-contrast, theme-aware tooltips for truncated table cells
// and elements with title/data-tooltip attributes on BOTH mouse hover and keyboard focus.
(function initGlobalAccessibleTooltip() {
    if (typeof document === 'undefined') return;
    let tooltipEl = null;
    let activeTarget = null;

    function getOrCreateTooltip() {
        if (!tooltipEl) {
            tooltipEl = document.createElement('div');
            tooltipEl.id = 'se-global-tooltip';
            tooltipEl.className = 'se-tooltip';
            tooltipEl.setAttribute('role', 'tooltip');
            tooltipEl.setAttribute('aria-hidden', 'true');
            document.body.appendChild(tooltipEl);
        }
        return tooltipEl;
    }

    function isTruncated(el) {
        return el.scrollWidth > el.clientWidth + 1;
    }

    function showTooltip(el, isKeyboard = false) {
        if (!el || el === document.body || el === document.documentElement) return;

        if (el.hasAttribute('data-no-tooltip') || (el.closest && el.closest('[data-no-tooltip]'))) {
            hideTooltip();
            return;
        }

        let text = '';
        if (el.dataset && el.dataset.seTooltip) {
            text = el.dataset.seTooltip;
        } else if (el.hasAttribute('title') && el.getAttribute('title').trim()) {
            text = el.getAttribute('title').trim();
            el.dataset.seTooltip = text;
            el.removeAttribute('title'); // Prevent clash with native browser tooltip
        } else if (el.hasAttribute('data-tooltip') && el.getAttribute('data-tooltip').trim()) {
            text = el.getAttribute('data-tooltip').trim();
        } else if (isTruncated(el)) {
            text = (el.dataset && el.dataset.fullText) ? el.dataset.fullText : (el.innerText || el.textContent || '');
            text = text.trim();
        }

        if (!text) {
            hideTooltip();
            return;
        }

        const tip = getOrCreateTooltip();
        tip.textContent = text;
        activeTarget = el;

        tip.classList.add('se-tooltip-visible');
        tip.setAttribute('aria-hidden', 'false');

        const rect = el.getBoundingClientRect();
        const tipHeight = tip.offsetHeight;
        const tipWidth = tip.offsetWidth;

        let top = rect.top - tipHeight - 6;
        if (top < 8) {
            top = rect.bottom + 6;
        }

        let left = rect.left + (rect.width - tipWidth) / 2;
        left = Math.max(8, Math.min(window.innerWidth - tipWidth - 8, left));

        tip.style.top = `${Math.round(top)}px`;
        tip.style.left = `${Math.round(left)}px`;
    }

    function hideTooltip() {
        if (activeTarget) {
            if (activeTarget.dataset && activeTarget.dataset.seTooltip) {
                activeTarget.setAttribute('title', activeTarget.dataset.seTooltip);
            }
            activeTarget = null;
        }
        if (tooltipEl) {
            tooltipEl.classList.remove('se-tooltip-visible');
            tooltipEl.setAttribute('aria-hidden', 'true');
        }
    }

    // Delegated Mouse Hover Interaction
    document.addEventListener('mouseover', function (e) {
        const candidate = e.target.closest('[title], [data-tooltip], .se-cell-truncate, .inv-cell-truncate, .se-table td, .se-table th');
        if (candidate) {
            showTooltip(candidate, false);
        }
    }, true);

    document.addEventListener('mouseout', function (e) {
        if (activeTarget && (!e.relatedTarget || !activeTarget.contains(e.relatedTarget))) {
            hideTooltip();
        }
    }, true);

    // Keyboard Focus Accessibility (FR-026c standard)
    document.addEventListener('focusin', function (e) {
        const candidate = e.target.closest('[title], [data-tooltip], [data-se-tooltip], .se-cell-truncate, .inv-cell-truncate, [tabindex="0"], a, button');
        if (candidate) {
            showTooltip(candidate, true);
        }
    }, true);

    document.addEventListener('focusout', function () {
        hideTooltip();
    }, true);

    // Dismiss on Escape or scroll
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            hideTooltip();
        }
    });

    window.addEventListener('scroll', function () {
        if (activeTarget && !document.activeElement?.contains(activeTarget)) {
            hideTooltip();
        }
    }, { passive: true });

    // Keyboard navigation: Ensure table cells / truncated spans have tabindex="0"
    function ensureKeyboardAccessibility() {
        const cells = document.querySelectorAll('.se-table td, .se-table th, .se-cell-truncate, .inv-cell-truncate');
        cells.forEach(cell => {
            if (cell.hasAttribute('data-no-tooltip') || (cell.closest && cell.closest('[data-no-tooltip]'))) return;
            if ((cell.hasAttribute('title') || (cell.dataset && cell.dataset.seTooltip) || isTruncated(cell)) &&
                !cell.hasAttribute('tabindex') &&
                !cell.querySelector('a, button, input')) {
                cell.setAttribute('tabindex', '0');
            }
        });
    }

    document.addEventListener('DOMContentLoaded', ensureKeyboardAccessibility);
    const observer = new MutationObserver(debounce(ensureKeyboardAccessibility, 200));
    observer.observe(document.documentElement, { childList: true, subtree: true });
})();
