# Standard library imports
import asyncio
import builtins
import json
import logging
import os
import random
import re
import secrets
import socket
import sqlite3
import string
import threading
import time
import traceback
from datetime import datetime, timedelta

# Third-party imports
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import requests

# Optional third-party imports
try:
    import websockets
except ImportError:
    websockets = None

# Local application imports
from utils.logger import get_bclient_logger, setup_print_redirect
from utils.config_manager import get_nsn_url, get_nsn_host, get_nsn_port

# Set up log redirection immediately (takes effect on module import)
logger = get_bclient_logger('app')
print_redirect = setup_print_redirect('app')

# Redirect print to logger
builtins.print = print_redirect

logger.info("B-Client application module imported")

if websockets is None:
    logger.warning("WebSocket dependencies not available. Install with: pip install websockets")

def safe_close_websocket(websocket, reason="Connection closed"):
    """
    Universal function for safely closing WebSocket connections
    Can be used in both synchronous and asynchronous contexts
    """
    try:
        if hasattr(websocket, 'close'):
            # Mark connection as closed (before attempting to close)
            websocket._closed_by_logout = True
            
            # Try to close connection - use asyncio.run to handle async close
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(websocket.close(code=1000, reason=reason))
                loop.close()
                # WebSocket close() called - this is handled by the logging system
                return True
            except Exception as close_error:
                # Error in async close - this is handled by the logging system
                # Mark as closed even if async close fails
                return True
        else:
            # WebSocket has no close method - this is handled by the logging system
            return False
    except Exception as e:
        # Error closing WebSocket - this is handled by the logging system
        return False

# Import database models
from services.models import db, UserCookie, UserAccount, init_db

# Import service modules
from services.nsn_client import NSNClient
from services.db_operations import save_cookie_to_db as db_save_cookie, save_account_to_db as db_save_account
from services.websocket_client import CClientWebSocketClient, init_websocket_client
from services.websocket_server import start_websocket_server, init_websocket_server
from services.sync_manager import SyncManager
from services.cluster_verification import init_cluster_verification, cluster_verification_service
from services.nodeManager import NodeManager

# Import route blueprints
from routes.page_routes import page_routes
from routes.api_routes import api_routes, init_api_routes
from routes.nsn_api_routes import nsn_api_routes, init_nsn_api_routes
from routes.b_client_api_routes import b_client_api_routes
from routes.c_client_api_routes import c_client_api_routes, init_c_client_api_routes
from routes.bind_routes import bind_routes, init_bind_routes
from routes.node_management_routes import node_management_routes, init_node_management_routes

app = Flask(__name__)
app.config['SECRET_KEY'] = 'b-client-enterprise-secret-key'

# Use standard SQLite database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///b_client_secure.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
init_db(app)

# Register blueprints
app.register_blueprint(page_routes)
app.register_blueprint(api_routes)
app.register_blueprint(nsn_api_routes)
app.register_blueprint(b_client_api_routes)
app.register_blueprint(c_client_api_routes)
app.register_blueprint(bind_routes)
app.register_blueprint(node_management_routes)

# Note: Page routes have been moved to routes/page_routes.py
# Note: Basic API routes have been moved to routes/api_routes.py
# Note: NSN API routes have been moved to routes/nsn_api_routes.py
# Note: B-Client API routes have been moved to routes/b_client_api_routes.py
# Note: C-Client API routes have been moved to routes/c_client_api_routes.py
# Note: Core bind route has been moved to routes/bind_routes.py

# Core business logic routes remain below

@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'B-Client Flask API Server'
    })

@app.route('/api/user/logout-status', methods=['GET'])
def get_user_logout_status():
    """Get user logout status for C-Client to check before auto-login"""
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id parameter is required'}), 400
        
        logger.info(f"Checking logout status for user: {user_id}")
        
        # Query user_accounts table for logout status
        user_account = UserAccount.query.filter_by(
            user_id=user_id,
            website='nsn'
        ).first()
        
        if user_account:
            logout_status = user_account.logout
            logger.info(f"User {user_id} logout status: {logout_status}")
            logger.info(f"User account details - user_id: {user_account.user_id}, website: {user_account.website}")
            logger.info(f"Logout field type: {type(logout_status)}, value: {logout_status}")
            return jsonify({
                'user_id': user_id,
                'logout': logout_status,
                'found': True
            })
        else:
            logger.warning(f"No user account found for user: {user_id}")
            return jsonify({
                'user_id': user_id,
                'logout': False,
                'found': False
            })
            
    except Exception as e:
        logger.error(f"Error checking logout status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def get_stats():
    try:
        auto_refresh_count = UserCookie.query.filter_by(auto_refresh=True).count()
        auto_register_count = UserAccount.query.filter_by(auto_generated=True).count()
        total_cookies_count = UserCookie.query.count()
        
        return jsonify({
            'autoRefreshUsers': auto_refresh_count,
            'autoRegisteredUsers': auto_register_count,
            'totalCookies': total_cookies_count
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cookies', methods=['GET'])
def get_cookies():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id is required'}), 400
        
        # Query user's cookie (should only have one record)
        cookie = UserCookie.query.filter_by(user_id=user_id).first()
        
        if cookie:
            # Found cookie: only return status, don't send session immediately
            # Session will be sent after WebSocket registration completes
            logger.info(f"Found cookie for user {user_id}")
            logger.info(f"Cookie details - username: {cookie.username}, node_id: {cookie.node_id}")
            logger.info(f"Session will be sent after WebSocket registration completes")
            
            return jsonify({
                'success': True,
                'has_cookie': True,
                'message': 'Cookie found and session sent to C-Client'
            })
        else:
            # Cookie not found: return failure response
            logger.info(f"No cookie found for user {user_id}")
            return jsonify({
                'success': False,
                'has_cookie': False,
                'message': 'No cookie found for user'
            })
            
    except Exception as e:
        logger.error(f"Error querying cookies: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/cookies', methods=['POST'])
def add_cookie():
    try:
        data = request.get_json()
        required_fields = ['user_id', 'username', 'cookie']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        # Delete existing cookies for this user_id
        UserCookie.query.filter_by(user_id=data['user_id']).delete()
        
        # Add new cookie
        cookie = UserCookie(
            user_id=data['user_id'],
            username=data['username'],
            node_id=data.get('node_id'),
            cookie=data['cookie'],
            auto_refresh=data.get('auto_refresh', False),
            refresh_time=datetime.fromisoformat(data['refresh_time']) if data.get('refresh_time') else None
        )
        
        db.session.add(cookie)
        db.session.commit()
        
        return jsonify({'message': 'Cookie added successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id is required'}), 400
        
        accounts = UserAccount.query.filter_by(user_id=user_id).all()
        result = []
        for account in accounts:
            result.append({
                'user_id': account.user_id,
                'username': account.username,
                'website': account.website,
                'account': account.account,
                'email': account.email,
                'first_name': account.first_name,
                'last_name': account.last_name,
                'location': account.location,
                'registration_method': account.registration_method,
                'auto_generated': account.auto_generated,
                'create_time': account.create_time.isoformat()
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts', methods=['POST'])
def add_account():
    try:
        data = request.get_json()
        required_fields = ['user_id', 'username', 'website', 'account', 'password']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        # Check if account already exists
        existing = UserAccount.query.filter_by(
            user_id=data['user_id'],
            username=data['username'],
            website=data['website'],
            account=data['account']
        ).first()
        
        if existing:
            # Update existing account
            existing.password = data['password']
            existing.email = data.get('email')
            existing.first_name = data.get('first_name')
            existing.last_name = data.get('last_name')
            existing.location = data.get('location')
            existing.registration_method = data.get('registration_method', 'manual')
            existing.auto_generated = data.get('auto_generated', False)
        else:
            # Create new account
            account = UserAccount(
                user_id=data['user_id'],
                username=data['username'],
                website=data['website'],
                account=data['account'],
                password=data['password'],
                email=data.get('email'),
                first_name=data.get('first_name'),
                last_name=data.get('last_name'),
                location=data.get('location'),
                registration_method=data.get('registration_method', 'manual'),
                auto_generated=data.get('auto_generated', False)
            )
            db.session.add(account)
        
        db.session.commit()
        return jsonify({'message': 'Account saved successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/<user_id>/<username>/<website>/<account>', methods=['DELETE'])
def delete_account(user_id, username, website, account):
    try:
        account_obj = UserAccount.query.filter_by(
            user_id=user_id,
            username=username,
            website=website,
            account=account
        ).first()
        
        if not account_obj:
            return jsonify({'error': 'Account not found'}), 404
        
        db.session.delete(account_obj)
        db.session.commit()
        
        return jsonify({'message': 'Account deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Configuration API Routes
@app.route('/api/config/environment', methods=['POST'])
def set_environment():
    try:
        data = request.get_json()
        environment = data.get('environment', 'local')
        
        # Save environment to config file
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
        else:
            config = {}
        
        config['current_environment'] = environment
        
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        return jsonify({'message': f'Environment set to {environment}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/environment', methods=['GET'])
def get_environment():
    try:
        from utils.config_manager import get_current_environment
        environment = get_current_environment()
        return jsonify({'environment': environment})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/database/info')
def database_info():
    try:
        # Get database statistics
        total_cookies = UserCookie.query.count()
        total_accounts = UserAccount.query.count()
        # Get domain count from NodeManager connection pools instead of database
        if hasattr(c_client_ws, 'node_manager') and c_client_ws.node_manager:
            total_domains = len(c_client_ws.node_manager.domain_pool)
        else:
            total_domains = 0
        
        # Get recent activity
        recent_cookies = UserCookie.query.order_by(UserCookie.create_time.desc()).limit(5).all()
        recent_accounts = UserAccount.query.order_by(UserAccount.create_time.desc()).limit(5).all()
        
        return jsonify({
            'database_stats': {
                'total_cookies': total_cookies,
                'total_accounts': total_accounts,
                'total_domains': total_domains
            },
            'recent_cookies': [
                {
                    'user_id': cookie.user_id,
                    'username': cookie.username,
                    'create_time': cookie.create_time.isoformat()
                } for cookie in recent_cookies
            ],
            'recent_accounts': [
                {
                    'user_id': account.user_id,
                    'username': account.username,
                    'website': account.website,
                    'create_time': account.create_time.isoformat()
                } for account in recent_accounts
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/node/offline', methods=['POST'])
def trigger_node_offline():
    """Trigger node offline cleanup"""
    try:
        data = request.get_json()
        node_id = data.get('node_id')
        
        if not node_id:
            return jsonify({'error': 'node_id is required'}), 400
        
        # Trigger node offline cleanup
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(c_client_ws.handle_node_offline(node_id))
            return jsonify({
                'success': True,
                'message': f'Node {node_id} offline cleanup completed',
                'node_id': node_id
            })
        finally:
            loop.close()
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# NSN API Integration
class NSNClient:
    def __init__(self):
        self.base_url = self.get_nsn_url()
        self.session = requests.Session()
    
    def get_nsn_url(self):
        """Get NSN URL based on current environment"""
        # Use the updated config manager function
        return get_nsn_url()
    
    def query_user_info(self, username):
        """Query user information from NSN"""
        try:
            url = f"{self.base_url}/api/user-info"
            data = {'username': username}
            response = self.session.post(url, json=data, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'success': False, 'error': f'HTTP {response.status_code}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_current_user(self, session_cookie):
        """Get current user from NSN using session cookie"""
        try:
            url = f"{self.base_url}/api/current-user"
            
            # Ensure proper cookie format
            if session_cookie and not session_cookie.startswith('session='):
                session_cookie = f"session={session_cookie}"
            
            headers = {'Cookie': session_cookie}
            response = self.session.get(url, headers=headers, timeout=30)
            
            logger.info(f"Current user API response status: {response.status_code}")
            logger.info(f"Current user API response content: {response.text[:200] if response.text else 'Empty'}")
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'success': False, 'error': f'HTTP {response.status_code}'}
        except Exception as e:
            logger.error(f"get_current_user error: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_current_user_from_session(self):
        """Get current user from NSN using the same session object that was used for login"""
        try:
            url = f"{self.base_url}/api/current-user"
            response = self.session.get(url, timeout=5)
            
            logger.info(f"Current user API (from session) response status: {response.status_code}")
            logger.info(f"Current user API (from session) response content: {response.text[:200] if response.text else 'Empty'}")
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'success': False, 'error': f'HTTP {response.status_code}'}
        except Exception as e:
            logger.error(f"get_current_user_from_session error: {e}")
            return {'success': False, 'error': str(e)}
    
    def login_with_nmp(self, username, password, nmp_params):
        """Login to NSN with NMP parameters"""
        try:
            url = f"{self.base_url}/login"
            
            # Prepare login data with NMP parameters (matching original B-Client)
            data = {
                'username': username,
                'password': password
            }
            
            # Add NMP parameters if provided
            if nmp_params:
                data.update(nmp_params)
            else:
                # Add default NMP parameters like original B-Client
                data.update({
                    'nmp_bind': 'true',
                    'nmp_bind_type': 'bind',
                    'nmp_auto_refresh': 'true',
                    'nmp_client_type': 'c-client',
                    'nmp_timestamp': str(int(time.time() * 1000))
                })
            
            # Use form-encoded data like original B-Client
            logger.info(f"Sending login request to NSN: {url}")
            logger.info(f"Request data keys: {list(data.keys())}")
            logger.info(f"Username: {data.get('username', 'NOT_SET')}")
            logger.info(f"Password length: {len(data.get('password', ''))}")
            logger.info(f"NMP parameters: {[k for k in data.keys() if k.startswith('nmp_')]}")
            
            response = self.session.post(url, data=data, timeout=30, allow_redirects=False)
            
            logger.info(f"NSN login response status: {response.status_code}")
            logger.info(f"Response headers: {dict(response.headers)}")
            logger.info(f"Response content length: {len(response.content) if response.content else 0}")
            
            # Extract session cookie from response headers
            session_cookie = None
            if 'set-cookie' in response.headers:
                cookies = response.headers['set-cookie']
                if isinstance(cookies, list):
                    cookies = '; '.join(cookies)
                
                # Extract session cookie
                session_match = re.search(r'session=([^;]+)', cookies)
                if session_match:
                    session_cookie = f"session={session_match.group(1)}"
                    logger.info(f"Session cookie extracted: {session_cookie}")
            
            # NSN login success is indicated by 302 redirect or 200 with session cookie
            is_success = response.status_code == 302 or (response.status_code == 200 and session_cookie)
            
            if is_success:
                logger.info("NSN login successful, getting user info...")
                
                # Get user information from NSN using the same session object
                # This ensures the session cookie is properly maintained
                user_info = self.get_current_user_from_session()
                
                return {
                    'success': True,
                    'session_cookie': session_cookie,
                    'redirect_url': response.headers.get('Location', url),
                    'user_info': user_info
                }
            else:
                return {'success': False, 'error': f'Login failed with HTTP {response.status_code}'}
        except Exception as e:
            logger.error(f"NSN login error: {e}")
            return {'success': False, 'error': str(e)}
    
    def register_user(self, signup_data, nmp_params=None):
        """Register a new user with NSN and then login to get session"""
        try:
            logger.info(f"===== REGISTERING NEW USER =====")
            logger.info(f"Signup data: {signup_data}")
            logger.info(f"NMP params: {nmp_params}")
            
            # Generate a secure password for NMP registration
            
            # Generate a password that meets NSN requirements:
            # - At least 8 characters
            # - At least one uppercase letter
            # - At least one lowercase letter  
            # - At least one number
            # - At least one special character
            def generate_secure_password():
                # Define character sets
                uppercase = string.ascii_uppercase
                lowercase = string.ascii_lowercase
                digits = string.digits
                special_chars = '@#$%^&+=!'
                
                # Ensure at least one character from each required set
                password = [
                    secrets.choice(uppercase),
                    secrets.choice(lowercase),
                    secrets.choice(digits),
                    secrets.choice(special_chars)
                ]
                
                # Fill the rest with random characters from all sets
                all_chars = uppercase + lowercase + digits + special_chars
                for _ in range(4):  # Total length will be 8
                    password.append(secrets.choice(all_chars))
                
                # Shuffle the password
                secrets.SystemRandom().shuffle(password)
                return ''.join(password)
            
            generated_password = generate_secure_password()
            logger.info(f"Generated secure password for NMP registration: {generated_password}")
            
            # Generate unique username to avoid conflicts
            
            base_username = signup_data.get('username')
            
            # Clean base username: remove non-alphanumeric characters
            clean_base = re.sub(r'[^A-Za-z0-9]', '', base_username)
            
            # Ensure base username doesn't exceed 16 characters (leave space for suffix)
            if len(clean_base) > 16:
                clean_base = clean_base[:16]
            
            # Generate a random suffix (4 characters: 2 letters + 2 digits)
            random_suffix = ''.join(secrets.choice(string.ascii_lowercase) for _ in range(2)) + \
                           ''.join(secrets.choice(string.digits) for _ in range(2))
            
            # Combine username, ensuring total length doesn't exceed 20 characters
            unique_username = f"{clean_base}{random_suffix}"
            
            # Final length check
            if len(unique_username) > 20:
                unique_username = unique_username[:20]
            
            logger.info(f"Generated unique username: {unique_username}")
            logger.info(f"Username length: {len(unique_username)}")
            logger.info(f"Username validation: {'PASS' if re.match(r'^[A-Za-z0-9]+$', unique_username) and len(unique_username) <= 20 else 'FAIL'}")
            
            # Prepare registration data
            registration_data = {
                'username': unique_username,
                'email': signup_data.get('email'),
                'first_name': signup_data.get('first_name'),
                'last_name': signup_data.get('last_name'),
                'location': signup_data.get('location'),
                'password': generated_password,
                'confirm_password': generated_password
            }
            
            # Add NMP parameters if provided
            if nmp_params:
                registration_data.update(nmp_params)
            
            logger.info(f"Registration data: {registration_data}")
            logger.info(f"===== CALLING NSN SIGNUP ENDPOINT =====")
            logger.info(f"Signup URL: {self.base_url}/signup")
            logger.info(f"Request method: POST")
            logger.info(f"Request data keys: {list(registration_data.keys())}")
            logger.info(f"NMP parameters included: {bool(nmp_params)}")
            logger.info(f"===== END CALLING NSN SIGNUP ENDPOINT =====")
            
            # Call NSN signup endpoint (without B-Client headers to get normal HTML response)
            signup_url = f"{self.base_url}/signup"
            
            logger.info(f"===== CALLING NSN SIGNUP ENDPOINT =====")
            logger.info(f"Signup URL: {signup_url}")
            logger.info(f"Username: {unique_username}")
            logger.info(f"Password: {generated_password[:3]}...")
            logger.info(f"===== END CALLING NSN SIGNUP ENDPOINT =====")
            
            # Call NSN signup endpoint (fire and forget - don't wait for response)
            try:
                response = self.session.post(signup_url, data=registration_data, timeout=5, allow_redirects=False)
                logger.info(f"Registration request sent (status: {response.status_code})")
            except Exception as e:
                logger.warning(f"Registration request failed (expected): {e}")
            
            # Assume registration is successful, proceed immediately
            logger.info("Assuming registration successful, proceeding with login...")
            
            # Now login with the registered user credentials to get session
            username = unique_username  # Use the unique username
            password = generated_password  # Use the generated password
            
            logger.info(f"Attempting to login with username: {username}")
            logger.info(f"Login password length: {len(password)}")
            logger.info(f"Login password preview: {password[:3]}...")
            
            # Prepare login data
            login_data = {
                'username': username,
                'password': password
            }
            
            # Add NMP parameters if provided
            if nmp_params:
                login_data.update(nmp_params)
            
            # Call NSN login endpoint
            login_url = f"{self.base_url}/login"
            login_response = self.session.post(login_url, data=login_data, timeout=30, allow_redirects=False)
            
            logger.info(f"Login response status: {login_response.status_code}")
            logger.info(f"Login response headers: {dict(login_response.headers)}")
            
            # Extract session cookie from login response
            session_cookie = None
            if 'set-cookie' in login_response.headers:
                cookies = login_response.headers['set-cookie']
                if isinstance(cookies, list):
                    cookies = '; '.join(cookies)
                
                # Extract session cookie
                session_match = re.search(r'session=([^;]+)', cookies)
                if session_match:
                    session_cookie = f"session={session_match.group(1)}"
                    logger.info(f"Session cookie extracted from login: {session_cookie[:50]}...")
            
            # Check if login was successful (302 redirect or 200 with session cookie)
            if login_response.status_code == 302 or (login_response.status_code == 200 and session_cookie):
                logger.info("Login successful after registration")
                
                # Get user information to confirm login
                user_info = self.get_current_user(session_cookie)
                if user_info.get('success'):
                        logger.info(f"User info confirmed: {user_info.get('username')} (ID: {user_info.get('user_id')})")
                        
                        return {
                            'success': True,
                            'session_cookie': session_cookie,
                            'user_info': user_info,
                            'redirect_url': signup_url,
                            'generated_password': generated_password,
                            'unique_username': unique_username
                        }
                else:
                    logger.warning(f"Login successful but user info retrieval failed: {user_info.get('error')}")
                    return {
                        'success': True,
                        'session_cookie': session_cookie,
                        'user_info': None,
                        'redirect_url': signup_url,
                        'generated_password': generated_password,
                        'unique_username': unique_username
                    }
            else:
                logger.error(f"Login failed after registration with status {login_response.status_code}")
                logger.error(f"Login response text: {login_response.text[:500]}...")
                return {'success': False, 'error': f'Signup to website failed: Login failed with HTTP {login_response.status_code}'}
                
        except Exception as e:
            logger.error(f"Registration error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {'success': False, 'error': str(e)}

# Initialize NSN client
nsn_client = NSNClient()

# WebSocket Client for C-Client communication

# Note: CClientWebSocketClient class has been moved to services/websocket_client.py
# Note: WebSocket server startup has been moved to services/websocket_server.py


# Initialize C-Client WebSocket client (without send_session_to_client, will inject later)
init_websocket_client(app, db, UserCookie, UserAccount)
c_client_ws = CClientWebSocketClient() if websockets else None

# Initialize WebSocket server
init_websocket_server(websockets, asyncio, c_client_ws)

# Initialize cluster verification service (global service for this B-Client instance)
if c_client_ws:
    init_cluster_verification(c_client_ws, db)
    logger.info("B-Client cluster verification service initialized (global service)")
    logger.info(f"Service object: {cluster_verification_service}")

# Initialize API routes with database models and services
init_api_routes(db, UserCookie, UserAccount, c_client_ws)
init_nsn_api_routes(db, UserCookie, nsn_client)
init_c_client_api_routes(c_client_ws)
# Note: init_bind_routes and send_session_to_client injection will be called after send_session_to_client is defined

# Start WebSocket server when app starts
start_websocket_server()

# NSN API Routes
@app.route('/api/nsn/user-info', methods=['POST'])
def nsn_user_info():
    """Query user information from NSN"""
    try:
        data = request.get_json()
        username = data.get('username')
        
        if not username:
            return jsonify({'success': False, 'error': 'Username is required'}), 400
        
        result = nsn_client.query_user_info(username)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/nsn/current-user', methods=['POST'])
def nsn_current_user():
    """Get current user from NSN"""
    try:
        data = request.get_json()
        session_cookie = data.get('session_cookie')
        
        if not session_cookie:
            return jsonify({'success': False, 'error': 'Session cookie is required'}), 400
        
        result = nsn_client.get_current_user(session_cookie)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/nsn/login', methods=['POST'])
def nsn_login():
    """Login to NSN with NMP parameters"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        nmp_params = data.get('nmp_params', {})
        user_id = data.get('user_id')
        
        if not username or not password:
            return jsonify({'success': False, 'error': 'Username and password are required'}), 400
        
        # Perform NSN login
        result = nsn_client.login_with_nmp(username, password, nmp_params)
        
        if result['success']:
            # Store session data in database (like original B-Client)
            session_data = {
                'nsn_session_data': {
                    'loggedin': True,
                    'user_id': result.get('user_info', {}).get('user_id'),
                    'username': username,
                    'role': result.get('user_info', {}).get('role', 'traveller'),
                    'nmp_user_id': nmp_params.get('nmp_user_id'),
                    'nmp_username': nmp_params.get('nmp_username'),
                    'nmp_client_type': 'c-client',
                    'nmp_timestamp': str(int(time.time() * 1000))
                },
                'nsn_user_id': result.get('user_info', {}).get('user_id'),
                'nsn_username': username,
                'nsn_role': result.get('user_info', {}).get('role', 'traveller'),
                'timestamp': int(time.time() * 1000)
            }
            
            # Store in user_cookies table
            if user_id:
                try:
                    # Delete existing cookie for this user
                    UserCookie.query.filter_by(user_id=user_id).delete()
                    
                    # Add new cookie
                    cookie = UserCookie(
                        user_id=user_id,
                        username=username,
                        cookie=json.dumps(session_data),
                        auto_refresh=True,
                        refresh_time=datetime.now()
                    )
                    
                    db.session.add(cookie)
                    db.session.commit()
                    
                    result['session_data'] = session_data
                    logger.info(f"Stored NSN session for user: {username}")
                except Exception as e:
                    logger.warning(f"Failed to store session: {e}")
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/nsn/status')
def nsn_status():
    """Check NSN server status"""
    try:
        # Try to access NSN root page instead of /api/health which doesn't exist in production
        url = f"{nsn_client.base_url}/"
        logger.info(f"NSN Status Check: Attempting to access {url}")
        
        response = requests.get(url, timeout=10)
        logger.info(f"NSN Status Check: Response status {response.status_code}")

        if response.status_code == 200:
            logger.info("NSN Status Check: Success - NSN is online")
            return jsonify({
                'success': True,
                'nsn_url': nsn_client.base_url,
                'status': 'online',
                'response_time': response.elapsed.total_seconds()
            })
        else:
            logger.warning(f"NSN Status Check: Failed - HTTP {response.status_code}")
            return jsonify({
                'success': False,
                'nsn_url': nsn_client.base_url,
                'status': 'offline',
                'error': f'HTTP {response.status_code}'
            })
    except Exception as e:
        logger.error(f"NSN Status Check: Exception occurred - {str(e)}")
        return jsonify({
            'success': False,
            'nsn_url': nsn_client.base_url,
            'status': 'offline',
            'error': str(e)
        })

@app.route('/api/b-client/info')
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

# C-Client WebSocket API Routes
@app.route('/api/c-client/status')
def c_client_status():
    """Check C-Client WebSocket server status and connected clients"""
    if not c_client_ws:
        return jsonify({
            'success': False,
            'error': 'WebSocket functionality not available',
            'connected': False,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # Get connection info using the new method
    connection_info = c_client_ws.get_connection_info()
    
    return jsonify({
        'success': True,
        'websocket_server': {
            'enabled': True,
            'host': c_client_ws.config.get('server_host', '0.0.0.0'),
            'port': c_client_ws.config.get('server_port', 8766),
            'status': 'running'
        },
        'connected_clients': connection_info,
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/api/c-client/update-cookie', methods=['POST'])
def c_client_update_cookie():
    """Update cookie in C-Client via WebSocket"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        username = data.get('username')
        cookie = data.get('cookie')
        auto_refresh = data.get('auto_refresh', False)

        if not all([user_id, username, cookie]):
            return jsonify({'success': False, 'error': 'user_id, username, and cookie are required'}), 400

        # Send WebSocket message
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(c_client_ws.update_cookie(user_id, username, cookie, auto_refresh))
        loop.close()

        return jsonify({
            'success': True,
            'message': 'Cookie update sent to C-Client',
            'user_id': user_id,
            'username': username
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/c-client/notify-login', methods=['POST'])
def c_client_notify_login():
    """Notify C-Client of user login via WebSocket"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        username = data.get('username')
        session_data = data.get('session_data', {})

        if not user_id or not username:
            return jsonify({'success': False, 'error': 'user_id and username are required'}), 400

        # Send WebSocket message
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(c_client_ws.notify_user_login(user_id, username, session_data))
        loop.close()

        return jsonify({
            'success': True,
            'message': 'Login notification sent to C-Client',
            'user_id': user_id,
            'username': username
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/c-client/notify-logout', methods=['POST'])
def c_client_notify_logout():
    """Notify C-Client of user logout via WebSocket"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        username = data.get('username')

        if not user_id or not username:
            return jsonify({'success': False, 'error': 'user_id and username are required'}), 400

        # Send WebSocket message
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(c_client_ws.notify_user_logout(user_id, username))
        loop.close()

        return jsonify({
            'success': True,
            'message': 'Logout notification sent to C-Client',
            'user_id': user_id,
            'username': username
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/c-client/sync-session', methods=['POST'])
def c_client_sync_session():
    """Sync session data with C-Client via WebSocket"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        session_data = data.get('session_data', {})

        if not user_id:
            return jsonify({'success': False, 'error': 'user_id is required'}), 400

        # Send WebSocket message
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(c_client_ws.sync_session(user_id, session_data))
        loop.close()

        return jsonify({
            'success': True,
            'message': 'Session sync sent to C-Client',
            'user_id': user_id
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/websocket/check-user', methods=['POST'])
def websocket_check_user():
    """Check if a user is connected to the WebSocket server"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({'success': False, 'error': 'user_id is required'}), 400
        
        logger.info(f"Checking WebSocket connection for user_id: {user_id}")
        
        # Check if user exists in user_connections pool
        user_connected = user_id in c_client_ws.user_connections
        
        # Get WebSocket URL from configuration
        websocket_host = c_client_ws.config.get('server_host', '127.0.0.1')
        websocket_port = c_client_ws.config.get('server_port', 8766)
        websocket_url = f"ws://{websocket_host}:{websocket_port}"
        
        if user_connected:
            connections = c_client_ws.user_connections.get(user_id, [])
            logger.info(f"User {user_id} is connected with {len(connections)} connections")
        else:
            logger.info(f"User {user_id} is not connected to WebSocket")
        
        return jsonify({
            'success': True,
            'connected': user_connected,
            'websocket_url': websocket_url,
            'user_id': user_id,
            'connection_count': len(c_client_ws.user_connections.get(user_id, [])) if user_connected else 0
        })
        
    except Exception as e:

# Note: NMP Bind API Endpoint has been moved to routes/bind_routes.py
# This is the core business logic endpoint that handles signup/login integration

        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500

def save_cookie_to_db(user_id, username, raw_session_cookie, node_id, auto_refresh, nsn_user_id=None, nsn_username=None):
    """Save preprocessed session cookie to user_cookies table"""
    try:
        logger.info(f"===== SAVING COOKIE TO DATABASE =====")
        logger.info(f"User ID: {user_id}")
        logger.info(f"Username: {username}")
        logger.info(f"Node ID: {node_id}")
        logger.info(f"Auto refresh: {auto_refresh}")
        logger.info(f"NSN User ID: {nsn_user_id}")
        logger.info(f"NSN Username: {nsn_username}")
        logger.info(f"Raw session cookie length: {len(raw_session_cookie) if raw_session_cookie else 0}")
        logger.info(f"Raw session cookie preview: {raw_session_cookie[:100] if raw_session_cookie else 'None'}...")
        
        # Preprocess session data to JSON format
        logger.info(f"===== PREPROCESSING SESSION DATA =====")
        session_data_json = {
            'loggedin': True,
            'user_id': nsn_user_id or user_id,  # Use NMP user_id as fallback
            'username': nsn_username or username,  # Use NMP username as fallback
            'role': 'traveller',
            'nmp_user_id': user_id,
            'nmp_username': username,
            'nmp_client_type': 'c-client',
            'nmp_timestamp': str(int(time.time() * 1000))
        }
        
        # Encode to JSON string
        processed_cookie = json.dumps(session_data_json)
        logger.info(f"Preprocessed session data: {processed_cookie}")
        logger.info(f"Preprocessed cookie length: {len(processed_cookie)}")
        
        # Delete existing records
        logger.info(f"Deleting existing cookie records...")
        deleted_count = UserCookie.query.filter_by(user_id=user_id, username=username).delete()
        logger.info(f"Deleted {deleted_count} existing cookie records")
        
        # Create new record (save preprocessed JSON string)
        logger.info(f"Creating new cookie record with preprocessed data...")
        user_cookie = UserCookie(
            user_id=user_id,
            username=username,
            node_id=node_id,
            cookie=processed_cookie,  # Save preprocessed JSON string
            auto_refresh=auto_refresh,
            refresh_time=datetime.utcnow()
        )
        logger.info(f"Cookie record created: {user_cookie}")
        
        logger.info(f"Adding cookie record to session...")
        db.session.add(user_cookie)
        
        logger.info(f"Committing transaction...")
        db.session.commit()
        logger.info(f"Cookie saved to database successfully for user {user_id}")
        logger.info(f"===== END SAVING COOKIE TO DATABASE =====")
        
    except Exception as e:
        logger.error(f"Failed to save cookie to database: {e}")
        logger.info(f"Rolling back transaction...")
        db.session.rollback()
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise e

def save_account_to_db(user_id, username, account, password, account_data):
    """Save account information to user_accounts table"""
    try:
        logger.info(f"===== SAVING ACCOUNT TO DATABASE =====")
        logger.info(f"User ID: {user_id}")
        logger.info(f"Username: {username}")
        logger.info(f"Account: {account}")
        logger.info(f"Password length: {len(password) if password else 0}")
        logger.info(f"Account data: {account_data}")
        
        # Delete existing records
        logger.info(f"Deleting existing account records...")
        deleted_count = UserAccount.query.filter_by(
            user_id=user_id, 
            username=username, 
            website='nsn'
        ).delete()
        logger.info(f"Deleted {deleted_count} existing account records")
        
        # Create new record
        logger.info(f"Creating new account record...")
        user_account = UserAccount(
            user_id=user_id,
            username=username,
            website='nsn',
            account=account,
            password=password,
            email=account_data.get('email'),
            first_name=account_data.get('first_name'),
            last_name=account_data.get('last_name'),
            location=account_data.get('location'),
            registration_method='nmp_auto',
            auto_generated=True,
            logout=False  # Reset logout status for new registration
        )
        logger.info(f"Account record created: {user_account}")
        
        logger.info(f"Adding account record to session...")
        db.session.add(user_account)
        
        logger.info(f"Committing transaction...")
        db.session.commit()
        logger.info(f"Account saved to database successfully for user {user_id}")
        logger.info(f"===== END SAVING ACCOUNT TO DATABASE =====")
        
    except Exception as e:
        logger.error(f"Failed to save account to database: {e}")
        logger.info(f"Rolling back transaction...")
        db.session.rollback()
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise e

async def send_session_to_client(user_id, processed_session_cookie, nsn_user_id=None, nsn_username=None, website_root_path=None, website_name=None, session_partition=None, max_retries=3, reset_logout_status=False, channel_id=None, node_id=None):
    """Send preprocessed session data to C-Client via WebSocket with feedback and retry"""
    try:
        logger.info(f"===== SENDING SESSION TO C-CLIENT WITH FEEDBACK =====")
        logger.info(f"User ID: {user_id}")
        logger.info(f"Max retries: {max_retries}")
        logger.info(f"Reset logout status: {reset_logout_status}")
        logger.info(f"Processed session cookie length: {len(processed_session_cookie) if processed_session_cookie else 0}")
        logger.info(f"Processed session cookie: {processed_session_cookie}")
        
        # Reset logout status if requested (for manual login triggered session sends)
        if reset_logout_status:
            logger.info(f"===== RESETTING LOGOUT STATUS FOR SESSION SEND =====")
            try:
                with app.app_context():
                    user_account = UserAccount.query.filter_by(
                        user_id=user_id,
                        website='nsn'
                    ).first()
                    
                    if user_account:
                        logger.info(f"Found user account, resetting logout status from {user_account.logout} to False")
                        user_account.logout = False
                        db.session.commit()
                        logger.info(f"Logout status reset successfully")
                    else:
                        logger.warning(f"No user account found for user {user_id}")
            except Exception as e:
                logger.error(f"Error resetting logout status: {e}")
        
        if not c_client_ws:
            logger.warning(f"WebSocket client not available")
            logger.info(f"===== END SENDING SESSION: NO WEBSOCKET CLIENT =====")
            return False
            
        logger.info(f"WebSocket client available: {c_client_ws}")
        logger.info(f"WebSocket client instance ID: {id(c_client_ws)}")
        logger.info(f"User connections: {c_client_ws.user_connections}")
        logger.info(f"User connections object ID: {id(c_client_ws.user_connections)}")
        
        # Find WebSocket connections for this user
        logger.info(f"===== SESSION SEND DEBUG INFO =====")
        logger.info(f"Target user_id: {user_id}")
        logger.info(f"All user_connections keys: {list(c_client_ws.user_connections.keys())}")
        logger.info(f"All user_connections: {c_client_ws.user_connections}")
        
        if user_id in c_client_ws.user_connections:
            connections = c_client_ws.user_connections[user_id]
            logger.info(f"Found {len(connections)} connections for user {user_id}")
            
            # Log each connection's user_id in detail
            for i, conn in enumerate(connections):
                conn_user_id = getattr(conn, 'user_id', 'unknown')
                conn_node_id = getattr(conn, 'node_id', 'unknown')
                conn_client_id = getattr(conn, 'client_id', 'unknown')
                logger.info(f"Connection {i+1}: user_id={conn_user_id}, node_id={conn_node_id}, client_id={conn_client_id}")
        else:
            logger.warning(f"User {user_id} not found in user_connections")
            logger.info(f"Available users: {list(c_client_ws.user_connections.keys())}")
            logger.info(f"===== END SENDING SESSION: NO CONNECTIONS =====")
            return False
            
        # Try to send session data with retry support
        for attempt in range(max_retries):
            logger.info(f"===== SESSION SEND ATTEMPT {attempt + 1}/{max_retries} =====")
            
            success_count = 0
            successful_connections = []  # Track actually successful connections
            
            # Create feedback tracking dictionary BEFORE sending
            # This ensures the dictionary exists when C-Client sends feedback
            feedback_tracking = {conn: False for conn in connections}
            
            # Set up feedback tracking on ALL websocket objects BEFORE sending
            for websocket in connections:
                websocket._session_feedback_tracking = feedback_tracking
            
            logger.info(f"Feedback tracking pre-setup for {len(connections)} connections")
            
            # Send session data to all connections for this user
            logger.info(f"===== STARTING FOR LOOP: {len(connections)} connections to process =====")
            for i, websocket in enumerate(connections):
                logger.info(f"===== FOR LOOP ITERATION {i+1}/{len(connections)} =====")
                try:
                        logger.info(f"Checking connection {i+1}/{len(connections)} (attempt {attempt + 1})")
                        
                        # Check if connection is being logged out
                        if hasattr(websocket, '_logout_in_progress') and websocket._logout_in_progress:
                            logger.warning(f"Connection {i+1} logout in progress, skipping session send")
                            continue
                        
                        # Check if connection is still valid - prioritize our marker
                        if hasattr(websocket, '_closed_by_logout') and websocket._closed_by_logout:
                            logger.warning(f"Connection {i+1} was closed by logout, skipping")
                            continue
                        
                        # Check WebSocket's closed attribute
                        if hasattr(websocket, 'closed') and websocket.closed:
                            logger.warning(f"Connection {i+1} is closed (closed=True), skipping")
                            continue
                        
                        # Check connection state - stricter check
                        if hasattr(websocket, 'state'):
                            state_value = websocket.state
                            state_name = websocket.state.name if hasattr(websocket.state, 'name') else str(websocket.state)
                            
                            # Check state value (3 = CLOSED, 2 = CLOSING)
                            if state_value in [2, 3] or state_name in ['CLOSED', 'CLOSING']:
                                logger.warning(f"Connection {i+1} is in {state_name} state (value: {state_value}), skipping")
                                continue
                        
                        # Check close_code - if close_code is set, connection is closed
                        if hasattr(websocket, 'close_code') and websocket.close_code is not None:
                            logger.warning(f"Connection {i+1} has close_code {websocket.close_code}, skipping")
                            continue
                        
                        # Try to send test message to verify connection is really valid
                        try:
                            # Send a simple ping message to test connection
                            test_message = {'type': 'ping', 'timestamp': int(time.time() * 1000)}
                            await websocket.send(json.dumps(test_message))
                            logger.info(f"Connection {i+1} ping successful, connection is valid")
                        except Exception as ping_error:
                            logger.warning(f"Connection {i+1} ping failed: {ping_error}, skipping")
                            continue
                        
                        logger.info(f"Connection {i+1} is valid, sending session")
                        
                        # Extract NSN user info from cookie
                        nsn_user_id_from_cookie = None
                        nsn_username_from_cookie = None
                        
                        try:
                            cookie_data = json.loads(processed_session_cookie)
                            nsn_user_id_from_cookie = cookie_data.get('user_id')
                            nsn_username_from_cookie = cookie_data.get('username')
                            logger.info(f"Extracted from cookie - nsn_user_id: {nsn_user_id_from_cookie}, nsn_username: {nsn_username_from_cookie}")
                        except Exception as e:
                            logger.warning(f"Failed to parse cookie data: {e}")
                            # Use passed parameters as fallback
                            nsn_user_id_from_cookie = nsn_user_id
                            nsn_username_from_cookie = nsn_username
                        
                        # Use info extracted from cookie, use passed parameters if extraction fails
                        final_nsn_user_id = nsn_user_id_from_cookie or nsn_user_id
                        final_nsn_username = nsn_username_from_cookie or nsn_username
                        
                        # Directly use preprocessed session data
                        processed_session_data = {
                            'session_cookie': processed_session_cookie,  # Directly use preprocessed JSON string
                            'nsn_user_id': final_nsn_user_id,
                            'nsn_username': final_nsn_username,
                            'loggedin': True,
                            'role': 'traveller'
                        }
                        
                        # Add website config info
                        # Get NSN root URL from environment configuration
                        nsn_root_url = c_client_ws.get_nsn_root_url() if hasattr(c_client_ws, 'get_nsn_root_url') else get_nsn_url()
                        website_config = {
                            'root_path': website_root_path or nsn_root_url,
                            'name': website_name or 'NSN',
                            'session_partition': session_partition or 'persist:nsn',
                            'root_url': c_client_ws.get_nsn_root_url()  # Add NSN root URL
                        }
                        
                        # Get cluster verification result from websocket connection if available
                        verification_result = None
                        if hasattr(websocket, 'cluster_verification_result'):
                            verification_result = websocket.cluster_verification_result
                            logger.info(f"Found cluster verification result: {verification_result}")
                        
                        # Check total number of users in WebSocket user pool for message determination
                        total_users = len(c_client_ws.user_connections) if hasattr(c_client_ws, 'user_connections') else 0
                        logger.info(f"🔍 [Session Send] Total users in WebSocket pool: {total_users}")
                        
                        # Only send message field for validation scenarios (multiple users)
                        message = {
                            'type': 'auto_login',
                            'user_id': user_id,
                            'session_data': processed_session_data,
                            'website_config': website_config,
                            'nsn_user_id': final_nsn_user_id,
                            'nsn_username': final_nsn_username,
                            'timestamp': datetime.utcnow().isoformat(),
                            'channel_id': channel_id,
                            'node_id': node_id,
                            'cluster_verification': verification_result  # Add verification result to message
                        }
                        
                        # Only add message field for validation scenarios
                        if total_users > 1:
                            message['message'] = 'login success with validation'
                            logger.info(f"🔍 [Session Send] Multiple users detected ({total_users}), adding validation message")
                        else:
                            logger.info(f"🔍 [Session Send] Single user detected ({total_users}), no message field needed")
                        
                        # Check if WebSocket connection is still open using centralized validation
                        if hasattr(c_client_ws, 'is_connection_valid'):
                            if not c_client_ws.is_connection_valid(websocket):
                                logger.warning(f"WebSocket connection {i+1} is invalid, skipping...")
                                continue
                        else:
                            # Fallback to simple check if centralized validation is not available
                            try:
                                if hasattr(websocket, 'closed') and websocket.closed:
                                    logger.warning(f"WebSocket connection {i+1} is closed, skipping...")
                                    continue
                            except AttributeError:
                                # ServerConnection doesn't have 'closed' attribute, try to send anyway
                                pass
                        
                        message_json = json.dumps(message)
                        await websocket.send(message_json)
                        logger.info(f"Session data sent to C-Client connection {i+1} for user {user_id}")
                        success_count += 1
                        successful_connections.append(websocket)  # Track this successful connection
                        
                except websockets.exceptions.ConnectionClosed:
                        logger.warning(f"WebSocket connection {i+1} is closed, removing from pool...")
                        # Remove closed connection from pool
                        if user_id in c_client_ws.user_connections:
                            c_client_ws.user_connections[user_id] = [
                                conn for conn in c_client_ws.user_connections[user_id] 
                                if conn != websocket
                            ]
                        continue
                except Exception as e:
                        logger.error(f"Failed to send session to C-Client connection {i+1}: {e}")
                        # Don't print full traceback for connection errors
                        if "ConnectionClosed" not in str(e):
                            logger.error(f"Traceback: {traceback.format_exc()}")
            
            logger.info(f"===== FOR LOOP COMPLETED: {success_count} successful sends out of {len(connections)} connections =====")
            
            if success_count == 0:
                logger.error(f"Failed to send to any connections on attempt {attempt + 1}")
                continue
            
            # Wait for feedback - only wait for actually successful connections (already tracked above)
            logger.info(f"Waiting for session feedback from {len(successful_connections)} successful connections...")
            start_time = asyncio.get_event_loop().time()
            timeout = 5  # 5 second timeout (reduced from 30 for faster sync)
            
            # Wait for feedback from successfully sent connections only
            while asyncio.get_event_loop().time() - start_time < timeout:
                # Check feedback_tracking dictionary (shared with websocket objects)
                successful_feedbacks = [feedback_tracking[conn] for conn in successful_connections]
                if all(successful_feedbacks):
                    logger.info(f"All session feedback received for user {user_id} on attempt {attempt + 1}")
                    # Clean up feedback tracking
                    for websocket in successful_connections:
                        if hasattr(websocket, '_session_feedback_tracking'):
                            delattr(websocket, '_session_feedback_tracking')
                    
                    logger.info(f"===== END SENDING SESSION: SUCCESS =====")
                    return True
                
                await asyncio.sleep(0.5)
            else:
                # Timeout
                missing_feedback = [conn for conn in successful_connections if not feedback_tracking[conn]]
                logger.warning(f"Session feedback timeout on attempt {attempt + 1}")
                logger.warning(f"   Missing feedback from {len(missing_feedback)} connections")
                logger.warning(f"   Feedback status: {sum(feedback_tracking.values())} / {len(feedback_tracking)} received")
                
                # Clean up feedback tracking
                for websocket in successful_connections:
                    if hasattr(websocket, '_session_feedback_tracking'):
                        delattr(websocket, '_session_feedback_tracking')
                
                if attempt < max_retries - 1:
                    logger.info(f"Retrying session send... ({attempt + 2}/{max_retries})")
                    await asyncio.sleep(2)  # Wait 2 seconds before retry
                    continue
                else:
                    logger.error(f"Max retries reached, giving up")
                    break
            
            logger.error(f"===== END SENDING SESSION: FAILED AFTER {max_retries} ATTEMPTS =====")
            return False
        else:
            logger.warning(f"No WebSocket connections found for user {user_id}")
            logger.info(f"Available user connections: {list(c_client_ws.user_connections.keys())}")
            logger.info(f"===== END SENDING SESSION: NO CONNECTIONS =====")
            return False
            
    except Exception as e:
        logger.error(f"Error sending session to C-Client: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        logger.error(f"===== END SENDING SESSION: ERROR =====")
        return False


# Inject send_session_to_client into WebSocket client after it's defined
init_websocket_client(app, db, UserCookie, UserAccount, send_session_to_client)

# Initialize bind routes after send_session_to_client is defined
init_bind_routes(db, UserCookie, UserAccount, nsn_client, c_client_ws, 
                 save_cookie_to_db, save_account_to_db, send_session_to_client)

# Initialize node manager for node management system
logger.info("=" * 80)
logger.info("Initializing NodeManager for node management system...")
node_manager = NodeManager()
logger.info(f"NodeManager instance created: {node_manager}")
logger.info("Registering node management routes...")
init_node_management_routes(node_manager)
logger.info("Node management routes registered")

# Inject NodeManager into WebSocket client for C-Client registration
logger.info("Injecting NodeManager into WebSocket client...")
c_client_ws.node_manager = node_manager
logger.info(f"NodeManager injected into c_client_ws")
logger.info(f"   c_client_ws.node_manager = {c_client_ws.node_manager}")

# Reinitialize SyncManager with updated NodeManager
logger.info("Reinitializing SyncManager with updated NodeManager...")
from utils.config_manager import get_config_manager
config_manager = get_config_manager()
sync_manager = SyncManager(c_client_ws, node_manager, config_manager)
logger.info(f"SyncManager reinitialized: {sync_manager}")

# Inject SyncManager into WebSocket client
logger.info("Injecting SyncManager into WebSocket client...")
import services.websocket_client as ws_module
ws_module.sync_manager = sync_manager
logger.info(f"SyncManager injected into websocket_client module")
logger.info("=" * 80)

# ===== Security Code Cleanup Task =====
logger.info("=" * 80)
logger.info("Setting up security code cleanup task...")

def cleanup_old_security_codes():
    """Clean up security codes older than 15 minutes"""
    try:
        from datetime import datetime, timedelta
        from services.models import UserSecurityCode, db
        
        with app.app_context():
            # Calculate cutoff time (15 minutes ago)
            cutoff_time = datetime.utcnow() - timedelta(minutes=15)
            
            # Query old security codes
            old_codes = UserSecurityCode.query.filter(
                UserSecurityCode.create_time < cutoff_time
            ).all()
            
            if old_codes:
                logger.info(f"🧹 Cleaning up {len(old_codes)} old security codes...")
                for code in old_codes:
                    logger.info(f"🧹 Deleting security code for user {code.nmp_username} (created at {code.create_time})")
                    db.session.delete(code)
                
                db.session.commit()
                logger.info(f"✅ Successfully cleaned up {len(old_codes)} old security codes")
            else:
                logger.debug("✅ No old security codes to clean up")
                
    except Exception as e:
        logger.error(f"❌ Error cleaning up old security codes: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")

# Schedule cleanup task to run every 15 minutes
import threading

# Global variable to track cleanup timer
cleanup_timer = None

def schedule_cleanup_task():
    """Schedule periodic cleanup task"""
    global cleanup_timer
    cleanup_old_security_codes()
    # Schedule next cleanup in 15 minutes (900 seconds)
    # Use daemon thread to allow clean shutdown
    cleanup_timer = threading.Timer(900, schedule_cleanup_task)
    cleanup_timer.daemon = True  # Set as daemon thread so it won't block shutdown
    cleanup_timer.start()

# Start the cleanup task
schedule_cleanup_task()
logger.info("✅ Security code cleanup task scheduled (runs every 15 minutes)")
logger.info("=" * 80)


if __name__ == '__main__':
    logger.info("B-Client application starting...")
    
    with app.app_context():
        db.create_all()
        logger.info("Database initialized successfully")
    
    logger.info("Starting Flask server on 0.0.0.0:3000")
    
    # Configure Flask log level to reduce console output
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    app.run(debug=True, host='0.0.0.0', port=3000)
