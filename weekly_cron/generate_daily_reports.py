#!/usr/bin/env python3
"""
Daily Report Generator for SentinelEdge
Generates individual daily activity reports for a specific agent.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta, date
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor

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
        'replit.com', 'leetcode.com', 'hackerrank.com', 'codesandbox.io'
    ],
    'Communication': [
        'mail.google.com', 'outlook.com', 'office.com', 'webmail',
        'teams.microsoft.com', 'slack.com', 'discord.com', 'zoom.us',
        'webex.com', 'mail.yahoo.com', 'protonmail.com'
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
        'soundcloud.com', 'gaana.com'
    ],
    'News': [
        'news.google.com', 'bbc.com', 'cnn.com', 'nytimes.com',
        'theguardian.com', 'news.ycombinator.com'
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
    if not app_name:
        return 'Other'
    app_lower = app_name.lower()
    for category, apps in APP_CATEGORIES.items():
        if app_lower in apps:
            return category
    return 'Other'


def get_domain_category(domain):
    if not domain:
        return 'Uncategorized'
    domain_lower = domain.lower()
    for category, domains in DOMAIN_CATEGORIES.items():
        for d in domains:
            if d in domain_lower:
                return category
    return 'Other'


def get_friendly_name(app_name):
    if not app_name:
        return 'Unknown'
    return APP_FRIENDLY_NAMES.get(app_name.lower(), app_name.replace('.exe', '').title())


def format_duration(seconds):
    if seconds is None:
        return '0h 0m'
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f'{hours}h {minutes}m'


def format_hours(seconds):
    if seconds is None:
        return 0.0
    return round(seconds / 3600, 1)


class DailyReportGenerator:
    def __init__(self, db_url=None):
        self.db_url = db_url or os.environ.get('DATABASE_URL')
        if not self.db_url:
            raise ValueError("DATABASE_URL not provided")
        
        self.conn = psycopg2.connect(self.db_url)
        self.output_dir = Path(__file__).parent.parent / 'reports' / 'daily'
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_agent_info(self, agent_id):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT a.agent_id, a.agent_name, a.hostname, a.os,
                       acs.username, a.created_at
                FROM agents a
                LEFT JOIN agent_current_status acs ON a.agent_id = acs.agent_id
                WHERE a.agent_id = %s
            """, (agent_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_screen_time_data(self, agent_id, target_date):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT date, 
                       COALESCE(active_seconds, 0) as active_seconds,
                       COALESCE(idle_seconds, 0) as idle_seconds,
                       COALESCE(locked_seconds, 0) as locked_seconds,
                       COALESCE(away_seconds, 0) as away_seconds
                FROM screen_time
                WHERE agent_id = %s AND date = %s
            """, (agent_id, target_date))
            return dict(cur.fetchone()) if cur.rowcount else None

    def get_app_usage_data(self, agent_id, target_date):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT app, 
                       duration_seconds as total_time,
                       session_count as sessions
                FROM app_usage
                WHERE agent_id = %s AND date = %s
                AND duration_seconds > 0
                ORDER BY total_time DESC
                LIMIT 15
            """, (agent_id, target_date))
            return [dict(row) for row in cur.fetchall()]

    def get_domain_usage_data(self, agent_id, target_date):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT domain, 
                       duration_seconds as total_time,
                       session_count as visits
                FROM domain_usage
                WHERE agent_id = %s AND date = %s
                AND duration_seconds > 0
                ORDER BY total_time DESC
                LIMIT 15
            """, (agent_id, target_date))
            return [dict(row) for row in cur.fetchall()]

    def generate_daily_report(self, agent_id, target_date):
        agent_info = self.get_agent_info(agent_id)
        if not agent_info:
            logger.warning(f"No agent found for ID: {agent_id}")
            return None
        
        username = agent_info.get('username', 'Unknown')
        if username and '\\' in username:
            username = username.split('\\')[-1]
        
        screen_time = self.get_screen_time_data(agent_id, target_date)
        
        if not screen_time or screen_time.get('active_seconds', 0) == 0:
            logger.info(f"No activity for {target_date}, skipping")
            return None
        
        app_usage = self.get_app_usage_data(agent_id, target_date)
        domain_usage = self.get_domain_usage_data(agent_id, target_date)
        
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
        
        report_data = {
            'agent_info': agent_info,
            'username': username,
            'target_date': target_date,
            'generated_at': datetime.now(),
            'screen_time': screen_time,
            'apps': processed_apps,
            'domains': processed_domains,
            'total_app_categories': self._count_by_category(processed_apps),
            'total_domain_categories': self._count_by_category(processed_domains)
        }
        
        return report_data

    def _count_by_category(self, items):
        counts = {}
        for item in items:
            cat = item.get('category', 'Other')
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def save_report(self, report_data):
        if not report_data:
            return None
        
        date_str = report_data['target_date'].strftime('%Y-%m-%d')
        username = report_data['username']
        
        filename = f"{username}_daily_{date_str}.html"
        
        filepath = self.output_dir / filename
        
        html_content = self._generate_html(report_data)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"Report saved: {filepath}")
        return filepath

    def _generate_html(self, data):
        username = data['username']
        target_date = data['target_date'].strftime('%Y-%m-%d')
        st = data['screen_time']
        
        active_h = format_hours(st.get('active_seconds', 0))
        idle_h = format_hours(st.get('idle_seconds', 0))
        locked_h = format_hours(st.get('locked_seconds', 0))
        
        apps_html = ""
        for app in data['apps'][:10]:
            apps_html += f"""
            <tr>
                <td>{app['friendly_name']}</td>
                <td>{app['category']}</td>
                <td>{app['duration']}</td>
                <td>{app['sessions']}</td>
            </tr>
            """
        
        domains_html = ""
        for domain in data['domains'][:10]:
            domains_html += f"""
            <tr>
                <td>{domain['domain']}</td>
                <td>{domain['category']}</td>
                <td>{domain['duration']}</td>
                <td>{domain['visits']}</td>
            </tr>
            """
        
        hostname = data['agent_info'].get('hostname', 'N/A')
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Report - {username} - {target_date}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #4a90d9; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .meta {{ color: #777; margin-bottom: 20px; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin: 20px 0; }}
        .stat-card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 28px; font-weight: bold; color: #4a90d9; }}
        .stat-label {{ color: #666; font-size: 14px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        tr:hover {{ background: #f8f9fa; }}
        .footer {{ margin-top: 40px; text-align: center; color: #999; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Daily Activity Report</h1>
        <div class="meta">
            <strong>User:</strong> {username} | 
            <strong>Date:</strong> {target_date} | 
            <strong>Device:</strong> {hostname}
        </div>
        
        <h2>Screen Time</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{active_h}h</div>
                <div class="stat-label">Active</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{idle_h}h</div>
                <div class="stat-label">Idle</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{locked_h}h</div>
                <div class="stat-label">Locked</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(data['apps'])}</div>
                <div class="stat-label">Apps Used</div>
            </div>
        </div>
        
        <h2>Top Applications</h2>
        <table>
            <thead>
                <tr>
                    <th>Application</th>
                    <th>Category</th>
                    <th>Duration</th>
                    <th>Sessions</th>
                </tr>
            </thead>
            <tbody>
                {apps_html or '<tr><td colspan="4">No app data</td></tr>'}
            </tbody>
        </table>
        
        <h2>Top Domains</h2>
        <table>
            <thead>
                <tr>
                    <th>Domain</th>
                    <th>Category</th>
                    <th>Duration</th>
                    <th>Visits</th>
                </tr>
            </thead>
            <tbody>
                {domains_html or '<tr><td colspan="4">No domain data</td></tr>'}
            </tbody>
        </table>
        
        <div class="footer">
            Generated by SentinelEdge | {data['generated_at'].strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>
</body>
</html>"""
        return html

    def generate_reports_for_range(self, agent_id, start_date, end_date):
        current_date = start_date
        generated = []
        
        while current_date <= end_date:
            report = self.generate_daily_report(agent_id, current_date)
            if report:
                filepath = self.save_report(report)
                if filepath:
                    generated.append(filepath)
            current_date += timedelta(days=1)
        
        return generated

    def close(self):
        self.conn.close()


def main():
    parser = argparse.ArgumentParser(description='Generate daily activity reports')
    parser.add_argument('--agent-id', required=True, help='Agent UUID')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--db-url', help='Database URL override')
    
    args = parser.parse_args()
    
    db_url = args.db_url or os.environ.get('DATABASE_URL')
    if not db_url:
        logger.error("DATABASE_URL not provided")
        sys.exit(1)
    
    start_date = datetime.strptime(args.start, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end, '%Y-%m-%d').date()
    
    generator = DailyReportGenerator(db_url)
    
    try:
        files = generator.generate_reports_for_range(args.agent_id, start_date, end_date)
        logger.info(f"\nGenerated {len(files)} daily report(s)")
        for f in files:
            logger.info(f"  {f}")
    finally:
        generator.close()


if __name__ == '__main__':
    main()
