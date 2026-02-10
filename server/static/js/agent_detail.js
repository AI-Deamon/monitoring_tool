let reportData = null;
const USERNAME = window.USERNAME || 'User';

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
                el.style.display = el.textContent.toLowerCase().includes(term) ? '' : 'none';
            });
        });
    }
    
    document.addEventListener('DOMContentLoaded', () => {
        setupSearch('app-search', 'apps-body', 'tr');
        setupSearch('domain-search', 'domains-body', 'tr');
        setupSearch('inventory-search', 'inventory-body', 'tr');
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
        return el ? el.value : new Date().toISOString().split('T')[0];
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
    async function loadFullReport() {
        const selectedDate = getSelectedDate();
        const data = await fetchJSON(`/dashboard/api/agent/${AGENT_ID}/full-report?date=${selectedDate}`);
        if (!data) return;
        reportData = data;

        // Update agent info
        if (data.agent) {
            if (data.agent.username) {
                document.getElementById('agent-title').innerHTML = `
                    <img src="${window.USER_ICON_URL}" class="w-8 h-8 mr-2 inline-block" />
                    ${data.agent.username}
                `;
            }
            document.getElementById('registered-at').textContent = data.agent.registered_at ? new Date(data.agent.registered_at).toLocaleDateString() : '-';
            document.getElementById('first-seen-today').textContent = data.agent.first_seen_today
                ? new Date(data.agent.first_seen_today).toLocaleTimeString('en-IN', {
               year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                })
                : 'No activity';
            document.getElementById('last-seen').textContent = data.agent.last_seen
                ? new Date(data.agent.last_seen).toLocaleString('en-IN', {
                 
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                })
                : 'No activity';
            
            // Update current state - show detailed state for admin users
            const stateEl = document.getElementById('current-state');
            const currentState = data.live_status?.current_state || (data.agent.is_online ? 'active' : 'offline');
            
            // Map states to display text and colors
            const stateConfig = {
                'active': { text: 'Active', class: 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200' },
                'idle': { text: 'Idle', class: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200' },
                'locked': { text: 'Locked', class: 'bg-orange-100 dark:bg-orange-900 text-orange-800 dark:text-orange-200' },
                'offline': { text: 'Offline', class: 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200' }
            };
            
            const config = stateConfig[currentState] || stateConfig['offline'];
            stateEl.textContent = config.text;
            stateEl.className = `inline-block px-2 py-1 ${config.class} text-xs font-medium rounded-full`;
        }

        // Live status
        if (data.live_status && data.live_status.current_app) {
            document.getElementById('live-status-banner').classList.remove('hidden');
            document.getElementById('live-app-name').textContent = data.live_status.current_app;
            document.getElementById('live-window-title').textContent = data.live_status.window_title || '';
            document.getElementById('live-duration').textContent = formatTime(data.live_status.duration_seconds || 0);
            document.getElementById('current-activity').textContent = data.live_status.current_app;
        } else {
            document.getElementById('live-status-banner').classList.add('hidden');
            document.getElementById('current-activity').innerHTML = '<span class="opacity-70">Offline</span>';
        }

        // Screen time
        const st = data.screen_time || {};
        const activeSeconds = st.active_seconds || 0;
        const idleSeconds = st.idle_seconds || 0;
        const lockedSeconds = st.locked_seconds || 0;
        const awaySeconds = st.away_seconds || 0;
        const totalTracked = activeSeconds + idleSeconds + lockedSeconds + awaySeconds;

        document.getElementById('active-time').textContent = formatTime(activeSeconds);
        document.getElementById('idle-time').textContent = formatTime(idleSeconds);
        document.getElementById('locked-time').textContent = formatTime(lockedSeconds);
        document.getElementById('away-time').textContent = formatTime(awaySeconds);
        document.getElementById('total-time').textContent = formatTime(totalTracked);

        if (totalTracked > 0) {
            document.getElementById('active-pct').textContent = Math.round((activeSeconds / totalTracked) * 100) + '%';
            document.getElementById('idle-pct').textContent = Math.round((idleSeconds / totalTracked) * 100) + '%';
            document.getElementById('locked-pct').textContent = Math.round((lockedSeconds / totalTracked) * 100) + '%';
            document.getElementById('away-pct').textContent = Math.round((awaySeconds / totalTracked) * 100) + '%';
        }

        // Update Quick Stats
        const totalScreenSeconds = activeSeconds + idleSeconds;
        document.getElementById('quick-screen-time').textContent = formatTime(totalScreenSeconds);
        document.getElementById('quick-apps-count').textContent = data.app_usage?.count || 0;
        document.getElementById('quick-domains-count').textContent = data.domain_usage?.count || 0;
        document.getElementById('quick-sessions-count').textContent = data.app_sessions?.count || 0;

        // Render tables
        renderAppUsage(data.app_usage, data.live_status);
        renderDomainUsage(data.domain_usage, data.live_status);
        renderDomainVisits(data.domain_visits);
        renderInventory(data.inventory);
        loadScreenTimeHistory();
    }

    function renderAppUsage(appData, liveStatus) {
        const tbody = document.getElementById('apps-body');
        tbody.innerHTML = '';
        document.getElementById('apps-count').textContent = `${appData?.count || 0} apps`;

        if (liveStatus?.current_app) {
            document.getElementById('app-ongoing-section').classList.remove('hidden');
            document.getElementById('ongoing-app-name').textContent = liveStatus.current_app;
            document.getElementById('ongoing-app-duration').textContent = formatTime(liveStatus.duration_seconds || 0);
        } else {
            document.getElementById('app-ongoing-section').classList.add('hidden');
        }

        if (!appData?.data?.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-gray-500">No data</td></tr>';
            return;
        }

        appData.data.forEach(app => {
            const pct = parseFloat(app.percentage) || 0;
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-50 dark:hover:bg-gray-700';
            tr.innerHTML = `
                <td class="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">${app.app}</td>
                <td class="px-4 py-3 text-right text-sm text-gray-600 dark:text-gray-300">${app.session_count || '-'}</td>
                <td class="px-4 py-3 text-right font-mono text-sm text-gray-900 dark:text-gray-100">${formatTime(app.duration_seconds)}</td>
                <td class="px-4 py-3 text-right">
                    <div class="flex items-center justify-end gap-2">
                        <div class="w-16 h-2 bg-gray-200 rounded-full overflow-hidden">
                            <div class="h-full bg-gradient-to-r from-blue-500 to-purple-600 rounded-full" style="width:${Math.min(pct, 100)}%"></div>
                        </div>
                        <span class="text-sm font-medium w-10 text-right">${app.percentage}%</span>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    function renderDomainUsage(domainData, liveStatus) {
        const tbody = document.getElementById('domains-body');
        tbody.innerHTML = '';
        document.getElementById('domains-count').textContent = `${domainData?.count || 0} domains`;

        if (liveStatus?.current_domain) {
            document.getElementById('domain-ongoing-section').classList.remove('hidden');
            document.getElementById('ongoing-domain-name').textContent = liveStatus.current_domain;
            document.getElementById('ongoing-domain-duration').textContent = formatTime(liveStatus.domain_duration || 0);
        } else {
            document.getElementById('domain-ongoing-section').classList.add('hidden');
        }

        if (!domainData?.data?.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-gray-500">No data</td></tr>';
            return;
        }

        const total = domainData.data.reduce((sum, d) => sum + (d.duration_seconds || 0), 0);
        domainData.data.forEach(d => {
            const pct = total > 0 ? ((d.duration_seconds || 0) / total * 100).toFixed(1) : 0;
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-50 dark:hover:bg-gray-700';
            tr.innerHTML = `
                <td class="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">${d.domain}</td>
                <td class="px-4 py-3 text-right text-sm text-gray-600 dark:text-gray-300">${d.session_count || '-'}</td>
                <td class="px-4 py-3 text-right font-mono text-sm text-gray-900 dark:text-gray-100">${formatTime(d.duration_seconds)}</td>
                <td class="px-4 py-3 text-right">
                    <div class="flex items-center justify-end gap-2">
                        <div class="w-16 h-2 bg-gray-200 rounded-full overflow-hidden">
                            <div class="h-full bg-gradient-to-r from-green-500 to-blue-500 rounded-full" style="width:${Math.min(pct, 100)}%"></div>
                        </div>
                        <span class="text-sm font-medium w-10 text-right">${pct}%</span>
                    </div>
                </td>
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

        visitsData.data.slice(0, 100).forEach(v => {
            const div = document.createElement('div');
            div.className = 'site-item flex items-center gap-4 p-3 border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700';
            div.innerHTML = `
<span class="text-xs text-gray-500 dark:text-gray-400 font-mono w-20">
  ${v.visited_at
    ? new Date(v.visited_at).toLocaleTimeString('en-IN', {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        minute: '2-digit'
      })
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
            tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-gray-500">No inventory data</td></tr>';
            return;
        }

        invData.data.forEach(app => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-50 dark:hover:bg-gray-700';
            tr.innerHTML = `
                <td class="px-3 py-2 font-medium text-sm break-words text-gray-900 dark:text-gray-100">${escapeHtml(app.name)}</td>
                <td class="px-3 py-2 text-xs text-gray-600 dark:text-gray-300 font-mono break-all">${escapeHtml(app.version || '-')}</td>
                <td class="px-3 py-2 text-xs break-words text-gray-900 dark:text-gray-100">${escapeHtml(cleanPublisher(app.publisher))}</td>
                <td class="px-3 py-2 text-xs text-gray-500 dark:text-gray-400 font-mono break-all">${app.install_location || '-'}</td>
          <td class="px-3 py-2 text-xs text-gray-900 dark:text-gray-100">
  ${
    app.install_date
      ? (() => {
          const d = new Date(app.install_date);
          const day = String(d.getDate()).padStart(2, '0');
          const month = String(d.getMonth() + 1).padStart(2, '0');
          const year = d.getFullYear();
          return `${day}-${month}-${year}`;
        })()
      : '-'
  }
</td>

                <td class="px-3 py-2 text-center">${getSourceBadge(app.source)}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function cleanPublisher(publisher) {
        if (!publisher || publisher === '-') return 'Unknown';
        const cnMatch = publisher.match(/CN=([^,]+)/);
        const oMatch = publisher.match(/O=([^,]+)/);
        if (cnMatch && cnMatch[1]) return cnMatch[1].trim();
        if (oMatch && oMatch[1]) return oMatch[1].trim();
        return publisher.length > 40 ? publisher.substring(0, 37) + '...' : publisher;
    }

    function cleanInstallLocation(location) {
        if (!location || location === '-') return '-';
        const parts = location.split('\\\\');
        if (parts.length > 4) return `${parts[0]}\\\\...\\\\${parts[parts.length - 1]}`;
        if (location.length > 40) return '...' + location.slice(-37);
        return location;
    }

    function formatInstallDate(dateStr) {
        if (!dateStr || dateStr === '-') return '-';
        try {
            const date = new Date(dateStr);
            if (isNaN(date.getTime())) return dateStr;
            return date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
        } catch {
            return dateStr;
        }
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function getSourceBadge(source) {
        if (!source) return '<span class="  px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 text-xs rounded-full">Unknown</span>';
        if (source.includes('HKLM')) return '<span  class="px-2 py-1 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 text-xs rounded-full">System</span>';
        if (source.includes('HKCU')) return '<span class="px-2 py-1 bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 text-xs rounded-full">User</span>';
        if (source.includes('Store')) return '<span class="px-2 py-1 bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 text-xs rounded-full">Store</span>';
        return `<span class="px-2  py-1 bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 text-xs rounded-full">${escapeHtml(source)}</span>`;
    }

    async function loadScreenTimeHistory() {
        const data = await fetchJSON(`/dashboard/api/agent/${AGENT_ID}/screentime`);
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
                    { label: 'Idle', data: data.idle, backgroundColor: '#f59e0b', stack: 'Stack 0', borderRadius: 4 },
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

    function exportTableToCSV(tableId, filename) {
        const table = document.getElementById(tableId);
        let csv = [];
        table.querySelectorAll('tr').forEach(row => {
            let cols = [];
            row.querySelectorAll('th, td').forEach(col => cols.push('"' + col.textContent.trim().replace(/"/g, '""') + '"'));
            csv.push(cols.join(','));
        });
        const blob = new Blob([csv.join('\\n')], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
    }

    // Initialize
    document.addEventListener('DOMContentLoaded', () => {
        loadFullReport();
    });

    const dateSelect = document.getElementById('global-date-select');
    if (dateSelect) dateSelect.addEventListener('change', loadFullReport);