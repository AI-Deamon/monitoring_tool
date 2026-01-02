"""
Helper Identity Sync Module
Ensures Helper always has the same agent_id and local_agent_key as Core
"""
import json
import urllib.request
import urllib.error
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class IdentitySynchronizer:
    """Handles Helper identity synchronization with Core"""
    
    def __init__(self, config):
        self.config = config
        self.identity_cache_path = config.data_dir / 'identity.json'
    
    def sync_from_core(self) -> bool:
        """Sync agent_id and local_agent_key from Core via /identity endpoint
        
        Returns:
            True if sync successful, False otherwise
        """
        try:
            url = f"http://{self.config.core_host}:{self.config.core_port}/identity"
            logger.info(f"[SYNC] Requesting identity from Core: {url}")
            
            response = urllib.request.urlopen(url, timeout=5)
            identity = json.loads(response.read().decode('utf-8'))
            
            old_agent_id = self.config.agent_id
            old_key = self.config.local_agent_key
            
            # Update from Core
            self.config.agent_id = identity['agent_id']
            self.config.local_agent_key = identity['local_agent_key']
            
            # NOTE: Do NOT call self.config.save_config()
            # Helper should NEVER write to C:\ProgramData\SentinelEdge\config.json
            # Only Core manages that file. Helper writes to identity cache only.
            
            # Save to identity cache (in user's AppData)
            self._save_identity_cache(identity)
            
            # Cleanup if ID changed
            if old_agent_id and old_agent_id != identity['agent_id']:
                logger.warning(f"[SYNC] Agent ID changed: {old_agent_id[:16]}... → {identity['agent_id'][:16]}...")
                self._cleanup_old_state()
            
            logger.info(f"[SYNC] Identity synced with Core - Agent ID: {identity['agent_id'][:16]}...")
            return True
            
        except urllib.error.HTTPError as e:
            logger.error(f"[SYNC] HTTP error getting identity: {e.code} {e.reason}")
            return False
        except urllib.error.URLError as e:
            logger.error(f"[SYNC] Failed to reach Core: {e.reason}")
            return False
        except Exception as e:
            logger.error(f"[SYNC] Failed to sync identity: {e}")
            return False
    
    def load_cached_identity(self) -> bool:
        """Load identity from cache file if available
        
        Returns:
            True if loaded from cache, False otherwise
        """
        try:
            if self.identity_cache_path.exists():
                with open(self.identity_cache_path, 'r') as f:
                    identity = json.load(f)
                
                self.config.agent_id = identity.get('agent_id', 'pending')
                self.config.local_agent_key = identity.get('local_agent_key', 'pending')
                
                logger.info(f"[SYNC] Loaded cached identity: {self.config.agent_id[:16]}...")
                return True
            else:
                logger.debug("[SYNC] No identity cache found")
                return False
        except Exception as e:
            logger.error(f"[SYNC] Failed to load cached identity: {e}")
            return False
    
    def _save_identity_cache(self, identity: dict):
        """Save identity to cache file for faster startup"""
        try:
            self.identity_cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.identity_cache_path, 'w') as f:
                json.dump(identity, f, indent=2)
            logger.debug("[SYNC] Saved identity cache")
        except Exception as e:
            logger.warning(f"[SYNC] Failed to save identity cache: {e}")
    
    def _cleanup_old_state(self):
        """Delete old state files after agent_id change"""
        try:
            state_file = self.config.data_dir / 'helper_state.json'
            if state_file.exists():
                state_file.unlink()
                logger.info("[SYNC] Deleted old helper_state.json")
        except Exception as e:
            logger.warning(f"[SYNC] Failed to cleanup old state: {e}")
    
    def ensure_synced(self) -> bool:
        """Ensure Helper has valid identity
        
        Returns:
            True if identity is valid, False otherwise
        """
        # If pending, try to sync
        if self.config.agent_id == 'pending' or not self.config.agent_id:
            logger.warning("[SYNC] Agent ID is pending, syncing from Core...")
            return self.sync_from_core()
        
        if self.config.local_agent_key == 'pending' or not self.config.local_agent_key:
            logger.warning("[SYNC] Local agent key is pending, syncing from Core...")
            return self.sync_from_core()
        
        # Identity looks valid
        return True
