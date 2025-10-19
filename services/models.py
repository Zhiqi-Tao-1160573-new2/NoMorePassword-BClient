"""
B-Client Database Models
Database table definitions for B-Client Flask Application
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Import logging system
import sys
import os
sys.path.append(os.path.dirname(__file__))
from utils.logger import get_bclient_logger

# Initialize logger
logger = get_bclient_logger('models')

# Database instance (will be initialized in app.py)
db = SQLAlchemy()

class UserCookie(db.Model):
    """User Cookie Management Table
    
    Stores user cookie information for automatic login and session management.
    Supports multiple cookies per user across different nodes.
    """
    __tablename__ = 'user_cookies'
    
    # Primary Keys (Composite)
    user_id = db.Column(db.String(50), primary_key=True, comment='User ID')
    username = db.Column(db.String(255), primary_key=True, comment='Username')
    
    # Node Information
    node_id = db.Column(db.String(50), comment='Node ID where cookie was created')
    
    # Cookie Data
    cookie = db.Column(db.Text, comment='Cookie content (encrypted)')
    auto_refresh = db.Column(db.Boolean, default=False, comment='Enable automatic cookie refresh')
    refresh_time = db.Column(db.DateTime, comment='Last refresh timestamp')
    
    # Metadata
    create_time = db.Column(db.DateTime, default=datetime.utcnow, comment='Record creation time')
    
    def __repr__(self):
        return f'<UserCookie {self.username}@{self.user_id}>'

class UserAccount(db.Model):
    """User Account Management Table
    
    Stores detailed user account information including passwords, 
    personal details, and registration metadata.
    """
    __tablename__ = 'user_accounts'
    
    # Primary Keys (Composite)
    user_id = db.Column(db.String(50), primary_key=True, comment='User ID')
    username = db.Column(db.String(255), primary_key=True, comment='Username')
    website = db.Column(db.String(255), primary_key=True, comment='Website domain')
    account = db.Column(db.String(50), primary_key=True, comment='Account identifier')
    
    # Authentication
    password = db.Column(db.Text, comment='Plain text password for login')
    
    # Personal Information
    email = db.Column(db.String(255), comment='Email address')
    first_name = db.Column(db.String(255), comment='First name')
    last_name = db.Column(db.String(255), comment='Last name')
    location = db.Column(db.String(255), comment='User location')
    
    # Registration Metadata
    registration_method = db.Column(db.String(20), default='manual', comment='Registration method (manual/auto)')
    auto_generated = db.Column(db.Boolean, default=False, comment='Whether account was auto-generated')
    
    # Logout Status
    logout = db.Column(db.Boolean, default=False, comment='Whether user has logged out (prevents auto-login)')
    
    # Metadata
    create_time = db.Column(db.DateTime, default=datetime.utcnow, comment='Account creation time')
    
    def __repr__(self):
        return f'<UserAccount {self.username}@{self.website}>'

class UserSecurityCode(db.Model):
    """User Security Code Table
    
    Stores security codes for user authentication and verification.
    Links users with their domain, cluster, and channel hierarchy.
    """
    __tablename__ = 'user_security_codes'
    
    # Primary Key
    nmp_user_id = db.Column(db.String(50), primary_key=True, comment='NMP User ID (UUID)')
    
    # User Information
    nmp_username = db.Column(db.String(50), nullable=False, comment='NMP Username')
    
    # Hierarchy Information
    domain_id = db.Column(db.String(50), comment='Domain ID (UUID)')
    cluster_id = db.Column(db.String(50), comment='Cluster ID (UUID)')
    channel_id = db.Column(db.String(50), comment='Channel ID (UUID)')
    
    # Security Code
    security_code = db.Column(db.String(50), comment='Security Code (UUID)')
    
    # Metadata
    create_time = db.Column(db.DateTime, default=datetime.utcnow, comment='Record creation time')
    update_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='Last update time')
    
    def __repr__(self):
        return f'<UserSecurityCode {self.nmp_username}@{self.nmp_user_id}>'

# Note: DomainNode class removed - domain information now managed by NodeManager connection pools

# Database initialization function
def init_db(app):
    """Initialize database with Flask app context
    
    Args:
        app: Flask application instance
    """
    db.init_app(app)
    
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.warning(f"Database creation warning: {e}")
            logger.info("If using SQLCipher, make sure pysqlcipher3 is installed")
            logger.info("Run: pip install pysqlcipher3")

# Export all models for easy importing
__all__ = ['db', 'UserCookie', 'UserAccount', 'UserSecurityCode', 'init_db']
