#!/usr/bin/env python3
"""
ASGI Application for B-Client
Uses the real WebSocket service from app.py instead of creating adapters
"""

# Standard library imports
import os
import asyncio
import threading
import time
import traceback

# Third-party imports
from asgiref.wsgi import WsgiToAsgi

# Local imports
from app import app, c_client_ws
from utils.logger import get_bclient_logger

# Initialize logger
logger = get_bclient_logger('asgi_app')

# Exception for WebSocket connection closed
class ConnectionClosed(Exception):
    pass

# Convert Flask WSGI app to ASGI
flask_asgi = WsgiToAsgi(app)

logger.info("✅ Using asgiref.wsgi.WsgiToAsgi for Flask ASGI conversion")

class ASGIAppWithWebSocket:
    def __init__(self, flask_app):
        self.flask_app = flask_app
        self.websocket_started = False
    
    async def __call__(self, scope, receive, send):
        # Handle WebSocket connections using the real WebSocket service
        if scope["type"] == "websocket":
            print(f"🔧 [ASGI] Handling WebSocket connection using real service")
            logger.info("Handling WebSocket connection using real service")
            
            await self.handle_websocket_connection(scope, receive, send)
            return
        
        # Handle HTTP requests with Flask
        await self.flask_app(scope, receive, send)
    
    async def handle_websocket_connection(self, scope, receive, send):
        """Handle WebSocket connections using the real WebSocket service from app.py"""
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
            
            # Use the real WebSocket service from app.py
            print(f"🔧 [ASGI] Using real WebSocket service from app.py...")
            logger.info("Using real WebSocket service from app.py")
            
            # Create an ASGI-compatible WebSocket adapter that works with the real service
            class ASGIWebSocketAdapter:
                def __init__(self, send_func, receive_func):
                    self.send_func = send_func
                    self.receive_func = receive_func
                    self.remote_address = (client_host, client_port)
                    self.local_address = (server_host, server_port)
                    self.path = path
                    self._closed = False
                
                async def send(self, message):
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
                            self._closed = True
                            raise ConnectionClosed()
                
                def close(self):
                    self._closed = True
                
                @property
                def closed(self):
                    return self._closed
                
                # Add iterator methods for async for loop support
                def __aiter__(self):
                    return self
                
                async def __anext__(self):
                    if self._closed:
                        raise StopAsyncIteration
                    
                    try:
                        message = await self.receive_func()
                        if message["type"] == "websocket.receive":
                            return message.get("text", "")
                        elif message["type"] == "websocket.disconnect":
                            self._closed = True
                            raise StopAsyncIteration
                        else:
                            # Skip non-receive messages and continue
                            return await self.__anext__()
                    except Exception as e:
                        self._closed = True
                        raise StopAsyncIteration
            
            # Create the adapter and use it with the real WebSocket service
            websocket_adapter = ASGIWebSocketAdapter(send, receive)
            
            # Use the real WebSocket service from app.py
            print(f"🔧 [ASGI] Calling real WebSocket service...")
            logger.info("Calling real WebSocket service")
            
            # Call the real WebSocket service handler
            await c_client_ws.handle_c_client_connection(websocket_adapter)
            
            print(f"✅ [ASGI] Real WebSocket service completed")
            logger.info("Real WebSocket service completed")
                    
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

# Create the ASGI application
asgi_app = ASGIAppWithWebSocket(flask_asgi)

print(f"🔧 [ASGI] ASGI application created with real WebSocket service")
logger.info("ASGI application created with real WebSocket service")

# Export the ASGI application
__all__ = ['asgi_app']