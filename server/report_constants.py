"""
report_constants.py — Shared classification maps and formatting helpers for report generation.
Imported by report_engine.py. weekly_cron generators maintain their own copies.
"""

APP_CATEGORIES = {
    'Development': ['code.exe','devenv.exe','idea64.exe','pycharm64.exe','webstorm64.exe',
        'sublime_text.exe','notepad++.exe','atom.exe','cursor.exe','antigravity.exe',
        'putty.exe','winscp.exe','code - insiders.exe','rider64.exe','goland64.exe',
        'phpstorm64.exe','rubymine64.exe','eclipse.exe','netbeans64.exe'],
    'Communication': ['slack.exe','teams.exe','ms-teams.exe','discord.exe','zoom.exe',
        'skype.exe','telegram.exe','whatsapp.exe','olk.exe','outlook.exe',
        'teams for business.exe','slack - beta.exe'],
    'Browsers': ['chrome.exe','msedge.exe','firefox.exe','brave.exe','opera.exe',
        'vivaldi.exe','safari.exe','chromium.exe'],
    'Productivity': ['winword.exe','excel.exe','powerpnt.exe','onenote.exe','toad.exe',
        'ssms.exe','azuredatastudio.exe','dbeaver.exe','heidisql.exe','navicat.exe'],
    'Terminal': ['windowsterminal.exe','cmd.exe','powershell.exe','wt.exe',
        'terminus.exe','hyper.exe','alacritty.exe'],
    'Media': ['spotify.exe','vlc.exe','music.ui.exe'],
    'Database': ['ssms.exe','azuredatastudio.exe','dbeaver.exe','heidisql.exe',
        'navicat.exe','mysql.exe','psql.exe'],
}

APP_FRIENDLY_NAMES = {
    'code.exe':'VS Code','devenv.exe':'Visual Studio','idea64.exe':'IntelliJ IDEA',
    'pycharm64.exe':'PyCharm','webstorm64.exe':'WebStorm','sublime_text.exe':'Sublime Text',
    'notepad++.exe':'Notepad++','cursor.exe':'Cursor','slack.exe':'Slack',
    'teams.exe':'Microsoft Teams','ms-teams.exe':'Microsoft Teams','discord.exe':'Discord',
    'zoom.exe':'Zoom','olk.exe':'Outlook (New)','chrome.exe':'Google Chrome',
    'msedge.exe':'Microsoft Edge','firefox.exe':'Mozilla Firefox','brave.exe':'Brave Browser',
    'winword.exe':'Microsoft Word','excel.exe':'Microsoft Excel','powerpnt.exe':'PowerPoint',
    'outlook.exe':'Outlook','onenote.exe':'OneNote','windowsterminal.exe':'Windows Terminal',
    'cmd.exe':'Command Prompt','powershell.exe':'PowerShell','spotify.exe':'Spotify',
    'vlc.exe':'VLC Media Player','toad.exe':'Toad for Oracle',
    'ssms.exe':'SQL Server Management Studio','azuredatastudio.exe':'Azure Data Studio',
    'dbeaver.exe':'DBeaver','mstsc.exe':'Remote Desktop','antigravity.exe':'Antigravity',
}

DOMAIN_CATEGORIES = {
    'Productivity': ['github.com','gitlab.com','stackoverflow.com','atlassian.net',
        'aws.amazon.com','jira','confluence'],
    'Communication': ['mail.google.com','outlook.com','office.com','teams.microsoft.com',
        'slack.com','discord.com','zoom.us','web.whatsapp.com'],
    'AI Tools': ['chatgpt.com','claude.ai','gemini.google','perplexity.ai',
        'copilot.microsoft.com'],
    'Learning': ['docs.microsoft.com','developer.mozilla.org','w3schools.com',
        'medium.com','stackoverflow.com','freecodecamp.org'],
    'Social': ['linkedin.com','twitter.com','facebook.com','instagram.com','reddit.com'],
    'Entertainment': ['youtube.com','netflix.com','spotify.com','cricbuzz.com','twitch.tv'],
}

SYSTEM_APPS = {
    'lockapp.exe','applicationframehost.exe','shellexperiencehost.exe',
    'startmenuexperiencehost.exe','searchui.exe','runtimebroker.exe',
    'backgroundtaskhost.exe','systemsettings.exe','textinputhost.exe',
    'dwm.exe','csrss.exe','winlogon.exe','sihost.exe','ctfmon.exe',
    'dllhost.exe','smartscreen.exe','securityhealthservice.exe',
    'searchapp.exe','msmpeng.exe','services.exe','lsass.exe','svchost.exe',
    'system','smss.exe','conhost.exe','taskhostw.exe','explorer.exe',
}


def get_category(app):
    a = (app or '').lower()
    for cat, apps in APP_CATEGORIES.items():
        if a in apps:
            return cat
    return 'Other'


def get_domain_category(domain):
    d = (domain or '').lower()
    for cat, domains in DOMAIN_CATEGORIES.items():
        for item in domains:
            if item in d:
                return cat
    return 'Other'


def friendly_name(app):
    return APP_FRIENDLY_NAMES.get((app or '').lower(), (app or '').replace('.exe', '').title())


def fmt_duration(seconds):
    if not seconds:
        return '0h 0m'
    h, m = int(seconds // 3600), int((seconds % 3600) // 60)
    return f'{h}h {m}m'


def fmt_hours(seconds):
    return round((seconds or 0) / 3600, 1)
