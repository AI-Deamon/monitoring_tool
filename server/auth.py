"""
Dashboard Authentication Module
================================
Provides user authentication, session management, and role-based access control.

Roles:
    - admin: Can view all agents and manage users
    - user: Can only view their linked agent (matched by username)
"""

from functools import wraps
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
import logging
import os
import secrets
import re

logger = logging.getLogger(__name__)

# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def validate_username(username: str) -> tuple[bool, str]:
    """Validate username format (alphanumeric, dots, underscores, hyphens only)"""
    if not username or len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(username) > 50:
        return False, "Username must be less than 50 characters"
    if not re.match(r'^[a-zA-Z0-9._-]+$', username):
        return False, "Username can only contain letters, numbers, dots, underscores, and hyphens"
    return True, ""

def check_linked_username_unique(linked_username: str, exclude_user_id: int = None) -> bool:
    """Check if linked_username is already in use by another user"""
    if not linked_username:
        return True  # Empty is allowed
    query = DashboardUser.query.filter_by(linked_username=linked_username)
    if exclude_user_id:
        query = query.filter(DashboardUser.id != exclude_user_id)
    return query.first() is None

# Blueprint
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


# ============================================================================
# ISSUE-002 FIX: CSRF PROTECTION
# ============================================================================

def generate_csrf_token():
    """Generate CSRF token for forms"""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def validate_csrf_token():
    """Validate CSRF token from form submission"""
    form_token = request.form.get('csrf_token', '')
    session_token = session.get('csrf_token', '')
    
    if not form_token or not session_token:
        logger.warning(f"[CSRF] Missing token - Form: {bool(form_token)}, Session: {bool(session_token)}")
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
        if request.method == 'POST':
            if not validate_csrf_token():
                flash('Invalid request. Please try again.', 'danger')
                return redirect(request.url)
        return f(*args, **kwargs)
    return decorated_function

# Make CSRF token available in all templates
@auth_bp.app_context_processor
def inject_csrf_token():
    return {'csrf_token': generate_csrf_token}


# ============================================================================
# DATABASE MODEL
# ============================================================================

class DashboardUser(db.Model):
    """Dashboard user for authentication"""
    __tablename__ = 'dashboard_users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')  # 'admin' or 'user'
    
    # Link to agent data (for user role - matched by Windows username)
    linked_username = db.Column(db.String(255), nullable=True)  # Windows username from agent
    
    # Account status
    is_active = db.Column(db.Boolean, default=True)
    is_locked = db.Column(db.Boolean, default=False)
    failed_login_count = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def set_password(self, password: str):
        """Hash and set password"""
        # Using pbkdf2 with 600000 iterations (OWASP 2023 recommendation)
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256:600000')
    
    def check_password(self, password: str) -> bool:
        """Verify password"""
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'linked_username': self.linked_username,
            'is_active': self.is_active,
            'is_locked': self.is_locked,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
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
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        # Load current user
        user = DashboardUser.query.filter_by(id=session['user_id']).first()
        if not user or not user.is_active:
            session.clear()
            flash('Your session has expired. Please log in again.', 'warning')
            return redirect(url_for('auth.login'))
        
        # Store user in g for access in views
        g.current_user = user
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator: Require user to be admin"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if g.current_user.role != 'admin':
            flash('Administrator access required.', 'danger')
            return redirect(url_for('dashboard.dashboard_home'))
        return f(*args, **kwargs)
    return decorated_function


def can_view_agent(agent_id: str, username: str = None) -> bool:
    """Check if current user can view a specific agent's data"""
    if not hasattr(g, 'current_user') or not g.current_user:
        return False
    
    # Admin can view all
    if g.current_user.role == 'admin':
        return True
    
    # User can only view their linked data
    # Match by the Windows username from the agent data
    if g.current_user.linked_username:
        # If username is provided (from query), check against it
        if username:
            return g.current_user.linked_username.lower() == username.lower()
        
        # Otherwise, we need to check if this agent has data for the user's linked username
        # This requires querying the database - let the caller handle this
        return True  # Allow, but filter in query
    
    return False


def get_user_filter():
    """Get filter for queries based on user role"""
    if not hasattr(g, 'current_user') or not g.current_user:
        return None
    
    if g.current_user.role == 'admin':
        return None  # No filter for admin
    
    # User: filter by linked username
    return g.current_user.linked_username


# ============================================================================
# ROUTES
# ============================================================================

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page and handler"""
    # If already logged in, redirect to dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard.dashboard_home'))
    
    if request.method == 'POST':
        # CSRF validation
        if not validate_csrf_token():
            flash('Invalid request. Please try again.', 'danger')
            return render_template('auth/login.html')
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Please enter username and password.', 'danger')
            return render_template('auth/login.html')
        
        user = DashboardUser.query.filter_by(username=username).first()
        
        if user:
            # Check if account is locked
            if user.is_locked:
                if user.locked_until and user.locked_until > datetime.utcnow():
                    remaining = (user.locked_until - datetime.utcnow()).seconds // 60
                    flash(f'Account is locked. Try again in {remaining} minutes.', 'danger')
                    logger.warning(f"[AUTH] Login attempt on locked account: {username}")
                    return render_template('auth/login.html')
                else:
                    # Lockout period has passed, unlock
                    user.is_locked = False
                    user.failed_login_count = 0
                    user.locked_until = None
            
            # Check password
            if user.check_password(password):
                if not user.is_active:
                    flash('Your account has been deactivated. Contact administrator.', 'danger')
                    logger.warning(f"[AUTH] Login attempt on deactivated account: {username}")
                    return render_template('auth/login.html')
                
                # Success! Create session
                session.clear()  # Prevent session fixation
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role
                session.permanent = True
                
                # Update user record
                user.failed_login_count = 0
                user.last_login = datetime.utcnow()
                db.session.commit()
                
                logger.info(f"[AUTH] Login successful: {username} (role: {user.role})")
                flash(f'Welcome back, {username}!', 'success')
                
                # Redirect to intended page or dashboard
                next_page = request.args.get('next')
                if next_page and next_page.startswith('/'):
                    return redirect(next_page)
                return redirect(url_for('dashboard.dashboard_home'))
            else:
                # Wrong password
                user.failed_login_count += 1
                if user.failed_login_count >= MAX_FAILED_ATTEMPTS:
                    user.is_locked = True
                    user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                    logger.warning(f"[AUTH] Account locked after {MAX_FAILED_ATTEMPTS} failed attempts: {username}")
                    flash(f'Account locked due to too many failed attempts. Try again in {LOCKOUT_DURATION_MINUTES} minutes.', 'danger')
                else:
                    remaining = MAX_FAILED_ATTEMPTS - user.failed_login_count
                    logger.warning(f"[AUTH] Failed login attempt for: {username} ({remaining} attempts remaining)")
                    flash('Invalid username or password.', 'danger')
                db.session.commit()
        else:
            # User doesn't exist - don't reveal this
            logger.warning(f"[AUTH] Login attempt for non-existent user: {username}")
            flash('Invalid username or password.', 'danger')
        
        return render_template('auth/login.html')
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    """Logout and clear session"""
    username = session.get('username', 'Unknown')
    session.clear()
    logger.info(f"[AUTH] User logged out: {username}")
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change own password"""
    if request.method == 'POST':
        # CSRF validation
        if not validate_csrf_token():
            flash('Invalid request. Please try again.', 'danger')
            return render_template('auth/change_password.html')
        
        current = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        
        if not g.current_user.check_password(current):
            flash('Current password is incorrect.', 'danger')
            return render_template('auth/change_password.html')
        
        # Check if new password is same as current
        if g.current_user.check_password(new_password):
            flash('New password cannot be the same as current password.', 'danger')
            return render_template('auth/change_password.html')
        
        if new_password != confirm:
            flash('New passwords do not match.', 'danger')
            return render_template('auth/change_password.html')
        
        if len(new_password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('auth/change_password.html')
        
        g.current_user.set_password(new_password)
        db.session.commit()
        
        logger.info(f"[AUTH] Password changed: {g.current_user.username}")
        flash('Password changed successfully.', 'success')
        return redirect(url_for('dashboard.dashboard_home'))
    
    return render_template('auth/change_password.html')


# ============================================================================
# ADMIN: USER MANAGEMENT
# ============================================================================

@auth_bp.route('/users')
@admin_required
def list_users():
    """List all dashboard users (admin only)"""
    users = DashboardUser.query.order_by(DashboardUser.username).all()
    return render_template('auth/users.html', users=users)


@auth_bp.route('/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    """Add new dashboard user (admin only)"""
    # Get available Windows usernames from agents for dropdown
    from sqlalchemy import func
    import server_models
    
    available_usernames = db.session.query(
        server_models.AgentCurrentStatus.username
    ).filter(
        server_models.AgentCurrentStatus.username.isnot(None)
    ).distinct().order_by(server_models.AgentCurrentStatus.username).all()
    available_usernames = [u[0] for u in available_usernames if u[0]]
    
    if request.method == 'POST':
        # CSRF validation
        if not validate_csrf_token():
            flash('Invalid request. Please try again.', 'danger')
            return render_template('auth/add_user.html', available_usernames=available_usernames)
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')
        linked_username = request.form.get('linked_username', '').strip()
        
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('auth/add_user.html', available_usernames=available_usernames)
        
        if DashboardUser.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('auth/add_user.html', available_usernames=available_usernames)
        
        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('auth/add_user.html', available_usernames=available_usernames)
        
        user = DashboardUser(
            username=username,
            role=role,
            linked_username=linked_username if linked_username else None
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        logger.info(f"[AUTH] User created by {g.current_user.username}: {username} (role: {role})")
        flash(f'User "{username}" created successfully.', 'success')
        return redirect(url_for('auth.list_users'))
    
    return render_template('auth/add_user.html', available_usernames=available_usernames)


@auth_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    """Edit dashboard user (admin only)"""
    user = DashboardUser.query.get_or_404(user_id)
    
    if request.method == 'POST':
        # CSRF validation
        if not validate_csrf_token():
            flash('Invalid request. Please try again.', 'danger')
            return render_template('auth/edit_user.html', user=user)
        
        role = request.form.get('role', 'user')
        linked_username = request.form.get('linked_username', '').strip()
        is_active = request.form.get('is_active') == 'on'
        
        user.role = role
        user.linked_username = linked_username if linked_username else None
        user.is_active = is_active
        
        # Reset password if provided
        new_password = request.form.get('new_password', '').strip()
        if new_password:
            if len(new_password) < 8:
                flash('Password must be at least 8 characters.', 'danger')
                return render_template('auth/edit_user.html', user=user)
            user.set_password(new_password)
            logger.info(f"[AUTH] Password reset by admin for: {user.username}")
        
        # Unlock if locked
        if user.is_locked:
            user.is_locked = False
            user.failed_login_count = 0
            user.locked_until = None
            logger.info(f"[AUTH] Account unlocked by admin: {user.username}")
        
        db.session.commit()
        
        logger.info(f"[AUTH] User updated by {g.current_user.username}: {user.username}")
        flash(f'User "{user.username}" updated successfully.', 'success')
        return redirect(url_for('auth.list_users'))
    
    return render_template('auth/edit_user.html', user=user)


@auth_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    """Delete dashboard user (admin only)"""
    # CSRF validation
    if not validate_csrf_token():
        flash('Invalid request. Please try again.', 'danger')
        return redirect(url_for('auth.list_users'))
    
    user = DashboardUser.query.get_or_404(user_id)
    
    # Prevent deleting yourself
    if user.id == g.current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('auth.list_users'))
    
    username = user.username
    db.session.delete(user)
    db.session.commit()
    
    logger.info(f"[AUTH] User deleted by {g.current_user.username}: {username}")
    flash(f'User "{username}" deleted.', 'success')
    return redirect(url_for('auth.list_users'))


# ============================================================================
# API ENDPOINTS (for AJAX)
# ============================================================================

@auth_bp.route('/api/me')
@login_required
def api_me():
    """Get current user info"""
    return jsonify(g.current_user.to_dict())


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def create_default_admin():
    """Create default admin user if none exists"""
    if DashboardUser.query.filter_by(role='admin').first():
        return False  # Admin already exists
    
    admin = DashboardUser(
        username='admin',
        role='admin',
        is_active=True
    )
    admin.set_password('changeme123')
    
    db.session.add(admin)
    db.session.commit()
    
    logger.info("[AUTH] Default admin user created: admin / changeme123")
    return True


def init_auth(app):
    """Initialize authentication module"""
    # Set session configuration
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=SESSION_LIFETIME_HOURS)
    app.config['SESSION_COOKIE_SECURE'] = False  # Set to True when using HTTPS
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Register blueprint
    app.register_blueprint(auth_bp)
    
    # Create tables and default admin
    with app.app_context():
        db.create_all()
        create_default_admin()
