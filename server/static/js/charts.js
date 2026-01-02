// Global Chart.js Configuration

if (window.Chart) {
    // Modern Typography
    Chart.defaults.font.family = "'Inter', -apple-system, system-ui, sans-serif";
    Chart.defaults.font.weight = '500';
    Chart.defaults.color = 'rgba(100, 116, 139, 0.8)';

    // New Brand Palette
    window.chartColors = {
        primary: '#6366f1',  // Indigo 500
        success: '#10b981',  // Emerald 500
        warning: '#f59e0b',  // Amber 500
        danger: '#ef4444',   // Red 500
        purple: '#8b5cf6',   // Violet 500
        accent: '#f43f5e',   // Rose 500
        gray: '#94a3b8'      // Slate 400
    };

    // Modern Tooltops
    Chart.defaults.plugins.tooltip.backgroundColor = '#0f172a';
    Chart.defaults.plugins.tooltip.padding = { x: 12, y: 10 };
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.plugins.tooltip.titleFont = { size: 13, weight: '700' };
    Chart.defaults.plugins.tooltip.usePointStyle = true;

    // Grid Configuration
    Chart.defaults.scale.grid.color = 'rgba(226, 232, 240, 0.5)';
    Chart.defaults.scale.ticks.backdropColor = 'transparent';

    // Responsive
    Chart.defaults.maintainAspectRatio = false;
}
