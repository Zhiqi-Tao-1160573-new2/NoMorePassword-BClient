"""
B-Client Sync Manager
Manages user activity history synchronization between C-clients
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from uuid import uuid4
from urllib.parse import urlparse

# Import logging system
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger


class SyncManager:
    """B-Client Sync Manager for user activity synchronization"""
    
    def __init__(self, websocket_client, node_manager, config_manager=None):
        """
        Initialize Sync Manager
        
        Args:
            websocket_client: WebSocket client instance for communication
            node_manager: NodeManager instance for connection management
            config_manager: ConfigManager instance for URL filtering configuration
        """
        self.websocket_client = websocket_client
        self.node_manager = node_manager
        self.config_manager = config_manager
        self.logger = get_bclient_logger('sync_manager')
        
        # Track pending batches for feedback
        self.pending_batches: Dict[str, Dict] = {}
        
        # Load URL filtering configuration
        self.url_filtering_config = self._load_url_filtering_config()
        
        self.logger.info("SyncManager initialized")
        self.logger.info(f"URL filtering enabled: {self.url_filtering_config.get('enabled', False)}")
        if self.url_filtering_config.get('enabled', False):
            self.logger.info(f"Allowed domains: {self.url_filtering_config.get('allowed_domains', [])}")
            self.logger.info(f"Allowed patterns: {self.url_filtering_config.get('allowed_patterns', [])}")
    
    def _load_url_filtering_config(self) -> Dict:
        """Load URL filtering configuration from config manager"""
        try:
            if self.config_manager:
                config = self.config_manager.get_config()
                return config.get('url_filtering', {
                    'enabled': False,
                    'allowed_domains': [],
                    'allowed_patterns': []
                })
            else:
                # Fallback configuration
                return {
                    'enabled': True,
                    'allowed_domains': [
                        'comp693nsnproject.pythonanywhere.com',
                        'localhost:5000',
                        '127.0.0.1:5000'
                    ],
                    'allowed_patterns': [
                        'https://comp693nsnproject.pythonanywhere.com/*',
                        'http://localhost:5000/*',
                        'http://127.0.0.1:5000/*'
                    ]
                }
        except Exception as e:
            self.logger.error(f"Error loading URL filtering config: {e}")
            return {'enabled': False, 'allowed_domains': [], 'allowed_patterns': []}
    
    def _filter_activities_by_url(self, activities: List[Dict]) -> List[Dict]:
        """
        Filter activities based on URL patterns
        
        Args:
            activities: List of activity dictionaries
            
        Returns:
            Filtered list of activities that match allowed URL patterns
        """
        if not self.url_filtering_config.get('enabled', False):
            self.logger.debug("URL filtering disabled, returning all activities")
            return activities
        
        allowed_domains = self.url_filtering_config.get('allowed_domains', [])
        allowed_patterns = self.url_filtering_config.get('allowed_patterns', [])
        
        filtered_activities = []
        filtered_count = 0
        
        self.logger.info(f"🔍 [URL Filter] Filtering {len(activities)} activities")
        self.logger.info(f"🔍 [URL Filter] Allowed domains: {allowed_domains}")
        self.logger.info(f"🔍 [URL Filter] Allowed patterns: {allowed_patterns}")
        
        for activity in activities:
            url = activity.get('url', '')
            if not url:
                self.logger.debug(f"🔍 [URL Filter] Activity has no URL, skipping: {activity.get('title', 'No title')}")
                continue
            
            # Check if URL matches any allowed domain or pattern
            is_allowed = False
            
            # Check domain matching
            try:
                parsed_url = urlparse(url)
                domain = parsed_url.netloc
                
                for allowed_domain in allowed_domains:
                    if domain == allowed_domain or domain.endswith('.' + allowed_domain):
                        is_allowed = True
                        self.logger.debug(f"🔍 [URL Filter] ✅ Domain match: {url} matches {allowed_domain}")
                        break
            except Exception as e:
                self.logger.debug(f"🔍 [URL Filter] Error parsing URL {url}: {e}")
            
            # Check pattern matching
            if not is_allowed:
                for pattern in allowed_patterns:
                    # Convert pattern to regex
                    regex_pattern = pattern.replace('*', '.*')
                    if re.match(regex_pattern, url):
                        is_allowed = True
                        self.logger.debug(f"🔍 [URL Filter] ✅ Pattern match: {url} matches {pattern}")
                        break
            
            if is_allowed:
                filtered_activities.append(activity)
                self.logger.debug(f"🔍 [URL Filter] ✅ Allowed: {url}")
            else:
                filtered_count += 1
                self.logger.debug(f"🔍 [URL Filter] ❌ Filtered out: {url}")
        
        self.logger.info(f"🔍 [URL Filter] Filtering result: {len(filtered_activities)}/{len(activities)} activities allowed")
        self.logger.info(f"🔍 [URL Filter] Filtered out {filtered_count} activities")
        
        return filtered_activities
    
    async def handle_user_activities_batch(self, websocket, batch_data: Dict) -> None:
        """
        Handle incoming user activities batch from C-client
        
        Args:
            websocket: Source WebSocket connection
            batch_data: Batch data containing activities
        """
        try:
            batch_id = batch_data.get('batch_id')
            user_id = batch_data.get('user_id')
            # Only support new data format: sync_data
            activities = batch_data.get('sync_data', [])
            batch_timestamp = batch_data.get('timestamp', 'N/A')
            
            self.logger.info(f"🔄 [SyncManager] ===== RECEIVED USER ACTIVITIES BATCH =====")
            self.logger.info(f"📦 [SyncManager] Batch ID: {batch_id}")
            self.logger.info(f"👤 [SyncManager] User ID: {user_id}")
            self.logger.info(f"📊 [SyncManager] Activities Count: {len(activities)}")
            self.logger.info(f"⏰ [SyncManager] Batch Timestamp: {batch_timestamp}")
            self.logger.info(f"🔗 [SyncManager] Source WebSocket: {id(websocket)}")
            
            # Log sample activities for debugging
            if activities:
                self.logger.info(f"📝 [SyncManager] Sample activities:")
                for i, activity in enumerate(activities[:3]):  # Show first 3 activities
                    self.logger.info(f"   Activity {i+1}: {activity.get('title', 'No title')} - {activity.get('url', 'No URL')}")
                if len(activities) > 3:
                    self.logger.info(f"   ... and {len(activities) - 3} more activities")
            
            # Apply URL filtering before forwarding
            self.logger.info(f"🔍 [SyncManager] ===== APPLYING URL FILTERING =====")
            filtered_activities = self._filter_activities_by_url(activities)
            
            if not filtered_activities:
                self.logger.info(f"🔍 [SyncManager] ===== NO ACTIVITIES PASSED FILTER =====")
                self.logger.info(f"🔍 [SyncManager] All {len(activities)} activities were filtered out")
                self.logger.info(f"🔍 [SyncManager] Skipping batch forwarding")
                
                # Send feedback to sender about filtering
                await self._send_batch_feedback(websocket, batch_id, True, f"Batch received but {len(activities)} activities filtered out by URL filter")
                return
            
            # Update batch data with filtered activities
            batch_data['sync_data'] = filtered_activities
            self.logger.info(f"🔍 [SyncManager] ===== URL FILTERING COMPLETED =====")
            self.logger.info(f"🔍 [SyncManager] Original activities: {len(activities)}")
            self.logger.info(f"🔍 [SyncManager] Filtered activities: {len(filtered_activities)}")
            self.logger.info(f"🔍 [SyncManager] Activities filtered out: {len(activities) - len(filtered_activities)}")
            
            # Store batch info for feedback tracking
            self.pending_batches[batch_id] = {
                'source_websocket': websocket,
                'user_id': user_id,
                'batch_data': batch_data,
                'timestamp': datetime.utcnow(),
                'forwarded_count': 0,
                'feedback_received': 0
            }
            
            self.logger.info(f"💾 [SyncManager] Stored batch {batch_id} in pending_batches")
            self.logger.info(f"📊 [SyncManager] Total pending batches: {len(self.pending_batches)}")
            
            # Start async operations without waiting
            self.logger.info(f"🚀 [SyncManager] Starting forward process to channel nodes...")
            forward_task = asyncio.create_task(self._forward_to_channel_nodes(user_id, batch_data))
            
            # Send initial feedback to sender asynchronously (don't wait)
            self.logger.info(f"📤 [SyncManager] Sending initial feedback to sender...")
            feedback_task = asyncio.create_task(
                self._send_batch_feedback(websocket, batch_id, True, "Batch received and forwarded")
            )
            
            # Wait for forward operation to complete (but don't block feedback)
            await forward_task
            
            self.logger.info(f"✅ [SyncManager] ===== BATCH PROCESSING COMPLETED =====")
            
        except Exception as e:
            self.logger.error(f"❌ [SyncManager] Error handling user activities batch: {e}")
            # Send error feedback
            await self._send_batch_feedback(websocket, batch_id, False, str(e))
    
    async def handle_batch_feedback(self, websocket, feedback_data: Dict) -> None:
        """
        Handle feedback from C-client about batch processing
        
        Args:
            websocket: Source WebSocket connection
            feedback_data: Feedback data
        """
        try:
            batch_id = feedback_data.get('batch_id')
            success = feedback_data.get('success', False)
            message = feedback_data.get('message', '')
            timestamp = feedback_data.get('timestamp', 'N/A')
            
            self.logger.info(f"📨 [SyncManager] ===== RECEIVED BATCH FEEDBACK =====")
            self.logger.info(f"📦 [SyncManager] Batch ID: {batch_id}")
            self.logger.info(f"✅ [SyncManager] Success: {success}")
            self.logger.info(f"💬 [SyncManager] Message: {message}")
            self.logger.info(f"⏰ [SyncManager] Timestamp: {timestamp}")
            self.logger.info(f"🔗 [SyncManager] Source WebSocket: {id(websocket)}")
            
            if batch_id in self.pending_batches:
                batch_info = self.pending_batches[batch_id]
                batch_info['feedback_received'] += 1
                
                # Check if all expected feedback has been received
                expected_feedback = batch_info['forwarded_count']
                received_feedback = batch_info['feedback_received']
                user_id = batch_info.get('user_id', 'unknown')
                
                self.logger.info(f"📊 [SyncManager] ===== FEEDBACK PROGRESS =====")
                self.logger.info(f"📦 [SyncManager] Batch: {batch_id}")
                self.logger.info(f"👤 [SyncManager] User: {user_id}")
                self.logger.info(f"📈 [SyncManager] Progress: {received_feedback}/{expected_feedback} feedback received")
                self.logger.info(f"⏱️ [SyncManager] Processing time: {datetime.utcnow() - batch_info['timestamp']}")
                
                # Log individual feedback status
                status_icon = "✅" if success else "❌"
                self.logger.info(f"{status_icon} [SyncManager] Node feedback: {message}")
                
                # Clean up if all feedback received
                if received_feedback >= expected_feedback:
                    self.logger.info(f"🎉 [SyncManager] ===== BATCH COMPLETED =====")
                    self.logger.info(f"📦 [SyncManager] Batch ID: {batch_id}")
                    self.logger.info(f"👤 [SyncManager] User ID: {user_id}")
                    self.logger.info(f"✅ [SyncManager] Total successful feedback: {received_feedback}")
                    self.logger.info(f"⏱️ [SyncManager] Total processing time: {datetime.utcnow() - batch_info['timestamp']}")
                    
                    del self.pending_batches[batch_id]
                    self.logger.info(f"🧹 [SyncManager] Cleaned up completed batch {batch_id}")
                    self.logger.info(f"📊 [SyncManager] Remaining pending batches: {len(self.pending_batches)}")
                else:
                    remaining = expected_feedback - received_feedback
                    self.logger.info(f"⏳ [SyncManager] Waiting for {remaining} more feedback responses...")
            else:
                self.logger.warning(f"⚠️ [SyncManager] Received feedback for unknown batch: {batch_id}")
                self.logger.warning(f"📊 [SyncManager] Current pending batches: {list(self.pending_batches.keys())}")
            
        except Exception as e:
            self.logger.error(f"❌ [SyncManager] Error handling batch feedback: {e}")
    
    async def _forward_to_channel_nodes(self, user_id: str, batch_data: Dict) -> None:
        """
        Forward batch data to all nodes in the same channel
        
        Args:
            user_id: User ID to find channel nodes
            batch_data: Batch data to forward
        """
        try:
            batch_id = batch_data.get('batch_id')
            
            self.logger.info(f"🔍 [SyncManager] ===== FINDING USER CONNECTION =====")
            self.logger.info(f"👤 [SyncManager] Searching for user: {user_id}")
            
            # Find the user's connection to get channel information
            user_connection = None
            for domain_id, connections in self.node_manager.domain_pool.items():
                self.logger.debug(f"🔍 [SyncManager] Checking domain {domain_id} with {len(connections)} connections")
                for conn in connections:
                    if conn.user_id == user_id:
                        user_connection = conn
                        self.logger.info(f"✅ [SyncManager] Found user connection in domain {domain_id}")
                        self.logger.info(f"📊 [SyncManager] Connection details: node_id={conn.node_id}, channel_id={conn.channel_id}")
                        break
                if user_connection:
                    break
            
            if not user_connection:
                self.logger.warning(f"⚠️ [SyncManager] No connection found for user {user_id}")
                return
            
            channel_id = user_connection.channel_id
            if not channel_id:
                self.logger.warning(f"⚠️ [SyncManager] No channel_id found for user {user_id}")
                return
            
            self.logger.info(f"🎯 [SyncManager] Target channel: {channel_id}")
            
            # Get all connections in the same channel
            channel_connections = self.node_manager.channel_pool.get(channel_id, [])
            
            self.logger.info(f"📡 [SyncManager] ===== CHANNEL NODES DISCOVERY =====")
            self.logger.info(f"🎯 [SyncManager] Channel {channel_id} has {len(channel_connections)} total connections")
            
            # Log all connections in the channel
            for i, conn in enumerate(channel_connections):
                is_sender = conn.user_id == user_id
                self.logger.info(f"   Node {i+1}: user_id={conn.user_id}, node_id={conn.node_id} {'(SENDER - will skip)' if is_sender else ''}")
            
            # Forward to all nodes in the channel (excluding the sender)
            self.logger.info(f"🚀 [SyncManager] ===== STARTING FORWARD PROCESS =====")
            forwarded_count = 0
            failed_count = 0
            
            for i, conn in enumerate(channel_connections):
                if conn.user_id != user_id and conn.websocket:  # Exclude sender
                    self.logger.info(f"📤 [SyncManager] Forwarding to node {i+1}: {conn.user_id} (node_id: {conn.node_id})")
                    try:
                        # Directly forward batch_data (already in new format)
                        await self._send_to_node(conn.websocket, batch_data)
                        forwarded_count += 1
                        self.logger.info(f"✅ [SyncManager] Successfully forwarded to node {conn.user_id}")
                    except Exception as e:
                        failed_count += 1
                        self.logger.error(f"❌ [SyncManager] Failed to forward to node {conn.node_id}: {e}")
                elif conn.user_id == user_id:
                    self.logger.info(f"⏭️ [SyncManager] Skipping sender node: {conn.user_id}")
                elif not conn.websocket:
                    self.logger.warning(f"⚠️ [SyncManager] Node {conn.user_id} has no WebSocket connection")
            
            # Update pending batch info
            if batch_id in self.pending_batches:
                self.pending_batches[batch_id]['forwarded_count'] = forwarded_count
            
            self.logger.info(f"📊 [SyncManager] ===== FORWARD SUMMARY =====")
            self.logger.info(f"✅ [SyncManager] Successfully forwarded to: {forwarded_count} nodes")
            self.logger.info(f"❌ [SyncManager] Failed to forward to: {failed_count} nodes")
            self.logger.info(f"⏭️ [SyncManager] Sender excluded: 1 node")
            self.logger.info(f"📦 [SyncManager] Batch ID: {batch_id}")
            
        except Exception as e:
            self.logger.error(f"❌ [SyncManager] Error forwarding to channel nodes: {e}")
    
    async def _send_to_node(self, websocket, batch_data: Dict) -> None:
        """
        Send batch data to a specific node
        
        Args:
            websocket: Target WebSocket connection
            batch_data: Batch data to send (format: {user_id, batch_id, sync_data: [activities]})
        """
        try:
            batch_id = batch_data.get('batch_id')
            user_id = batch_data.get('user_id')
            sync_data = batch_data.get('sync_data', [])
            activities_count = len(sync_data)
            
            self.logger.info(f"📤 [SyncManager] Preparing to send batch {batch_id} to node")
            self.logger.info(f"📊 [SyncManager] Batch contains {activities_count} activities for user {user_id}")
            self.logger.info(f"📋 [SyncManager] Sync data type: {type(sync_data)}")
            self.logger.info(f"📋 [SyncManager] Sync data length: {len(sync_data) if sync_data else 0}")
            
            # Keep same format when forwarding: {user_id, batch_id, sync_data: [activities]}
            forward_data = {
                'user_id': user_id,
                'batch_id': batch_id,
                'sync_data': sync_data
            }
            
            self.logger.info(f"📤 [SyncManager] Forward data created: {forward_data.keys()}")
            self.logger.info(f"📤 [SyncManager] Forward sync_data length: {len(forward_data.get('sync_data', []))}")
            
            message = {
                'type': 'user_activities_batch_forward',
                'data': forward_data
            }
            
            # Log message size for performance monitoring
            message_str = json.dumps(message)
            message_size = len(message_str.encode('utf-8'))
            self.logger.debug(f"📏 [SyncManager] Message size: {message_size} bytes")
            
            await websocket.send(message_str)
            self.logger.debug(f"✅ [SyncManager] Successfully sent batch {batch_id} to node (WebSocket ID: {id(websocket)})")
            
        except Exception as e:
            batch_id = batch_data.get('batch_id', 'unknown')
            self.logger.error(f"❌ [SyncManager] Error sending batch {batch_id} to node: {e}")
            self.logger.error(f"🔗 [SyncManager] WebSocket ID: {id(websocket)}")
            raise
    
    async def _send_batch_feedback(self, websocket, batch_id: str, success: bool, message: str) -> None:
        """
        Send feedback to C-client about batch processing
        
        Args:
            websocket: Target WebSocket connection
            batch_id: Batch ID
            success: Success status
            message: Feedback message
        """
        try:
            status_icon = "✅" if success else "❌"
            self.logger.info(f"📤 [SyncManager] ===== SENDING BATCH FEEDBACK =====")
            self.logger.info(f"📦 [SyncManager] Batch ID: {batch_id}")
            self.logger.info(f"{status_icon} [SyncManager] Success: {success}")
            self.logger.info(f"💬 [SyncManager] Message: {message}")
            self.logger.info(f"🔗 [SyncManager] Target WebSocket: {id(websocket)}")
            
            feedback_message = {
                'type': 'user_activities_batch_feedback',
                'data': {
                    'batch_id': batch_id,
                    'success': success,
                    'message': message,
                    'timestamp': datetime.utcnow().isoformat()
                }
            }
            
            # Log message size for performance monitoring
            message_str = json.dumps(feedback_message)
            message_size = len(message_str.encode('utf-8'))
            self.logger.debug(f"📏 [SyncManager] Feedback message size: {message_size} bytes")
            
            await websocket.send(message_str)
            self.logger.info(f"✅ [SyncManager] Successfully sent feedback for batch {batch_id}")
            self.logger.info(f"📤 [SyncManager] ===== FEEDBACK SENT =====")
            
        except Exception as e:
            self.logger.error(f"❌ [SyncManager] Error sending batch feedback: {e}")
            self.logger.error(f"📦 [SyncManager] Batch ID: {batch_id}")
            self.logger.error(f"🔗 [SyncManager] WebSocket ID: {id(websocket)}")
    
    def get_sync_stats(self) -> Dict:
        """
        Get synchronization statistics
        
        Returns:
            Dictionary with sync statistics
        """
        self.logger.info(f"📊 [SyncManager] ===== SYNC STATISTICS =====")
        
        stats = {
            'pending_batches': len(self.pending_batches),
            'batch_details': []
        }
        
        if self.pending_batches:
            self.logger.info(f"📦 [SyncManager] Currently tracking {len(self.pending_batches)} pending batches:")
            
            for batch_id, batch_info in self.pending_batches.items():
                batch_detail = {
                    'batch_id': batch_id,
                    'user_id': batch_info['user_id'],
                    'forwarded_count': batch_info['forwarded_count'],
                    'feedback_received': batch_info['feedback_received'],
                    'timestamp': batch_info['timestamp'].isoformat(),
                    'processing_time': str(datetime.utcnow() - batch_info['timestamp'])
                }
                stats['batch_details'].append(batch_detail)
                
                # Log individual batch status
                progress = f"{batch_info['feedback_received']}/{batch_info['forwarded_count']}"
                self.logger.info(f"   📦 {batch_id[:8]}... | User: {batch_info['user_id'][:8]}... | Progress: {progress} | Time: {batch_detail['processing_time']}")
        else:
            self.logger.info(f"✅ [SyncManager] No pending batches - all sync operations completed")
        
        self.logger.info(f"📊 [SyncManager] ===== END SYNC STATISTICS =====")
        return stats
    
    def cleanup_old_batches(self, max_age_hours: int = 24) -> None:
        """
        Clean up old pending batches
        
        Args:
            max_age_hours: Maximum age in hours before cleanup
        """
        
        self.logger.info(f"🧹 [SyncManager] ===== CLEANING UP OLD BATCHES =====")
        self.logger.info(f"⏰ [SyncManager] Max age threshold: {max_age_hours} hours")
        
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        old_batches = []
        
        self.logger.info(f"🔍 [SyncManager] Checking {len(self.pending_batches)} pending batches for age...")
        
        for batch_id, batch_info in self.pending_batches.items():
            batch_age = datetime.utcnow() - batch_info['timestamp']
            age_hours = batch_age.total_seconds() / 3600
            
            if batch_info['timestamp'] < cutoff_time:
                old_batches.append(batch_id)
                self.logger.info(f"⏰ [SyncManager] Old batch found: {batch_id[:8]}... (age: {age_hours:.1f} hours)")
            else:
                self.logger.debug(f"✅ [SyncManager] Batch still fresh: {batch_id[:8]}... (age: {age_hours:.1f} hours)")
        
        if old_batches:
            self.logger.info(f"🗑️ [SyncManager] Cleaning up {len(old_batches)} old batches...")
            for batch_id in old_batches:
                batch_info = self.pending_batches[batch_id]
                user_id = batch_info.get('user_id', 'unknown')
                batch_age = datetime.utcnow() - batch_info['timestamp']
                
                del self.pending_batches[batch_id]
                self.logger.info(f"🗑️ [SyncManager] Cleaned up batch: {batch_id[:8]}... | User: {user_id[:8]}... | Age: {batch_age}")
            
            self.logger.info(f"✅ [SyncManager] Cleanup completed: {len(old_batches)} batches removed")
            self.logger.info(f"📊 [SyncManager] Remaining pending batches: {len(self.pending_batches)}")
        else:
            self.logger.info(f"✅ [SyncManager] No old batches found - all batches are within age limit")
        
        self.logger.info(f"🧹 [SyncManager] ===== CLEANUP COMPLETED =====")
