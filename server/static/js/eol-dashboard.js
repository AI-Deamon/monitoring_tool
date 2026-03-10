/**
 * SentinelEdge EOL Dashboard - UI Logic
 * Handles risk charts, alert banners, and lifecycle reporting
 */

document.addEventListener('DOMContentLoaded', function () {
    // Only run if we are in the dashboard area
    if (window.location.pathname.includes('/dashboard')) {
        initEolAlerts();

        // Initialize charts if on overview page
        if (document.getElementById('eolRiskChart')) {
            initEolRiskChart();
        }
    }
});

/**
 * Global EOL Alerts Banner
 * Fetches fleet-wide summary and shows alert if there are critical EOL risks
 */
async function initEolAlerts() {
    try {
        const response = await fetch('/dashboard/api/lifecycle/fleet-summary');
        if (!response.ok) return;

        const data = await response.json();
        const banner = document.getElementById('global-eol-alert');
        const messageEl = document.getElementById('alert-message');

        if (data.eol_count > 0 && banner && messageEl) {
            messageEl.innerHTML = `<b>${data.eol_count}</b> products are currently End-of-Life. Upgrade recommended immediately.`;
            banner.classList.remove('hidden');
        }
    } catch (e) {
        console.warn('[EOL] Alert check failed:', e);
    }
}

/**
 * Fleet Lifecycle Risk Chart (Doughnut)
 */
async function initEolRiskChart() {
    try {
        const response = await fetch('/dashboard/api/lifecycle/fleet-summary');
        if (!response.ok) return;

        const data = await response.json();
        const ctx = document.getElementById('eolRiskChart').getContext('2d');

        // Match status names to colors
        const colors = {
            'EOL': '#dc3545',       // danger
            'Outdated': '#fd7e14',  // warning (orange)
            'Supported': '#22c55e', // success
            'Unknown': '#6c757d'    // secondary
        };

        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['EOL', 'Outdated', 'Supported', 'Unknown'],
                datasets: [{
                    data: [
                        data.eol_count || 0,
                        data.outdated_count || 0,
                        data.supported_count || 0,
                        data.unknown_count || 0
                    ],
                    backgroundColor: [colors['EOL'], colors['Outdated'], colors['Supported'], colors['Unknown']],
                    borderWidth: 0,
                    hoverOffset: 10
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '70%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 20,
                            usePointStyle: true,
                            font: { size: 12 }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const value = context.raw;
                                const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                return ` ${context.label}: ${value} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });

        // Update summary numbers if elements exist
        const eolCounter = document.getElementById('eol-counter');
        if (eolCounter) eolCounter.textContent = data.eol_count;

        const complianceCounter = document.getElementById('compliance-rate');
        if (complianceCounter) complianceCounter.textContent = data.compliance_rate + '%';

    } catch (e) {
        console.error('[EOL] Chart initialization failed:', e);
    }
}
