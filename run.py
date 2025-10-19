#!/usr/bin/env python3
"""
B-Client Flask Application
Enterprise-level client for NoMorePassword Backend Service
"""

import os
import sys
from app import app
from services.models import db

# Import logging system
from utils.logger import get_bclient_logger, setup_print_redirect

# Cluster verification service is now handled in websocket_client.py

# Set up log redirection immediately (takes effect on module import)
logger = get_bclient_logger('main')
print_redirect = setup_print_redirect('main')

# Redirect print to logger
import builtins
builtins.print = print_redirect

logger.info("B-Client run.py module imported")

def create_database():
    """Create database tables if they don't exist"""
    try:
        with app.app_context():
            db.create_all()
            logger.info("Database tables created successfully")
    except Exception as e:
        logger.warning(f"Database creation warning: {e}")
        logger.info("If using SQLCipher, make sure pysqlcipher3 is installed")
        logger.info("Run: pip install pysqlcipher3")

def main():
    """Main entry point for the B-Client Flask application"""
    logger.info("🚀 Starting B-Client Flask Application...")
    logger.info("📊 Enterprise-level client for NoMorePassword Backend Service")
    
    # Create database tables
    create_database()
    
    # Get configuration
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 3000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    # Get environment from environment variable or config file
    from utils.config_manager import ConfigManager
    config_manager = ConfigManager()
    environment = os.environ.get('B_CLIENT_ENVIRONMENT') or config_manager.get_config().get('current_environment', 'local')
    
    logger.info(f"🌍 Environment: {environment}")
    if environment == 'production':
        logger.info("🚀 Running in PRODUCTION mode - connecting to comp693nsnproject.pythonanywhere.com")
    else:
        logger.info("🔧 Running in LOCAL mode - connecting to localhost:5000")
    
    logger.info(f"🌐 Server will start on http://{host}:{port}")
    logger.info(f"🔧 Debug mode: {debug}")
    
    # Only print access URLs in local development
    if environment == 'local':
        print("📱 Access the application at:")
        print(f"   - Main page: http://localhost:{port}")
        print(f"   - Dashboard: http://localhost:{port}/dashboard")
        print(f"   - History: http://localhost:{port}/history")
        print(f"   - API Health: http://localhost:{port}/api/health")
        print("\n" + "="*60)
    
    try:
        app.run(host=host, port=port, debug=debug)
    except KeyboardInterrupt:
        logger.info("\n👋 B-Client Flask Application stopped")
    except Exception as e:
        logger.error(f"Error starting B-Client Flask Application: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
