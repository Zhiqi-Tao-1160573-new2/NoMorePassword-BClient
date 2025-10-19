"""
Cluster Verification Service
Handles cluster verification logic for C-Client authentication
"""
import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Import logging system
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger

# Initialize logger
logger = get_bclient_logger('cluster_verification')


class ClusterVerificationService:
    """Cluster verification service for C-Client authentication"""
    
    def __init__(self, websocket_client, database):
        self.websocket_client = websocket_client
        self.db = database
        self.verification_timeout = 30  # 30 seconds timeout for verification
        self.min_batch_size = 3  # Minimum batch size for verification
        
        # Response storage for async communication
        self.pending_responses = {}  # Store responses by node_id
        self.response_events = {}   # Store asyncio events for waiting
    
    async def verify_user_cluster(self, user_id: str, channel_id: str, node_id: str) -> Dict:
        """
        Verify user cluster membership (instance method)
        
        Args:
            user_id: C-Client user ID
            channel_id: Channel ID
            node_id: Current node ID
            
        Returns:
            Dict with verification result
        """
        return await self.initiate_cluster_verification(user_id, channel_id, node_id)
        
    async def initiate_cluster_verification(self, user_id: str, channel_id: str, node_id: str) -> Dict:
        """
        Initiate cluster verification process
        
        Args:
            user_id: C-Client user ID
            channel_id: Channel ID for cluster communication
            node_id: Current node ID
            
        Returns:
            Dict with verification result
        """
        try:
            logger.info(f"🔍 ===== INITIATING CLUSTER VERIFICATION =====")
            logger.info(f"🔍 User ID: {user_id}")
            logger.info(f"🔍 Channel ID: {channel_id}")
            logger.info(f"🔍 Node ID: {node_id}")
            logger.info(f"🔍 Min batch size: {self.min_batch_size}")
            
            # Step 1: Query other nodes in the channel for valid batches
            logger.info(f"🔍 ===== STEP 1: QUERYING CHANNEL FOR VALID BATCH =====")
            valid_batch = await self._query_channel_for_valid_batch(user_id, channel_id, node_id)
            
            if not valid_batch:
                logger.info(f"🔍 ===== NO VALID BATCH FOUND - TREATING AS NEW USER =====")
                logger.info(f"🔍 No valid batch found in cluster for user {user_id}")
                return {
                    'success': True,
                    'is_new_user': True,
                    'verification_passed': True,
                    'message': 'New user - no verification required'
                }
            
            logger.info(f"🔍 ===== VALID BATCH FOUND =====")
            logger.info(f"🔍 Batch ID: {valid_batch.get('batch_id')}")
            logger.info(f"🔍 Record count: {valid_batch.get('record_count')}")
            logger.info(f"🔍 First record: {valid_batch.get('first_record')}")
            
            # Step 2: Request verification from the C-Client
            logger.info(f"🔍 ===== STEP 2: REQUESTING CLIENT VERIFICATION =====")
            logger.info(f"🔍 Requesting verification from user {user_id} for batch {valid_batch['batch_id']}")
            verification_result = await self._request_client_verification(
                user_id, valid_batch['batch_id'], valid_batch['first_record']
            )
            
            if verification_result and verification_result.get('success'):
                # First comparison already completed inside _request_client_verification
                # If returns success=True, verification has passed
                logger.info(f"🔍 ===== CLUSTER VERIFICATION PASSED =====")
                logger.info(f"🔍 Client verification successful - records match")
                return {
                    'success': True,
                    'is_new_user': False,
                    'verification_passed': True,
                    'message': 'Cluster verification successful'
                }
            else:
                logger.warning(f"🔍 ===== CLIENT VERIFICATION FAILED =====")
                logger.warning(f"🔍 Client verification failed for user {user_id}")
                return {
                    'success': False,
                    'is_new_user': False,
                    'verification_passed': False,
                    'message': 'Client verification failed'
                }
                
        except Exception as e:
            logger.error(f"Cluster verification error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'is_new_user': True,  # Default to new user on error
                'verification_passed': True,
                'message': f'Verification error: {str(e)}'
            }
    
    async def _query_channel_for_valid_batch(self, user_id: str, channel_id: str, current_node_id: str) -> Optional[Dict]:
        """
        Query other nodes in the channel for valid batches
        
        Args:
            channel_id: Channel ID
            current_node_id: Current node ID (to exclude from query)
            
        Returns:
            Dict with batch_id and first_record, or None if no valid batch found
        """
        try:
            logger.info(f"===== B-CLIENT QUERYING CHANNEL FOR VALID BATCHES =====")
            logger.info(f"Channel ID: {channel_id}")
            logger.info(f"Current Node ID: {current_node_id}")
            logger.info(f"Excluding current node from query")
            
            # Get all nodes in the channel except current node
            channel_nodes = await self._get_channel_nodes(channel_id, current_node_id)
            
            if not channel_nodes:
                logger.info(f"No other nodes found in channel {channel_id}")
                return None
            
            logger.info(f"Found {len(channel_nodes)} nodes to query: {channel_nodes}")
            
            # Query each node for valid batches
            for node_id in channel_nodes:
                try:
                    logger.info(f"===== B-CLIENT SENDING QUERY TO NODE {node_id} =====")
                    batch_data = await self._query_node_for_batch(user_id, node_id, channel_id)
                    if batch_data:
                        logger.info(f"===== B-CLIENT RECEIVED VALID BATCH FROM NODE {node_id} =====")
                        logger.info(f"Batch ID: {batch_data['batch_id']}")
                        logger.info(f"Record count: {batch_data.get('record_count', 'unknown')}")
                        return batch_data
                    else:
                        logger.info(f"Node {node_id} returned no valid batches")
                except Exception as e:
                    logger.warning(f"Error querying node {node_id}: {e}")
                    continue
            
            logger.info("===== B-CLIENT NO VALID BATCHES FOUND IN ANY NODES =====")
            return None
            
        except Exception as e:
            logger.error(f"Error querying channel for valid batch: {e}")
            return None
    
    async def _get_channel_nodes(self, channel_id: str, exclude_node_id: str) -> List[str]:
        """
        Get all nodes in the channel except the specified node
        
        Args:
            channel_id: Channel ID
            exclude_node_id: Node ID to exclude
            
        Returns:
            List of node IDs in the channel
        """
        try:
            if not hasattr(self.websocket_client, 'node_manager'):
                logger.warning("WebSocket client has no node_manager")
                return []
            
            # Get nodes from the channel
            channel_nodes = []
            if hasattr(self.websocket_client.node_manager, 'get_channel_nodes'):
                channel_nodes = self.websocket_client.node_manager.get_channel_nodes(channel_id)
            else:
                # Fallback: get all connected nodes
                if hasattr(self.websocket_client, 'node_connections'):
                    channel_nodes = list(self.websocket_client.node_connections.keys())
            
            # Exclude current node
            channel_nodes = [node for node in channel_nodes if node != exclude_node_id]
            
            logger.info(f"Found {len(channel_nodes)} nodes in channel {channel_id}: {channel_nodes}")
            return channel_nodes
            
        except Exception as e:
            logger.error(f"Error getting channel nodes: {e}")
            return []
    
    async def _query_node_for_batch(self, user_id: str, node_id: str, channel_id: str) -> Optional[Dict]:
        """
        Query a specific node for valid batches
        
        Args:
            node_id: Target node ID
            channel_id: Channel ID
            
        Returns:
            Dict with batch_id and first_record, or None
        """
        try:
            logger.info(f"===== B-CLIENT QUERYING NODE {node_id} FOR VALID BATCHES =====")
            logger.info(f"Target Node ID: {node_id}")
            logger.info(f"Channel ID: {channel_id}")
            logger.info(f"Min batch size: {self.min_batch_size}")
            
            # Create query message (following sync_data message format)
            query_message = {
                'type': 'cluster_verification_query',
                'data': {
                    'action': 'get_valid_batch',
                    'user_id': user_id,  # C1's user_id
                    'channel_id': channel_id,
                    'min_batch_size': self.min_batch_size,
                    'timestamp': int(time.time() * 1000)
                }
            }
            
            logger.info(f"===== B-CLIENT SENDING QUERY MESSAGE TO NODE {node_id} =====")
            logger.info(f"Query message: {query_message}")
            
            # Send query to node
            response = await self._send_node_query(node_id, query_message)
            
            if response and response.get('success'):
                batch_data = response.get('batch_data')
                if batch_data and batch_data.get('batch_id'):
                    logger.info(f"===== B-CLIENT RECEIVED SUCCESSFUL RESPONSE FROM NODE {node_id} =====")
                    logger.info(f"Batch ID: {batch_data['batch_id']}")
                    logger.info(f"Record count: {batch_data.get('record_count', 'unknown')}")
                    return batch_data
                else:
                    logger.info(f"Node {node_id} returned success but no batch data")
            else:
                logger.info(f"Node {node_id} returned unsuccessful response: {response}")
            
            logger.info(f"===== B-CLIENT NODE {node_id} HAS NO VALID BATCHES =====")
            return None
            
        except Exception as e:
            logger.error(f"Error querying node {node_id}: {e}")
            return None
    
    async def _send_node_query(self, node_id: str, message: Dict) -> Optional[Dict]:
        """
        Send query message to a specific node and wait for response
        
        Args:
            node_id: Target node ID
            message: Message to send
            
        Returns:
            Response from node, or None if failed
        """
        try:
            logger.info(f"===== SENDING QUERY TO NODE {node_id} =====")
            logger.info(f"Message: {message}")
            
            # Get node connections
            if not hasattr(self.websocket_client, 'node_connections'):
                logger.warning("🔍 ❌ No node_connections available")
                logger.warning(f"🔍 WebSocket client attributes: {dir(self.websocket_client)}")
                return None
            
            node_connections = self.websocket_client.node_connections.get(node_id, [])
            logger.info(f"🔍 Node {node_id} connections: {len(node_connections)}")
            logger.info(f"🔍 Available nodes: {list(self.websocket_client.node_connections.keys())}")
            
            if not node_connections:
                logger.warning(f"🔍 ❌ No connections found for node {node_id}")
                logger.warning(f"🔍 This might be why C2 response is not received")
                return None
            
            # Create response event for this query
            response_event = asyncio.Event()
            self.response_events[node_id] = response_event
            
            # Send message to all connections of the node
            for connection in node_connections:
                try:
                    await connection.send(json.dumps(message))
                    logger.info(f"Query sent to node {node_id}")
                    
                    # Wait for response using event mechanism
                    try:
                        logger.info(f"🔍 Waiting for response from node {node_id} (timeout: 15 seconds)")
                        await asyncio.wait_for(response_event.wait(), timeout=15.0)
                        
                        # Check if we received a response
                        if node_id in self.pending_responses:
                            response = self.pending_responses.pop(node_id)
                            logger.info(f"🔍 ✅ Received response from node {node_id}: {response}")
                            # Only clean up event after response processing completes
                            self._cleanup_response_event(node_id)
                            return response
                        else:
                            logger.warning(f"🔍 ❌ No response data for node {node_id}")
                            logger.warning(f"🔍 Available pending responses: {list(self.pending_responses.keys())}")
                            
                    except asyncio.TimeoutError:
                        logger.warning(f"🔍 ❌ Timeout waiting for response from node {node_id}")
                        logger.warning(f"🔍 Event state: {response_event.is_set()}")
                        logger.warning(f"🔍 Pending responses: {list(self.pending_responses.keys())}")
                        logger.warning(f"🔍 Response events: {list(self.response_events.keys())}")
                        # Don't clean up event immediately, give response processing some time
                        await asyncio.sleep(0.1)
                        break
                        
                except Exception as e:
                    logger.warning(f"Error sending to node {node_id}: {e}")
                    continue
            
            # Clean up event after timeout
            logger.warning(f"🔍 ❌ No response received from node {node_id}")
            logger.warning(f"🔍 ❌ This indicates a problem with response handling")
            logger.warning(f"🔍 ❌ Final response events: {list(self.response_events.keys())}")
            logger.warning(f"🔍 ❌ Final pending responses: {list(self.pending_responses.keys())}")
            
            # Clean up event
            self._cleanup_response_event(node_id)
            return None
            
        except Exception as e:
            logger.error(f"Error sending node query: {e}")
            return None
    
    def _cleanup_response_event(self, node_id: str):
        """Clean up response event after processing"""
        try:
            if node_id in self.response_events:
                del self.response_events[node_id]
                logger.info(f"🔍 ✅ Cleaned up response event for node {node_id}")
            if node_id in self.pending_responses:
                del self.pending_responses[node_id]
                logger.info(f"🔍 ✅ Cleaned up pending response for node {node_id}")
        except Exception as e:
            logger.error(f"Error cleaning up response event for node {node_id}: {e}")
    
    def _cleanup_client_response_event(self, user_id: str):
        """Clean up client response event after processing"""
        try:
            response_key = f"client_{user_id}"
            if response_key in self.response_events:
                del self.response_events[response_key]
                logger.info(f"🔍 ✅ Cleaned up client response event for user {user_id}")
            if response_key in self.pending_responses:
                del self.pending_responses[response_key]
                logger.info(f"🔍 ✅ Cleaned up client pending response for user {user_id}")
        except Exception as e:
            logger.error(f"Error cleaning up client response event for user {user_id}: {e}")
    
    async def _wait_for_websocket_response(self, connection, timeout: int = 10) -> Optional[Dict]:
        """
        Wait for response from WebSocket connection
        
        Args:
            connection: WebSocket connection
            timeout: Timeout in seconds
            
        Returns:
            Response message, or None if timeout
        """
        try:
            logger.info(f"===== WAITING FOR WEBSOCKET RESPONSE =====")
            logger.info(f"Timeout: {timeout} seconds")
            
            # Since we can't use connection.recv() due to the main message loop,
            # we'll use a simple timeout approach and let the main message handler
            # process the response through handle_verification_response
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                await asyncio.sleep(0.1)
            
            logger.warning(f"Timeout waiting for response from WebSocket")
            return None
            
        except Exception as e:
            logger.error(f"Error waiting for WebSocket response: {e}")
            return None
    
    async def _request_client_verification(self, user_id: str, batch_id: str, reference_record: Dict) -> Dict:
        """
        Request verification from C-Client
        
        Args:
            user_id: C-Client user ID
            batch_id: Batch ID to verify
            reference_record: Reference record from other node
            
        Returns:
            Dict with verification result
        """
        try:
            logger.info(f"🔍 ===== REQUESTING CLIENT VERIFICATION =====")
            logger.info(f"🔍 C-Client User ID: {user_id}")
            logger.info(f"🔍 Batch ID: {batch_id}")
            logger.info(f"🔍 Reference record: {reference_record}")
            logger.info(f"🔍 Reference record keys: {list(reference_record.keys())}")
            
            # Create verification request
            verification_message = {
                'type': 'cluster_verification_request',
                'action': 'verify_batch',
                'batch_id': batch_id,
                'user_id': user_id,
                'timestamp': int(time.time() * 1000)
            }
            
            logger.info(f"🔍 ===== SENDING VERIFICATION REQUEST TO C-CLIENT =====")
            logger.info(f"🔍 Target User ID: {user_id}")
            logger.info(f"🔍 Verification message: {verification_message}")
            
            # Send request to C-Client
            response = await self._send_client_verification_request(user_id, verification_message)
            
            if not response:
                logger.warning(f"===== B-CLIENT NO RESPONSE FROM C-CLIENT {user_id} =====")
                return {'success': False, 'message': 'No response from C-Client'}
            
            logger.info(f"===== B-CLIENT RECEIVED RESPONSE FROM C-CLIENT {user_id} =====")
            logger.info(f"Response: {response}")
            
            if not response.get('success'):
                logger.warning(f"C-Client verification failed: {response.get('message')}")
                return {'success': False, 'message': response.get('message', 'C-Client verification failed')}
            
            # Compare records
            client_record = response.get('record')
            if not client_record:
                logger.warning("No record returned from C-Client")
                return {'success': False, 'message': 'No record returned from C-Client'}
            
            logger.info(f"===== B-CLIENT PERFORMING RECORD COMPARISON =====")
            logger.info(f"Reference record: {reference_record}")
            logger.info(f"Client record: {client_record}")
            
            # Perform record comparison
            comparison_result = self._compare_records(reference_record, client_record)
            
            if comparison_result:
                logger.info(f"===== B-CLIENT RECORD COMPARISON SUCCESSFUL FOR USER {user_id} =====")
                return {
                    'success': True, 
                    'message': 'Verification successful',
                    'record': client_record,  # Return record for upper layer use
                    'first_record': client_record  # Compatibility field
                }
            else:
                logger.warning(f"===== B-CLIENT RECORD COMPARISON FAILED FOR USER {user_id} =====")
                return {
                    'success': False, 
                    'message': 'Record comparison failed',
                    'record': client_record,  # Return record even on failure for debugging
                    'first_record': client_record
                }
                
        except Exception as e:
            logger.error(f"Error requesting client verification: {e}")
            return {'success': False, 'message': f'Verification error: {str(e)}'}
    
    async def _wait_for_connection_ready(self, user_id: str, max_wait_seconds: int = 5) -> bool:
        """
        Wait for user connection to be ready before sending verification request
        
        Args:
            user_id: C-Client user ID
            max_wait_seconds: Maximum wait time in seconds
            
        Returns:
            True if connection is ready, False if timeout
        """
        try:
            logger.info(f"⏳ ===== WAITING FOR CONNECTION READY =====")
            logger.info(f"⏳ User ID: {user_id}")
            logger.info(f"⏳ Max wait time: {max_wait_seconds} seconds")
            
            start_time = time.time()
            check_interval = 0.5  # Check every 500ms
            
            while time.time() - start_time < max_wait_seconds:
                # Check if user has connections
                if hasattr(self.websocket_client, 'user_connections'):
                    user_connections = self.websocket_client.user_connections.get(user_id, [])
                    
                    if user_connections:
                        # Check if any connection is valid and ready
                        for connection in user_connections:
                            # Check if connection is open and ready
                            if hasattr(connection, 'open') and connection.open:
                                logger.info(f"⏳ ✅ Found ready connection for user {user_id}")
                                logger.info(f"⏳ Wait time: {time.time() - start_time:.2f} seconds")
                                return True
                            
                            # Alternative check using state
                            if hasattr(connection, 'state'):
                                state_value = connection.state.value if hasattr(connection.state, 'value') else connection.state
                                if state_value == 1:  # OPEN state
                                    logger.info(f"⏳ ✅ Found open connection for user {user_id}")
                                    logger.info(f"⏳ Wait time: {time.time() - start_time:.2f} seconds")
                                    return True
                        
                        logger.debug(f"⏳ Connections found but not ready yet, waiting...")
                    else:
                        logger.debug(f"⏳ No connections found yet, waiting...")
                else:
                    logger.debug(f"⏳ user_connections not available yet, waiting...")
                
                # Wait before next check
                await asyncio.sleep(check_interval)
            
            # Timeout
            elapsed = time.time() - start_time
            logger.warning(f"⏳ ❌ Timeout waiting for connection ready after {elapsed:.2f} seconds")
            return False
            
        except Exception as e:
            logger.error(f"⏳ ❌ Error waiting for connection ready: {e}")
            return False
        finally:
            logger.info(f"⏳ ===== END WAITING FOR CONNECTION READY =====")
    
    async def _send_client_verification_request(self, user_id: str, message: Dict) -> Optional[Dict]:
        """
        Send verification request to C-Client
        
        Args:
            user_id: C-Client user ID
            message: Verification message
            
        Returns:
            Response from C-Client, or None if failed
        """
        try:
            logger.info(f"🔍 ===== SENDING CLIENT VERIFICATION REQUEST =====")
            logger.info(f"🔍 Target User ID: {user_id}")
            logger.info(f"🔍 Message: {message}")
            
            # CRITICAL FIX: Wait for connection to be ready before sending request
            logger.info(f"🔍 Waiting for connection to be ready...")
            connection_ready = await self._wait_for_connection_ready(user_id, max_wait_seconds=5)
            
            if not connection_ready:
                logger.warning(f"🔍 ❌ Connection not ready after waiting, cannot send verification request")
                return None
            
            logger.info(f"🔍 ✅ Connection is ready, proceeding with verification request")
            
            # Get user connections
            if not hasattr(self.websocket_client, 'user_connections'):
                logger.warning("🔍 ❌ No user_connections available")
                return None
            
            user_connections = self.websocket_client.user_connections.get(user_id, [])
            logger.info(f"🔍 Found {len(user_connections)} connections for user {user_id}")
            
            if not user_connections:
                logger.warning(f"🔍 ❌ No connections found for user {user_id}")
                return None
            
            # Create response event for this request
            response_event = asyncio.Event()
            self.response_events[f"client_{user_id}"] = response_event
            
            # Send message to all user connections
            for connection in user_connections:
                try:
                    logger.info(f"🔍 Sending verification request to connection for user {user_id}")
                    await connection.send(json.dumps(message))
                    logger.info(f"🔍 ✅ Verification request sent to user {user_id}")
                    
                    # Wait for response using event mechanism
                    try:
                        logger.info(f"🔍 Waiting for response from user {user_id} (timeout: 15 seconds)")
                        await asyncio.wait_for(response_event.wait(), timeout=15.0)
                        
                        # Check if we received a response
                        response_key = f"client_{user_id}"
                        if response_key in self.pending_responses:
                            response = self.pending_responses.pop(response_key)
                            logger.info(f"🔍 ✅ Received response from user {user_id}: {response}")
                            # Only clean up event after response processing completes
                            self._cleanup_client_response_event(user_id)
                            return response
                        else:
                            logger.warning(f"🔍 ❌ No response data for user {user_id}")
                            
                    except asyncio.TimeoutError:
                        logger.warning(f"🔍 ❌ Timeout waiting for response from user {user_id}")
                        break
                        
                except Exception as e:
                    logger.warning(f"🔍 ❌ Error sending to user {user_id}: {e}")
                    continue
            
            # Clean up event after timeout
            logger.warning(f"🔍 ❌ No response received from user {user_id}")
            self._cleanup_client_response_event(user_id)
            return None
            
        except Exception as e:
            logger.error(f"🔍 ❌ Error sending client verification request: {e}")
            return None
    
    async def _wait_for_client_response(self, connection, timeout: int = 15) -> Optional[Dict]:
        """
        Wait for response from C-Client connection
        
        Args:
            connection: WebSocket connection
            timeout: Timeout in seconds
            
        Returns:
            Response message, or None if timeout
        """
        try:
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    # Check if connection has pending messages
                    if hasattr(connection, 'pending_messages'):
                        if connection.pending_messages:
                            message = connection.pending_messages.pop(0)
                            data = json.loads(message)
                            if data.get('type') == 'cluster_verification_response':
                                return data
                    
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.warning(f"Error waiting for client response: {e}")
                    break
            
            logger.warning(f"Timeout waiting for response from C-Client")
            return None
            
        except Exception as e:
            logger.error(f"Error waiting for client response: {e}")
            return None
    
    def _compare_records(self, reference_record: Dict, client_record: Dict) -> bool:
        """
        Compare two records for exact match
        
        Args:
            reference_record: Reference record from other node
            client_record: Record from C-Client
            
        Returns:
            True if records match exactly, False otherwise
        """
        try:
            logger.info(f"🔍 ===== COMPARING RECORDS FOR VERIFICATION =====")
            logger.info(f"🔍 Reference record: {reference_record}")
            logger.info(f"🔍 Client record: {client_record}")
            logger.info(f"🔍 Reference record keys: {list(reference_record.keys())}")
            logger.info(f"🔍 Client record keys: {list(client_record.keys())}")
            
            # Compare all fields in reference record
            for key, value in reference_record.items():
                logger.info(f"🔍 Comparing field '{key}': reference='{value}' vs client='{client_record.get(key)}'")
                if key not in client_record:
                    logger.warning(f"🔍 ❌ Key '{key}' missing in client record")
                    return False
                
                if client_record[key] != value:
                    logger.warning(f"Value mismatch for key {key}: {client_record[key]} != {value}")
                    return False
            
            # Check if client record has extra fields (should be same)
            for key in client_record:
                if key not in reference_record:
                    logger.warning(f"Extra key {key} in client record")
                    return False
            
            logger.info("Record comparison successful - records match exactly")
            return True
            
        except Exception as e:
            logger.error(f"Error comparing records: {e}")
            return False
    
    async def handle_verification_response(self, websocket, data):
        """Handle verification response from C-Client"""
        try:
            logger.info(f"🔍 ===== HANDLING VERIFICATION RESPONSE =====")
            logger.info(f"🔍 Response data: {data}")
            logger.info(f"🔍 Response type: {data.get('type')}")
            
            # Check if this is a valid verification response
            if data.get('type') == 'cluster_verification_response':
                success = data.get('success', False)
                channel_id = data.get('channel_id')
                user_id = getattr(websocket, 'user_id', None)
                
                logger.info(f"🔍 Response success: {success}")
                logger.info(f"🔍 Channel ID: {channel_id}")
                logger.info(f"🔍 User ID: {user_id}")
                
                if success:
                    batch_id = data.get('batch_id')
                    record_count = data.get('record_count', 0)
                    # C1's response field is 'record', C2's response field is 'first_record'
                    first_record = data.get('first_record') or data.get('record')
                    
                    logger.info(f"🔍 ✅ Valid verification response received:")
                    logger.info(f"🔍   Batch ID: {batch_id}")
                    logger.info(f"🔍   Record count: {record_count}")
                    logger.info(f"🔍   First record: {first_record}")
                    
                    # Check if this is a response from C1 (client verification) or C2 (node verification)
                    # C2's response usually has no user_id, or user_id is C1's user_id
                    # We need to determine if this is C1 or C2's response based on waiting events
                    
                    # First check if there are waiting C1 response events
                    client_response_key = f"client_{user_id}" if user_id else None
                    if client_response_key and client_response_key in self.response_events:
                        # This is from C1 (client verification)
                        logger.info(f"🔍 Processing client verification response from user {user_id}")
                        
                        logger.info(f"🔍 Storing client response for user {user_id}")
                        # Store the response data for client verification
                        self.pending_responses[client_response_key] = {
                            'success': True,
                            'record': first_record,
                            'batch_id': batch_id,
                            'record_count': record_count
                        }
                        
                        # Trigger the waiting event
                        event = self.response_events.get(client_response_key)
                        if event:
                            event.set()
                            logger.info(f"🔍 ✅ Client response event triggered for user {user_id}")
                        else:
                            logger.warning(f"🔍 ❌ Event not found for user {user_id}")
                    else:
                        # This is from C2 (node verification) - find waiting node events
                        logger.info(f"🔍 Processing node verification response")
                        target_node_id = None
                        logger.info(f"🔍 Available response events: {list(self.response_events.keys())}")
                        logger.info(f"🔍 Event states: {[(k, v.is_set() if v else 'None') for k, v in self.response_events.items()]}")
                        
                        # Find waiting node events (not events starting with client_)
                        logger.info(f"🔍 Searching for waiting node events...")
                        for node_id, event in self.response_events.items():
                            logger.info(f"🔍 Checking event for node {node_id}: event={event}, is_set={event.is_set() if event else 'None'}")
                            if not node_id.startswith('client_') and event and not event.is_set():
                                target_node_id = node_id
                                logger.info(f"🔍 ✅ Found waiting event for node {node_id}")
                                break
                            else:
                                logger.info(f"🔍 ❌ Event for node {node_id} not suitable: starts_with_client={node_id.startswith('client_')}, event_exists={event is not None}, is_set={event.is_set() if event else 'None'}")
                        
                        if target_node_id:
                            logger.info(f"🔍 Storing response for node {target_node_id}")
                            # Store the response data
                            self.pending_responses[target_node_id] = {
                                'success': True,
                                'batch_data': {
                                    'batch_id': batch_id,
                                    'record_count': record_count,
                                    'first_record': first_record
                                }
                            }
                            
                            # Trigger the waiting event
                            event = self.response_events.get(target_node_id)
                            if event:
                                event.set()
                                logger.info(f"🔍 ✅ Response event triggered for node {target_node_id}")
                            else:
                                logger.warning(f"🔍 ❌ Event not found for node {target_node_id}")
                        else:
                            logger.warning(f"🔍 ❌ No waiting event found for this response")
                            logger.warning(f"🔍 This might cause timeout in _send_node_query")
                    
                else:
                    logger.info(f"🔍 Verification response indicates no valid batches found")
                    
                    # Still need to trigger the event to unblock waiting
                    for node_id, event in self.response_events.items():
                        if event and not event.is_set():
                            self.pending_responses[node_id] = {'success': False}
                            event.set()
                            logger.info(f"🔍 No valid batches event triggered for node {node_id}")
                            break
            else:
                logger.warning(f"🔍 ❌ Invalid verification response format: {data}")
                logger.warning(f"🔍 Expected type: cluster_verification_response")
                logger.warning(f"🔍 Received type: {data.get('type')}")
            
        except Exception as e:
            logger.error(f"🔍 ❌ Error handling verification response: {e}")
            logger.error(f"🔍 ❌ Traceback: {traceback.format_exc()}")


# Global instance
cluster_verification_service = None


def get_cluster_verification_service():
    """Get the current cluster verification service instance"""
    global cluster_verification_service
    return cluster_verification_service


def init_cluster_verification(websocket_client, database):
    """Initialize cluster verification service"""
    global cluster_verification_service
    cluster_verification_service = ClusterVerificationService(websocket_client, database)
    logger.info("Cluster verification service initialized")


async def verify_user_cluster(user_id: str, channel_id: str, node_id: str) -> Dict:
    """
    Verify user cluster membership
    
    Args:
        user_id: C-Client user ID
        channel_id: Channel ID
        node_id: Current node ID
        
    Returns:
        Dict with verification result
    """
    if not cluster_verification_service:
        logger.error("Cluster verification service not initialized")
        return {
            'success': False,
            'is_new_user': True,
            'verification_passed': True,
            'message': 'Service not initialized'
        }
    
    return await cluster_verification_service.initiate_cluster_verification(user_id, channel_id, node_id)
