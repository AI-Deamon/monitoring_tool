"""
report_constants.py — Shared classification maps and formatting helpers for report generation.
Imported by engines/report_engine.py. weekly_cron generators maintain their own copies.
"""

APP_CATEGORIES = {
    'Development': ['code.exe','devenv.exe','idea64.exe','pycharm64.exe','webstorm64.exe',
        'sublime_text.exe','notepad++.exe','atom.exe','cursor.exe','antigravity.exe',
        'putty.exe','winscp.exe','code - insiders.exe','rider64.exe','goland64.exe',
        'phpstorm64.exe','rubymine64.exe','eclipse.exe','netbeans64.exe',
        'clion64.exe','datagrip64.exe','android studio64.exe','studio64.exe',
        'unity.exe','unityhub.exe','postman.exe','insomnia.exe','fiddler.exe',
        'wireshark.exe','docker desktop.exe','github desktop.exe','githubdesktop.exe',
        'sourcetree.exe','gitkraken.exe','tortoiseproc.exe','vagrant.exe',
        'kitty.exe','windsurf.exe'],
    'Communication': ['slack.exe','teams.exe','ms-teams.exe','discord.exe','zoom.exe',
        'skype.exe','telegram.exe','whatsapp.exe','olk.exe','outlook.exe',
        'teams for business.exe','slack - beta.exe','signal.exe','webex.exe',
        'gotomeeting.exe','element.exe','thunderbird.exe','mattermost.exe',
        'ringcentral.exe','viber.exe'],
    'Browsers': ['chrome.exe','msedge.exe','firefox.exe','brave.exe','opera.exe',
        'vivaldi.exe','safari.exe','chromium.exe','arc.exe','tor.exe','iron.exe'],
    'Productivity': ['winword.exe','excel.exe','powerpnt.exe','onenote.exe','toad.exe',
        'ssms.exe','azuredatastudio.exe','dbeaver.exe','heidisql.exe','navicat.exe',
        'notion.exe','obsidian.exe','evernote.exe','todoist.exe','trello.exe',
        'acrobat.exe','acrord32.exe','soffice.exe','libreoffice.exe','wps.exe',
        'visio.exe','project.exe','xmind.exe','miro.exe'],
    'Terminal': ['windowsterminal.exe','cmd.exe','powershell.exe','pwsh.exe','wt.exe',
        'terminus.exe','hyper.exe','alacritty.exe','mintty.exe','cmder.exe',
        'conemu64.exe','tabby.exe'],
    'Media': ['spotify.exe','vlc.exe','music.ui.exe','wmplayer.exe','potplayer.exe',
        'itunes.exe','audacity.exe','obs64.exe'],
    'Database': ['ssms.exe','azuredatastudio.exe','dbeaver.exe','heidisql.exe',
        'navicat.exe','mysql.exe','psql.exe','pgadmin4.exe','mongodbcompass.exe',
        'redis-cli.exe','robo3t.exe','studio3t.exe'],
    'Design': ['photoshop.exe','illustrator.exe','figma.exe','xd.exe','indesign.exe',
        'premiere.exe','aftereffects.exe','blender.exe','sketch.exe','canva.exe',
        'coreldrw.exe','gimp.exe','inkscape.exe'],
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
    'clion64.exe':'CLion','datagrip64.exe':'DataGrip','studio64.exe':'Android Studio',
    'postman.exe':'Postman','insomnia.exe':'Insomnia','wireshark.exe':'Wireshark',
    'githubdesktop.exe':'GitHub Desktop','sourcetree.exe':'Sourcetree','gitkraken.exe':'GitKraken',
    'signal.exe':'Signal','webex.exe':'Webex','thunderbird.exe':'Thunderbird',
    'mattermost.exe':'Mattermost','arc.exe':'Arc Browser','notion.exe':'Notion',
    'obsidian.exe':'Obsidian','evernote.exe':'Evernote','todoist.exe':'Todoist',
    'trello.exe':'Trello','acrobat.exe':'Adobe Acrobat','acrord32.exe':'Adobe Acrobat Reader',
    'soffice.exe':'LibreOffice','visio.exe':'Microsoft Visio','miro.exe':'Miro',
    'pwsh.exe':'PowerShell 7','pgadmin4.exe':'pgAdmin','mongodbcompass.exe':'MongoDB Compass',
    'obs64.exe':'OBS Studio','photoshop.exe':'Adobe Photoshop','illustrator.exe':'Adobe Illustrator',
    'figma.exe':'Figma','xd.exe':'Adobe XD','premiere.exe':'Adobe Premiere Pro',
    'aftereffects.exe':'Adobe After Effects','blender.exe':'Blender','canva.exe':'Canva',
    'gimp.exe':'GIMP','inkscape.exe':'Inkscape',
}

DOMAIN_CATEGORIES = {
    'Productivity': ['github.com','gitlab.com','bitbucket.org','stackoverflow.com',
        'atlassian.net','aws.amazon.com','jira','confluence','notion.so',
        'trello.com','asana.com','monday.com','miro.com','figma.com',
        'canva.com','docs.google.com','drive.google.com','dropbox.com',
        'onedrive.live.com','sharepoint.com'],
    'Communication': ['mail.google.com','gmail.com','outlook.com','office.com',
        'teams.microsoft.com','slack.com','discord.com','zoom.us','webex.com',
        'web.whatsapp.com','web.telegram.org','meet.google.com','goto.com'],
    'AI Tools': ['chatgpt.com','openai.com','claude.ai','gemini.google','perplexity.com',
        'perplexity.ai','copilot.microsoft.com','huggingface.co','midjourney.com'],
    'Learning': ['docs.microsoft.com','developer.mozilla.org','w3schools.com',
        'medium.com','stackoverflow.com','freecodecamp.org','udemy.com',
        'coursera.org','pluralsight.com','geeksforgeeks.org'],
    'Social': ['linkedin.com','twitter.com','x.com','facebook.com','instagram.com',
        'reddit.com','pinterest.com','snapchat.com','tiktok.com'],
    'Entertainment': ['youtube.com','netflix.com','spotify.com','cricbuzz.com',
        'twitch.tv','primevideo.com','hotstar.com','espn.com'],
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
