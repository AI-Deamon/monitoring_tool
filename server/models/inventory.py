"""
Inventory Models: AppInventory, AppInventoryChange, DomainVisit
Plus helper functions and constants for app/domain filtering.
"""
import re
from datetime import datetime
from extensions import db
from sqlalchemy.dialects import postgresql


class AppInventory(db.Model):
    """Application inventory snapshot."""
    __tablename__ = 'app_inventory'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    version = db.Column(db.String(100), nullable=True)
    publisher = db.Column(db.String(255), nullable=True)
    install_location = db.Column(db.Text, nullable=True)
    install_date = db.Column(db.Date, nullable=True)
    source = db.Column(db.String(50), nullable=True)  # Registry-HKLM, Registry-HKCU, MicrosoftStore
    architecture = db.Column(db.String(50), nullable=True)  # x86, x64, ARM64, Unknown
    uninstall_command = db.Column(db.Text, nullable=True)
    estimated_size_kb = db.Column(db.BigInteger, nullable=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('agent_id', 'name', name='uq_app_inventory_agent_name'),)

    def to_dict(self):
        return {
            'name': self.name,
            'version': self.version,
            'publisher': self.publisher,
            'install_location': self.install_location,
            'install_date': self.install_date.isoformat() if self.install_date else None,
            'source': self.source,
            'architecture': self.architecture,
            'uninstall_command': self.uninstall_command,
            'estimated_size_kb': self.estimated_size_kb
        }


class AppInventoryChange(db.Model):
    """Tracks installed/uninstalled app changes for audit history."""
    __tablename__ = 'app_inventory_changes'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
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


class DomainVisit(db.Model):
    """Sites opened (Column B) - Browser history without duration.
    Tracks all domains visited including background tabs and quick visits.
    """
    __tablename__ = 'domain_visits'

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), nullable=False, index=True)
    domain = db.Column(db.String(255), nullable=False)
    browser = db.Column(db.String(100), nullable=True)
    url = db.Column(db.Text, nullable=True)
    title = db.Column(db.Text, nullable=True)
    visited_at = db.Column(db.DateTime, default=datetime.utcnow)
    visit_count = db.Column(db.Integer, default=1)

    __table_args__ = (
        db.Index('ix_domain_visits_agent_date', 'agent_id', 'visited_at'),
        db.UniqueConstraint('agent_id', 'domain', 'visited_at', name='uq_domain_visit_unique'),
    )

    def to_dict(self):
        return {
            'agent_id': self.agent_id,
            'domain': self.domain,
            'browser': self.browser,
            'url': self.url,
            'title': self.title,
            'visited_at': self.visited_at.isoformat() if self.visited_at else None,
            'visit_count': self.visit_count
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
# ============================================================================
SYSTEM_APPS_FILTER = {
    'lockapp.exe',
    'searchhost.exe',
    'applicationframehost.exe',
    'shellexperiencehost.exe',
    'startmenuexperiencehost.exe',
    'searchui.exe',
    'runtimebroker.exe',
    'backgroundtaskhost.exe',
    'systemsettings.exe',
    'textinputhost.exe',
    'dwm.exe',
    'csrss.exe',
    'winlogon.exe',
    'sihost.exe',
    'fontdrvhost.exe',
    'ctfmon.exe',
    'dllhost.exe',
    'wudfhost.exe',
    'smartscreen.exe',
    'securityhealthservice.exe',
    'phonelinkserver.exe',
    'widgets.exe',
    'gamebar.exe',
    'gamebarpresencewriter.exe',
}

# ============================================================================
# SYSTEM INVENTORY APPS TO EXCLUDE FROM REPORTS
# ============================================================================
# Pre-lowercased patterns for faster matching (Bolt ⚡)
SYSTEM_INVENTORY_FILTER_PATTERNS = [p.lower() for p in [
    'Microsoft.Windows.',
    'MicrosoftWindows.',
    'Windows.',
    'HERUNTERLADEN',
    'KB',
    'Update for',
    'Security Update',
    'Hotfix',
    'Python 3.',
]]

# Pre-lowercased patterns for faster matching (Bolt ⚡)
PYTHON_COMPONENT_PATTERNS = [p.lower() for p in [
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
]]


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
    python_versions = {}
    other_apps = []
    
    for app in apps:
        name = app.get('name', '')
        
        # Check if it's a Python entry
        python_match = re.match(r'^Python (\d+\.\d+(?:\.\d+)?)', name)
        if python_match:
            version = python_match.group(1)
            is_component = any(comp.lower() in name.lower() for comp in PYTHON_COMPONENT_PATTERNS)
            
            if version not in python_versions:
                python_versions[version] = {
                    'name': f'Python {version}',
                    'version': version,
                    'publisher': 'Python Software Foundation',
                    'source': app.get('source', 'Registry-HKLM'),
                    'install_date': app.get('install_date'),
                }
            
            if not is_component and app.get('install_location'):
                python_versions[version]['install_location'] = app.get('install_location')
        else:
            other_apps.append(app)
    
    for version_data in python_versions.values():
        other_apps.append(version_data)
    
    return other_apps


# ============================================================================
# INTERNAL/SYSTEM DOMAINS TO EXCLUDE FROM REPORTS
# ============================================================================
INTERNAL_DOMAINS_FILTER = {
    'recent-download-history.local',
    'newtab.local',
    'extensions.local',
    'settings.local',
    'history.local',
    'downloads.local',
    'bookmarks.local',
    'chrome-native.local',
    'edge-settings.local',
    'edge-newtab.local',
    'edgeservices.local',
    'localhost',
    '127.0.0.1',
    'about:blank',
    'about:newtab',
}


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
