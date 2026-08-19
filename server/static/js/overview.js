  // Time formatting utility
  function formatTime(seconds) {
      if (!seconds || seconds === 0) return '0m';
      const hours = Math.floor(seconds / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      if (hours > 0) {
          return `${hours}h ${minutes}m`;
      }
      return `${minutes}m`;
  }

  function getSelectedDate() {
        // Use global date selector from navbar
        const dateInput = document.getElementById('global-date-select');
        if (dateInput && dateInput.value) {
            return dateInput.value;
        }
        const params = new URLSearchParams(window.location.search);
        return params.get('date') || localDateStr();
    }

    // Initialize global date picker and attach listener
    document.addEventListener('DOMContentLoaded', () => {
        const dateInput = document.getElementById('global-date-select');
        if (dateInput) {
            const today = localDateStr();
            dateInput.value = getSelectedDate();
            dateInput.max = today;
            // Attach change listener for this page
            dateInput.addEventListener('change', () => {
                loadOverview();
            });
        }
    });

    async function loadOverview() {
        console.log('=== Loading Overview ===');
        document.getElementById('refresh-indicator').classList.add('active');

        const selectedDate = getSelectedDate();
        console.log('Selected date:', selectedDate);
        
        const data = await fetchJSON(`/dashboard/api/overview?date=${selectedDate}`);
        console.log('API Response:', data);

        document.getElementById('refresh-indicator').classList.remove('active');

        if (!data) {
            console.error('No data received from API');
            return;
        }

        // Update metrics
        document.getElementById('total-agents').textContent = data.total_agents;
        document.getElementById('active-agents').textContent = data.active_agents;
        document.getElementById('offline-agents').textContent = data.offline_agents;

        // Update Top 5 Agents (Top Performance cards)
        renderTop5Agents(data);

        // Update Last Updated
        // FR-007: canonical format via the shared formatter, not the browser locale.
        document.getElementById('last-updated').textContent =
            "Last updated: " + DateFmt.formatDateTime(new Date());

        // -- Charts --
        console.log('About to render charts...');
        renderCharts(data);
        console.log('Charts rendering completed');
    }

    function renderCharts(data) {
        console.log('Rendering charts with data:', data);
        
        // Check if Chart.js is loaded
        if (typeof Chart === 'undefined') {
            console.error('Chart.js is not loaded!');
            return;
        }

        // 1. Agent Status Pie Chart
        const ctxStatus = document.getElementById('agent-status-chart');
        if (!ctxStatus) {
            console.error('Canvas element agent-status-chart not found!');
        } else if (window.statusChart) {
            // Update in place — destroy()+recreate blanked the canvas for a
            // frame on every 30s auto-refresh, which read as a visible flicker.
            window.statusChart.data.datasets[0].data = [data.active_agents, data.offline_agents];
            window.statusChart.update();
        } else {
            try {
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
                                display: true,
                                position: 'bottom',
                                labels: {
                                    usePointStyle: true,
                                    pointStyle: 'circle',
                                    font: { size: 10 },
                                    padding: 8,
                                    boxWidth: 12,
                                    boxHeight: 12
                                }
                            }
                        },
                        layout: {
                            padding: {
                                bottom: 20
                            }
                        }
                    }
                });
                console.log('Agent status chart created successfully');
            } catch (error) {
                console.error('Error creating agent status chart:', error);
            }
        }

        // 2. Screen Time Breakdown Chart
        const ctxScreen = document.getElementById('screentime-chart');
        if (!ctxScreen) {
            console.error('Canvas element screentime-chart not found!');
        } else if (window.screenChart) {
            window.screenChart.data.datasets[0].data = [
                data.screen_time.active, data.screen_time.idle,
                data.screen_time.locked, data.screen_time.away || 0,
            ];
            window.screenChart.update();
        } else {
            try {
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
                                display: true,
                                position: 'bottom',
                                labels: {
                                    usePointStyle: true,
                                    pointStyle: 'circle',
                                    font: { size: 10 },
                                    padding: 8,
                                    boxWidth: 12,
                                    boxHeight: 12
                                }
                            },
                            tooltip: {
                                callbacks: {
                                    label: (ctx) => ctx.label + ': ' + formatTime(ctx.parsed)
                                }
                            }
                        },
                        layout: {
                            padding: {
                                bottom: 20
                            }
                        }
                    }
                });
                console.log('Screen time chart created successfully');
            } catch (error) {
                console.error('Error creating screen time chart:', error);
            }
        }
    }

    function renderTop5Agents(data) {
        // Render Top Idle Agents
        const idleList = document.getElementById('top-idle-list');
        if (idleList) {
            if (data.top_idle_agents && data.top_idle_agents.length > 0) {
                idleList.innerHTML = data.top_idle_agents.slice(0, 3).map((agent, index) => `
                    <li class="flex justify-between items-center gap-1 text-xs">
                        <span class="text-gray-900 dark:text-gray-100 min-w-0 flex-1 truncate"><strong>${index + 1}.</strong> ${AgentFmt.nameHtml(agent)}</span>
                        <span class="font-mono text-warning-600 dark:text-warning-400 text-[11px]">${formatTime(agent.idle_seconds)}</span>
                    </li>
                `).join('');
            } else {
                idleList.innerHTML = '<li class="text-gray-500 dark:text-gray-400 text-xs">No data</li>';
            }
        }

        // Render Top Active Agents
        const activeList = document.getElementById('top-active-list');
        if (activeList) {
            if (data.top_active_agents && data.top_active_agents.length > 0) {
                activeList.innerHTML = data.top_active_agents.slice(0, 3).map((agent, index) => `
                    <li class="flex justify-between items-center gap-1 text-xs">
                        <span class="text-gray-900 dark:text-gray-100 min-w-0 flex-1 truncate"><strong>${index + 1}.</strong> ${AgentFmt.nameHtml(agent)}</span>
                        <span class="font-mono text-success-600 dark:text-success-400 text-[11px]">${formatTime(agent.active_seconds)}</span>
                    </li>
                `).join('');
            } else {
                activeList.innerHTML = '<li class="text-gray-500 dark:text-gray-400 text-xs">No data</li>';
            }
        }

        // Render Top Locked Agents
        const lockedList = document.getElementById('top-locked-list');
        if (lockedList) {
            if (data.top_locked_agents && data.top_locked_agents.length > 0) {
                lockedList.innerHTML = data.top_locked_agents.slice(0, 3).map((agent, index) => `
                    <li class="flex justify-between items-center gap-1 text-xs">
                        <span class="text-gray-900 dark:text-gray-100 min-w-0 flex-1 truncate"><strong>${index + 1}.</strong> ${AgentFmt.nameHtml(agent)}</span>
                        <span class="font-mono text-gray-600 dark:text-gray-400 text-[11px]">${formatTime(agent.locked_seconds)}</span>
                    </li>
                `).join('');
            } else {
                lockedList.innerHTML = '<li class="text-gray-500 dark:text-gray-400 text-xs">No data</li>';
            }
        }
    }

    // Initial Load
    document.addEventListener('DOMContentLoaded', () => {
        console.log('=== DOM Content Loaded ===');
        
        // Check if Chart.js is loaded
        console.log('Chart.js available:', typeof Chart !== 'undefined');
        
        // Check if canvas elements exist
        const agentChart = document.getElementById('agent-status-chart');
        const screenChart = document.getElementById('screentime-chart');
        console.log('Agent status chart element:', agentChart ? 'Found' : 'NOT FOUND');
        console.log('Screen time chart element:', screenChart ? 'Found' : 'NOT FOUND');
        
        // Check if utils.js functions are available
        console.log('fetchJSON function available:', typeof fetchJSON !== 'undefined');
        
        loadOverview();
    });

    // Setup responsive chart handling for zoom and resize
    function setupResponsiveCharts() {
        const chartContainers = document.querySelectorAll('canvas[id$="-chart"]');
        
        if (chartContainers.length === 0) {
            console.log('No chart containers found for responsive setup');
            return;
        }

        // ResizeObserver to handle zoom and window resize
        const resizeObserver = new ResizeObserver(() => {
            // Throttle resize updates to prevent excessive redraws
            clearTimeout(window.chartResizeTimeout);
            window.chartResizeTimeout = setTimeout(() => {
                const charts = [window.statusChart, window.screenChart];
                charts.forEach(chart => {
                    if (chart && typeof chart.resize === 'function') {
                        try {
                            chart.resize();
                        } catch (e) {
                            console.warn('Error resizing chart:', e);
                        }
                    }
                });
            }, 100);
        });

        // Observe all chart parents (not the canvas itself)
        chartContainers.forEach(canvas => {
            const parent = canvas.parentElement;
            if (parent) {
                resizeObserver.observe(parent);
            }
        });

        // Also listen to window resize events
        window.addEventListener('resize', () => {
            clearTimeout(window.chartResizeTimeout);
            window.chartResizeTimeout = setTimeout(() => {
                const charts = [window.statusChart, window.screenChart];
                charts.forEach(chart => {
                    if (chart && typeof chart.resize === 'function') {
                        try {
                            chart.resize();
                        } catch (e) {
                            console.warn('Error resizing chart on window resize:', e);
                        }
                    }
                });
            }, 100);
        });

        console.log('Responsive chart handling initialized');
    }

    // Call setup after charts are rendered
    const originalLoadOverview = window.loadOverview;
    if (typeof originalLoadOverview === 'function') {
        window.loadOverview = function() {
            originalLoadOverview.call(this);
            setTimeout(() => setupResponsiveCharts(), 500);
        };
    }

    // Refresh every 30s for more real-time data
    setInterval(() => {
        loadOverview();
    }, 30000);