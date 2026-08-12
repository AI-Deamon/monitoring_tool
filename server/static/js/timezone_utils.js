/**
 * SentinelEdge Dashboard - date/time display helpers.
 *
 * ---------------------------------------------------------------------------
 * Rewritten for feature 037 (FR-007, FR-008). Previously "IST Timezone
 * Utilities": every function here hardcoded Asia/Kolkata and appended a literal
 * " IST" suffix, and each used its own toLocaleString() options — a second,
 * competing date formatter alongside the rest of the dashboard.
 *
 * That is exactly the missing-abstraction problem behind six reported defects.
 * All of these functions now delegate to DateFmt (js/datetime_format.js), which
 * renders DD-MM-YYYY / DD-MM-YYYY HH:mm in the VIEWER's timezone.
 *
 * The function NAMES are deliberately unchanged, including their "IST" suffixes.
 * Renaming them would mean touching every call site in one change; keeping them
 * fixes every caller at once and can be renamed later as pure cleanup. The names
 * are now historical, not descriptive — none of these is IST-specific.
 *
 * Requires js/datetime_format.js to be loaded first (base.html does this).
 * ---------------------------------------------------------------------------
 */

/**
 * Parse a stored timestamp into a Date.
 * Naive strings are treated as UTC, matching how the API serves them.
 * Historical name; no longer converts to IST.
 */
function toIST(date) {
    return DateFmt.parseStored(date);
}

/** DD-MM-YYYY HH:mm in the viewer's timezone. */
function formatDateTimeIST(dateStr) {
    return DateFmt.formatDateTime(dateStr);
}

/** HH:mm in the viewer's timezone. */
function formatTimeIST(dateStr) {
    const text = DateFmt.formatDateTime(dateStr);
    return text === DateFmt.EMPTY_DISPLAY ? text : text.split(' ')[1];
}

/** DD-MM-YYYY in the viewer's timezone. */
function formatDateOnlyIST(dateStr) {
    return DateFmt.formatDate(dateStr);
}

/**
 * DD-MM-YYYY HH:mm with the timezone labelled (FR-008).
 * Historical name mentions seconds; the canonical format does not include them,
 * and no caller depended on second-level precision.
 */
function formatDateTimeISTWithSeconds(dateStr) {
    return DateFmt.formatDateTimeLabelled(dateStr);
}

/** Current time, DD-MM-YYYY HH:mm in the viewer's timezone. */
function getCurrentTimeIST() {
    return DateFmt.formatDateTime(new Date());
}

/**
 * DD-MM-YYYY. Historical name says "long" — it previously rendered a verbose
 * locale form, which is a second format competing with the canonical one.
 */
function formatDateLongIST(dateStr) {
    return DateFmt.formatDate(dateStr);
}

/**
 * Relative age ("5 minutes ago"), falling back to an absolute timestamp for
 * anything older than a week.
 */
function getRelativeTimeIST(dateStr) {
    if (!dateStr) return 'Never';

    const date = DateFmt.parseStored(dateStr);
    if (!date) return 'Never';

    const seconds = Math.floor((new Date() - date) / 1000);

    if (seconds < 0) return 'Just now';
    if (seconds < 60) return `${seconds} seconds ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)} days ago`;

    return DateFmt.formatDateTime(dateStr);
}

/* -------------------------------------------------------------------------
 * Duration helpers — NOT timezone related, unchanged.
 * ---------------------------------------------------------------------- */

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
