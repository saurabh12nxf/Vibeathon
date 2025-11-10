"""
FastAPI server for Arogya-AI Alert Engine and Emotion Analyzer

This provides REST API and WebSocket endpoints for real-time emotion analysis
and medical alert detection.
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime
import json

from .alert_engine import AlertEngine, Alert
from .emotion_analyzer import EmotionAnalyzer, EmotionResult
from .database import DatabaseClient
from .stt_pipeline import get_stt_pipeline, validate_stt_configuration
from .audio_converter_ffmpeg import get_audio_converter
from .appointments import router as appointments_router
from .lab_reports import router as lab_reports_router
from .medical_images import router as medical_images_router
from .signaling import router as signaling_router
from .voice_intake import router as voice_intake_router
from .health_tips import router as health_tips_router
from .captions import router as captions_router
from .summarizer import generate_notes_with_empathy
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Arogya-AI Medical Intelligence API")

# Startup event to validate configuration
@app.on_event("startup")
async def startup_validation():
    """Validate STT pipeline configuration at startup."""
    logger.info("=" * 80)
    logger.info("🚀 Starting Arogya-AI Medical Intelligence API")
    logger.info("=" * 80)
    
    # Validate STT configuration
    logger.info("🔍 Validating STT Pipeline Configuration...")
    validation_result = validate_stt_configuration()
    
    logger.info("\n📊 Configuration Status:")
    logger.info(f"   Google Cloud Libraries: {'✅ Available' if validation_result['google_cloud_available'] else '❌ Not Available'}")
    logger.info(f"   Google Cloud Credentials: {'✅ Valid' if validation_result['google_credentials_valid'] else '❌ Invalid'}")
    logger.info(f"   Google Speech-to-Text: {'✅ Ready' if validation_result['google_speech_client'] else '❌ Not Available'}")
    logger.info(f"   Google Translation: {'✅ Ready' if validation_result['google_translate_client'] else '❌ Not Available'}")
    logger.info(f"   OpenAI Whisper (Fallback): {'✅ Ready' if validation_result['openai_client'] else '❌ Not Available'}")
    
    # Log warnings
    if validation_result['warnings']:
        logger.info("\n⚠️  Warnings:")
        for warning in validation_result['warnings']:
            logger.warning(f"   - {warning}")
    
    # Log errors
    if validation_result['errors']:
        logger.info("\n❌ Errors:")
        for error in validation_result['errors']:
            logger.error(f"   - {error}")
        logger.error("\n⚠️  Live captions may not work properly without a valid ASR service!")
    else:
        logger.info("\n✅ All critical services initialized successfully")
    
    logger.info("=" * 80)

# Include appointment routes
app.include_router(appointments_router)

# Include lab reports routes
app.include_router(lab_reports_router)
# Include medical images routes
app.include_router(medical_images_router)
# Include signaling routes for WebRTC
app.include_router(signaling_router)
# Include voice intake routes
app.include_router(voice_intake_router)
# Include health tips routes
app.include_router(health_tips_router)
# Include captions routes for live transcription
app.include_router(captions_router)

# Production CORS configuration
import os

# Base allowed origins for development
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:3001", 
    "http://localhost:3002",
    "https://localhost:3000",
]

# Add production frontend URLs from environment
frontend_url = os.getenv("FRONTEND_URL")
if frontend_url:
    allowed_origins.append(frontend_url)

# Add common production domains (update these with your actual domains)
production_domains = [
    "https://arogya-ai.vercel.app",
    "https://your-app.vercel.app",
    "https://your-app.netlify.app",
]

# Only add production domains in production environment
if os.getenv("RAILWAY_ENVIRONMENT") == "production" or os.getenv("RENDER") or os.getenv("NODE_ENV") == "production":
    allowed_origins.extend(production_domains)
    logger.info(f"🌐 Production CORS enabled for: {production_domains}")

logger.info(f"🔒 CORS allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Initialize services
alert_engine = AlertEngine()
emotion_analyzer = EmotionAnalyzer()
db_client = DatabaseClient()
stt_pipeline = get_stt_pipeline()
audio_converter = get_audio_converter()

# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for real-time communication"""
    
    def _init_(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
    
    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
    
    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)

manager = ConnectionManager()


class TranscriptRequest(BaseModel):
    """Request model for transcript analysis"""
    text: str
    consultation_id: str
    speaker_type: str  # "patient" or "doctor"


class AlertResponse(BaseModel):
    """Response model for alert detection"""
    alert_detected: bool
    alert: Optional[dict] = None
    message: str


class EmotionAnalysisRequest(BaseModel):
    """Request model for emotion analysis simulation"""
    emotion_type: str
    confidence_score: float
    user_id: str
    consultation_id: Optional[str] = None


class EmotionStatsResponse(BaseModel):
    """Response model for emotion statistics"""
    total_detections: int
    distribution: Dict[str, float]
    last_emotion: Optional[dict]
    stats: List[dict]


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Arogya-AI Medical Intelligence API",
        "version": "2.0.0",
        "features": ["alert_engine", "emotion_analyzer"]
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "alert_engine": "operational",
            "emotion_analyzer": "operational",
            "database": "operational"
        }
    }


# ============================================================================
# EMOTION ANALYZER ENDPOINTS
# ============================================================================

@app.post("/api/emotions/log")
async def log_emotion(request: EmotionAnalysisRequest):
    """
    Log an emotion detection (for testing/simulation).
    
    Args:
        request: EmotionAnalysisRequest with emotion data
    
    Returns:
        Success response with logged emotion
    """
    try:
        result = await db_client.log_emotion(
            user_id=request.user_id,
            emotion_type=request.emotion_type,
            confidence_score=request.confidence_score,
            consultation_id=request.consultation_id
        )
        
        return {
            "success": True,
            "message": "Emotion logged successfully",
            "data": result
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/emotions/stats/{user_id}")
async def get_emotion_stats(user_id: str):
    """
    Get emotion statistics for a user.
    
    Args:
        user_id: ID of the user
    
    Returns:
        Emotion statistics and summary
    """
    try:
        summary = await db_client.get_emotion_summary(user_id)
        return summary
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/emotions/recent/{user_id}")
async def get_recent_emotions(user_id: str, limit: int = 50):
    """
    Get recent emotion detections for a user.
    
    Args:
        user_id: ID of the user
        limit: Maximum number of records to return
    
    Returns:
        List of recent emotion logs
    """
    try:
        emotions = await db_client.get_recent_emotions(user_id, limit)
        return {
            "success": True,
            "count": len(emotions),
            "emotions": emotions
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/emotions/consultation/{consultation_id}")
async def get_consultation_emotions(consultation_id: str):
    """
    Get all emotions for a specific consultation.
    
    Args:
        consultation_id: ID of the consultation
    
    Returns:
        List of emotion logs for the consultation
    """
    try:
        emotions = await db_client.get_consultation_emotions(consultation_id)
        return {
            "success": True,
            "count": len(emotions),
            "emotions": emotions
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/emotions/{user_id}")
async def delete_user_emotions(user_id: str):
    """
    Delete all emotion logs for a user (GDPR compliance).
    
    Args:
        user_id: ID of the user
    
    Returns:
        Success response
    """
    try:
        success = await db_client.delete_user_emotions(user_id)
        
        if success:
            return {
                "success": True,
                "message": "All emotion data deleted successfully"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to delete emotion data")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/{consultation_id}/{user_type}")
async def video_call_websocket(websocket: WebSocket, consultation_id: str, user_type: str):
    """
    WebSocket endpoint for video call room with real-time translation.
    
    Handles audio streaming and returns translated captions.
    
    Args:
        websocket: WebSocket connection
        consultation_id: ID of the consultation
        user_type: Type of user (doctor or patient)
    """
    connection_id = f"{consultation_id}_{user_type}"
    await websocket.accept()
    print(f"Video call WebSocket connected: {connection_id}")
    
    try:
        while True:
            # Wait for any message from client
            message = await websocket.receive()
            
            # Check if client disconnected
            if message["type"] == "websocket.disconnect":
                break
            
            # Handle binary data (audio)
            if message["type"] == "websocket.receive" and "bytes" in message:
                audio_data = message["bytes"]
                print(f"✅ Received {len(audio_data)} bytes of audio data from {user_type}")
                
                # Validate audio data
                if not audio_converter.is_valid_audio(audio_data):
                    print("⚠️  Audio data too small, skipping...")
                    continue
                
                print(f"✅ Audio validation passed")
                print(f"✅ Sending {len(audio_data)} bytes directly to Google Cloud (OGG Opus)")
                
                # Process audio through STT pipeline (no conversion needed for OGG Opus)
                try:
                    print(f"🔄 Processing through STT pipeline...")
                    result = await stt_pipeline.process_audio_stream(
                        audio_chunk=audio_data,
                        user_type=user_type,
                        consultation_id=consultation_id,
                        db_client=db_client
                    )
                    
                    print(f"✅ STT result: {result}")
                    
                    # Send translation result back to client
                    if result and result.get("original_text"):
                        caption_message = {
                            "speaker_id": result["speaker_id"],
                            "original_text": result["original_text"],
                            "translated_text": result["translated_text"],
                            "timestamp": datetime.now().timestamp()
                        }
                        
                        await websocket.send_json(caption_message)
                        print(f"✅ Sent caption: {result['original_text'][:50]}...")
                    else:
                        print(f"⚠️  No text transcribed (silence or unclear audio)")
                    
                except Exception as e:
                    print(f"❌ Error processing audio: {e}")
                    import traceback
                    traceback.print_exc()
                    # Continue listening even if processing fails
            
            # Handle text/JSON data
            elif message["type"] == "websocket.receive" and "text" in message:
                try:
                    data = json.loads(message["text"])
                    print(f"Received message from {user_type}: {data}")
                except json.JSONDecodeError:
                    print(f"Received text from {user_type}: {message['text']}")
    
    except WebSocketDisconnect:
        print(f"Video call WebSocket disconnected: {connection_id}")
    except Exception as e:
        print(f"Video call WebSocket error: {e}")
    finally:
        # Clean up connection
        try:
            await websocket.close()
        except:
            pass


@app.websocket("/ws/emotions/{user_id}")
async def emotion_websocket(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for real-time emotion updates.
    
    Clients connect and receive emotion updates in real-time.
    Can also send simulated emotions for testing.
    
    Args:
        websocket: WebSocket connection
        user_id: ID of the user
    """
    await manager.connect(user_id, websocket)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            message_type = data.get("type")
            
            if message_type == "emotion_update":
                # Log emotion to database
                emotion_data = data.get("data", {})
                
                await db_client.log_emotion(
                    user_id=user_id,
                    emotion_type=emotion_data.get("emotion_type"),
                    confidence_score=emotion_data.get("confidence_score"),
                    consultation_id=emotion_data.get("consultation_id")
                )
                
                # Broadcast back to client
                await manager.send_personal_message({
                    "type": "emotion_logged",
                    "data": emotion_data
                }, user_id)
            
            elif message_type == "get_stats":
                # Send current stats
                stats = await db_client.get_emotion_summary(user_id)
                await manager.send_personal_message({
                    "type": "stats_update",
                    "data": stats
                }, user_id)
    
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(user_id)


# ============================================================================
# ALERT ENGINE ENDPOINTS
# ============================================================================

@app.post("/analyze", response_model=AlertResponse)
async def analyze_transcript(request: TranscriptRequest):
    """
    Analyze transcript text for critical medical symptoms.
    
    Args:
        request: TranscriptRequest with text, consultation_id, and speaker_type
    
    Returns:
        AlertResponse with alert detection results
    """
    try:
        # Analyze the transcript
        alert = await alert_engine.analyze_transcript(
            text=request.text,
            consultation_id=request.consultation_id,
            speaker_type=request.speaker_type
        )
        
        if alert:
            return AlertResponse(
                alert_detected=True,
                alert=alert.to_dict(),
                message=f"Critical symptom detected: {alert.symptom_type}"
            )
        else:
            return AlertResponse(
                alert_detected=False,
                alert=None,
                message="No critical symptoms detected"
            )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/clear-cache/{consultation_id}")
async def clear_consultation_cache(consultation_id: str):
    """
    Clear alert cache for a specific consultation.
    
    Args:
        consultation_id: ID of the consultation to clear
    
    Returns:
        Success message
    """
    try:
        alert_engine.clear_consultation_cache(consultation_id)
        return {
            "success": True,
            "message": f"Cache cleared for consultation {consultation_id}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/patterns")
async def get_patterns():
    """
    Get all critical symptom patterns.
    
    Returns:
        Dictionary of all symptom patterns
    """
    return {
        "patterns": alert_engine.critical_patterns
    }


# ============================================================================
# SOAP NOTES GENERATION ENDPOINTS
# ============================================================================

@app.post("/api/consultations/{consultation_id}/generate_soap")
async def generate_soap_notes(consultation_id: str):
    """
    Generate SOAP notes for a consultation.
    
    Fetches the consultation transcript, generates SOAP notes using AI,
    analyzes for stigmatizing language, and saves the results to the database.
    
    Args:
        consultation_id: ID of the consultation
    
    Returns:
        Dictionary with generated SOAP notes and de-stigmatization suggestions
    
    Raises:
        HTTPException: If consultation not found or generation fails
    """
    try:
        # 1. Fetch the consultation transcript
        logger.info(f"Fetching transcript for consultation {consultation_id}")
        transcript = await db_client.get_transcript(consultation_id)
        
        if not transcript:
            logger.error(f"Consultation {consultation_id} not found or has no transcript")
            raise HTTPException(
                status_code=404,
                detail="Consultation not found"
            )
        
        # 2. Generate SOAP notes with Compassion Reflex
        logger.info(f"Generating SOAP notes for consultation {consultation_id}")
        soap_note, stigma_suggestions = await generate_notes_with_empathy(transcript)
        
        # 3. Save to database
        logger.info(f"Saving SOAP notes to database for consultation {consultation_id}")
        try:
            db_client.client.table("consultations")\
                .update({
                    "raw_soap_note": soap_note,
                    "de_stigma_suggestions": stigma_suggestions,
                    "soap_notes": soap_note,  # Also update old column for compatibility
                    "stigma_suggestions": stigma_suggestions  # Also update old column
                })\
                .eq("id", consultation_id)\
                .execute()
            
            logger.info(f"SOAP notes saved successfully for consultation {consultation_id}")
        except Exception as db_error:
            logger.error(f"Error saving SOAP notes to database: {db_error}")
            # Continue anyway - we can still return the generated notes
        
        # 4. Return the generated notes
        return {
            "success": True,
            "consultation_id": consultation_id,
            "soap_note": soap_note,
            "stigma_suggestions": stigma_suggestions,
            "message": "SOAP notes generated successfully"
        }
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except ValueError as ve:
        logger.error(f"Validation error generating SOAP notes: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error generating SOAP notes: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate SOAP notes: {str(e)}"
        )


@app.get("/api/consultations/{consultation_id}/soap")
async def get_soap_notes(consultation_id: str):
    """
    Get existing SOAP notes for a consultation.
    
    Args:
        consultation_id: ID of the consultation
    
    Returns:
        Dictionary with SOAP notes and suggestions
    
    Raises:
        HTTPException: If consultation not found or no SOAP notes exist
    """
    try:
        result = db_client.client.table("consultations")\
            .select("raw_soap_note, de_stigma_suggestions, soap_notes, stigma_suggestions")\
            .eq("id", consultation_id)\
            .single()\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Consultation not found")
        
        # Try new column names first, fall back to old ones
        soap_note = result.data.get("raw_soap_note") or result.data.get("soap_notes")
        stigma_suggestions = result.data.get("de_stigma_suggestions") or result.data.get("stigma_suggestions") or []
        
        if not soap_note:
            raise HTTPException(status_code=404, detail="No SOAP notes found for this consultation")
        
        return {
            "success": True,
            "consultation_id": consultation_id,
            "soap_note": soap_note,
            "stigma_suggestions": stigma_suggestions
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching SOAP notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)