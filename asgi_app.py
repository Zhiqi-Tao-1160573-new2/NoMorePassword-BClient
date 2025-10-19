#!/usr/bin/env python3
"""
ASGI Application for B-Client
Combines Flask HTTP routes with WebSocket server using Hypercorn
"""

import os
import asyncio
import threading
from hypercorn.asyncio import serve
from hypercorn.config import Config

# Import Flask app and WebSocket client
from app import app, c_client_ws
from utils.logger import get_bclient_logger

# Initialize logger
logger = get_bclient_logger('asgi_app')

# Global variables for WebSocket server
websocket_server = None
websocket_task = None

async def start_websocket_server_background():
    """Start WebSocket server in background"""
    global websocket_server
    
    try:
        # Get port (use same port for both HTTP and WebSocket in Heroku)
        port = int(os.environ.get('PORT', 8000))
        ws_port = port  # Use same port for WebSocket in Heroku
        
        print(f"🚀 [ASGI] Starting WebSocket server on port {ws_port}")
        logger.info(f"Starting WebSocket server on port {ws_port}")
        
        # Start WebSocket server
        print(f"🔧 [ASGI] Calling c_client_ws.start_server(host='0.0.0.0', port={ws_port})")
        websocket_server = await c_client_ws.start_server(host='0.0.0.0', port=ws_port)
        print(f"📦 [ASGI] WebSocket server object created: {websocket_server}")
        logger.info(f"WebSocket server object created: {websocket_server}")
        
        if websocket_server:
            print(f"✅ [ASGI] WebSocket server started successfully on port {ws_port}")
            logger.info(f"✅ WebSocket server started successfully on port {ws_port}")
            print(f"🔄 [ASGI] Waiting for WebSocket server to close...")
            # Keep server running
            await websocket_server.wait_closed()
            print(f"🔚 [ASGI] WebSocket server closed")
        else:
            print(f"❌ [ASGI] Failed to start WebSocket server")
            logger.error("❌ Failed to start WebSocket server")
            
    except Exception as e:
        print(f"❌ [ASGI] WebSocket server error: {e}")
        logger.error(f"❌ WebSocket server error: {e}")
        import traceback
        print(f"❌ [ASGI] Traceback: {traceback.format_exc()}")
        logger.error(traceback.format_exc())

# Create ASGI application using Flask with WSGI-to-ASGI adapter
try:
    # Try to import WSGI-to-ASGI adapter
    from asgiref.wsgi import WsgiToAsgi
    
    # Convert Flask WSGI app to ASGI
    asgi_app = WsgiToAsgi(app)
    
    logger.info("✅ Using asgiref.wsgi.WsgiToAsgi for Flask ASGI conversion")
    
except ImportError:
    logger.warning("⚠️ asgiref not available, using basic ASGI wrapper")
    
    # Fallback: Basic ASGI wrapper (limited functionality)
    class BasicASGIWrapper:
        def __init__(self, wsgi_app):
            self.wsgi_app = wsgi_app
        
        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await send({
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [(b"content-type", b"text/plain")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b"Only HTTP supported in basic wrapper",
                })
                return
            
            # Simple HTTP handling (not production-ready)
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html")],
            })
            await send({
                "type": "http.response.body",
                "body": b"<h1>B-Client</h1><p>WebSocket server running separately on port " + str(int(os.environ.get('PORT', 8000)) + 1).encode() + b"</p>",
            })
    
    asgi_app = BasicASGIWrapper(app)

# Start WebSocket server in background
async def startup():
    """Startup function to initialize WebSocket server"""
    global websocket_task
    
    if not websocket_task:
        print(f"🎯 [ASGI] Creating WebSocket server task...")
        websocket_task = asyncio.create_task(start_websocket_server_background())
        print(f"✅ [ASGI] WebSocket server task created: {websocket_task}")
        logger.info("🚀 WebSocket server task created")

# Initialize WebSocket server on module import
try:
    print(f"🔧 [ASGI] Initializing WebSocket server on module import...")
    # Create event loop and start WebSocket server
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print(f"🔄 [ASGI] Creating startup task...")
    loop.create_task(startup())
    print(f"✅ [ASGI] WebSocket server startup scheduled")
    logger.info("🚀 WebSocket server startup scheduled")
except Exception as e:
    print(f"❌ [ASGI] Failed to schedule WebSocket server startup: {e}")
    logger.error(f"❌ Failed to schedule WebSocket server startup: {e}")

# For Hypercorn deployment
def get_asgi_app():
    """Get ASGI application for Hypercorn"""
    return asgi_app

# Export the ASGI app for direct import
__all__ = ['asgi_app', 'get_asgi_app']

# For testing/direct usage
if __name__ == "__main__":
    import asyncio
    
    async def main():
        print(f"🚀 [ASGI] Starting main function...")
        # Start WebSocket server
        await startup()
        
        # Configure Hypercorn
        config = Config()
        config.bind = ["0.0.0.0:8000"]
        config.use_reloader = False
        
        print(f"🌐 [ASGI] Starting ASGI server with Hypercorn on 0.0.0.0:8000...")
        logger.info("🚀 Starting ASGI server with Hypercorn...")
        await serve(asgi_app, config)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Server stopped by user")