"""
B-Client API Routes
Handles B-Client specific API endpoints
"""

# Standard library imports
import json
import os
import socket
import time

# Third-party imports
from flask import Blueprint, request, jsonify

# Create blueprint for B-Client API routes
b_client_api_routes = Blueprint('b_client_api_routes', __name__)


@b_client_api_routes.route('/api/b-client/info')
def b_client_info():
    """Return B-Client configuration information for C-Client connections"""
    try:
        # Get current environment
        from utils.config_manager import get_current_environment
        environment = get_current_environment()
        
        # Calculate ports dynamically
        # HTTP port is the main PORT environment variable
        http_port = int(os.environ.get('PORT', 8000))
        
        # WebSocket port is HTTP port + 1 for ASGI deployment
        # In local development, use the configured port
        if environment == 'local':
            websocket_port = 8766  # Default local WebSocket port
        else:
            websocket_port = http_port + 1  # Production: HTTP port + 1
        
        # Get B-Client WebSocket server configuration
        websocket_config = {
            'enabled': True,
            'host': '0.0.0.0',  # B-Client WebSocket server host
            'port': websocket_port,  # Dynamic WebSocket port
            'environment': environment
        }
        
        # Get network information
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        return jsonify({
            'success': True,
            'b_client_info': {
                'websocket': websocket_config,
                'environment': environment,
                'hostname': hostname,
                'local_ip': local_ip,
                'api_port': http_port,  # Dynamic HTTP port
                'websocket_port': websocket_port,  # Explicit WebSocket port
                'timestamp': int(time.time() * 1000)
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@b_client_api_routes.route('/api/b-client/websocket-info')
def websocket_info():
    """Simple endpoint for C-Client to discover WebSocket connection details"""
    try:
        # Calculate ports dynamically
        http_port = int(os.environ.get('PORT', 8000))
        
        # Get environment
        from utils.config_manager import get_current_environment
        environment = get_current_environment()
        
        # Calculate WebSocket port
        if environment == 'local':
            websocket_port = 8766  # Default local WebSocket port
        else:
            websocket_port = http_port + 1  # Production: HTTP port + 1
        
        return jsonify({
            'websocket_url': f"ws://0.0.0.0:{websocket_port}",
            'websocket_host': '0.0.0.0',
            'websocket_port': websocket_port,
            'http_port': http_port,
            'environment': environment,
            'timestamp': int(time.time() * 1000)
        })
    except Exception as e:
        return jsonify({
            'error': str(e)
        })

