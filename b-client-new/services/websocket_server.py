"""
WebSocket Server Module
Handles WebSocket server startup and management
"""
import threading
import sys
import os
import traceback

# Import logging system
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger

# Initialize logger
logger = get_bclient_logger('websocket_server')

# These will be injected when initialized
websockets = None
asyncio = None
c_client_ws = None


def init_websocket_server(ws_module, async_module, ws_client):
    """Initialize WebSocket server with dependencies"""
    global websockets, asyncio, c_client_ws
    websockets = ws_module
    asyncio = async_module
    c_client_ws = ws_client


# Global flag to track if WebSocket server has been started
websocket_server_started = False

def start_websocket_server():
    """Start WebSocket server for C-Client connections in background thread"""
    global websocket_server_started
    
    if websocket_server_started:
        logger.warning("WebSocket server already started, skipping...")
        return
        
    if not websockets or not asyncio or not threading:
        logger.warning("WebSocket functionality disabled - dependencies not available")
        return
        
    if not c_client_ws.config.get('enabled', True):
        logger.warning("WebSocket server disabled in config")
        return
        
    def run_websocket_server():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # B-Client as server, use configured address and port
            host = c_client_ws.config.get('server_host', '0.0.0.0')
            port = c_client_ws.config.get('server_port', 8766)
            logger.info(f"Starting WebSocket server on {host}:{port}")
            
            # Start the server and keep it running
            server = loop.run_until_complete(c_client_ws.start_server(host=host, port=port))
            if server:
                logger.info(f"WebSocket server started successfully on {host}:{port}")
                # Keep the server running
                loop.run_forever()
            else:
                logger.error(f"Failed to start WebSocket server")
        except Exception as e:
            logger.error(f"WebSocket server error: {e}")
            traceback.print_exc()
    
    thread = threading.Thread(target=run_websocket_server, daemon=True)
    thread.start()
    websocket_server_started = True

# Start WebSocket server when app starts
