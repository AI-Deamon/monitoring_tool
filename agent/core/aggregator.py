"""
Aggregator Module
Merges heartbeats into sessionized events
"""
from datetime import datetime, timezone, timedelta
from typing import List, Dict
import logging

from .buffer import BufferDB

logger = logging.getLogger(__name__)

class HeartbeatAggregator:
    """Aggregates heartbeats into merged events - Config-driven"""
    
    def __init__(self, buffer: BufferDB, config=None):
        self.buffer = buffer
        self.enabled = True  # Can be toggled via config
        self.logger = logging.getLogger('HeartbeatAggregator')
        
        if config:
            self.apply_config(config)
    
    def apply_config(self, config):
        """Apply configuration changes dynamically"""
        core_config = config.config.get("core", {})
        old_enabled = self.enabled
        self.enabled = core_config.get("enable_aggregator", True)
        
        if old_enabled != self.enabled:
            status = "enabled" if self.enabled else "disabled"
            self.logger.info(f"[CONFIG] Aggregator {status}")
        
    def process_heartbeats(self):
        """
        Process unprocessed heartbeats and create merged events with sequence validation
        """
        # Check if aggregator is enabled
        if not self.enabled:
            return
        
        try:
            # Get unprocessed heartbeats
            heartbeats = self.buffer.get_unprocessed_heartbeats(limit=1000)
            
            if not heartbeats:
                return
            
            logger.info(f"Processing {len(heartbeats)} heartbeats...")
            
            # Fix #7: Detect sequence gaps
            sequences = [h['data'].get('sequence', 0) for h in heartbeats]
            if sequences:
                sequences_sorted = sorted(sequences)
                for i in range(1, len(sequences_sorted)):
                    gap = sequences_sorted[i] - sequences_sorted[i-1]
                    if gap > 1:
                        logger.warning(
                            f"AGGREGATOR: Sequence gap detected: "
                            f"{sequences_sorted[i-1]} -> {sequences_sorted[i]} "
                            f"(missing {gap-1} heartbeats)"
                        )
            
            # Group by agent_id
            by_agent = {}
            for hb in heartbeats:
                agent_id = hb['data'].get('agent_id')
                if agent_id not in by_agent:
                    by_agent[agent_id] = []
                by_agent[agent_id].append(hb)
            
            # Process each agent's heartbeats
            processed_ids = []
            for agent_id, agent_heartbeats in by_agent.items():
                # Sort by sequence
                agent_heartbeats.sort(key=lambda x: x['data'].get('sequence', 0))
                
                # Process screentime data (state-change events come from helper)
                self._process_screentime(agent_id, agent_heartbeats)
                
                # Merge app sessions (still needed for app usage tracking)
                self._merge_app_sessions(agent_id, agent_heartbeats)
                
                # Mark as processed
                processed_ids.extend([hb['id'] for hb in agent_heartbeats])
            
            # Mark heartbeats as processed
            self.buffer.mark_heartbeats_processed(processed_ids)
            
            logger.info(f"[OK] Processed {len(processed_ids)} heartbeats")
            
        except Exception as e:
            logger.error(f"Aggregation error: {e}", exc_info=True)
    
    # ❌ REMOVED: _merge_idle_states() method was deleted in Bug #4 fix.
    # State changes now come directly from Helper via /telemetry/state-change endpoint.
    # The aggregator was creating duplicate screen-* events that corrupted server data.
    # DO NOT RE-ADD THIS METHOD.
    
    def _process_screentime(self, agent_id: str, heartbeats: List[Dict]):
        """
        Process cumulative screentime from heartbeats.
        
        CRITICAL: Helper sends CUMULATIVE totals (10, 20, 30, 40, 50, 60).
        We must take the LATEST value (60), NOT sum them (210).
        
        The server uses GREATEST() to handle cumulative daily totals.
        """
        if not heartbeats:
            return
        
        # Take LATEST cumulative values from the batch
        # (Helper sends cumulative totals, not incremental deltas)
        latest_hb = heartbeats[-1]
        hb = latest_hb['data']
        screentime = hb.get('screentime', {})
        
        # Extract cumulative totals from latest heartbeat
        cumulative_active = screentime.get('delta_active_seconds', 0)
        cumulative_idle = screentime.get('delta_idle_seconds', 0)
        cumulative_locked = screentime.get('delta_locked_seconds', 0)
        
        # Get metadata from latest heartbeat
        latest_timestamp = hb.get('timestamp')
        username = hb.get('username', 'unknown')
        
        # FIX: Prioritize system_state (from StateDetector) over idle.state
        system_state = hb.get('system_state')
        idle_state = hb.get('idle', {}).get('state', 'active')
        current_state = system_state if system_state else idle_state
        
        # Only store if there's actual time to report
        if cumulative_active == 0 and cumulative_idle == 0 and cumulative_locked == 0:
            return
        
        # Create event for uploader with CUMULATIVE values
        # Server will use GREATEST() to ensure monotonic updates
        event = {
            'agent_id': agent_id,
            'username': username,
            'type': 'screentime',
            'timestamp': latest_timestamp,
            'delta_active_seconds': cumulative_active,
            'delta_idle_seconds': cumulative_idle,
            'delta_locked_seconds': cumulative_locked,
            'current_state': current_state
        }
        
        self.buffer.store_merged_event(event)
    
    def _merge_app_sessions(self, agent_id: str, heartbeats: List[Dict]):
        """Merge app foreground sessions into events"""
        if not heartbeats:
            return
        
        current_app = None
        current_start = None
        current_username = None
        current_title = None
        
        for hb_record in heartbeats:
            hb = hb_record['data']
            app_data = hb.get('app', {})
            app_name = app_data.get('current')
            title = app_data.get('current_title')
            timestamp = hb.get('timestamp')
            username = hb.get('username', 'unknown')
            
            # Skip if app is None (user was idle/locked)
            if not app_name or app_name == 'None' or app_name == 'null':
                # User was idle - end current app session if exists
                if current_app and current_start:
                    try:
                        ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    except:
                        continue
                        
                    duration = (ts - current_start).total_seconds()
                    if duration > 0:
                        event = {
                            'agent_id': agent_id,
                            'username': current_username,
                            'type': 'app',
                            'start': current_start.isoformat(),
                            'end': ts.isoformat(),
                            'duration_seconds': duration,
                            'state': {
                                'app_name': current_app,
                                'window_title': current_title
                            },
                            'heartbeat_count': 1
                        }
                        self.buffer.store_merged_event(event)
                    
                    # Reset current session
                    current_app = None
                    current_start = None
                continue  # Skip to next heartbeat
            
            if not timestamp:
                continue
            
            # Parse timestamp
            try:
                ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except:
                continue
            
            # If app changed, save previous and start new
            if app_name != current_app:
                # Save previous app if exists
                if current_app and current_start:
                    duration = (ts - current_start).total_seconds()
                    if duration > 0:
                        event = {
                            'agent_id': agent_id,
                            'username': current_username,
                            'type': 'app',
                            'start': current_start.isoformat(),
                            'end': ts.isoformat(),
                            'duration_seconds': duration,
                            'state': {
                                'app_name': current_app,
                                'window_title': current_title
                            },
                            'heartbeat_count': 1
                        }
                        self.buffer.store_merged_event(event)
                
                # Start new app
                current_app = app_name
                current_start = ts
                current_username = username
                current_title = title
        
        # Save final app
        if current_app and current_start:
            end_time = datetime.now(timezone.utc)
            duration = (end_time - current_start).total_seconds()
            if duration > 0:
                event = {
                    'agent_id': agent_id,
                    'username': current_username,
                    'type': 'app',
                    'start': current_start.isoformat(),
                    'end': end_time.isoformat(),
                    'duration_seconds': duration,
                    'state': {
                        'app_name': current_app,
                        'window_title': current_title
                    },
                    'heartbeat_count': 1
                }
                self.buffer.store_merged_event(event)
