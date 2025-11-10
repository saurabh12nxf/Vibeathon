"""
Render deployment entry point for Arogya-AI Backend
"""
import os
import sys
import uvicorn
import logging
import json
from pathlib import Path

# Add current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def setup_logging():
    """Configure logging for Render"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

def setup_credentials():
    """Setup Google Cloud credentials from Render environment"""
    try:
        credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        
        if credentials_json:
            # Validate JSON
            try:
                credentials_data = json.loads(credentials_json)
                project_id = credentials_data.get('project_id', 'unknown')
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON in GOOGLE_CREDENTIALS_JSON: {e}")
                return False
            
            # Create credentials file in Render's writable directory
            credentials_path = '/opt/render/project/src/google-credentials.json'
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(credentials_path), exist_ok=True)
            
            with open(credentials_path, 'w') as f:
                f.write(credentials_json)
            
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
            print(f"✅ Google Cloud credentials configured (Project: {project_id})")
            return True
        else:
            print("⚠️ GOOGLE_CREDENTIALS_JSON not found in environment")
            print("   STT and Translation features will not be available")
            return False
            
    except Exception as e:
        print(f"❌ Error setting up Google Cloud credentials: {e}")
        return False

def validate_environment():
    """Validate required environment variables"""
    required_vars = {
        'SUPABASE_URL': 'Database connection',
        'SUPABASE_KEY': 'Database authentication',
    }
    
    missing_vars = []
    for var, description in required_vars.items():
        if not os.getenv(var):
            missing_vars.append(f"{var} ({description})")
    
    if missing_vars:
        print("⚠️ Missing environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print("   Some features may not work correctly")
    
    # Optional variables
    optional_vars = {
        'OPENAI_API_KEY': 'Whisper API fallback',
        'FRONTEND_URL': 'CORS configuration',
    }
    
    print("📊 Environment Status:")
    for var, description in optional_vars.items():
        status = "✅" if os.getenv(var) else "❌"
        print(f"   {status} {var} ({description})")

def main():
    """Main entry point for Render deployment"""
    print("🚀 Starting Arogya-AI Backend on Render...")
    print("=" * 50)
    
    setup_logging()
    
    # Debug: Check current working directory and Python path
    print(f"📁 Current working directory: {os.getcwd()}")
    print(f"🐍 Python path: {sys.path[:3]}...")  # Show first 3 entries
    
    # Test import of FastAPI app
    try:
        print("🔍 Testing FastAPI app import...")
        from app.main import app
        print("✅ FastAPI app imported successfully")
    except Exception as e:
        print(f"❌ Error importing FastAPI app: {e}")
        print("🔧 Attempting to fix import path...")
        # Try adding backend directory to path
        backend_path = os.path.dirname(os.path.abspath(__file__))
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        try:
            from app.main import app
            print("✅ FastAPI app imported successfully after path fix")
        except Exception as e2:
            print(f"❌ Still failed to import: {e2}")
            return
    
    # Setup credentials
    google_cloud_ok = setup_credentials()
    
    # Validate environment
    validate_environment()
    
    # Render configuration
    port = int(os.getenv("PORT", 8000))
    host = "0.0.0.0"
    
    print("=" * 50)
    print(f"🌐 Server starting on {host}:{port}")
    print(f"📚 API Documentation: https://your-app.onrender.com/docs")
    print(f"🔍 Health Check: https://your-app.onrender.com/health")
    print("=" * 50)
    
    try:
        # Start the FastAPI server
        print("🚀 Starting uvicorn server...")
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=False,
            log_level="info",
            access_log=True,
            workers=1,  # Single worker for Render free tier
            timeout_keep_alive=30,
            timeout_graceful_shutdown=10
        )
    except Exception as e:
        print(f"❌ Error starting server: {e}")
        # Try alternative approach
        print("🔧 Trying alternative server start...")
        try:
            uvicorn.run(
                app,
                host=host,
                port=port,
                log_level="info"
            )
        except Exception as e2:
            print(f"❌ Alternative approach also failed: {e2}")
            raise

if __name__ == "__main__":
    main()