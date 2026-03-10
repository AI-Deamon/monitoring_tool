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
- WMI (Windows Management Instrumentation) via PowerShell
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
class HardwareSpecs:
    """Hardware specifications"""
    cpu_name: str = ""
    cpu_cores: int = 0
    cpu_threads: int = 0
    cpu_speed_mhz: int = 0
    ram_total_gb: float = 0.0
    ram_slots_used: int = 0
    ram_slots_total: int = 0
    gpu_name: str = ""
    gpu_memory_gb: float = 0.0
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
    
    Uses PowerShell/WMI for most data collection with Python fallbacks.
    """
    
    # Collection interval: 24 hours
    COLLECTION_INTERVAL = 24 * 60 * 60  # 86400 seconds
    
    def __init__(self, config=None):
        self.config = config
        self.last_collection_time: Optional[datetime] = None
        self.last_hash: str = ""
        self._state_file = self._get_state_file()
        self._load_state()
        
        logger.info("[HARDWARE] HardwareCollector initialized (24-hour intervals)")
    
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
                    last_time = state.get('last_collection_time')
                    if last_time:
                        self.last_collection_time = datetime.fromisoformat(last_time)
                    logger.debug(f"[HARDWARE] Loaded state: hash={self.last_hash[:8] if self.last_hash else 'none'}")
        except Exception as e:
            logger.warning(f"[HARDWARE] Could not load state: {e}")
    
    def _save_state(self, data_hash: str):
        """Save collection state to disk"""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'hash': data_hash,
                'last_collection_time': datetime.now(timezone.utc).isoformat()
            }
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
        
        # Save state and return data
        self._save_state(current_hash)
        self.last_hash = current_hash
        self.last_collection_time = datetime.now(timezone.utc)
        
        logger.info(f"[HARDWARE] Collection complete (hash: {current_hash})")
        return asset_data.to_dict()
    
    def _run_powershell(self, script: str, timeout: int = 30) -> Optional[str]:
        """Run PowerShell command and return output"""
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                timeout=timeout,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.debug(f"[HARDWARE] PowerShell error: {result.stderr[:100]}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning(f"[HARDWARE] PowerShell timeout ({timeout}s)")
            return None
        except Exception as e:
            logger.debug(f"[HARDWARE] PowerShell error: {e}")
            return None
    
    def _collect_identity(self) -> AssetIdentity:
        """Collect system identity information"""
        identity = AssetIdentity()
        
        # Hostname (Python fallback)
        identity.hostname = socket.gethostname()
        
        # System info via WMI
        script = '''
        $cs = Get-WmiObject Win32_ComputerSystem | Select-Object Manufacturer, Model, Domain, PartOfDomain, Workgroup
        $bios = Get-WmiObject Win32_BIOS | Select-Object SerialNumber, SMBIOSBIOSVersion
        $csproduct = Get-WmiObject Win32_ComputerSystemProduct | Select-Object UUID, IdentifyingNumber
        
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
        
        # Fallback for UUID if WMI failed
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
        
        # CPU
        $cpu = Get-WmiObject Win32_Processor | Select-Object -First 1
        
        # RAM
        $ram = Get-WmiObject Win32_PhysicalMemory
        $ramSlots = (Get-WmiObject Win32_PhysicalMemoryArray).MemoryDevices
        
        # GPU
        $gpu = Get-WmiObject Win32_VideoController | Where-Object { $_.AdapterRAM -gt 0 } | Select-Object -First 1
        
        # Disks
        $disks = Get-WmiObject Win32_DiskDrive | Select-Object Model, Size, MediaType, InterfaceType
        
        # Motherboard
        $mb = Get-WmiObject Win32_BaseBoard | Select-Object Manufacturer, Product
        
        @{
            CPU_Name = $cpu.Name
            CPU_Cores = $cpu.NumberOfCores
            CPU_Threads = $cpu.NumberOfLogicalProcessors
            CPU_Speed = $cpu.MaxClockSpeed
            RAM_Total = ($ram | Measure-Object -Property Capacity -Sum).Sum
            RAM_SlotsUsed = ($ram | Measure-Object).Count
            RAM_SlotsTotal = $ramSlots
            GPU_Name = $gpu.Name
            GPU_Memory = $gpu.AdapterRAM
            Disks = $disks | ForEach-Object {
                @{
                    Name = $_.Model
                    SizeGB = [math]::Round($_.Size / 1GB, 2)
                    Type = $_.MediaType
                    Interface = $_.InterfaceType
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
                
                hardware.gpu_name = (data.get('GPU_Name', '') or '').strip()
                gpu_bytes = data.get('GPU_Memory', 0) or 0
                hardware.gpu_memory_gb = round(gpu_bytes / (1024**3), 2)
                
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
        
        # Python fallback for basic info
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
        
        # Get active network adapters
        $adapters = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true }
        
        # Get computer system for domain info
        $cs = Get-WmiObject Win32_ComputerSystem
        
        $macs = @()
        $ips = @()
        $dns = @()
        
        foreach ($adapter in $adapters) {
            if ($adapter.MACAddress) { $macs += $adapter.MACAddress }
            if ($adapter.IPAddress) { $ips += $adapter.IPAddress }
            if ($adapter.DNSServerSearchOrder) { $dns += $adapter.DNSServerSearchOrder }
        }
        
        @{
            PrimaryMAC = if ($macs.Count -gt 0) { $macs[0] } else { "" }
            PrimaryIP = if ($ips.Count -gt 0) { ($ips | Where-Object { $_ -notmatch ':' })[0] } else { "" }
            AllMACs = $macs | Select-Object -Unique
            AllIPs = $ips | Where-Object { $_ -notmatch ':' } | Select-Object -Unique
            DNSServers = $dns | Select-Object -Unique
            DomainJoined = $cs.PartOfDomain
            DomainName = if ($cs.PartOfDomain) { $cs.Domain } else { "" }
        } | ConvertTo-Json -Depth 2
        '''
        
        output = self._run_powershell(script)
        if output:
            try:
                data = json.loads(output)
                network.primary_mac = data.get('PrimaryMAC', '') or ''
                network.primary_ip = data.get('PrimaryIP', '') or ''
                network.all_macs = data.get('AllMACs', []) or []
                network.all_ips = data.get('AllIPs', []) or []
                network.dns_servers = data.get('DNSServers', []) or []
                network.domain_joined = bool(data.get('DomainJoined', False))
                network.domain_name = data.get('DomainName', '') or ''
            except json.JSONDecodeError:
                logger.debug("[HARDWARE] Failed to parse network JSON")
        
        # Python fallback
        if not network.primary_ip:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                network.primary_ip = s.getsockname()[0]
                s.close()
            except:
                network.primary_ip = "127.0.0.1"
        
        return network
    
    def _collect_security(self) -> SecurityInfo:
        """Collect security posture information"""
        security = SecurityInfo()
        
        # OS info (Python)
        security.os_name = platform.system()
        security.os_version = platform.version()
        security.os_build = platform.release()
        security.os_architecture = platform.machine()
        
        script = '''
        $ProgressPreference = 'SilentlyContinue'
        
        # Antivirus (Windows Security Center)
        $av = @()
        try {
            $avProducts = Get-WmiObject -Namespace "root\SecurityCenter2" -Class AntiVirusProduct -ErrorAction SilentlyContinue
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
        
        # Last boot time
        $os = Get-WmiObject Win32_OperatingSystem
        $lastBoot = $os.ConvertToDateTime($os.LastBootUpTime).ToString("o")
        
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
        $osEdition = $osCaption -replace 'Microsoft Windows \d+ ' -replace 'Microsoft Windows ', ''
        
        # Get SKU number for precise identification
        $osSku = $os.OperatingSystemSKU
        
        @{
            Antivirus = $av
            FirewallEnabled = $fwEnabled
            LastBootTime = $lastBoot
            WindowsUpdateEnabled = $wuEnabled
            BitLockerStatus = $bitlocker
            OSCaption = $osCaption
            OSVersion = $os.Version
            OSBuild = $os.BuildNumber
            OSEdition = $osEdition
            OSSKU = $osSku
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
                
                # Override with more accurate OS info from WMI
                if data.get('OSCaption'):
                    security.os_name = data['OSCaption']
                if data.get('OSVersion'):
                    security.os_version = data['OSVersion']
                if data.get('OSBuild'):
                    security.os_build = str(data['OSBuild'])
                
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
            'last_collection': self.last_collection_time.isoformat() if self.last_collection_time else None
        }
