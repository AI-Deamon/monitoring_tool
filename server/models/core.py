"""
Core Models: Organization, Agent, AgentCurrentStatus
"""
from datetime import datetime
from extensions import db
from sqlalchemy.dialects import postgresql
import uuid


class Organization(db.Model):
    """
    Organization/Tenant model for multi-user scalability.
    All agents and users belong to an organization.
    """
    __tablename__ = 'organizations'
    
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(postgresql.UUID(as_uuid=True), unique=True, nullable=False, index=True, default=uuid.uuid4)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False) # e.g. "acme-corp"
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    agents = db.relationship('Agent', backref='organization', lazy='dynamic')
    users = db.relationship('DashboardUser', backref='organization', lazy='dynamic')

class Agent(db.Model):
    """
    Agent registration and metadata.
    
    This is the central model - all other tables link to this via agent_id.
    Relationships provide easy access to all agent data:
        agent.screen_times -> List of ScreenTime records
        agent.app_usages -> List of AppUsage records
        agent.app_sessions -> List of AppSession records
        agent.domain_usages -> List of DomainUsage records
        agent.domain_visits -> List of DomainVisit records
        agent.inventory -> List of AppInventory records
        agent.inventory_changes -> List of AppInventoryChange records
        agent.current_status -> AgentCurrentStatus (one-to-one)
    """
    __tablename__ = 'agents'
    
    id = db.Column(db.Integer, primary_key=True)  # Auto-increment ID
    agent_id = db.Column(postgresql.UUID(as_uuid=True), unique=True, nullable=False, index=True)  # agent_id from client
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True, index=True) # Multi-tenant link
    agent_name = db.Column(db.String(255), nullable=True)  # Custom display name
    hostname = db.Column(db.String(255), nullable=True)
    
    # OS Information (enhanced)
    os = db.Column(db.String(255), nullable=True)  # os_version: "Windows 11 Pro (Build 22631)"
    os_build = db.Column(db.Integer, nullable=True)  # NEW: 22631
    windows_edition = db.Column(db.String(50), nullable=True)  # NEW: "Pro", "Home"
    architecture = db.Column(db.String(50), nullable=True)  # NEW: "AMD64", "x86", "ARM64"
    
    # Agent Version
    version = db.Column(db.String(50), nullable=True)  # agent_version
    
    # ================================================================
    # UPDATE CONTROL - Dashboard-driven update management
    # ================================================================
    target_version = db.Column(db.String(50), nullable=True)         # Set by dashboard admin
    update_status = db.Column(db.String(50), default='up_to_date')   # up_to_date | pending | downloading | installing | success | failed | rolled_back
    last_update_check = db.Column(db.DateTime, nullable=True)        # Last time agent polled for updates
    update_attempts = db.Column(db.Integer, default=0)               # Retry counter
    last_update_error = db.Column(db.Text, nullable=True)            # Last failure reason
    force_update_check = db.Column(db.Boolean, default=False)         # Server-triggered immediate check
    
    local_agent_key = db.Column(db.String(255), nullable=True)
    api_token = db.Column(db.Text, nullable=True)  # Legacy JWT token
    api_key = db.Column(db.String(128), nullable=True)  # New API key (sk_live_...)
    hashed_api_token = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), default='active')  # active, inactive, suspended
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    first_activity_at = db.Column(db.DateTime, nullable=True)  # First real telemetry activity
    last_seen = db.Column(db.DateTime, nullable=True)  # Any authenticated request
    last_telemetry_time = db.Column(db.DateTime, nullable=True)  # Actual telemetry data received
    
    # ================================================================
    # OPERATIONAL STATUS - Helper monitoring and degraded mode
    # ================================================================
    operational_status = db.Column(db.String(50), default='NORMAL')  # NORMAL, DEGRADED, OFFLINE
    status_reason = db.Column(db.Text, nullable=True)  # Reason for degraded/offline
    last_status_change = db.Column(db.DateTime, nullable=True)  # When status last changed
    diagnostics_json = db.Column(db.Text, nullable=True)  # JSON string with diagnostics
    
    # ================================================================
    # RELATIONSHIPS - Link all tables to Agent for clean data access
    # ================================================================
    screen_times = db.relationship('ScreenTime', backref='agent', lazy='dynamic',
                                   cascade='all, delete-orphan')
    app_usages = db.relationship('AppUsage', backref='agent', lazy='dynamic',
                                 cascade='all, delete-orphan')
    app_sessions = db.relationship('AppSession', backref='agent', lazy='dynamic',
                                   cascade='all, delete-orphan')
    domain_usages = db.relationship('DomainUsage', backref='agent', lazy='dynamic',
                                    cascade='all, delete-orphan')
    domain_visits = db.relationship('DomainVisit', backref='agent', lazy='dynamic',
                                    cascade='all, delete-orphan')
    domain_sessions = db.relationship('DomainSession', backref='agent', lazy='dynamic',
                                      cascade='all, delete-orphan')
    inventory = db.relationship('AppInventory', backref='agent', lazy='dynamic',
                                cascade='all, delete-orphan')
    inventory_changes = db.relationship('AppInventoryChange', backref='agent', lazy='dynamic',
                                        cascade='all, delete-orphan')
    state_changes = db.relationship('StateChange', backref='agent', lazy='dynamic',
                                    cascade='all, delete-orphan')
    raw_events = db.relationship('RawEvent', backref='agent', lazy='dynamic',
                                 cascade='all, delete-orphan')
    asset_info = db.relationship('AssetInfo', backref='agent', uselist=False,
                                cascade='all, delete-orphan')
    update_history = db.relationship('UpdateHistory', backref='agent', lazy='dynamic',
                                     cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'agent_id': str(self.agent_id), # Actual UUID
            'internal_id': self.id,        # Primary key (integer)
            'agent_name': self.agent_name,  # Custom display name
            'hostname': self.hostname,
            'os': self.os,
            'os_version': self.os,  # Alias for compatibility
            'os_build': self.os_build,
            'windows_edition': self.windows_edition,
            'architecture': self.architecture,
            'version': self.version,
            'agent_version': self.version,  # Alias for compatibility
            'target_version': self.target_version,
            'update_status': self.update_status or 'up_to_date',
            'last_update_check': self.last_update_check.isoformat() if self.last_update_check else None,
            'update_attempts': self.update_attempts or 0,
            'last_update_error': self.last_update_error,
            'status': self.status,
            'operational_status': self.operational_status or 'NORMAL',
            'status_reason': self.status_reason,
            'last_status_change': self.last_status_change.isoformat() if self.last_status_change else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'first_activity_at': self.first_activity_at.isoformat() if self.first_activity_at else None
        }


class AgentCurrentStatus(db.Model):
    """
    LIVE LAYER: Real-time agent status.
    
    Rule: ONE ROW per agent. Updated on every heartbeat.
    Dashboard: "Team Status" widget showing what each user is doing RIGHT NOW.
    
    Example:
        Alice | VS Code | Active for 5m | 10:05:30
        Bob   | Chrome  | Active for 1m | 10:05:31
    """
    __tablename__ = 'agent_current_status'
    
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), primary_key=True)
    username = db.Column(db.String(255), nullable=True)
    current_app = db.Column(db.String(255), nullable=True)
    window_title = db.Column(db.Text, nullable=True)
    current_state = db.Column(db.String(20), default='active')  # active, idle, locked
    session_start = db.Column(db.DateTime, nullable=True)  # When this app session started
    duration_seconds = db.Column(db.Integer, default=0)  # Duration in current app
    
    # Live Domain Tracking
    current_domain = db.Column(db.String(255), nullable=True)
    current_browser = db.Column(db.String(100), nullable=True)
    current_url = db.Column(db.Text, nullable=True)
    domain_session_start = db.Column(db.DateTime, nullable=True)  # When this domain session started
    domain_duration_seconds = db.Column(db.Integer, default=0)  # Duration in current domain
    
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    
    agent = db.relationship('Agent', backref='current_status', uselist=False)
    
    # FIX 5: STALE STATUS DETECTION
    @property
    def is_stale(self):
        """Check if status is stale (no update in 5 minutes)"""
        if not self.last_seen:
            return True
        return (datetime.utcnow() - self.last_seen).total_seconds() > 300  # 5 minutes

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'username': self.username,
            'current_app': self.current_app,
            'window_title': self.window_title,
            'current_state': self.current_state,
            'current_domain': self.current_domain,
            'current_browser': self.current_browser,
            'session_start': self.session_start.isoformat() if self.session_start else None,
            'duration_seconds': self.duration_seconds,
            'domain_session_start': self.domain_session_start.isoformat() if self.domain_session_start else None,
            'domain_duration_seconds': self.domain_duration_seconds,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None
        }
