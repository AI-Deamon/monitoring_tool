"""
SentinelEdge Server - Dashboard Blueprint

Handles both frontend page rendering (Jinja2) and data API endpoints (JSON).
Now includes authentication - users must log in to access dashboard.
"""

import logging
from datetime import datetime, timedelta, date
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, g, session
from sqlalchemy import func, desc, case
from extensions import db
import server_models

# ============================================================================
# AUTHENTICATION IMPORTS
# ============================================================================
from auth import login_required, admin_required, get_user_filter, can_view_agent

# FIX 4: Rate limiting with flask_limiter
logger = logging.getLogger(__name__)

RATE_LIMIT_AVAILABLE = False
limiter = None

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    
    # Limiter will be initialized with app in init_app pattern
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["200 per minute", "1000 per hour"]
    )
    RATE_LIMIT_AVAILABLE = True
    logger.info("Rate limiting enabled (flask_limiter)")
except ImportError:
    logger.warning("flask_limiter not available, rate limiting disabled")
except Exception as e:
    logger.warning(f"Rate limiter init error: {e}")

# Create rate limit decorator (works even if limiter not available)
def api_rate_limit(f):
    """Rate limit decorator that gracefully degrades if limiter unavailable"""
    if limiter and RATE_LIMIT_AVAILABLE:
        return limiter.limit("100 per minute")(f)
    return f

bp = Blueprint('dashboard', __name__, 
               url_prefix='/dashboard',
               template_folder='templates',
               static_folder='static')

# ============================================================================
# FRONTEND ROUTES (Protected by login_required)
# ============================================================================

@bp.route('/')
@login_required
def dashboard_home():
    """Render overview dashboard page."""
    return render_template('dashboard/overview.html', 
                           current_user=g.current_user)

@bp.route('/agents')
@login_required
def agents_list():
    """Render agents list page."""
    return render_template('dashboard/agents.html',
                           current_user=g.current_user)

@bp.route('/agent/<path:agent_id>')
@login_required
def agent_detail(agent_id):
    """Render agent detail page. Note: agent_id might be UUID or string."""
    agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
    if not agent:
        return render_template('dashboard/404.html', message=f"Agent {agent_id} not found"), 404
    
    # Check if user can view this agent (role-based access)
    if not can_view_agent(agent_id):
        return render_template('dashboard/403.html', 
                              message="You don't have permission to view this agent"), 403
    
    return render_template('dashboard/agent_detail.html', 
                           agent=agent, 
                           current_user=g.current_user)

@bp.route('/agent/<path:agent_id>/report')
@login_required
def agent_report(agent_id):
    """
    Render printable/exportable agent activity report.
    
    This page provides:
    - Comprehensive daily activity summary
    - Print-friendly layout for PDF export
    - CSV export for all data
    - Charts for visual analysis
    """
    agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
    if not agent:
        return render_template('dashboard/404.html', message=f"Agent {agent_id} not found"), 404
    return render_template('dashboard/agent_report.html', agent_id=agent_id, agent=agent)


@bp.route('/agent/<path:agent_id>/report-v2')
@login_required
def agent_report_v2(agent_id):
    """
    Clean, professional single-page report (Version 2).
    
    Features:
    - Single-page design for easy printing
    - Smart data filtering (removes 0-minute apps)
    - Card-based metrics
    - Clean typography
    - Print-optimized CSS
    """
    agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
    if not agent:
        return render_template('dashboard/404.html', message=f"Agent {agent_id} not found"), 404
    return render_template('dashboard/agent_report_v2.html', agent_id=agent_id, agent=agent)


@bp.route('/reports')
@login_required
def reports():
    """Render reports page."""
    return render_template('dashboard/reports.html')

# ============================================================================
# API ENDPOINTS (Protected by login_required)
# ============================================================================

@bp.route('/api/overview', methods=['GET'])
@login_required
@api_rate_limit
def api_overview():
    """Get overview metrics for all agents (filtered by user role)."""
    try:
        # Get user filter (None for admin, linked_username for regular users)
        user_filter = get_user_filter()
        
        # Date selection (Time-Travel)
        date_str = request.args.get('date')
        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                target_date = datetime.utcnow().date()
        else:
            target_date = datetime.utcnow().date()
        
        # 1. Agent Counts (Current State - ALWAYS Real-time)
        total_agents = server_models.Agent.query.count()
        
        # Active agents (last seen < 5 min)
        five_min_ago = datetime.utcnow() - timedelta(minutes=5)
        active_agents = server_models.Agent.query.filter(
            server_models.Agent.last_seen >= five_min_ago
        ).count()
        
        # 2. Fleet Scope Metrics
        # Total Applications: Unique apps installed across entire fleet (Inventory)
        total_applications = db.session.query(
            func.count(func.distinct(server_models.AppInventory.name))
        ).scalar() or 0

        # Total Domains: Unique domains visited across fleet on selected date
        total_domains = db.session.query(
            func.count(func.distinct(server_models.DomainUsage.domain))
        ).filter(
            server_models.DomainUsage.date == target_date
        ).scalar() or 0
        
        # 3. Total Screen Time (Selected Date) - From screen_time table (AGENT'S DAILY TOTALS)
        # The agent tracks daily totals and sends them via /screentime endpoint
        # This is the SOURCE OF TRUTH for screen time (active/idle/locked/away)
        screen_time_totals = db.session.query(
            func.sum(server_models.ScreenTime.active_seconds),
            func.sum(server_models.ScreenTime.idle_seconds),
            func.sum(server_models.ScreenTime.locked_seconds),
            func.sum(server_models.ScreenTime.away_seconds)
        ).filter(
            server_models.ScreenTime.date == target_date
        ).first()
        
        total_active = int(screen_time_totals[0] or 0) if screen_time_totals else 0
        total_idle = int(screen_time_totals[1] or 0) if screen_time_totals else 0
        total_locked = int(screen_time_totals[2] or 0) if screen_time_totals else 0
        total_away = int(screen_time_totals[3] or 0) if screen_time_totals else 0

        

        # 4. Top App (Selected Date - Fleet Wide)
        # Sum duration per app across all agents
        top_app = db.session.query(
            server_models.AppUsage.app,
            func.sum(server_models.AppUsage.duration_seconds).label('total')
        ).filter(
            server_models.AppUsage.date == target_date
        ).group_by(
            server_models.AppUsage.app
        ).order_by(
            desc('total')
        ).first()
        
        # 5. Top Domain (Selected Date - Fleet Wide)
        top_domain = db.session.query(
            server_models.DomainUsage.domain,
            func.sum(server_models.DomainUsage.duration_seconds).label('total')
        ).filter(
            server_models.DomainUsage.date == target_date
        ).group_by(
            server_models.DomainUsage.domain
        ).order_by(
            desc('total')
        ).first()
        
        # 6. Top 5 Agents by Idle Time (Selected Date)
        top_idle_agents = db.session.query(
            server_models.Agent.hostname,
            server_models.ScreenTime.idle_seconds
        ).join(
            server_models.ScreenTime,
            server_models.Agent.agent_id == server_models.ScreenTime.agent_id
        ).filter(
            server_models.ScreenTime.date == target_date,
            server_models.ScreenTime.idle_seconds > 0
        ).order_by(
            desc(server_models.ScreenTime.idle_seconds)
        ).limit(5).all()
        
        # 7. Top 5 Agents by Active Time (Selected Date)
        top_active_agents = db.session.query(
            server_models.Agent.hostname,
            server_models.ScreenTime.active_seconds
        ).join(
            server_models.ScreenTime,
            server_models.Agent.agent_id == server_models.ScreenTime.agent_id
        ).filter(
            server_models.ScreenTime.date == target_date,
            server_models.ScreenTime.active_seconds > 0
        ).order_by(
            desc(server_models.ScreenTime.active_seconds)
        ).limit(5).all()
        
        # 8. Top 5 Agents by Locked Time (Selected Date)
        top_locked_agents = db.session.query(
            server_models.Agent.hostname,
            server_models.ScreenTime.locked_seconds
        ).join(
            server_models.ScreenTime,
            server_models.Agent.agent_id == server_models.ScreenTime.agent_id
        ).filter(
            server_models.ScreenTime.date == target_date,
            server_models.ScreenTime.locked_seconds > 0
        ).order_by(
            desc(server_models.ScreenTime.locked_seconds)
        ).limit(5).all()
        
        return jsonify({
            'total_agents': total_agents,
            'active_agents': active_agents,
            'offline_agents': total_agents - active_agents,
            'total_applications': total_applications,
            'total_domains': total_domains,
            'screen_time': {
                'active': int(total_active),
                'idle': total_idle,
                'locked': total_locked,
                'away': total_away
            },

            'top_app': {
                'name': top_app[0] if top_app else 'N/A',
                'duration': int(top_app[1]) if top_app else 0
            },
            'top_domain': {
                'name': top_domain[0] if top_domain else 'N/A',
                'duration': int(top_domain[1]) if top_domain else 0
            },
            'top_idle_agents': [
                {'hostname': agent[0], 'idle_seconds': int(agent[1])}
                for agent in top_idle_agents
            ],
            'top_active_agents': [
                {'hostname': agent[0], 'active_seconds': int(agent[1])}
                for agent in top_active_agents
            ],
            'top_locked_agents': [
                {'hostname': agent[0], 'locked_seconds': int(agent[1])}
                for agent in top_locked_agents
            ]
        }), 200
    
    except Exception as e:
        logger.error(f"Overview API error: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/agents', methods=['GET'])
@login_required
@api_rate_limit
def api_agents():
    """
    Get detailed summary for all agents - Multi-Agent Comparison View.
    
    Returns per-agent metrics for the selected date:
    - Agent info (hostname, status, first/last seen)
    - Screen time (active, idle, locked hours)
    - Top app and usage stats
    - Domain usage stats  
    - App inventory count
    
    SECURITY: Non-admin users only see agents with their linked_username data.
    """
    try:
        # ISSUE-003 FIX: Get user filter for role-based access
        user_filter = get_user_filter()
        
        # Date selection
        date_str = request.args.get('date')
        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                target_date = datetime.utcnow().date()
        else:
            target_date = datetime.utcnow().date()

        five_min_ago = datetime.utcnow() - timedelta(minutes=5)
        
        # ISSUE-003 FIX: Filter agents based on user role
        if user_filter:
            # Non-admin: Only get agents that have data for this user's linked_username
            # The linked_username can be:
            #   - Just the username (e.g., "sumant")
            #   - Domain\username (e.g., "BSOLAD\sumant")
            # We check both formats
            
            # Build a list of possible username formats to match
            linked_username = user_filter
            possible_usernames = [linked_username]
            
            # If no domain prefix, also check with any domain prefix
            if '\\' not in linked_username:
                # Will use LIKE query to match any domain prefix
                pass  # Handle below
            else:
                # If has domain, also check without domain
                bare_username = linked_username.split('\\')[-1]
                possible_usernames.append(bare_username)
            
            # Find agent IDs that have data for this username
            # Use AgentCurrentStatus table which has username field
            from sqlalchemy import or_
            
            if '\\' not in linked_username:
                # Match username or any domain\username
                linked_agent_ids = db.session.query(
                    server_models.AgentCurrentStatus.agent_id
                ).filter(
                    or_(
                        server_models.AgentCurrentStatus.username == linked_username,
                        server_models.AgentCurrentStatus.username.ilike(f'%\\{linked_username}')
                    )
                ).distinct().all()
            else:
                # Match exact or bare username
                linked_agent_ids = db.session.query(
                    server_models.AgentCurrentStatus.agent_id
                ).filter(
                    server_models.AgentCurrentStatus.username.in_(possible_usernames)
                ).distinct().all()
            
            linked_agent_ids = [a[0] for a in linked_agent_ids]
            
            if linked_agent_ids:
                agents = server_models.Agent.query.filter(
                    server_models.Agent.agent_id.in_(linked_agent_ids)
                ).all()
            else:
                agents = []
            logger.debug(f"[API] User {user_filter} can view {len(agents)} agents")
        else:
            # Admin: See all agents
            agents = server_models.Agent.query.all()
        
        # ================================================================
        # PERFORMANCE: Pre-fetch all data to avoid N+1 queries
        # ================================================================
        
        # Date range for session queries
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date, datetime.max.time())
        
        # 1. SCREEN TIME: From screen_time table (AGENT'S DAILY TOTALS - SOURCE OF TRUTH)
        # Agent tracks and sends daily totals via /screentime endpoint
        screen_time_records = server_models.ScreenTime.query.filter_by(
            date=target_date
        ).all()
        
        screen_time_map = {
            st.agent_id: {
                'active': st.active_seconds or 0,
                'idle': st.idle_seconds or 0,
                'locked': st.locked_seconds or 0
            } for st in screen_time_records
        }
        
        # 2. App Usage - Get top app per agent (subquery)
        app_totals = db.session.query(
            server_models.AppUsage.agent_id,
            server_models.AppUsage.app,
            server_models.AppUsage.duration_seconds
        ).filter_by(date=target_date).all()
        
        # Build top app map per agent
        app_map = {}  # agent_id -> {top_app, total_apps, total_duration}
        for rec in app_totals:
            if rec.agent_id not in app_map:
                app_map[rec.agent_id] = {'apps': [], 'total_duration': 0, 'total_apps': 0}
            app_map[rec.agent_id]['apps'].append((rec.app, rec.duration_seconds))
            app_map[rec.agent_id]['total_duration'] += rec.duration_seconds
            app_map[rec.agent_id]['total_apps'] += 1
        
        # Sort to get top app per agent
        for agent_id in app_map:
            apps = app_map[agent_id]['apps']
            apps.sort(key=lambda x: x[1], reverse=True)
            app_map[agent_id]['top_app'] = apps[0][0] if apps else None
            app_map[agent_id]['top_app_duration'] = apps[0][1] if apps else 0
        
        # 3. Domain Usage totals
        domain_totals = db.session.query(
            server_models.DomainUsage.agent_id,
            func.count(server_models.DomainUsage.domain).label('domain_count'),
            func.sum(server_models.DomainUsage.duration_seconds).label('total_duration')
        ).filter_by(date=target_date).group_by(
            server_models.DomainUsage.agent_id
        ).all()
        domain_map = {d.agent_id: {'count': d.domain_count, 'duration': d.total_duration or 0} for d in domain_totals}
        
        # 4. App Inventory counts
        inv_counts = db.session.query(
            server_models.AppInventory.agent_id,
            func.count(server_models.AppInventory.id).label('app_count')
        ).group_by(server_models.AppInventory.agent_id).all()
        inv_map = {i.agent_id: i.app_count for i in inv_counts}
        
        # 5. Live Status (from AgentCurrentStatus)
        live_records = server_models.AgentCurrentStatus.query.all()
        live_map = {l.agent_id: l for l in live_records}


        # ================================================================
        # BUILD RESULT
        # ================================================================
        result = []
        for agent in agents:
            # Status check
            is_online = agent.last_seen and agent.last_seen >= five_min_ago
            
            # Screen time - From screen_time table (AGENT'S DAILY TOTALS - SOURCE OF TRUTH)
            screen_data = screen_time_map.get(agent.agent_id, {'active': 0, 'idle': 0, 'locked': 0})
            active_seconds = screen_data['active']
            idle_seconds = screen_data['idle']
            locked_seconds = screen_data['locked']
            total_screen_seconds = active_seconds + idle_seconds + locked_seconds
            

            # App usage
            app_data = app_map.get(agent.agent_id, {})
            top_app = app_data.get('top_app')
            top_app_duration = app_data.get('top_app_duration', 0)
            total_apps_used = app_data.get('total_apps', 0)
            
            # Domain usage
            domain_data = domain_map.get(agent.agent_id, {})
            domains_visited = domain_data.get('count', 0)
            
            # Inventory
            installed_apps = inv_map.get(agent.agent_id, 0)
            
            # Live status - ONLY use if agent is actually online
            # FIX: Offline agents were showing stale "active" state
            live = live_map.get(agent.agent_id)
            if is_online and live:
                # Agent is online - use live data
                current_app = live.current_app
                # Double-check: if live.last_seen is stale, override to offline
                live_is_stale = live.last_seen and (datetime.utcnow() - live.last_seen).total_seconds() > 300
                current_state = 'offline' if live_is_stale else (live.current_state or 'active')
                username = live.username
            else:
                # Agent is offline - don't use stale live data
                current_app = None
                current_state = 'offline'
                username = live.username if live else None

            result.append({
                'agent_id': str(agent.agent_id),
                'hostname': agent.hostname or 'Unknown',
                'os': agent.os,
                'username': username,
                'status': 'online' if is_online else 'offline',
                'is_online': is_online,
                'first_seen': agent.created_at.isoformat() if agent.created_at else None,
                'last_seen': agent.last_seen.isoformat() if agent.last_seen else None,
                
                # NEW: Telemetry tracking for silent failure detection
                'last_telemetry_time': agent.last_telemetry_time.isoformat() if agent.last_telemetry_time else None,
                'operational_status': agent.operational_status or 'NORMAL',
                'status_reason': agent.status_reason,
                # Flag agents that are "online" but haven't sent telemetry in 10+ minutes
                'telemetry_stale': is_online and (
                    not agent.last_telemetry_time or 
                    (datetime.utcnow() - agent.last_telemetry_time).total_seconds() > 600
                ),
                
                # Screen Time
                'active_seconds': active_seconds,
                'idle_seconds': idle_seconds,
                'locked_seconds': locked_seconds,
                'total_screen_seconds': total_screen_seconds,
                'active_hours': round(active_seconds / 3600, 2),
                
                # App Usage
                'top_app': top_app,
                'top_app_duration': top_app_duration,
                'total_apps_used': total_apps_used,
                
                # Current Activity (Live)
                'current_app': current_app,
                'current_state': current_state,
                
                # Domain Usage
                'domains_visited': domains_visited,
                
                # Inventory
                'installed_apps': installed_apps
            })
            
        return jsonify({'data': result}), 200
    except Exception as e:
        logger.error(f"Agents API error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/agent/<path:agent_id>/screentime', methods=['GET'])
@api_rate_limit
def api_agent_screentime(agent_id):
    """Get agent screen time data (7-day history)."""
    try:
        start_date = datetime.utcnow().date() - timedelta(days=6)
        
        # Try to find by UUID first, then by numeric ID (for backwards compatibility)
        records = server_models.ScreenTime.query.filter(
            server_models.ScreenTime.agent_id == agent_id,
            server_models.ScreenTime.date >= start_date
        ).order_by(server_models.ScreenTime.date).all()
        
        if not records:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    records = server_models.ScreenTime.query.filter(
                        server_models.ScreenTime.agent_id == agent.agent_id,
                        server_models.ScreenTime.date >= start_date
                    ).order_by(server_models.ScreenTime.date).all()
            except ValueError:
                pass
        
        data = {
            'labels': [],
            'active': [],
            'idle': [],
            'locked': [],
            'away': []
        }
        
        # Fill in gaps with 0s
        record_map = {r.date: r for r in records}
        for i in range(7):
            d = start_date + timedelta(days=i)
            data['labels'].append(d.strftime('%a %d'))
            rec = record_map.get(d)
            data['active'].append(rec.active_seconds if rec else 0)
            data['idle'].append(rec.idle_seconds if rec else 0)
            data['locked'].append(rec.locked_seconds if rec else 0)
            data['away'].append(rec.away_seconds if rec and rec.away_seconds else 0)
            
        return jsonify(data), 200
    except Exception as e:
        logger.error(f"Agent Screentime API error: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/agent/<path:agent_id>/apps', methods=['GET'])
@api_rate_limit
def api_agent_apps(agent_id):
    """
    Get top 20 apps by usage PLUS ongoing session.
    
    Returns:
        - data: List of completed app usage from app_usage table
        - ongoing: Current app session from agent_current_status (if any)
        - combined_total: Total duration including ongoing session
    """
    try:
        date_str = request.args.get('date')
        if not date_str:
            target_date = datetime.utcnow().date()
        else:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Get completed app usage from app_usage table
        # Try to find by UUID first, then by numeric ID (for backwards compatibility)
        apps = server_models.AppUsage.query.filter_by(
            agent_id=agent_id,
            date=target_date
        ).order_by(desc(server_models.AppUsage.duration_seconds)).limit(20).all()
        
        if not apps:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    apps = server_models.AppUsage.query.filter_by(
                        agent_id=agent.agent_id,
                        date=target_date
                    ).order_by(desc(server_models.AppUsage.duration_seconds)).limit(20).all()
            except ValueError:
                pass
        
        total_completed = sum(a.duration_seconds for a in apps) or 0
        
        result = [{
            'name': server_models.get_friendly_app_name(a.app),
            'exe': a.app,
            'duration': a.duration_seconds,
            'sessions': a.session_count,
            'percentage': 0,  # Will calculate after including ongoing
            'is_ongoing': False
        } for a in apps]
        
        # Get ongoing session from agent_current_status
        ongoing = None
        live_status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
        
        if not live_status:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    live_status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent.agent_id).first()
            except ValueError:
                pass
        
        if live_status and live_status.current_app:
            # Only count as ongoing if last_seen is recent (within 2 minutes)
            is_recent = live_status.last_seen and \
                        (datetime.utcnow() - live_status.last_seen).total_seconds() < 120
            
            if is_recent:
                ongoing = {
                    'name': server_models.get_friendly_app_name(live_status.current_app),
                    'exe': live_status.current_app,
                    'duration': live_status.duration_seconds or 0,
                    'sessions': '-',  # Ongoing session
                    'percentage': 0,
                    'is_ongoing': True,
                    'window_title': live_status.window_title,
                    'session_start': live_status.session_start.isoformat() if live_status.session_start else None
                }
                
                # Remove ongoing app from completed list to avoid duplicates
                result = [app for app in result if app['exe'] != live_status.current_app]
        
        # Calculate combined total for percentage
        ongoing_duration = ongoing['duration'] if ongoing else 0
        total_completed = sum(app['duration'] for app in result)  # Recalculate after removing duplicates
        combined_total = total_completed + ongoing_duration
        
        # Calculate percentages
        if combined_total > 0:
            for app in result:
                app['percentage'] = round((app['duration'] / combined_total) * 100, 1)
            if ongoing:
                ongoing['percentage'] = round((ongoing['duration'] / combined_total) * 100, 1)
        
        return jsonify({
            'data': result,
            'ongoing': ongoing,
            'totals': {
                'completed': total_completed,
                'ongoing': ongoing_duration,
                'combined': combined_total
            }
        }), 200
    except Exception as e:
        logger.error(f"Agent Apps API error: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/agent/<path:agent_id>/domains', methods=['GET'])
@api_rate_limit
def api_agent_domains(agent_id):
    """
    Get top 20 domains by usage PLUS ongoing session.
    
    Returns:
        - data: List of completed domain usage from domain_usage table
        - ongoing: Current domain from agent_current_status (if any)
    """
    try:
        date_str = request.args.get('date')
        if not date_str:
            target_date = datetime.utcnow().date()
        else:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
        # Get completed domain usage
        # Try to find by UUID first, then by numeric ID (for backwards compatibility)
        domains = server_models.DomainUsage.query.filter_by(
            agent_id=agent_id,
            date=target_date
        ).order_by(desc(server_models.DomainUsage.duration_seconds)).limit(20).all()
        
        if not domains:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    domains = server_models.DomainUsage.query.filter_by(
                        agent_id=agent.agent_id,
                        date=target_date
                    ).order_by(desc(server_models.DomainUsage.duration_seconds)).limit(20).all()
            except ValueError:
                pass
        
        total_completed = sum(d.duration_seconds for d in domains) or 0
        
        result = [{
            'domain': d.domain,
            'browser': d.browser,
            'duration': d.duration_seconds,
            'sessions': d.session_count,
            'is_ongoing': False
        } for d in domains]
        
        # Get ongoing domain from agent_current_status
        ongoing = None
        live_status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
        
        if not live_status:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    live_status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent.agent_id).first()
            except ValueError:
                pass
        
        if live_status and live_status.current_domain:
            # Only count as ongoing if last_seen is recent (within 2 minutes)
            is_recent = live_status.last_seen and \
                        (datetime.utcnow() - live_status.last_seen).total_seconds() < 120
            
            if is_recent:
                ongoing = {
                    'domain': live_status.current_domain,
                    'browser': live_status.current_browser,
                    'duration': live_status.domain_duration_seconds or 0,
                    'sessions': '-',
                    'is_ongoing': True
                }
                
                # Remove ongoing domain from completed list to avoid duplicates
                result = [d for d in result if d['domain'] != live_status.current_domain]
        
        # Recalculate totals after removing duplicates
        total_completed = sum(d['duration'] for d in result)
        ongoing_duration = ongoing['duration'] if ongoing else 0
        combined_total = total_completed + ongoing_duration
        
        return jsonify({
            'data': result,
            'ongoing': ongoing,
            'totals': {
                'completed': total_completed,
                'ongoing': ongoing_duration,
                'combined': combined_total
            }
        }), 200
    except Exception as e:
        logger.error(f"Agent Domains API error: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/agent/<path:agent_id>/inventory', methods=['GET'])
@api_rate_limit
def api_agent_inventory(agent_id):
    """Get application inventory."""
    try:
        # Try to find by UUID first, then by numeric ID (for backwards compatibility)
        apps = server_models.AppInventory.query.filter_by(
            agent_id=agent_id
        ).order_by(server_models.AppInventory.name).all()
        
        if not apps:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    apps = server_models.AppInventory.query.filter_by(
                        agent_id=agent.agent_id
                    ).order_by(server_models.AppInventory.name).all()
            except ValueError:
                pass
        
        result = [a.to_dict() for a in apps]
        return jsonify({'data': result}), 200
    except Exception as e:
        logger.error(f"Agent Inventory API error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/agent/<path:agent_id>/full-report', methods=['GET'])
@api_rate_limit
def api_agent_full_report(agent_id):
    """
    COMPREHENSIVE AGENT REPORT - Connects ALL database tables for one agent.
    
    Returns everything for a specific agent on a given date:
    - Agent info (hostname, OS, first/last seen)
    - Live status (current app, state)
    - Screen time (active, idle, locked breakdown)
    - App usage (all apps with durations)
    - App sessions (detailed session history)
    - Domain usage (all domains with durations)
    - Domain visits (raw visit history)
    - App inventory (installed applications)
    - Inventory changes (install/uninstall audit)
    """
    try:
        # Parse date
        date_str = request.args.get('date')
        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                target_date = datetime.utcnow().date()
        else:
            target_date = datetime.utcnow().date()
        
        # Date range for queries
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date, datetime.max.time())
        
        five_min_ago = datetime.utcnow() - timedelta(minutes=5)
        
        # ================================================================
        # 1. AGENT INFO
        # ================================================================
        # Try to find agent by UUID first, then by numeric ID (for backwards compatibility)
        import uuid
        try:
            # Check if agent_id is a valid UUID
            uuid.UUID(agent_id)
            agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        except ValueError:
            # If not a valid UUID, try numeric ID
            try:
                agent_id_num = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=agent_id_num).first()
            except ValueError:
                agent = None
        
        if not agent:
            try:
                # Try to parse as numeric ID
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
            except ValueError:
                pass
                
        if not agent:
            return jsonify({'error': 'Agent not found'}), 404
        
        is_online = agent.last_seen and agent.last_seen >= five_min_ago
        
        # Try to find username from various sources
        username = None
        
        # Use resolved agent UUID for all subsequent queries
        resolved_agent_id = str(agent.agent_id)
        
        # Source 1: Live Status
        live_status = server_models.AgentCurrentStatus.query.filter_by(agent_id=resolved_agent_id).first()
        if live_status and live_status.username:
            username = live_status.username
            
        # Source 2: Screen Time record (if live status didn't have it)
        if not username:
            st_rec = server_models.ScreenTime.query.filter_by(agent_id=resolved_agent_id).order_by(desc(server_models.ScreenTime.date)).first()
            if st_rec and st_rec.username:
                username = st_rec.username
        
        # Find first activity today (earliest app session start)
        first_session_today = server_models.AppSession.query.filter(
            server_models.AppSession.agent_id == resolved_agent_id,
            server_models.AppSession.start_time >= start_dt,
            server_models.AppSession.start_time <= end_dt
        ).order_by(server_models.AppSession.start_time.asc()).first()
        
        first_seen_today = first_session_today.start_time.isoformat() if first_session_today else None
        
        # Find last activity today (latest app session)
        last_session_today = server_models.AppSession.query.filter(
            server_models.AppSession.agent_id == resolved_agent_id,
            server_models.AppSession.start_time >= start_dt,
            server_models.AppSession.start_time <= end_dt
        ).order_by(server_models.AppSession.start_time.desc()).first()
        
        last_seen_today = None
        total_tracked_seconds = 0
        if last_session_today:
            if last_session_today.end_time:
                last_seen_today = last_session_today.end_time.isoformat()
            else:
                last_seen_today = last_session_today.start_time.isoformat()
        
        # Calculate total tracked time (last - first)
        if first_session_today and last_session_today:
            first_ts = first_session_today.start_time
            last_ts = last_session_today.end_time or last_session_today.start_time
            total_tracked_seconds = max(0, int((last_ts - first_ts).total_seconds()))
                
        agent_info = {
            'agent_id': str(agent.agent_id),
            'hostname': agent.hostname or 'Unknown',
            'os': agent.os,
            'version': agent.version,
            'username': username,
            'status': 'online' if is_online else 'offline',
            'is_online': is_online,
            'registered_at': agent.created_at.isoformat() if agent.created_at else None,
            'first_seen': agent.created_at.isoformat() if agent.created_at else None,
            'first_seen_today': first_seen_today,
            'last_seen_today': last_seen_today,
            'total_tracked_seconds': total_tracked_seconds,
            'last_seen': agent.last_seen.isoformat() if agent.last_seen else None,
            'is_viewing_today': target_date == datetime.utcnow().date()
        }
        
        # ================================================================
        # 2. LIVE STATUS (from AgentCurrentStatus)
        # FIX: Only show live data if agent is actually online
        # ================================================================
        live_data = None
        if live_status and is_online:
            # Check if live data is stale (last_seen > 5 min ago)
            live_is_stale = live_status.last_seen and \
                            (datetime.utcnow() - live_status.last_seen).total_seconds() > 300
            
            friendly = server_models.get_friendly_app_name(live_status.current_app)
            live_data = {
                'current_app': friendly if not live_is_stale else None,
                'current_app_exe': live_status.current_app if not live_is_stale else None,
                'window_title': live_status.window_title if not live_is_stale else None,
                'current_state': 'offline' if live_is_stale else (live_status.current_state or 'offline'),
                'session_start': live_status.session_start.isoformat() if live_status.session_start else None,
                'duration_seconds': live_status.duration_seconds if not live_is_stale else 0,
                'last_seen': live_status.last_seen.isoformat() if live_status.last_seen else None,
                'is_stale': live_is_stale
            }
        elif live_status:
            # Agent offline but has historical data
            live_data = {
                'current_app': None,
                'current_app_exe': None,
                'window_title': None,
                'current_state': 'offline',
                'session_start': None,
                'duration_seconds': 0,
                'last_seen': live_status.last_seen.isoformat() if live_status.last_seen else None,
                'is_stale': True
            }
        
        # ================================================================
        # 3. SCREEN TIME - From screen_time table (AGENT'S DAILY TOTALS - SOURCE OF TRUTH)
        # ================================================================
        screen_time = server_models.ScreenTime.query.filter_by(
            agent_id=resolved_agent_id,
            date=target_date
        ).first()
        
        # Use screen_time table as single source of truth
        active_s = screen_time.active_seconds if screen_time else 0
        idle_s = screen_time.idle_seconds if screen_time else 0
        locked_s = screen_time.locked_seconds if screen_time else 0
        away_s = (screen_time.away_seconds or 0) if screen_time else 0
        
        screen_data = {
            'date': target_date.isoformat(),
            'active_seconds': active_s,
            'idle_seconds': idle_s,
            'locked_seconds': locked_s,
            'away_seconds': away_s,
            'total_seconds': active_s + idle_s + locked_s + away_s,
            'active_hours': round(active_s / 3600, 2),
            'away_note': 'Prolonged lock (>2h) classified as away'
        }
        
        # ================================================================
        # 4. APP USAGE (Daily aggregation) - FILTERED
        # ================================================================
        app_usage = server_models.AppUsage.query.filter_by(
            agent_id=resolved_agent_id,
            date=target_date
        ).order_by(desc(server_models.AppUsage.duration_seconds)).all()
        
        # Filter out system apps
        filtered_app_usage = [a for a in app_usage if not server_models.is_system_app(a.app)]
        total_app_duration = sum(a.duration_seconds for a in filtered_app_usage) or 1
        app_usage_data = [{
            'app': server_models.get_friendly_app_name(a.app),
            'exe': a.app,
            'duration_seconds': a.duration_seconds,
            'session_count': a.session_count,
            'percentage': round((a.duration_seconds / total_app_duration) * 100, 1)
        } for a in filtered_app_usage]
        
        # ================================================================
        # 5. APP SESSIONS (Detailed history) - FILTERED
        # ================================================================
        app_sessions = server_models.AppSession.query.filter(
            server_models.AppSession.agent_id == resolved_agent_id,
            server_models.AppSession.start_time >= start_dt,
            server_models.AppSession.start_time <= end_dt
        ).order_by(desc(server_models.AppSession.start_time)).limit(200).all()
        
        # Filter out system apps from sessions
        filtered_sessions = [s for s in app_sessions if not server_models.is_system_app(s.app)]
        app_sessions_data = [{
            'app': s.app,
            'window_title': s.window_title,
            'start_time': s.start_time.isoformat() if s.start_time else None,
            'end_time': s.end_time.isoformat() if s.end_time else None,
            'duration_seconds': s.duration_seconds
        } for s in filtered_sessions[:100]]
        
        # ================================================================
        # 6. DOMAIN USAGE (Daily aggregation) - FILTERED + CLASSIFIED
        # ================================================================
        domain_usage = server_models.DomainUsage.query.filter_by(
            agent_id=resolved_agent_id,
            date=target_date
        ).order_by(desc(server_models.DomainUsage.duration_seconds)).all()
        
        # Filter out internal/system domains
        filtered_domain_usage = [d for d in domain_usage if not server_models.is_internal_domain(d.domain)]
        
        # Apply classification rules to map pseudo-domains to real domains
        try:
            from domain_classifier import get_classifier
            classifier = get_classifier(db)
            
            # Group by classified domain (consolidate pseudo-domains)
            classified_domains = {}
            for d in filtered_domain_usage:
                # Try to classify the domain
                result = classifier.classify(d.domain, None)
                # Use classified domain if available, otherwise keep original
                classified_domain = result.get('domain') or d.domain
                
                # NOTE: We do NOT skip any domains - show everything!
                # (Previously we skipped 'ignore' action, but user wants all domains)
                
                # Aggregate by classified domain
                if classified_domain in classified_domains:
                    classified_domains[classified_domain]['duration_seconds'] += d.duration_seconds
                    classified_domains[classified_domain]['session_count'] += (d.session_count or 1)
                else:
                    classified_domains[classified_domain] = {
                        'domain': classified_domain,
                        'browser': d.browser,
                        'duration_seconds': d.duration_seconds,
                        'session_count': d.session_count or 1
                    }
            
            # Convert to list and sort by duration
            domain_usage_data = sorted(
                classified_domains.values(), 
                key=lambda x: x['duration_seconds'], 
                reverse=True
            )
        except Exception as e:
            logger.warning(f"Classification failed, using raw domains: {e}")
            # Fallback to unclassified data
            domain_usage_data = [{
                'domain': d.domain,
                'browser': d.browser,
                'duration_seconds': d.duration_seconds,
                'session_count': d.session_count
            } for d in filtered_domain_usage]
        
        # ================================================================
        # 7. DOMAIN VISITS (Raw history) - FILTERED
        # ================================================================
        domain_visits = server_models.DomainVisit.query.filter(
            server_models.DomainVisit.agent_id == resolved_agent_id,
            server_models.DomainVisit.visited_at >= start_dt,
            server_models.DomainVisit.visited_at <= end_dt
        ).order_by(desc(server_models.DomainVisit.visited_at)).limit(200).all()
        
        # Filter out internal domains
        filtered_visits = [v for v in domain_visits if not server_models.is_internal_domain(v.domain)]
        domain_visits_data = [{
            'domain': v.domain,
            'url': v.url,
            'browser': v.browser,
            'visited_at': v.visited_at.isoformat() if v.visited_at else None
        } for v in filtered_visits[:100]]
        
        # ================================================================
        # 8. APP INVENTORY - FILTERED & CONSOLIDATED
        # ================================================================
        inventory = server_models.AppInventory.query.filter_by(
            agent_id=resolved_agent_id
        ).order_by(server_models.AppInventory.name).all()
        
        # Convert to list of dicts and filter system apps
        raw_inventory_data = [{
            'name': a.name,
            'version': a.version,
            'publisher': a.publisher,
            'install_location': a.install_location,
            'install_date': a.install_date.isoformat() if a.install_date else None,
            'source': a.source,
            'last_seen': a.last_seen.isoformat() if a.last_seen else None
        } for a in inventory if not server_models.is_system_inventory_app(a.name)]
        
        # Consolidate Python versions (e.g., merge "Python 3.11.9 Core Interpreter" into "Python 3.11.9")
        inventory_data = server_models.consolidate_python_versions(raw_inventory_data)
        
        # ================================================================
        # 9. INVENTORY CHANGES (Audit history)
        # ================================================================
        inv_changes = server_models.AppInventoryChange.query.filter(
            server_models.AppInventoryChange.agent_id == resolved_agent_id,
            server_models.AppInventoryChange.timestamp >= start_dt,
            server_models.AppInventoryChange.timestamp <= end_dt
        ).order_by(desc(server_models.AppInventoryChange.timestamp)).all()
        
        inv_changes_data = [{
            'change_type': c.change_type,
            'app_name': c.app_name,
            'version': c.version,
            'timestamp': c.timestamp.isoformat() if c.timestamp else None
        } for c in inv_changes]
        
        # ================================================================
        # BUILD RESPONSE
        # ================================================================
        return jsonify({
            'date': target_date.isoformat(),
            'agent': agent_info,
            'live_status': live_data,
            'screen_time': screen_data,
            'app_usage': {
                'count': len(app_usage_data),
                'total_duration': sum(a['duration_seconds'] for a in app_usage_data),
                'top_app': app_usage_data[0]['app'] if app_usage_data else None,
                'data': app_usage_data
            },
            'app_sessions': {
                'count': len(app_sessions_data),
                'data': app_sessions_data
            },
            'domain_usage': {
                'count': len(domain_usage_data),
                'total_duration': sum(d['duration_seconds'] for d in domain_usage_data),
                'top_domain': domain_usage_data[0]['domain'] if domain_usage_data else None,
                'data': domain_usage_data
            },
            'domain_visits': {
                'count': len(domain_visits_data),
                'data': domain_visits_data
            },
            'inventory': {
                'count': len(inventory_data),
                'data': inventory_data
            },
            'inventory_changes': {
                'count': len(inv_changes_data),
                'data': inv_changes_data
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Agent Full Report API error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/agent/<path:agent_id>/activity-timeline', methods=['GET'])
def api_agent_activity_timeline(agent_id):
    """Get hourly activity breakdown."""
    try:
        date_str = request.args.get('date')
        if not date_str:
            target_date = datetime.utcnow().date()
            start_dt = datetime.combine(target_date, datetime.min.time())
            end_dt = datetime.utcnow()
        else:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_dt = datetime.combine(target_date, datetime.min.time())
            end_dt = datetime.combine(target_date, datetime.max.time())

        # Aggregate sessions by hour
        # Try to find by UUID first, then by numeric ID (for backwards compatibility)
        sessions = server_models.AppSession.query.filter(
            server_models.AppSession.agent_id == agent_id,
            server_models.AppSession.start_time >= start_dt,
            server_models.AppSession.start_time <= end_dt
        ).all()
        
        if not sessions:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    sessions = server_models.AppSession.query.filter(
                        server_models.AppSession.agent_id == agent.agent_id,
                        server_models.AppSession.start_time >= start_dt,
                        server_models.AppSession.start_time <= end_dt
                    ).all()
            except ValueError:
                pass
        
        timeline = {} # {hour: {app: duration}}
        
        for sess in sessions:
            hour = sess.start_time.hour
            if hour not in timeline:
                timeline[hour] = {}
            
            app = sess.app
            duration = int(sess.duration_seconds)
            timeline[hour][app] = timeline[hour].get(app, 0) + duration
            
        # Format for Chart.js stacked bar
        hours = list(range(24))
        datasets = {} # {app: [d0, d1, ... d23]}
        
        # Get all unique apps in timeline
        all_apps = set()
        for h in timeline.values():
            all_apps.update(h.keys())
            
        for app in all_apps:
            datasets[app] = [0] * 24
            
        for h in timeline:
            for app, dur in timeline[h].items():
                datasets[app][h] = dur
                
        return jsonify({
            'labels': [f"{h:02d}:00" for h in hours],
            'datasets': [{'label': app, 'data': data} for app, data in datasets.items()]
        }), 200
        
    except Exception as e:
        logger.error(f"Activity Timeline API error: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# NEW API ENDPOINTS FOR REDESIGNED DASHBOARD
# ============================================================================

@bp.route('/api/agent/<path:agent_id>/domain-visits', methods=['GET'])
def api_agent_domain_visits(agent_id):
    """
    Get sites opened (Column B) - Browser history without duration.
    Returns all domains visited including background tabs and quick visits.
    """
    try:
        date_str = request.args.get('date')
        if not date_str:
            target_date = datetime.utcnow().date()
        else:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date, datetime.max.time())
        
        # Get unique domains visited today (no duplicates, just list)
        # Try to find by UUID first, then by numeric ID (for backwards compatibility)
        visits = db.session.query(
            server_models.DomainVisit.domain,
            server_models.DomainVisit.browser,
            func.max(server_models.DomainVisit.visited_at).label('last_visited')
        ).filter(
            server_models.DomainVisit.agent_id == agent_id,
            server_models.DomainVisit.visited_at >= start_dt,
            server_models.DomainVisit.visited_at <= end_dt
        ).group_by(
            server_models.DomainVisit.domain,
            server_models.DomainVisit.browser
        ).order_by(
            desc('last_visited')
        ).limit(50).all()
        
        if not visits:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    visits = db.session.query(
                        server_models.DomainVisit.domain,
                        server_models.DomainVisit.browser,
                        func.max(server_models.DomainVisit.visited_at).label('last_visited')
                    ).filter(
                        server_models.DomainVisit.agent_id == agent.agent_id,
                        server_models.DomainVisit.visited_at >= start_dt,
                        server_models.DomainVisit.visited_at <= end_dt
                    ).group_by(
                        server_models.DomainVisit.domain,
                        server_models.DomainVisit.browser
                    ).order_by(
                        desc('last_visited')
                    ).limit(50).all()
            except ValueError:
                pass
        
        result = [{
            'domain': v.domain,
            'browser': v.browser,
            'last_visited': v.last_visited.isoformat() if v.last_visited else None
        } for v in visits]
        
        return jsonify({'data': result}), 200
    except Exception as e:
        logger.error(f"Agent Domain Visits API error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/agent/<path:agent_id>/app-sessions', methods=['GET'])
def api_agent_app_sessions(agent_id):
    """
    Get individual app sessions (expandable view).
    Groups by app and shows each session with start/end times.
    """
    try:
        date_str = request.args.get('date')
        if not date_str:
            target_date = datetime.utcnow().date()
        else:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date, datetime.max.time())
        
        # Try to find by UUID first, then by numeric ID (for backwards compatibility)
        sessions = server_models.AppSession.query.filter(
            server_models.AppSession.agent_id == agent_id,
            server_models.AppSession.start_time >= start_dt,
            server_models.AppSession.start_time <= end_dt
        ).order_by(
            server_models.AppSession.app,
            server_models.AppSession.start_time
        ).all()
        
        if not sessions:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    sessions = server_models.AppSession.query.filter(
                        server_models.AppSession.agent_id == agent.agent_id,
                        server_models.AppSession.start_time >= start_dt,
                        server_models.AppSession.start_time <= end_dt
                    ).order_by(
                        server_models.AppSession.app,
                        server_models.AppSession.start_time
                    ).all()
            except ValueError:
                pass
        
        # Group by app
        app_groups = {}
        for sess in sessions:
            app_name = sess.app
            friendly_name = server_models.get_friendly_app_name(app_name)
            
            if friendly_name not in app_groups:
                app_groups[friendly_name] = {
                    'app': friendly_name,
                    'exe': app_name,
                    'total_duration': 0,
                    'sessions': []
                }
            
            app_groups[friendly_name]['total_duration'] += sess.duration_seconds or 0
            app_groups[friendly_name]['sessions'].append({
                'start': sess.start_time.strftime('%H:%M') if sess.start_time else None,
                'end': sess.end_time.strftime('%H:%M') if sess.end_time else None,
                'duration': int(sess.duration_seconds or 0),
                'window_title': sess.window_title
            })
        
        # Sort by total duration
        result = sorted(app_groups.values(), key=lambda x: x['total_duration'], reverse=True)
        
        return jsonify({'data': result}), 200
    except Exception as e:
        logger.error(f"Agent App Sessions API error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/agent/<path:agent_id>/today', methods=['GET'])
def api_agent_today(agent_id):
    """
    Get complete agent data for TODAY in one API call.
    Includes: agent info, screen time, top apps, domains used, sites opened.
    """
    try:
        today = datetime.utcnow().date()
        
        # 1. Agent Info
        # Try to find agent by UUID first, then by numeric ID (for backwards compatibility)
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        
        if not agent:
            try:
                # Try to parse as numeric ID
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
            except ValueError:
                pass
                
        if not agent:
            return jsonify({'error': 'Agent not found'}), 404
        
        # 2. Screen Time
        # Use agent.agent_id (UUID) instead of agent_id parameter
        screen_time = server_models.ScreenTime.query.filter_by(
            agent_id=agent.agent_id,
            date=today
        ).first()
        
        active_s = screen_time.active_seconds if screen_time else 0
        idle_s = screen_time.idle_seconds if screen_time else 0
        locked_s = screen_time.locked_seconds if screen_time else 0
        
        # 3. App Usage (with friendly names)
        apps = server_models.AppUsage.query.filter_by(
            agent_id=agent.agent_id,
            date=today
        ).order_by(desc(server_models.AppUsage.duration_seconds)).limit(20).all()
        
        app_data = [{
            'name': server_models.get_friendly_app_name(a.app),
            'exe': a.app,
            'duration': a.duration_seconds,
            'sessions': a.session_count,
            'is_ongoing': False
        } for a in apps]
        
        # 4. Domains Used (Column A - with duration)
        domains_used = server_models.DomainUsage.query.filter_by(
            agent_id=agent.agent_id,
            date=today
        ).order_by(desc(server_models.DomainUsage.duration_seconds)).limit(20).all()
        
        domains_used_data = [{
            'domain': d.domain,
            'browser': d.browser,
            'duration': d.duration_seconds,
            'is_ongoing': False
        } for d in domains_used]
        
        # 5. Sites Opened (Column B - no duration)
        start_dt = datetime.combine(today, datetime.min.time())
        end_dt = datetime.combine(today, datetime.max.time())
        
        sites_opened = db.session.query(
            server_models.DomainVisit.domain,
            server_models.DomainVisit.browser,
            func.max(server_models.DomainVisit.visited_at).label('last_visited')
        ).filter(
            server_models.DomainVisit.agent_id == agent.agent_id,
            server_models.DomainVisit.visited_at >= start_dt,
            server_models.DomainVisit.visited_at <= end_dt
        ).group_by(
            server_models.DomainVisit.domain,
            server_models.DomainVisit.browser
        ).order_by(
            desc('last_visited')
        ).limit(30).all()
        
        sites_opened_data = [{
            'domain': v.domain,
            'browser': v.browser
        } for v in sites_opened]
        
        # 6. ONGOING SESSION from agent_current_status
        live_status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent.agent_id).first()
        ongoing = None
        
        if live_status and live_status.last_seen:
            is_recent = (datetime.utcnow() - live_status.last_seen).total_seconds() < 120
            
            if is_recent:
                ongoing = {
                    'app': {
                        'name': server_models.get_friendly_app_name(live_status.current_app) if live_status.current_app else None,
                        'exe': live_status.current_app,
                        'duration': live_status.duration_seconds or 0,
                        'window_title': live_status.window_title,
                        'session_start': live_status.session_start.isoformat() if live_status.session_start else None,
                        'state': live_status.current_state
                    },
                    'domain': {
                        'domain': live_status.current_domain,
                        'browser': live_status.current_browser,
                        'duration': live_status.domain_duration_seconds or 0
                    } if live_status.current_domain else None
                }
                
                # Remove ongoing items from completed lists to avoid duplicates
                if live_status.current_app:
                    app_data = [app for app in app_data if app['exe'] != live_status.current_app]
                if live_status.current_domain:
                    domains_used_data = [d for d in domains_used_data if d['domain'] != live_status.current_domain]
        
        return jsonify({
            'agent': {
                'id': agent.id,
                'hostname': agent.hostname,
                'os': agent.os,
                'username': screen_time.username if screen_time else None,
                'status': agent.status,
                'last_seen': agent.last_seen.isoformat() if agent.last_seen else None
            },
            'screen_time': {
                'active': active_s,
                'idle': idle_s,
                'locked': locked_s,
                'total': active_s + idle_s + locked_s
            },
            'apps': app_data,
            'domains_used': domains_used_data,
            'sites_opened': sites_opened_data,
            'ongoing': ongoing,  # Current app/domain being used right now
            'last_updated': screen_time.last_updated.isoformat() if screen_time and screen_time.last_updated else None
        }), 200
        
    except Exception as e:
        logger.error(f"Agent Today API error: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# REAL-TIME ACTIVITY API ENDPOINTS
# ============================================================================

@bp.route('/api/agent/<path:agent_id>/current-activity')
def get_agent_current_activity(agent_id):
    """
    Get current real-time activity for agent.
    Used by the live activity display in the dashboard.
    """
    try:
        # Get live status from agent_current_status table
        # Try to find by UUID first, then by numeric ID (for backwards compatibility)
        import uuid
        try:
            # Check if agent_id is a valid UUID
            uuid.UUID(agent_id)
            live_status = server_models.AgentCurrentStatus.query.filter_by(
                agent_id=agent_id
            ).first()
        except ValueError:
            live_status = None
        
        if not live_status:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    live_status = server_models.AgentCurrentStatus.query.filter_by(
                        agent_id=agent.agent_id
                    ).first()
            except ValueError:
                pass
        
        if not live_status or not live_status.last_seen:
            return jsonify({
                'current_app': None,
                'duration_seconds': 0,
                'state': 'offline',
                'timestamp': None
            })
        
        # Check if recent (within 2 minutes)
        is_recent = (datetime.utcnow() - live_status.last_seen).total_seconds() < 120
        
        if not is_recent:
            return jsonify({
                'current_app': None,
                'duration_seconds': 0,
                'state': 'offline',
                'timestamp': live_status.last_seen.isoformat() if live_status.last_seen else None
            })
        
        # Get friendly app name
        friendly_name = server_models.get_friendly_app_name(live_status.current_app) if live_status.current_app else None
        
        return jsonify({
            'current_app': friendly_name,
            'current_app_exe': live_status.current_app,
            'duration_seconds': live_status.duration_seconds or 0,
            'state': live_status.current_state or 'active',
            'timestamp': live_status.session_start.isoformat() if live_status.session_start else None,
            'window_title': live_status.window_title
        })
        
    except Exception as e:
        logger.error(f"Error fetching current activity: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/agent/<path:agent_id>/recent-activities')
def get_agent_recent_activities(agent_id):
    """
    Get recent activities (last 10 app sessions) for agent.
    Used by the activity timeline in the dashboard.
    """
    try:
        date_str = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
        limit = int(request.args.get('limit', 10))
        
        # Parse date
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        date_start = datetime.combine(target_date, datetime.min.time())
        date_end = datetime.combine(target_date, datetime.max.time())
        
        # Get recent app sessions
        # Try to find by UUID first, then by numeric ID (for backwards compatibility)
        sessions = server_models.AppSession.query.filter(
            server_models.AppSession.agent_id == agent_id,
            server_models.AppSession.start_time >= date_start,
            server_models.AppSession.start_time <= date_end
        ).order_by(
            desc(server_models.AppSession.start_time)
        ).limit(limit).all()
        
        if not sessions:
            try:
                # Try to parse as numeric ID to get UUID first
                numeric_id = int(agent_id)
                agent = server_models.Agent.query.filter_by(id=numeric_id).first()
                if agent:
                    sessions = server_models.AppSession.query.filter(
                        server_models.AppSession.agent_id == agent.agent_id,
                        server_models.AppSession.start_time >= date_start,
                        server_models.AppSession.start_time <= date_end
                    ).order_by(
                        desc(server_models.AppSession.start_time)
                    ).limit(limit).all()
            except ValueError:
                pass
        
        # Filter out system apps
        filtered = [s for s in sessions if not server_models.is_system_app(s.app)]
        
        result = []
        for session in filtered:
            duration = int(session.duration_seconds or 0)
            friendly_name = server_models.get_friendly_app_name(session.app)
            
            result.append({
                'app_name': friendly_name,
                'exe_name': session.app,
                'duration_seconds': duration,
                'timestamp': session.start_time.isoformat() if session.start_time else None,
                'end_time': session.end_time.isoformat() if session.end_time else None,
                'system_state': session.system_state if hasattr(session, 'system_state') else 'active',
                'window_title': session.window_title
            })
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error fetching recent activities: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# NEW CHART API ENDPOINTS (Dashboard Enhancement)
# ============================================================================

@bp.route('/api/overview/productivity-score', methods=['GET'])
@login_required
@api_rate_limit
def api_productivity_score():
    """
    Calculate fleet-wide productivity score.
    Formula: (active_seconds / total_monitored_seconds) * 100
    """
    try:
        date_str = request.args.get('date')
        if date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = datetime.utcnow().date()
        
        # Get total screen time for the date
        totals = db.session.query(
            func.sum(server_models.ScreenTime.active_seconds),
            func.sum(server_models.ScreenTime.idle_seconds),
            func.sum(server_models.ScreenTime.locked_seconds)
        ).filter(
            server_models.ScreenTime.date == target_date
        ).first()
        
        active = float(totals[0] or 0)
        idle = float(totals[1] or 0)
        locked = float(totals[2] or 0)
        
        total = active + idle + locked
        score = round((active / total) * 100, 1) if total > 0 else 0
        
        return jsonify({
            'score': score,
            'target': 70,
            'activeMinutes': int(active / 60),
            'totalMinutes': int(total / 60)
        })
    except Exception as e:
        logger.error(f"Productivity score error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/overview/category-breakdown', methods=['GET'])
@login_required
@api_rate_limit
def api_category_breakdown():
    """
    Get application usage by category.
    Categories: productivity, communication, browsing, development, other
    """
    try:
        date_str = request.args.get('date')
        if date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = datetime.utcnow().date()
        
        # Initialize categories
        breakdown = {
            'productivity': 0,
            'communication': 0,
            'browsing': 0,
            'development': 0,
            'other': 0
        }
        
        # Get all app usage for the date
        usage = server_models.AppUsage.query.filter(
            server_models.AppUsage.date == target_date
        ).all()
        
        for u in usage:
            app_name = u.app.lower() if u.app else ''
            duration = u.duration_seconds or 0
            
            # Simple categorization based on app name
            if any(x in app_name for x in ['excel', 'word', 'powerpoint', 'outlook', 'teams', 'office']):
                breakdown['productivity'] += duration
            elif any(x in app_name for x in ['slack', 'discord', 'zoom', 'skype', 'telegram', 'whatsapp']):
                breakdown['communication'] += duration
            elif any(x in app_name for x in ['chrome', 'firefox', 'edge', 'safari', 'browser']):
                breakdown['browsing'] += duration
            elif any(x in app_name for x in ['code', 'visual studio', 'pycharm', 'intellij', 'sublime', 'vim', 'terminal', 'git']):
                breakdown['development'] += duration
            else:
                breakdown['other'] += duration
        
        # Convert to minutes
        for key in breakdown:
            breakdown[key] = int(breakdown[key] / 60)
        
        return jsonify(breakdown)
    except Exception as e:
        logger.error(f"Category breakdown error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/overview/idle-analysis', methods=['GET'])
@login_required
@api_rate_limit
def api_idle_analysis():
    """
    Get hourly breakdown of active/idle/locked states for the fleet.
    Returns 24 data points (one per hour).
    """
    try:
        date_str = request.args.get('date')
        if date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = datetime.utcnow().date()
        
        # Initialize hourly data
        labels = [f"{h:02d}:00" for h in range(24)]
        active = [0] * 24
        idle = [0] * 24
        locked = [0] * 24
        
        # Get app sessions for the date to determine hourly states
        date_start = datetime.combine(target_date, datetime.min.time())
        date_end = datetime.combine(target_date, datetime.max.time())
        
        sessions = server_models.AppSession.query.filter(
            server_models.AppSession.start_time >= date_start,
            server_models.AppSession.start_time <= date_end
        ).all()
        
        for session in sessions:
            if session.start_time:
                hour = session.start_time.hour
                duration = session.duration_seconds or 0
                state = getattr(session, 'system_state', 'active') or 'active'
                
                if state == 'active':
                    active[hour] += duration
                elif state == 'idle':
                    idle[hour] += duration
                elif state == 'locked':
                    locked[hour] += duration
        
        # Convert to minutes
        active = [int(x / 60) for x in active]
        idle = [int(x / 60) for x in idle]
        locked = [int(x / 60) for x in locked]
        
        return jsonify({
            'labels': labels,
            'active': active,
            'idle': idle,
            'locked': locked
        })
    except Exception as e:
        logger.error(f"Idle analysis error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/overview/activity-heatmap', methods=['GET'])
@login_required
@api_rate_limit
def api_activity_heatmap():
    """
    Get activity heatmap data (7 days x 24 hours).
    Returns count of active agents per hour per day.
    """
    try:
        days = int(request.args.get('days', 7))
        days = min(days, 30)  # Cap at 30 days
        
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days - 1)
        
        # Initialize 7x24 grid (rows = days starting from start_date)
        data = [[0 for _ in range(24)] for _ in range(days)]
        
        # Get hourly activity counts
        for day_offset in range(days):
            current_date = start_date + timedelta(days=day_offset)
            date_start = datetime.combine(current_date, datetime.min.time())
            date_end = datetime.combine(current_date, datetime.max.time())
            
            # Count active sessions per hour
            hourly_counts = db.session.query(
                func.extract('hour', server_models.AppSession.start_time).label('hour'),
                func.count(func.distinct(server_models.AppSession.agent_id)).label('count')
            ).filter(
                server_models.AppSession.start_time >= date_start,
                server_models.AppSession.start_time <= date_end
            ).group_by(
                func.extract('hour', server_models.AppSession.start_time)
            ).all()
            
            for row in hourly_counts:
                hour = int(row.hour)
                data[day_offset][hour] = row.count
        
        max_value = max(max(row) for row in data) if data else 1
        
        return jsonify({
            'data': data,
            'maxValue': max_value,
            'startDate': start_date.isoformat(),
            'endDate': end_date.isoformat()
        })
    except Exception as e:
        logger.error(f"Activity heatmap error: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# NEW CHART API ENDPOINTS (8 New Charts)
# ============================================================================

@bp.route('/api/overview/os-distribution', methods=['GET'])
@login_required
@api_rate_limit
def api_os_distribution():
    """Get OS distribution across all agents."""
    try:
        results = db.session.query(
            server_models.Agent.os,
            server_models.Agent.windowsedition,
            func.count(server_models.Agent.id).label('count')
        ).group_by(
            server_models.Agent.os, 
            server_models.Agent.windowsedition
        ).all()
        
        distribution = {}
        for os, edition, count in results:
            if os and edition:
                label = f"{os} {edition}"
            elif os:
                label = os
            else:
                label = "Unknown"
            distribution[label] = count
        
        return jsonify(distribution)
    except Exception as e:
        logger.error(f"OS distribution error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/overview/app-categories', methods=['GET'])
@login_required
@api_rate_limit
def api_app_categories():
    """Get application usage by category."""
    try:
        date_str = request.args.get('date')
        if date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = datetime.utcnow().date()
        
        categories = {
            'productivity': 0,
            'communication': 0,
            'browsing': 0,
            'development': 0,
            'other': 0
        }
        
        usage = server_models.AppUsage.query.filter(
            server_models.AppUsage.date == target_date
        ).all()
        
        for u in usage:
            app_name = (u.app or '').lower()
            duration = u.duration_seconds or 0
            
            if any(x in app_name for x in ['excel', 'word', 'powerpoint', 'outlook', 'teams', 'office', 'onenote']):
                categories['productivity'] += duration
            elif any(x in app_name for x in ['slack', 'discord', 'zoom', 'skype', 'telegram', 'whatsapp', 'teams']):
                categories['communication'] += duration
            elif any(x in app_name for x in ['chrome', 'firefox', 'edge', 'safari', 'browser', 'msedge', 'brave']):
                categories['browsing'] += duration
            elif any(x in app_name for x in ['code', 'visual studio', 'pycharm', 'intellij', 'sublime', 'vim', 'terminal', 'git', 'idea', 'devenv']):
                categories['development'] += duration
            else:
                categories['other'] += duration
        
        return jsonify(categories)
    except Exception as e:
        logger.error(f"App categories error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/overview/browser-usage', methods=['GET'])
@login_required
@api_rate_limit
def api_browser_usage():
    """Get browser usage distribution."""
    try:
        date_str = request.args.get('date')
        if date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = datetime.utcnow().date()
        
        results = db.session.query(
            server_models.DomainUsage.browser,
            func.sum(server_models.DomainUsage.duration_seconds).label('total')
        ).filter(
            server_models.DomainUsage.date == target_date,
            server_models.DomainUsage.browser.isnot(None)
        ).group_by(
            server_models.DomainUsage.browser
        ).all()
        
        browser_map = {
            'chrome': 'Google Chrome',
            'edge': 'Microsoft Edge',
            'firefox': 'Mozilla Firefox',
            'brave': 'Brave Browser',
            'opera': 'Opera'
        }
        
        usage = {}
        for browser, duration in results:
            if browser:
                display_name = browser_map.get(browser.lower(), browser.title())
                usage[display_name] = int(duration or 0)
        
        return jsonify(usage)
    except Exception as e:
        logger.error(f"Browser usage error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/database/status', methods=['GET'])
@login_required
@api_rate_limit
def api_database_status():
    """Get database health metrics."""
    try:
        from sqlalchemy import text
        
        result = db.session.execute(text("""
            SELECT 
                pg_database_size(current_database()) as db_size_bytes,
                (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) as connections
        """))
        row = result.fetchone()
        
        cache_result = db.session.execute(text("""
            SELECT 
                CASE 
                    WHEN (blks_read + blks_hit) = 0 THEN 100.0
                    ELSE round(100.0 * blks_hit / (blks_read + blks_hit), 2)
                END as cache_hit_ratio
            FROM pg_stat_database 
            WHERE datname = current_database()
        """))
        cache_row = cache_result.fetchone()
        
        return jsonify({
            'database_size_bytes': int(row[0]) if row else 0,
            'database_size_mb': round((row[0] or 0) / 1024 / 1024, 2),
            'active_connections': int(row[1]) if row else 0,
            'cache_hit_ratio': float(cache_row[0]) if cache_row else 0.0
        })
    except Exception as e:
        logger.error(f"Database status error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/monitoring/failed-events', methods=['GET'])
@login_required
@api_rate_limit
def api_failed_events():
    """Get count of failed events in last 24 hours."""
    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        
        # Check if RawEvent model exists and has error field
        if hasattr(server_models, 'RawEvent'):
            failed_count = db.session.query(server_models.RawEvent).filter(
                server_models.RawEvent.processed == False,
                server_models.RawEvent.error.isnot(None),
                server_models.RawEvent.received_at >= cutoff
            ).count()
        else:
            failed_count = 0
        
        return jsonify({
            'failed_count': failed_count,
            'recent_errors': []
        })
    except Exception as e:
        logger.error(f"Failed events error: {e}")
        return jsonify({'failed_count': 0, 'recent_errors': []})


@bp.route('/api/monitoring/stale-agents', methods=['GET'])
@login_required
@api_rate_limit
def api_stale_agents():
    """Get agents with no recent activity (>5 minutes)."""
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        
        stale = db.session.query(
            server_models.Agent.id,
            server_models.Agent.hostname,
            server_models.Agent.last_seen
        ).filter(
            server_models.Agent.last_seen < cutoff
        ).order_by(
            server_models.Agent.last_seen.asc()
        ).limit(20).all()
        
        stale_agents = []
        for agent_id, hostname, last_seen in stale:
            if last_seen:
                minutes_since = int((datetime.utcnow() - last_seen).total_seconds() / 60)
            else:
                minutes_since = 999
            
            stale_agents.append({
                'agent_id': agent_id[:8] + '...' if agent_id else 'Unknown',
                'hostname': hostname or 'Unknown',
                'last_seen': last_seen.isoformat() if last_seen else None,
                'minutes_since': minutes_since
            })
        
        return jsonify({
            'stale_count': len(stale_agents),
            'stale_agents': stale_agents
        })
    except Exception as e:
        logger.error(f"Stale agents error: {e}")
        return jsonify({'stale_count': 0, 'stale_agents': []})


@bp.route('/api/monitoring/agent-versions', methods=['GET'])
@login_required
@api_rate_limit
def api_agent_versions():
    """Get agent version distribution."""
    try:
        results = db.session.query(
            server_models.Agent.version,
            func.count(server_models.Agent.id).label('count')
        ).group_by(
            server_models.Agent.version
        ).order_by(
            func.count(server_models.Agent.id).desc()
        ).all()
        
        versions = {}
        for version, count in results:
            versions[version or 'Unknown'] = count
        
        return jsonify(versions)
    except Exception as e:
        logger.error(f"Agent versions error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/database/table-sizes', methods=['GET'])
@login_required
@api_rate_limit
def api_table_sizes():
    """Get size of each table in database."""
    try:
        from sqlalchemy import text
        
        result = db.session.execute(text("""
            SELECT 
                tablename,
                pg_total_relation_size('public.'||quote_ident(tablename)) as size_bytes
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size('public.'||quote_ident(tablename)) DESC
            LIMIT 10
        """))
        
        tables = {}
        for row in result:
            table_name = row[0]
            size_mb = round(row[1] / 1024 / 1024, 2)
            tables[table_name] = size_mb
        
        return jsonify(tables)
    except Exception as e:
        logger.error(f"Table sizes error: {e}")
        return jsonify({'error': str(e)}), 500
