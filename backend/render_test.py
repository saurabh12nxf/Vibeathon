#!/usr/bin/env python3
"""
Simple test script for Render deployment
"""
import os
import uvicorn
from fastapi import FastAPI

# Create minimal app
app = FastAPI(title="Arogya-AI Test")

@app.get("/")
def root():
    return {"message": "Arogya-AI Backend is running on Render", "status": "healthy"}

@app.get("/health")
def health():
    return {"status": "healthy", "platform": "render"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Starting test server on 0.0.0.0:{port}")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,  # CRITICAL for Render
        log_level="info"
    )