#!/usr/bin/env python3
"""
Weekly Report Generator for SentinelEdge
Generates individual and team weekly activity reports from database data.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from jinja2 import Environment, FileSystemLoader, select_autoescape

# FR-007: the single canonical date presentation, shared with the Flask
# app so cron-rendered reports match server-rendered ones.
try:
    from utils.datetime_format import format_date as _fmt_date
    from utils.datetime_format import format_datetime as _fmt_datetime
    from utils.datetime_format import format_datetime_labelled as _fmt_datetime_tz
    from utils.datetime_format import format_datetime_seconds_labelled as _fmt_datetime_seconds_tz
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'server'))
    from utils.datetime_format import format_date as _fmt_date
    from utils.datetime_format import format_datetime as _fmt_datetime
    from utils.datetime_format import format_datetime_labelled as _fmt_datetime_tz
    from utils.datetime_format import format_datetime_seconds_labelled as _fmt_datetime_seconds_tz

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

APP_CATEGORIES = {
    'Development': [
        'code.exe', 'devenv.exe', 'idea64.exe', 'pycharm64.exe', 'webstorm64.exe',
        'sublime_text.exe', 'notepad++.exe', 'atom.exe', 'cursor.exe', 'antigravity.exe',
        'putty.exe', 'winscp.exe', 'code - insiders.exe', ' rider64.exe', 'goland64.exe',
        'phpstorm64.exe', 'rubymine64.exe', 'eclipse.exe', 'netbeans64.exe'
    ],
    'Communication': [
        'slack.exe', 'teams.exe', 'ms-teams.exe', 'discord.exe', 'zoom.exe',
        'skype.exe', 'telegram.exe', 'whatsapp.exe', 'olk.exe', 'outlook.exe',
        'teams for business.exe', 'slack - beta.exe'
    ],
    'Browsers': [
        'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe',
        'vivaldi.exe', 'safari.exe', 'chromium.exe'
    ],
    'Productivity': [
        'winword.exe', 'excel.exe', 'powerpnt.exe', 'onenote.exe', 'toad.exe',
        'ssms.exe', 'azuredatastudio.exe', 'dbeaver.exe', 'heidisql.exe',
        'navicat.exe', 'dbvisualizer.exe'
    ],
    'Terminal': [
        'windowsterminal.exe', 'cmd.exe', 'powershell.exe', 'wt.exe',
        'WindowsTerminal.exe', 'terminus.exe', 'hyper.exe', 'alacritty.exe'
    ],
    'Media': [
        'spotify.exe', 'vlc.exe', 'vlc-media-player.exe', 'music.ui.exe',
        'windows photos.exe', 'media player.exe'
    ],
    'Database': [
        'ssms.exe', 'azuredatastudio.exe', 'dbeaver.exe', 'heidisql.exe',
        'navicat.exe', 'dbvisualizer.exe', 'mysql.exe', 'psql.exe', 'mongo.exe'
    ]
}

APP_FRIENDLY_NAMES = {
    'code.exe': 'VS Code',
    'devenv.exe': 'Visual Studio',
    'idea64.exe': 'IntelliJ IDEA',
    'pycharm64.exe': 'PyCharm',
    'webstorm64.exe': 'WebStorm',
    'sublime_text.exe': 'Sublime Text',
    'notepad++.exe': 'Notepad++',
    'atom.exe': 'Atom',
    'cursor.exe': 'Cursor',
    'slack.exe': 'Slack',
    'teams.exe': 'Microsoft Teams',
    'ms-teams.exe': 'Microsoft Teams',
    'discord.exe': 'Discord',
    'zoom.exe': 'Zoom',
    'skype.exe': 'Skype',
    'telegram.exe': 'Telegram',
    'whatsapp.exe': 'WhatsApp',
    'olk.exe': 'Outlook (New)',
    'chrome.exe': 'Google Chrome',
    'msedge.exe': 'Microsoft Edge',
    'firefox.exe': 'Mozilla Firefox',
    'brave.exe': 'Brave Browser',
    'winword.exe': 'Microsoft Word',
    'excel.exe': 'Microsoft Excel',
    'powerpnt.exe': 'PowerPoint',
    'outlook.exe': 'Outlook',
    'onenote.exe': 'OneNote',
    'windowsterminal.exe': 'Windows Terminal',
    'cmd.exe': 'Command Prompt',
    'powershell.exe': 'PowerShell',
    'wt.exe': 'Windows Terminal',
    'spotify.exe': 'Spotify',
    'vlc.exe': 'VLC Media Player',
    'postman.exe': 'Postman',
    'insomnia.exe': 'Insomnia',
    'figma.exe': 'Figma',
    'notion.exe': 'Notion',
    'obsidian.exe': 'Obsidian',
    'explorer.exe': 'File Explorer',
    'taskmgr.exe': 'Task Manager',
    'mstsc.exe': 'Remote Desktop',
    'toad.exe': 'Toad for Oracle',
    'ssms.exe': 'SQL Server Management Studio',
    'azuredatastudio.exe': 'Azure Data Studio',
    'dbeaver.exe': 'DBeaver',
}

DOMAIN_CATEGORIES = {
    'Productivity': [
        'github.com', 'gitlab.com', 'bitbucket.org', 'stackoverflow.com',
        'stackexchange.com', 'jira', 'confluence', 'azure devops',
        'aws.amazon.com', 'digitalocean.com', 'heroku.com', 'vercel.com',
        'netlify.com', 'render.com', 'codepen.io', 'jsfiddle.net',
        'replit.com', 'leetcode.com', 'hackerrank.com', 'codesandbox.io',
        'atlassian.net', 'onedrive.live.com'
    ],
    'Communication': [
        'mail.google.com', 'outlook.com', 'office.com', 'webmail',
        'teams.microsoft.com', 'slack.com', 'discord.com', 'zoom.us',
        'webex.com', 'mail.yahoo.com', 'protonmail.com', 'web.whatsapp.com'
    ],
    'AI Tools': [
        'chatgpt.com', 'claude.ai', 'gemini.google', 'perplexity.ai',
        'copilot.microsoft.com', 'cursor.sh'
    ],
    'Learning': [
        'docs.microsoft.com', 'developer.mozilla.org', 'w3schools.com',
        'medium.com', 'dev.to', 'medium.com', 'towardsdatascience.com',
        'freecodecamp.org', 'kaggle.com', 'coursera.org', 'udemy.com',
        'pluralsight.com', 'linkedin.com/learning', 'edx.org'
    ],
    'Social': [
        'linkedin.com', 'twitter.com', 'facebook.com', 'instagram.com',
        'reddit.com', 'pinterest.com', 'tumblr.com', 'quora.com'
    ],
    'Entertainment': [
        'youtube.com', 'netflix.com', 'primevideo.com', 'hotstar.com',
        'disneyplus.com', 'hulu.com', 'twitch.tv', 'spotify.com',
        'soundcloud.com', 'gaana.com', 'cricbuzz.com'
    ],
    'News': [
        'news.google.com', 'bbc.com', 'cnn.com', 'nytimes.com',
        'theguardian.com', 'news.ycombinator.com', 'msn.com'
    ]
}

SYSTEM_APPS = {
    'lockapp.exe', 'applicationframehost.exe', 'shellexperiencehost.exe',
    'startmenuexperiencehost.exe', 'searchui.exe', 'runtimebroker.exe',
    'backgroundtaskhost.exe', 'systemsettings.exe', 'textinputhost.exe',
    'dwm.exe', 'csrss.exe', 'winlogon.exe', 'sihost.exe', 'fontdrvhost.exe',
    'ctfmon.exe', 'dllhost.exe', 'wudfhost.exe', 'smartscreen.exe',
    'securityhealthservice.exe', 'phonelinkserver.exe', 'widgets.exe',
    'gamebar.exe', 'gamebarpresencewriter.exe', 'searchapp.exe',
    'shellhost.exe', 'securityhealthsystray.exe', 'msmpeng.exe',
    'nissh.exe', 'sentinel.exe', 'wmiadap.exe', 'audiodg.exe',
    'services.exe', 'lsass.exe', 'svchost.exe', 'winlogon.exe',
    'system', 'csrss.exe', 'smss.exe', 'conhost.exe', 'taskhostw.exe',
    'runtimebroker.exe', 'textinputhost.exe', 'explorer.exe'
}


def get_category(app_name):
    """Get category for an application."""
    if not app_name:
        return 'Other'
    app_lower = app_name.lower()
    for category, apps in APP_CATEGORIES.items():
        if app_lower in apps:
            return category
    return 'Other'


def get_domain_category(domain):
    """Get category for a domain."""
    if not domain:
        return 'Uncategorized'
    domain_lower = domain.lower().strip()
    for category, domains in DOMAIN_CATEGORIES.items():
        for d in domains:
            d_lower = d.lower()
            if d_lower in domain_lower or domain_lower.endswith('.' + d_lower):
                return category
    return 'Other'


def get_friendly_name(app_name):
    """Get friendly name for an application."""
    if not app_name:
        return 'Unknown'
    return APP_FRIENDLY_NAMES.get(app_name.lower(), app_name.replace('.exe', '').title())


def format_duration(seconds):
    """Format seconds into human readable duration."""
    if seconds is None:
        return '0h 0m'
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f'{hours}h {minutes}m'


def format_hours(seconds):
    """Format seconds into decimal hours."""
    if seconds is None:
        return 0.0
    return round(seconds / 3600, 1)


class WeeklyReportGenerator:
    def __init__(self, db_url=None):
        self.db_url = db_url or os.environ.get('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not provided")
        
        self.conn = psycopg2.connect(self.db_url)
        self.template_dir = Path(__file__).parent / 'templates' / 'reports'
        self.output_dir = Path(__file__).parent / 'reports'
        
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(['html', 'xml'])
        )
        
        self.jinja_env.filters['format_duration'] = format_duration
        self.jinja_env.filters['format_hours'] = format_hours
        self.jinja_env.filters['get_category'] = get_category
        self.jinja_env.filters['get_friendly_name'] = get_friendly_name
        self.jinja_env.filters['fmt_date'] = _fmt_date
        self.jinja_env.filters['fmt_datetime'] = _fmt_datetime
        self.jinja_env.filters['fmt_datetime_tz'] = _fmt_datetime_tz
        self.jinja_env.filters['fmt_datetime_seconds_tz'] = _fmt_datetime_seconds_tz

    def get_agent_ids_by_username(self, username):
        """Get agent IDs for a specific username."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT agent_id 
                FROM agent_current_status 
                WHERE username = %s OR username LIKE %s
            """, (username, f'%\\{username}'))
            return [row['agent_id'] for row in cur.fetchall()]

    def get_all_active_usernames(self, start_date, end_date):
        """Get all usernames with activity in date range."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT acs.username, a.agent_id, a.agent_name, a.hostname
                FROM agent_current_status acs
                JOIN agents a ON acs.agent_id = a.agent_id
                WHERE a.status = 'active'
                AND acs.username IS NOT NULL
                ORDER BY acs.username
            """)
            return [dict(row) for row in cur.fetchall()]

    def get_agent_info(self, agent_id):
        """Get agent information."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT a.agent_id, a.agent_name, a.hostname, a.os,
                       acs.username
                FROM agents a
                LEFT JOIN agent_current_status acs ON a.agent_id = acs.agent_id
                WHERE a.agent_id = %s
            """, (agent_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_screen_time_data(self, agent_id, start_date, end_date):
        """Get screen time data for date range."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT date, 
                       COALESCE(active_seconds, 0) as active_seconds,
                       COALESCE(idle_seconds, 0) as idle_seconds,
                       COALESCE(locked_seconds, 0) as locked_seconds,
                       COALESCE(away_seconds, 0) as away_seconds
                FROM screen_time
                WHERE agent_id = %s 
                AND date BETWEEN %s AND %s
                ORDER BY date
            """, (agent_id, start_date, end_date))
            return [dict(row) for row in cur.fetchall()]

    def get_app_usage_data(self, agent_id, start_date, end_date):
        """Get app usage data for date range."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT app, 
                       SUM(duration_seconds) as total_time,
                       SUM(session_count) as sessions
                FROM app_usage
                WHERE agent_id = %s 
                AND date BETWEEN %s AND %s
                GROUP BY app
                HAVING SUM(duration_seconds) > 0
                ORDER BY total_time DESC
                LIMIT 20
            """, (agent_id, start_date, end_date))
            return [dict(row) for row in cur.fetchall()]

    def get_domain_usage_data(self, agent_id, start_date, end_date):
        """Get domain usage data for date range."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT domain, 
                       SUM(duration_seconds) as total_time,
                       SUM(session_count) as visits
                FROM domain_usage
                WHERE agent_id = %s 
                AND date BETWEEN %s AND %s
                GROUP BY domain
                HAVING SUM(duration_seconds) > 0
                ORDER BY total_time DESC
                LIMIT 20
            """, (agent_id, start_date, end_date))
            return [dict(row) for row in cur.fetchall()]

    def get_inventory_changes(self, agent_id, start_date, end_date):
        """Get software changes for date range."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT change_type, app_name, version, timestamp
                FROM app_inventory_changes
                WHERE agent_id = %s 
                AND DATE(timestamp) BETWEEN %s AND %s
                ORDER BY timestamp DESC
            """, (agent_id, start_date, end_date))
            return [dict(row) for row in cur.fetchall()]

    def aggregate_screen_time(self, screen_time_data):
        """Aggregate screen time data."""
        total_active = sum(d['active_seconds'] for d in screen_time_data)
        total_idle = sum(d['idle_seconds'] for d in screen_time_data)
        total_locked = sum(d['locked_seconds'] for d in screen_time_data)
        total_away = sum(d['away_seconds'] for d in screen_time_data)
        total = total_active + total_idle + total_locked + total_away
        
        days_with_activity = len([d for d in screen_time_data if d['active_seconds'] > 0])
        
        return {
            'total_active': total_active,
            'total_idle': total_idle,
            'total_locked': total_locked,
            'total_away': total_away,
            'total': total,
            'days_worked': days_with_activity,
            'avg_daily': total_active / days_with_activity if days_with_activity > 0 else 0,
            'daily_breakdown': screen_time_data
        }

    def generate_individual_report(self, agent_id, start_date, end_date):
        """Generate individual weekly report."""
        agent_info = self.get_agent_info(agent_id)
        if not agent_info:
            logger.warning(f"No agent found for ID: {agent_id}")
            return None
        
        username = agent_info.get('username', 'Unknown')
        if '\\' in username:
            username = username.split('\\')[-1]
        
        screen_time = self.get_screen_time_data(agent_id, start_date, end_date)
        app_usage = self.get_app_usage_data(agent_id, start_date, end_date)
        domain_usage = self.get_domain_usage_data(agent_id, start_date, end_date)
        inventory_changes = self.get_inventory_changes(agent_id, start_date, end_date)
        
        screen_agg = self.aggregate_screen_time(screen_time)
        
        processed_apps = []
        for app in app_usage:
            if app['app'].lower() not in SYSTEM_APPS:
                processed_apps.append({
                    'app': app['app'],
                    'friendly_name': get_friendly_name(app['app']),
                    'category': get_category(app['app']),
                    'total_time': app['total_time'],
                    'sessions': app['sessions'],
                    'hours': format_hours(app['total_time']),
                    'duration': format_duration(app['total_time'])
                })
        
        processed_domains = []
        for domain in domain_usage:
            processed_domains.append({
                'domain': domain['domain'],
                'category': get_domain_category(domain['domain']),
                'total_time': domain['total_time'],
                'visits': domain['visits'],
                'hours': format_hours(domain['total_time']),
                'duration': format_duration(domain['total_time'])
            })
        
        new_installs = [c for c in inventory_changes if c['change_type'] == 'installed']
        uninstalls = [c for c in inventory_changes if c['change_type'] == 'uninstalled']
        
        highest_day = max(screen_time, key=lambda x: x['active_seconds']) if screen_time else None
        lowest_day = min([d for d in screen_time if d['active_seconds'] > 0], 
                        key=lambda x: x['active_seconds']) if screen_time else None
        
        report_data = {
            'agent_info': agent_info,
            'username': username,
            'start_date': start_date,
            'end_date': end_date,
            'generated_at': datetime.now(timezone.utc),
            'screen_time': screen_agg,
            'apps': processed_apps,
            'domains': processed_domains,
            'new_installs': new_installs,
            'uninstalls': uninstalls,
            'highest_day': highest_day,
            'lowest_day': lowest_day,
            'total_app_categories': self._count_by_category(processed_apps),
            'total_domain_categories': self._count_by_category(processed_domains)
        }
        
        return report_data

    def _count_by_category(self, items):
        """Count items by category."""
        counts = {}
        for item in items:
            cat = item.get('category', 'Other')
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def save_report(self, report_data, report_type='individual'):
        """Save report to HTML and PDF files with collision-safe filenames."""
        if not report_data:
            return None

        try:
            from engines.report_naming import build_report_filename
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'server'))
            from engines.report_naming import build_report_filename

        start_str = report_data['start_date'].strftime('%Y-%m-%d')
        end_str = report_data['end_date'].strftime('%Y-%m-%d')

        date_range_dir = self.output_dir / f"{start_str}_to_{end_str}"
        date_range_dir.mkdir(parents=True, exist_ok=True)

        if report_type == 'individual':
            template = self.jinja_env.get_template('individual_weekly_report.html')
            filename = build_report_filename(
                report_type='weekly',
                scope='individual',
                identity=report_data.get('username'),
                start_date=report_data['start_date'],
                end_date=report_data['end_date'],
                ext='html'
            )
        else:
            template = self.jinja_env.get_template('team_weekly_report.html')
            filename = build_report_filename(
                report_type='weekly',
                scope='team',
                identity='team',
                start_date=report_data['start_date'],
                end_date=report_data['end_date'],
                ext='html'
            )

        filepath = date_range_dir / filename

        html_content = template.render(**report_data)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Report saved: {filepath}")

        if report_type == 'team':
            try:
                from weasyprint import HTML
                pdf_template = self.jinja_env.get_template('team_weekly_report_pdf.html')
                pdf_filename = build_report_filename(
                    report_type='weekly',
                    scope='team',
                    identity='team',
                    start_date=report_data['start_date'],
                    end_date=report_data['end_date'],
                    ext='pdf'
                )
                pdf_filepath = date_range_dir / pdf_filename
                pdf_content = pdf_template.render(**report_data)
                HTML(string=pdf_content).write_pdf(str(pdf_filepath))
                logger.info(f"PDF saved: {pdf_filepath}")
            except ImportError:
                logger.warning("WeasyPrint not installed, skipping PDF")
            except Exception as e:
                logger.error(f"PDF generation failed: {e}", exc_info=True)

        return filepath

    def generate_for_user(self, username, start_date, end_date):
        """Generate report for a specific user."""
        agent_ids = self.get_agent_ids_by_username(username)
        
        if not agent_ids:
            logger.warning(f"No agent found for username: {username}")
            return []
        
        reports = []
        for agent_id in agent_ids:
            logger.info(f"Generating report for {username} (agent: {agent_id})")
            report_data = self.generate_individual_report(agent_id, start_date, end_date)
            if report_data:
                filepath = self.save_report(report_data, 'individual')
                reports.append(filepath)
        
        return reports

    def build_team_report_data(self, start_date, end_date):
        """Build and return team report data dict without saving."""
        users = self.get_all_active_usernames(start_date, end_date)

        team_data = {
            'start_date': start_date,
            'end_date': end_date,
            'generated_at': datetime.now(timezone.utc),
            'team_members': []
        }

        total_team_active = 0

        for user in users:
            report = self.generate_individual_report(
                user['agent_id'], start_date, end_date
            )
            if report:
                if report['screen_time']['days_worked'] > 0:
                    team_data['team_members'].append(report)
                    total_team_active += report['screen_time']['total_active']
                else:
                    logger.warning(f"Skipping {user['username']}: no active screen_time rows for {start_date} to {end_date}")

        team_data['total_team_hours'] = format_hours(total_team_active)
        team_data['avg_per_member'] = (
            format_hours(total_team_active / len(team_data['team_members']))
            if team_data['team_members'] else 0
        )
        team_data['active_members'] = len(team_data['team_members'])

        team_data['team_members'].sort(
            key=lambda x: x['screen_time']['total_active'], reverse=True
        )

        all_apps = {}
        for member in team_data['team_members']:
            for app in member['apps'][:15]:
                key = (app['app'], app['friendly_name'], app['category'])
                if key not in all_apps:
                    all_apps[key] = {'hours': 0, 'sessions': 0}
                all_apps[key]['hours'] += app['total_time']
                all_apps[key]['sessions'] += app['sessions']

        team_data['top_team_apps'] = [
            {
                'app': k[0],
                'friendly_name': k[1],
                'category': k[2],
                'hours': format_hours(v['hours']),
                'duration': format_duration(v['hours']),
                'sessions': v['sessions']
            }
            for k, v in sorted(all_apps.items(), key=lambda x: x[1]['hours'], reverse=True)[:15]
        ]

        all_domains = {}
        for member in team_data['team_members']:
            for domain in member['domains'][:15]:
                key = domain['domain']
                if key not in all_domains:
                    all_domains[key] = {'hours': 0, 'visits': 0, 'category': domain['category']}
                all_domains[key]['hours'] += domain['total_time']
                all_domains[key]['visits'] += domain['visits']

        team_data['top_team_domains'] = [
            {
                'domain': k,
                'category': v['category'],
                'hours': format_hours(v['hours']),
                'duration': format_duration(v['hours']),
                'visits': v['visits']
            }
            for k, v in sorted(all_domains.items(), key=lambda x: x[1]['hours'], reverse=True)[:15]
        ]

        daily_totals = {i: {'active': 0, 'idle': 0, 'locked': 0} for i in range((end_date - start_date).days + 1)}
        num_days = (end_date - start_date).days + 1
        for member in team_data['team_members']:
            for day in member['screen_time']['daily_breakdown']:
                day_index = (day['date'] - start_date).days
                if 0 <= day_index < num_days:
                    daily_totals[day_index]['active'] += day['active_seconds']
                    daily_totals[day_index]['idle'] += day['idle_seconds']
                    daily_totals[day_index]['locked'] += day['locked_seconds']

        team_data['daily_totals'] = [
            {
                'day': (start_date + timedelta(days=i)).strftime('%A'),
                'date': (start_date + timedelta(days=i)).strftime('%Y-%m-%d'),
                **daily_totals[i]
            }
            for i in range(num_days)
        ]

        return team_data

    def generate_team_report(self, start_date, end_date):
        """Generate team summary report."""
        team_data = self.build_team_report_data(start_date, end_date)
        filepath = self.save_report(team_data, 'team')
        return [filepath]

    def close(self):
        """Close database connection."""
        self.conn.close()


def get_last_week_dates():
    """Get start and end dates for the previous complete week."""
    today = date.today()
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday


def main():
    parser = argparse.ArgumentParser(
        description='Generate weekly activity reports for SentinelEdge'
    )
    parser.add_argument('--user', '-u', help='Generate report for specific username')
    parser.add_argument('--users', help='Comma-separated list of usernames')
    parser.add_argument('--all', '-a', action='store_true', help='Generate team report for all users')
    parser.add_argument('--team', '-t', action='store_true', help='Generate team summary report')
    parser.add_argument('--start', '-s', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', '-e', help='End date (YYYY-MM-DD)')
    parser.add_argument('--last-week', '-l', action='store_true', help='Use previous week')
    parser.add_argument('--output', '-o', help='Output directory override')
    parser.add_argument('--db-url', help='Database URL override')
    
    args = parser.parse_args()
    
    if args.last_week:
        start_date, end_date = get_last_week_dates()
    elif args.start and args.end:
        start_date = datetime.strptime(args.start, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end, '%Y-%m-%d').date()
    else:
        start_date, end_date = get_last_week_dates()
        logger.info(f"No dates specified, using last week: {start_date} to {end_date}")
    
    db_url = args.db_url or os.environ.get('DATABASE_URL')
    if not db_url:
        logger.error("DATABASE_URL not provided. Use --db-url or set DATABASE_URL environment variable.")
        sys.exit(1)
    
    generator = WeeklyReportGenerator(db_url)
    
    if args.output:
        generator.output_dir = Path(args.output)
    
    generated_files = []
    
    try:
        if args.user:
            files = generator.generate_for_user(args.user, start_date, end_date)
            generated_files.extend(files)
        
        elif args.users:
            for username in args.users.split(','):
                username = username.strip()
                if username:
                    files = generator.generate_for_user(username, start_date, end_date)
                    generated_files.extend(files)
        
        elif args.all or args.team:
            files = generator.generate_team_report(start_date, end_date)
            generated_files.extend(files)
        
        else:
            parser.print_help()
            logger.info("\nExamples:")
            logger.info("  python generate_weekly_reports.py --user surya --start 2026-02-10 --end 2026-02-16")
            logger.info("  python generate_weekly_reports.py --users surya,chetan,anish --last-week")
            logger.info("  python generate_weekly_reports.py --team --last-week")
            logger.info("  python generate_weekly_reports.py --all")
            sys.exit(0)
        
        if generated_files:
            logger.info(f"\n✅ Generated {len(generated_files)} report(s)")
            for f in generated_files:
                logger.info(f"   {f}")
        else:
            logger.warning("No reports generated")
    
    finally:
        generator.close()


if __name__ == '__main__':
    main()
