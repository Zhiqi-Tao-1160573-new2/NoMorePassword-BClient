"""
Configuration Manager
Manages application configuration from config.json
"""

# Standard library imports
import json
import os
from typing import Dict, Any, Optional

class ConfigManager:
    """Configuration manager for B-Client"""
    
    def __init__(self, config_path: str = None):
        """Initialize configuration manager"""
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
        self.config_path = config_path
        self._config = None
        self._load_config()
    
    def _load_config(self):
        """Load configuration from config.json"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            else:
                # Default configuration if file doesn't exist
                self._config = self._get_default_config()
        except Exception as e:
            print(f"Error loading config: {e}")
            self._config = self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            "current_environment": "local",
            "environments": {
                "local": {
                    "name": "Local Development Environment",
                    "api": {
                        "nsn_url": "http://localhost:5000",
                        "nsn_host": "localhost",
                        "nsn_port": 5000
                    },
                    "websocket": {
                        "enabled": True,
                        "server_host": "127.0.0.1",
                        "server_port": 8766
                    }
                },
                "production": {
                    "name": "Production Environment",
                    "api": {
                        "nsn_url": "https://comp693nsnproject.pythonanywhere.com",
                        "nsn_host": "comp693nsnproject.pythonanywhere.com",
                        "nsn_port": 443
                    },
                    "websocket": {
                        "enabled": True,
                        "server_host": "127.0.0.1",
                        "server_port": 8766
                    }
                }
            },
            "network": {
                "use_public_ip": False,
                "public_ip": "121.74.37.6",
                "local_ip": "127.0.0.1"
            },
            "default": {
                "autoRefreshIntervalMinutes": 30
            }
        }
    
    def get_config(self) -> Dict[str, Any]:
        """Get the complete configuration"""
        return self._config
    
    def get_nsn_config(self) -> Dict[str, Any]:
        """Get NSN configuration based on current environment"""
        # Check environment variable first, then config file
        import os
        current_env = os.environ.get('B_CLIENT_ENVIRONMENT') or self._config.get('current_environment', 'local')
        
        # Check for environment variable overrides first
        nsn_url = os.environ.get('NSN_PRODUCTION_URL')
        nsn_host = os.environ.get('NSN_PRODUCTION_HOST')
        nsn_port = os.environ.get('NSN_PRODUCTION_PORT')
        
        if current_env == 'production' and nsn_url:
            # Use environment variable configuration for production
            return {
                'base_url': nsn_url,
                'name': 'NSN Production Server',
                'api_endpoints': {
                    'session_data': f"{nsn_url}/api/nmp-session-data",
                    'signup': f"{nsn_url}/signup",
                    'login': f"{nsn_url}/login"
                }
            }
        
        # Get environment-specific configuration
        environments = self._config.get('environments', {})
        env_config = environments.get(current_env, environments.get('local', {}))
        api_config = env_config.get('api', {})
        
        # Ensure we have API configuration
        if not api_config:
            raise ValueError(f"No API configuration found for environment: {current_env}")
        
        # Use new environment-specific configuration
        base_url = api_config.get('nsn_url')
        if not base_url:
            raise ValueError(f"No nsn_url found in API configuration for environment: {current_env}")
        return {
            'base_url': base_url,
            'name': f"NSN {current_env.title()} Environment",
            'api_endpoints': {
                'session_data': f"{base_url}/api/nmp-session-data",
                'signup': f"{base_url}/signup",
                'login': f"{base_url}/login"
            }
        }
    
    def get_current_api_config(self) -> Dict[str, Any]:
        """Get current environment's API configuration"""
        import os
        current_env = os.environ.get('B_CLIENT_ENVIRONMENT') or self._config.get('current_environment', 'local')
        
        # Get environment-specific configuration
        environments = self._config.get('environments', {})
        env_config = environments.get(current_env, environments.get('local', {}))
        api_config = env_config.get('api', {})
        
        # Ensure we have API configuration
        if not api_config:
            raise ValueError(f"No API configuration found for environment: {current_env}")
        
        return api_config
    
    def get_current_websocket_config(self) -> Dict[str, Any]:
        """Get current environment's WebSocket configuration"""
        import os
        current_env = os.environ.get('B_CLIENT_ENVIRONMENT') or self._config.get('current_environment', 'local')
        
        # Get environment-specific configuration
        environments = self._config.get('environments', {})
        env_config = environments.get(current_env, environments.get('local', {}))
        websocket_config = env_config.get('websocket', {})
        
        # Ensure we have WebSocket configuration
        if not websocket_config:
            raise ValueError(f"No WebSocket configuration found for environment: {current_env}")
        
        return websocket_config

    def get_nsn_base_url(self) -> str:
        """Get NSN base URL"""
        nsn_config = self.get_nsn_config()
        return nsn_config['base_url']
    
    def get_nsn_api_url(self, endpoint: str) -> str:
        """Get NSN API URL for specific endpoint"""
        nsn_config = self.get_nsn_config()
        return nsn_config['api_endpoints'].get(endpoint, f"{nsn_config['base_url']}/{endpoint}")
    
    def get_current_environment(self) -> str:
        """Get current environment"""
        import os
        return os.environ.get('B_CLIENT_ENVIRONMENT') or self._config.get('current_environment', 'local')
    
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.get_current_environment() == 'production'
    
    def is_local(self) -> bool:
        """Check if running in local environment"""
        return self.get_current_environment() == 'local'

# Global configuration manager instance
_config_manager = None

def get_config_manager() -> ConfigManager:
    """Get global configuration manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager

def get_nsn_base_url() -> str:
    """Get NSN base URL from configuration"""
    return get_config_manager().get_nsn_base_url()

def get_nsn_api_url(endpoint: str) -> str:
    """Get NSN API URL for specific endpoint"""
    return get_config_manager().get_nsn_api_url(endpoint)

def get_current_environment() -> str:
    """Get current environment"""
    return get_config_manager().get_current_environment()

def is_production() -> bool:
    """Check if running in production environment"""
    return get_config_manager().is_production()

def is_local() -> bool:
    """Check if running in local environment"""
    return get_config_manager().is_local()

def get_current_api_config() -> Dict[str, Any]:
    """Get current environment's API configuration"""
    return get_config_manager().get_current_api_config()

def get_current_websocket_config() -> Dict[str, Any]:
    """Get current environment's WebSocket configuration"""
    return get_config_manager().get_current_websocket_config()

def get_nsn_host() -> str:
    """Get NSN host from configuration"""
    import os
    from urllib.parse import urlparse
    
    # Check environment variable first
    nsn_host = os.environ.get('NSN_PRODUCTION_HOST')
    if nsn_host:
        return nsn_host
    
    # Fall back to config manager
    nsn_url = get_nsn_url()
    parsed_url = urlparse(nsn_url)
    return parsed_url.hostname or 'localhost'

def get_nsn_port() -> int:
    """Get NSN port from configuration"""
    import os
    from urllib.parse import urlparse
    
    # Check environment variable first
    nsn_port = os.environ.get('NSN_PRODUCTION_PORT')
    if nsn_port:
        return int(nsn_port)
    
    # Fall back to config manager
    nsn_url = get_nsn_url()
    parsed_url = urlparse(nsn_url)
    return parsed_url.port or (443 if parsed_url.scheme == 'https' else 5000)

def get_nsn_url() -> str:
    """Get NSN URL from configuration"""
    config_manager = get_config_manager()
    nsn_config = config_manager.get_nsn_config()
    return nsn_config['base_url']
