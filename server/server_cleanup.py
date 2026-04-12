"""
SentinelEdge Server - Data Retention and Cleanup

Implements 30-day data retention policy:
- Keeps detailed session data for 30 days
- Aggregates to daily summaries
- Deletes old per-minute/session data

Run daily via cron or scheduler.
"""

import logging
from datetime import datetime, timedelta, timezone
from flask import Flask
from extensions import db
from server_config import get_config
import server_models
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Retention periods
SESSION_RETENTION_DAYS = 30  # Keep detailed sessions for 30 days
VISIT_RETENTION_DAYS = 30    # Keep domain visits for 30 days


def cleanup_old_data():
    """
    Clean up data older than retention period.
    Run this daily via cron/scheduler.
    """
    config = get_config()
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = config.DATABASE_URL
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=SESSION_RETENTION_DAYS)
        cutoff_datetime = datetime.combine(cutoff_date, datetime.min.time())
        
        print(f"=== Data Cleanup ===")
        print(f"Cutoff date: {cutoff_date}")
        print(f"Retention: {SESSION_RETENTION_DAYS} days")
        
        try:
            # 1. Delete old app_sessions
            deleted = server_models.AppSession.query.filter(
                server_models.AppSession.start_time < cutoff_datetime
            ).delete()
            print(f"[OK] Deleted {deleted} old app_sessions")
            
            # 2. Delete old domain_sessions
            deleted = server_models.DomainSession.query.filter(
                server_models.DomainSession.start_time < cutoff_datetime
            ).delete()
            print(f"[OK] Deleted {deleted} old domain_sessions")
            
            # 3. Delete old domain_visits
            deleted = server_models.DomainVisit.query.filter(
                server_models.DomainVisit.visited_at < cutoff_datetime
            ).delete()
            print(f"[OK] Deleted {deleted} old domain_visits")
            
            # 4. Delete old state_changes
            deleted = server_models.StateChange.query.filter(
                server_models.StateChange.timestamp < cutoff_datetime
            ).delete()
            print(f"[OK] Deleted {deleted} old state_changes")
            
            # Note: We keep screen_time and app_usage (daily aggregates) forever
            # These are already summarized per-day
            
            db.session.commit()
            print("\n[OK] Cleanup complete!")
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Cleanup error: {e}")
            logger.error(f"Data cleanup error: {e}")


def get_daily_summary(agent_id: str, date):
    """
    Generate daily summary for an agent.
    Returns dict with all metrics for that day.
    """
    with db.session.begin_nested():
        # Screen time
        screen = server_models.ScreenTime.query.filter_by(
            agent_id=agent_id,
            date=date
        ).first()
        
        # App usage totals
        apps = server_models.AppUsage.query.filter_by(
            agent_id=agent_id,
            date=date
        ).all()
        
        # Domain usage totals
        domains = server_models.DomainUsage.query.filter_by(
            agent_id=agent_id,
            date=date
        ).all()
        
        return {
            'date': date.isoformat(),
            'screen_time': {
                'active': screen.active_seconds if screen else 0,
                'idle': screen.idle_seconds if screen else 0,
                'locked': screen.locked_seconds if screen else 0
            },
            'apps': [{
                'name': server_models.get_friendly_app_name(a.app),
                'exe': a.app,
                'duration': a.duration_seconds,
                'sessions': a.session_count
            } for a in apps],
            'domains': [{
                'domain': d.domain,
                'duration': d.duration_seconds,
                'sessions': d.session_count
            } for d in domains]
        }


def classify_unreviewed_domains():
    """
    Classify domain sessions that need review.
    Uses rules from domain_classification_rules table.
    Run this hourly via cron/scheduler.
    """
    config = get_config()
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = config.DATABASE_URL
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        try:
            # Get unreviewed sessions
            unreviewed = server_models.DomainSession.query.filter(
                server_models.DomainSession.domain_source == 'agent',
                server_models.DomainSession.needs_review == True,
                server_models.DomainSession.raw_title.isnot(None)
            ).limit(1000).all()
            
            if not unreviewed:
                print("✅ No domains to classify")
                return
            
            print(f"🔍 Classifying {len(unreviewed)} unreviewed domains...")
            
            # Get classification rules
            rules = db.session.execute(text('''
                SELECT pattern, pattern_type, classified_as, action
                FROM domain_classification_rules
                WHERE is_active = TRUE
                ORDER BY priority ASC
            ''')).fetchall()
            
            classified_count = 0
            ignored_count = 0
            
            for session in unreviewed:
                raw_title = session.raw_title or ''
                raw_url = session.raw_url or ''
                
                matched = False
                for rule in rules:
                    pattern, pattern_type, classified_as, action = rule
                    
                    # Check if pattern matches
                    if pattern_type == 'substring':
                        match = pattern.lower() in raw_title.lower() or pattern.lower() in raw_url.lower()
                    elif pattern_type == 'exact':
                        match = pattern.lower() == raw_title.lower() or pattern.lower() == raw_url.lower()
                    else:
                        match = False
                    
                    if match:
                        if action == 'ignore':
                            # Mark as ignored (will be deleted by cleanup)
                            session.domain = 'ignored'
                            session.domain_source = 'classifier'
                            session.needs_review = False
                            ignored_count += 1
                            print(f"  🚫 {raw_title[:50]} → IGNORED")
                        else:
                            # Map to classified domain
                            session.domain = classified_as
                            session.domain_source = 'classifier'
                            session.needs_review = False
                            classified_count += 1
                            print(f"  ✅ {raw_title[:50]} → {classified_as}")
                        
                        # Update rule match count
                        db.session.execute(text('''
                            UPDATE domain_classification_rules
                            SET match_count = match_count + 1,
                                last_matched_at = NOW()
                            WHERE pattern = :pattern
                        '''), {'pattern': pattern})
                        
                        matched = True
                        break
                
                if not matched:
                    # No rule matched - extract domain from URL if possible
                    if raw_url:
                        try:
                            from urllib.parse import urlparse
                            parsed = urlparse(raw_url if raw_url.startswith('http') else f'https://{raw_url}')
                            domain = parsed.netloc or parsed.path.split('/')[0]
                            if domain:
                                session.domain = domain.lower()
                                session.domain_source = 'url_parse'
                                session.needs_review = False
                                classified_count += 1
                                print(f"  🔗 {raw_title[:50]} → {domain} (from URL)")
                        except:
                            pass
            
            db.session.commit()
            print(f"\n✅ Classification complete!")
            print(f"   Classified: {classified_count}")
            print(f"   Ignored: {ignored_count}")
            print(f"   Remaining: {len(unreviewed) - classified_count - ignored_count}")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Classification error: {e}")
            logger.error(f"Domain classification error: {e}")


import sys

if __name__ == "__main__":
    if "--classify-domains" in sys.argv or "--classify" in sys.argv:
        classify_unreviewed_domains()
    elif "--help" in sys.argv:
        print("SentinelEdge Data Management")
        print("Usage:")
        print("  python server_cleanup.py              - Run data cleanup (default)")
        print("  python server_cleanup.py --classify   - Classify unreviewed domains")
        print("  python server_cleanup.py --help       - Show this help")
    else:
        cleanup_old_data()

