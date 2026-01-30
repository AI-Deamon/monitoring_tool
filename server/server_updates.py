"""
SentinelEdge Auto-Update Server Endpoints
==========================================
Provides version checking and update download endpoints.

Endpoints:
- GET /api/v1/updates/latest - Get latest version info (signed)
- GET /api/v1/updates/download/<version> - Download update package
- GET /api/v1/updates/health - Health check for updated agents

This module is OPTIONAL - server works without it for legacy agents.
"""

import os
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from flask import Blueprint, jsonify, request, send_file, current_app

logger = logging.getLogger(__name__)

# Blueprint for auto-update endpoints
updates_bp = Blueprint('updates', __name__, url_prefix='/api/v1/updates')

# Configuration (can be overridden via environment)
UPDATES_DIR = Path(os.environ.get('SENTINELEDGE_UPDATES_DIR', 
                                   Path(__file__).parent / 'updates'))
VERSION_FILE = UPDATES_DIR / 'latest.json'


def get_updates_config() -> Dict[str, Any]:
    """Get updates configuration from app config or defaults."""
    return {
        'updates_dir': Path(current_app.config.get('UPDATES_DIR', UPDATES_DIR)),
        'require_auth': current_app.config.get('UPDATES_REQUIRE_AUTH', True),
        'min_version': current_app.config.get('UPDATES_MIN_VERSION', '2.0.0'),
    }


def verify_agent_auth(request) -> bool:
    """
    Verify agent is authenticated for updates.
    Uses existing agent authentication from the server.
    """
    config = get_updates_config()
    if not config['require_auth']:
        return True
    
    # Check for API key in header
    api_key = request.headers.get('X-Agent-Key') or request.headers.get('Authorization')
    if not api_key:
        return False
    
    # Use existing agent verification (imported from server_app)
    try:
        from server_app import verify_agent_api_key
        return verify_agent_api_key(api_key)
    except ImportError:
        # Fall back to simple check if function not available
        return bool(api_key)


@updates_bp.route('/latest', methods=['GET'])
def get_latest_version():
    """
    Get latest version information (signed metadata).
    
    Response:
    {
        "version": "2.5.0",
        "release_date": "2026-01-09T10:00:00Z",
        "min_agent_version": "2.0.0",
        "package_url": "/api/v1/updates/download/2.5.0",
        "package_sha256": "abc123...",
        "package_size": 12345678,
        "signature": "base64_signature...",
        "key_id": "key_2026_01",
        "changelog": "Bug fixes and performance improvements",
        "mandatory": false
    }
    """
    try:
        config = get_updates_config()
        version_file = config['updates_dir'] / 'latest.json'
        
        if not version_file.exists():
            logger.warning("[UPDATES] No updates available - latest.json not found")
            return jsonify({
                'error': 'no_updates',
                'message': 'No updates available'
            }), 404
        
        # Load version info
        version_info = json.loads(version_file.read_text())
        
        # Add download URL
        version = version_info.get('version', 'unknown')
        version_info['package_url'] = f'/api/v1/updates/download/{version}'
        
        # Log request (for analytics)
        agent_id = request.headers.get('X-Agent-ID', 'unknown')
        current_version = request.headers.get('X-Agent-Version', 'unknown')
        logger.info(f"[UPDATES] Version check: agent={agent_id}, current={current_version}, latest={version}")
        
        return jsonify(version_info)
        
    except Exception as e:
        logger.error(f"[UPDATES] Error getting latest version: {e}")
        return jsonify({'error': 'server_error', 'message': str(e)}), 500


@updates_bp.route('/download/<version>', methods=['GET'])
def download_update(version: str):
    """
    Download update package for specified version.
    
    Requires authentication.
    Returns the signed ZIP package.
    """
    # Verify authentication
    if not verify_agent_auth(request):
        logger.warning(f"[UPDATES] Unauthorized download attempt for version {version}")
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        config = get_updates_config()
        
        # Sanitize version to prevent path traversal
        safe_version = ''.join(c for c in version if c.isalnum() or c in '.-_')
        if safe_version != version:
            logger.warning(f"[UPDATES] Invalid version format: {version}")
            return jsonify({'error': 'invalid_version'}), 400
        
        # Find package file
        package_file = config['updates_dir'] / f'sentineledge-agent-{safe_version}.zip'
        
        if not package_file.exists():
            logger.warning(f"[UPDATES] Package not found: {package_file}")
            return jsonify({'error': 'version_not_found'}), 404
        
        # Log download
        agent_id = request.headers.get('X-Agent-ID', 'unknown')
        logger.info(f"[UPDATES] Download started: agent={agent_id}, version={version}")
        
        return send_file(
            package_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'sentineledge-agent-{safe_version}.zip'
        )
        
    except Exception as e:
        logger.error(f"[UPDATES] Error downloading version {version}: {e}")
        return jsonify({'error': 'download_failed', 'message': str(e)}), 500


@updates_bp.route('/health', methods=['POST'])
def report_update_health():
    """
    Agent reports health after update.
    
    Request body:
    {
        "agent_id": "uuid",
        "version": "2.5.0",
        "status": "healthy" | "failed",
        "details": {...}
    }
    """
    try:
        data = request.get_json()
        
        agent_id = data.get('agent_id', 'unknown')
        version = data.get('version', 'unknown')
        status = data.get('status', 'unknown')
        details = data.get('details', {})
        
        logger.info(
            f"[UPDATES] Health report: agent={agent_id}, version={version}, "
            f"status={status}, details={json.dumps(details)}"
        )
        
        # Store health report (could be used for analytics/rollback decisions)
        # For now, just acknowledge
        
        return jsonify({
            'acknowledged': True,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
    except Exception as e:
        logger.error(f"[UPDATES] Error processing health report: {e}")
        return jsonify({'error': 'failed', 'message': str(e)}), 500


@updates_bp.route('/check-compatibility', methods=['GET'])
def check_compatibility():
    """
    Check if agent version is compatible with server.
    Used by older agents to check if they need manual update.
    """
    try:
        agent_version = request.headers.get('X-Agent-Version', '0.0.0')
        config = get_updates_config()
        min_version = config['min_version']
        
        # Simple version comparison
        def parse_version(v):
            try:
                return tuple(int(x) for x in v.split('.')[:3])
            except:
                return (0, 0, 0)
        
        is_compatible = parse_version(agent_version) >= parse_version(min_version)
        
        return jsonify({
            'compatible': is_compatible,
            'agent_version': agent_version,
            'min_supported_version': min_version,
            'message': 'OK' if is_compatible else f'Please update to at least {min_version}'
        })
        
    except Exception as e:
        logger.error(f"[UPDATES] Compatibility check error: {e}")
        return jsonify({'error': str(e)}), 500


def init_updates_directory():
    """Create updates directory structure if it doesn't exist."""
    try:
        UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"[UPDATES] Updates directory ready: {UPDATES_DIR}")
    except Exception as e:
        logger.warning(f"[UPDATES] Could not create updates directory: {e}")


# Initialize on module load
init_updates_directory()
