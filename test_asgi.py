#!/usr/bin/env python3
"""
Test script for ASGI configuration
"""

import os
import sys

def test_imports():
    """Test if all required modules can be imported"""
    print("🧪 Testing imports...")
    
    try:
        # Test Flask app import
        from app import app, c_client_ws
        print("✅ Flask app and WebSocket client imported successfully")
        
        # Test ASGI app import
        from asgi_app import asgi_app, get_asgi_app
        print("✅ ASGI app imported successfully")
        
        # Test WSGI app import
        from wsgi_app import wsgi_app, application
        print("✅ WSGI app imported successfully")
        
        # Test required dependencies
        try:
            import hypercorn
            print("✅ Hypercorn imported successfully")
        except ImportError:
            print("⚠️ Hypercorn not available - install with: pip install hypercorn")
        
        try:
            import asgiref
            print("✅ asgiref imported successfully")
        except ImportError:
            print("⚠️ asgiref not available - install with: pip install asgiref")
        
        return True
        
    except Exception as e:
        print(f"❌ Import error: {e}")
        return False

def test_websocket_client():
    """Test WebSocket client configuration"""
    print("\n🧪 Testing WebSocket client...")
    
    try:
        from app import c_client_ws
        
        if c_client_ws:
            print("✅ WebSocket client initialized")
            print(f"   - Config: {c_client_ws.config}")
            print(f"   - Client ID: {c_client_ws.client_id}")
            print(f"   - Server host: {c_client_ws.config.get('server_host', '0.0.0.0')}")
            print(f"   - Server port: {c_client_ws.config.get('server_port', 8766)}")
            return True
        else:
            print("❌ WebSocket client is None")
            return False
            
    except Exception as e:
        print(f"❌ WebSocket client error: {e}")
        return False

def test_flask_app():
    """Test Flask app configuration"""
    print("\n🧪 Testing Flask app...")
    
    try:
        from app import app
        
        print("✅ Flask app initialized")
        print(f"   - Secret key configured: {'Yes' if app.config.get('SECRET_KEY') else 'No'}")
        print(f"   - Database URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
        print(f"   - Blueprints registered: {len(app.blueprints)}")
        
        # Test a simple route
        with app.test_client() as client:
            response = client.get('/api/health')
            if response.status_code == 200:
                print("✅ Health endpoint working")
                return True
            else:
                print(f"⚠️ Health endpoint returned status {response.status_code}")
                return False
                
    except Exception as e:
        print(f"❌ Flask app error: {e}")
        return False

def test_asgi_app():
    """Test ASGI app configuration"""
    print("\n🧪 Testing ASGI app...")
    
    try:
        from asgi_app import asgi_app, get_asgi_app
        
        app_instance = get_asgi_app()
        
        if app_instance:
            print("✅ ASGI app created successfully")
            print(f"   - App type: {type(app_instance)}")
            return True
        else:
            print("❌ ASGI app is None")
            return False
            
    except Exception as e:
        print(f"❌ ASGI app error: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 B-Client ASGI Configuration Test")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_websocket_client,
        test_flask_app,
        test_asgi_app
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    print("\n📊 Test Results:")
    print("=" * 50)
    
    passed = sum(results)
    total = len(results)
    
    for i, (test, result) in enumerate(zip(tests, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{i+1}. {test.__name__}: {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! ASGI configuration is ready.")
        return 0
    else:
        print("⚠️ Some tests failed. Please check the configuration.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
