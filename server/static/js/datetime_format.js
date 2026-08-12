/*
 * Shared date/time presentation for the dashboard (feature 037, US4/US5).
 *
 * Contract: specs/037-v4-qa-defect-fixes/contracts/datetime-format.md
 *
 *     dates      DD-MM-YYYY        07-08-2026
 *     date-times DD-MM-YYYY HH:mm  07-08-2026 14:30   (24-hour, zero-padded)
 *
 * Mirrors server/utils/datetime_format.py. The two must stay in step — a value
 * rendered server-side and the same value rendered client-side have to look
 * identical, or SC-004 ("zero deviating screens") cannot hold.
 *
 * ---------------------------------------------------------------------------
 * Why this file exists, and the two traps it closes
 * ---------------------------------------------------------------------------
 *
 * 1. `toLocaleDateString()` with no arguments follows the *browser's* locale.
 *    The same screen therefore rendered differently for different users, which
 *    is why several reported date defects could never be reproduced
 *    consistently. Never call it. Use DateFmt instead.
 *
 * 2. `new Date("2026-08-07T14:30:00")` — an ISO date-time with NO timezone
 *    offset — is parsed as *local* time by JavaScript. Our API serves naive UTC
 *    (server_telemetry.parse_agent_timestamp normalizes every timestamp to UTC
 *    on write, and .isoformat() emits no suffix). Passing those strings
 *    straight to `new Date()` silently shifts every timestamp by the viewer's
 *    UTC offset. parseStored() below appends the missing 'Z' so the value is
 *    read as the UTC it actually is.
 */
(function (global) {
    'use strict';

    var EMPTY_DISPLAY = '-';

    function pad(n) {
        return String(n).padStart(2, '0');
    }

    /** The viewer's IANA timezone, or null if it cannot be determined. */
    function viewerTimeZone() {
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
        } catch (e) {
            return null;
        }
    }

    /**
     * Parse a stored timestamp into a Date.
     *
     * Strings that carry no timezone designator are treated as UTC, because
     * that is how the server stores and serves them. Without this, every
     * timestamp is off by the viewer's offset — see trap 2 above.
     */
    function parseStored(value) {
        if (value === null || value === undefined || value === '') return null;
        if (value instanceof Date) return isNaN(value.getTime()) ? null : value;

        var text = String(value);
        // A date-time with no 'Z' and no ±HH:MM offset is naive UTC from us.
        if (/T\d{2}:\d{2}/.test(text) && !/(Z|[+-]\d{2}:?\d{2})$/.test(text)) {
            text += 'Z';
        }
        var parsed = new Date(text);
        return isNaN(parsed.getTime()) ? null : parsed;
    }

    /**
     * Break a Date into calendar parts in the target timezone.
     *
     * Uses Intl with an explicit timeZone rather than the Date's own getters,
     * which would silently use the runtime's local zone.
     */
    function partsIn(dateObj, tz) {
        var options = {
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
            hour12: false,
        };
        if (tz) options.timeZone = tz;

        var parts = {};
        try {
            new Intl.DateTimeFormat('en-GB', options)
                .formatToParts(dateObj)
                .forEach(function (p) { parts[p.type] = p.value; });
        } catch (e) {
            // Unknown zone: fall back to UTC rather than throwing. A formatting
            // helper must never be able to break a page.
            options.timeZone = 'UTC';
            new Intl.DateTimeFormat('en-GB', options)
                .formatToParts(dateObj)
                .forEach(function (p) { parts[p.type] = p.value; });
        }
        // 'en-GB' renders midnight as '24' in some engines; normalise it.
        if (parts.hour === '24') parts.hour = '00';
        return parts;
    }

    /** DD-MM-YYYY */
    function formatDate(value, tz) {
        var d = parseStored(value);
        if (!d) return EMPTY_DISPLAY;
        var p = partsIn(d, tz || viewerTimeZone());
        return pad(p.day) + '-' + pad(p.month) + '-' + p.year;
    }

    /** DD-MM-YYYY HH:mm, 24-hour */
    function formatDateTime(value, tz) {
        var d = parseStored(value);
        if (!d) return EMPTY_DISPLAY;
        var p = partsIn(d, tz || viewerTimeZone());
        return pad(p.day) + '-' + pad(p.month) + '-' + p.year +
               ' ' + pad(p.hour) + ':' + pad(p.minute);
    }

    /** The timezone actually in use, for labelling (FR-008). Never empty. */
    function timezoneLabel(tz) {
        return tz || viewerTimeZone() || 'UTC';
    }

    /** DD-MM-YYYY HH:mm (Zone) */
    function formatDateTimeLabelled(value, tz) {
        var text = formatDateTime(value, tz);
        if (text === EMPTY_DISPLAY) return text;
        return text + ' (' + timezoneLabel(tz) + ')';
    }

    /** Today's calendar date in the viewer's zone, as YYYY-MM-DD for date inputs. */
    function todayISO(tz) {
        var p = partsIn(new Date(), tz || viewerTimeZone());
        return p.year + '-' + pad(p.month) + '-' + pad(p.day);
    }

    /**
     * Publish the viewer's timezone to the server as a cookie (FR-011).
     *
     * Date FILTERING happens server-side, so the server has to know which
     * timezone "today" means — otherwise a selected date is resolved in one zone
     * and the timestamps beside it displayed in another, and they disagree about
     * which day a record belongs to. That disagreement is D04 in its subtler
     * form.
     *
     * A cookie rather than a query parameter so every request carries it
     * automatically, without each of the many fetch call sites having to
     * remember to append it. SameSite=Lax; no personal data — an IANA zone name.
     */
    function publishTimeZone() {
        try {
            var tz = viewerTimeZone();
            if (!tz) return;
            document.cookie = 'viewer_tz=' + encodeURIComponent(tz) +
                              ';path=/;max-age=31536000;SameSite=Lax';
        } catch (e) { /* never let a display concern break the page */ }
    }
    publishTimeZone();

    global.DateFmt = {
        publishTimeZone: publishTimeZone,
        EMPTY_DISPLAY: EMPTY_DISPLAY,
        viewerTimeZone: viewerTimeZone,
        parseStored: parseStored,
        formatDate: formatDate,
        formatDateTime: formatDateTime,
        formatDateTimeLabelled: formatDateTimeLabelled,
        timezoneLabel: timezoneLabel,
        todayISO: todayISO,
    };
})(window);
