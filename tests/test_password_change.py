"""
T075 / D20 / FR-004, FR-005 — changing a password must not error.

QA repro: Login to agent -> Profile -> Change password -> enter current, new and
confirm password. Actual: an internal server error page.

## Root cause (T074)

`DashboardUser.password_hash` is nullable (auth.py:249) and `check_password()`
passed it straight to Werkzeug with no guard:

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

Werkzeug 3.1.5 raises on a null hash rather than returning False:

    check_password_hash(None, "x")  -> AttributeError: 'NoneType' object has no
                                       attribute 'split'
    check_password_hash("",   "x")  -> False
    check_password_hash("junk","x") -> False

Only None raises. An Active-Directory-authenticated account has no local
password hash, so `g.current_user.check_password(current)` on the first line of
the change-password POST handler raised an unhandled AttributeError and Flask
returned the 500 page. That matches the symptom exactly: the error appears on
*submitting* the form, never on opening it.

This was diagnosed statically — `logs/server.log` was empty (106 bytes) so no
traceback was available, but the behaviour is deterministic and verifiable
without one.
"""
import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from auth import DashboardUser


class TestWerkzeugNullHashBehaviour:
    """Pins the third-party behaviour this defect depends on."""

    def test_null_hash_raises(self):
        with pytest.raises(AttributeError):
            check_password_hash(None, "anything")

    @pytest.mark.parametrize("bad", ["", "not-a-hash"])
    def test_malformed_hash_returns_false_without_raising(self, bad):
        assert check_password_hash(bad, "anything") is False


class TestCheckPasswordIsSafeWithoutALocalHash:
    """
    FR-004: a password change must complete or fail cleanly — never with a
    server error page.
    """

    def _user(self, password_hash):
        user = DashboardUser()
        user.password_hash = password_hash
        return user

    def test_no_hash_returns_false_instead_of_raising(self):
        """
        This is D20. An AD account reaching the change-password form must be
        told something useful, not handed a 500.
        """
        user = self._user(None)
        assert user.check_password("anything") is False, (
            "check_password still raises or misbehaves for an account with no "
            "local password hash (D20, FR-004)"
        )

    def test_empty_hash_returns_false(self):
        assert self._user("").check_password("anything") is False

    def test_correct_password_still_verifies(self):
        """The guard must not weaken normal verification."""
        user = self._user(generate_password_hash("CorrectHorse1!"))
        assert user.check_password("CorrectHorse1!") is True

    def test_wrong_password_still_rejected(self):
        user = self._user(generate_password_hash("CorrectHorse1!"))
        assert user.check_password("wrong") is False

    def test_none_password_does_not_raise(self):
        """Defensive: a missing form field must not become a 500 either."""
        user = self._user(generate_password_hash("CorrectHorse1!"))
        assert user.check_password(None) is False


class TestChangePasswordHandlerGuardsAdAccounts:
    """
    FR-005: rejected changes get a specific, human-readable message and leave
    the stored credential unchanged — not a server error.
    """

    def _auth_source(self):
        from pathlib import Path

        return (Path(__file__).parent.parent / "server" / "auth.py").read_text(
            encoding="utf-8"
        )

    def test_handler_rejects_ad_accounts_with_a_message(self):
        """
        An AD account has no local password to change. Telling the user that is
        the correct outcome; erroring is not.
        """
        src = self._auth_source()
        start = src.index("def change_password()")
        body = src[start : start + 3000]
        assert '"ad"' in body or "'ad'" in body, (
            "the change-password handler does not distinguish AD accounts, so "
            "an AD user still reaches a code path that cannot work (D20)"
        )
