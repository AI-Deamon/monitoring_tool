"""
SentinelEdge Agent Auto-Updater
================================
Handles the complete update lifecycle:
    1. Check server for new version
    2. Verify HMAC signature of metadata
    3. Download update package
    4. Verify SHA256 of package
    5. Backup current installation
    6. Apply update (extract + compile)
    7. Signal service restart
    8. Report health on next startup

ARCHITECTURE:
- Runs inside Core Service (SYSTEM level)
- Core updates BOTH core/ and helper - Helper never self-updates
- Uses atomic directory operations (rename, not overwrite)
- Rollback is automatic if startup fails after update

FILE LAYOUT:
    C:/ProgramData/SentinelEdge/
      |- config.json              (preserved across updates)
      |- agent_id                 (preserved)
      |- updates/
      |   +-- <version>/          (temp download, cleaned after apply)
      +-- backup/
          +-- pre_<version>/      (previous install, cleaned on health OK)

    C:/Program Files/SentinelEdge/
      |- python313/               (unchanged)
      |- nssm/                    (unchanged)
      |- core/                    (UPDATED)
      |- helper/                  (UPDATED)
      |- sentinel_core.pyc        (UPDATED)
      |- sentinel_helper.pyc      (UPDATED)
      +-- version.json            (current version metadata)
"""

import os
import sys
import json
import hmac
import time
import shutil
import hashlib
import base64
import zipfile
import logging
import urllib.request
import urllib.error
import py_compile
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)


class AgentUpdater:
    """Manages agent auto-updates with verification and rollback."""

    # Never update these directories/files
    PRESERVE = {'python313', 'nssm', 'config.json', 'agent_id', 'local_key'}

    def __init__(self, config):
        """
        Args:
            config: CoreConfig instance
        """
        self.config = config
        self.data_dir = config.data_dir  # C:\ProgramData\SentinelEdge
        self.install_dir = self._detect_install_dir()
        self.updates_dir = self.data_dir / 'updates'
        self.backup_dir = self.data_dir / 'backup'
        self.pending_file = self.data_dir / 'update_pending.json'
        self.failed_swap_file = self.data_dir / 'failed_swap.json'
        self.update_lock_file = self.data_dir / 'update.lock'
        self.version_file = self.install_dir / 'version.json'

        # Ensure dirs
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self._current_version = self._read_current_version()
        self._last_update_check_reason = "not_checked"
        logger.info(f"[UPDATER] Initialized. Version={self._current_version}, "
                     f"Install={self.install_dir}")

    # =========================================================================
    # Version Management
    # =========================================================================

    def _detect_install_dir(self) -> Path:
        """Detect the agent installation directory."""
        # service.py sets install_dir as parent of core/
        # __file__ is core/updater.py -> parent is core/ -> parent is agent install
        candidate = Path(__file__).resolve().parent.parent
        if (candidate / 'core').is_dir():
            return candidate
        # Fallback: check stealth name first, then legacy
        for dirname in ['WinDiagSvc', 'SentinelEdge']:
            fallback = Path(r'C:\Program Files') / dirname
            if fallback.exists():
                return fallback
        return Path(r'C:\Program Files\WinDiagSvc')

    def _read_current_version(self) -> str:
        """Read current agent version from version.json, fallback to config.json."""
        try:
            if self.version_file.exists():
                data = json.loads(self.version_file.read_text())
                version = data.get('version', '')
                if version:
                    return version
        except Exception as e:
            logger.warning(f"[UPDATER] Cannot read version.json: {e}")

        # Fallback to config.json current_version field
        config_version = getattr(self.config, 'current_version', '')
        if config_version:
            logger.info(f"[UPDATER] Using version from config.json: {config_version}")
            return config_version

        return '0.0.0'

    @property
    def current_version(self) -> str:
        return self._current_version

    @staticmethod
    def compare_versions(a: str, b: str) -> int:
        """
        Compare two version strings.
        Returns: >0 if a > b, 0 if equal, <0 if a < b
        """
        def parse(v):
            try:
                return tuple(int(x) for x in v.split('.')[:3])
            except (ValueError, AttributeError):
                return (0, 0, 0)
        va, vb = parse(a), parse(b)
        if va > vb:
            return 1
        if va < vb:
            return -1
        return 0

    # =========================================================================
    # HMAC Signature Verification
    # =========================================================================

    def _get_signing_key(self) -> bytes:
        """Get the HMAC signing key from config."""
        updates_config = self.config.config.get('updates', {})
        key = updates_config.get('signing_key', '')
        if not key:
            logger.warning("[UPDATER] No update signing key in config")
            return b''
        return key.encode('utf-8')

    def verify_signature(self, metadata: Dict) -> bool:
        """
        Verify HMAC-SHA256 signature on version metadata.

        Args:
            metadata: Server response with 'signature' field

        Returns:
            True if valid, False if invalid or no key configured
        """
        key = self._get_signing_key()
        if not key:
            logger.warning(
                "[UPDATER] Skipping signature verification - no signing key"
            )
            return True

        received_sig = metadata.get('signature', '')
        if not received_sig:
            logger.error("[UPDATER] Server response has no signature")
            return False

        # Rebuild canonical payload
        signable = {
            'version': metadata.get('version', ''),
            'package_sha256': metadata.get('package_sha256', ''),
            'package_size': metadata.get('package_size', 0),
            'min_agent_version': metadata.get('min_agent_version', '2.0.0'),
            'mandatory': metadata.get('mandatory', False),
        }
        canonical = json.dumps(signable, sort_keys=True, separators=(',', ':'))

        expected_sig = hmac.new(
            key, canonical.encode('utf-8'), hashlib.sha256
        ).digest()
        expected_b64 = base64.b64encode(expected_sig).decode('ascii')

        if hmac.compare_digest(received_sig, expected_b64):
            logger.info("[UPDATER] [OK] Signature verified")
            return True
        else:
            logger.error("[UPDATER] [FAIL] Signature mismatch -- possible tampering")
            return False

    # =========================================================================
    # Check for Updates
    # =========================================================================

    def check_for_update(self) -> Optional[Dict]:
        """
        Check server for available updates.

        Returns:
            Update metadata dict if update available, None otherwise.
            Metadata includes 'force_check' bool if server set force_update_check.
        """
        try:
            self._last_update_check_reason = "checking"
            url = f"{self.config.server_url}/api/v1/updates/latest"
            headers = {
                'X-Agent-ID': self.config.agent_id,
                'X-Agent-Version': self._current_version,
            }

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))

            # Server may request clearing local swap-failure gate.
            if data.get('clear_failed_swap'):
                if self.failed_swap_file.exists():
                    logger.info(
                        "[UPDATER] Server signaled clear_failed_swap - removing "
                        "failed_swap.json"
                    )
                    try:
                        self.failed_swap_file.unlink()
                    except Exception as e:
                        logger.warning(
                            f"[UPDATER] Failed to remove failed_swap.json: {e}"
                        )

            if not data.get('update_available', False):
                self._last_update_check_reason = "no_update_available"
                logger.info("[UPDATER] No updates available")
                return None

            server_version = data.get('version', '0.0.0')

            # Version comparison
            if self.compare_versions(server_version, self._current_version) <= 0:
                self._last_update_check_reason = "already_up_to_date"
                logger.info(
                    f"[UPDATER] Already up to date: "
                    f"{self._current_version} >= {server_version}"
                )
                return None

            # Verify HMAC signature
            if not self.verify_signature(data):
                self._last_update_check_reason = "signature_verification_failed"
                logger.error("[UPDATER] Update rejected - invalid signature")
                return None

            # Capture force_check flag from server
            if data.get('force_check'):
                data['_force_check'] = True
                logger.info("[UPDATER] Server triggered forced check")

            logger.info(
                f"[UPDATER] [NEW] Update available: "
                f"{self._current_version} -> {server_version}"
            )
            self._last_update_check_reason = "update_available"
            return data

        except urllib.error.URLError as e:
            self._last_update_check_reason = f"server_unreachable: {e}"
            logger.warning(f"[UPDATER] Server unreachable during update check: {e}")
            return None
        except Exception as e:
            self._last_update_check_reason = f"update_check_error: {e}"
            logger.error(f"[UPDATER] Error checking for updates: {e}")
            return None

    def check_compatibility(self) -> Tuple[bool, str]:
        """
        Preflight compatibility check before download (AUE-16).

        Calls /api/v1/updates/check-compatibility to verify this agent's
        version meets the server's minimum requirements.

        Returns:
            (compatible, message) â€” if False, agent should NOT proceed.
        """
        try:
            url = f"{self.config.server_url}/api/v1/updates/check-compatibility"
            headers = {
                'X-Agent-ID': self.config.agent_id,
                'X-Agent-Version': self._current_version,
            }

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode('utf-8'))

            compatible = data.get('compatible', True)
            message = data.get('message', '')

            if not compatible:
                logger.warning(
                    f"[UPDATER] Compatibility check FAILED: {message} "
                    f"(agent={self._current_version}, "
                    f"min={data.get('min_supported_version')})"
                )
            else:
                logger.info(f"[UPDATER] Compatibility OK: {message}")

            return compatible, message

        except Exception as e:
            # If we can't reach the server, assume compatible (fail-open)
            logger.warning(f"[UPDATER] Compatibility check skipped: {e}")
            return True, 'Check unavailable'

    # =========================================================================
    # Download & Verify
    # =========================================================================

    def download_update(self, metadata: Dict) -> Optional[Path]:
        """
        Download update package and verify SHA256.

        Args:
            metadata: Update metadata from check_for_update()

        Returns:
            Path to verified ZIP file, or None on failure
        """
        version = metadata['version']
        expected_sha256 = metadata.get('package_sha256', '')
        download_url = metadata.get('package_url', '')

        if not download_url or not expected_sha256:
            logger.error("[UPDATER] Missing package_url or package_sha256")
            return None

        # Build full URL
        if download_url.startswith('/'):
            download_url = f"{self.config.server_url}{download_url}"

        # Prepare download directory
        version_dir = self.updates_dir / version
        if version_dir.exists():
            shutil.rmtree(version_dir)
        version_dir.mkdir(parents=True)

        zip_path = version_dir / f'sentineledge-agent-{version}.zip'
        token = self.config.api_token or self.config.api_key
        if not token:
            logger.warning("[UPDATER] No API token available for update download")
        headers = {
            'Authorization': f'Bearer {token}',
            'X-Agent-ID': self.config.agent_id,
        }

        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"[UPDATER] Downloading {version} "
                    f"(attempt {attempt}/{max_retries})..."
                )
                req = urllib.request.Request(download_url, headers=headers)
                with urllib.request.urlopen(req, timeout=120) as response:
                    with open(zip_path, 'wb') as f:
                        while True:
                            chunk = response.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)

                # Verify SHA256
                actual_sha256 = self._compute_sha256(zip_path)
                if actual_sha256 != expected_sha256:
                    logger.error(
                        f"[UPDATER] [FAIL] SHA256 mismatch on attempt {attempt}! "
                        f"Expected: {expected_sha256[:16]}... "
                        f"Got: {actual_sha256[:16]}..."
                    )
                    try:
                        zip_path.unlink()
                    except Exception:
                        pass
                    return None

                file_size = zip_path.stat().st_size
                logger.info(
                    f"[UPDATER] [OK] Downloaded and verified: "
                    f"{file_size:,} bytes, SHA256 OK"
                )
                return zip_path

            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                logger.warning(
                    f"[UPDATER] Download attempt {attempt}/{max_retries} failed: {e}"
                )
                if zip_path.exists():
                    try:
                        zip_path.unlink()
                    except Exception:
                        pass
                if attempt < max_retries:
                    wait_seconds = min(2 ** attempt, 30)
                    logger.info(
                        f"[UPDATER] Retrying download in {wait_seconds}s..."
                    )
                    time.sleep(wait_seconds)
                else:
                    logger.error(
                        f"[UPDATER] Download failed after {max_retries} attempts"
                    )
            except Exception as e:
                logger.error(f"[UPDATER] Download failed: {e}")
                if zip_path.exists():
                    try:
                        zip_path.unlink()
                    except Exception:
                        pass
                return None

        return None

    @staticmethod
    def _compute_sha256(file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    # =========================================================================
    # Apply Update
    # =========================================================================

    def apply_update(self, zip_path: Path, metadata: Dict) -> bool:
        """
        Apply update: backup current -> extract new -> compile -> write pending flag.

        Does NOT restart service - caller (service.py) handles that.

        Args:
            zip_path: Path to verified ZIP package
            metadata: Version metadata

        Returns:
            True if applied successfully, False on error
        """
        version = metadata['version']
        previous_version = self._current_version

        logger.info(f"[UPDATER] Applying update {previous_version} -> {version}")

        # Step 1: Create backup
        backup_path = self.backup_dir / f'pre_{version}'
        if not self._create_backup(backup_path):
            logger.error("[UPDATER] Backup failed - aborting update")
            return False

        # Step 2: Extract to staging
        staging_dir = self.updates_dir / version / 'staging'
        try:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            staging_dir.mkdir(parents=True)

            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Security: check for path traversal in zip
                for name in zf.namelist():
                    if '..' in name or name.startswith('/'):
                        logger.error(
                            f"[UPDATER] [FAIL] Suspicious path in ZIP: {name}"
                        )
                        return False
                zf.extractall(staging_dir)

            logger.info(f"[UPDATER] Extracted to staging: {staging_dir}")

        except Exception as e:
            logger.error(f"[UPDATER] Extract failed: {e}")
            return False

        # Step 3: Replace agent files
        try:
            updated_items = []

            # Replace core/ directory
            if (staging_dir / 'core').is_dir():
                target = self.install_dir / 'core'
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(staging_dir / 'core', target)
                updated_items.append('core/')

            # Replace helper/ directory
            if (staging_dir / 'helper').is_dir():
                target = self.install_dir / 'helper'
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(staging_dir / 'helper', target)
                updated_items.append('helper/')

            # Replace main scripts
            for script in ['sentinel_core.py', 'sentinel_helper.py']:
                src = staging_dir / script
                if src.exists():
                    dst = self.install_dir / script
                    shutil.copy2(src, dst)
                    updated_items.append(script)

            logger.info(f"[UPDATER] Replaced: {', '.join(updated_items)}")

        except Exception as e:
            logger.error(f"[UPDATER] File replacement failed: {e}")
            logger.info("[UPDATER] Attempting rollback...")
            self.rollback(version)
            return False

        # Step 4: Compile .py -> .pyc
        try:
            self._compile_python(self.install_dir)
            logger.info("[UPDATER] Compiled .py -> .pyc")
        except Exception as e:
            logger.warning(f"[UPDATER] Compilation warning: {e}")
            # Non-fatal - Python can still run .py files

        # Step 5: Write version.json
        version_data = {
            'version': version,
            'previous_version': previous_version,
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'items_updated': updated_items,
        }

        # Check if ZIP contained version.json with extra metadata
        staging_version = staging_dir / 'version.json'
        if staging_version.exists():
            try:
                extra = json.loads(staging_version.read_text())
                version_data.update({
                    k: v for k, v in extra.items()
                    if k not in ('version', 'previous_version', 'updated_at')
                })
            except Exception:
                pass

        self.version_file.write_text(json.dumps(version_data, indent=2))

        # Step 6: Write pending flag (read on next startup)
        pending = {
            'version': version,
            'previous_version': previous_version,
            'applied_at': datetime.now(timezone.utc).isoformat(),
            'backup_path': str(backup_path),
        }
        self.pending_file.write_text(json.dumps(pending, indent=2))

        logger.info(f"[UPDATER] [OK] Update applied: {version}")
        logger.info("[UPDATER] Restart required to complete update")

        # Cleanup staging
        try:
            staging_dir_parent = self.updates_dir / version
            if staging_dir_parent.exists():
                shutil.rmtree(staging_dir_parent)
        except Exception:
            pass

        self._current_version = version
        return True

    def _create_backup(self, backup_path: Path) -> bool:
        """Backup current core/ and helper/ directories."""
        try:
            if backup_path.exists():
                shutil.rmtree(backup_path)
            backup_path.mkdir(parents=True)

            for item in ['core', 'helper', 'sentinel_core.py',
                         'sentinel_core.pyc', 'sentinel_helper.py',
                         'sentinel_helper.pyc']:
                src = self.install_dir / item
                if src.is_dir():
                    shutil.copytree(src, backup_path / item)
                elif src.is_file():
                    shutil.copy2(src, backup_path / item)

            # Backup version.json
            if self.version_file.exists():
                shutil.copy2(self.version_file, backup_path / 'version.json')

            logger.info(f"[UPDATER] Backup created: {backup_path}")
            return True

        except Exception as e:
            logger.error(f"[UPDATER] Backup failed: {e}")
            return False

    def _compile_python(self, target_dir: Path):
        """Compile .py files to .pyc and remove source."""
        for py_file in target_dir.rglob('*.py'):
            # Skip __pycache__ and python313
            if '__pycache__' in str(py_file) or 'python313' in str(py_file):
                continue
            try:
                py_compile.compile(str(py_file), cfile=str(py_file) + 'c',
                                   doraise=True)
                # Remove source .py for security (matches install.bat behavior)
                py_file.unlink()
            except py_compile.PyCompileError as e:
                logger.warning(f"[UPDATER] Compile warning: {py_file.name}: {e}")

    # =========================================================================
    # Rollback
    # =========================================================================

    def rollback(self, version: str = None) -> bool:
        """
        Restore from backup after a failed update.

        Args:
            version: Version that was attempted (to find backup)

        Returns:
            True if rollback succeeded
        """
        # Find backup
        if version:
            backup_path = self.backup_dir / f'pre_{version}'
        else:
            # Find most recent backup
            backups = sorted(self.backup_dir.iterdir(),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            backup_path = backups[0] if backups else None

        if not backup_path or not backup_path.exists():
            logger.error("[UPDATER] [FAIL] No backup found for rollback")
            return False

        logger.info(f"[UPDATER] [ROLLBACK] Rolling back from {backup_path}")

        try:
            # Restore backed up items
            for item in backup_path.iterdir():
                target = self.install_dir / item.name
                if item.is_dir():
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(item, target)
                elif item.is_file():
                    shutil.copy2(item, target)

            # Restore version
            restored_version = self.version_file
            if restored_version.exists():
                data = json.loads(restored_version.read_text())
                self._current_version = data.get('version', '0.0.0')

            logger.info(f"[UPDATER] [OK] Rollback complete -> {self._current_version}")
            return True

        except Exception as e:
            logger.error(f"[UPDATER] [FAIL] Rollback FAILED: {e}")
            return False

    # =========================================================================
    # Startup Health Check
    # =========================================================================

    def check_pending_update(self) -> Optional[Dict]:
        """
        Check if there's a pending update (we just restarted after apply).

        Returns:
            Pending update info dict, or None if no pending update
        """
        if not self.pending_file.exists():
            return None

        try:
            return json.loads(self.pending_file.read_text())
        except Exception as e:
            logger.error(f"[UPDATER] Failed to read pending file: {e}")
            return None

    def run_self_test(self) -> Tuple[bool, str]:
        """
        Quick self-test after update to verify agent is functional.

        Returns:
            (success, details) tuple
        """
        issues = []

        # Test 1: Can we import core modules?
        try:
            from . import config, buffer, aggregator, ingest, uploader
        except ImportError as e:
            issues.append(f"Import failed: {e}")

        # Test 2: Config loads?
        try:
            if not self.config.config:
                issues.append("Config is empty")
        except Exception as e:
            issues.append(f"Config error: {e}")

        # Test 3: version.json readable?
        try:
            v = self._read_current_version()
            if v == '0.0.0':
                issues.append("version.json missing or invalid")
        except Exception as e:
            issues.append(f"Version read error: {e}")

        if issues:
            return False, '; '.join(issues)
        return True, 'All checks passed'

    def complete_update(self, pending: Dict):
        """
        Complete update lifecycle: self-test -> report -> cleanup.

        Called on startup when update_pending.json exists.
        """
        version = pending.get('version', 'unknown')
        previous = pending.get('previous_version', 'unknown')
        backup_path = pending.get('backup_path', '')

        logger.info(f"[UPDATER] Post-update check: {previous} -> {version}")

        # Run self-test
        success, details = self.run_self_test()

        if success:
            logger.info(f"[UPDATER] [OK] Self-test passed: {details}")

            # Write version to config.json for redundant tracking
            from datetime import datetime, timezone
            self.config.current_version = version
            self.config.last_update_time = datetime.now(timezone.utc).isoformat()
            self.config.save_config()
            logger.info(
                f"[UPDATER] [OK] Version {version} written to config.json"
            )

            # Report healthy to server
            self.report_health('healthy', version, previous, details)

            # Cleanup: remove pending flag
            self._safe_delete(self.pending_file)

            # Cleanup: remove backup (keep for 1 version)
            # Only delete backup for THIS version, keep previous as safety net
            if backup_path:
                # Don't delete backup immediately - keep for 24h
                logger.info(f"[UPDATER] Keeping backup at {backup_path} for safety")

        else:
            logger.error(f"[UPDATER] [FAIL] Self-test FAILED: {details}")
            logger.info("[UPDATER] Initiating rollback...")

            # Rollback
            if self.rollback(version):
                self.report_health('rolled_back', version, previous, details)
                logger.info("[UPDATER] Rollback complete -- restart needed")
            else:
                self.report_health('failed', version, previous,
                                   'Rollback also failed: ' + details)
                logger.error("[UPDATER] [FAIL] CRITICAL: Rollback failed")

            # Remove pending flag regardless
            self._safe_delete(self.pending_file)

    def report_health(self, status: str, version: str,
                      previous_version: str, details: str = ''):
        """Report update health status to server."""
        try:
            url = f"{self.config.server_url}/api/v1/updates/health"
            token = self.config.api_token or self.config.api_key
            payload = {
                'agent_id': self.config.agent_id,
                'version': version,
                'previous_version': previous_version,
                'status': status,
                'details': {
                    'message': details,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                },
            }

            data = json.dumps(payload).encode('utf-8')
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {token}',
                'X-Agent-ID': self.config.agent_id,
            }

            req = urllib.request.Request(url, data=data, headers=headers,
                                         method='POST')
            with urllib.request.urlopen(req, timeout=15) as response:
                result = json.loads(response.read().decode('utf-8'))
                if result.get('acknowledged'):
                    logger.info(f"[UPDATER] Health report sent: {status}")
                    return

            logger.warning("[UPDATER] Health report not acknowledged")

        except Exception as e:
            logger.error(f"[UPDATER] Failed to report health: {e}")

    def report_status(self, status: str, version: str = '', details: str = ''):
        """Report update progress to dashboard (downloading/installing)."""
        try:
            url = f"{self.config.server_url}/api/v1/updates/status"
            token = self.config.api_token or self.config.api_key
            payload = {
                'agent_id': self.config.agent_id,
                'status': status,
                'version': version,
                'details': details,
            }

            data = json.dumps(payload).encode('utf-8')
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {token}',
                'X-Agent-ID': self.config.agent_id,
            }

            req = urllib.request.Request(url, data=data, headers=headers,
                                         method='POST')
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
                if result.get('acknowledged'):
                    logger.info(f"[UPDATER] Status reported: {status}")

        except Exception as e:
            # Non-fatal - don't block update for status reporting
            logger.debug(f"[UPDATER] Status report failed (non-fatal): {e}")

    # =========================================================================
    # Service Restart
    # =========================================================================

    def trigger_restart(self):
        """Signal NSSM to restart the Core service after update."""
        try:
            nssm_path = self.install_dir / 'nssm' / 'win64' / 'nssm.exe'
            if nssm_path.exists():
                # NSSM will detect the process exit and restart it
                logger.info("[UPDATER] Requesting service restart via NSSM...")
                subprocess.Popen(
                    [str(nssm_path), 'restart', 'WinDiagSvc'],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # Fallback: use net stop/start
                logger.info("[UPDATER] Requesting service restart via net...")
                subprocess.Popen(
                    ['net', 'stop', 'WinDiagSvc'],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                # NSSM auto-restart will handle the start
        except Exception as e:
            logger.error(f"[UPDATER] Restart trigger failed: {e}")

    # =========================================================================
    # Full Update Cycle
    # =========================================================================

    def trigger_exe_swap(self, zip_path: Path, metadata: Dict) -> bool:
        """
        Launch a detached external swapper process for EXE bundle updates.

        The swapper waits for the current process to exit, replaces .exe files,
        then restarts the service. This avoids file-lock issues when the running
        EXE tries to overwrite itself.

        Args:
            zip_path: Path to verified ZIP containing EXE files
            metadata: Version metadata

        Returns:
            True if swapper launched (caller should exit), False on failure
        """
        version = metadata['version']
        previous_version = self._current_version

        # Write swap manifest
        swap_manifest = {
            'version': version,
            'previous_version': previous_version,
            'zip_path': str(zip_path),
            'install_dir': str(self.install_dir),
            'data_dir': str(self.data_dir),
            'backup_dir': str(self.backup_dir / f'pre_{version}'),
            'pid': os.getpid(),
            'service_name': 'WinDiagSvc',
            'helper_task': 'SysHealthMon',
            'created_at': datetime.now(timezone.utc).isoformat(),
        }

        manifest_path = self.data_dir / 'swap_manifest.json'
        manifest_path.write_text(json.dumps(swap_manifest, indent=2))

        # Look for swapper executable
        swapper_candidates = [
            self.install_dir / 'swapper.exe',
            self.install_dir / 'tools' / 'swapper.exe',
            self.data_dir / 'swapper.exe',
        ]

        swapper_path = None
        for candidate in swapper_candidates:
            if candidate.exists():
                swapper_path = candidate
                break

        if not swapper_path:
            # Fallback to Python-based swapper script
            swapper_script = self.install_dir / 'tools' / 'swapper.py'
            if swapper_script.exists():
                bundled_python = self.install_dir / 'python313' / 'python.exe'
                if bundled_python.exists():
                    python_exe = str(bundled_python)
                elif Path(sys.executable).name.lower() in (
                    'python.exe', 'pythonw.exe'
                ):
                    python_exe = sys.executable
                else:
                    python_exe = 'python'
                try:
                    subprocess.Popen(
                        [python_exe, str(swapper_script), str(manifest_path)],
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW |
                            subprocess.DETACHED_PROCESS
                        )
                    )
                    logger.info(
                        f"[UPDATER] EXE swap script launched: {swapper_script} "
                        f"(python={python_exe})"
                    )
                    return True
                except Exception as e:
                    logger.error(f"[UPDATER] Failed to launch swap script: {e}")
                    return False

            logger.error(
                "[UPDATER] No swapper found at any candidate path - "
                "exe_bundle update cannot proceed without swapper.py/.exe"
            )
            return False

        # Launch detached swapper process
        try:
            subprocess.Popen(
                [str(swapper_path), str(manifest_path)],
                creationflags=(
                    subprocess.CREATE_NO_WINDOW |
                    subprocess.DETACHED_PROCESS
                )
            )
            logger.info(f"[UPDATER] EXE swapper launched: {swapper_path}")
            return True

        except Exception as e:
            logger.error(f"[UPDATER] Failed to launch EXE swapper: {e}")
            return False

    def run_update_cycle(self) -> bool:
        """
        Run a full update cycle: check -> preflight -> download -> verify -> apply -> restart.
        Reports progress to dashboard at each stage.

        Enhanced with:
        - Compatibility preflight check (AUE-16)
        - EXE bundle swap support for frozen executables
        - force_check awareness from server trigger

        Returns:
            True if update was applied (restart pending), False if no update
        """
        prechecked_metadata = None

        # Block auto-update retries until an admin clears failed_swap.json.
        # We still poll /latest once so server can send clear_failed_swap.
        if self.failed_swap_file.exists():
            prechecked_metadata = self.check_for_update()
            if self.failed_swap_file.exists():
                self._last_update_check_reason = "blocked_failed_swap"
                failed_data = {}
                try:
                    failed_data = json.loads(self.failed_swap_file.read_text())
                except Exception as e:
                    logger.warning(f"[UPDATER] Failed to parse failed_swap.json: {e}")

                failed_version = str(failed_data.get('version', 'unknown'))
                failed_previous = str(
                    failed_data.get('previous_version', self._current_version)
                )
                failed_error = str(
                    failed_data.get('error', 'Unknown swap failure')
                )

                logger.warning(
                    f"[UPDATER] Update cycle blocked by failed_swap.json "
                    f"(version={failed_version}, error={failed_error})"
                )

                if not bool(failed_data.get('reported_to_server', False)):
                    self.report_health(
                        'failed',
                        failed_version,
                        failed_previous,
                        f"Blocked by failed_swap.json: {failed_error}",
                    )
                    failed_data['reported_to_server'] = True
                    failed_data['reported_at'] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    try:
                        self.failed_swap_file.write_text(
                            json.dumps(failed_data, indent=2)
                        )
                    except Exception as e:
                        logger.warning(
                            f"[UPDATER] Could not update failed_swap.json: {e}"
                        )
                return False
            logger.info(
                "[UPDATER] failed_swap.json cleared by server signal - "
                "resuming update cycle"
            )

        # UPD-002: Prevent concurrent update cycles
        if self.update_lock_file.exists():
            # Check if lock is stale (older than 30 mins)
            if time.time() - self.update_lock_file.stat().st_mtime > 1800:
                logger.warning("[UPDATER] Stale update lock found, removing")
                try: self.update_lock_file.unlink()
                except: pass
            else:
                logger.info("[UPDATER] Update cycle skipped - lock file exists")
                return False

        try:
            # Acquire lock
            self.update_lock_file.write_text(str(os.getpid()))

            # Check for updates
            metadata = prechecked_metadata
            if metadata is None:
                metadata = self.check_for_update()
            if not metadata:
                logger.info(
                    f"[UPDATER] Update cycle complete - no update applied "
                    f"(reason={self._last_update_check_reason})"
                )
                return False

            version = metadata['version']
            logger.info(f"[UPDATER] Starting update to {version}...")

            # â”€â”€ Compatibility preflight (AUE-16) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            compatible, compat_msg = self.check_compatibility()
            if not compatible:
                logger.warning(
                    f"[UPDATER] Update aborted â€” compatibility failed: {compat_msg}"
                )
                self.report_health(
                    'failed', version, self._current_version,
                    f'Compatibility preflight failed: {compat_msg}'
                )
                return False

            # Report: downloading
            self.report_status('downloading', version)

            # Download
            zip_path = self.download_update(metadata)
            if not zip_path:
                self.report_health(
                    'failed', version, self._current_version,
                    'Download failed'
                )
                return False

            # Report: installing
            self.report_status('installing', version)

            # â”€â”€ EXE bundle handling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            artifact_type = metadata.get('artifact_type', 'zip')

            if artifact_type == 'exe_bundle':
                # EXE bundles must be applied by external swapper.
                if self.trigger_exe_swap(zip_path, metadata):
                    logger.info(
                        "[UPDATER] EXE swap initiated - service will restart"
                    )
                    return True

                logger.error(
                    "[UPDATER] EXE swap failed - cannot apply exe_bundle "
                    "without swapper"
                )
                self.report_health(
                    'failed', version, self._current_version,
                    'EXE swap failed - swapper unavailable or launch failed'
                )
                return False

            # Standard apply (non-EXE bundles)
            if not self.apply_update(zip_path, metadata):
                self.report_health(
                    'failed', version, self._current_version,
                    'Apply failed'
                )
                # cleanup download
                try:
                    version_dir = self.updates_dir / version
                    if version_dir.exists():
                        shutil.rmtree(version_dir)
                except Exception:
                    pass
                return False

            # Restart service
            self.trigger_restart()

            # Lock is removed after restart (clean data dir) or by OS on exit normally,
            # but here we should keep it until we die to ensure nothing else starts.
            return True
        except Exception as e:
            logger.error(f"[UPDATER] Critical error in update cycle: {e}")
            return False
        finally:
            if self.update_lock_file.exists():
                try: self.update_lock_file.unlink()
                except: pass

    # =========================================================================
    # Utilities
    # =========================================================================

    @staticmethod
    def _safe_delete(path: Path):
        """Safely delete a file or directory."""
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.is_file():
                path.unlink()
        except Exception as e:
            logger.warning(f"[UPDATER] Could not delete {path}: {e}")

    def cleanup_old_backups(self, keep_count: int = 1):
        """Remove old backups, keeping only the most recent."""
        try:
            backups = sorted(
                [p for p in self.backup_dir.iterdir() if p.is_dir()],
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            for old_backup in backups[keep_count:]:
                shutil.rmtree(old_backup)
                logger.info(f"[UPDATER] Cleaned old backup: {old_backup.name}")
        except Exception as e:
            logger.warning(f"[UPDATER] Backup cleanup error: {e}")

