"""
App Name Mapper - Maps executable names to friendly display names
"""
from typing import Optional
import os
import re

# Mapping of executable names to friendly names
APP_NAME_MAP = {
    # Browsers
    'chrome.exe': 'Google Chrome',
    'brave.exe': 'Brave Browser',
    'msedge.exe': 'Microsoft Edge',
    'firefox.exe': 'Mozilla Firefox',
    'opera.exe': 'Opera Browser',
    'vivaldi.exe': 'Vivaldi Browser',
    'iexplore.exe': 'Internet Explorer',
    
    # Development
    'code.exe': 'VS Code',
    'devenv.exe': 'Visual Studio',
    'pycharm64.exe': 'PyCharm',
    'idea64.exe': 'IntelliJ IDEA',
    'webstorm64.exe': 'WebStorm',
    'sublime_text.exe': 'Sublime Text',
    'notepad++.exe': 'Notepad++',
    'atom.exe': 'Atom',
    'rider64.exe': 'JetBrains Rider',
    'datagrip64.exe': 'DataGrip',
    'android studio.exe': 'Android Studio',
    'eclipse.exe': 'Eclipse',
    'postman.exe': 'Postman',
    'windowsterminal.exe': 'Windows Terminal',
    'powershell.exe': 'PowerShell',
    'cmd.exe': 'Command Prompt',
    'wt.exe': 'Windows Terminal',
    'mintty.exe': 'Git Bash',
    'conhost.exe': 'Console Host',
    'github desktop.exe': 'GitHub Desktop',
    'gitkraken.exe': 'GitKraken',
    'sourcetree.exe': 'SourceTree',
    
    # Microsoft Office
    'winword.exe': 'Microsoft Word',
    'excel.exe': 'Microsoft Excel',
    'powerpnt.exe': 'Microsoft PowerPoint',
    'outlook.exe': 'Microsoft Outlook',
    'onenote.exe': 'Microsoft OneNote',
    'msteams.exe': 'Microsoft Teams',
    'teams.exe': 'Microsoft Teams',
    'lync.exe': 'Skype for Business',
    
    # Communication
    'slack.exe': 'Slack',
    'discord.exe': 'Discord',
    'zoom.exe': 'Zoom',
    'skype.exe': 'Skype',
    'telegram.exe': 'Telegram',
    'whatsapp.exe': 'WhatsApp',
    'signal.exe': 'Signal',
    
    # Media
    'spotify.exe': 'Spotify',
    'vlc.exe': 'VLC Media Player',
    'wmplayer.exe': 'Windows Media Player',
    'itunes.exe': 'iTunes',
    
    # Graphics/Design
    'photoshop.exe': 'Adobe Photoshop',
    'illustrator.exe': 'Adobe Illustrator',
    'acrobat.exe': 'Adobe Acrobat',
    'acrord32.exe': 'Adobe Reader',
    'figma.exe': 'Figma',
    'xd.exe': 'Adobe XD',
    'sketch.exe': 'Sketch',
    
    # System
    'explorer.exe': 'File Explorer',
    'taskmgr.exe': 'Task Manager',
    'notepad.exe': 'Notepad',
    'mspaint.exe': 'Paint',
    'calc.exe': 'Calculator',
    'snippingtool.exe': 'Snipping Tool',
    'mmc.exe': 'Management Console',
    'regedit.exe': 'Registry Editor',
    'control.exe': 'Control Panel',
    'systemsettings.exe': 'Settings',
    
    # Utilities
    '7zfm.exe': '7-Zip File Manager',
    'winrar.exe': 'WinRAR',
    'everything.exe': 'Everything Search',
    'ditto.exe': 'Ditto Clipboard',
    'greenshot.exe': 'Greenshot',
    'sharex.exe': 'ShareX',
    
    # Database
    'ssms.exe': 'SQL Server Management Studio',
    'pgadmin4.exe': 'pgAdmin',
    'dbeaver.exe': 'DBeaver',
    'mongodb compass.exe': 'MongoDB Compass',
    'robo3t.exe': 'Robo 3T',
    
    # Other
    'filezilla.exe': 'FileZilla',
    'putty.exe': 'PuTTY',
    'winscp.exe': 'WinSCP',
    'anydesk.exe': 'AnyDesk',
    'teamviewer.exe': 'TeamViewer',
    'steam.exe': 'Steam',
    'epicgameslauncher.exe': 'Epic Games',
    
    # AI Tools
    'claude.exe': 'Claude AI',
    'chatgpt.exe': 'ChatGPT',
    'antigravity.exe': 'Antigravity IDE',
    'cursor.exe': 'Cursor AI',
    'copilot.exe': 'GitHub Copilot',
    
    # UWP / Microsoft Store Apps
    'calculator.exe': 'Calculator',
    'store.exe': 'Microsoft Store',
    'mail.exe': 'Mail',
    'calendar.exe': 'Calendar',
    'photos.exe': 'Photos',
    'movies.exe': 'Movies & TV',
    'music.exe': 'Groove Music',
    'xbox.exe': 'Xbox',
    'gamebar.exe': 'Xbox Game Bar',
    'feedback.exe': 'Feedback Hub',
    'weather.exe': 'Weather',
    'clock.exe': 'Alarms & Clock',
    'snip.exe': 'Snip & Sketch',
    'stickynotes.exe': 'Sticky Notes',
    'yourphone.exe': 'Phone Link',
    'netflix.exe': 'Netflix',
    'twitter.exe': 'Twitter',
    'instagram.exe': 'Instagram',
    'tiktok.exe': 'TikTok',
    'amazonmusic.exe': 'Amazon Music',
    'primevideo.exe': 'Prime Video',
    'disneyplus.exe': 'Disney+',
    'todo.exe': 'Microsoft To Do',
    'news.exe': 'News',
    'cortana.exe': 'Cortana',
    'securityhealthhost.exe': 'Windows Security',
    'peopleexperiencehost.exe': 'People',
    'windowsalarms.exe': 'Alarms & Clock',
    'someappname.exe': 'Fallback UWP App',
}


def get_friendly_name(exe_name: str) -> str:
    """
    Get friendly name for an executable.
    
    Args:
        exe_name: The executable name (e.g., 'chrome.exe')
        
    Returns:
        Friendly name (e.g., 'Google Chrome') or cleaned-up exe name
    """
    if not exe_name:
        return 'Unknown'
    
    # Normalize to lowercase
    exe_lower = exe_name.lower().strip()
    
    # Direct lookup
    if exe_lower in APP_NAME_MAP:
        return APP_NAME_MAP[exe_lower]
    
    # Try without .exe suffix
    if exe_lower.endswith('.exe'):
        base_name = exe_lower[:-4]
        # Check if base name is in mapping
        for key, value in APP_NAME_MAP.items():
            if key.startswith(base_name):
                return value
    
    # Fallback: Clean up the exe name
    # Remove .exe, capitalize, replace underscores/dots with spaces
    clean = exe_lower.replace('.exe', '')
    clean = re.sub(r'[_\-.]', ' ', clean)
    clean = clean.title()
    
    return clean


def get_app_category(exe_name: str) -> str:
    """
    Get category for an app (for grouping in dashboard).
    
    Returns: 'browser', 'development', 'communication', 'productivity', 'media', 'system', 'other'
    """
    exe_lower = exe_name.lower().strip()
    
    browsers = {'chrome.exe', 'brave.exe', 'msedge.exe', 'firefox.exe', 'opera.exe', 'vivaldi.exe', 'iexplore.exe'}
    development = {'code.exe', 'devenv.exe', 'pycharm64.exe', 'idea64.exe', 'sublime_text.exe', 'notepad++.exe', 
                   'windowsterminal.exe', 'powershell.exe', 'cmd.exe', 'postman.exe', 'antigravity.exe', 'cursor.exe'}
    communication = {'slack.exe', 'discord.exe', 'zoom.exe', 'msteams.exe', 'teams.exe', 'skype.exe', 'telegram.exe',
                     'whatsapp.exe', 'signal.exe', 'mail.exe', 'twitter.exe', 'instagram.exe'}
    productivity = {'winword.exe', 'excel.exe', 'powerpnt.exe', 'outlook.exe', 'onenote.exe', 'notepad.exe',
                    'calendar.exe', 'stickynotes.exe'}
    media = {'spotify.exe', 'vlc.exe', 'wmplayer.exe', 'itunes.exe', 'photos.exe', 'movies.exe', 'music.exe',
             'netflix.exe', 'primevideo.exe', 'disneyplus.exe', 'amazonmusic.exe', 'tiktok.exe'}
    entertainment = {'xbox.exe', 'gamebar.exe', 'steam.exe', 'epicgameslauncher.exe'}
    system = {'explorer.exe', 'taskmgr.exe', 'control.exe', 'systemsettings.exe', 'mmc.exe', 
              'calculator.exe', 'clock.exe', 'snip.exe', 'weather.exe', 'store.exe', 'feedback.exe', 'yourphone.exe'}
    
    if exe_lower in browsers:
        return 'browser'
    elif exe_lower in development:
        return 'development'
    elif exe_lower in communication:
        return 'communication'
    elif exe_lower in productivity:
        return 'productivity'
    elif exe_lower in media:
        return 'media'
    elif exe_lower in entertainment:
        return 'entertainment'
    elif exe_lower in system:
        return 'system'
    else:
        return 'other'


def is_browser(exe_name: str) -> bool:
    """Check if app is a browser (for domain tracking)."""
    browsers = {'chrome.exe', 'brave.exe', 'msedge.exe', 'firefox.exe', 'opera.exe', 'vivaldi.exe', 'iexplore.exe'}
    return exe_name.lower().strip() in browsers
