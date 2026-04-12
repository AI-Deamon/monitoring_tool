import logging
import json
import os
import re
import uuid
from datetime import datetime, date, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app
from extensions import db
import server_models
from server_auth import generate_api_key, generate_api_token, require_auth
from schemas import RegisterSchema, AppInventorySchema, DomainUsageSchema, HeartbeatSchema
from pydantic import ValidationError

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


def validate_agent_id(agent_id: str) -> bool:
    """DATA-001: Validate agent_id is a proper UUID format."""
    if not agent_id or not isinstance(agent_id, str):
        return False
    try:
        uuid.UUID(str(agent_id))
        return True
    except (ValueError, AttributeError):
        return False


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
            received_at=datetime.now(timezone.utc),
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
        existing.last_seen = datetime.utcnow()
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
            last_seen=datetime.utcnow()
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
    
    # DATA-001: Validate agent_id format
    if not validate_agent_id(agent_id):
        logger.warning(f"Inventory: Invalid agent_id format: {agent_id}")
        return jsonify({'status': 'error', 'message': 'Invalid agent_id format'}), 400
    
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
            timestamp = datetime.now(timezone.utc)
    else:
        timestamp = datetime.now(timezone.utc)
    
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
        
        # BUG-003 FIX: Use savepoint to prevent data loss if insert phase fails.
        # If something goes wrong inserting new apps, we rollback to the savepoint
        # and the old inventory remains intact.
        savepoint = db.session.begin_nested()
        
        try:
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
                    architecture=app_data.get('architecture'),
                    uninstall_command=app_data.get('uninstall_command'),
                    estimated_size_kb=app_data.get('estimated_size_kb'),
                    last_seen=timestamp
                )
                db.session.add(new_app)
            
            savepoint.commit()
        except Exception as insert_error:
            savepoint.rollback()
            logger.error(f"[AGENT {agent_id}] Insert phase failed, old inventory preserved: {insert_error}")
            raise  # Re-raise to trigger outer error handler

        if raw_event:
            raw_event.processed = True
            
        db.session.commit()
        
        # EOL-002: Trigger lifecycle evaluation after inventory update
        try:
            from eol_engine import evaluate_agent_lifecycle
            agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
            if agent:
                evaluate_agent_lifecycle(agent)
                logger.debug(f"[EOL] Triggered evaluation for agent {agent_id}")
        except Exception as eol_error:
            logger.warning(f"[EOL] Background evaluation trigger failed: {eol_error}")

        logger.info(f"[OK] Inventory from {agent_id}: {len(seen_apps)} apps (replaced)")

        return jsonify({
            'status': 'ok',
            'message': 'Inventory processed successfully',
            'apps_count': len(seen_apps)
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
                    received_at=datetime.now(timezone.utc),
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

    # DATA-001: Validate agent_id format
    if not validate_agent_id(agent_id):
        logger.warning(f"Domain usage: Invalid agent_id format: {agent_id}")
        return jsonify({'status': 'error', 'message': 'Invalid agent_id format'}), 400

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

    # Process heartbeat
    if payload:
        try:
            if raw_event:
                raw_event.processed = True
                
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to process heartbeat: {e}")
            if raw_event:
                try:
                    failed_raw = server_models.RawEvent(
                        agent_id=agent_id,
                        event_type='heartbeat',
                        sequence=payload.sequence if hasattr(payload, 'sequence') else None,
                        payload=json.dumps(payload.dict()),
                        received_at=datetime.now(timezone.utc),
                        processed=False,
                        error=str(e)
                    )
                    db.session.add(failed_raw)
                    db.session.commit()
                except:
                    pass

    server_time = datetime.now(timezone.utc).isoformat() + 'Z'
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
                status.session_start = datetime.now(timezone.utc)
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
                session_start=datetime.now(timezone.utc),
                duration_seconds=duration,
                last_seen=datetime.now(timezone.utc)
            )
            db.session.add(status)
        
        db.session.commit()
        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"App active error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@telemetry_bp.route("/event", methods=["POST"])
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
        return process_state_duration_event(payload)

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
        start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00')) if start_str else datetime.now(timezone.utc)
    except:
        start_time = datetime.now(timezone.utc)

    try:
        end_time = datetime.fromisoformat(end_str.replace('Z', '+00:00')) if end_str else datetime.now(timezone.utc)
    except:
        end_time = datetime.now(timezone.utc)
    
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
            app_usage_rec.last_updated = datetime.now(timezone.utc)
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
                start_ts = datetime.now(timezone.utc)
            
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
                usage_rec.last_updated = datetime.now(timezone.utc)
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
                    start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00')) if start_str else datetime.now(timezone.utc)
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
                    timestamp = datetime.fromisoformat(start_str.replace('Z', '+00:00')) if start_str else datetime.now(timezone.utc)
                    
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
                    received_at=datetime.now(timezone.utc),
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
                visited_at = datetime.now(timezone.utc)
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
                        visited_at = datetime.now(timezone.utc)
                else:
                    visited_at = datetime.now(timezone.utc)
            
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


@bp.route('/asset-hardware', methods=['POST'])
@require_auth
def asset_hardware():
    """
    Receive hardware/asset information from agent.
    Upsert: create if new, update if changed, skip if unchanged.
    """
    from flask import g
    data = request.get_json() or {}
    
    agent_id = data.get('agent_id')
    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400
    
    sid = short_agent_id(agent_id)
    
    try:
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if not agent:
            logger.warning(f"[ASSET {sid}] Unknown agent")
            return jsonify({'error': 'Unknown agent'}), 404

        # Update last_seen
        agent.last_seen = datetime.utcnow()

        # Extract nested data structures
        identity = data.get('identity', {})
        hardware = data.get('hardware', {})
        network = data.get('network', {})
        security = data.get('security', {})
        collection_hash = data.get('collection_hash', '')
        
        # Check if record exists
        existing = server_models.AssetInfo.query.filter_by(agent_id=agent_id).first()
        
        if existing and existing.collection_hash == collection_hash and collection_hash:
            # No changes
            logger.debug(f"[ASSET {sid}] No changes (hash match)")
            db.session.commit()
            return jsonify({'status': 'unchanged'}), 304
        
        if not existing:
            existing = server_models.AssetInfo(agent_id=agent_id)
            db.session.add(existing)
            action = 'created'
        else:
            action = 'updated'
        
        # Identity fields
        existing.hostname = identity.get('hostname', '')
        existing.serial_number = identity.get('serial_number', '')
        existing.manufacturer = identity.get('manufacturer', '')
        existing.model = identity.get('model', '')
        existing.bios_uuid = identity.get('bios_uuid', '')
        existing.system_uuid = identity.get('system_uuid', '')
        existing.asset_tag = identity.get('asset_tag', '')
        existing.domain = identity.get('domain', '')
        existing.workgroup = identity.get('workgroup', '')
        
        # Hardware fields
        existing.cpu_name = hardware.get('cpu_name', '')
        existing.cpu_cores = hardware.get('cpu_cores', 0)
        existing.cpu_threads = hardware.get('cpu_threads', 0)
        existing.cpu_speed_mhz = hardware.get('cpu_speed_mhz', 0)
        existing.ram_total_gb = hardware.get('ram_total_gb', 0.0)
        existing.ram_slots_used = hardware.get('ram_slots_used', 0)
        existing.ram_slots_total = hardware.get('ram_slots_total', 0)
        existing.gpu_name = hardware.get('gpu_name', '')
        existing.gpu_memory_gb = hardware.get('gpu_memory_gb', 0.0)
        existing.disks_json = json.dumps(hardware.get('disks', []))
        existing.motherboard = hardware.get('motherboard', '')
        
        # Network fields
        existing.primary_mac = network.get('primary_mac', '')
        existing.primary_ip = network.get('primary_ip', '')
        existing.all_macs_json = json.dumps(network.get('all_macs', []))
        existing.all_ips_json = json.dumps(network.get('all_ips', []))
        existing.dns_servers_json = json.dumps(network.get('dns_servers', []))
        existing.domain_joined = network.get('domain_joined', False)
        existing.domain_name = network.get('domain_name', '')
        
        # Security fields
        existing.os_name = security.get('os_name', '')
        existing.os_version = security.get('os_version', '')
        existing.os_build = security.get('os_build', '')
        existing.os_architecture = security.get('os_architecture', '')
        existing.antivirus_json = json.dumps(security.get('antivirus_installed', []))
        existing.firewall_enabled = security.get('firewall_enabled', False)
        existing.last_boot_time = security.get('last_boot_time', '')
        existing.windows_update_enabled = security.get('windows_update_enabled', False)
        existing.bitlocker_status = security.get('bitlocker_status', '')
        
        # Meta
        existing.collected_at = datetime.now(timezone.utc)
        existing.collection_hash = collection_hash
        existing.agent_version = data.get('agent_version', '')
        
        db.session.commit()
        
        logger.info(f"[ASSET {sid}] Asset info {action}: {identity.get('manufacturer', '')} {identity.get('model', '')}")
        
        status_code = 201 if action == 'created' else 200
        return jsonify({'status': action}), status_code
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[ASSET {sid}] Error: {e}")
        return jsonify({'error': 'Asset update failed', 'message': str(e)}), 500


# =============================================================================
# Extended Inventory API Endpoints
# =============================================================================

def _resolve_agent_id_from_request(data):
    """Resolve agent_id from payload first, then authenticated agent context."""
    from flask import g

    agent_id = None
    if isinstance(data, dict):
        agent_id = data.get('agent_id')

    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if getattr(g, 'current_agent', None) else None

    return agent_id


def _normalize_inventory_items(data, category_key):
    """
    Normalize category payload to a list of items.

    Supported payload forms:
    - { "<category_key>": [...] }
    - { "items": [...] }
    - [ ... ]  (direct list)
    - { ... }  (single item object)
    """
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    items = data.get(category_key)
    if items is None:
        items = data.get('items')

    if items is None:
        # Treat remaining dict payload as a single record when category key is absent.
        fallback_item = dict(data)
        fallback_item.pop('agent_id', None)
        return [fallback_item] if fallback_item else []

    if isinstance(items, list):
        return items
    if isinstance(items, dict):
        return [items]

    return []


def _process_inventory_category_upload(category_key, upsert_func):
    """
    Shared handler for compatibility category endpoints under /inventory/*.
    """
    data = request.get_json(silent=True)
    if data is None:
        data = {}

    agent_id = _resolve_agent_id_from_request(data)
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    if not validate_agent_id(agent_id):
        return jsonify({'error': 'Invalid agent_id format'}), 400

    sid = short_agent_id(agent_id)

    try:
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if not agent:
            logger.warning(f"[EXTENDED {sid}] Unknown agent")
            return jsonify({'error': 'Unknown agent'}), 404

        items = _normalize_inventory_items(data, category_key)
        result = {'count': 0, 'action': 'upserted'}

        if items:
            result = upsert_func(agent_id, items)

        db.session.commit()

        # Keep lifecycle risk model current for categories that can impact lifecycle views.
        if items:
            try:
                from eol_engine import evaluate_extended_inventory_lifecycle, evaluate_agent_lifecycle
                evaluate_extended_inventory_lifecycle(agent)
                evaluate_agent_lifecycle(agent)
            except Exception as eol_error:
                logger.warning(f"[EOL] Extended evaluation trigger failed: {eol_error}")

        return jsonify({
            'status': 'ok',
            'category': category_key,
            'results': {category_key: result},
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[EXTENDED {sid}] Category upload error for {category_key}: {e}")
        return jsonify({'error': 'Extended inventory category failed', 'message': str(e)}), 500


@bp.route('/extended-inventory', methods=['POST'])
@require_auth
def extended_inventory():
    """
    Receive extended inventory data from agent (CLI tools, drivers, extensions, plugins).
    Uses upsert pattern: create if new, update if changed.
    """
    from flask import g
    data = request.get_json() or {}
    
    agent_id = data.get('agent_id')
    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400
    
    sid = short_agent_id(agent_id)
    
    try:
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if not agent:
            logger.warning(f"[EXTENDED {sid}] Unknown agent")
            return jsonify({'error': 'Unknown agent'}), 404
        
        results = {}
        
        # The agent sends payloads nested in a 'data' envelope
        payload_data = data.get('data', data)
        
        # Process CLI Tools
        cli_tools = payload_data.get('cli_tools', [])
        if cli_tools:
            results['cli_tools'] = _upsert_cli_tools(agent_id, cli_tools)
        
        # Process Hardware Drivers
        drivers = payload_data.get('drivers', [])
        if drivers:
            results['drivers'] = _upsert_hardware_drivers(agent_id, drivers)
        
        # Process VS Code Extensions
        vscode_extensions = payload_data.get('vscode_extensions', [])
        if vscode_extensions:
            results['vscode_extensions'] = _upsert_vscode_extensions(agent_id, vscode_extensions)
        
        # Process Browser Extensions
        browser_extensions = payload_data.get('browser_extensions', [])
        if browser_extensions:
            results['browser_extensions'] = _upsert_browser_extensions(agent_id, browser_extensions)
        
        # Process Application Plugins
        plugins = payload_data.get('plugins', [])
        if plugins:
            results['plugins'] = _upsert_application_plugins(agent_id, plugins)
        
        # Process Portable Applications
        portable_apps = payload_data.get('portable_apps', [])
        if portable_apps:
            results['portable_apps'] = _upsert_portable_applications(agent_id, portable_apps)
        
        db.session.commit()
        
        total_items = sum(r.get('count', 0) for r in results.values())
        
        # EOL-002: Trigger lifecycle evaluation after extended inventory update
        # This is critical for CLI tools and portable apps risk detection
        try:
            from eol_engine import evaluate_extended_inventory_lifecycle, evaluate_agent_lifecycle
            # Evaluate extended first
            evaluate_extended_inventory_lifecycle(agent)
            # Then run general agent evaluation to ensure OS/Apps are also up to date
            evaluate_agent_lifecycle(agent)
            logger.debug(f"[EOL] Triggered extended evaluation for agent {sid}")
        except Exception as eol_error:
            logger.warning(f"[EOL] Extended evaluation trigger failed: {eol_error}")

        logger.info(f"[EXTENDED {sid}] Processed extended inventory: {total_items} items across {len(results)} categories")
        
        return jsonify({'status': 'ok', 'results': results}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[EXTENDED {sid}] Error: {e}")
        return jsonify({'error': 'Extended inventory failed', 'message': str(e)}), 500


# Compatibility category endpoints (docs compatibility and phased agent rollout)
@bp.route('/inventory/cli-tools', methods=['POST'])
@require_auth
def inventory_cli_tools():
    return _process_inventory_category_upload('cli_tools', _upsert_cli_tools)


@bp.route('/inventory/drivers', methods=['POST'])
@require_auth
def inventory_drivers():
    return _process_inventory_category_upload('drivers', _upsert_hardware_drivers)


@bp.route('/inventory/vscode-extensions', methods=['POST'])
@require_auth
def inventory_vscode_extensions():
    return _process_inventory_category_upload('vscode_extensions', _upsert_vscode_extensions)


@bp.route('/inventory/browser-extensions', methods=['POST'])
@require_auth
def inventory_browser_extensions():
    return _process_inventory_category_upload('browser_extensions', _upsert_browser_extensions)


@bp.route('/inventory/plugins', methods=['POST'])
@require_auth
def inventory_plugins():
    return _process_inventory_category_upload('plugins', _upsert_application_plugins)


@bp.route('/inventory/portable-apps', methods=['POST'])
@require_auth
def inventory_portable_apps():
    return _process_inventory_category_upload('portable_apps', _upsert_portable_applications)


# =============================================================================
# Security Indicators API Endpoint
# =============================================================================

@bp.route('/security-indicators', methods=['POST'])
@require_auth
def security_indicators():
    """
    Receive security indicator data from agent (unsigned drivers, risky extensions, file changes).
    Uses upsert pattern: create if new, update last_seen if existing.
    """
    from flask import g
    data = request.get_json() or {}
    
    agent_id = data.get('agent_id')
    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400
    
    sid = short_agent_id(agent_id)
    
    try:
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if not agent:
            logger.warning(f"[SECURITY {sid}] Unknown agent")
            return jsonify({'error': 'Unknown agent'}), 404
        
        indicators = data.get('indicators', [])
        created = 0
        updated = 0
        
        for ind in indicators:
            indicator_type = ind.get('indicator_type', 'unknown')
            title = ind.get('title', '')[:500]  # Truncate to column limit
            severity = ind.get('severity', 'low')
            risk_score = ind.get('risk_score', 0)
            details = ind.get('details', {})
            
            # Upsert: find existing or create new
            existing = server_models.SecurityIndicator.query.filter_by(
                agent_id=agent_id,
                indicator_type=indicator_type,
                title=title
            ).first()
            
            if existing:
                # Update existing indicator
                existing.severity = severity
                existing.risk_score = risk_score
                existing.details_json = json.dumps(details) if details else None
                existing.last_seen = datetime.utcnow()
                existing.resolved = False  # Re-detected, so not resolved
                updated += 1
            else:
                # Create new indicator
                new_ind = server_models.SecurityIndicator(
                    agent_id=agent_id,
                    indicator_type=indicator_type,
                    severity=severity,
                    title=title,
                    details_json=json.dumps(details) if details else None,
                    risk_score=risk_score,
                )
                db.session.add(new_ind)
                created += 1
        
        db.session.commit()
        
        logger.info(
            f"[SECURITY {sid}] Processed {len(indicators)} indicators: "
            f"{created} new, {updated} updated"
        )
        
        return jsonify({
            'status': 'ok',
            'created': created,
            'updated': updated,
            'total': len(indicators),
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[SECURITY {sid}] Error: {e}")
        return jsonify({'error': 'Security indicators failed', 'message': str(e)}), 500


@bp.route('/system-visibility', methods=['POST'])
@require_auth
def system_visibility():
    """
    Receive raw system visibility snapshot (ports, connections, startup, tasks, disk).
    Stored as raw event for latest dashboard visibility.
    """
    from flask import g
    data = request.get_json() or {}

    agent_id = data.get('agent_id')
    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else None

    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    sid = short_agent_id(agent_id)

    try:
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if not agent:
            logger.warning(f"[VISIBILITY {sid}] Unknown agent")
            return jsonify({'error': 'Unknown agent'}), 404

        raw_event = store_raw_event(agent_id, 'system_visibility', data, processed=True)
        db.session.commit()

        counts = data.get('counts', {})
        logger.info(f"[VISIBILITY {sid}] Snapshot received: {counts}")

        return jsonify({
            'status': 'ok',
            'event_id': raw_event.id if raw_event else None,
            'counts': counts
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[VISIBILITY {sid}] Error: {e}")
        return jsonify({'error': 'System visibility failed', 'message': str(e)}), 500


def _upsert_cli_tools(agent_id, tools):
    """Upsert CLI tools inventory."""
    count = 0
    for tool in tools:
        name = tool.get('name')
        path = tool.get('executable_path', '')
        
        if not name:
            continue
        
        existing = server_models.CLITool.query.filter_by(
            agent_id=agent_id, 
            name=name, 
            executable_path=path
        ).first()
        
        if existing:
            existing.version = tool.get('version')
            existing.source = tool.get('source')
            existing.publisher = tool.get('publisher')
            existing.last_updated = datetime.now(timezone.utc)
        else:
            db.session.add(server_models.CLITool(
                agent_id=agent_id,
                name=name,
                version=tool.get('version'),
                executable_path=path,
                source=tool.get('source'),
                publisher=tool.get('publisher')
            ))
        count += 1
    
    return {'count': count, 'action': 'upserted'}


def _upsert_hardware_drivers(agent_id, drivers):
    """Upsert hardware drivers inventory."""
    count = 0
    for driver in drivers:
        device_id = driver.get('device_id')
        
        if not device_id:
            continue
        
        existing = server_models.HardwareDriver.query.filter_by(
            agent_id=agent_id,
            device_id=device_id
        ).first()
        
        driver_date = None
        if driver.get('driver_date'):
            try:
                driver_date = datetime.strptime(driver['driver_date'][:10], '%Y-%m-%d').date()
            except:
                pass
        
        if existing:
            existing.device_name = driver.get('device_name')
            existing.driver_name = driver.get('driver_name')
            existing.driver_version = driver.get('driver_version')
            existing.driver_date = driver_date
            existing.manufacturer = driver.get('manufacturer')
            existing.device_class = driver.get('device_class')
            existing.is_signed = driver.get('is_signed', False)
            existing.signer = driver.get('signer')
            existing.last_updated = datetime.now(timezone.utc)
        else:
            db.session.add(server_models.HardwareDriver(
                agent_id=agent_id,
                device_name=driver.get('device_name'),
                driver_name=driver.get('driver_name'),
                driver_version=driver.get('driver_version'),
                driver_date=driver_date,
                manufacturer=driver.get('manufacturer'),
                device_class=driver.get('device_class'),
                device_id=device_id,
                is_signed=driver.get('is_signed', False),
                signer=driver.get('signer')
            ))
        count += 1
    
    return {'count': count, 'action': 'upserted'}


def _upsert_vscode_extensions(agent_id, extensions):
    """Upsert VS Code extensions inventory."""
    count = 0
    for ext in extensions:
        ext_id = ext.get('extension_id')
        
        if not ext_id:
            continue
        
        existing = server_models.VSCodeExtension.query.filter_by(
            agent_id=agent_id,
            extension_id=ext_id,
            source=ext.get('source')
        ).first()
        
        if existing:
            existing.display_name = ext.get('display_name')
            existing.version = ext.get('version')
            existing.publisher = ext.get('publisher')
            existing.install_path = ext.get('install_path')
            existing.last_updated = datetime.now(timezone.utc)
            existing.source = ext.get('source')
        else:
            db.session.add(server_models.VSCodeExtension(
                agent_id=agent_id,
                extension_id=ext_id,
                display_name=ext.get('display_name'),
                version=ext.get('version'),
                publisher=ext.get('publisher'),
                install_path=ext.get('install_path'),
                source=ext.get('source')
            ))
        count += 1
    
    return {'count': count, 'action': 'upserted'}


def _upsert_browser_extensions(agent_id, extensions):
    """Upsert browser extensions inventory."""
    count = 0
    for ext in extensions:
        browser = ext.get('browser')
        ext_id = ext.get('extension_id')
        
        if not browser or not ext_id:
            continue
        
        existing = server_models.BrowserExtension.query.filter_by(
            agent_id=agent_id,
            browser=browser,
            extension_id=ext_id
        ).first()
        
        install_date = None
        if ext.get('install_date'):
            try:
                install_date = datetime.strptime(ext['install_date'][:10], '%Y-%m-%d').date()
            except:
                pass
        
        if existing:
            existing.name = ext.get('name')
            existing.version = ext.get('version')
            existing.description = ext.get('description')
            existing.enabled = ext.get('enabled', True)
            existing.install_date = install_date
            existing.profile_path = ext.get('profile_path')
            existing.last_updated = datetime.now(timezone.utc)
        else:
            db.session.add(server_models.BrowserExtension(
                agent_id=agent_id,
                browser=browser,
                extension_id=ext_id,
                name=ext.get('name'),
                version=ext.get('version'),
                description=ext.get('description'),
                enabled=ext.get('enabled', True),
                install_date=install_date,
                profile_path=ext.get('profile_path')
            ))
        count += 1
    
    return {'count': count, 'action': 'upserted'}


def _upsert_application_plugins(agent_id, plugins):
    """Upsert application plugins inventory."""
    count = 0
    for plugin in plugins:
        plugin_type = plugin.get('plugin_type')
        name = plugin.get('name')
        path = plugin.get('install_path', '')
        
        if not plugin_type or not name:
            continue
        
        existing = server_models.ApplicationPlugin.query.filter_by(
            agent_id=agent_id,
            plugin_type=plugin_type,
            name=name,
            install_path=path
        ).first()
        
        if existing:
            existing.version = plugin.get('version')
            existing.publisher = plugin.get('publisher')
            existing.host_application = plugin.get('host_application')
            existing.enabled = plugin.get('enabled', True)
            existing.last_updated = datetime.now(timezone.utc)
        else:
            db.session.add(server_models.ApplicationPlugin(
                agent_id=agent_id,
                plugin_type=plugin_type,
                name=name,
                version=plugin.get('version'),
                publisher=plugin.get('publisher'),
                install_path=path,
                host_application=plugin.get('host_application'),
                enabled=plugin.get('enabled', True)
            ))
        count += 1
    
    return {'count': count, 'action': 'upserted'}


def _upsert_portable_applications(agent_id, apps):
    """Upsert portable applications inventory."""
    count = 0
    for app in apps:
        path = app.get('executable_path')
        
        if not path:
            continue
        
        existing = server_models.PortableApplication.query.filter_by(
            agent_id=agent_id,
            executable_path=path
        ).first()
        
        if existing:
            existing.name = app.get('name')
            existing.version = app.get('version')
            existing.install_directory = app.get('install_directory')
            existing.publisher = app.get('publisher')
            existing.detection_method = app.get('detection_method')
            existing.file_size_bytes = app.get('file_size_bytes')
            existing.last_updated = datetime.now(timezone.utc)
        else:
            db.session.add(server_models.PortableApplication(
                agent_id=agent_id,
                name=app.get('name'),
                version=app.get('version'),
                executable_path=path,
                install_directory=app.get('install_directory'),
                publisher=app.get('publisher'),
                detection_method=app.get('detection_method'),
                file_size_bytes=app.get('file_size_bytes')
            ))
        count += 1
    
    return {'count': count, 'action': 'upserted'}


# =============================================================================
# EOL Data Ingestion API Endpoint
# =============================================================================

@bp.route('/eol-data', methods=['POST'])
@require_auth
def eol_data():
    """
    Receive EOL-specific data from agent.
    Ingests: Windows updates, software metering, product keys, ESU status, warranty info.
    """
    from flask import g
    data = request.get_json() or {}

    agent_id = data.get('agent_id')
    if not agent_id:
        agent_id = str(g.current_agent.agent_id) if g.current_agent else None

    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    sid = short_agent_id(agent_id)

    try:
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if not agent:
            logger.warning(f"[EOL {sid}] Unknown agent")
            return jsonify({'error': 'Unknown agent'}), 404

        results = {}

        # 1. Windows Updates
        updates = data.get('updates', [])
        if updates:
            results['updates'] = _upsert_windows_updates(agent_id, updates)

        # 2. Software Metering
        metering = data.get('metering', [])
        if metering:
            results['metering'] = _upsert_software_metering(agent_id, metering)

        # 3. Product Keys (partial)
        product_keys = data.get('product_keys', [])
        if product_keys:
            results['product_keys'] = _upsert_product_keys(agent_id, product_keys)

        # 4. ESU Status — store on AssetInfo (existing model)
        esu = data.get('esu')
        if esu:
            _update_esu_status(agent_id, esu)
            results['esu'] = {'status': 'updated'}

        # 5. Warranty info — store on AssetInfo (existing model)
        warranty = data.get('warranty')
        if warranty:
            _update_warranty_info(agent_id, warranty)
            results['warranty'] = {'status': 'updated'}

        db.session.commit()

        total_items = sum(r.get('count', 0) for r in results.values() if isinstance(r, dict) and 'count' in r)
        logger.info(f"[EOL {sid}] Processed EOL data: {total_items} items across {len(results)} categories")

        return jsonify({'status': 'ok', 'results': results}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[EOL {sid}] Error: {e}")
        return jsonify({'error': 'EOL data ingestion failed', 'message': str(e)}), 500


def _upsert_windows_updates(agent_id, updates):
    """Upsert Windows update (KB) records."""
    count = 0
    for update in updates:
        kb = update.get('kb_number', '')
        if not kb:
            continue

        existing = server_models.WindowsUpdateRecord.query.filter_by(
            agent_id=agent_id, kb_number=kb
        ).first()

        install_date = None
        if update.get('install_date'):
            try:
                install_date = datetime.strptime(update['install_date'][:10], '%Y-%m-%d').date()
            except:
                pass

        if existing:
            existing.title = update.get('title', existing.title)
            existing.update_type = update.get('update_type', existing.update_type)
            existing.install_date = install_date or existing.install_date
            existing.result_code = update.get('result_code', existing.result_code)
            existing.is_pending = update.get('is_pending', existing.is_pending)
            existing.last_updated = datetime.now(timezone.utc)
        else:
            db.session.add(server_models.WindowsUpdateRecord(
                agent_id=agent_id,
                kb_number=kb,
                title=update.get('title', ''),
                update_type=update.get('update_type', 'Unknown'),
                install_date=install_date,
                result_code=update.get('result_code', 0),
                is_pending=update.get('is_pending', False)
            ))
        count += 1

    return {'count': count, 'action': 'upserted'}


def _upsert_software_metering(agent_id, entries):
    """Upsert software metering (usage frequency) records."""
    count = 0
    for entry in entries:
        exe_name = entry.get('executable_name', '')
        if not exe_name:
            continue

        existing = server_models.SoftwareMeteringRecord.query.filter_by(
            agent_id=agent_id, executable_name=exe_name
        ).first()

        last_used = None
        if entry.get('last_used'):
            try:
                last_used = datetime.fromisoformat(entry['last_used'])
            except:
                pass

        if existing:
            existing.app_name = entry.get('app_name', existing.app_name)
            existing.usage_count = max(existing.usage_count, entry.get('usage_count', 0))
            if last_used:
                existing.last_used = last_used
            existing.source = entry.get('source', existing.source)
            existing.last_updated = datetime.now(timezone.utc)
        else:
            db.session.add(server_models.SoftwareMeteringRecord(
                agent_id=agent_id,
                app_name=entry.get('app_name', ''),
                executable_name=exe_name,
                usage_count=entry.get('usage_count', 0),
                last_used=last_used,
                source=entry.get('source', 'prefetch')
            ))
        count += 1

    return {'count': count, 'action': 'upserted'}


def _upsert_product_keys(agent_id, keys):
    """Upsert partial product key records (last 5 chars only)."""
    count = 0
    for key in keys:
        product = key.get('product_name', '')
        if not product:
            continue

        # Safety: truncate partial key to max 5 chars
        partial = str(key.get('partial_key', ''))
        if len(partial) > 5:
            partial = partial[-5:]

        existing = server_models.ProductKeyRecord.query.filter_by(
            agent_id=agent_id, product_name=product
        ).first()

        if existing:
            existing.partial_key = partial
            existing.key_source = key.get('key_source', existing.key_source)
            existing.license_status = key.get('license_status', existing.license_status)
            existing.last_updated = datetime.now(timezone.utc)
        else:
            db.session.add(server_models.ProductKeyRecord(
                agent_id=agent_id,
                product_name=product,
                partial_key=partial,
                key_source=key.get('key_source', 'Unknown'),
                license_status=key.get('license_status', 'Unknown')
            ))
        count += 1

    return {'count': count, 'action': 'upserted'}


def _update_esu_status(agent_id, esu_data):
    """Update ESU status on AssetInfo record."""
    asset = server_models.AssetInfo.query.filter_by(agent_id=agent_id).first()
    if not asset:
        return

    # Store ESU data as JSON in a flexible field
    esu_json = json.dumps({
        'eligible': esu_data.get('esu_eligible', False),
        'activated': esu_data.get('esu_activated', False),
        'expiry_date': esu_data.get('esu_expiry_date'),
        'detection_method': esu_data.get('detection_method', 'unknown'),
    })
    # Use the existing collected_at field to track last update
    if hasattr(asset, 'esu_status_json'):
        asset.esu_status_json = esu_json
    logger.debug(f"[EOL] Updated ESU status for agent {agent_id[:8]}")


def _update_warranty_info(agent_id, warranty_data):
    """Update warranty info on AssetInfo record."""
    asset = server_models.AssetInfo.query.filter_by(agent_id=agent_id).first()
    if not asset:
        return

    # Store warranty data as JSON
    if hasattr(asset, 'warranty_json'):
        asset.warranty_json = json.dumps({
            'serial_number': warranty_data.get('serial_number', ''),
            'manufacturer': warranty_data.get('manufacturer', ''),
            'model': warranty_data.get('model', ''),
            'warranty_expiry': warranty_data.get('warranty_expiry'),
            'warranty_source': warranty_data.get('warranty_source', 'agent_collected'),
        })
    logger.debug(f"[EOL] Updated warranty info for agent {agent_id[:8]}")


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

    @app.route('/asset-hardware', methods=['POST'])
    @require_auth
    def asset_hardware_root():
        return asset_hardware()

    @app.route('/extended-inventory', methods=['POST'])
    @require_auth
    def extended_inventory_root():
        return extended_inventory()

    @app.route('/eol-data', methods=['POST'])
    @require_auth
    def eol_data_root():
        return eol_data()

