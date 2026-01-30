"""
Application Inventory Module - Enhanced
========================================
Tracks installed applications on Windows using PowerShell.
Features:
- Full inventory on registration
- Check every 4 hours
- Hash-based change detection
- Only sends updates when changes detected
"""
import subprocess
import json
import hashlib
import logging
import math
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional
from pathlib import Path
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# FIX: GUID-to-friendly-name mapping for Store apps that report package IDs
GUID_TO_FRIENDLY_NAME = {
    '1527c705-839a-4832-9118-54d4bd6a0c89': 'File Picker',
    'c5e2524a-ea46-4f67-841f-6a9465d9d515': 'File Explorer',
    'e2a4f912-2574-4a75-9bb0-0d023378592b': 'App Resolver UX',
    'f46d4000-fd22-4db4-ac8e-4e1ddde828fe': 'Add Folders Dialog',
}

# GUID Publisher mapping
GUID_TO_PUBLISHER = {
    'CE36AF3D-FF94-43EB-9908-7EC8FD1D29FB': 'PaddyXu',
    'ED346674-0FA1-4272-85CE-3187C9C86E26': 'HP Inc.',
    'EB51A5DA-0E72-4863-82E4-EA21C1F8DFE3': 'Intel Corporation',
}


@dataclass
class Application:
    """Represents an installed application"""
    name: str
    version: str = "Unknown"
    publisher: str = "Unknown"
    install_location: Optional[str] = None
    install_date: Optional[str] = None
    source: Optional[str] = None  # Registry-HKLM, Registry-HKCU, MicrosoftStore
    
    def to_dict(self) -> Dict:
        return asdict(self)


class InventoryTracker:
    """
    Enhanced App Inventory Tracker
    
    Behavior:
    - On registration: Send full inventory
    - Every 4 hours: Check for changes
    - If changes detected: Send updated inventory with change details
    """
    
    # Check interval: 4 hours in seconds
    CHECK_INTERVAL = 4 * 60 * 60  # 14400 seconds
    
    def __init__(self, config=None):
        self.config = config
        self.last_scan_time: Optional[datetime] = None
        self.last_hash: str = ""
        self.last_apps: Dict[str, Application] = {}
        self.is_first_scan: bool = True
        
        # State file for persistence
        self._state_file = self._get_state_file()
        self._load_state()
        
        # Create PowerShell script
        self._ps_script = self._get_script_path()
        self._create_powershell_script()
        
        logger.info("[INVENTORY] InventoryTracker initialized (4-hour intervals)")
    
    def _get_state_file(self) -> Path:
        """Get path to state file"""
        if self.config and hasattr(self.config, 'state_dir'):
            return Path(self.config.state_dir) / "app_inventory_state.json"
        return Path.home() / ".sentineledge" / "app_inventory_state.json"
    
    def _get_script_path(self) -> Path:
        """Get path to PowerShell script"""
        if self.config and hasattr(self.config, 'state_dir'):
            return Path(self.config.state_dir) / "collect_apps.ps1"
        return Path.home() / ".sentineledge" / "collect_apps.ps1"
    
    def _create_powershell_script(self):
        """Create comprehensive PowerShell script - FIXED for Store apps"""
        script_content = r'''
# Suppress progress output
$ProgressPreference = 'SilentlyContinue'
$VerbosePreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'

# FIX: Increase output width to prevent path truncation
$PSDefaultParameterValues['Out-String:Width'] = 4096

$AllApps = @()

# METHOD 1: System-wide apps (HKLM)
$paths = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
foreach ($path in $paths) {
    if (Test-Path $path) {
        $items = Get-ItemProperty $path -ErrorAction SilentlyContinue | 
                 Where-Object { 
                     $_.DisplayName -and 
                     $_.DisplayName -notmatch '^KB\d{6,}' -and 
                     $_.DisplayName -notmatch 'Update for' 
                 } |
                 Select-Object @{N='DisplayName';E={$_.DisplayName}},
                               @{N='DisplayVersion';E={$_.DisplayVersion}},
                               @{N='Publisher';E={$_.Publisher}},
                               @{N='InstallLocation';E={$_.InstallLocation}},
                               @{N='InstallDate';E={
                                   $rawDate = $_.InstallDate
                                   if ($rawDate -and $rawDate -match '^\d{8}$') {
                                       # Convert YYYYMMDD to YYYY-MM-DD
                                       $year = $rawDate.Substring(0,4)
                                       $month = $rawDate.Substring(4,2)
                                       $day = $rawDate.Substring(6,2)
                                       "$year-$month-$day"
                                   } else {
                                       $rawDate
                                   }
                               }},
                               @{N='Source';E={'Registry-HKLM'}}
        if ($items) { $AllApps += $items }
    }
}

# METHOD 2: User-installed apps (HKCU)
$userPaths = @('HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')
foreach ($path in $userPaths) {
    if (Test-Path $path) {
        $items = Get-ItemProperty $path -ErrorAction SilentlyContinue | 
                 Where-Object { $_.DisplayName } |
                 Select-Object @{N='DisplayName';E={$_.DisplayName}},
                               @{N='DisplayVersion';E={$_.DisplayVersion}},
                               @{N='Publisher';E={$_.Publisher}},
                               @{N='InstallLocation';E={$_.InstallLocation}},
                               @{N='InstallDate';E={
                                   $rawDate = $_.InstallDate
                                   if ($rawDate -and $rawDate -match '^\d{8}$') {
                                       # Convert YYYYMMDD to YYYY-MM-DD
                                       $year = $rawDate.Substring(0,4)
                                       $month = $rawDate.Substring(4,2)
                                       $day = $rawDate.Substring(6,2)
                                       "$year-$month-$day"
                                   } else {
                                       $rawDate
                                   }
                               }},
                               @{N='Source';E={'Registry-HKCU'}}
        if ($items) { $AllApps += $items }
    }
}

# METHOD 3: Microsoft Store Apps (FIXED - with install date retrieval)
# System noise apps to filter out
$SystemNoise = @(
    'Microsoft.AAD.BrokerPlugin',
    'Microsoft.AccountsControl',
    'Microsoft.AsyncTextService',
    'Microsoft.BioEnrollment',
    'Microsoft.CredDialogHost',
    'Microsoft.ECApp',
    'Microsoft.LockApp',
    'Microsoft.Win32WebViewHost',
    'Microsoft.XboxGameCallableUI',
    'Microsoft.Services.Store.Engagement',
    'Microsoft.VCLibs.*',
    'Microsoft.NET.Native.*',
    'Microsoft.UI.Xaml.*',
    'Microsoft.WindowsAppRuntime.*'
)

try {
    $storeApps = Get-AppxPackage -ErrorAction Stop |
                 Where-Object { 
                     $name = $_.Name
                     # Exclude Windows core components and system noise
                     $_.Name -notmatch '^Microsoft\.Windows\.' -and
                     -not ($SystemNoise | Where-Object { $name -like $_ })
                 } |
                 ForEach-Object {
                     $pkg = $_
                     $installDate = $null
                     
                     # FIX: Get install date from registry
                     $regPath = "HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages\$($pkg.PackageFullName)"
                     if (Test-Path $regPath) {
                         try {
                             $installTime = (Get-ItemProperty $regPath -ErrorAction SilentlyContinue).InstallTime
                             if ($installTime) {
                                $installDate = [DateTime]::FromFileTime($installTime).ToString('yyyy-MM-dd')
                             }
                         } catch {}
                     }
                     
                     # Fallback: Use InstallLocation folder creation date
                     if (-not $installDate -and $pkg.InstallLocation -and (Test-Path $pkg.InstallLocation)) {
                         try {
                             $installDate = (Get-Item $pkg.InstallLocation).CreationTime.ToString('yyyy-MM-dd')
                         } catch {}
                     }
                     
                     # Get full install location path (not truncated)
                     $fullPath = $pkg.InstallLocation
                     
                     [PSCustomObject]@{
                         DisplayName = $pkg.Name
                         DisplayVersion = $pkg.Version
                         Publisher = $pkg.Publisher
                         InstallLocation = $fullPath
                         InstallDate = $installDate
                         Source = 'MicrosoftStore'
                     }
                 }
    
    if ($storeApps) { $AllApps += $storeApps }
} catch {
    # Silently fail - don't break the script
}

# Deduplicate by DisplayName
$AllApps = $AllApps | Group-Object DisplayName | ForEach-Object { $_.Group[0] }

# Output clean JSON with full width
$AllApps | ConvertTo-Json -Compress -Depth 10
'''
        
        try:
            self._ps_script.parent.mkdir(parents=True, exist_ok=True)
            self._ps_script.write_text(script_content, encoding='utf-8')
            logger.debug(f"[INVENTORY] Comprehensive PowerShell script created: {self._ps_script}")
        except Exception as e:
            logger.error(f"[INVENTORY] Error creating PowerShell script: {e}")
    
    def _load_state(self):
        """Load previous state from disk"""
        try:
            if self._state_file.exists():
                with open(self._state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    self.last_hash = state.get('hash', '')
                    self.last_apps = {
                        name: Application(**data) 
                        for name, data in state.get('apps', {}).items()
                    }
                    last_scan = state.get('last_scan_time')
                    if last_scan:
                        self.last_scan_time = datetime.fromisoformat(last_scan)
                    self.is_first_scan = False
                    logger.debug(f"[INVENTORY] Loaded state: {len(self.last_apps)} apps")
        except Exception as e:
            logger.warning(f"[INVENTORY] Could not load state: {e}")
            self.is_first_scan = True
    
    def _save_state(self, apps_dict: Dict[str, Application], apps_hash: str):
        """Save current state to disk"""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'hash': apps_hash,
                'apps': {name: app.to_dict() for name, app in apps_dict.items()},
                'last_scan_time': datetime.now(timezone.utc).isoformat(),
                'total_apps': len(apps_dict)
            }
            with open(self._state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            logger.debug(f"[INVENTORY] State saved: {len(apps_dict)} apps")
        except Exception as e:
            logger.error(f"[INVENTORY] Error saving state: {e}")
    
    def _compute_hash(self, apps: List[Application]) -> str:
        """Compute hash of app inventory for change detection"""
        app_list = sorted([f"{app.name.lower()}:{app.version}" for app in apps])
        return hashlib.sha256("|".join(app_list).encode()).hexdigest()[:16]
    
    def _collect_via_powershell(self) -> Optional[List[Application]]:
        """Collect apps using PowerShell script (HIDDEN WINDOW)"""
        try:
            # ✅ FIXED: Hide PowerShell window to prevent popup
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # ✅ Added -NonInteractive to prevent any prompts that could show a window
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", 
                 "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", 
                 "-File", str(self._ps_script)],
                capture_output=True,
                text=True,
                timeout=120,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode != 0:
                logger.error(f"[INVENTORY] PowerShell failed: {result.stderr[:200]}")
                return None
            
            # Parse JSON output
            output = result.stdout.strip()
            if not output:
                logger.warning("[INVENTORY] Empty output from PowerShell")
                return []
            
            try:
                apps_data = json.loads(output)
                if not isinstance(apps_data, list):
                    apps_data = [apps_data]
            except json.JSONDecodeError as e:
                logger.error(f"[INVENTORY] Failed to parse JSON: {e}")
                return None
            
            apps = []
            for app_data in apps_data:
                try:
                    # Support both old 'Name' and new 'DisplayName' keys
                    name = app_data.get('DisplayName') or app_data.get('Name') or ''
                    name = name.strip()
                    
                    # FIX: Normalize GUID names to friendly names
                    name_lower = name.lower()
                    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', name_lower):
                        friendly = GUID_TO_FRIENDLY_NAME.get(name_lower)
                        if friendly:
                            logger.debug(f"[INVENTORY] Mapped GUID {name} → {friendly}")
                            name = friendly
                        else:
                            logger.debug(f"[INVENTORY] Unknown GUID app: {name}")
                            name = f"System App ({name[:8]}...)"
                    
                    version = app_data.get('DisplayVersion') or app_data.get('Version') or 'Unknown'
                    publisher = app_data.get('Publisher') or 'Unknown'
                    
                    # FIX: Normalize GUID publishers to company names
                    publisher_upper = publisher.upper() if publisher else ''
                    if publisher_upper in GUID_TO_PUBLISHER:
                        publisher = GUID_TO_PUBLISHER[publisher_upper]
                        logger.debug(f"[INVENTORY] Mapped publisher GUID to {publisher}")
                    
                    install_location = app_data.get('InstallLocation')
                    install_date = app_data.get('InstallDate')
                    source = app_data.get('Source')  # Registry-HKLM, Registry-HKCU, MicrosoftStore
                    
                    app = Application(
                        name=name,
                        version=version,
                        publisher=publisher,
                        install_location=install_location,
                        install_date=install_date,
                        source=source
                    )
                    if app.name:
                        # Diagnostic logging for missing data
                        if not install_location:
                            logger.debug(f"[INVENTORY] {name}: No install location")
                        if not install_date:
                            logger.debug(f"[INVENTORY] {name}: No install date")
                        apps.append(app)
                except Exception as e:
                    continue
            
            return apps
            
        except subprocess.TimeoutExpired:
            logger.error("[INVENTORY] PowerShell timeout (120s)")
            return None
        except Exception as e:
            logger.error(f"[INVENTORY] Collection error: {e}")
            return None
    
    def should_check(self) -> bool:
        """
        Determine if we should check inventory.
        
        Returns True if:
        - First run (no previous scan)
        - More than 4 hours since last scan
        """
        if self.is_first_scan or self.last_scan_time is None:
            return True
        
        elapsed = (datetime.now(timezone.utc) - self.last_scan_time).total_seconds()
        return elapsed >= self.CHECK_INTERVAL
    
    def scan(self, force: bool = False) -> Optional[List[Dict]]:
        """
        Scan installed applications.
        
        Args:
            force: Force scan regardless of interval
            
        Returns:
            List of application dicts, or None if no scan needed/failed
        """
        apps = self._collect_via_powershell()
        
        if apps is None:
            logger.error("[INVENTORY] Scan failed")
            return None
        
        self.last_scan_time = datetime.now(timezone.utc)
        
        # Sort by name
        apps.sort(key=lambda x: x.name.lower())
        
        logger.info(f"[INVENTORY] Scanned {len(apps)} applications")
        return [app.to_dict() for app in apps]
    
    def collect(self, force: bool = False) -> Optional[Dict]:
        """
        Collect inventory with change detection.
        
        Behavior:
        - If first run or forced: Return full inventory
        - If changes detected: Return inventory with change details
        - If no changes: Return None (no upload needed)
        
        Args:
            force: Force full inventory (use on registration)
            
        Returns:
            Dict with inventory data, or None if no changes
        """
        if not force and not self.should_check():
            return None
        
        logger.info("[INVENTORY] Collecting app inventory...")
        
        apps = self._collect_via_powershell()
        if apps is None:
            return None
        
        # Fix #6: Validate inventory scan completed successfully
        if len(apps) < 5:  # Minimum threshold - even basic Windows has more apps
            logger.error(
                f"INVENTORY: Scan incomplete, only {len(apps)} apps found. "
                f"Expected at least 5. Skipping this collection."
            )
            return None

        logger.info(f"INVENTORY: Collected {len(apps)} applications successfully")
        
        # Build dict and compute hash
        apps_dict = {app.name: app for app in apps}
        current_hash = self._compute_hash(apps)
        
        # Check for changes
        changes = {
            'installed': [],
            'uninstalled': [],
            'updated': [],
            'changed': False
        }
        
        is_registration = self.is_first_scan or force
        
        if current_hash != self.last_hash:
            changes['changed'] = True
            
            if not is_registration and self.last_apps:
                previous_names = set(self.last_apps.keys())
                current_names = set(apps_dict.keys())
                
                changes['installed'] = sorted(list(current_names - previous_names))
                changes['uninstalled'] = sorted(list(previous_names - current_names))
                
                # Check for version updates
                for name in current_names & previous_names:
                    if apps_dict[name].version != self.last_apps[name].version:
                        changes['updated'].append(name)
                changes['updated'].sort()
                
                logger.info(
                    f"[INVENTORY] Changes detected: "
                    f"+{len(changes['installed'])} -{len(changes['uninstalled'])} "
                    f"~{len(changes['updated'])}"
                )
        else:
            if not is_registration:
                logger.debug("[INVENTORY] No changes detected")
                self.last_scan_time = datetime.now(timezone.utc)
                return None
        
        # Update state
        self._save_state(apps_dict, current_hash)
        self.last_hash = current_hash
        self.last_apps = apps_dict
        self.is_first_scan = False
        self.last_scan_time = datetime.now(timezone.utc)
        
        result = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_apps': len(apps),
            'inventory_hash': current_hash,
            'is_full_inventory': is_registration,
            'changes': changes,
            'apps': [app.to_dict() for app in apps]
        }
        
        if is_registration:
            logger.info(f"[INVENTORY] Full inventory: {len(apps)} apps (hash: {current_hash})")
        else:
            logger.info(f"[INVENTORY] Updated inventory: {len(apps)} apps")
        
        # Debug: Log sample of first app with all fields
        if result['apps']:
            sample = result['apps'][0]
            logger.info(f"[INVENTORY] Sample app JSON:")
            logger.info(f"  Name: {sample.get('name')}")
            logger.info(f"  Version: {sample.get('version')}")
            logger.info(f"  Publisher: {sample.get('publisher')}")
            logger.info(f"  Location: {sample.get('install_location')}")
            logger.info(f"  Date: {sample.get('install_date')}")
            logger.info(f"  Source: {sample.get('source')}")
        
        return result  # CRITICAL: Return the inventory data!

        
    def _validate_field(self, field_name: str, field_value: str) -> bool:
        """Validate individual field values"""
        if not field_value:
            return True  # Empty field is valid
        
        # Common validation patterns
        invalid_patterns = {
            'name': [
                r'[<>:"\'"]',  # No special chars
                r'^(CON|PRN|AUX|LPT)\d+\d+$',  # No Windows device names
                r'^(?|\.|\.\.|/|\\)$'  # No paths or special chars
            ],
            'version': [
                r'[<>:"\'"]',  # No special chars
                r'^[0-9]+$',  # Version numbers only
                r'^[a-fA-F\.]{0,}$',  # Version format check
            ],
            'publisher': [
                r'[<>:"\'"]',  # No special chars
                r'^(Microsoft|Adobe|Oracle|VMware|Unknown)$',  # Block known fake publishers
            ]
        }
        
        # Check against invalid patterns
        field_patterns = invalid_patterns.get(field_name, [])
        for pattern in field_patterns:
            if re.search(pattern, field_value):
                logger.warning(f"[INVENTORY] Invalid {field_name}: {field_value}")
                return False
        
        return True
    
    def _validate_inventory(self, inventory: Dict) -> int:
        """Validate inventory data for safety"""
        if not inventory or 'apps' not in inventory:
            return 0
        
        invalid_count = 0
        for app_data in inventory.get('apps', []):
            app_name = app_data.get('name', '').strip()
            if not app_name:
                logger.warning(f"[INVENTORY] Invalid app entry: missing name")
                continue
            
            # Validate all fields
            fields_to_validate = ['name', 'version', 'publisher', 'install_location']
            for field in fields_to_validate:
                field_value = app_data.get(field, '')
                if not self._validate_field(field, field_value):
                    invalid_count += 1
            
            # Additional sanity checks
            # App name must be reasonable length (1-100 chars)
            if len(app_name) < 1 or len(app_name) > 100:
                logger.warning(f"[INVENTORY] Invalid app name length: {app_name}")
                invalid_count += 1
            
            # Version must be reasonable (format x.x.x, max 50 chars)
            version = app_data.get('version', '')
            if version and not re.match(r'^\d+\.\d+$', version):
                logger.warning(f"[INVENTORY] Invalid version format: {version} for {app_name}")
                invalid_count += 1
        
        if invalid_count > 0:
            logger.warning(f"[INVENTORY] Rejected {invalid_count} invalid entries")
        
        return invalid_count
    
    def _add_validation_results(self, inventory: Dict, invalid_count: int) -> Dict:
        """Add validation results to inventory dict"""
        if invalid_count > 0:
            inventory['validation'] = {
                'invalid_entries': invalid_count,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        else:
            inventory['validation'] = {
                'invalid_entries': 0,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        
        return inventory
    
    def _validate_app_data(self, app_data: Dict) -> Dict:
        """Validate a single app's data"""
        if not app_data:
            return {}
        
        validated_data = {}
        
        # Sanitize name
        name = app_data.get('name', '').strip()
        if not name:
            return app_data  # Skip empty names
        
        # Only keep alphanumeric chars, dots, hyphens, and spaces
        validated_name = re.sub(r'[^a-zA-Z0-9\-\.\s]', '', name)
        validated_name = re.sub(r'\s+', ' ', validated_name)  # Replace multiple spaces with single space
        validated_name = validated_name[:100]  # Limit length
        
        # Validate other fields (FIXED: Added install_date and source)
        for field in ['version', 'publisher', 'install_location', 'install_date', 'source']:
            if field in app_data:
                value = app_data[field]
                
                # Metadata fields - don't validate, just preserve
                if field in ['install_date', 'source', 'install_location']:
                    # Keep original value or None (not empty string)
                    validated_data[field] = value if value else None
                # Validate other string fields
                elif value and not self._validate_field(field, str(value)):
                    validated_data[field] = f"[INVALID]{value}"
                else:
                    validated_data[field] = value if value else None
            else:
                # Use None for metadata fields, "Unknown" for required fields
                validated_data[field] = None if field in ['install_date', 'source', 'install_location'] else "Unknown"
        
        # Create validated app object (FIXED: use validated_data for ALL fields)
        validated_app = Application(
            name=validated_name,
            version=validated_data.get('version') or 'Unknown',
            publisher=validated_data.get('publisher') or 'Unknown',
            install_location=validated_data.get('install_location'),  # None if not available
            source=validated_data.get('source'),  # None if not available
            install_date=validated_data.get('install_date')  # None if not available
        )
        
        return validated_app
    
    def _normalize_publisher(self, publisher: str) -> str:
        """Normalize publisher name"""
        if not publisher:
            return "Unknown"
        
        # Convert to title case for display
        normalized = publisher.title().strip()
        
        # Remove common artifacts
        artifacts_to_remove = [' Corporation', ' Corp.', ' Inc.', ' LLC', ' Ltd.']
        for artifact in artifacts_to_remove:
            normalized = normalized.replace(artifact, '')
        
        # Limit length
        return normalized[:50]
    
    def _validate_and_normalize(self, inventory: Dict) -> Dict:
        """Validate and normalize all app data"""
        if not inventory or 'apps' not in inventory:
            return inventory
        
        validated_apps = {}
        invalid_count = 0
        
        for app_key, app_data in list(inventory.get('apps', {}).items()):
            # Validate and normalize app data
            validated_app = self._validate_app_data(app_data)
            if validated_app:
                validated_apps[app_key] = validated_app
                invalid_count += 1
        
        if invalid_count > 0:
            logger.warning(f"[INVENTORY] Rejected {invalid_count} apps during validation")
        
        # Return with validation results
        return self._add_validation_results(inventory, invalid_count)
