"""
T076–T078, T116–T118 / FR-006a–g — password policy by authentication type.

The rule, clarified 2026-08-07:

  * Active Directory accounts are governed by the directory's own policy and
    MUST NOT have a product-level rule applied to them at any point (FR-006a).
  * Local ordinary users require 12 characters and at least three of the four
    character classes (FR-006b).
  * Local administrators require 14 characters and all four classes (FR-006c).

Both dimensions already exist in the model — `auth_type` ('local'/'ad') and
`role` ('admin'/'user') — and the old length check was already gated on
auth_type at one of its call sites, so the rule maps onto columns that are
there rather than requiring new state.

Why a single validator matters (FR-006d): the previous `len(password) < 8`
check appeared at SIX separate call sites in auth.py. A rule added to five of
them and missed at the sixth leaves an account-creation path that bypasses
policy entirely. Consolidating is a prerequisite for the requirement, not a
tidy-up.
"""
import pytest

from auth import (
    PASSWORD_MIN_LENGTH_ADMIN,
    PASSWORD_MIN_LENGTH_USER,
    validate_password_policy,
)

# Meets the admin rule: 14+ chars, all four classes.
STRONG_ADMIN = "Adm1n!Str0ngPwd#2026"
# Meets the user rule (12+, three classes) but NOT the admin rule (13 chars).
OK_USER_ONLY = "UserPass1234x"
# Too short for either.
TOO_SHORT = "Ab1!xyz"


def _err(password, auth_type="local", role="user"):
    """Return the validator's failure message, or None when it accepts."""
    return validate_password_policy(password, auth_type=auth_type, role=role)


class TestActiveDirectoryExemption:
    """FR-006a / SC-003b: zero product-level rules applied to AD accounts."""

    @pytest.mark.parametrize("role", ["user", "admin"])
    @pytest.mark.parametrize("password", ["", "a", TOO_SHORT, OK_USER_ONLY, STRONG_ADMIN])
    def test_ad_accounts_are_never_rejected(self, password, role):
        assert _err(password, auth_type="ad", role=role) is None, (
            "a product-level password rule was applied to an AD account; its "
            "policy belongs to the directory (FR-006a)"
        )


class TestLocalUserRule:
    """FR-006b: 12 characters, at least three of four classes."""

    def test_accepts_a_compliant_password(self):
        assert _err(OK_USER_ONLY) is None

    def test_rejects_below_minimum_length(self):
        assert _err("Ab1!" + "x" * (PASSWORD_MIN_LENGTH_USER - 5)) is not None

    def test_rejects_too_few_character_classes(self):
        # 12+ characters but only lowercase and digits — two classes.
        assert _err("abcdefgh1234") is not None

    def test_accepts_exactly_three_classes(self):
        assert _err("abcdefgh1234A") is None

    def test_boundary_length_is_accepted(self):
        pwd = "Ab1" + "x" * (PASSWORD_MIN_LENGTH_USER - 3)
        assert len(pwd) == PASSWORD_MIN_LENGTH_USER
        assert _err(pwd) is None

    def test_one_below_boundary_is_rejected(self):
        pwd = "Ab1" + "x" * (PASSWORD_MIN_LENGTH_USER - 4)
        assert len(pwd) == PASSWORD_MIN_LENGTH_USER - 1
        assert _err(pwd) is not None


class TestLocalAdminRule:
    """FR-006c: stricter — 14 characters and all four classes."""

    def test_accepts_a_compliant_admin_password(self):
        assert _err(STRONG_ADMIN, role="admin") is None

    def test_rejects_a_password_that_only_meets_the_user_rule(self):
        """The whole point of the stricter rule."""
        assert _err(OK_USER_ONLY, role="admin") is not None, (
            "an administrator was allowed a password that only meets the "
            "ordinary-user rule (FR-006c)"
        )

    def test_rejects_missing_symbol(self):
        assert _err("Abcdefgh12345678", role="admin") is not None

    def test_rejects_missing_uppercase(self):
        assert _err("abcdefgh12345678!", role="admin") is not None

    def test_admin_minimum_is_stricter_than_user_minimum(self):
        assert PASSWORD_MIN_LENGTH_ADMIN > PASSWORD_MIN_LENGTH_USER


class TestMessagesAreSpecific:
    """FR-006e: name the rule that failed, not the whole policy."""

    def test_length_failure_mentions_length(self):
        msg = _err(TOO_SHORT) or ""
        assert str(PASSWORD_MIN_LENGTH_USER) in msg, (
            f"length failure message does not state the required length: {msg!r}"
        )

    def test_class_failure_mentions_character_types(self):
        msg = (_err("abcdefgh1234") or "").lower()
        assert any(w in msg for w in ("character", "letter", "digit", "symbol", "uppercase")), (
            "the message does not say which character types are missing (FR-006e)"
        )

    def test_admin_message_reflects_the_admin_rule(self):
        msg = _err(OK_USER_ONLY, role="admin") or ""
        assert str(PASSWORD_MIN_LENGTH_ADMIN) in msg


class TestSingleValidatorIsUsedEverywhere:
    """
    FR-006d / SC-003a: enforced at account creation, password change, and
    password reset. Asserted against the source because a rule missed at one
    call site is invisible to any test that only exercises the others.
    """

    def _auth_source(self):
        from pathlib import Path

        return (Path(__file__).parent.parent / "server" / "auth.py").read_text(
            encoding="utf-8"
        )

    def test_no_bare_length_checks_remain(self):
        """
        Matches executable checks only (`if len(...) < N`), not prose. The
        validator's own docstring quotes the old check when explaining why it
        exists, and that mention is not a bypass.
        """
        import re

        src = self._auth_source()
        offenders = re.findall(r"if\s+.*len\(\s*\w*password\w*\s*\)\s*<\s*\d+", src)
        assert not offenders, (
            f"{len(offenders)} bare length checks remain in auth.py: {offenders}. "
            f"Each is a path that bypasses the policy (FR-006d)"
        )

    def test_validator_covers_every_password_setting_path(self):
        """
        Five call sites plus the definition.

        Six sites carried the old length check, but one of them was the *login*
        handler — not a password-setting path. Validating policy at sign-in
        would reject every existing user whose password predates the policy,
        which FR-006f explicitly forbids, so that check was removed rather than
        migrated. The five that remain are reset, change, add-user (×2) and
        edit-user: the three entry points FR-006d names.
        """
        src = self._auth_source()
        calls = src.count("validate_password_policy(")
        assert calls >= 6, (
            f"validate_password_policy appears {calls} times; expected the "
            f"definition plus five password-setting sites (FR-006d)"
        )

    def test_login_does_not_apply_the_policy(self):
        """FR-006f: nobody is locked out of signing in by a policy change."""
        src = self._auth_source()
        start = src.index("def login(")
        body = src[start : start + 4000]
        assert "validate_password_policy" not in body, (
            "the login handler applies the password policy, which would lock "
            "out existing users whose password predates it (FR-006f)"
        )
