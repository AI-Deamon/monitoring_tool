#!/usr/bin/env python3
"""
Break-glass recovery for a locked-out administrator (feature 037, FR-006h-j).

Feature 037 forces existing local administrators whose password does not meet
the stricter admin rule to set a compliant one before doing anything else
(FR-006f). That hold is applied in `login_required`, so an administrator who
cannot complete the change — a forgotten password, a mistyped one, an account
with no working local credential — has no route back in through the dashboard.

If every administrator ends up in that state at once, nobody can create or fix
an administrator, because doing so requires being an administrator. This script
is the way out.

Deliberate properties (FR-006h-j):

  * Requires shell access to the server. It is a script, not a route, and is
    never reachable over the network — the recovery path must not become an
    authentication bypass.
  * Resets one named administrator's password and clears the forced-rotation
    hold in a single action, so the account is immediately usable.
  * Validates the new password against the same policy as the dashboard, so
    recovery cannot be used to sidestep the rule it exists to survive.
  * Logs every use with the account and a timestamp.

Usage
-----
    cd monitoring_tool/server
    python scripts/admin/reset_admin_password.py <username>
    python scripts/admin/reset_admin_password.py <username> --password '<new>'
    python scripts/admin/reset_admin_password.py --list

With no --password the script generates a compliant one and prints it once.
"""
import argparse
import getpass
import logging
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

# Match the path convention used by the other scripts in this directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server_app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from auth import (  # noqa: E402
    DashboardUser,
    PASSWORD_MIN_LENGTH_ADMIN,
    validate_password_policy,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reset_admin_password")


def _generate_compliant_password():
    """
    Generate a password that satisfies the administrator rule.

    Built from one character of each required class plus random filler, then
    shuffled, so it cannot accidentally fail the class requirement.
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    length = max(PASSWORD_MIN_LENGTH_ADMIN + 4, 18)
    while True:
        chars = [
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.digits),
            secrets.choice("!@#$%^&*-_=+"),
        ]
        chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
        secrets.SystemRandom().shuffle(chars)
        candidate = "".join(chars)
        if validate_password_policy(candidate, auth_type="local", role="admin") is None:
            return candidate


def list_administrators():
    admins = DashboardUser.query.filter_by(role="admin").all()
    if not admins:
        logger.warning("No administrator accounts exist.")
        return 1
    print(f"{'username':<28} {'auth':<6} {'active':<7} must_change_password")
    for a in admins:
        print(
            f"{a.username:<28} {(a.auth_type or 'local'):<6} "
            f"{str(bool(a.is_active)):<7} {bool(getattr(a, 'must_change_password', False))}"
        )
    return 0


def reset_password(username, new_password=None):
    user = DashboardUser.query.filter_by(username=username).first()
    if not user:
        logger.error(f"No account named {username!r}.")
        return 1

    if (user.auth_type or "local").lower() == "ad":
        logger.error(
            f"{username!r} authenticates against the directory; its password is "
            f"managed there and cannot be reset here (FR-006a)."
        )
        return 1

    if (user.role or "user").lower() != "admin":
        logger.error(
            f"{username!r} is not an administrator. This script exists for "
            f"administrator lockout; use the dashboard for ordinary accounts."
        )
        return 1

    generated = new_password is None
    if generated:
        new_password = _generate_compliant_password()

    # Recovery must not be a way around the policy it exists to survive.
    policy_error = validate_password_policy(
        new_password, auth_type="local", role="admin"
    )
    if policy_error:
        logger.error(f"Refused: {policy_error}")
        return 1

    user.set_password(new_password)
    user.must_change_password = False
    user.is_active = True
    # Invalidate any session still holding the old credential.
    user.session_version = (user.session_version or 1) + 1
    db.session.commit()

    logger.info(
        f"[BREAK-GLASS] Administrator password reset for {username!r} at "
        f"{datetime.now(timezone.utc).isoformat()} by OS user "
        f"{getpass.getuser()!r}; forced-rotation hold cleared, other sessions "
        f"invalidated."
    )
    if generated:
        print("\nNew password (shown once — copy it now):\n")
        print(f"    {new_password}\n")
    else:
        print("\nPassword updated.\n")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Break-glass recovery for a locked-out administrator."
    )
    parser.add_argument("username", nargs="?", help="administrator account to reset")
    parser.add_argument(
        "--password",
        help="new password; omit to generate a compliant one and print it once",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list administrator accounts and their forced-rotation state",
    )
    args = parser.parse_args()

    if not args.list and not args.username:
        parser.error("provide a username, or --list")

    app = create_app()
    with app.app_context():
        if args.list:
            return list_administrators()
        return reset_password(args.username, args.password)


if __name__ == "__main__":
    sys.exit(main())
