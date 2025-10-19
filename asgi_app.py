#!/usr/bin/env python3
"""
ASGI Application for B-Client
Combines Flask HTTP routes with WebSocket server using Hypercorn
"""

# Standard library imports
import os
import asyncio
import threading
import traceback

# Third-party imports
from hypercorn.asyncio import serve
from hypercorn.config import Config

# Local imports
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
        # Get port (try different ports if main port is occupied)
        port = int(os.environ.get('PORT', 8000))
        
        # Try different ports for WebSocket server
        for port_offset in range(5):  # Try up to 5 different ports
            ws_port = port + port_offset
            print(f"🚀 [ASGI] Attempting to start WebSocket server on port {ws_port}")
            logger.info(f"Attempting to start WebSocket server on port {ws_port}")
            
            # Start WebSocket server
            print(f"🔧 [ASGI] Calling c_client_ws.start_server(host='0.0.0.0', port={ws_port})")
            websocket_server = await c_client_ws.start_server(host='0.0.0.0', port=ws_port)
            
            if websocket_server is not None:
                print(f"✅ [ASGI] WebSocket server started successfully on port {ws_port}")
                logger.info(f"✅ WebSocket server started successfully on port {ws_port}")
                break
            else:
                print(f"❌ [ASGI] Failed to start WebSocket server on port {ws_port}, trying next port...")
                logger.warning(f"Failed to start WebSocket server on port {ws_port}, trying next port...")
                continue
        
        print(f"📦 [ASGI] WebSocket server object created: {websocket_server}")
        logger.info(f"WebSocket server object created: {websocket_server}")
        
        if websocket_server:
            print(f"🔄 [ASGI] Waiting for WebSocket server to close...")
            # Keep server running
            await websocket_server.wait_closed()
            print(f"🔚 [ASGI] WebSocket server closed")
        else:
            print(f"❌ [ASGI] Failed to start WebSocket server on any port")
            logger.error("❌ Failed to start WebSocket server on any port")
            
    except Exception as e:
        print(f"❌ [ASGI] WebSocket server error: {e}")
        logger.error(f"❌ WebSocket server error: {e}")
        print(f"❌ [ASGI] Traceback: {traceback.format_exc()}")
        logger.error(traceback.format_exc())

# Create ASGI application using Flask with WSGI-to-ASGI adapter
try:
    # Try to import WSGI-to-ASGI adapter
    from asgiref.wsgi import WsgiToAsgi
    
    # Convert Flask WSGI app to ASGI
    flask_asgi = WsgiToAsgi(app)
    
    logger.info("✅ Using asgiref.wsgi.WsgiToAsgi for Flask ASGI conversion")
    
    # Wrap with WebSocket server startup
    class ASGIAppWithWebSocket:
        def __init__(self, flask_app):
            self.flask_app = flask_app
            self.websocket_started = False
        
        async def __call__(self, scope, receive, send):
            # Start WebSocket server on first request
            if not self.websocket_started:
                print(f"🚀 [ASGI] Starting WebSocket server on first request...")
                logger.info("🚀 Starting WebSocket server on first request...")
                await startup()
                self.websocket_started = True
            
            # Handle the request with Flask
            await self.flask_app(scope, receive, send)
    
    asgi_app = ASGIAppWithWebSocket(flask_asgi)
    print(f"✅ [ASGI] ASGI app wrapper created successfully")
    logger.info("✅ ASGI app wrapper created successfully")
    
except ImportError:
    logger.warning("⚠️ asgiref not available, using basic ASGI wrapper")
    
    # Fallback: Basic ASGI wrapper (limited functionality)
    class BasicASGIWrapper:
        def __init__(self, wsgi_app):
            self.wsgi_app = wsgi_app
            self.websocket_started = False
        
        async def __call__(self, scope, receive, send):
            # Start WebSocket server on first request
            if not self.websocket_started:
                print(f"🚀 [ASGI] Starting WebSocket server on first request...")
                logger.info("🚀 Starting WebSocket server on first request...")
                await startup()
                self.websocket_started = True
            
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
                "body": b"<h1>B-Client</h1><p>WebSocket server running separately on port " + str(int(os.environ.get('PORT', 8000))).encode() + b"</p>",
            })
    
    asgi_app = BasicASGIWrapper(app)
    print(f"⚠️ [ASGI] Using BasicASGIWrapper (limited functionality)")
    logger.warning("⚠️ Using BasicASGIWrapper (limited functionality)")

# Start WebSocket server in background
async def startup():
    """Startup function to initialize WebSocket server"""
    global websocket_task
    
    if not websocket_task:
        print(f"🎯 [ASGI] Creating WebSocket server task...")
        websocket_task = asyncio.create_task(start_websocket_server_background())
        print(f"✅ [ASGI] WebSocket server task created: {websocket_task}")
        logger.info("🚀 WebSocket server task created")

# WebSocket server will be started when Hypercorn calls the ASGI app
print(f"🔧 [ASGI] ASGI app created, WebSocket server will start with Hypercorn")
logger.info("🔧 ASGI app created, WebSocket server will start with Hypercorn")

# For Hypercorn deployment
def get_asgi_app():
    """Get ASGI application for Hypercorn"""
    return asgi_app

# Export the ASGI app for direct import
__all__ = ['asgi_app', 'get_asgi_app']

# For testing/direct usage
if __name__ == "__main__":
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