"""
CPU-Based Fallback Tracker
Used when window tracking fails (RDP, service mode, locked screen)
Estimates active app by CPU usage (70-80% accuracy)
"""

import psutil
import logging
from typing import Optional, Dict
from collections import defaultdict
import time

logger = logging.getLogger(__name__)


class CPUBasedTracker:
    """
    Fallback tracker using CPU usage patterns.
    
    WARNING: Not 100% accurate! Use only when window tracking fails.
    Background processes (compiling, virus scan, etc.) can have high CPU.
    """
    
    def __init__(self):
        self.logger = logging.getLogger('CPUFallback')
        self.cpu_history = defaultdict(list)
        self.sample_count = 3  # Take 3 samples
        self.excluded_processes = {
            'system', 'idle', 'system idle process',
            'svchost.exe', 'dwm.exe', 'csrss.exe',
            'services.exe', 'lsass.exe', 'smss.exe',
            'wininit.exe', 'winlogon.exe', 'spoolsv.exe',
            'searchindexer.exe', 'windows defender',
            'mssense.exe', 'antimalware service executable',
            'runtimebroker.exe', 'applicationframehost.exe',
            'shellexperiencehost.exe', 'startmenuexperiencehost.exe',
            'securityhealthservice.exe', 'searchui.exe',
            'sihost.exe', 'fontdrvhost.exe', 'ctfmon.exe',
            'taskhostw.exe', 'dllhost.exe', 'conhost.exe',
            'smartscreen.exe', 'searchapp.exe', 'lockapp.exe',
            'textinputhost.exe', 'widgetservice.exe'
        }
        
    def get_active_app_by_cpu(self) -> Optional[str]:
        """
        Estimate active app by CPU usage.
        
        Returns:
            App name (e.g., "chrome.exe") or None
        """
        try:
            cpu_usage = {}
            
            # Take multiple samples over ~1 second
            for _ in range(self.sample_count):
                for proc in psutil.process_iter(['name', 'cpu_percent']):
                    try:
                        name = proc.info['name'].lower()
                        
                        # Skip system processes
                        if name in self.excluded_processes:
                            continue
                        
                        # Skip if name is empty
                        if not name or name == '':
                            continue
                        
                        # Get CPU usage (interval=0.1 for quick sampling)
                        cpu = proc.cpu_percent(interval=0.1)
                        
                        if name in cpu_usage:
                            cpu_usage[name] += cpu
                        else:
                            cpu_usage[name] = cpu
                            
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
                
                time.sleep(0.2)  # Brief pause between samples
            
            if not cpu_usage:
                return None
            
            # Average CPU usage
            for name in cpu_usage:
                cpu_usage[name] /= self.sample_count
            
            # Get top 3 CPU consumers for logging
            top_apps = sorted(cpu_usage.items(), key=lambda x: x[1], reverse=True)[:3]
            
            if not top_apps:
                return None
            
            # Get highest CPU app
            top_app = top_apps[0]
            
            # Only consider if CPU > 3% (filter out idle apps)
            if top_app[1] > 3.0:
                top_3_str = ', '.join([f"{app}({cpu:.1f}%)" for app, cpu in top_apps])
                self.logger.debug(f"[CPU] Top apps: {top_3_str}")
                return top_app[0]
            
            self.logger.debug(f"[CPU] All apps idle (max CPU: {top_app[1]:.1f}%)")
            return None
            
        except Exception as e:
            self.logger.error(f"[CPU] Error: {e}")
            return None
    
    def get_top_apps(self, count: int = 5) -> list:
        """
        Get top CPU consuming apps.
        
        Returns:
            List of (app_name, cpu_percent) tuples
        """
        try:
            cpu_usage = {}
            
            for proc in psutil.process_iter(['name', 'cpu_percent']):
                try:
                    name = proc.info['name'].lower()
                    
                    if name in self.excluded_processes:
                        continue
                    
                    if not name:
                        continue
                    
                    cpu = proc.cpu_percent(interval=0.1)
                    
                    if name in cpu_usage:
                        cpu_usage[name] = max(cpu_usage[name], cpu)
                    else:
                        cpu_usage[name] = cpu
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            return sorted(cpu_usage.items(), key=lambda x: x[1], reverse=True)[:count]
            
        except Exception as e:
            self.logger.error(f"[CPU] Error getting top apps: {e}")
            return []
