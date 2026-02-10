  function getSelectedDate() {
        // Use global date selector from navbar
        const dateInput = document.getElementById('global-date-select');
        if (dateInput && dateInput.value) {
            return dateInput.value;
        }
        const params = new URLSearchParams(window.location.search);
        return params.get('date') || new Date().toISOString().split('T')[0];
    }

    // Initialize global date picker and attach listener
    document.addEventListener('DOMContentLoaded', () => {
        const dateInput = document.getElementById('global-date-select');
        if (dateInput) {
            const today = new Date().toISOString().split('T')[0];
            dateInput.value = getSelectedDate();
            dateInput.max = today;
            // Attach change listener for this page
            dateInput.addEventListener('change', () => {
                loadOverview();
            });
        }
    });

    async function loadOverview() {
        document.getElementById('refresh-indicator').classList.add('active');

        const selectedDate = getSelectedDate();
        const data = await fetchJSON(`/dashboard/api/overview?date=${selectedDate}`);

        document.getElementById('refresh-indicator').classList.remove('active');

        if (!data) return;

        // Update metrics
        document.getElementById('total-agents').textContent = data.total_agents;
        document.getElementById('active-agents').textContent = data.active_agents;
        document.getElementById('offline-agents').textContent = data.offline_agents;

        // Update Highlights
        document.getElementById('top-app-name').textContent = data.top_app.name;
        document.getElementById('top-app-duration').textContent = formatTime(data.top_app.duration);

        document.getElementById('top-domain-name').textContent = data.top_domain.name;
        document.getElementById('top-domain-duration').textContent = formatTime(data.top_domain.duration);

        // Update Top 5 Agents
        renderTop5Agents(data);

        // Update Last Updated
        document.getElementById('last-updated').textContent = "Last updated: " + new Date().toLocaleTimeString();

        // -- Charts --
        renderCharts(data);
    }

    function renderCharts(data) {
        // 1. Agent Status Pie Chart
        const ctxStatus = document.getElementById('agent-status-chart');
        if (window.statusChart) window.statusChart.destroy();

        window.statusChart = new Chart(ctxStatus, {
            type: 'doughnut',
            data: {
                labels: ['Online', 'Offline'],
                datasets: [{
                    data: [data.active_agents, data.offline_agents],
                    backgroundColor: ['#10b981', '#ef4444']
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true,
                            pointStyle: 'circle',
                            font: { size: 10 },
                            padding: 10
                        }
                    }
                }
            }
        });

        // 2. Screen Time Breakdown Chart
        const ctxScreen = document.getElementById('screentime-chart');
        if (window.screenChart) window.screenChart.destroy();

        const awayTime = data.screen_time.away || 0;
        window.screenChart = new Chart(ctxScreen, {
            type: 'doughnut',
            data: {
                labels: ['Active', 'Idle', 'Locked', 'Away'],
                datasets: [{
                    data: [data.screen_time.active, data.screen_time.idle, data.screen_time.locked, awayTime],
                    backgroundColor: ['#38bdf8', '#fbbf24', '#e6005c', '#334155']
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true,
                            pointStyle: 'circle',
                            font: { size: 10 },
                            padding: 10
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => ctx.label + ': ' + formatTime(ctx.parsed)
                        }
                    }
                }
            }
        });
    }

    function renderTop5Agents(data) {
        // Render Top Idle Agents
        const idleList = document.getElementById('top-idle-list');
        if (data.top_idle_agents && data.top_idle_agents.length > 0) {
            idleList.innerHTML = data.top_idle_agents.map((agent, index) => `
                <li class="flex justify-between items-center py-2 border-b border-gray-200 dark:border-gray-600 last:border-b-0">
                    <span class="text-sm text-gray-900 dark:text-gray-100"><strong>${index + 1}.</strong> ${agent.hostname}</span>
                    <span class="font-mono text-sm text-warning-600 dark:text-warning-400">${formatTime(agent.idle_seconds)}</span>
                </li>
            `).join('');
        } else {
            idleList.innerHTML = '<li class="text-gray-500 dark:text-gray-400 text-sm">No data</li>';
        }

        // Render Top Active Agents
        const activeList = document.getElementById('top-active-list');
        if (data.top_active_agents && data.top_active_agents.length > 0) {
            activeList.innerHTML = data.top_active_agents.map((agent, index) => `
                <li class="flex justify-between items-center py-2 border-b border-gray-200 dark:border-gray-600 last:border-b-0">
                    <span class="text-sm text-gray-900 dark:text-gray-100"><strong>${index + 1}.</strong> ${agent.hostname}</span>
                    <span class="font-mono text-sm text-success-600 dark:text-success-400">${formatTime(agent.active_seconds)}</span>
                </li>
            `).join('');
        } else {
            activeList.innerHTML = '<li class="text-gray-500 dark:text-gray-400 text-sm">No data</li>';
        }

        // Render Top Locked Agents
        const lockedList = document.getElementById('top-locked-list');
        if (data.top_locked_agents && data.top_locked_agents.length > 0) {
            lockedList.innerHTML = data.top_locked_agents.map((agent, index) => `
                <li class="flex justify-between items-center py-2 border-b border-gray-200 dark:border-gray-600 last:border-b-0">
                    <span class="text-sm text-gray-900 dark:text-gray-100"><strong>${index + 1}.</strong> ${agent.hostname}</span>
                    <span class="font-mono text-sm text-red-600 dark:text-red-400">${formatTime(agent.locked_seconds)}</span>
                </li>
            `).join('');
        } else {
            lockedList.innerHTML = '<li class="text-gray-500 dark:text-gray-400 text-sm">No data</li>';
        }
    }

    // Initial Load
    document.addEventListener('DOMContentLoaded', () => {
        loadOverview();
    });

    // Refresh every 30s for more real-time data
    setInterval(() => {
        loadOverview();
    }, 30000);