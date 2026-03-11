"""
Extended Inventory Collector Module
====================================
Collects comprehensive inventory including:
- CLI tools (opencode, claude code, etc.)
- Hardware drivers
- VS Code extensions
- Browser extensions (Chrome, Firefox, Edge)
- Application plugins
- Portable applications
- Full disk scan

This module extends the base inventory.py functionality.
"""
import subprocess
import json
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from pathlib import Path
from dataclasses import dataclass, asdict, field
import time

logger = logging.getLogger(__name__)


# =============================================================================
# DATACLASSES FOR EXTENDED INVENTORY
# =============================================================================

@dataclass
class CLITool:
    """Represents a command-line tool"""
    name: str
    version: str = "Unknown"
    publisher: str = "Unknown"
    executable_path: Optional[str] = None     # was install_path
    source: str = "Unknown"                   # was detected_via — 'path', 'registry', 'known_location'
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class HardwareDriver:
    """Represents a hardware driver"""
    device_name: Optional[str] = None          # was name
    driver_name: Optional[str] = None          # NEW — driver file name
    driver_version: str = "Unknown"            # was version
    driver_date: Optional[str] = None
    manufacturer: str = "Unknown"              # was publisher
    device_class: str = "Unknown"              # was driver_type
    device_id: Optional[str] = None
    is_signed: bool = False                    # was digital_signed
    signer: Optional[str] = None               # NEW — code signer
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class VSCodeExtension:
    """Represents a VS Code extension"""
    extension_id: str
    display_name: str = "Unknown"              # was name
    publisher: str = "Unknown"
    version: str = "Unknown"
    install_path: Optional[str] = None         # was installed_path
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BrowserExtension:
    """Represents a browser extension"""
    browser: str  # Chrome, Firefox, Edge, Opera, Brave
    extension_id: str
    name: str = "Unknown"
    version: str = "Unknown"
    description: Optional[str] = None
    enabled: bool = True
    install_date: Optional[str] = None
    profile_path: Optional[str] = None
    profile: Optional[str] = None  # Profile name (Default, Profile 1, etc.)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ApplicationPlugin:
    """Represents an application plugin"""
    plugin_type: str = "Unknown"               # was positional — 'office_addin', 'adobe_plugin', etc.
    name: str = "Unknown"                      # was plugin_name
    version: str = "Unknown"
    publisher: str = "Unknown"
    install_path: Optional[str] = None
    host_application: Optional[str] = None     # was positional
    enabled: bool = True
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PortableApplication:
    """Represents a portable application"""
    name: str
    version: str = "Unknown"
    publisher: str = "Unknown"
    executable_path: str = ""
    install_directory: Optional[str] = None    # was detected_path
    detection_method: str = "disk_scan"        # NEW — 'disk_scan', 'known_pattern'
    file_size_bytes: int = 0                   # was file_size_kb (now bytes)
    
    def to_dict(self) -> Dict:
        return asdict(self)


# =============================================================================
# EXTENDED INVENTORY COLLECTOR
# =============================================================================

class ExtendedInventoryCollector:
    """
    Collects extended inventory including CLI tools, drivers, extensions, etc.
    """
    
    # Known CLI tools to look for
    KNOWN_CLI_TOOLS = [
        'opencode', 'claude', 'cursor', 'aider', 'continue',
        'gh', 'git', 'docker', 'kubectl', 'terraform', 'ansible',
        'python', 'pip', 'node', 'npm', 'yarn', 'pnpm',
        'go', 'rustc', 'cargo', 'dotnet',
        'az', 'aws', 'gcloud',
        'code', 'code-insiders',
        'winget', 'choco', 'scoop',
        'npm', 'npx', 'yarn', 'pnpm',
        'pip', 'pip3', 'poetry', 'pipenv',
        'mvn', 'gradle',
        'ruby', 'gem', 'bundler',
    ]
    
    # Common portable app locations (legacy reference only).
    # Actual scanning is built dynamically from all fixed drives.
    PORTABLE_APP_PATHS = [
        'C:\\Portable Apps',
        'C:\\Tools',
        'C:\\Programs',
    ]
    
    def __init__(self, config=None):
        self.config = config
        self._ps_script_dir = self._get_script_dir()
        
    def _get_script_dir(self) -> Path:
        """Get directory for PowerShell scripts"""
        if self.config and hasattr(self.config, 'state_dir'):
            return Path(self.config.state_dir)
        return Path.home() / ".sentineledge"
    
    def _run_powershell(self, script: str, timeout: int = 120) -> Optional[str]:
        """Run PowerShell command and return output"""
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
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.debug(f"[EXTENDED] PowerShell error: {result.stderr[:200]}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning(f"[EXTENDED] PowerShell timeout ({timeout}s)")
            return None
        except Exception as e:
            logger.error(f"[EXTENDED] PowerShell error: {e}")
            return None
    
    # =========================================================================
    # CLI TOOLS COLLECTION
    # =========================================================================
    
    def collect_cli_tools(self) -> List[CLITool]:
        """Collect command-line tools from PATH, registry, and known locations"""
        tools = []
        
        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $tools = @()
        
        # Helper: Get version info for executables, safe for .cmd/.bat
        function Get-ToolInfo {
            param($FilePath, $DetectedVia)
            $ext = [System.IO.Path]::GetExtension($FilePath).ToLower()
            $baseName = [System.IO.Path]::GetFileNameWithoutExtension($FilePath)
            $version = 'Unknown'
            $publisher = 'Unknown'
            
            if ($ext -eq '.exe') {
                try {
                    $vi = (Get-Item $FilePath -ErrorAction SilentlyContinue).VersionInfo
                    if ($vi.FileVersion) { $version = $vi.FileVersion }
                    if ($vi.CompanyName) { $publisher = $vi.CompanyName }
                } catch {}
            } elseif ($ext -in @('.cmd', '.bat', '.ps1')) {
                # For script wrappers, try to get version via --version
                try {
                    $verOutput = & $FilePath --version 2>&1 | Select-Object -First 1
                    if ($verOutput -match '(\d+\.\d+[\d.]*)') {
                        $version = $Matches[1]
                    }
                } catch {}
            }
            
            return @{
                Name = $baseName
                Version = $version
                Publisher = $publisher
                Path = $FilePath
                DetectedVia = $DetectedVia
            }
        }
        
        # Scannable file extensions
        $scanExts = @('*.exe', '*.cmd', '*.bat')
        
        # Method 1: Scan PATH directories
        $env:PATH -split ';' | Where-Object { $_ -and (Test-Path $_.Trim('"')) } | ForEach-Object {
            $dir = $_.Trim('"')
            try {
                foreach ($ext in $scanExts) {
                    Get-ChildItem $dir -Filter $ext -ErrorAction SilentlyContinue | ForEach-Object {
                        $tools += Get-ToolInfo -FilePath $_.FullName -DetectedVia 'PATH'
                    }
                }
            } catch {}
        }
        
        # Method 2: Known CLI tool locations (expanded)
        $knownPaths = @(
            "$env:LOCALAPPDATA\Programs",
            "$env:LOCALAPPDATA\Microsoft\WindowsApps",
            "$env:APPDATA\npm",
            "$env:APPDATA\npm\node_modules\.bin",
            "$env:USERPROFILE\.local\bin",
            "$env:USERPROFILE\scoop\shims",
            "$env:USERPROFILE\AppData\Local\Programs",
            "$env:USERPROFILE\.cursor\bin",
            "$env:LOCALAPPDATA\Programs\cursor",
            "$env:USERPROFILE\.claude",
            "$env:USERPROFILE\.cargo\bin",
            "$env:USERPROFILE\go\bin",
            "$env:USERPROFILE\.deno\bin",
            "$env:USERPROFILE\.bun\bin",
            "$env:APPDATA\.gh\extensions",
            "$env:LOCALAPPDATA\Programs\Windsurf",
            "$env:LOCALAPPDATA\pipx\venvs",
            "C:\Program Files\GitHub CLI",
            "C:\Program Files\Docker\Docker\resources\bin",
            "C:\Program Files\Microsoft VS Code\bin",
            "C:\Program Files\Kubernetes\Minikube",
            "C:\Program Files\Terraform",
            "C:\ProgramData\chocolatey\bin"
        )
        
        foreach ($basePath in $knownPaths) {
            if (Test-Path $basePath) {
                foreach ($ext in $scanExts) {
                    Get-ChildItem $basePath -Filter $ext -Recurse -Depth 2 -ErrorAction SilentlyContinue | ForEach-Object {
                        $tools += Get-ToolInfo -FilePath $_.FullName -DetectedVia 'KnownLocation'
                    }
                }
            }
        }
        
        # Method 3: Registry App Paths
        @('HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths', 
          'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths') | ForEach-Object {
            if (Test-Path $_) {
                Get-ChildItem $_ -ErrorAction SilentlyContinue | ForEach-Object {
                    $exePath = (Get-ItemProperty $_.PSPath).'(default)'
                    if ($exePath -and (Test-Path $exePath)) {
                        $tools += Get-ToolInfo -FilePath $exePath -DetectedVia 'Registry'
                    }
                }
            }
        }
        
        # Method 4: Get-Command fallback for well-known tools
        $knownToolNames = @(
            'opencode', 'claude', 'aider', 'copilot',
            'docker', 'kubectl', 'terraform', 'ansible',
            'gh', 'az', 'aws', 'gcloud',
            'go', 'rustc', 'cargo', 'deno', 'bun',
            'winget', 'choco', 'scoop'
        )
        $existingNames = $tools | ForEach-Object { $_.Name.ToLower() }
        foreach ($toolName in $knownToolNames) {
            if ($toolName -notin $existingNames) {
                try {
                    $cmd = Get-Command $toolName -ErrorAction SilentlyContinue
                    if ($cmd -and $cmd.Source) {
                        $tools += Get-ToolInfo -FilePath $cmd.Source -DetectedVia 'GetCommand'
                    }
                } catch {}
            }
        }
        
        # Deduplicate by name (case-insensitive)
        $tools | Group-Object { $_.Name.ToLower() } | ForEach-Object { $_.Group[0] } | ConvertTo-Json -Depth 3
        '''
        
        output = self._run_powershell(script, timeout=180)
        if output:
            try:
                data = json.loads(output)
                if not isinstance(data, list):
                    data = [data]
                
                for item in data:
                    tool = CLITool(
                        name=item.get('Name', 'Unknown'),
                        version=item.get('Version', 'Unknown'),
                        publisher=item.get('Publisher', 'Unknown'),
                        executable_path=item.get('Path'),
                        source=item.get('DetectedVia', 'Unknown')
                    )
                    tools.append(tool)
                    
            except json.JSONDecodeError as e:
                logger.error(f"[EXTENDED] Failed to parse CLI tools JSON: {e}")
        
        logger.info(f"[EXTENDED] Collected {len(tools)} CLI tools")
        return tools
    
    # =========================================================================
    # HARDWARE DRIVERS COLLECTION
    # =========================================================================
    
    def collect_hardware_drivers(self) -> List[HardwareDriver]:
        """Collect hardware drivers from WMI"""
        drivers = []
        
        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $drivers = @()
        
        # Get signed drivers from WMI
        Get-WmiObject Win32_PnPSignedDriver -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.DeviceName) {
                # Parse WMI datetime format safely
                $driverDate = $null
                if ($_.DriverDate) {
                    try {
                        $driverDate = [Management.ManagementDateTimeConverter]::ToDateTime($_.DriverDate).ToString('yyyy-MM-dd')
                    } catch { $driverDate = $null }
                }
                
                $drivers += @{
                    Name = $_.DeviceName
                    DriverName = $_.FriendlyName
                    Version = $_.DriverVersion
                    Manufacturer = if ($_.Manufacturer) { $_.Manufacturer } else { 'Unknown' }
                    Signer = $_.Signer
                    DriverDate = $driverDate
                    DriverType = if ($_.DeviceClass) { $_.DeviceClass } else { 'Unknown' }
                    DeviceName = $_.DeviceName
                    DeviceID = $_.DeviceID
                    DigitalSigned = [bool]$_.IsSigned
                }
            }
        }
        
        # Get system drivers (kernel, filesystem)
        Get-WmiObject Win32_SystemDriver -ErrorAction SilentlyContinue | Where-Object { 
            $_.ServiceType -match 'KernelDriver|FileSystemDriver' 
        } | ForEach-Object {
            $drivers += @{
                Name = $_.DisplayName
                DriverName = $_.Name
                Version = 'Unknown'
                Manufacturer = 'Microsoft'
                Signer = 'Microsoft Windows'
                DriverDate = $null
                DriverType = $_.ServiceType
                DeviceName = $_.Name
                DeviceID = $null
                DigitalSigned = $true
            }
        }
        
        # Deduplicate by DeviceID or Name
        $drivers | Group-Object { if ($_.DeviceID) { $_.DeviceID } else { $_.Name } } | ForEach-Object { $_.Group[0] } | ConvertTo-Json -Depth 3
        '''
        
        output = self._run_powershell(script, timeout=120)
        if output:
            try:
                data = json.loads(output)
                if not isinstance(data, list):
                    data = [data]
                
                for item in data:
                    driver = HardwareDriver(
                        device_name=item.get('DeviceName') or item.get('Name', 'Unknown'),
                        driver_name=item.get('DriverName') or item.get('Name'),
                        driver_version=item.get('Version', 'Unknown'),
                        driver_date=item.get('DriverDate'),
                        manufacturer=item.get('Manufacturer') or item.get('Signer', 'Unknown'),
                        device_class=item.get('DriverType', 'Unknown'),
                        device_id=item.get('DeviceID'),
                        is_signed=item.get('DigitalSigned', False),
                        signer=item.get('Signer', '')
                    )
                    drivers.append(driver)
                    
            except json.JSONDecodeError as e:
                logger.error(f"[EXTENDED] Failed to parse drivers JSON: {e}")
        
        logger.info(f"[EXTENDED] Collected {len(drivers)} hardware drivers")
        return drivers
    
    # =========================================================================
    # VS CODE EXTENSIONS COLLECTION
    # =========================================================================
    
    def collect_vscode_extensions(self) -> List[VSCodeExtension]:
        """Collect VS Code and VS Code Insiders extensions"""
        extensions = []
        
        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $extensions = @()
        
        # VS Code extension paths
        $extensionPaths = @{
            'stable' = "$env:USERPROFILE\.vscode\extensions"
            'insiders' = "$env:USERPROFILE\.vscode-insiders\extensions"
        }
        
        foreach ($type in $extensionPaths.Keys) {
            $path = $extensionPaths[$type]
            if (Test-Path $path) {
                Get-ChildItem $path -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                    $packageJson = Join-Path $_.FullName 'package.json'
                    if (Test-Path $packageJson) {
                        try {
                            $pkg = Get-Content $packageJson -Raw | ConvertFrom-Json
                            
                            # Parse extension ID from folder name (publisher.extension-version)
                            $folderName = $_.Name
                            $parts = $folderName -split '-'
                            $publisher = $parts[0]
                            $extName = $parts[1]
                            
                            $extensions += @{
                                ExtensionID = "$publisher.$extName"
                                Name = $pkg.displayName
                                Publisher = $pkg.publisher
                                Version = $pkg.version
                                Description = $pkg.description
                                Path = $_.FullName
                                InstallDate = $_.CreationTime.ToString('yyyy-MM-dd')
                                VSCodeType = $type
                            }
                        } catch {}
                    }
                }
            }
        }
        
        $extensions | ConvertTo-Json -Depth 3
        '''
        
        output = self._run_powershell(script, timeout=60)
        if output:
            try:
                # BUG-004 FIX: Validate output before parsing
                cleaned = output.strip()
                if not cleaned or cleaned in ('null', 'None', ''):
                    logger.debug("[EXTENDED] VS Code extensions returned empty output")
                    return extensions
                
                data = json.loads(cleaned)
                if not isinstance(data, list):
                    data = [data] if data else []
                
                for item in data:
                    ext = VSCodeExtension(
                        extension_id=item.get('ExtensionID', 'Unknown'),
                        display_name=item.get('Name', 'Unknown'),
                        publisher=item.get('Publisher', 'Unknown'),
                        version=item.get('Version', 'Unknown'),
                        install_path=item.get('Path')
                    )
                    extensions.append(ext)
                    
            except json.JSONDecodeError as e:
                logger.warning(f"[EXTENDED] Failed to parse VS Code extensions JSON: {e}")
        
        logger.info(f"[EXTENDED] Collected {len(extensions)} VS Code extensions")
        return extensions
    
    # =========================================================================
    # BROWSER EXTENSIONS COLLECTION
    # =========================================================================
    
    def collect_browser_extensions(self) -> List[BrowserExtension]:
        """
        Collect browser extensions from Chrome, Edge, Firefox, Opera, and Brave.
        
        Extracts: extension ID, name, version, enabled status, description
        Supports: multiple profiles per browser
        """
        extensions = []
        
        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $extensions = @()
        
        # Helper: Parse Chromium-based browser extensions with multi-profile support
        function Get-ChromiumExtensions {
            param($BrowserName, $UserDataPath)
            
            if (-not (Test-Path $UserDataPath)) { return }
            
            # Get all profiles
            $profiles = @('Default')
            $localState = Join-Path $UserDataPath 'Local State'
            if (Test-Path $localState) {
                try {
                    $ls = Get-Content $localState -Raw | ConvertFrom-Json
                    if ($ls.profile.info_cache) {
                        $profiles = @($ls.profile.info_cache.PSObject.Properties.Name) + 'Default'
                    }
                } catch {}
            }
            
            foreach ($profile in ($profiles | Select-Object -Unique)) {
                $profilePath = Join-Path $UserDataPath $profile
                $extPath = Join-Path $profilePath 'Extensions'
                $prefsPath = Join-Path $profilePath 'Preferences'
                
                # Read enabled extensions from Preferences
                $enabledExtensions = @{}
                if (Test-Path $prefsPath) {
                    try {
                        $prefs = Get-Content $prefsPath -Raw | ConvertFrom-Json
                        if ($prefs.extensions.settings) {
                            $prefs.extensions.settings.PSObject.Properties | ForEach-Object {
                                $extId = $_.Name
                                $extInfo = $_.Value
                                $enabledExtensions[$extId] = @{
                                    Enabled = -not $extInfo.disabled
                                    Name = $extInfo.manifest.name
                                }
                            }
                        }
                    } catch {}
                }
                
                # Scan extension directories
                if (Test-Path $extPath) {
                    Get-ChildItem $extPath -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                        $extId = $_.Name
                        $latestVersion = Get-ChildItem $_.FullName -Directory | 
                                         Sort-Object {[version]$_.Name} -Descending -ErrorAction SilentlyContinue | 
                                         Select-Object -First 1
                        
                        if ($latestVersion) {
                            $manifest = Join-Path $latestVersion.FullName 'manifest.json'
                            if (Test-Path $manifest) {
                                try {
                                    $m = Get-Content $manifest -Raw | ConvertFrom-Json
                                    
                                    # Get name (handle localized names like __MSG_appName__)
                                    $name = $m.name
                                    if ($name -and $name.StartsWith('__MSG_')) {
                                        if ($enabledExtensions[$extId].Name) {
                                            $name = $enabledExtensions[$extId].Name
                                        } else {
                                            $name = $extId
                                        }
                                    }
                                    
                                    # Determine enabled status
                                    $isEnabled = $true
                                    if ($enabledExtensions.ContainsKey($extId)) {
                                        $isEnabled = $enabledExtensions[$extId].Enabled
                                    }
                                    
                                    $script:extensions += @{
                                        Browser = $BrowserName
                                        ExtensionID = $extId
                                        Name = $name
                                        Version = $m.version
                                        Publisher = $m.author
                                        Description = $m.description
                                        Path = $latestVersion.FullName
                                        Profile = $profile
                                        Enabled = $isEnabled
                                    }
                                } catch {}
                            }
                        }
                    }
                }
            }
        }
        
        # Chrome
        Get-ChromiumExtensions -BrowserName 'Chrome' -UserDataPath "$env:LOCALAPPDATA\Google\Chrome\User Data"
        
        # Edge
        Get-ChromiumExtensions -BrowserName 'Edge' -UserDataPath "$env:LOCALAPPDATA\Microsoft\Edge\User Data"
        
        # Brave
        Get-ChromiumExtensions -BrowserName 'Brave' -UserDataPath "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\User Data"
        
        # Opera (Stable, GX, Developer)
        @('Opera Software\Opera Stable', 'Opera Software\Opera GX Stable', 'Opera Software\Opera Developer') | ForEach-Object {
            $operaPath = Join-Path $env:APPDATA $_
            if (Test-Path $operaPath) {
                $browserName = if ($_ -match 'GX') { 'Opera GX' } elseif ($_ -match 'Developer') { 'Opera Developer' } else { 'Opera' }
                Get-ChromiumExtensions -BrowserName $browserName -UserDataPath $operaPath
            }
        }
        
        # Firefox Extensions (parse extensions.json + XPI manifests)
        $firefoxProfiles = "$env:APPDATA\Mozilla\Firefox\Profiles"
        if (Test-Path $firefoxProfiles) {
            Get-ChildItem $firefoxProfiles -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $profile = $_.Name
                $extPath = Join-Path $_.FullName 'extensions'
                
                # Primary: Read extensions.json for full metadata
                $extJson = Join-Path $_.FullName 'extensions.json'
                if (Test-Path $extJson) {
                    try {
                        $extData = Get-Content $extJson -Raw | ConvertFrom-Json
                        $extData.addons | Where-Object { $_.type -eq 'extension' } | ForEach-Object {
                            $extensions += @{
                                Browser = 'Firefox'
                                ExtensionID = $_.id
                                Name = if ($_.defaultLocale.name) { $_.defaultLocale.name } else { $_.id }
                                Version = $_.version
                                Publisher = $_.defaultLocale.creator
                                Description = $_.defaultLocale.description
                                Path = $_.path
                                Profile = $profile
                                Enabled = $_.active
                            }
                        }
                    } catch {}
                }
                
                # Fallback: scan XPI files
                if (Test-Path $extPath) {
                    $existingIds = $extensions | Where-Object { $_.Browser -eq 'Firefox' } | ForEach-Object { $_.ExtensionID }
                    Get-ChildItem $extPath -Filter '*.xpi' -ErrorAction SilentlyContinue | ForEach-Object {
                        $extId = $_.BaseName
                        if ($extId -notin $existingIds) {
                            try {
                                Add-Type -AssemblyName System.IO.Compression.FileSystem
                                $zip = [System.IO.Compression.ZipFile]::OpenRead($_.FullName)
                                $manifestEntry = $zip.Entries | Where-Object { $_.Name -eq 'manifest.json' }
                                if ($manifestEntry) {
                                    $stream = $manifestEntry.Open()
                                    $reader = New-Object System.IO.StreamReader($stream)
                                    $manifest = $reader.ReadToEnd() | ConvertFrom-Json
                                    $reader.Close()
                                    $zip.Dispose()
                                    
                                    $extensions += @{
                                        Browser = 'Firefox'
                                        ExtensionID = $extId
                                        Name = $manifest.name
                                        Version = $manifest.version
                                        Publisher = $manifest.author
                                        Description = $manifest.description
                                        Path = $_.FullName
                                        Profile = $profile
                                        Enabled = $true
                                    }
                                } else {
                                    $zip.Dispose()
                                }
                            } catch {
                                $extensions += @{
                                    Browser = 'Firefox'
                                    ExtensionID = $extId
                                    Name = $extId
                                    Version = 'Unknown'
                                    Publisher = 'Unknown'
                                    Description = $null
                                    Path = $_.FullName
                                    Profile = $profile
                                    Enabled = $true
                                }
                            }
                        }
                    }
                }
            }
        }
        
        # Deduplicate by Browser+ExtensionID+Profile
        $extensions | Group-Object { "$($_.Browser)-$($_.ExtensionID)-$($_.Profile)" } | ForEach-Object { $_.Group[0] } | ConvertTo-Json -Depth 3
        '''
        
        output = self._run_powershell(script, timeout=180)
        if output:
            try:
                data = json.loads(output)
                if not isinstance(data, list):
                    data = [data]
                
                for item in data:
                    ext = BrowserExtension(
                        browser=item.get('Browser', 'Unknown'),
                        extension_id=item.get('ExtensionID', 'Unknown'),
                        name=item.get('Name', 'Unknown'),
                        version=item.get('Version', 'Unknown'),
                        description=item.get('Description'),
                        enabled=item.get('Enabled', True),
                        profile_path=item.get('Path'),
                        profile=item.get('Profile')
                    )
                    extensions.append(ext)
                    
            except json.JSONDecodeError as e:
                logger.error(f"[EXTENDED] Failed to parse browser extensions JSON: {e}")
        
        # Log summary by browser
        by_browser = {}
        for ext in extensions:
            by_browser[ext.browser] = by_browser.get(ext.browser, 0) + 1
        logger.info(f"[EXTENDED] Collected {len(extensions)} browser extensions: {by_browser}")
        
        return extensions
    
    # =========================================================================
    # APPLICATION PLUGINS COLLECTION
    # =========================================================================
    
    def collect_application_plugins(self) -> List[ApplicationPlugin]:
        """Collect application plugins (Office add-ins, Adobe plugins, etc.)"""
        plugins = []
        
        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $plugins = @()
        
        # Office Add-ins from Registry
        $officeApps = @('Word', 'Excel', 'Outlook', 'PowerPoint', 'Access')
        foreach ($app in $officeApps) {
            $regPath = "HKCU:\Software\Microsoft\Office\$app\Addins"
            if (Test-Path $regPath) {
                Get-ChildItem $regPath -ErrorAction SilentlyContinue | ForEach-Object {
                    $props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
                    $plugins += @{
                        HostApplication = "Microsoft $app"
                        PluginName = $_.PSChildName
                        PluginID = $_.PSChildName
                        Version = $props.Version
                        Publisher = 'Unknown'
                        Path = $props.Path
                        PluginType = 'OfficeAddin'
                        Enabled = $props.LoadBehavior -eq 3
                    }
                }
            }
        }
        
        # Adobe Plugins
        $adobePaths = @(
            "$env:PROGRAMFILES\Adobe\Acrobat*\Acrobat\plug_ins",
            "$env:PROGRAMFILES(x86)\Adobe\Acrobat*\Acrobat\plug_ins"
        )
        foreach ($path in $adobePaths) {
            if (Test-Path $path) {
                Get-ChildItem $path -Filter '*.api' -ErrorAction SilentlyContinue | ForEach-Object {
                    $versionInfo = (Get-Item $_.FullName).VersionInfo
                    $plugins += @{
                        HostApplication = 'Adobe Acrobat'
                        PluginName = $_.BaseName
                        PluginID = $_.Name
                        Version = $versionInfo.FileVersion
                        Publisher = $versionInfo.CompanyName
                        Path = $_.FullName
                        PluginType = 'AdobePlugin'
                        Enabled = $true
                    }
                }
            }
        }
        
        # Visual Studio Extensions (VSIX)
        $vsixPath = "$env:USERPROFILE\.vs\extensions"
        if (Test-Path $vsixPath) {
            Get-ChildItem $vsixPath -Directory -Recurse -Depth 2 -ErrorAction SilentlyContinue | Where-Object {
                Test-Path (Join-Path $_.FullName 'extension.vsixmanifest')
            } | ForEach-Object {
                $plugins += @{
                    HostApplication = 'Visual Studio'
                    PluginName = $_.Name
                    PluginID = $_.Name
                    Version = 'Unknown'
                    Publisher = 'Unknown'
                    Path = $_.FullName
                    PluginType = 'VSExtension'
                    Enabled = $true
                }
            }
        }
        
        $plugins | ConvertTo-Json -Depth 3
        '''
        
        output = self._run_powershell(script, timeout=90)
        if output:
            try:
                data = json.loads(output)
                if not isinstance(data, list):
                    data = [data]
                
                for item in data:
                    plugin = ApplicationPlugin(
                        plugin_type=item.get('PluginType', 'Unknown'),
                        name=item.get('PluginName', 'Unknown'),
                        version=item.get('Version', 'Unknown'),
                        publisher=item.get('Publisher', 'Unknown'),
                        install_path=item.get('Path'),
                        host_application=item.get('HostApplication'),
                        enabled=item.get('Enabled', True)
                    )
                    plugins.append(plugin)
                    
            except json.JSONDecodeError as e:
                logger.error(f"[EXTENDED] Failed to parse plugins JSON: {e}")
        
        logger.info(f"[EXTENDED] Collected {len(plugins)} application plugins")
        return plugins
    
    # =========================================================================
    # PORTABLE APPLICATIONS COLLECTION
    # =========================================================================
    
    def collect_portable_applications(self) -> List[PortableApplication]:
        """Collect portable applications from all fixed drives."""
        apps = []
        
        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $apps = @()
        
        # Build portable app scan paths from all fixed drives
        $scanPaths = @()
        try {
            $fixedDrives = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty DeviceID
            foreach ($drive in $fixedDrives) {
                $scanPaths += @(
                    "$drive\Portable Apps",
                    "$drive\Tools",
                    "$drive\Programs"
                )
            }
        } catch {}
        $scanPaths += @(
            "$env:USERPROFILE\PortableApps",
            "$env:USERPROFILE\Tools",
            "$env:USERPROFILE\Desktop\Tools"
        )
        
        # Exclude directories
        $excludeDirs = @('Windows', 'Program Files', 'Program Files (x86)', 'ProgramData', '$Recycle.Bin')
        
        foreach ($basePath in $scanPaths) {
            if (Test-Path $basePath) {
                Get-ChildItem $basePath -Recurse -Filter '*.exe' -Depth 3 -ErrorAction SilentlyContinue | 
                Where-Object { 
                    $dir = $_.Directory.Name
                    -not ($excludeDirs | Where-Object { $dir -like $_ })
                } | ForEach-Object {
                    $versionInfo = (Get-Item $_.FullName).VersionInfo
                    if ($versionInfo.FileDescription) {
                        $apps += @{
                            Name = $versionInfo.FileDescription
                            Version = $versionInfo.FileVersion
                            Publisher = $versionInfo.CompanyName
                            ExecutablePath = $_.FullName
                            DetectedPath = $_.Directory.FullName
                            FileSizeKB = [math]::Round($_.Length / 1KB, 2)
                            FileVersion = $versionInfo.FileVersion
                            ProductVersion = $versionInfo.ProductVersion
                        }
                    }
                }
            }
        }
        
        # Deduplicate by executable path
        $apps | Group-Object ExecutablePath | ForEach-Object { $_.Group[0] } | ConvertTo-Json -Depth 3
        '''
        
        output = self._run_powershell(script, timeout=180)
        if output:
            try:
                data = json.loads(output)
                if not isinstance(data, list):
                    data = [data]
                
                for item in data:
                    app = PortableApplication(
                        name=item.get('Name', 'Unknown'),
                        version=item.get('Version', 'Unknown'),
                        publisher=item.get('Publisher', 'Unknown'),
                        executable_path=item.get('ExecutablePath', ''),
                        install_directory=item.get('DetectedPath'),
                        detection_method=item.get('DetectionMethod', 'disk_scan'),
                        file_size_bytes=int(float(item.get('FileSizeKB', 0)) * 1024)
                    )
                    apps.append(app)
                    
            except json.JSONDecodeError as e:
                logger.error(f"[EXTENDED] Failed to parse portable apps JSON: {e}")
        
        logger.info(f"[EXTENDED] Collected {len(apps)} portable applications")
        return apps
    
    # =========================================================================
    # COMPREHENSIVE DISK SCAN
    # =========================================================================
    
    def collect_disk_scan(self) -> Dict[str, Any]:
        """
        Perform comprehensive disk scan for applications across fixed drives.
        Returns dict with all discovered applications.
        """
        script = r'''
        $ProgressPreference = 'SilentlyContinue'
        $results = @{
            'ProgramFiles' = @()
            'ProgramFilesX86' = @()
            'ProgramData' = @()
            'AppData' = @()
            'FixedDrives' = @()
            'Registry' = @()
        }
        
        # Method 1: Registry-based installed application scan
        $regPaths = @(
            'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
        )
        foreach ($regPath in $regPaths) {
            Get-ItemProperty $regPath -ErrorAction SilentlyContinue | Where-Object {
                $_.DisplayName -and $_.DisplayName.Trim()
            } | ForEach-Object {
                $results.Registry += @{
                    Name = $_.DisplayName
                    Version = if ($_.DisplayVersion) { $_.DisplayVersion } else { 'Unknown' }
                    Publisher = if ($_.Publisher) { $_.Publisher } else { 'Unknown' }
                    Path = if ($_.InstallLocation) { $_.InstallLocation } else { '' }
                    Source = 'Registry'
                }
            }
        }
        
        # C:\Program Files
        $pfPath = 'C:\Program Files'
        if (Test-Path $pfPath) {
            Get-ChildItem $pfPath -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $exeFiles = Get-ChildItem $_.FullName -Filter '*.exe' -Depth 1 -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($exeFiles) {
                    $v = (Get-Item $exeFiles.FullName).VersionInfo
                    $results.ProgramFiles += @{
                        Name = $v.FileDescription
                        Version = $v.FileVersion
                        Publisher = $v.CompanyName
                        Path = $_.FullName
                        Source = 'ProgramFiles'
                    }
                }
            }
        }
        
        # C:\Program Files (x86)
        $pfxPath = 'C:\Program Files (x86)'
        if (Test-Path $pfxPath) {
            Get-ChildItem $pfxPath -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $exeFiles = Get-ChildItem $_.FullName -Filter '*.exe' -Depth 1 -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($exeFiles) {
                    $v = (Get-Item $exeFiles.FullName).VersionInfo
                    $results.ProgramFilesX86 += @{
                        Name = $v.FileDescription
                        Version = $v.FileVersion
                        Publisher = $v.CompanyName
                        Path = $_.FullName
                        Source = 'ProgramFilesX86'
                    }
                }
            }
        }
        
        # C:\ProgramData (for installers and shared apps)
        $pdPath = 'C:\ProgramData'
        if (Test-Path $pdPath) {
            Get-ChildItem $pdPath -Directory -ErrorAction SilentlyContinue | Where-Object {
                $_.Name -notmatch '^(Microsoft|Windows|Package Cache|USOPrivate|Application Data)'
            } | ForEach-Object {
                $exeFiles = Get-ChildItem $_.FullName -Filter '*.exe' -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($exeFiles) {
                    $v = (Get-Item $exeFiles.FullName).VersionInfo
                    if ($v.FileDescription) {
                        $results.ProgramData += @{
                            Name = $v.FileDescription
                            Version = $v.FileVersion
                            Publisher = $v.CompanyName
                            Path = $_.FullName
                            Source = 'ProgramData'
                        }
                    }
                }
            }
        }
        
        # User AppData
        $appDataPaths = @(
            "$env:LOCALAPPDATA\Programs",
            "$env:APPDATA"
        )
        foreach ($adPath in $appDataPaths) {
            if (Test-Path $adPath) {
                Get-ChildItem $adPath -Directory -ErrorAction SilentlyContinue | Where-Object {
                    $_.Name -notmatch '^(Microsoft|Windows)$'
                } | ForEach-Object {
                    $exeFiles = Get-ChildItem $_.FullName -Filter '*.exe' -Depth 1 -ErrorAction SilentlyContinue | Select-Object -First 1
                    if ($exeFiles) {
                        $v = (Get-Item $exeFiles.FullName).VersionInfo
                        if ($v.FileDescription) {
                            $results.AppData += @{
                                Name = $v.FileDescription
                                Version = $v.FileVersion
                                Publisher = $v.CompanyName
                                Path = $_.FullName
                                Source = 'AppData'
                            }
                        }
                    }
                }
            }
        }
        
        # Additional fixed drives (D:, E:, ...), including non-standard app folders
        try {
            $fixedDrives = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty DeviceID
            foreach ($drive in $fixedDrives) {
                if ($drive -eq 'C:') { continue }
                $drivePaths = @("$drive\Program Files", "$drive\Program Files (x86)", "$drive\Tools", "$drive\Programs", "$drive\Portable Apps")
                foreach ($basePath in $drivePaths) {
                    if (Test-Path $basePath) {
                        Get-ChildItem $basePath -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                            $exeFiles = Get-ChildItem $_.FullName -Filter '*.exe' -Depth 1 -ErrorAction SilentlyContinue | Select-Object -First 1
                            if ($exeFiles) {
                                $v = (Get-Item $exeFiles.FullName).VersionInfo
                                if ($v.FileDescription) {
                                    $results.FixedDrives += @{
                                        Name = $v.FileDescription
                                        Version = $v.FileVersion
                                        Publisher = $v.CompanyName
                                        Path = $_.FullName
                                        Source = $drive
                                    }
                                }
                            }
                        }
                    }
                }
            }
        } catch {}
        
        $results | ConvertTo-Json -Depth 3
        '''
        
        output = self._run_powershell(script, timeout=300)
        if output:
            try:
                return json.loads(output)
            except json.JSONDecodeError as e:
                logger.error(f"[EXTENDED] Failed to parse disk scan JSON: {e}")
        
        return {}
    
    # =========================================================================
    # FULL COLLECTION
    # =========================================================================
    
    def collect_all(self) -> Dict[str, Any]:
        """Collect all extended inventory data"""
        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'cli_tools': [t.to_dict() for t in self.collect_cli_tools()],
            'drivers': [d.to_dict() for d in self.collect_hardware_drivers()],
            'vscode_extensions': [e.to_dict() for e in self.collect_vscode_extensions()],
            'browser_extensions': [e.to_dict() for e in self.collect_browser_extensions()],
            'plugins': [p.to_dict() for p in self.collect_application_plugins()],
            'portable_apps': [a.to_dict() for a in self.collect_portable_applications()],
            'disk_scan': self.collect_disk_scan()
        }
