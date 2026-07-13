"""
Hardware Collector Module - IT Asset Management
================================================
Collects comprehensive hardware and system information for asset tracking.

Features:
- System identity (hostname, serial, manufacturer, model, BIOS UUID)
- Hardware specs (CPU, RAM, disk sizes/types, GPU)
- Network configuration (MAC address, IP address, domain membership)
- Security posture (AV installed, firewall status, Windows version)

Collection Methods:
- CIM (Common Information Model) via PowerShell - modern replacement for WMI
- Native Python libraries where possible
- Graceful fallback on errors

Data Flow:
- Collected on agent startup and every 24 hours
- Sent to server with heartbeat or dedicated endpoint
- Changes detected via hash comparison (like inventory)
"""

import subprocess
import json
import hashlib
import logging
import socket
import platform
import uuid
import os
import re
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any
from pathlib import Path
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class AssetIdentity:
    """Core identity information for the asset"""
    hostname: str = ""
    serial_number: str = ""
    manufacturer: str = ""
    model: str = ""
    bios_uuid: str = ""
    system_uuid: str = ""
    asset_tag: str = ""  # Often same as serial or custom
    domain: str = ""
    workgroup: str = ""


@dataclass
class GPUInfo:
    """Single GPU entry"""
    name: str = ""
    memory_gb: float = 0.0


@dataclass
class HardwareSpecs:
    """Hardware specifications"""
    cpu_name: str = ""
    cpu_cores: int = 0
    cpu_threads: int = 0
    cpu_speed_mhz: int = 0
    ram_total_gb: float = 0.0
    ram_slots_used: int = 0
    ram_slots_total: int = 0
    gpus: List[GPUInfo] = field(default_factory=list)  # List of all GPUs
    disks: List[Dict] = field(default_factory=list)  # [{name, size_gb, type, interface}]
    motherboard: str = ""


@dataclass
class NetworkInfo:
    """Network configuration"""
    primary_mac: str = ""
    primary_ip: str = ""
    all_macs: List[str] = field(default_factory=list)
    all_ips: List[str] = field(default_factory=list)
    dns_servers: List[str] = field(default_factory=list)
    domain_joined: bool = False
    domain_name: str = ""


@dataclass
class SecurityInfo:
    """Security posture information"""
    os_name: str = ""
    os_version: str = ""
    os_build: str = ""
    os_architecture: str = ""
    os_edition: str = ""      # Pro, Enterprise, Home, Education, LTSC
    os_sku: int = 0           # Windows SKU number for precise identification
    antivirus_installed: List[str] = field(default_factory=list)
    firewall_enabled: bool = False
    last_boot_time: str = ""
    windows_update_enabled: bool = False
    bitlocker_status: str = ""


@dataclass
class AssetData:
    """Complete asset data structure"""
    identity: AssetIdentity = field(default_factory=AssetIdentity)
    hardware: HardwareSpecs = field(default_factory=HardwareSpecs)
    network: NetworkInfo = field(default_factory=NetworkInfo)
    security: SecurityInfo = field(default_factory=SecurityInfo)
    collected_at: str = ""
    collection_hash: str = ""
    agent_version: str = "2.0"

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'identity': asdict(self.identity),
            'hardware': asdict(self.hardware),
            'network': asdict(self.network),
            'security': asdict(self.security),
            'collected_at': self.collected_at,
            'collection_hash': self.collection_hash,
            'agent_version': self.agent_version
        }


class HardwareCollector:
    """
    Collects comprehensive hardware and system information.

    Collection runs:
    - On agent registration (full collection)
    - Every 24 hours (change detection)
    - On-demand when requested

    Uses PowerShell/CIM for most data collection with Python fallbacks.
    Get-CimInstance is the modern replacement for deprecated Get-WmiObject,
    using WS-Management instead of DCOM (required on Windows 11 25H2+).
    """

    # Collection interval: 24 hours
    COLLECTION_INTERVAL = 24 * 60 * 60  # 86400 seconds

    def __init__(self, config=None):
        self.config = config
        self.last_collection_time: Optional[datetime] = None
        self.last_hash: str = ""
        self.last_network_hash: str = ""
        self._state_file = self._get_state_file()
        self._load_state()

        logger.info("[HARDWARE] HardwareCollector initialized (24h hardware, instant network)")

    def _get_state_file(self) -> Path:
        """Get path to state file for persistence"""
        if self.config and hasattr(self.config, 'state_dir'):
            return Path(self.config.state_dir) / "hardware_state.json"
        return Path.home() / ".sentineledge" / "hardware_state.json"

    def _load_state(self):
        """Load previous collection state"""
        try:
            if self._state_file.exists():
                with open(self._state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    self.last_hash = state.get('hash', '')
                    self.last_network_hash = state.get('network_hash', '')
                    last_time = state.get('last_collection_time')
                    if last_time:
                        self.last_collection_time = datetime.fromisoformat(last_time)
                    logger.debug(f"[HARDWARE] Loaded state: hash={self.last_hash[:8] if self.last_hash else 'none'}, net={self.last_network_hash[:8] if self.last_network_hash else 'none'}")
        except Exception as e:
            logger.warning(f"[HARDWARE] Could not load state: {e}")

    def _save_state(self, data_hash: str, network_hash: str = None):
        """Save collection state to disk"""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'hash': data_hash,
                'last_collection_time': datetime.now(timezone.utc).isoformat()
            }
            if network_hash is not None:
                state['network_hash'] = network_hash
            elif self.last_network_hash:
                state['network_hash'] = self.last_network_hash
            with open(self._state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            logger.debug(f"[HARDWARE] State saved")
        except Exception as e:
            logger.error(f"[HARDWARE] Error saving state: {e}")

    def should_collect(self) -> bool:
        """Check if collection is due"""
        if self.last_collection_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self.last_collection_time).total_seconds()
        return elapsed >= self.COLLECTION_INTERVAL

    def collect(self, force: bool = False) -> Optional[Dict]:
        """
        Collect all hardware/system information.

        Args:
            force: Force collection regardless of interval

        Returns:
            Dict with asset data, or None if no changes/not due
        """
        if not force and not self.should_collect():
            logger.debug("[HARDWARE] Collection not due yet")
            return None

        logger.info("[HARDWARE] Starting hardware collection...")

        asset_data = AssetData()
        asset_data.collected_at = datetime.now(timezone.utc).isoformat()

        # Collect each category
        try:
            asset_data.identity = self._collect_identity()
            logger.debug("[HARDWARE] Identity collected")
        except Exception as e:
            logger.error(f"[HARDWARE] Identity collection failed: {e}")

        try:
            asset_data.hardware = self._collect_hardware()
            logger.debug("[HARDWARE] Hardware specs collected")
        except Exception as e:
            logger.error(f"[HARDWARE] Hardware collection failed: {e}")

        try:
            asset_data.network = self._collect_network()
            logger.debug("[HARDWARE] Network info collected")
        except Exception as e:
            logger.error(f"[HARDWARE] Network collection failed: {e}")

        try:
            asset_data.security = self._collect_security()
            logger.debug("[HARDWARE] Security info collected")
        except Exception as e:
            logger.error(f"[HARDWARE] Security collection failed: {e}")

        # Compute hash for change detection
        data_dict = asset_data.to_dict()
        # Exclude timestamp from hash calculation
        hash_data = {k: v for k, v in data_dict.items() if k != 'collected_at'}
        current_hash = hashlib.sha256(
            json.dumps(hash_data, sort_keys=True).encode()
        ).hexdigest()[:16]

        asset_data.collection_hash = current_hash

        # Check for changes
        if current_hash == self.last_hash and not force:
            logger.info("[HARDWARE] No changes detected")
            self.last_collection_time = datetime.now(timezone.utc)
            return None

        # Save state and return data.
        # Also compute and persist the network hash so that
        # collect_network_partial() (called every 5 min) sees an up-to-date
        # baseline after agent restarts.  Without this, last_network_hash would
        # stay stale and every first network check would look like a "change".
        network = asset_data.network
        network_hash_data = {
            'all_macs': sorted(network.all_macs),
            'all_ips': sorted(network.all_ips),
            'dns_servers': sorted(network.dns_servers),
            'domain_joined': network.domain_joined,
            'domain_name': network.domain_name,
        }
        current_network_hash = hashlib.sha256(
            json.dumps(network_hash_data, sort_keys=True).encode()
        ).hexdigest()[:16]
        self.last_network_hash = current_network_hash
        self._save_state(current_hash, current_network_hash)
        self.last_hash = current_hash
        self.last_collection_time = datetime.now(timezone.utc)

        logger.info(
            f"[HARDWARE] Collection complete "
            f"(hash: {current_hash}, net: {current_network_hash})"
        )
        return asset_data.to_dict()

    def _run_powershell(self, script: str, timeout: int = 30) -> Optional[str]:
        """Run PowerShell command and return output"""
        try:
            # Force UTF-8 output to prevent JSON corruption from down-converted smart quotes
            utf8_script = f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {script}"
            
            # Use CREATE_NO_WINDOW for robust background execution
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", utf8_script],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode == 0:
                return result.stdout.strip()
            else:
                stderr_preview = result.stderr[:100] if result.stderr else "No stderr"
                logger.debug(f"[HARDWARE] PowerShell execution failed (code {result.returncode}): {stderr_preview}")
                return None

        except subprocess.TimeoutExpired:
            logger.warning(f"[HARDWARE] PowerShell timeout ({timeout}s)")
            return None
        except Exception as e:
            logger.debug(f"[HARDWARE] PowerShell process creation failed: {e}")
            return None

    @staticmethod
    def _normalize_powershell_scalar(value: Any) -> str:
        """Normalize PowerShell JSON output that may be scalar or single-item list."""
        if isinstance(value, list):
            value = value[0] if value else ""
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _normalize_powershell_list(value: Any) -> List[str]:
        """Normalize PowerShell JSON output so single-item arrays stay lists."""
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [str(item).strip() for item in value if item not in (None, "")]

    def _collect_identity(self) -> AssetIdentity:
        """Collect system identity information"""
        identity = AssetIdentity()

        # Hostname (Python fallback)
        identity.hostname = socket.gethostname()

        # System info via CIM (modern replacement for deprecated Get-WmiObject)
        script = '''
        $ErrorActionPreference = 'SilentlyContinue'
        $cs = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, Domain, PartOfDomain, Workgroup
        $bios = Get-CimInstance Win32_BIOS | Select-Object SerialNumber, SMBIOSBIOSVersion
        $csproduct = Get-CimInstance Win32_ComputerSystemProduct | Select-Object UUID, IdentifyingNumber

        @{
            Manufacturer = $cs.Manufacturer
            Model = $cs.Model
            Domain = $cs.Domain
            PartOfDomain = $cs.PartOfDomain
            Workgroup = $cs.Workgroup
            SerialNumber = $bios.SerialNumber
            BIOSVersion = $bios.SMBIOSBIOSVersion
            UUID = $csproduct.UUID
            AssetTag = $csproduct.IdentifyingNumber
        } | ConvertTo-Json
        '''

        output = self._run_powershell(script)
        if output:
            try:
                data = json.loads(output)
                identity.manufacturer = data.get('Manufacturer', '') or ''
                identity.model = data.get('Model', '') or ''
                identity.serial_number = data.get('SerialNumber', '') or ''
                identity.bios_uuid = data.get('UUID', '') or ''
                identity.system_uuid = data.get('UUID', '') or ''
                identity.asset_tag = data.get('AssetTag', '') or identity.serial_number
                identity.domain = data.get('Domain', '') or ''
                identity.workgroup = data.get('Workgroup', '') or ''
            except json.JSONDecodeError:
                logger.debug("[HARDWARE] Failed to parse identity JSON")

        # Fallback for UUID if CIM failed
        if not identity.system_uuid:
            try:
                identity.system_uuid = str(uuid.getnode())
            except:
                pass

        return identity

    def _collect_hardware(self) -> HardwareSpecs:
        """Collect hardware specifications"""
        hardware = HardwareSpecs()

        script = '''
        $ProgressPreference = 'SilentlyContinue'
        $ErrorActionPreference = 'SilentlyContinue'

        # CPU - use Get-CimInstance (modern, replaces deprecated Get-WmiObject)
        $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1

        # RAM
        $ram = Get-CimInstance Win32_PhysicalMemory
        $ramSlots = (Get-CimInstance Win32_PhysicalMemoryArray).MemoryDevices

        # GPU - use Get-CimInstance (not deprecated Get-WmiObject).
        # Do NOT filter on $_.Name - Intel Arc / integrated GPUs on Win11 25H2
        # may return an empty Name on first query but valid Caption/Description.
        # Let ALL objects through; resolve name with fallback chain in ForEach.
        $gpuObjects = Get-CimInstance Win32_VideoController

        # Fallback 1: try PnP device list if CIM query returns nothing
        if (-not $gpuObjects) {
            $gpuObjects = Get-CimInstance Win32_PnPEntity |
                Where-Object { $_.PNPClass -eq "Display" }
        }

        # Fallback 2: legacy Get-WmiObject in case CIM/WinRM is unavailable
        if (-not $gpuObjects) {
            $gpuObjects = Get-WmiObject Win32_VideoController -ErrorAction SilentlyContinue
        }

        $gpus = @($gpuObjects | ForEach-Object {
            # Resolve display name via fallback chain
            $gpuName = if ($_.Name)        { $_.Name }
                       elseif ($_.Caption)  { $_.Caption }
                       elseif ($_.Description) { $_.Description }
                       else                { "Unknown GPU" }

            $memoryGb = 0
            # AdapterRAM is a UINT32 and overflows at ~4 GB on some drivers.
            # Only trust values above 128 MB (134217728 bytes) to avoid noise.
            if ($null -ne $_.AdapterRAM -and $_.AdapterRAM -gt 134217728) {
                $memoryGb = [math]::Round($_.AdapterRAM / 1GB, 2)
            }
            @{
                Name     = $gpuName.Trim()
                MemoryGB = $memoryGb
            }
        })

        # Disks - use Get-CimInstance
        $disks = Get-CimInstance Win32_DiskDrive | Select-Object Model, Size, MediaType, InterfaceType

        # Motherboard - use Get-CimInstance
        $mb = Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product

        @{
            CPU_Name = $cpu.Name
            CPU_Cores = $cpu.NumberOfCores
            CPU_Threads = $cpu.NumberOfLogicalProcessors
            CPU_Speed = $cpu.MaxClockSpeed
            RAM_Total = ($ram | Measure-Object -Property Capacity -Sum).Sum
            RAM_SlotsUsed = ($ram | Measure-Object).Count
            RAM_SlotsTotal = $ramSlots
            GPUs = $gpus
            Disks = $disks | ForEach-Object {
                $diskName = $_.Model
                $isVirtual = $false

                # Detect virtual disks
                if ($diskName -match 'Virtual Disk|VMware|Virtual HD|Virtual DVD|CD-ROM|DVD|Mounted|ramdisk|ImDisk') {
                    $isVirtual = $true
                    if ($diskName -notmatch '^\\[VD\\]') {
                        $diskName = "[VD] " + $diskName
                    }
                }

                @{
                    Name = $diskName
                    SizeGB = [math]::Round($_.Size / 1GB, 2)
                    Type = $_.MediaType
                    Interface = $_.InterfaceType
                    IsVirtual = $isVirtual
                }
            }
            Motherboard = "$($mb.Manufacturer) $($mb.Product)"
        } | ConvertTo-Json -Depth 3
        '''

        output = self._run_powershell(script, timeout=45)
        if output:
            try:
                data = json.loads(output)
                hardware.cpu_name = (data.get('CPU_Name', '') or '').strip()
                hardware.cpu_cores = int(data.get('CPU_Cores', 0) or 0)
                hardware.cpu_threads = int(data.get('CPU_Threads', 0) or 0)
                hardware.cpu_speed_mhz = int(data.get('CPU_Speed', 0) or 0)

                ram_bytes = data.get('RAM_Total', 0) or 0
                hardware.ram_total_gb = round(ram_bytes / (1024**3), 2)
                hardware.ram_slots_used = int(data.get('RAM_SlotsUsed', 0) or 0)
                hardware.ram_slots_total = int(data.get('RAM_SlotsTotal', 0) or 0)

                # Parse all GPUs - do NOT filter on name here (already resolved in PS)
                gpus_data = data.get('GPUs', [])
                if gpus_data:
                    if isinstance(gpus_data, dict):
                        gpus_data = [gpus_data]
                    hardware.gpus = [
                        GPUInfo(
                            name=g.get('Name', 'Unknown GPU').strip(),
                            memory_gb=float(g.get('MemoryGB', 0) or 0)
                        )
                        for g in gpus_data if g
                    ]

                hardware.motherboard = (data.get('Motherboard', '') or '').strip()

                # Parse disks
                disks_data = data.get('Disks', [])
                if disks_data:
                    if isinstance(disks_data, dict):
                        disks_data = [disks_data]
                    hardware.disks = [
                        {
                            'name': d.get('Name', 'Unknown'),
                            'size_gb': d.get('SizeGB', 0),
                            'type': d.get('Type', 'Unknown'),
                            'interface': d.get('Interface', 'Unknown')
                        }
                        for d in disks_data if d
                    ]
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug(f"[HARDWARE] Failed to parse hardware JSON: {e}")

        # Python fallback for basic CPU info
        if not hardware.cpu_name:
            hardware.cpu_name = platform.processor()
        if hardware.cpu_cores == 0:
            try:
                hardware.cpu_cores = os.cpu_count() or 1
            except:
                pass

        return hardware

    def _collect_network(self) -> NetworkInfo:
        """Collect network configuration"""
        network = NetworkInfo()

        script = '''
        $ProgressPreference = 'SilentlyContinue'
        $ErrorActionPreference = 'SilentlyContinue'

        # Get active network adapters - use Get-CimInstance (modern)
        $adapters = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true }

        # Get computer system for domain info
        $cs = Get-CimInstance Win32_ComputerSystem

        $macs = @()
        $ips = @()
        $dns = @()

        foreach ($adapter in $adapters) {
            if ($adapter.MACAddress) { $macs += $adapter.MACAddress }
            if ($adapter.IPAddress) { $ips += $adapter.IPAddress }
            if ($adapter.DNSServerSearchOrder) { $dns += $adapter.DNSServerSearchOrder }
        }

        $ipv4 = @($ips | Where-Object { $_ -and $_ -notmatch ':' } | Select-Object -Unique)
        $uniqueMacs = @($macs | Where-Object { $_ } | Select-Object -Unique)
        $uniqueDns = @($dns | Where-Object { $_ } | Select-Object -Unique)

        @{
            PrimaryMAC = if ($uniqueMacs.Count -gt 0) { $uniqueMacs[0] } else { "" }
            PrimaryIP = if ($ipv4.Count -gt 0) { $ipv4[0] } else { "" }
            AllMACs = $uniqueMacs
            AllIPs = $ipv4
            DNSServers = $uniqueDns
            DomainJoined = $cs.PartOfDomain
            DomainName = if ($cs.PartOfDomain) { $cs.Domain } else { "" }
        } | ConvertTo-Json -Depth 2
        '''

        output = self._run_powershell(script)
        if output:
            try:
                data = json.loads(output)
                network.primary_mac = self._normalize_powershell_scalar(data.get('PrimaryMAC'))
                network.primary_ip = self._normalize_powershell_scalar(data.get('PrimaryIP'))
                network.all_macs = self._normalize_powershell_list(data.get('AllMACs'))
                network.all_ips = self._normalize_powershell_list(data.get('AllIPs'))
                network.dns_servers = self._normalize_powershell_list(data.get('DNSServers'))
                network.domain_joined = bool(data.get('DomainJoined', False))
                network.domain_name = self._normalize_powershell_scalar(data.get('DomainName'))
            except json.JSONDecodeError:
                logger.debug("[HARDWARE] Failed to parse network JSON")

        # Python fallback (always overrides PowerShell — socket connects to routing interface)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            network.primary_ip = s.getsockname()[0]
            s.close()
        except:
            network.primary_ip = network.primary_ip or "127.0.0.1"

        return network

    def _collect_security(self) -> SecurityInfo:
        """Collect security posture information"""
        security = SecurityInfo()

        script = '''
        $ProgressPreference = 'SilentlyContinue'
        $ErrorActionPreference = 'SilentlyContinue'

        # Antivirus (Windows Security Center) - use Get-CimInstance
        $av = @()
        try {
            $avProducts = Get-CimInstance -Namespace "root\\SecurityCenter2" -ClassName AntiVirusProduct -ErrorAction SilentlyContinue
            foreach ($product in $avProducts) {
                $av += $product.displayName
            }
        } catch {}

        # Firewall status
        $fwEnabled = $false
        try {
            $fw = Get-NetFirewallProfile -Profile Domain,Public,Private -ErrorAction SilentlyContinue
            $fwEnabled = ($fw | Where-Object { $_.Enabled -eq $true }).Count -gt 0
        } catch {}

        # Last boot time - use Get-CimInstance (LastBootUpTime is already a DateTime)
        $os = Get-CimInstance Win32_OperatingSystem
        $lastBoot = $os.LastBootUpTime.ToString("o")

        # Windows Update status
        $wuEnabled = $false
        try {
            $wuService = Get-Service -Name wuauserv -ErrorAction SilentlyContinue
            $wuEnabled = $wuService.Status -eq 'Running'
        } catch {}

        # BitLocker (simplified check)
        $bitlocker = "Unknown"
        try {
            $bl = Get-BitLockerVolume -MountPoint "C:" -ErrorAction SilentlyContinue
            if ($bl) {
                $bitlocker = $bl.ProtectionStatus.ToString()
            }
        } catch {}

        # Extract Windows edition from Caption (e.g., "Microsoft Windows 11 Pro" -> "Pro")
        $osCaption = $os.Caption
        $osEdition = $osCaption -replace 'Microsoft Windows \\d+ ' -replace 'Microsoft Windows ', ''

        # Get SKU number for precise identification
        $osSku = $os.OperatingSystemSKU

        # Get Windows version from registry (DisplayVersion like "23H2", "24H2", "25H2")
        $regPath = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion'
        $displayVersion = ""
        try {
            $reg = Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue
            $displayVersion = $reg.DisplayVersion
            if ([string]::IsNullOrEmpty($displayVersion)) {
                $displayVersion = $reg.ReleaseId
            }
        } catch {}

        @{
            Antivirus = $av
            FirewallEnabled = $fwEnabled
            LastBootTime = $lastBoot
            WindowsUpdateEnabled = $wuEnabled
            BitLockerStatus = $bitlocker
            OSCaption = $osCaption
            OSVersion = $os.Version
            OSBuild = $os.BuildNumber
            OSArchitecture = $os.OSArchitecture
            OSEdition = $osEdition
            OSSKU = $osSku
            DisplayVersion = $displayVersion
        } | ConvertTo-Json
        '''

        output = self._run_powershell(script, timeout=45)
        if output:
            try:
                data = json.loads(output)
                security.antivirus_installed = data.get('Antivirus', []) or []
                security.firewall_enabled = bool(data.get('FirewallEnabled', False))
                security.last_boot_time = data.get('LastBootTime', '') or ''
                security.windows_update_enabled = bool(data.get('WindowsUpdateEnabled', False))
                security.bitlocker_status = data.get('BitLockerStatus', 'Unknown') or 'Unknown'

                # OS info from CIM (more accurate than platform module)
                security.os_name = data.get('OSCaption') or security.os_name
                # Use DisplayVersion from registry (e.g., "25H2") instead of raw build number
                display_ver = data.get('DisplayVersion') or ''
                if display_ver and display_ver.strip():
                    security.os_version = display_ver.strip()
                else:
                    security.os_version = data.get('OSVersion') or security.os_version
                security.os_build = str(data.get('OSBuild') or security.os_build)
                security.os_architecture = data.get('OSArchitecture') or security.os_architecture

                # Windows edition and SKU for EOL matching
                if data.get('OSEdition'):
                    security.os_edition = data['OSEdition']
                if data.get('OSSKU'):
                    try:
                        security.os_sku = int(data['OSSKU'])
                    except (ValueError, TypeError):
                        security.os_sku = 0
            except json.JSONDecodeError:
                logger.debug("[HARDWARE] Failed to parse security JSON")

        return security

    def get_summary(self) -> Dict:
        """Get a brief summary of collected data (for logging/heartbeat)"""
        if not self.last_hash:
            return {'status': 'not_collected'}

        return {
            'status': 'collected',
            'hash': self.last_hash,
            'network_hash': self.last_network_hash,
            'last_collection': self.last_collection_time.isoformat() if self.last_collection_time else None
        }

    def check_network_changed(self) -> bool:
        """
        Check if network adapters have changed since last collection.
        Call this periodically or on network event to detect changes.

        Returns:
            True if network has changed, False otherwise
        """
        network = self._collect_network()

        # Create hash from network data only (sorted lists for order-independence)
        network_hash_data = {
            'all_macs': sorted(network.all_macs),
            'all_ips': sorted(network.all_ips),
            'dns_servers': sorted(network.dns_servers),
            'domain_joined': network.domain_joined,
            'domain_name': network.domain_name
        }
        current_network_hash = hashlib.sha256(
            json.dumps(network_hash_data, sort_keys=True).encode()
        ).hexdigest()[:16]

        changed = current_network_hash != self.last_network_hash

        if changed:
            logger.info(f"[HARDWARE] Network changed: {self.last_network_hash[:8] if self.last_network_hash else 'none'} -> {current_network_hash}")
        else:
            logger.debug(f"[HARDWARE] Network unchanged")

        return changed

    def collect_network_partial(self) -> Optional[Dict]:
        """
        Collect and send ONLY network data when change is detected.
        This is lightweight and can be called on network events.

        Returns:
            Dict with network data, or None if no changes
        """
        network = self._collect_network()

        # Create hash from network data only (sorted lists for order-independence)
        network_hash_data = {
            'all_macs': sorted(network.all_macs),
            'all_ips': sorted(network.all_ips),
            'dns_servers': sorted(network.dns_servers),
            'domain_joined': network.domain_joined,
            'domain_name': network.domain_name
        }
        current_network_hash = hashlib.sha256(
            json.dumps(network_hash_data, sort_keys=True).encode()
        ).hexdigest()[:16]

        # Check for actual change
        if current_network_hash == self.last_network_hash:
            logger.debug("[HARDWARE] Network unchanged, skipping partial upload")
            return None

        # Update state
        self.last_network_hash = current_network_hash
        self._save_state(self.last_hash, current_network_hash)

        logger.info(f"[HARDWARE] Network partial collected: {current_network_hash}")

        return {
            'agent_id': getattr(self.config, 'agent_id', '') if self.config else '',
            'network': asdict(network),
            'collected_at': datetime.now(timezone.utc).isoformat(),
            'collection_hash': current_network_hash,
            'update_type': 'network_partial'
        }

    def get_network_state(self) -> Dict:
        """Get current network state info for external monitoring"""
        return {
            'last_network_hash': self.last_network_hash,
            'has_baseline': bool(self.last_network_hash)
        }
