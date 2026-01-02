"""
Helper Persistence Module
Implements durable file-based queue for telemetry resilience.
"""
import json
import os
import uuid
import glob
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class PersistenceQueue:
    """
    Durable file-based queue for Helper telemetry.
    Ensures zero data loss if Core is unavailable.
    """
    
    def __init__(self, data_dir: Path, queue_name: str = "telemetry"):
        self.queue_dir = data_dir / "queue" / queue_name
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.max_size = 1000  # Max files to prevent disk filling
        
    def add(self, payload: Dict, endpoint: str) -> str:
        """
        Add item to queue.
        Returns the file path generated.
        """
        try:
            # Enforce max size (FIFO - delete oldest if full)
            self._enforce_limit()
            
            # Create unique filename with timestamp for sorting
            timestamp = int(time.time() * 1000)
            unique_id = str(uuid.uuid4())[:8]
            filename = f"{timestamp}_{unique_id}.json"
            file_path = self.queue_dir / filename
            
            item = {
                'endpoint': endpoint,
                'payload': payload,
                'created_at': timestamp
            }
            
            # Atomic write
            temp_path = file_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                json.dump(item, f)
            temp_path.replace(file_path)
            
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Failed to queue item: {e}")
            return ""
            
    def get_oldest(self, limit: int = 10) -> List[Tuple[Path, Dict]]:
        """
        Get oldest items from queue.
        Returns list of (file_path, item_dict).
        """
        items = []
        try:
            # Get all .json files sorted by name (timestamp)
            files = sorted(self.queue_dir.glob("*.json"))
            
            for file_path in files[:limit]:
                try:
                    with open(file_path, 'r') as f:
                        item = json.load(f)
                        items.append((file_path, item))
                except Exception as e:
                    logger.warning(f"Corrupt queue file {file_path}: {e}")
                    # Move to corrupt folder or delete? Delete for now.
                    try:
                        file_path.unlink()
                    except:
                        pass
                        
            return items
            
        except Exception as e:
            logger.error(f"Failed to read queue: {e}")
            return []
            
    def remove(self, file_path: Path):
        """Remove item from queue (Ack)"""
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logger.error(f"Failed to remove queued item {file_path}: {e}")
            
    def _enforce_limit(self):
        """Delete oldest files if limit reached"""
        try:
            files = sorted(self.queue_dir.glob("*.json"))
            if len(files) > self.max_size:
                excess = len(files) - self.max_size
                for i in range(excess):
                    try:
                        files[i].unlink()
                    except:
                        pass
                logger.warning(f"Queue limit reached, dropped {excess} old items")
        except Exception:
            pass
            
    def count(self) -> int:
        """Get number of items in queue"""
        return len(list(self.queue_dir.glob("*.json")))
