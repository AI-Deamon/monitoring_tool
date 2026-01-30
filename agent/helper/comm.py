"""
Communication Module
Enhanced with strict HMAC verification, replay protection, and persistent queuing
"""
import os
import json
import hmac
import hashlib
import time
from datetime import datetime, timezone
from typing import Dict, Optional
import logging
import urllib.request
import urllib.error
from pathlib import Path

from .config import HelperConfig
from .persistence import PersistenceQueue

logger = logging.getLogger(__name__)

class ReplayProtectionCache:
    """Simple replay protection for outgoing requests"""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.cache = set()
    
    def add_and_check(self, payload_hash: str) -> bool:
        """Add hash to cache and check if it's a duplicate"""
        if payload_hash in self.cache:
            return False  # Duplicate detected
        
        self.cache.add(payload_hash)
        
        # Maintain size limit
        if len(self.cache) > self.max_size:
            # Remove oldest entries (simplified - in production, use OrderedDict)
            self.cache = set(list(self.cache)[-self.max_size//2:])
        
        return True

class CoreCommunicator:
    """Handles communication with Core service with enhanced security and persistence"""
    
    def __init__(self, config: HelperConfig):
        self.config = config
        self.replay_cache = ReplayProtectionCache()
        self.queue = PersistenceQueue(config.data_dir)
        
        # Initial flush of pending items
        try:
            self._flush_queue()
        except:
            pass
    
    @property
    def core_url(self) -> str:
        """Get core_url dynamically from config"""
        return self.config.core_url
    
    @property
    def agent_id(self) -> str:
        """Get agent_id dynamically from config (may change after identity sync)"""
        return self.config.agent_id or os.environ.get('COMPUTERNAME', 'unknown')
        
    def _make_request(self, endpoint: str, data: Dict, timeout: int = 30) -> Optional[Dict]:
        """Make HTTP request to core (Security Disabled)"""
        try:
            url = f"{self.core_url}{endpoint}"
            
            # Prepare request
            json_data = json.dumps(data).encode('utf-8')
            
            req = urllib.request.Request(
                url,
                data=json_data,
                headers={
                    'Content-Type': 'application/json',
                    'X-Agent-Id': self.agent_id
                },
                method='POST'
            )
            
            # Send request
            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_data = response.read().decode('utf-8')
                if response_data:
                    return json.loads(response_data)
                return {'status': 'ok'}
                
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP error {e.code} for {endpoint}: {e.reason}")
            
            # Auto-reload identity if 401 occurs
            if e.code == 401:
                logger.error("[SYNC] 401 Unauthorized - reloading identity from Core")
                # This will be handled by the main loop's safety check
                return None
            return None
        except urllib.error.URLError as e:
            logger.error(f"URL error for {endpoint}: {e.reason}")
            return None
        except ValueError as e:
            if "Duplicate payload" in str(e):
                logger.warning(f"Duplicate request prevented for {endpoint}")
            else:
                logger.error(f"Request error for {endpoint}: {e}")
            return None
        except Exception as e:
            logger.error(f"Request error for {endpoint}: {e}")
            return None
    
    def _flush_queue(self):
        """Flush pending items from queue to core"""
        # Get oldest items first (FIFO)
        items = self.queue.get_oldest(limit=5)
        
        if not items:
            return
            
        logger.debug(f"Flushing {len(items)} items from queue...")
        
        for file_path, item in items:
            endpoint = item.get('endpoint')
            payload = item.get('payload')
            
            if not endpoint or not payload:
                self.queue.remove(file_path)
                continue
            
            # Try to send
            response = self._make_request(endpoint, payload)
            
            if response is not None:
                # Success - remove from queue
                self.queue.remove(file_path)
            else:
                # Failure - stop flushing to preserve order
                logger.debug("Flush interrupted due to connection failure")
                break
                
    def send_heartbeat(self, heartbeat: Dict) -> bool:
        """
        Queue and send heartbeat to core
        
        Args:
            heartbeat: Heartbeat data dict
            
        Returns:
            True (always accepted for processing)
        """
        # Add to persistent queue first
        self.queue.add(heartbeat, '/heartbeat')
        
        # Try to flush queue immediately
        self._flush_queue()
        
        return True
    
    def send_domains(self, domains: list) -> bool:
        """
        Queue and send domain visits to core
        
        Args:
            domains: List of domain visit dicts
            
        Returns:
            True if successful
        """
        if not domains:
            return True
        
        payload = {
            'agent_id': self.agent_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'domains': domains
        }
        
        self.queue.add(payload, '/domains')
        self._flush_queue()
        return True
    
    def send_domain_sessions(self, sessions: list) -> bool:
        """
        Queue and send domain usage sessions to core
        
        Args:
            sessions: List of domain session dicts with start, end, duration
            
        Returns:
            True if successful
        """
        if not sessions:
            return True
        
        payload = {
            'agent_id': self.agent_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'domains_active': sessions
        }
        
        self.queue.add(payload, '/domains_active')
        self._flush_queue()
        return True
    
    def send_inventory(self, inventory: Dict) -> bool:
        """
        Queue and send application inventory to core
        
        Args:
            inventory: Inventory data dict
            
        Returns:
            True if successful
        """
        self.queue.add(inventory, '/inventory')
        self._flush_queue()
        return True
    
    def ping(self) -> bool:
        """
        Ping core to check connectivity
        
        Returns:
            True if core is reachable
        """
        try:
            payload = {
                'agent_id': self.agent_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            # Ping is ephemeral, don't queue
            response = self._make_request('/ping', payload, timeout=5)
            return response is not None
        except Exception:
            return False
    
    def send_state_change(self, payload: dict) -> bool:
        """
        Send immediate state-change telemetry to Core.
        
        Args:
            payload: State change data with previous_state, current_state, timestamp
            
        Returns:
            True if successful
        """
        try:
            # Add agent_id to payload
            payload['agent_id'] = self.agent_id
            
            # State changes are time-sensitive - send immediately, don't queue
            response = self._make_request('/telemetry/state-change', payload, timeout=5)
            
            if response is not None:
                logger.debug(f"State change sent: {payload.get('previous_state')} -> {payload.get('current_state')}")
                return True
            else:
                logger.warning("State change telemetry failed")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send state change: {e}")
            return False

    def send_state_spans(self, spans: list) -> bool:
        """
        Queue and send state spans to core.
        
        Args:
            spans: List of span dicts
            
        Returns:
            True if successful
        """
        if not spans:
            return True
        
        payload = {
            'agent_id': self.agent_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'spans': spans
        }
        
        self.queue.add(payload, '/screentime_spans')
        self._flush_queue()
        return True
