"""
NSN Client Service
Handles all NSN API integration and communication
"""
import os
import json
import requests
import re
import time
import secrets
import string
import sys
import traceback

# Import logging system
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_bclient_logger
from utils.config_manager import get_nsn_url


class NSNClient:
    def __init__(self):
        # Initialize logger
        self.logger = get_bclient_logger('nsn_client')
        
        self.base_url = self.get_nsn_url()
        self.session = requests.Session()
    
    def get_nsn_url(self):
        """Get NSN URL based on current environment"""
        # Use the config manager instead of directly reading config file
        from utils.config_manager import get_nsn_base_url
        return get_nsn_base_url()
    
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
            
            self.logger.info(f"Current user API response status: {response.status_code}")
            self.logger.info(f"Current user API response content: {response.text[:200] if response.text else 'Empty'}")
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'success': False, 'error': f'HTTP {response.status_code}'}
        except Exception as e:
            self.logger.error(f"get_current_user error: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_current_user_from_session(self):
        """Get current user from NSN using the same session object that was used for login"""
        try:
            url = f"{self.base_url}/api/current-user"
            response = self.session.get(url, timeout=5)
            
            self.logger.info(f"Current user API (from session) response status: {response.status_code}")
            self.logger.info(f"Current user API (from session) response content: {response.text[:200] if response.text else 'Empty'}")
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'success': False, 'error': f'HTTP {response.status_code}'}
        except Exception as e:
            self.logger.error(f"get_current_user_from_session error: {e}")
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
            self.logger.info(f"Sending login request to NSN: {url}")
            self.logger.info(f"Request data keys: {list(data.keys())}")
            self.logger.info(f"Username: {data.get('username', 'NOT_SET')}")
            self.logger.info(f"Password length: {len(data.get('password', ''))}")
            self.logger.info(f"NMP parameters: {[k for k in data.keys() if k.startswith('nmp_')]}")
            
            response = self.session.post(url, data=data, timeout=30, allow_redirects=False)
            
            self.logger.info(f"NSN login response status: {response.status_code}")
            self.logger.info(f"Response headers: {dict(response.headers)}")
            self.logger.info(f"Response content length: {len(response.content) if response.content else 0}")
            
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
                    self.logger.info(f"Session cookie extracted: {session_cookie}")
            
            # NSN login success is indicated by 302 redirect or 200 with session cookie
            is_success = response.status_code == 302 or (response.status_code == 200 and session_cookie)
            
            if is_success:
                self.logger.info("NSN login successful, getting user info...")
                
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
            self.logger.error(f"NSN login error: {e}")
            return {'success': False, 'error': str(e)}
    
    def register_user(self, signup_data, nmp_params=None):
        """Register a new user with NSN and then login to get session"""
        try:
            self.logger.info(f"===== REGISTERING NEW USER =====")
            self.logger.info(f"Signup data: {signup_data}")
            self.logger.info(f"NMP params: {nmp_params}")
            
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
            self.logger.info(f"Generated secure password for NMP registration: {generated_password}")
            
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
            
            self.logger.info(f"Generated unique username: {unique_username}")
            self.logger.info(f"Username length: {len(unique_username)}")
            self.logger.info(f"Username validation: {'PASS' if re.match(r'^[A-Za-z0-9]+$', unique_username) and len(unique_username) <= 20 else 'FAIL'}")
            
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
            
            self.logger.info(f"Registration data: {registration_data}")
            self.logger.info(f"===== CALLING NSN SIGNUP ENDPOINT =====")
            self.logger.info(f"Signup URL: {self.base_url}/signup")
            self.logger.info(f"Request method: POST")
            self.logger.info(f"Request data keys: {list(registration_data.keys())}")
            self.logger.info(f"NMP parameters included: {bool(nmp_params)}")
            self.logger.info(f"===== END CALLING NSN SIGNUP ENDPOINT =====")
            
            # Call NSN signup endpoint (without B-Client headers to get normal HTML response)
            signup_url = f"{self.base_url}/signup"
            
            self.logger.info(f"===== CALLING NSN SIGNUP ENDPOINT =====")
            self.logger.info(f"Signup URL: {signup_url}")
            self.logger.info(f"Username: {unique_username}")
            self.logger.info(f"Password: {generated_password[:3]}...")
            self.logger.info(f"===== END CALLING NSN SIGNUP ENDPOINT =====")
            
            # Call NSN signup endpoint (fire and forget - don't wait for response)
            try:
                response = self.session.post(signup_url, data=registration_data, timeout=5, allow_redirects=False)
                self.logger.info(f"Registration request sent (status: {response.status_code})")
            except Exception as e:
                self.logger.warning(f"Registration request failed (expected): {e}")
            
            # Assume registration is successful, proceed immediately
            self.logger.info("Assuming registration successful, proceeding with login...")
            
            # Now login with the registered user credentials to get session
            username = unique_username  # Use the unique username
            password = generated_password  # Use the generated password
            
            self.logger.info(f"Attempting to login with username: {username}")
            self.logger.info(f"Login password length: {len(password)}")
            self.logger.info(f"Login password preview: {password[:3]}...")
            
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
            
            self.logger.info(f"Login response status: {login_response.status_code}")
            self.logger.info(f"Login response headers: {dict(login_response.headers)}")
            
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
                    self.logger.info(f"Session cookie extracted from login: {session_cookie[:50]}...")
            
            # Check if login was successful (302 redirect or 200 with session cookie)
            if login_response.status_code == 302 or (login_response.status_code == 200 and session_cookie):
                self.logger.info("Login successful after registration")
                
                # Get user information to confirm login
                user_info = self.get_current_user(session_cookie)
                if user_info.get('success'):
                        self.logger.info(f"User info confirmed: {user_info.get('username')} (ID: {user_info.get('user_id')})")
                        
                        return {
                            'success': True,
                            'session_cookie': session_cookie,
                            'user_info': user_info,
                            'redirect_url': signup_url,
                            'generated_password': generated_password,
                            'unique_username': unique_username
                        }
                else:
                    self.logger.warning(f"Login successful but user info retrieval failed: {user_info.get('error')}")
                    return {
                        'success': True,
                        'session_cookie': session_cookie,
                        'user_info': None,
                        'redirect_url': signup_url,
                        'generated_password': generated_password,
                        'unique_username': unique_username
                    }
            else:
                self.logger.error(f"Login failed after registration with status {login_response.status_code}")
                self.logger.error(f"Login response text: {login_response.text[:500]}...")
                return {'success': False, 'error': f'Signup to website failed: Login failed with HTTP {login_response.status_code}'}
                
        except Exception as e:
            self.logger.error(f"Registration error: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return {'success': False, 'error': str(e)}

