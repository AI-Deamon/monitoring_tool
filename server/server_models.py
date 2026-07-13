from datetime import datetime, timezone
from extensions import db
from sqlalchemy.dialects import postgresql
import uuid


class Organization(db.Model):
    """
    Organization/Tenant model for multi-user scalability.
    All agents and users belong to an organization.
    """

    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(
        postgresql.UUID(as_uuid=True),
        unique=True,
        nullable=False,
        index=True,
        default=uuid.uuid4,
    )
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)  # e.g. "acme-corp"

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    agents = db.relationship("Agent", backref="organization", lazy="dynamic")
    # NOTE: intentionally no cascade="all, delete-orphan" here, unlike Agent's
    # owned relationships elsewhere in this file - deleting an Organization
    # must not silently cascade-delete DashboardUser accounts. org_id on
    # DashboardUser blocks the delete instead (IntegrityError) until users
    # are explicitly reassigned or removed.
    users = db.relationship("DashboardUser", backref="organization", lazy="dynamic")


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

    __tablename__ = "agents"

    id = db.Column(db.Integer, primary_key=True)  # Auto-increment ID
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True), unique=True, nullable=False, index=True
    )  # agent_id from client
    org_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=True, index=True
    )  # Multi-tenant link
    agent_name = db.Column(db.String(255), nullable=True)  # Custom display name
    hostname = db.Column(db.String(255), nullable=True)

    # OS Information (enhanced)
    os = db.Column(
        db.String(255), nullable=True
    )  # os_version: "Windows 11 Pro (Build 22631)"
    os_build = db.Column(db.Integer, nullable=True)  # NEW: 22631
    windows_edition = db.Column(db.String(50), nullable=True)  # NEW: "Pro", "Home"
    architecture = db.Column(
        db.String(50), nullable=True
    )  # NEW: "AMD64", "x86", "ARM64"

    # Agent Version
    version = db.Column(db.String(50), nullable=True)  # agent_version

    # ================================================================
    # UPDATE CONTROL - Dashboard-driven update management
    # ================================================================
    target_version = db.Column(db.String(50), nullable=True)  # Set by dashboard admin
    update_status = db.Column(
        db.String(50), default="up_to_date"
    )  # up_to_date | pending | downloading | installing | success | failed | rolled_back
    last_update_check = db.Column(
        db.DateTime, nullable=True
    )  # Last time agent polled for updates
    update_attempts = db.Column(db.Integer, default=0)  # Retry counter
    last_update_error = db.Column(db.Text, nullable=True)  # Last failure reason
    force_update_check = db.Column(
        db.Boolean, default=False
    )  # Server-triggered immediate check

    local_agent_key = db.Column(db.String(255), nullable=True)
    api_token = db.Column(db.Text, nullable=True)  # Legacy JWT token
    api_key = db.Column(db.String(128), nullable=True)  # New API key (sk_live_...)
    hashed_api_token = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), default="active")  # active, inactive, suspended
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    first_activity_at = db.Column(
        db.DateTime, nullable=True
    )  # First real telemetry activity
    last_seen = db.Column(db.DateTime, nullable=True)  # Any authenticated request
    last_telemetry_time = db.Column(
        db.DateTime, nullable=True
    )  # Actual telemetry data received

    # ================================================================
    # OPERATIONAL STATUS - Helper monitoring and degraded mode
    # ================================================================
    operational_status = db.Column(
        db.String(50), default="NORMAL"
    )  # NORMAL, DEGRADED, OFFLINE
    status_reason = db.Column(db.Text, nullable=True)  # Reason for degraded/offline
    last_status_change = db.Column(
        db.DateTime, nullable=True
    )  # When status last changed
    diagnostics_json = db.Column(db.Text, nullable=True)  # JSON string with diagnostics

    # ================================================================
    # RELATIONSHIPS - Link all tables to Agent for clean data access
    # ================================================================
    screen_times = db.relationship(
        "ScreenTime", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )
    app_usages = db.relationship(
        "AppUsage", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )
    app_sessions = db.relationship(
        "AppSession", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )
    domain_usages = db.relationship(
        "DomainUsage", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )
    domain_visits = db.relationship(
        "DomainVisit", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )
    domain_sessions = db.relationship(
        "DomainSession", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )
    inventory = db.relationship(
        "AppInventory", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )
    inventory_changes = db.relationship(
        "AppInventoryChange",
        backref="agent",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    state_changes = db.relationship(
        "StateChange", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )
    raw_events = db.relationship(
        "RawEvent", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )
    asset_info = db.relationship(
        "AssetInfo", backref="agent", uselist=False, cascade="all, delete-orphan"
    )
    update_history = db.relationship(
        "UpdateHistory", backref="agent", lazy="dynamic", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "agent_id": str(self.agent_id),  # Actual UUID
            "internal_id": self.id,  # Primary key (integer)
            "agent_name": self.agent_name,  # Custom display name
            "hostname": self.hostname,
            "os": self.os,
            "os_version": self.os,  # Alias for compatibility
            "os_build": self.os_build,
            "windows_edition": self.windows_edition,
            "architecture": self.architecture,
            "version": self.version,
            "agent_version": self.version,  # Alias for compatibility
            "target_version": self.target_version,
            "update_status": self.update_status or "up_to_date",
            "last_update_check": self.last_update_check.isoformat()
            if self.last_update_check
            else None,
            "update_attempts": self.update_attempts or 0,
            "last_update_error": self.last_update_error,
            "status": self.status,
            "operational_status": self.operational_status or "NORMAL",
            "status_reason": self.status_reason,
            "last_status_change": self.last_status_change.isoformat()
            if self.last_status_change
            else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "first_activity_at": self.first_activity_at.isoformat()
            if self.first_activity_at
            else None,
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

    __tablename__ = "agent_current_status"

    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        primary_key=True,
    )
    username = db.Column(db.String(255), nullable=True)
    current_app = db.Column(db.String(255), nullable=True)
    window_title = db.Column(db.Text, nullable=True)
    current_state = db.Column(db.String(20), default="active")  # active, idle, locked
    session_start = db.Column(
        db.DateTime, nullable=True
    )  # When this app session started
    duration_seconds = db.Column(db.Integer, default=0)  # Duration in current app

    # Live Domain Tracking
    current_domain = db.Column(db.String(255), nullable=True)
    current_browser = db.Column(db.String(100), nullable=True)
    current_url = db.Column(db.Text, nullable=True)
    domain_session_start = db.Column(
        db.DateTime, nullable=True
    )  # When this domain session started
    domain_duration_seconds = db.Column(
        db.Integer, default=0
    )  # Duration in current domain

    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    agent = db.relationship("Agent", backref="current_status", uselist=False)

    # FIX 5: STALE STATUS DETECTION
    @property
    def is_stale(self):
        """Check if status is stale (no update in 5 minutes)"""
        if not self.last_seen:
            return True
        # Handle naive datetime from database (default=datetime.utcnow)
        last_seen_ts = self.last_seen
        if last_seen_ts.tzinfo is None:
            last_seen_ts = last_seen_ts.replace(tzinfo=timezone.utc)
        return (
            datetime.now(timezone.utc) - last_seen_ts
        ).total_seconds() > 300  # 5 minutes

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "username": self.username,
            "current_app": self.current_app,
            "window_title": self.window_title,
            "current_state": self.current_state,
            "current_domain": self.current_domain,
            "current_browser": self.current_browser,
            "session_start": self.session_start.isoformat()
            if self.session_start
            else None,
            "duration_seconds": self.duration_seconds,
            "domain_session_start": self.domain_session_start.isoformat()
            if self.domain_session_start
            else None,
            "domain_duration_seconds": self.domain_duration_seconds,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }


class ScreenTime(db.Model):
    """Daily screen time aggregation.

    Fields:
        active_seconds: Time user was actively using the computer
        idle_seconds: Time user was logged in but idle (no input)
        locked_seconds: Time the screen was locked (short lock periods < 2 hours)
        away_seconds: Prolonged locked periods (> 2 hours), indicating user is away
    """

    __tablename__ = "screen_time"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username = db.Column(db.String(255), nullable=True)
    date = db.Column(db.Date, nullable=False)
    active_seconds = db.Column(db.Float, default=0.0)
    idle_seconds = db.Column(db.Float, default=0.0)
    locked_seconds = db.Column(db.Float, default=0.0)
    away_seconds = db.Column(db.Float, default=0.0)  # Prolonged locked (> 2 hours)
    session_start = db.Column(
        db.DateTime, nullable=True
    )  # Agent session start for reset detection
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint("agent_id", "date", name="uq_screen_time_agent_date"),
    )

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "username": self.username,
            "date": self.date.isoformat(),
            "active_seconds": self.active_seconds,
            "idle_seconds": self.idle_seconds,
            "locked_seconds": self.locked_seconds,
            "away_seconds": self.away_seconds or 0,
        }


class AppUsage(db.Model):
    """Daily app usage aggregation."""

    __tablename__ = "app_usage"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username = db.Column(db.String(255), nullable=True)
    date = db.Column(db.Date, nullable=False)
    app = db.Column(db.String(255), nullable=False)
    duration_seconds = db.Column(db.Integer, default=0)
    session_count = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "agent_id", "date", "app", name="uq_app_usage_agent_date_app"
        ),
    )

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "app": self.app,
            "date": self.date.isoformat(),
            "duration_seconds": self.duration_seconds,
            "session_count": self.session_count,
        }


class AppSession(db.Model):
    """Detailed app session history for completed activities"""

    __tablename__ = "app_sessions"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username = db.Column(db.String(255), nullable=True)
    app = db.Column(db.String(255), nullable=False)
    window_title = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "app": self.app,
            "window_title": self.window_title,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
        }


class DomainUsage(db.Model):
    """Daily domain usage aggregation."""

    __tablename__ = "domain_usage"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username = db.Column(db.String(255), nullable=True)
    date = db.Column(db.Date, nullable=False)
    domain = db.Column(db.String(255), nullable=False)
    browser = db.Column(db.String(50), nullable=True)
    duration_seconds = db.Column(db.Integer, default=0)
    session_count = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "agent_id", "date", "domain", name="uq_domain_usage_agent_date_domain"
        ),
    )

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "domain": self.domain,
            "browser": self.browser,
            "date": self.date.isoformat(),
            "duration_seconds": self.duration_seconds,
            "session_count": self.session_count,
        }


class DomainSession(db.Model):
    """Individual domain visit records."""

    __tablename__ = "domain_sessions"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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
    raw_url = db.Column(db.Text, nullable=True)  # CDP URL if available
    domain_source = db.Column(
        db.String(20), default="agent"
    )  # 'agent', 'rule', 'admin'
    needs_review = db.Column(
        db.Boolean, default=False
    )  # For classification review queue

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "domain": self.domain,
            "browser": self.browser,
            "url": self.url,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "raw_title": self.raw_title,
            "domain_source": self.domain_source,
        }


class AppInventory(db.Model):
    """Application inventory snapshot."""

    __tablename__ = "app_inventory"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    version = db.Column(db.String(100), nullable=True)
    publisher = db.Column(db.String(255), nullable=True)
    install_location = db.Column(db.Text, nullable=True)
    install_date = db.Column(db.Date, nullable=True)
    source = db.Column(
        db.String(50), nullable=True
    )  # Registry-HKLM, Registry-HKCU, MicrosoftStore
    architecture = db.Column(db.String(50), nullable=True)  # x86, x64, ARM64, Unknown
    uninstall_command = db.Column(db.Text, nullable=True)
    estimated_size_kb = db.Column(db.BigInteger, nullable=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("agent_id", "name", name="uq_app_inventory_agent_name"),
    )

    def to_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "install_location": self.install_location,
            "install_date": self.install_date.isoformat()
            if self.install_date
            else None,
            "source": self.source,
            "architecture": self.architecture,
            "uninstall_command": self.uninstall_command,
            "estimated_size_kb": self.estimated_size_kb,
        }


class AppInventoryChange(db.Model):
    """Tracks installed/uninstalled app changes for audit history."""

    __tablename__ = "app_inventory_changes"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    change_type = db.Column(
        db.String(20), nullable=False
    )  # installed, uninstalled, updated
    app_name = db.Column(db.String(255), nullable=False)
    version = db.Column(db.String(100), nullable=True)

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "change_type": self.change_type,
            "app_name": self.app_name,
            "version": self.version,
        }


class StateChange(db.Model):
    """State transition events (active/idle/locked)."""

    __tablename__ = "state_changes"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username = db.Column(db.String(255), nullable=True)
    previous_state = db.Column(db.String(50), nullable=False)  # active, idle, locked
    current_state = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "previous_state": self.previous_state,
            "current_state": self.current_state,
            "timestamp": self.timestamp.isoformat(),
        }


class DomainVisit(db.Model):
    """
    Sites opened (Column B) - Browser history without duration.
    Tracks all domains visited including background tabs and quick visits.
    """

    __tablename__ = "domain_visits"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username = db.Column(db.String(255), nullable=True)
    domain = db.Column(db.String(255), nullable=False)
    url = db.Column(db.Text, nullable=True)
    browser = db.Column(db.String(50), nullable=True)
    visited_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.Index("ix_domain_visits_agent_date", "agent_id", "visited_at"),
        db.UniqueConstraint(
            "agent_id", "domain", "visited_at", name="uq_domain_visit_unique"
        ),
    )

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "domain": self.domain,
            "url": self.url,
            "browser": self.browser,
            "visited_at": self.visited_at.isoformat(),
        }


# ============================================================================
# FRIENDLY APP NAMES MAPPING
# ============================================================================
APP_FRIENDLY_NAMES = {
    # Browsers
    "chrome.exe": "Google Chrome",
    "brave.exe": "Brave Browser",
    "firefox.exe": "Mozilla Firefox",
    "msedge.exe": "Microsoft Edge",
    "opera.exe": "Opera",
    "vivaldi.exe": "Vivaldi",
    "safari.exe": "Safari",
    # Development
    "code.exe": "VS Code",
    "devenv.exe": "Visual Studio",
    "idea64.exe": "IntelliJ IDEA",
    "pycharm64.exe": "PyCharm",
    "webstorm64.exe": "WebStorm",
    "sublime_text.exe": "Sublime Text",
    "notepad++.exe": "Notepad++",
    "notepad.exe": "Notepad",
    "atom.exe": "Atom",
    "cursor.exe": "Cursor",
    "antigravity.exe": "Antigravity",
    "putty.exe": "PuTTY",
    "winscp.exe": "WinSCP",
    # Communication
    "slack.exe": "Slack",
    "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams",
    "discord.exe": "Discord",
    "zoom.exe": "Zoom",
    "skype.exe": "Skype",
    "telegram.exe": "Telegram",
    "whatsapp.exe": "WhatsApp",
    "olk.exe": "Outlook (New)",
    # Office
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "PowerPoint",
    "outlook.exe": "Outlook",
    "onenote.exe": "OneNote",
    "toad.exe": "Toad for Oracle",
    # Terminals
    "windowsterminal.exe": "Windows Terminal",
    "cmd.exe": "Command Prompt",
    "powershell.exe": "PowerShell",
    "wt.exe": "Windows Terminal",
    # System (visible but labeled properly)
    "explorer.exe": "File Explorer",
    "shellhost.exe": "Shell Host",
    "taskmgr.exe": "Task Manager",
    "control.exe": "Control Panel",
    "settings.exe": "Windows Settings",
    "mstsc.exe": "Remote Desktop",
    # Media
    "spotify.exe": "Spotify",
    "vlc.exe": "VLC Media Player",
    # Other
    "postman.exe": "Postman",
    "insomnia.exe": "Insomnia",
    "figma.exe": "Figma",
    "notion.exe": "Notion",
    "obsidian.exe": "Obsidian",
    "searchapp.exe": "Windows Search",
}

# ============================================================================
# SYSTEM APPS TO EXCLUDE FROM REPORTS
# These are background/system processes that don't represent actual user work
# ============================================================================
SYSTEM_APPS_FILTER = {
    "lockapp.exe",  # Windows Lock Screen
    "searchhost.exe",  # Windows Search Host (Win11)
    "applicationframehost.exe",  # UWP App Host (system process)
    "shellexperiencehost.exe",  # Windows Shell
    "startmenuexperiencehost.exe",  # Start Menu
    "searchui.exe",  # Cortana/Search UI
    "runtimebroker.exe",  # Runtime Broker
    "backgroundtaskhost.exe",  # Background Tasks
    "systemsettings.exe",  # Settings app overlay
    "textinputhost.exe",  # Text Input
    "dwm.exe",  # Desktop Window Manager
    "csrss.exe",  # Client Server Runtime
    "winlogon.exe",  # Windows Logon
    "sihost.exe",  # Shell Infrastructure Host
    "fontdrvhost.exe",  # Font Driver Host
    "ctfmon.exe",  # CTF Loader
    "dllhost.exe",  # DLL Host
    "wudfhost.exe",  # Windows User-Mode Driver Framework
    "smartscreen.exe",  # SmartScreen
    "securityhealthservice.exe",  # Windows Security
    "phonelinkserver.exe",  # Phone Link
    "widgets.exe",  # Windows Widgets
    "gamebar.exe",  # Game Bar
    "gamebarpresencewriter.exe",  # Game Bar
}

# ============================================================================
# SYSTEM INVENTORY APPS TO EXCLUDE FROM REPORTS
# These are Windows system apps that clutter the inventory
# ============================================================================
# Pre-lowercased patterns for faster matching (Bolt ⚡)
SYSTEM_INVENTORY_FILTER_PATTERNS = [
    p.lower()
    for p in [
        "Microsoft.Windows.",  # Windows system components
        "MicrosoftWindows.",  # Alternate naming
        "Windows.",  # Generic Windows apps
        "HERUNTERLADEN",  # German KB downloads
        "KB",  # Knowledge Base updates
        "Update for",  # Update packages
        "Security Update",  # Security updates
        "Hotfix",  # Hotfixes
        "Python 3.",  # Python components (will be consolidated)
    ]
]

# Pre-lowercased patterns for faster matching (Bolt ⚡)
PYTHON_COMPONENT_PATTERNS = [
    p.lower()
    for p in [
        "Add to Path",
        "Core Interpreter",
        "Development Libraries",
        "Documentation",
        "Executables",
        "pip",
        "Standard Library",
        "Tcl/Tk",
        "Test Suite",
        "Utility Scripts",
        "py launcher",
    ]
]


def is_system_inventory_app(name: str) -> bool:
    """Check if the app is a system app that should be filtered from inventory."""
    if not name:
        return False
    name_lower = name.lower()
    for pattern_lower in SYSTEM_INVENTORY_FILTER_PATTERNS:
        if pattern_lower in name_lower:
            return True
    return False


def consolidate_python_versions(apps: list) -> list:
    """
    Consolidate multiple Python component entries into single Python version entries.
    e.g., 'Python 3.11.9 Core Interpreter', 'Python 3.11.9 Documentation' -> 'Python 3.11.9'
    """
    import re

    python_versions = {}
    other_apps = []

    for app in apps:
        name = app.get("name", "")

        # Check if it's a Python entry
        python_match = re.match(r"^Python (\d+\.\d+(?:\.\d+)?)", name)
        if python_match:
            version = python_match.group(1)
            # Check if it's a component entry (not the base install)
            is_component = any(
                comp.lower() in name.lower() for comp in PYTHON_COMPONENT_PATTERNS
            )

            if version not in python_versions:
                python_versions[version] = {
                    "name": f"Python {version}",
                    "version": version,
                    "publisher": "Python Software Foundation",
                    "source": app.get("source", "Registry-HKLM"),
                    "install_date": app.get("install_date"),
                }

            # Keep the install location from the base install
            if not is_component and app.get("install_location"):
                python_versions[version]["install_location"] = app.get(
                    "install_location"
                )
        else:
            other_apps.append(app)

    # Add consolidated Python entries to list
    for version_data in python_versions.values():
        other_apps.append(version_data)

    return other_apps


# ============================================================================
# INTERNAL/SYSTEM DOMAINS TO EXCLUDE FROM REPORTS
# These are browser internal pages, not real websites
# ============================================================================
INTERNAL_DOMAINS_FILTER = {
    # Chrome internal pages
    "recent-download-history.local",
    "newtab.local",
    "extensions.local",
    "settings.local",
    "history.local",
    "downloads.local",
    "bookmarks.local",
    "chrome-native.local",
    # Edge internal pages
    "edge-settings.local",
    "edge-newtab.local",
    "edgeservices.local",
    # Other internal
    "localhost",
    "127.0.0.1",
    "about:blank",
    "about:newtab",
}


class RawEvent(db.Model):
    """
    Raw event log for all incoming telemetry.
    Stores exact payload before processing for auditing and replay.
    """

    __tablename__ = "raw_events"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = db.Column(db.String(50), nullable=False)
    sequence = db.Column(db.Integer, nullable=True)  # From agent (if available)
    payload = db.Column(db.Text, nullable=False)  # JSON string
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)
    error = db.Column(db.Text, nullable=True)

    # Ensure (agent_id, sequence, event_type) is unique to prevent duplicate processing
    # Note: Sequence might be reset or not available for all types, so partial index might be better
    # But for now, a simple index is good.
    __table_args__ = (
        db.Index("ix_raw_events_agent_seq", "agent_id", "sequence", "event_type"),
    )


def get_friendly_app_name(exe_name: str) -> str:
    """Convert executable name to friendly display name."""
    if not exe_name:
        return "Unknown"
    exe_lower = exe_name.lower()
    return APP_FRIENDLY_NAMES.get(exe_lower, exe_name.replace(".exe", "").title())


def is_system_app(exe_name: str) -> bool:
    """Check if the app is a system process that should be filtered from reports."""
    if not exe_name:
        return False
    return exe_name.lower() in SYSTEM_APPS_FILTER


def is_internal_domain(domain: str) -> bool:
    """Check if the domain is an internal/system domain that should be filtered.

    NOTE: Currently disabled - showing ALL domains as requested by admin.
    To re-enable filtering, uncomment the checks below.
    """
    # ALL FILTERING DISABLED - Show everything
    return False

    # Original filtering (commented out):
    # if not domain:
    #     return False
    # domain_lower = domain.lower()
    # if domain_lower in INTERNAL_DOMAINS_FILTER:
    #     return True
    # return False


class AssetInfo(db.Model):
    """
    Hardware and system information for IT asset management.
    One-to-one with Agent — stores latest hardware snapshot.
    """

    __tablename__ = "asset_info"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    org_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=True, index=True
    )  # Multi-tenant link

    # ================================================================
    # IDENTITY
    # ================================================================
    hostname = db.Column(db.String(255), nullable=True)
    serial_number = db.Column(db.String(255), nullable=True)
    manufacturer = db.Column(db.String(255), nullable=True)
    model = db.Column(db.String(255), nullable=True)
    bios_uuid = db.Column(db.String(255), nullable=True)
    system_uuid = db.Column(db.String(255), nullable=True)
    asset_tag = db.Column(db.String(255), nullable=True)
    domain = db.Column(db.String(255), nullable=True)
    workgroup = db.Column(db.String(255), nullable=True)

    # ================================================================
    # HARDWARE SPECS
    # ================================================================
    cpu_name = db.Column(db.Text, nullable=True)
    cpu_cores = db.Column(db.Integer, nullable=True)
    cpu_threads = db.Column(db.Integer, nullable=True)
    cpu_speed_mhz = db.Column(db.Integer, nullable=True)
    ram_total_gb = db.Column(db.Float, nullable=True)
    ram_slots_used = db.Column(db.Integer, nullable=True)
    ram_slots_total = db.Column(db.Integer, nullable=True)
    gpus_json = db.Column(db.Text, nullable=True)  # JSON array of {name, memory_gb}
    disks_json = db.Column(db.Text, nullable=True)  # JSON array of disk info
    motherboard = db.Column(db.Text, nullable=True)

    # ================================================================
    # NETWORK
    # ================================================================
    primary_mac = db.Column(db.String(255), nullable=True)
    primary_ip = db.Column(db.String(255), nullable=True)
    all_macs_json = db.Column(db.Text, nullable=True)  # JSON array
    all_ips_json = db.Column(db.Text, nullable=True)  # JSON array
    dns_servers_json = db.Column(db.Text, nullable=True)  # JSON array
    domain_joined = db.Column(db.Boolean, nullable=True)
    domain_name = db.Column(db.String(255), nullable=True)

    # ================================================================
    # SECURITY POSTURE
    # ================================================================
    os_name = db.Column(db.String(255), nullable=True)
    os_version = db.Column(db.String(255), nullable=True)
    os_build = db.Column(db.String(255), nullable=True)
    os_architecture = db.Column(db.String(255), nullable=True)
    os_edition = db.Column(
        db.String(50), nullable=True
    )  # Pro, Enterprise, Home, Education
    os_sku = db.Column(db.Integer, nullable=True)  # Windows SKU number
    antivirus_json = db.Column(db.Text, nullable=True)  # JSON array of AV products
    firewall_enabled = db.Column(db.Boolean, nullable=True)
    last_boot_time = db.Column(db.String(255), nullable=True)
    windows_update_enabled = db.Column(db.Boolean, nullable=True)
    bitlocker_status = db.Column(db.String(255), nullable=True)

    # ================================================================
    # META
    # ================================================================
    collected_at = db.Column(db.DateTime, default=datetime.utcnow)
    collection_hash = db.Column(db.String(64), nullable=True)
    agent_version = db.Column(db.String(50), nullable=True)

    def to_dict(self):
        import json as _json

        return {
            "agent_id": str(self.agent_id),
            "hostname": self.hostname,
            "serial_number": self.serial_number,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "bios_uuid": self.bios_uuid,
            "system_uuid": self.system_uuid,
            "asset_tag": self.asset_tag,
            "domain": self.domain,
            "workgroup": self.workgroup,
            "cpu_name": self.cpu_name,
            "cpu_cores": self.cpu_cores,
            "cpu_threads": self.cpu_threads,
            "cpu_speed_mhz": self.cpu_speed_mhz,
            "ram_total_gb": self.ram_total_gb,
            "ram_slots_used": self.ram_slots_used,
            "ram_slots_total": self.ram_slots_total,
            "gpus": _json.loads(self.gpus_json) if self.gpus_json else [],
            "disks": _json.loads(self.disks_json) if self.disks_json else [],
            "motherboard": self.motherboard,
            "primary_mac": self.primary_mac,
            "primary_ip": self.primary_ip,
            "all_macs": _json.loads(self.all_macs_json) if self.all_macs_json else [],
            "all_ips": _json.loads(self.all_ips_json) if self.all_ips_json else [],
            "dns_servers": _json.loads(self.dns_servers_json)
            if self.dns_servers_json
            else [],
            "domain_joined": self.domain_joined,
            "domain_name": self.domain_name,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "os_build": self.os_build,
            "os_architecture": self.os_architecture,
            "os_edition": self.os_edition,
            "os_sku": self.os_sku,
            "antivirus": _json.loads(self.antivirus_json)
            if self.antivirus_json
            else [],
            "firewall_enabled": self.firewall_enabled,
            "last_boot_time": self.last_boot_time,
            "windows_update_enabled": self.windows_update_enabled,
            "bitlocker_status": self.bitlocker_status,
            "collected_at": self.collected_at.isoformat()
            if self.collected_at
            else None,
            "collection_hash": self.collection_hash,
            "agent_version": self.agent_version,
        }


class SoftwareLifecycle(db.Model):
    """
    EOL knowledge base. One row per product-cycle combination.
    Populated from endoflife.date API or manual curation.
    """

    __tablename__ = "software_lifecycle"

    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(
        db.String(255), nullable=False, index=True
    )  # e.g. "windows", "office", "chrome"
    cycle = db.Column(db.String(100), nullable=False)  # e.g. "10-22h2", "2019", "120"
    release_label = db.Column(
        db.String(255), nullable=True
    )  # Human-readable, e.g. "10 22H2"
    release_date = db.Column(db.Date, nullable=True)
    eol_date = db.Column(db.Date, nullable=True)  # End of Life date
    eos_date = db.Column(db.Date, nullable=True)  # End of mainstream Support
    is_lts = db.Column(db.Boolean, default=False)
    latest_version = db.Column(db.String(100), nullable=True)  # e.g. "10.0.19045"
    reference_url = db.Column(db.Text, nullable=True)
    source = db.Column(
        db.String(50), default="endoflife.date"
    )  # 'endoflife.date' or 'manual'
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("product_name", "cycle", name="uq_lifecycle_product_cycle"),
    )


class AssetLifecycleStatus(db.Model):
    """
    Cached lifecycle evaluation result per agent per product.
    Recalculated when inventory updates or lifecycle DB changes.
    """

    __tablename__ = "asset_lifecycle_status"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_name = db.Column(db.String(255), nullable=False)  # Normalized name
    installed_version = db.Column(db.String(255), nullable=True)
    matched_cycle = db.Column(
        db.String(100), nullable=True
    )  # Which lifecycle cycle matched
    status = db.Column(
        db.String(30),
        nullable=False,  # 'supported', 'approaching_eol', 'eol', 'unknown'
        default="unknown",
    )
    eol_date = db.Column(db.Date, nullable=True)
    risk_score = db.Column(db.Integer, default=0)  # 0-50 per-product contribution
    severity = db.Column(
        db.String(20), default="info"
    )  # 'info', 'low', 'medium', 'high', 'critical'
    evaluated_at = db.Column(db.DateTime, default=datetime.utcnow)

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "lifecycle_statuses", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "agent_id", "product_name", name="uq_asset_lifecycle_agent_product"
        ),
    )


# =============================================================================
# Extended Inventory Models (CLI Tools, Drivers, Extensions, Plugins)
# =============================================================================


class CLITool(db.Model):
    """
    Command-line tools inventory (git, node, python, opencode, etc.)
    Detected via PATH scanning, registry App Paths, and known locations.
    """

    __tablename__ = "cli_tools"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)  # Tool name (git, node, python)
    version = db.Column(db.String(100), nullable=True)  # Parsed version
    executable_path = db.Column(
        db.String(500), nullable=True
    )  # Full path to executable
    source = db.Column(
        db.String(50), nullable=True
    )  # 'path', 'registry', 'known_location'
    publisher = db.Column(db.String(255), nullable=True)  # Publisher/vendor
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    agent = db.relationship(
        "Agent",
        backref=db.backref("cli_tools", lazy="dynamic", cascade="all, delete-orphan"),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "agent_id", "name", "executable_path", name="uq_cli_tool_agent_name_path"
        ),
    )


class HardwareDriver(db.Model):
    """
    Hardware drivers inventory from WMI Win32_PnPSignedDriver.
    Critical for EOL tracking on graphics, network, and storage drivers.
    """

    __tablename__ = "hardware_drivers"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_name = db.Column(db.String(255), nullable=True)  # Friendly name
    driver_name = db.Column(db.String(255), nullable=True)  # Driver file name
    driver_version = db.Column(db.String(100), nullable=True)  # Driver version
    driver_date = db.Column(db.Date, nullable=True)  # Driver date from WMI
    manufacturer = db.Column(db.String(255), nullable=True)  # Manufacturer
    device_class = db.Column(
        db.String(100), nullable=True
    )  # 'Display', 'Network', 'Storage', etc.
    device_id = db.Column(db.String(500), nullable=True)  # PnP device ID
    is_signed = db.Column(db.Boolean, default=False)  # Driver signed status
    signer = db.Column(db.String(255), nullable=True)  # Code signer
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "hardware_drivers", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint("agent_id", "device_id", name="uq_driver_agent_device"),
    )


class VSCodeExtension(db.Model):
    """
    VS Code extensions from ~/.vscode/extensions.
    Extensions can have security vulnerabilities and EOL concerns.
    """

    __tablename__ = "vscode_extensions"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    extension_id = db.Column(db.String(255), nullable=True)  # Publisher.extension-name
    display_name = db.Column(db.String(255), nullable=True)  # Human-readable name
    version = db.Column(db.String(100), nullable=True)  # Extension version
    publisher = db.Column(db.String(255), nullable=True)  # Publisher ID
    install_path = db.Column(db.String(500), nullable=True)  # Installation directory
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    source = db.Column(db.String(50), nullable=True)  # 'vscode', 'antigravity'

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "vscode_extensions", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint("agent_id", "extension_id", name="uq_vscode_ext_agent_ext"),
    )


class BrowserExtension(db.Model):
    """
    Browser extensions from Chrome, Firefox, Edge.
    Extensions can pose security risks and need tracking.
    """

    __tablename__ = "browser_extensions"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    browser = db.Column(db.String(50), nullable=False)  # 'chrome', 'firefox', 'edge'
    extension_id = db.Column(db.String(255), nullable=True)  # Browser-specific ID
    name = db.Column(db.String(255), nullable=True)  # Extension name
    version = db.Column(db.String(100), nullable=True)  # Extension version
    description = db.Column(db.Text, nullable=True)  # Extension description
    enabled = db.Column(db.Boolean, default=True)  # Enabled status
    install_date = db.Column(db.Date, nullable=True)  # Install date if available
    profile_path = db.Column(db.String(500), nullable=True)  # Browser profile path
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "browser_extensions", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "agent_id",
            "browser",
            "extension_id",
            name="uq_browser_ext_agent_browser_ext",
        ),
    )


class ApplicationPlugin(db.Model):
    """
    Application plugins and add-ins (Office, Adobe, browsers, etc.)
    Plugins can introduce security vulnerabilities.
    """

    __tablename__ = "application_plugins"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plugin_type = db.Column(
        db.String(50), nullable=False
    )  # 'office_addin', 'adobe_plugin', etc.
    name = db.Column(db.String(255), nullable=True)  # Plugin name
    version = db.Column(db.String(100), nullable=True)  # Plugin version
    publisher = db.Column(db.String(255), nullable=True)  # Publisher
    install_path = db.Column(db.String(500), nullable=True)  # Installation path
    host_application = db.Column(
        db.String(255), nullable=True
    )  # Host app (Word, Excel, etc.)
    enabled = db.Column(db.Boolean, default=True)  # Load behavior
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "application_plugins", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "agent_id",
            "plugin_type",
            "name",
            "install_path",
            name="uq_plugin_agent_type_name_path",
        ),
    )


class PortableApplication(db.Model):
    """
    Portable applications found via disk scanning.
    These don't appear in Add/Remove Programs but need tracking.
    """

    __tablename__ = "portable_applications"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)  # Application name
    version = db.Column(db.String(100), nullable=True)  # Detected version
    executable_path = db.Column(
        db.String(500), nullable=True
    )  # Path to main executable
    install_directory = db.Column(
        db.String(500), nullable=True
    )  # Application directory
    publisher = db.Column(db.String(255), nullable=True)  # Publisher if detected
    detection_method = db.Column(
        db.String(50), nullable=True
    )  # 'disk_scan', 'known_pattern'
    file_size_bytes = db.Column(db.BigInteger, nullable=True)  # Size of application
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "portable_applications", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "agent_id", "executable_path", name="uq_portable_app_agent_path"
        ),
    )


# =============================================================================
# EOL SYSTEM MODELS — Phase 3 additions
# =============================================================================


class NVDCacheEntry(db.Model):
    """
    Local cache of NIST NVD vulnerability data.
    Synced periodically from NVD 2.0 API for risk scoring.
    """

    __tablename__ = "nvd_cache"

    id = db.Column(db.Integer, primary_key=True)
    cve_id = db.Column(db.String(20), nullable=False, index=True)  # CVE-YYYY-NNNNN
    cpe_string = db.Column(db.String(500), nullable=False, index=True)  # CPE 2.3 string
    cvss_score = db.Column(db.Float, default=0.0)  # CVSS base score (0-10)
    severity = db.Column(
        db.String(20), default="NONE"
    )  # NONE, LOW, MEDIUM, HIGH, CRITICAL
    description = db.Column(db.Text, nullable=True)  # CVE description (truncated)
    published_date = db.Column(db.String(30), nullable=True)  # ISO date string
    last_modified = db.Column(db.String(30), nullable=True)  # ISO date string
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("cve_id", "cpe_string", name="uq_nvd_cve_cpe"),
        db.Index("ix_nvd_cvss", "cvss_score"),
    )


class WindowsUpdateRecord(db.Model):
    """
    Windows update (KB) records collected from agents.
    Tracks installed and pending updates for security posture assessment.
    """

    __tablename__ = "windows_updates"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kb_number = db.Column(db.String(20), nullable=False)  # KB1234567
    title = db.Column(db.String(500), nullable=True)  # Update title
    update_type = db.Column(
        db.String(50), default="Unknown"
    )  # Security, Critical, Feature
    install_date = db.Column(db.Date, nullable=True)  # When installed
    result_code = db.Column(db.Integer, default=0)  # 0-4 (WUA codes)
    is_pending = db.Column(db.Boolean, default=False)  # Pending install
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "windows_updates", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint("agent_id", "kb_number", name="uq_update_agent_kb"),
    )


class SoftwareMeteringRecord(db.Model):
    """
    Software usage frequency data from Prefetch/MUI cache.
    Helps identify actively used vs. shelfware applications.
    """

    __tablename__ = "software_metering"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    app_name = db.Column(db.String(255), nullable=False)
    executable_name = db.Column(db.String(255), nullable=True)
    usage_count = db.Column(db.Integer, default=0)
    last_used = db.Column(db.DateTime, nullable=True)
    source = db.Column(db.String(50), default="prefetch")  # prefetch, mui_cache
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "software_metering", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "agent_id", "executable_name", name="uq_metering_agent_exe"
        ),
    )


class ProductKeyRecord(db.Model):
    """
    Partial product keys for license compliance tracking.
    Only stores last 5 characters — never full keys.
    """

    __tablename__ = "product_keys"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_name = db.Column(db.String(255), nullable=False)
    partial_key = db.Column(db.String(10), nullable=True)  # Last 5 chars max
    key_source = db.Column(db.String(50), default="Unknown")  # wmi, registry
    license_status = db.Column(db.String(50), default="Unknown")  # Licensed, OEM, etc.
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "product_keys", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint("agent_id", "product_name", name="uq_key_agent_product"),
    )


class SecurityIndicator(db.Model):
    """
    Security risk indicators detected by the agent's SecurityCollector.
    Stores unsigned drivers, suspicious extensions, and file change alerts.
    """

    __tablename__ = "security_indicators"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    indicator_type = db.Column(
        db.String(50), nullable=False
    )  # 'unsigned_driver', 'suspicious_extension', 'file_change'
    severity = db.Column(
        db.String(20), nullable=False
    )  # 'critical', 'high', 'medium', 'low'
    title = db.Column(db.String(500), nullable=False)  # Human-readable summary
    details_json = db.Column(db.Text, nullable=True)  # Full details as JSON
    risk_score = db.Column(db.Integer, default=0)  # 0-100
    first_detected = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    resolved = db.Column(db.Boolean, default=False)

    agent = db.relationship(
        "Agent",
        backref=db.backref(
            "security_indicators", lazy="dynamic", cascade="all, delete-orphan"
        ),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "agent_id", "indicator_type", "title", name="uq_security_agent_type_title"
        ),
    )


# ============================================================================
# AUTO-UPDATE MANAGEMENT TABLES
# ============================================================================


class UpdateHistory(db.Model):
    """
    Audit trail for every agent update lifecycle event.
    Each status transition (pending → downloading → installing → success/failed)
    creates a row here for full traceability.
    """

    __tablename__ = "update_history"

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(
        postgresql.UUID(as_uuid=True),
        db.ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_version = db.Column(db.String(50), nullable=True)
    to_version = db.Column(db.String(50), nullable=False)
    status = db.Column(
        db.String(30), nullable=False
    )  # pending, downloading, installing, success, failed, rolled_back
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    package_sha256 = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index("ix_update_history_agent_created", "agent_id", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "agent_id": str(self.agent_id),
            "from_version": self.from_version,
            "to_version": self.to_version,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "error_message": self.error_message,
            "package_sha256": self.package_sha256,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UpdateGlobalPolicy(db.Model):
    """
    Singleton row storing global auto-update policy.
    Only one row should exist (id=1). Dashboard reads/writes this row.
    """

    __tablename__ = "update_global_policy"

    id = db.Column(db.Integer, primary_key=True)
    auto_update_enabled = db.Column(db.Boolean, default=False)
    channel = db.Column(db.String(20), default="stable")  # stable, beta, edge
    min_version = db.Column(db.String(50), nullable=True)  # Floor version
    canary_percentage = db.Column(db.Integer, default=0)  # 0-100
    update_window_enabled = db.Column(db.Boolean, default=False)
    update_window_start = db.Column(db.Time, nullable=True)  # e.g. 02:00
    update_window_end = db.Column(db.Time, nullable=True)  # e.g. 06:00
    update_window_tz = db.Column(db.String(50), default="UTC")
    updated_by = db.Column(db.String(255), nullable=True)  # admin username
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self):
        return {
            "auto_update_enabled": self.auto_update_enabled,
            "channel": self.channel,
            "min_version": self.min_version,
            "canary_percentage": self.canary_percentage,
            "update_window_enabled": self.update_window_enabled,
            "update_window_start": self.update_window_start.strftime("%H:%M")
            if self.update_window_start
            else None,
            "update_window_end": self.update_window_end.strftime("%H:%M")
            if self.update_window_end
            else None,
            "update_window_tz": self.update_window_tz,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UpdateVersion(db.Model):
    """
    Version metadata cache for dashboard discovery.
    Populated by background sync from updates directory or manual upload.
    """

    __tablename__ = "update_versions"

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(50), unique=True, nullable=False, index=True)
    artifact_type = db.Column(db.String(30), default="exe_bundle")  # exe_bundle, zip
    package_size = db.Column(db.BigInteger, nullable=True)
    package_sha256 = db.Column(db.String(64), nullable=True)
    min_agent_version = db.Column(db.String(50), nullable=True)
    mandatory = db.Column(db.Boolean, default=False)
    changelog = db.Column(db.Text, nullable=True)
    release_date = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "version": self.version,
            "artifact_type": self.artifact_type,
            "package_size": self.package_size,
            "package_sha256": self.package_sha256,
            "min_agent_version": self.min_agent_version,
            "mandatory": self.mandatory,
            "changelog": self.changelog,
            "release_date": self.release_date.isoformat()
            if self.release_date
            else None,
            "is_active": self.is_active,
        }


class ReportSchedule(db.Model):
    """Scheduled report generation and email delivery"""
    __tablename__ = "report_schedules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    report_type = db.Column(db.String(20), nullable=False)
    scope = db.Column(db.String(20), nullable=False)
    agent_id = db.Column(db.String(100), nullable=True)
    recipients = db.Column(db.Text, nullable=False)
    frequency = db.Column(db.String(20), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=True)
    day_of_month = db.Column(db.Integer, nullable=True)
    send_hour = db.Column(db.Integer, default=9, nullable=False)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    last_run = db.Column(db.DateTime, nullable=True)
    next_run = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    include_pdf = db.Column(db.Boolean, default=False, nullable=False)
    auto_email = db.Column(db.Boolean, default=True, nullable=False)
    template_name = db.Column(db.String(100), nullable=True)
    # JSONB on PostgreSQL; falls back to JSON on SQLite so tests can create the schema
    recipients_json = db.Column(db.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=True)  # overrides recipients field


class ReportGenerationJob(db.Model):
    """Async report generation job tracking"""
    __tablename__ = "report_generation_jobs"

    id = db.Column(db.String(36), primary_key=True)  # UUID string
    schedule_id = db.Column(db.Integer, db.ForeignKey('report_schedules.id', ondelete='SET NULL'), nullable=True)
    report_type = db.Column(db.String(20), nullable=False)
    scope = db.Column(db.String(20), nullable=False)
    agent_id = db.Column(db.String(100), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)
    progress = db.Column(db.JSON().with_variant(postgresql.JSONB(), 'postgresql'), default=dict, nullable=False)
    result_html = db.Column(db.Text, nullable=True)
    result_pdf_path = db.Column(db.String(500), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
