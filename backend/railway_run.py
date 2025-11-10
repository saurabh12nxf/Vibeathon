"""
Railway deployment entry point for FastAPI backend
"""
import os
import sys
import uvicorn
from setup_credentials import setup_google_credentials

def main():
    """Main entry point for Railway deployment"""
    print("🚀 Starting Arogya-AI Backend on Railway...")
    
    # Setup Google credentials from environment
    try:
        setup_google_credentials()
        print("✅ Google Cloud credentials configured")
    except Exception as e:
        print(f"⚠️ Warning: Google Cloud credentials setup failed: {e}")
        print("   STT and Translation features may not work")
    
    # Railway provides PORT environment variable
    port = int(os.getenv("PORT", 8000))
    host = "0.0.0.0"
    
    print(f"🌐 Server starting on {host}:{port}")
    print(f"📚 API Documentation will be available at: http://{host}:{port}/docs")
    
    # Start the FastAPI server
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,  # Disable reload in production
        log_level="info",
        access_log=True,
        workers=1  # Single worker for Railway's resource limits
    )

if __name__ == "__main__":
    main()