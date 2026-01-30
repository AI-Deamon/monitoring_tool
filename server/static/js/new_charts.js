/**
 * New Charts Module - Additional Chart Types for SentinelEdge Dashboard
 * Requires Chart.js 3.x
 */

// Chart color palette matching CSS variables
const CHART_COLORS = {
    primary: '#6366f1',
    primaryDark: '#4f46e5',
    primaryLight: '#818cf8',
    success: '#10b981',
    warning: '#f59e0b',
    danger: '#ef4444',
    info: '#0ea5e9',
    gray: '#6b7280',
    // Transparent variants
    primaryAlpha: 'rgba(99, 102, 241, 0.2)',
    successAlpha: 'rgba(16, 185, 129, 0.2)',
    warningAlpha: 'rgba(245, 158, 11, 0.2)',
    dangerAlpha: 'rgba(239, 68, 68, 0.2)',
    // Category colors for pie/treemap
    categories: {
        productivity: '#10b981',
        communication: '#6366f1',
        browsing: '#f59e0b',
        development: '#0ea5e9',
        other: '#6b7280'
    },
    // Heatmap gradient
    heatmap: {
        low: '#e0e7ff',
        medium: '#818cf8',
        high: '#4f46e5'
    }
};

/**
 * Initialize Productivity Gauge Chart (180-degree arc)
 * @param {string} canvasId - Canvas element ID
 * @param {number} score - Productivity score (0-100)
 * @param {number} target - Target threshold (default 70)
 */
function initProductivityGauge(canvasId, score, target = 70) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) {
        console.warn('[Charts] Canvas not found:', canvasId);
        return null;
    }

    // Determine color based on score vs target
    let scoreColor = CHART_COLORS.danger;
    if (score >= target) scoreColor = CHART_COLORS.success;
    else if (score >= target * 0.8) scoreColor = CHART_COLORS.warning;

    // Destroy existing chart if any
    if (window[`${canvasId}Chart`]) {
        window[`${canvasId}Chart`].destroy();
    }

    const chart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Productivity', 'Remaining'],
            datasets: [{
                data: [score, 100 - score],
                backgroundColor: [scoreColor, '#e5e7eb'],
                borderWidth: 0,
                circumference: 180,
                rotation: 270
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '75%',
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false }
            }
        }
    });

    // Store reference for cleanup
    window[`${canvasId}Chart`] = chart;

    // Update center text
    const parentContainer = ctx.parentElement;
    let valueEl = parentContainer.querySelector('.gauge-value');
    if (!valueEl) {
        valueEl = document.createElement('div');
        valueEl.className = 'gauge-value';
        parentContainer.appendChild(valueEl);
    }
    valueEl.textContent = `${Math.round(score)}%`;
    valueEl.style.color = scoreColor;

    return chart;
}

/**
 * Initialize Category Breakdown Donut Chart
 * @param {string} canvasId - Canvas element ID
 * @param {Object} data - Category data {productivity: 480, communication: 120, ...}
 */
function initCategoryBreakdown(canvasId, data) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) {
        console.warn('[Charts] Canvas not found:', canvasId);
        return null;
    }

    const labels = Object.keys(data);
    const values = Object.values(data);
    const colors = labels.map(l => CHART_COLORS.categories[l.toLowerCase()] || CHART_COLORS.gray);

    // Destroy existing chart if any
    if (window[`${canvasId}Chart`]) {
        window[`${canvasId}Chart`].destroy();
    }

    const chart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels.map(l => l.charAt(0).toUpperCase() + l.slice(1)),
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderWidth: 0,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        padding: 12,
                        usePointStyle: true,
                        pointStyle: 'circle',
                        font: { size: 11 }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const value = ctx.raw;
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                            return `${ctx.label}: ${formatDuration(value)} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });

    window[`${canvasId}Chart`] = chart;
    return chart;
}

/**
 * Initialize Idle Time Analysis Stacked Area Chart
 * @param {string} canvasId - Canvas element ID
 * @param {Object} data - {labels: ['00:00', ...], active: [...], idle: [...], locked: [...]}
 */
function initIdleTimeAnalysis(canvasId, data) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) {
        console.warn('[Charts] Canvas not found:', canvasId);
        return null;
    }

    // Destroy existing chart if any
    if (window[`${canvasId}Chart`]) {
        window[`${canvasId}Chart`].destroy();
    }

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: 'Active',
                    data: data.active,
                    fill: true,
                    backgroundColor: CHART_COLORS.successAlpha,
                    borderColor: CHART_COLORS.success,
                    borderWidth: 2,
                    tension: 0.4,
                    pointRadius: 0
                },
                {
                    label: 'Idle',
                    data: data.idle,
                    fill: true,
                    backgroundColor: CHART_COLORS.warningAlpha,
                    borderColor: CHART_COLORS.warning,
                    borderWidth: 2,
                    tension: 0.4,
                    pointRadius: 0
                },
                {
                    label: 'Locked',
                    data: data.locked,
                    fill: true,
                    backgroundColor: CHART_COLORS.dangerAlpha,
                    borderColor: CHART_COLORS.danger,
                    borderWidth: 2,
                    tension: 0.4,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        padding: 10,
                        font: { size: 11 }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${formatDuration(ctx.raw)}`
                    }
                }
            },
            scales: {
                y: {
                    stacked: true,
                    beginAtZero: true,
                    title: { display: false },
                    ticks: {
                        font: { size: 10 },
                        callback: (val) => formatDurationShort(val)
                    }
                },
                x: {
                    ticks: {
                        font: { size: 10 },
                        maxTicksLimit: 12
                    }
                }
            }
        }
    });

    window[`${canvasId}Chart`] = chart;
    return chart;
}

/**
 * Initialize Activity Heatmap (Canvas-based)
 * @param {string} canvasId - Canvas element ID
 * @param {Object} data - {data: [[...], ...] (7 rows × 24 cols), maxValue: 150}
 */
function initActivityHeatmap(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) {
        console.warn('[Charts] Canvas not found:', canvasId);
        return null;
    }

    const ctx = canvas.getContext('2d');
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const hours = 24;

    // Get container dimensions
    const container = canvas.parentElement;
    const containerRect = container.getBoundingClientRect();
    
    // Set canvas size
    canvas.width = containerRect.width;
    canvas.height = containerRect.height;

    const marginLeft = 40;
    const marginTop = 20;
    const marginRight = 10;
    const marginBottom = 25;

    const availableWidth = canvas.width - marginLeft - marginRight;
    const availableHeight = canvas.height - marginTop - marginBottom;

    const cellWidth = availableWidth / hours;
    const cellHeight = availableHeight / 7;

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw cells
    if (data.data && data.data.length > 0) {
        const maxValue = data.maxValue || 1;

        data.data.forEach((row, dayIndex) => {
            row.forEach((value, hourIndex) => {
                const intensity = Math.min(value / maxValue, 1);
                ctx.fillStyle = interpolateHeatmapColor(intensity);
                ctx.fillRect(
                    marginLeft + hourIndex * cellWidth,
                    marginTop + dayIndex * cellHeight,
                    cellWidth - 1,
                    cellHeight - 1
                );
            });
        });
    }

    // Draw day labels
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || '#6b7280';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'right';
    days.forEach((day, i) => {
        const y = marginTop + i * cellHeight + cellHeight / 2 + 4;
        ctx.fillText(day, marginLeft - 5, y);
    });

    // Draw hour labels
    ctx.textAlign = 'center';
    for (let h = 0; h < hours; h += 3) {
        const x = marginLeft + h * cellWidth + cellWidth / 2;
        ctx.fillText(`${h}:00`, x, canvas.height - 5);
    }

    return { canvas, ctx };
}

/**
 * Interpolate heatmap color based on intensity (0-1)
 */
function interpolateHeatmapColor(intensity) {
    // Get CSS variables or use defaults
    const low = '#e0e7ff';
    const medium = '#818cf8';
    const high = '#4f46e5';

    if (intensity <= 0.5) {
        return lerpColor(low, medium, intensity * 2);
    } else {
        return lerpColor(medium, high, (intensity - 0.5) * 2);
    }
}

/**
 * Linear interpolation between two hex colors
 */
function lerpColor(color1, color2, factor) {
    const hex = (c) => parseInt(c, 16);
    const r1 = hex(color1.slice(1, 3));
    const g1 = hex(color1.slice(3, 5));
    const b1 = hex(color1.slice(5, 7));
    const r2 = hex(color2.slice(1, 3));
    const g2 = hex(color2.slice(3, 5));
    const b2 = hex(color2.slice(5, 7));

    const r = Math.round(r1 + (r2 - r1) * factor);
    const g = Math.round(g1 + (g2 - g1) * factor);
    const b = Math.round(b1 + (b2 - b1) * factor);

    return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Format duration in seconds to human-readable string
 */
function formatDuration(seconds) {
    if (!seconds || seconds < 0) return '0m';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

/**
 * Format duration as short string (for axis labels)
 */
function formatDurationShort(seconds) {
    if (!seconds || seconds < 0) return '0';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h`;
    return `${m}m`;
}

/**
 * Fetch and render productivity gauge
 * @param {string} canvasId - Canvas element ID
 */
async function loadProductivityGauge(canvasId) {
    try {
        const response = await fetchJSON('/dashboard/api/overview/productivity-score');
        if (!response) return;

        initProductivityGauge(canvasId, response.score || 0, response.target || 70);
    } catch (error) {
        console.error('[Charts] Failed to load productivity gauge:', error);
    }
}

/**
 * Fetch and render category breakdown
 * @param {string} canvasId - Canvas element ID
 */
async function loadCategoryBreakdown(canvasId) {
    try {
        const response = await fetchJSON('/dashboard/api/overview/category-breakdown');
        if (!response) return;

        initCategoryBreakdown(canvasId, response);
    } catch (error) {
        console.error('[Charts] Failed to load category breakdown:', error);
    }
}

/**
 * Fetch and render idle time analysis
 * @param {string} canvasId - Canvas element ID
 * @param {string} date - Date in YYYY-MM-DD format
 */
async function loadIdleTimeAnalysis(canvasId, date) {
    try {
        const response = await fetchJSON(`/dashboard/api/overview/idle-analysis?date=${date}`);
        if (!response) return;

        initIdleTimeAnalysis(canvasId, response);
    } catch (error) {
        console.error('[Charts] Failed to load idle time analysis:', error);
    }
}

/**
 * Fetch and render activity heatmap
 * @param {string} canvasId - Canvas element ID
 */
async function loadActivityHeatmap(canvasId) {
    try {
        const response = await fetchJSON('/dashboard/api/overview/activity-heatmap?days=7');
        if (!response) return;

        initActivityHeatmap(canvasId, response);
    } catch (error) {
        console.error('[Charts] Failed to load activity heatmap:', error);
    }
}

// Expose functions globally
window.initProductivityGauge = initProductivityGauge;
window.initCategoryBreakdown = initCategoryBreakdown;
window.initIdleTimeAnalysis = initIdleTimeAnalysis;
window.initActivityHeatmap = initActivityHeatmap;
window.loadProductivityGauge = loadProductivityGauge;
window.loadCategoryBreakdown = loadCategoryBreakdown;
window.loadIdleTimeAnalysis = loadIdleTimeAnalysis;
window.loadActivityHeatmap = loadActivityHeatmap;
window.CHART_COLORS = CHART_COLORS;
