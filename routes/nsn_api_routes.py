"""
NSN API Routes
Handles NSN-related API endpoints
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
import json
import time
import requests

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger

# Create blueprint for NSN API routes
nsn_api_routes = Blueprint('nsn_api_routes', __name__)

# Initialize logger
logger = get_bclient_logger('nsn_api_routes')

# These will be injected when blueprint is registered
db = None
UserCookie = None
nsn_client = None


def init_nsn_api_routes(database, user_cookie_model, nsn_service):
    """Initialize NSN API routes with database models and NSN client"""
    global db, UserCookie, nsn_client
    db = database
    UserCookie = user_cookie_model
    nsn_client = nsn_service


@nsn_api_routes.route('/api/nsn/user-info', methods=['POST'])
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


@nsn_api_routes.route('/api/nsn/current-user', methods=['POST'])
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


@nsn_api_routes.route('/api/nsn/login', methods=['POST'])
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


@nsn_api_routes.route('/api/nsn/status')
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

