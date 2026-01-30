from datetime import datetime
from extensions import db
from sqlalchemy.dialects import postgresql

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
    agent_name = db.Column(db.String(255), nullable=True)  # Custom display name
    hostname = db.Column(db.String(255), nullable=True)
    
    # OS Information (enhanced)
    os = db.Column(db.String(255), nullable=True)  # os_version: "Windows 11 Pro (Build 22631)"
    os_build = db.Column(db.Integer, nullable=True)  # NEW: 22631
    windows_edition = db.Column(db.String(50), nullable=True)  # NEW: "Pro", "Home"
    architecture = db.Column(db.String(50), nullable=True)  # NEW: "AMD64", "x86", "ARM64"
    
    # Agent Version
    version = db.Column(db.String(50), nullable=True)  # agent_version
    
    local_agent_key = db.Column(db.String(255), nullable=True)
    api_token = db.Column(db.Text, nullable=True)  # Legacy JWT token
    api_key = db.Column(db.String(128), nullable=True)  # New API key (sk_live_...)
    status = db.Column(db.String(50), default='active')  # active, inactive, suspended
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
            'status': self.status,
            'operational_status': self.operational_status or 'NORMAL',
            'status_reason': self.status_reason,
            'last_status_change': self.last_status_change.isoformat() if self.last_status_change else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
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
    
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), primary_key=True)
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
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    date = db.Column(db.Date, nullable=False)
    active_seconds = db.Column(db.Float, default=0.0)
    idle_seconds = db.Column(db.Float, default=0.0)
    locked_seconds = db.Column(db.Float, default=0.0)
    away_seconds = db.Column(db.Float, default=0.0)  # Prolonged locked (> 2 hours)
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
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
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
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
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
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
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
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
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


class AppInventory(db.Model):
    """Application inventory snapshot."""
    __tablename__ = 'app_inventory'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    version = db.Column(db.String(100), nullable=True)
    publisher = db.Column(db.String(255), nullable=True)
    install_location = db.Column(db.Text, nullable=True)
    install_date = db.Column(db.Date, nullable=True)
    source = db.Column(db.String(50), nullable=True)  # Registry-HKLM, Registry-HKCU, MicrosoftStore
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('agent_id', 'name', name='uq_app_inventory_agent_name'),)

    def to_dict(self):
        return {
            'name': self.name,
            'version': self.version,
            'publisher': self.publisher,
            'install_location': self.install_location,
            'install_date': self.install_date.isoformat() if self.install_date else None,
            'source': self.source
        }


class AppInventoryChange(db.Model):
    """Tracks installed/uninstalled app changes for audit history."""
    __tablename__ = 'app_inventory_changes'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    change_type = db.Column(db.String(20), nullable=False)  # installed, uninstalled, updated
    app_name = db.Column(db.String(255), nullable=False)
    version = db.Column(db.String(100), nullable=True)

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'change_type': self.change_type,
            'app_name': self.app_name,
            'version': self.version
        }


class StateChange(db.Model):
    """State transition events (active/idle/locked)."""
    __tablename__ = 'state_changes'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    previous_state = db.Column(db.String(50), nullable=False)  # active, idle, locked
    current_state = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'previous_state': self.previous_state,
            'current_state': self.current_state,
            'timestamp': self.timestamp.isoformat()
        }


class DomainVisit(db.Model):
    """
    Sites opened (Column B) - Browser history without duration.
    Tracks all domains visited including background tabs and quick visits.
    """
    __tablename__ = 'domain_visits'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    domain = db.Column(db.String(255), nullable=False)
    url = db.Column(db.Text, nullable=True)
    browser = db.Column(db.String(50), nullable=True)
    visited_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    __table_args__ = (
        db.Index('ix_domain_visits_agent_date', 'agent_id', 'visited_at'),
        db.UniqueConstraint('agent_id', 'domain', 'visited_at', name='uq_domain_visit_unique'),
    )

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'domain': self.domain,
            'url': self.url,
            'browser': self.browser,
            'visited_at': self.visited_at.isoformat()
        }


# ============================================================================
# FRIENDLY APP NAMES MAPPING
# ============================================================================
APP_FRIENDLY_NAMES = {
    # Browsers
    'chrome.exe': 'Google Chrome',
    'brave.exe': 'Brave Browser',
    'firefox.exe': 'Mozilla Firefox',
    'msedge.exe': 'Microsoft Edge',
    'opera.exe': 'Opera',
    'vivaldi.exe': 'Vivaldi',
    'safari.exe': 'Safari',
    
    # Development
    'code.exe': 'VS Code',
    'devenv.exe': 'Visual Studio',
    'idea64.exe': 'IntelliJ IDEA',
    'pycharm64.exe': 'PyCharm',
    'webstorm64.exe': 'WebStorm',
    'sublime_text.exe': 'Sublime Text',
    'notepad++.exe': 'Notepad++',
    'notepad.exe': 'Notepad',
    'atom.exe': 'Atom',
    'cursor.exe': 'Cursor',
    'antigravity.exe': 'Antigravity',
    'putty.exe': 'PuTTY',
    'winscp.exe': 'WinSCP',
    
    # Communication
    'slack.exe': 'Slack',
    'teams.exe': 'Microsoft Teams',
    'ms-teams.exe': 'Microsoft Teams',
    'discord.exe': 'Discord',
    'zoom.exe': 'Zoom',
    'skype.exe': 'Skype',
    'telegram.exe': 'Telegram',
    'whatsapp.exe': 'WhatsApp',
    'olk.exe': 'Outlook (New)',
    
    # Office
    'winword.exe': 'Microsoft Word',
    'excel.exe': 'Microsoft Excel',
    'powerpnt.exe': 'PowerPoint',
    'outlook.exe': 'Outlook',
    'onenote.exe': 'OneNote',
    'toad.exe': 'Toad for Oracle',
    
    # Terminals
    'windowsterminal.exe': 'Windows Terminal',
    'cmd.exe': 'Command Prompt',
    'powershell.exe': 'PowerShell',
    'wt.exe': 'Windows Terminal',
    
    # System (visible but labeled properly)
    'explorer.exe': 'File Explorer',
    'shellhost.exe': 'Shell Host',
    'taskmgr.exe': 'Task Manager',
    'control.exe': 'Control Panel',
    'settings.exe': 'Windows Settings',
    'mstsc.exe': 'Remote Desktop',
    
    # Media
    'spotify.exe': 'Spotify',
    'vlc.exe': 'VLC Media Player',
    
    # Other
    'postman.exe': 'Postman',
    'insomnia.exe': 'Insomnia',
    'figma.exe': 'Figma',
    'notion.exe': 'Notion',
    'obsidian.exe': 'Obsidian',
    'searchapp.exe': 'Windows Search',
}

# ============================================================================
# SYSTEM APPS TO EXCLUDE FROM REPORTS
# These are background/system processes that don't represent actual user work
# ============================================================================
SYSTEM_APPS_FILTER = {
    'lockapp.exe',              # Windows Lock Screen
    'applicationframehost.exe', # UWP App Host (system process)
    'shellexperiencehost.exe',  # Windows Shell
    'startmenuexperiencehost.exe', # Start Menu
    'searchui.exe',             # Cortana/Search UI
    'runtimebroker.exe',        # Runtime Broker
    'backgroundtaskhost.exe',   # Background Tasks
    'systemsettings.exe',       # Settings app overlay
    'textinputhost.exe',        # Text Input
    'dwm.exe',                  # Desktop Window Manager
    'csrss.exe',                # Client Server Runtime
    'winlogon.exe',             # Windows Logon
    'sihost.exe',               # Shell Infrastructure Host
    'fontdrvhost.exe',          # Font Driver Host
    'ctfmon.exe',               # CTF Loader
    'dllhost.exe',              # DLL Host
    'wudfhost.exe',             # Windows User-Mode Driver Framework
    'smartscreen.exe',          # SmartScreen
    'securityhealthservice.exe', # Windows Security
    'phonelinkserver.exe',      # Phone Link
    'widgets.exe',              # Windows Widgets
    'gamebar.exe',              # Game Bar
    'gamebarpresencewriter.exe', # Game Bar
}

# ============================================================================
# SYSTEM INVENTORY APPS TO EXCLUDE FROM REPORTS
# These are Windows system apps that clutter the inventory
# ============================================================================
SYSTEM_INVENTORY_FILTER_PATTERNS = [
    'Microsoft.Windows.',          # Windows system components
    'MicrosoftWindows.',          # Alternate naming
    'Windows.',                   # Generic Windows apps
    'HERUNTERLADEN',              # German KB downloads
    'KB',                         # Knowledge Base updates
    'Update for',                 # Update packages
    'Security Update',            # Security updates
    'Hotfix',                     # Hotfixes
    'Python 3.',                  # Python components (will be consolidated)
]

# Python component patterns to consolidate
PYTHON_COMPONENT_PATTERNS = [
    'Add to Path',
    'Core Interpreter',
    'Development Libraries', 
    'Documentation',
    'Executables',
    'pip',
    'Standard Library',
    'Tcl/Tk',
    'Test Suite',
    'Utility Scripts',
    'py launcher',
]


def is_system_inventory_app(name: str) -> bool:
    """Check if the app is a system app that should be filtered from inventory."""
    if not name:
        return False
    name_lower = name.lower()
    for pattern in SYSTEM_INVENTORY_FILTER_PATTERNS:
        if pattern.lower() in name_lower:
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
        name = app.get('name', '')
        
        # Check if it's a Python entry
        python_match = re.match(r'^Python (\d+\.\d+(?:\.\d+)?)', name)
        if python_match:
            version = python_match.group(1)
            # Check if it's a component entry (not the base install)
            is_component = any(comp.lower() in name.lower() for comp in PYTHON_COMPONENT_PATTERNS)
            
            if version not in python_versions:
                python_versions[version] = {
                    'name': f'Python {version}',
                    'version': version,
                    'publisher': 'Python Software Foundation',
                    'source': app.get('source', 'Registry-HKLM'),
                    'install_date': app.get('install_date'),
                }
            
            # Keep the install location from the base install
            if not is_component and app.get('install_location'):
                python_versions[version]['install_location'] = app.get('install_location')
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
    'recent-download-history.local',
    'newtab.local',
    'extensions.local',
    'settings.local',
    'history.local',
    'downloads.local',
    'bookmarks.local',
    'chrome-native.local',
    
    # Edge internal pages
    'edge-settings.local',
    'edge-newtab.local',
    'edgeservices.local',
    
    # Other internal
    'localhost',
    '127.0.0.1',
    'about:blank',
    'about:newtab',
}


class RawEvent(db.Model):
    """
    Raw event log for all incoming telemetry.
    Stores exact payload before processing for auditing and replay.
    """
    __tablename__ = 'raw_events'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id'), nullable=False, index=True)
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
        db.Index('ix_raw_events_agent_seq', 'agent_id', 'sequence', 'event_type'),
    )


def get_friendly_app_name(exe_name: str) -> str:
    """Convert executable name to friendly display name."""
    if not exe_name:
        return 'Unknown'
    exe_lower = exe_name.lower()
    return APP_FRIENDLY_NAMES.get(exe_lower, exe_name.replace('.exe', '').title())


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

