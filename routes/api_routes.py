"""
API Routes
Handles basic API endpoints for B-Client
"""

# Standard library imports
import asyncio
import json
import os
import sys
from datetime import datetime

# Third-party imports
from flask import Blueprint, request, jsonify

# Local application imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger

# Create blueprint for API routes
api_routes = Blueprint('api_routes', __name__)

# Initialize logger
logger = get_bclient_logger('api_routes')

# These will be injected when blueprint is registered
db = None
UserCookie = None
UserAccount = None
c_client_ws = None


def init_api_routes(database, user_cookie_model, user_account_model, websocket_client):
    """Initialize API routes with database models and websocket client"""
    global db, UserCookie, UserAccount, c_client_ws
    db = database
    UserCookie = user_cookie_model
    UserAccount = user_account_model
    c_client_ws = websocket_client


@api_routes.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'B-Client Flask API Server'
    })


@api_routes.route('/api/user/logout-status', methods=['GET'])
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
            logger.debug(f"Logout field type: {type(logout_status)}, value: {logout_status}")
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


@api_routes.route('/api/stats')
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


@api_routes.route('/api/config')
def get_config():
    try:
        # Use the new config manager to get current environment's configuration
        from utils.config_manager import get_config_manager, get_current_api_config, get_current_websocket_config, get_current_environment
        
        config_manager = get_config_manager()
        current_env = get_current_environment()
        api_config = get_current_api_config()
        websocket_config = get_current_websocket_config()
        
        # Return current environment's configuration
        config = {
            "current_environment": current_env,
            "api": api_config,
            "websocket": websocket_config,
            "network": config_manager.get_config().get('network', {}),
            "default": {
                "autoRefreshIntervalMinutes": 30
            }
        }
        
        return jsonify(config)
    except Exception as e:
        return jsonify({'error': f'Configuration error: {str(e)}'}), 500


@api_routes.route('/api/cookies', methods=['GET'])
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
            print(f"🔍 B-Client: Session will be sent after WebSocket registration completes")
            
            return jsonify({
                'success': True,
                'has_cookie': True,
                'message': 'Cookie found and session sent to C-Client'
            })
        else:
            # Cookie not found: return failure response
            print(f"🔍 B-Client: No cookie found for user {user_id}")
            return jsonify({
                'success': False,
                'has_cookie': False,
                'message': 'No cookie found for user'
            })
            
    except Exception as e:
        print(f"❌ B-Client: Error querying cookies: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_routes.route('/api/cookies', methods=['POST'])
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


@api_routes.route('/api/accounts', methods=['GET'])
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


@api_routes.route('/api/accounts', methods=['POST'])
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


@api_routes.route('/api/accounts/<user_id>/<username>/<website>/<account>', methods=['DELETE'])
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
@api_routes.route('/api/config/environment', methods=['POST'])
def set_environment():
    try:
        data = request.get_json()
        environment = data.get('environment', 'local')
        
        # Validate environment value
        valid_environments = ['local', 'production']
        if environment not in valid_environments:
            return jsonify({'error': f'Invalid environment. Must be one of: {", ".join(valid_environments)}'}), 400
        
        # Save environment to config file
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
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


@api_routes.route('/api/config/environment', methods=['GET'])
def get_environment():
    try:
        from utils.config_manager import get_current_environment
        environment = get_current_environment()
        return jsonify({'environment': environment})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_routes.route('/api/database/info')
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


@api_routes.route('/api/node/offline', methods=['POST'])
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

