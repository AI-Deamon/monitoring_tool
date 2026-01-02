"""
Integrity Verification Module - SEC-024 ENHANCED
=================================================
Provides comprehensive tamper detection and resistance:

Level 1 - Tamper Detection:
  1. File hash verification (detect modified code)
  2. Heartbeat gap monitoring (detect service stops)
  3. Anomaly detection (unusual patterns)
  4. Watchdog monitoring

Level 2 - Tamper Resistance:
  1. HMAC signing of all outgoing data
  2. Config integrity verification
  3. Encrypted local storage (optional)
"""
import hashlib
import hmac
import json
import logging
import secrets
import sys
import base64
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# LEVEL 1: FILE INTEGRITY VERIFICATION
# =============================================================================

def calculate_file_hash(filepath: Path) -> str:
    """Calculate SHA256 hash of file"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def generate_manifest(install_dir: Path) -> Dict[str, str]:
    """
    Generate manifest of all .pyc files
    
    Args:
        install_dir: Root installation directory
        
    Returns:
        Dictionary mapping relative paths to SHA256 hashes
    """
    manifest = {}
    
    for pyc_file in install_dir.rglob('*.pyc'):
        # Skip __pycache__ directories (these are regenerated)
        if '__pycache__' in str(pyc_file):
            continue
            
        relative_path = pyc_file.relative_to(install_dir)
        file_hash = calculate_file_hash(pyc_file)
        manifest[str(relative_path)] = file_hash
        
    return manifest


def save_manifest(install_dir: Path, manifest: Dict[str, str]) -> bool:
    """
    Save manifest to secure location
    
    Args:
        install_dir: Root installation directory
        manifest: Dictionary of file paths to hashes
        
    Returns:
        True if saved successfully
    """
    try:
        manifest_file = install_dir / '.integrity_manifest'
        
        # Add metadata
        manifest_data = {
            'version': 2,
            'files': manifest,
            'file_count': len(manifest),
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        with open(manifest_file, 'w') as f:
            json.dump(manifest_data, f, indent=2)
            
        logger.info(f"SEC-024: Integrity manifest created with {len(manifest)} files")
        return True
        
    except Exception as e:
        logger.error(f"SEC-024: Failed to save manifest: {e}")
        return False


def load_manifest(install_dir: Path) -> Optional[Dict[str, str]]:
    """
    Load manifest from file
    
    Args:
        install_dir: Root installation directory
        
    Returns:
        Dictionary of file paths to hashes, or None if not found
    """
    manifest_file = install_dir / '.integrity_manifest'
    
    if not manifest_file.exists():
        return None
        
    try:
        with open(manifest_file, 'r') as f:
            data = json.load(f)
            
        # Handle both v1 format and legacy format
        if 'files' in data:
            return data['files']
        else:
            return data
            
    except Exception as e:
        logger.error(f"SEC-024: Failed to load manifest: {e}")
        return None


def verify_integrity(install_dir: Path, strict: bool = False) -> Tuple[bool, List[str]]:
    """
    Verify all files match manifest
    
    Args:
        install_dir: Root installation directory
        strict: If True, return False on any violation. If False, log but continue.
        
    Returns:
        Tuple of (success, list of violations)
    """
    violations = []
    
    manifest = load_manifest(install_dir)
    
    if manifest is None:
        msg = "SEC-024: Integrity manifest NOT FOUND"
        logger.warning(msg)
        
        # If no manifest exists, we can't verify - not necessarily an error
        # This could be a fresh install or development environment
        if strict:
            return False, [msg]
        else:
            logger.info("SEC-024: Skipping integrity check (no manifest)")
            return True, []
    
    # Verify each file in manifest
    for file_path, expected_hash in manifest.items():
        full_path = install_dir / file_path
        
        if not full_path.exists():
            violations.append(f"MISSING: {file_path}")
            continue
            
        actual_hash = calculate_file_hash(full_path)
        if actual_hash != expected_hash:
            violations.append(f"MODIFIED: {file_path}")
    
    # Report violations
    if violations:
        logger.critical("=" * 70)
        logger.critical("SEC-024: CODE TAMPERING DETECTED!")
        logger.critical("The following files have been modified or removed:")
        for violation in violations:
            logger.critical(f"  - {violation}")
        logger.critical("=" * 70)
        
        if strict:
            return False, violations
    else:
        logger.info(f"SEC-024: Integrity verified ({len(manifest)} files OK)")
    
    return len(violations) == 0, violations


def verify_integrity_or_exit(install_dir: Path):
    """
    Verify integrity and exit if tampering detected
    
    This is the recommended function to call at agent startup.
    """
    success, violations = verify_integrity(install_dir, strict=True)
    
    if not success:
        print("=" * 70, file=sys.stderr)
        print("FATAL: Code integrity check failed!", file=sys.stderr)
        print("SEC-024: Possible code tampering detected", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(1)


# =============================================================================
# LEVEL 2: DATA SIGNING (HMAC)
# =============================================================================

class DataSigner:
    """
    Signs all outgoing data with HMAC-SHA256.
    Server can verify data hasn't been tampered with in transit.
    """
    
    def __init__(self, secret_key: str = None, key_file: Path = None):
        """
        Initialize data signer.
        
        Args:
            secret_key: Optional pre-shared key
            key_file: Path to store/load key
        """
        self._key_file = key_file
        
        if secret_key:
            self._key = secret_key
        elif key_file and key_file.exists():
            self._key = self._load_key()
        else:
            self._key = self._generate_and_save_key()
        
        logger.info(f"SEC-024: DataSigner initialized (key: {self._key[:8]}...)")
    
    def _generate_and_save_key(self) -> str:
        """Generate new signing key and save it"""
        new_key = secrets.token_hex(32)  # 256-bit key
        
        if self._key_file:
            try:
                self._key_file.write_text(new_key)
                logger.info(f"SEC-024: Signing key saved to {self._key_file}")
            except Exception as e:
                logger.warning(f"SEC-024: Could not save key: {e}")
        
        return new_key
    
    def _load_key(self) -> str:
        """Load existing key from file"""
        try:
            return self._key_file.read_text().strip()
        except Exception as e:
            logger.error(f"SEC-024: Could not load key: {e}")
            return self._generate_and_save_key()
    
    def get_key_fingerprint(self) -> str:
        """Get fingerprint of signing key (for server registration)"""
        return hashlib.sha256(self._key.encode()).hexdigest()[:16]
    
    def sign(self, data: Dict) -> Dict:
        """
        Sign a data payload.
        Adds '_sig' and '_ts' fields.
        
        Args:
            data: Dictionary to sign
            
        Returns:
            Signed copy of data
        """
        # Create copy with timestamp
        signed_data = data.copy()
        signed_data['_ts'] = datetime.now(timezone.utc).isoformat()
        
        # Create canonical JSON string (sorted keys for consistency)
        payload = json.dumps(signed_data, sort_keys=True, default=str)
        
        # Compute HMAC signature
        signature = hmac.new(
            self._key.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        signed_data['_sig'] = signature
        
        return signed_data
    
    def verify(self, data: Dict) -> bool:
        """
        Verify a signed payload.
        
        Args:
            data: Signed dictionary
            
        Returns:
            True if signature is valid
        """
        if '_sig' not in data:
            return False
        
        stored_sig = data.pop('_sig')
        payload = json.dumps(data, sort_keys=True, default=str)
        
        expected_sig = hmac.new(
            self._key.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Restore signature
        data['_sig'] = stored_sig
        
        return hmac.compare_digest(stored_sig, expected_sig)


# =============================================================================
# LEVEL 2: CONFIG INTEGRITY
# =============================================================================

class ConfigIntegrity:
    """
    Protects config.json from tampering.
    Signs config on save, verifies on load.
    """
    
    SIGNATURE_KEY = '_config_sig'
    
    def __init__(self, signer: DataSigner):
        self._signer = signer
    
    def sign_config(self, config: Dict) -> Dict:
        """Sign configuration, return signed copy"""
        # Remove existing signature
        config_copy = {k: v for k, v in config.items() if not k.startswith('_')}
        
        # Use DataSigner
        return self._signer.sign(config_copy)
    
    def verify_config(self, config: Dict) -> bool:
        """Verify config signature"""
        if '_sig' not in config:
            logger.warning("SEC-024: Config has no signature")
            return False
        
        is_valid = self._signer.verify(config.copy())
        
        if not is_valid:
            logger.critical("=" * 70)
            logger.critical("SEC-024: CONFIG TAMPERING DETECTED!")
            logger.critical("config.json has been modified without authorization")
            logger.critical("=" * 70)
        
        return is_valid


# =============================================================================
# LEVEL 1: WATCHDOG & ANOMALY DETECTION
# =============================================================================

class IntegrityWatchdog:
    """
    Monitors agent health and detects anomalies.
    """
    
    # Anomaly thresholds
    MAX_HEARTBEAT_GAP = 180  # 3 minutes
    MAX_ACTIVE_HOURS = 16    # No human is active 16+ hours
    MIN_IDLE_RATIO = 0.05    # At least 5% idle time expected
    
    def __init__(self):
        self._start_time = datetime.now(timezone.utc)
        self._last_heartbeat = datetime.now(timezone.utc)
        self._heartbeat_count = 0
        self._anomalies: List[Dict] = []
        self._daily_stats = {
            'active_seconds': 0,
            'idle_seconds': 0,
            'locked_seconds': 0
        }
    
    def record_heartbeat(self, state: str, duration: float):
        """Record a heartbeat and check for anomalies"""
        now = datetime.now(timezone.utc)
        gap = (now - self._last_heartbeat).total_seconds()
        
        # Check for suspicious gap
        if gap > self.MAX_HEARTBEAT_GAP:
            self._record_anomaly('heartbeat_gap', {
                'gap_seconds': gap,
                'expected_max': self.MAX_HEARTBEAT_GAP
            })
        
        # Update stats
        if state == 'active':
            self._daily_stats['active_seconds'] += duration
        elif state == 'idle':
            self._daily_stats['idle_seconds'] += duration
        elif state == 'locked':
            self._daily_stats['locked_seconds'] += duration
        
        self._last_heartbeat = now
        self._heartbeat_count += 1
        
        # Periodic anomaly checks
        if self._heartbeat_count % 100 == 0:  # Every ~50 minutes
            self._check_usage_anomalies()
    
    def _check_usage_anomalies(self):
        """Check for unrealistic usage patterns"""
        total = sum(self._daily_stats.values())
        
        if total == 0:
            return
        
        active = self._daily_stats['active_seconds']
        idle = self._daily_stats['idle_seconds']
        
        # Check 1: Too much active time (impossible for humans)
        if active > self.MAX_ACTIVE_HOURS * 3600:
            self._record_anomaly('excessive_active_time', {
                'active_hours': active / 3600,
                'threshold_hours': self.MAX_ACTIVE_HOURS
            })
        
        # Check 2: No idle time (suspicious - likely tampering)
        idle_ratio = idle / total if total > 0 else 0
        if total > 3600 and idle_ratio < self.MIN_IDLE_RATIO:
            self._record_anomaly('no_idle_time', {
                'idle_ratio': idle_ratio,
                'threshold': self.MIN_IDLE_RATIO,
                'suspicious': True
            })
    
    def _record_anomaly(self, anomaly_type: str, details: Dict):
        """Record an anomaly"""
        anomaly = {
            'type': anomaly_type,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'details': details
        }
        self._anomalies.append(anomaly)
        
        logger.warning(f"SEC-024: ANOMALY - {anomaly_type}: {details}")
        
        # Keep only last 100 anomalies
        if len(self._anomalies) > 100:
            self._anomalies = self._anomalies[-100:]
    
    def get_anomalies(self, clear: bool = False) -> List[Dict]:
        """Get recorded anomalies"""
        result = self._anomalies.copy()
        if clear:
            self._anomalies.clear()
        return result
    
    def get_integrity_report(self) -> Dict:
        """Get full integrity status report for server"""
        now = datetime.now(timezone.utc)
        uptime = (now - self._start_time).total_seconds()
        
        return {
            'uptime_seconds': uptime,
            'heartbeat_count': self._heartbeat_count,
            'last_heartbeat': self._last_heartbeat.isoformat(),
            'anomaly_count': len(self._anomalies),
            'anomalies': self._anomalies[-10:],  # Last 10 only
            'daily_stats': self._daily_stats,
            'status': 'healthy' if len(self._anomalies) == 0 else 'anomalies_detected'
        }
    
    def reset_daily_stats(self):
        """Reset daily stats (call at midnight)"""
        self._daily_stats = {
            'active_seconds': 0,
            'idle_seconds': 0,
            'locked_seconds': 0
        }


# =============================================================================
# GLOBAL INSTANCES (Singleton Pattern)
# =============================================================================

_data_signer: Optional[DataSigner] = None
_watchdog: Optional[IntegrityWatchdog] = None


def init_integrity(data_dir: Path) -> Tuple[DataSigner, IntegrityWatchdog]:
    """Initialize global integrity components"""
    global _data_signer, _watchdog
    
    key_file = data_dir / '.signing_key'
    _data_signer = DataSigner(key_file=key_file)
    _watchdog = IntegrityWatchdog()
    
    logger.info("SEC-024: Integrity system initialized")
    
    return _data_signer, _watchdog


def get_signer() -> Optional[DataSigner]:
    """Get global data signer"""
    return _data_signer


def get_watchdog() -> Optional[IntegrityWatchdog]:
    """Get global watchdog"""
    return _watchdog


# =============================================================================
# CLI support for generating manifest during installation
# =============================================================================
if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python integrity.py <install_dir>")
        print("Generates integrity manifest for all .pyc files")
        sys.exit(1)
    
    install_dir = Path(sys.argv[1])
    
    if not install_dir.exists():
        print(f"Error: Directory not found: {install_dir}")
        sys.exit(1)
    
    print(f"Generating integrity manifest for: {install_dir}")
    manifest = generate_manifest(install_dir)
    
    if save_manifest(install_dir, manifest):
        print(f"Success: Manifest created with {len(manifest)} files")
        for path in sorted(manifest.keys()):
            print(f"  - {path}")
    else:
        print("Error: Failed to create manifest")
        sys.exit(1)

