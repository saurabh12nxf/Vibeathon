#!/usr/bin/env python3
"""
Memory-optimized Render deployment entry point for Arogya-AI Backend
Designed to work within Render's 512MB free tier limit
"""
import os
import sys
import uvicorn
import logging
from pathlib import Path

# Add current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def setup_logging():
    """Configure minimal logging for Render"""
    logging.basicConfig(
        level=logging.WARNING,  # Reduce log verbosity to save memory
        format='%(levelname)s - %(message)s'
    )

def setup_minimal_environment():
    """Setup minimal environment to reduce memory usage"""
    # Disable heavy ML libraries to save memory
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    
    # Disable sentence transformers model loading
    os.environ['DISABLE_SENTENCE_TRANSFORMERS'] = '1'
    
    # Set minimal Python settings
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PYTHONUNBUFFERED'] = '1'

def create_minimal_app():
    """Create a minimal FastAPI app for Render free tier"""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    
    app = FastAPI(
        title="Arogya-AI Backend (Render Optimized)",
        description="Healthcare AI Platform API - Memory Optimized",
        version="1.0.0"
    )
    
    # Basic CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all for demo
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/")
    async def root():
        return {
            "status": "healthy",
            "service": "Arogya-AI Backend (Render Optimized)",
            "version": "1.0.0",
            "message": "Backend is running on Render free tier"
        }
    
    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "memory_optimized": True,
            "platform": "render"
        }
    
    # Basic appointments endpoint (without heavy dependencies)
    @app.get("/api/appointments")
    async def get_appointments():
        return {
            "appointments": [],
            "message": "Appointments endpoint available"
        }
    
    # Basic captions endpoint (without ML processing)
    @app.post("/api/captions/test")
    async def test_captions():
        return {
            "status": "success",
            "message": "Captions endpoint available (ML features disabled for memory optimization)"
        }
    
    return app

def main():
    """Main entry point for memory-optimized Render deployment"""
    print("🚀 Starting Memory-Optimized Arogya-AI Backend on Render...")
    
    setup_logging()
    setup_minimal_environment()
    
    # Get port from environment
    port = int(os.getenv("PORT", 8000))
    host = "0.0.0.0"
    
    print(f"🌐 Server starting on {host}:{port}")
    print("⚡ Memory-optimized mode: Heavy ML features disabled")
    
    try:
        # Try to import full app first
        print("🔍 Attempting to load full application...")
        from app.main import app
        print("✅ Full application loaded successfully")
    except Exception as e:
        print(f"⚠️ Full app failed to load: {e}")
        print("🔧 Using minimal optimized app...")
        app = create_minimal_app()
    
    try:
        print(f"🚀 Starting uvicorn server on port {port}...")
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="warning",  # Reduce logging
            access_log=False,     # Disable access logs to save memory
            workers=1,
            loop="asyncio",       # Use asyncio loop (lighter than uvloop)
            timeout_keep_alive=30
        )
    except Exception as e:
        print(f"❌ Server failed to start: {e}")
        raise

if __name__ == "__main__":
    main()