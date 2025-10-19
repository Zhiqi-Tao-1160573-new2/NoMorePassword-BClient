"""
Database Operations Service
Handles all database CRUD operations for B-Client
"""
from datetime import datetime
import json
import time
import sys
import os
import traceback

# Import logging system
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_bclient_logger


def save_cookie_to_db(db, UserCookie, user_id, username, raw_session_cookie, node_id, auto_refresh, nsn_user_id=None, nsn_username=None, logger=None):
    """Save preprocessed session cookie to user_cookies table"""
    # Initialize logger if not provided
    if logger is None:
        logger = get_bclient_logger('db_operations')
    
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


def save_account_to_db(db, UserAccount, user_id, username, account, password, account_data, logger=None):
    """Save account information to user_accounts table"""
    # Initialize logger if not provided
    if logger is None:
        logger = get_bclient_logger('db_operations')
    
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

