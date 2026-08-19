/**
 * Per-tab authentication binding — feature 037, D01 / FR-002a, FR-002i-l.
 *
 * QA reported that opening a second tab admitted an already-signed-in admin
 * without asking for credentials. That is how session cookies normally work —
 * they are shared by every tab in the browser — so honouring the requirement
 * means binding the session to something the tabs do NOT share.
 *
 * `sessionStorage` is the only per-tab web storage, and it gives three of the
 * four required behaviours for free:
 *
 *   FR-002i  survives a refresh and in-tab navigation  -> stays signed in
 *   FR-002j  destroyed when the tab closes             -> reopening needs sign-in
 *   FR-002a  not shared with other tabs                -> a new tab needs sign-in
 *   FR-002k  a link opened into a new tab gets a fresh, empty sessionStorage
 *
 * The token here is opaque and is NOT the authority. The server holds a
 * `tab_session` row and decides whether the token is still valid, which is what
 * makes this access control rather than a client-side flag — a browser can only
 * ever discard its own token, never mint a valid one.
 *
 * ── Accepted limitation: DUPLICATED tabs (FR-002l) ────────────────────────────
 *
 * Chrome and Firefox COPY sessionStorage into a tab created with "Duplicate
 * tab". Such a tab therefore starts holding a valid token and is
 * indistinguishable from its parent — same browser, same cookie, same token,
 * same everything the server can observe. No web platform primitive separates
 * them.
 *
 * Closing that hole requires claim detection: a per-tab in-memory nonce, with
 * the server revoking the session when it sees a second nonce against one
 * token — which signs out BOTH tabs. That was considered and deliberately
 * rejected during clarification: "duplicating a tab signs you out of both" is
 * disruptive for a rare action and would be reported as a defect in its own
 * right.
 *
 * So: duplicated tabs retain authentication, by decision. Please do not "fix"
 * this by adding claim detection without revisiting FR-002l first.
 */
(function (global) {
    'use strict';

    var STORAGE_KEY = 'sentinel_tab_token';
    var HEADER = 'X-Tab-Session';

    /** The token for THIS tab, or null when the tab has never been authenticated. */
    function token() {
        try {
            return global.sessionStorage.getItem(STORAGE_KEY);
        } catch (e) {
            // Private modes and hardened settings can deny storage access.
            // Failing closed is correct: no token means the server treats the
            // request as unauthenticated rather than trusting it.
            return null;
        }
    }

    function setToken(value) {
        try {
            if (value) {
                global.sessionStorage.setItem(STORAGE_KEY, value);
            } else {
                global.sessionStorage.removeItem(STORAGE_KEY);
            }
        } catch (e) { /* see token() */ }
    }

    function clear() {
        setToken(null);
    }

    /**
     * Attach the tab token to every same-origin request.
     *
     * Wrapping fetch means individual call sites cannot forget it. A call site
     * that forgets would be treated as an unauthenticated request, which fails
     * safe but looks like a random logout — the hardest kind of bug to trace.
     */
    function install() {
        if (!global.fetch || global.fetch.__tabSessionWrapped) return;

        var original = global.fetch.bind(global);
        var wrapped = function (input, init) {
            var current = token();
            if (!current) return original(input, init);

            init = init || {};
            var headers = new Headers(init.headers || (input && input.headers) || {});
            headers.set(HEADER, current);
            init.headers = headers;
            return original(input, init);
        };
        wrapped.__tabSessionWrapped = true;
        global.fetch = wrapped;

        // Forms post without fetch, so the token rides along as a hidden field.
        document.addEventListener('submit', function (event) {
            var form = event.target;
            if (!form || form.method === '' || form.method.toLowerCase() !== 'post') return;
            var current = token();
            if (!current) return;
            if (form.querySelector('input[name="tab_session"]')) return;
            var field = document.createElement('input');
            field.type = 'hidden';
            field.name = 'tab_session';
            field.value = current;
            form.appendChild(field);
        }, true);
    }

    install();

    global.TabSession = {
        HEADER: HEADER,
        STORAGE_KEY: STORAGE_KEY,
        token: token,
        setToken: setToken,
        clear: clear,
        install: install,
    };
})(window);
