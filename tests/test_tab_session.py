"""
T085, T088, T097 / D01 / FR-001, FR-002, FR-002a, FR-002i–l — per-tab authentication.

QA repro: sign in as admin in one tab, then try to sign in as the same admin in
another tab. The second tab was admitted with no credentials.

Clarified 2026-08-07 to the literal reading: a browser tab must not inherit
authentication from another tab. That is deliberately stricter than normal web
behaviour, where a session cookie is shared across every tab, so it cannot be
done with a cookie alone — the session is bound to per-tab storage with a
server-side registry deciding validity.

Tab lifecycle required (contracts/session-auth.md):

    sign in            -> that tab authenticated, no other
    refresh / navigate -> stays signed in            (FR-002i)
    new tab / link     -> requires its own sign-in   (FR-002a, FR-002k)
    close tab          -> that tab's auth ends       (FR-002j)
    sign out any tab   -> ALL of that user's tabs end (scenario 1a)
    duplicate tab      -> retains auth, ACCEPTED     (FR-002l)

FR-002l is a deliberate carve-out, not an oversight: Chrome and Firefox copy
sessionStorage into a duplicated tab, so the duplicate is indistinguishable from
its parent. Closing that hole needs claim detection that signs out both tabs,
which was rejected during clarification as too disruptive for a rare action.
"""
from datetime import datetime, timedelta, timezone

import pytest

from auth import (
    SESSION_ABSOLUTE_TIMEOUT,
    SESSION_IDLE_TIMEOUT,
    TabSession,
    hash_tab_token,
    new_tab_token,
)


class TestTokenHandling:
    def test_token_is_not_stored_in_the_clear(self):
        """
        Stored hashed for the same reason agent API keys are: reading the
        database must not yield a usable credential.
        """
        raw = new_tab_token()
        assert hash_tab_token(raw) != raw
        assert len(hash_tab_token(raw)) == 64  # sha256 hex

    def test_hashing_is_deterministic(self):
        raw = new_tab_token()
        assert hash_tab_token(raw) == hash_tab_token(raw)

    def test_tokens_are_unique(self):
        assert len({new_tab_token() for _ in range(200)}) == 200

    def test_token_has_meaningful_entropy(self):
        assert len(new_tab_token()) >= 32

    def test_hashing_a_missing_token_is_safe(self):
        """A request arriving with no token must not raise."""
        assert hash_tab_token(None) is None
        assert hash_tab_token("") is None


class TestRevocationIsTerminal:
    def _session(self):
        now = datetime.now(timezone.utc)
        return TabSession(
            user_id=1, tab_token="x" * 64, issued_at=now, last_seen_at=now
        )

    def test_new_session_is_not_revoked(self):
        assert self._session().is_revoked is False

    def test_revoke_records_the_reason(self):
        s = self._session()
        s.revoke(TabSession.REASON_SIGNED_OUT)
        assert s.is_revoked is True
        assert s.revoked_reason == TabSession.REASON_SIGNED_OUT

    def test_revoke_is_idempotent_and_keeps_the_first_reason(self):
        """
        The first reason is the true one. A later sweep must not relabel why a
        session ended, or FR-002c reports the wrong cause to the user.
        """
        s = self._session()
        s.revoke(TabSession.REASON_IDLE_TIMEOUT)
        first_at = s.revoked_at
        s.revoke(TabSession.REASON_DEPLOYMENT)
        assert s.revoked_reason == TabSession.REASON_IDLE_TIMEOUT
        assert s.revoked_at == first_at

    @pytest.mark.parametrize(
        "reason",
        [
            TabSession.REASON_SIGNED_OUT,
            TabSession.REASON_IDLE_TIMEOUT,
            TabSession.REASON_ABSOLUTE_TIMEOUT,
            TabSession.REASON_PASSWORD_CHANGED,
            TabSession.REASON_DEPLOYMENT,
        ],
    )
    def test_every_reason_fits_the_column(self, reason):
        assert len(reason) <= 32


class TestValidityWindow:
    """
    FR-001: authenticated content is served only while a session is present,
    unrevoked, and inside BOTH limits.
    """

    def _session(self, age=timedelta(0), idle=timedelta(0)):
        now = datetime.now(timezone.utc)
        return TabSession(
            user_id=1,
            tab_token="x" * 64,
            issued_at=now - age,
            last_seen_at=now - idle,
        )

    def test_fresh_session_is_valid(self):
        assert self._session().expiry_reason() is None

    def test_idle_past_the_limit_expires(self):
        s = self._session(idle=SESSION_IDLE_TIMEOUT + timedelta(minutes=1))
        assert s.expiry_reason() == TabSession.REASON_IDLE_TIMEOUT

    def test_active_but_past_the_absolute_limit_expires(self):
        """
        FR-002b: the absolute limit applies regardless of recent activity —
        that is what makes it absolute.
        """
        s = self._session(age=SESSION_ABSOLUTE_TIMEOUT + timedelta(minutes=1))
        assert s.expiry_reason() == TabSession.REASON_ABSOLUTE_TIMEOUT

    def test_just_inside_both_limits_is_valid(self):
        s = self._session(
            age=SESSION_ABSOLUTE_TIMEOUT - timedelta(minutes=1),
            idle=SESSION_IDLE_TIMEOUT - timedelta(minutes=1),
        )
        assert s.expiry_reason() is None

    def test_absolute_limit_wins_when_both_are_breached(self):
        s = self._session(
            age=SESSION_ABSOLUTE_TIMEOUT + timedelta(hours=1),
            idle=SESSION_IDLE_TIMEOUT + timedelta(hours=1),
        )
        assert s.expiry_reason() == TabSession.REASON_ABSOLUTE_TIMEOUT

    def test_an_already_revoked_session_is_never_valid(self):
        s = self._session()
        s.revoke(TabSession.REASON_SIGNED_OUT)
        assert s.expiry_reason() == TabSession.REASON_SIGNED_OUT

    def test_absolute_limit_is_longer_than_idle_limit(self):
        assert SESSION_ABSOLUTE_TIMEOUT > SESSION_IDLE_TIMEOUT


class TestClientSideTabBinding:
    """
    T090, T097. The per-tab half lives in JavaScript, and there is no JS test
    runner here, so the contract is asserted against the source.
    """

    def _js(self):
        from pathlib import Path

        return (
            Path(__file__).parent.parent
            / "server"
            / "static"
            / "js"
            / "tab_session.js"
        ).read_text(encoding="utf-8")

    def test_client_helper_exists(self):
        assert self._js().strip(), "no client-side tab-session helper"

    def test_uses_per_tab_storage_not_cookies_or_localstorage(self):
        """
        sessionStorage is the only per-tab web storage. localStorage is shared
        across tabs and would defeat the entire requirement.
        """
        js = self._js()
        assert "sessionStorage" in js, "per-tab storage is not used (FR-002a)"
        assert "localStorage" not in js, (
            "localStorage is shared across tabs, so a new tab would inherit "
            "authentication — the exact defect being fixed (FR-002a)"
        )

    def test_token_is_sent_on_requests(self):
        js = self._js()
        assert "X-Tab-Session" in js, (
            "the tab token is never sent, so the server cannot bind the request "
            "to a tab"
        )

    def test_documents_the_accepted_duplicate_tab_limitation(self):
        """
        FR-002l. Recorded in the source so the next reader does not 'fix' it by
        building the claim detection that was deliberately rejected.
        """
        js = self._js().lower()
        assert "duplicate" in js, (
            "the accepted duplicated-tab limitation (FR-002l) is not documented "
            "where the next maintainer will look"
        )


class TestNoCachedAuthenticatedContent:
    """T088 / FR-002: the Back button must not serve authenticated pages."""

    def _app_source(self):
        from pathlib import Path

        return (Path(__file__).parent.parent / "server" / "server_app.py").read_text(
            encoding="utf-8"
        )

    def test_no_store_is_set(self):
        src = self._app_source().lower()
        assert "no-store" in src, (
            "authenticated responses are cacheable, so Back-button navigation "
            "can render a page after sign-out (FR-002)"
        )

    def test_the_header_hook_actually_runs(self):
        """
        Guard against the trap this very test file fell into: asserting that a
        string appears in a source file proves nothing about whether the code
        executes. The first version of the no-store change referenced `session`
        without importing it, which the grep-style test above happily passed
        while every real request would have raised NameError.

        This exercises the response through a real request instead.
        """
        from server_app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.get("/auth/login")
            # Unauthenticated: no-store is not required, but the handler must
            # have run without raising.
            assert resp.status_code in (200, 302, 308)

    def test_authenticated_responses_are_not_cacheable(self):
        from server_app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = 1
            resp = client.get("/auth/login")
            cache_control = resp.headers.get("Cache-Control", "")
            assert "no-store" in cache_control, (
                f"authenticated response is cacheable: {cache_control!r} (FR-002)"
            )
