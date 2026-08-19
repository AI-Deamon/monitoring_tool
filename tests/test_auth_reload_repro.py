"""
Reproduction harness for the two reported authentication defects:

  Bug 1: user logs in successfully but is immediately logged out.
  Bug 2: user logs in successfully, reloads the page, and is logged out.

Both manifest on a browser NAVIGATION — a plain top-level GET that carries the
session cookie but NO X-Tab-Session header (browsers cannot attach custom
headers to navigations). The per-tab gate in login_required must fall back to
the token carried in the session cookie and keep the user signed in.

These tests drive the REAL app + DB through Flask's test client. They set up the
post-login cookie state directly (user_id + tab_token + a live tab_session row),
which is exactly what auth.login() produces, so we exercise login_required's
reload path without depending on CSRF/rate-limit plumbing.
"""
import uuid
from datetime import datetime, timezone

import pytest

from server_app import create_app
from extensions import db
from auth import DashboardUser, issue_tab_session, TabSession


@pytest.fixture()
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def local_user(app):
    """A fresh, active local user that is NOT under forced password rotation."""
    with app.app_context():
        uname = f"repro_{uuid.uuid4().hex[:8]}"
        u = DashboardUser(
            username=uname,
            role="user",
            auth_type="local",
            is_active=True,
            must_change_password=False,
            session_version=1,
        )
        u.set_password("Reproduce-Me-123!")
        db.session.add(u)
        db.session.commit()
        yield {"id": u.id, "username": u.username, "role": u.role,
               "session_version": u.session_version}
        # Cleanup
        TabSession.query.filter_by(user_id=u.id).delete()
        obj = DashboardUser.query.get(u.id)
        if obj:
            db.session.delete(obj)
        db.session.commit()


def _login_like_session(app, user):
    """Mint the exact server state auth.login() creates: a live tab_session row
    plus the cookie fields, and return the raw tab token."""
    with app.app_context():
        obj = DashboardUser.query.get(user["id"])
        raw = issue_tab_session(obj)
    return raw


def _establish_cookie(client, user, raw_tab_token):
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["username"] = user["username"]
        sess["role"] = user["role"]
        sess["session_version"] = user["session_version"]
        sess["tab_token"] = raw_tab_token
        sess["_permanent"] = True


def test_bug1_immediate_request_after_login_stays_authenticated(app, local_user):
    """First authenticated NAVIGATION after login (no X-Tab-Session header)."""
    raw = _login_like_session(app, local_user)
    client = app.test_client()
    _establish_cookie(client, local_user, raw)

    # A navigation-style GET (non-/api path -> redirects to login on failure).
    resp = client.get("/auth/change-password")
    assert resp.status_code == 200, (
        f"immediately logged out: expected 200, got {resp.status_code} "
        f"-> {resp.headers.get('Location')}"
    )


def test_bug2_reload_stays_authenticated(app, local_user):
    """Multiple reloads in a row, each a navigation with no tab header."""
    raw = _login_like_session(app, local_user)
    client = app.test_client()
    _establish_cookie(client, local_user, raw)

    for i in range(3):
        resp = client.get("/auth/change-password")
        assert resp.status_code == 200, (
            f"logged out on reload #{i+1}: got {resp.status_code} "
            f"-> {resp.headers.get('Location')}"
        )


def test_fetch_style_request_with_header_also_works(app, local_user):
    """A page fetch() carries the token in the header; must also authenticate."""
    raw = _login_like_session(app, local_user)
    client = app.test_client()
    _establish_cookie(client, local_user, raw)

    resp = client.get("/auth/api/me", headers={"X-Tab-Session": raw})
    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_unauthenticated_navigation_is_rejected(app):
    """Control: no session at all -> must be redirected to login, not 200."""
    app2 = app
    client = app2.test_client()
    resp = client.get("/auth/change-password")
    assert resp.status_code in (301, 302), resp.status_code
    assert "/auth/login" in resp.headers.get("Location", "")
