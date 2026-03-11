"""
Password Reset Module
====================
Handles generation, validation, and usage of password reset tokens, as well as sending emails.
"""

from datetime import datetime, timedelta
from sqlalchemy import text
from flask import current_app, url_for
import secrets
import hashlib
import logging
from extensions import db
from auth import DashboardUser

logger = logging.getLogger(__name__)

class PasswordResetToken(db.Model):
    """Password reset token storage"""
    __tablename__ = 'password_reset_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('dashboard_users.id', ondelete='CASCADE'), nullable=False)
    token_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=text('CURRENT_TIMESTAMP'))
    
    # Relationships
    user = db.relationship('DashboardUser', backref=db.backref('reset_tokens', lazy='dynamic'))
    
    @classmethod
    def cleanup_expired(cls):
        """Remove expired tokens"""
        expired_tokens = cls.query.filter(cls.expires_at < datetime.utcnow()).all()
        for token in expired_tokens:
            db.session.delete(token)
        db.session.commit()
    
    def is_valid(self):
        """Check if token is valid and not used"""
        return (
            self.expires_at > datetime.utcnow() and 
            self.used_at is None
        )

class PasswordResetService:
    """Service for password reset operations"""
    
    TOKEN_EXPIRY_HOURS = 1  # 1 hour expiry
    TOKEN_LENGTH = 32       # 32 bytes = 64 hex chars
    
    @classmethod
    def generate_reset_token(cls, user_id: int) -> str:
        """Generate a secure reset token"""
        token = secrets.token_hex(cls.TOKEN_LENGTH)
        token_hash = cls._hash_token(token)
        
        expires_at = datetime.utcnow() + timedelta(hours=cls.TOKEN_EXPIRY_HOURS)
        
        reset_token = PasswordResetToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at
        )
        
        db.session.add(reset_token)
        db.session.commit()
        
        logger.info(f"[AUTH] Generated reset token for user {user_id}")
        return token
    
    @classmethod
    def validate_reset_token(cls, token: str) -> tuple[bool, DashboardUser]:
        """Validate reset token and return user if valid"""
        token_hash = cls._hash_token(token)
        
        reset_token = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
        
        if not reset_token:
            logger.warning("[AUTH] Invalid reset token attempted")
            return False, None
            
        if not reset_token.is_valid():
            logger.warning(f"[AUTH] Expired or used reset token attempted for user {reset_token.user_id}")
            return False, None
            
        return True, reset_token.user
    
    @classmethod
    def reset_user_password(cls, token: str, new_password: str) -> bool:
        """Reset user password using valid token"""
        is_valid, user = cls.validate_reset_token(token)
        
        if not is_valid or not user:
            return False
            
        # Update password
        user.set_password(new_password)
        
        # Atomically mark token as used to prevent race conditions
        token_hash_val = cls._hash_token(token)
        result = db.session.execute(
            db.update(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash_val)
            .where(PasswordResetToken.used_at.is_(None))
            .values(used_at=datetime.utcnow())
        )
        
        if result.rowcount == 0:
            logger.warning(f"[AUTH] Token race condition mitigated for user {user.id}")
            db.session.rollback()
            return False
        
        # Reset any active lockouts
        user.is_locked = False
        user.failed_login_count = 0
        user.locked_until = None
        
        db.session.commit()
        logger.info(f"[AUTH] Password reset successful for user {user.username}")
        return True
        
    @classmethod
    def send_reset_email(cls, user: DashboardUser, token: str) -> bool:
        """Send password reset email"""
        try:
            from flask_mail import Mail, Message
            
            # Ensure mail is configured on current app
            if not getattr(current_app, 'mail', None):
                current_app.mail = Mail(current_app)
                
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            subject = "SentinelEdge Password Reset"
            body = f"""Hello {user.username},
            
We received a request to reset your SentinelEdge password.

Click the link below to reset your password:
{reset_url}

This link will expire in {cls.TOKEN_EXPIRY_HOURS} hour(s).

If you didn't request this reset, please ignore this email.

Best regards,
SentinelEdge Security Team
"""
            
            msg = Message(
                subject=subject,
                recipients=[user.email],
                body=body
            )
            
            # Use a background thread to send the email to prevent timing attacks
            # (email enumeration) where an attacker measures request duration
            import threading
            
            def send_async_email(app, message):
                with app.app_context():
                    try:
                        app.mail.send(message)
                        logger.info(f"[AUTH] Background password reset email sent to {message.recipients}")
                    except Exception as e:
                        logger.error(f"[AUTH] Background email send failed: {e}", exc_info=True)
            
            app_proxy = current_app._get_current_object()
            thread = threading.Thread(target=send_async_email, args=(app_proxy, msg))
            thread.daemon = True
            thread.start()
            
            logger.info(f"[AUTH] Password reset email queued for background delivery to {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"[AUTH] Failed to send reset email: {e}", exc_info=True)
            return False

    @staticmethod
    def _hash_token(token: str) -> str:
        """Hash token for secure storage"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    @classmethod
    def cleanup_expired_tokens(cls):
        """Clean up expired tokens"""
        PasswordResetToken.cleanup_expired()
