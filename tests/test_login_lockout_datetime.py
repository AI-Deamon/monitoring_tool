"""
Login lockout must not 500 — naive/aware datetime regression.

## Repro

Found by a ZAP scan against /auth/login. After MAX_FAILED_ATTEMPTS bad
passwords the account is locked, and *every* subsequent login POST for that
username returned:

    File "server/auth.py", line 1070, in login
      if user.locked_until and user.locked_until > datetime.now(timezone.utc):
    TypeError: can't compare offset-naive and offset-aware datetimes

## Root cause

`DashboardUser.locked_until` is `db.Column(db.DateTime)` — Postgres
TIMESTAMP WITHOUT TIME ZONE — so psycopg2 always hands back a *naive* value.
The lockout branch compared it against an *aware* `datetime.now(timezone.utc)`.

## Why it was a security bug, not just a crash

The unlock path ("lockout period has passed -> is_locked = False") sits in the
`else` of that same comparison, so it was unreachable. The 30-minute lockout
never expired: five unauthenticated requests permanently denied service to any
known username until someone edited the database by hand.

The same pattern existed on `PasswordResetToken.expires_at`, which would have
made every password-reset link a 500 — i.e. the documented recovery path out
of a lockout was broken by the identical bug.

Both now go through `auth.utcnow_naive()` / `auth.as_naive_utc()`, matching the
D02 / FR-009 convention already applied to `DashboardUser.last_login`.
"""
from datetime import datetime, timedelta, timezone

import pytest

from auth import (
    LOCKOUT_DURATION_MINUTES,
    DashboardUser,
    as_naive_utc,
    resolve_lockout_config,
    utcnow_naive,
)


class TestPythonComparisonBehaviour:
    """Pins the language behaviour this defect depends on."""

    def test_naive_vs_aware_comparison_raises(self):
        naive = datetime(2026, 8, 12, 12, 0, 0)
        aware = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(TypeError):
            _ = naive > aware


class TestNaiveUtcHelpers:
    def test_utcnow_naive_is_naive(self):
        assert utcnow_naive().tzinfo is None

    def test_utcnow_naive_tracks_utc_not_local_time(self):
        """A machine in IST must not stamp locked_until 5.5 hours ahead."""
        delta = abs(
            (utcnow_naive() - datetime.now(timezone.utc).replace(tzinfo=None))
            .total_seconds()
        )
        assert delta < 5, f"utcnow_naive() drifted from UTC by {delta}s"

    def test_as_naive_utc_strips_offset_by_converting(self):
        aware_ist = datetime(
            2026, 8, 12, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
        )
        assert as_naive_utc(aware_ist) == datetime(2026, 8, 12, 12, 0)

    def test_as_naive_utc_passes_naive_through(self):
        naive = datetime(2026, 8, 12, 12, 0)
        assert as_naive_utc(naive) is naive

    def test_as_naive_utc_tolerates_none(self):
        assert as_naive_utc(None) is None


class TestLockoutComparison:
    """
    Reproduces the exact expressions in the login view's lockout branch
    against values shaped the way each storage backend returns them.
    """

    def _locked_user(self, locked_until):
        user = DashboardUser()
        user.is_locked = True
        user.locked_until = locked_until
        return user

    @pytest.mark.parametrize(
        "locked_until",
        [
            # what Postgres returns for TIMESTAMP WITHOUT TIME ZONE
            utcnow_naive() + timedelta(minutes=LOCKOUT_DURATION_MINUTES),
            # a legacy row written before this fix, if a driver kept the offset
            datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES),
        ],
        ids=["naive_column_value", "legacy_aware_value"],
    )
    def test_still_locked_does_not_raise_and_reports_minutes(self, locked_until):
        user = self._locked_user(locked_until)

        locked_until_n = as_naive_utc(user.locked_until)
        now_naive = utcnow_naive()

        assert locked_until_n > now_naive
        remaining = int((locked_until_n - now_naive).total_seconds() // 60) + 1
        assert 1 <= remaining <= LOCKOUT_DURATION_MINUTES

    def test_expired_lockout_falls_through_to_the_unlock_branch(self):
        """
        The bug that mattered: this branch was unreachable, so a lockout was
        permanent rather than LOCKOUT_DURATION_MINUTES long.
        """
        user = self._locked_user(utcnow_naive() - timedelta(minutes=1))

        locked_until_n = as_naive_utc(user.locked_until)
        assert not (locked_until_n and locked_until_n > utcnow_naive())

    def test_sub_minute_remainder_never_displays_as_zero_minutes(self):
        """`.seconds // 60` used to render "Try again in 0 minutes"."""
        locked_until_n = utcnow_naive() + timedelta(seconds=20)
        remaining = int(
            (locked_until_n - utcnow_naive()).total_seconds() // 60
        ) + 1
        assert remaining >= 1


class TestLockoutIsConfigurable:
    """
    MAX_FAILED_LOGIN_ATTEMPTS=0 disables lockout for test/QA environments,
    following the Configurable Security convention already used by
    SESSION_IDLE_TIMEOUT. Defaults must stay at the previous hard-coded values
    so an unconfigured deployment is unchanged.
    """

    def test_defaults_are_unchanged_when_unset(self):
        """An unconfigured deployment keeps the previous hard-coded values."""
        assert resolve_lockout_config({}) == (5, 30)

    def test_zero_disables_lockout(self):
        attempts, _ = resolve_lockout_config({"MAX_FAILED_LOGIN_ATTEMPTS": "0"})
        assert attempts == 0
        assert (attempts > 0) is False, "LOCKOUT_ENABLED would still be True"

    def test_custom_values_are_honoured(self):
        assert resolve_lockout_config(
            {"MAX_FAILED_LOGIN_ATTEMPTS": "3", "LOCKOUT_DURATION_MINUTES": "15"}
        ) == (3, 15)

    @pytest.mark.parametrize("bad", ["", "   ", "yes", "5.5", None])
    def test_garbage_falls_back_to_the_secure_default(self, bad):
        """
        A typo in .env must not disable lockout silently, and must not crash
        the server at import time.
        """
        attempts, _ = resolve_lockout_config({"MAX_FAILED_LOGIN_ATTEMPTS": bad})
        assert attempts == 5

    def test_whitespace_is_tolerated(self):
        """`MAX_FAILED_LOGIN_ATTEMPTS=0 ` with a trailing space still disables."""
        attempts, _ = resolve_lockout_config({"MAX_FAILED_LOGIN_ATTEMPTS": " 0 "})
        assert attempts == 0


class TestNoUsernameEnumerationViaLockout:
    """
    The login view must not let an unauthenticated caller distinguish
    "this account exists and is locked" from "no such user".

    An attacker can *cause* a lockout with MAX_FAILED_ATTEMPTS bad guesses, so
    any signal unique to the locked state is a username oracle on demand.
    """

    LOGIN_SOURCE = None
    LOGIN_AST = None

    @classmethod
    def setup_class(cls):
        import ast
        from pathlib import Path

        import auth as auth_module

        source = Path(auth_module.__file__).read_text(encoding="utf-8")
        start = source.index("def login(")
        cls.LOGIN_SOURCE = source[start : source.index("\ndef ", start + 1)]

        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.name == "login":
                cls.LOGIN_AST = node
                break
        assert cls.LOGIN_AST is not None, "could not locate login() in auth.py"

    def _flashed_messages(self):
        """
        Every string literal passed to flash() inside login().

        Parsed from the AST rather than grepped from the file: the source
        carries comments *explaining* the removed messages, and a substring
        search would match those instead of real behaviour.
        """
        import ast

        messages = []
        for node in ast.walk(self.LOGIN_AST):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "flash"):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                messages.append(arg.value)
            elif isinstance(arg, ast.JoinedStr):  # f-string
                messages.append(
                    "".join(
                        part.value
                        for part in arg.values
                        if isinstance(part, ast.Constant)
                    )
                )
        return messages

    def test_no_flash_discloses_lock_state(self):
        """Neither "you are locked" nor "you have just been locked"."""
        for message in self._flashed_messages():
            lowered = message.lower()
            assert "lock" not in lowered, (
                f"login() flashes {message!r}, which confirms to an "
                f"unauthenticated caller that the username exists"
            )

    def test_every_wrong_credential_outcome_says_the_same_thing(self):
        """
        The unknown-user, wrong-password and locked-account branches must be
        indistinguishable by message text.
        """
        generic = "Invalid username or password."
        assert self._flashed_messages().count(generic) >= 3, (
            "expected the unknown-user, wrong-password and locked-account "
            "branches to share one message; found "
            f"{self._flashed_messages()}"
        )

    def test_locked_branch_applies_the_same_constant_time_delay(self):
        """
        Identical text is not enough — returning faster than the other failure
        branches is itself an oracle. The locked branch used to return with no
        delay at all while every other failure slept 0.5s.
        """
        locked_branch = self.LOGIN_SOURCE[
            self.LOGIN_SOURCE.index("if locked_until and locked_until > now_naive:") :
        ]
        locked_branch = locked_branch[: locked_branch.index("return render_template")]
        assert "time.sleep(0.5)" in locked_branch, (
            "locked-account branch returns without the constant-time delay used "
            "by the other failure branches (timing oracle)"
        )

    def test_locked_branch_is_audit_logged(self):
        """
        A lockout DoS in progress must be visible in the login-attempt audit
        table. This branch previously returned without recording anything.
        """
        locked_branch = self.LOGIN_SOURCE[
            self.LOGIN_SOURCE.index("if locked_until and locked_until > now_naive:") :
        ]
        locked_branch = locked_branch[: locked_branch.index("return render_template")]
        assert "_log_login_attempt(" in locked_branch, (
            "attempts against a locked account leave no audit trail"
        )


class TestPasswordResetTokenExpiry:
    """The recovery path out of a lockout carried the identical defect."""

    def test_is_valid_does_not_raise_on_a_naive_expires_at(self):
        from password_reset import PasswordResetToken

        token = PasswordResetToken()
        token.expires_at = utcnow_naive() + timedelta(hours=1)
        token.used_at = None
        assert token.is_valid() is True

    def test_expired_token_is_invalid(self):
        from password_reset import PasswordResetToken

        token = PasswordResetToken()
        token.expires_at = utcnow_naive() - timedelta(hours=1)
        token.used_at = None
        assert token.is_valid() is False

    def test_used_token_is_invalid(self):
        from password_reset import PasswordResetToken

        token = PasswordResetToken()
        token.expires_at = utcnow_naive() + timedelta(hours=1)
        token.used_at = utcnow_naive()
        assert token.is_valid() is False
