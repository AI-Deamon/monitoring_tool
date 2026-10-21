/**
 * SentinelEdge Theme Manager
 * Single source of truth for dark/light mode toggling, state persistence,
 * system preference detection, and Chart.js theme synchronization.
 *
 * Design Strategy:
 * - Single localStorage key: 'sentinel-theme' (with fallback read for legacy 'theme')
 * - Primary class strategy: .dark on document.documentElement (aligned with Tailwind)
 * - Co-set data-theme="dark"|"light" on document.documentElement for backward compatibility
 * - Automatic Chart.js grid, tick, and legend color updates
 * - Broadcasts 'themechange' CustomEvent for dashboard components
 */

const ThemeManager = {
    STORAGE_KEY: 'sentinel-theme',
    LEGACY_KEY: 'theme',

    /**
     * Detect system color scheme preference
     * @returns {'dark' | 'light'} System preference
     */
    getSystemPreference() {
        if (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    },

    /**
     * Get saved theme preference or fall back to system preference
     * @returns {'dark' | 'light'} Theme to use
     */
    getSavedPreference() {
        try {
            const saved = localStorage.getItem(this.STORAGE_KEY) || localStorage.getItem(this.LEGACY_KEY);
            if (saved === 'dark' || saved === 'light') {
                return saved;
            }
        } catch (e) {
            console.warn('[ThemeManager] Could not access localStorage', e);
        }
        return this.getSystemPreference();
    },

    /**
     * Get current theme from the root element
     * @returns {'dark' | 'light'} Current theme
     */
    getCurrentTheme() {
        if (typeof document === 'undefined') return 'light';
        return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    },

    /**
     * Apply theme to document
     * @param {'dark' | 'light'} theme Theme to apply
     */
    setTheme(theme) {
        if (typeof document === 'undefined') return;
        const isDark = theme === 'dark';
        const root = document.documentElement;

        // Apply .dark class to root (Tailwind & CSS tokens standard)
        if (isDark) {
            root.classList.add('dark');
            root.setAttribute('data-theme', 'dark');
        } else {
            root.classList.remove('dark');
            root.setAttribute('data-theme', 'light');
        }

        // Clean up any legacy body attribute to avoid conflicting selectors
        if (document.body) {
            document.body.removeAttribute('data-theme');
            document.body.classList.remove('dark');
        }

        // Save preference to unified localStorage key
        try {
            localStorage.setItem(this.STORAGE_KEY, theme);
        } catch (e) {
            console.warn('[ThemeManager] Could not save to localStorage', e);
        }

        // Update toggle button UI
        this.updateToggleButton(theme);

        // Update Chart.js charts if they exist
        this.updateChartColors(theme);

        // Dispatch event for other components
        if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('themechange', {
                detail: { theme, isDark }
            }));
        }

        console.log(`[Theme] Applied: ${theme}`);
    },

    /**
     * Toggle between dark and light mode
     * @returns {'dark' | 'light'} The newly applied theme
     */
    toggle() {
        const current = this.getCurrentTheme();
        const newTheme = current === 'dark' ? 'light' : 'dark';
        this.setTheme(newTheme);
        return newTheme;
    },

    /**
     * Update toggle button appearance
     * @param {'dark' | 'light'} theme Current theme
     */
    updateToggleButton(theme) {
        if (typeof document === 'undefined') return;
        const toggleBtn = document.getElementById('theme-toggle');
        if (!toggleBtn) return;

        const isDark = theme === 'dark';
        const label = isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode';
        toggleBtn.setAttribute('data-theme', theme);
        toggleBtn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
        toggleBtn.setAttribute('title', label);
        toggleBtn.setAttribute('aria-label', label);
    },

    /**
     * Update Chart.js chart colors when theme changes
     * @param {'dark' | 'light'} theme Current theme
     */
    updateChartColors(theme) {
        if (typeof Chart !== 'undefined' && Chart.instances) {
            const isDark = theme === 'dark';
            Object.values(Chart.instances).forEach(chart => {
                if (!chart || !chart.options) return;

                // Update grid and tick colors
                if (chart.options.scales) {
                    Object.values(chart.options.scales).forEach(scale => {
                        if (scale.grid) {
                            scale.grid.color = isDark ? 'rgba(148, 163, 184, 0.1)' : 'rgba(0, 0, 0, 0.05)';
                        }
                        if (scale.ticks) {
                            scale.ticks.color = isDark ? '#94a3b8' : '#64748b';
                            if (scale.ticks.font) {
                                scale.ticks.font.family = "'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
                            }
                        }
                    });
                }

                // Update legend colors
                if (chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
                    chart.options.plugins.legend.labels.color = isDark ? '#cbd5e1' : '#475569';
                    if (chart.options.plugins.legend.labels.font) {
                        chart.options.plugins.legend.labels.font.family = "'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
                    }
                }

                chart.update('none'); // Update without animation
            });
        }
    },

    /**
     * Initialize theme manager
     */
    init() {
        // Apply saved/system preference immediately
        const theme = this.getSavedPreference();
        this.setTheme(theme);

        // Listen for system preference changes (only auto-switch if no manual saved preference)
        if (typeof window !== 'undefined' && window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                try {
                    const savedPref = localStorage.getItem(this.STORAGE_KEY) || localStorage.getItem(this.LEGACY_KEY);
                    if (!savedPref) {
                        this.setTheme(e.matches ? 'dark' : 'light');
                    }
                } catch (err) {}
            });
        }

        // Attach toggle button click handler
        const attachHandler = () => {
            const toggleBtn = document.getElementById('theme-toggle');
            if (toggleBtn && !toggleBtn._themeBound) {
                toggleBtn._themeBound = true;
                toggleBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    this.toggle();
                });
                this.updateToggleButton(this.getCurrentTheme());
            }
        };

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', attachHandler);
        } else {
            attachHandler();
        }

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
                        family: "'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
                    }
                }
            },
            tooltip: {
                backgroundColor: isDark ? 'rgba(30, 41, 59, 0.95)' : 'rgba(15, 23, 42, 0.95)',
                titleColor: '#ffffff',
                bodyColor: '#e2e8f0',
                titleFont: { size: 13, weight: '600', family: "'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" },
                bodyFont: { size: 12, family: "'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" },
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
                ticks: {
                    color: colors.textSecondary,
                    font: {
                        size: 11,
                        family: "'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
                    }
                }
            },
            y: {
                grid: { color: colors.grid },
                ticks: {
                    color: colors.textSecondary,
                    font: {
                        size: 11,
                        family: "'Space Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
                    }
                },
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

/**
 * Get CVD-accessible category colors for app usage
 * @returns {Object} Category colors for current theme
 */
function getCategoryColors() {
    const isDark = ThemeManager.getCurrentTheme() === 'dark';
    return isDark ? {
        productivity: '#3987e5',
        communication: '#10b981',
        browsing: '#f472b6',
        development: '#fbbf24',
        other: '#94a3b8'
    } : {
        productivity: '#2a78d6',
        communication: '#008300',
        browsing: '#e87ba4',
        development: '#eda100',
        other: '#94a3af'
    };
}

// Initialize theme manager immediately
ThemeManager.init();
ThemeManager.getCategoryColors = getCategoryColors;

// Export globals
window.ThemeManager = ThemeManager;
window.initTheme = () => ThemeManager.init();
window.toggleTheme = () => ThemeManager.toggle();
window.getChartColors = getChartColors;
window.getChartOptions = getChartOptions;
window.getChartPalette = getChartPalette;
window.getCategoryColors = getCategoryColors;

