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
        
        # Get B-Client WebSocket server configuration
        websocket_config = {
            'enabled': True,
            'host': '0.0.0.0',  # B-Client WebSocket server host
            'port': 8766,       # B-Client WebSocket server port
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
                'api_port': 3000,  # B-Client API port
                'timestamp': int(time.time() * 1000)
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

