"""
C-Client WebSocket Client Service
Handles WebSocket communication with C-Client
"""

# Standard library imports
import asyncio
import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime

# Third-party imports
try:
    import websockets
except ImportError:
    # WebSocket dependencies not available - will be handled by logger when available
    websockets = None

# Local application imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger
from utils.config_manager import get_nsn_url

# Service imports
from .cluster_verification import verify_user_cluster, ClusterVerificationService, get_cluster_verification_service
from .nodeManager import ClientConnection

# These will be injected when initialized
app = None
db = None
UserCookie = None
UserAccount = None
send_session_to_client = None
sync_manager = None


def init_websocket_client(flask_app, database=None, user_cookie_model=None, user_account_model=None, send_session_func=None):
    """Initialize WebSocket client with Flask app and database models"""
    global app, db, UserCookie, UserAccount, send_session_to_client
    app = flask_app
    if database:
        db = database
    if user_cookie_model:
        UserCookie = user_cookie_model
    if user_account_model:
        UserAccount = user_account_model
    if send_session_func:
        send_session_to_client = send_session_func


class CClientWebSocketClient:
    def __init__(self):
        # Initialize logging system
        self.logger = get_bclient_logger('websocket')
        
        self.websocket = None
        self.client_id = f"b-client-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.is_connected = False
        self.config = self.load_websocket_config()
        self.reconnect_interval = self.config.get('reconnect_interval', 30)
        
        # Initialize cluster verification service reference
        self.cluster_verification_service = None
        # Store cluster verification instances per connection
        self.connection_cluster_verification = {}
        
        # Initialize dual connection pools for C-Client connections with pre-allocation
        self.node_connections = {}     # Node-based connection pool (node_id -> websocket)
        self.user_connections = {}    # User-based connection pool (user_id -> list of websockets)
        self.client_connections = {}  # Client-based connection pool (client_id -> list of websockets)
    
    def _init_cluster_verification_for_connection(self, websocket, user_id, node_id, channel_id):
        """Initialize cluster verification instance for a specific C-Client connection"""
        try:
            # Create a unique connection identifier
            connection_id = id(websocket)
            
            # Initialize cluster verification instance for this connection
            cluster_verification_instance = ClusterVerificationService(self, db)
            
            # Store the instance for this connection
            self.connection_cluster_verification[connection_id] = cluster_verification_instance
            
            # Set the instance on the websocket object for easy access
            websocket.cluster_verification_instance = cluster_verification_instance
            
            self.logger.info(f"===== CLUSTER VERIFICATION INSTANCE INITIALIZED =====")
            self.logger.info(f"Connection ID: {connection_id}")
            self.logger.info(f"User ID: {user_id}")
            self.logger.info(f"Node ID: {node_id}")
            self.logger.info(f"Channel ID: {channel_id}")
            self.logger.info(f"Instance: {cluster_verification_instance}")
            self.logger.info(f"===== END CLUSTER VERIFICATION INITIALIZATION =====")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize cluster verification for connection: {e}")
            self.logger.error(f"User ID: {user_id}, Node ID: {node_id}, Channel ID: {channel_id}")
            # Set a None instance to avoid errors
            websocket.cluster_verification_instance = None
    
    def _cleanup_cluster_verification_for_connection(self, websocket):
        """Clean up cluster verification instance for a specific C-Client connection"""
        try:
            connection_id = id(websocket)
            
            if connection_id in self.connection_cluster_verification:
                # Remove the instance from our tracking
                del self.connection_cluster_verification[connection_id]
                self.logger.info(f"===== CLUSTER VERIFICATION INSTANCE CLEANED UP =====")
                self.logger.info(f"Connection ID: {connection_id}")
                self.logger.info(f"===== END CLUSTER VERIFICATION CLEANUP =====")
            else:
                self.logger.debug(f"No cluster verification instance found for connection {connection_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup cluster verification for connection: {e}")
            self.logger.error(f"Connection ID: {id(websocket)}")
    
    async def _sync_connection_to_nodemanager(self, websocket, connection_data):
        """Sync WebSocket connection to NodeManager with comprehensive error handling"""
        try:
            self.logger.info(f"🔗 ===== SYNCING CONNECTION TO NODEMANAGER =====")
            self.logger.info(f"🔗 WebSocket: {websocket}")
            self.logger.info(f"🔗 Connection data: {connection_data}")
            
            # Check if NodeManager is available
            if not hasattr(self, 'node_manager') or not self.node_manager:
                self.logger.error(f"🔗 ❌ NodeManager not available for connection sync")
                return False
            
            # Prepare NMP parameters for NodeManager
            nmp_params = {
                'nmp_user_id': connection_data.get('user_id'),
                'nmp_username': connection_data.get('username'),
                'nmp_node_id': connection_data.get('node_id'),
                'nmp_domain_main_node_id': connection_data.get('domain_main_node_id'),
                'nmp_cluster_main_node_id': connection_data.get('cluster_main_node_id'),
                'nmp_channel_main_node_id': connection_data.get('channel_main_node_id'),
                'nmp_domain_id': connection_data.get('domain_id'),
                'nmp_cluster_id': connection_data.get('cluster_id'),
                'nmp_channel_id': connection_data.get('channel_id')
            }
            
            self.logger.info(f"🔗 NMP parameters for NodeManager sync:")
            for key, value in nmp_params.items():
                self.logger.info(f"🔗   {key}: {value}")
            
            # Call NodeManager's handle_new_connection method
            self.logger.info(f"🔗 Calling NodeManager.handle_new_connection()...")
            connection = await self.node_manager.handle_new_connection(websocket, nmp_params)
            
            if connection:
                self.logger.info(f"🔗 ✅ NodeManager connection sync successful")
                self.logger.info(f"🔗 NodeManager connection: {connection}")
                self.logger.info(f"🔗 Node ID: {connection.node_id}")
                self.logger.info(f"🔗 Domain ID: {connection.domain_id}")
                self.logger.info(f"🔗 Cluster ID: {connection.cluster_id}")
                self.logger.info(f"🔗 Channel ID: {connection.channel_id}")
                
                # Store the NodeManager connection reference on the websocket
                websocket.nodemanager_connection = connection
                self.logger.info(f"🔗 ✅ NodeManager connection reference stored on websocket")
                
                return True
            else:
                self.logger.error(f"🔗 ❌ NodeManager.handle_new_connection() returned None")
                return False
                
        except Exception as e:
            self.logger.error(f"🔗 ❌ Error syncing connection to NodeManager: {e}")
            self.logger.error(f"🔗 ❌ Traceback: {traceback.format_exc()}")
            return False
        finally:
            self.logger.info(f"🔗 ===== END NODEMANAGER SYNC =====")
    
    async def _sync_disconnection_to_nodemanager(self, websocket):
        """Sync WebSocket disconnection to NodeManager with comprehensive error handling"""
        try:
            self.logger.info(f"🔗 ===== SYNCING DISCONNECTION TO NODEMANAGER =====")
            self.logger.info(f"🔗 WebSocket: {websocket}")
            
            # Check if NodeManager is available
            if not hasattr(self, 'node_manager') or not self.node_manager:
                self.logger.warning(f"🔗 ⚠️ NodeManager not available for disconnection sync")
                return False
            
            # Get NodeManager connection reference from websocket
            nodemanager_connection = getattr(websocket, 'nodemanager_connection', None)
            
            if nodemanager_connection:
                self.logger.info(f"🔗 Found NodeManager connection reference: {nodemanager_connection}")
                self.logger.info(f"🔗 Node ID: {nodemanager_connection.node_id}")
                self.logger.info(f"🔗 Domain ID: {nodemanager_connection.domain_id}")
                self.logger.info(f"🔗 Cluster ID: {nodemanager_connection.cluster_id}")
                self.logger.info(f"🔗 Channel ID: {nodemanager_connection.channel_id}")
                
                # Call NodeManager's remove_connection method
                self.logger.info(f"🔗 Calling NodeManager.remove_connection()...")
                self.node_manager.remove_connection(nodemanager_connection)
                
                # Clear the reference
                websocket.nodemanager_connection = None
                self.logger.info(f"🔗 ✅ NodeManager disconnection sync successful")
                return True
            else:
                self.logger.warning(f"🔗 ⚠️ No NodeManager connection reference found on websocket")
                # Try to create a minimal connection object for cleanup
                try:
                    minimal_connection = ClientConnection(
                        websocket=websocket,
                        node_id=getattr(websocket, 'node_id', None),
                        user_id=getattr(websocket, 'user_id', None),
                        username=getattr(websocket, 'username', None),
                        domain_id=getattr(websocket, 'domain_id', None),
                        cluster_id=getattr(websocket, 'cluster_id', None),
                        channel_id=getattr(websocket, 'channel_id', None),
                        is_domain_main_node=getattr(websocket, 'is_domain_main_node', False),
                        is_cluster_main_node=getattr(websocket, 'is_cluster_main_node', False),
                        is_channel_main_node=getattr(websocket, 'is_channel_main_node', False)
                    )
                    
                    self.logger.info(f"🔗 Created minimal connection object for cleanup: {minimal_connection}")
                    self.node_manager.remove_connection(minimal_connection)
                    self.logger.info(f"🔗 ✅ NodeManager disconnection sync with minimal connection successful")
                    return True
                except Exception as e:
                    self.logger.error(f"🔗 ❌ Error creating minimal connection for cleanup: {e}")
                    return False
                
        except Exception as e:
            self.logger.error(f"🔗 ❌ Error syncing disconnection to NodeManager: {e}")
            self.logger.error(f"🔗 ❌ Traceback: {traceback.format_exc()}")
            return False
        finally:
            self.logger.info(f"🔗 ===== END NODEMANAGER DISCONNECTION SYNC =====")
    
    async def _sync_connection_status_to_nodemanager_pools(self, websocket, status):
        """Sync connection status changes to NodeManager pools"""
        try:
            self.logger.info(f"🔗 ===== SYNCING CONNECTION STATUS TO NODEMANAGER POOLS =====")
            self.logger.info(f"🔗 WebSocket: {websocket}")
            self.logger.info(f"🔗 Status: {status}")
            
            # Check if NodeManager is available
            if not hasattr(self, 'node_manager') or not self.node_manager:
                self.logger.warning(f"🔗 ⚠️ NodeManager not available for status sync")
                return False
            
            # Get NodeManager connection reference
            nodemanager_connection = getattr(websocket, 'nodemanager_connection', None)
            if not nodemanager_connection:
                self.logger.warning(f"🔗 ⚠️ No NodeManager connection reference found")
                return False
            
            # Update connection status in NodeManager
            if status == 'closed_by_logout':
                # Mark the websocket as closed in NodeManager's connection
                nodemanager_connection.websocket._closed_by_logout = True
                self.logger.info(f"🔗 ✅ Marked NodeManager connection as closed by logout")
                
                # Trigger cleanup of invalid connections in NodeManager
                await self.node_manager.cleanup_disconnected_connections()
                self.logger.info(f"🔗 ✅ Triggered NodeManager cleanup of invalid connections")
                
            elif status == 'reconnected':
                # Clear logout flag if reconnected
                if hasattr(nodemanager_connection.websocket, '_closed_by_logout'):
                    nodemanager_connection.websocket._closed_by_logout = False
                    self.logger.info(f"🔗 ✅ Cleared logout flag for reconnected connection")
            
            # Get updated pool statistics
            valid_counts = self.node_manager.get_valid_connections_count()
            self.logger.info(f"🔗 NodeManager pool status after sync:")
            self.logger.info(f"🔗   Valid connections: {valid_counts.get('total_valid', 0)}")
            self.logger.info(f"🔗   Invalid connections: {valid_counts.get('total_invalid', 0)}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"🔗 ❌ Error syncing connection status to NodeManager pools: {e}")
            self.logger.error(f"🔗 ❌ Traceback: {traceback.format_exc()}")
            return False
        finally:
            self.logger.info(f"🔗 ===== END NODEMANAGER POOL STATUS SYNC =====")
    
    async def _monitor_connection_health(self, websocket):
        """Monitor connection health and sync status with NodeManager"""
        try:
            self.logger.info(f"🔍 ===== MONITORING CONNECTION HEALTH =====")
            self.logger.info(f"🔍 WebSocket: {websocket}")
            
            # Check if websocket is still valid
            if not self.is_connection_valid(websocket):
                self.logger.warning(f"🔍 ⚠️ Connection is invalid, triggering cleanup")
                await self._sync_disconnection_to_nodemanager(websocket)
                return False
            
            # Check NodeManager connection reference
            nodemanager_connection = getattr(websocket, 'nodemanager_connection', None)
            if not nodemanager_connection:
                self.logger.warning(f"🔍 ⚠️ No NodeManager connection reference found")
                return False
            
            # Verify NodeManager connection is still in pools
            if hasattr(self, 'node_manager') and self.node_manager:
                # Check if connection exists in NodeManager pools
                found_in_pools = False
                for pool_name, pool in [
                    ('domain_pool', self.node_manager.domain_pool),
                    ('cluster_pool', self.node_manager.cluster_pool),
                    ('channel_pool', self.node_manager.channel_pool)
                ]:
                    for pool_id, connections in pool.items():
                        if nodemanager_connection in connections:
                            found_in_pools = True
                            self.logger.debug(f"🔍 ✅ Connection found in {pool_name}[{pool_id}]")
                            break
                    if found_in_pools:
                        break
                
                if not found_in_pools:
                    self.logger.warning(f"🔍 ⚠️ Connection not found in any NodeManager pools")
                    return False
            
            self.logger.info(f"🔍 ✅ Connection health check passed")
            return True
            
        except Exception as e:
            self.logger.error(f"🔍 ❌ Error monitoring connection health: {e}")
            return False
        finally:
            self.logger.info(f"🔍 ===== END CONNECTION HEALTH MONITORING =====")
    
    async def _sync_connection_status_to_nodemanager(self, websocket, status_change):
        """Sync connection status changes to NodeManager"""
        try:
            self.logger.info(f"🔗 ===== SYNCING CONNECTION STATUS CHANGE =====")
            self.logger.info(f"🔗 WebSocket: {websocket}")
            self.logger.info(f"🔗 Status change: {status_change}")
            
            # Check if NodeManager is available
            if not hasattr(self, 'node_manager') or not self.node_manager:
                self.logger.warning(f"🔗 ⚠️ NodeManager not available for status sync")
                return False
            
            # Get NodeManager connection reference
            nodemanager_connection = getattr(websocket, 'nodemanager_connection', None)
            if not nodemanager_connection:
                self.logger.warning(f"🔗 ⚠️ No NodeManager connection reference found")
                return False
            
            # Handle different status changes
            if status_change == 'reconnected':
                self.logger.info(f"🔗 Handling reconnection status")
                # Update connection attributes if needed
                nodemanager_connection.user_id = getattr(websocket, 'user_id', nodemanager_connection.user_id)
                nodemanager_connection.username = getattr(websocket, 'username', nodemanager_connection.username)
                nodemanager_connection.node_id = getattr(websocket, 'node_id', nodemanager_connection.node_id)
                
            elif status_change == 'user_changed':
                self.logger.info(f"🔗 Handling user change status")
                # Update user-related attributes
                nodemanager_connection.user_id = getattr(websocket, 'user_id', nodemanager_connection.user_id)
                nodemanager_connection.username = getattr(websocket, 'username', nodemanager_connection.username)
                
            elif status_change == 'node_assigned':
                self.logger.info(f"🔗 Handling node assignment status")
                # Update node-related attributes
                nodemanager_connection.domain_id = getattr(websocket, 'domain_id', nodemanager_connection.domain_id)
                nodemanager_connection.cluster_id = getattr(websocket, 'cluster_id', nodemanager_connection.cluster_id)
                nodemanager_connection.channel_id = getattr(websocket, 'channel_id', nodemanager_connection.channel_id)
                nodemanager_connection.is_domain_main_node = getattr(websocket, 'is_domain_main_node', nodemanager_connection.is_domain_main_node)
                nodemanager_connection.is_cluster_main_node = getattr(websocket, 'is_cluster_main_node', nodemanager_connection.is_cluster_main_node)
                nodemanager_connection.is_channel_main_node = getattr(websocket, 'is_channel_main_node', nodemanager_connection.is_channel_main_node)
            
            self.logger.info(f"🔗 ✅ Connection status sync completed")
            return True
            
        except Exception as e:
            self.logger.error(f"🔗 ❌ Error syncing connection status: {e}")
            self.logger.error(f"🔗 ❌ Traceback: {traceback.format_exc()}")
            return False
        finally:
            self.logger.info(f"🔗 ===== END CONNECTION STATUS SYNC =====")
    
    async def _test_connection_management_integrity(self):
        """Test the integrity of connection management between WebSocket and NodeManager"""
        try:
            self.logger.info(f"🧪 ===== TESTING CONNECTION MANAGEMENT INTEGRITY =====")
            
            # Test 1: Check WebSocket connection pools
            websocket_stats = {
                'node_connections': len(self.node_connections) if hasattr(self, 'node_connections') else 0,
                'user_connections': len(self.user_connections) if hasattr(self, 'user_connections') else 0,
                'client_connections': len(self.client_connections) if hasattr(self, 'client_connections') else 0
            }
            
            self.logger.info(f"🧪 WebSocket connection pools:")
            self.logger.info(f"   Node connections: {websocket_stats['node_connections']}")
            self.logger.info(f"   User connections: {websocket_stats['user_connections']}")
            self.logger.info(f"   Client connections: {websocket_stats['client_connections']}")
            
            # Test 2: Check NodeManager connection pools
            if hasattr(self, 'node_manager') and self.node_manager:
                nodemanager_stats = self.node_manager.get_pool_stats()
                self.logger.info(f"🧪 NodeManager connection pools:")
                self.logger.info(f"   Domains: {nodemanager_stats['domains']}")
                self.logger.info(f"   Clusters: {nodemanager_stats['clusters']}")
                self.logger.info(f"   Channels: {nodemanager_stats['channels']}")
                self.logger.info(f"   Total connections: {nodemanager_stats['total_connections']}")
            else:
                self.logger.warning(f"🧪 ⚠️ NodeManager not available for integrity test")
                return False
            
            # Test 3: Cross-reference connections
            websocket_connections = set()
            nodemanager_connections = set()
            
            # Collect WebSocket connections
            for node_id, connections in self.node_connections.items():
                websocket_connections.update(connections)
            
            # Collect NodeManager connections
            for pool_name, pool in [
                ('domain_pool', self.node_manager.domain_pool),
                ('cluster_pool', self.node_manager.cluster_pool),
                ('channel_pool', self.node_manager.channel_pool)
            ]:
                for pool_id, connections in pool.items():
                    for conn in connections:
                        nodemanager_connections.add(conn.websocket)
            
            # Test 4: Check for orphaned connections
            orphaned_websockets = websocket_connections - nodemanager_connections
            orphaned_nodemanager = nodemanager_connections - websocket_connections
            
            if orphaned_websockets:
                self.logger.warning(f"🧪 ⚠️ Found {len(orphaned_websockets)} orphaned WebSocket connections")
                for ws in list(orphaned_websockets)[:5]:  # Show first 5
                    self.logger.warning(f"   Orphaned WebSocket: {ws}")
            
            if orphaned_nodemanager:
                self.logger.warning(f"🧪 ⚠️ Found {len(orphaned_nodemanager)} orphaned NodeManager connections")
                for ws in list(orphaned_nodemanager)[:5]:  # Show first 5
                    self.logger.warning(f"   Orphaned NodeManager: {ws}")
            
            # Test 5: Check connection references
            reference_issues = 0
            for node_id, connections in self.node_connections.items():
                for websocket in connections:
                    nodemanager_ref = getattr(websocket, 'nodemanager_connection', None)
                    if not nodemanager_ref:
                        reference_issues += 1
                        self.logger.warning(f"🧪 ⚠️ WebSocket {websocket} missing NodeManager reference")
            
            # Test 6: Summary
            integrity_score = 100
            if orphaned_websockets:
                integrity_score -= len(orphaned_websockets) * 10
            if orphaned_nodemanager:
                integrity_score -= len(orphaned_nodemanager) * 10
            if reference_issues:
                integrity_score -= reference_issues * 5
            
            integrity_score = max(0, integrity_score)
            
            self.logger.info(f"🧪 ===== INTEGRITY TEST RESULTS =====")
            self.logger.info(f"🧪 Integrity Score: {integrity_score}/100")
            self.logger.info(f"🧪 Orphaned WebSocket connections: {len(orphaned_websockets)}")
            self.logger.info(f"🧪 Orphaned NodeManager connections: {len(orphaned_nodemanager)}")
            self.logger.info(f"🧪 Missing references: {reference_issues}")
            
            if integrity_score >= 90:
                self.logger.info(f"🧪 ✅ Connection management integrity: EXCELLENT")
            elif integrity_score >= 70:
                self.logger.info(f"🧪 ⚠️ Connection management integrity: GOOD")
            elif integrity_score >= 50:
                self.logger.info(f"🧪 ⚠️ Connection management integrity: FAIR")
            else:
                self.logger.warning(f"🧪 ❌ Connection management integrity: POOR")
            
            return integrity_score >= 70
            
        except Exception as e:
            self.logger.error(f"🧪 ❌ Error testing connection management integrity: {e}")
            self.logger.error(f"🧪 ❌ Traceback: {traceback.format_exc()}")
            return False
        finally:
            self.logger.info(f"🧪 ===== END CONNECTION MANAGEMENT INTEGRITY TEST =====")
    
    async def test_connection_management(self):
        """Public method to test connection management integrity"""
        return await self._test_connection_management_integrity()
    
    async def get_connection_status_report(self):
        """Get a comprehensive status report of all connections"""
        try:
            self.logger.info(f"📊 ===== GENERATING CONNECTION STATUS REPORT =====")
            
            report = {
                'timestamp': datetime.now().isoformat(),
                'websocket_pools': {},
                'nodemanager_pools': {},
                'connection_health': {},
                'recommendations': []
            }
            
            # WebSocket pool status
            if hasattr(self, 'node_connections'):
                report['websocket_pools']['node_connections'] = {
                    'count': len(self.node_connections),
                    'nodes': list(self.node_connections.keys())
                }
            
            if hasattr(self, 'user_connections'):
                report['websocket_pools']['user_connections'] = {
                    'count': len(self.user_connections),
                    'users': list(self.user_connections.keys())
                }
            
            if hasattr(self, 'client_connections'):
                report['websocket_pools']['client_connections'] = {
                    'count': len(self.client_connections),
                    'clients': list(self.client_connections.keys())
                }
            
            # NodeManager pool status
            if hasattr(self, 'node_manager') and self.node_manager:
                nodemanager_stats = self.node_manager.get_pool_stats()
                report['nodemanager_pools'] = nodemanager_stats
            else:
                report['nodemanager_pools'] = {'error': 'NodeManager not available'}
            
            # Connection health check
            health_score = await self._test_connection_management_integrity()
            report['connection_health'] = {
                'score': health_score,
                'status': 'EXCELLENT' if health_score >= 90 else 'GOOD' if health_score >= 70 else 'FAIR' if health_score >= 50 else 'POOR'
            }
            
            # Generate recommendations
            if health_score < 90:
                report['recommendations'].append("Consider running connection cleanup")
            if health_score < 70:
                report['recommendations'].append("Investigate orphaned connections")
            if health_score < 50:
                report['recommendations'].append("Critical: Connection management needs immediate attention")
            
            self.logger.info(f"📊 Connection status report generated")
            self.logger.info(f"📊 Health score: {health_score}/100")
            self.logger.info(f"📊 Status: {report['connection_health']['status']}")
            
            return report
            
        except Exception as e:
            self.logger.error(f"📊 ❌ Error generating connection status report: {e}")
            return {'error': str(e)}
        finally:
            self.logger.info(f"📊 ===== END CONNECTION STATUS REPORT =====")
    
    async def get_nodemanager_connection_status(self):
        """Get NodeManager connection status with valid/invalid connection counts"""
        try:
            self.logger.info(f"📊 ===== GETTING NODEMANAGER CONNECTION STATUS =====")
            
            if not hasattr(self, 'node_manager') or not self.node_manager:
                return {'error': 'NodeManager not available'}
            
            # Get valid connection counts
            valid_counts = self.node_manager.get_valid_connections_count()
            
            # Get pool statistics
            pool_stats = self.node_manager.get_pool_stats()
            
            status = {
                'timestamp': datetime.now().isoformat(),
                'pool_statistics': pool_stats,
                'valid_connections': valid_counts,
                'health_score': 0
            }
            
            # Calculate health score
            total_connections = valid_counts.get('total_valid', 0) + valid_counts.get('total_invalid', 0)
            if total_connections > 0:
                health_score = (valid_counts.get('total_valid', 0) / total_connections) * 100
                status['health_score'] = round(health_score, 2)
            
            self.logger.info(f"📊 NodeManager connection status:")
            self.logger.info(f"📊   Total valid connections: {valid_counts.get('total_valid', 0)}")
            self.logger.info(f"📊   Total invalid connections: {valid_counts.get('total_invalid', 0)}")
            self.logger.info(f"📊   Health score: {status['health_score']}%")
            
            return status
            
        except Exception as e:
            self.logger.error(f"📊 ❌ Error getting NodeManager connection status: {e}")
            return {'error': str(e)}
        finally:
            self.logger.info(f"📊 ===== END NODEMANAGER CONNECTION STATUS =====")
    
    async def cleanup_nodemanager_invalid_connections(self):
        """Clean up invalid connections from NodeManager pools"""
        try:
            self.logger.info(f"🧹 ===== CLEANING UP NODEMANAGER INVALID CONNECTIONS =====")
            
            if not hasattr(self, 'node_manager') or not self.node_manager:
                self.logger.warning(f"🧹 ⚠️ NodeManager not available for cleanup")
                return False
            
            # Trigger cleanup
            await self.node_manager.cleanup_disconnected_connections()
            
            # Get updated statistics
            valid_counts = self.node_manager.get_valid_connections_count()
            self.logger.info(f"🧹 Cleanup completed:")
            self.logger.info(f"🧹   Valid connections: {valid_counts.get('total_valid', 0)}")
            self.logger.info(f"🧹   Invalid connections: {valid_counts.get('total_invalid', 0)}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"🧹 ❌ Error cleaning up NodeManager invalid connections: {e}")
            return False
        finally:
            self.logger.info(f"🧹 ===== END NODEMANAGER CLEANUP =====")
        
        # Connection state cache for faster lookups
        self.connection_cache = {}
        self.connection_validity_cache = {}
        
        # Logout processing optimization - NO FEEDBACK WAITING
        self.logout_timeout_config = {
            'first_logout': 1,   # Ultra-fast: 1 second (just for message sending)
            'subsequent_logout': 1,  # Ultra-fast: 1 second (just for message sending)
            'feedback_check_interval': 0.1,  # Not used anymore
            'immediate_feedback_threshold': 0.5,  # Not used anymore
            'no_feedback_waiting': True  # Key: don't wait for feedback
        }
        
        # Pre-initialize connection pools for instant access
        self.pre_initialize_connection_pools()
        
        self.logger.info("Connection pools and caches initialized with optimization")
    
    def pre_initialize_connection_pools(self):
        """Pre-initialize connection pools for instant access"""
        self.logger.info("Pre-initializing connection pools...")
        
        # Pre-allocate common connection structures
        self.node_connections = {}
        self.user_connections = {}
        self.client_connections = {}
        
        # Pre-allocate cache structures
        self.connection_cache = {}
        self.connection_validity_cache = {}
        
        # Pre-allocate logout history tracking
        self.user_logout_history = {}
        
        # Pre-allocate feedback tracking structures
        self.feedback_tracking = {}
        
        self.logger.info("Connection pools pre-initialized for instant access")
    
    def load_websocket_config(self):
        """Load WebSocket configuration from config.json"""
        try:
            # Use the new config manager to get current environment's websocket config
            from utils.config_manager import get_current_websocket_config
            return get_current_websocket_config()
        except Exception as e:
            self.logger.warning(f"Error loading WebSocket config: {e}")
            return {
                'enabled': True,
                'server_host': '0.0.0.0',
                'server_port': 8766,
                'auto_reconnect': True,
                'reconnect_interval': 30
            }
        
    async def connect(self, host=None, port=None):
        """Connect to C-Client WebSocket server"""
        if not self.config.get('enabled', True):
            self.logger.warning("WebSocket connection disabled in config")
            return False
            
        # Use config values if not provided
        host = host or self.config.get('host', 'localhost')
        port = port or self.config.get('port', 8765)
        
        try:
            uri = f"ws://{host}:{port}"
            self.websocket = await websockets.connect(uri)
            self.is_connected = True
            
            # Register as B-Client
            await self.send_message({
                'type': 'b_client_register',
                'client_id': self.client_id
            })
            
            self.logger.info(f"Connected to C-Client WebSocket at {uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to C-Client WebSocket: {e}")
            self.is_connected = False
            return False
    
    async def start_server(self, host='0.0.0.0', port=8766):
        """Start WebSocket server for C-Client connections"""
        try:
            # Configure WebSocket server with better error handling
            server = await websockets.serve(
                self.handle_c_client_connection, 
                host, 
                port,
                # Add connection handling options
                ping_interval=20,  # Send ping every 20 seconds
                ping_timeout=10,   # Wait 10 seconds for pong
                close_timeout=10,  # Wait 10 seconds for close
                max_size=2**20,    # 1MB max message size
                max_queue=32       # Max 32 messages in queue
            )
            self.logger.info(f"WebSocket server started on ws://{host}:{port}")
            self.logger.info(f"Server configured with ping/pong and connection management")
            return server
        except Exception as e:
            self.logger.error(f"Failed to start WebSocket server: {e}")
            return None
    
    async def _handle_node_management_async(self, websocket, nmp_params):
        """Handle node management in background to allow WebSocket message loop to run"""
        try:
            self.logger.info(f"Background task: Starting NodeManager connection sync...")
            
            # Prepare connection data for sync
            connection_data = {
                'user_id': nmp_params.get('nmp_user_id'),
                'username': nmp_params.get('nmp_username'),
                'node_id': nmp_params.get('nmp_node_id'),
                'domain_main_node_id': nmp_params.get('nmp_domain_main_node_id'),
                'cluster_main_node_id': nmp_params.get('nmp_cluster_main_node_id'),
                'channel_main_node_id': nmp_params.get('nmp_channel_main_node_id'),
                'domain_id': nmp_params.get('nmp_domain_id'),
                'cluster_id': nmp_params.get('nmp_cluster_id'),
                'channel_id': nmp_params.get('nmp_channel_id')
            }
            
            # Use the new comprehensive sync method
            sync_success = await self._sync_connection_to_nodemanager(websocket, connection_data)
            
            if sync_success:
                self.logger.info(f"Background task: ✅ NodeManager connection sync successful")
                
                # Get the connection reference for logging
                nodemanager_connection = getattr(websocket, 'nodemanager_connection', None)
                if nodemanager_connection:
                    self.logger.info(f"Background task: Connection details:")
                    self.logger.info(f"   Node ID: {nodemanager_connection.node_id}")
                    self.logger.info(f"   Domain ID: {nodemanager_connection.domain_id}")
                    self.logger.info(f"   Cluster ID: {nodemanager_connection.cluster_id}")
                    self.logger.info(f"   Channel ID: {nodemanager_connection.channel_id}")
                    self.logger.info(f"   Is Domain Main: {nodemanager_connection.is_domain_main_node}")
                    self.logger.info(f"   Is Cluster Main: {nodemanager_connection.is_cluster_main_node}")
                    self.logger.info(f"   Is Channel Main: {nodemanager_connection.is_channel_main_node}")
                
                # Log pool statistics
                stats = self.node_manager.get_pool_stats()
                self.logger.info(f"Background task: NodeManager pool stats:")
                self.logger.info(f"   Domains: {stats['domains']}")
                self.logger.info(f"   Clusters: {stats['clusters']}")
                self.logger.info(f"   Channels: {stats['channels']}")
                self.logger.info(f"   Total connections: {stats['total_connections']}")
            else:
                self.logger.error(f"Background task: ❌ NodeManager connection sync failed")
            
        except Exception as e:
            self.logger.error(f"Background task: Error in node management: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
    
    async def handle_c_client_connection(self, websocket, path=None):
        """Handle incoming C-Client connections"""
        try:
            self.logger.info(f"===== C-CLIENT CONNECTION RECEIVED =====")
            self.logger.info(f"C-Client connected from {websocket.remote_address}")
            self.logger.info(f"Connection path: {path}")
            self.logger.info(f"WebSocket object: {websocket}")
            
            # Wait for registration message
            self.logger.info(f"Waiting for registration message...")
            message = await websocket.recv()
            self.logger.info(f"Received message: {message}")
            
            data = json.loads(message)
            self.logger.info(f"Parsed message data: {data}")
            self.logger.info(f"Message type: {data.get('type')}")
            
            if data.get('type') == 'c_client_register':
                # Process the registration
                await self._process_c_client_registration(websocket, data)
                
        except websockets.exceptions.ConnectionClosedOK:
            self.logger.info(f"C-Client connection closed normally")
        except websockets.exceptions.ConnectionClosedError as e:
            self.logger.error(f"C-Client connection closed with error: {e}")
        except Exception as e:
            self.logger.error(f"Error handling C-Client connection: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    async def _process_c_client_registration(self, websocket, data, start_message_loop=True):
        """Internal method to process C-Client registration data
        
        Args:
            websocket: WebSocket connection
            data: Registration data dict
            start_message_loop: If True, start the message processing loop after registration.
                                If False, only process registration and return (for re-registration case).
        """
        try:
                self.logger.info(f"===== C-CLIENT REGISTRATION MESSAGE =====")
                client_id = data.get('client_id', 'unknown')
                user_id = data.get('user_id')  # Get user_id from registration
                username = data.get('username')
                node_id = data.get('node_id')
                domain_id = data.get('domain_id')
                cluster_id = data.get('cluster_id')
                channel_id = data.get('channel_id')
                websocket_port = data.get('websocket_port')  # Get C-Client WebSocket port
                
                # Check if username is a security code (new device login)
                # Can be set from handle_c_client_reregistration
                is_new_device_login = data.get('_is_new_device_login', False)
                security_code_record = data.get('_security_code_record', None)
                
                # Use dedicated security code logger
                security_logger = get_bclient_logger('security_code')
                
                # If not already detected by reregistration, check now
                if not is_new_device_login:
                    with app.app_context():
                        from services.models import UserSecurityCode
                        # Check if username matches a security_code (not nmp_username)
                        security_code_record = UserSecurityCode.query.filter_by(security_code=username).first()
                        
                        if security_code_record:
                            security_logger.info(f"🔐 ===== NEW DEVICE LOGIN DETECTED =====")
                            security_logger.info(f"🔐 Registration message received with username: {username}")
                            security_logger.info(f"🔐 Username matches security code in database")
                            security_logger.info(f"🔐 Security code: {security_code_record.security_code}")
                            security_logger.info(f"🔐 Original user_id: {security_code_record.nmp_user_id}")
                            security_logger.info(f"🔐 Original username: {security_code_record.nmp_username}")
                            security_logger.info(f"🔐 Client ID: {client_id}")
                            
                            # Override with real user information from security_code table
                            is_new_device_login = True
                            user_id = security_code_record.nmp_user_id
                            username = security_code_record.nmp_username
                            domain_id = security_code_record.domain_id
                            cluster_id = security_code_record.cluster_id
                            channel_id = security_code_record.channel_id
                            
                            security_logger.info(f"🔐 ===== OVERRIDING WITH REAL USER INFORMATION =====")
                            security_logger.info(f"🔐 Real user_id: {user_id}")
                            security_logger.info(f"🔐 Real username: {username}")
                            security_logger.info(f"🔐 Domain ID: {domain_id}")
                            security_logger.info(f"🔐 Cluster ID: {cluster_id}")
                            security_logger.info(f"🔐 Channel ID: {channel_id}")
                            security_logger.info(f"🔐 Node ID will be assigned: {node_id}")
                else:
                    security_logger.info(f"🔐 ===== NEW DEVICE LOGIN (FROM RE-REGISTRATION) =====")
                    security_logger.info(f"🔐 Already detected and overridden by handle_c_client_reregistration")
                    security_logger.info(f"🔐 User: {username} ({user_id})")
                
                self.logger.info(f"Registration details:")
                self.logger.info(f"   Client ID: {client_id}")
                self.logger.info(f"   User ID: {user_id}")
                self.logger.info(f"   Username: {username}")
                self.logger.info(f"   Node ID: {node_id}")
                self.logger.info(f"   Domain ID: {domain_id}")
                self.logger.info(f"   Cluster ID: {cluster_id}")
                self.logger.info(f"   Channel ID: {channel_id}")
                self.logger.info(f"   WebSocket Port: {websocket_port}")
                
                self.logger.info(f"C-Client registered: {client_id}, user_id: {user_id}")
                self.logger.info(f"   Username: {username}")
                self.logger.info(f"   Node ID: {node_id}")
                self.logger.info(f"   Domain ID: {domain_id}")
                self.logger.info(f"   Cluster ID: {cluster_id}")
                self.logger.info(f"   Channel ID: {channel_id}")
                self.logger.info(f"   WebSocket Port: {websocket_port}")
                
                # Store connection directly with user_id as key
                # Initialize connection pools if not exists
                if not hasattr(self, 'node_connections'):
                    self.node_connections = {}
                if not hasattr(self, 'user_connections'):
                    self.user_connections = {}
                if not hasattr(self, 'client_connections'):
                    self.client_connections = {}
                
                # Set metadata on the websocket object for reference
                websocket.user_id = user_id
                websocket.client_id = client_id
                websocket.username = username
                websocket.node_id = node_id
                websocket.domain_id = domain_id
                websocket.cluster_id = cluster_id
                websocket.channel_id = channel_id
                websocket.websocket_port = websocket_port  # Store C-Client WebSocket port
                
                # Clear any logout flags from previous session (fresh registration)
                if hasattr(websocket, '_closed_by_logout'):
                    delattr(websocket, '_closed_by_logout')
                    self.logger.info(f"Cleared _closed_by_logout flag from fresh registration")
                if hasattr(websocket, '_logout_in_progress'):
                    delattr(websocket, '_logout_in_progress')
                    self.logger.info(f"Cleared _logout_in_progress flag from fresh registration")
                
                # Note: Cluster verification instance is created on-demand during verification
                # to avoid memory overhead and ensure clean state for each verification
                
                # Log unique connection identifier for debugging
                connection_id = id(websocket)
                self.logger.info(f"===== NEW WEBSOCKET CONNECTION CREATED =====")
                self.logger.info(f"Connection ID: {connection_id}")
                self.logger.info(f"Client ID: {client_id}")
                self.logger.info(f"User ID: {user_id}")
                self.logger.info(f"Node ID: {node_id}")
                self.logger.info(f"WebSocket Object: {websocket}")
                self.logger.info(f"===== END NEW CONNECTION =====")
                
                # Allow multiple connections per node - no rejection logic
                self.logger.info(f"Allowing multiple connections per node: {node_id}")
                
                # Store connection in triple pools
                # Node-based connection pool (node_id -> list of websockets)
                if node_id:
                    if node_id not in self.node_connections:
                        self.node_connections[node_id] = []
                    self.node_connections[node_id].append(websocket)
                    self.logger.info(f"Node connection added: {node_id} (total: {len(self.node_connections[node_id])})")
                    self.logger.info(f"Current node connections: {list(self.node_connections.keys())}")
                
                # Client-based connection pool (client_id -> list of websockets)
                # Handle re-registration: update existing connection or create new one
                if client_id:
                    # For new device login, clean up old connections first (user switch scenario)
                    if is_new_device_login:
                        self.logger.info(f"🔐 NEW DEVICE LOGIN: Cleaning up old connections for client {client_id}")
                        # Remove old connections for this client
                        if client_id in self.client_connections:
                            old_connections = self.client_connections[client_id][:]  # Copy to avoid modification during iteration
                            for old_ws in old_connections:
                                # CRITICAL: Check if this is the same websocket connection
                                # In re-registration scenario, old_ws == websocket
                                if old_ws == websocket:
                                    self.logger.info(f"🔐 Same websocket connection - updating metadata instead of closing")
                                    continue
                                
                                old_user_id = getattr(old_ws, 'user_id', None)
                                old_username = getattr(old_ws, 'username', None)
                                self.logger.info(f"🔐 Removing old connection: client={client_id}, old_user={old_username} ({old_user_id})")
                                
                                # Clean up from all pools
                                await self.remove_connection_from_all_pools(old_ws)
                                
                                # Close the old connection
                                try:
                                    await old_ws.close(code=1000, reason="User switch - new device login")
                                except Exception as e:
                                    self.logger.warning(f"🔐 Error closing old connection: {e}")
                            
                            self.logger.info(f"🔐 Old connections cleaned up successfully")
                    
                    # Check for exact duplicate registration (same node_id, client_id, user_id)
                    # Skip this check for new device login as we've already cleaned up old connections
                    if not is_new_device_login and self.check_duplicate_registration(node_id, client_id, user_id, websocket):
                        self.logger.info(f"Duplicate registration detected - same node_id, client_id, user_id")
                        self.logger.info(f"Node: {node_id}, Client: {client_id}, User: {user_id}")
                        self.logger.info(f"Sending success response to existing connection")
                        
                        # Find the existing connection
                        existing_websocket = self.find_existing_connection(node_id, client_id, user_id)
                        if existing_websocket:
                            # Send success response to existing connection
                            await self.send_message_to_websocket(existing_websocket, {
                                'type': 'registration_success',
                                'client_id': client_id,
                                'user_id': user_id,
                                'username': username,
                                'message': 'Already registered with same credentials'
                            })
                            
                            self.logger.info(f"Duplicate registration response sent to existing connection")
                            
                            # Close the new connection since it's a duplicate
                            await websocket.close(code=1000, reason="Duplicate registration - using existing connection")
                            return
                    
                    # Check if this client is already connected
                    # Skip this check for new device login as we've already cleaned up old connections
                    if not is_new_device_login and client_id in self.client_connections:
                        existing_connections = self.client_connections[client_id]
                        existing_websocket = existing_connections[0] if existing_connections else None
                        
                        if existing_websocket:
                            existing_node_id = getattr(existing_websocket, 'node_id', None)
                            existing_user_id = getattr(existing_websocket, 'user_id', None)
                            
                            # If same node and same user, this is a duplicate
                            if existing_node_id == node_id and existing_user_id == user_id:
                                self.logger.info(f"Exact duplicate registration detected")
                                self.logger.info(f"Same node ({node_id}), client ({client_id}), and user ({user_id})")
                                
                                # Send success response to existing connection
                                await self.send_message_to_websocket(existing_websocket, {
                                    'type': 'registration_success',
                                    'client_id': client_id,
                                    'user_id': user_id,
                                    'username': username,
                                    'message': 'Already registered with same credentials'
                                })
                                
                                self.logger.info(f"Duplicate registration response sent to existing connection")
                                
                                # Close the new connection since it's a duplicate
                                await websocket.close(code=1000, reason="Duplicate registration - using existing connection")
                                return
                            
                            # If same node but different user, update user info (re-registration)
                            elif existing_node_id == node_id:
                                self.logger.info(f"Client {client_id} re-registering on same node {node_id}")
                                self.logger.info(f"Updating user info to {user_id} ({username})")
                                
                                # Update websocket metadata
                                existing_websocket.user_id = user_id
                                existing_websocket.username = username
                                existing_websocket.domain_id = domain_id
                                existing_websocket.cluster_id = cluster_id
                                existing_websocket.channel_id = channel_id
                                
                                # Update user connections pool based on new user_id
                                if user_id:
                                    # First, remove from old user pool if exists
                                    old_user_id = None
                                    for uid, connections in list(self.user_connections.items()):
                                        if existing_websocket in connections:
                                            old_user_id = uid
                                            connections.remove(existing_websocket)
                                            self.logger.info(f"Removed connection from old user pool: {uid}")
                                            # Clean up empty user connection lists
                                            if not connections:
                                                del self.user_connections[uid]
                                                self.logger.info(f"Removed empty user connection list for {uid}")
                                            break
                                    
                                    # CRITICAL FIX: Only reuse connection if it's still valid
                                    if self.is_connection_valid(existing_websocket):
                                        self.logger.info(f"Existing connection is still valid, reusing it")
                                    
                                    # Then add to new user pool
                                    if user_id not in self.user_connections:
                                        # New user - create new user pool
                                        self.user_connections[user_id] = []
                                        self.logger.info(f"Created new user pool for {user_id}")
                                    
                                    if existing_websocket not in self.user_connections[user_id]:
                                        # Add connection to user pool
                                        self.user_connections[user_id].append(existing_websocket)
                                        self.logger.info(f"Added connection to user pool: {user_id} (total: {len(self.user_connections[user_id])})")
                                    else:
                                        self.logger.info(f"Connection already in user pool: {user_id}")
                                else:
                                    self.logger.error(f"Existing connection is invalid (closed/logged out), closing new connection and not reusing")
                                    # Close the new connection since we can't reuse the old one
                                    await websocket.close(code=1000, reason="Existing connection invalid, not reusing")
                                    return
                                
                                # Send success response to existing connection
                                await self.send_message_to_websocket(existing_websocket, {
                                    'type': 'registration_success',
                                    'client_id': client_id,
                                    'user_id': user_id,
                                    'username': username
                                })
                                
                                self.logger.info(f"Re-registration response sent to existing connection")
                                
                                # After successful re-registration, check if user has a saved session and send it
                                # CRITICAL FIX: Run in background to avoid blocking message loop
                                asyncio.create_task(self.send_session_if_appropriate(user_id, existing_websocket, is_reregistration=True))
                                
                                # Close the new connection since we're using the existing one
                                await websocket.close(code=1000, reason="Re-registration successful, using existing connection")
                                return
                            else:
                                # Different node - reject
                                self.logger.warning(f"Client {client_id} is already connected to node {existing_node_id}, rejecting connection to node {node_id}")
                                
                                await self.send_message_to_websocket(websocket, {
                                    'type': 'registration_rejected',
                                    'reason': 'client_already_connected_to_different_node',
                                    'message': f'Client {client_id} is already connected to node {existing_node_id}. One client can only connect to one node.',
                                    'client_id': client_id,
                                    'user_id': user_id,
                                    'username': username,
                                    'node_id': node_id,
                                    'existing_node_id': existing_node_id
                                })
                                
                                await websocket.close(code=1000, reason="Client already connected to different node")
                                return
                    
                    # Add new connection to client pool
                    if client_id not in self.client_connections:
                        self.client_connections[client_id] = []
                        self.logger.info(f"Created new client pool for {client_id}")
                    self.client_connections[client_id].append(websocket)
                    self.logger.info(f"Client connection added: {client_id} (total: {len(self.client_connections[client_id])})")
                    self.logger.info(f"Current client connections: {list(self.client_connections.keys())}")
                    
                    # Print detailed client pool status
                    self.logger.info(f"Client pool status after new registration:")
                    self.logger.info(f"   Total clients: {len(self.client_connections)}")
                    for cid, connections in self.client_connections.items():
                        self.logger.info(f"   Client {cid}: {len(connections)} connections")
                        for i, conn in enumerate(connections):
                            conn_user = getattr(conn, 'user_id', 'unknown')
                            conn_client = getattr(conn, 'client_id', 'unknown')
                            self.logger.info(f"     Connection {i+1}: user={conn_user}, client={conn_client}")
                
                # User-based connection pool (user_id -> list of websockets)
                if user_id:
                    # IMMEDIATE CHECK: Verify user logout status (DO NOT reset automatically)
                    self.logger.info(f"IMMEDIATE CHECK: Verifying user {user_id} logout status...")
                    try:
                        # Ensure we have Flask application context for database operations
                        with app.app_context():
                            user_account = UserAccount.query.filter_by(user_id=user_id).first()
                            if user_account and user_account.logout:
                                self.logger.warning(f"User {user_id} is logged out, connection will be limited")
                                self.logger.warning(f"Logout status will NOT be reset automatically - user must login manually")
                            else:
                                self.logger.info(f"User {user_id} is not logged out, proceeding with connection")
                    except Exception as e:
                        self.logger.warning(f"Error checking user logout status: {e}")
                    
                    # Check if this client already has a different user connected
                    await self.handle_client_user_switch(client_id, user_id, username, websocket)
                    
                    # Check if this node already has a different user connected
                    await self.handle_node_user_switch(node_id, user_id, username, websocket)
                    
                    # Add new connection to user pool
                    if user_id not in self.user_connections:
                        self.user_connections[user_id] = []
                        self.logger.info(f"Created new user pool for {user_id}")
                    
                    # Clean up old connections with closed_by_logout flag before adding new one
                    # CRITICAL: Don't clean up connections that are waiting for logout feedback
                    old_connections = self.user_connections[user_id][:]
                    cleaned_count = 0
                    for old_ws in old_connections:
                        if hasattr(old_ws, '_closed_by_logout') and old_ws._closed_by_logout:
                            # CRITICAL: Check if connection is waiting for logout feedback
                            if hasattr(old_ws, '_logout_feedback_tracking'):
                                self.logger.info(f"Skipping cleanup of connection waiting for logout feedback for user {user_id}")
                                continue  # Don't remove connections waiting for feedback
                            
                            self.logger.info(f"Removing old closed_by_logout connection for user {user_id}")
                            self.user_connections[user_id].remove(old_ws)
                            cleaned_count += 1
                    
                    if cleaned_count > 0:
                        self.logger.info(f"Cleaned up {cleaned_count} old closed_by_logout connections for user {user_id}")
                    
                    self.user_connections[user_id].append(websocket)
                    self.logger.info(f"User connection added: {user_id} (total: {len(self.user_connections[user_id])})")
                    
                    self.logger.info(f"Current user connections: {list(self.user_connections.keys())}")
                    self.logger.info(f"User {user_id} connected on nodes: {[getattr(ws, 'node_id', 'unknown') for ws in self.user_connections[user_id]]}")
                    
                    # Print detailed user pool status
                    self.logger.info(f"User pool status after new registration:")
                    self.logger.info(f"   Total users: {len(self.user_connections)}")
                    for uid, connections in self.user_connections.items():
                        self.logger.info(f"   User {uid}: {len(connections)} connections")
                        for i, conn in enumerate(connections):
                            conn_user = getattr(conn, 'user_id', 'unknown')
                            conn_client = getattr(conn, 'client_id', 'unknown')
                            self.logger.info(f"     Connection {i+1}: user={conn_user}, client={conn_client}")
                    
                    # Check logout status before notifying existing connections
                    # Only notify if user is not logged out
                    try:
                        with app.app_context():
                            user_account = UserAccount.query.filter_by(user_id=user_id).first()
                            is_logged_out = user_account and user_account.logout
                            
                            if is_logged_out:
                                self.logger.warning(f"User {user_id} is logged out, skipping notification to existing connections")
                            else:
                                # Notify all existing connections about user login
                                # This ensures all clients are aware when a user logs in
                                existing_connections = [conn for conn in self.user_connections[user_id] if conn != websocket]
                                if existing_connections:
                                    self.logger.info(f"User {user_id} ({username}) logged in, notifying {len(existing_connections)} existing connections")
                                    await self.notify_user_connected_on_another_client(user_id, username, client_id, node_id, existing_connections)
                                else:
                                    self.logger.info(f"No existing connections to notify for user {user_id}")
                    except Exception as e:
                        self.logger.warning(f"Error checking logout status for notification: {e}")
                        # Fallback: don't notify if we can't check logout status
                        self.logger.info(f"Skipping notification due to logout status check error")
                
                # ========== NodeManager Integration ==========
                self.logger.info("=" * 80)
                self.logger.info("NODEMANAGER INTEGRATION CHECKPOINT")
                self.logger.info(f"Checking if NodeManager is available...")
                
                if hasattr(self, 'node_manager'):
                    self.logger.info(f"NodeManager found: {self.node_manager}")
                    self.logger.info(f"Preparing to call node_manager.handle_new_connection()...")
                    
                    try:
                        # Construct NMP parameters
                        nmp_params = {
                            'nmp_user_id': user_id,
                            'nmp_username': username,
                            'nmp_node_id': node_id,
                            'nmp_domain_main_node_id': data.get('domain_main_node_id'),
                            'nmp_cluster_main_node_id': data.get('cluster_main_node_id'),
                            'nmp_channel_main_node_id': data.get('channel_main_node_id'),
                            'nmp_domain_id': domain_id,
                            'nmp_cluster_id': cluster_id,
                            'nmp_channel_id': channel_id
                        }
                        
                        self.logger.info(f"NMP params for NodeManager:")
                        for key, value in nmp_params.items():
                            self.logger.info(f"   {key}: {value}")
                        
                        self.logger.info(f"Starting node_manager.handle_new_connection() in background...")
                        # Create background task to handle node management
                        # This allows the WebSocket message loop to start and receive responses
                        asyncio.create_task(self._handle_node_management_async(websocket, nmp_params))
                        self.logger.info(f"Node management task created successfully")
                        
                    except Exception as e:
                        self.logger.error(f"NodeManager integration error: {e}")
                        self.logger.error(f"Traceback: {traceback.format_exc()}")
                else:
                    self.logger.error(f"NodeManager NOT FOUND on self")
                    self.logger.error(f"   Available attributes: {[attr for attr in dir(self) if not attr.startswith('_')]}")
                    self.logger.warning(f"C-Client will NOT be added to node management pools")
                
                self.logger.info("=" * 80)
                # ========== End NodeManager Integration ==========
                
                # Send registration confirmation
                registration_message = {
                    'type': 'registration_success',
                    'client_id': client_id,
                    'user_id': user_id,
                    'username': username
                }
                
                # If this is a new device login, include full user information
                if is_new_device_login:
                    security_logger.info(f"🔐 ===== PREPARING REGISTRATION SUCCESS MESSAGE =====")
                    
                    registration_message['is_new_device_login'] = True
                    registration_message['username'] = username
                    registration_message['domain_id'] = domain_id
                    registration_message['cluster_id'] = cluster_id
                    registration_message['channel_id'] = channel_id
                    registration_message['node_id'] = node_id
                    
                    security_logger.info(f"🔐 Message includes is_new_device_login flag: True")
                    security_logger.info(f"🔐 Message includes user info:")
                    security_logger.info(f"🔐   - user_id: {user_id}")
                    security_logger.info(f"🔐   - username: {username}")
                    security_logger.info(f"🔐   - node_id: {node_id}")
                    security_logger.info(f"🔐   - domain_id: {domain_id}")
                    security_logger.info(f"🔐   - cluster_id: {cluster_id}")
                    security_logger.info(f"🔐   - channel_id: {channel_id}")
                    
                    # Get main node IDs from NodeManager's node structure
                    security_logger.info(f"🔐 Querying main node IDs from NodeManager...")
                    if self.node_manager:
                        main_node_ids = self.node_manager.get_main_node_ids(
                            domain_id=domain_id,
                            cluster_id=cluster_id,
                            channel_id=channel_id
                        )
                        
                        registration_message['domain_main_node_id'] = main_node_ids.get('domain_main_node_id')
                        registration_message['cluster_main_node_id'] = main_node_ids.get('cluster_main_node_id')
                        registration_message['channel_main_node_id'] = main_node_ids.get('channel_main_node_id')
                        
                        security_logger.info(f"🔐 Message includes main node IDs from NodeManager:")
                        security_logger.info(f"🔐   - domain_main_node_id: {registration_message['domain_main_node_id']}")
                        security_logger.info(f"🔐   - cluster_main_node_id: {registration_message['cluster_main_node_id']}")
                        security_logger.info(f"🔐   - channel_main_node_id: {registration_message['channel_main_node_id']}")
                    else:
                        security_logger.warn(f"⚠️ NodeManager not available, setting main node IDs to None")
                        registration_message['domain_main_node_id'] = None
                        registration_message['cluster_main_node_id'] = None
                        registration_message['channel_main_node_id'] = None
                    
                    # Delete the security code record to ensure one-time use
                    if security_code_record:
                        try:
                            security_logger.info(f"🔐 ===== DELETING SECURITY CODE (ONE-TIME USE) =====")
                            security_code_to_delete = security_code_record.security_code
                            security_user_id = security_code_record.nmp_user_id
                            security_username = security_code_record.nmp_username
                            security_created_at = security_code_record.create_time
                            
                            security_logger.info(f"🔐 Security code to delete: {security_code_to_delete}")
                            security_logger.info(f"🔐 User: {security_username} ({security_user_id})")
                            security_logger.info(f"🔐 Created at: {security_created_at}")
                            
                            with app.app_context():
                                from services.models import UserSecurityCode, db
                                
                                # Re-query in the new session to avoid session conflict
                                record_to_delete = UserSecurityCode.query.filter_by(security_code=security_code_to_delete).first()
                                if record_to_delete:
                                    db.session.delete(record_to_delete)
                                    db.session.commit()
                                    
                                    security_logger.info(f"✅ Security code record deleted successfully")
                                    security_logger.info(f"✅ One-time use enforced - code cannot be reused")
                                else:
                                    security_logger.warning(f"⚠️ Security code record not found (may have been deleted already)")
                        except Exception as e:
                            security_logger.error(f"❌ Error deleting security code record: {e}")
                            security_logger.error(f"❌ Traceback: {traceback.format_exc()}")
                    
                    security_logger.info(f"🔐 ===== SENDING REGISTRATION SUCCESS TO C-CLIENT =====")
                    security_logger.info(f"🔐 Target client_id: {client_id}")
                    security_logger.info(f"🔐 Message type: registration_success")
                    security_logger.info(f"🔐 Message contains full user info and main node IDs")
                
                await self.send_message_to_websocket(websocket, registration_message)
                
                # Log completion for new device login
                if is_new_device_login:
                    security_logger.info(f"✅ ===== NEW DEVICE LOGIN REGISTRATION COMPLETE =====")
                    security_logger.info(f"✅ C-Client {client_id} successfully registered as user {username}")
                    security_logger.info(f"✅ Security code has been deleted (one-time use)")
                    security_logger.info(f"✅ C-Client will now switch to user {username} and perform cleanup")
                    security_logger.info(f"=" * 80)
                
                self.logger.info(f"🔌 ===== REGISTRATION SUCCESSFUL =====")
                self.logger.info(f"🔌 Node: {node_id}, User: {user_id} ({username}), Client: {client_id}")
                self.logger.info(f"🔌 Final connection pools status:")
                self.logger.info(f"🔌   Nodes: {len(self.node_connections)} - {list(self.node_connections.keys())}")
                self.logger.info(f"🔌   Users: {len(self.user_connections)} - {list(self.user_connections.keys())}")
                self.logger.info(f"🔌   Clients: {len(self.client_connections)} - {list(self.client_connections.keys())}")
                
                # Detailed pool analysis
                for uid, connections in self.user_connections.items():
                    node_list = [getattr(ws, 'node_id', 'unknown') for ws in connections]
                    client_list = [getattr(ws, 'client_id', 'unknown') for ws in connections]
                    self.logger.info(f"🔌   User {uid}: {len(connections)} connections on nodes {node_list} with clients {client_list}")
                
                # Node pool analysis
                for nid, connections in self.node_connections.items():
                    user_list = [getattr(ws, 'user_id', 'unknown') for ws in connections]
                    client_list = [getattr(ws, 'client_id', 'unknown') for ws in connections]
                    self.logger.info(f"🔌   Node {nid}: {len(connections)} connections for users {user_list} with clients {client_list}")
                
                self.logger.info(f"🔌 ===== END REGISTRATION =====")
                for cid, connections in self.client_connections.items():
                    user_list = [getattr(ws, 'user_id', 'unknown') for ws in connections]
                    node_list = [getattr(ws, 'node_id', 'unknown') for ws in connections]
                    self.logger.info(f"   Client {cid}: {len(connections)} connections for users {user_list} on nodes {node_list}")
                
                # After successful registration, check if user has a saved session and send it
                # CRITICAL FIX: Run in background to avoid blocking message loop
                asyncio.create_task(self.send_session_if_appropriate(user_id, websocket, is_reregistration=False))
                
                # Handle messages from C-Client (only if start_message_loop is True)
                if start_message_loop:
                    self.logger.info(f"Starting message processing loop for {client_id}")
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await self.process_c_client_message(websocket, data, client_id, user_id)
                    except json.JSONDecodeError:
                        await self.send_error(websocket, "Invalid JSON format")
                    except Exception as e:
                        self.logger.error(f"Error processing C-Client message: {e}")
                else:
                    self.logger.info(f"Skipping message loop (re-registration case) for {client_id}")
                        
        except websockets.exceptions.ConnectionClosed:
            self.logger.info(f"🔌 ===== C-CLIENT DISCONNECTED =====")
            self.logger.info(f"🔌 WebSocket: {websocket}")
            self.logger.info(f"🔌 Node ID: {getattr(websocket, 'node_id', 'None')}")
            self.logger.info(f"🔌 User ID: {getattr(websocket, 'user_id', 'None')}")
            self.logger.info(f"🔌 Client ID: {getattr(websocket, 'client_id', 'None')}")
            
            # Note: Cluster verification instances are created on-demand and cleaned up after each verification
            # No need to clean up here as they are temporary and scoped to verification operations
            
            # CRITICAL FIX: Clean up connection pools when connection is closed
            self.remove_invalid_connection(websocket)
            
            self.logger.info(f"🔌 ===== END DISCONNECTION CLEANUP =====")
        except websockets.exceptions.InvalidMessage as e:
            # Handle WebSocket handshake failure - this is usually not a critical error
            if "did not receive a valid HTTP request" in str(e):
                self.logger.debug(f"WebSocket handshake failed (connection closed before HTTP request) - this is usually normal")
            else:
                self.logger.error(f"WebSocket invalid message: {e}")
        except EOFError as e:
            # Handle connection closed unexpectedly - this is usually not a critical error
            if "connection closed while reading HTTP request line" in str(e):
                self.logger.debug(f"WebSocket connection closed during handshake - this is usually normal")
            else:
                self.logger.warning(f"WebSocket connection closed unexpectedly: {e}")
        except Exception as e:
            self.logger.error(f"Error handling C-Client connection: {e}")
        finally:
            # Remove from all connection pools using websocket object reference
            await self.remove_connection_from_all_pools(websocket)
    
    async def process_c_client_message(self, websocket, data, client_id, user_id=None):
        """Process messages from C-Client"""
        message_type = data.get('type')
        
        # Check if this is a NodeManager command response (has request_id and command_type)
        if 'request_id' in data and 'command_type' in data:
            self.logger.info(f"Received NodeManager response from C-Client {client_id}")
            self.logger.info(f"   Command type: {data.get('command_type')}")
            self.logger.info(f"   Request ID: {data.get('request_id')}")
            self.logger.info(f"   Success: {data.get('success')}")
            
            # Forward to NodeManager for processing
            if hasattr(self, 'node_manager') and self.node_manager:
                self.logger.info(f"Forwarding response to NodeManager...")
                
                # Find the actual ClientConnection object from NodeManager's pools
                node_id = data.get('data', {}).get('node_id') or getattr(websocket, 'node_id', None)
                connection = None
                
                if node_id:
                    self.logger.info(f"Looking for connection with node_id: {node_id}")
                    # Search in all pools
                    for domain_id, connections in self.node_manager.domain_pool.items():
                        for conn in connections:
                            if conn.node_id == node_id:
                                connection = conn
                                self.logger.info(f"Found connection in domain_pool[{domain_id}]")
                                break
                        if connection:
                            break
                    
                    if not connection:
                        for cluster_id, connections in self.node_manager.cluster_pool.items():
                            for conn in connections:
                                if conn.node_id == node_id:
                                    connection = conn
                                    self.logger.info(f"Found connection in cluster_pool[{cluster_id}]")
                                    break
                            if connection:
                                break
                    
                    if not connection:
                        for channel_id, connections in self.node_manager.channel_pool.items():
                            for conn in connections:
                                if conn.node_id == node_id:
                                    connection = conn
                                    self.logger.info(f"Found connection in channel_pool[{channel_id}]")
                                    break
                            if connection:
                                break
                
                if not connection:
                    self.logger.warning(f"Could not find ClientConnection object, creating temporary one")
                    # Create a minimal connection object if not found
                    connection = ClientConnection(
                        websocket=websocket,
                        node_id=node_id,
                        user_id=user_id,
                        username=data.get('username', ''),
                        domain_id=data.get('data', {}).get('domain_id'),
                        cluster_id=data.get('data', {}).get('cluster_id'),
                        channel_id=data.get('data', {}).get('channel_id'),
                        domain_main_node_id=None,
                        cluster_main_node_id=None,
                        channel_main_node_id=None,
                        is_domain_main_node=False,
                        is_cluster_main_node=False,
                        is_channel_main_node=False
                    )
                
                await self.node_manager.handle_c_client_response(connection, data)
                self.logger.info(f"Response forwarded to NodeManager")
            return
        
        if message_type == 'c_client_register':
            # Handle re-registration from C-Client
            self.logger.info(f"Received re-registration from C-Client {client_id}")
            await self.handle_c_client_reregistration(websocket, data)
        elif message_type == 'assignConfirmed':
            # Handle assignConfirmed notification from C-Client
            self.logger.info(f"Received assignConfirmed from C-Client {client_id}")
            assign_data = data.get('data', {})
            self.logger.info(f"   Domain ID: {assign_data.get('domain_id')}")
            self.logger.info(f"   Cluster ID: {assign_data.get('cluster_id')}")
            self.logger.info(f"   Channel ID: {assign_data.get('channel_id')}")
            self.logger.info(f"   Node ID: {assign_data.get('node_id')}")
            
            # Forward to NodeManager to update connection pools if needed
            if hasattr(self, 'node_manager') and self.node_manager:
                node_id = assign_data.get('node_id')
                if node_id:
                    self.logger.info(f"Updating connection pools for node {node_id}...")
                    # Search for connection and update its IDs
                    for domain_id, connections in self.node_manager.domain_pool.items():
                        for conn in connections:
                            if conn.node_id == node_id:
                                conn.domain_id = assign_data.get('domain_id') or conn.domain_id
                                conn.cluster_id = assign_data.get('cluster_id') or conn.cluster_id
                                conn.channel_id = assign_data.get('channel_id') or conn.channel_id
                                self.logger.info(f"Updated connection in domain_pool: domain={conn.domain_id}, cluster={conn.cluster_id}, channel={conn.channel_id}")
                                
                                # Add to cluster pool if cluster_id exists and not already there
                                if conn.cluster_id and conn.is_cluster_main_node:
                                    if conn.cluster_id not in self.node_manager.cluster_pool:
                                        self.node_manager.cluster_pool[conn.cluster_id] = []
                                    if conn not in self.node_manager.cluster_pool[conn.cluster_id]:
                                        self.node_manager.cluster_pool[conn.cluster_id].append(conn)
                                        self.logger.info(f"Added to cluster_pool[{conn.cluster_id}]")
                                
                                # Add to channel pool if channel_id exists and not already there
                                if conn.channel_id and conn.is_channel_main_node:
                                    if conn.channel_id not in self.node_manager.channel_pool:
                                        self.node_manager.channel_pool[conn.channel_id] = []
                                    if conn not in self.node_manager.channel_pool[conn.channel_id]:
                                        self.node_manager.channel_pool[conn.channel_id].append(conn)
                                        self.logger.info(f"Added to channel_pool[{conn.channel_id}]")
                                break
                    
                    # Also update WebSocket object attributes for proper cleanup on disconnect
                    websocket.domain_id = assign_data.get('domain_id') or websocket.domain_id
                    websocket.cluster_id = assign_data.get('cluster_id') or websocket.cluster_id
                    websocket.channel_id = assign_data.get('channel_id') or websocket.channel_id
                    
                    # Update main node flags based on the connection's status in NodeManager
                    # Find the connection in NodeManager to get the correct flags
                    for domain_id, connections in self.node_manager.domain_pool.items():
                        for conn in connections:
                            if conn.node_id == node_id:
                                websocket.is_domain_main_node = conn.is_domain_main_node
                                websocket.is_cluster_main_node = conn.is_cluster_main_node
                                websocket.is_channel_main_node = conn.is_channel_main_node
                                break
                    
                    self.logger.info(f"Updated WebSocket attributes: domain={websocket.domain_id}, cluster={websocket.cluster_id}, channel={websocket.channel_id}")
                    self.logger.info(f"Updated WebSocket main node flags: domain_main={websocket.is_domain_main_node}, cluster_main={websocket.is_cluster_main_node}, channel_main={websocket.is_channel_main_node}")
                    
                    self.logger.info(f"Current pool stats:")
                    self.logger.info(f"   Domains: {len(self.node_manager.domain_pool)}")
                    self.logger.info(f"   Clusters: {len(self.node_manager.cluster_pool)}")
                    self.logger.info(f"   Channels: {len(self.node_manager.channel_pool)}")
        elif message_type == 'cookie_response':
            # Handle cookie response from C-Client
            self.logger.info(f"Received cookie response from C-Client {client_id}")
        elif message_type == 'cookie_update_response':
            # Handle cookie update response from C-Client
            self.logger.info(f"Received cookie update response from C-Client {client_id}")
        elif message_type == 'user_login_notification':
            # Handle user login notification from C-Client
            self.logger.info(f"Received user login notification from C-Client {client_id}")
        elif message_type == 'user_logout_notification':
            # Handle user logout notification from C-Client
            self.logger.info(f"Received user logout notification from C-Client {client_id}")
        elif message_type == 'logout_feedback':
            # Handle logout feedback from C-Client
            self.logger.info(f"Received logout feedback from C-Client {client_id}")
            await self.handle_logout_feedback(websocket, data, client_id, user_id)
        elif message_type == 'session_feedback':
            # Handle session feedback from C-Client
            self.logger.info(f"Received session feedback from C-Client {client_id}")
            await self.handle_session_feedback(websocket, data, client_id, user_id)
        elif message_type == 'user_activities_batch':
            # Handle user activities batch from C-Client
            self.logger.info(f"Received user activities batch from C-Client {client_id}")
            if sync_manager:
                await sync_manager.handle_user_activities_batch(websocket, data.get('data', {}))
            else:
                self.logger.warning("SyncManager not initialized, cannot handle user activities batch")
        elif message_type == 'user_activities_batch_feedback':
            # Handle batch feedback from C-Client
            self.logger.info(f"Received batch feedback from C-Client {client_id}")
            if sync_manager:
                await sync_manager.handle_batch_feedback(websocket, data.get('data', {}))
            else:
                self.logger.warning("SyncManager not initialized, cannot handle batch feedback")
        elif message_type == 'cluster_verification_response':
            # Handle cluster verification response from C-Client
            self.logger.info(f"Received cluster verification response from C-Client {client_id}")
            # Route to the originator instance (C1's instance)
            await self.handle_cluster_verification_response_to_originator(websocket, data, client_id, user_id)
        elif message_type == 'request_security_code':
            # Handle security code request from C-Client
            self.logger.info(f"Received security code request from C-Client {client_id}")
            await self.handle_security_code_request(websocket, data, client_id, user_id)
        else:
            self.logger.warning(f"Unknown message type from C-Client: {message_type}")
    
    async def handle_cluster_verification_response_to_originator(self, websocket, data, client_id, user_id):
        """Handle cluster verification response by routing to the originator's instance"""
        try:
            self.logger.info(f"🔍 ===== CLUSTER VERIFICATION RESPONSE ROUTING =====")
            self.logger.info(f"🔍 From C-Client: {client_id}")
            self.logger.info(f"🔍 User ID: {user_id}")
            self.logger.info(f"🔍 Response data: {data}")
            
            # Find all connection instances with waiting events
            originator_instance = None
            for connection_id, instance in self.connection_cluster_verification.items():
                if hasattr(instance, 'response_events') and instance.response_events:
                    self.logger.info(f"🔍 Found instance with waiting events: {connection_id}")
                    self.logger.info(f"🔍 Waiting events: {list(instance.response_events.keys())}")
                    originator_instance = instance
                    break
            
            if originator_instance:
                self.logger.info(f"🔍 ===== ROUTING TO ORIGINATOR INSTANCE =====")
                await originator_instance.handle_verification_response(websocket, data)
                self.logger.info(f"🔍 ✅ Response routed to originator instance")
            else:
                self.logger.warning(f"🔍 ❌ No originator instance found with waiting events")
                # Fallback to global service
                global_service = get_cluster_verification_service()
                if global_service:
                    self.logger.info(f"🔍 ===== FALLBACK TO GLOBAL SERVICE =====")
                    await global_service.handle_verification_response(websocket, data)
                else:
                    self.logger.error(f"🔍 ❌ No global service available as fallback")
                
        except Exception as e:
            self.logger.error(f"❌ Error routing cluster verification response: {e}")
            self.logger.error(f"❌ Traceback: {traceback.format_exc()}")
    
    
    async def send_message_to_c_client(self, client_id, message):
        """Send message to specific C-Client by client_id"""
        # Search in client_connections for the websocket with matching client_id
        if hasattr(self, 'client_connections') and self.client_connections:
            if client_id in self.client_connections:
                for websocket in self.client_connections[client_id]:
                    try:
                        await self.send_message_to_websocket(websocket, message)
                    except Exception as e:
                        self.logger.error(f"Error sending message to client {client_id}: {e}")
                return True
        return False
    
    async def send_message_to_node(self, node_id, message):
        """Send message to C-Client by node_id (node_id is the connection key)"""
        if hasattr(self, 'node_connections') and self.node_connections:
            if node_id in self.node_connections:
                for websocket in self.node_connections[node_id]:
                    try:
                        await self.send_message_to_websocket(websocket, message)
                        self.logger.info(f"Message sent to node {node_id}")
                    except Exception as e:
                        self.logger.error(f"Error sending message to node {node_id}: {e}")
                return True
            else:
                self.logger.error(f"No connection found for node_id: {node_id}")
                return False
        return False
    
    async def send_message_to_user(self, user_id, message):
        """Send message to all C-Client connections for a specific user"""
        if hasattr(self, 'user_connections') and self.user_connections:
            user_websockets = self.user_connections.get(user_id, [])
            if user_websockets:
                success_count = 0
                failed_connections = []
                
                for i, websocket in enumerate(user_websockets):
                    try:
                        # Check if websocket is still open using centralized validation
                        if not self.is_connection_valid(websocket):
                            self.logger.warning(f"Connection {i} for user {user_id} is invalid, skipping")
                            failed_connections.append(i)
                            continue
                            
                        await self.send_message_to_websocket(websocket, message)
                        success_count += 1
                        self.logger.info(f"Message sent to connection {i} for user {user_id}")
                        
                    except Exception as e:
                        self.logger.error(f"Error sending to user {user_id} connection {i}: {e}")
                        failed_connections.append(i)
                
                # Clean up failed connections
                if failed_connections:
                    self.logger.info(f"Cleaning up {len(failed_connections)} failed connections for user {user_id}")
                    # Remove failed connections from the list (in reverse order to maintain indices)
                    for i in reversed(failed_connections):
                        if i < len(user_websockets):
                            user_websockets.pop(i)
                    
                    # Update the user_connections dictionary
                    if user_websockets:
                        self.user_connections[user_id] = user_websockets
                    else:
                        del self.user_connections[user_id]
                        self.logger.info(f"Removed user {user_id} from connections (no active connections)")
                
                self.logger.info(f"Message sent to {success_count}/{len(user_websockets) + len(failed_connections)} connections for user {user_id}")
                return success_count > 0
            else:
                self.logger.error(f"No connections found for user_id: {user_id}")
                return False
        return False
    
    async def send_message_to_user_node(self, user_id, node_id, message):
        """Send message to a specific user on a specific node"""
        if hasattr(self, 'user_connections') and self.user_connections:
            user_websockets = self.user_connections.get(user_id, [])
            for websocket in user_websockets:
                # Check if this websocket belongs to the specified node
                if hasattr(websocket, 'node_id') and websocket.node_id == node_id:
                    await self.send_message_to_websocket(websocket, message)
                    self.logger.info(f"Message sent to user {user_id} on node {node_id}")
                    return True
            
            self.logger.error(f"No connection found for user {user_id} on node {node_id}")
            return False
        return False
    
    async def send_session_if_appropriate(self, user_id, websocket=None, is_reregistration=False):
        """Unified method to send session data with intelligent logout status checking"""
        try:
            self.logger.info(f"===== CHECKING FOR SAVED SESSION =====")
            self.logger.info(f"User ID: {user_id}")
            self.logger.info(f"Is re-registration: {is_reregistration}")
            
            with app.app_context():
                cookie = UserCookie.query.filter_by(user_id=user_id).first()
                if not cookie:
                    self.logger.info(f"No saved session found for user {user_id}")
                    return False
                
                self.logger.info(f"Found saved session for user {user_id}")
                
                # Check if user has logged out and if this is a legitimate reconnection
                user_account = UserAccount.query.filter_by(
                    user_id=user_id,
                    website='nsn'
                ).first()
                
                should_send_session = True
                if user_account and user_account.logout:
                    self.logger.info(f"User {user_id} had logged out (logout=True)")
                    self.logger.info(f"User is logged out, NOT sending auto-login")
                    self.logger.info(f"User must login manually to reset logout status")
                    self.logger.info(f"This prevents automatic re-login after logout")
                    should_send_session = False
                
                if should_send_session:
                    self.logger.info(f"Sending session to C-client")
                    # Extract channel_id and node_id from websocket attributes
                    channel_id = getattr(websocket, 'channel_id', None) if websocket else None
                    node_id = getattr(websocket, 'node_id', None) if websocket else None
                    
                    self.logger.info(f"Extracted channel_id: {channel_id}, node_id: {node_id}")
                    
                    # Check if cluster verification is required
                    if channel_id and node_id:
                        self.logger.info(f"🔍 ===== WEBSOCKET CLUSTER VERIFICATION REQUIRED =====")
                        self.logger.info(f"🔍 User ID: {user_id}")
                        self.logger.info(f"🔍 Channel ID: {channel_id}")
                        self.logger.info(f"🔍 Node ID: {node_id}")
                        self.logger.info(f"🔍 ===== STARTING CLUSTER VERIFICATION =====")
                        
                        # Perform cluster verification - query other nodes and verify with C-Client
                        try:
                            self.logger.info(f"===== STARTING CLUSTER VERIFICATION =====")
                            
                            # Create temporary instance for this verification (avoid multi-user confusion)
                            # This instance is only used for this verification flow: query C2 → query C1 → compare results
                            verification_instance = ClusterVerificationService(self, db)
                            
                            self.logger.info(f"🔍 Created temporary verification instance for this verification")
                            self.logger.info(f"🔍 Instance: {verification_instance}")
                            self.logger.info(f"🔍 Connection ID: {id(websocket)}")
                            
                            # Temporarily store instance for response routing
                            connection_id = id(websocket)
                            self.connection_cluster_verification[connection_id] = verification_instance
                            
                            try:
                                # Perform cluster verification using the temporary instance
                                verification_result = await verification_instance.verify_user_cluster(user_id, channel_id, node_id)
                            finally:
                                # Clean up temporary instance after verification
                                if connection_id in self.connection_cluster_verification:
                                    del self.connection_cluster_verification[connection_id]
                                    self.logger.info(f"🔍 Cleaned up temporary verification instance")
                            
                            self.logger.info(f"===== CLUSTER VERIFICATION COMPLETED =====")
                            self.logger.info(f"Verification Result: {verification_result}")
                            
                            # Save verification result to websocket connection for later use in session send
                            websocket.cluster_verification_result = verification_result
                            self.logger.info(f"Saved verification result to websocket connection")
                            
                            # Check verification result
                            if verification_result.get('success', False):
                                if verification_result.get('verification_passed', False):
                                    self.logger.info(f"===== CLUSTER VERIFICATION PASSED - SENDING SESSION =====")
                                    # Continue with normal session send (verification passed, continue sending session)
                                else:
                                    self.logger.warning(f"===== CLUSTER VERIFICATION FAILED - BLOCKING SESSION =====")
                                    # Block session send
                                    return False
                            else:
                                self.logger.warning(f"===== CLUSTER VERIFICATION ERROR - BLOCKING SESSION =====")
                                self.logger.warning(f"Error: {verification_result.get('message', 'Unknown error')}")
                                # Block session send on error
                                return False
                                
                        except Exception as e:
                            self.logger.error(f"===== CLUSTER VERIFICATION EXCEPTION =====")
                            self.logger.error(f"Exception: {e}")
                            self.logger.error(f"Traceback: {traceback.format_exc()}")
                            # Block session send on exception
                            return False
                    
                    # Verification passed or not required, send session to all connections
                    # Use app.py's send_session_to_client for consistency with bind_routes
                    # Note: DO NOT pass channel_id/node_id here - cluster verification is already done
                    send_result = await send_session_to_client(
                        user_id, 
                        cookie.cookie, 
                        None,  # nsn_user_id - will be extracted from cookie
                        None,  # nsn_username - will be extracted from cookie
                        website_root_path=self.get_nsn_root_url(),
                        website_name='NSN',
                        session_partition='persist:nsn',
                        reset_logout_status=False  # Already handled above
                        # DO NOT pass channel_id/node_id - verification already done, send to ALL connections
                    )
                    
                    if send_result:
                        self.logger.info(f"Session sent to all connections for user {user_id}")
                        return True
                    else:
                        self.logger.warning(f"Failed to send session to C-client for user {user_id}")
                        return False
                else:
                    self.logger.info(f"Skipping session send - preventing duplicate login")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error checking/sending saved session for user {user_id}: {e}")
        return False
    
    async def handle_c_client_reregistration(self, websocket, data):
        """Handle re-registration from existing C-Client connection"""
        try:
            client_id = data.get('client_id', 'unknown')
            user_id = data.get('user_id')
            username = data.get('username')
            node_id = data.get('node_id')
            domain_id = data.get('domain_id')
            cluster_id = data.get('cluster_id')
            channel_id = data.get('channel_id')
            
            self.logger.info(f"Processing re-registration for client {client_id}")
            self.logger.info(f"   New User ID: {user_id}")
            self.logger.info(f"   New Username: {username}")
            self.logger.info(f"   Node ID: {node_id}")
            
            # Check if username is a security code (new device login during re-registration)
            is_new_device_login = False
            security_code_record = None
            
            # Use dedicated security code logger
            from utils.logger import get_bclient_logger
            security_logger = get_bclient_logger('security_code')
            
            with app.app_context():
                from services.models import UserSecurityCode
                # Check if username matches a security_code
                security_code_record = UserSecurityCode.query.filter_by(security_code=username).first()
                
                if security_code_record:
                    security_logger.info(f"🔐 ===== NEW DEVICE LOGIN DETECTED (RE-REGISTRATION) =====")
                    security_logger.info(f"🔐 Re-registration with username: {username}")
                    security_logger.info(f"🔐 Username matches security code in database")
                    security_logger.info(f"🔐 Security code: {security_code_record.security_code}")
                    security_logger.info(f"🔐 Original user_id: {security_code_record.nmp_user_id}")
                    security_logger.info(f"🔐 Original username: {security_code_record.nmp_username}")
                    security_logger.info(f"🔐 Client ID: {client_id}")
                    
                    # Override with real user information
                    is_new_device_login = True
                    user_id = security_code_record.nmp_user_id
                    username = security_code_record.nmp_username
                    domain_id = security_code_record.domain_id
                    cluster_id = security_code_record.cluster_id
                    channel_id = security_code_record.channel_id
                    
                    security_logger.info(f"🔐 ===== OVERRIDING WITH REAL USER INFORMATION =====")
                    security_logger.info(f"🔐 Real user_id: {user_id}")
                    security_logger.info(f"🔐 Real username: {username}")
                    security_logger.info(f"🔐 Domain ID: {domain_id}")
                    security_logger.info(f"🔐 Cluster ID: {cluster_id}")
                    security_logger.info(f"🔐 Channel ID: {channel_id}")
                    
                    # For new device login, send registration_success with special flag
                    # and process as a new registration
                    security_logger.info(f"🔐 Processing as new device login registration")
                    
                    # Update data with real user info
                    data['user_id'] = user_id
                    data['username'] = username
                    data['domain_id'] = domain_id
                    data['cluster_id'] = cluster_id
                    data['channel_id'] = channel_id
                    data['_is_new_device_login'] = True  # Internal flag
                    data['_security_code_record'] = security_code_record  # Pass record for deletion
                    
                    # Call the registration processing method directly
                    # Pass start_message_loop=False because re-registration doesn't need a new message loop
                    await self._process_c_client_registration(websocket, data, start_message_loop=False)
                    return
            
            # Check for duplicate registration first
            if self.check_duplicate_registration(node_id, client_id, user_id, websocket):
                self.logger.info(f"Duplicate re-registration detected - same node_id, client_id, user_id")
                self.logger.info(f"Node: {node_id}, Client: {client_id}, User: {user_id}")
                
                # Find the existing connection
                existing_websocket = self.find_existing_connection(node_id, client_id, user_id)
                if existing_websocket and existing_websocket != websocket:
                    self.logger.info(f"Sending success response to existing connection")
                    
                    # Send success response to existing connection
                    await self.send_message_to_websocket(existing_websocket, {
                        'type': 'registration_success',
                        'client_id': client_id,
                        'user_id': user_id,
                        'username': username,
                        'message': 'Already registered with same credentials'
                    })
                    
                    self.logger.info(f"Duplicate re-registration response sent to existing connection")
                    
                    # Close the new connection since it's a duplicate
                    await websocket.close(code=1000, reason="Duplicate re-registration - using existing connection")
                    return
            
            # Check if this client is already connected
            if client_id in self.client_connections:
                existing_connections = self.client_connections[client_id]
                existing_websocket = existing_connections[0] if existing_connections else None
                
                if existing_websocket:
                    existing_node_id = getattr(existing_websocket, 'node_id', None)
                    
                    # If same node, update user info (re-registration)
                    if existing_node_id == node_id:
                        self.logger.info(f"Client {client_id} re-registering on same node {node_id}")
                        self.logger.info(f"Updating user info to {user_id} ({username})")
                        
                        # Update websocket metadata
                        existing_websocket.user_id = user_id
                        existing_websocket.username = username
                        existing_websocket.domain_id = domain_id
                        existing_websocket.cluster_id = cluster_id
                        existing_websocket.channel_id = channel_id
                        
                        # Update user connections pool based on new user_id
                        if user_id:
                            # First, remove from old user pool if exists
                            old_user_id = None
                            for uid, connections in list(self.user_connections.items()):
                                if existing_websocket in connections:
                                    old_user_id = uid
                                    connections.remove(existing_websocket)
                                    self.logger.info(f"Removed connection from old user pool: {uid}")
                                    # Clean up empty user connection lists
                                    if not connections:
                                        del self.user_connections[uid]
                                        self.logger.info(f"Removed empty user connection list for {uid}")
                                    break
                            
                            # CRITICAL FIX: Only reuse connection if it's still valid
                            if self.is_connection_valid(existing_websocket):
                                self.logger.info(f"Existing connection is still valid, reusing it")
                            
                            # Then add to new user pool
                            if user_id not in self.user_connections:
                                # New user - create new user pool
                                self.user_connections[user_id] = []
                                self.logger.info(f"Created new user pool for {user_id}")
                            
                            if existing_websocket not in self.user_connections[user_id]:
                                # Add connection to user pool
                                self.user_connections[user_id].append(existing_websocket)
                                self.logger.info(f"Added connection to user pool: {user_id} (total: {len(self.user_connections[user_id])})")
                            else:
                                self.logger.info(f"Connection already in user pool: {user_id}")
                        else:
                            self.logger.error(f"Existing connection is invalid (closed/logged out), closing new connection and not reusing")
                            # Close the new connection since we can't reuse the old one
                            await websocket.close(code=1000, reason="Existing connection invalid, not reusing")
                        return
                    else:
                        # Different node - reject
                        self.logger.error(f"Client {client_id} trying to connect to different node")
                        await self.send_message_to_websocket(websocket, {
                            'type': 'registration_rejected',
                            'client_id': client_id,
                            'message': f'Client already connected to different node: {existing_node_id}'
                        })
                        return
                else:
                    self.logger.error(f"No existing websocket found for client {client_id}")
            else:
                self.logger.error(f"Client {client_id} not found in client connections")
                
        except Exception as e:
            self.logger.error(f"Error handling re-registration: {e}")
    
    async def handle_client_user_switch(self, client_id, new_user_id, new_username, websocket):
        """Handle client switching to a different user - clean up previous user records"""
        if not client_id:
            return
            
        # Check if this client already has different users connected
        if client_id in self.client_connections:
            existing_connections = self.client_connections[client_id]
            for existing_websocket in existing_connections:
                if existing_websocket != websocket:
                    old_user_id = getattr(existing_websocket, 'user_id', None)
                    old_username = getattr(existing_websocket, 'username', None)
                    
                    if old_user_id and old_user_id != new_user_id:
                        self.logger.info(f"Client {client_id} switching from user {old_user_id} ({old_username}) to {new_user_id} ({new_username})")
                        self.logger.info(f"Starting cleanup for old user {old_user_id} from client {client_id}")
                        
                        # Remove old user from user connections pool
                        await self.remove_user_from_client(old_user_id, client_id)
                        self.logger.info(f"Cleanup completed for user {old_user_id} from client {client_id}")
    
    async def handle_node_user_switch(self, node_id, new_user_id, new_username, websocket):
        """Handle node switching to a different user - clean up previous user records"""
        if not node_id:
            return
            
        # Check if this node already has different users connected
        if node_id in self.node_connections:
            existing_connections = self.node_connections[node_id]
            for existing_websocket in existing_connections:
                if existing_websocket != websocket:
                    old_user_id = getattr(existing_websocket, 'user_id', None)
                    old_username = getattr(existing_websocket, 'username', None)
                    
                    if old_user_id and old_user_id != new_user_id:
                        self.logger.info(f"Node {node_id} has user {old_user_id} ({old_username}) and new user {new_user_id} ({new_username})")
                        self.logger.info(f"Allowing multiple users on same node - no cleanup needed")
    
    async def remove_user_from_client(self, user_id, client_id):
        """Remove user from a specific client in user connections pool"""
        self.logger.info(f"Attempting to remove user {user_id} from client {client_id}")
        
        if user_id in self.user_connections:
            # Find and remove the websocket for this specific client
            user_websockets = self.user_connections[user_id]
            websockets_to_remove = []
            
            self.logger.info(f"User {user_id} has {len(user_websockets)} connections")
            
            for websocket in user_websockets:
                if hasattr(websocket, 'client_id') and websocket.client_id == client_id:
                    websockets_to_remove.append(websocket)
                    self.logger.info(f"Found websocket for user {user_id} on client {client_id}")
            
            # Remove the websockets
            for websocket in websockets_to_remove:
                user_websockets.remove(websocket)
                self.logger.info(f"Removed user {user_id} from client {client_id}")
            
            # Clean up empty user connection lists
            if not user_websockets:
                del self.user_connections[user_id]
                self.logger.info(f"Removed empty user connection list for {user_id}")
                self.logger.info(f"User {user_id} completely removed from system")
            else:
                self.logger.info(f"User {user_id} still has {len(user_websockets)} connections on other clients")
        else:
            self.logger.warning(f"User {user_id} not found in user connections pool")
    
    async def remove_user_from_node(self, user_id, node_id):
        """Remove user from a specific node in user connections pool"""
        self.logger.info(f"Attempting to remove user {user_id} from node {node_id}")
        
        if user_id in self.user_connections:
            # Find and remove the websocket for this specific node
            user_websockets = self.user_connections[user_id]
            websockets_to_remove = []
            
            self.logger.info(f"User {user_id} has {len(user_websockets)} connections")
            
            for websocket in user_websockets:
                if hasattr(websocket, 'node_id') and websocket.node_id == node_id:
                    websockets_to_remove.append(websocket)
                    self.logger.info(f"Found websocket for user {user_id} on node {node_id}")
            
            # Remove the websockets
            for websocket in websockets_to_remove:
                user_websockets.remove(websocket)
                self.logger.info(f"Removed user {user_id} from node {node_id}")
            
            # Clean up empty user connection lists
            if not user_websockets:
                del self.user_connections[user_id]
                self.logger.info(f"Removed empty user connection list for {user_id}")
                self.logger.info(f"User {user_id} completely removed from system")
            else:
                self.logger.info(f"User {user_id} still has {len(user_websockets)} connections on other nodes")
        else:
            self.logger.warning(f"User {user_id} not found in user connections pool")
    

    async def notify_user_connected_on_another_client(self, user_id, username, new_client_id, new_node_id, existing_connections):
        """Notify existing connections that user logged in on another client/node"""
        self.logger.info(f"===== STARTING NOTIFICATION =====")
        self.logger.info(f"notify_user_connected_on_another_client called")
        self.logger.info(f"user_id: {user_id}")
        self.logger.info(f"username: {username}")
        self.logger.info(f"new_client_id: {new_client_id}")
        self.logger.info(f"new_node_id: {new_node_id}")
        self.logger.info(f"existing_connections count: {len(existing_connections)}")
        
        notification_message = {
            'type': 'user_connected_on_another_client',
            'user_id': user_id,
            'username': username,
            'new_client_id': new_client_id,
            'new_node_id': new_node_id,
            'message': f'User {username} has logged in on another client: {new_client_id} (node: {new_node_id})',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        self.logger.info(f"Notification message: {notification_message}")
        
        success_count = 0
        for i, websocket in enumerate(existing_connections):
            try:
                existing_client_id = getattr(websocket, 'client_id', 'unknown')
                existing_node_id = getattr(websocket, 'node_id', 'unknown')
                self.logger.info(f"Sending notification to connection {i+1}: client={existing_client_id}, node={existing_node_id}")
                
                await self.send_message_to_websocket(websocket, notification_message)
                success_count += 1
                self.logger.info(f"Successfully notified client {existing_client_id} (node {existing_node_id}) about user {user_id} login on client {new_client_id} (node {new_node_id})")
            except Exception as e:
                self.logger.error(f"Error notifying client about user login: {e}")
                self.logger.error(f"Traceback: {traceback.format_exc()}")
        
        self.logger.info(f"Notified {success_count}/{len(existing_connections)} existing connections about user {user_id} login on client {new_client_id} (node {new_node_id})")
        self.logger.info(f"===== NOTIFICATION COMPLETE =====")

    
    async def notify_user_connected_on_another_node(self, user_id, username, new_node_id, existing_connections):
        """Notify existing connections that user logged in on another node (legacy method)"""
        notification_message = {
            'type': 'user_connected_on_another_node',
            'user_id': user_id,
            'username': username,
            'new_node_id': new_node_id,
            'message': f'User {username} has logged in on another node: {new_node_id}',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        success_count = 0
        for websocket in existing_connections:
            try:
                await self.send_message_to_websocket(websocket, notification_message)
                success_count += 1
                self.logger.info(f"Notified node {getattr(websocket, 'node_id', 'unknown')} about user {user_id} login on {new_node_id}")
            except Exception as e:
                self.logger.error(f"Error notifying node about user login: {e}")
        
        self.logger.info(f"Notified {success_count}/{len(existing_connections)} existing connections about user {user_id} login on {new_node_id}")
    
    async def handle_node_offline(self, node_id):
        """Handle node offline - close all clients on this node and clean up users if needed"""
        self.logger.info(f"Node {node_id} going offline - starting cleanup...")
        
        if not hasattr(self, 'node_connections') or node_id not in self.node_connections:
            self.logger.warning(f"Node {node_id} not found in connections")
            return
        
        # Get all connections on this node
        node_connections = self.node_connections[node_id]
        self.logger.info(f"Found {len(node_connections)} connections on node {node_id}")
        
        # Collect all clients and users on this node
        clients_to_close = set()
        users_to_check = set()
        
        for websocket in node_connections:
            client_id = getattr(websocket, 'client_id', None)
            user_id = getattr(websocket, 'user_id', None)
            
            if client_id:
                clients_to_close.add(client_id)
            if user_id:
                users_to_check.add(user_id)
        
        self.logger.info(f"Found {len(clients_to_close)} clients to close: {list(clients_to_close)}")
        self.logger.info(f"Found {len(users_to_check)} users to check: {list(users_to_check)}")
        
        # Close all connections on this node
        for websocket in node_connections:
            try:
                await websocket.close(code=1000, reason="Node offline")
                self.logger.info(f"Closed connection on node {node_id}")
            except Exception as e:
                self.logger.error(f"Error closing connection: {e}")
        
        # Remove node from node connections pool
        del self.node_connections[node_id]
        self.logger.info(f"Removed node {node_id} from node connections pool")
        
        # Check each user to see if they should be cleaned up
        for user_id in users_to_check:
            await self.check_and_cleanup_user_if_orphaned(user_id, node_id)
        
        # Check each client to see if they should be cleaned up
        for client_id in clients_to_close:
            await self.check_and_cleanup_client_if_orphaned(client_id, node_id)
        
        self.logger.info(f"Node {node_id} offline cleanup completed")
    
    async def check_and_cleanup_user_if_orphaned(self, user_id, offline_node_id):
        """Check if user is only connected on the offline node, if so clean up"""
        self.logger.info(f"Checking if user {user_id} is orphaned after node {offline_node_id} offline...")
        
        if user_id not in self.user_connections:
            self.logger.warning(f"User {user_id} not found in user connections")
            return
        
        user_websockets = self.user_connections[user_id]
        remaining_connections = []
        
        # Check which connections are still active (not on the offline node)
        for websocket in user_websockets:
            websocket_node_id = getattr(websocket, 'node_id', None)
            if websocket_node_id != offline_node_id:
                remaining_connections.append(websocket)
        
        self.logger.info(f"User {user_id} has {len(remaining_connections)} remaining connections after node {offline_node_id} offline")
        
        if not remaining_connections:
            # User is orphaned, clean up
            self.logger.info(f"User {user_id} is orphaned, cleaning up...")
            del self.user_connections[user_id]
            self.logger.info(f"User {user_id} completely removed from system")
        else:
            # User still has connections, update the list
            self.user_connections[user_id] = remaining_connections
            self.logger.info(f"User {user_id} still has {len(remaining_connections)} active connections")
    
    async def check_and_cleanup_client_if_orphaned(self, client_id, offline_node_id):
        """Check if client is only connected on the offline node, if so clean up"""
        self.logger.info(f"Checking if client {client_id} is orphaned after node {offline_node_id} offline...")
        
        if client_id not in self.client_connections:
            self.logger.warning(f"Client {client_id} not found in client connections")
            return
        
        client_websockets = self.client_connections[client_id]
        remaining_connections = []
        
        # Check which connections are still active (not on the offline node)
        for websocket in client_websockets:
            websocket_node_id = getattr(websocket, 'node_id', None)
            if websocket_node_id != offline_node_id:
                remaining_connections.append(websocket)
        
        self.logger.info(f"Client {client_id} has {len(remaining_connections)} remaining connections after node {offline_node_id} offline")
        
        if not remaining_connections:
            # Client is orphaned, clean up
            self.logger.info(f"Client {client_id} is orphaned, cleaning up...")
            del self.client_connections[client_id]
            self.logger.info(f"Client {client_id} completely removed from system")
        else:
            # Client still has connections, update the list
            self.client_connections[client_id] = remaining_connections
            self.logger.info(f"Client {client_id} still has {len(remaining_connections)} active connections")

    def check_duplicate_registration(self, node_id, client_id, user_id, new_websocket):
        """Check if a registration with the same node_id, client_id, and user_id already exists and is still valid"""
        self.logger.info(f"Checking for duplicate registration...")
        self.logger.info(f"Node: {node_id}, Client: {client_id}, User: {user_id}")
        
        # Check in all connection pools
        if hasattr(self, 'node_connections') and self.node_connections:
            for nid, connections in self.node_connections.items():
                if nid == node_id:
                    for conn in connections:
                        if (conn != new_websocket and 
                            getattr(conn, 'client_id', None) == client_id and 
                            getattr(conn, 'user_id', None) == user_id):
                            # Check if the existing connection is still valid
                            if self.is_connection_valid(conn):
                                self.logger.info(f"Found valid duplicate in node connections")
                                return True
                            else:
                                self.logger.info(f"Found invalid duplicate in node connections, will allow new connection")
                                # Remove invalid connection from pool
                                self.remove_invalid_connection(conn)
        
        if hasattr(self, 'client_connections') and self.client_connections:
            if client_id in self.client_connections:
                for conn in self.client_connections[client_id]:
                    if (conn != new_websocket and 
                        getattr(conn, 'node_id', None) == node_id and 
                        getattr(conn, 'user_id', None) == user_id):
                        # Check if the existing connection is still valid
                        if self.is_connection_valid(conn):
                            self.logger.info(f"Found valid duplicate in client connections")
                            return True
                        else:
                            self.logger.info(f"Found invalid duplicate in client connections, will allow new connection")
                            # Remove invalid connection from pool
                            self.remove_invalid_connection(conn)
        
        if hasattr(self, 'user_connections') and self.user_connections:
            if user_id in self.user_connections:
                for conn in self.user_connections[user_id]:
                    if (conn != new_websocket and 
                        getattr(conn, 'node_id', None) == node_id and 
                        getattr(conn, 'client_id', None) == client_id):
                        # Check if the existing connection is still valid
                        if self.is_connection_valid(conn):
                            self.logger.info(f"Found valid duplicate in user connections")
                            return True
                        else:
                            self.logger.info(f"Found invalid duplicate in user connections, will allow new connection")
                            # Remove invalid connection from pool
                            self.remove_invalid_connection(conn)
        
        self.logger.info(f"No valid duplicate registration found")
        return False
    
    def is_connection_valid(self, websocket):
        """Check if a WebSocket connection is still valid"""
        try:
            # CRITICAL: If logout is in progress, keep connection valid during the brief sending window
            if hasattr(websocket, '_logout_in_progress'):
                self.logger.debug(f"🔍 Connection has logout in progress, keeping valid during message send")
                return True
            
            # CRITICAL: If logout feedback tracking is active, keep connection valid
            # to prevent cleanup from removing it before feedback arrives
            if hasattr(websocket, '_logout_feedback_tracking'):
                self.logger.debug(f"🔍 Connection has logout feedback tracking, keeping valid during feedback wait")
                return True
            
            # Check if connection was marked as closed by logout
            if hasattr(websocket, '_closed_by_logout') and websocket._closed_by_logout:
                self.logger.debug(f"🔍 Connection invalid: marked as closed by logout")
                return False
            
            # Check WebSocket closed attribute
            if hasattr(websocket, 'closed') and websocket.closed:
                self.logger.debug(f"🔍 Connection invalid: websocket.closed = True")
                return False
            
            # Check connection state - use multiple methods for reliability
            connection_valid = True
            
            # Method 1: Check websockets state attribute
            if hasattr(websocket, 'state'):
                state_value = websocket.state
                state_name = websocket.state.name if hasattr(websocket.state, 'name') else str(websocket.state)
                
                self.logger.debug(f"🔍 Connection state: {state_name} (value: {state_value})")
                
                # Check state value (3 = CLOSED, 2 = CLOSING)
                if state_value in [2, 3] or state_name in ['CLOSED', 'CLOSING']:
                    self.logger.debug(f"🔍 Connection invalid: state is {state_name}")
                    connection_valid = False
            
            # Method 2: Check close_code
            if hasattr(websocket, 'close_code') and websocket.close_code is not None:
                self.logger.debug(f"🔍 Connection invalid: close_code = {websocket.close_code}")
                connection_valid = False
            
            # Method 3: Check _closed attribute
            try:
                if hasattr(websocket, '_closed') and websocket._closed:
                    self.logger.debug(f"🔍 Connection invalid: _closed = True")
                    connection_valid = False
            except Exception as e:
                self.logger.debug(f"🔍 Connection invalid: exception checking _closed: {e}")
                connection_valid = False
            
            # Log the final result
            if connection_valid:
                self.logger.debug(f"🔍 ✅ Connection is valid")
            else:
                self.logger.debug(f"🔍 ❌ Connection is invalid")
            
            return connection_valid
            
        except Exception as e:
            self.logger.debug(f"🔍 ❌ Connection invalid: exception in validation: {e}")
            return False
    
    def cleanup_invalid_connections(self):
        """Clean up invalid connections from all pools"""
        total_removed = 0
        
        # Clean up node connections
        if hasattr(self, 'node_connections') and self.node_connections:
            for node_id, connections in list(self.node_connections.items()):
                invalid_connections = [ws for ws in connections if not self.is_connection_valid(ws)]
                for ws in invalid_connections:
                    connections.remove(ws)
                    total_removed += 1
                
                if not connections:
                    del self.node_connections[node_id]
        
        # Clean up user connections
        if hasattr(self, 'user_connections') and self.user_connections:
            for user_id, connections in list(self.user_connections.items()):
                invalid_connections = [ws for ws in connections if not self.is_connection_valid(ws)]
                for ws in invalid_connections:
                    connections.remove(ws)
                    total_removed += 1
                
                if not connections:
                    del self.user_connections[user_id]
        
        # Clean up client connections
        if hasattr(self, 'client_connections') and self.client_connections:
            for client_id, connections in list(self.client_connections.items()):
                invalid_connections = [ws for ws in connections if not self.is_connection_valid(ws)]
                for ws in invalid_connections:
                    connections.remove(ws)
                    total_removed += 1
                
                if not connections:
                    del self.client_connections[client_id]
        
        # Only log if connections were actually removed
        if total_removed > 0:
            self.logger.info(f"Cleaned up {total_removed} invalid connections")
    
    def remove_invalid_connection(self, websocket):
        """Remove an invalid connection from all connection pools"""
        try:
            self.logger.info(f"🔌 ===== REMOVING INVALID CONNECTION =====")
            self.logger.info(f"🔌 WebSocket object: {websocket}")
            self.logger.info(f"🔌 Connection attributes: node_id={getattr(websocket, 'node_id', 'None')}, user_id={getattr(websocket, 'user_id', 'None')}, client_id={getattr(websocket, 'client_id', 'None')}")
            
            # Log current pool states before removal
            self.logger.info(f"🔌 Pool states BEFORE removal:")
            self.logger.info(f"🔌   node_connections: {len(self.node_connections)} nodes - {list(self.node_connections.keys())}")
            self.logger.info(f"🔌   user_connections: {len(self.user_connections)} users - {list(self.user_connections.keys())}")
            self.logger.info(f"🔌   client_connections: {len(self.client_connections)} clients - {list(self.client_connections.keys())}")
            
            removed_from = []
            
            # Remove from node_connections
            if hasattr(self, 'node_connections'):
                for node_id, connections in list(self.node_connections.items()):
                    if websocket in connections:
                        connections.remove(websocket)
                        removed_from.append(f"node_{node_id}")
                        self.logger.info(f"🔌 ✅ Removed from node {node_id}")
                        if not connections:
                            del self.node_connections[node_id]
                            self.logger.info(f"🔌 ✅ Removed empty node {node_id}")
            
            # Remove from client_connections
            if hasattr(self, 'client_connections'):
                for client_id, connections in list(self.client_connections.items()):
                    if websocket in connections:
                        connections.remove(websocket)
                        removed_from.append(f"client_{client_id}")
                        self.logger.info(f"🔌 ✅ Removed from client {client_id}")
                        if not connections:
                            del self.client_connections[client_id]
                            self.logger.info(f"🔌 ✅ Removed empty client {client_id}")
            
            # Remove from user_connections
            if hasattr(self, 'user_connections'):
                for user_id, connections in list(self.user_connections.items()):
                    if websocket in connections:
                        connections.remove(websocket)
                        removed_from.append(f"user_{user_id}")
                        self.logger.info(f"🔌 ✅ Removed from user {user_id}")
                        if not connections:
                            del self.user_connections[user_id]
                            self.logger.info(f"🔌 ✅ Removed empty user {user_id}")
            
            # Log current pool states after removal
            self.logger.info(f"🔌 Pool states AFTER removal:")
            self.logger.info(f"🔌   node_connections: {len(self.node_connections)} nodes - {list(self.node_connections.keys())}")
            self.logger.info(f"🔌   user_connections: {len(self.user_connections)} users - {list(self.user_connections.keys())}")
            self.logger.info(f"🔌   client_connections: {len(self.client_connections)} clients - {list(self.client_connections.keys())}")
            self.logger.info(f"🔌 Removed from: {removed_from}")
            self.logger.info(f"🔌 ===== END REMOVING INVALID CONNECTION =====")
            
        except Exception as e:
            self.logger.error(f"🔌 ❌ Error removing invalid connection: {e}")
            self.logger.error(f"🔌 ❌ Traceback: {traceback.format_exc()}")
    
    def find_existing_connection(self, node_id, client_id, user_id):
        """Find existing connection with the same node_id, client_id, and user_id"""
        self.logger.info(f"Finding existing connection...")
        self.logger.info(f"Node: {node_id}, Client: {client_id}, User: {user_id}")
        
        # Search in all connection pools
        if hasattr(self, 'node_connections') and self.node_connections:
            for nid, connections in self.node_connections.items():
                if nid == node_id:
                    for conn in connections:
                        if (getattr(conn, 'client_id', None) == client_id and 
                            getattr(conn, 'user_id', None) == user_id):
                            self.logger.info(f"Found existing connection in node connections")
                            return conn
        
        if hasattr(self, 'client_connections') and self.client_connections:
            if client_id in self.client_connections:
                for conn in self.client_connections[client_id]:
                    if (getattr(conn, 'node_id', None) == node_id and 
                        getattr(conn, 'user_id', None) == user_id):
                        self.logger.info(f"Found existing connection in client connections")
                        return conn
        
        if hasattr(self, 'user_connections') and self.user_connections:
            if user_id in self.user_connections:
                for conn in self.user_connections[user_id]:
                    if (getattr(conn, 'node_id', None) == node_id and 
                        getattr(conn, 'client_id', None) == client_id):
                        self.logger.info(f"Found existing connection in user connections")
                        return conn
        
        self.logger.info(f"No existing connection found")
        return None

    async def remove_connection_from_all_pools(self, websocket):
        """Remove connection from all connection pools"""
        removed_from = []
        
        # Get connection info before removal
        node_id = getattr(websocket, 'node_id', 'unknown')
        user_id = getattr(websocket, 'user_id', 'unknown')
        username = getattr(websocket, 'username', 'unknown')
        
        self.logger.info(f"Connection disconnected - Node: {node_id}, User: {user_id} ({username})")
        
        # Remove from node connections pool
        if hasattr(self, 'node_connections') and self.node_connections:
            for node_id_key, connections in list(self.node_connections.items()):
                if websocket in connections:
                    connections.remove(websocket)
                    removed_from.append(f"node({node_id_key})")
                    self.logger.info(f"Removed from node connections: {node_id_key}")
                    # Clean up empty node connection lists
                    if not connections:
                        del self.node_connections[node_id_key]
                        self.logger.info(f"Removed empty node connection list for {node_id_key}")
                    break
        
        # Remove from user connections pool
        if hasattr(self, 'user_connections') and self.user_connections:
            for user_id_key, websockets in list(self.user_connections.items()):
                if websocket in websockets:
                    websockets.remove(websocket)
                    removed_from.append(f"user({user_id_key})")
                    self.logger.info(f"Removed from user connections: {user_id_key}")
                    # Clean up empty user connection lists
                    if not websockets:
                        del self.user_connections[user_id_key]
                        self.logger.info(f"Removed empty user connection list for {user_id_key}")
                    break
        
        # Remove from client connections pool
        if hasattr(self, 'client_connections') and self.client_connections:
            for client_id_key, websockets in list(self.client_connections.items()):
                if websocket in websockets:
                    websockets.remove(websocket)
                    removed_from.append(f"client({client_id_key})")
                    self.logger.info(f"Removed from client connections: {client_id_key}")
                    # Clean up empty client connection lists
                    if not websockets:
                        del self.client_connections[client_id_key]
                        self.logger.info(f"Removed empty client connection list for {client_id_key}")
                    break
        
        # Sync disconnection to NodeManager using the new comprehensive method
        if removed_from:
            try:
                self.logger.info(f"🔗 Starting NodeManager disconnection sync...")
                sync_success = await self._sync_disconnection_to_nodemanager(websocket)
                
                if sync_success:
                    self.logger.info(f"🔗 ✅ NodeManager disconnection sync successful")
                else:
                    self.logger.warning(f"🔗 ⚠️ NodeManager disconnection sync failed or skipped")
            except Exception as e:
                self.logger.error(f"🔗 ❌ Error in NodeManager disconnection sync: {e}")
                self.logger.error(f"🔗 ❌ Traceback: {traceback.format_exc()}")
        else:
            self.logger.info(f"No connections removed, skipping NodeManager notification")
        
        if removed_from:
            self.logger.info(f"Connection cleanup completed from: {', '.join(removed_from)}")
            self.logger.info(f"Remaining nodes: {list(self.node_connections.keys()) if hasattr(self, 'node_connections') else []}")
            self.logger.info(f"Remaining users: {list(self.user_connections.keys()) if hasattr(self, 'user_connections') else []}")
            self.logger.info(f"Remaining clients: {list(self.client_connections.keys()) if hasattr(self, 'client_connections') else []}")
        else:
            self.logger.warning(f"Connection not found in any pool")
    
    async def broadcast_to_c_clients(self, message):
        """Broadcast message to all connected C-Clients"""
        if hasattr(self, 'node_connections') and self.node_connections:
            for node_id, connections in self.node_connections.items():
                for websocket in connections:
                    try:
                        await self.send_message_to_websocket(websocket, message)
                    except Exception as e:
                        self.logger.error(f"Error broadcasting to node {node_id}: {e}")
    
    async def send_error(self, websocket, error_message):
        """Send error message to websocket"""
        error_response = {
            'type': 'error',
            'message': error_message,
            'timestamp': datetime.utcnow().isoformat()
        }
        await self.send_message_to_websocket(websocket, error_response)
    
    def get_connection_info(self):
        """Get information about all connected C-Clients with dual pool support - only valid connections"""
        # Clean up invalid connections before getting info
        self.cleanup_invalid_connections()
        
        # Get node connections info - only valid connections
        node_connections_info = []
        if hasattr(self, 'node_connections') and self.node_connections:
            self.logger.info(f"🔍 ===== GETTING NODE CONNECTIONS INFO =====")
            self.logger.info(f"🔍 Total nodes in pool: {len(self.node_connections)}")
            for node_id, connections in self.node_connections.items():
                self.logger.info(f"🔍 Node {node_id}: {len(connections)} total connections")
                valid_count = 0
                for websocket in connections:
                    # Only include valid connections
                    if self.is_connection_valid(websocket):
                        valid_count += 1
                        connection_info = {
                            'node_id': node_id,
                            'user_id': getattr(websocket, 'user_id', None),
                            'client_id': getattr(websocket, 'client_id', None),
                            'username': getattr(websocket, 'username', None),
                            'domain_id': getattr(websocket, 'domain_id', None),
                            'cluster_id': getattr(websocket, 'cluster_id', None),
                            'channel_id': getattr(websocket, 'channel_id', None),
                            'remote_address': str(websocket.remote_address) if hasattr(websocket, 'remote_address') else 'unknown'
                        }
                        node_connections_info.append(connection_info)
                        self.logger.info(f"🔍 ✅ Added connection info for node {node_id}, user {getattr(websocket, 'user_id', 'None')}")
                    else:
                        self.logger.info(f"🔍 ❌ Skipped invalid connection for node {node_id}, user {getattr(websocket, 'user_id', 'None')}")
                self.logger.info(f"🔍 Node {node_id}: {valid_count}/{len(connections)} valid connections")
            self.logger.info(f"🔍 Total node_connections_info: {len(node_connections_info)}")
        
        # Get node connections summary - only valid connections
        node_connections = {}
        if hasattr(self, 'node_connections') and self.node_connections:
            self.logger.info(f"🔍 ===== GETTING NODE CONNECTIONS SUMMARY =====")
            self.logger.info(f"🔍 Total nodes in pool: {len(self.node_connections)}")
            for node_id, connections in self.node_connections.items():
                self.logger.info(f"🔍 Node {node_id}: {len(connections)} total connections")
                # Filter to only valid connections
                valid_connections = [ws for ws in connections if self.is_connection_valid(ws)]
                self.logger.info(f"🔍 Node {node_id}: {len(valid_connections)} valid connections")
                if valid_connections:  # Only include nodes with valid connections
                    node_connections[node_id] = {
                        'connection_count': len(valid_connections),
                        'users': [getattr(ws, 'user_id', None) for ws in valid_connections],
                        'clients': [getattr(ws, 'client_id', None) for ws in valid_connections],
                        'usernames': list(set([getattr(ws, 'username', None) for ws in valid_connections if hasattr(ws, 'username')]))
                    }
                    self.logger.info(f"🔍 ✅ Node {node_id} included in summary")
                else:
                    self.logger.info(f"🔍 ❌ Node {node_id} excluded from summary (no valid connections)")
            self.logger.info(f"🔍 Final node_connections: {len(node_connections)} nodes")
        
        # Get user connections summary - only valid connections
        user_connections = {}
        if hasattr(self, 'user_connections') and self.user_connections:
            for user_id, websockets in self.user_connections.items():
                # Filter to only valid connections
                valid_websockets = [ws for ws in websockets if self.is_connection_valid(ws)]
                if valid_websockets:  # Only include users with valid connections
                    user_connections[user_id] = {
                        'connection_count': len(valid_websockets),
                        'nodes': [getattr(ws, 'node_id', None) for ws in valid_websockets if hasattr(ws, 'node_id')],
                        'clients': [getattr(ws, 'client_id', None) for ws in valid_websockets if hasattr(ws, 'client_id')],
                        'usernames': list(set([getattr(ws, 'username', None) for ws in valid_websockets if hasattr(ws, 'username')]))
                    }
        
        # Get client connections summary - only valid connections
        client_connections = {}
        if hasattr(self, 'client_connections') and self.client_connections:
            for client_id, websockets in self.client_connections.items():
                # Filter to only valid connections
                valid_websockets = [ws for ws in websockets if self.is_connection_valid(ws)]
                if valid_websockets:  # Only include clients with valid connections
                    client_connections[client_id] = {
                        'connection_count': len(valid_websockets),
                        'users': [getattr(ws, 'user_id', None) for ws in valid_websockets if hasattr(ws, 'user_id')],
                        'nodes': [getattr(ws, 'node_id', None) for ws in valid_websockets if hasattr(ws, 'node_id')],
                        'usernames': list(set([getattr(ws, 'username', None) for ws in valid_websockets if hasattr(ws, 'username')]))
                    }
        
        return {
            'total_connections': len(node_connections_info),
            'node_connections_info': node_connections_info,
            'node_connections': node_connections,
            'user_connections': user_connections,
            'client_connections': client_connections,
            'summary': {
                'total_nodes': len(node_connections),
                'total_users': len(user_connections),
                'total_clients': len(client_connections),
                'total_connections': len(node_connections_info)
            }
        }
    
    async def disconnect(self):
        """Disconnect from C-Client WebSocket server"""
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False
            self.logger.info("Disconnected from C-Client WebSocket")
    
    async def send_message(self, message):
        """Send message to C-Client"""
        if self.websocket and self.is_connected:
            try:
                await self.websocket.send(json.dumps(message))
            except Exception as e:
                self.logger.error(f"Error sending message to C-Client: {e}")
                self.is_connected = False
    
    async def send_message_to_websocket(self, websocket, message):
        """Send message to specific WebSocket connection"""
        try:
            await websocket.send(json.dumps(message))
        except Exception as e:
            self.logger.error(f"Error sending message to WebSocket: {e}")
    
    
    async def update_cookie(self, user_id, username, cookie, auto_refresh=False):
        """Update cookie in C-Client"""
        message = {
            'type': 'cookie_update',
            'user_id': user_id,
            'username': username,
            'cookie': cookie,
            'auto_refresh': auto_refresh
        }
        # Send to all connections for this user
        await self.send_message_to_user(user_id, message)
    
    async def notify_user_login(self, user_id, username, session_data=None):
        """Notify C-Client of user login (deprecated - use send_session_to_client instead)"""
        # Note: This method is no longer used because send_session_to_client already
        # sends auto_login messages to all user connections. Calling this separately
        # would cause duplicate login messages and timing issues.
        message = {
            'type': 'user_login',
            'user_id': user_id,
            'username': username,
            'session_data': session_data or {}
        }
        # Send to all connections for this user
        await self.send_message_to_user(user_id, message)
    
    async def notify_user_logout(self, user_id, username, website_root_path=None, website_name=None, client_id=None):
        """Notify C-Client of user logout and wait for feedback"""
        # Get NSN logout URL from environment configuration
        nsn_logout_url = self.get_nsn_logout_url()
        
        message = {
            'type': 'user_logout',
            'user_id': user_id,
            'username': username,
            'website_config': {
                'root_path': website_root_path or self.get_nsn_root_url(),
                'name': website_name or 'NSN'
            },
            'logout_api': {
                'url': nsn_logout_url,
                'method': 'GET',
                'description': 'NSN logout endpoint for server-side session cleanup'
            }
        }
        
        # Send to all connections for this user and wait for feedback
        # If client_id is provided, only send to connections matching that client_id
        await self.send_message_to_user_with_feedback(user_id, message, client_id=client_id)
    
    async def send_message_to_user_with_feedback(self, user_id, message, timeout=None, client_id=None):
        """Send message to user and wait for ALL feedback before cleanup - 可靠的反馈机制"""
        
        self.logger.info(f"Sending logout message to user {user_id}" + (f" (client_id: {client_id})" if client_id else "") + " (WAITING FOR ALL FEEDBACK)...")
        
        # CRITICAL FIX: For logout operations, always check connections in real-time (no cache)
        user_websockets = self.get_cached_user_connections(user_id, use_cache=False)
        
        # Filter by client_id if provided (to only logout specific C-Client)
        if client_id:
            self.logger.info(f"Filtering connections by client_id: {client_id}")
            user_websockets = [ws for ws in user_websockets if getattr(ws, 'client_id', None) == client_id]
            self.logger.info(f"Found {len(user_websockets)} connections matching client_id {client_id}")
        
        if not user_websockets:
            self.logger.warning(f"No active connections for user {user_id}" + (f" with client_id {client_id}" if client_id else ""))
            # Double-check by looking directly in user_connections pool
            direct_connections = self.user_connections.get(user_id, [])
            if direct_connections:
                # Filter by client_id if provided
                if client_id:
                    direct_connections = [ws for ws in direct_connections if getattr(ws, 'client_id', None) == client_id]
                
                self.logger.info(f"Found {len(direct_connections)} connections in direct pool, but all are invalid")
                # Clean up invalid connections immediately
                if client_id:
                    # Only remove connections matching client_id
                    self.user_connections[user_id] = [ws for ws in self.user_connections[user_id] if getattr(ws, 'client_id', None) != client_id]
                else:
                    self.user_connections[user_id] = []
                
                if not self.user_connections[user_id]:
                    del self.user_connections[user_id]
            return
        
        self.logger.info(f"Sending logout message to {len(user_websockets)} connections")
        
        # IMPORTANT: Mark connections as "logging out" BEFORE sending logout message
        # Use a temporary flag to prevent session sends during logout
        for websocket in user_websockets:
            websocket._logout_in_progress = True
            self.logger.info(f"🔒 Marked connection as logout-in-progress (before sending message): {getattr(websocket, 'client_id', 'unknown')}")
        
        # Send logout message in parallel to all connections
        await self.send_logout_message_parallel(user_id, message, user_websockets)
        
        # Immediately after sending, mark as closed by logout
        # This ensures logout message is sent, but prevents future session sends
        for websocket in user_websockets:
            websocket._closed_by_logout = True
            if hasattr(websocket, '_logout_in_progress'):
                delattr(websocket, '_logout_in_progress')
            self.logger.info(f"🔒 Marked connection as closed by logout (after sending message): {getattr(websocket, 'client_id', 'unknown')}")
        
        # Set up feedback tracking mechanism
        feedback_received = {}
        for websocket in user_websockets:
            feedback_received[websocket] = False
        
        # Store feedback tracking to websocket object
        for websocket in user_websockets:
            websocket._logout_feedback_tracking = feedback_received
        
        self.logger.info(f"Waiting for logout feedback from {len(user_websockets)} connections...")
        
        # Wait for all feedback with longer timeout for stability
        timeout = timeout or 10  # 10 second timeout, ensure all C-Clients have time to respond
        start_time = asyncio.get_event_loop().time()
        check_interval = 0.1  # 100ms check interval
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            elapsed = asyncio.get_event_loop().time() - start_time
            
            # Check if all feedback has been received
            if all(feedback_received.values()):
                self.logger.info(f"All logout feedback received for user {user_id} in {elapsed:.2f}s")
                break
            
            # Show progress
            received_count = sum(1 for received in feedback_received.values() if received)
            self.logger.info(f"Received {received_count}/{len(user_websockets)} feedbacks ({elapsed:.1f}s)")
            
            # Wait for check interval
            await asyncio.sleep(check_interval)
        else:
            # Timeout handling
            missing_feedback = [ws for ws, received in feedback_received.items() if not received]
            self.logger.warning(f"Logout feedback timeout for user {user_id} after {timeout}s")
            self.logger.warning(f"   Missing feedback from {len(missing_feedback)} connections")
            self.logger.warning(f"   Proceeding with logout completion anyway...")
        
        # Clean up feedback tracking and sync to NodeManager
        for websocket in user_websockets:
            if hasattr(websocket, '_logout_feedback_tracking'):
                delattr(websocket, '_logout_feedback_tracking')
            
            # Connection already marked as _closed_by_logout above (before sending message)
            # Now sync to NodeManager pools
            try:
                await self._sync_connection_status_to_nodemanager_pools(websocket, 'closed_by_logout')
                self.logger.info(f"🔗 ✅ Connection status synced to NodeManager pools for {getattr(websocket, 'client_id', 'unknown')}")
            except Exception as e:
                self.logger.error(f"🔗 ❌ Error syncing connection status to NodeManager: {e}")
        
        self.logger.info(f"Logout notification process completed for user {user_id}")
        self.logger.info(f"All C-Client feedback received, connections marked as closed and synced to NodeManager")
    
    def get_cached_user_connections(self, user_id, use_cache=True):
        """Get cached user connections for faster access"""
        if use_cache and user_id in self.connection_cache:
            # Return cached connections if still valid
            cached_connections = self.connection_cache[user_id]
            valid_connections = [conn for conn in cached_connections if self.is_connection_valid_cached(conn)]
            
            if len(valid_connections) == len(cached_connections):
                return valid_connections
            else:
                # Update cache with valid connections
                self.connection_cache[user_id] = valid_connections
                return valid_connections
        
        # Fallback to direct lookup and cache the result
        user_connections = self.user_connections.get(user_id, [])
        if use_cache:
            valid_connections = [conn for conn in user_connections if self.is_connection_valid_cached(conn)]
            self.connection_cache[user_id] = valid_connections
        else:
            # CRITICAL FIX: For logout operations, always check connection validity in real-time
            valid_connections = [conn for conn in user_connections if self.is_connection_valid(conn)]
            self.logger.info(f"Real-time connection check for logout - found {len(valid_connections)}/{len(user_connections)} valid connections")
            for i, conn in enumerate(user_connections):
                is_valid = self.is_connection_valid(conn)
                connection_id = id(conn)
                self.logger.info(f"   Connection {i+1}: ID={connection_id}, Valid={is_valid}, State={getattr(conn, 'state', 'N/A')}, CloseCode={getattr(conn, 'close_code', 'N/A')}")
        return valid_connections
    
    def is_connection_valid_cached(self, websocket):
        """Check connection validity using cache"""
        websocket_id = id(websocket)
        
        # Check cache first
        if websocket_id in self.connection_validity_cache:
            cache_entry = self.connection_validity_cache[websocket_id]
            # Cache is valid for 5 seconds
            if time.time() - cache_entry['timestamp'] < 5:
                return cache_entry['valid']
        
        # Perform actual validation
        is_valid = self.is_connection_valid(websocket)
        
        # Cache the result
        self.connection_validity_cache[websocket_id] = {
            'valid': is_valid,
            'timestamp': time.time()
        }
        
        return is_valid
    
    def get_optimized_logout_timeout(self, user_id):
        """Get optimized timeout based on user logout history - NO FEEDBACK WAITING"""
        # Check if this is first logout for this user
        if not hasattr(self, 'user_logout_history'):
            self.user_logout_history = {}
        
        if user_id not in self.user_logout_history:
            # First logout - use ultra-fast timeout (just for message sending)
            self.user_logout_history[user_id] = 1
            self.logger.info(f"First logout for user {user_id} - using ultra-fast timeout")
            return self.logout_timeout_config['first_logout']
        else:
            # Subsequent logout - use ultra-fast timeout
            self.user_logout_history[user_id] += 1
            self.logger.info(f"Subsequent logout for user {user_id} - using ultra-fast timeout")
            return self.logout_timeout_config['subsequent_logout']
    
    async def send_logout_message_parallel(self, user_id, message, user_websockets):
        """Send logout message to all connections in parallel with delivery confirmation"""
        
        self.logger.info(f"Sending logout message in parallel to {len(user_websockets)} connections...")
        
        # Create tasks for parallel sending with delivery confirmation
        send_tasks = []
        for i, websocket in enumerate(user_websockets):
            task = asyncio.create_task(self.send_message_to_websocket_with_confirmation(websocket, message, i+1))
            send_tasks.append(task)
        
        # Wait for all messages to be sent with confirmation
        try:
            results = await asyncio.gather(*send_tasks, return_exceptions=True)
            
            # Count successful deliveries
            successful_deliveries = 0
            failed_deliveries = 0
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self.logger.error(f"Message delivery failed to connection {i+1}: {result}")
                    failed_deliveries += 1
                else:
                    self.logger.info(f"Message delivered to connection {i+1}")
                    successful_deliveries += 1
            
            self.logger.info(f"Delivery summary for user {user_id}")
            self.logger.info(f"   ✅ Successful deliveries: {successful_deliveries}")
            self.logger.info(f"   ❌ Failed deliveries: {failed_deliveries}")
            self.logger.info(f"   📤 Total connections: {len(user_websockets)}")
            
        except Exception as e:
            self.logger.error(f"Error in parallel message sending: {e}")
    
    async def send_message_to_websocket_with_confirmation(self, websocket, message, connection_id):
        """Send message to websocket with delivery confirmation"""
        try:
            # CRITICAL: Check connection validity BEFORE attempting to send
            if not self.is_connection_valid(websocket):
                self.logger.error(f"Connection {connection_id} is invalid before sending, skipping")
                self.logger.error(f"Connection {connection_id} validation failed:")
                self.logger.error(f"   - Connection state: {getattr(websocket, 'state', 'N/A')}")
                self.logger.error(f"   - Connection closed: {getattr(websocket, 'closed', 'N/A')}")
                self.logger.error(f"   - Close code: {getattr(websocket, 'close_code', 'N/A')}")
                return False
            
            # Add detailed connection state logging before sending
            self.logger.debug(f"===== CONNECTION STATE BEFORE SENDING ======")
            self.logger.debug(f"Connection {connection_id} state check:")
            self.logger.debug(f"   - WebSocket object: {websocket}")
            self.logger.debug(f"   - Connection state: {getattr(websocket, 'state', 'N/A')}")
            self.logger.debug(f"   - Connection closed: {getattr(websocket, 'closed', 'N/A')}")
            self.logger.debug(f"   - Close code: {getattr(websocket, 'close_code', 'N/A')}")
            self.logger.debug(f"   - Message type: {message.get('type', 'unknown')}")
            self.logger.debug(f"===== END CONNECTION STATE CHECK ======")
            
            await self.send_message_to_websocket(websocket, message)
            self.logger.info(f"Message sent to connection {connection_id}")
            
            # Add connection state logging after sending
            self.logger.debug(f"===== CONNECTION STATE AFTER SENDING ======")
            self.logger.debug(f"Connection {connection_id} state after send:")
            self.logger.debug(f"   - Connection state: {getattr(websocket, 'state', 'N/A')}")
            self.logger.debug(f"   - Connection closed: {getattr(websocket, 'closed', 'N/A')}")
            self.logger.debug(f"   - Close code: {getattr(websocket, 'close_code', 'N/A')}")
            self.logger.debug(f"===== END POST-SEND STATE CHECK ======")
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to send message to connection {connection_id}: {e}")
            self.logger.error(f"Exception type: {type(e)}")
            self.logger.error(f"Exception details: {str(e)}")
            # Add connection state logging after exception
            self.logger.debug(f"===== CONNECTION STATE AFTER EXCEPTION ======")
            self.logger.debug(f"Connection {connection_id} state after exception:")
            self.logger.debug(f"   - Connection state: {getattr(websocket, 'state', 'N/A')}")
            self.logger.debug(f"   - Connection closed: {getattr(websocket, 'closed', 'N/A')}")
            self.logger.debug(f"   - Close code: {getattr(websocket, 'close_code', 'N/A')}")
            self.logger.debug(f"===== END EXCEPTION STATE CHECK ======")
            raise e
    
    async def handle_logout_feedback(self, websocket, data, client_id, user_id):
        """Handle logout feedback from C-Client"""
        try:
            success = data.get('success', False)
            message = data.get('message', 'No message')
            timestamp = data.get('timestamp')
            immediate = data.get('immediate', False)
            feedback_client_id = data.get('client_id', 'unknown')
            
            self.logger.info(f"===== LOGOUT FEEDBACK RECEIVED =====")
            self.logger.info(f"   Client ID: {client_id}")
            self.logger.info(f"   Feedback Client ID: {feedback_client_id}")
            self.logger.info(f"   User ID: {user_id}")
            self.logger.info(f"   Success: {success}")
            self.logger.info(f"   Message: {message}")
            self.logger.info(f"   Immediate: {immediate}")
            self.logger.info(f"   Timestamp: {timestamp}")
            
            # CRITICAL FIX: Find feedback tracking using ALL connections for this user
            # (including ones that may have already disconnected)
            feedback_marked = False
            
            # First, try to find in current active connections
            user_websockets = self.user_connections.get(user_id, [])
            for i, ws in enumerate(user_websockets):
                # Match by client_id (more reliable than websocket object reference)
                if hasattr(ws, 'client_id') and ws.client_id == feedback_client_id:
                    self.logger.info(f"Logout feedback matched to active connection {i} for user {user_id}")
                    
                    # Mark feedback as received in tracking dict
                    if hasattr(ws, '_logout_feedback_tracking'):
                        ws._logout_feedback_tracking[ws] = True
                        self.logger.info(f"IMMEDIATELY marked logout feedback as received")
                        feedback_marked = True
                        
                        # Show current feedback progress
                        total_connections = len(ws._logout_feedback_tracking)
                        received_count = sum(1 for received in ws._logout_feedback_tracking.values() if received)
                        self.logger.info(f"Feedback progress: {received_count}/{total_connections} received")
                    break
            
            # If not found in active connections, check if ANY connection has the tracking dict
            # This handles cases where C-Client disconnected before B-Client processed feedback
            if not feedback_marked:
                self.logger.info(f"Connection for {feedback_client_id} not in active list, checking tracking dicts...")
                
                # Check all connections to find the one with tracking dict
                for ws_list in self.user_connections.values():
                    for ws in ws_list:
                        if hasattr(ws, '_logout_feedback_tracking'):
                            # Mark feedback as received for THIS client_id
                            # Use client_id matching instead of websocket object matching
                            for tracked_ws in ws._logout_feedback_tracking.keys():
                                if hasattr(tracked_ws, 'client_id') and tracked_ws.client_id == feedback_client_id:
                                    ws._logout_feedback_tracking[tracked_ws] = True
                                    self.logger.info(f"IMMEDIATELY marked logout feedback as received (via tracking dict)")
                                    feedback_marked = True
                                    
                                    total_connections = len(ws._logout_feedback_tracking)
                                    received_count = sum(1 for received in ws._logout_feedback_tracking.values() if received)
                                    self.logger.info(f"Feedback progress: {received_count}/{total_connections} received")
                                    break
                            if feedback_marked:
                                break
                    if feedback_marked:
                        break
            
            if feedback_marked:
                if success:
                    self.logger.info(f"Logout completed successfully on C-Client {client_id}")
                else:
                    self.logger.warning(f"Logout failed on C-Client {client_id}: {message}")
                
                # If immediate feedback, trigger fast completion
                if immediate:
                    self.logger.info(f"Immediate feedback detected from {feedback_client_id}")
            else:
                self.logger.warning(f"Received logout feedback from unknown connection for user {user_id}")
                self.logger.warning(f"Could not find tracking dict for client_id: {feedback_client_id}")
                
        except Exception as e:
            self.logger.error(f"Error handling logout feedback: {e}")
    
    async def handle_session_feedback(self, websocket, data, client_id, user_id):
        """Handle session feedback from C-Client"""
        try:
            success = data.get('success', False)
            message = data.get('message', 'No message')
            timestamp = data.get('timestamp')
            
            self.logger.info(f"===== SESSION FEEDBACK RECEIVED =====")
            self.logger.info(f"   Client ID: {client_id}")
            self.logger.info(f"   User ID: {user_id}")
            self.logger.info(f"   Success: {success}")
            self.logger.info(f"   Message: {message}")
            self.logger.info(f"   Timestamp: {timestamp}")
            
            # Mark this connection's feedback as received
            if hasattr(websocket, '_session_feedback_tracking'):
                # Update the shared feedback tracking dictionary
                feedback_dict = websocket._session_feedback_tracking
                feedback_dict[websocket] = True
                self.logger.info(f"Marked session feedback as received for this connection")
                self.logger.info(f"Feedback tracking status: {sum(feedback_dict.values())} / {len(feedback_dict)} received")
            else:
                self.logger.warning(f"No feedback tracking found for this connection, feedback may be ignored")
            
            if success:
                self.logger.info(f"Session processing completed successfully on C-Client {client_id}")
            else:
                self.logger.warning(f"Session processing failed on C-Client {client_id}: {message}")
                
        except Exception as e:
            self.logger.error(f"Error handling session feedback: {e}")
    
    def get_nsn_logout_url(self):
        """Get NSN logout URL based on current environment"""
        # Use the config manager instead of directly reading config file
        from utils.config_manager import get_nsn_base_url
        return f"{get_nsn_base_url()}/logout"
    
    def get_nsn_root_url(self):
        """Get NSN root URL based on current environment"""
        # Use the config manager instead of directly reading config file
        from utils.config_manager import get_nsn_base_url
        base_url = get_nsn_base_url()
        return base_url if base_url.endswith('/') else f"{base_url}/"
    
    async def sync_session(self, user_id, session_data):
        """Sync session data with C-Client"""
        message = {
            'type': 'session_sync',
            'user_id': user_id,
            'session_data': session_data
        }
        # Send to all connections for this user
        await self.send_message_to_user(user_id, message)
    
    async def send_session_to_client(self, user_id, session_data):
        """Send session data to C-Client for auto-login"""
        try:
            # Check total number of users in WebSocket user pool
            total_users = len(self.user_connections) if hasattr(self, 'user_connections') else 0
            self.logger.info(f"🔍 [Session Send] Total users in WebSocket pool: {total_users}")
            
            # Find WebSocket connections for this user
            if user_id in self.user_connections:
                connections = self.user_connections[user_id]
                self.logger.info(f"Found {len(connections)} connections for user {user_id}")
                
                # Only add message field for validation scenarios (multiple users)
                # Send session data to all connections for this user
                for websocket in connections:
                    try:
                        message = {
                            'type': 'auto_login',
                            'user_id': user_id,
                            'session_data': session_data
                        }
                        
                        # Only add message field for validation scenarios
                        if total_users > 1:
                            message['message'] = 'login success with validation'
                            self.logger.info(f"🔍 [Session Send] Multiple users detected ({total_users}), adding validation message")
                        else:
                            self.logger.info(f"🔍 [Session Send] Single user detected ({total_users}), no message field needed")
                        
                        await websocket.send(json.dumps(message))
                        self.logger.info(f"Session data sent to C-Client for user {user_id}")
                    except Exception as e:
                        self.logger.error(f"Failed to send session to C-Client: {e}")
            else:
                self.logger.warning(f"No WebSocket connections found for user {user_id}")
                
        except Exception as e:
            self.logger.error(f"Error sending session to C-Client: {e}")
    
    async def handle_security_code_request(self, websocket, data, client_id, user_id):
        """Handle security code request from C-Client for another device login"""
        try:
            # Use dedicated security code logger
            from utils.logger import get_bclient_logger
            security_logger = get_bclient_logger('security_code')
            
            security_logger.info(f"📱 ===== SECURITY CODE REQUEST =====")
            security_logger.info(f"📱 From C-Client: {client_id}")
            security_logger.info(f"📱 User ID: {user_id}")
            security_logger.info(f"📱 Request message: {data}")
            
            # Extract actual data from message
            request_data = data.get('data', {})
            security_logger.info(f"📱 Request data: {request_data}")
            
            nmp_user_id = request_data.get('nmp_user_id')
            nmp_username = request_data.get('nmp_username')
            domain_id = request_data.get('domain_id')
            cluster_id = request_data.get('cluster_id')
            channel_id = request_data.get('channel_id')
            
            if not nmp_user_id or not nmp_username:
                security_logger.error("📱 Missing required fields: nmp_user_id or nmp_username")
                await self.send_security_code_response(websocket, False, "Missing required fields")
                return
            
            security_logger.info(f"📱 User hierarchy from C-Client: domain={domain_id}, cluster={cluster_id}, channel={channel_id}")
            
            # Import models
            from services.models import UserSecurityCode
            
            # Use application context for database operations (app is injected globally)
            with app.app_context():
                # Check if user already has a security code
                existing_code = UserSecurityCode.query.filter_by(nmp_user_id=nmp_user_id).first()
                
                if existing_code:
                    security_logger.info(f"📱 Found existing security code for user {nmp_username}")
                    await self.send_security_code_response(
                        websocket, 
                        True, 
                        "Security code retrieved",
                        existing_code.security_code,
                        existing_code.nmp_username,
                        existing_code.domain_id,
                        existing_code.cluster_id,
                        existing_code.channel_id
                    )
                else:
                    # Generate new 8-character security code
                    # Exclude confusing characters: I, l, 2, z, Z, 5, s, S, 0, o, O
                    import random
                    import string
                    
                    # Build character set excluding confusing characters
                    allowed_chars = ''
                    # Add uppercase letters except I, Z, S, O
                    allowed_chars += ''.join(c for c in string.ascii_uppercase if c not in 'IZSO')
                    # Add lowercase letters except l, z, s, o
                    allowed_chars += ''.join(c for c in string.ascii_lowercase if c not in 'lzso')
                    # Add digits except 0, 2, 5
                    allowed_chars += ''.join(c for c in string.digits if c not in '025')
                    
                    security_code = ''.join(random.choices(allowed_chars, k=8))
                    
                    security_logger.info(f"📱 Generated new security code for user {nmp_username}: {security_code}")
                    security_logger.info(f"📱 Allowed characters: {allowed_chars}")
                    
                    # Save to database
                    new_security_code = UserSecurityCode(
                        nmp_user_id=nmp_user_id,
                        nmp_username=nmp_username,
                        domain_id=domain_id,
                        cluster_id=cluster_id,
                        channel_id=channel_id,
                        security_code=security_code
                    )
                    
                    db.session.add(new_security_code)
                    db.session.commit()
                    
                    security_logger.info(f"📱 Security code saved to database")
                    
                    await self.send_security_code_response(
                        websocket,
                        True,
                        "Security code generated",
                        security_code,
                        nmp_username,
                        domain_id,
                        cluster_id,
                        channel_id
                    )
            
            security_logger.info(f"📱 ===== SECURITY CODE REQUEST COMPLETED =====")
            
        except Exception as e:
            security_logger.error(f"📱 Error handling security code request: {e}")
            security_logger.error(f"📱 Traceback: {traceback.format_exc()}")
            await self.send_security_code_response(websocket, False, str(e))
    
    async def send_security_code_response(self, websocket, success, message, security_code=None, 
                                         nmp_username=None, domain_id=None, cluster_id=None, channel_id=None):
        """Send security code response to C-Client"""
        try:
            from utils.logger import get_bclient_logger
            security_logger = get_bclient_logger('security_code')
            
            response = {
                'type': 'security_code_response',
                'data': {
                    'success': success,
                    'message': message,
                    'security_code': security_code,
                    'nmp_username': nmp_username,
                    'domain_id': domain_id,
                    'cluster_id': cluster_id,
                    'channel_id': channel_id,
                    'timestamp': int(time.time() * 1000)
                }
            }
            
            await websocket.send(json.dumps(response))
            security_logger.info(f"📱 Security code response sent: success={success}")
            
        except Exception as e:
            security_logger.error(f"📱 Error sending security code response: {e}")
