"""
B-Client Logging System
Unified logging management for all B-Client modules
"""
import os
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
import sys

class BClientLogger:
    """B-Client log manager"""
    
    def __init__(self, log_dir="logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Generate log filename (module_startup_date_time)
        start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = start_time
        
        # Log file paths
        self.main_log_file = self.log_dir / f"bclient_main_{start_time}.log"
        self.websocket_log_file = self.log_dir / f"bclient_websocket_{start_time}.log"
        self.nodemanager_log_file = self.log_dir / f"bclient_nodemanager_{start_time}.log"
        self.sync_log_file = self.log_dir / f"bclient_sync_{start_time}.log"  # Unified sync log file
        self.sync_manager_log_file = self.log_dir / f"bclient_sync_{start_time}.log"  # Redirect to sync file
        self.routes_log_file = self.log_dir / f"bclient_routes_{start_time}.log"
        self.app_log_file = self.log_dir / f"bclient_app_{start_time}.log"
        self.cluster_verification_log_file = self.log_dir / f"bclient_cluster_verification_{start_time}.log"
        self.security_code_log_file = self.log_dir / f"bclient_security_code_{start_time}.log"
        self.history_log_file = self.log_dir / f"bclient_history_{start_time}.log"
        
        # Initialize loggers for each module
        self._setup_loggers()
    
    def _setup_loggers(self):
        """Setup loggers for each module"""
        # Main application logger
        self.main_logger = self._create_logger(
            'bclient_main',
            self.main_log_file,
            level=logging.INFO
        )
        
        # WebSocket module logger
        self.websocket_logger = self._create_logger(
            'bclient_websocket',
            self.websocket_log_file,
            level=logging.INFO
        )
        
        # NodeManager module logger
        self.nodemanager_logger = self._create_logger(
            'bclient_nodemanager',
            self.nodemanager_log_file,
            level=logging.INFO
        )
        
        # SyncManager module logger
        self.sync_manager_logger = self._create_logger(
            'bclient_sync_manager',
            self.sync_manager_log_file,
            level=logging.INFO
        )
        
        # Routes module logger
        self.routes_logger = self._create_logger(
            'bclient_routes',
            self.routes_log_file,
            level=logging.INFO
        )
        
        # App module logger
        self.app_logger = self._create_logger(
            'bclient_app',
            self.app_log_file,
            level=logging.INFO
        )
        
        # Cluster Verification module logger
        self.cluster_verification_logger = self._create_logger(
            'bclient_cluster_verification',
            self.cluster_verification_log_file,
            level=logging.INFO
        )
        
        # Security Code module logger
        self.security_code_logger = self._create_logger(
            'bclient_security_code',
            self.security_code_log_file,
            level=logging.INFO
        )
        
        # History module logger
        self.history_logger = self._create_logger(
            'bclient_history',
            self.history_log_file,
            level=logging.INFO
        )
    
    def _create_logger(self, name, log_file, level=logging.INFO):
        """Create logger instance"""
        logger = logging.getLogger(name)
        logger.setLevel(level)
        
        # Avoid adding duplicate handlers
        if logger.handlers:
            return logger
        
        # File handler - use RotatingFileHandler to prevent log files from getting too large
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        
        # Console handler - show INFO and above levels for better debugging
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)  # Show INFO and above levels
        
        # Log format
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
    
    def get_logger(self, module_name):
        """Get corresponding logger based on module name"""
        module_map = {
            'websocket': self.websocket_logger,
            'websocket_server': self.websocket_logger,  # Use same logger for websocket server
            'nodemanager': self.nodemanager_logger,
            'sync_manager': self.sync_manager_logger,
            'routes': self.routes_logger,
            'app': self.app_logger,
            'main': self.main_logger,
            'cluster_verification': self.cluster_verification_logger,
            'security_code': self.security_code_logger,
            'history': self.history_logger
        }
        return module_map.get(module_name, self.main_logger)
    
    def log_startup_info(self):
        """Log startup information"""
        self.main_logger.info("=" * 60)
        self.main_logger.info(f"B-Client Starting at {datetime.now()}")
        self.main_logger.info(f"Log files created:")
        self.main_logger.info(f"  Main: {self.main_log_file}")
        self.main_logger.info(f"  WebSocket: {self.websocket_log_file}")
        self.main_logger.info(f"  NodeManager: {self.nodemanager_log_file}")
        self.main_logger.info(f"  SyncManager: {self.sync_manager_log_file}")
        self.main_logger.info(f"  Routes: {self.routes_log_file}")
        self.main_logger.info(f"  App: {self.app_log_file}")
        self.main_logger.info(f"  Cluster Verification: {self.cluster_verification_log_file}")
        self.main_logger.info(f"  Security Code: {self.security_code_log_file}")
        self.main_logger.info(f"  History: {self.history_log_file}")
        self.main_logger.info("=" * 60)

# Global logger instance
bclient_logger = BClientLogger()

def get_bclient_logger(module_name):
    """Convenience function to get B-Client module logger"""
    return bclient_logger.get_logger(module_name)

# Override print function to also log print output
class PrintToLogger:
    """Redirect print output to logs"""
    
    def __init__(self, logger):
        self.logger = logger
        self.original_print = print
    
    def __call__(self, *args, **kwargs):
        # Call original print
        self.original_print(*args, **kwargs)
        
        # Also log output to file
        message = ' '.join(str(arg) for arg in args)
        if message.strip():  # Only log non-empty messages
            self.logger.info(message)

# Replace print function
def setup_print_redirect(module_name):
    """Setup print redirection to logs"""
    logger = get_bclient_logger(module_name)
    return PrintToLogger(logger)
