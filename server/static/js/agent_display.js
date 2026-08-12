/**
 * Shared agent identity display — feature 037, D21 / FR-026, FR-026a-d.
 *
 * QA reported agent names cut short in two places: the Top Performance
 * leaderboards (`hostname.substring(0, 8)`) and the Update History table
 * (`agent_id.slice(0, 8) + '...'`, with no name at all). Each screen had
 * invented its own truncation, which is why the same defect appeared twice and
 * would have appeared a third time on the next screen built.
 *
 * This is the single rule, mirroring the DateFmt helper introduced for the date
 * sweep. The rules it enforces:
 *
 *   FR-026   identify by human-readable name, falling back to the identifier
 *            when no name is recorded — never blank.
 *   FR-026a  truncate visually, but keep the full value retrievable.
 *   FR-026b  never render two different agents identically.
 *   FR-026c  reachable by keyboard and touch, not mouse hover alone.
 *   FR-026d  a long name must not distort the layout around it.
 *
 * Truncation is done in CSS (text-overflow: ellipsis) rather than by cutting the
 * string, so the full value stays in the DOM — available to screen readers,
 * copy/paste, and browser find — while the visible width stays bounded.
 */
(function (global) {
    'use strict';

    var EMPTY_LABEL = 'Unnamed agent';

    /**
     * Escape text destined for innerHTML.
     *
     * Hostnames come from the monitored endpoint, so they are attacker-influenced
     * data being interpolated into innerHTML by every caller. The previous
     * per-screen code did not escape at all.
     */
    function escapeHtml(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /** Short, stable form of an identifier, for use *beside* a name — never instead of one. */
    function shortId(agentId) {
        var id = String(agentId || '');
        return id.length > 8 ? id.slice(0, 8) : id;
    }

    /**
     * The human-readable name for an agent, with identifier fallback (FR-026).
     *
     * Accepts the several row shapes the dashboard endpoints return:
     * `hostname`, `agent_name`, or only `agent_id`.
     */
    function label(agent) {
        if (!agent) return EMPTY_LABEL;
        var name = agent.agent_name || agent.hostname || agent.name || '';
        name = String(name).trim();
        if (name) return name;
        var id = String(agent.agent_id || agent.id || '').trim();
        return id ? id : EMPTY_LABEL;
    }

    /**
     * The value shown when hovering, focusing, or reading the element.
     *
     * Carries both name and identifier, so two agents whose names truncate to
     * the same visible text remain distinguishable (FR-026b).
     */
    function fullLabel(agent) {
        if (!agent) return EMPTY_LABEL;
        var name = label(agent);
        var id = String((agent.agent_id || agent.id || '')).trim();
        if (id && id !== name) return name + ' (' + id + ')';
        return name;
    }

    /**
     * HTML for an agent name that truncates visually but stays fully retrievable.
     *
     * `title` gives the full value on hover; `tabindex="0"` makes the same value
     * reachable by keyboard and assistive technology, which a title alone is not
     * (FR-026c). `truncate` bounds the width so one long name cannot push a
     * table column out of alignment (FR-026d).
     */
    function nameHtml(agent, extraClasses) {
        var visible = escapeHtml(label(agent));
        var full = escapeHtml(fullLabel(agent));
        var cls = 'inline-block max-w-full truncate align-bottom' +
                  (extraClasses ? ' ' + extraClasses : '');
        return '<span class="' + cls + '" title="' + full + '" tabindex="0">' + visible + '</span>';
    }

    /**
     * Name plus identifier for wider surfaces such as the update history table,
     * where the identifier is genuinely useful alongside the name rather than a
     * replacement for it (FR-026).
     */
    function nameWithIdHtml(agent, extraClasses) {
        var id = String((agent && (agent.agent_id || agent.id)) || '').trim();
        var html = nameHtml(agent, extraClasses);
        if (!id) return html;
        return html +
            '<span class="block text-[10px] font-mono text-gray-500 dark:text-gray-400 truncate"' +
            ' title="' + escapeHtml(id) + '" tabindex="0">' + escapeHtml(id) + '</span>';
    }

    global.AgentFmt = {
        EMPTY_LABEL: EMPTY_LABEL,
        escapeHtml: escapeHtml,
        shortId: shortId,
        label: label,
        fullLabel: fullLabel,
        nameHtml: nameHtml,
        nameWithIdHtml: nameWithIdHtml,
    };
})(window);
