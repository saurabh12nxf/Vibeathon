#!/usr/bin/env python3
"""
Ultra-minimal server for Render free tier
Guaranteed to work within 512MB limit
"""
import os
import uvicorn
from fastapi import FastAPI

# Create the most minimal FastAPI app possible
app = FastAPI(title="Arogya-AI")

@app.get("/")
def root():
    return {"message": "Arogya-AI Backend", "status": "healthy"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/api/test")
def test():
    return {"status": "working"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Ultra-minimal server starting on 0.0.0.0:{port}")
    
    # Absolutely minimal uvicorn configuration
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )