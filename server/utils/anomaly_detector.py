"""
SentinelEdge Server - Telemetry Anomaly Detection
==================================================
Detects suspicious patterns in agent telemetry that may indicate:
- Agent tampering or bypass attempts
- Clock manipulation
- Data gaps from killed processes

SEC-026: Server-Side Anomaly Detection
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy import func, desc

logger = logging.getLogger(__name__)


class TelemetryAnomalyDetector:
    """
    Analyzes agent telemetry for suspicious patterns.
    
    Detection methods:
    1. Heartbeat gaps - Agent went silent
    2. Zero locked time - User never locks screen (suspicious for full day)
    3. Constant active state - No idle at all (unrealistic)
    4. Clock jumps - Timestamps that don't make sense
    5. Pattern anomalies - Perfect patterns that look automated
    """
    
    # Thresholds for anomaly detection
    HEARTBEAT_GAP_THRESHOLD_SECONDS = 600  # 10 minutes without heartbeat
    MIN_REALISTIC_IDLE_RATIO = 0.02  # At least 2% idle for 8+ hour day
    MAX_REALISTIC_ACTIVE_RATIO = 0.95  # No more than 95% active
    
    def __init__(self, db):
        self.db = db
        self.logger = logging.getLogger('AnomalyDetector')
    
    def analyze_agent(self, agent_id: str, date: datetime.date = None) -> Dict:
        """
        Analyze a single agent's telemetry for anomalies.
        
        Args:
            agent_id: The agent to analyze
            date: Date to analyze (defaults to today)
        
        Returns:
            dict with anomaly findings
        """
        from server_models import ScreenTime, StateChange, AppSession
        
        if date is None:
            date = datetime.utcnow().date()
        
        result = {
            'agent_id': agent_id,
            'date': date.isoformat(),
            'anomalies': [],
            'risk_level': 'low',
            'details': {}
        }
        
        # Get screen time for the day
        screen_time = ScreenTime.query.filter_by(
            agent_id=agent_id,
            date=date
        ).first()
        
        if not screen_time:
            result['details']['no_data'] = True
            return result
        
        # 1. Check for zero locked time (suspicious if working full day)
        total_time = (
            (screen_time.active_seconds or 0) +
            (screen_time.idle_seconds or 0) +
            (screen_time.locked_seconds or 0)
        )
        
        if total_time >= 28800:  # 8+ hours
            if (screen_time.locked_seconds or 0) == 0:
                result['anomalies'].append({
                    'type': 'zero_locked_time',
                    'severity': 'medium',
                    'description': f'No lock events for {total_time/3600:.1f} hours of activity',
                    'detail': 'Most users lock screen for breaks - zero locks is unusual'
                })
        
        # 2. Check for unrealistically high active ratio
        if total_time >= 14400:  # 4+ hours
            active_ratio = (screen_time.active_seconds or 0) / total_time
            idle_ratio = (screen_time.idle_seconds or 0) / total_time
            
            if active_ratio > self.MAX_REALISTIC_ACTIVE_RATIO:
                result['anomalies'].append({
                    'type': 'excessive_active_time',
                    'severity': 'medium',
                    'description': f'Active ratio of {active_ratio*100:.1f}% is unusually high',
                    'detail': 'Normal users have periodic idle time (reading, thinking)'
                })
            
            if idle_ratio < self.MIN_REALISTIC_IDLE_RATIO and total_time >= 28800:
                result['anomalies'].append({
                    'type': 'insufficient_idle_time',
                    'severity': 'low',
                    'description': f'Only {idle_ratio*100:.1f}% idle time over {total_time/3600:.1f} hours',
                    'detail': 'Very low idle time may indicate simulated input'
                })
        
        # 3. Check for state change patterns
        state_changes = StateChange.query.filter(
            StateChange.agent_id == agent_id,
            StateChange.timestamp >= datetime.combine(date, datetime.min.time()),
            StateChange.timestamp < datetime.combine(date + timedelta(days=1), datetime.min.time())
        ).order_by(StateChange.timestamp).all()
        
        if state_changes:
            # Check for suspiciously regular patterns
            if len(state_changes) >= 10:
                intervals = []
                for i in range(1, len(state_changes)):
                    delta = (state_changes[i].timestamp - state_changes[i-1].timestamp).total_seconds()
                    intervals.append(delta)
                
                if intervals:
                    avg_interval = sum(intervals) / len(intervals)
                    variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
                    std_dev = variance ** 0.5
                    
                    # If intervals are suspiciously regular (low std dev)
                    if std_dev < 10 and avg_interval < 300:  # Very regular short intervals
                        result['anomalies'].append({
                            'type': 'regular_state_pattern',
                            'severity': 'high',
                            'description': f'State changes at suspiciously regular intervals (~{avg_interval:.0f}s)',
                            'detail': 'Natural activity has more variation in timing'
                        })
        
        # 4. Check for large time gaps in app sessions
        app_sessions = AppSession.query.filter(
            AppSession.agent_id == agent_id,
            AppSession.start_time >= datetime.combine(date, datetime.min.time()),
            AppSession.start_time < datetime.combine(date + timedelta(days=1), datetime.min.time())
        ).order_by(AppSession.start_time).all()
        
        if len(app_sessions) >= 5:
            gaps = []
            for i in range(1, len(app_sessions)):
                if app_sessions[i-1].end_time and app_sessions[i].start_time:
                    gap = (app_sessions[i].start_time - app_sessions[i-1].end_time).total_seconds()
                    if gap > self.HEARTBEAT_GAP_THRESHOLD_SECONDS:
                        gaps.append({
                            'start': app_sessions[i-1].end_time.isoformat(),
                            'end': app_sessions[i].start_time.isoformat(),
                            'duration_seconds': gap
                        })
            
            if gaps:
                result['anomalies'].append({
                    'type': 'activity_gaps',
                    'severity': 'medium',
                    'description': f'{len(gaps)} gaps in activity tracking (>{self.HEARTBEAT_GAP_THRESHOLD_SECONDS/60:.0f} min)',
                    'detail': 'Gaps may indicate helper process was stopped'
                })
                result['details']['gaps'] = gaps
        
        # Calculate overall risk level
        severities = [a['severity'] for a in result['anomalies']]
        if 'high' in severities:
            result['risk_level'] = 'high'
        elif len([s for s in severities if s == 'medium']) >= 2:
            result['risk_level'] = 'high'
        elif 'medium' in severities:
            result['risk_level'] = 'medium'
        elif severities:
            result['risk_level'] = 'low'
        
        # Add summary stats
        result['details']['screen_time'] = {
            'active_seconds': screen_time.active_seconds or 0,
            'idle_seconds': screen_time.idle_seconds or 0,
            'locked_seconds': screen_time.locked_seconds or 0,
            'away_seconds': screen_time.away_seconds or 0,
            'total_seconds': total_time
        }
        result['details']['state_change_count'] = len(state_changes) if state_changes else 0
        result['details']['session_count'] = len(app_sessions) if app_sessions else 0
        
        return result
    
    def get_fleet_anomalies(self, date: datetime.date = None) -> List[Dict]:
        """
        Analyze all agents for anomalies.
        
        Returns:
            List of agents with anomalies, sorted by risk level
        """
        from server_models import Agent
        
        if date is None:
            date = datetime.utcnow().date()
        
        agents = Agent.query.all()
        results = []
        
        for agent in agents:
            analysis = self.analyze_agent(agent.id, date)
            if analysis['anomalies']:
                results.append(analysis)
        
        # Sort by risk level (high first)
        risk_order = {'high': 0, 'medium': 1, 'low': 2}
        results.sort(key=lambda x: risk_order.get(x['risk_level'], 3))
        
        return results


def register_anomaly_endpoints(app, db):
    """Register anomaly detection API endpoints."""
    from flask import Blueprint, jsonify, request
    from auth import login_required, admin_required
    
    bp = Blueprint('anomaly', __name__, url_prefix='/api/v1/admin')
    detector = TelemetryAnomalyDetector(db)
    
    @bp.route('/anomalies', methods=['GET'])
    @login_required
    @admin_required
    def get_anomalies():
        """Get anomalies for all agents on a specific date."""
        date_str = request.args.get('date')
        if date_str:
            try:
                date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                date = datetime.utcnow().date()
        else:
            date = datetime.utcnow().date()
        
        results = detector.get_fleet_anomalies(date)
        
        return jsonify({
            'date': date.isoformat(),
            'total_anomalies': len(results),
            'high_risk': len([r for r in results if r['risk_level'] == 'high']),
            'medium_risk': len([r for r in results if r['risk_level'] == 'medium']),
            'agents': results
        }), 200
    
    @bp.route('/anomalies/<agent_id>', methods=['GET'])
    @login_required
    @admin_required
    def get_agent_anomalies(agent_id):
        """Get anomalies for a specific agent."""
        date_str = request.args.get('date')
        if date_str:
            try:
                date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                date = datetime.utcnow().date()
        else:
            date = datetime.utcnow().date()
        
        result = detector.analyze_agent(agent_id, date)
        
        return jsonify(result), 200
    
    app.register_blueprint(bp)
    logger.info("[SECURITY] Anomaly detection endpoints registered")
