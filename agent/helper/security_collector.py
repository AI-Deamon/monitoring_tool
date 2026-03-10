"""
Security Collector Module — Phase 1 + 2 + 3
=============================================
Produces security risk indicators via analysis and PowerShell collection:

Phase 1 (analysis of existing data):
- Unsigned drivers (kernel-level compromise risk)
- Suspicious browser extensions (data exfiltration, credential theft)
- System file change detection (hosts hijack, sticky keys backdoor)

Phase 2 (PowerShell collection):
- Startup programs (persistence via autorun)
- Scheduled tasks (persistence via task scheduler)
- Open ports (network exposure)

Phase 3 (PowerShell collection):
- Active network connections (suspicious outbound traffic)
- USB device history (removable media audit)
- Login history (brute force, RDP sessions)

Architecture:
    SecurityCollector consumes data from ExtendedInventoryCollector/EOLCollector
    and produces risk assessments sent via /security-indicators pipeline.
"""

import hashlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# RISK SCORING CONSTANTS
# =============================================================================

# Extension risk factors
RISK_UNKNOWN_PUBLISHER = 30
RISK_DISABLED_BY_USER = 10
RISK_EXCESSIVE_COUNT = 5       # Per extension above threshold
RISK_RISKY_NAME_PATTERN = 25
RISK_NO_VERSION = 10

EXTENSION_COUNT_THRESHOLD = 15  # Extensions per browser before risk increases

# Risky extension name patterns (case-insensitive substrings)
RISKY_NAME_PATTERNS = [
    'free vpn', 'vpn free', 'pdf converter', 'pdf download',
    'video downloader', 'mp3 download', 'coupon', 'cashback',
    'screen capture', 'web scraper', 'auto clicker',
    'coin miner', 'crypto', 'wallet', 'toolbar',
    'search bar', 'new tab', 'homepage', 'start page',
]

# Driver risk classification by device class
DRIVER_RISK_CLASSES = {
    'System':       'critical',   # Kernel-level access
    'Display':      'high',       # GPU driver with kernel component
    'Net':          'high',       # Network stack access
    'SCSIAdapter':  'high',       # Storage controller
    'HIDClass':     'medium',     # Input devices
    'USB':          'medium',     # USB controller
    'Media':        'low',        # Audio/video
    'Printer':      'low',        # Printer drivers
    'Image':        'low',        # Scanner/camera
}

# System files to monitor for tampering
SYSTEM_FILES = {
    'hosts': {
        'path': r'C:\Windows\System32\drivers\etc\hosts',
        'type': 'text',
        'severity': 'high',
        'reason': 'DNS hijacking — redirect domains to malicious IPs',
    },
    'sethc': {
        'path': r'C:\Windows\System32\sethc.exe',
        'type': 'binary',
        'severity': 'critical',
        'reason': 'Sticky keys backdoor — replaced with cmd.exe for login bypass',
    },
    'utilman': {
        'path': r'C:\Windows\System32\utilman.exe',
        'type': 'binary',
        'severity': 'critical',
        'reason': 'Utility Manager backdoor — replaced with cmd.exe for login bypass',
    },
    'osk': {
        'path': r'C:\Windows\System32\osk.exe',
        'type': 'binary',
        'severity': 'high',
        'reason': 'On-Screen Keyboard backdoor — replaced for accessibility bypass',
    },
}

# Phase 2 — Risky executable paths (startup programs & scheduled tasks)
RISKY_EXE_PATHS = [
    '\\temp\\', '\\tmp\\', '\\downloads\\',
    '\\appdata\\local\\temp\\', '\\appdata\\roaming\\',
    '\\users\\public\\', '\\programdata\\',
]

# Phase 2 — Dangerous listening ports
DANGEROUS_PORTS = {
    21:   ('FTP',        'high'),
    23:   ('Telnet',     'critical'),
    445:  ('SMB',        'high'),
    1433: ('MSSQL',      'high'),
    1434: ('MSSQL-UDP',  'high'),
    3306: ('MySQL',      'high'),
    3389: ('RDP',        'high'),
    5432: ('PostgreSQL',  'medium'),
    5900: ('VNC',        'high'),
    5985: ('WinRM-HTTP', 'medium'),
    5986: ('WinRM-HTTPS','medium'),
    6379: ('Redis',      'high'),
    27017:('MongoDB',    'high'),
}

# Microsoft scheduled task path prefixes to skip
MS_TASK_PREFIXES = (
    '\\Microsoft\\', '\\Mozilla\\', '\\Google\\',
    '\\Adobe\\', '\\Apple\\',
)

# Phase 3 — Suspicious outbound ports (C2, IRC, proxy, common malware)
SUSPICIOUS_OUTBOUND_PORTS = {
    4444, 5555, 6666, 6667, 6668, 6669,  # Metasploit default, IRC
    8443, 8888, 9999,                     # Common C2 callback
    1080, 3128,                           # SOCKS/HTTP proxy
}

# Phase 3 — Known safe processes to exclude from connection analysis
SAFE_PROCESSES = {
    'svchost', 'system', 'lsass', 'services', 'wininit', 'csrss',
    'chrome', 'msedge', 'firefox', 'opera', 'brave',
    'code', 'teams', 'outlook', 'onedrive', 'searchhost',
    'microsoftedgeupdate', 'googleupdate', 'spotify',
}


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class SecurityIndicator:
    """A single security risk indicator."""
    indicator_type: str           # 'unsigned_driver', 'suspicious_extension', 'file_change'
    severity: str                 # 'critical', 'high', 'medium', 'low'
    title: str                    # Human-readable summary
    risk_score: int               # 0-100
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict:
        return asdict(self)


# =============================================================================
# SECURITY COLLECTOR
# =============================================================================

class SecurityCollector:
    """
    Phase 1+2+3 security risk analyzer.
    
    Phase 1: Analyzes existing collected data (drivers, extensions, files).
    Phase 2: Collects new data via PowerShell (startup, tasks, ports).
    Phase 3: Collects network connections, USB history, login events.
    
    Produces SecurityIndicator objects sent via /security-indicators pipeline.
    """
    
    def __init__(self, config=None):
        self.config = config
        self.enable_disk_usage_indicator = getattr(config, 'enable_disk_usage_indicator', True) if config else True
        self._baselines: Dict[str, str] = {}   # file_name -> sha256 hash
        self._baseline_path = self._get_baseline_path()
        self._load_baselines()
    
    def _get_baseline_path(self) -> Path:
        """Get path for storing file baselines."""
        if self.config and hasattr(self.config, 'data_dir'):
            base = Path(self.config.data_dir)
        else:
            base = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'WinDiagSvc'
        
        baseline_dir = base / 'security'
        baseline_dir.mkdir(parents=True, exist_ok=True)
        return baseline_dir / 'file_baselines.json'
    
    def _load_baselines(self):
        """Load stored file baselines from disk."""
        try:
            if self._baseline_path.exists():
                with open(self._baseline_path, 'r') as f:
                    self._baselines = json.load(f)
                logger.debug(f"[SECURITY] Loaded {len(self._baselines)} file baselines")
        except Exception as e:
            logger.warning(f"[SECURITY] Failed to load baselines: {e}")
            self._baselines = {}
    
    def _save_baselines(self):
        """Persist file baselines to disk."""
        try:
            with open(self._baseline_path, 'w') as f:
                json.dump(self._baselines, f, indent=2)
        except Exception as e:
            logger.warning(f"[SECURITY] Failed to save baselines: {e}")
    
    def _calculate_file_hash(self, filepath: str) -> Optional[str]:
        """Calculate SHA256 hash of a file."""
        try:
            sha256 = hashlib.sha256()
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except PermissionError:
            logger.debug(f"[SECURITY] Permission denied reading: {filepath}")
            return None
        except Exception as e:
            logger.debug(f"[SECURITY] Hash error for {filepath}: {e}")
            return None

    # =========================================================================
    # P1-A: Unsigned Driver Analysis
    # =========================================================================

    def analyze_unsigned_drivers(self, drivers: List[Dict]) -> List[SecurityIndicator]:
        """
        Analyze driver signing status from existing collected data.
        
        Args:
            drivers: List of driver dicts from ExtendedInventoryCollector
            
        Returns:
            SecurityIndicator for each unsigned driver
        """
        indicators = []
        
        if not drivers:
            return indicators
        
        # DEBUG LOG - MAY BE REMOVED
        logger.info(f"[SECURITY] START Driver analysis for {len(drivers)} drivers")
        
        unsigned_count = 0
        
        for drv in drivers:
            is_signed = drv.get('is_signed', True)
            
            if is_signed:
                continue
            
            unsigned_count += 1
            device_class = drv.get('device_class', 'Unknown')
            device_name = drv.get('device_name', 'Unknown device')
            driver_name = drv.get('driver_name', '')
            manufacturer = drv.get('manufacturer', 'Unknown')
            
            # Classify risk by device class
            severity = DRIVER_RISK_CLASSES.get(device_class, 'medium')
            
            # Calculate risk score
            risk_score = 40  # Base score for any unsigned driver
            if severity == 'critical':
                risk_score = 85
            elif severity == 'high':
                risk_score = 70
            elif severity == 'medium':
                risk_score = 50
            
            indicator = SecurityIndicator(
                indicator_type='unsigned_driver',
                severity=severity,
                title=f"Unsigned {device_class} driver: {device_name}",
                risk_score=risk_score,
                details={
                    'device_name': device_name,
                    'driver_name': driver_name,
                    'device_class': device_class,
                    'manufacturer': manufacturer,
                    'driver_version': drv.get('driver_version', ''),
                    'device_id': drv.get('device_id', ''),
                },
            )
            indicators.append(indicator)
        
        logger.info(
            f"[SECURITY] Driver analysis: {unsigned_count} unsigned "
            f"out of {len(drivers)} total drivers"
        )
        
        return indicators

    # =========================================================================
    # P1-B: Browser Extension Risk Analysis
    # =========================================================================

    def analyze_extension_risks(self, extensions: List[Dict]) -> List[SecurityIndicator]:
        """
        Score browser extensions for security risk.
        
        Risk factors:
          - Unknown/empty publisher (+30)
          - Matches risky name patterns (+25)
          - No version info (+10)
          - Browser has excessive extensions (+5 each above threshold)
        
        Only reports extensions with risk_score >= 30.
        """
        indicators = []
        
        if not extensions:
            return indicators
        
        # DEBUG LOG - MAY BE REMOVED
        logger.info(f"[SECURITY] START Extension analysis for {len(extensions)} extensions")
        
        # Count extensions per browser for excessive-count penalty
        browser_counts: Dict[str, int] = {}
        for ext in extensions:
            browser = ext.get('browser', 'Unknown')
            browser_counts[browser] = browser_counts.get(browser, 0) + 1
        
        high_risk_count = 0
        
        for ext in extensions:
            risk_score = 0
            risk_factors = []
            
            name = ext.get('name', 'Unknown')
            browser = ext.get('browser', 'Unknown')
            version = ext.get('version', '')
            ext_id = ext.get('extension_id', '')
            
            # Factor 1: Unknown publisher / no name
            if name in ('Unknown', '', None):
                risk_score += RISK_UNKNOWN_PUBLISHER
                risk_factors.append('unknown_name')
            
            # Factor 2: Risky name patterns
            name_lower = (name or '').lower()
            for pattern in RISKY_NAME_PATTERNS:
                if pattern in name_lower:
                    risk_score += RISK_RISKY_NAME_PATTERN
                    risk_factors.append(f'risky_pattern:{pattern}')
                    break  # Only count once
            
            # Factor 3: No version
            if not version or version in ('Unknown', '0.0.0'):
                risk_score += RISK_NO_VERSION
                risk_factors.append('no_version')
            
            # Factor 4: Excessive extensions per browser
            count = browser_counts.get(browser, 0)
            if count > EXTENSION_COUNT_THRESHOLD:
                excess = count - EXTENSION_COUNT_THRESHOLD
                penalty = excess * RISK_EXCESSIVE_COUNT
                risk_score += penalty
                risk_factors.append(f'excessive_count:{count}')
            
            # Only report if risk score meets threshold
            if risk_score >= 30:
                high_risk_count += 1
                
                # Map score to severity
                if risk_score >= 70:
                    severity = 'high'
                elif risk_score >= 50:
                    severity = 'medium'
                else:
                    severity = 'low'
                
                indicator = SecurityIndicator(
                    indicator_type='suspicious_extension',
                    severity=severity,
                    title=f"Suspicious {browser} extension: {name}",
                    risk_score=min(risk_score, 100),
                    details={
                        'browser': browser,
                        'extension_id': ext_id,
                        'name': name,
                        'version': version,
                        'enabled': ext.get('enabled', True),
                        'profile': ext.get('profile', ''),
                        'risk_factors': risk_factors,
                    },
                )
                indicators.append(indicator)
        
        logger.info(
            f"[SECURITY] Extension analysis: {high_risk_count} suspicious "
            f"out of {len(extensions)} total extensions "
            f"(browsers: {browser_counts})"
        )
        
        return indicators

    # =========================================================================
    # P1-C: System File Change Detection
    # =========================================================================

    def check_system_files(self) -> List[SecurityIndicator]:
        """
        Detect changes in security-critical system files using SHA256 baselines.
        
        First run: creates baselines (no alerts).
        Subsequent runs: reports any hash changes.
        """
        indicators = []
        baselines_changed = False
        
        # DEBUG LOG - MAY BE REMOVED
        logger.info("[SECURITY] START System file change check")
        
        for file_name, file_info in SYSTEM_FILES.items():
            filepath = file_info['path']
            
            if not os.path.exists(filepath):
                logger.debug(f"[SECURITY] File not found: {filepath}")
                continue
            
            current_hash = self._calculate_file_hash(filepath)
            if current_hash is None:
                continue
            
            stored_hash = self._baselines.get(file_name)
            
            if stored_hash is None:
                # First run — store baseline
                self._baselines[file_name] = current_hash
                baselines_changed = True
                logger.info(f"[SECURITY] Baseline created for {file_name}: {current_hash[:16]}...")
                
            elif stored_hash != current_hash:
                # Change detected
                try:
                    mtime = os.path.getmtime(filepath)
                    last_modified = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                except Exception:
                    last_modified = None
                
                details = {
                    'file': file_name,
                    'path': filepath,
                    'old_hash': stored_hash,
                    'new_hash': current_hash,
                    'last_modified': last_modified,
                    'reason': file_info['reason'],
                }
                
                # For text files (hosts), include content diff
                if file_info['type'] == 'text':
                    try:
                        with open(filepath, 'r', errors='ignore') as f:
                            content = f.read(4096)  # Cap at 4KB
                        details['content_preview'] = content
                    except Exception:
                        pass
                
                indicator = SecurityIndicator(
                    indicator_type='file_change',
                    severity=file_info['severity'],
                    title=f"System file modified: {file_name}",
                    risk_score=90 if file_info['severity'] == 'critical' else 75,
                    details=details,
                )
                indicators.append(indicator)
                
                # Update baseline to new hash
                self._baselines[file_name] = current_hash
                baselines_changed = True
                
                logger.warning(
                    f"[SECURITY] FILE CHANGE DETECTED: {file_name} "
                    f"({stored_hash[:16]}... -> {current_hash[:16]}...)"
                )
        
        if baselines_changed:
            self._save_baselines()
        
        if not indicators:
            logger.debug("[SECURITY] No system file changes detected")
        
        return indicators

    # =========================================================================
    # POWERSHELL HELPER
    # =========================================================================

    def _run_powershell(self, script: str, timeout: int = 60) -> Optional[str]:
        """Run a PowerShell command and return stdout."""
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                 "-Command", script],
                capture_output=True,
                text=True,
                timeout=timeout,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.debug(f"[SECURITY] PowerShell error: {result.stderr[:200]}")
                return None

        except subprocess.TimeoutExpired:
            logger.warning(f"[SECURITY] PowerShell timeout ({timeout}s)")
            return None
        except Exception as e:
            logger.error(f"[SECURITY] PowerShell error: {e}")
            return None

    @staticmethod
    def _is_risky_path(exe_path: str) -> bool:
        """Check if an executable path matches common malware locations."""
        if not exe_path:
            return False
        path_lower = exe_path.lower()
        return any(rp in path_lower for rp in RISKY_EXE_PATHS)

    # =========================================================================
    # P2-A: Startup Programs (Persistence Detection)
    # =========================================================================

    def collect_startup_programs(self) -> List[SecurityIndicator]:
        """
        Collect autorun entries from Registry Run keys, Startup folder, and WMI.
        Flags entries in suspicious paths or with unknown publishers.
        """
        # DEBUG LOG - MAY BE REMOVED
        logger.info("[SECURITY] START Startup programs collection")
        
        indicators = []

        ps_script = r'''
$results = @()

# Registry HKLM Run
try {
    $hklm = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue
    if ($hklm) {
        $hklm.PSObject.Properties | Where-Object { $_.Name -notin @('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider') } | ForEach-Object {
            $results += [PSCustomObject]@{ Name=$_.Name; Command=$_.Value; Source='HKLM_Run' }
        }
    }
} catch {}

# Registry HKCU Run
try {
    $hkcu = Get-ItemProperty -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue
    if ($hkcu) {
        $hkcu.PSObject.Properties | Where-Object { $_.Name -notin @('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider') } | ForEach-Object {
            $results += [PSCustomObject]@{ Name=$_.Name; Command=$_.Value; Source='HKCU_Run' }
        }
    }
} catch {}

# Startup folder
try {
    $startupPath = [Environment]::GetFolderPath('Startup')
    if (Test-Path $startupPath) {
        Get-ChildItem -Path $startupPath -File -ErrorAction SilentlyContinue | ForEach-Object {
            $results += [PSCustomObject]@{ Name=$_.BaseName; Command=$_.FullName; Source='StartupFolder' }
        }
    }
} catch {}

# WMI Startup commands
try {
    Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue | ForEach-Object {
        $results += [PSCustomObject]@{ Name=$_.Name; Command=$_.Command; Source='WMI'; User=$_.User; Location=$_.Location }
    }
} catch {}

$results | ConvertTo-Json -Compress -Depth 3
'''

        output = self._run_powershell(ps_script, timeout=30)
        if not output:
            logger.debug("[SECURITY] No startup program data returned")
            return indicators

        try:
            entries = json.loads(output)
            if isinstance(entries, dict):
                entries = [entries]  # Single result comes as dict
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse startup program JSON")
            return indicators

        # De-duplicate by (name, command)
        seen = set()
        suspicious_count = 0

        for entry in entries:
            name = entry.get('Name', 'Unknown')
            command = entry.get('Command', '')
            source = entry.get('Source', '')
            dedup_key = (name.lower(), command.lower())

            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Score risk
            risk_score = 0
            risk_factors = []

            if self._is_risky_path(command):
                risk_score += 60
                risk_factors.append('risky_path')

            # Encoded commands or script blocks
            cmd_lower = command.lower()
            if '-encodedcommand' in cmd_lower or '-enc ' in cmd_lower:
                risk_score += 70
                risk_factors.append('encoded_command')
            elif 'powershell' in cmd_lower and ('-c ' in cmd_lower or '-command' in cmd_lower):
                risk_score += 40
                risk_factors.append('inline_powershell')
            elif cmd_lower.endswith('.vbs') or cmd_lower.endswith('.bat') or cmd_lower.endswith('.js'):
                risk_score += 30
                risk_factors.append('script_extension')

            if risk_score < 30:
                continue  # Not suspicious enough to report

            suspicious_count += 1

            if risk_score >= 70:
                severity = 'high'
            elif risk_score >= 50:
                severity = 'medium'
            else:
                severity = 'low'

            indicators.append(SecurityIndicator(
                indicator_type='startup_program',
                severity=severity,
                title=f"Suspicious startup: {name}",
                risk_score=min(risk_score, 100),
                details={
                    'name': name,
                    'command': command[:500],
                    'source': source,
                    'user': entry.get('User', ''),
                    'location': entry.get('Location', ''),
                    'risk_factors': risk_factors,
                },
            ))

        logger.info(
            f"[SECURITY] Startup analysis: {suspicious_count} suspicious "
            f"out of {len(seen)} total entries"
        )
        return indicators

    # =========================================================================
    # P2-B: Scheduled Tasks (Persistence Detection)
    # =========================================================================

    def collect_scheduled_tasks(self) -> List[SecurityIndicator]:
        """
        Collect non-Microsoft scheduled tasks and flag risky ones.
        Filters out standard OS/vendor tasks by path prefix.
        """
        # DEBUG LOG - MAY BE REMOVED
        logger.info("[SECURITY] START Scheduled tasks collection")
        
        indicators = []

        ps_script = r'''
$results = @()
try {
    Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' } | ForEach-Object {
        $task = $_
        $actions = @()
        foreach ($action in $task.Actions) {
            if ($action.Execute) {
                $actions += [PSCustomObject]@{
                    Execute  = $action.Execute
                    Arguments = $action.Arguments
                }
            }
        }
        if ($actions.Count -gt 0) {
            $triggers = @()
            foreach ($trigger in $task.Triggers) {
                $triggers += $trigger.CimClass.CimClassName
            }
            $results += [PSCustomObject]@{
                TaskPath = $task.TaskPath
                TaskName = $task.TaskName
                State    = $task.State.ToString()
                Actions  = $actions
                Triggers = ($triggers -join ',')
                Principal = $task.Principal.UserId
            }
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 4
'''

        output = self._run_powershell(ps_script, timeout=45)
        if not output:
            logger.debug("[SECURITY] No scheduled task data returned")
            return indicators

        try:
            tasks = json.loads(output)
            if isinstance(tasks, dict):
                tasks = [tasks]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse scheduled task JSON")
            return indicators

        suspicious_count = 0

        for task in tasks:
            task_path = task.get('TaskPath', '')
            task_name = task.get('TaskName', 'Unknown')
            principal = task.get('Principal', '') or ''

            # Skip known vendor tasks
            if any(task_path.startswith(prefix) for prefix in MS_TASK_PREFIXES):
                continue

            actions = task.get('Actions', [])
            if isinstance(actions, dict):
                actions = [actions]

            for action in actions:
                exe = action.get('Execute', '')
                args = action.get('Arguments', '') or ''
                full_cmd = f"{exe} {args}".strip()

                risk_score = 0
                risk_factors = []

                # Risky executable path
                if self._is_risky_path(exe):
                    risk_score += 60
                    risk_factors.append('risky_exe_path')

                # Encoded PowerShell
                cmd_lower = full_cmd.lower()
                if '-encodedcommand' in cmd_lower or '-enc ' in cmd_lower:
                    risk_score += 70
                    risk_factors.append('encoded_command')
                elif 'powershell' in cmd_lower and ('-c ' in cmd_lower or '-command' in cmd_lower):
                    risk_score += 35
                    risk_factors.append('inline_powershell')

                # SYSTEM principal on non-standard path
                if 'system' in principal.lower() and not exe.lower().startswith('c:\\windows\\'):
                    risk_score += 25
                    risk_factors.append('system_non_standard')

                if risk_score < 30:
                    continue

                suspicious_count += 1

                if risk_score >= 70:
                    severity = 'high'
                elif risk_score >= 50:
                    severity = 'medium'
                else:
                    severity = 'low'

                indicators.append(SecurityIndicator(
                    indicator_type='scheduled_task',
                    severity=severity,
                    title=f"Suspicious task: {task_name}",
                    risk_score=min(risk_score, 100),
                    details={
                        'task_name': task_name,
                        'task_path': task_path,
                        'execute': exe[:300],
                        'arguments': args[:300],
                        'principal': principal,
                        'state': task.get('State', ''),
                        'triggers': task.get('Triggers', ''),
                        'risk_factors': risk_factors,
                    },
                ))

        logger.info(
            f"[SECURITY] Task analysis: {suspicious_count} suspicious "
            f"out of {len(tasks)} total tasks"
        )
        return indicators

    # =========================================================================
    # P2-C: Open Ports (Network Exposure)
    # =========================================================================

    def collect_open_ports(self) -> List[SecurityIndicator]:
        """
        Collect listening TCP ports and cross-reference with owning process.
        Flags dangerous ports and unknown listeners.
        """
        # DEBUG LOG - MAY BE REMOVED
        logger.info("[SECURITY] START Open ports collection")
        
        indicators = []

        ps_script = r'''
$results = @()
try {
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        $proc = $null
        try { $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } catch {}
        $pName = 'Unknown'; $pPath = ''
        if ($proc) { $pName = $proc.ProcessName; $pPath = $proc.Path }
        $results += [PSCustomObject]@{
            LocalPort    = $_.LocalPort
            LocalAddress = $_.LocalAddress
            ProcessId    = $_.OwningProcess
            ProcessName  = $pName
            ProcessPath  = $pPath
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 3
'''

        output = self._run_powershell(ps_script, timeout=30)
        if not output:
            logger.debug("[SECURITY] No open port data returned")
            return indicators

        try:
            ports = json.loads(output)
            if isinstance(ports, dict):
                ports = [ports]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse open port JSON")
            return indicators

        # De-duplicate by port (keep first entry per port)
        seen_ports = set()
        flagged_count = 0

        for entry in ports:
            port = entry.get('LocalPort', 0)
            addr = entry.get('LocalAddress', '')
            proc_name = entry.get('ProcessName', 'Unknown')
            proc_path = entry.get('ProcessPath', '')
            pid = entry.get('ProcessId', 0)

            if port in seen_ports:
                continue
            seen_ports.add(port)

            # Skip localhost-only listeners (generally safe)
            if addr in ('127.0.0.1', '::1') and port not in DANGEROUS_PORTS:
                continue

            risk_score = 0
            risk_factors = []

            # Check against known dangerous ports
            if port in DANGEROUS_PORTS:
                service_name, port_severity = DANGEROUS_PORTS[port]
                risk_score += 60 if port_severity in ('high', 'critical') else 40
                risk_factors.append(f'dangerous_port:{service_name}')

                # Listening on all interfaces is worse
                if addr in ('0.0.0.0', '::'):
                    risk_score += 20
                    risk_factors.append('all_interfaces')

            # Unknown process on high port
            elif port > 1024 and proc_name in ('Unknown', 'System'):
                risk_score += 35
                risk_factors.append('unknown_process')

            # Risky process path
            if self._is_risky_path(proc_path):
                risk_score += 30
                risk_factors.append('risky_process_path')

            if risk_score < 30:
                continue

            flagged_count += 1

            if risk_score >= 70:
                severity = 'high'
            elif risk_score >= 50:
                severity = 'medium'
            else:
                severity = 'low'

            indicators.append(SecurityIndicator(
                indicator_type='open_port',
                severity=severity,
                title=f"Port {port} ({proc_name}) listening on {addr}",
                risk_score=min(risk_score, 100),
                details={
                    'port': port,
                    'address': addr,
                    'process_name': proc_name,
                    'process_path': proc_path[:300],
                    'pid': pid,
                    'risk_factors': risk_factors,
                },
            ))

        logger.info(
            f"[SECURITY] Port analysis: {flagged_count} flagged "
            f"out of {len(seen_ports)} listening ports"
        )
        return indicators

    # =========================================================================
    # P3-A: Active Network Connections (Suspicious Outbound)
    # =========================================================================

    def collect_active_connections(self) -> List[SecurityIndicator]:
        """
        Collect established outbound TCP connections and flag suspicious ones.
        Filters out known safe processes and localhost traffic.
        """
        # DEBUG LOG - MAY BE REMOVED
        logger.info("[SECURITY] START Active connections collection")
        
        indicators = []

        ps_script = r'''
$results = @()
try {
    Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | ForEach-Object {
        $proc = $null
        try { $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } catch {}
        $pName = 'Unknown'; $pPath = ''
        if ($proc) { $pName = $proc.ProcessName; $pPath = $proc.Path }
        $results += [PSCustomObject]@{
            RemotePort    = $_.RemotePort
            RemoteAddress = $_.RemoteAddress
            LocalPort     = $_.LocalPort
            LocalAddress  = $_.LocalAddress
            ProcessId     = $_.OwningProcess
            ProcessName   = $pName
            ProcessPath   = $pPath
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 3
'''

        output = self._run_powershell(ps_script, timeout=30)
        if not output:
            logger.debug("[SECURITY] No active connection data returned")
            return indicators

        try:
            conns = json.loads(output)
            if isinstance(conns, dict):
                conns = [conns]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse connection JSON")
            return indicators

        # Count connections per process for volume detection
        proc_conn_counts: Dict[str, int] = {}
        for c in conns:
            pname = (c.get('ProcessName') or 'Unknown').lower()
            proc_conn_counts[pname] = proc_conn_counts.get(pname, 0) + 1

        seen = set()  # (remote_addr, remote_port, process_name)
        flagged = 0

        for entry in conns:
            proc_name = entry.get('ProcessName', 'Unknown')
            proc_path = entry.get('ProcessPath', '')
            remote_addr = entry.get('RemoteAddress', '')
            remote_port = entry.get('RemotePort', 0)
            pid = entry.get('ProcessId', 0)

            # Skip safe processes
            if proc_name.lower() in SAFE_PROCESSES:
                continue

            # Skip localhost/link-local
            if remote_addr in ('127.0.0.1', '::1', '0.0.0.0') or remote_addr.startswith('fe80'):
                continue

            dedup_key = (remote_addr, remote_port, proc_name.lower())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            risk_score = 0
            risk_factors = []

            # Suspicious outbound port
            if remote_port in SUSPICIOUS_OUTBOUND_PORTS:
                risk_score += 65
                risk_factors.append(f'suspicious_port:{remote_port}')

            # Risky process path
            if self._is_risky_path(proc_path):
                risk_score += 50
                risk_factors.append('risky_process_path')

            # High connection volume from single process
            conn_count = proc_conn_counts.get(proc_name.lower(), 0)
            if conn_count > 20:
                risk_score += 25
                risk_factors.append(f'high_volume:{conn_count}')

            # Unknown process connecting outbound
            if proc_name == 'Unknown':
                risk_score += 40
                risk_factors.append('unknown_process')

            if risk_score < 30:
                continue

            flagged += 1
            if risk_score >= 70:
                severity = 'high'
            elif risk_score >= 50:
                severity = 'medium'
            else:
                severity = 'low'

            indicators.append(SecurityIndicator(
                indicator_type='network_connection',
                severity=severity,
                title=f"{proc_name} -> {remote_addr}:{remote_port}",
                risk_score=min(risk_score, 100),
                details={
                    'process_name': proc_name,
                    'process_path': proc_path[:300],
                    'pid': pid,
                    'remote_address': remote_addr,
                    'remote_port': remote_port,
                    'local_port': entry.get('LocalPort', 0),
                    'total_connections': conn_count,
                    'risk_factors': risk_factors,
                },
            ))

        logger.info(
            f"[SECURITY] Connection analysis: {flagged} suspicious "
            f"out of {len(seen)} unique connections ({len(conns)} total)"
        )
        return indicators

    # =========================================================================
    # P3-B: USB Device History (Removable Media Audit)
    # =========================================================================

    def collect_usb_history(self) -> List[SecurityIndicator]:
        """
        Collect USB storage device history from the registry.
        Flags recent device connections and high device counts.
        """
        # DEBUG LOG - MAY BE REMOVED
        logger.info("[SECURITY] START USB history collection")
        
        indicators = []

        ps_script = r'''
$results = @()
try {
    $usbstorPath = 'HKLM:\SYSTEM\CurrentControlSet\Enum\USBSTOR'
    if (Test-Path $usbstorPath) {
        Get-ChildItem -Path $usbstorPath -ErrorAction SilentlyContinue | ForEach-Object {
            $deviceClass = $_.PSChildName
            Get-ChildItem -Path $_.PSPath -ErrorAction SilentlyContinue | ForEach-Object {
                $serial = $_.PSChildName
                $props = Get-ItemProperty -Path $_.PSPath -ErrorAction SilentlyContinue
                $friendlyName = ''
                if ($props.FriendlyName) { $friendlyName = $props.FriendlyName }
                $lastWrite = $_.GetValue('LastWrite')
                $mfg = ''; if ($props.Mfg) { $mfg = $props.Mfg }
                $results += [PSCustomObject]@{
                    DeviceClass  = $deviceClass
                    SerialNumber = $serial
                    FriendlyName = $friendlyName
                    Manufacturer = $mfg
                }
            }
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 3
'''

        output = self._run_powershell(ps_script, timeout=30)
        if not output:
            logger.debug("[SECURITY] No USB history data returned")
            return indicators

        try:
            devices = json.loads(output)
            if isinstance(devices, dict):
                devices = [devices]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse USB history JSON")
            return indicators

        device_count = len(devices)

        for dev in devices:
            device_class = dev.get('DeviceClass', 'Unknown')
            serial = dev.get('SerialNumber', '')
            friendly = dev.get('FriendlyName', '') or device_class
            manufacturer = dev.get('Manufacturer', '')

            risk_score = 0
            risk_factors = []

            # No friendly name / unknown vendor
            if not dev.get('FriendlyName'):
                risk_score += 15
                risk_factors.append('no_friendly_name')

            # Many unique USB storage devices = data exfiltration risk
            if device_count > 5:
                risk_score += 20
                risk_factors.append(f'high_device_count:{device_count}')

            # All USB storage devices get a base score (removable media policy)
            risk_score += 10
            risk_factors.append('removable_storage')

            if risk_score < 30:
                continue

            if risk_score >= 50:
                severity = 'medium'
            else:
                severity = 'low'

            indicators.append(SecurityIndicator(
                indicator_type='usb_device',
                severity=severity,
                title=f"USB storage: {friendly}",
                risk_score=min(risk_score, 100),
                details={
                    'device_class': device_class,
                    'serial_number': serial,
                    'friendly_name': friendly,
                    'manufacturer': manufacturer,
                    'total_usb_devices': device_count,
                    'risk_factors': risk_factors,
                },
            ))

        logger.info(
            f"[SECURITY] USB analysis: {len(indicators)} flagged "
            f"out of {device_count} USB storage devices"
        )
        return indicators

    # =========================================================================
    # P3-C: Login History (Brute Force & RDP Detection)
    # =========================================================================

    def collect_login_history(self) -> List[SecurityIndicator]:
        """
        Analyze Windows Security event log for failed logins and RDP sessions.
        Requires SYSTEM privileges (Helper runs as SYSTEM).
        """
        # DEBUG LOG - MAY BE REMOVED
        logger.info("[SECURITY] START Login history analysis")
        
        indicators = []

        ps_script = r'''
$result = @{ FailedLogins = @(); RDPLogins = @(); FailedCount = 0 }
try {
    # Failed logins (Event 4625) in last 24 hours
    $cutoff = (Get-Date).AddHours(-24)
    $failed = Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4625; StartTime=$cutoff} -MaxEvents 100 -ErrorAction SilentlyContinue
    if ($failed) {
        $result.FailedCount = $failed.Count
        # Group by target account
        $grouped = $failed | Group-Object { $_.Properties[5].Value } | Sort-Object Count -Descending | Select-Object -First 10
        foreach ($g in $grouped) {
            $sample = $g.Group[0]
            $result.FailedLogins += [PSCustomObject]@{
                Account    = $g.Name
                Count      = $g.Count
                LastTime   = $sample.TimeCreated.ToString('o')
                SourceIP   = $sample.Properties[19].Value
                LogonType  = $sample.Properties[10].Value
            }
        }
    }
} catch {}
try {
    # RDP logins (Event 4624, LogonType 10) in last 7 days
    $rdpCutoff = (Get-Date).AddDays(-7)
    $rdp = Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4624; StartTime=$rdpCutoff} -MaxEvents 200 -ErrorAction SilentlyContinue
    if ($rdp) {
        $rdpEvents = $rdp | Where-Object { $_.Properties[8].Value -eq 10 }
        foreach ($evt in ($rdpEvents | Select-Object -First 20)) {
            $result.RDPLogins += [PSCustomObject]@{
                Account   = $evt.Properties[5].Value
                Domain    = $evt.Properties[6].Value
                SourceIP  = $evt.Properties[18].Value
                Time      = $evt.TimeCreated.ToString('o')
            }
        }
    }
} catch {}
$result | ConvertTo-Json -Compress -Depth 4
'''

        output = self._run_powershell(ps_script, timeout=45)
        if not output:
            logger.debug("[SECURITY] No login history data returned")
            return indicators

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse login history JSON")
            return indicators

        # --- Analyze failed logins ---
        failed_total = data.get('FailedCount', 0)
        failed_entries = data.get('FailedLogins', [])
        if isinstance(failed_entries, dict):
            failed_entries = [failed_entries]

        if failed_total > 0:
            risk_score = 0
            risk_factors = []

            if failed_total >= 10:
                risk_score = 85
                severity = 'critical'
                risk_factors.append('brute_force_likely')
            elif failed_total >= 5:
                risk_score = 65
                severity = 'high'
                risk_factors.append('multiple_failures')
            elif failed_total >= 3:
                risk_score = 45
                severity = 'medium'
                risk_factors.append('repeated_failures')
            else:
                risk_score = 25
                severity = 'low'
                risk_factors.append('minor_failures')

            if risk_score >= 25:
                # Build summary of top targeted accounts
                top_accounts = []
                for fe in failed_entries[:5]:
                    top_accounts.append({
                        'account': fe.get('Account', ''),
                        'count': fe.get('Count', 0),
                        'source_ip': fe.get('SourceIP', ''),
                        'last_time': fe.get('LastTime', ''),
                    })

                indicators.append(SecurityIndicator(
                    indicator_type='login_event',
                    severity=severity,
                    title=f"{failed_total} failed logins in last 24h",
                    risk_score=min(risk_score, 100),
                    details={
                        'event_type': 'failed_logins',
                        'total_failures': failed_total,
                        'top_accounts': top_accounts,
                        'risk_factors': risk_factors,
                    },
                ))

        # --- Analyze RDP logins ---
        rdp_logins = data.get('RDPLogins', [])
        if isinstance(rdp_logins, dict):
            rdp_logins = [rdp_logins]

        non_local_rdp = [
            r for r in rdp_logins
            if r.get('SourceIP') not in ('127.0.0.1', '::1', '-', '', None)
        ]

        if non_local_rdp:
            risk_score = 50
            severity = 'medium'
            risk_factors = ['remote_rdp_access']

            if len(non_local_rdp) > 5:
                risk_score = 70
                severity = 'high'
                risk_factors.append('frequent_rdp')

            rdp_details = []
            for r in non_local_rdp[:10]:
                rdp_details.append({
                    'account': r.get('Account', ''),
                    'domain': r.get('Domain', ''),
                    'source_ip': r.get('SourceIP', ''),
                    'time': r.get('Time', ''),
                })

            indicators.append(SecurityIndicator(
                indicator_type='login_event',
                severity=severity,
                title=f"{len(non_local_rdp)} RDP sessions in last 7 days",
                risk_score=min(risk_score, 100),
                details={
                    'event_type': 'rdp_sessions',
                    'total_sessions': len(non_local_rdp),
                    'sessions': rdp_details,
                    'risk_factors': risk_factors,
                },
            ))

        logger.info(
            f"[SECURITY] Login analysis: {failed_total} failed logins, "
            f"{len(non_local_rdp)} RDP sessions, {len(indicators)} indicators"
        )
        return indicators

    def collect_disk_usage(self) -> List[SecurityIndicator]:
        """
        Collect disk usage pressure indicators for fixed drives.
        Thresholds:
        - 85%+: medium
        - 90%+: high
        - 95%+: critical
        """
        indicators = []

        ps_script = r'''
$results = @()
try {
    Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction SilentlyContinue | ForEach-Object {
        $size = [double]$_.Size
        $free = [double]$_.FreeSpace
        if ($size -gt 0) {
            $usedPercent = [math]::Round((($size - $free) / $size) * 100, 2)
            $results += [PSCustomObject]@{
                Drive       = $_.DeviceID
                VolumeName  = $_.VolumeName
                SizeGB      = [math]::Round($size / 1GB, 2)
                FreeGB      = [math]::Round($free / 1GB, 2)
                UsedPercent = $usedPercent
            }
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 3
'''

        output = self._run_powershell(ps_script, timeout=25)
        if not output:
            return indicators

        try:
            disks = json.loads(output)
            if isinstance(disks, dict):
                disks = [disks]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse disk usage JSON")
            return indicators

        for disk in disks:
            used_pct = float(disk.get('UsedPercent', 0))
            if used_pct < 85:
                continue

            if used_pct >= 95:
                severity = 'critical'
                risk_score = 95
            elif used_pct >= 90:
                severity = 'high'
                risk_score = 80
            else:
                severity = 'medium'
                risk_score = 60

            drive = disk.get('Drive', 'Unknown')
            volume = disk.get('VolumeName', '')
            indicators.append(SecurityIndicator(
                indicator_type='disk_usage',
                severity=severity,
                title=f"Disk usage high on {drive}: {used_pct:.1f}%",
                risk_score=risk_score,
                details={
                    'drive': drive,
                    'volume_name': volume,
                    'used_percent': used_pct,
                    'free_gb': float(disk.get('FreeGB', 0)),
                    'size_gb': float(disk.get('SizeGB', 0)),
                },
            ))

        logger.info(
            f"[SECURITY] Disk usage analysis: {len(indicators)} drives above threshold"
        )
        return indicators

    # =========================================================================
    # RAW SYSTEM VISIBILITY SNAPSHOT (NO RISK FILTERING)
    # =========================================================================

    def _collect_all_startup_programs_raw(self) -> List[Dict[str, Any]]:
        """Collect all startup programs (raw visibility view)."""
        ps_script = r'''
$results = @()
try {
    $hklm = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue
    if ($hklm) {
        $hklm.PSObject.Properties | Where-Object { $_.Name -notin @('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider') } | ForEach-Object {
            $results += [PSCustomObject]@{ Name=$_.Name; Command=$_.Value; Source='HKLM_Run' }
        }
    }
} catch {}
try {
    $hkcu = Get-ItemProperty -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue
    if ($hkcu) {
        $hkcu.PSObject.Properties | Where-Object { $_.Name -notin @('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider') } | ForEach-Object {
            $results += [PSCustomObject]@{ Name=$_.Name; Command=$_.Value; Source='HKCU_Run' }
        }
    }
} catch {}
try {
    $startupPath = [Environment]::GetFolderPath('Startup')
    if (Test-Path $startupPath) {
        Get-ChildItem -Path $startupPath -File -ErrorAction SilentlyContinue | ForEach-Object {
            $results += [PSCustomObject]@{ Name=$_.BaseName; Command=$_.FullName; Source='StartupFolder' }
        }
    }
} catch {}
try {
    Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue | ForEach-Object {
        $results += [PSCustomObject]@{
            Name=$_.Name; Command=$_.Command; Source='WMI'; User=$_.User; Location=$_.Location
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 3
'''
        output = self._run_powershell(ps_script, timeout=30)
        if not output:
            return []

        try:
            entries = json.loads(output)
            if isinstance(entries, dict):
                entries = [entries]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse raw startup JSON")
            return []

        results = []
        seen = set()
        for entry in entries:
            name = entry.get('Name', 'Unknown')
            command = entry.get('Command', '')
            source = entry.get('Source', '')
            dedup_key = (name.lower(), str(command).lower(), source)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            results.append({
                'name': name,
                'command': command[:600] if isinstance(command, str) else str(command),
                'source': source,
                'user': entry.get('User', ''),
                'location': entry.get('Location', ''),
            })
        return results

    def _collect_all_scheduled_tasks_raw(self) -> List[Dict[str, Any]]:
        """Collect all enabled scheduled tasks (raw visibility view)."""
        ps_script = r'''
$results = @()
try {
    Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' } | ForEach-Object {
        $task = $_
        $actions = @()
        foreach ($action in $task.Actions) {
            if ($action.Execute) {
                $actions += [PSCustomObject]@{
                    Execute = $action.Execute
                    Arguments = $action.Arguments
                }
            }
        }
        if ($actions.Count -gt 0) {
            $results += [PSCustomObject]@{
                TaskPath = $task.TaskPath
                TaskName = $task.TaskName
                State = $task.State.ToString()
                Actions = $actions
                Principal = $task.Principal.UserId
                Triggers = ($task.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ','
            }
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 4
'''
        output = self._run_powershell(ps_script, timeout=45)
        if not output:
            return []

        try:
            tasks = json.loads(output)
            if isinstance(tasks, dict):
                tasks = [tasks]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse raw task JSON")
            return []

        results = []
        for task in tasks:
            actions = task.get('Actions', [])
            if isinstance(actions, dict):
                actions = [actions]
            normalized_actions = []
            for action in actions:
                normalized_actions.append({
                    'execute': action.get('Execute', ''),
                    'arguments': action.get('Arguments', ''),
                })
            results.append({
                'task_name': task.get('TaskName', 'Unknown'),
                'task_path': task.get('TaskPath', ''),
                'state': task.get('State', ''),
                'principal': task.get('Principal', ''),
                'triggers': task.get('Triggers', ''),
                'actions': normalized_actions,
            })
        return results

    def _collect_all_open_ports_raw(self) -> List[Dict[str, Any]]:
        """Collect all listening TCP ports (raw visibility view)."""
        ps_script = r'''
$results = @()
try {
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        $proc = $null
        try { $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } catch {}
        $pName = 'Unknown'; $pPath = ''
        if ($proc) { $pName = $proc.ProcessName; $pPath = $proc.Path }
        $results += [PSCustomObject]@{
            LocalPort = $_.LocalPort
            LocalAddress = $_.LocalAddress
            ProcessId = $_.OwningProcess
            ProcessName = $pName
            ProcessPath = $pPath
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 3
'''
        output = self._run_powershell(ps_script, timeout=30)
        if not output:
            return []

        try:
            ports = json.loads(output)
            if isinstance(ports, dict):
                ports = [ports]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse raw ports JSON")
            return []

        results = []
        for entry in ports:
            results.append({
                'local_port': entry.get('LocalPort', 0),
                'local_address': entry.get('LocalAddress', ''),
                'process_id': entry.get('ProcessId', 0),
                'process_name': entry.get('ProcessName', 'Unknown'),
                'process_path': entry.get('ProcessPath', '')[:400] if isinstance(entry.get('ProcessPath', ''), str) else '',
            })
        return results

    def _collect_all_active_connections_raw(self) -> List[Dict[str, Any]]:
        """Collect all established TCP connections (raw visibility view)."""
        ps_script = r'''
$results = @()
try {
    Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | ForEach-Object {
        $proc = $null
        try { $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } catch {}
        $pName = 'Unknown'; $pPath = ''
        if ($proc) { $pName = $proc.ProcessName; $pPath = $proc.Path }
        $results += [PSCustomObject]@{
            LocalPort = $_.LocalPort
            LocalAddress = $_.LocalAddress
            RemotePort = $_.RemotePort
            RemoteAddress = $_.RemoteAddress
            ProcessId = $_.OwningProcess
            ProcessName = $pName
            ProcessPath = $pPath
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 3
'''
        output = self._run_powershell(ps_script, timeout=30)
        if not output:
            return []

        try:
            conns = json.loads(output)
            if isinstance(conns, dict):
                conns = [conns]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse raw connection JSON")
            return []

        results = []
        for entry in conns:
            results.append({
                'local_port': entry.get('LocalPort', 0),
                'local_address': entry.get('LocalAddress', ''),
                'remote_port': entry.get('RemotePort', 0),
                'remote_address': entry.get('RemoteAddress', ''),
                'process_id': entry.get('ProcessId', 0),
                'process_name': entry.get('ProcessName', 'Unknown'),
                'process_path': entry.get('ProcessPath', '')[:400] if isinstance(entry.get('ProcessPath', ''), str) else '',
            })
        return results

    def _collect_all_disk_usage_raw(self) -> List[Dict[str, Any]]:
        """Collect disk usage for all fixed drives (raw visibility view)."""
        ps_script = r'''
$results = @()
try {
    Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction SilentlyContinue | ForEach-Object {
        $size = [double]$_.Size
        $free = [double]$_.FreeSpace
        $used = 0
        if ($size -gt 0) { $used = [math]::Round((($size - $free) / $size) * 100, 2) }
        $results += [PSCustomObject]@{
            Drive = $_.DeviceID
            VolumeName = $_.VolumeName
            FileSystem = $_.FileSystem
            SizeGB = [math]::Round($size / 1GB, 2)
            FreeGB = [math]::Round($free / 1GB, 2)
            UsedPercent = $used
        }
    }
} catch {}
$results | ConvertTo-Json -Compress -Depth 3
'''
        output = self._run_powershell(ps_script, timeout=25)
        if not output:
            return []

        try:
            disks = json.loads(output)
            if isinstance(disks, dict):
                disks = [disks]
        except json.JSONDecodeError:
            logger.warning("[SECURITY] Failed to parse raw disk usage JSON")
            return []

        results = []
        for disk in disks:
            results.append({
                'drive': disk.get('Drive', ''),
                'volume_name': disk.get('VolumeName', ''),
                'file_system': disk.get('FileSystem', ''),
                'size_gb': float(disk.get('SizeGB', 0)),
                'free_gb': float(disk.get('FreeGB', 0)),
                'used_percent': float(disk.get('UsedPercent', 0)),
            })
        return results

    def collect_system_visibility_snapshot(self) -> Dict[str, Any]:
        """
        Collect raw latest system visibility (no risk filtering).
        Intended for dashboard visibility tables.
        """
        startup_programs = self._collect_all_startup_programs_raw()
        scheduled_tasks = self._collect_all_scheduled_tasks_raw()
        open_ports = self._collect_all_open_ports_raw()
        network_connections = self._collect_all_active_connections_raw()
        disk_usage = self._collect_all_disk_usage_raw()

        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'startup_programs': startup_programs,
            'scheduled_tasks': scheduled_tasks,
            'open_ports': open_ports,
            'network_connections': network_connections,
            'disk_usage': disk_usage,
            'counts': {
                'startup_programs': len(startup_programs),
                'scheduled_tasks': len(scheduled_tasks),
                'open_ports': len(open_ports),
                'network_connections': len(network_connections),
                'disk_usage': len(disk_usage),
            }
        }

    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================

    def collect_all_security(self, ext_inventory: Optional[Dict] = None) -> Dict:
        """
        Run all Phase 1 + 2 + 3 security analyses.
        
        Args:
            ext_inventory: Dict from ExtendedInventoryCollector.collect_all()
                          If None, only independent checks run.
        
        Returns:
            Dict with 'indicators' list and 'summary' metadata
        """
        all_indicators: List[Dict] = []
        summary = {
            'unsigned_drivers': 0,
            'suspicious_extensions': 0,
            'file_changes': 0,
            'suspicious_startups': 0,
            'suspicious_tasks': 0,
            'open_ports': 0,
            'suspicious_connections': 0,
            'usb_devices': 0,
            'login_events': 0,
            'disk_usage': 0,
        }
        
        # --- Phase 1: Analyze existing data ---
        if ext_inventory:
            drivers = ext_inventory.get('drivers', [])
            if drivers:
                driver_indicators = self.analyze_unsigned_drivers(drivers)
                summary['unsigned_drivers'] = len(driver_indicators)
                all_indicators.extend(ind.to_dict() for ind in driver_indicators)
            
            extensions = ext_inventory.get('browser_extensions', [])
            if extensions:
                ext_indicators = self.analyze_extension_risks(extensions)
                summary['suspicious_extensions'] = len(ext_indicators)
                all_indicators.extend(ind.to_dict() for ind in ext_indicators)
        
        # Always check system files (independent of ext_inventory)
        file_indicators = self.check_system_files()
        summary['file_changes'] = len(file_indicators)
        all_indicators.extend(ind.to_dict() for ind in file_indicators)
        
        # --- Phase 2: Persistence & network exposure ---
        try:
            startup_indicators = self.collect_startup_programs()
            summary['suspicious_startups'] = len(startup_indicators)
            all_indicators.extend(ind.to_dict() for ind in startup_indicators)
        except Exception as e:
            logger.error(f"[SECURITY] Startup collection failed: {e}")
        
        try:
            task_indicators = self.collect_scheduled_tasks()
            summary['suspicious_tasks'] = len(task_indicators)
            all_indicators.extend(ind.to_dict() for ind in task_indicators)
        except Exception as e:
            logger.error(f"[SECURITY] Task collection failed: {e}")
        
        try:
            port_indicators = self.collect_open_ports()
            summary['open_ports'] = len(port_indicators)
            all_indicators.extend(ind.to_dict() for ind in port_indicators)
        except Exception as e:
            logger.error(f"[SECURITY] Port collection failed: {e}")
        
        # --- Phase 3: Connections, USB, login history ---
        try:
            conn_indicators = self.collect_active_connections()
            summary['suspicious_connections'] = len(conn_indicators)
            all_indicators.extend(ind.to_dict() for ind in conn_indicators)
        except Exception as e:
            logger.error(f"[SECURITY] Connection collection failed: {e}")
        
        try:
            usb_indicators = self.collect_usb_history()
            summary['usb_devices'] = len(usb_indicators)
            all_indicators.extend(ind.to_dict() for ind in usb_indicators)
        except Exception as e:
            logger.error(f"[SECURITY] USB collection failed: {e}")
        
        try:
            login_indicators = self.collect_login_history()
            summary['login_events'] = len(login_indicators)
            all_indicators.extend(ind.to_dict() for ind in login_indicators)
        except Exception as e:
            logger.error(f"[SECURITY] Login history collection failed: {e}")

        if self.enable_disk_usage_indicator:
            try:
                disk_indicators = self.collect_disk_usage()
                summary['disk_usage'] = len(disk_indicators)
                all_indicators.extend(ind.to_dict() for ind in disk_indicators)
            except Exception as e:
                logger.error(f"[SECURITY] Disk usage collection failed: {e}")
        
        total = len(all_indicators)
        logger.info(
            f"[SECURITY] Collection complete ({total} total): "
            f"drivers={summary['unsigned_drivers']}, "
            f"extensions={summary['suspicious_extensions']}, "
            f"files={summary['file_changes']}, "
            f"startups={summary['suspicious_startups']}, "
            f"tasks={summary['suspicious_tasks']}, "
            f"ports={summary['open_ports']}, "
            f"connections={summary['suspicious_connections']}, "
            f"usb={summary['usb_devices']}, "
            f"logins={summary['login_events']}, "
            f"disk={summary['disk_usage']}"
        )
        
        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'indicators': all_indicators,
            'summary': summary,
        }
