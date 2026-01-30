import logging
import json
import os
import re
from datetime import datetime, date, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app
from extensions import db
import server_models
from extensions import db
from server_auth import generate_api_key, generate_api_token, require_auth
from schemas import RegisterSchema, AppInventorySchema, DomainUsageSchema, HeartbeatSchema
from pydantic import ValidationError
from server_analytics import process_heartbeat_analytics

logger = logging.getLogger(__name__)
bp = Blueprint('api', __name__)
telemetry_bp = Blueprint('telemetry_api', __name__)


# =============================================================================
# SEC-010: LOG REDACTION UTILITY
# =============================================================================
# Never log full secrets, tokens, or API keys. Use this utility for safe logging.
# =============================================================================

def redact_secret(value: str, show_chars: int = 8) -> str:
    """
    Redact a secret value for safe logging.
    Shows first few chars and masks the rest.
    
    Args:
        value: The secret value to redact
        show_chars: Number of characters to show (default 8)
    
    Returns:
        Redacted string like "sk_live_a1***[REDACTED]"
    """
    if not value:
        return "[EMPTY]"
    if len(value) <= show_chars:
        return "***[REDACTED]"
    return f"{value[:show_chars]}***[REDACTED]"

# ============================================================================
# SECURITY CONFIGURATION (Bug #1 Fix)
# ============================================================================
# Optional registration secret - if set, agents must provide this to register
REGISTRATION_SECRET = os.getenv('REGISTRATION_SECRET')
_is_dev_mode = os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_DEBUG') == '1'

if REGISTRATION_SECRET:
    logger.info("[SECURITY] Registration secret is configured (new agents must authenticate)")
elif not _is_dev_mode:
    logger.warning(
        "[SECURITY] ⚠️ REGISTRATION_SECRET not set! "
        "Anyone can register fake agents. Set REGISTRATION_SECRET env var in production."
    )

# ============================================================================
# LOGGING HELPERS
# ============================================================================
def short_agent_id(agent_id):
    """Return last 6 chars of agent ID for concise logging."""
    if not agent_id:
        return "??????"
    # Convert to string in case agent_id is an integer
    agent_id_str = str(agent_id)
    return agent_id_str[-6:] if len(agent_id_str) > 6 else agent_id_str


def should_ignore_domain_session(session_data):
    """
    Check if domain session should be ignored (localhost/internal).
    Returns True if should ignore, False if should store.
    """
    # Check raw_title if available (new format from agent)
    raw_title = session_data.get('raw_title', '')
    if raw_title:
        title_lower = raw_title.lower()
        ignore_patterns = [
            'sentineledge', 'localhost', '127.0.0.1',
            '192.168.', '10.0.', 'internal', 'dashboard'
        ]
        for pattern in ignore_patterns:
            if pattern in title_lower:
                logger.debug(f"[DOMAIN] Ignoring localhost session: {raw_title[:50]}")
                return True

    # Check raw_url if available
    raw_url = session_data.get('raw_url', '')
    if raw_url:
        url_lower = raw_url.lower()
        if any(x in url_lower for x in ['localhost', '127.0.0.1', '192.168.', '10.0.']):
            logger.debug(f"[DOMAIN] Ignoring localhost URL: {raw_url[:50]}")
            return True

    # Check domain field (fallback for old format)
    domain = session_data.get('domain', '')
    if domain and domain.lower() in ['localhost', '127.0.0.1']:
        logger.debug(f"[DOMAIN] Ignoring localhost domain: {domain}")
        return True

    return False


def store_raw_event(agent_id, event_type, payload, processed=False, error=None):
    """Store raw event payload for auditing and replay."""
    try:
        raw = server_models.RawEvent(
            agent_id=agent_id,
            event_type=event_type,
            sequence=payload.get('sequence'),
            payload=json.dumps(payload),
            received_at=datetime.utcnow(),
            processed=processed,
            error=error
        )
        db.session.add(raw)
        db.session.flush() # Ensure ID is generated
        return raw
    except Exception as e:
        logger.error(f"Failed to store raw event: {e}")
        return None

@bp.route('/register', methods=['POST'])
def register():
    """
    Register new agent and return API key.
    
    This endpoint is OPEN (no authentication required).
    
    Request Body:
    {
        "agent_id": "COMPUTERNAME-UUID",
        "hostname": "john-laptop",
        "os_version": "Windows 10 Pro",
        "os_build": 22631,
        "windows_edition": "Pro",
        "architecture": "AMD64",
        "agent_version": "2.0.0"
    }
    
    Response:
    {
        "message": "Agent registered successfully",
        "api_key": "sk_live_abc123def456...",
        "agent": {
            "agent_id": "COMPUTERNAME-UUID",
            "hostname": "john-laptop",
            "status": "active",
            "last_seen": "2025-12-07T10:30:00Z"
        }
    }
    """
    try:
        payload = RegisterSchema.parse_obj(request.get_json() or {})
    except ValidationError as e:
        logger.warning(f"[REGISTER] Validation error: {e}")
        return jsonify({'error': 'Invalid input', 'detail': e.errors()}), 400
    
    # ========================================================================
    # BUG-008 Fix: Enforce registration secret in production
    # ========================================================================
    if REGISTRATION_SECRET:
        # Secret is configured - verify it
        provided_secret = request.headers.get('X-Registration-Secret')
        if provided_secret != REGISTRATION_SECRET:
            logger.warning(f"[REGISTER] Invalid or missing registration secret from {request.remote_addr}")
            return jsonify({'error': 'Invalid registration secret'}), 403
    elif not _is_dev_mode:
        # PRODUCTION MODE WITHOUT SECRET - BLOCK REGISTRATION
        # This is a critical security issue - registration must be protected
        logger.critical(
            f"[REGISTER] BLOCKED - Production mode requires REGISTRATION_SECRET! "
            f"Attempted registration from {request.remote_addr}"
        )
        return jsonify({
            'error': 'Server misconfiguration',
            'message': 'Registration is disabled until REGISTRATION_SECRET is configured'
        }), 503
    # else: Development mode without secret - allow for testing

    agent_id = payload.agent_id
    agent_name = payload.agent_name  # Custom display name
    hostname = payload.hostname
    os_version = payload.get_os_version()
    agent_version = payload.get_agent_version()
    
    # NEW: Extract enhanced OS fields
    os_build = payload.os_build
    windows_edition = payload.windows_edition
    architecture = payload.architecture
    
    short_id = short_agent_id(agent_id)
    logger.info(f"[{short_id}] REGISTER: {hostname} ({os_version}, Build {os_build}, {architecture}, v{agent_version})")
    
    # Generate JWT token - this is what the agent will use for authentication
    # The agent sends this as Authorization: Bearer <token>
    api_token = generate_api_token(agent_id)
    
    # SEC-007: Generate sk_live key - returns (plaintext, hashed)
    # plaintext: Given to agent (only once during registration)
    # hashed: Stored in database for security
    api_key_plaintext, api_key_hashed = generate_api_key()
    
    # Check if agent already exists by UUID
    existing = server_models.Agent.query.filter_by(agent_id=agent_id).first()
    
    # ========================================================================
    # SIMPLIFIED REGISTRATION LOGIC:
    # 1. If agent_id exists -> update that agent
    # 2. If hostname exists -> link to existing agent (re-install scenario)
    # 3. Otherwise create new agent
    # ========================================================================
    if not existing and hostname:
        existing_by_hostname = server_models.Agent.query.filter_by(hostname=hostname).first()
        if existing_by_hostname:
            logger.info(f"[REGISTER] Hostname '{hostname}' exists - PRESERVING existing Agent {existing_by_hostname.agent_id}")
            # FIX: Reuse existing UUID instead of trying to update DB PK
            agent_id = str(existing_by_hostname.agent_id)
            existing = existing_by_hostname
            
            # Regenerate token for the CORRECT (preserved) ID
            api_token = generate_api_token(agent_id)
    
    if existing:
        # Always allow re-registration - just log key status for security auditing
        stored_key = existing.local_agent_key
        provided_key = payload.local_agent_key
        
        if stored_key and provided_key:
            import hmac
            if hmac.compare_digest(str(stored_key), str(provided_key)):
                logger.info(f"[REGISTER] Agent {agent_id} key verified ✓")
            else:
                logger.warning(f"[REGISTER] Agent {agent_id} key changed (re-install assumed)")
        elif provided_key:
            logger.info(f"[REGISTER] Agent {agent_id} providing key for first time")
        else:
            logger.warning(f"[REGISTER] Agent {agent_id} registered without key")
        
        # Re-registration - update existing agent with new credentials
        logger.info(f"[REGISTER] Agent {agent_id} already exists - updating credentials")
        # SEC-007: Store HASHED key in database
        existing.api_key = api_key_hashed
        existing.api_token = api_token
        existing.agent_name = agent_name  # Custom display name
        existing.hostname = hostname
        existing.os = os_version
        existing.os_build = os_build  # NEW
        existing.windows_edition = windows_edition  # NEW
        existing.architecture = architecture  # NEW
        existing.version = agent_version
        
        # Always update local_agent_key if provided (supports re-installs)
        if payload.local_agent_key:
            existing.local_agent_key = payload.local_agent_key
        
        existing.status = 'active'
        existing.last_seen = datetime.now(timezone.utc)
        agent = existing
    else:
        # New registration
        logger.info(f"[REGISTER] Creating new agent record: {agent_id}")
        agent = server_models.Agent(
            agent_id=agent_id, # Set the UUID field
            agent_name=agent_name,  # Custom display name
            hostname=hostname,
            os=os_version,
            os_build=os_build,  # NEW
            windows_edition=windows_edition,  # NEW
            architecture=architecture,  # NEW
            version=agent_version,
            local_agent_key=payload.local_agent_key,
            api_token=api_token,
            # SEC-007: Store HASHED key in database
            api_key=api_key_hashed,
            status='active',
            last_seen=datetime.now(timezone.utc)
        )
        db.session.add(agent)

    try:
        db.session.commit()
        logger.info("=" * 70)
        logger.info(f"[REGISTER] [OK] SUCCESS: Agent {agent_id} registered")
        # SEC-010: Use redact_secret to prevent token leakage in logs
        logger.info(f"[REGISTER] JWT Token issued: {redact_secret(api_token)}")
        logger.info("=" * 70)
        
        # Return JWT token as api_key - this is what agents expect!
        # Agents use: Authorization: Bearer <api_key>
        return jsonify({
            'message': 'Agent registered successfully',
            'api_key': api_token,  # Return JWT token as api_key!
            'agent': {
                'agent_id': agent_id,
                'hostname': hostname,
                'status': 'active',
                'last_seen': datetime.now(timezone.utc).isoformat() + 'Z'
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[REGISTER] ERROR: {e}")
        return jsonify({'error': 'Registration failed', 'message': str(e)}), 500


@bp.route('/inventory', methods=['POST'])
@require_auth
def inventory():
    """
    Update application inventory - Full Sync "Replace All" model.
    """
    from flask import g
    data = request.get_json() or {}
    
    agent_id = data.get('agent_id')
    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        logger.warning(f"Inventory: Missing agent_id in request or JWT")
        return jsonify({'status': 'error', 'message': 'Missing agent_id'}), 400
    
    if 'apps' not in data:
        logger.warning(f"[AGENT {agent_id}] Inventory: Missing apps data")
        return jsonify({'status': 'error', 'message': 'Missing apps data'}), 400
    
    # Store Raw Event
    raw_event = store_raw_event(agent_id, 'inventory', data, processed=False)
    
    # Parse timestamp
    timestamp_str = data.get('timestamp')
    if timestamp_str:
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except:
            timestamp = datetime.utcnow()
    else:
        timestamp = datetime.utcnow()
    
    apps = data.get('apps', [])
    changes = data.get('changes', {})
    
    logger.info(f"[AGENT {agent_id}] Inventory upload: {len(apps)} apps")

    try:
        if changes.get('changed'):
            for app_name in changes.get('installed', []):
                app_data = next((a for a in apps if a.get('name') == app_name), {})
                db.session.add(server_models.AppInventoryChange(
                    agent_id=agent_id,
                    timestamp=timestamp,
                    change_type='installed',
                    app_name=app_name,
                    version=app_data.get('version')
                ))
            
            for app_name in changes.get('uninstalled', []):
                db.session.add(server_models.AppInventoryChange(
                    agent_id=agent_id,
                    timestamp=timestamp,
                    change_type='uninstalled',
                    app_name=app_name
                ))
            
            for app_name in changes.get('updated', []):
                app_data = next((a for a in apps if a.get('name') == app_name), {})
                db.session.add(server_models.AppInventoryChange(
                    agent_id=agent_id,
                    timestamp=timestamp,
                    change_type='updated',
                    app_name=app_name,
                    version=app_data.get('version')
                ))
        
        deleted_count = server_models.AppInventory.query.filter_by(agent_id=agent_id).delete()
        logger.debug(f"[AGENT {agent_id}] Deleted {deleted_count} old inventory records")
        
        # Track seen apps to prevent duplicates in the same batch
        seen_apps = set()
        
        for app_data in apps:
            app_name = app_data.get('name')
            if not app_name:
                continue
            
            # Skip if we've already processed this app name in this batch
            if app_name in seen_apps:
                continue
            
            seen_apps.add(app_name)
            
            # Parse install_date - handle various formats
            install_date_raw = app_data.get('install_date')
            install_date = None
            if install_date_raw and isinstance(install_date_raw, str) and install_date_raw.strip():
                try:
                    # Try YYYYMMDD format (Windows registry format)
                    if len(install_date_raw) == 8 and install_date_raw.isdigit():
                        install_date = date(
                            int(install_date_raw[:4]),
                            int(install_date_raw[4:6]),
                            int(install_date_raw[6:8])
                        )
                    # Try ISO format (YYYY-MM-DD)
                    elif '-' in install_date_raw:
                        install_date = date.fromisoformat(install_date_raw[:10])
                except (ValueError, TypeError):
                    install_date = None  # Invalid date, skip it
            
            new_app = server_models.AppInventory(
                agent_id=agent_id,
                name=app_name,
                version=app_data.get('version', 'Unknown'),
                publisher=app_data.get('publisher', 'Unknown'),
                install_location=app_data.get('install_location') or None,  # Convert empty to None
                install_date=install_date,
                source=app_data.get('source'),  # Registry-HKLM, Registry-HKCU, MicrosoftStore
                last_seen=timestamp
            )
            db.session.add(new_app)


        if raw_event:
            raw_event.processed = True
            
        db.session.commit()
        
        logger.info(f"[OK] Inventory from {agent_id}: {len(apps)} apps (replaced)")

        return jsonify({
            'status': 'ok',
            'message': 'Inventory processed successfully',
            'apps_count': len(apps)
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[ERROR] Inventory error: {e}", exc_info=True)
        
        # Log failure to RawEvent
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id,
                    event_type='inventory',
                    sequence=data.get('sequence'),
                    payload=json.dumps(data),
                    received_at=datetime.utcnow(),
                    processed=False,
                    error=str(e)
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
                
        return jsonify({'status': 'error', 'message': 'Failed to update inventory'}), 500


@bp.route('/domain-usage', methods=['POST'])
@require_auth
def domain_usage():
    """Batch domain usage upload."""
    from flask import g
    data = request.get_json() or {}
    
    agent_id = data.get('agent_id')
    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        logger.warning(f"Domain usage: Missing agent_id in request or JWT")
        return jsonify({'status': 'error', 'message': 'Missing agent_id'}), 400

    records = data.get('records', [])
    if not records:
        logger.warning(f"[AGENT {agent_id}] Domain usage: No records provided")
        return jsonify({'status': 'error', 'message': 'No records provided'}), 400
    
    logger.info(f"[AGENT {agent_id}] Domain usage upload: {len(records)} records")

    try:
        for record in records:
            date_str = record.get('date')
            if isinstance(date_str, str):
                date_value = date.fromisoformat(date_str)
            elif isinstance(date_str, date):
                date_value = date_str
            else:
                date_value = date.today()
            
            domain_rec = server_models.DomainUsage.query.filter_by(
                agent_id=agent_id,
                date=date_value,
                domain=record.get('domain')
            ).first()

            if domain_rec:
                domain_rec.duration_seconds = record.get('total_seconds', 0)
                domain_rec.session_count = record.get('session_count', 0)
                domain_rec.last_updated = datetime.now(timezone.utc)
            else:
                domain_rec = server_models.DomainUsage(
                    agent_id=agent_id,
                    date=date_value,
                    domain=record.get('domain'),
                    duration_seconds=record.get('total_seconds', 0),
                    session_count=record.get('session_count', 0)
                )
                db.session.add(domain_rec)

        db.session.commit()
        logger.info(f"[AGENT {agent_id}] Domain usage processed: {len(records)} records")
        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Domain usage error: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to update domain usage'}), 500


@bp.route('/heartbeat', methods=['GET', 'POST'])
@require_auth
def heartbeat():
    """Heartbeat health check."""
    from flask import g
    try:
        payload = HeartbeatSchema.parse_obj(request.get_json() or {'agent_id': request.headers.get('X-Agent-ID'), 'timestamp': ''})
    except ValidationError as e:
        logger.debug(f"Heartbeat validation: {e}")
    
    agent_id = str(g.current_agent.agent_id) if g.current_agent else "unknown"
    logger.debug(f"[AGENT {agent_id}] Heartbeat received")
    
    # FIX 2: DUPLICATE DETECTION
    data = request.get_json() or {}
    idempotency_key = data.get('idempotency_key')
    sequence = data.get('sequence')
    if idempotency_key and sequence:
        existing = server_models.RawEvent.query.filter_by(
            agent_id=agent_id,
            sequence=sequence,
            idempotency_key=idempotency_key
        ).first()
        if existing and existing.processed:
            logger.info(f"[HEARTBEAT] Duplicate detected: {short_agent_id(agent_id)} seq={sequence}")
            return jsonify(status='duplicate', message='Already processed'), 200

    # Store Raw Event for Heartbeat (Critical for sequence tracking)
    raw_event = None
    if payload:
        try:
            raw_event = store_raw_event(agent_id, 'heartbeat', data, processed=False)
        except:
            pass

    # Process analytics if payload is present
    if payload:
        try:
            heartbeat_data = payload.dict()
            process_heartbeat_analytics(agent_id, heartbeat_data)
            
            if raw_event:
                raw_event.processed = True
                
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to process V1 heartbeat analytics: {e}")
            if raw_event:
                try:
                    failed_raw = server_models.RawEvent(
                        agent_id=agent_id,
                        event_type='heartbeat',
                        sequence=payload.sequence if hasattr(payload, 'sequence') else None,
                        payload=json.dumps(payload.dict()),
                        received_at=datetime.utcnow(),
                        processed=False,
                        error=str(e)
                    )
                    db.session.add(failed_raw)
                    db.session.commit()
                except:
                    pass

    server_time = datetime.utcnow().isoformat() + 'Z'
    return jsonify({
        'status': 'ok',
        'server_time': server_time
    }), 200


@bp.route('/agent/status', methods=['POST'])
@require_auth
def update_agent_status():
    """
    Receive agent operational status updates (NORMAL, DEGRADED, OFFLINE).
    Called by HelperMonitor when Helper fails or recovers.
    """
    from flask import g
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        agent_id = data.get('agent_id')
        operational_status = data.get('operational_status', 'UNKNOWN')
        status_reason = data.get('status_reason', '')
        diagnostics = data.get('diagnostics', {})
        
        # Get agent from auth context or lookup
        agent = g.current_agent if hasattr(g, 'current_agent') else None
        
        if not agent and agent_id:
            agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        
        # Get old status for logging
        old_status = getattr(agent, 'operational_status', 'NORMAL') or 'NORMAL'
        
        # Update agent status
        agent.operational_status = operational_status
        agent.status_reason = status_reason
        agent.last_status_change = datetime.now(timezone.utc)
        
        # Store diagnostics as JSON string
        if diagnostics:
            agent.diagnostics_json = json.dumps(diagnostics)
        
        # Log status change
        if old_status != operational_status:
            logger.info(f"[AGENT {short_agent_id(agent.id)}] Status: {old_status} -> {operational_status}")
            if status_reason:
                logger.info(f"[AGENT {short_agent_id(agent.id)}] Reason: {status_reason}")
        
        # Alert on degraded mode
        if operational_status == 'DEGRADED':
            logger.warning("=" * 70)
            logger.warning(f"ALERT: Agent {agent.hostname or agent.id} entered DEGRADED MODE")
            logger.warning(f"Reason: {status_reason}")
            logger.warning("=" * 70)
        
        # Log recovery
        elif operational_status == 'NORMAL' and old_status == 'DEGRADED':
            logger.info("=" * 70)
            logger.info(f"RECOVERY: Agent {agent.hostname or agent.id} returned to NORMAL")
            logger.info("=" * 70)
        
        db.session.commit()
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating agent status: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/screentime', methods=['POST'])
@require_auth
def screentime():
    """Handle screentime batch upload with minute-based records."""
    from flask import g
    data = request.get_json() or {}
    records = data.get('records', [])
    
    if not records and ('date' in data or 'active_seconds' in data or 'total_active_minutes' in data):
        records = [data]

    if not records:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else "unknown"
        logger.warning(f"[AGENT {agent_id}] Screentime: No records provided")
        return jsonify({'status': 'error', 'message': 'No records provided'}), 400
    
    agent_id = str(g.current_agent.agent_id) if g.current_agent else "unknown"
    
    logger.info(f"[AGENT {agent_id}] Screentime batch received: {len(records)} records (SKIPPED - using live telemetry)")
    
    return jsonify({'status': 'ok', 'note': 'Using live telemetry for screentime'}), 200


@bp.route('/app-usage', methods=['POST'])
@require_auth
def app_usage():
    """Handle app usage at /api/v1/app-usage (agent compatibility)."""
    from flask import g
    data = request.get_json() or {}
    agent_id = data.get('agent_id')
    
    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        logger.warning("App usage: Missing agent_id")
        return jsonify({'status': 'error', 'message': 'Missing agent_id'}), 400
    
    records = data.get('records', [])
    if not records and all(k in data for k in ['date', 'app', 'total_seconds']):
        records = [data]
    
    logger.info(f"[AGENT {agent_id}] App usage upload: {len(records)} records")
    
    try:
        for record in records:
            date_str = record.get('date')
            if isinstance(date_str, str):
                date_value = date.fromisoformat(date_str)
            elif isinstance(date_str, date):
                date_value = date_str
            else:
                date_value = date.today()
            
            app_usage_rec = server_models.AppUsage.query.filter_by(
                agent_id=agent_id,
                date=date_value,
                app=record.get('app')
            ).first()
            
            if app_usage_rec:
                app_usage_rec.duration_seconds = record.get('total_seconds', 0)
                app_usage_rec.last_updated = datetime.now(timezone.utc)
            else:
                app_usage_rec = server_models.AppUsage(
                    agent_id=agent_id,
                    date=date_value,
                    app=record.get('app'),
                    duration_seconds=record.get('total_seconds', 0)
                )
                db.session.add(app_usage_rec)
        
        db.session.commit()
        logger.info(f"[AGENT {agent_id}] App usage processed: {len(records)} records")
        return jsonify({'status': 'ok'}), 200
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"App usage error: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to update app usage'}), 500


@bp.route('/app-active', methods=['POST'])
@require_auth
def app_active():
    """LIVE LAYER: Real-time heartbeat showing what user is doing NOW."""
    from flask import g
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'status': 'error', 'message': 'Missing agent_id'}), 400
    
    current_app = data.get('current_app') or data.get('app')
    window_title = data.get('window_title')
    duration = data.get('duration_seconds', 0)
    username = data.get('username')
    
    # Detect locked state from lock screen apps
    LOCK_APPS = ['lockapp.exe', 'logonui.exe', 'winlogon.exe']
    
    state = data.get('state', 'active')
    if current_app and current_app.lower() in LOCK_APPS:
        state = 'locked'
    
    try:
        status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
        
        if status:
            if status.current_app != current_app:
                status.session_start = datetime.utcnow()
            status.current_app = current_app
            status.window_title = window_title
            status.duration_seconds = duration
            status.current_state = state
            status.last_seen = datetime.utcnow()
            if username:
                status.username = username
        else:
            status = server_models.AgentCurrentStatus(
                agent_id=agent_id,
                username=username,
                current_app=current_app,
                window_title=window_title,
                current_state=state,
                session_start=datetime.utcnow(),
                duration_seconds=duration,
                last_seen=datetime.utcnow()
            )
            db.session.add(status)
        
        db.session.commit()
        return jsonify({'status': 'ok'}), 200
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"App active error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@telemetry_bp.route("/telemetry/event", methods=["POST"])
@require_auth
def telemetry_event():
    """
    Gateway for all authoritative telemetry events.
    Matches Step 367 Refined Plan.
    """
    from server_telemetry import process_state_duration_event
    payload = request.get_json(force=True)
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({"error": "Missing agent authentication"}), 401

    if payload.get("event") == "state_duration":
        # Inject agent_id for the processor
        payload["agent_id"] = agent_id
        process_state_duration_event(payload)
        return jsonify({"status": "ok"}), 200

    return jsonify({"status": "ignored"}), 200


@bp.route('/app-switch', methods=['POST'])
@require_auth
def app_switch():
    """HISTORICAL LAYER: Completed app session (user switched away)."""
    from flask import g
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'status': 'error', 'message': 'Missing agent_id'}), 400
    
    app_name = data.get('app')
    if not app_name:
        return jsonify({'status': 'error', 'message': 'Missing app name'}), 400
    
    start_str = data.get('start_time')
    end_str = data.get('end_time')
    
    try:
        start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00')) if start_str else datetime.utcnow()
    except:
        start_time = datetime.utcnow()
    
    try:
        end_time = datetime.fromisoformat(end_str.replace('Z', '+00:00')) if end_str else datetime.utcnow()
    except:
        end_time = datetime.utcnow()
    
    duration = data.get('duration_seconds', 0)
    if not duration and start_time and end_time:
        duration = (end_time - start_time).total_seconds()
    
    try:
        session = server_models.AppSession(
            agent_id=agent_id,
            username=data.get('username'),
            app=app_name,
            window_title=data.get('window_title'),
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration
        )
        db.session.add(session)
        
        session_date = start_time.date()
        app_usage_rec = server_models.AppUsage.query.filter_by(
            agent_id=agent_id,
            date=session_date,
            app=app_name
        ).first()
        
        if app_usage_rec:
            app_usage_rec.duration_seconds += int(duration)
            app_usage_rec.session_count += 1
            app_usage_rec.last_updated = datetime.utcnow()
        else:
            app_usage_rec = server_models.AppUsage(
                agent_id=agent_id,
                date=session_date,
                app=app_name,
                duration_seconds=int(duration),
                session_count=1
            )
            db.session.add(app_usage_rec)
        
        db.session.commit()
        return jsonify({'status': 'ok'}), 200
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"App switch error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@bp.route('/domain-active', methods=['POST'])
@require_auth
def domain_active_batch():
    """
    Handle batch domain active sessions with AGGREGATION.
    
    This endpoint now does TWO things:
    1. Stores detailed sessions in domain_sessions table (history)
    2. Aggregates into domain_usage table (dashboard source)
    """
    from flask import g
    data = request.get_json() or {}
    agent_id = data.get('agent_id')
    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    if not agent_id:
        logger.warning("Domain active: Missing agent_id")
        return jsonify({'status': 'error', 'message': 'Missing agent_id'}), 400
    
    domains_active = data.get('domains_active', [])
    if not domains_active:
        logger.warning(f"[AGENT {agent_id}] Domain active: No domains_active provided")
        return jsonify({'status': 'error', 'message': 'No domains_active provided'}), 400
    
    logger.info(f"[AGENT {agent_id}] Domain active upload: {len(domains_active)} sessions")
    
    try:
        aggregated_count = 0
        ignored_count = 0  # Count of ignored localhost sessions
        
        for session in domains_active:
            domain = session.get('domain')
            browser = session.get('browser')
            start_str = session.get('start')
            end_str = session.get('end')
            duration = session.get('duration_seconds', 0)
            raw_title = session.get('raw_title')  # New field from agent
            raw_url = session.get('raw_url')      # New field from agent
            
            # Check if should ignore (localhost/internal)
            if should_ignore_domain_session(session):
                ignored_count += 1
                continue
            
            if not domain or not start_str:
                logger.debug(f"Skipping session - missing domain or start time")
                continue
            
            # Parse timestamps
            try:
                start_ts = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            except:
                start_ts = datetime.utcnow()
            
            # Convert to naive datetime for database
            start_naive = start_ts.replace(tzinfo=None) if start_ts.tzinfo else start_ts
            
            # ================================================================
            # STEP 1: Store detailed session in domain_sessions table
            # ================================================================
            domain_rec = server_models.DomainSession.query.filter_by(
                agent_id=agent_id,
                domain=domain,
                start_time=start_naive
            ).first()
            
            if not domain_rec:
                end_naive = None
                if end_str:
                    try:
                        end_ts = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                        end_naive = end_ts.replace(tzinfo=None) if end_ts.tzinfo else end_ts
                    except:
                        pass
                
                domain_rec = server_models.DomainSession(
                    agent_id=agent_id,
                    domain=domain,
                    browser=browser,
                    start_time=start_naive,
                    end_time=end_naive,
                    duration_seconds=duration,
                    raw_title=raw_title,       # Store raw window title
                    raw_url=raw_url,           # Store raw URL
                    domain_source='agent'      # Source of classification
                )
                db.session.add(domain_rec)
                logger.debug(f"Created DomainSession: {domain} ({duration}s)")
            
            # ================================================================
            # STEP 2: Aggregate into domain_usage table (DASHBOARD SOURCE!)
            # ================================================================
            session_date = start_naive.date()
            usage_rec = server_models.DomainUsage.query.filter_by(
                agent_id=agent_id,
                date=session_date,
                domain=domain
            ).first()
            
            if usage_rec:
                # Update existing daily aggregate
                usage_rec.duration_seconds += int(duration)
                usage_rec.session_count += 1
                usage_rec.last_updated = datetime.utcnow()
                if browser and not usage_rec.browser:
                    usage_rec.browser = browser
                logger.debug(f"Updated DomainUsage: {domain} -> {usage_rec.duration_seconds}s total")
            else:
                # Create new daily aggregate
                usage_rec = server_models.DomainUsage(
                    agent_id=agent_id,
                    date=session_date,
                    domain=domain,
                    browser=browser,
                    duration_seconds=int(duration),
                    session_count=1
                )
                db.session.add(usage_rec)
                logger.debug(f"Created DomainUsage: {domain} ({duration}s)")
            
            aggregated_count += 1
        
        # Commit all changes
        db.session.commit()
        if ignored_count > 0:
            logger.info(f"[DOMAIN] Aggregated {aggregated_count}, ignored {ignored_count} localhost sessions")
        else:
            logger.info(f"[DOMAIN] Aggregated {aggregated_count} sessions into DomainUsage table")
        return jsonify({'status': 'ok', 'aggregated': aggregated_count, 'ignored': ignored_count}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Domain active batch error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to update domain sessions'}), 500


@bp.route('/merged-events', methods=['POST'])
@require_auth
def merged_events():
    """Handle merged events (idle and app sessions)."""
    from flask import g
    agent_id = str(g.current_agent.agent_id) if g.current_agent else "unknown"
    data = request.get_json() or {}
    
    events = data.get('events', [])
    short_id = short_agent_id(agent_id)
    logger.info(f"[{short_id}] merged-events: {len(events)} events")
    
    # Store Raw Event
    raw_event = store_raw_event(agent_id, 'merged-events', data, processed=False)
    
    try:
        for event in events:
            event_type = event.get('type')
            state = event.get('state', {})
            
            if event_type == 'app':
                try:
                    start_str = event.get('start')
                    end_str = event.get('end')
                    start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00')) if start_str else datetime.utcnow()
                    end_time = datetime.fromisoformat(end_str.replace('Z', '+00:00')) if end_str else None
                    
                    app_session = server_models.AppSession(
                        agent_id=agent_id,
                        username=event.get('username'),
                        app=state.get('app_name', 'Unknown'),
                        window_title=state.get('window_title'),
                        start_time=start_time,
                        end_time=end_time,
                        duration_seconds=event.get('duration_seconds', 0)
                    )
                    db.session.add(app_session)
                except Exception as e:
                    logger.warning(f"[AGENT {agent_id}] Failed to store app session from merged events: {e}")
            
            elif event_type == 'idle':
                try:
                    start_str = event.get('start')
                    timestamp = datetime.fromisoformat(start_str.replace('Z', '+00:00')) if start_str else datetime.utcnow()
                    
                    state_change = server_models.StateChange(
                        agent_id=agent_id,
                        username=event.get('username'),
                        previous_state=state.get('previous_state', 'unknown'),
                        current_state=state.get('state', 'unknown'),
                        timestamp=timestamp
                    )
                    db.session.add(state_change)
                except Exception as e:
                    logger.warning(f"[AGENT {agent_id}] Failed to store state change from merged events: {e}")

        # Mark processed
        if raw_event:
            raw_event.processed = True
            
        db.session.commit()
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[AGENT {agent_id}] Merged events error: {e}")
        
        # Log failure to RawEvent
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id,
                    event_type='merged-events',
                    sequence=data.get('sequence'),
                    payload=json.dumps(data),
                    received_at=datetime.utcnow(),
                    processed=False,
                    error=str(e)
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
                
        return jsonify({'error': 'Failed to process merged events'}), 500


@bp.route('/domains', methods=['POST'])
@require_auth
def domains():
    """
    Handle browser history domains (Column B - Sites Opened).
    Now with deduplication and browser name normalization.
    """
    from flask import g
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400
    
    data = request.get_json() or {}
    domain_list = data.get('domains', [])
    
    short_id = short_agent_id(agent_id)
    logger.info(f"[{short_id}] domains: {len(domain_list)} sites")
    
    # Browser name normalization map
    BROWSER_NAME_MAP = {
        'microsoft': 'Microsoft Edge',
        'edge': 'Microsoft Edge',
        'msedge': 'Microsoft Edge',
        'chrome': 'Google Chrome',
        'brave': 'Brave',
        'firefox': 'Mozilla Firefox',
    }
    
    try:
        added_count = 0
        skipped_count = 0
        
        for domain_data in domain_list:
            if isinstance(domain_data, str):
                domain = domain_data
                url = None
                browser = None
                visited_at = datetime.utcnow()
            else:
                domain = domain_data.get('domain')
                url = domain_data.get('url')
                browser = domain_data.get('browser')
                visited_str = domain_data.get('visited_at') or domain_data.get('timestamp')
                if visited_str:
                    try:
                        visited_at = datetime.fromisoformat(visited_str.replace('Z', '+00:00'))
                        # Convert to naive datetime for DB comparison
                        visited_at = visited_at.replace(tzinfo=None) if visited_at.tzinfo else visited_at
                    except:
                        visited_at = datetime.utcnow()
                else:
                    visited_at = datetime.utcnow()
            
            if not domain:
                continue
            
            # Normalize browser name
            if browser:
                browser_lower = browser.lower().strip()
                browser = BROWSER_NAME_MAP.get(browser_lower, browser.title())
            
            # DEDUPLICATION: Check if this exact domain+timestamp already exists
            # This prevents duplicate entries from re-sending the same data
            existing = server_models.DomainVisit.query.filter_by(
                agent_id=agent_id,
                domain=domain,
                visited_at=visited_at
            ).first()
            
            if existing:
                skipped_count += 1
                continue  # Skip duplicate
            
            visit = server_models.DomainVisit(
                agent_id=agent_id,
                username=data.get('username'),
                domain=domain,
                url=url,
                browser=browser,
                visited_at=visited_at
            )
            db.session.add(visit)
            added_count += 1
        
        try:
            db.session.commit()
        except Exception as commit_error:
            # Handle race condition: if unique constraint fails, rollback and continue
            db.session.rollback()
            if 'duplicate' in str(commit_error).lower() or 'unique' in str(commit_error).lower():
                logger.debug(f"[{short_id}] Some duplicates caught by DB constraint")
                # Re-add non-duplicate entries one by one
                # For simplicity, just report partial success
                return jsonify({'status': 'partial', 'note': 'Some duplicates filtered by DB constraint'}), 200
            raise  # Re-raise if it's a different error
        
        if skipped_count > 0:
            logger.debug(f"[{short_id}] domains: added {added_count}, skipped {skipped_count} duplicates")
        
        return jsonify({'status': 'ok', 'added': added_count, 'skipped': skipped_count}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[AGENT {agent_id}] Domains storage error: {e}")
        return jsonify({'error': str(e)}), 500


def register_root_endpoint(app):
    """Register all endpoints at root level for agent compatibility."""
    
    @app.route('/register', methods=['POST'])
    def register_agent_root():
        return register()
    
    @app.route('/heartbeat', methods=['POST', 'GET'])
    def heartbeat_root():
        return heartbeat()
    
    @app.route('/inventory', methods=['POST'])
    @require_auth
    def inventory_root():
        return inventory()
    
    @app.route('/domain-usage', methods=['POST'])
    @require_auth
    def domain_usage_root():
        return domain_usage()
    
    @app.route('/merged-events', methods=['POST'])
    @require_auth
    def merged_events_root():
        return merged_events()
    
    @app.route('/domains', methods=['POST'])
    @require_auth
    def domains_root():
        """Handle domains data (agent-specific endpoint)."""
        from flask import g
        agent_id = str(g.current_agent.agent_id) if g.current_agent else "unknown"
        data = request.get_json() or {}
        domain_count = len(data.get('domains', []))
        logger.info(f"[AGENT {agent_id}] Domains root endpoint from {request.remote_addr}: {domain_count} domains")
        return jsonify({'status': 'ok'}), 200
    @require_auth
    def domain_usage_root():
        return domain_usage()
