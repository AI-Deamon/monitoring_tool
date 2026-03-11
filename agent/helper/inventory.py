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
import time
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
    source: Optional[str] = None  # Registry-HKLM, Registry-HKCU, MicrosoftStore, DiskScan
    architecture: Optional[str] = None  # x86, x64, ARM64, Unknown
    uninstall_command: Optional[str] = None
    estimated_size_kb: Optional[int] = None
    
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
        self._consecutive_timeouts: int = 0
        self._max_consecutive_timeouts: int = 3
        self._timeout_cooldown_seconds: int = 30 * 60
        self._timeout_cooldown_until: float = 0.0
        self._is_suspended_check = None  # Set by main.py to check system suspend state
        
        # State file for persistence
        self._state_file = self._get_state_file()
        self._load_state()
        
        # Create PowerShell script
        self._ps_script = self._get_script_path()
        self._create_powershell_script()
        
        logger.info("[INVENTORY] InventoryTracker initialized (4-hour intervals)")

    def _in_timeout_cooldown(self) -> bool:
        return self._timeout_cooldown_until > time.time()
    
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

$script:AllApps = @()

# --- Helper: Resolve install location from registry entry ---
function Get-ResolvedInstallLocation {
    param($RegItem)
    
    # 1. Direct InstallLocation value
    $loc = $RegItem.InstallLocation
    if ($loc -and (Test-Path $loc -ErrorAction SilentlyContinue)) { return $loc }
    
    # 2. Extract directory from DisplayIcon (often contains exe path)
    $icon = $RegItem.DisplayIcon
    if ($icon) {
        $iconPath = $icon -replace ',.*$', '' -replace '"', ''
        if ($iconPath -and (Test-Path $iconPath -ErrorAction SilentlyContinue)) {
            return [System.IO.Path]::GetDirectoryName($iconPath)
        }
    }
    
    # 3. Try InstallSource
    $src = $RegItem.InstallSource
    if ($src -and (Test-Path $src -ErrorAction SilentlyContinue)) { return $src }
    
    # 4. Extract directory from UninstallString
    $uninstall = $RegItem.UninstallString
    if ($uninstall) {
        $uninstallPath = $uninstall -replace '"', '' -replace '\s+/.*$', '' -replace '\s+--.*$', ''
        if ($uninstallPath -and (Test-Path $uninstallPath -ErrorAction SilentlyContinue)) {
            return [System.IO.Path]::GetDirectoryName($uninstallPath)
        }
    }
    
    # 5. Return raw InstallLocation even if path doesn't exist (may be on another drive)
    if ($loc) { return $loc }
    
    return $null
}

# --- Helper: Resolve install date from registry entry ---
function Get-ResolvedInstallDate {
    param($RegItem, $ResolvedLocation)
    
    # 1. Direct InstallDate from registry (YYYYMMDD format)
    $rawDate = $RegItem.InstallDate
    if ($rawDate -and $rawDate -match '^\d{8}$') {
        $year = $rawDate.Substring(0,4)
        $month = $rawDate.Substring(4,2)
        $day = $rawDate.Substring(6,2)
        return "$year-$month-$day"
    }
    
    # 2. Registry key LastWriteTime (when the Uninstall key was last modified)
    $keyPath = $RegItem.PSPath
    if ($keyPath) {
        try {
            $key = Get-Item $keyPath -ErrorAction SilentlyContinue
            if ($key -and $key.LastWriteTime) {
                return $key.LastWriteTime.ToString('yyyy-MM-dd')
            }
        } catch {}
    }
    
    # 3. Folder creation date from resolved install location
    if ($ResolvedLocation -and (Test-Path $ResolvedLocation -ErrorAction SilentlyContinue)) {
        try {
            return (Get-Item $ResolvedLocation -ErrorAction SilentlyContinue).CreationTime.ToString('yyyy-MM-dd')
        } catch {}
    }
    
    return $null
}

# --- Helper: Detect application architecture ---
function Get-AppArchitecture {
    param($RegItem, $InstallLocation, $Source)
    
    # 1. Check if from WOW6432Node (32-bit on 64-bit OS)
    if ($Source -eq 'Registry-HKLM' -and $RegItem.PSPath -match 'WOW6432Node') {
        return 'x86'
    }
    
    # 2. Check install location path
    if ($InstallLocation) {
        if ($InstallLocation -match 'Program Files \(x86\)') {
            return 'x86'
        }
        if ($InstallLocation -match 'Program Files') {
            return 'x64'
        }
    }
    
    # 3. Try to detect from executable PE header
    if ($InstallLocation -and (Test-Path $InstallLocation)) {
        try {
            $exeFiles = Get-ChildItem -Path $InstallLocation -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 3
            foreach ($exe in $exeFiles) {
                try {
                    $bytes = [System.IO.File]::ReadAllBytes($exe.FullName)
                    if ($bytes.Length -gt 256) {
                        # PE header offset at 0x3C
                        $peOffset = [BitConverter]::ToInt32($bytes, 60)
                        if ($peOffset -gt 0 -and $peOffset -lt $bytes.Length - 6) {
                            # Machine type at PE header + 4
                            $machine = [BitConverter]::ToUInt16($bytes, $peOffset + 4)
                            if ($machine -eq 0x8664) { return 'x64' }
                            if ($machine -eq 0x014c) { return 'x86' }
                            if ($machine -eq 0xAA64) { return 'ARM64' }
                        }
                    }
                } catch {}
            }
        } catch {}
    }
    
    return 'Unknown'
}

# --- Helper: Resolve architecture from executable ---
function Get-ExeArchitecture {
    param($Path)
    if (-not (Test-Path $Path)) { return 'Unknown' }
    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
        if ($bytes.Length -gt 256) {
            $peOffset = [BitConverter]::ToInt32($bytes, 60)
            if ($peOffset -gt 0 -and $peOffset -lt $bytes.Length - 6) {
                $machine = [BitConverter]::ToUInt16($bytes, $peOffset + 4)
                if ($machine -eq 0x8664) { return 'x64' }
                if ($machine -eq 0x014c) { return 'x86' }
                if ($machine -eq 0xAA64) { return 'ARM64' }
            }
        }
    } catch {}
    return 'Unknown'
}

# --- Drive Scanning Logic ---
function Scan-ForPortableApps {
    param([string[]]$Drives)
    
    $PortableApps = @()
    $ScanPaths = @(
        'Program Files',
        'Program Files (x86)',
        'ProgramData',
        'Users\*\AppData\Local',
        'Users\*\AppData\Roaming'
    )
    
    foreach ($drive in $Drives) {
        $root = "${drive}:\"
        if (-not (Test-Path $root)) { continue }
        
        foreach ($scanPath in $ScanPaths) {
            $fullPath = Join-Path $root $scanPath
            try {
                $dirs = Get-ChildItem -Path $fullPath -Directory -ErrorAction SilentlyContinue
                foreach ($dir in $dirs) {
                    # Skip if already found in registry (heuristically based on path)
                    $dirPath = $dir.FullName
                    if ($script:AllApps | Where-Object { $_.InstallLocation -eq $dirPath }) { continue }
                    
                    # Look for main executable
                    $exe = Get-ChildItem -Path $dirPath -Filter "*.exe" -File -ErrorAction SilentlyContinue | 
                           Sort-Object Length -Descending | Select-Object -First 1
                    
                    if ($exe) {
                        # Simple publisher detection from file info
                        $versionInfo = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($exe.FullName)
                        $PortableApps += [PSCustomObject]@{
                            DisplayName = $dir.Name
                            DisplayVersion = $versionInfo.ProductVersion -or 'Unknown'
                            Publisher = $versionInfo.CompanyName -or 'Unknown'
                            InstallLocation = $dirPath
                            InstallDate = $dir.CreationTime.ToString('yyyy-MM-dd')
                            Source = 'DiskScan'
                            Architecture = Get-ExeArchitecture $exe.FullName
                            UninstallCommand = $null
                            EstimatedSizeKB = [math]::Round((Get-ChildItem $dirPath -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1KB)
                        }
                    }
                }
            } catch {}
        }
    }
    return $PortableApps
}

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
                 ForEach-Object {
                     $resolvedLoc = Get-ResolvedInstallLocation $_
                     $resolvedDate = Get-ResolvedInstallDate $_ $resolvedLoc
                     $arch = Get-AppArchitecture $_ $resolvedLoc 'Registry-HKLM'
                     $uninstallCmd = $_.UninstallString
                     if ($_.QuietUninstallString) { $uninstallCmd = $_.QuietUninstallString }
                     
                     [PSCustomObject]@{
                         DisplayName = $_.DisplayName
                         DisplayVersion = $_.DisplayVersion
                         Publisher = $_.Publisher
                         InstallLocation = $resolvedLoc
                         InstallDate = $resolvedDate
                         Source = 'Registry-HKLM'
                         Architecture = $arch
                         UninstallCommand = $uninstallCmd
                         EstimatedSizeKB = $_.EstimatedSize
                     }
                 }
        if ($items) { $script:AllApps += $items }
    }
}

# METHOD 2: User-installed apps (HKCU)
$userPaths = @('HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')
foreach ($path in $userPaths) {
    if (Test-Path $path) {
        $items = Get-ItemProperty $path -ErrorAction SilentlyContinue | 
                 Where-Object { $_.DisplayName } |
                 ForEach-Object {
                     $resolvedLoc = Get-ResolvedInstallLocation $_
                     $resolvedDate = Get-ResolvedInstallDate $_ $resolvedLoc
                     $arch = Get-AppArchitecture $_ $resolvedLoc 'Registry-HKCU'
                     $uninstallCmd = $_.UninstallString
                     if ($_.QuietUninstallString) { $uninstallCmd = $_.QuietUninstallString }
                     
                     [PSCustomObject]@{
                         DisplayName = $_.DisplayName
                         DisplayVersion = $_.DisplayVersion
                         Publisher = $_.Publisher
                         InstallLocation = $resolvedLoc
                         InstallDate = $resolvedDate
                         Source = 'Registry-HKCU'
                         Architecture = $arch
                         UninstallCommand = $uninstallCmd
                         EstimatedSizeKB = $_.EstimatedSize
                     }
                 }
        if ($items) { $script:AllApps += $items }
    }
}

# METHOD 3: Microsoft Store Apps
try {
    $storeApps = Get-AppxPackage -ErrorAction SilentlyContinue |
                 Where-Object { 
                     $name = $_.Name
                     $_.Name -notmatch '^Microsoft\.Windows\.' -and
                     -not ($SystemNoise | Where-Object { $name -like $_ })
                 } |
                 ForEach-Object {
                     $pkg = $_
                     $installDate = $null
                     $regPath = "HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages\$($pkg.PackageFullName)"
                     if (Test-Path $regPath) {
                         try {
                             $installTime = (Get-ItemProperty $regPath -ErrorAction SilentlyContinue).InstallTime
                             if ($installTime) {
                                $installDate = [DateTime]::FromFileTime($installTime).ToString('yyyy-MM-dd')
                             }
                         } catch {}
                     }
                      
                      if (-not $installDate -and $pkg.InstallLocation -and (Test-Path $pkg.InstallLocation)) {
                          try {
                              $installDate = (Get-Item $pkg.InstallLocation).CreationTime.ToString('yyyy-MM-dd')
                          } catch {}
                      }
                      
                      $fullPath = $pkg.InstallLocation
                      $storeArch = if ($pkg.Architecture) { $pkg.Architecture.ToString() } else { 'Unknown' }
                      
                      [PSCustomObject]@{
                          DisplayName = $pkg.Name
                          DisplayVersion = $pkg.Version
                          Publisher = $pkg.Publisher
                          InstallLocation = $fullPath
                          InstallDate = $installDate
                          Source = 'MicrosoftStore'
                          Architecture = $storeArch
                          UninstallCommand = $null
                          EstimatedSizeKB = $null
                      }
                  }
    
    if ($storeApps) { $script:AllApps += $storeApps }
} catch {}

# METHOD 4: Disk Scan for Portable Apps
$portable = Scan-ForPortableApps -Drives @('C', 'D')
if ($portable) { $script:AllApps += $portable }

# Deduplicate by DisplayName
$script:AllApps = $script:AllApps | Group-Object DisplayName | ForEach-Object { $_.Group[0] }

# Output clean JSON with full width
$script:AllApps | ConvertTo-Json -Compress -Depth 10
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
        # Include version, publisher, arch, and uninstall cmd in hash for better change detection
        # We skip estimated_size_kb as it might fluctuate slightly on disk scans
        app_list = sorted([
            f"{app.name.lower()}:{app.version}:{app.publisher}:{app.architecture}:{app.uninstall_command}" 
            for app in apps
        ])
        return hashlib.sha256("|".join(app_list).encode()).hexdigest()[:16]
    
    def _kill_process_tree(self, process):
        """Aggressively kill a subprocess and its entire process tree."""
        if not process:
            return
        try:
            process.kill()
        except Exception:
            pass
        try:
            if process.pid:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, text=True, timeout=10
                )
        except Exception:
            pass

    def _collect_via_powershell(self, is_suspended_check=None) -> Optional[List[Application]]:
        """Collect apps using PowerShell script with suspend-aware timeout.

        Uses self._is_suspended_check as default if no explicit checker passed.

        Instead of one blocking ``communicate(timeout=120)`` call, this polls
        every 5 seconds so the helper can detect a system suspend mid-collection
        and abort immediately — preventing zombie PowerShell processes that
        hang the main loop on resume.

        Args:
            is_suspended_check: Optional callable returning True when the
                system is suspended.  Passed from main.py via the collector.
        """
        process = None
        try:
            # Use instance-level checker as fallback
            check = is_suspended_check or self._is_suspended_check

            # Skip if system is currently suspended
            if check and check():
                logger.info("[INVENTORY] Skipping collection — system suspended")
                return None

            if self._in_timeout_cooldown():
                remaining = int(max(0, self._timeout_cooldown_until - time.time()))
                logger.warning(f"[INVENTORY] [HEALTH] Collection paused due to timeout circuit breaker ({remaining}s remaining)")
                return None

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                 "-File", str(self._ps_script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # ── Suspend-aware polling loop ──────────────────────────
            # Poll every 5s so we can abort if the system suspends.
            POLL_INTERVAL = 5   # seconds per poll chunk
            TOTAL_TIMEOUT = 120  # overall deadline
            deadline = time.time() + TOTAL_TIMEOUT
            stdout = None
            stderr = None

            while time.time() < deadline:
                # Check for suspend between polls
                if check and check():
                    logger.info("[INVENTORY] System suspended mid-collection — aborting PowerShell")
                    self._kill_process_tree(process)
                    return None

                try:
                    stdout, stderr = process.communicate(timeout=POLL_INTERVAL)
                    break  # Process completed normally
                except subprocess.TimeoutExpired:
                    continue  # Still running, poll again
            else:
                # Overall deadline exceeded
                raise subprocess.TimeoutExpired(
                    cmd="powershell.exe", timeout=TOTAL_TIMEOUT
                )

            if process.returncode != 0:
                logger.error(f"[INVENTORY] PowerShell failed: {(stderr or '')[:200]}")
                return None

            output = (stdout or '').strip()
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
                    name = app_data.get('DisplayName') or app_data.get('Name') or ''
                    name = name.strip()

                    name_lower = name.lower()
                    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', name_lower):
                        friendly = GUID_TO_FRIENDLY_NAME.get(name_lower)
                        if friendly:
                            logger.debug(f"[INVENTORY] Mapped GUID {name} -> {friendly}")
                            name = friendly
                        else:
                            logger.debug(f"[INVENTORY] Unknown GUID app: {name}")
                            name = f"System App ({name[:8]}...)"

                    version = app_data.get('DisplayVersion') or app_data.get('Version') or 'Unknown'
                    publisher = app_data.get('Publisher') or 'Unknown'

                    publisher_upper = publisher.upper() if publisher else ''
                    if publisher_upper in GUID_TO_PUBLISHER:
                        publisher = GUID_TO_PUBLISHER[publisher_upper]
                        logger.debug(f"[INVENTORY] Mapped publisher GUID to {publisher}")

                    install_location = app_data.get('InstallLocation')
                    install_date = app_data.get('InstallDate')
                    source = app_data.get('Source')
                    architecture = app_data.get('Architecture')
                    uninstall_command = app_data.get('UninstallCommand')
                    estimated_size_kb = app_data.get('EstimatedSizeKB')

                    app = Application(
                        name=name,
                        version=version,
                        publisher=publisher,
                        install_location=install_location,
                        install_date=install_date,
                        source=source,
                        architecture=architecture,
                        uninstall_command=uninstall_command,
                        estimated_size_kb=estimated_size_kb
                    )
                    if app.name:
                        if not install_location:
                            logger.debug(f"[INVENTORY] {name}: No install location")
                        if not install_date:
                            logger.debug(f"[INVENTORY] {name}: No install date")
                        apps.append(app)
                except Exception:
                    continue

            self._consecutive_timeouts = 0
            self._timeout_cooldown_until = 0.0
            return apps

        except subprocess.TimeoutExpired:
            self._kill_process_tree(process)

            self._consecutive_timeouts += 1
            logger.error("[INVENTORY] PowerShell timeout (120s)")
            logger.error(f"[INVENTORY] [HEALTH] Timeout streak: {self._consecutive_timeouts}/{self._max_consecutive_timeouts}")
            if self._consecutive_timeouts >= self._max_consecutive_timeouts:
                self._timeout_cooldown_until = time.time() + self._timeout_cooldown_seconds
                logger.error(f"[INVENTORY] [HEALTH] Circuit breaker OPEN for {self._timeout_cooldown_seconds}s")
                self._consecutive_timeouts = 0
            return None
        except Exception as e:
            logger.error(f"[INVENTORY] Collection error: {e}")
            self._kill_process_tree(process)
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
        
        # Validate other fields (FIXED: Added install_date, source, arch, etc.)
        for field in ['version', 'publisher', 'install_location', 'install_date', 'source', 'architecture', 'uninstall_command', 'estimated_size_kb']:
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
            install_location=validated_data.get('install_location'),
            source=validated_data.get('source'),
            install_date=validated_data.get('install_date'),
            architecture=validated_data.get('architecture'),
            uninstall_command=validated_data.get('uninstall_command'),
            estimated_size_kb=validated_data.get('estimated_size_kb')
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
