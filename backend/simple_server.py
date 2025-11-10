#!/usr/bin/env python3
"""
Simple fallback server for Render deployment
This is a minimal FastAPI server that should always work
"""
import os
import sys
from pathlib import Path

# Add current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

try:
    from fastapi import FastAPI
    import uvicorn
    
    # Create a simple FastAPI app
    app = FastAPI(title="Arogya-AI Backend", version="1.0.0")
    
    @app.get("/")
    async def root():
        return {"message": "Arogya-AI Backend is running", "status": "healthy"}
    
    @app.get("/health")
    async def health():
        return {"status": "healthy", "message": "Server is running"}
    
    # Try to import the main app
    try:
        from app.main import app as main_app
        print("✅ Main app imported successfully, using full application")
        app = main_app
    except Exception as e:
        print(f"⚠️ Could not import main app: {e}")
        print("🔧 Using simple fallback server")
    
    def main():
        port = int(os.getenv("PORT", 8000))
        host = "0.0.0.0"
        
        print(f"🚀 Starting server on {host}:{port}")
        
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info"
        )
    
    if __name__ == "__main__":
        main()

except Exception as e:
    print(f"❌ Critical error: {e}")
    # Last resort - basic HTTP server
    import http.server
    import socketserver
    
    port = int(os.getenv("PORT", 8000))
    
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path in ['/', '/health']:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "healthy", "message": "Basic server running"}')
            else:
                self.send_response(404)
                self.end_headers()
    
    print(f"🆘 Starting basic HTTP server on port {port}")
    with socketserver.TCPServer(("", port), Handler) as httpd:
        httpd.serve_forever()