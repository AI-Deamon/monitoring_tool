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
from extensions import db
import logging
import os
import secrets
import re
import time

logger = logging.getLogger(__name__)


# Lazy import to avoid circular dependency
def get_password_reset_service():
    from password_reset import PasswordResetService

    return PasswordResetService


# ============================================================================
# VALIDATION HELPERS
# ============================================================================


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
    """Generate CSRF token for forms"""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf_token():
    """Validate CSRF token from form submission"""
    form_token = request.form.get("csrf_token", "")
    session_token = session.get("csrf_token", "")

    if not form_token or not session_token:
        logger.warning(
            f"[CSRF] Missing token - Form: {bool(form_token)}, Session: {bool(session_token)}"
        )
        return False

    # Use constant-time comparison
    if secrets.compare_digest(form_token, session_token):
        return True

    logger.warning(f"[CSRF] Token mismatch from {request.remote_addr}")
    return False


def csrf_protect(f):
    """Decorator to require CSRF token on POST requests"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == "POST":
            if not validate_csrf_token():
                flash("Invalid request. Please try again.", "danger")
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
        """Verify password"""
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


# ============================================================================
# CONFIGURATION
# ============================================================================

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30
SESSION_LIFETIME_HOURS = 8


# ============================================================================
# DECORATORS
# ============================================================================


def login_required(f):
    """Decorator: Require user to be logged in"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.url))

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
            flash(
                "Your session has expired or your password was changed. Please log in again.",
                "warning",
            )
            return redirect(url_for("auth.login"))

        # Store user in g for access in views
        g.current_user = user
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Decorator: Require user to be admin"""

    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if g.current_user.role != "admin":
            flash("Administrator access required.", "danger")
            return redirect(url_for("dashboard.dashboard_home"))
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
                    server_models.AgentCurrentStatus.username.ilike(
                        f"{linked_username}%"
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
                    server_models.ScreenTime.username.ilike(f"{linked_username}%"),
                )
            )
            .first()
        )

        return screen_time is not None

    return False


def get_user_filter():
    """Get filter for queries based on user role"""
    if not hasattr(g, "current_user") or not g.current_user:
        return None

    if g.current_user.role == "admin":
        return None  # No filter for admin

    # User: filter by linked username
    return g.current_user.linked_username


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
            flash("Invalid request. Please try again.", "danger")
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
            flash("Invalid request. Please try again.", "danger")
            return render_template("auth/reset_password.html", token=token)

        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not new_password or not confirm_password:
            flash("Please fill out all fields.", "danger")
            return render_template("auth/reset_password.html", token=token)

        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("auth/reset_password.html", token=token)

        if len(new_password) < 8:
            flash("Password must be at least 8 characters.", "danger")
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
            flash("Invalid request. Please try again.", "danger")
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
        if len(password) < 8:
            _log_login_attempt(None, username, "local", request, False, "Password too short")
            time.sleep(0.5)  # Constant-time delay
            flash("Password must be at least 8 characters.", "danger")
            return render_template("auth/login.html")

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
            # Check if account is locked
            if user.is_locked:
                if user.locked_until and user.locked_until > datetime.now(timezone.utc):
                    remaining = (
                        user.locked_until - datetime.now(timezone.utc)
                    ).seconds // 60
                    flash(
                        f"Account is locked. Try again in {remaining} minutes.",
                        "danger",
                    )
                    logger.warning(
                        f"[AUTH] Login attempt on locked account: {username}"
                    )
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
                        flash("Invalid username or password.", "danger")
                        logger.warning(
                            f"[AUTH] AD login failed, no local fallback: {username}"
                        )
                        time.sleep(0.5)  # Constant-time delay
                        return render_template("auth/login.html")
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

                # Update user record
                user.failed_login_count = 0
                user.last_login = datetime.now(timezone.utc)
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
                if user.failed_login_count >= MAX_FAILED_ATTEMPTS:
                    user.is_locked = True
                    user.locked_until = datetime.now(timezone.utc) + timedelta(
                        minutes=LOCKOUT_DURATION_MINUTES
                    )
                    logger.warning(
                        f"[AUTH] Account locked after {MAX_FAILED_ATTEMPTS} failed attempts: {username}"
                    )
                    flash(
                        f"Account locked due to too many failed attempts. Try again in {LOCKOUT_DURATION_MINUTES} minutes.",
                        "danger",
                    )
                else:
                    remaining = MAX_FAILED_ATTEMPTS - user.failed_login_count
                    logger.warning(
                        f"[AUTH] Failed login attempt for: {username} ({remaining} attempts remaining)"
                    )
                    flash("Invalid username or password.", "danger")
                db.session.commit()
        else:
            # User doesn't exist - don't reveal this
            logger.warning(f"[AUTH] Login attempt for non-existent user: {username}")
            flash("Invalid username or password.", "danger")

        return render_template("auth/login.html")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    """Logout and clear session"""
    username = session.get("username", "Unknown")
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
            flash("Invalid request. Please try again.", "danger")
            return render_template("auth/change_password.html")

        current = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

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

        if len(new_password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("auth/change_password.html")

        # Increment session version to invalidate other devices
        g.current_user.session_version += 1
        g.current_user.set_password(new_password)
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
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "danger")
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

        # Password validation only for local auth
        if auth_type == "local" and len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
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
        db.session.commit()

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

        user.role = role
        user.email = email
        user.linked_username = linked_username if linked_username else None
        user.auth_type = auth_type
        user.is_active = is_active

        # Reset password if provided
        new_password = request.form.get("new_password", "").strip()
        if new_password:
            if len(new_password) < 8:
                flash("Password must be at least 8 characters.", "danger")
                return render_template("auth/edit_user.html", user=user)
            user.set_password(new_password)
            logger.info(f"[AUTH] Password reset by admin for: {user.username}")

        # Unlock if locked
        if user.is_locked:
            user.is_locked = False
            user.failed_login_count = 0
            user.locked_until = None
            logger.info(f"[AUTH] Account unlocked by admin: {user.username}")

        db.session.commit()

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
    admin.set_password("changeme123")

    db.session.add(admin)
    db.session.commit()

    logger.info(
        "[AUTH] Default admin user created: admin / changeme123 (linked to Default Org)"
    )
    return True


def init_auth(app):
    """Initialize authentication module"""
    # Set session configuration
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=SESSION_LIFETIME_HOURS)
    app.config["SESSION_COOKIE_SECURE"] = False  # Set to True when using HTTPS
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Register blueprint
    app.register_blueprint(auth_bp)

    # Note: Schema now managed exclusively via Alembic migrations.
    # db.create_all() removed.
    with app.app_context():
        create_default_admin()
