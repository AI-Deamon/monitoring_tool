"""
Asset, Lifecycle, Extended Inventory, Security, and Update Models
"""
from datetime import datetime
from extensions import db
from sqlalchemy.dialects import postgresql


class AssetInfo(db.Model):
    """
    Hardware and system information for IT asset management.
    One-to-one with Agent — stores latest hardware snapshot.
    """
    __tablename__ = 'asset_info'
    
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(postgresql.UUID(as_uuid=True), db.ForeignKey('agents.agent_id', ondelete='CASCADE'), 
                         unique=True, nullable=False, index=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True, index=True)
    
    # IDENTITY
    hostname = db.Column(db.String(255), nullable=True)
    serial_number = db.Column(db.String(255), nullable=True)
    manufacturer = db.Column(db.String(255), nullable=True)
    model = db.Column(db.String(255), nullable=True)
    bios_uuid = db.Column(db.String(255), nullable=True)
    system_uuid = db.Column(db.String(255), nullable=True)
    asset_tag = db.Column(db.String(255), nullable=True)
    domain = db.Column(db.String(255), nullable=True)
    workgroup = db.Column(db.String(255), nullable=True)
    
    # HARDWARE SPECS
    cpu_name = db.Column(db.Text, nullable=True)
    cpu_cores = db.Column(db.Integer, nullable=True)
    cpu_threads = db.Column(db.Integer, nullable=True)
    cpu_speed_mhz = db.Column(db.Integer, nullable=True)
    ram_total_gb = db.Column(db.Float, nullable=True)
    ram_slots_used = db.Column(db.Integer, nullable=True)
    ram_slots_total = db.Column(db.Integer, nullable=True)
    gpu_name = db.Column(db.Text, nullable=True)
    gpu_memory_gb = db.Column(db.Float, nullable=True)
    disks_json = db.Column(db.Text, nullable=True)
    motherboard = db.Column(db.Text, nullable=True)
    
    # NETWORK
    primary_mac = db.Column(db.String(255), nullable=True)
    primary_ip = db.Column(db.String(255), nullable=True)
    all_macs_json = db.Column(db.Text, nullable=True)
    all_ips_json = db.Column(db.Text, nullable=True)
    dns_servers_json = db.Column(db.Text, nullable=True)
    domain_joined = db.Column(db.Boolean, nullable=True)
    domain_name = db.Column(db.String(255), nullable=True)
    
    # SECURITY POSTURE
    os_name = db.Column(db.String(255), nullable=True)
    os_version = db.Column(db.String(255), nullable=True)
    os_build = db.Column(db.String(255), nullable=True)
    os_architecture = db.Column(db.String(255), nullable=True)
    os_edition = db.Column(db.String(50), nullable=True)
    os_sku = db.Column(db.Integer, nullable=True)
    antivirus_json = db.Column(db.Text, nullable=True)
    firewall_enabled = db.Column(db.Boolean, nullable=True)
    last_boot_time = db.Column(db.String(255), nullable=True)
    windows_update_enabled = db.Column(db.Boolean, nullable=True)
    bitlocker_status = db.Column(db.String(255), nullable=True)
    
    # META
    collected_at = db.Column(db.DateTime, default=datetime.utcnow)
    collection_hash = db.Column(db.String(64), nullable=True)
    agent_version = db.Column(db.String(50), nullable=True)
    
    def to_dict(self):
        import json as _json
        return {
            'agent_id': str(self.agent_id),
            'hostname': self.hostname,
            'serial_number': self.serial_number,
            'manufacturer': self.manufacturer,
            'model': self.model,
            'bios_uuid': self.bios_uuid,
            'system_uuid': self.system_uuid,
            'asset_tag': self.asset_tag,
            'domain': self.domain,
            'workgroup': self.workgroup,
            'cpu_name': self.cpu_name,
            'cpu_cores': self.cpu_cores,
            'cpu_threads': self.cpu_threads,
            'cpu_speed_mhz': self.cpu_speed_mhz,
            'ram_total_gb': self.ram_total_gb,
            'ram_slots_used': self.ram_slots_used,
            'ram_slots_total': self.ram_slots_total,
            'gpu_name': self.gpu_name,
            'gpu_memory_gb': self.gpu_memory_gb,
            'disks': _json.loads(self.disks_json) if self.disks_json else [],
            'motherboard': self.motherboard,
            'primary_mac': self.primary_mac,
            'primary_ip': self.primary_ip,
            'all_macs': _json.loads(self.all_macs_json) if self.all_macs_json else [],
            'all_ips': _json.loads(self.all_ips_json) if self.all_ips_json else [],
            'dns_servers': _json.loads(self.dns_servers_json) if self.dns_servers_json else [],
            'domain_joined': self.domain_joined,
            'domain_name': self.domain_name,
            'os_name': self.os_name,
            'os_version': self.os_version,
            'os_build': self.os_build,
            'os_architecture': self.os_architecture,
            'os_edition': self.os_edition,
            'os_sku': self.os_sku,
            'antivirus': _json.loads(self.antivirus_json) if self.antivirus_json else [],
            'firewall_enabled': self.firewall_enabled,
            'last_boot_time': self.last_boot_time,
            'windows_update_enabled': self.windows_update_enabled,
            'bitlocker_status': self.bitlocker_status,
            'collected_at': self.collected_at.isoformat() if self.collected_at else None,
            'collection_hash': self.collection_hash,
            'agent_version': self.agent_version
        }


class SoftwareLifecycle(db.Model):
    """
    EOL knowledge base. One row per product-cycle combination.
    Populated from endoflife.date API or manual curation.
    """
    __tablename__ = 'software_lifecycle'
    
    id              = db.Column(db.Integer, primary_key=True)
    product_name    = db.Column(db.String(255), nullable=False, index=True)
    cycle           = db.Column(db.String(100), nullable=False)
    release_label   = db.Column(db.String(255), nullable=True)
    release_date    = db.Column(db.Date, nullable=True)
    eol_date        = db.Column(db.Date, nullable=True)
    eos_date        = db.Column(db.Date, nullable=True)
    is_lts          = db.Column(db.Boolean, default=False)
    latest_version  = db.Column(db.String(100), nullable=True)
    reference_url   = db.Column(db.Text, nullable=True)
    source          = db.Column(db.String(50), default='endoflife.date')
    synced_at       = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('product_name', 'cycle', name='uq_lifecycle_product_cycle'),
    )


class AssetLifecycleStatus(db.Model):
    """
    Cached lifecycle evaluation result per agent per product.
    Recalculated when inventory updates or lifecycle DB changes.
    """
    __tablename__ = 'asset_lifecycle_status'
    
    id                = db.Column(db.Integer, primary_key=True)
    agent_id          = db.Column(postgresql.UUID(as_uuid=True), 
                                  db.ForeignKey('agents.agent_id', ondelete='CASCADE'), 
                                  nullable=False, index=True)
    product_name      = db.Column(db.String(255), nullable=False)
    installed_version = db.Column(db.String(255), nullable=True)
    matched_cycle     = db.Column(db.String(100), nullable=True)
    status            = db.Column(db.String(30), nullable=False, default='unknown')
    eol_date          = db.Column(db.Date, nullable=True)
    risk_score        = db.Column(db.Integer, default=0)
    severity          = db.Column(db.String(20), default='info')
    evaluated_at      = db.Column(db.DateTime, default=datetime.utcnow)
    
    agent = db.relationship('Agent', backref=db.backref('lifecycle_statuses', lazy='dynamic',
                                                         cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.UniqueConstraint('agent_id', 'product_name', name='uq_asset_lifecycle_agent_product'),
    )


# =============================================================================
# Extended Inventory Models
# =============================================================================

class CLITool(db.Model):
    """Command-line tools inventory (git, node, python, etc.)"""
    __tablename__ = 'cli_tools'
    
    id                = db.Column(db.Integer, primary_key=True)
    agent_id          = db.Column(postgresql.UUID(as_uuid=True), 
                                  db.ForeignKey('agents.agent_id', ondelete='CASCADE'), 
                                  nullable=False, index=True)
    name              = db.Column(db.String(255), nullable=False)
    version           = db.Column(db.String(100), nullable=True)
    executable_path   = db.Column(db.String(500), nullable=True)
    source            = db.Column(db.String(50), nullable=True)
    publisher         = db.Column(db.String(255), nullable=True)
    first_detected    = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    agent = db.relationship('Agent', backref=db.backref('cli_tools', lazy='dynamic',
                                                         cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.UniqueConstraint('agent_id', 'name', 'executable_path', name='uq_cli_tool_agent_name_path'),
    )


class HardwareDriver(db.Model):
    """Hardware drivers inventory from WMI Win32_PnPSignedDriver."""
    __tablename__ = 'hardware_drivers'
    
    id                = db.Column(db.Integer, primary_key=True)
    agent_id          = db.Column(postgresql.UUID(as_uuid=True), 
                                  db.ForeignKey('agents.agent_id', ondelete='CASCADE'), 
                                  nullable=False, index=True)
    device_name       = db.Column(db.String(255), nullable=True)
    driver_name       = db.Column(db.String(255), nullable=True)
    driver_version    = db.Column(db.String(100), nullable=True)
    driver_date       = db.Column(db.Date, nullable=True)
    manufacturer      = db.Column(db.String(255), nullable=True)
    device_class      = db.Column(db.String(100), nullable=True)
    device_id         = db.Column(db.String(500), nullable=True)
    is_signed         = db.Column(db.Boolean, default=False)
    signer            = db.Column(db.String(255), nullable=True)
    first_detected    = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    agent = db.relationship('Agent', backref=db.backref('hardware_drivers', lazy='dynamic',
                                                         cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.UniqueConstraint('agent_id', 'device_id', name='uq_driver_agent_device'),
    )


class VSCodeExtension(db.Model):
    """VS Code extensions from ~/.vscode/extensions."""
    __tablename__ = 'vscode_extensions'
    
    id                = db.Column(db.Integer, primary_key=True)
    agent_id          = db.Column(postgresql.UUID(as_uuid=True), 
                                  db.ForeignKey('agents.agent_id', ondelete='CASCADE'), 
                                  nullable=False, index=True)
    extension_id      = db.Column(db.String(255), nullable=True)
    display_name      = db.Column(db.String(255), nullable=True)
    version           = db.Column(db.String(100), nullable=True)
    publisher         = db.Column(db.String(255), nullable=True)
    install_path      = db.Column(db.String(500), nullable=True)
    first_detected    = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    agent = db.relationship('Agent', backref=db.backref('vscode_extensions', lazy='dynamic',
                                                         cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.UniqueConstraint('agent_id', 'extension_id', name='uq_vscode_ext_agent_ext'),
    )


class BrowserExtension(db.Model):
    """Browser extensions from Chrome, Firefox, Edge."""
    __tablename__ = 'browser_extensions'
    
    id                = db.Column(db.Integer, primary_key=True)
    agent_id          = db.Column(postgresql.UUID(as_uuid=True), 
                                  db.ForeignKey('agents.agent_id', ondelete='CASCADE'), 
                                  nullable=False, index=True)
    browser           = db.Column(db.String(50), nullable=False)
    extension_id      = db.Column(db.String(255), nullable=True)
    name              = db.Column(db.String(255), nullable=True)
    version           = db.Column(db.String(100), nullable=True)
    description       = db.Column(db.Text, nullable=True)
    enabled           = db.Column(db.Boolean, default=True)
    install_date      = db.Column(db.Date, nullable=True)
    profile_path      = db.Column(db.String(500), nullable=True)
    first_detected    = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    agent = db.relationship('Agent', backref=db.backref('browser_extensions', lazy='dynamic',
                                                         cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.UniqueConstraint('agent_id', 'browser', 'extension_id', name='uq_browser_ext_agent_browser_ext'),
    )


class ApplicationPlugin(db.Model):
    """Application plugins and add-ins (Office, Adobe, etc.)"""
    __tablename__ = 'application_plugins'
    
    id                = db.Column(db.Integer, primary_key=True)
    agent_id          = db.Column(postgresql.UUID(as_uuid=True), 
                                  db.ForeignKey('agents.agent_id', ondelete='CASCADE'), 
                                  nullable=False, index=True)
    plugin_type       = db.Column(db.String(50), nullable=False)
    name              = db.Column(db.String(255), nullable=True)
    version           = db.Column(db.String(100), nullable=True)
    publisher         = db.Column(db.String(255), nullable=True)
    install_path      = db.Column(db.String(500), nullable=True)
    host_application  = db.Column(db.String(255), nullable=True)
    enabled           = db.Column(db.Boolean, default=True)
    first_detected    = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    agent = db.relationship('Agent', backref=db.backref('application_plugins', lazy='dynamic',
                                                         cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.UniqueConstraint('agent_id', 'plugin_type', 'name', 'install_path', 
                           name='uq_plugin_agent_type_name_path'),
    )


class PortableApplication(db.Model):
    """Portable applications found via disk scanning."""
    __tablename__ = 'portable_applications'
    
    id                = db.Column(db.Integer, primary_key=True)
    agent_id          = db.Column(postgresql.UUID(as_uuid=True), 
                                  db.ForeignKey('agents.agent_id', ondelete='CASCADE'), 
                                  nullable=False, index=True)
    name              = db.Column(db.String(255), nullable=False)
    version           = db.Column(db.String(100), nullable=True)
    executable_path   = db.Column(db.String(500), nullable=True)
    install_directory = db.Column(db.String(500), nullable=True)
    publisher         = db.Column(db.String(255), nullable=True)
    detection_method  = db.Column(db.String(50), nullable=True)
    file_size_bytes   = db.Column(db.BigInteger, nullable=True)
    first_detected    = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    agent = db.relationship('Agent', backref=db.backref('portable_applications', lazy='dynamic',
                                                         cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.UniqueConstraint('agent_id', 'executable_path', name='uq_portable_app_agent_path'),
    )


# =============================================================================
# EOL SYSTEM MODELS
# =============================================================================

class NVDCacheEntry(db.Model):
    """Local cache of NIST NVD vulnerability data."""
    __tablename__ = 'nvd_cache'

    id              = db.Column(db.Integer, primary_key=True)
    cve_id          = db.Column(db.String(20), nullable=False, index=True)
    cpe_string      = db.Column(db.String(500), nullable=False, index=True)
    cvss_score      = db.Column(db.Float, default=0.0)
    severity        = db.Column(db.String(20), default='NONE')
    description     = db.Column(db.Text, nullable=True)
    published_date  = db.Column(db.String(30), nullable=True)
    last_modified   = db.Column(db.String(30), nullable=True)
    synced_at       = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('cve_id', 'cpe_string', name='uq_nvd_cve_cpe'),
        db.Index('ix_nvd_cvss', 'cvss_score'),
    )


class WindowsUpdateRecord(db.Model):
    """Windows update (KB) records collected from agents."""
    __tablename__ = 'windows_updates'

    id              = db.Column(db.Integer, primary_key=True)
    agent_id        = db.Column(postgresql.UUID(as_uuid=True),
                                db.ForeignKey('agents.agent_id', ondelete='CASCADE'),
                                nullable=False, index=True)
    kb_number       = db.Column(db.String(20), nullable=False)
    title           = db.Column(db.String(500), nullable=True)
    update_type     = db.Column(db.String(50), default='Unknown')
    install_date    = db.Column(db.Date, nullable=True)
    result_code     = db.Column(db.Integer, default=0)
    is_pending      = db.Column(db.Boolean, default=False)
    first_detected  = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent = db.relationship('Agent', backref=db.backref('windows_updates', lazy='dynamic',
                                                         cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('agent_id', 'kb_number', name='uq_update_agent_kb'),
    )


class SoftwareMeteringRecord(db.Model):
    """Software usage frequency data from Prefetch/MUI cache."""
    __tablename__ = 'software_metering'

    id              = db.Column(db.Integer, primary_key=True)
    agent_id        = db.Column(postgresql.UUID(as_uuid=True),
                                db.ForeignKey('agents.agent_id', ondelete='CASCADE'),
                                nullable=False, index=True)
    app_name        = db.Column(db.String(255), nullable=False)
    executable_name = db.Column(db.String(255), nullable=True)
    usage_count     = db.Column(db.Integer, default=0)
    last_used       = db.Column(db.DateTime, nullable=True)
    source          = db.Column(db.String(50), default='prefetch')
    first_detected  = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent = db.relationship('Agent', backref=db.backref('software_metering', lazy='dynamic',
                                                         cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('agent_id', 'executable_name', name='uq_metering_agent_exe'),
    )


class ProductKeyRecord(db.Model):
    """Partial product keys for license compliance tracking."""
    __tablename__ = 'product_keys'

    id              = db.Column(db.Integer, primary_key=True)
    agent_id        = db.Column(postgresql.UUID(as_uuid=True),
                                db.ForeignKey('agents.agent_id', ondelete='CASCADE'),
                                nullable=False, index=True)
    product_name    = db.Column(db.String(255), nullable=False)
    partial_key     = db.Column(db.String(10), nullable=True)
    key_source      = db.Column(db.String(50), default='Unknown')
    license_status  = db.Column(db.String(50), default='Unknown')
    first_detected  = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent = db.relationship('Agent', backref=db.backref('product_keys', lazy='dynamic',
                                                         cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('agent_id', 'product_name', name='uq_key_agent_product'),
    )


class SecurityIndicator(db.Model):
    """Security risk indicators detected by the agent's SecurityCollector."""
    __tablename__ = 'security_indicators'

    id              = db.Column(db.Integer, primary_key=True)
    agent_id        = db.Column(postgresql.UUID(as_uuid=True),
                                db.ForeignKey('agents.agent_id', ondelete='CASCADE'),
                                nullable=False, index=True)
    indicator_type  = db.Column(db.String(50), nullable=False)
    severity        = db.Column(db.String(20), nullable=False)
    title           = db.Column(db.String(500), nullable=False)
    details_json    = db.Column(db.Text, nullable=True)
    risk_score      = db.Column(db.Integer, default=0)
    first_detected  = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved        = db.Column(db.Boolean, default=False)

    agent = db.relationship('Agent', backref=db.backref('security_indicators', lazy='dynamic',
                                                         cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('agent_id', 'indicator_type', 'title', name='uq_security_agent_type_title'),
    )


# ============================================================================
# AUTO-UPDATE MANAGEMENT TABLES
# ============================================================================

class UpdateHistory(db.Model):
    """Audit trail for every agent update lifecycle event."""
    __tablename__ = 'update_history'

    id              = db.Column(db.Integer, primary_key=True)
    agent_id        = db.Column(postgresql.UUID(as_uuid=True),
                                db.ForeignKey('agents.agent_id', ondelete='CASCADE'),
                                nullable=False, index=True)
    from_version    = db.Column(db.String(50), nullable=True)
    to_version      = db.Column(db.String(50), nullable=False)
    status          = db.Column(db.String(30), nullable=False)
    started_at      = db.Column(db.DateTime, nullable=True)
    completed_at    = db.Column(db.DateTime, nullable=True)
    error_message   = db.Column(db.Text, nullable=True)
    package_sha256  = db.Column(db.String(64), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index('ix_update_history_agent_created', 'agent_id', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'agent_id': str(self.agent_id),
            'from_version': self.from_version,
            'to_version': self.to_version,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'error_message': self.error_message,
            'package_sha256': self.package_sha256,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UpdateGlobalPolicy(db.Model):
    """Singleton row storing global auto-update policy."""
    __tablename__ = 'update_global_policy'

    id                    = db.Column(db.Integer, primary_key=True)
    auto_update_enabled   = db.Column(db.Boolean, default=False)
    channel               = db.Column(db.String(20), default='stable')
    min_version           = db.Column(db.String(50), nullable=True)
    canary_percentage     = db.Column(db.Integer, default=0)
    update_window_enabled = db.Column(db.Boolean, default=False)
    update_window_start   = db.Column(db.Time, nullable=True)
    update_window_end     = db.Column(db.Time, nullable=True)
    update_window_tz      = db.Column(db.String(50), default='UTC')
    updated_by            = db.Column(db.String(255), nullable=True)
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'auto_update_enabled': self.auto_update_enabled,
            'channel': self.channel,
            'min_version': self.min_version,
            'canary_percentage': self.canary_percentage,
            'update_window_enabled': self.update_window_enabled,
            'update_window_start': self.update_window_start.strftime('%H:%M') if self.update_window_start else None,
            'update_window_end': self.update_window_end.strftime('%H:%M') if self.update_window_end else None,
            'update_window_tz': self.update_window_tz,
            'updated_by': self.updated_by,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class UpdateVersion(db.Model):
    """Version metadata cache for dashboard discovery."""
    __tablename__ = 'update_versions'

    id                = db.Column(db.Integer, primary_key=True)
    version           = db.Column(db.String(50), unique=True, nullable=False, index=True)
    artifact_type     = db.Column(db.String(30), default='exe_bundle')
    package_size      = db.Column(db.BigInteger, nullable=True)
    package_sha256    = db.Column(db.String(64), nullable=True)
    min_agent_version = db.Column(db.String(50), nullable=True)
    mandatory         = db.Column(db.Boolean, default=False)
    changelog         = db.Column(db.Text, nullable=True)
    release_date      = db.Column(db.DateTime, nullable=True)
    is_active         = db.Column(db.Boolean, default=True)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'version': self.version,
            'artifact_type': self.artifact_type,
            'package_size': self.package_size,
            'package_sha256': self.package_sha256,
            'min_agent_version': self.min_agent_version,
            'mandatory': self.mandatory,
            'changelog': self.changelog,
            'release_date': self.release_date.isoformat() if self.release_date else None,
            'is_active': self.is_active,
        }
