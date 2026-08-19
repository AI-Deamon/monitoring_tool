"""
Dashboard API routes must fail LOUDLY when a session lapses.

## The defect

`login_required` answered every unauthenticated request with
`redirect(url_for("auth.login"))` — a 302 to an HTML page — including requests
to `/dashboard/api/*` and `/api/v1/*`.

The dashboard's fetch handlers then did:

    const resp = await fetch('/dashboard/api/updates/set-target', {...});
    const data = await resp.json();          // <-- SyntaxError on HTML
    if (resp.ok) { alert(...) } else { alert(...) }

fetch() follows the 302 transparently, `.json()` throws on the login page's
HTML, and the rejection happens BEFORE either alert(). The user clicks
"Deploy All" and absolutely nothing happens — no error, no dialog, no log
entry server-side, because the request was answered 200 with a login page.

SESSION_IDLE_TIMEOUT is 30 minutes, so any Updates tab left open goes silently
dead. This is what made a 4.2.3 rollout impossible to trigger from the UI while
every server-side precondition was correct.

## The fix

`wants_json_response()` distinguishes an API caller from a browser navigation,
and the auth decorators return JSON 401/403 for those. Browser navigations must
still redirect — otherwise clicking a protected link shows raw JSON instead of
the login page.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SECRET_KEY", "z" * 40)

from flask import Flask  # noqa: E402

import auth  # noqa: E402


def _app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
    return app


class TestWantsJsonResponse:
    """Which callers get JSON rather than a redirect."""

    @pytest.mark.parametrize(
        "path",
        [
            "/dashboard/api/updates/set-target",
            "/dashboard/api/updates/retry",
            "/dashboard/api/updates/summary",
            "/api/v1/updates/policy",
            "/api/v1/updates/trigger-check",
        ],
    )
    def test_api_paths_want_json(self, path):
        app = _app()
        with app.test_request_context(path, method="POST"):
            assert auth.wants_json_response() is True

    @pytest.mark.parametrize(
        "path",
        ["/dashboard/updates", "/dashboard/", "/auth/login", "/dashboard/agents"],
    )
    def test_page_navigations_do_not_want_json(self, path):
        """A protected link must still land on the login page, not raw JSON."""
        app = _app()
        with app.test_request_context(path):
            assert auth.wants_json_response() is False

    def test_xhr_header_wants_json(self):
        app = _app()
        with app.test_request_context(
            "/dashboard/updates", headers={"X-Requested-With": "XMLHttpRequest"}
        ):
            assert auth.wants_json_response() is True

    def test_json_content_type_wants_json(self):
        app = _app()
        with app.test_request_context(
            "/dashboard/anything",
            method="POST",
            json={"target_version": "4.2.3"},
        ):
            assert auth.wants_json_response() is True

    def test_wildcard_accept_alone_does_not_want_json(self):
        """
        `Accept: */*` is the fetch default AND close to what browsers send.
        Treating it as a JSON preference would break ordinary navigation.
        """
        app = _app()
        with app.test_request_context("/dashboard/updates", headers={"Accept": "*/*"}):
            assert auth.wants_json_response() is False


class TestAuthFailureShape:
    """_auth_failure() returns JSON for API callers, a redirect otherwise."""

    def test_api_caller_gets_json_401_not_a_redirect(self):
        app = _app()
        with app.test_request_context("/dashboard/api/updates/set-target", method="POST"):
            resp, status = auth._auth_failure(
                "session_expired", "Your session has expired.", 401, "/auth/login"
            )
            assert status == 401, "an expired session must not be answered 200/302"
            payload = resp.get_json()
            assert payload["error"] == "session_expired"
            assert "expired" in payload["message"].lower()

    def test_api_caller_gets_json_403_for_admin_only(self):
        app = _app()
        with app.test_request_context("/dashboard/api/updates/retry", method="POST"):
            resp, status = auth._auth_failure(
                "admin_required", "Administrator access required.", 403, "/dashboard/"
            )
            assert status == 403
            assert resp.get_json()["error"] == "admin_required"

    def test_response_is_json_parseable(self):
        """
        The whole point: `await resp.json()` must succeed so the page can show
        the message instead of throwing SyntaxError on an HTML body.
        """
        app = _app()
        with app.test_request_context("/dashboard/api/updates/summary"):
            resp, _ = auth._auth_failure("x", "y", 401, "/auth/login")
            assert resp.mimetype == "application/json"
            assert resp.get_json() is not None

    def test_browser_navigation_still_redirects(self):
        app = _app()
        with app.test_request_context("/dashboard/updates"):
            resp = auth._auth_failure(
                "session_expired", "Your session has expired.", 401, "/auth/login"
            )
            # A redirect response, not a (body, status) tuple.
            assert not isinstance(resp, tuple)
            assert resp.status_code == 302
            assert resp.headers["Location"] == "/auth/login"
