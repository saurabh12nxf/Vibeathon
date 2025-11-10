#!/usr/bin/env python3
"""
Memory-optimized run.py for Render deployment (512MB limit)
"""
import os
import sys
import uvicorn
from pathlib import Path

# Memory optimization settings
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['PYTHONUNBUFFERED'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

# Add current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def create_minimal_app():
    """Create memory-optimized FastAPI app"""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    
    app = FastAPI(
        title="Arogya-AI Backend (Memory Optimized)",
        description="Healthcare AI Platform - Render Free Tier",
        version="1.0.0"
    )
    
    # CORS for frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/")
    async def root():
        return {
            "message": "Arogya-AI Backend is running",
            "status": "healthy",
            "mode": "memory_optimized",
            "platform": "render_free_tier"
        }
    
    @app.get("/health")
    async def health():
        return {"status": "healthy", "memory_optimized": True}
    
    # Basic API endpoints (without heavy ML dependencies)
    @app.get("/api/appointments")
    async def get_appointments():
        return {"appointments": [], "message": "Appointments API available"}
    
    @app.post("/api/test")
    async def test_endpoint():
        return {"status": "success", "message": "API is working"}
    
    return app

def main():
    """Main entry point with memory optimization"""
    print("🚀 Starting Memory-Optimized Arogya-AI Backend...")
    
    # Get port from Render environment
    port = int(os.getenv("PORT", 8000))
    host = "0.0.0.0"
    
    print(f"🌐 Server starting on {host}:{port}")
    print("⚡ Memory-optimized mode for Render free tier")
    
    # Check available memory
    try:
        import psutil
        memory_mb = psutil.virtual_memory().available / 1024 / 1024
        print(f"💾 Available memory: {memory_mb:.0f}MB")
    except:
        print("💾 Memory info not available")
    
    try:
        # Try to import full app (may fail due to memory)
        print("🔍 Attempting to load full application...")
        from app.main import app
        print("✅ Full FastAPI app loaded successfully")
        
        # Start with production settings for Render
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
            reload=False,         # CRITICAL: Disable reload for production
            workers=1,
            access_log=True
        )
        
    except (ImportError, MemoryError, Exception) as e:
        print(f"⚠️ Full app failed: {e}")
        print("🔧 Using minimal memory-optimized server...")
        
        # Use minimal app
        app = create_minimal_app()
        
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
            reload=False,         # CRITICAL: Disable reload for production
            workers=1,
            access_log=True
        )

if __name__ == "__main__":
    main()