/**
 * SentinelEdge Theme Manager
 * Complete Dark/Light Mode Implementation with System Preference Detection
 * 
 * Features:
 * - localStorage persistence
 * - System preference detection (prefers-color-scheme)
 * - Smooth transitions between themes
 * - Chart color updates on theme change
 * - Event dispatch for other components
 */

const ThemeManager = {
    STORAGE_KEY: 'sentinel-theme',

    /**
     * Detect system color scheme preference
     * @returns {'dark' | 'light'} System preference
     */
    getSystemPreference() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    },

    /**
     * Get saved theme preference or fall back to system preference
     * @returns {'dark' | 'light'} Theme to use
     */
    getSavedPreference() {
        const saved = localStorage.getItem(this.STORAGE_KEY);
        if (saved === 'dark' || saved === 'light') {
            return saved;
        }
        return this.getSystemPreference();
    },

    /**
     * Get current theme
     * @returns {'dark' | 'light'} Current theme
     */
    getCurrentTheme() {
        return document.body.getAttribute('data-theme') || 'light';
    },

    /**
     * Apply theme to document
     * @param {'dark' | 'light'} theme Theme to apply
     */
    setTheme(theme) {
        // Apply to body
        document.body.setAttribute('data-theme', theme);

        // Save preference
        localStorage.setItem(this.STORAGE_KEY, theme);

        // Update toggle button UI
        this.updateToggleButton(theme);

        // Update Chart.js charts if they exist
        this.updateChartColors(theme);

        // Dispatch event for other components
        window.dispatchEvent(new CustomEvent('themechange', {
            detail: { theme, isDark: theme === 'dark' }
        }));

        console.log(`[Theme] Applied: ${theme}`);
    },

    /**
     * Toggle between dark and light mode
     */
    toggle() {
        const current = this.getCurrentTheme();
        const newTheme = current === 'dark' ? 'light' : 'dark';
        this.setTheme(newTheme);
    },

    /**
     * Update toggle button appearance
     * @param {'dark' | 'light'} theme Current theme
     */
    updateToggleButton(theme) {
        const toggleBtn = document.getElementById('theme-toggle');
        if (!toggleBtn) return;

        // Update icon visibility via data attribute
        toggleBtn.setAttribute('data-theme', theme);

        // Update tooltip
        toggleBtn.title = theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
    },

    /**
     * Update Chart.js chart colors when theme changes
     * @param {'dark' | 'light'} theme Current theme
     */
    updateChartColors(theme) {
        // Update all existing Chart.js instances
        if (typeof Chart !== 'undefined' && Chart.instances) {
            Object.values(Chart.instances).forEach(chart => {
                const isDark = theme === 'dark';

                // Update grid colors
                if (chart.options.scales) {
                    Object.values(chart.options.scales).forEach(scale => {
                        if (scale.grid) {
                            scale.grid.color = isDark ? 'rgba(148, 163, 184, 0.1)' : 'rgba(0, 0, 0, 0.05)';
                        }
                        if (scale.ticks) {
                            scale.ticks.color = isDark ? '#94a3b8' : '#64748b';
                        }
                    });
                }

                // Update legend colors
                if (chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
                    chart.options.plugins.legend.labels.color = isDark ? '#cbd5e1' : '#475569';
                }

                chart.update('none'); // Update without animation
            });
        }
    },

    /**
     * Initialize theme manager on page load
     */
    init() {
        // Apply saved/system preference immediately
        const theme = this.getSavedPreference();
        this.setTheme(theme);

        // Listen for system preference changes
        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                // Only auto-switch if user hasn't manually set a preference
                const savedPref = localStorage.getItem(this.STORAGE_KEY);
                if (!savedPref) {
                    this.setTheme(e.matches ? 'dark' : 'light');
                }
            });
        }

        // Attach toggle button click handler
        document.addEventListener('DOMContentLoaded', () => {
            const toggleBtn = document.getElementById('theme-toggle');
            if (toggleBtn) {
                toggleBtn.addEventListener('click', () => this.toggle());
            }
        });

        console.log('[Theme] Manager initialized');
    }
};

/**
 * Get theme-aware chart colors
 * @returns {Object} Color palette for charts
 */
function getChartColors() {
    const isDark = ThemeManager.getCurrentTheme() === 'dark';

    return isDark ? {
        // Brighter colors for dark mode
        primary: '#60A5FA',
        success: '#34D399',
        warning: '#FBBF24',
        danger: '#F87171',
        info: '#38BDF8',
        purple: '#A78BFA',
        pink: '#F472B6',
        gray: '#94A3B8',
        text: '#CBD5E1',
        textSecondary: '#94A3B8',
        grid: 'rgba(148, 163, 184, 0.1)',
        border: '#334155'
    } : {
        // Standard colors for light mode
        primary: '#3B82F6',
        success: '#10B981',
        warning: '#F59E0B',
        danger: '#EF4444',
        info: '#0EA5E9',
        purple: '#8B5CF6',
        pink: '#EC4899',
        gray: '#94A3B8',
        text: '#475569',
        textSecondary: '#64748B',
        grid: 'rgba(0, 0, 0, 0.05)',
        border: '#E2E8F0'
    };
}

/**
 * Get standard Chart.js options with theme-aware colors
 * @param {string} type Chart type ('doughnut', 'bar', 'line', etc.)
 * @returns {Object} Chart.js options object
 */
function getChartOptions(type = 'bar') {
    const colors = getChartColors();
    const isDark = ThemeManager.getCurrentTheme() === 'dark';

    const baseOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                position: 'bottom',
                labels: {
                    padding: 16,
                    usePointStyle: true,
                    color: colors.text,
                    font: {
                        size: 12,
                        family: "'Inter', sans-serif"
                    }
                }
            },
            tooltip: {
                backgroundColor: isDark ? 'rgba(30, 41, 59, 0.95)' : 'rgba(15, 23, 42, 0.95)',
                titleColor: '#ffffff',
                bodyColor: '#e2e8f0',
                titleFont: { size: 13, weight: '600' },
                bodyFont: { size: 12 },
                padding: 12,
                cornerRadius: 8,
                displayColors: true
            }
        },
        animation: {
            duration: 750,
            easing: 'easeOutQuart'
        }
    };

    // Add scales for bar/line charts
    if (type === 'bar' || type === 'line') {
        baseOptions.scales = {
            x: {
                grid: { color: colors.grid },
                ticks: { color: colors.textSecondary }
            },
            y: {
                grid: { color: colors.grid },
                ticks: { color: colors.textSecondary },
                beginAtZero: true
            }
        };
    }

    return baseOptions;
}

/**
 * Get chart color palette array
 * @param {number} count Number of colors needed
 * @returns {string[]} Array of colors
 */
function getChartPalette(count = 7) {
    const colors = getChartColors();
    const palette = [
        colors.primary,
        colors.success,
        colors.warning,
        colors.danger,
        colors.info,
        colors.purple,
        colors.pink
    ];

    // Extend palette if more colors needed
    while (palette.length < count) {
        palette.push(...palette);
    }

    return palette.slice(0, count);
}

// Initialize theme manager immediately (before DOM ready)
ThemeManager.init();

// Export for use in other scripts
window.ThemeManager = ThemeManager;
window.getChartColors = getChartColors;
window.getChartOptions = getChartOptions;
window.getChartPalette = getChartPalette;
