#!/usr/bin/env python3
"""
ASGI Application for B-Client
Combines Flask HTTP routes with WebSocket server using Hypercorn
"""

# Standard library imports
import os
import asyncio
import threading
import time
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
            """Handle WebSocket connections directly using ASGI interface"""
            try:
                # Accept WebSocket connection
                await send({
                    "type": "websocket.accept",
                })
                
                # Extract client information from ASGI scope
                client_host = scope.get("client", ["unknown"])[0] if scope.get("client") else "unknown"
                client_port = scope.get("client", [0, 0])[1] if scope.get("client") else 0
                server_host = scope.get("server", ["unknown"])[0] if scope.get("server") else "unknown"
                server_port = scope.get("server", [0, 0])[1] if scope.get("server") else 0
                path = scope.get("path", "/ws")
                
                print(f"✅ [ASGI] WebSocket connection accepted from {client_host}:{client_port}")
                logger.info(f"WebSocket connection accepted from {client_host}:{client_port}")
                print(f"🔧 [ASGI] Connection details: client={client_host}:{client_port}, server={server_host}:{server_port}, path={path}")
                logger.info(f"Connection details: client={client_host}:{client_port}, server={server_host}:{server_port}, path={path}")
                
                # Handle WebSocket messages directly using ASGI interface
                print(f"🔧 [ASGI] Starting WebSocket message loop...")
                logger.info("Starting WebSocket message loop")
                
                while True:
                    message = await receive()
                    
                    if message["type"] == "websocket.receive":
                        # Process incoming message
                        text_data = message.get("text", "")
                        print(f"📨 [ASGI] Received WebSocket message: {text_data[:100]}...")
                        logger.info(f"Received WebSocket message: {text_data[:100]}...")
                        
                        try:
                            # Parse JSON message
                            import json
                            data = json.loads(text_data)
                            
                            # Handle registration message
                            if data.get("type") == "c_client_register":
                                print(f"🔧 [ASGI] Processing C-Client registration...")
                                logger.info("Processing C-Client registration")
                                
                                # Send registration response
                                response = {
                                    "type": "c_client_registered",
                                    "data": {
                                        "success": True,
                                        "message": "C-Client registered successfully",
                                        "client_id": data.get("client_id"),
                                        "user_id": data.get("user_id"),
                                        "username": data.get("username"),
                                        "node_id": data.get("node_id"),
                                        "timestamp": int(time.time() * 1000)
                                    }
                                }
                                
                                await send({
                                    "type": "websocket.send",
                                    "text": json.dumps(response)
                                })
                                
                                print(f"✅ [ASGI] Registration response sent")
                                logger.info("Registration response sent")
                            
                            else:
                                # Echo other messages for now
                                echo_response = {
                                    "type": "echo",
                                    "data": data,
                                    "timestamp": int(time.time() * 1000)
                                }
                                
                                await send({
                                    "type": "websocket.send",
                                    "text": json.dumps(echo_response)
                                })
                                
                                print(f"📤 [ASGI] Echo response sent")
                                logger.info("Echo response sent")
                                
                        except json.JSONDecodeError as e:
                            print(f"❌ [ASGI] Invalid JSON message: {e}")
                            logger.error(f"Invalid JSON message: {e}")
                            
                            # Send error response
                            error_response = {
                                "type": "error",
                                "message": "Invalid JSON format",
                                "timestamp": int(time.time() * 1000)
                            }
                            
                            await send({
                                "type": "websocket.send",
                                "text": json.dumps(error_response)
                            })
                    
                    elif message["type"] == "websocket.disconnect":
                        print(f"🔚 [ASGI] WebSocket disconnected")
                        logger.info("WebSocket disconnected")
                        break
                        
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