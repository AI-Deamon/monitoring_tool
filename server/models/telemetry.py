"""
Telemetry Models: ScreenTime, AppUsage, AppSession, DomainUsage, DomainSession
"""
from datetime import datetime
from extensions import db
from sqlalchemy.dialects import postgresql


class ScreenTime(db.Model):
    """Daily screen time aggregation.
    
    Fields:
        active_seconds: Time user was actively using the computer
        idle_seconds: Time user was logged in but idle (no input)
        locked_seconds: Time the screen was locked (short lock periods < 2 hours)
        away_seconds: Prolonged locked periods (> 2 hours), indicating user is away
    """
    __tablename__ = 'screen_time'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    date = db.Column(db.Date, nullable=False)
    active_seconds = db.Column(db.Float, default=0.0)
    idle_seconds = db.Column(db.Float, default=0.0)
    locked_seconds = db.Column(db.Float, default=0.0)
    away_seconds = db.Column(db.Float, default=0.0)  # Prolonged locked (> 2 hours)
    session_start = db.Column(db.DateTime, nullable=True)  # Agent session start for reset detection
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('agent_id', 'date', name='uq_screen_time_agent_date'),)

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'username': self.username,
            'date': self.date.isoformat(),
            'active_seconds': self.active_seconds,
            'idle_seconds': self.idle_seconds,
            'locked_seconds': self.locked_seconds,
            'away_seconds': self.away_seconds or 0
        }


class AppUsage(db.Model):
    """Daily app usage aggregation."""
    __tablename__ = 'app_usage'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    date = db.Column(db.Date, nullable=False)
    app = db.Column(db.String(255), nullable=False)
    duration_seconds = db.Column(db.Integer, default=0)
    session_count = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('agent_id', 'date', 'app', name='uq_app_usage_agent_date_app'),)

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'app': self.app,
            'date': self.date.isoformat(),
            'duration_seconds': self.duration_seconds,
            'session_count': self.session_count
        }


class AppSession(db.Model):
    """Detailed app session history for completed activities"""
    __tablename__ = 'app_sessions'

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    app = db.Column(db.String(255), nullable=False)
    window_title = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'app': self.app,
            'window_title': self.window_title,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': self.duration_seconds
        }


class DomainUsage(db.Model):
    """Daily domain usage aggregation."""
    __tablename__ = 'domain_usage'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    date = db.Column(db.Date, nullable=False)
    domain = db.Column(db.String(255), nullable=False)
    browser = db.Column(db.String(50), nullable=True)
    duration_seconds = db.Column(db.Integer, default=0)
    session_count = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('agent_id', 'date', 'domain', name='uq_domain_usage_agent_date_domain'),)

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'domain': self.domain,
            'browser': self.browser,
            'date': self.date.isoformat(),
            'duration_seconds': self.duration_seconds,
            'session_count': self.session_count
        }


class DomainSession(db.Model):
    """Individual domain visit records."""
    __tablename__ = 'domain_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    domain = db.Column(db.String(255), nullable=False)
    browser = db.Column(db.String(50), nullable=True)
    url = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Raw data fields for server-side classification
    raw_title = db.Column(db.Text, nullable=True)  # Original window title
    raw_url = db.Column(db.Text, nullable=True)    # CDP URL if available
    domain_source = db.Column(db.String(20), default='agent')  # 'agent', 'rule', 'admin'
    needs_review = db.Column(db.Boolean, default=False)  # For classification review queue

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'domain': self.domain,
            'browser': self.browser,
            'url': self.url,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': self.duration_seconds,
            'raw_title': self.raw_title,
            'domain_source': self.domain_source
        }
