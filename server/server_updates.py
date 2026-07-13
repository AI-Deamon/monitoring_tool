"""
SentinelEdge Auto-Update Server Endpoints (Dashboard-Controlled)
=================================================================
Provides version checking, update download, policy management,
version discovery, history audit, and stale detection endpoints.

Existing Endpoints (preserved):
- GET  /api/v1/updates/latest              - Get update info if target_version is set
- GET  /api/v1/updates/download/<version>  - Download update package (auth required)
- POST /api/v1/updates/health              - Agent reports health after update
- POST /api/v1/updates/status              - Agent reports progress (downloading/installing)
- GET  /api/v1/updates/check-compatibility - Version compatibility check

New Endpoints (Phase 1-3):
- GET  /api/v1/updates/available-versions  - List available versions for dashboard
- GET  /api/v1/updates/policy              - Read global auto-update policy
- PUT  /api/v1/updates/policy              - Update global auto-update policy
- GET  /api/v1/updates/history             - Query update audit trail
- GET  /api/v1/updates/stale              - Report agents stuck in update states
- POST /api/v1/updates/trigger-check       - Trigger immediate update check on agent(s)

Security:
- /latest response includes HMAC-SHA256 signature so agents can verify authenticity
- /download requires JWT authentication (existing require_auth)
- /health requires JWT authentication
- signing_key loaded from UPDATE_SIGNING_KEY env var or server .env
"""

import os
import re
import hmac
import json
import hashlib
import logging
import base64
from pathlib import Path
from datetime import datetime, timezone, timedelta, time as dt_time
from typing import Dict, Any, Optional

from flask import Blueprint, jsonify, request, send_file, current_app
from server_auth import require_auth

logger = logging.getLogger(__name__)

updates_bp = Blueprint('updates', __name__, url_prefix='/api/v1/updates')

UPDATES_DIR = Path(os.environ.get('SENTINELEDGE_UPDATES_DIR',
                                   Path(__file__).parent / 'updates'))
CLEAR_FAILED_SWAP_SENTINEL = "__CLEAR_FAILED_SWAP__"


# =============================================================================
# H-15 FIX: Package Checksum Utilities
# =============================================================================

def calculate_file_sha256(file_path: Path) -> str:
    """
    Calculate SHA256 checksum of a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Hex-encoded SHA256 checksum
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            # Read in 64KB chunks to handle large files
            for chunk in iter(lambda: f.read(65536), b''):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.error(f"[UPDATES] Failed to calculate SHA256 for {file_path}: {e}")
        return ''


def verify_package_checksum(file_path: Path, expected_sha256: str) -> bool:
    """
    Verify package file matches expected SHA256 checksum.
    
    Args:
        file_path: Path to package file
        expected_sha256: Expected SHA256 hex string
        
    Returns:
        True if checksum matches, False otherwise
    """
    if not expected_sha256:
        logger.warning(f"[UPDATES] No checksum provided for {file_path.name}")
        return False
        
    actual_sha256 = calculate_file_sha256(file_path)
    
    if not actual_sha256:
        return False
        
    match = actual_sha256.lower() == expected_sha256.lower()
    
    if not match:
        logger.critical(
            f"[UPDATES] CHECKSUM MISMATCH for {file_path.name}!\n"
            f"  Expected: {expected_sha256}\n"
            f"  Actual:   {actual_sha256}"
        )
    
    return match


# =============================================================================
# HMAC Signing Utilities
# =============================================================================

def _get_signing_key() -> bytes:
    """Get the HMAC signing key for update metadata."""
    key = os.environ.get('UPDATE_SIGNING_KEY', '')
    if not key:
        # Try .env file
        env_path = Path(__file__).parent / '.env'
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith('UPDATE_SIGNING_KEY='):
                    key = line.split('=', 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        logger.warning("[UPDATES] UPDATE_SIGNING_KEY not set — signatures will be empty")
        return b''
    return key.encode('utf-8')


def sign_version_metadata(metadata: Dict) -> str:
    """
    Create HMAC-SHA256 signature of version metadata.
    
    Signs a canonical JSON string of the signable fields:
    version, package_sha256, package_size, min_agent_version, mandatory
    
    Returns base64-encoded signature string.
    """
    key = _get_signing_key()
    if not key:
        return ''
    
    # Canonical payload: deterministic JSON of signable fields
    signable = {
        'version': metadata.get('version', ''),
        'package_sha256': metadata.get('package_sha256', ''),
        'package_size': metadata.get('package_size', 0),
        'min_agent_version': metadata.get('min_agent_version', '2.0.0'),
        'mandatory': metadata.get('mandatory', False),
    }
    canonical = json.dumps(signable, sort_keys=True, separators=(',', ':'))
    
    sig = hmac.new(key, canonical.encode('utf-8'), hashlib.sha256).digest()
    return base64.b64encode(sig).decode('ascii')


def _get_updates_config() -> Dict[str, Any]:
    """Get updates configuration from app config or defaults."""
    return {
        'updates_dir': Path(current_app.config.get('UPDATES_DIR', UPDATES_DIR)),
        'min_version': current_app.config.get('UPDATES_MIN_VERSION', '2.0.0'),
    }


def _parse_version(v: str) -> tuple:
    """Parse version string to comparable tuple."""
    try:
        return tuple(int(x) for x in v.split('.')[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _log_update_event(agent_id: str, event: str, version: str, details: str = ''):
    """Log update event to file AND database for audit trail."""
    # File-based log (original)
    try:
        log_file = UPDATES_DIR / 'update_log.jsonl'
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'agent_id': agent_id,
            'event': event,
            'version': version,
            'details': details,
        }
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        logger.error(f"[UPDATES] Failed to log event to file: {e}")

    # Database audit (new — write to update_history)
    _write_update_history(agent_id, event, version, details)


def _write_update_history(agent_id: str, event: str, version: str, details: str = ''):
    """Write an audit row to update_history table."""
    try:
        import server_models
        from extensions import db

        # Map event names to status values
        status_map = {
            'version_check': 'pending',
            'status_downloading': 'downloading',
            'status_installing': 'installing',
            'health_healthy': 'success',
            'health_failed': 'failed',
            'health_rolled_back': 'rolled_back',
            'trigger_check': 'pending',
        }
        status = status_map.get(event)
        if not status:
            return  # Not a lifecycle event worth auditing

        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if not agent:
            return

        now = datetime.now(timezone.utc)
        history = server_models.UpdateHistory(
            agent_id=agent_id,
            from_version=agent.version,
            to_version=version,
            status=status,
            started_at=now if status in ('pending', 'downloading', 'installing') else None,
            completed_at=now if status in ('success', 'failed', 'rolled_back') else None,
            error_message=details if status in ('failed', 'rolled_back') else None,
        )
        db.session.add(history)
        db.session.commit()
    except Exception as e:
        logger.error(f"[UPDATES] Failed to write update_history: {e}")
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass


def _get_agent_from_db(agent_id: str):
    """Helper to get agent record from DB."""
    try:
        import uuid as _uuid
        import server_models
        # agents.agent_id is a native UUID column; bind a uuid.UUID so the
        # lookup works on every dialect (SQLite's UUID binding rejects str).
        try:
            agent_id = _uuid.UUID(str(agent_id))
        except (ValueError, AttributeError, TypeError):
            pass  # non-UUID id - let the query match (or miss) as-is
        return server_models.Agent.query.filter_by(agent_id=agent_id).first()
    except Exception as e:
        logger.error(f"[UPDATES] DB lookup failed for {agent_id}: {e}")
        return None


def _admin_api_guard():
    """Authorize an admin-only JSON endpoint.

    Returns None when the caller is an authenticated admin, otherwise an
    (response, status) tuple to return directly.

    Fails CLOSED: any error while resolving the user denies the request.
    (The previous inline checks only tested for `user_id in session`, so any
    logged-in non-admin could change global update policy, and they swallowed
    import errors with `pass`, skipping authorization entirely.)
    """
    try:
        from flask import session
        from auth import DashboardUser

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Authentication required'}), 401

        user = DashboardUser.query.filter_by(id=user_id).first()
        if not user or not user.is_active:
            return jsonify({'error': 'Authentication required'}), 401

        # Password change / deactivation invalidates existing sessions.
        if user.session_version != session.get('session_version', 1):
            return jsonify({'error': 'Session expired'}), 401

        if user.role != 'admin':
            return jsonify({'error': 'Administrator access required'}), 403

        return None
    except Exception as e:
        logger.error(f"[UPDATES] Admin authorization failed: {e}")
        return jsonify({'error': 'Authorization unavailable'}), 403


def _get_global_policy():
    """Get the singleton global policy row, creating default if missing."""
    try:
        import server_models
        from extensions import db
        policy = server_models.UpdateGlobalPolicy.query.get(1)
        if not policy:
            policy = server_models.UpdateGlobalPolicy(id=1)
            db.session.add(policy)
            db.session.commit()
        return policy
    except Exception as e:
        logger.error(f"[UPDATES] Policy lookup error: {e}")
        return None


def _is_within_update_window(policy) -> bool:
    """Check if current time is within the configured update window."""
    if not policy or not policy.update_window_enabled:
        return True  # No window = always allowed

    if not policy.update_window_start or not policy.update_window_end:
        return True

    try:
        import pytz
        tz = pytz.timezone(policy.update_window_tz or 'UTC')
        now_local = datetime.now(tz).time()
    except Exception:
        now_local = datetime.now(timezone.utc).time()

    start = policy.update_window_start
    end = policy.update_window_end

    if start <= end:
        return start <= now_local <= end
    else:
        # Window spans midnight (e.g., 22:00 to 06:00)
        return now_local >= start or now_local <= end


# =============================================================================
# Existing Endpoints (Preserved + Enhanced)
# =============================================================================

@updates_bp.route('/latest', methods=['GET'])
def get_latest_version():
    """
    Dashboard-controlled update check — enhanced with policy enforcement.
    
    Agent sends X-Agent-ID and X-Agent-Version headers.
    Server checks:
    1. Global policy (auto_update_enabled, update window, canary %)
    2. Agent has a target_version set in DB
    3. Target_version > current_version
    4. Package is available on filesystem
    
    Response includes HMAC signature for agent verification.
    """
    try:
        agent_id = request.headers.get('X-Agent-ID', 'unknown')
        current_ver = request.headers.get('X-Agent-Version', 'unknown')
        
        config = _get_updates_config()
        
        # Capture control flags before clearing them
        force_flag = False
        clear_failed_swap_flag = False
        agent = _get_agent_from_db(agent_id)
        if agent:
            try:
                from extensions import db
                force_flag = bool(agent.force_update_check)
                clear_failed_swap_flag = (
                    agent.last_update_error == CLEAR_FAILED_SWAP_SENTINEL
                )
                agent.last_update_check = datetime.utcnow()

                # FIX 3: Update agent's current version on every poll
                # This keeps the dashboard accurate between updates
                if current_ver and current_ver != 'unknown':
                    if agent.version != current_ver:
                        agent.version = current_ver
                        logger.debug(
                            f"[UPDATES] Updated agent.version = {current_ver} "
                            f"for agent={agent_id}"
                        )

                # Clear force flag after capturing
                if agent.force_update_check:
                    agent.force_update_check = False
                if clear_failed_swap_flag:
                    agent.last_update_error = None
                db.session.commit()
            except Exception:
                pass

        def _no_update(message: str):
            payload = {
                'update_available': False,
                'message': message
            }
            if force_flag:
                payload['force_check'] = True
            if clear_failed_swap_flag:
                payload['clear_failed_swap'] = True
            return jsonify(payload)
        
        # ── Policy gate ─────────────────────────────────────────────
        policy = _get_global_policy()
        
        # Fix #4: Enforce auto_update_enabled
        if policy and not policy.auto_update_enabled:
            logger.debug(
                f"[UPDATES] Auto-update disabled globally, agent={agent_id}"
            )
            return _no_update('Auto-update is disabled by admin policy')
        
        # Check update window (Phase 2: AUE-11)
        if policy and not _is_within_update_window(policy):
            logger.debug(
                f"[UPDATES] Outside update window for agent={agent_id}"
            )
            return _no_update('Outside update window')
        
        # ── Target version check ────────────────────────────────────
        target_version = None
        if agent and agent.target_version:
            target_version = agent.target_version
        
        # If no target set, or agent is already at target — no update
        if not target_version or target_version == current_ver:
            logger.debug(
                f"[UPDATES] No update for agent={agent_id}, "
                f"current={current_ver}, target={target_version}"
            )
            return _no_update('Agent is up to date')
        
        # Check if target is actually newer
        if _parse_version(target_version) <= _parse_version(current_ver):
            logger.debug(
                f"[UPDATES] Target {target_version} <= current {current_ver}, skipping"
            )
            return _no_update('Agent version is current or newer')
        
        # ── Compatibility preflight (Phase 2: AUE-16) ──────────────
        if policy and policy.min_version:
            if _parse_version(current_ver) < _parse_version(policy.min_version):
                logger.warning(
                    f"[UPDATES] Agent {agent_id} version {current_ver} below "
                    f"min_version {policy.min_version} — needs manual update"
                )
                return _no_update(
                    f'Agent version too old for auto-update. '
                    f'Minimum: {policy.min_version}'
                )
        
        # Load version metadata from latest.json
        version_file = config['updates_dir'] / 'latest.json'
        if not version_file.exists():
            logger.warning("[UPDATES] latest.json not found")
            return _no_update('Update package not available on server')
        
        version_info = json.loads(version_file.read_text())
        package_version = version_info.get('version', 'unknown')
        
        # Only serve if the package matches target_version
        if package_version != target_version:
            logger.warning(
                f"[UPDATES] Package version {package_version} != "
                f"target {target_version} for agent {agent_id}"
            )
            return _no_update(
                f'Target {target_version} not yet available as package'
            )
        
        # Build response
        version_info['package_url'] = f'/api/v1/updates/download/{package_version}'
        version_info['update_available'] = True
        version_info['signature'] = sign_version_metadata(version_info)
        
        # Include force_update_check flag (captured before clearing)
        if force_flag:
            version_info['force_check'] = True
        if clear_failed_swap_flag:
            version_info['clear_failed_swap'] = True
        
        logger.info(
            f"[UPDATES] Update available: agent={agent_id}, "
            f"current={current_ver} → target={target_version}"
        )
        _log_update_event(agent_id, 'version_check', target_version,
                          f'from={current_ver}')
        
        return jsonify(version_info)

    except Exception as e:
        logger.error(f"[UPDATES] Error getting latest version: {e}")
        return jsonify({'error': 'server_error', 'message': str(e)}), 500


@updates_bp.route('/download/<version>', methods=['GET'])
@require_auth
def download_update(version: str):
    """
    Download update package with SHA256 verification.
    Requires JWT/API-key authentication.
    """

    try:
        config = _get_updates_config()

        # Sanitize version — prevent path traversal
        safe_version = ''.join(c for c in version if c.isalnum() or c in '.-_')
        if safe_version != version:
            logger.warning(f"[UPDATES] Invalid version format: {version}")
            return jsonify({'error': 'invalid_version'}), 400

        package_file = config['updates_dir'] / f'sentineledge-agent-{safe_version}.zip'

        if not package_file.exists():
            logger.warning(f"[UPDATES] Package not found: {package_file}")
            return jsonify({'error': 'version_not_found'}), 404

        # H-15 FIX: Verify package integrity before sending
        metadata_file = config['updates_dir'] / f'{safe_version}.json'
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text())
                expected_sha256 = metadata.get('package_sha256')
                
                if expected_sha256:
                    if not verify_package_checksum(package_file, expected_sha256):
                        logger.error(f"[UPDATES] Package integrity check failed for {safe_version}")
                        return jsonify({'error': 'integrity_check_failed'}), 500
                    logger.debug(f"[UPDATES] Package integrity verified for {safe_version}")
            except Exception as e:
                logger.warning(f"[UPDATES] Could not verify package integrity: {e}")

        agent_id = request.headers.get('X-Agent-ID', 'unknown')
        file_size = package_file.stat().st_size
        logger.info(
            f"[UPDATES] Download: agent={agent_id}, "
            f"version={version}, size={file_size}"
        )
        _log_update_event(agent_id, 'download', version,
                          f'size={file_size}')

        return send_file(
            package_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'sentineledge-agent-{safe_version}.zip'
        )

    except Exception as e:
        logger.error(f"[UPDATES] Download error for {version}: {e}")
        return jsonify({'error': 'download_failed', 'message': str(e)}), 500


@updates_bp.route('/status', methods=['POST'])
@require_auth
def report_update_status():
    """
    Agent reports update progress to dashboard.
    Now also writes to update_history audit table.
    
    Request body:
    {
        "agent_id": "uuid",
        "status": "downloading" | "installing",
        "version": "2.5.0",
        "details": "optional message"
    }
    """
    try:
        data = request.get_json() or {}
        agent_id = data.get('agent_id', 'unknown')
        status = data.get('status', 'unknown')
        version = data.get('version', 'unknown')
        details = data.get('details', '')
        
        valid_statuses = ('downloading', 'installing')
        if status not in valid_statuses:
            return jsonify({
                'error': f'Invalid status. Must be one of: {valid_statuses}'
            }), 400
        
        # Update DB
        agent = _get_agent_from_db(agent_id)
        if agent:
            try:
                from extensions import db
                agent.update_status = status
                db.session.commit()
                logger.info(
                    f"[UPDATES] Agent {agent_id} status → {status} "
                    f"(target={version})"
                )
            except Exception as e:
                logger.error(f"[UPDATES] DB update failed: {e}")
        
        _log_update_event(agent_id, f'status_{status}', version, details)
        
        return jsonify({
            'acknowledged': True,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    
    except Exception as e:
        logger.error(f"[UPDATES] Status report error: {e}")
        return jsonify({'error': 'failed', 'message': str(e)}), 500


@updates_bp.route('/health', methods=['POST'])
@require_auth
def report_update_health():
    """
    Agent reports health after update completion.
    Now also writes completion row to update_history.
    
    Request body:
    {
        "agent_id": "uuid",
        "version": "2.5.0",
        "previous_version": "2.4.0",
        "status": "healthy" | "failed" | "rolled_back",
        "details": {...}
    }
    """
    try:
        data = request.get_json() or {}

        agent_id = data.get('agent_id', 'unknown')
        version = data.get('version', 'unknown')
        prev_version = data.get('previous_version', 'unknown')
        status = data.get('status', 'unknown')
        details = data.get('details', {})

        if status == 'healthy':
            logger.info(
                f"[UPDATES] ✅ Agent {agent_id} updated "
                f"{prev_version} → {version} successfully"
            )
        elif status == 'rolled_back':
            logger.warning(
                f"[UPDATES] ⚠️ Agent {agent_id} ROLLED BACK "
                f"{version} → {prev_version}"
            )
        else:
            logger.error(
                f"[UPDATES] ❌ Agent {agent_id} update to {version} "
                f"FAILED: {json.dumps(details)}"
            )

        _log_update_event(agent_id, f'health_{status}', version,
                          json.dumps(details))

        # Update agent record
        agent = _get_agent_from_db(agent_id)
        if agent:
            try:
                from extensions import db
                
                if status == 'healthy':
                    agent.version = version
                    agent.update_status = 'up_to_date'
                    agent.target_version = None  # Clear — update complete
                    agent.update_attempts = 0
                    agent.last_update_error = None
                    logger.info(
                        f"[UPDATES] Agent {agent_id} version "
                        f"updated to {version} in DB"
                    )
                elif status == 'rolled_back':
                    agent.update_status = 'rolled_back'
                    agent.update_attempts = (agent.update_attempts or 0) + 1
                    agent.last_update_error = f"Rolled back to {prev_version}"
                else:  # failed
                    agent.update_status = 'failed'
                    agent.update_attempts = (agent.update_attempts or 0) + 1
                    agent.last_update_error = json.dumps(details)[:500]
                
                db.session.commit()
            except Exception as e:
                logger.error(f"[UPDATES] Failed to update agent record: {e}")

        return jsonify({
            'acknowledged': True,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    except Exception as e:
        logger.error(f"[UPDATES] Health report error: {e}")
        return jsonify({'error': 'failed', 'message': str(e)}), 500


@updates_bp.route('/check-compatibility', methods=['GET'])
def check_compatibility():
    """Check if agent version is compatible with server."""
    try:
        agent_version = request.headers.get('X-Agent-Version', '0.0.0')
        config = _get_updates_config()
        min_version = config['min_version']

        # Fix #5: Also check against package-specific min_agent_version
        package_min = min_version
        try:
            version_file = config['updates_dir'] / 'latest.json'
            if version_file.exists():
                info = json.loads(version_file.read_text())
                pkg_min = info.get('min_agent_version')
                if pkg_min and _parse_version(pkg_min) > _parse_version(min_version):
                    package_min = pkg_min
        except Exception:
            pass

        is_compatible = (
            _parse_version(agent_version) >= _parse_version(package_min)
        )

        return jsonify({
            'compatible': is_compatible,
            'agent_version': agent_version,
            'min_supported_version': package_min,
            'message': ('OK' if is_compatible
                        else f'Please update to at least {package_min}')
        })

    except Exception as e:
        logger.error(f"[UPDATES] Compatibility check error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# New Endpoints — Phase 1 Foundation
# =============================================================================

@updates_bp.route('/available-versions', methods=['GET'])
def get_available_versions():
    """
    List available update versions for dashboard selection (AUE-12).
    
    Reads from update_versions DB table, falls back to filesystem scan.
    
    Query params:
        active_only (bool): Filter to active versions only (default: true)
    
    Response:
    {
        "versions": [
            {
                "version": "2.5.0",
                "artifact_type": "exe_bundle",
                "package_size": 12345678,
                "mandatory": false,
                "changelog": "...",
                "release_date": "2026-03-01T...",
                "is_active": true
            }
        ]
    }
    """
    try:
        import server_models

        active_only = request.args.get('active_only', 'true').lower() == 'true'

        query = server_models.UpdateVersion.query
        if active_only:
            query = query.filter_by(is_active=True)

        db_versions = query.order_by(
            server_models.UpdateVersion.version.desc()
        ).all()

        if db_versions:
            versions = [v.to_dict() for v in db_versions]
        else:
            # Filesystem fallback: scan updates directory
            versions = _scan_filesystem_versions()

        return jsonify({'versions': versions})

    except Exception as e:
        logger.error(f"[UPDATES] Available versions error: {e}")
        return jsonify({'versions': [], 'error': str(e)}), 200


def _scan_filesystem_versions():
    """Scan updates directory for available packages as fallback."""
    versions = []
    try:
        config = _get_updates_config()
        updates_dir = config['updates_dir']

        if not updates_dir.exists():
            return versions

        # Read latest.json if it exists
        latest_file = updates_dir / 'latest.json'
        if latest_file.exists():
            info = json.loads(latest_file.read_text())
            versions.append({
                'version': info.get('version', 'unknown'),
                'artifact_type': info.get('artifact_type', 'exe_bundle'),
                'package_size': info.get('package_size'),
                'package_sha256': info.get('package_sha256'),
                'min_agent_version': info.get('min_agent_version'),
                'mandatory': info.get('mandatory', False),
                'changelog': info.get('changelog', ''),
                'is_active': True,
            })

        # Also scan for zip files not in latest.json
        for zip_file in updates_dir.glob('sentineledge-agent-*.zip'):
            match = re.search(r'sentineledge-agent-(.+)\.zip', zip_file.name)
            if match:
                v = match.group(1)
                if not any(ver.get('version') == v for ver in versions):
                    versions.append({
                        'version': v,
                        'artifact_type': 'exe_bundle',
                        'package_size': zip_file.stat().st_size,
                        'is_active': True,
                    })
    except Exception as e:
        logger.error(f"[UPDATES] Filesystem scan error: {e}")

    return versions


@updates_bp.route('/policy', methods=['GET'])
def get_update_policy():
    """
    Get the global auto-update policy (AUE-14).
    
    Response:
    {
        "auto_update_enabled": false,
        "channel": "stable",
        "min_version": null,
        "canary_percentage": 0,
        "update_window_enabled": false,
        "update_window_start": null,
        "update_window_end": null,
        "update_window_tz": "UTC"
    }
    """
    try:
        policy = _get_global_policy()
        if not policy:
            return jsonify({'error': 'Policy not found'}), 500

        return jsonify(policy.to_dict())

    except Exception as e:
        logger.error(f"[UPDATES] Get policy error: {e}")
        return jsonify({'error': str(e)}), 500


@updates_bp.route('/policy', methods=['PUT'])
def update_policy():
    """
    Update the global auto-update policy (AUE-14). Admin-only.
    """
    denied = _admin_api_guard()
    if denied:
        return denied

    try:
        from extensions import db
        data = request.get_json() or {}

        policy = _get_global_policy()
        if not policy:
            return jsonify({'error': 'Policy not found'}), 500

        # Apply only provided fields
        if 'auto_update_enabled' in data:
            policy.auto_update_enabled = bool(data['auto_update_enabled'])
        if 'channel' in data:
            if data['channel'] in ('stable', 'beta', 'edge'):
                policy.channel = data['channel']
            else:
                return jsonify({'error': 'Invalid channel. Must be: stable, beta, edge'}), 400
        if 'min_version' in data:
            policy.min_version = data['min_version']
        if 'canary_percentage' in data:
            pct = int(data['canary_percentage'])
            if 0 <= pct <= 100:
                policy.canary_percentage = pct
            else:
                return jsonify({'error': 'canary_percentage must be 0-100'}), 400
        if 'update_window_enabled' in data:
            policy.update_window_enabled = bool(data['update_window_enabled'])
        if 'update_window_start' in data:
            try:
                h, m = data['update_window_start'].split(':')
                policy.update_window_start = dt_time(int(h), int(m))
            except (ValueError, AttributeError):
                return jsonify({'error': 'Invalid update_window_start. Use HH:MM'}), 400
        if 'update_window_end' in data:
            try:
                h, m = data['update_window_end'].split(':')
                policy.update_window_end = dt_time(int(h), int(m))
            except (ValueError, AttributeError):
                return jsonify({'error': 'Invalid update_window_end. Use HH:MM'}), 400
        if 'update_window_tz' in data:
            policy.update_window_tz = data['update_window_tz']

        policy.updated_at = datetime.now(timezone.utc)

        db.session.commit()
        logger.info(f"[UPDATES] Policy updated: {data}")

        return jsonify(policy.to_dict())

    except Exception as e:
        logger.error(f"[UPDATES] Update policy error: {e}")
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500


@updates_bp.route('/history', methods=['GET'])
def get_update_history():
    """
    Query update audit trail (AUE-09). Admin-only.
    """
    # Admin auth
    try:
        from flask import session
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
    except Exception:
        pass

    try:
        import server_models

        agent_id = request.args.get('agent_id')
        limit = min(int(request.args.get('limit', 50)), 200)
        status_filter = request.args.get('status')

        query = server_models.UpdateHistory.query

        if agent_id:
            query = query.filter_by(agent_id=agent_id)
        if status_filter:
            query = query.filter_by(status=status_filter)

        total = query.count()
        history = query.order_by(
            server_models.UpdateHistory.created_at.desc()
        ).limit(limit).all()

        return jsonify({
            'history': [h.to_dict() for h in history],
            'total': total
        })

    except Exception as e:
        logger.error(f"[UPDATES] History query error: {e}")
        return jsonify({'history': [], 'total': 0, 'error': str(e)}), 200


@updates_bp.route('/stale', methods=['GET'])
def get_stale_updates():
    """
    Report agents stuck in update states for >30 minutes (AUE-13). Admin-only.
    """
    # Admin auth
    try:
        from flask import session
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
    except Exception:
        pass

    try:
        import server_models

        threshold_minutes = int(request.args.get('threshold', 30))
        cutoff = datetime.utcnow() - timedelta(minutes=threshold_minutes)

        stale_agents = server_models.Agent.query.filter(
            server_models.Agent.update_status.in_(['pending', 'downloading', 'installing']),
            server_models.Agent.last_update_check < cutoff
        ).all()

        result = []
        for agent in stale_agents:
            minutes_stuck = 0
            if agent.last_update_check:
                _luc = agent.last_update_check
                if _luc.tzinfo is None:
                    _luc = _luc.replace(tzinfo=timezone.utc)
                minutes_stuck = int(
                    (datetime.now(timezone.utc) - _luc).total_seconds() / 60
                )
            result.append({
                'agent_id': str(agent.agent_id),
                'hostname': agent.hostname or 'Unknown',
                'update_status': agent.update_status,
                'target_version': agent.target_version,
                'last_update_check': agent.last_update_check.isoformat() if agent.last_update_check else None,
                'minutes_stuck': minutes_stuck,
                'update_attempts': agent.update_attempts or 0,
            })

        return jsonify({
            'stale_agents': result,
            'stale_count': len(result),
            'threshold_minutes': threshold_minutes
        })

    except Exception as e:
        logger.error(f"[UPDATES] Stale check error: {e}")
        return jsonify({'stale_agents': [], 'stale_count': 0, 'error': str(e)}), 200


# =============================================================================
# Phase 3 — Advanced Control
# =============================================================================

@updates_bp.route('/trigger-check', methods=['POST'])
def trigger_update_check():
    """
    Trigger immediate update check on agent(s) (AUE-15). Admin-only.
    """
    denied = _admin_api_guard()
    if denied:
        return denied

    try:
        import server_models
        from extensions import db

        data = request.get_json() or {}
        agent_id = data.get('agent_id')
        trigger_all = data.get('all', False)

        if not agent_id and not trigger_all:
            return jsonify({'error': 'Provide agent_id or all=true'}), 400

        triggered = 0

        if trigger_all:
            agents = server_models.Agent.query.filter(
                server_models.Agent.status == 'active'
            ).all()
            for agent in agents:
                agent.force_update_check = True
                triggered += 1
        else:
            agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
            if not agent:
                return jsonify({'error': 'Agent not found'}), 404
            agent.force_update_check = True
            triggered = 1
            _log_update_event(agent_id, 'trigger_check', agent.target_version or '',
                              'Admin triggered immediate check')

        db.session.commit()
        logger.info(f"[UPDATES] Trigger-check: {triggered} agent(s)")

        return jsonify({
            'triggered': triggered,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    except Exception as e:
        logger.error(f"[UPDATES] Trigger-check error: {e}")
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500


@updates_bp.route('/clear-failure/<agent_id>', methods=['POST'])
def clear_failure(agent_id: str):
    """
    Queue a one-time clear_failed_swap signal for an agent. Admin-only.
    """
    denied = _admin_api_guard()
    if denied:
        return denied

    try:
        agent = _get_agent_from_db(agent_id)
        if not agent:
            return jsonify({'error': 'Agent not found'}), 404

        from extensions import db
        agent.force_update_check = True
        agent.last_update_error = CLEAR_FAILED_SWAP_SENTINEL
        db.session.commit()

        _log_update_event(
            agent_id,
            'trigger_check',
            agent.target_version or '',
            'Admin requested clear_failed_swap'
        )
        logger.info(f"[UPDATES] clear-failure queued for agent={agent_id}")

        return jsonify({
            'cleared': True,
            'message': 'Agent will clear failed swap gate on next check',
            'agent_id': agent_id,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    except Exception as e:
        logger.error(f"[UPDATES] clear-failure error for {agent_id}: {e}")
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Initialization
# =============================================================================

def init_updates_directory():
    """Create updates directory structure if it doesn't exist."""
    try:
        UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"[UPDATES] Directory ready: {UPDATES_DIR}")
    except Exception as e:
        logger.warning(f"[UPDATES] Could not create updates directory: {e}")


init_updates_directory()
