"""
Bind Routes
Handles the core NMP bind API endpoint for signup/login integration
"""
from flask import Blueprint, request, jsonify, current_app as app
from datetime import datetime
import json
import time
import threading
import asyncio
import requests
import traceback
import random
import string
import re
import sys
import os

# Import logging system and configuration
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger
from utils.config_manager import get_nsn_base_url, get_nsn_api_url, get_current_environment
from services.nodeManager import ClientConnection

# Create blueprint for bind routes
bind_routes = Blueprint('bind_routes', __name__)

# Initialize logging system
logger = get_bclient_logger('bind_routes')

# These will be injected when blueprint is registered
db = None
UserCookie = None
UserAccount = None
nsn_client = None
c_client_ws = None
save_cookie_to_db_func = None
save_account_to_db_func = None
send_session_to_client_func = None


def init_bind_routes(database, user_cookie_model, user_account_model, nsn_service, websocket_client, save_cookie_func, save_account_func, send_session_func):
    """Initialize bind routes with database models and services"""
    global db, UserCookie, UserAccount, nsn_client, c_client_ws
    global save_cookie_to_db_func, save_account_to_db_func, send_session_to_client_func
    
    # Initialize logging system
    global logger
    logger = get_bclient_logger('routes')
    
    db = database
    UserCookie = user_cookie_model
    UserAccount = user_account_model
    nsn_client = nsn_service
    c_client_ws = websocket_client
    save_cookie_to_db_func = save_cookie_func
    save_account_to_db_func = save_account_func
    send_session_to_client_func = send_session_func


# Helper function: Generate NMP parameters
def _generate_nmp_params(nmp_user_id, nmp_username):
    """Generate standard NMP parameters"""
    return {
        'nmp_user_id': nmp_user_id,
        'nmp_username': nmp_username,
        'nmp_client_type': 'c-client',
        'nmp_timestamp': str(int(time.time() * 1000)),
        'nmp_injected': 'true'  # Add this parameter to let NSN identify as B-Client request
    }


# Helper function: Generate session data JSON
def _generate_session_data_json(nsn_user_id, nsn_username, nmp_user_id, nmp_username):
    """Generate standard session data JSON"""
    return {
        'loggedin': True,
        'user_id': nsn_user_id,
        'username': nsn_username,
        'role': 'traveller',
        'nmp_user_id': nmp_user_id,
        'nmp_username': nmp_username,
        'nmp_client_type': 'c-client',
        'nmp_timestamp': str(int(time.time() * 1000))
    }


# Helper function: Send session to C-Client
def _send_session_to_client(nmp_user_id, session_cookie, nsn_user_id, nsn_username, reset_logout_status=True, channel_id=None, node_id=None):
    """Unified function to send session to C-Client with optional cluster verification"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Preprocess session data
        session_data_json = _generate_session_data_json(nsn_user_id, nsn_username, nmp_user_id, nsn_username)
        processed_session = json.dumps(session_data_json)
        
        # Cluster verification is now handled in websocket_client.py during session send
        # No need to handle it here in bind routes
        
        # Send session to C-Client
        send_result = loop.run_until_complete(send_session_to_client_func(
            nmp_user_id, 
            processed_session, 
            nsn_user_id, 
            nsn_username,
            website_root_path=get_nsn_base_url(),
            website_name='NSN',
            session_partition='persist:nsn',
            reset_logout_status=reset_logout_status,
            channel_id=channel_id,
            node_id=node_id
        ))
        logger.info(f"Session send result: {send_result}")
        logger.info(f"Session sent to C-Client for user {nmp_user_id}")
        return True
    except Exception as e:
        logger.warning(f"Failed to send session to C-Client: {e}")
        traceback.print_exc()
        return False
    finally:
        loop.close()


# Helper function: Generate signup data
def _generate_signup_data(unique_username, nmp_username, generated_password):
    """Generate standard signup data"""
    return {
        'username': unique_username,
        'email': f"{unique_username}@nomorepassword.local",
        'first_name': nmp_username.split('-')[0] if '-' in nmp_username else nmp_username,
        'last_name': 'NMP User',
        'location': 'Unknown',
        'password': generated_password,
        'confirm_password': generated_password
    }


# Helper function: Save session and send to C-Client
def _save_and_send_session(nmp_user_id, nsn_username, session_cookie, nsn_user_id, node_id, auto_refresh, reset_logout_status=True, channel_id=None):
    """Unified function to save session to database and send to C-Client with optional cluster verification"""
    try:
        # Save session to database
        logger.info(f"===== SAVING SESSION TO DATABASE =====")
        save_cookie_to_db_func(nmp_user_id, nsn_username, session_cookie, node_id, auto_refresh, nsn_user_id, nsn_username)
        logger.info(f"Session saved to database successfully")
        
        # Try to send to C-Client (if WebSocket is connected)
        # Note: Even if send fails (no connections), we still return success
        # because the session is saved and will be sent when C-Client reconnects
        logger.info(f"===== SENDING SESSION TO C-CLIENT =====")
        send_result = _send_session_to_client(nmp_user_id, session_cookie, nsn_user_id, nsn_username, reset_logout_status, channel_id, node_id)
        
        if send_result:
            logger.info(f"Session sent to C-Client successfully")
        else:
            logger.warning(f"Failed to send session to C-Client (no active connections), but session is saved to database")
            logger.info(f"Session will be sent when C-Client reconnects to WebSocket")
        
        # Return True even if send failed, because session is saved
        return True
    except Exception as e:
        logger.error(f"Failed to save and send session: {e}")
        return False


# Helper function: Return success response
def _return_success_response(session_cookie, message):
    """Unified success response function"""
    response_data = {
        'success': True,
        'login_success': True,
        'complete_session_data': session_cookie,
        'message': message
    }
    logger.info(f"===== RETURNING SUCCESS RESPONSE =====")
    logger.info(f"Response data: {response_data}")
    return jsonify(response_data)


# Helper function: Return error response
def _return_error_response(error_message, status_code=400):
    """Unified error response function"""
    error_response = {
        'success': False,
        'error': error_message
    }
    logger.info(f"===== RETURNING ERROR RESPONSE =====")
    logger.info(f"Error response: {error_response}")
    return jsonify(error_response), status_code


def _parse_bind_request():
    """Parse bind request parameters"""
    logger.info(f"===== BIND API CALLED =====")
    logger.info(f"Request timestamp: {datetime.now()}")
    logger.info(f"Request IP: {request.remote_addr}")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request content type: {request.content_type}")
    
    data = request.get_json()
    logger.info(f"Raw request data: {data}")
    
    # Extract request parameters
    nmp_user_id = data.get('user_id')
    nmp_username = data.get('user_name')
    request_type = data.get('request_type', 1)  # 0=signup, 1=bind
    domain_id = data.get('domain_id', get_nsn_base_url().replace('http://', '').replace('https://', ''))
    node_id = data.get('node_id', 'nsn-node-001')
    channel_id = data.get('channel_id', None)  # Channel ID for cluster verification
    client_id = data.get('client_id', None)  # Client ID to identify specific C-Client (for logout)
    auto_refresh = data.get('auto_refresh', True)
    provided_account = data.get('account', '')  # Account from NSN form
    provided_password = data.get('password', '')  # Password from NSN form
    nsn_session_cookie = data.get('session_cookie', '')  # Session cookie from NSN after successful login
    nsn_user_id = data.get('nsn_user_id', '')  # NSN user ID from successful login
    nsn_username = data.get('nsn_username', '')  # NSN username from successful login
    
    logger.info(f"===== BIND API REQUEST =====")
    logger.info(f"Request timestamp: {datetime.utcnow().isoformat()}")
    logger.info(f"Request data: {data}")
    logger.info(f"nmp_user_id: {nmp_user_id}")
    logger.info(f"nmp_username: {nmp_username}")
    logger.info(f"request_type: {request_type} ({'signup' if request_type == 0 else 'logout' if request_type == 2 else 'bind'})")
    logger.info(f"domain_id: {domain_id}")
    logger.info(f"node_id: {node_id}")
    logger.info(f"channel_id: {channel_id}")
    logger.info(f"client_id: {client_id}")
    logger.info(f"auto_refresh: {auto_refresh}")
    logger.info(f"provided_account: {provided_account}")
    logger.info(f"provided_password: {'*' * len(provided_password) if provided_password else 'None'}")
    logger.info(f"nsn_session_cookie: {'provided' if nsn_session_cookie else 'None'}")
    logger.info(f"nsn_user_id: {nsn_user_id}")
    logger.info(f"nsn_username: {nsn_username}")
    logger.info(f"===== END BIND API REQUEST =====")
    
    # Validate required parameters
    if not nmp_user_id or not nmp_username:
        return None, _return_error_response('user_id and user_name are required')
    
    return {
        'nmp_user_id': nmp_user_id,
        'nmp_username': nmp_username,
        'request_type': request_type,
        'domain_id': domain_id,
        'node_id': node_id,
        'channel_id': channel_id,
        'client_id': client_id,
        'auto_refresh': auto_refresh,
        'provided_account': provided_account,
        'provided_password': provided_password,
        'nsn_session_cookie': nsn_session_cookie,
        'nsn_user_id': nsn_user_id,
        'nsn_username': nsn_username
    }, None


def _handle_nsn_session_provided(nmp_user_id, nmp_username, nsn_session_cookie, nsn_user_id, nsn_username, node_id, auto_refresh, channel_id=None):
    """Handle NSN session already provided case"""
    logger.info(f"===== STEP 0: NSN SESSION PROVIDED =====")
    logger.info(f"Processing NSN session provided after successful login")
    logger.info(f"NSN user ID: {nsn_user_id}, Username: {nsn_username}")
    
    # Reset logout status to allow user to login again
    # This is called AFTER NSN login success, so we should always allow it
    # The logout check is handled in send_session_if_appropriate (auto-reconnect)
    logger.info(f"===== RESETTING LOGOUT STATUS =====")
    try:
        updated_accounts = UserAccount.query.filter_by(
            user_id=nmp_user_id,
            website='nsn'
        ).update({'logout': False})
        db.session.commit()
        logger.info(f"Reset logout status for {updated_accounts} user_accounts records")
    except Exception as e:
        logger.warning(f"Failed to reset logout status: {e}")
    
    # Save session and send to C-Client
    if not _save_and_send_session(nmp_user_id, nsn_username, nsn_session_cookie, nsn_user_id, node_id, auto_refresh, reset_logout_status=True, channel_id=channel_id):
        return _return_error_response('Failed to save session to database', 500)
    
    return _return_success_response(nsn_session_cookie, 'NSN session saved and sent to C-Client')


def _delete_user_data(nmp_user_id):
    """Delete user database records"""
    deleted_cookies_count = UserCookie.query.filter_by(user_id=nmp_user_id).delete()
    updated_accounts_count = UserAccount.query.filter_by(user_id=nmp_user_id).update({'logout': True})
    db.session.commit()
    db.session.flush()
    logger.info(f"Deleted {deleted_cookies_count} cookies, marked {updated_accounts_count} accounts as logged out")
    return deleted_cookies_count


def _notify_c_client_logout(nmp_user_id, nmp_username, client_id=None):
    """Notify C-Client user logout"""
    # Check if there are active connections
    user_connections = c_client_ws.user_connections.get(nmp_user_id, []) if hasattr(c_client_ws, 'user_connections') else []
    
    # Filter connections by client_id if provided (to only logout specific C-Client)
    if client_id:
        logger.info(f"Filtering connections by client_id: {client_id}")
        user_connections = [ws for ws in user_connections if getattr(ws, 'client_id', None) == client_id]
        logger.info(f"Found {len(user_connections)} connections matching client_id {client_id}")
    
    active_connections = [ws for ws in user_connections if c_client_ws.is_connection_valid(ws)]
    
    if not active_connections:
        logger.info(f"No active connections for user {nmp_user_id}" + (f" with client_id {client_id}" if client_id else ""))
        return False
    
    # Send logout notification
    with app.app_context():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            notify_result = loop.run_until_complete(c_client_ws.notify_user_logout(
                nmp_user_id, 
                nmp_username,
                website_root_path=get_nsn_base_url(),
                website_name='NSN',
                client_id=client_id  # Pass client_id to only notify specific C-Client
            ))
            logger.info(f"Logout notification sent: {notify_result}")
            return notify_result
        except Exception as e:
            logger.error(f"Error notifying C-client: {e}")
            return False
        finally:
            loop.close()


def _cleanup_websocket_connections(nmp_user_id):
    """Clean up WebSocket connections"""
    # Remove user from connection pool
    if hasattr(c_client_ws, 'user_connections') and nmp_user_id in c_client_ws.user_connections:
        user_connections = c_client_ws.user_connections[nmp_user_id]
        
        # Mark connections as closed
        for ws in user_connections:
            ws._closed_by_logout = True
            # Clean connection cache
            websocket_id = id(ws)
            if hasattr(c_client_ws, 'connection_validity_cache') and websocket_id in c_client_ws.connection_validity_cache:
                del c_client_ws.connection_validity_cache[websocket_id]
        
        # Notify NodeManager to clean up hierarchy structure
        if hasattr(c_client_ws, 'node_manager') and c_client_ws.node_manager:
            for ws in user_connections:
                try:
                    
                    connection = ClientConnection(
                        websocket=ws,
                        node_id=getattr(ws, 'node_id', 'unknown'),
                        user_id=getattr(ws, 'user_id', 'unknown'),
                        username=getattr(ws, 'username', 'unknown'),
                        domain_id=getattr(ws, 'domain_id', None),
                        cluster_id=getattr(ws, 'cluster_id', None),
                        channel_id=getattr(ws, 'channel_id', None),
                        is_domain_main_node=getattr(ws, 'is_domain_main_node', False),
                        is_cluster_main_node=getattr(ws, 'is_cluster_main_node', False),
                        is_channel_main_node=getattr(ws, 'is_channel_main_node', False)
                    )
                    c_client_ws.node_manager.remove_connection(connection)
                except Exception as e:
                    logger.warning(f"Error notifying NodeManager: {e}")
        
        # Remove from connection pool
        del c_client_ws.user_connections[nmp_user_id]
        logger.info(f"Removed {len(user_connections)} connections for user {nmp_user_id}")
    
    # Clean other connection pools
    for pool_name in ['node_connections', 'client_connections']:
        if hasattr(c_client_ws, pool_name):
            pool = getattr(c_client_ws, pool_name)
            for key, connections in list(pool.items()):
                connections[:] = [ws for ws in connections if not (hasattr(ws, 'user_id') and ws.user_id == nmp_user_id)]
                if not connections:
                    del pool[key]


def _cleanup_internal_cache(nmp_user_id):
    """Clean up internal cache"""
    cache_keys = ['user_sessions', 'user_cookies', 'auto_login_cache', 'connection_cache']
    for cache_key in cache_keys:
        if hasattr(c_client_ws, cache_key):
            cache = getattr(c_client_ws, cache_key)
            if nmp_user_id in cache:
                del cache[nmp_user_id]


def _handle_existing_cookie_check(nmp_user_id, nmp_username, channel_id=None, node_id=None):
    """Check and handle existing cookies with cluster verification"""
    existing_cookie = UserCookie.query.filter_by(user_id=nmp_user_id).first()
    
    if not existing_cookie:
        logger.info(f"No existing cookie found for user {nmp_user_id}")
        return None
    
    logger.info(f"Found existing cookie for user {nmp_user_id}")
    logger.info(f"Channel ID: {channel_id}, Node ID: {node_id}")
    
    # Get NSN user information
    nsn_username = existing_cookie.username
    nsn_user_id = None
    
    try:
        nsn_user_info = nsn_client.query_user_info(nsn_username)
        if nsn_user_info.get('success'):
            nsn_user_id = nsn_user_info.get('user_id')
    except Exception as e:
        logger.warning(f"Error querying NSN user info: {e}")
    
    # Send session to C-Client with cluster verification
    try:
        # Get user's WebSocket connection for cluster verification
        websocket_connection = None
        if c_client_ws and hasattr(c_client_ws, 'user_connections'):
            user_connections = c_client_ws.user_connections.get(nmp_user_id, [])
            if user_connections:
                websocket_connection = user_connections[0]  # Use first connection
                logger.info(f"Found WebSocket connection for user {nmp_user_id}")
                
                # Extract channel_id and node_id from connection (if not provided in parameters)
                if not channel_id:
                    channel_id = getattr(websocket_connection, 'channel_id', None)
                    logger.info(f"Extracted channel_id from connection: {channel_id}")
                if not node_id:
                    node_id = getattr(websocket_connection, 'node_id', None)
                    logger.info(f"Extracted node_id from connection: {node_id}")
            else:
                logger.warning(f"No WebSocket connection found for user {nmp_user_id}")
        
        # If WebSocket connection and channel_id/node_id exist, use send_session_if_appropriate for cluster verification
        if websocket_connection and channel_id and node_id:
            logger.info(f"===== USING CLUSTER VERIFICATION FOR EXISTING COOKIE =====")
            logger.info(f"User ID: {nmp_user_id}")
            logger.info(f"Channel ID: {channel_id}")
            logger.info(f"Node ID: {node_id}")
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Use send_session_if_appropriate, which performs cluster verification internally
            send_result = loop.run_until_complete(
                c_client_ws.send_session_if_appropriate(nmp_user_id, websocket_connection, is_reregistration=False)
            )
            
            loop.close()
            
            if send_result:
                logger.info(f"✅ Session sent to C-Client with cluster verification passed")
                return _return_success_response(existing_cookie.cookie, 'Existing session found and sent to C-Client after verification')
            else:
                logger.warning(f"❌ Cluster verification failed or session send failed")
                return _return_error_response('Cluster verification failed', 403)
        else:
            # No WebSocket connection or no channel_id/node_id, send directly (no cluster verification)
            # This case is for: new users' first connection, or single-node environment
            logger.info(f"No WebSocket connection or missing cluster info, sending session without cluster verification")
            logger.info(f"Reason: websocket_connection={bool(websocket_connection)}, channel_id={channel_id}, node_id={node_id}")
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            send_result = loop.run_until_complete(send_session_to_client_func(
                nmp_user_id, 
                existing_cookie.cookie, 
                nsn_user_id, 
                nsn_username,
                website_root_path=get_nsn_base_url(),
                website_name='NSN',
                session_partition='persist:nsn',
                reset_logout_status=True
            ))
            
            loop.close()
            
            logger.info(f"Session sent to C-Client: {send_result}")
            return _return_success_response(existing_cookie.cookie, 'Existing session found and sent to C-Client')
        
    except Exception as e:
        logger.error(f"Failed to send session to C-Client: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return _return_error_response('Failed to send session to C-Client', 500)


def _handle_nsn_session_check(nmp_user_id, node_id, auto_refresh, channel_id=None):
    """Check if NSN has session data"""
    try:
        session_response = requests.get(get_nsn_api_url('session_data'), timeout=10)
        
        if session_response.status_code == 200:
            session_data = session_response.json()
            if session_data.get('success'):
                nsn_session_cookie = session_data.get('session_cookie')
                nsn_user_id = session_data.get('nsn_user_id')
                nsn_username = session_data.get('nsn_username')
                
                logger.info(f"NSN session data found: {nsn_username} (ID: {nsn_user_id})")
                
                # Save session and send to C-Client
                if not _save_and_send_session(nmp_user_id, nsn_username, nsn_session_cookie, nsn_user_id, node_id, auto_refresh, reset_logout_status=True, channel_id=channel_id):
                    return _return_error_response('Failed to save NSN session to database', 500)
                
                return _return_success_response(nsn_session_cookie, 'NSN session retrieved and sent to C-Client')
        
        logger.info("No NSN session data available")
        return None
        
    except Exception as e:
        logger.warning(f"Failed to check NSN session data: {e}")
        return None


def _handle_nsn_form_login(nmp_user_id, nmp_username, provided_account, provided_password, node_id, auto_refresh, channel_id=None):
    """Handle NSN form login"""
    logger.info(f"Processing NSN form login for user {nmp_user_id}")
    
    nmp_params = _generate_nmp_params(nmp_user_id, nmp_username)
    login_result = nsn_client.login_with_nmp(provided_account, provided_password, nmp_params)
    
    if not login_result['success']:
        logger.error(f"NSN login failed: {login_result.get('error')}")
        return _return_error_response('Wrong account or password, please try again or sign up with NMP')
    
    # Extract NSN user information
    nsn_user_id = login_result.get('user_info', {}).get('user_id')
    nsn_username = login_result.get('user_info', {}).get('username')
    
    # Use NMP user information as fallback
    if not nsn_username:
        nsn_username = nmp_username
    if not nsn_user_id:
        nsn_user_id = nmp_user_id
    
    logger.info(f"NSN login successful: {nsn_username} (ID: {nsn_user_id})")
    
    # Save session and send to C-Client
    if not _save_and_send_session(nmp_user_id, nsn_username, login_result['session_cookie'], nsn_user_id, node_id, auto_refresh, reset_logout_status=True, channel_id=channel_id):
        return _return_error_response('Failed to save session to database', 500)
    
    return _return_success_response(login_result['session_cookie'], 'NSN form login successful and session sent to C-Client')


def _handle_existing_account_login(nmp_user_id, nmp_username, request_type, node_id, auto_refresh, channel_id=None):
    """Handle existing account login"""
    # Query account based on request type
    if request_type == 1:  # Manual login
        existing_account = UserAccount.query.filter_by(user_id=nmp_user_id, website='nsn').first()
    else:  # Auto-login
        existing_account = UserAccount.query.filter_by(user_id=nmp_user_id, website='nsn', logout=False).first()
    
    if not existing_account:
        logger.info(f"No existing account found for user {nmp_user_id}")
        return None
    
    logger.info(f"Found existing account for user {nmp_user_id}")
    
    # Check credential validity
    if not existing_account.password or len(existing_account.password) == 0:
        logger.error(f"No valid NSN credentials for user {nmp_user_id}")
        return _return_error_response('No valid NSN credentials found. Please sign up with NMP first.')
    
    # Use existing account to login to NSN
    nmp_params = _generate_nmp_params(nmp_user_id, nmp_username)
    login_result = nsn_client.login_with_nmp(existing_account.account, existing_account.password, nmp_params)
    
    if not login_result['success']:
        logger.error(f"NSN login failed: {login_result.get('error')}")
        return _return_error_response('Login failed with existing account')
    
    # Extract NSN user information
    nsn_user_id = login_result.get('user_info', {}).get('user_id')
    nsn_username = login_result.get('user_info', {}).get('username')
    
    # Use NMP user information as fallback
    if not nsn_username:
        nsn_username = nmp_username
    if not nsn_user_id:
        nsn_user_id = nmp_user_id
    
    logger.info(f"NSN login successful: {nsn_username} (ID: {nsn_user_id})")
    
    # Reset logout status
    try:
        UserAccount.query.filter_by(user_id=nmp_user_id, website='nsn').update({'logout': False})
        db.session.commit()
    except Exception as e:
        logger.warning(f"Failed to reset logout status: {e}")
    
    # Save session and send to C-Client
    if not _save_and_send_session(nmp_user_id, nsn_username, login_result['session_cookie'], nsn_user_id, node_id, auto_refresh, reset_logout_status=True, channel_id=channel_id):
        return _return_error_response('Failed to save session to database', 500)
    
    return _return_success_response(login_result['session_cookie'], 'Logged in with existing account and session sent to C-Client')


def _generate_credentials(nmp_username):
    """Generate NSN username and password"""
    
    # Generate username
    unique_username = f"{nmp_username}{int(time.time())}"
    
    # Generate password
    uppercase = random.choice(string.ascii_uppercase)
    lowercase = random.choice(string.ascii_lowercase)
    digit = random.choice(string.digits)
    special = random.choice('@#$%^&+=!')
    
    remaining_chars = ''.join(random.choices(
        string.ascii_letters + string.digits + '@#$%^&+=!', 
        k=8
    ))
    
    password_chars = list(uppercase + lowercase + digit + special + remaining_chars)
    random.shuffle(password_chars)
    generated_password = ''.join(password_chars)
    
    return unique_username, generated_password


def _handle_signup_with_nmp(nmp_user_id, nmp_username, node_id, auto_refresh, channel_id=None):
    """Handle Signup with NMP"""
    logger.info(f"Processing signup request for user {nmp_user_id}")
    
    # Check if account already exists
    existing_account = UserAccount.query.filter_by(user_id=nmp_user_id, website='nsn').first()
    
    if existing_account:
        logger.info(f"Found existing account for user {nmp_user_id}, using existing credentials")
        unique_username = existing_account.account  # FIXED: Use 'account' field, not 'nsn_username'
        generated_password = existing_account.password
        skip_nsn_registration = True
    else:
        logger.info(f"Creating new account for user {nmp_user_id}")
        unique_username, generated_password = _generate_credentials(nmp_username)
        skip_nsn_registration = False
        
        # Save account to database
        signup_data = _generate_signup_data(unique_username, nmp_username, generated_password)
        try:
            save_account_to_db_func(nmp_user_id, nmp_username, unique_username, generated_password, signup_data)
        except Exception as e:
            logger.error(f"Failed to save account to database: {e}")
            return _return_error_response('Failed to create account', 500)
    
    # Only attempt NSN registration when creating new account
    if not skip_nsn_registration:
        try:
            signup_data = _generate_signup_data(unique_username, nmp_username, generated_password)
            requests.post(get_nsn_api_url('signup'), data=signup_data, timeout=5, allow_redirects=False)
        except Exception as e:
            logger.warning(f"NSN registration request failed (expected): {e}")
    else:
        logger.info(f"Skipping NSN registration for existing account")
    
    # Attempt to login to NSN
    try:
        
        nmp_params = _generate_nmp_params(nmp_user_id, nmp_username)
        login_data = {
            'username': unique_username,
            'password': generated_password
        }
        login_data.update(nmp_params)
        
        login_response = requests.post(get_nsn_api_url('login'), data=login_data, timeout=30, allow_redirects=False)
        
        # Log login response details for debugging
        logger.info(f"NSN login response status: {login_response.status_code}")
        logger.info(f"NSN login response headers: {dict(login_response.headers)}")
        if login_response.text:
            logger.info(f"NSN login response text (first 500 chars): {login_response.text[:500]}")
        
        # Extract session cookie
        session_cookie = None
        if 'set-cookie' in login_response.headers:
            cookies = login_response.headers['set-cookie']
            if isinstance(cookies, list):
                cookies = '; '.join(cookies)
            session_match = re.search(r'session=([^;]+)', cookies)
            if session_match:
                session_cookie = f"session={session_match.group(1)}"
        
        if login_response.status_code == 302 or (login_response.status_code == 200 and session_cookie):
            logger.info("NSN login successful after registration")
            
            # Get session data
            try:
                session_response = requests.get(get_nsn_api_url('session_data'), timeout=10)
                if session_response.status_code == 200:
                    session_data = session_response.json()
                    if session_data.get('success'):
                        session_cookie = session_data.get('session_cookie')
                        nsn_user_id = session_data.get('nsn_user_id')
                        nsn_username = session_data.get('nsn_username')
                    else:
                        nsn_user_id = None
                        nsn_username = unique_username
                else:
                    nsn_user_id = None
                    nsn_username = unique_username
            except Exception as e:
                logger.warning(f"Failed to get session data: {e}")
                nsn_user_id = None
                nsn_username = unique_username
            
            # Save session and asynchronously send to C-Client
            try:
                save_cookie_to_db_func(nmp_user_id, nsn_username, session_cookie, node_id, auto_refresh, nsn_user_id, nsn_username)
                
                def send_session_async():
                    # CRITICAL FIX: Pass channel_id and node_id for cluster verification
                    _send_session_to_client(nmp_user_id, session_cookie, nsn_user_id, nsn_username, reset_logout_status=True, channel_id=channel_id, node_id=node_id)
                
                thread = threading.Thread(target=send_session_async)
                thread.daemon = True
                thread.start()
                
                return _return_success_response(session_cookie, 'User registered and logged in successfully')
                
            except Exception as e:
                logger.error(f"Failed to save and send session: {e}")
                return _return_error_response(f'Failed to save session: {str(e)}', 500)
        else:
            logger.error(f"NSN login failed with status {login_response.status_code}")
            logger.error(f"NSN login response text: {login_response.text}")
            
            # Check if the error is about account already exists
            if "Account already exists" in login_response.text:
                logger.error("NSN returned 'Account already exists' error during login attempt")
                return _return_error_response('Account already exists! Please use "Login with No More Password" instead.')
            else:
                return _return_error_response('Signup to website failed: Login failed after registration')
            
    except Exception as e:
        logger.error(f"Error during NSN login attempt: {e}")
        return _return_error_response(f'Signup to website failed: {str(e)}')


def _handle_logout_request(nmp_user_id, nmp_username, client_id=None):
    """Handle logout request"""
    logger.info(f"Processing logout request for user {nmp_user_id}" + (f" (client_id: {client_id})" if client_id else ""))
    
    try:
        # 1. Delete database records
        deleted_count = _delete_user_data(nmp_user_id)
        
        # 2. Notify C-Client (this handles connection cleanup internally)
        # Pass client_id to only logout specific C-Client connection
        _notify_c_client_logout(nmp_user_id, nmp_username, client_id)
        
        # 3. Clean up WebSocket connections
        # CRITICAL FIX: Don't directly delete connections here
        # notify_user_logout already handles connection cleanup (marks as closed_by_logout, waits for feedback)
        # Directly deleting connections can interfere with concurrent login requests
        # _cleanup_websocket_connections(nmp_user_id)  # Commented out - handled by notify_user_logout
        
        # 4. Clean up internal cache
        _cleanup_internal_cache(nmp_user_id)
        
        # 5. Clean up invalid connections
        c_client_ws.cleanup_invalid_connections()
        
        logger.info(f"User {nmp_user_id} logged out successfully")
        return jsonify({
            'success': True,
            'message': 'User logged out successfully',
            'cleared_count': deleted_count,
            'user_id': nmp_user_id,
            'username': nmp_username
        })
        
    except Exception as e:
        logger.error(f"Error during logout process: {e}")
        traceback.print_exc()
        return _return_error_response(f'Logout failed: {str(e)}', 500)


@bind_routes.route('/bind', methods=['POST'])
def bind():
    """B-Client bind API endpoint for NMP signup/login"""
    try:
        # Parse request parameters
        request_data, error_response = _parse_bind_request()
        if error_response:
            return error_response
        
        # Extract parameters
        nmp_user_id = request_data['nmp_user_id']
        nmp_username = request_data['nmp_username']
        request_type = request_data['request_type']
        domain_id = request_data['domain_id']
        node_id = request_data['node_id']
        channel_id = request_data['channel_id']
        client_id = request_data['client_id']
        auto_refresh = request_data['auto_refresh']
        provided_account = request_data['provided_account']
        provided_password = request_data['provided_password']
        nsn_session_cookie = request_data['nsn_session_cookie']
        nsn_user_id = request_data['nsn_user_id']
        nsn_username = request_data['nsn_username']
        
        # Handle logout request (request_type = 2)
        if request_type == 2:  # logout
            return _handle_logout_request(nmp_user_id, nmp_username, client_id)
        
        # 0. Handle NSN already logged in successfully case (new flow)
        if nsn_session_cookie and nsn_user_id and nsn_username:
            return _handle_nsn_session_provided(nmp_user_id, nmp_username, nsn_session_cookie, nsn_user_id, nsn_username, node_id, auto_refresh, channel_id)
        
        # 1. Query user_cookies (with cluster verification if needed)
        result = _handle_existing_cookie_check(nmp_user_id, nmp_username, channel_id, node_id)
        if result:
            return result
        
        # 2. Check if NSN has session data (Login with NMP scenario)
        if not provided_account and not provided_password and request_type == 1:
            result = _handle_nsn_session_check(nmp_user_id, node_id, auto_refresh, channel_id)
            if result:
                return result

        # 3. Handle NSN form login (if account and password are provided)
        if provided_account and provided_password:
            return _handle_nsn_form_login(nmp_user_id, nmp_username, provided_account, provided_password, node_id, auto_refresh, channel_id)

        # 4. Query user_accounts
        result = _handle_existing_account_login(nmp_user_id, nmp_username, request_type, node_id, auto_refresh, channel_id)
        if result:
            return result
        
        # 5. Call NSN registration interface
        if request_type == 0:  # signup
            return _handle_signup_with_nmp(nmp_user_id, nmp_username, node_id, auto_refresh, channel_id)
        else:
            # request_type == 1 (bind) but no existing account found
            logger.error(f"No existing account found for user {nmp_user_id} and bind request")
            return _return_error_response('Wrong account or password, please try again or sign up with NMP')
        
    except Exception as e:
        logger.error(f"Bind API error: {e}")
        traceback.print_exc()
        return _return_error_response(str(e), 500)