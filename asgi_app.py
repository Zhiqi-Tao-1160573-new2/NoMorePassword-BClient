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
    """No longer needed - WebSocket handling integrated into ASGI app"""
    global websocket_server
    
    print(f"ℹ️ [ASGI] No separate WebSocket server needed - integrated into ASGI app")
    logger.info("No separate WebSocket server needed - integrated into ASGI app")
    
    # No separate WebSocket server
    websocket_server = None
    return None

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
            # Handle WebSocket connections directly in ASGI
            if scope["type"] == "websocket":
                print(f"🔧 [ASGI] Handling WebSocket connection directly")
                logger.info("Handling WebSocket connection directly")
                
                # Handle WebSocket connection using our WebSocket client
                await self.handle_websocket_connection(scope, receive, send)
                return
            
            # Handle HTTP requests with Flask
            await self.flask_app(scope, receive, send)
        
        async def handle_websocket_connection(self, scope, receive, send):
            """Handle WebSocket connections using the real C-Client handler"""
            try:
                # Accept WebSocket connection
                await send({
                    "type": "websocket.accept",
                })
                
                print(f"✅ [ASGI] WebSocket connection accepted")
                logger.info("WebSocket connection accepted")
                
                # Import and initialize the real WebSocket client
                from services.websocket_client import c_client_ws
                
                # Create a mock websocket object that implements the websockets interface
                class MockWebSocket:
                    def __init__(self, send_func, receive_func):
                        self.send_func = send_func
                        self.receive_func = receive_func
                        self.closed = False
                    
                    async def send(self, message):
                        if not self.closed:
                            await self.send_func({
                                "type": "websocket.send",
                                "text": message
                            })
                    
                    async def recv(self):
                        while True:
                            message = await self.receive_func()
                            if message["type"] == "websocket.receive":
                                return message.get("text", "")
                            elif message["type"] == "websocket.disconnect":
                                self.closed = True
                                raise websockets.exceptions.ConnectionClosed(None, None)
                
                # Create mock websocket and handle connection
                mock_websocket = MockWebSocket(send, receive)
                await c_client_ws.handle_c_client_connection(mock_websocket)
                        
            except Exception as e:
                print(f"❌ [ASGI] WebSocket error: {e}")
                logger.error(f"WebSocket error: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                try:
                    await send({
                        "type": "websocket.close",
                        "code": 1011,
                        "reason": "Internal server error"
                    })
                except:
                    pass
    
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

# WebSocket handling is now integrated into ASGI app
async def startup():
    """No longer needed - WebSocket handling integrated into ASGI app"""
    print(f"ℹ️ [ASGI] WebSocket handling integrated into ASGI app - no startup needed")
    logger.info("WebSocket handling integrated into ASGI app - no startup needed")

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