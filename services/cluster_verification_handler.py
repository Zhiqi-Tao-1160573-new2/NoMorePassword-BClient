"""
Cluster Verification WebSocket Handler
Handles WebSocket messages for cluster verification process
"""
import asyncio
import datetime
import json
import os
import sys
from typing import Dict, Optional

# Import logging system
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger

# Import sync data queries
from .sync_data_queries import get_valid_batches_for_channel, get_batch_first_record_data

# Initialize logger
logger = get_bclient_logger('cluster_verification_handler')


class ClusterVerificationHandler:
    """WebSocket handler for cluster verification messages"""
    
    def __init__(self, websocket_client, database):
        self.websocket_client = websocket_client
        self.db = database
        self.pending_requests = {}  # Store pending verification requests
    
    async def handle_cluster_verification_query(self, message: Dict, connection) -> Optional[Dict]:
        """
        Handle cluster verification query from other nodes
        
        Args:
            message: Query message
            connection: WebSocket connection
            
        Returns:
            Response message, or None if no response needed
        """
        try:
            logger.info(f"===== OTHER NODE RECEIVED CLUSTER VERIFICATION QUERY =====")
            logger.info(f"Query action: {message.get('action')}")
            logger.info(f"Channel ID: {message.get('channel_id')}")
            logger.info(f"Min batch size: {message.get('min_batch_size', 3)}")
            logger.info(f"Timestamp: {message.get('timestamp')}")
            
            action = message.get('action')
            channel_id = message.get('channel_id')
            min_batch_size = message.get('min_batch_size', 3)
            
            if action == 'get_valid_batch':
                logger.info(f"===== OTHER NODE PROCESSING GET_VALID_BATCH QUERY =====")
                result = await self._handle_get_valid_batch_query(channel_id, min_batch_size)
                logger.info(f"===== OTHER NODE PREPARING RESPONSE =====")
                logger.info(f"Response: {result}")
                return result
            else:
                logger.warning(f"Unknown cluster verification action: {action}")
                return None
                
        except Exception as e:
            logger.error(f"Error handling cluster verification query: {e}")
            return {
                'type': 'cluster_verification_response',
                'success': False,
                'error': str(e)
            }
    
    async def _handle_get_valid_batch_query(self, channel_id: str, min_batch_size: int) -> Dict:
        """
        Handle get valid batch query
        
        Args:
            channel_id: Channel ID
            min_batch_size: Minimum batch size
            
        Returns:
            Response with batch data
        """
        try:
            logger.info(f"===== OTHER NODE QUERYING DATABASE FOR VALID BATCHES =====")
            logger.info(f"Channel ID: {channel_id}")
            logger.info(f"Min batch size: {min_batch_size}")
            
            # Get valid batches
            valid_batches = get_valid_batches_for_channel(channel_id, min_batch_size)
            
            if not valid_batches:
                logger.info(f"===== OTHER NODE NO VALID BATCHES FOUND FOR CHANNEL {channel_id} =====")
                return {
                    'type': 'cluster_verification_response',
                    'success': False,
                    'message': 'No valid batches found'
                }
            
            logger.info(f"===== OTHER NODE FOUND {len(valid_batches)} VALID BATCHES =====")
            logger.info(f"Valid batches: {[batch['batch_id'] for batch in valid_batches]}")
            
            # Get the first valid batch
            first_batch = valid_batches[0]
            batch_id = first_batch['batch_id']
            
            logger.info(f"===== OTHER NODE GETTING FIRST RECORD FOR BATCH {batch_id} =====")
            
            # Get the first record of the batch
            first_record = get_batch_first_record_data(batch_id)
            
            if not first_record:
                logger.warning(f"===== OTHER NODE NO FIRST RECORD FOUND FOR BATCH {batch_id} =====")
                return {
                    'type': 'cluster_verification_response',
                    'success': False,
                    'message': 'No first record found for batch'
                }
            
            logger.info(f"===== OTHER NODE FOUND VALID BATCH {batch_id} WITH {first_batch['record_count']} RECORDS =====")
            logger.info(f"First record keys: {list(first_record.keys())}")
            
            return {
                'type': 'cluster_verification_response',
                'success': True,
                'batch_data': {
                    'batch_id': batch_id,
                    'record_count': first_batch['record_count'],
                    'first_record': first_record
                }
            }
            
        except Exception as e:
            logger.error(f"Error handling get valid batch query: {e}")
            return {
                'type': 'cluster_verification_response',
                'success': False,
                'error': str(e)
            }
    
    async def handle_client_verification_request(self, message: Dict, connection) -> Optional[Dict]:
        """
        Handle verification request from B-Client to C-Client
        
        Args:
            message: Verification request message
            connection: WebSocket connection
            
        Returns:
            Response message, or None if no response needed
        """
        try:
            logger.info(f"===== C-CLIENT RECEIVED VERIFICATION REQUEST =====")
            logger.info(f"Request action: {message.get('action')}")
            logger.info(f"User ID: {message.get('user_id')}")
            logger.info(f"Batch ID: {message.get('batch_id')}")
            logger.info(f"Timestamp: {message.get('timestamp')}")
            
            action = message.get('action')
            user_id = message.get('user_id')
            batch_id = message.get('batch_id')
            
            if action == 'verify_batch':
                logger.info(f"===== C-CLIENT PROCESSING VERIFY_BATCH REQUEST =====")
                result = await self._handle_verify_batch_request(user_id, batch_id)
                logger.info(f"===== C-CLIENT PREPARING VERIFICATION RESPONSE =====")
                logger.info(f"Response: {result}")
                return result
            else:
                logger.warning(f"Unknown client verification action: {action}")
                return None
                
        except Exception as e:
            logger.error(f"Error handling client verification request: {e}")
            return {
                'type': 'cluster_verification_response',
                'success': False,
                'error': str(e)
            }
    
    async def _handle_verify_batch_request(self, user_id: str, batch_id: str) -> Dict:
        """
        Handle verify batch request
        
        Args:
            user_id: User ID
            batch_id: Batch ID to verify
            
        Returns:
            Response with verification result
        """
        try:
            logger.info(f"===== C-CLIENT VERIFYING BATCH {batch_id} FOR USER {user_id} =====")
            
            logger.info(f"===== C-CLIENT QUERYING DATABASE FOR BATCH {batch_id} =====")
            
            # Get the first record of the batch
            first_record = get_batch_first_record_data(batch_id)
            
            if not first_record:
                logger.warning(f"===== C-CLIENT NO FIRST RECORD FOUND FOR BATCH {batch_id} =====")
                return {
                    'type': 'cluster_verification_response',
                    'success': False,
                    'message': 'No first record found for batch'
                }
            
            logger.info(f"===== C-CLIENT FOUND FIRST RECORD FOR BATCH {batch_id} =====")
            logger.info(f"Record keys: {list(first_record.keys())}")
            
            return {
                'type': 'cluster_verification_response',
                'success': True,
                'record': first_record
            }
            
        except Exception as e:
            logger.error(f"Error handling verify batch request: {e}")
            return {
                'type': 'cluster_verification_response',
                'success': False,
                'error': str(e)
            }
    
    async def process_websocket_message(self, message: Dict, connection) -> Optional[Dict]:
        """
        Process WebSocket message for cluster verification
        
        Args:
            message: WebSocket message
            connection: WebSocket connection
            
        Returns:
            Response message, or None if no response needed
        """
        try:
            message_type = message.get('type')
            
            if message_type == 'cluster_verification_query':
                return await self.handle_cluster_verification_query(message, connection)
            elif message_type == 'cluster_verification_request':
                return await self.handle_client_verification_request(message, connection)
            else:
                # Not a cluster verification message
                return None
                
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")
            return None
    
    async def handle_verify_batch_request(self, message: Dict) -> Dict:
        """
        Handle verify batch request from C-Client
        
        Args:
            message: The verification request message
            
        Returns:
            Response message
        """
        try:
            batch_id = message.get('batch_id')
            user_id = message.get('user_id')
            
            logger.info(f"===== C-CLIENT RECEIVED VERIFICATION REQUEST FROM B-CLIENT =====")
            logger.info(f"Request Type: {message.get('type')}")
            logger.info(f"Action: {message.get('action')}")
            logger.info(f"Batch ID: {batch_id}")
            logger.info(f"User ID: {user_id}")
            logger.info(f"Timestamp: {message.get('timestamp')}")
            logger.info(f"Received Time: {datetime.now().isoformat()}")
            
            logger.info(f"===== C-CLIENT QUERYING LOCAL DATABASE FOR BATCH {batch_id} =====")
            
            # Get first record from batch
            first_record = get_batch_first_record_data(batch_id)
            
            if not first_record:
                logger.warning(f"===== C-CLIENT NO FIRST RECORD FOUND FOR BATCH {batch_id} =====")
                logger.warning(f"Batch ID: {batch_id}")
                logger.warning(f"User ID: {user_id}")
                return {
                    'type': 'cluster_verification_response',
                    'success': False,
                    'message': 'No first record found for batch'
                }
            
            logger.info(f"===== C-CLIENT FOUND FIRST RECORD FOR BATCH {batch_id} =====")
            logger.info(f"Record ID: {first_record.get('id')}")
            logger.info(f"Record URL: {first_record.get('url')}")
            logger.info(f"Record Title: {first_record.get('title')}")
            logger.info(f"Record Timestamp: {first_record.get('timestamp')}")
            logger.info(f"Record Keys: {list(first_record.keys())}")
            
            # Create response message
            response = {
                'type': 'cluster_verification_response',
                'success': True,
                'record': first_record
            }
            
            logger.info(f"===== C-CLIENT SENDING VERIFICATION RESPONSE TO B-CLIENT =====")
            logger.info(f"Response Type: {response['type']}")
            logger.info(f"Response Success: {response['success']}")
            logger.info(f"Response Record Keys: {list(response['record'].keys())}")
            logger.info(f"Sent Time: {datetime.now().isoformat()}")
            
            return response
            
        except Exception as e:
            logger.error(f"===== C-CLIENT ERROR HANDLING VERIFY BATCH REQUEST =====")
            logger.error(f"Batch ID: {batch_id}")
            logger.error(f"User ID: {user_id}")
            logger.error(f"Error: {e}")
            return {
                'type': 'cluster_verification_response',
                'success': False,
                'error': str(e)
            }


# Global instance
cluster_verification_handler = None


def init_cluster_verification_handler(websocket_client, database):
    """Initialize cluster verification handler"""
    global cluster_verification_handler
    cluster_verification_handler = ClusterVerificationHandler(websocket_client, database)
    logger.info("Cluster verification handler initialized")


async def handle_cluster_verification_message(message: Dict, connection) -> Optional[Dict]:
    """
    Handle cluster verification WebSocket message
    
    Args:
        message: WebSocket message
        connection: WebSocket connection
        
    Returns:
        Response message, or None if no response needed
    """
    if not cluster_verification_handler:
        logger.error("Cluster verification handler not initialized")
        return None
    
    return await cluster_verification_handler.process_websocket_message(message, connection)
