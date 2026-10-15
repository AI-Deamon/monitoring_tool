"""
Dashboard Authentication Module
================================
Provides user authentication, session management, and role-based access control.

Roles:
    - admin: Can view all agents and manage users
    - user: Can only view their linked agent (matched by username)
"""

from functools import wraps
from datetime import datetime, timedelta, timezone
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    g,
    jsonify,
)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from extensions import db
import logging
import os
import secrets
import re
import time
import hmac
import hashlib
import base64

logger = logging.getLogger(__name__)


# Lazy import to avoid circular dependency
def get_password_reset_service():
    from password_reset import PasswordResetService

    return PasswordResetService


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

# Password policy (feature 037, FR-006a-g).
#
# Configurable per the constitution's Configurable Security principle. The
# defaults are the values agreed during clarification; confirm them against your
# security standard before relying on them.
PASSWORD_MIN_LENGTH_USER = int(os.getenv("PASSWORD_MIN_LENGTH_USER", "12"))
PASSWORD_MIN_LENGTH_ADMIN = int(os.getenv("PASSWORD_MIN_LENGTH_ADMIN", "14"))
PASSWORD_MIN_CLASSES_USER = int(os.getenv("PASSWORD_MIN_CLASSES_USER", "3"))
PASSWORD_MIN_CLASSES_ADMIN = int(os.getenv("PASSWORD_MIN_CLASSES_ADMIN", "4"))

_CLASS_NAMES = ("a lowercase letter", "an uppercase letter", "a digit", "a symbol")


def _character_classes(password: str):
    """Which of the four character classes appear in `password`."""
    return (
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    )


def validate_password_policy(password, auth_type="local", role="user"):
    """
    Check a password against the policy for this kind of account.

    Returns None when the password is acceptable, otherwise a specific,
    human-readable message naming the rule that failed (FR-006e).

    The policy splits by authentication type and role (clarified 2026-08-07):

      * auth_type 'ad'    — exempt entirely. Directory-authenticated accounts
                            are governed by the directory's own policy, and the
                            product must not impose a second one (FR-006a).
      * local, role user  — 12 characters, at least 3 of 4 classes (FR-006b).
      * local, role admin — 14 characters, all 4 classes (FR-006c).

    This exists because the previous `len(password) < 8` check was duplicated at
    six call sites in this module. A rule added to five of them and missed at
    the sixth leaves an account-creation path that bypasses policy, so the rule
    has to live in one place to be enforceable at all (FR-006d).
    """
    if (auth_type or "local").lower() == "ad":
        return None

    password = password or ""
    is_admin = (role or "user").lower() == "admin"
    min_length = PASSWORD_MIN_LENGTH_ADMIN if is_admin else PASSWORD_MIN_LENGTH_USER
    min_classes = PASSWORD_MIN_CLASSES_ADMIN if is_admin else PASSWORD_MIN_CLASSES_USER
    who = "Administrator passwords" if is_admin else "Passwords"

    if len(password) < min_length:
        return f"{who} must be at least {min_length} characters."

    present = _character_classes(password)
    if sum(present) < min_classes:
        missing = [name for name, seen in zip(_CLASS_NAMES, present) if not seen]
        if min_classes >= 4:
            return (
                f"{who} must contain a lowercase letter, an uppercase letter, "
                f"a digit and a symbol. Missing: {', '.join(missing)}."
            )
        return (
            f"{who} must contain at least {min_classes} of: a lowercase letter, "
            f"an uppercase letter, a digit, a symbol. Missing: {', '.join(missing)}."
        )

    return None



def validate_username(username: str) -> tuple[bool, str]:
    """Validate username format (alphanumeric, dots, underscores, hyphens only)"""
    if not username or len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(username) > 50:
        return False, "Username must be less than 50 characters"
    if not re.match(r"^[a-zA-Z0-9._-]+$", username):
        return (
            False,
            "Username can only contain letters, numbers, dots, underscores, and hyphens",
        )
    return True, ""


def _log_login_attempt(user_id, username, auth_type, request, success, failure_reason=None):
    """Log login attempt to audit table with timing attack prevention"""
    try:
        audit = LoginAudit(
            user_id=user_id,
            username=username[:100],
            auth_type=auth_type,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent", "")[:500],
            success=success,
            failure_reason=failure_reason[:255] if failure_reason else None,
        )
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        logger.error(f"[AUTH] Failed to log login attempt: {e}")


def validate_login_username(username: str) -> tuple[bool, str]:
    r"""Validate login username (supports AD DOMAIN\user, user@domain, bare user)"""
    if not username or len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(username) > 100:
        return False, "Username must be less than 100 characters"
    # Allow DOMAIN\user, user@domain, bare user, and spaces in AD usernames
    if not re.match(r"^[a-zA-Z0-9._@\\ -]+$", username):
        return False, "Username contains invalid characters"
    return True, ""


def check_linked_username_unique(
    linked_username: str, exclude_user_id: int = None
) -> bool:
    """Check if linked_username is already in use by another user"""
    if not linked_username:
        return True  # Empty is allowed
    query = DashboardUser.query.filter_by(linked_username=linked_username)
    if exclude_user_id:
        query = query.filter(DashboardUser.id != exclude_user_id)
    return query.first() is None


# Blueprint
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded errors for form-based login"""
    flash("Too many login attempts. Please wait 15 minutes before trying again.", "danger")
    return redirect(url_for("auth.login"))


# ============================================================================
# ISSUE-002 FIX: CSRF PROTECTION
# ============================================================================


def generate_csrf_token():
    """Generate HMAC-based CSRF token, bound to the current session.

    Uses URL-safe base64 (no +/ or padding issues in form POST).
    The token is self-validating: timestamp:nonce:session_seed:HMAC_signature.
    Binding to session["user_id"] prevents an anonymously-harvested token from
    being replayed against a logged-in victim. Pre-login routes share the
    "anon" seed, which is fine since there is no victim session to protect.
    """
    from flask import current_app
    secret = current_app.config["SECRET_KEY"]
    expires = int(time.time()) + 3600  # 1 hour expiry
    nonce = secrets.token_hex(16)
    session_seed = str(session.get("user_id", "anon"))
    payload = f"{expires}:{nonce}:{session_seed}"
    sig = hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    raw = f"{payload}:{sig}"
    token = base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()
    return token


def validate_csrf_token():
    """Validate HMAC-based CSRF token and that it belongs to this session."""
    from flask import current_app
    # Burp #10: form POSTs carry the token in a hidden field; JSON/fetch API
    # clients that have no form body pass the same HMAC token in a header.
    form_token = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")

    if not form_token:
        logger.warning("[CSRF] Missing token in form/header")
        return False

    try:
        # Restore padding before decoding
        padded = form_token
        pad = len(padded) % 4
        if pad:
            padded += "=" * (4 - pad)
        decoded = base64.urlsafe_b64decode(padded).decode()
        parts = decoded.split(":")
        if len(parts) < 4:
            return False

        expires = int(parts[0])
        nonce = parts[1]
        token_seed = parts[2]
        sig = parts[3]
        payload = f"{expires}:{nonce}:{token_seed}"

        # Verify HMAC signature
        secret = current_app.config["SECRET_KEY"]
        expected_sig = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            logger.warning(f"[CSRF] Token signature mismatch from {request.remote_addr}")
            return False

        # Token must have been minted for this session, otherwise an
        # anonymously-harvested token could be replayed against a victim.
        current_seed = str(session.get("user_id", "anon"))
        if not hmac.compare_digest(token_seed, current_seed):
            logger.warning(f"[CSRF] Token/session mismatch from {request.remote_addr}")
            return False

        # Check expiry
        if time.time() > expires:
            logger.warning("[CSRF] Token expired")
            return False

        return True
    except Exception as e:
        logger.warning(f"[CSRF] Token validation error: {e}")
        return False


def csrf_protect(f):
    """Decorator to require CSRF token on POST requests"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == "POST":
            if not validate_csrf_token():
                flash("The page has expired. Please try again.", "warning")
                return redirect(request.url)
        return f(*args, **kwargs)

    return decorated_function


# Make CSRF token available in all templates
@auth_bp.app_context_processor
def inject_csrf_token():
    return {"csrf_token": generate_csrf_token}


# ============================================================================
# DATABASE MODEL
# ============================================================================


class LoginAudit(db.Model):
    """Track all login attempts for compliance and security monitoring"""

    __tablename__ = "login_audit"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("dashboard_users.id", ondelete="SET NULL"), nullable=True)
    username = db.Column(db.String(100), nullable=False)
    auth_type = db.Column(db.String(20), nullable=False, default="local")  # 'local' or 'ad'
    ip_address = db.Column(db.String(45), nullable=True)  # Supports IPv6
    user_agent = db.Column(db.Text(), nullable=True)
    success = db.Column(db.Boolean, nullable=False)
    failure_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DashboardUser(db.Model):
    """Dashboard user for authentication"""

    __tablename__ = "dashboard_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(20), default="user")  # 'admin' or 'user'
    org_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=True, index=True
    )  # Multi-tenant link

    # Link to agent data (for user role - matched by Windows username)
    linked_username = db.Column(
        db.String(255), nullable=True
    )  # Windows username from agent

    # AD Authentication
    auth_type = db.Column(db.String(20), default="local")  # 'local' or 'ad'
    ad_object_guid = db.Column(db.String(100), nullable=True)  # AD object GUID

    # Contact info
    email = db.Column(db.String(255), nullable=True)
    email_verified = db.Column(db.Boolean, default=False)

    # Account status
    is_active = db.Column(db.Boolean, default=True)
    is_locked = db.Column(db.Boolean, default=False)
    failed_login_count = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)

    # Session Management
    session_version = db.Column(db.Integer, default=1, nullable=False)

    # Password policy (feature 037, FR-006f). Set for existing local
    # administrators by migration 20260807_admin_password_rotation. Blocks all
    # authenticated activity except the password-change flow until cleared.
    # Never set for AD accounts — their policy belongs to the directory.
    must_change_password = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.text("false")
    )

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def set_password(self, password: str):
        """Hash and set password"""
        # Using pbkdf2 with 600000 iterations (OWASP 2023 recommendation)
        self.password_hash = generate_password_hash(
            password, method="pbkdf2:sha256:600000"
        )

    def check_password(self, password: str) -> bool:
        """
        Verify a password against this account's local hash.

        Returns False when the account has no local hash rather than raising.
        password_hash is nullable — an Active-Directory-authenticated account
        never has one — and Werkzeug raises on a null hash instead of returning
        False:

            check_password_hash(None, "x")   -> AttributeError ('NoneType' has
                                                no attribute 'split')
            check_password_hash("", "x")     -> False
            check_password_hash("junk", "x") -> False

        That unguarded call is defect D20: an AD user submitting the
        change-password form hit the AttributeError on the handler's first line
        and got an internal server error page. Only None raises, so the guard is
        just a presence check; malformed hashes already fail safely.
        """
        if not self.password_hash or password is None:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "auth_type": self.auth_type,
            "linked_username": self.linked_username,
            "ad_object_guid": self.ad_object_guid,
            "is_active": self.is_active,
            "is_locked": self.is_locked,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _as_aware(value):
    """
    Treat a naive timestamp as UTC.

    PostgreSQL returns timezone-aware values for these columns, but SQLite and
    freshly-constructed unsaved rows can yield naive ones. Comparing a naive to
    an aware datetime raises, which would turn a session check into a 500 —
    the same class of failure as D20.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class TabSession(db.Model):
    """
    Per-tab dashboard authentication (feature 037, FR-002a / FR-002b).

    A browser tab holds an opaque token in sessionStorage; this table is the
    server-side authority on whether that token is still valid. Holding the
    decision server-side is what makes this access control rather than a
    client-side flag, and it makes deployment-wide revocation (FR-002g) a
    single UPDATE.

    Sits alongside the existing session_version mechanism, which must keep
    invalidating other sessions on password change (FR-003). Both checks apply.
    """

    __tablename__ = "tab_session"

    # Revocation reasons, surfaced to the user by FR-002c.
    REASON_SIGNED_OUT = "signed_out"
    REASON_IDLE_TIMEOUT = "idle_timeout"
    REASON_ABSOLUTE_TIMEOUT = "absolute_timeout"
    REASON_PASSWORD_CHANGED = "password_changed"
    REASON_DEPLOYMENT = "deployment"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("dashboard_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256 hex digest of the token held by the browser. Stored hashed for the
    # same reason agent API keys are: a database read must not yield a usable
    # credential.
    tab_token = db.Column(db.String(64), nullable=False, unique=True, index=True)

    # Start of the absolute lifetime (FR-002b: 4 hours).
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False)
    # Advanced on each authenticated request; start of the idle window
    # (FR-002b: 30 minutes).
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False)

    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_reason = db.Column(db.String(32), nullable=True)

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def revoke(self, reason: str, now=None):
        """
        Mark this tab session unusable. Terminal — sign-in creates a new row.

        Idempotent, and the FIRST reason wins. A later sweep (a deployment
        revocation, say) must not relabel a session that already ended through
        idle timeout, or FR-002c reports the wrong cause to the user.
        """
        if self.revoked_at is None:
            self.revoked_at = now or datetime.now(timezone.utc)
            self.revoked_reason = reason

    def expiry_reason(self, now=None):
        """
        Why this session is unusable, or None while it is still valid.

        Checked in severity order: an explicit revocation is already final; the
        absolute limit outranks the idle limit because it applies regardless of
        activity, so when both are breached the absolute one is the true cause.
        """
        if self.revoked_at is not None:
            return self.revoked_reason

        now = now or datetime.now(timezone.utc)
        issued = _as_aware(self.issued_at)
        last_seen = _as_aware(self.last_seen_at)

        if issued is not None and now - issued > SESSION_ABSOLUTE_TIMEOUT:
            return self.REASON_ABSOLUTE_TIMEOUT
        if last_seen is not None and now - last_seen > SESSION_IDLE_TIMEOUT:
            return self.REASON_IDLE_TIMEOUT
        return None


# ============================================================================
# CONFIGURATION
# ============================================================================

# Account lockout. Environment-configurable per the constitution's Configurable
# Security principle; the defaults are the previous hard-coded values, so an
# unconfigured deployment is unchanged.
#
# MAX_FAILED_LOGIN_ATTEMPTS=0 DISABLES lockout entirely. That is intended for
# test/QA environments where a scanner (ZAP) or repeated manual testing would
# otherwise lock every account — never for production, where lockout is the
# only control here that bounds online password guessing.
def resolve_lockout_config(env=None):
    """(max_attempts, duration_minutes) from the environment.

    A function rather than inline os.getenv so the precedence and the
    disable switch are testable without reimporting this module — reloading
    auth re-declares its SQLAlchemy models against the same base.

    A non-numeric value falls back to the secure default rather than raising
    at import time and taking the whole server down.
    """
    env = os.environ if env is None else env

    def _int(name, default):
        try:
            return int(str(env.get(name, default)).strip())
        except (TypeError, ValueError):
            logger.warning(
                f"[AUTH] Invalid {name}={env.get(name)!r}; using default {default}"
            )
            return default

    return _int("MAX_FAILED_LOGIN_ATTEMPTS", 5), _int("LOCKOUT_DURATION_MINUTES", 30)


MAX_FAILED_ATTEMPTS, LOCKOUT_DURATION_MINUTES = resolve_lockout_config()

#: False when lockout is switched off by configuration.
LOCKOUT_ENABLED = MAX_FAILED_ATTEMPTS > 0


# D02 / FR-009 storage convention: every db.DateTime column here is naive UTC.
# Re-exported so existing callers keep importing these from auth; utils.dt
# carries the full rationale.
from utils.dt import as_naive_utc, utcnow_naive  # noqa: E402,F401

# Session limits (feature 037, FR-002b). Two independent limits: an idle window
# and an absolute lifetime. Flask's PERMANENT_SESSION_LIFETIME expresses only
# one, and cannot distinguish which limit ended a session — FR-002c requires
# telling the user which it was — so both are enforced against the tab_session
# row instead.
#
# Environment-configurable per the constitution's Configurable Security
# principle. The defaults replace the previous 8-hour lifetime; the constitution
# was amended to match (T004).
SESSION_IDLE_TIMEOUT = timedelta(
    minutes=int(os.getenv("SESSION_IDLE_TIMEOUT_MINUTES", "30"))
)
SESSION_ABSOLUTE_TIMEOUT = timedelta(
    hours=int(os.getenv("SESSION_ABSOLUTE_TIMEOUT_HOURS", "4"))
)

#: Header carrying the per-tab token. A header, not a cookie — cookies are
#: shared across tabs by design, which is the behaviour being fixed.
TAB_SESSION_HEADER = "X-Tab-Session"


def new_tab_token() -> str:
    """A fresh opaque per-tab token. Held by the browser in sessionStorage."""
    return secrets.token_urlsafe(32)


def issue_tab_session(user, now=None):
    """
    Create a tab session for `user` and return the RAW token.

    The raw token is returned once, for the browser to hold; only its hash is
    stored. Called on sign-in, so each sign-in — including a second sign-in by
    the same user in a different tab — produces its own row.
    """
    now = now or datetime.now(timezone.utc)
    raw = new_tab_token()
    db.session.add(
        TabSession(
            user_id=user.id,
            tab_token=hash_tab_token(raw),
            issued_at=now,
            last_seen_at=now,
        )
    )
    db.session.commit()
    return raw


def lookup_tab_session(raw_token):
    """The unrevoked TabSession for this raw token, or None."""
    token_hash = hash_tab_token(raw_token)
    if not token_hash:
        return None
    return TabSession.query.filter_by(tab_token=token_hash).first()


def revoke_user_tab_sessions(user_id, reason, now=None):
    """
    Revoke every live tab session belonging to one user. Returns the count.

    Used by sign-out (scenario 1a) and password change (FR-003) — both mean
    "end this person's access everywhere", not just in the current tab.
    """
    now = now or datetime.now(timezone.utc)
    sessions = TabSession.query.filter_by(user_id=user_id, revoked_at=None).all()
    for tab in sessions:
        tab.revoke(reason, now=now)
    if sessions:
        db.session.commit()
    return len(sessions)


def revoke_all_tab_sessions(reason=None, now=None):
    """
    Revoke every live tab session for every user. Returns the count.

    FR-002g: deployment invalidates all existing sessions, so no session created
    under the previous, longer-lived rules survives the change. This touches
    authentication state only — saved schedules, reports and settings are
    untouched (FR-002h).
    """
    now = now or datetime.now(timezone.utc)
    reason = reason or TabSession.REASON_DEPLOYMENT
    sessions = TabSession.query.filter_by(revoked_at=None).all()
    for tab in sessions:
        tab.revoke(reason, now=now)
    if sessions:
        db.session.commit()
    logger.info(f"[AUTH] Revoked {len(sessions)} tab session(s): {reason}")
    return len(sessions)


#: What the user is told when each limit ends their session (FR-002c).
SESSION_END_MESSAGES = {
    TabSession.REASON_IDLE_TIMEOUT: (
        "You were signed out because you were inactive for a while. "
        "Please sign in again."
    ),
    TabSession.REASON_ABSOLUTE_TIMEOUT: (
        "Your session reached its maximum length. Please sign in again."
    ),
    TabSession.REASON_PASSWORD_CHANGED: (
        "Your password was changed, so other sessions were signed out."
    ),
    TabSession.REASON_DEPLOYMENT: (
        "The application was updated and all sessions were signed out. "
        "Please sign in again."
    ),
    TabSession.REASON_SIGNED_OUT: "You have been signed out.",
}


def hash_tab_token(raw_token):
    """
    SHA-256 of a tab token, or None when there is no token.

    Stored hashed for the same reason agent API keys are: a database read must
    not yield a usable credential. Returning None for a missing token lets
    callers treat "no token" and "unknown token" identically.
    """
    if not raw_token:
        return None
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
# NOTE: session lifetime is configured in server_app.py via
# PERMANENT_SESSION_LIFETIME (8 hours). Do not reintroduce a duplicate constant
# here - it drifts from the real setting.


# ============================================================================
# DECORATORS
# ============================================================================


def wants_json_response() -> bool:
    """
    True when the caller is a fetch/XHR client rather than a browser navigation.

    Redirecting an API call to the HTML login page is what made every dashboard
    admin action fail SILENTLY once a session lapsed: fetch() transparently
    follows the 302, the handler calls `await resp.json()` on a login page, and
    the resulting SyntaxError rejects the promise before any alert() runs. The
    user sees a click that does nothing. Returning a JSON 401/403 lets the page
    say "your session expired" instead.
    """
    if "/api/" in request.path:
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    # Accept: */* (the fetch default) must NOT count as a JSON preference, or
    # ordinary navigations would stop redirecting to the login page.
    return request.is_json


def _auth_failure(reason: str, message: str, status: int, redirect_to):
    """JSON for API callers, flash+redirect for browser navigations."""
    if wants_json_response():
        return jsonify({"error": reason, "message": message}), status
    flash(message, "warning" if status == 401 else "danger")
    return redirect(redirect_to)


def login_required(f):
    """Decorator: Require user to be logged in"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return _auth_failure(
                "authentication_required",
                "Please log in to access this page.",
                401,
                url_for("auth.login", next=request.url),
            )

        # Load current user
        user = DashboardUser.query.filter_by(id=session["user_id"]).first()

        # Session Invalidation Check:
        # If the user doesn't exist, is inactive, OR their session version mismatch (e.g., password reset occurred)
        current_session_version = session.get("session_version", 1)
        if (
            not user
            or not user.is_active
            or user.session_version != current_session_version
        ):
            if user:
                logger.info(
                    f"[AUTH] Terminated outdated session for {user.username} (Version mismatch or inactive)"
                )
            session.clear()
            return _auth_failure(
                "session_expired",
                "Your session has expired or your password was changed. "
                "Please log in again.",
                401,
                url_for("auth.login"),
            )

        # Per-tab authentication and session limits (FR-002a, FR-002b).
        #
        # The cookie above proves a browser signed in; it does NOT prove THIS
        # tab did, because cookies are shared across tabs. The tab token does.
        # Enforced here so every authenticated route is covered — a per-route
        # check would be one forgotten decorator away from a hole.
        # The token normally arrives in a header (or a form field on POST), put
        # there by tab_session.js from this tab's sessionStorage.
        raw_tab_token = request.headers.get(TAB_SESSION_HEADER) or request.form.get(
            "tab_session"
        )

        # Bootstrap: immediately after sign-in the browser has not yet stored the
        # token, so it is handed over through the session cookie until the tab
        # confirms it has it — which it does by sending the header.
        #
        # It is deliberately NOT consumed on first read. An earlier version
        # popped it immediately, reasoning that a token left in the cookie is
        # shared with every tab. That broke sign-in outright: the first
        # authenticated request after login is often a REDIRECT (forced password
        # rotation, a `next=` target, trailing-slash normalisation), and a 302
        # carries no HTML, so the token was consumed without ever reaching the
        # browser. The next request then had nothing and signed the user out.
        #
        # Trade-off, accepted and bounded: the token remains in the cookie from
        # sign-in until this tab's first header-bearing request. A second tab
        # opened inside that window inherits the session. The window is one page
        # load, and it closes permanently the moment the tab's JavaScript runs.
        if not raw_tab_token:
            raw_tab_token = session.get("tab_token")
            if raw_tab_token:
                # Handed to the template so tab_session.js can store it.
                g.tab_bootstrap_token = raw_tab_token
        # NOTE: the session copy is deliberately NOT removed once the header
        # starts arriving.
        #
        # Browsers cannot attach custom headers to top-level navigations. Every
        # click from Overview to Agents to Reports is a plain GET, so it carries
        # no X-Tab-Session header. Removing the cookie copy therefore signs the
        # user out on the first link they click — verified in a real browser:
        # the page's fetch() calls all authenticated (hdr=True), and the very
        # next navigation did not (hdr=False).
        #
        # Consequence, and it is a real one: authentication is effectively
        # carried by the session cookie, which every tab shares. FR-002a's
        # per-tab isolation is NOT achieved by this mechanism and cannot be
        # without routing every navigation through fetch (an SPA rewrite).
        # See the note in login() and the feature spec before changing this.

        tab = lookup_tab_session(raw_tab_token)
        expiry = tab.expiry_reason() if tab else None

        if tab is None or expiry is not None:
            if tab is not None and tab.revoked_at is None:
                # Record WHY it ended, so the message below is accurate and the
                # row is not re-judged later (FR-002c).
                tab.revoke(expiry)
                db.session.commit()
            reason = expiry or TabSession.REASON_SIGNED_OUT
            session.clear()
            return _auth_failure(
                reason,
                SESSION_END_MESSAGES.get(reason, "Please sign in again."),
                401,
                url_for("auth.login"),
            )

        # Still valid — advance the idle window (FR-002b).
        tab.last_seen_at = datetime.now(timezone.utc)
        db.session.commit()
        g.tab_session = tab

        # Store user in g for access in views
        g.current_user = user

        # Forced password rotation (feature 037, FR-006f).
        #
        # Existing local administrators whose password does not meet the
        # stricter admin rule must set a compliant one before doing anything
        # else. Ordinary local users are deliberately NOT forced — FR-006f
        # requires that nobody is locked out by the policy change — and AD
        # accounts are exempt entirely (FR-006a).
        #
        # The allow-list must include the change-password page itself and
        # sign-out, or the user has no route out of the state. Static files are
        # allowed so the page can render.
        if getattr(user, "must_change_password", False) and request.endpoint not in (
            "auth.change_password",
            "auth.logout",
            "static",
        ):
            return _auth_failure(
                "password_change_required",
                "Your password does not meet the current policy. "
                "Please set a new one to continue.",
                403,
                url_for("auth.change_password"),
            )

        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Decorator: Require user to be admin"""

    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if g.current_user.role != "admin":
            return _auth_failure(
                "admin_required",
                "Administrator access required.",
                403,
                url_for("dashboard.dashboard_home"),
            )
        return f(*args, **kwargs)

    return decorated_function


def can_view_agent(agent_id: str, username: str = None) -> bool:
    """Check if current user can view a specific agent's data"""
    if not hasattr(g, "current_user") or not g.current_user:
        return False

    # Admin can view all
    if g.current_user.role == "admin":
        return True

    # User can only view their linked data
    if g.current_user.linked_username:
        # Import here to avoid circular imports
        import server_models
        from sqlalchemy import or_

        # Check if this agent has data for the user's linked username
        linked_username = g.current_user.linked_username

        # Check AgentCurrentStatus table for username match
        agent_status = (
            server_models.AgentCurrentStatus.query.filter(
                server_models.AgentCurrentStatus.agent_id == agent_id
            )
            .filter(
                or_(
                    server_models.AgentCurrentStatus.username == linked_username,
                    server_models.AgentCurrentStatus.username.ilike(linked_username),
                    server_models.AgentCurrentStatus.username.ilike(
                        f"%\\{linked_username}"
                    ),
                    # UPN form (user@domain) only - NOT an open "{name}%" prefix,
                    # which would leak e.g. "johnson"/"john.doe" data to "john".
                    server_models.AgentCurrentStatus.username.ilike(
                        f"{linked_username}@%"
                    ),
                )
            )
            .first()
        )

        if agent_status:
            return True

        # Also check ScreenTime table as fallback
        screen_time = (
            server_models.ScreenTime.query.filter(
                server_models.ScreenTime.agent_id == agent_id
            )
            .filter(
                or_(
                    server_models.ScreenTime.username == linked_username,
                    server_models.ScreenTime.username.ilike(linked_username),
                    server_models.ScreenTime.username.ilike(f"%\\{linked_username}"),
                    # UPN form only - see can_view_agent note above (no open prefix).
                    server_models.ScreenTime.username.ilike(f"{linked_username}@%"),
                )
            )
            .first()
        )

        return screen_time is not None

    return False


# Sentinel username that can never match a real Windows account. Callers
# treat a falsy filter as "admin - show everything", so a non-admin who has
# no linked_username (or a missing session) MUST still get a truthy filter,
# otherwise they would see every agent's data. Returning this value keeps
# every existing `if user_filter:` call site correct and fails closed: the
# query runs, but matches nothing.
NO_ACCESS_USERNAME = "__no_linked_user__"


def get_user_filter():
    """Get filter for queries based on user role.

    Returns:
        None                  -> admin: no filtering, sees all agents
        <linked_username>     -> user: scoped to their own agent data
        NO_ACCESS_USERNAME    -> user without a linked account, or no session:
                                 scoped to nothing (fail closed)
    """
    if not hasattr(g, "current_user") or not g.current_user:
        return NO_ACCESS_USERNAME

    if g.current_user.role == "admin":
        return None  # No filter for admin

    # User: filter by linked username. Never fall through to "no filter".
    return g.current_user.linked_username or NO_ACCESS_USERNAME


# ============================================================================
# ROUTES
# ============================================================================

try:
    from server_app import limiter

    LIMITER_AVAILABLE = True
except ImportError:
    LIMITER_AVAILABLE = False


def conditional_limit(limit_string, **kwargs):
    """Apply rate limit only if limiter is available, support method filtering"""

    def decorator(f):
        if LIMITER_AVAILABLE and limiter is not None:
            return limiter.limit(limit_string, **kwargs)(f)
        return f

    return decorator


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@conditional_limit("3 per 15 minute")
def forgot_password():
    """Request a password reset link via email"""
    if "user_id" in session:
        return redirect(url_for("dashboard.dashboard_home"))

    if request.method == "POST":
        if not validate_csrf_token():
            flash("The page has expired. Please try again.", "warning")
            return render_template("auth/forgot_password.html")

        email = request.form.get("email", "").strip()
        if not email:
            flash("Please enter your email address.", "danger")
            return render_template("auth/forgot_password.html")

        user = DashboardUser.query.filter_by(email=email).first()
        if user:
            # Generate token and send email
            svc = get_password_reset_service()
            token = svc.generate_reset_token(user.id)
            if svc.send_reset_email(user, token):
                logger.info(f"[AUTH] Password reset email queued for {email}")
            else:
                logger.error(f"[AUTH] Failed to send email to {email}")
                flash(
                    "An error occurred while sending the email. Please contact the administrator.",
                    "danger",
                )
                return render_template("auth/forgot_password.html")

        # Always show success regardless of whether email exists to prevent email enumeration
        flash(
            "If an account exists with that email, a password reset link has been sent.",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Reset password using a token from an email link"""
    if "user_id" in session:
        return redirect(url_for("dashboard.dashboard_home"))

    svc = get_password_reset_service()
    is_valid, user = svc.validate_reset_token(token)

    if not is_valid:
        flash("Invalid or expired reset link. Please request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        if not validate_csrf_token():
            flash("The page has expired. Please try again.", "warning")
            return render_template("auth/reset_password.html", token=token)

        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not new_password or not confirm_password:
            flash("Please fill out all fields.", "danger")
            return render_template("auth/reset_password.html", token=token)

        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("auth/reset_password.html", token=token)

        # FR-006d: same policy at reset as at creation and change.
        policy_error = validate_password_policy(
            new_password,
            auth_type=getattr(user, "auth_type", "local"),
            role=getattr(user, "role", "user"),
        )
        if policy_error:
            flash(policy_error, "danger")
            return render_template("auth/reset_password.html", token=token)

        if svc.reset_user_password(token, new_password):
            flash(
                "Your password has been reset successfully. You can now log in.",
                "success",
            )
            logger.info(
                f"[AUTH] Password successfully reset for {user.username} via token"
            )
            return redirect(url_for("auth.login"))
        else:
            flash("Error resetting password. The link may have expired.", "danger")
            return redirect(url_for("auth.forgot_password"))

    return render_template("auth/reset_password.html", token=token)


@auth_bp.route("/login", methods=["GET", "POST"])
@conditional_limit("10 per 15 minutes", methods=["POST"])  # Only rate limit login attempts
def login():
    """Login page and handler"""
    # If already logged in, redirect to dashboard
    if "user_id" in session:
        return redirect(url_for("dashboard.dashboard_home"))

    if request.method == "POST":
        # CSRF validation
        if not validate_csrf_token():
            logger.warning(
                f"[AUTH] Login rejected due to invalid or expired CSRF token from {request.remote_addr}"
            )
            flash("The page has expired. Please try again.", "warning")
            return render_template("auth/login.html")

        username = request.form.get("username", "").strip()[:100]  # Truncate overlong inputs
        password = request.form.get("password", "")[:128]  # Truncate overlong inputs

        # Validate username format (supports AD formats)
        is_valid, msg = validate_login_username(username)
        if not is_valid:
            flash(msg, "danger")
            return render_template("auth/login.html")

        # Validate password exists + min length
        if not password:
            # Log failed attempt - no password
            _log_login_attempt(None, username, "local", request, False, "No password provided")
            time.sleep(0.5)  # Constant-time delay to prevent timing attacks
            flash("Please enter username and password.", "danger")
            return render_template("auth/login.html")
        # Feature 037 / FR-006f: deliberately NO password-policy check at sign-in.
        # Login verifies against the stored credential, never against the current
        # policy. Checking policy here would reject every existing user whose
        # password predates a policy change — exactly what FR-006f forbids ("no
        # one is locked out by the change"). It also stops no attacker; it only
        # tells one what the minimum length is.

        user = DashboardUser.query.filter_by(username=username).first()

        # If not found by username, try to find by linked_username (AD username login)
        # This allows users to login with their AD username directly
        if not user:
            # Parse input username to match linked_username exactly (DOMAIN\user or bare user)
            search_term = username
            if "\\" in username:
                search_term = username.split("\\")[-1]  # Extract bare user from DOMAIN\user
            
            user = DashboardUser.query.filter(
                (DashboardUser.linked_username == username) |  # Exact DOMAIN\user match
                (DashboardUser.linked_username == search_term)   # Exact bare user match
            ).first()

            if user and user.auth_type == "ad":
                logger.info(
                    f"[AUTH] Found user via linked_username: {user.username} for AD username: {username}"
                )

        # Track AD server failures for circuit breaker
        ad_failure_key = f"ad_failure_count_{username}"
        ad_failure_count = int(session.get(ad_failure_key, 0))

        if user:
            # Lockout switched off by configuration (MAX_FAILED_LOGIN_ATTEMPTS=0).
            # Clear a lock left over from when it was enabled rather than
            # stranding the account — this is what makes the setting take effect
            # for accounts that are ALREADY locked, with no SQL required.
            # Committed here because two paths below return without a commit
            # (AD circuit breaker, deactivated account).
            if user.is_locked and not LOCKOUT_ENABLED:
                logger.info(
                    f"[AUTH] Lockout disabled by configuration; clearing "
                    f"existing lock on: {username}"
                )
                user.is_locked = False
                user.failed_login_count = 0
                user.locked_until = None
                db.session.commit()

            # Check if account is locked
            if user.is_locked:
                # locked_until is a naive-UTC column; compare naive-to-naive.
                # Comparing it against an aware datetime.now(timezone.utc) used
                # to raise TypeError here, which made this branch a 500 and left
                # the account locked forever because the expiry/unlock path
                # below was never reached.
                locked_until = as_naive_utc(user.locked_until)
                now_naive = utcnow_naive()
                if locked_until and locked_until > now_naive:
                    # total_seconds(), not .seconds: the latter discards the
                    # days component and misreports negative deltas. +1 so a
                    # sub-minute remainder never displays as "0 minutes".
                    remaining = int((locked_until - now_naive).total_seconds() // 60) + 1
                    # The lockout is RECORDED but never DISCLOSED.
                    #
                    # "Account is locked" told an unauthenticated caller that the
                    # username exists, and since anyone can *cause* a lockout with
                    # MAX_FAILED_ATTEMPTS bad guesses, that was a username oracle
                    # on demand. The caller now gets the same message, and the same
                    # 0.5s delay, as every other failure — so neither the text nor
                    # the response time distinguishes this branch. The real reason
                    # goes to the audit table and the server log, where an admin
                    # investigating a lockout can actually see it.
                    _log_login_attempt(
                        user.id,
                        username,
                        user.auth_type,
                        request,
                        False,
                        f"Account locked, {remaining} minutes remaining",
                    )
                    logger.warning(
                        f"[AUTH] Login attempt on locked account: {username} "
                        f"({remaining} minutes remaining)"
                    )
                    time.sleep(0.5)  # Constant-time delay, matches other failure branches
                    flash("Invalid username or password.", "danger")
                    return render_template("auth/login.html")
                else:
                    # Lockout period has passed, unlock
                    user.is_locked = False
                    user.failed_login_count = 0
                    user.locked_until = None

            # Check password
            ad_auth_success = False
            if user.auth_type == "ad":
                # AD circuit breaker: if 3+ recent failures, skip AD
                if ad_failure_count >= 3:
                    flash("AD authentication temporarily unavailable. Try local password if set.", "warning")
                    logger.warning(f"[AUTH] AD circuit breaker triggered for {username}")
                    time.sleep(0.5)
                    return render_template("auth/login.html")
                
                # AD authentication
                from ad_auth import authenticate_ldap

                ad_success, ad_message = authenticate_ldap(
                    username=username,
                    password=password,
                    linked_username=user.linked_username,
                )
                if ad_success:
                    ad_auth_success = True
                    # Reset failure count on success
                    session[ad_failure_key] = 0
                    _log_login_attempt(user.id, username, "ad", request, True)
                    logger.info(f"[AUTH] AD login successful: {username}")
                else:
                    # Track AD failure for circuit breaker
                    session[ad_failure_key] = ad_failure_count + 1
                    # Check for local password fallback
                    if user.password_hash and user.password_hash.startswith("pbkdf2"):
                        # Try local password as fallback
                        if user.check_password(password):
                            ad_auth_success = True
                            _log_login_attempt(user.id, username, "ad", request, True, "AD failed, used local fallback")
                            logger.info(
                                f"[AUTH] AD failed, used local fallback: {username}"
                            )
                        else:
                            ad_auth_success = False
                            _log_login_attempt(user.id, username, "ad", request, False, "Invalid password")
                    else:
                        _log_login_attempt(user.id, username, "ad", request, False, "AD auth failed")
                        logger.warning(
                            f"[AUTH] AD login failed, no local fallback: {username}"
                        )
                        time.sleep(0.5)  # Constant-time delay
                        # Do NOT return early: fall through to the shared lockout
                        # handling below (ad_auth_success stays False) so AD-only
                        # accounts accrue failed_login_count and can be locked out.
            else:
                # Local authentication
                ad_auth_success = user.check_password(password)
                if not ad_auth_success:
                    _log_login_attempt(user.id, username, "local", request, False, "Invalid password")
                    time.sleep(0.5)  # Constant-time delay

            if ad_auth_success:
                if not user.is_active:
                    flash(
                        "Your account has been deactivated. Contact administrator.",
                        "danger",
                    )
                    logger.warning(
                        f"[AUTH] Login attempt on deactivated account: {username}"
                    )
                    return render_template("auth/login.html")

                # Success! Create session
                session.clear()  # Prevent session fixation
                session["user_id"] = user.id
                session["username"] = user.username
                session["role"] = user.role
                session["session_version"] = (
                    user.session_version
                )  # Track session validity
                session.permanent = True

                # FR-002a: bind this sign-in to the tab that performed it. The
                # cookie above is shared by every tab in the browser; this token
                # is not, and the server row is what decides whether it is still
                # valid. The raw token is handed to the page once and stored in
                # sessionStorage by tab_session.js — only its hash is persisted.
                session["tab_token"] = issue_tab_session(user)

                # Update user record.
                # FR-002e: a successful sign-in resets the failed-attempt counter,
                # so a legitimate user signing in across several tabs can never
                # lock their own account.
                user.failed_login_count = 0
                # D02 / FR-009: store NAIVE UTC.
                #
                # This wrote datetime.now(timezone.utc) — an AWARE value — into a
                # naive db.DateTime column, while every other timestamp in the
                # schema (created_at, updated_at, agent last_seen) stores naive
                # UTC. Whether the offset survives that write is driver-dependent,
                # and a value that is sometimes aware and sometimes naive cannot be
                # interpreted consistently on read.
                #
                # utils.datetime_format treats a naive value as UTC and converts it
                # to the viewer's timezone for display, which is what makes the
                # displayed sign-in time correct rather than 5.5 hours out for an
                # IST viewer — the reported "last logged in time is showing wrong".
                user.last_login = utcnow_naive()
                db.session.commit()
                
                # Log successful login
                _log_login_attempt(user.id, username, user.auth_type, request, True)

                logger.info(f"[AUTH] Login successful: {username} (role: {user.role})")
                flash(f"Welcome back, {username}!", "success")

                # Redirect based on user role
                next_page = request.args.get("next", "")
                # Strict allowlist: only relative paths starting with single /, no protocol-relative URLs
                if next_page and next_page.startswith("/") and "//" not in next_page and "://" not in next_page:
                    return redirect(next_page)

                # Role-based redirect
                if user.role == "admin":
                    return redirect(url_for("dashboard.dashboard_home"))
                else:
                    # Non-admin users: redirect to agent detail page
                    from server_dashboard import get_user_agent_id

                    agent_id = get_user_agent_id(user)
                    if agent_id:
                        return redirect(
                            url_for("dashboard.agent_detail", agent_id=agent_id)
                        )
                    else:
                        return redirect(url_for("dashboard.agents_detail"))
            else:
                # Wrong password
                user.failed_login_count += 1
                if LOCKOUT_ENABLED and user.failed_login_count >= MAX_FAILED_ATTEMPTS:
                    user.is_locked = True
                    # D02 / FR-009: store NAIVE UTC, matching last_login below
                    # and every other db.DateTime column in the schema.
                    user.locked_until = utcnow_naive() + timedelta(
                        minutes=LOCKOUT_DURATION_MINUTES
                    )
                    logger.warning(
                        f"[AUTH] Account locked after {MAX_FAILED_ATTEMPTS} failed attempts: {username}"
                    )
                elif LOCKOUT_ENABLED:
                    remaining = MAX_FAILED_ATTEMPTS - user.failed_login_count
                    logger.warning(
                        f"[AUTH] Failed login attempt for: {username} ({remaining} attempts remaining)"
                    )
                else:
                    logger.warning(
                        f"[AUTH] Failed login attempt for: {username} (lockout disabled)"
                    )
                # One message for every wrong-password outcome. Announcing
                # "Account locked due to too many failed attempts" was the other
                # half of the username oracle: an unknown username never reaches
                # this branch, so five guesses confirmed the account exists.
                flash("Invalid username or password.", "danger")
                db.session.commit()
        else:
            # User doesn't exist - don't reveal this
            logger.warning(f"[AUTH] Login attempt for non-existent user: {username}")
            time.sleep(0.5)  # Constant-time delay, matches other failure branches (no enumeration)
            flash("Invalid username or password.", "danger")

        return render_template("auth/login.html")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    """
    Sign out.

    Scenario 1a: signing out in ANY tab ends every tab that user has open.
    Clearing the cookie alone would leave other tabs holding valid tab tokens,
    so the sign-out would appear not to have worked in them.
    """
    username = session.get("username", "Unknown")
    user_id = session.get("user_id")
    if user_id:
        revoked = revoke_user_tab_sessions(user_id, TabSession.REASON_SIGNED_OUT)
        logger.info(f"[AUTH] Sign-out revoked {revoked} tab session(s) for {username}")
    session.clear()
    logger.info(f"[AUTH] User logged out: {username}")
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Change own password"""
    if request.method == "POST":
        # CSRF validation
        if not validate_csrf_token():
            flash("The page has expired. Please try again.", "warning")
            return render_template("auth/change_password.html")

        current = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        # D20: an Active-Directory account has no local password to change. It
        # previously fell through to check_password(), which passed a NULL hash
        # to Werkzeug and raised — producing the internal server error page QA
        # reported. Saying so plainly is the correct outcome (FR-005).
        if (g.current_user.auth_type or "local").lower() == "ad":
            flash(
                "Your account signs in through your organisation's directory, "
                "so your password is managed there and cannot be changed here.",
                "danger",
            )
            return render_template("auth/change_password.html")

        if not g.current_user.check_password(current):
            flash("Current password is incorrect.", "danger")
            return render_template("auth/change_password.html")

        # Check if new password is same as current
        if g.current_user.check_password(new_password):
            flash("New password cannot be the same as current password.", "danger")
            return render_template("auth/change_password.html")

        if new_password != confirm:
            flash("New passwords do not match.", "danger")
            return render_template("auth/change_password.html")

        policy_error = validate_password_policy(
            new_password,
            auth_type=g.current_user.auth_type,
            role=g.current_user.role,
        )
        if policy_error:
            flash(policy_error, "danger")
            return render_template("auth/change_password.html")

        # Increment session version to invalidate other devices (FR-003).
        g.current_user.session_version += 1
        g.current_user.set_password(new_password)
        # FR-006f: the new password passed validate_password_policy above, so
        # the forced-rotation hold is satisfied and must be released — otherwise
        # the user is redirected back here forever.
        g.current_user.must_change_password = False
        db.session.commit()

        # Keep the user logged into *this* specific session they just used
        session["session_version"] = g.current_user.session_version

        logger.info(f"[AUTH] Password changed: {g.current_user.username}")
        flash(
            "Password changed successfully. All other devices have been logged out.",
            "success",
        )
        return redirect(url_for("dashboard.dashboard_home"))

    return render_template("auth/change_password.html")


# ============================================================================
# ADMIN: USER MANAGEMENT
# ============================================================================


@auth_bp.route("/users")
@admin_required
def list_users():
    """List all dashboard users (admin only)"""
    users = DashboardUser.query.order_by(DashboardUser.username).all()
    return render_template("auth/users.html", users=users)


@auth_bp.route("/users/list")
@login_required
@admin_required
def list_users_json():
    """Return dashboard users as JSON for report recipient picker (BUG-012)."""
    users = DashboardUser.query.order_by(DashboardUser.username).all()
    return jsonify([{
        'username': u.username,
        'email': u.email or '',
        'role': u.role,
    } for u in users])


@auth_bp.route("/users/add", methods=["GET", "POST"])
@admin_required
def add_user():
    """Add new dashboard user (admin only)"""
    # Get available Windows usernames from agents for dropdown
    import server_models

    available_usernames = (
        db.session.query(server_models.AgentCurrentStatus.username)
        .filter(server_models.AgentCurrentStatus.username.isnot(None))
        .distinct()
        .order_by(server_models.AgentCurrentStatus.username)
        .all()
    )
    available_usernames = [u[0] for u in available_usernames if u[0]]
    available_login_usernames = sorted(
        {
            username.split("\\")[-1].strip()
            for username in available_usernames
            if username and username.split("\\")[-1].strip()
        },
        key=str.lower,
    )

    if request.method == "POST":
        # CSRF validation
        if not validate_csrf_token():
            flash("Invalid request. Please try again.", "danger")
            return render_template(
                "auth/add_user.html",
                available_usernames=available_usernames,
                available_login_usernames=available_login_usernames,
            )

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")
        linked_username = request.form.get("linked_username", "").strip()
        auth_type = request.form.get("auth_type", "local")
        email = request.form.get("email", "").strip()

        # Validate based on auth type
        if auth_type == "local":
            if not username or not password:
                flash("Username and password are required for local auth.", "danger")
                return render_template(
                    "auth/add_user.html",
                    available_usernames=available_usernames,
                    available_login_usernames=available_login_usernames,
                )
            policy_error = validate_password_policy(
                password, auth_type=auth_type, role=role
            )
            if policy_error:
                flash(policy_error, "danger")
                return render_template(
                    "auth/add_user.html",
                    available_usernames=available_usernames,
                    available_login_usernames=available_login_usernames,
                )
        else:
            # AD auth - username and linked_username required
            if not username:
                flash("Username is required.", "danger")
                return render_template(
                    "auth/add_user.html",
                    available_usernames=available_usernames,
                    available_login_usernames=available_login_usernames,
                )
            if not linked_username:
                flash("Linked Windows Username is required for AD auth.", "danger")
                return render_template(
                    "auth/add_user.html",
                    available_usernames=available_usernames,
                    available_login_usernames=available_login_usernames,
                )

        if DashboardUser.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
            return render_template(
                "auth/add_user.html",
                available_usernames=available_usernames,
                available_login_usernames=available_login_usernames,
            )

        # Password policy applies to local accounts only; validate_password_policy
        # exempts AD accounts itself (FR-006a), so the gate is kept for clarity.
        policy_error = validate_password_policy(
            password, auth_type=auth_type, role=role
        )
        if policy_error:
            flash(policy_error, "danger")
            return render_template(
                "auth/add_user.html",
                available_usernames=available_usernames,
                available_login_usernames=available_login_usernames,
            )

        if linked_username and not check_linked_username_unique(linked_username):
            flash("This Windows username is already linked to another user.", "danger")
            return render_template(
                "auth/add_user.html",
                available_usernames=available_usernames,
                available_login_usernames=available_login_usernames,
            )

        user = DashboardUser(
            username=username,
            email=email,
            role=role,
            linked_username=linked_username if linked_username else None,
            auth_type=auth_type,
        )
        # Only set password for local auth
        if auth_type == "local" and password:
            user.set_password(password)

        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("This Windows username is already linked to another user.", "danger")
            return render_template(
                "auth/add_user.html",
                available_usernames=available_usernames,
                available_login_usernames=available_login_usernames,
            )

        logger.info(
            f"[AUTH] User created by {g.current_user.username}: {username} (role: {role})"
        )
        flash(f'User "{username}" created successfully.', "success")
        return redirect(url_for("auth.list_users"))

    return render_template(
        "auth/add_user.html",
        available_usernames=available_usernames,
        available_login_usernames=available_login_usernames,
    )


@auth_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id):
    """Edit dashboard user (admin only)"""
    user = DashboardUser.query.get_or_404(user_id)

    if request.method == "POST":
        # CSRF validation
        if not validate_csrf_token():
            flash("Invalid request. Please try again.", "danger")
            return render_template("auth/edit_user.html", user=user)

        role = request.form.get("role", "user")
        linked_username = request.form.get("linked_username", "").strip()
        email = request.form.get("email", "").strip()
        is_active = request.form.get("is_active") == "on"
        auth_type = request.form.get("auth_type", "local")

        # Validate for AD auth
        if auth_type == "ad" and not linked_username:
            flash("Linked Windows Username is required for AD auth.", "danger")
            return render_template("auth/edit_user.html", user=user)

        # Email is optional - removed required constraint

        if linked_username and not check_linked_username_unique(
            linked_username, exclude_user_id=user.id
        ):
            flash("This Windows username is already linked to another user.", "danger")
            return render_template("auth/edit_user.html", user=user)

        # FR-006g: promoting a user to administrator applies the stricter admin
        # rule from that point. The password they already have was only ever
        # checked against the weaker user rule, so require a compliant one at
        # next sign-in unless they set one in this same request (handled below,
        # which validates against the NEW role and clears the flag).
        was_admin = (user.role or "user").lower() == "admin"
        user.role = role
        if not was_admin and (role or "user").lower() == "admin":
            user.must_change_password = True
        user.email = email
        user.linked_username = linked_username if linked_username else None
        user.auth_type = auth_type
        user.is_active = is_active

        # Reset password if provided
        new_password = request.form.get("new_password", "").strip()
        if new_password:
            # Validated against the account's role AFTER any role change made
            # on this same form, so promoting a user to admin and setting a
            # password in one action applies the stricter admin rule (FR-006g).
            policy_error = validate_password_policy(
                new_password, auth_type=user.auth_type, role=user.role
            )
            if policy_error:
                flash(policy_error, "danger")
                return render_template("auth/edit_user.html", user=user)
            user.set_password(new_password)
            # FR-006f/g: this password was validated against the account's role
            # as it stands after any change made on this same form, so a forced
            # rotation hold set above (promotion to admin) is already satisfied.
            user.must_change_password = False
            # Invalidate any existing sessions for this user - an admin-driven
            # reset must not leave a previously-hijacked session valid.
            user.session_version = (user.session_version or 1) + 1
            logger.info(f"[AUTH] Password reset by admin for: {user.username}")

        # Unlock if locked
        if user.is_locked:
            user.is_locked = False
            user.failed_login_count = 0
            user.locked_until = None
            logger.info(f"[AUTH] Account unlocked by admin: {user.username}")

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("This Windows username is already linked to another user.", "danger")
            return render_template("auth/edit_user.html", user=user)

        logger.info(
            f"[AUTH] User updated by {g.current_user.username}: {user.username}"
        )
        flash(f'User "{user.username}" updated successfully.', "success")
        return redirect(url_for("auth.list_users"))

    return render_template("auth/edit_user.html", user=user)


@auth_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    """Delete dashboard user (admin only)"""
    # CSRF validation
    if not validate_csrf_token():
        flash("Invalid request. Please try again.", "danger")
        return redirect(url_for("auth.list_users"))

    user = DashboardUser.query.get_or_404(user_id)

    # Prevent deleting yourself
    if user.id == g.current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("auth.list_users"))

    username = user.username
    db.session.delete(user)
    db.session.commit()

    logger.info(f"[AUTH] User deleted by {g.current_user.username}: {username}")
    flash(f'User "{username}" deleted.', "success")
    return redirect(url_for("auth.list_users"))


# ============================================================================
# API ENDPOINTS (for AJAX)
# ============================================================================


@auth_bp.route("/api/me")
@login_required
def api_me():
    """Get current user info"""
    return jsonify(g.current_user.to_dict())


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def create_default_admin():
    """Create default admin user and organization if none exists"""
    import server_models

    # Ensure default organization exists
    default_org = server_models.Organization.query.filter_by(slug="default").first()
    if not default_org:
        default_org = server_models.Organization(
            name="Default Organization", slug="default"
        )
        db.session.add(default_org)
        db.session.commit()
        logger.info("[AUTH] Default organization created")

    if DashboardUser.query.filter_by(role="admin").first():
        return False  # Admin already exists

    admin = DashboardUser(
        username="admin", role="admin", org_id=default_org.id, is_active=True
    )
    admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "changeme123")
    admin.set_password(admin_password)

    db.session.add(admin)
    db.session.commit()

    if admin_password == "changeme123":
        logger.info(
            "[AUTH] Default admin user created: admin / changeme123 (linked to Default Org)"
        )
    else:
        logger.info(
            "[AUTH] Default admin user created: admin / <DEFAULT_ADMIN_PASSWORD from .env> (linked to Default Org)"
        )
    return True


# C-09 FIX: Removed init_auth() function that was overriding SESSION_COOKIE_SECURE
# Cookie security is now properly configured in server_app.py based on config.USE_TLS
