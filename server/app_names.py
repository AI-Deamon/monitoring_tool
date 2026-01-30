
CATEGORY_MAPPING = {
    # Productivity
    'code.exe': 'productivity',
    'devenv.exe': 'productivity',
    'idea64.exe': 'productivity',
    'winword.exe': 'productivity',
    'excel.exe': 'productivity',
    'powerpnt.exe': 'productivity',
    'outlook.exe': 'productivity',
    'onenote.exe': 'productivity',
    'notion.exe': 'productivity',
    
    # Communication
    'teams.exe': 'communication',
    'slack.exe': 'communication',
    'zoom.exe': 'communication',
    'discord.exe': 'communication',
    'skype.exe': 'communication',
    'whatsapp.exe': 'communication',
    'telegram.exe': 'communication',
    
    # Browsing
    'chrome.exe': 'browsing',
    'firefox.exe': 'browsing',
    'msedge.exe': 'browsing',
    'opera.exe': 'browsing',
    'brave.exe': 'browsing',
    'safari.exe': 'browsing',
    
    # Development
    'idea64.exe': 'development',
    'pycharm64.exe': 'development',
    'code.exe': 'development',
    'sublime_text.exe': 'development',
    'powershell.exe': 'development',
    'cmd.exe': 'development',
    'wt.exe': 'development',
    'bash.exe': 'development',
    
    # Other (default for unmapped apps)
}

def get_app_category(app_name: str) -> str:
    """Get category for an app"""
    if not app_name:
        return 'other'
    app_lower = app_name.lower()
    return CATEGORY_MAPPING.get(app_lower, 'other')
