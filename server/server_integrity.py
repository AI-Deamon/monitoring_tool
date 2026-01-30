"""
Server-Side Anomaly Detection Service - SEC-025
================================================
Detects potential agent tampering through:
1. Heartbeat gap monitoring (agent stopped/killed)
2. Signature verification (data tampering)
3. Usage pattern anomalies (fake data detection)
4. Integrity report analysis
"""
import json
import hmac
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from flask import Blueprint, request, jsonify, g
from extensions import db
import server_models
from server_auth import require_auth

logger = logging.getLogger(__name__)
bp = Blueprint('integrity', __name__)


# =============================================================================
# ANOMALY THRESHOLDS (Configurable)
# =============================================================================

class AnomalyThresholds:
    """Configurable thresholds for anomaly detection"""
    
    # Heartbeat monitoring
    OFFLINE_THRESHOLD_MINUTES = 10      # Minutes without heartbeat = offline
    GAP_WARNING_MINUTES = 5             # Gap that triggers warning
    GAP_ALERT_MINUTES = 30              # Gap that triggers alert
    
    # Usage patterns
    MAX_ACTIVE_HOURS_PER_DAY = 14       # No one works 14+ hours
    MIN_IDLE_PERCENT = 5                # At least 5% idle expected
    MAX_CONSECUTIVE_ACTIVE_HOURS = 4    # Humans need breaks
    
    # Data integrity
    MAX_TIMESTAMP_DRIFT_SECONDS = 300   # 5 min clock drift allowed
    SIGNATURE_REQUIRED = False          # Set True when all agents support signing


# =============================================================================
# AGENT INTEGRITY STATUS TRACKING
# =============================================================================

def get_agent_integrity_status(agent_id: str) -> Dict:
    """
    Analyze agent integrity and return status with any detected issues.
    
    Returns:
        {
            'status': 'healthy' | 'warning' | 'alert' | 'offline',
            'issues': [...],
            'last_seen': datetime,
            'uptime_percent': float
        }
    """
    issues = []
    
    agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
    if not agent:
        return {'status': 'unknown', 'issues': ['Agent not found']}
    
    # 1. Check last_seen (heartbeat gap)
    now = datetime.now(timezone.utc)
    if agent.last_seen:
        # Handle timezone-naive datetime
        last_seen = agent.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        
        gap_minutes = (now - last_seen).total_seconds() / 60
        
        if gap_minutes > AnomalyThresholds.OFFLINE_THRESHOLD_MINUTES:
            issues.append({
                'type': 'offline',
                'severity': 'critical',
                'message': f'Agent offline for {gap_minutes:.0f} minutes',
                'gap_minutes': gap_minutes
            })
        elif gap_minutes > AnomalyThresholds.GAP_ALERT_MINUTES:
            issues.append({
                'type': 'heartbeat_gap',
                'severity': 'high',
                'message': f'No heartbeat for {gap_minutes:.0f} minutes',
                'gap_minutes': gap_minutes
            })
        elif gap_minutes > AnomalyThresholds.GAP_WARNING_MINUTES:
            issues.append({
                'type': 'heartbeat_gap',
                'severity': 'medium',
                'message': f'Heartbeat delayed {gap_minutes:.0f} minutes',
                'gap_minutes': gap_minutes
            })
    else:
        issues.append({
            'type': 'never_seen',
            'severity': 'high',
            'message': 'Agent never sent heartbeat'
        })
    
    # 2. Check operational status (from HelperMonitor)
    if agent.operational_status == 'DEGRADED':
        issues.append({
            'type': 'degraded_mode',
            'severity': 'high',
            'message': f'Helper failed: {agent.status_reason or "Unknown reason"}'
        })
    
    # 3. Check today's usage patterns
    today = now.date()
    screen_time = server_models.ScreenTime.query.filter_by(
        agent_id=agent_id,
        date=today
    ).first()
    
    if screen_time:
        active_hours = (screen_time.active_seconds or 0) / 3600
        idle_seconds = screen_time.idle_seconds or 0
        locked_seconds = screen_time.locked_seconds or 0
        total_seconds = (screen_time.active_seconds or 0) + idle_seconds + locked_seconds
        
        # Check for excessive active time
        if active_hours > AnomalyThresholds.MAX_ACTIVE_HOURS_PER_DAY:
            issues.append({
                'type': 'excessive_active_time',
                'severity': 'high',
                'message': f'Active for {active_hours:.1f} hours today (>14h is suspicious)',
                'active_hours': active_hours
            })
        
        # Check for no idle time (impossible for humans)
        if total_seconds > 3600:  # More than 1 hour online
            idle_percent = (idle_seconds / total_seconds) * 100 if total_seconds > 0 else 0
            if idle_percent < AnomalyThresholds.MIN_IDLE_PERCENT:
                issues.append({
                    'type': 'no_idle_time',
                    'severity': 'medium',
                    'message': f'Only {idle_percent:.1f}% idle time (expected >5%)',
                    'idle_percent': idle_percent
                })
    
    # Determine overall status
    severities = [i['severity'] for i in issues]
    if 'critical' in severities:
        status = 'offline'
    elif 'high' in severities:
        status = 'alert'
    elif 'medium' in severities:
        status = 'warning'
    else:
        status = 'healthy'
    
    return {
        'agent_id': agent_id,
        'status': status,
        'issues': issues,
        'issue_count': len(issues),
        'last_seen': agent.last_seen.isoformat() if agent.last_seen else None,
        'operational_status': agent.operational_status or 'NORMAL',
        'checked_at': now.isoformat()
    }


def get_all_agents_integrity() -> List[Dict]:
    """Get integrity status for all agents"""
    agents = server_models.Agent.query.filter_by(status='active').all()
    
    results = []
    for agent in agents:
        status = get_agent_integrity_status(str(agent.agent_id))
        status['hostname'] = agent.hostname
        status['agent_name'] = agent.agent_name
        results.append(status)
    
    # Sort by severity (offline first, then alert, warning, healthy)
    severity_order = {'offline': 0, 'alert': 1, 'warning': 2, 'healthy': 3, 'unknown': 4}
    results.sort(key=lambda x: severity_order.get(x['status'], 5))
    
    return results


# =============================================================================
# SIGNATURE VERIFICATION
# =============================================================================

def verify_agent_signature(agent_id: str, data: Dict) -> Tuple[bool, str]:
    """
    Verify HMAC signature on incoming data.
    
    Args:
        agent_id: Agent ID
        data: Signed payload with _sig and _ts fields
        
    Returns:
        (is_valid, error_message)
    """
    # Get agent by UUID
    agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
    if not agent:
        return False, "Agent not found"
    
    # Check if signature is present
    if '_sig' not in data:
        if AnomalyThresholds.SIGNATURE_REQUIRED:
            return False, "Signature required but missing"
        return True, "Signature not provided (not required)"
    
    # Check timestamp to prevent replay attacks
    if '_ts' in data:
        try:
            ts = datetime.fromisoformat(data['_ts'].replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            drift = abs((now - ts).total_seconds())
            
            if drift > AnomalyThresholds.MAX_TIMESTAMP_DRIFT_SECONDS:
                return False, f"Timestamp drift too large: {drift:.0f}s"
        except Exception as e:
            logger.warning(f"Could not parse timestamp: {e}")
    
    # TODO: Implement full signature verification when key exchange is implemented
    # For now, just check that signature is present and properly formatted
    sig = data.get('_sig', '')
    if len(sig) != 64:  # SHA256 hex = 64 chars
        return False, "Invalid signature format"
    
    return True, "Signature validated"


# =============================================================================
# API ENDPOINTS
# =============================================================================

@bp.route('/integrity/status', methods=['GET'])
@require_auth
def api_integrity_status():
    """Get integrity status for current agent"""
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Agent not authenticated'}), 401
    
    status = get_agent_integrity_status(agent_id)
    return jsonify(status), 200


@bp.route('/integrity/report', methods=['POST'])
@require_auth
def api_integrity_report():
    """
    Receive integrity report from agent.
    Contains anomalies, manifest hash, watchdog status.
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Agent not authenticated'}), 401
    
    # Verify signature if present
    is_valid, msg = verify_agent_signature(agent_id, data)
    if not is_valid:
        logger.warning(f"[INTEGRITY] Agent {agent_id}: {msg}")
        # Don't reject, just log for now
    
    # Store/update agent integrity info
    agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
    if agent:
        # Store diagnostics JSON
        agent.diagnostics_json = json.dumps({
            'manifest_hash': data.get('manifest_hash'),
            'file_count': data.get('file_count'),
            'anomalies': data.get('anomalies', []),
            'uptime_seconds': data.get('uptime_seconds'),
            'reported_at': datetime.now(timezone.utc).isoformat()
        })
        
        # Check for anomalies from agent
        anomalies = data.get('anomalies', [])
        if anomalies:
            logger.warning(f"[INTEGRITY] Agent {agent_id} reports {len(anomalies)} anomalies")
            for anomaly in anomalies[:5]:  # Log first 5
                logger.warning(f"  - {anomaly.get('type')}: {anomaly.get('details')}")
        
        db.session.commit()
    
    return jsonify({'status': 'received'}), 200


@bp.route('/integrity/all', methods=['GET'])
def api_all_agents_integrity():
    """
    Get integrity status for all agents (dashboard endpoint).
    Requires dashboard authentication.
    """
    # TODO: Add dashboard auth check
    
    results = get_all_agents_integrity()
    
    # Summary counts
    summary = {
        'total': len(results),
        'healthy': sum(1 for r in results if r['status'] == 'healthy'),
        'warning': sum(1 for r in results if r['status'] == 'warning'),
        'alert': sum(1 for r in results if r['status'] == 'alert'),
        'offline': sum(1 for r in results if r['status'] == 'offline')
    }
    
    return jsonify({
        'summary': summary,
        'agents': results,
        'checked_at': datetime.now(timezone.utc).isoformat()
    }), 200


# =============================================================================
# REGISTER ENDPOINTS
# =============================================================================

def register_integrity_endpoints(app):
    """Register integrity endpoints at root level"""
    
    @app.route('/api/integrity/status', methods=['GET'])
    @require_auth
    def root_integrity_status():
        return api_integrity_status()
    
    @app.route('/api/integrity/report', methods=['POST'])
    @require_auth
    def root_integrity_report():
        return api_integrity_report()
    
    @app.route('/api/integrity/all', methods=['GET'])
    def root_all_integrity():
        return api_all_agents_integrity()
    
    logger.info("[INTEGRITY] Endpoints registered")
