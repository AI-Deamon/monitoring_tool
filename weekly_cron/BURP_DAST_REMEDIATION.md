# Burp DAST Report — Remediation Summary

Source report: `weekly_cron/Burp dast reprot.html` (scan of `http://192.168.1.79:5050`).
Plan: `~/.claude/plans/monitoring-tool-weekly-cron-burp-dast-re-lively-puppy.md`.

## Status by finding

| # | Finding | Severity | Status | Where |
|---|---------|----------|--------|-------|
| 4 | Cross-site scripting (reflected) — `date`/`limit` | High | **Fixed** | `server_dashboard.py` `_parse_limit()`, safe date parse, generic error bodies |
| 12 | Input returned in response (reflected) | Info | **Fixed** | same as #4 |
| 8 | CORS `Access-Control-Allow-Origin: *` | Low/Med | **Fixed** | `server_app.py` `resolve_cors_origins()` — default empty, no `*` in prod |
| 9 | CORS: arbitrary origin trusted (+creds) | Med | **Fixed** | same — no arbitrary-origin reflection |
| 2 | Cleartext submission of password | Med | **Mitigated** (code) + **deploy** | Secure cookie + HSTS (`USE_TLS`), `FORCE_HTTPS` redirect. Requires TLS termination — see Deploy |
| 5 | CSP: allowlisted script resources (CDN) | Info | **Fixed** | CDN allowlist dropped; Tailwind/Chart/fonts vendored locally |
| 6 | CSP: allows untrusted script execution | Info | **Fixed** | nonce-based `script-src`, no `'unsafe-inline'` (confined to `script-src-attr`) |
| 7 | CSP: allows untrusted style execution | Info | **Fixed** | precompiled Tailwind (`static/css/tailwind.css`), nonce `style-src` |
| 3 | Open redirection (DOM-based) | Low | **Fixed** | `utils.js` `safeDateParam`/`safeAgentId`; sinks rebuilt in `selectors.js` + templates |
| 1 | Client-side desync (`/static/js/*`) | High (Tentative) | **Mitigated** (code) + **deploy** | `/static/` rejects non-GET (405). Full fix = HTTP/2 upstream (a `Connection: close` header is *not* usable — it is hop-by-hop and Waitress rejects it) |
| 10 | Cross-site request forgery | Low | **Fixed** | `SameSite=Strict` cookie (already) + `X-CSRF-Token` header accepted for JSON APIs |
| 11 | External service interaction (DNS) — 42 | High | **Investigated — no code fix needed** | see below |
| 13 | Email addresses disclosed | Info | **Accepted** | internal tool — admin emails are product data |
| 14 | Private IP addresses disclosed | Info | **Accepted** | internal `192.168.x` fleet tool |
| 15 | Base64-encoded data in parameter | Info | **Accepted (false positive)** | the flagged value is the app's own `csrf_token` |

## Finding #11 — External service interaction (DNS): investigation result

Burp reported 42 instances spanning nearly every endpoint (including `/static/` and
JSON APIs). Investigation found:

- **No request-fed outbound sink.** The only server-side outbound HTTP calls are
  `nvd_cache.py` and `eol_engine.py` (CVE/EOL lookups). Both build URLs from software
  **product names taken from agent inventory** during scheduled background syncs — not
  from any HTTP request parameter or header. They are not reachable per dashboard request.
- **No reverse DNS on client input.** No `gethostbyaddr`/`getaddrinfo`/`getfqdn` on a
  client IP or header anywhere in the request path.
- **No `Host`-header-derived page resources.** No template or view builds an absolute
  external URL from `request.host`/`host_url`/`url_root`.

Conclusion: the 42 uniform hits are a **scanner-side artifact** of the reflected-input
class (#4/#12), where Burp's headless browser resolves injected content while rendering.
That input reflection is now fixed, and the hardened CSP (`default-src 'self'`,
`connect-src 'self'`, `img-src 'self' data:`, nonce `script-src` with no wildcard) now
**blocks a browser from being coerced into an external fetch**. Residual risk: low. No
additional code change is warranted for #11.

## Bonus finding (not in the Burp report) — password-reset Host-header injection

`server/password_reset.py:137` builds the reset link with
`url_for('auth.reset_password', token=token, _external=True)`. With no `SERVER_NAME`
configured, the host is taken from the request `Host` header, so a poisoned `Host` can
produce a reset link pointing at an attacker domain. **Recommended follow-up:** set
`SERVER_NAME`/`PREFERRED_URL_SCHEME`, or build the reset URL from a configured base URL,
or validate `Host` against an allowlist. Low severity (requires triggering a reset).

## Deployment steps required to fully close #1 and #2

- **#2 Cleartext password:** terminate TLS in front of the app. Then set `USE_TLS=true`
  (activates `SESSION_COOKIE_SECURE` + HSTS) and `FORCE_HTTPS=true` (activates the 308
  redirect). Windows/Waitress and any plain-HTTP listener must sit behind HTTPS.
- **#1 Client-side desync:** enable **HTTP/2** at the TLS terminator / reverse proxy, or
  ensure it closes reused connections after POST. Gunicorn+mTLS (Linux) already terminates
  TLS; front Waitress (Windows) with an HTTP/2-capable reverse proxy.

## Tests

`monitoring_tool/tests/`: `test_xss_overview_params.py`, `test_cors_default.py`,
`test_security_headers.py`, `test_dom_redirect_sanitize.py` (Node), `test_csrf_json_header.py`,
`test_static_method_guard.py`. Run: `python -m unittest discover -s tests` from the
`monitoring_tool` root (or `pytest tests/ -v` where pytest is installed).
