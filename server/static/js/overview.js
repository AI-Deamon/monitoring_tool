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
        } else {
            try {
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
        } else {
            try {
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
                idleList.innerHTML = data.top_idle_agents.map((agent, index) => `
                    <li class="flex justify-between items-center py-2 border-b border-gray-200 dark:border-gray-600 last:border-b-0">
                        <span class="text-sm text-gray-900 dark:text-gray-100"><strong>${index + 1}.</strong> ${agent.hostname}</span>
                        <span class="font-mono text-sm text-warning-600 dark:text-warning-400">${formatTime(agent.idle_seconds)}</span>
                    </li>
                `).join('');
            } else {
                idleList.innerHTML = '<li class="text-gray-500 dark:text-gray-400 text-sm">No data</li>';
            }
        } else {
            console.warn('top-idle-list element not found');
        }

        // Render Top Active Agents
        const activeList = document.getElementById('top-active-list');
        if (activeList) {
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
        } else {
            console.warn('top-active-list element not found');
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

    // Refresh every 30s for more real-time data
    setInterval(() => {
        loadOverview();
    }, 30000);