#!/usr/bin/env python3
"""
WSGI Application for B-Client with integrated WebSocket server
Alternative approach: Keep Flask as WSGI and run WebSocket server separately
"""

import os
import asyncio
import threading
import time

# Import Flask app and WebSocket client
from app import app, c_client_ws
from utils.logger import get_bclient_logger

# Initialize logger
logger = get_bclient_logger('wsgi_app')

# Global variables for WebSocket server
websocket_server = None
websocket_thread = None

def start_websocket_server_thread():
    """Start WebSocket server in a separate thread"""
    global websocket_server
    
    try:
        # Get WebSocket port (use PORT + 1 to avoid conflicts with main app)
        port = int(os.environ.get('PORT', 8000))
        ws_port = port + 1
        
        logger.info(f"Starting WebSocket server thread on port {ws_port}")
        
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Start WebSocket server
        websocket_server = loop.run_until_complete(
            c_client_ws.start_server(host='0.0.0.0', port=ws_port)
        )
        
        if websocket_server:
            logger.info(f"WebSocket server started successfully on port {ws_port}")
            # Keep server running
            loop.run_until_complete(websocket_server.wait_closed())
        else:
            logger.error("Failed to start WebSocket server")
            
    except Exception as e:
        logger.error(f"WebSocket server thread error: {e}")
        import traceback
        logger.error(traceback.format_exc())

def initialize_websocket_server():
    """Initialize WebSocket server in background thread"""
    global websocket_thread
    
    if not websocket_thread:
        websocket_thread = threading.Thread(
            target=start_websocket_server_thread,
            daemon=True,
            name="WebSocketServer"
        )
        websocket_thread.start()
        logger.info("WebSocket server thread started")
        
        # Give the server a moment to start
        time.sleep(1)

# Initialize WebSocket server on module import
initialize_websocket_server()

# Export Flask app as WSGI application
wsgi_app = app

# For Gunicorn/uWSGI deployment
application = app

# Export the WSGI app for direct import
__all__ = ['wsgi_app', 'application']

# For testing/direct usage
if __name__ == "__main__":
    import sys
    
    # Get configuration
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 8000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting Flask server on {host}:{port}")
    logger.info(f"WebSocket server running on port {port + 1}")
    
    try:
        app.run(host=host, port=port, debug=debug)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        sys.exit(0)
