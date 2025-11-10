#!/usr/bin/env python3
"""
Simple test script to verify the FastAPI server can start
"""
import os
import sys
from pathlib import Path

# Add current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def test_imports():
    """Test if all required modules can be imported"""
    print("🔍 Testing imports...")
    
    try:
        import uvicorn
        print("✅ uvicorn imported")
    except ImportError as e:
        print(f"❌ uvicorn import failed: {e}")
        return False
    
    try:
        from app.main import app
        print("✅ FastAPI app imported")
        print(f"   App type: {type(app)}")
        return True
    except ImportError as e:
        print(f"❌ FastAPI app import failed: {e}")
        print(f"   Current directory: {os.getcwd()}")
        print(f"   Python path: {sys.path[:3]}")
        return False

def test_port_binding():
    """Test if we can bind to the port"""
    import socket
    
    port = int(os.getenv("PORT", 8000))
    host = "0.0.0.0"
    
    try:
        # Test if port is available
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((host, port))
        sock.close()
        print(f"✅ Port {port} is available")
        return True
    except Exception as e:
        print(f"❌ Port {port} binding failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 Testing Render deployment setup...")
    print("=" * 50)
    
    # Test imports
    imports_ok = test_imports()
    
    # Test port binding
    port_ok = test_port_binding()
    
    print("=" * 50)
    if imports_ok and port_ok:
        print("✅ All tests passed! Server should start correctly.")
        return True
    else:
        print("❌ Some tests failed. Check the issues above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)