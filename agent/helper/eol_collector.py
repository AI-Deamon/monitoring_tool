"""
EOL Data Collector Module
=========================
Collects End-of-Life specific data from Windows endpoints:
- Windows Update History (installed KBs, pending updates)
- ESU (Extended Security Updates) status
- Standardized identifiers (CPE 2.3, PURL, SWID tags)
- Software metering (usage frequency via Prefetch/MUI cache)
- Product key extraction (partial, last 5 chars only)
- Warranty expiry stub (serial + manufacturer for correlation)

This module extends the base hardware_collector and inventory modules
with EOL-specific intelligence that feeds the server's risk scoring engine.
"""
import subprocess
import json
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class WindowsUpdate:
    """Represents an installed Windows update (KB)"""
    kb_number: str
    title: str = ""
    update_type: str = "Unknown"    # Security, Critical, Feature, ServicePack
    install_date: Optional[str] = None
    result_code: int = 0            # 0=NotStarted, 1=InProgress, 2=Succeeded, 3=SucceededWithErrors, 4=Failed
    is_pending: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ESUInfo:
    """Extended Security Updates status for Windows 7/10/Server"""
    esu_eligible: bool = False
    esu_activated: bool = False
    esu_expiry_date: Optional[str] = None
    detection_method: str = "registry"  # 'registry', 'wmi', 'servicing'

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SoftwareIdentifier:
    """Standardized identifier for a software product"""
    app_name: str
    identifier_type: str    # 'cpe', 'purl', 'swid'
    identifier_value: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SoftwareMeteringEntry:
    """Usage frequency data for an application"""
    app_name: str
    executable_name: str
    usage_count: int = 0
    last_used: Optional[str] = None
    source: str = "prefetch"    # 'prefetch', 'mui_cache'

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ProductKeyInfo:
    """Partial product key for compliance tracking"""
    product_name: str
    partial_key: str = ""       # Last 5 characters only
    key_source: str = "Unknown"  # 'wmi', 'registry'
    license_status: str = "Unknown"

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class WarrantyInfo:
    """Warranty expiry stub — populated server-side or manually"""
    serial_number: str = ""
    manufacturer: str = ""
    model: str = ""
    warranty_expiry: Optional[str] = None
    warranty_source: str = "manual"  # 'manual', 'api', 'dell_api', 'hp_api'

    def to_dict(self) -> Dict:
        return asdict(self)


# =============================================================================
# EOL COLLECTOR
# =============================================================================

class EOLCollector:
    """
    Collects End-of-Life specific data from Windows endpoints.

    Each collector is independent and fails gracefully — a failure in
    one collector does not affect others. All PowerShell commands use
    the same security-hardened execution pattern as ExtendedInventoryCollector.
    """

    def __init__(self, config=None):
        self.config = config

    def _run_powershell(self, script: str, timeout: int = 120) -> Optional[str]:
        """Run PowerShell command and return output"""
        try:
            # Use CREATE_NO_WINDOW for robust background execution
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", script],
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
                logger.debug(f"[EOL] PowerShell execution failed (code {result.returncode}): {stderr_preview}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning(f"[EOL] PowerShell timeout ({timeout}s)")
            return None
        except Exception as e:
            logger.error(f"[EOL] PowerShell process creation failed: {e}")
            return None

    # =========================================================================
    # COLLECT ALL — Main orchestration method
    # =========================================================================

    def collect_all(self) -> Dict[str, Any]:
        """
        Collect all EOL-specific data. Each sub-collector runs independently.

        Returns:
            Dict with keys: updates, esu, identifiers, metering, product_keys, warranty
        """
        result = {}

        # 1. Windows Update History
        try:
            updates = self.collect_update_history()
            result['updates'] = [u.to_dict() for u in updates]
            logger.info(f"[EOL] Collected {len(updates)} Windows updates")
        except Exception as e:
            logger.error(f"[EOL] Update history collection failed: {e}")
            result['updates'] = []

        # 2. ESU Status
        try:
            esu = self.collect_esu_status()
            result['esu'] = esu.to_dict() if esu else None
            logger.info(f"[EOL] ESU status: eligible={esu.esu_eligible if esu else 'N/A'}")
        except Exception as e:
            logger.error(f"[EOL] ESU detection failed: {e}")
            result['esu'] = None

        # 3. Software Metering (lightweight)
        try:
            metering = self.collect_software_metering()
            result['metering'] = [m.to_dict() for m in metering]
            logger.info(f"[EOL] Collected metering for {len(metering)} apps")
        except Exception as e:
            logger.error(f"[EOL] Software metering failed: {e}")
            result['metering'] = []

        # 4. Product Keys (partial only)
        try:
            keys = self.collect_product_keys()
            result['product_keys'] = [k.to_dict() for k in keys]
            logger.info(f"[EOL] Collected {len(keys)} product keys (partial)")
        except Exception as e:
            logger.error(f"[EOL] Product key collection failed: {e}")
            result['product_keys'] = []

        # 5. Warranty Info (stub — just serial + manufacturer)
        try:
            warranty = self.collect_warranty_info()
            result['warranty'] = warranty.to_dict() if warranty else None
        except Exception as e:
            logger.error(f"[EOL] Warranty info collection failed: {e}")
            result['warranty'] = None

        result['collected_at'] = datetime.now(timezone.utc).isoformat()
        return result

    # =========================================================================
    # 1. WINDOWS UPDATE HISTORY
    # =========================================================================

    def collect_update_history(self) -> List[WindowsUpdate]:
        """
        Collect installed Windows updates and pending updates.
        Uses both Get-HotFix and COM Microsoft.Update.Session for coverage.
        """
        updates = []

        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $results = @()

        # Method 1: Get-HotFix (fast, limited info)
        try {
            Get-HotFix -ErrorAction SilentlyContinue | ForEach-Object {
                $results += @{
                    KBNumber = $_.HotFixID
                    Title = $_.Description
                    UpdateType = switch ($_.Description) {
                        'Security Update' { 'Security' }
                        'Update' { 'Critical' }
                        'Hotfix' { 'Hotfix' }
                        default { $_.Description }
                    }
                    InstallDate = if ($_.InstalledOn) { $_.InstalledOn.ToString('yyyy-MM-dd') } else { $null }
                    ResultCode = 2
                    IsPending = $false
                }
            }
        } catch {}

        # Method 2: COM Update Session (richer data, includes pending)
        try {
            $session = New-Object -ComObject Microsoft.Update.Session
            $searcher = $session.CreateUpdateSearcher()

            # Get installed updates (last 50)
            $historyCount = $searcher.GetTotalHistoryCount()
            $toFetch = [Math]::Min($historyCount, 50)
            if ($toFetch -gt 0) {
                $history = $searcher.QueryHistory(0, $toFetch)
                foreach ($entry in $history) {
                    $kb = ''
                    if ($entry.Title -match 'KB(\d+)') {
                        $kb = "KB$($Matches[1])"
                    }
                    if (-not $kb) { continue }

                    # Skip if already seen from Get-HotFix
                    if ($results | Where-Object { $_.KBNumber -eq $kb }) { continue }

                    $results += @{
                        KBNumber = $kb
                        Title = $entry.Title
                        UpdateType = switch ($entry.Categories.Item(0).Name) {
                            'Security Updates' { 'Security' }
                            'Critical Updates' { 'Critical' }
                            'Feature Packs' { 'Feature' }
                            'Service Packs' { 'ServicePack' }
                            default { 'Other' }
                        }
                        InstallDate = if ($entry.Date) { $entry.Date.ToString('yyyy-MM-dd') } else { $null }
                        ResultCode = $entry.ResultCode
                        IsPending = $false
                    }
                }
            }

            # Get pending updates
            try {
                $searchResult = $searcher.Search("IsInstalled=0 AND IsHidden=0")
                foreach ($update in $searchResult.Updates) {
                    $kb = ''
                    foreach ($kbId in $update.KBArticleIDs) {
                        $kb = "KB$kbId"
                        break
                    }
                    if (-not $kb -and $update.Title -match 'KB(\d+)') {
                        $kb = "KB$($Matches[1])"
                    }
                    if (-not $kb) { $kb = "PENDING-$($update.Identity.UpdateID.SubString(0,8))" }

                    $results += @{
                        KBNumber = $kb
                        Title = $update.Title
                        UpdateType = if ($update.MsrcSeverity) { $update.MsrcSeverity } else { 'Other' }
                        InstallDate = $null
                        ResultCode = 0
                        IsPending = $true
                    }
                }
            } catch {}
        } catch {}

        $results | ConvertTo-Json -Depth 3
        '''

        output = self._run_powershell(script, timeout=180)
        if output:
            try:
                data = json.loads(output)
                if not isinstance(data, list):
                    data = [data]

                for item in data:
                    update = WindowsUpdate(
                        kb_number=item.get('KBNumber', ''),
                        title=item.get('Title', ''),
                        update_type=item.get('UpdateType', 'Unknown'),
                        install_date=item.get('InstallDate'),
                        result_code=int(item.get('ResultCode', 0)),
                        is_pending=bool(item.get('IsPending', False))
                    )
                    if update.kb_number:
                        updates.append(update)

            except json.JSONDecodeError as e:
                logger.error(f"[EOL] Failed to parse update history JSON: {e}")

        return updates

    # =========================================================================
    # 2. ESU STATUS DETECTION
    # =========================================================================

    def collect_esu_status(self) -> Optional[ESUInfo]:
        """
        Detect Extended Security Updates (ESU) activation status.
        Checks registry CBS packages + WMI SoftwareLicensingProduct.
        """
        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $esu = @{
            Eligible = $false
            Activated = $false
            ExpiryDate = $null
            DetectionMethod = 'none'
        }

        # Check 1: CBS Packages for ESU markers
        try {
            $cbsPath = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\Packages'
            if (Test-Path $cbsPath) {
                $esuPackages = Get-ChildItem $cbsPath -ErrorAction SilentlyContinue |
                    Where-Object { $_.PSChildName -match 'ESU|Extended.Security' }
                if ($esuPackages) {
                    $esu['Eligible'] = $true
                    $esu['DetectionMethod'] = 'cbs_registry'

                    # Check if any ESU package is installed (state = 112 = Installed)
                    foreach ($pkg in $esuPackages) {
                        $props = Get-ItemProperty $pkg.PSPath -ErrorAction SilentlyContinue
                        if ($props.CurrentState -eq 112) {
                            $esu['Activated'] = $true
                            break
                        }
                    }
                }
            }
        } catch {}

        # Check 2: WMI SoftwareLicensingProduct for ESU add-ons
        try {
            $esuLicenses = Get-WmiObject SoftwareLicensingProduct -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match 'ESU|Extended.Security' -and $_.LicenseStatus -eq 1 }
            if ($esuLicenses) {
                $esu['Eligible'] = $true
                $esu['Activated'] = $true
                $esu['DetectionMethod'] = 'wmi_licensing'

                # Try to get expiry from grace period
                $firstLicense = $esuLicenses | Select-Object -First 1
                if ($firstLicense.GracePeriodRemaining -gt 0) {
                    $expiryDate = (Get-Date).AddMinutes($firstLicense.GracePeriodRemaining)
                    $esu['ExpiryDate'] = $expiryDate.ToString('yyyy-MM-dd')
                }
            }
        } catch {}

        # Check 3: OS version eligibility (Windows 10 < 22H2 or Windows 7/8.1)
        try {
            $os = Get-WmiObject Win32_OperatingSystem -ErrorAction SilentlyContinue
            if ($os) {
                $caption = $os.Caption
                $build = [int]($os.BuildNumber)

                # Windows 7 (6.1.7601) — ESU ended Jan 2023
                if ($caption -match 'Windows 7') {
                    $esu['Eligible'] = $true
                }
                # Windows 8.1 (6.3.9600) — ESU ended Jan 2023
                elseif ($caption -match 'Windows 8\.1') {
                    $esu['Eligible'] = $true
                }
                # Windows 10 versions approaching/past EOL
                elseif ($caption -match 'Windows 10' -and $build -lt 19045) {
                    $esu['Eligible'] = $true
                }
                # Windows Server 2012/2012 R2
                elseif ($caption -match 'Server 2012') {
                    $esu['Eligible'] = $true
                }

                if ($esu['DetectionMethod'] -eq 'none') {
                    $esu['DetectionMethod'] = 'os_version'
                }
            }
        } catch {}

        $esu | ConvertTo-Json -Depth 3
        '''

        output = self._run_powershell(script, timeout=60)
        if output:
            try:
                data = json.loads(output)
                return ESUInfo(
                    esu_eligible=bool(data.get('Eligible', False)),
                    esu_activated=bool(data.get('Activated', False)),
                    esu_expiry_date=data.get('ExpiryDate'),
                    detection_method=data.get('DetectionMethod', 'unknown')
                )
            except json.JSONDecodeError as e:
                logger.error(f"[EOL] Failed to parse ESU JSON: {e}")

        return ESUInfo()

    # =========================================================================
    # 3. STANDARDIZED IDENTIFIERS (CPE 2.3, PURL, SWID)
    # =========================================================================

    def generate_identifiers(self, apps: List[Dict]) -> List[SoftwareIdentifier]:
        """
        Generate standardized identifiers for a list of applications.
        Called server-side or agent-side with registry app data.

        Args:
            apps: List of dicts with 'name', 'version', 'publisher' keys

        Returns:
            List of SoftwareIdentifier objects (CPE + PURL per app)
        """
        identifiers = []

        for app in apps:
            name = app.get('name', '') or ''
            version = app.get('version', '') or ''
            publisher = app.get('publisher', '') or ''

            if not name:
                continue

            # Generate CPE 2.3
            cpe = self._generate_cpe(name, version, publisher)
            if cpe:
                identifiers.append(SoftwareIdentifier(
                    app_name=name,
                    identifier_type='cpe',
                    identifier_value=cpe
                ))

            # Generate PURL
            purl = self._generate_purl(name, version, publisher)
            if purl:
                identifiers.append(SoftwareIdentifier(
                    app_name=name,
                    identifier_type='purl',
                    identifier_value=purl
                ))

        return identifiers

    def collect_swid_tags(self) -> List[SoftwareIdentifier]:
        """
        Discover SWID (Software Identification) tags from standard locations.
        ISO/IEC 19770-2 compliant tags are XML files with .swidtag extension.
        """
        identifiers = []

        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $tags = @()

        $searchPaths = @(
            'C:\ProgramData',
            "$env:PROGRAMFILES",
            "${env:PROGRAMFILES(x86)}"
        )

        foreach ($basePath in $searchPaths) {
            if (Test-Path $basePath) {
                Get-ChildItem $basePath -Filter '*.swidtag' -Recurse -Depth 3 -ErrorAction SilentlyContinue |
                Select-Object -First 50 | ForEach-Object {
                    try {
                        [xml]$xml = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
                        $ns = $xml.DocumentElement.NamespaceURI

                        $name = $xml.DocumentElement.GetAttribute('name')
                        $version = $xml.DocumentElement.GetAttribute('version')
                        $tagId = $xml.DocumentElement.GetAttribute('tagId')

                        if ($name) {
                            $tags += @{
                                AppName = $name
                                Version = $version
                                TagId = $tagId
                                Path = $_.FullName
                            }
                        }
                    } catch {}
                }
            }
        }

        $tags | ConvertTo-Json -Depth 3
        '''

        output = self._run_powershell(script, timeout=90)
        if output:
            try:
                data = json.loads(output)
                if not isinstance(data, list):
                    data = [data]

                for item in data:
                    tag_id = item.get('TagId', '')
                    name = item.get('AppName', '')
                    if tag_id or name:
                        identifiers.append(SoftwareIdentifier(
                            app_name=name,
                            identifier_type='swid',
                            identifier_value=tag_id or f"swid:{name}"
                        ))

            except json.JSONDecodeError as e:
                logger.error(f"[EOL] Failed to parse SWID JSON: {e}")

        logger.info(f"[EOL] Discovered {len(identifiers)} SWID tags")
        return identifiers

    def _generate_cpe(self, name: str, version: str, publisher: str) -> str:
        """
        Generate CPE 2.3 formatted string.
        Format: cpe:2.3:a:<vendor>:<product>:<version>:*:*:*:*:*:*:*
        """
        vendor = self._normalize_for_cpe(publisher)
        product = self._normalize_for_cpe(name)
        ver = self._normalize_for_cpe(version) if version and version != 'Unknown' else '*'

        if not vendor or not product:
            return ''

        return f"cpe:2.3:a:{vendor}:{product}:{ver}:*:*:*:*:*:*:*"

    def _generate_purl(self, name: str, version: str, publisher: str) -> str:
        """
        Generate Package URL (PURL) identifier.
        Format: pkg:windows/<publisher>/<name>@<version>
        """
        pub = self._normalize_for_purl(publisher)
        prod = self._normalize_for_purl(name)
        ver = version if version and version != 'Unknown' else ''

        if not prod:
            return ''

        purl = f"pkg:windows/{pub}/{prod}" if pub else f"pkg:windows/{prod}"
        if ver:
            purl += f"@{ver}"
        return purl

    @staticmethod
    def _normalize_for_cpe(value: str) -> str:
        """Normalize a string for CPE format (lowercase, underscores, no special chars)"""
        if not value or value == 'Unknown':
            return ''
        normalized = value.lower().strip()
        # Remove common suffixes
        for suffix in ['corporation', 'inc.', 'inc', 'llc', 'ltd.', 'ltd', 'co.', 'gmbh']:
            normalized = normalized.replace(suffix, '')
        # Replace spaces and special chars with underscores
        normalized = re.sub(r'[^a-z0-9]', '_', normalized)
        # Collapse multiple underscores
        normalized = re.sub(r'_+', '_', normalized).strip('_')
        return normalized

    @staticmethod
    def _normalize_for_purl(value: str) -> str:
        """Normalize a string for PURL format (lowercase, hyphens)"""
        if not value or value == 'Unknown':
            return ''
        normalized = value.lower().strip()
        for suffix in ['corporation', 'inc.', 'inc', 'llc', 'ltd.', 'ltd']:
            normalized = normalized.replace(suffix, '')
        normalized = re.sub(r'[^a-z0-9]', '-', normalized)
        normalized = re.sub(r'-+', '-', normalized).strip('-')
        return normalized

    # =========================================================================
    # 4. SOFTWARE METERING
    # =========================================================================

    def collect_software_metering(self) -> List[SoftwareMeteringEntry]:
        """
        Collect software usage frequency from Prefetch files and MUI cache.
        Prefetch: Execution count + last run time.
        MUI Cache: Recently used applications.
        """
        metering = []

        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $entries = @()

        # Method 1: Prefetch files (requires admin, but works without if readable)
        $prefetchPath = "$env:SYSTEMROOT\Prefetch"
        if (Test-Path $prefetchPath) {
            try {
                Get-ChildItem $prefetchPath -Filter '*.pf' -ErrorAction SilentlyContinue |
                Select-Object -First 200 | ForEach-Object {
                    $fileName = $_.BaseName
                    # Prefetch format: APPNAME-HASH.pf
                    if ($fileName -match '^(.+)-[A-F0-9]{8}$') {
                        $appName = $Matches[1]
                        $entries += @{
                            AppName = $appName
                            ExecutableName = "$appName.exe"
                            UsageCount = 1
                            LastUsed = $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
                            Source = 'prefetch'
                        }
                    }
                }
            } catch {}
        }

        # Method 2: MUI Cache (user-level, no admin needed)
        try {
            $muiPath = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache'
            if (Test-Path $muiPath) {
                $muiProps = Get-ItemProperty $muiPath -ErrorAction SilentlyContinue
                if ($muiProps) {
                    $muiProps.PSObject.Properties | Where-Object {
                        $_.Name -match '\.exe\.' -and $_.Name -notmatch '^PS'
                    } | ForEach-Object {
                        if ($_.Name -match '([^\\]+\.exe)') {
                            $exeName = $Matches[1]
                            $appName = $exeName -replace '\.exe$', ''

                            # Skip if already in prefetch results
                            $existing = $entries | Where-Object { $_.ExecutableName -eq $exeName }
                            if (-not $existing) {
                                $entries += @{
                                    AppName = $appName
                                    ExecutableName = $exeName
                                    UsageCount = 1
                                    LastUsed = $null
                                    Source = 'mui_cache'
                                }
                            }
                        }
                    }
                }
            }
        } catch {}

        # Deduplicate by executable name
        $entries | Group-Object ExecutableName | ForEach-Object {
            $group = $_.Group
            $first = $group[0]
            $first['UsageCount'] = $group.Count
            $first
        } | ConvertTo-Json -Depth 3
        '''

        output = self._run_powershell(script, timeout=60)
        if output:
            try:
                data = json.loads(output)
                if not isinstance(data, list):
                    data = [data]

                for item in data:
                    entry = SoftwareMeteringEntry(
                        app_name=item.get('AppName', ''),
                        executable_name=item.get('ExecutableName', ''),
                        usage_count=int(item.get('UsageCount', 0)),
                        last_used=item.get('LastUsed'),
                        source=item.get('Source', 'prefetch')
                    )
                    if entry.app_name:
                        metering.append(entry)

            except json.JSONDecodeError as e:
                logger.error(f"[EOL] Failed to parse metering JSON: {e}")

        return metering

    # =========================================================================
    # 5. PRODUCT KEY EXTRACTION (PARTIAL)
    # =========================================================================

    def collect_product_keys(self) -> List[ProductKeyInfo]:
        """
        Extract PARTIAL product keys (last 5 characters only) for compliance.
        Never stores or transmits full product keys.
        """
        keys = []

        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $keys = @()

        # Windows Product Key (last 5 chars only)
        try {
            $slsvc = Get-WmiObject SoftwareLicensingService -ErrorAction SilentlyContinue
            if ($slsvc -and $slsvc.OA3xOriginalProductKey) {
                $fullKey = $slsvc.OA3xOriginalProductKey
                $partial = $fullKey.Substring($fullKey.Length - 5)
                $keys += @{
                    ProductName = 'Windows OS'
                    PartialKey = $partial
                    KeySource = 'wmi_sls'
                    LicenseStatus = 'OEM'
                }
            }
        } catch {}

        # Windows activation status
        try {
            $slp = Get-WmiObject SoftwareLicensingProduct -ErrorAction SilentlyContinue |
                Where-Object { $_.ApplicationId -eq '55c92734-d682-4d71-983e-d6ec3f16059f' -and $_.LicenseStatus -eq 1 }
            if ($slp) {
                $partial = if ($slp.PartialProductKey) { $slp.PartialProductKey } else { '' }
                # Only add if we didn't get it from SLS above
                $existing = $keys | Where-Object { $_.ProductName -eq 'Windows OS' }
                if (-not $existing) {
                    $keys += @{
                        ProductName = 'Windows OS'
                        PartialKey = $partial
                        KeySource = 'wmi_slp'
                        LicenseStatus = switch ($slp.LicenseStatus) {
                            0 { 'Unlicensed' }
                            1 { 'Licensed' }
                            2 { 'OOBGrace' }
                            3 { 'OOTGrace' }
                            4 { 'NonGenuineGrace' }
                            5 { 'Notification' }
                            6 { 'ExtendedGrace' }
                            default { 'Unknown' }
                        }
                    }
                }
            }
        } catch {}

        # Office Product Keys (partial, from registry)
        try {
            $officeVersions = @('16.0', '15.0', '14.0')
            foreach ($ver in $officeVersions) {
                $regPath = "HKLM:\SOFTWARE\Microsoft\Office\$ver\Registration"
                if (Test-Path $regPath) {
                    Get-ChildItem $regPath -ErrorAction SilentlyContinue | ForEach-Object {
                        $props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
                        if ($props.DigitalProductID -or $props.ProductName) {
                            $productName = if ($props.ProductName) { $props.ProductName } else { "Microsoft Office $ver" }
                            # Try to get partial key
                            $partial = ''
                            if ($props.PartialProductKey) {
                                $partial = $props.PartialProductKey
                            }
                            $keys += @{
                                ProductName = $productName
                                PartialKey = $partial
                                KeySource = 'registry'
                                LicenseStatus = 'Detected'
                            }
                        }
                    }
                }
            }
        } catch {}

        $keys | ConvertTo-Json -Depth 3
        '''

        output = self._run_powershell(script, timeout=60)
        if output:
            try:
                data = json.loads(output)
                if not isinstance(data, list):
                    data = [data]

                for item in data:
                    partial = str(item.get('PartialKey', ''))
                    # Safety: truncate to max 5 chars
                    if len(partial) > 5:
                        partial = partial[-5:]

                    key = ProductKeyInfo(
                        product_name=item.get('ProductName', 'Unknown'),
                        partial_key=partial,
                        key_source=item.get('KeySource', 'Unknown'),
                        license_status=item.get('LicenseStatus', 'Unknown')
                    )
                    keys.append(key)

            except json.JSONDecodeError as e:
                logger.error(f"[EOL] Failed to parse product keys JSON: {e}")

        return keys

    # =========================================================================
    # 6. WARRANTY INFO (STUB)
    # =========================================================================

    def collect_warranty_info(self) -> Optional[WarrantyInfo]:
        """
        Collect hardware identity for warranty correlation.
        Actual warranty lookup happens server-side or via manual import.
        This only provides the serial + manufacturer for correlation.
        """
        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        try {
            $bios = Get-WmiObject Win32_BIOS -ErrorAction SilentlyContinue
            $cs = Get-WmiObject Win32_ComputerSystem -ErrorAction SilentlyContinue

            @{
                SerialNumber = if ($bios.SerialNumber) { $bios.SerialNumber.Trim() } else { '' }
                Manufacturer = if ($cs.Manufacturer) { $cs.Manufacturer.Trim() } else { '' }
                Model = if ($cs.Model) { $cs.Model.Trim() } else { '' }
            } | ConvertTo-Json
        } catch {
            '{}' | Write-Output
        }
        '''

        output = self._run_powershell(script, timeout=30)
        if output:
            try:
                data = json.loads(output)
                return WarrantyInfo(
                    serial_number=data.get('SerialNumber', ''),
                    manufacturer=data.get('Manufacturer', ''),
                    model=data.get('Model', ''),
                    warranty_source='agent_collected'
                )
            except json.JSONDecodeError as e:
                logger.error(f"[EOL] Failed to parse warranty JSON: {e}")

        return WarrantyInfo()
