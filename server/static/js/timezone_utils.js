/**
 * SentinelEdge Dashboard - IST Timezone Utilities
 * All times are stored in UTC in the database
 * This utility converts UTC timestamps to IST for display
 */

// IST Offset: UTC + 5 hours 30 minutes
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

/**
 * Convert UTC date to IST
 * @param {string|Date} date - UTC date string or Date object
 * @returns {Date} IST Date object
 */
function toIST(date) {
    if (!date) return null;

    // If string, append 'Z' to treat as UTC
    if (typeof date === 'string') {
        if (!date.endsWith('Z') && !date.includes('+')) {
            date = date + 'Z';
        }
        date = new Date(date);
    }

    // Add IST offset
    return new Date(date.getTime() + IST_OFFSET_MS);
}

/**
 * Format datetime in IST - Full format
 * Example: "Dec 17, 2025, 10:30 AM IST"
 */
function formatDateTimeIST(dateStr) {
    if (!dateStr) return 'N/A';

    let ts = dateStr;
    if (typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+')) {
        ts = ts + 'Z';
    }

    const date = new Date(ts);
    const options = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
        timeZone: 'Asia/Kolkata'
    };

    return date.toLocaleString('en-IN', options) + ' IST';
}

/**
 * Format time only in IST
 * Example: "10:30 AM IST"
 */
function formatTimeIST(dateStr) {
    if (!dateStr) return 'N/A';

    let ts = dateStr;
    if (typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+')) {
        ts = ts + 'Z';
    }

    const date = new Date(ts);
    const options = {
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
        timeZone: 'Asia/Kolkata'
    };

    return date.toLocaleString('en-IN', options) + ' IST';
}

/**
 * Format date only in IST
 * Example: "Dec 17, 2025"
 */
function formatDateOnlyIST(dateStr) {
    if (!dateStr) return 'N/A';

    let ts = dateStr;
    if (typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+')) {
        ts = ts + 'Z';
    }

    const date = new Date(ts);
    const options = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        timeZone: 'Asia/Kolkata'
    };

    return date.toLocaleString('en-IN', options);
}

/**
 * Format datetime with seconds in IST
 * Example: "Dec 17, 2025, 10:30:15 AM IST"
 */
function formatDateTimeISTWithSeconds(dateStr) {
    if (!dateStr) return 'N/A';

    let ts = dateStr;
    if (typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+')) {
        ts = ts + 'Z';
    }

    const date = new Date(ts);
    const options = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
        timeZone: 'Asia/Kolkata'
    };

    return date.toLocaleString('en-IN', options) + ' IST';
}

/**
 * Get current time in IST
 * Example: "Dec 17, 2025, 10:30:15 AM IST"
 */
function getCurrentTimeIST() {
    const now = new Date();
    const options = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
        timeZone: 'Asia/Kolkata'
    };

    return now.toLocaleString('en-IN', options) + ' IST';
}

/**
 * Format long date in IST for reports
 * Example: "Monday, December 17, 2025"
 */
function formatDateLongIST(dateStr) {
    if (!dateStr) return 'N/A';

    const date = new Date(dateStr + 'T00:00:00Z');
    const options = {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        timeZone: 'Asia/Kolkata'
    };

    return date.toLocaleDateString('en-IN', options);
}

/**
 * Get relative time (e.g., "5 minutes ago")
 * Returns IST timestamp with relative time
 */
function getRelativeTimeIST(dateStr) {
    if (!dateStr) return 'Never';

    let ts = dateStr;
    if (typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+')) {
        ts = ts + 'Z';
    }

    const date = new Date(ts);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 0) return 'Just now';
    if (seconds < 60) return `${seconds} seconds ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)} days ago`;

    // For older dates, show full IST timestamp
    return formatDateTimeIST(dateStr);
}

/**
 * Helper for duration formatting (NOT timezone-related)
 * Shows seconds when time is under 1 minute
 */
function formatTime(seconds) {
    if (!seconds || seconds < 0) return '0s';

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m ${secs}s`;
    return `${secs}s`;
}

function formatTimeShort(seconds) {
    if (!seconds || seconds < 0) return '0s';

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m`;
    return `${secs}s`;
}

// Console log to confirm loading
console.log('🌏 IST Timezone Utilities loaded - All times in Asia/Kolkata (UTC+5:30)');
