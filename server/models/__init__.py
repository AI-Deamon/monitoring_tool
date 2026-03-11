"""
SentinelEdge Models Package
===========================
Provides backward-compatible re-exports from domain-specific sub-modules.

Usage (unchanged from before):
    from models import Agent, ScreenTime, AssetInfo
    # or
    from models.core import Organization, Agent, AgentCurrentStatus
    from models.telemetry import ScreenTime, AppUsage, AppSession
"""

# Core models: Organization, Agent, AgentCurrentStatus
from models.core import (
    Organization,
    Agent,
    AgentCurrentStatus,
)

# Telemetry models: ScreenTime, AppUsage, AppSession, DomainUsage, DomainSession
from models.telemetry import (
    ScreenTime,
    AppUsage,
    AppSession,
    DomainUsage,
    DomainSession,
)

# Inventory models + helper functions
from models.inventory import (
    AppInventory,
    AppInventoryChange,
    DomainVisit,
    APP_FRIENDLY_NAMES,
    SYSTEM_APPS_FILTER,
    SYSTEM_INVENTORY_FILTER_PATTERNS,
    PYTHON_COMPONENT_PATTERNS,
    is_system_inventory_app,
    consolidate_python_versions,
    get_friendly_app_name,
    is_system_app,
    INTERNAL_DOMAINS_FILTER,
    is_internal_domain,
)

# Events & raw data
from models.events import (
    StateChange,
    RawEvent,
)

# Asset & lifecycle models
from models.assets import (
    AssetInfo,
    SoftwareLifecycle,
    AssetLifecycleStatus,
    CLITool,
    HardwareDriver,
    VSCodeExtension,
    BrowserExtension,
    ApplicationPlugin,
    PortableApplication,
    NVDCacheEntry,
    WindowsUpdateRecord,
    SoftwareMeteringRecord,
    ProductKeyRecord,
    SecurityIndicator,
    UpdateHistory,
    UpdateGlobalPolicy,
    UpdateVersion,
)

# Make all models discoverable via `from models import *`
__all__ = [
    'Organization', 'Agent', 'AgentCurrentStatus',
    'ScreenTime', 'AppUsage', 'AppSession', 'DomainUsage', 'DomainSession',
    'AppInventory', 'AppInventoryChange', 'DomainVisit',
    'StateChange', 'RawEvent',
    'AssetInfo', 'SoftwareLifecycle', 'AssetLifecycleStatus',
    'CLITool', 'HardwareDriver', 'VSCodeExtension', 'BrowserExtension',
    'ApplicationPlugin', 'PortableApplication',
    'NVDCacheEntry', 'WindowsUpdateRecord', 'SoftwareMeteringRecord',
    'ProductKeyRecord', 'SecurityIndicator',
    'UpdateHistory', 'UpdateGlobalPolicy', 'UpdateVersion',
    'APP_FRIENDLY_NAMES', 'SYSTEM_APPS_FILTER',
    'INTERNAL_DOMAINS_FILTER',
    'is_system_inventory_app', 'consolidate_python_versions',
    'get_friendly_app_name', 'is_system_app', 'is_internal_domain',
]
