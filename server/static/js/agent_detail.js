let reportData = null;
const USERNAME = window.USERNAME || 'User';
let _lastTimelineArgs = null;
new MutationObserver(() => {
    if (_lastTimelineArgs) renderTimeline(..._lastTimelineArgs);
}).observe(document.documentElement, { attributeFilter: ['class'] });

function setGreeting() {
    const hour = new Date().getHours();
    let greeting = "Welcome back";

    if (hour >= 5 && hour < 12) {
        greeting = `<img src='/static/morning.png' class='w-10 h-10 mr-2 inline-block' /> Good Morning <span class='text-blue-600 dark:text-blue-400'></span>`;
    } else if (hour >= 12 && hour < 17) {
        greeting = `<img src='/static/afternoon.png' class='w-10 h-10 mr-2 inline-block' /> Good Afternoon <span class='text-blue-600 dark:text-blue-400'></span>`;
    } else {
        greeting = `<img src='/static/evening.png' class='w-10 h-10 mr-2 inline-block' /> Good Evening <span class='text-blue-600 dark:text-blue-400'></span>`;
    }

    const greetingEl = document.getElementById("greeting-text");
    if (greetingEl) {
        greetingEl.innerHTML = greeting;
    }
}

document.addEventListener("DOMContentLoaded", setGreeting);
// Tab Navigation
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const tabName = btn.dataset.tab;
        // Update button styles
        document.querySelectorAll('.tab-btn').forEach(b => {
            b.classList.remove('bg-gradient-to-r', 'from-blue-500', 'to-purple-600', 'text-white', 'shadow-md');
            b.classList.add('text-gray-600', 'dark:text-gray-300', 'hover:text-gray-900', 'dark:hover:text-gray-100', 'hover:bg-gray-50', 'dark:hover:bg-gray-700');
        });
        btn.classList.remove('text-gray-600', 'dark:text-gray-300', 'hover:text-gray-900', 'dark:hover:text-gray-100', 'hover:bg-gray-50', 'dark:hover:bg-gray-700');
        btn.classList.add('bg-gradient-to-r', 'from-blue-500', 'to-purple-600', 'text-white', 'shadow-md');

        // Show/hide content
        document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
        document.getElementById(`tab-${tabName}`).classList.remove('hidden');
    });
});

// Search Filtering
function setupSearch(inputId, containerId, selector) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener('input', () => {
        const term = input.value.toLowerCase();
        document.querySelectorAll(`#${containerId} ${selector}`).forEach(el => {
            const matches = el.textContent.toLowerCase().includes(term);
            el.style.display = matches ? '' : 'none';
            if (el.dataset.subrowId) {
                const sub = document.getElementById(el.dataset.subrowId);
                if (sub) {
                    if (!matches) {
                        sub.style.display = 'none';
                    } else if (!sub.classList.contains('hidden')) {
                        sub.style.display = '';
                    }
                }
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', () => {
    setupSearch('app-search', 'apps-body', 'tr');
    setupSearch('domain-search', 'domains-body', 'tr');
    setupSearch('inventory-search', 'inventory-body', 'tr.inv-row');
    setupSearch('visits-search', 'visits-list', '.site-item');
});

// Utility functions
function formatTime(seconds) {
    if (!seconds || seconds < 0) return '0s';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function formatTimeShort(seconds) {
    if (!seconds || seconds < 0) return '0s';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return h + 'h';
    if (m > 0) return m + 'm';
    return Math.floor(seconds % 60) + 's';
}

function getSelectedDate() {
    const el = document.getElementById('global-date-select');
    return el ? el.value : localDateStr();
}

async function fetchJSON(url) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(res.statusText);
        return await res.json();
    } catch (e) {
        console.error('Fetch error:', e);
        return null;
    }
}

// Copy Agent ID
function copyAgentId() {
    const agentId = document.getElementById('agent-id-full').value;
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(agentId).then(() => {
            showToast('Agent ID copied to clipboard!', 'success');
        }).catch(() => fallbackCopy(agentId));
    } else {
        fallbackCopy(agentId);
    }
}

function fallbackCopy(text) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    document.body.appendChild(textArea);
    textArea.select();
    try {
        document.execCommand('copy');
        showToast('Agent ID copied to clipboard!', 'success');
    } catch {
        showToast('Copy failed - please copy manually', 'error');
    }
    document.body.removeChild(textArea);
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 px-4 py-2 rounded-lg text-white font-medium z-50 ${type === 'success' ? 'bg-green-500' : 'bg-red-500'}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// Main data loader
async function loadFullReport(isManual = false) {
    const refreshIcon = document.getElementById('refresh-icon');
    if (refreshIcon) refreshIcon.classList.add('animate-spin');

    const selectedDate = getSelectedDate();
    const data = await fetchJSON(`/dashboard/api/agent/${AGENT_ID}/full-report?date=${selectedDate}`);

    if (refreshIcon) {
        // Subtle delay to ensure the animation is visible
        setTimeout(() => refreshIcon.classList.remove('animate-spin'), 600);
    }

    if (!data) {
        showToast('Failed to refresh data', 'error');
        return;
    }

    if (isManual) {
        showToast('Data refreshed successfully', 'success');
    }
    reportData = data;

    // Update agent info
    if (data.agent) {
        if (data.agent.username) {
            const userIcon = window.USER_ICON_SVG || `<img src="${window.USER_ICON_URL}" class="w-8 h-8 mr-2 inline-block" />`;
            document.getElementById('agent-title').innerHTML = `
                    ${userIcon}
                    <span>${data.agent.username}</span>
                `;
        }

        // FR-007: canonical format, viewer timezone. Was toLocaleDateString(),
        // which follows the BROWSER's locale — the same screen rendered
        // differently for different users.
        document.getElementById('registered-at').textContent =
            DateFmt.formatDate(data.agent.registered_at);
        document.getElementById('first-seen-today').textContent = data.agent.first_seen_today
            ? DateFmt.formatDateTime(data.agent.first_seen_today)
            : 'No activity';
        document.getElementById('last-seen-today').textContent = data.agent.last_seen_today
            ? DateFmt.formatDateTime(data.agent.last_seen_today)
            : 'No activity';

        // Live status
        const liveBanner = document.getElementById('live-status-banner');
        if (data.live_status && data.live_status.current_app) {
            if (liveBanner) liveBanner.classList.remove('hidden');
            const liveAppEl = document.getElementById('live-app-name');
            if (liveAppEl) liveAppEl.textContent = data.live_status.current_app;
            const liveTitleEl = document.getElementById('live-window-title');
            if (liveTitleEl) liveTitleEl.textContent = data.live_status.window_title || '';
            const durationEl = document.getElementById('live-duration');
            if (durationEl) {
                if (data.live_status.duration_seconds > 0) {
                    durationEl.textContent = formatTime(data.live_status.duration_seconds);
                    durationEl.classList.remove('hidden');
                } else {
                    durationEl.classList.add('hidden');
                }
            }
            const actEl = document.getElementById('current-activity');
            if (actEl) {
                const app = escapeHtml(data.live_status.current_app);
                actEl.innerHTML = `
                    <span class="se-live-indicator" title="${app}">
                        <span class="se-live-dot"></span>
                        <span class="se-live-text">${app}</span>
                    </span>
                `;
            }
        } else {
            if (liveBanner) liveBanner.classList.add('hidden');
            const actEl = document.getElementById('current-activity');
            if (actEl) {
                actEl.innerHTML = '<span class="text-xs text-gray-500 dark:text-gray-400 font-medium">Offline</span>';
            }
        }

        const stateEl = document.getElementById('current-state');
        const currentState = data.live_status?.current_state || (data.agent.is_online ? 'active' : 'offline');
        const stateConfig = {
            'active': { text: 'Active', class: 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200' },
            'idle': { text: 'Idle', class: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200' },
            'locked': { text: 'Locked', class: 'bg-orange-100 dark:bg-orange-900 text-orange-800 dark:text-orange-200' },
            'offline': { text: 'Offline', class: 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200' }
        };

        const config = stateConfig[currentState] || stateConfig.offline;
        stateEl.textContent = config.text;
        stateEl.className = `inline-block px-2 py-1 ${config.class} text-xs font-medium rounded-full`;
    }

    // Screen time
    const st = data.screen_time || {};
    const activeSeconds = st.active_seconds || 0;
    const idleSeconds = st.idle_seconds || 0;

    // Update Quick Stats
    const totalScreenSeconds = activeSeconds + idleSeconds;
    document.getElementById('quick-screen-time').textContent = formatTime(totalScreenSeconds);
    document.getElementById('quick-apps-count').textContent = data.app_usage?.count || 0;
    document.getElementById('quick-domains-count').textContent = data.domain_usage?.count || 0;
    document.getElementById('quick-sessions-count').textContent = data.app_sessions?.count || 0;

    // T012: Render flip cards
    renderFlipCards(data.screen_time || {}, data.state_events || []);

    // Render tables
    renderAppUsage(data.app_usage);
    renderDomainUsage(data.domain_usage);
    renderDomainVisits(data.domain_visits);
    renderInventory(data.inventory);
    loadScreenTimeHistory();
    loadSecurityIndicators();
    loadSystemVisibility();
}

function renderAppUsage(appData) {
    const tbody = document.getElementById('apps-body');
    tbody.innerHTML = '';
    document.getElementById('apps-count').textContent = `${appData?.count || 0} apps`;

    if (!appData?.data?.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-gray-500">No data</td></tr>';
        return;
    }

    appData.data.forEach(app => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
                <td class="col-app-name"><span class="se-cell-truncate font-medium text-gray-900 dark:text-gray-100" title="${escapeHtml(app.app)}">${escapeHtml(app.app)}</span></td>
                <td class="col-app-sessions se-align-right text-sm text-gray-600 dark:text-gray-300">${app.session_count || '-'}</td>
                <td class="col-app-duration se-align-right se-cell-mono text-sm text-gray-900 dark:text-gray-100">${formatTime(app.duration_seconds)}</td>
                <td class="col-app-pct se-align-right"><span class="text-xs font-medium">${app.percentage}%</span></td>
            `;
        tbody.appendChild(tr);
    });
}

function renderDomainUsage(domainData) {
    const tbody = document.getElementById('domains-body');
    tbody.innerHTML = '';
    document.getElementById('domains-count').textContent = `${domainData?.count || 0} domains`;

    if (!domainData?.data?.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-gray-500">No data</td></tr>';
        return;
    }

    const total = domainData.data.reduce((sum, d) => sum + (d.duration_seconds || 0), 0);
    domainData.data.forEach(d => {
        const pct = total > 0 ? ((d.duration_seconds || 0) / total * 100).toFixed(1) : 0;
        const tr = document.createElement('tr');
        tr.innerHTML = `
                <td class="col-domain-name"><span class="se-cell-truncate font-medium text-gray-900 dark:text-gray-100" title="${escapeHtml(d.domain)}">${escapeHtml(d.domain)}</span></td>
                <td class="col-domain-sessions se-align-right text-sm text-gray-600 dark:text-gray-300">${d.session_count || '-'}</td>
                <td class="col-domain-duration se-align-right se-cell-mono text-sm text-gray-900 dark:text-gray-100">${formatTime(d.duration_seconds)}</td>
                <td class="col-domain-pct se-align-right"><span class="text-xs font-medium">${pct}%</span></td>
            `;
        tbody.appendChild(tr);
    });
}

function renderDomainVisits(visitsData) {
    const list = document.getElementById('visits-list');
    list.innerHTML = '';
    document.getElementById('visits-count').textContent = `${visitsData?.count || 0} visits`;

    if (!visitsData?.data?.length) {
        list.innerHTML = '<div class="p-8 text-center text-gray-500">No browser history</div>';
        return;
    }

    visitsData.data.slice(0, 1000).forEach(v => {
        const div = document.createElement('div');
        div.className = 'site-item flex items-center gap-4 p-3 border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700';
        div.innerHTML = `
<span class="text-xs text-gray-500 dark:text-gray-400 font-mono w-20">
  ${v.visited_at
                ? DateFmt.formatDateTime(v.visited_at).split(' ')[1]
                : ''}
</span>

                <span class="font-medium flex-1 text-gray-900 dark:text-gray-100">${v.domain}</span>
                <span class="text-sm text-gray-500 dark:text-gray-400">${v.browser || ''}</span>
            `;
        list.appendChild(div);
    });
}

function renderInventory(invData) {
    const tbody = document.getElementById('inventory-body');
    tbody.innerHTML = '';
    document.getElementById('inventory-count').textContent = `${invData?.count || 0} apps`;

    if (!invData?.data?.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="px-4 py-8 text-center text-gray-500 dark:text-gray-400">No inventory data</td></tr>';
        return;
    }

    invData.data.forEach((app, idx) => {
        const rawName = app.name || 'Unnamed Application';
        const rawVersion = app.version || '-';
        const cleanPub = cleanPublisher(app.publisher);
        const fullPub = app.publisher || cleanPub;
        const rawLocation = app.install_location || '-';
        const dateFormatted = formatInstallDate(app.install_date);
        const sourceBadgeHtml = getSourceBadge(app.source);

        const tr = document.createElement('tr');
        tr.className = 'inv-row';
        tr.id = `inv-row-${idx}`;
        tr.dataset.subrowId = `inv-subrow-${idx}`;
        tr.onclick = (e) => {
            if (!e.target.closest('button') && !e.target.closest('a')) {
                toggleInventoryDetail(idx);
            }
        };

        const locationTooltip = app.install_location ? app.install_location : 'Not specified';

        tr.innerHTML = `
            <td class="col-inv-name">
                <div class="flex items-center justify-between w-full min-w-0">
                    <span class="inv-cell-truncate font-medium text-sm text-gray-900 dark:text-gray-100 flex-1 min-w-0" title="${escapeHtml(rawName)}">${escapeHtml(rawName)}</span>
                    <span class="inv-mobile-source-badge ml-2 shrink-0 md:hidden">${sourceBadgeHtml}</span>
                </div>
            </td>
            <td class="col-inv-version">
                <span class="inv-mobile-label">Version</span>
                <span class="inv-cell-truncate text-xs text-gray-600 dark:text-gray-300 font-mono" title="${escapeHtml(rawVersion)}">${escapeHtml(rawVersion)}</span>
            </td>
            <td class="col-inv-publisher">
                <span class="inv-mobile-label">Publisher</span>
                <span class="inv-cell-truncate text-xs text-gray-900 dark:text-gray-100" title="${escapeHtml(fullPub)}">${escapeHtml(cleanPub)}</span>
            </td>
            <td class="col-inv-location">
                <span class="inv-mobile-label">Install Location</span>
                <span class="inv-cell-truncate text-xs text-gray-500 dark:text-gray-400 font-mono" title="${escapeHtml(locationTooltip)}">${escapeHtml(rawLocation)}</span>
            </td>
            <td class="col-inv-date">
                <span class="inv-mobile-label">Install Date</span>
                <span class="inv-cell-truncate text-xs text-gray-900 dark:text-gray-100" title="${dateFormatted}">${dateFormatted}</span>
            </td>
            <td class="col-inv-source">
                <span class="inv-mobile-label">Source</span>
                <div class="inv-source-badge-wrap">${sourceBadgeHtml}</div>
            </td>
            <td class="col-inv-action">
                <button type="button" class="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors focus:outline-none" onclick="event.stopPropagation(); toggleInventoryDetail(${idx})" title="Toggle install location">
                    ${window.CHEVRON_DOWN_SVG ? window.CHEVRON_DOWN_SVG(`inv-chevron-${idx}`) : `<svg class="w-4 h-4 transform transition-transform duration-200" id="inv-chevron-${idx}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true"><path d="m19.5 8.25-7.5 7.5-7.5-7.5"/></svg>`}
                </button>
            </td>
        `;

        const subTr = document.createElement('tr');
        subTr.className = 'inv-subrow hidden';
        subTr.id = `inv-subrow-${idx}`;
        subTr.innerHTML = `
            <td colspan="7" class="p-0 border-b border-gray-200 dark:border-gray-700 bg-gray-50/70 dark:bg-gray-800/60">
                <div class="px-4 py-2.5 flex items-center gap-2 text-xs">
                    <span class="font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider text-[11px] shrink-0">Install Location:</span>
                    <span class="font-mono text-gray-700 dark:text-gray-300 break-all select-all">${escapeHtml(rawLocation)}</span>
                </div>
            </td>
        `;

        tbody.appendChild(tr);
        tbody.appendChild(subTr);
    });
}

window.toggleInventoryDetail = function (idx) {
    const subrow = document.getElementById(`inv-subrow-${idx}`);
    const chevron = document.getElementById(`inv-chevron-${idx}`);
    if (!subrow) return;
    const isHidden = subrow.classList.contains('hidden');
    if (isHidden) {
        subrow.classList.remove('hidden');
        if (chevron) chevron.classList.add('rotate-180');
    } else {
        subrow.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
    }
};

function cleanPublisher(publisher) {
    if (!publisher || publisher === '-' || publisher.trim() === '') return 'Unknown';
    const cnMatch = publisher.match(/CN=([^,]+)/);
    const oMatch = publisher.match(/O=([^,]+)/);
    if (cnMatch && cnMatch[1]) return cnMatch[1].trim();
    if (oMatch && oMatch[1]) return oMatch[1].trim();
    return publisher.trim();
}

function cleanInstallLocation(location) {
    if (!location || location === '-') return '-';
    return location;
}

function formatInstallDate(dateStr) {
    if (!dateStr || dateStr === '-') return '-';
    const result = DateFmt.formatDate(dateStr);
    return result === DateFmt.EMPTY_DISPLAY ? dateStr : result;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getSourceBadge(source) {
    if (!source || source === '-' || String(source).trim() === '' || String(source).toLowerCase() === 'unknown') {
        return '<span class="inv-badge-source inv-badge-unknown" title="Unknown Source">Unknown</span>';
    }
    const s = String(source).trim().toLowerCase();
    if (s.includes('hklm') || s === 'system') {
        return `<span class="inv-badge-source inv-badge-system" title="${escapeHtml(source)}">System</span>`;
    }
    if (s.includes('hkcu') || s === 'user') {
        return `<span class="inv-badge-source inv-badge-user" title="${escapeHtml(source)}">User</span>`;
    }
    if (s.includes('store')) {
        return `<span class="inv-badge-source inv-badge-store" title="${escapeHtml(source)}">Store</span>`;
    }
    return `<span class="inv-badge-source inv-badge-other" title="${escapeHtml(source)}">${escapeHtml(source)}</span>`;
}

async function loadScreenTimeHistory() {
    const selectedDate = getSelectedDate();
    const data = await fetchJSON(`/dashboard/api/agent/${AGENT_ID}/screentime?date=${selectedDate}`);
    if (!data) return;

    const ctx = document.getElementById('screentime-history-chart');
    if (!ctx) return;

    if (window.screentimeChart) window.screentimeChart.destroy();

    window.screentimeChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [
                { label: 'Active', data: data.active, backgroundColor: '#00ffaa', stack: 'Stack 0', borderRadius: 4 },
                // TEMPORARY: Idle disabled / merged into Active
                // { label: 'Idle', data: data.idle, backgroundColor: '#f59e0b', stack: 'Stack 0', borderRadius: 4 },
                { label: 'Locked', data: data.locked, backgroundColor: '#e6005c', stack: 'Stack 0', borderRadius: 4 }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { callback: (val) => formatTimeShort(val) },
                    stacked: true,
                    title: { display: true, text: 'Usage Time' }
                },
                x: { stacked: true, grid: { display: false } }
            },
            plugins: {
                legend: { position: 'top' },
                tooltip: {
                    callbacks: {
                        label: (ctx) => ctx.dataset.label + ': ' + formatTime(ctx.parsed.y)
                    }
                }
            }
        }
    });
}

// Inventory export (D15 / FR-025b).
//
// This used to scrape the rendered #inventory-table into CSV in the browser.
// That produced a document unlike the one the Reports page hands out for the
// same data: no title, no agent identity, no de-duplication, and whatever
// columns the table happened to show. It was also broken — rows were joined on
// the literal two-character sequence \n, so every export was one long line.
//
// Both downloads now come from build_inventory_workbook() on the server, so
// there is one inventory template rather than two that drift apart.
async function downloadInventoryWorkbook() {
    const btn = document.getElementById('btn-inventory-xlsx');
    const original = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = 'Preparing…';
    }
    try {
        const resp = await fetch(
            `/dashboard/api/inventory/fleet-export.xlsx?agent_id=${encodeURIComponent(AGENT_ID)}`
        );
        if (!resp.ok) {
            let msg = 'Failed to generate the spreadsheet.';
            try { const j = await resp.json(); if (j && j.error) msg = j.error; } catch (e) { /* non-JSON error body */ }
            alert(msg);
            return;
        }

        // Honour the server's Content-Disposition so the DD-MM-YYYY filename
        // (FR-007) is defined in exactly one place.
        let filename = 'inventory.xlsx';
        const disposition = resp.headers.get('Content-Disposition') || '';
        const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
        if (match) filename = decodeURIComponent(match[1]);

        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('Failed to generate the spreadsheet: ' + e);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = original;
        }
    }
}

// Hardware data loader
async function loadHardware() {
    const data = await fetchJSON(`/dashboard/api/agent/${AGENT_ID}/hardware`);
    const loading = document.getElementById('hardware-loading');
    const empty = document.getElementById('hardware-empty');
    const content = document.getElementById('hardware-content');

    if (!loading || !empty || !content) return;

    loading.classList.add('hidden');

    if (!data || !data.data) {
        empty.classList.remove('hidden');
        return;
    }

    const hw = data.data;
    content.classList.remove('hidden');

    // Identity
    const setText = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val || '-';
    };

    setText('hw-hostname', hw.hostname);
    setText('hw-manufacturer', hw.manufacturer);
    setText('hw-model', hw.model);
    setText('hw-serial', hw.serial_number);
    setText('hw-os-version', hw.os_version);
    setText('hw-os-build', hw.os_build);

    // Hardware specs
    setText('hw-cpu', hw.cpu_name);
    setText('hw-cpu-cores', hw.cpu_cores ? `${hw.cpu_cores} cores / ${hw.cpu_threads || hw.cpu_cores} threads` : '-');
    setText('hw-ram', hw.ram_total_gb ? `${hw.ram_total_gb} GB` : '-');
    if (hw.gpus && hw.gpus.length > 0) {
        setText('hw-gpu', hw.gpus.map(g => g.name).join(', '));
    } else {
        setText('hw-gpu', '-');
    }
    // Compute total disk from disks array
    const totalDisk = hw.disks && hw.disks.length > 0
        ? hw.disks.reduce((sum, d) => sum + (d.size_gb || 0), 0).toFixed(0)
        : null;
    setText('hw-disk', totalDisk ? `${totalDisk} GB` : '-');
    // Battery health replaces the old "BIOS Version" tile. Color-coded health
    // bar (green >= 80%, yellow 60-79%, red < 60%). Charge % and cycle count
    // were dropped - WMI reports both unreliably across OEMs/drivers, and a
    // silent 0 was indistinguishable from "no data".
    const battery = hw.battery;
    const bHealth = document.getElementById('hw-battery-health');
    const bName = document.getElementById('hw-battery-name');
    const bBar = document.getElementById('hw-battery-bar');
    if (battery && battery.name) {
        bHealth.textContent = battery.health_percent != null ? `${Math.round(battery.health_percent)}%` : '-';
        bName.textContent = battery.name;
        const pct = Math.max(0, Math.min(100, battery.health_percent || 0));
        bBar.style.width = `${pct}%`;
        bBar.style.backgroundColor = pct >= 80 ? '#22c55e' : pct >= 60 ? '#eab308' : '#ef4444';
    } else {
        bHealth.textContent = 'No battery';
        bName.textContent = '';
        bBar.style.width = '0%';
    }

    // Network
    setText('hw-ip', hw.primary_ip);
    setText('hw-mac', hw.primary_mac);
    setText('hw-domain', hw.domain_name);

    // Security
    const avProduct = hw.antivirus && hw.antivirus.length > 0 ? hw.antivirus.map(a => a.name || a).join(', ') : '-';
    setText('hw-antivirus', avProduct);
    setText('hw-firewall', hw.firewall_enabled != null ? (hw.firewall_enabled ? 'Enabled ✅' : 'Disabled ❌') : '-');
    setText('hw-bitlocker', hw.bitlocker_status);

    // Meta
    setText('hw-collected-at', DateFmt.formatDateTime(hw.collected_at));
    setText('hw-hash', hw.collection_hash);
}

// Extended Inventory data loader
async function loadExtendedInventory() {
    const data = await fetchJSON(`/dashboard/api/agent/${AGENT_ID}/extended-inventory`);
    const loading = document.getElementById('extended-loading');
    const empty = document.getElementById('extended-empty');
    const content = document.getElementById('extended-content');

    if (loading) loading.classList.add('hidden');

    if (!data || data.error) {
        if (empty) empty.classList.remove('hidden');
        return;
    }

    // Check if any data exists
    const hasData = (data.cli_tools && data.cli_tools.length > 0) ||
        (data.drivers && data.drivers.length > 0) ||
        (data.vscode_extensions && data.vscode_extensions.length > 0) ||
        (data.browser_extensions && data.browser_extensions.length > 0) ||
        (data.plugins && data.plugins.length > 0) ||
        (data.portable_apps && data.portable_apps.length > 0);

    if (!hasData) {
        if (empty) empty.classList.remove('hidden');
        return;
    }

    if (content) content.classList.remove('hidden');

    // CLI Tools
    const cliToolsBody = document.getElementById('cli-tools-body');
    const cliToolsCount = document.getElementById('cli-tools-count');
    if (cliToolsBody && data.cli_tools && data.cli_tools.length > 0) {
        cliToolsBody.innerHTML = data.cli_tools.map(tool => `
            <tr>
                <td class="col-cli-name font-medium text-gray-900 dark:text-gray-100"><span class="se-cell-truncate" title="${escapeHtml(tool.name || '-')}">${escapeHtml(tool.name || '-')}</span></td>
                <td class="col-cli-ver text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(tool.version || '-')}">${escapeHtml(tool.version || '-')}</span></td>
                <td class="col-cli-path text-gray-500 dark:text-gray-400"><span class="se-cell-truncate se-cell-mono" title="${escapeHtml(tool.executable_path || '')}">${escapeHtml(tool.executable_path || '-')}</span></td>
                <td class="col-cli-src text-gray-500 dark:text-gray-400"><span class="se-cell-truncate" title="${escapeHtml(tool.source || '-')}">${escapeHtml(tool.source || '-')}</span></td>
            </tr>
        `).join('');
        if (cliToolsCount) cliToolsCount.textContent = `${data.cli_tools.length} tools`;
    }

    // Hardware Drivers
    const driversBody = document.getElementById('drivers-body');
    const driversCount = document.getElementById('drivers-count');
    if (driversBody && data.drivers && data.drivers.length > 0) {
        driversBody.innerHTML = data.drivers.map(driver => `
            <tr>
                <td class="col-drv-dev font-medium text-gray-900 dark:text-gray-100"><span class="se-cell-truncate" title="${escapeHtml(driver.device_name || driver.driver_name || '-')}">${escapeHtml(driver.device_name || driver.driver_name || '-')}</span></td>
                <td class="col-drv-ver text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(driver.driver_version || '-')}">${escapeHtml(driver.driver_version || '-')}</span></td>
                <td class="col-drv-mfr text-gray-500 dark:text-gray-400"><span class="se-cell-truncate" title="${escapeHtml(driver.manufacturer || '-')}">${escapeHtml(driver.manufacturer || '-')}</span></td>
                <td class="col-drv-class text-gray-500 dark:text-gray-400"><span class="se-cell-truncate" title="${escapeHtml(driver.device_class || '-')}">${escapeHtml(driver.device_class || '-')}</span></td>
                <td class="col-drv-sign se-align-center">${driver.is_signed ? '<span class="text-green-600 dark:text-green-400 font-semibold text-xs">✓ Signed</span>' : '<span class="text-red-600 dark:text-red-400 font-semibold text-xs">✗ Unsigned</span>'}</td>
            </tr>
        `).join('');
        if (driversCount) driversCount.textContent = `${data.drivers.length} drivers`;
    }

    // VS Code Extensions
    const vscodeExtBody = document.getElementById('vscode-ext-body');
    const vscodeExtCount = document.getElementById('vscode-ext-count');
    if (vscodeExtBody && data.vscode_extensions && data.vscode_extensions.length > 0) {
        vscodeExtBody.innerHTML = data.vscode_extensions.map(ext => `
            <tr>
                <td class="col-vsc-ext font-medium text-gray-900 dark:text-gray-100"><span class="se-cell-truncate" title="${escapeHtml(ext.display_name || ext.extension_id || '-')}">${escapeHtml(ext.display_name || ext.extension_id || '-')}</span></td>
                <td class="col-vsc-pub text-gray-500 dark:text-gray-400"><span class="se-cell-truncate" title="${escapeHtml(ext.publisher || '-')}">${escapeHtml(ext.publisher || '-')}</span></td>
                <td class="col-vsc-ver text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(ext.version || '-')}">${escapeHtml(ext.version || '-')}</span></td>
                <td class="col-vsc-src text-gray-500 dark:text-gray-400"><span class="se-cell-truncate" title="${escapeHtml(ext.source || '-')}">${escapeHtml(ext.source || '-')}</span></td>
            </tr>
        `).join('');
        if (vscodeExtCount) vscodeExtCount.textContent = `${data.vscode_extensions.length} extensions`;
    }

    // Browser Extensions
    const browserExtBody = document.getElementById('browser-ext-body');
    const browserExtCount = document.getElementById('browser-ext-count');
    if (browserExtBody && data.browser_extensions && data.browser_extensions.length > 0) {
        browserExtBody.innerHTML = data.browser_extensions.map(ext => `
            <tr>
                <td class="col-brw-type text-gray-500 dark:text-gray-400 capitalize"><span class="se-cell-truncate" title="${escapeHtml(ext.browser || '-')}">${escapeHtml(ext.browser || '-')}</span></td>
                <td class="col-brw-name font-medium text-gray-900 dark:text-gray-100"><span class="se-cell-truncate" title="${escapeHtml(ext.name || '-')}">${escapeHtml(ext.name || '-')}</span></td>
                <td class="col-brw-ver text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(ext.version || '-')}">${escapeHtml(ext.version || '-')}</span></td>
                <td class="col-brw-status se-align-center">${ext.enabled ? '<span class="text-green-600 dark:text-green-400 font-bold">✓</span>' : '<span class="text-gray-400">✗</span>'}</td>
            </tr>
        `).join('');
        if (browserExtCount) browserExtCount.textContent = `${data.browser_extensions.length} extensions`;
    }

    // Application Plugins
    const pluginsBody = document.getElementById('plugins-body');
    const pluginsCount = document.getElementById('plugins-count');
    if (pluginsBody && data.plugins && data.plugins.length > 0) {
        pluginsBody.innerHTML = data.plugins.map(plugin => `
            <tr>
                <td class="col-plg-type text-gray-500 dark:text-gray-400"><span class="se-cell-truncate" title="${escapeHtml(plugin.plugin_type || '-')}">${escapeHtml(plugin.plugin_type || '-')}</span></td>
                <td class="col-plg-name font-medium text-gray-900 dark:text-gray-100"><span class="se-cell-truncate" title="${escapeHtml(plugin.name || '-')}">${escapeHtml(plugin.name || '-')}</span></td>
                <td class="col-plg-host text-gray-500 dark:text-gray-400"><span class="se-cell-truncate" title="${escapeHtml(plugin.host_application || '-')}">${escapeHtml(plugin.host_application || '-')}</span></td>
                <td class="col-plg-status se-align-center">${plugin.enabled ? '<span class="text-green-600 dark:text-green-400 font-bold">✓</span>' : '<span class="text-gray-400">✗</span>'}</td>
            </tr>
        `).join('');
        if (pluginsCount) pluginsCount.textContent = `${data.plugins.length} plugins`;
    }

    // Portable Applications
    const portableBody = document.getElementById('portable-body');
    const portableCount = document.getElementById('portable-count');
    if (portableBody && data.portable_apps && data.portable_apps.length > 0) {
        portableBody.innerHTML = data.portable_apps.map(app => {
            const sizeStr = app.file_size_bytes ? formatBytes(app.file_size_bytes) : '-';
            const driveMatch = (app.executable_path || '').match(/^[A-Za-z]:/);
            const drive = driveMatch ? driveMatch[0].toUpperCase() : '-';
            return `
            <tr>
                <td class="col-prt-name font-medium text-gray-900 dark:text-gray-100"><span class="se-cell-truncate" title="${escapeHtml(app.name || '-')}">${escapeHtml(app.name || '-')}</span></td>
                <td class="col-prt-ver text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(app.version || '-')}">${escapeHtml(app.version || '-')}</span></td>
                <td class="col-prt-drv se-align-center text-gray-500 dark:text-gray-400">${escapeHtml(drive)}</td>
                <td class="col-prt-path text-gray-500 dark:text-gray-400"><span class="se-cell-truncate se-cell-mono" title="${escapeHtml(app.executable_path || '')}">${escapeHtml(app.executable_path || '-')}</span></td>
                <td class="col-prt-size se-align-right text-gray-500 dark:text-gray-400 font-mono text-xs">${sizeStr}</td>
            </tr>
        `}).join('');
        if (portableCount) portableCount.textContent = `${data.portable_apps.length} apps`;
    }
}

async function loadSystemVisibility() {
    const data = await fetchJSON(`/dashboard/api/agent/${AGENT_ID}/system-visibility`);
    if (!data || data.error) return;

    const openPorts = Array.isArray(data.open_ports) ? data.open_ports : [];
    const connections = Array.isArray(data.network_connections) ? data.network_connections : [];
    const startups = Array.isArray(data.startup_programs) ? data.startup_programs : [];
    const tasks = Array.isArray(data.scheduled_tasks) ? data.scheduled_tasks : [];
    const disks = Array.isArray(data.disk_usage) ? data.disk_usage : [];
    const counts = data.counts || {};

    const setText = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    };

    setText('visibility-open-ports-count', String(counts.open_ports ?? openPorts.length));
    setText('visibility-connections-count', String(counts.network_connections ?? connections.length));
    setText('visibility-startup-count', String(counts.startup_programs ?? startups.length));
    setText('visibility-tasks-count', String(counts.scheduled_tasks ?? tasks.length));
    setText('visibility-disks-count', String(counts.disk_usage ?? disks.length));

    const updatedEl = document.getElementById('system-visibility-updated');
    if (updatedEl) {
        if (data.timestamp) {
            const snapshot = DateFmt.formatDateTime(data.timestamp);
            updatedEl.textContent = `Latest snapshot: ${snapshot === DateFmt.EMPTY_DISPLAY ? data.timestamp : snapshot}`;
        } else {
            updatedEl.textContent = 'Latest snapshot: -';
        }
    }

    const fillBody = (id, rows, emptyColspan, emptyMessage) => {
        const tbody = document.getElementById(id);
        if (!tbody) return;
        if (!rows || rows.length === 0) {
            tbody.innerHTML = `<tr><td colspan="${emptyColspan}" class="px-3 py-3 text-center text-gray-500 dark:text-gray-400 text-sm">${emptyMessage}</td></tr>`;
            return;
        }
        tbody.innerHTML = rows.join('');
    };

    fillBody(
        'visibility-ports-body',
        openPorts.map(p => `
            <tr>
                <td class="col-port-num se-cell-mono font-medium text-gray-900 dark:text-gray-100">${escapeHtml(String(p.local_port ?? '-'))}</td>
                <td class="col-port-addr text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(p.local_address || '-')}">${escapeHtml(p.local_address || '-')}</span></td>
                <td class="col-port-proc text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(p.process_name || '-')}">${escapeHtml(p.process_name || '-')}</span></td>
            </tr>
        `),
        3,
        'No open ports data'
    );

    fillBody(
        'visibility-connections-body',
        connections.map(c => {
            const remote = `${c.remote_address || '-'}:${c.remote_port ?? '-'}`;
            const local = `${c.local_address || '-'}:${c.local_port ?? '-'}`;
            return `
            <tr>
                <td class="col-conn-remote text-gray-900 dark:text-gray-100"><span class="se-cell-truncate se-cell-mono" title="${escapeHtml(remote)}">${escapeHtml(remote)}</span></td>
                <td class="col-conn-local text-gray-600 dark:text-gray-300"><span class="se-cell-truncate se-cell-mono" title="${escapeHtml(local)}">${escapeHtml(local)}</span></td>
                <td class="col-conn-proc text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(c.process_name || '-')}">${escapeHtml(c.process_name || '-')}</span></td>
            </tr>
        `}),
        3,
        'No active connection data'
    );

    fillBody(
        'visibility-startup-body',
        startups.map(s => `
            <tr>
                <td class="col-startup-name text-gray-900 dark:text-gray-100"><span class="se-cell-truncate font-medium" title="${escapeHtml(s.name || s.program_name || '-')}">${escapeHtml(s.name || s.program_name || '-')}</span></td>
                <td class="col-startup-cmd text-gray-600 dark:text-gray-300"><span class="se-cell-truncate se-cell-mono" title="${escapeHtml(s.command || s.path || '')}">${escapeHtml(s.command || s.path || '-')}</span></td>
                <td class="col-startup-src text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(s.source || s.location || '-')}">${escapeHtml(s.source || s.location || '-')}</span></td>
            </tr>
        `),
        3,
        'No startup program data'
    );

    fillBody(
        'visibility-tasks-body',
        tasks.map(t => `
            <tr>
                <td class="col-task-name text-gray-900 dark:text-gray-100"><span class="se-cell-truncate font-medium" title="${escapeHtml(t.task_name || t.name || '-')}">${escapeHtml(t.task_name || t.name || '-')}</span></td>
                <td class="col-task-path text-gray-600 dark:text-gray-300"><span class="se-cell-truncate se-cell-mono" title="${escapeHtml(t.task_path || t.path || '')}">${escapeHtml(t.task_path || t.path || '-')}</span></td>
                <td class="col-task-prin text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(t.principal || '-')}">${escapeHtml(t.principal || '-')}</span></td>
            </tr>
        `),
        3,
        'No scheduled task data'
    );

    fillBody(
        'visibility-disk-body',
        disks.map(d => `
            <tr>
                <td class="col-disk-drive font-bold text-gray-900 dark:text-gray-100">${escapeHtml(d.drive || '-')}</td>
                <td class="col-disk-vol text-gray-600 dark:text-gray-300"><span class="se-cell-truncate" title="${escapeHtml(d.volume_name || '-')}">${escapeHtml(d.volume_name || '-')}</span></td>
                <td class="col-disk-pct se-align-right text-gray-600 dark:text-gray-300">${escapeHtml(String(d.used_percent ?? '-'))}%</td>
                <td class="col-disk-free se-align-right text-gray-600 dark:text-gray-300 font-mono">${escapeHtml(String(d.free_gb ?? '-'))}</td>
                <td class="col-disk-size se-align-right text-gray-600 dark:text-gray-300 font-mono">${escapeHtml(String(d.size_gb ?? '-'))}</td>
            </tr>
        `),
        5,
        'No disk usage data'
    );
}

// Helper function to format bytes
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Helper function to escape HTML
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Add auto-refresh mechanism
let refreshInterval;

function startAutoRefresh(intervalSeconds = 30) {
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(() => {
        console.log('[AUTO-REFRESH] Refreshing dashboard data...');
        loadFullReport();
    }, intervalSeconds * 1000);
}

// Security Indicators
async function loadSecurityIndicators() {
    const loading = document.getElementById('security-loading');
    const empty = document.getElementById('security-empty');
    const content = document.getElementById('security-content');

    if (!loading || !empty || !content) return;

    const data = await fetchJSON(`/dashboard/api/agent/${AGENT_ID}/security-indicators`);

    loading.classList.add('hidden');

    if (!Array.isArray(data)) {
        empty.classList.remove('hidden');
        content.classList.add('hidden');
        return;
    }

    empty.classList.add('hidden');
    content.classList.remove('hidden');

    if (data.length === 0) {
        const scoreEl = document.getElementById('security-score');
        const scoreBar = document.getElementById('security-score-bar');
        const scoreLabel = document.getElementById('security-score-label');

        if (scoreEl) {
            scoreEl.textContent = '100';
            scoreEl.className = 'text-4xl font-bold text-green-600 dark:text-green-400 mt-1';
        }
        if (scoreBar) scoreBar.style.width = '100%';
        if (scoreLabel) scoreLabel.textContent = 'No active security indicators reported';

        document.getElementById('critical-count').textContent = '0';
        document.getElementById('warning-count').textContent = '0';

        renderCriticalAlerts([]);
        renderSecurityTable('network-body', [], 'network');
        renderSecurityTable('extensions-body', [], 'extension');
        renderSecurityTable('persistence-body', [], 'persistence');
        renderSecurityTable('audit-body', [], 'audit');

        document.getElementById('network-count').textContent = '0 indicators';
        document.getElementById('extensions-count').textContent = '0 indicators';
        document.getElementById('persistence-count').textContent = '0 indicators';
        document.getElementById('audit-count').textContent = '0 indicators';
        return;
    }

    // Group indicators by type
    const grouped = {
        critical: data.filter(i => i.severity === 'critical' || i.severity === 'high'),
        unsigned_drivers: data.filter(i => i.indicator_type === 'unsigned_driver'),
        browser_extensions: data.filter(i => i.indicator_type === 'suspicious_extension' || i.indicator_type === 'browser_extension'),
        persistence: data.filter(i =>
            i.indicator_type === 'startup_program' ||
            i.indicator_type === 'scheduled_task' ||
            i.indicator_type === 'suspicious_startup' ||
            i.indicator_type === 'suspicious_task'
        ),
        network: data.filter(i =>
            i.indicator_type === 'open_port' ||
            i.indicator_type === 'network_connection' ||
            i.indicator_type === 'suspicious_connection'
        ),
        audit: data.filter(i =>
            i.indicator_type === 'usb_device' ||
            i.indicator_type === 'login_event' ||
            i.indicator_type === 'anomaly' ||
            i.indicator_type === 'disk_usage'
        )
    };

    // Calculate security score
    // Critical: -20, High: -15, Medium: -5, Low: -1
    let penalties = 0;
    data.forEach(i => {
        const sev = (i.severity || 'low').toLowerCase();
        if (sev === 'critical') penalties += 20;
        else if (sev === 'high') penalties += 15;
        else if (sev === 'medium') penalties += 5;
        else if (sev === 'low') penalties += 1;
    });

    const score = Math.max(0, 100 - penalties);
    const scoreEl = document.getElementById('security-score');
    const scoreBar = document.getElementById('security-score-bar');
    if (scoreEl) {
        scoreEl.textContent = score;
        if (score > 80) scoreEl.className = 'text-4xl font-bold text-green-600 dark:text-green-400 mt-1';
        else if (score > 50) scoreEl.className = 'text-4xl font-bold text-yellow-600 dark:text-yellow-400 mt-1';
        else scoreEl.className = 'text-4xl font-bold text-red-600 dark:text-red-400 mt-1';
    }
    if (scoreBar) scoreBar.style.width = `${score}%`;

    document.getElementById('critical-count').textContent = data.filter(i => i.severity === 'critical' || i.severity === 'high').length;
    document.getElementById('warning-count').textContent = data.filter(i => i.severity === 'medium').length;

    // Render sections
    renderCriticalAlerts(grouped.critical);
    renderSecurityTable('network-body', grouped.network, 'network');
    renderSecurityTable('extensions-body', grouped.browser_extensions, 'extension');
    renderSecurityTable('persistence-body', grouped.persistence, 'persistence');
    renderSecurityTable('audit-body', grouped.audit, 'audit');

    // Update counts
    document.getElementById('network-count').textContent = `${grouped.network.length} indicators`;
    document.getElementById('extensions-count').textContent = `${grouped.browser_extensions.length} indicators`;
    document.getElementById('persistence-count').textContent = `${grouped.persistence.length} indicators`;
    document.getElementById('audit-count').textContent = `${grouped.audit.length} indicators`;
}

function renderCriticalAlerts(alerts) {
    const container = document.getElementById('critical-issues-body');
    const badge = document.getElementById('critical-badge');
    if (!container) return;

    if (alerts.length === 0) {
        container.innerHTML = `
            <div class="p-8 text-center text-gray-500">
                <div class="text-3xl mb-2">✅</div>
                <p class="font-medium">No high priority alerts</p>
                <p class="text-xs">Your system posture looks healthy.</p>
            </div>
        `;
        if (badge) badge.classList.add('hidden');
        return;
    }

    if (badge) badge.classList.remove('hidden');

    container.innerHTML = alerts.map(item => {
        const details = item.details || {};
        return `
            <div class="p-4 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
                <div class="flex items-start gap-4">
                    <div class="mt-1 w-8 h-8 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center text-red-600">
                        🚨
                    </div>
                    <div class="flex-1">
                        <div class="flex items-center justify-between">
                            <h4 class="font-bold text-gray-900 dark:text-gray-100">${escapeHtml(item.title)}</h4>
                            ${getSeverityBadge(item.severity)}
                        </div>
                        <p class="text-sm text-gray-600 dark:text-gray-400 mt-1">${escapeHtml(details.description || item.indicator_type)}</p>
                        <div class="mt-2 flex items-center gap-4 text-xs text-gray-400">
                            <span>Detected: ${DateFmt.formatDate(item.first_detected)}</span>
                            <span>Score Impact: -${item.severity === 'critical' ? 20 : 15}</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderSecurityTable(tableId, items, category) {
    const tbody = document.getElementById(tableId);
    if (!tbody) return;

    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="px-4 py-8 text-center text-gray-400 text-sm">No indicators detected</td></tr>';
        return;
    }

    tbody.innerHTML = items.map(item => {
        const details = item.details || {};
        let col1 = '-', col2 = '-';

        if (category === 'network') {
            col1 = item.indicator_type === 'open_port' ? 'Open Port' : 'Connection';
            col2 = details.process_name ? `${details.process_name} (${details.local_port || item.title.match(/port (\d+)/)?.[1] || ''})` : item.title;
        } else if (category === 'extension') {
            col1 = details.browser || 'Unknown';
            col2 = details.name || item.title;
        } else if (category === 'persistence') {
            col1 = (item.indicator_type === 'startup_program' || item.indicator_type === 'suspicious_startup') ? 'Startup' : 'Task';
            col2 = details.name || details.task_name || item.title;
        } else if (category === 'audit') {
            col1 = item.indicator_type.replace('_', ' ');
            col2 = item.title;
        }

        return `
            <tr>
                <td class="col-sec-type text-sm font-medium text-gray-600 dark:text-gray-400 capitalize">${escapeHtml(col1)}</td>
                <td class="col-sec-desc"><span class="se-cell-truncate text-gray-900 dark:text-gray-100" title="${escapeHtml(col2)}">${escapeHtml(col2)}</span></td>
                <td class="col-sec-risk se-align-right">${getSeverityBadge(item.severity)}</td>
            </tr>
        `;
    }).join('');
}

function getSeverityBadge(severity) {
    const s = (severity || 'low').toLowerCase();
    const colors = {
        critical: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400 border-red-200 dark:border-red-800',
        high: 'bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-400 border-orange-200 dark:border-orange-800',
        medium: 'bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-400 border-yellow-200 dark:border-yellow-800',
        low: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400 border-blue-200 dark:border-blue-800'
    };
    const colorClass = colors[s] || colors.low;
    return `<span class="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded border ${colorClass}">${s}</span>`;
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadFullReport();
    loadHardware();
    loadExtendedInventory();
    startAutoRefresh(30);
});

// Handle visibility change to save resources
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        if (refreshInterval) clearInterval(refreshInterval);
    } else {
        startAutoRefresh(30);
    }
});

const dateSelect = document.getElementById('global-date-select');
if (dateSelect) dateSelect.addEventListener('change', loadFullReport);

// ─── T010: renderFlipCards ────────────────────────────────────────────────────
function renderFlipCards(st, stateEvents) {
    const utilPct = st.utilization_percent ?? 0;
    const availSec = st.available_seconds ?? 0;
    const lockedCh = st.locked_ch ?? 0;
    const awayCh = st.away_ch ?? 0;
    const activeSec = st.active_seconds ?? 0;
    const idleSec = st.idle_seconds ?? 0;
    const coreStart = st.core_hours_start || '09:00';
    const coreEnd = st.core_hours_end || '19:00';
    const coreWindowSec = (() => {
        const [sh, sm] = coreStart.split(':').map(Number);
        const [eh, em] = coreEnd.split(':').map(Number);
        return Math.max(0, (eh * 60 + em - sh * 60 - sm) * 60);
    })();

    // ── New shift-goal card (ea-*) ────────────────────────────────────────────
    const productivePct = st.productive_pct ?? utilPct;
    const productiveTimeStr = st.productive_time_str ?? formatTime(activeSec);
    const totalInactiveSec = awayCh + lockedCh + idleSec;
    const awayPctNew = st.away_pct ?? (totalInactiveSec > 0 ? Math.round(awayCh / totalInactiveSec * 100) : 0);
    const lockedPctNew = st.locked_pct ?? (totalInactiveSec > 0 ? Math.round(lockedCh / totalInactiveSec * 100) : 0);
    const idlePct = st.idle_pct ?? (totalInactiveSec > 0 ? Math.round(idleSec / totalInactiveSec * 100) : 0);
    const awayTimeStr = st.away_time_str ?? formatTime(awayCh);
    const lockedTimeStr = st.locked_time_str ?? formatTime(lockedCh);
    const idleTimeStr = st.idle_time_str ?? formatTime(idleSec);

    const eaTime = document.getElementById('ea-productive-time');
    const eaBar = document.getElementById('ea-progress-bar');
    const eaCaption = document.getElementById('ea-caption');
    const eaAway = document.getElementById('ea-away-stat');
    const eaLocked = document.getElementById('ea-locked-stat');
    const eaIdle = document.getElementById('ea-idle-stat');

    if (eaTime) eaTime.textContent = productiveTimeStr;
    if (eaBar) eaBar.style.width = productivePct + '%';
    if (eaCaption) eaCaption.textContent = `${productivePct}% of standard shift was active.`;
    if (eaAway) eaAway.textContent = `${awayTimeStr} (${awayPctNew}%)`;
    if (eaLocked) eaLocked.textContent = `${lockedTimeStr} (${lockedPctNew}%)`;
    if (eaIdle) eaIdle.textContent = `${idleTimeStr} (${idlePct}%)`;
    const eaShiftLabel = document.getElementById('ea-shift-target-label');
    if (eaShiftLabel && st.shift_target_label) eaShiftLabel.textContent = '/ ' + st.shift_target_label;

    // ── Legacy hidden flip-card elements (backward-compat) ───────────────────
    // Available sub-card
    document.getElementById('fc-avail-pct').textContent = utilPct + '%';
    document.getElementById('fc-avail-time').textContent = formatTime(availSec);
    document.getElementById('fc-avail-sub').textContent =
        'Active ' + formatTime(activeSec) + ' / Idle ' + formatTime(idleSec);

    // Locked sub-card
    const lockedPct = coreWindowSec > 0 ? Math.round(lockedCh / coreWindowSec * 100) : 0;
    document.getElementById('fc-locked-pct').textContent = lockedPct + '%';
    document.getElementById('fc-locked-time').textContent = formatTime(lockedCh);

    // Away sub-card — always shown, greyed when 0
    const awayPct = coreWindowSec > 0 ? Math.round(awayCh / coreWindowSec * 100) : 0;
    document.getElementById('fc-away-pct').textContent = awayPct + '%';
    document.getElementById('fc-away-time').textContent = formatTime(awayCh);
    const awayFront = document.getElementById('fc-away-front');
    if (awayFront) awayFront.style.opacity = awayCh === 0 ? '0.45' : '1';

    // Wire flip on the single outer frame (idempotent)
    const frame = document.getElementById('availability-frame');
    if (frame) {
        const newFrame = frame.cloneNode(true);
        frame.parentNode.replaceChild(newFrame, frame);
        newFrame.addEventListener('click', () => newFrame.classList.toggle('flipped'));
    }

    // One combined timeline for all states
    _lastTimelineArgs = ['timeline-combined', stateEvents, ['active'], coreStart, coreEnd];
    renderTimeline(..._lastTimelineArgs);
}

// ─── T011: renderTimeline ─────────────────────────────────────────────────────
function renderTimeline(containerId, stateEvents, filterStates, coreStart, coreEnd) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';

    const DAY_SEC = 86400;
    const dark = document.documentElement.classList.contains('dark');

    const segments = (stateEvents || []).filter(e => filterStates.includes(e.state));
    if (segments.length === 0) {
        container.innerHTML = `<div style="text-align:center;padding:20px 0;font-size:12px;color:${dark ? '#6b7280' : '#9ca3af'};">No timeline data available</div>`;
        return;
    }

    const [csh] = coreStart.split(':').map(Number);
    const [ceh] = coreEnd.split(':').map(Number);
    const coreStartSec = csh * 3600;
    const coreEndSec = ceh * 3600;
    const coreLeft = (coreStartSec / DAY_SEC * 100).toFixed(3);
    const coreWidth = ((coreEndSec - coreStartSec) / DAY_SEC * 100).toFixed(3);

    function spanStartSec(isoStr) {
        const m = isoStr.match(/([+-])(\d{2}):(\d{2})$/);
        if (m) {
            const sign = m[1] === '+' ? 1 : -1;
            const offsetMs = sign * (parseInt(m[2]) * 3600 + parseInt(m[3]) * 60) * 1000;
            const local = new Date(new Date(isoStr).getTime() + offsetMs);
            return local.getUTCHours() * 3600 + local.getUTCMinutes() * 60 + local.getUTCSeconds();
        }
        const d = new Date(isoStr);
        return d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
    }

    function fmtWall(isoStr) {
        const m = isoStr.match(/([+-])(\d{2}):(\d{2})$/);
        if (m) {
            const sign = m[1] === '+' ? 1 : -1;
            const offMs = sign * (parseInt(m[2]) * 3600 + parseInt(m[3]) * 60) * 1000;
            const d = new Date(new Date(isoStr).getTime() + offMs);
            return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
        }
        const d = new Date(isoStr);
        return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }

    // ── Root ──────────────────────────────────────────────────────────────────
    const root = document.createElement('div');
    root.style.cssText = 'position:relative;padding-top:12px;padding-bottom:8px;';

    // ── Bar area ──────────────────────────────────────────────────────────────
    const barArea = document.createElement('div');
    barArea.style.cssText = 'position:relative;height:56px;width:100%;';

    // Bar background (offline = dark bg)
    const bar = document.createElement('div');
    bar.style.cssText = `position:absolute;inset:0;background:${dark ? '#030712' : '#f9fafb'};border-radius:6px;overflow:hidden;border:1px solid ${dark ? '#1f2937' : 'rgba(0,0,0,0.08)'};box-shadow:inset 0 1px 3px rgba(0,0,0,0.06);`;

    // Active segments (green)
    segments.forEach(ev => {
        const startSec = spanStartSec(ev.start_time);
        const dur = Math.min(ev.duration_seconds, DAY_SEC - startSec);
        if (dur <= 0) return;
        const left = (startSec / DAY_SEC * 100).toFixed(3);
        const width = Math.max(dur / DAY_SEC * 100, 0.2).toFixed(3);
        const seg = document.createElement('div');
        seg.style.cssText = `position:absolute;top:0;bottom:0;left:${left}%;width:${width}%;background:#10b981;transition:filter 0.15s;`;
        seg.onmouseenter = () => seg.style.filter = 'brightness(1.1)';
        seg.onmouseleave = () => seg.style.filter = '';
        seg.title = `ACTIVE  ${fmtWall(ev.start_time)} – ${fmtWall(ev.end_time)}  (${formatTime(ev.duration_seconds)})`;
        bar.appendChild(seg);
    });

    // Tick lines
    for (let h = 1; h < 24; h++) {
        const tick = document.createElement('div');
        const inCore = h >= csh && h <= ceh;
        tick.style.cssText = `position:absolute;top:0;bottom:0;left:${(h / 24 * 100).toFixed(3)}%;width:1px;background:${inCore ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)'};`;
        bar.appendChild(tick);
    }
    barArea.appendChild(bar);

    // Core hours border frame
    const frame = document.createElement('div');
    frame.style.cssText = `position:absolute;top:-3px;bottom:-3px;left:${coreLeft}%;width:${coreWidth}%;border:3px solid #6366f1;border-radius:8px;pointer-events:none;z-index:10;opacity:0.9;`;
    barArea.appendChild(frame);

    root.appendChild(barArea);

    // ── X-axis ────────────────────────────────────────────────────────────────
    const axis = document.createElement('div');
    axis.style.cssText = 'position:relative;height:28px;margin-top:8px;';

    for (let h = 0; h <= 24; h++) {
        const pos = (h / 24 * 100).toFixed(3);
        const inCore = h >= csh && h <= ceh;
        let transform = 'translateX(-50%)';
        if (h === 0) transform = 'translateX(0)';
        if (h === 24) transform = 'translateX(-100%)';

        const item = document.createElement('div');
        item.style.cssText = `position:absolute;left:${pos}%;top:0;transform:${transform};display:flex;flex-direction:column;align-items:center;`;

        const tickMark = document.createElement('div');
        tickMark.style.cssText = `width:1px;height:6px;margin-bottom:2px;background:${inCore ? (dark ? '#6366f1' : '#818cf8') : (dark ? '#374151' : '#d1d5db')};`;
        item.appendChild(tickMark);

        const num = document.createElement('span');
        num.style.cssText = `font-size:9px;font-family:monospace;line-height:1;color:${inCore ? (dark ? '#818cf8' : '#4f46e5') : (dark ? '#4b5563' : '#9ca3af')};font-weight:${inCore ? '700' : '400'};`;
        num.textContent = h === 24 ? '0' : String(h);
        item.appendChild(num);

        axis.appendChild(item);
    }
    root.appendChild(axis);

    // ── Legend footer ─────────────────────────────────────────────────────────
    const footer = document.createElement('div');
    footer.style.cssText = `display:flex;align-items:center;justify-content:space-between;margin-top:10px;padding-top:10px;border-top:1px solid ${dark ? '#1f2937' : '#f1f5f9'};flex-wrap:wrap;gap:6px;`;

    const legendLeft = document.createElement('div');
    legendLeft.style.cssText = 'display:flex;align-items:center;gap:20px;flex-wrap:wrap;';

    const textColor = dark ? '#9ca3af' : '#4b5563';
    legendLeft.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;font-size:11px;color:${textColor};font-weight:500;">
            <div style="width:12px;height:12px;border-radius:3px;background:#10b981;flex-shrink:0;"></div>Active
        </div>
        <div style="display:flex;align-items:center;gap:8px;font-size:11px;color:${textColor};font-weight:500;">
            <div style="width:12px;height:12px;border-radius:3px;background:${dark ? '#030712' : '#e5e7eb'};border:1px solid ${dark ? '#1f2937' : '#d1d5db'};flex-shrink:0;"></div>Offline
        </div>`;
    footer.appendChild(legendLeft);

    const corePill = document.createElement('div');
    corePill.style.cssText = `display:flex;align-items:center;gap:6px;background:${dark ? 'rgba(99,102,241,0.15)' : '#eef2ff'};color:${dark ? '#a5b4fc' : '#4338ca'};padding:4px 10px;border-radius:999px;font-size:11px;font-weight:600;letter-spacing:0.02em;white-space:nowrap;`;
    corePill.innerHTML = `<div style="width:12px;height:3px;background:${dark ? '#818cf8' : '#6366f1'};border-radius:2px;flex-shrink:0;"></div>Core ${coreStart}–${coreEnd}`;
    footer.appendChild(corePill);

    root.appendChild(footer);
    container.appendChild(root);
}
