"""
Real-time Caption Generation WebSocket Endpoint

Handles audio streaming from video calls and generates live captions
with translation support.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set
import json
import logging
from .stt_pipeline import get_stt_pipeline
from .database import DatabaseClient

logger = logging.getLogger(__name__)

router = APIRouter()


class CaptionManager:
    """Manages caption WebSocket connections and audio processing"""
    
    def __init__(self):
        # Store connections per consultation room
        # Format: {consultation_id: {websocket1, websocket2}}
        self.rooms: Dict[str, Set[WebSocket]] = {}
        # Track user types per connection
        self.user_types: Dict[WebSocket, str] = {}
        # STT pipeline instance
        self.stt_pipeline = get_stt_pipeline()
        # Database client
        try:
            self.db_client = DatabaseClient()
        except Exception as e:
            logger.warning(f"Database client initialization failed: {e}")
            self.db_client = None
    
    async def connect(self, websocket: WebSocket, consultation_id: str, user_type: str):
        """Add a new caption connection"""
        await websocket.accept()
        
        if consultation_id not in self.rooms:
            self.rooms[consultation_id] = set()
        
        self.rooms[consultation_id].add(websocket)
        self.user_types[websocket] = user_type
        
        logger.info(f"✅ Caption connection: {user_type} joined room {consultation_id}")
        
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "message": "Caption service connected",
            "user_type": user_type
        })
    
    def disconnect(self, websocket: WebSocket, consultation_id: str):
        """Remove a caption connection"""
        if consultation_id in self.rooms:
            self.rooms[consultation_id].discard(websocket)
            user_type = self.user_types.pop(websocket, "unknown")
            
            logger.info(f"❌ Caption disconnection: {user_type} left room {consultation_id}")
            
            # Clean up empty rooms
            if not self.rooms[consultation_id]:
                del self.rooms[consultation_id]
    
    async def broadcast_caption(
        self,
        consultation_id: str,
        caption_data: dict,
        sender: WebSocket
    ):
        """
        Broadcast caption to all participants in the consultation room.
        
        Caption Broadcasting Logic (Task 6.2):
        
        This function ensures that captions are delivered to all participants
        in a consultation room, enabling real-time multilingual communication.
        
        Broadcasting Strategy:
        1. Validation:
           - Verify room exists
           - Check caption data has required fields (speaker, original_text, translated_text)
           - Log missing fields for debugging
        
        2. Message Construction:
           - Create standardized caption message
           - Include speaker identification (doctor/patient)
           - Include both original and translated text
           - Add optional timestamp
        
        3. Delivery:
           - Send to ALL participants (including sender)
           - Each participant receives the same caption data
           - Frontend decides which text to display based on user type
           - Track successful/failed deliveries
        
        4. Error Handling:
           - Catch send failures for individual connections
           - Mark failed connections for cleanup
           - Continue sending to other participants
           - Log detailed error information
        
        5. Cleanup:
           - Remove disconnected connections from room
           - Clean up empty rooms
           - Update user_types mapping
        
        Why Send to Sender?
        - Sender sees their own caption (confirmation)
        - Frontend shows original text for own speech
        - Provides immediate feedback that caption was generated
        - Ensures consistent experience for all participants
        
        Requirements: 3.5, 5.1, 5.2
        """
        if consultation_id not in self.rooms:
            logger.warning(f"⚠️ Cannot broadcast caption: Room {consultation_id} not found")
            return
        
        # Task 6.2: Verify caption data includes all required fields
        required_fields = ["speaker", "original_text", "translated_text"]
        missing_fields = [field for field in required_fields if field not in caption_data]
        
        if missing_fields:
            logger.error(f"❌ Caption data missing required fields: {missing_fields}")
            logger.error(f"   Caption data: {caption_data}")
            return
        
        # Task 6.2: Log broadcasting details
        room_size = len(self.rooms[consultation_id])
        logger.info(f"📢 Broadcasting caption to {room_size} participant(s) in room {consultation_id}")
        logger.debug(f"   Speaker: {caption_data['speaker']}")
        logger.debug(f"   Original: {caption_data['original_text'][:50]}...")
        logger.debug(f"   Translated: {caption_data['translated_text'][:50]}...")
        
        disconnected = []
        successful_sends = 0
        
        for connection in self.rooms[consultation_id]:
            # Task 6.2: Send to everyone (including sender for their own caption display)
            try:
                # Task 6.2: Ensure both original and translated text are included
                message = {
                    "type": "caption",
                    "speaker": caption_data["speaker"],  # Task 6.2: Speaker identification
                    "original_text": caption_data["original_text"],
                    "translated_text": caption_data["translated_text"],
                    "timestamp": caption_data.get("timestamp")  # Optional timestamp
                }
                
                await connection.send_json(message)
                successful_sends += 1
                
                # Log recipient info
                recipient_type = self.user_types.get(connection, "unknown")
                logger.debug(f"   ✅ Sent to {recipient_type} (connection {id(connection)})")
                
            except Exception as e:
                logger.error(f"❌ Error broadcasting caption to connection {id(connection)}: {e}")
                disconnected.append(connection)
        
        # Task 6.2: Log broadcast summary
        logger.info(f"✅ Caption broadcast complete: {successful_sends}/{room_size} successful")
        
        if disconnected:
            logger.warning(f"⚠️ Cleaning up {len(disconnected)} disconnected connection(s)")
        
        # Clean up disconnected connections
        for conn in disconnected:
            self.disconnect(conn, consultation_id)
    
    async def process_audio(
        self,
        audio_chunk: bytes,
        consultation_id: str,
        user_type: str,
        sender: WebSocket
    ):
        """Process audio chunk and generate caption"""
        # Task 8.2: Track chunk processing time (Requirement 7.4)
        import time
        processing_start_time = time.time()
        
        try:
            # Skip processing if chunk is too small (likely silence or empty)
            if len(audio_chunk) < 100:
                logger.debug(f"Skipping small audio chunk: {len(audio_chunk)} bytes")
                return
            
            # Task 8.2: Log chunk processing start
            logger.debug(f"⏱️ Starting audio processing for {user_type} ({len(audio_chunk)} bytes)")
            
            # Process through STT pipeline
            # Note: db_client can be None if database is not configured
            result = await self.stt_pipeline.process_audio_stream(
                audio_chunk=audio_chunk,
                user_type=user_type,
                consultation_id=consultation_id,
                db_client=self.db_client if self.db_client else None
            )
            
            # Task 8.2: Calculate and log chunk processing time
            processing_time = (time.time() - processing_start_time) * 1000  # Convert to ms
            logger.info(f"⏱️ Chunk processing time: {processing_time:.2f}ms")
            
            if result and result.get("original_text"):
                # Task 8.2: Track WebSocket message latency (time to broadcast)
                broadcast_start_time = time.time()
                
                # Task 6.2: Broadcast caption to all participants with all required fields
                caption_data = {
                    "speaker": user_type,  # Task 6.2: Speaker identification (doctor/patient)
                    "original_text": result["original_text"],  # Task 6.2: Original transcribed text
                    "translated_text": result.get("translated_text", result["original_text"]),  # Task 6.2: Translated text
                    "timestamp": None  # Will be set by frontend
                }
                
                # Task 6.2: Verify caption data is complete before broadcasting
                logger.debug(f"📋 Caption data prepared for broadcast:")
                logger.debug(f"   Speaker: {caption_data['speaker']}")
                logger.debug(f"   Original: {caption_data['original_text'][:50]}...")
                logger.debug(f"   Translated: {caption_data['translated_text'][:50]}...")
                
                await self.broadcast_caption(consultation_id, caption_data, sender)
                
                # Task 8.2: Calculate and log WebSocket broadcast latency
                broadcast_time = (time.time() - broadcast_start_time) * 1000  # Convert to ms
                logger.info(f"⏱️ WebSocket broadcast time: {broadcast_time:.2f}ms")
                
                # Task 8.2: Log total end-to-end processing time (Requirement 7.5)
                total_time = (time.time() - processing_start_time) * 1000  # Convert to ms
                logger.info(f"⏱️ Total processing time (end-to-end): {total_time:.2f}ms")
                
                logger.info(f"📝 Caption generated for {user_type}: {result['original_text'][:50]}...")
            else:
                # Don't log every silence - only log occasionally to reduce noise
                logger.debug(f"No caption generated (silence, unclear audio, or STT service unavailable)")
                
                # Task 8.2: Log processing time even for failed attempts
                processing_time = (time.time() - processing_start_time) * 1000
                logger.debug(f"⏱️ Processing time (no caption): {processing_time:.2f}ms")
                
        except Exception as e:
            # Task 8.2: Log processing time on error
            processing_time = (time.time() - processing_start_time) * 1000
            logger.error(f"Error processing audio for captions: {e} (processing time: {processing_time:.2f}ms)", exc_info=True)
            
            # Don't send error messages for every failure to avoid spamming the client
            # Only send error if it's a critical failure
            error_msg = str(e).lower()
            if "quota" in error_msg or "authentication" in error_msg or "credentials" in error_msg:
                try:
                    if sender.client_state.name == "CONNECTED":
                        await sender.send_json({
                            "type": "error",
                            "message": f"Caption service error: {str(e)}"
                        })
                except:
                    pass
            else:
                # For other errors, just log and continue silently
                logger.debug(f"Non-critical audio processing error, continuing: {e}")


# Global caption manager instance
caption_manager = CaptionManager()


@router.websocket("/ws/captions/{consultation_id}/{user_type}")
async def caption_endpoint(
    websocket: WebSocket,
    consultation_id: str,
    user_type: str
):
    """
    WebSocket endpoint for real-time caption generation
    
    Receives audio chunks and broadcasts captions to all participants
    
    Message format (from client):
    - Binary: Audio chunk (WebM/Opus format)
    - JSON: Control messages
    
    Message format (to client):
    {
        "type": "caption",
        "speaker": "doctor" | "patient",
        "original_text": "Original transcription",
        "translated_text": "Translated text",
        "timestamp": 1234567890
    }
    """
    await caption_manager.connect(websocket, consultation_id, user_type)
    
    try:
        while True:
            # Receive message (can be binary audio or JSON control)
            try:
                # Check if connection is still open before receiving
                if websocket.client_state.name != "CONNECTED":
                    logger.info(f"WebSocket not connected, state: {websocket.client_state.name}")
                    break
                
                # Try to receive as binary (audio chunk)
                data = await websocket.receive()
                
                if "bytes" in data:
                    # Audio chunk received
                    audio_chunk = data["bytes"]
                    
                    # Only process if chunk is large enough (filter out empty/silent chunks)
                    if len(audio_chunk) < 100:
                        logger.debug(f"Skipping small audio chunk: {len(audio_chunk)} bytes")
                        continue
                    
                    logger.info(f"📥 Received audio chunk: {len(audio_chunk)} bytes from {user_type}")
                    
                    # Process audio and generate caption
                    try:
                        await caption_manager.process_audio(
                            audio_chunk,
                            consultation_id,
                            user_type,
                            websocket
                        )
                    except Exception as process_error:
                        logger.error(f"Error in process_audio: {process_error}", exc_info=True)
                        # Send error message to client but don't close connection
                        try:
                            if websocket.client_state.name == "CONNECTED":
                                await websocket.send_json({
                                    "type": "error",
                                    "message": "Audio processing failed, continuing..."
                                })
                        except:
                            pass
                        # Continue processing other chunks even if one fails
                    
                elif "text" in data:
                    # JSON control message
                    message = json.loads(data["text"])
                    logger.debug(f"Received control message: {message}")
                    
                    # Handle control messages (e.g., pause, resume)
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                        logger.debug(f"Ping/pong with {user_type}")
                    else:
                        logger.debug(f"Received control message from {user_type}: {message}")
                    
            except json.JSONDecodeError:
                logger.error("Invalid JSON received")
            except Exception as receive_error:
                # Handle receive errors gracefully
                error_msg = str(receive_error).lower()
                if "disconnect" in error_msg or "disconnected" in error_msg or "closed" in error_msg:
                    logger.info(f"WebSocket disconnected during receive: {user_type}")
                    break
                else:
                    logger.error(f"Error receiving WebSocket message: {receive_error}")
                    # Continue to next iteration instead of breaking for non-critical errors
                    continue
                
    except WebSocketDisconnect:
        logger.info(f"Caption WebSocket disconnected: {user_type}")
        caption_manager.disconnect(websocket, consultation_id)
    except Exception as e:
        error_msg = str(e)
        if "disconnect" in error_msg.lower() or "receive" in error_msg.lower():
            logger.info(f"Caption WebSocket connection closed: {user_type}")
        else:
            logger.error(f"Caption WebSocket error: {e}")
        caption_manager.disconnect(websocket, consultation_id)
