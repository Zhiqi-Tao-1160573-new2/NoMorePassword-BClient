"""
C-Client API Routes
Handles C-Client WebSocket communication API endpoints
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
import sys
import os
import asyncio

# Import logging system
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger

# Create blueprint for C-Client API routes
c_client_api_routes = Blueprint('c_client_api_routes', __name__)

# Initialize logger
logger = get_bclient_logger('c_client_api_routes')

# This will be injected when blueprint is registered
c_client_ws = None


def init_c_client_api_routes(websocket_client):
    """Initialize C-Client API routes with WebSocket client"""
    global c_client_ws
    c_client_ws = websocket_client


@c_client_api_routes.route('/api/c-client/status')
def c_client_status():
    """Check C-Client WebSocket server status and connected clients"""
    if not c_client_ws:
        return jsonify({
            'success': False,
            'error': 'WebSocket functionality not available',
            'connected': False,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # Get connection info using the new method
    connection_info = c_client_ws.get_connection_info()
    
    return jsonify({
        'success': True,
        'websocket_server': {
            'enabled': True,
            'host': c_client_ws.config.get('server_host', '0.0.0.0'),
            'port': c_client_ws.config.get('server_port', 8766),
            'status': 'running'
        },
        'connected_clients': connection_info,
        'timestamp': datetime.utcnow().isoformat()
    })


@c_client_api_routes.route('/api/c-client/update-cookie', methods=['POST'])
def c_client_update_cookie():
    """Update cookie in C-Client via WebSocket"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        username = data.get('username')
        cookie = data.get('cookie')
        auto_refresh = data.get('auto_refresh', False)

        if not all([user_id, username, cookie]):
            return jsonify({'success': False, 'error': 'user_id, username, and cookie are required'}), 400

        # Send WebSocket message
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(c_client_ws.update_cookie(user_id, username, cookie, auto_refresh))
        loop.close()

        return jsonify({
            'success': True,
            'message': 'Cookie update sent to C-Client',
            'user_id': user_id,
            'username': username
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@c_client_api_routes.route('/api/c-client/notify-login', methods=['POST'])
def c_client_notify_login():
    """Notify C-Client of user login via WebSocket"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        username = data.get('username')
        session_data = data.get('session_data', {})

        if not user_id or not username:
            return jsonify({'success': False, 'error': 'user_id and username are required'}), 400

        # Send WebSocket message
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(c_client_ws.notify_user_login(user_id, username, session_data))
        loop.close()

        return jsonify({
            'success': True,
            'message': 'Login notification sent to C-Client',
            'user_id': user_id,
            'username': username
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@c_client_api_routes.route('/api/c-client/notify-logout', methods=['POST'])
def c_client_notify_logout():
    """Notify C-Client of user logout via WebSocket"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        username = data.get('username')

        if not user_id or not username:
            return jsonify({'success': False, 'error': 'user_id and username are required'}), 400

        # Send WebSocket message
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(c_client_ws.notify_user_logout(user_id, username))
        loop.close()

        return jsonify({
            'success': True,
            'message': 'Logout notification sent to C-Client',
            'user_id': user_id,
            'username': username
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@c_client_api_routes.route('/api/c-client/sync-session', methods=['POST'])
def c_client_sync_session():
    """Sync session data with C-Client via WebSocket"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        session_data = data.get('session_data', {})

        if not user_id:
            return jsonify({'success': False, 'error': 'user_id is required'}), 400

        # Send WebSocket message
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(c_client_ws.sync_session(user_id, session_data))
        loop.close()

        return jsonify({
            'success': True,
            'message': 'Session sync sent to C-Client',
            'user_id': user_id
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@c_client_api_routes.route('/api/websocket/check-user', methods=['POST'])
def websocket_check_user():
    """Check if a user is connected to the WebSocket server"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({'success': False, 'error': 'user_id is required'}), 400
        
        logger.info(f"Checking WebSocket connection for user_id: {user_id}")
        
        # Check if user exists in user_connections pool
        user_connected = user_id in c_client_ws.user_connections
        
        # Get WebSocket URL from configuration
        websocket_host = c_client_ws.config.get('server_host', '127.0.0.1')
        websocket_port = c_client_ws.config.get('server_port', 8766)
        websocket_url = f"ws://{websocket_host}:{websocket_port}"
        
        if user_connected:
            connections = c_client_ws.user_connections.get(user_id, [])
            logger.info(f"User {user_id} is connected with {len(connections)} connections")
        else:
            logger.info(f"User {user_id} is not connected to WebSocket")
        
        return jsonify({
            'success': True,
            'connected': user_connected,
            'websocket_url': websocket_url,
            'user_id': user_id
        })
    
    except Exception as e:
        logger.error(f"Error checking WebSocket connection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

