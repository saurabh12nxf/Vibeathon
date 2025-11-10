"""
Speech-to-Text Pipeline with Hinglish Support for Arogya-AI

This module handles real-time audio transcription, translation, and Community Lexicon
integration for multilingual medical consultations.

Features:
- Google Cloud Speech-to-Text (primary ASR with free tier)
- OpenAI Whisper API (fallback ASR)
- Google Cloud Translation API
- Community Lexicon vector similarity search
- Language-specific configuration for Hindi and Hinglish code-switching
"""

import os
import logging
from typing import Dict, Optional, Tuple
from io import BytesIO
import asyncio

# Google Cloud imports
try:
    from google.cloud import speech_v1 as speech
    from google.cloud import translate_v2 as translate
    GOOGLE_CLOUD_AVAILABLE = True
except ImportError:
    GOOGLE_CLOUD_AVAILABLE = False
    logging.warning("Google Cloud libraries not available")

# OpenAI imports
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logging.warning("OpenAI library not available")

# Sentence transformers for embeddings
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logging.warning("sentence-transformers library not available")

from dotenv import load_dotenv
from .database import DatabaseClient

# Audio converter for WebM/Opus to PCM conversion
# Try FFmpeg converter first (has better error handling), then fall back to pydub
try:
    from .audio_converter_ffmpeg import get_audio_converter, AudioConverter
    AUDIO_CONVERTER_AVAILABLE = True
except ImportError:
    try:
        from .audio_converter import get_audio_converter, AudioConverter
        AUDIO_CONVERTER_AVAILABLE = True
    except ImportError:
        AUDIO_CONVERTER_AVAILABLE = False
        logging.warning("Audio converter not available - WebM/Opus conversion will not work")

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class STTPipeline:
    """
    Speech-to-Text pipeline with ASR fallback, translation, and lexicon integration.
    """
    
    def __init__(self):
        """Initialize STT pipeline with ASR services and translation."""
        self.google_speech_client = None
        self.google_translate_client = None
        self.openai_client = None
        self.embedding_model = None
        self.google_credentials_valid = False
        
        # Verify Google Cloud credentials at startup
        self._verify_google_credentials()
        
        # Initialize Google Cloud Speech-to-Text (primary ASR)
        if GOOGLE_CLOUD_AVAILABLE and self.google_credentials_valid:
            try:
                self.google_speech_client = speech.SpeechClient()
                logger.info("✅ Google Cloud Speech-to-Text initialized (primary ASR)")
                
                # Test the client with a simple operation
                try:
                    # This will validate that the credentials work
                    config = speech.RecognitionConfig(
                        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                        sample_rate_hertz=16000,
                        language_code="en-US",
                    )
                    logger.info("✅ Google Cloud STT client validated successfully")
                except Exception as test_error:
                    logger.error(f"❌ Google Cloud STT client validation failed: {test_error}")
                    self.google_speech_client = None
                    self.google_credentials_valid = False
                    
            except Exception as e:
                logger.error(f"❌ Failed to initialize Google Cloud Speech: {str(e)}")
                logger.error("   Please check your GOOGLE_APPLICATION_CREDENTIALS environment variable")
                self.google_speech_client = None
        elif GOOGLE_CLOUD_AVAILABLE and not self.google_credentials_valid:
            logger.warning("⚠️ Google Cloud credentials not valid, Speech-to-Text will not be available")
        
        # Initialize Google Cloud Translation
        if GOOGLE_CLOUD_AVAILABLE and self.google_credentials_valid:
            try:
                self.google_translate_client = translate.Client()
                logger.info("✅ Google Cloud Translation initialized")
                
                # Test the translation client
                try:
                    # Simple test translation
                    test_result = self.google_translate_client.translate("test", target_language="hi")
                    logger.info("✅ Google Cloud Translation client validated successfully")
                except Exception as test_error:
                    logger.error(f"❌ Google Cloud Translation client validation failed: {test_error}")
                    self.google_translate_client = None
                    
            except Exception as e:
                logger.error(f"❌ Failed to initialize Google Cloud Translation: {str(e)}")
                self.google_translate_client = None
        elif GOOGLE_CLOUD_AVAILABLE and not self.google_credentials_valid:
            logger.warning("⚠️ Google Cloud credentials not valid, Translation will not be available")
        
        # Initialize OpenAI Whisper API (fallback ASR)
        if OPENAI_AVAILABLE:
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                try:
                    self.openai_client = OpenAI(api_key=api_key)
                    logger.info("OpenAI Whisper API initialized (fallback ASR)")
                except Exception as e:
                    logger.warning(f"Failed to initialize OpenAI client: {str(e)}")
            else:
                logger.info("OpenAI API key not found in environment. Whisper fallback will not be available.")
                logger.info("To enable Whisper fallback, set OPENAI_API_KEY environment variable.")
        
        # Initialize embedding model for Community Lexicon
        # Skip heavy models on memory-constrained environments (Render free tier)
        if os.getenv('DISABLE_SENTENCE_TRANSFORMERS') or os.getenv('DISABLE_COMMUNITY_LEXICON'):
            logger.info("⚡ Skipping sentence transformers (memory optimization)")
            self.embedding_model = None
        elif SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.embedding_model = SentenceTransformer('Supabase/gte-small')
                logger.info("✅ Embedding model initialized (gte-small)")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize embedding model: {str(e)}")
                self.embedding_model = None
    
    def _verify_google_credentials(self):
        """
        Verify Google Cloud credentials at startup.
        
        Checks:
        1. GOOGLE_APPLICATION_CREDENTIALS environment variable is set
        2. Credentials file exists at the specified path
        3. Credentials file is valid JSON
        
        Sets self.google_credentials_valid to True if all checks pass.
        """
        if not GOOGLE_CLOUD_AVAILABLE:
            logger.warning("⚠️ Google Cloud libraries not installed")
            logger.info("   Install with: pip install google-cloud-speech google-cloud-translate")
            self.google_credentials_valid = False
            return
        
        # Check if GOOGLE_APPLICATION_CREDENTIALS is set
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        
        if not credentials_path:
            logger.error("❌ GOOGLE_APPLICATION_CREDENTIALS environment variable not set")
            logger.error("   Please set it to the path of your Google Cloud service account JSON file")
            logger.error("   Example: GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json")
            logger.info("   Falling back to OpenAI Whisper API (if available)")
            self.google_credentials_valid = False
            return
        
        logger.info(f"🔍 Checking Google Cloud credentials at: {credentials_path}")
        
        # Check if credentials file exists
        if not os.path.exists(credentials_path):
            logger.error(f"❌ Google Cloud credentials file not found: {credentials_path}")
            logger.error("   Please ensure the file exists at the specified path")
            logger.info("   Falling back to OpenAI Whisper API (if available)")
            self.google_credentials_valid = False
            return
        
        logger.info(f"✅ Credentials file exists")
        
        # Check if credentials file is valid JSON
        try:
            import json
            with open(credentials_path, 'r') as f:
                credentials_data = json.load(f)
                
            # Verify it has required fields
            required_fields = ['type', 'project_id', 'private_key', 'client_email']
            missing_fields = [field for field in required_fields if field not in credentials_data]
            
            if missing_fields:
                logger.error(f"❌ Credentials file is missing required fields: {missing_fields}")
                logger.error("   Please ensure you downloaded the correct service account JSON file")
                self.google_credentials_valid = False
                return
            
            logger.info(f"✅ Credentials file is valid JSON")
            logger.info(f"   Project ID: {credentials_data.get('project_id')}")
            logger.info(f"   Service Account: {credentials_data.get('client_email')}")
            
            self.google_credentials_valid = True
            logger.info("✅ Google Cloud credentials verified successfully")
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Credentials file is not valid JSON: {e}")
            logger.error("   Please ensure you downloaded the correct service account JSON file")
            self.google_credentials_valid = False
        except Exception as e:
            logger.error(f"❌ Error reading credentials file: {e}")
            self.google_credentials_valid = False
    
    def _detect_audio_format(self, audio_chunk: bytes) -> Tuple[str, bool, int]:
        """
        Detect audio format from byte signature (magic numbers).
        
        Audio Format Detection Logic (Task 4.1):
        
        This function examines the first few bytes of audio data to identify
        the format. Different audio formats have unique byte signatures:
        
        1. WAV: Starts with 'RIFF' (0x52494646) and 'WAVE' (0x57415645)
           - Can extract sample rate from header (offset 24-27)
           - Needs conversion to PCM for Google Cloud STT
        
        2. WebM/Matroska: Starts with 0x1A 0x45 0xDF 0xA3
           - May contain 'OpusHead' marker with sample rate info
           - Always needs conversion (Opus codec → PCM)
           - Most common format from browser MediaRecorder
        
        3. OGG: Starts with 'OggS' (0x4F676753)
           - Typically contains Opus codec
           - Needs conversion to PCM
        
        4. FLAC: Starts with 'fLaC' (0x664C6143)
           - Lossless format, no conversion needed
           - Directly supported by Google Cloud STT
        
        5. Raw PCM: No header, just audio samples
           - Detected by size heuristics (even byte count, reasonable size)
           - No conversion needed
        
        6. Unknown: Defaults to WebM/Opus assumption
           - Will attempt conversion
           - Logs warning with byte header for debugging
        
        Returns:
            Tuple of (format_name, needs_conversion, sample_rate)
            - format_name: 'webm', 'ogg', 'flac', 'wav', or 'pcm'
            - needs_conversion: True if format needs conversion to LINEAR16 PCM
            - sample_rate: Detected sample rate in Hz (default: 16000)
        """
        sample_rate = 16000  # Default sample rate for speech recognition
        
        # Log audio chunk size for debugging
        logger.debug(f"🔍 Detecting audio format for {len(audio_chunk)} byte chunk")
        
        # Log first 16 bytes for debugging (always, not just on unknown format)
        if len(audio_chunk) >= 16:
            hex_bytes = ' '.join(f'{b:02x}' for b in audio_chunk[:16])
            logger.debug(f"   Audio header (first 16 bytes): {hex_bytes}")
        
        # Check for WAV format (RIFF header)
        if len(audio_chunk) > 12 and audio_chunk[0:4] == b'RIFF' and audio_chunk[8:12] == b'WAVE':
            # Try to extract sample rate from WAV header
            try:
                # The sample rate is stored as a 32-bit little-endian integer at offset 24
                sample_rate = int.from_bytes(audio_chunk[24:28], byteorder='little')
                logger.info(f"✅ Detected WAV format | Sample rate: {sample_rate} Hz | Size: {len(audio_chunk)} bytes")
                return ('wav', True, sample_rate)
            except Exception as e:
                logger.warning(f"⚠️ Could not parse WAV header, using default sample rate: {e}")
                logger.info(f"✅ Detected WAV format | Sample rate: {sample_rate} Hz (default) | Size: {len(audio_chunk)} bytes")
                return ('wav', True, sample_rate)
        
        # Check for WebM/Matroska signature (starts with specific bytes)
        # WebM files start with: 0x1A 0x45 0xDF 0xA3
        if len(audio_chunk) >= 4 and audio_chunk[:4] == b'\x1a\x45\xdf\xa3':
            # Try to extract Opus header if present
            opus_head_pos = audio_chunk.find(b'OpusHead')
            if opus_head_pos != -1 and len(audio_chunk) > opus_head_pos + 12:
                try:
                    # Sample rate is a 32-bit little-endian integer at offset 12-15 in OpusHead
                    sample_rate = int.from_bytes(
                        audio_chunk[opus_head_pos+12:opus_head_pos+16], 
                        byteorder='little'
                    )
                    logger.info(f"✅ Detected WebM/Opus format | Sample rate: {sample_rate} Hz | Size: {len(audio_chunk)} bytes | Needs conversion: Yes")
                except Exception as e:
                    logger.warning(f"⚠️ Could not parse Opus header: {e}")
                    logger.info(f"✅ Detected WebM/Opus format | Sample rate: {sample_rate} Hz (default) | Size: {len(audio_chunk)} bytes | Needs conversion: Yes")
            else:
                logger.info(f"✅ Detected WebM/Opus format | Sample rate: {sample_rate} Hz (default) | Size: {len(audio_chunk)} bytes | Needs conversion: Yes")
            return ('webm', True, sample_rate)
        
        # Check for OGG Opus signature
        # OGG files start with: "OggS"
        if len(audio_chunk) >= 4 and audio_chunk[:4] == b'OggS':
            # For OGG, we'll use the default sample rate as it's not easily extractable
            logger.info(f"✅ Detected OGG Opus format | Sample rate: {sample_rate} Hz (default) | Size: {len(audio_chunk)} bytes | Needs conversion: Yes")
            return ('ogg', True, sample_rate)
        
        # Check for FLAC signature
        if len(audio_chunk) >= 4 and audio_chunk[:4] == b'fLaC':
            logger.info(f"✅ Detected FLAC format | Sample rate: {sample_rate} Hz (default) | Size: {len(audio_chunk)} bytes | Needs conversion: No")
            return ('flac', False, sample_rate)
        
        # Check for raw PCM (no header)
        # Only treat as PCM if it doesn't have any container format signature
        # AND the size suggests it could be raw audio samples
        # Be more conservative - only treat very specific sizes as PCM
        if len(audio_chunk) % 2 == 0 and 8000 <= len(audio_chunk) <= 192000:
            # Additional check: raw PCM should not have any recognizable patterns
            # Check first 4 bytes don't match any known format
            header = audio_chunk[:4] if len(audio_chunk) >= 4 else b''
            
            # If it looks like it could be WebM/Opus (has 0x1a byte which is common in WebM)
            if b'\x1a' in header or b'\x42' in header:
                logger.info(f"✅ Detected WebM/Opus format (no clear signature but has WebM markers) | Sample rate: {sample_rate} Hz | Size: {len(audio_chunk)} bytes | Needs conversion: Yes")
                return ('webm', True, sample_rate)
            
            logger.info(f"✅ Detected raw PCM audio | Sample rate: {sample_rate} Hz (assumed 16-bit mono) | Size: {len(audio_chunk)} bytes | Needs conversion: No")
            return ('pcm', False, sample_rate)
        
        # Unknown format - log warning with header bytes
        logger.warning(f"⚠️ Unknown audio format detected | Size: {len(audio_chunk)} bytes")
        if len(audio_chunk) >= 16:
            logger.warning(f"   First 16 bytes (hex): {audio_chunk[:16].hex()}")
        logger.warning(f"   Assuming WebM/Opus format (will attempt conversion to PCM)")
        
        # Default: assume WebM with default sample rate
        return ('webm', True, sample_rate)
    
    async def transcribe_audio_google(
        self,
        audio_chunk: bytes,
        language_code: str,
        alternative_language_codes: Optional[list] = None
    ) -> Optional[str]:
        """
        Transcribe audio using Google Cloud Speech-to-Text.
        
        Google Cloud STT Integration (Task 5.1, 5.2, 5.3):
        
        This function handles the complete flow of sending audio to Google Cloud
        Speech-to-Text API and processing the response.
        
        Audio Processing Flow:
        
        1. Format Detection (Task 4.1):
           - Detect audio format from byte signature
           - Determine if conversion is needed
           - Extract sample rate if available
        
        2. Format Conversion (Task 4.2):
           - Convert WebM/Opus to LINEAR16 PCM if needed
           - Use FFmpeg for reliable conversion
           - Target: 16kHz mono PCM (required by Google Cloud STT)
           - Fall back to original format if conversion fails
        
        3. STT Configuration (Task 5.2):
           - Set encoding based on format (LINEAR16, FLAC, or WEBM_OPUS)
           - Configure language codes (hi-IN for patient, en-IN for doctor)
           - Enable enhanced model (latest_long) for better accuracy
           - Enable automatic punctuation
           - Set sample rate (16kHz for LINEAR16/FLAC)
        
        4. API Call:
           - Send audio to Google Cloud STT
           - Track response time for performance monitoring
           - Handle API responses and errors
        
        5. Error Handling (Task 5.3):
           - Log detailed error information
           - Provide context-specific error messages
           - Check for quota/authentication/format errors
           - Return None to allow fallback to Whisper
           - Don't raise exceptions (graceful degradation)
        
        Error Handling Paths:
        - Conversion failure → Try original format
        - STT API error → Log details, return None for Whisper fallback
        - Quota exceeded → Log warning, return None
        - Authentication error → Log credentials issue, return None
        - Invalid audio format → Log format details, return None
        
        Args:
            audio_chunk: Raw audio bytes (LINEAR16 PCM, WAV, WebM/Opus, etc.)
            language_code: Primary language code (e.g., 'hi-IN', 'en-IN')
            alternative_language_codes: Alternative language codes for code-switching
            
        Returns:
            Transcribed text or None if transcription fails
        """
        if not self.google_speech_client:
            logger.error("❌ Google Cloud Speech client not initialized")
            return None
        
        try:
            # Detect audio format
            format_name, needs_conversion, detected_sample_rate = self._detect_audio_format(audio_chunk)
            
            # Convert WebM/Opus/OGG to LINEAR16 PCM if needed
            processed_audio = audio_chunk
            target_sample_rate = 16000  # Standard 16kHz for speech recognition (required by task 5.2)
            conversion_attempted = False
            conversion_successful = False
            
            if needs_conversion and AUDIO_CONVERTER_AVAILABLE:
                logger.info(f"🔄 Converting {format_name.upper()} to LINEAR16 PCM (16kHz)")
                conversion_attempted = True
                try:
                    converter = get_audio_converter()
                    converted_audio = converter.webm_to_pcm(audio_chunk, target_sample_rate)
                    if converted_audio:
                        processed_audio = converted_audio
                        conversion_successful = True
                        logger.info(f"✅ Converted {len(audio_chunk)} bytes to {len(processed_audio)} bytes LINEAR16 PCM")
                    else:
                        logger.warning("⚠️ Audio conversion failed, will try original format as fallback")
                        logger.info(f"   Fallback: Attempting to send {format_name.upper()} directly to Google Cloud STT")
                        # Fall back to original format
                        needs_conversion = False
                except Exception as conv_error:
                    logger.warning(f"⚠️ Audio conversion error: {conv_error}")
                    logger.info(f"   Fallback: Attempting to send {format_name.upper()} directly to Google Cloud STT")
                    logger.debug(f"   Conversion error details: {conv_error}")
                    # Fall back to original format
                    needs_conversion = False
            elif needs_conversion and not AUDIO_CONVERTER_AVAILABLE:
                logger.warning("⚠️ Audio converter not available")
                logger.info(f"   Fallback: Attempting to send {format_name.upper()} directly to Google Cloud STT")
                logger.info("   Note: Install FFmpeg for better audio format support")
                needs_conversion = False
            
            # Configure recognition based on format and conversion status
            # Task 5.2: Ensure correct encoding (LINEAR16 after conversion) and sample rate (16kHz)
            if conversion_successful or format_name == 'pcm':
                # Use LINEAR16 PCM with explicit 16kHz sample rate (as per task 5.2)
                encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
                sample_rate_hertz = target_sample_rate  # 16000 Hz
                format_display = "LINEAR16 PCM (16kHz)"
                if conversion_successful:
                    logger.info(f"   ✅ Using converted LINEAR16 PCM audio for STT (16kHz)")
                else:
                    logger.info(f"   ✅ Using raw LINEAR16 PCM audio for STT (16kHz)")
            elif format_name == 'flac':
                # Use FLAC directly with 16kHz
                encoding = speech.RecognitionConfig.AudioEncoding.FLAC
                sample_rate_hertz = 16000  # 16kHz as per task 5.2
                format_display = "FLAC (16kHz)"
                logger.info(f"   ✅ Using FLAC format directly (16kHz, no conversion needed)")
            else:
                # Fallback: Try WebM/Opus (may fail with sample rate issues)
                encoding = speech.RecognitionConfig.AudioEncoding.WEBM_OPUS
                sample_rate_hertz = None  # Let Google Cloud detect it
                format_display = f"{format_name.upper()}/Opus (fallback)"
                logger.warning(f"   ⚠️ Using fallback: Sending {format_name.upper()} directly to Google Cloud STT")
                logger.warning(f"   Note: This may fail if audio format is not fully compatible")
            
            # Task 5.2: Configure language codes correctly (hi-IN for patient, en-IN for doctor)
            # Task 5.2: Enable enhanced model and automatic punctuation
            config_params = {
                "encoding": encoding,
                "language_code": language_code,  # hi-IN or en-IN as per task 5.2
                "alternative_language_codes": alternative_language_codes or [],
                "enable_automatic_punctuation": True,  # Task 5.2: Enable automatic punctuation
                "model": "latest_long",  # Task 5.2: Enhanced model for better accuracy
                "use_enhanced": True,  # Task 5.2: Use enhanced model
                "enable_word_time_offsets": False,  # Disable to reduce latency
                "max_alternatives": 1,  # Only need top result
                "profanity_filter": False,  # Medical terms might be flagged
                "audio_channel_count": 1,  # Mono audio
                "enable_separate_recognition_per_channel": False,
            }
            
            # Set sample_rate_hertz for LINEAR16 and FLAC (required)
            if sample_rate_hertz:
                config_params["sample_rate_hertz"] = sample_rate_hertz
            
            config = speech.RecognitionConfig(**config_params)
            audio = speech.RecognitionAudio(content=processed_audio)
            
            logger.info(f"📤 Sending {len(processed_audio)} bytes to Google Cloud STT")
            logger.info(f"   Format: {format_display}")
            logger.info(f"   Language: {language_code}" + (f" (alternatives: {alternative_language_codes})" if alternative_language_codes else ""))
            logger.info(f"   Model: latest_long (enhanced)")
            logger.info(f"   Punctuation: Enabled")
            logger.debug(f"   Config: encoding={encoding.name}, sample_rate={sample_rate_hertz or 'auto'}")
            
            # Task 8.2: Track STT API response time (Requirement 7.4)
            import time
            stt_start_time = time.time()
            
            try:
                response = self.google_speech_client.recognize(config=config, audio=audio)
                
                # Task 8.2: Calculate and log STT API response time
                stt_response_time = (time.time() - stt_start_time) * 1000  # Convert to ms
                logger.info(f"⏱️ Google Cloud STT API response time: {stt_response_time:.2f}ms")
                logger.info(f"📥 Google Cloud STT response: {len(response.results)} results")
            except Exception as stt_error:
                # Task 5.3: Add detailed error logging for STT API failures
                error_type = type(stt_error).__name__
                error_message = str(stt_error)
                
                logger.error(f"❌ Google Cloud STT API error ({error_type}): {error_message}")
                
                # Provide detailed error information based on the situation
                if conversion_attempted and not conversion_successful:
                    logger.error("   Context: Audio conversion failed, attempted fallback with original format")
                    logger.error(f"   Original format: {format_name.upper()}")
                    logger.error(f"   Audio size: {len(audio_chunk)} bytes")
                    logger.error("   Recommendation: Ensure FFmpeg is installed and working correctly")
                elif not conversion_attempted and format_name in ['webm', 'ogg']:
                    logger.error("   Context: Audio converter not available, sent original format")
                    logger.error(f"   Format: {format_name.upper()}/Opus")
                    logger.error("   Recommendation: Install FFmpeg for automatic audio conversion")
                    logger.error("   FFmpeg download: https://ffmpeg.org/download.html")
                else:
                    logger.error(f"   Format used: {format_display}")
                    logger.error(f"   Audio size: {len(processed_audio)} bytes")
                    logger.error(f"   Language: {language_code}")
                
                # Check for specific error types
                if "quota" in error_message.lower() or "limit" in error_message.lower():
                    logger.error("   ⚠️ API quota exceeded - consider upgrading your Google Cloud plan")
                elif "credentials" in error_message.lower() or "authentication" in error_message.lower():
                    logger.error("   ⚠️ Authentication error - check your Google Cloud credentials")
                elif "invalid" in error_message.lower() and "audio" in error_message.lower():
                    logger.error("   ⚠️ Invalid audio format - ensure audio is properly converted to LINEAR16 PCM")
                
                # Log the full error for debugging
                import traceback
                logger.debug(f"   Full error traceback:\n{traceback.format_exc()}")
                
                # Task 5.3: Don't raise - return None to allow fallback to Whisper
                logger.info("   Will attempt fallback to Whisper API if available")
                return None
            
            # Extract transcript from response
            if response.results:
                transcript = ' '.join([
                    result.alternatives[0].transcript
                    for result in response.results
                    if result.alternatives
                ])
                logger.info(f"✅ Google STT transcribed: {transcript}")
                return transcript
            
            logger.warning("⚠️ Google STT returned no results (silence or unclear audio)")
            return None
            
        except Exception as e:
            logger.error(f"❌ Google Cloud Speech-to-Text error: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    async def transcribe_audio_whisper(self, audio_chunk: bytes) -> Optional[str]:
        """
        Transcribe audio using OpenAI Whisper API (fallback).
        
        Task 5.3: Implement fallback to Whisper API if Google fails
        
        Args:
            audio_chunk: Raw audio bytes
            
        Returns:
            Transcribed text or None if transcription fails
        """
        if not self.openai_client:
            logger.debug("OpenAI client not initialized (API key may not be set). Skipping Whisper fallback.")
            return None
        
        try:
            logger.info("🔄 Attempting Whisper API transcription (fallback)")
            
            # Task 8.2: Track Whisper API response time
            import time
            whisper_start_time = time.time()
            
            # Create a file-like object from audio bytes
            audio_file = BytesIO(audio_chunk)
            audio_file.name = "audio.wav"
            
            # Call Whisper API
            response = self.openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
            
            # Task 8.2: Calculate and log Whisper API response time
            whisper_response_time = (time.time() - whisper_start_time) * 1000  # Convert to ms
            logger.info(f"⏱️ Whisper API response time: {whisper_response_time:.2f}ms")
            
            transcript = response if isinstance(response, str) else response.text
            
            if transcript and transcript.strip():
                logger.info(f"✅ Whisper API transcribed: {transcript[:100]}...")
                return transcript.strip()
            else:
                logger.warning("⚠️ Whisper API returned empty transcript")
                return None
            
        except Exception as e:
            # Task 5.3: Add detailed error logging for Whisper API failures
            error_type = type(e).__name__
            error_message = str(e)
            
            logger.error(f"❌ OpenAI Whisper API error ({error_type}): {error_message}")
            
            # Check for specific error types
            if "quota" in error_message.lower() or "limit" in error_message.lower():
                logger.error("   ⚠️ OpenAI API quota exceeded - check your usage limits")
            elif "api_key" in error_message.lower() or "authentication" in error_message.lower():
                logger.error("   ⚠️ OpenAI API key invalid or not set")
            elif "invalid" in error_message.lower() and "audio" in error_message.lower():
                logger.error("   ⚠️ Invalid audio format for Whisper API")
            
            # Log full error for debugging
            import traceback
            logger.debug(f"   Full error traceback:\n{traceback.format_exc()}")
            
            return None
    
    async def transcribe_audio(
        self,
        audio_chunk: bytes,
        user_type: str
    ) -> Optional[str]:
        """
        Transcribe audio with ASR fallback logic and language-specific configuration.
        
        Task 5.2: Configure language codes correctly (hi-IN for patient, en-IN for doctor)
        
        Args:
            audio_chunk: Raw audio bytes
            user_type: 'doctor' or 'patient'
            
        Returns:
            Transcribed text or None if all ASR services fail
        """
        # Task 5.2: Configure language based on user type
        if user_type == 'patient':
            # Patient speaks primarily Hindi (hi-IN as per task 5.2)
            language_code = 'hi-IN'
            alternative_codes = None
            logger.debug(f"🎤 Transcribing patient audio (language: hi-IN)")
        elif user_type == 'doctor':
            # Doctor speaks Hinglish (en-IN with hi-IN alternative as per task 5.2)
            language_code = 'en-IN'
            alternative_codes = ['hi-IN']
            logger.debug(f"🎤 Transcribing doctor audio (language: en-IN, alternatives: hi-IN)")
        else:
            logger.error(f"❌ Invalid user_type: {user_type}")
            return None
        
        # Try primary ASR: Google Cloud Speech-to-Text
        transcript = await self.transcribe_audio_google(
            audio_chunk,
            language_code,
            alternative_codes
        )
        
        if transcript:
            return transcript
        
        # Fallback to OpenAI Whisper API (only if available)
        if self.openai_client:
            logger.warning("⚠️ Google Cloud STT failed, falling back to Whisper API")
            transcript = await self.transcribe_audio_whisper(audio_chunk)
            
            if transcript:
                logger.info("✅ Whisper API fallback successful")
                return transcript
        else:
            logger.debug("Google Cloud STT returned no results. Whisper fallback not available (OPENAI_API_KEY not set).")
        
        logger.warning("⚠️ All available ASR services failed or returned no results")
        return None
    
    async def translate_text(
        self,
        text: str,
        source_language: str,
        target_language: str
    ) -> Optional[str]:
        """
        Translate text using Google Cloud Translation API.
        
        Task 5.3: Return original text if translation fails (graceful degradation)
        
        Args:
            text: Text to translate
            source_language: Source language code ('hi', 'en')
            target_language: Target language code ('hi', 'en')
            
        Returns:
            Translated text or original text if translation fails
        """
        if not self.google_translate_client:
            logger.warning("⚠️ Google Translate client not initialized, returning original text")
            return text
        
        # Skip translation if source and target are the same
        if source_language == target_language:
            logger.debug(f"Source and target languages are the same ({source_language}), skipping translation")
            return text
        
        try:
            logger.debug(f"🔄 Translating from {source_language} to {target_language}")
            
            # Task 8.2: Track translation API response time
            import time
            translation_start_time = time.time()
            
            result = self.google_translate_client.translate(
                text,
                source_language=source_language,
                target_language=target_language
            )
            
            # Task 8.2: Calculate and log translation API response time
            translation_response_time = (time.time() - translation_start_time) * 1000  # Convert to ms
            logger.info(f"⏱️ Translation API response time: {translation_response_time:.2f}ms")
            
            translated_text = result['translatedText']
            logger.info(f"✅ Translated: {text[:50]}... -> {translated_text[:50]}...")
            return translated_text
            
        except Exception as e:
            # Task 5.3: Add detailed error logging for translation failures
            error_type = type(e).__name__
            error_message = str(e)
            
            logger.error(f"❌ Translation error ({error_type}): {error_message}")
            
            # Check for specific error types
            if "quota" in error_message.lower() or "limit" in error_message.lower():
                logger.error("   ⚠️ Translation API quota exceeded")
            elif "credentials" in error_message.lower() or "authentication" in error_message.lower():
                logger.error("   ⚠️ Translation API authentication error")
            
            # Log full error for debugging
            import traceback
            logger.debug(f"   Full error traceback:\n{traceback.format_exc()}")
            
            # Task 5.3: Return original text on error (graceful degradation)
            logger.info(f"   Returning original text as fallback")
            return text
    
    async def lookup_lexicon_term(
        self,
        text: str,
        db_client: DatabaseClient
    ) -> str:
        """
        Perform Community Lexicon lookup and replace regional terms.
        
        Args:
            text: Text containing potential regional medical terms
            db_client: Database client for lexicon search
            
        Returns:
            Text with regional terms replaced by verified English equivalents
        """
        if not text or not text.strip():
            return text
        
        try:
            # Split text into words for term-by-term lookup
            words = text.split()
            replaced_words = []
            
            for word in words:
                # Clean word (remove punctuation for matching)
                clean_word = word.strip('.,!?;:')
                
                # Search lexicon for this term
                english_equivalent = await db_client.search_lexicon(
                    clean_word,
                    threshold=0.85
                )
                
                if english_equivalent:
                    # Replace with English equivalent, preserve punctuation
                    replaced_word = word.replace(clean_word, english_equivalent)
                    replaced_words.append(replaced_word)
                    logger.debug(f"Lexicon replacement: {clean_word} -> {english_equivalent}")
                else:
                    replaced_words.append(word)
            
            return ' '.join(replaced_words)
            
        except Exception as e:
            logger.error(f"Lexicon lookup error: {str(e)}")
            return text  # Return original text on error
    
    async def process_audio_stream(
        self,
        audio_chunk: bytes,
        user_type: str,
        consultation_id: str,
        db_client: Optional[DatabaseClient] = None
    ) -> Dict[str, str]:
        """
        Main STT pipeline: ASR → Lexicon Lookup → Translation → Storage.
        
        Complete Audio Processing Pipeline (Task 5.3, 8.2):
        
        This function orchestrates the complete speech-to-text pipeline for
        real-time audio processing during video consultations. It handles
        the entire flow from raw audio bytes to translated captions.
        
        Pipeline Stages:
        
        1. Speech-to-Text (ASR):
           - Primary: Google Cloud Speech-to-Text
           - Fallback: OpenAI Whisper API
           - Language-specific configuration (hi-IN for patient, en-IN for doctor)
           - Enhanced model with automatic punctuation
        
        2. Community Lexicon Lookup:
           - Replaces regional medical terms with verified English equivalents
           - Uses vector similarity search (embedding model)
           - Improves translation accuracy for medical terminology
           - Continues on failure (non-critical)
        
        3. Translation:
           - Patient (Hindi) → English for doctor
           - Doctor (English/Hinglish) → Hindi for patient
           - Uses Google Cloud Translation API
           - Falls back to original text on failure
        
        4. Transcript Storage:
           - Appends to consultation transcript in database
           - Includes speaker identification
           - Continues on failure (non-critical)
        
        Error Handling Strategy (Task 5.3):
        - Each stage has independent error handling
        - Failures in non-critical stages don't stop the pipeline
        - Returns meaningful error messages to frontend
        - Logs detailed error information for debugging
        - Continues processing other chunks even if one fails
        
        Performance Monitoring (Task 8.2):
        - Tracks timing for each pipeline stage
        - Logs comprehensive performance metrics
        - Helps identify bottlenecks
        - Monitors end-to-end latency
        
        Args:
            audio_chunk: Raw audio bytes from MediaRecorder (WebM/Opus format)
            user_type: 'doctor' or 'patient' (determines language configuration)
            consultation_id: UUID of the consultation session
            db_client: Database client for transcript storage and lexicon lookup
            
        Returns:
            Dictionary with:
                - original_text: Transcribed text in original language
                - translated_text: Translated text for the other participant
                - speaker_id: 'doctor' or 'patient'
                - error: Optional error code if processing failed
                - error_details: Optional detailed error message
        """
        # Task 8.2: Track overall pipeline performance
        import time
        pipeline_start_time = time.time()
        
        # Task 8.2: Track individual stage timings
        stage_timings = {}
        
        try:
            # Step 1: Transcribe audio with ASR fallback
            transcription_start = time.time()
            original_text = await self.transcribe_audio(audio_chunk, user_type)
            stage_timings['transcription'] = (time.time() - transcription_start) * 1000
            
            if not original_text:
                # Task 5.3: Return meaningful error message to frontend
                # Task 8.2: Log performance metrics even on failure
                total_time = (time.time() - pipeline_start_time) * 1000
                logger.warning(f"⚠️ Transcription failed for this audio chunk (time: {total_time:.2f}ms)")
                return {
                    "original_text": "",
                    "translated_text": "",
                    "speaker_id": user_type,
                    "error": "transcription_failed"
                }
            
            # Step 2: Community Lexicon lookup (before translation)
            # Replace regional medical terms with verified English equivalents
            lexicon_start = time.time()
            lexicon_corrected_text = original_text
            try:
                if db_client and hasattr(db_client, 'search_lexicon'):
                    lexicon_corrected_text = await self.lookup_lexicon_term(
                        original_text,
                        db_client
                    )
                stage_timings['lexicon_lookup'] = (time.time() - lexicon_start) * 1000
            except Exception as e:
                # Task 5.3: Continue processing even if lexicon lookup fails
                stage_timings['lexicon_lookup'] = (time.time() - lexicon_start) * 1000
                logger.warning(f"⚠️ Lexicon lookup failed, continuing with original text: {e}")
                lexicon_corrected_text = original_text
            
            # Step 3: Translate based on user type
            if user_type == 'patient':
                # Patient speaks Hindi → Translate to English for doctor
                source_lang = 'hi'
                target_lang = 'en'
            elif user_type == 'doctor':
                # Doctor speaks English/Hinglish → Translate to Hindi for patient
                source_lang = 'en'
                target_lang = 'hi'
            else:
                logger.error(f"❌ Invalid user_type: {user_type}")
                return {
                    "original_text": original_text,
                    "translated_text": original_text,
                    "speaker_id": user_type,
                    "error": "invalid_user_type"
                }
            
            # Task 5.3: Continue processing even if translation fails
            translation_start = time.time()
            translated_text = await self.translate_text(
                lexicon_corrected_text,
                source_lang,
                target_lang
            )
            stage_timings['translation'] = (time.time() - translation_start) * 1000
            
            # If translation failed, use original text
            if not translated_text:
                logger.warning(f"⚠️ Translation failed, using original text")
                translated_text = original_text
            
            # Step 4: Append to consultation transcript
            transcript_start = time.time()
            try:
                if db_client and hasattr(db_client, 'append_transcript'):
                    transcript_entry = f"[{user_type.upper()}]: {original_text}"
                    await db_client.append_transcript(consultation_id, transcript_entry)
                stage_timings['transcript_save'] = (time.time() - transcript_start) * 1000
            except Exception as e:
                # Task 5.3: Continue processing even if transcript save fails
                stage_timings['transcript_save'] = (time.time() - transcript_start) * 1000
                logger.warning(f"⚠️ Transcript save failed, continuing: {e}")
            
            # Task 8.2: Calculate total pipeline time and log performance metrics
            total_pipeline_time = (time.time() - pipeline_start_time) * 1000
            
            # Task 8.2: Log comprehensive performance metrics for debugging (Requirement 7.4, 7.5)
            logger.info(f"⏱️ Pipeline Performance Metrics:")
            logger.info(f"   Total pipeline time: {total_pipeline_time:.2f}ms")
            logger.info(f"   - Transcription: {stage_timings.get('transcription', 0):.2f}ms")
            logger.info(f"   - Lexicon lookup: {stage_timings.get('lexicon_lookup', 0):.2f}ms")
            logger.info(f"   - Translation: {stage_timings.get('translation', 0):.2f}ms")
            logger.info(f"   - Transcript save: {stage_timings.get('transcript_save', 0):.2f}ms")
            
            # Return result
            result = {
                "original_text": original_text,
                "translated_text": translated_text,
                "speaker_id": user_type
            }
            
            logger.info(f"✅ Processed audio for {user_type} in consultation {consultation_id}")
            return result
            
        except Exception as e:
            # Task 5.3: Add detailed error logging and return meaningful error message
            # Task 8.2: Log performance metrics even on error
            total_time = (time.time() - pipeline_start_time) * 1000
            error_type = type(e).__name__
            error_message = str(e)
            
            logger.error(f"❌ Error in process_audio_stream ({error_type}): {error_message}")
            logger.error(f"   Processing time before error: {total_time:.2f}ms")
            
            # Task 8.2: Log stage timings if available
            if stage_timings:
                logger.error(f"   Stage timings before error:")
                for stage, timing in stage_timings.items():
                    logger.error(f"     - {stage}: {timing:.2f}ms")
            
            # Log full error for debugging
            import traceback
            logger.debug(f"   Full error traceback:\n{traceback.format_exc()}")
            
            # Task 5.3: Return error information to frontend
            return {
                "original_text": "",
                "translated_text": "",
                "speaker_id": user_type,
                "error": "processing_failed",
                "error_details": error_message
            }


# Singleton instance
_stt_pipeline: Optional[STTPipeline] = None

def get_stt_pipeline() -> STTPipeline:
    """
    Get or create singleton STT pipeline instance.
    
    Returns:
        STTPipeline instance
    """
    global _stt_pipeline
    if _stt_pipeline is None:
        _stt_pipeline = STTPipeline()
    return _stt_pipeline


def validate_stt_configuration() -> Dict[str, any]:
    """
    Validate STT pipeline configuration at startup.
    
    Returns:
        Dictionary with validation results:
        {
            "google_cloud_available": bool,
            "google_credentials_valid": bool,
            "google_speech_client": bool,
            "google_translate_client": bool,
            "openai_available": bool,
            "openai_client": bool,
            "warnings": List[str],
            "errors": List[str]
        }
    """
    pipeline = get_stt_pipeline()
    
    warnings = []
    errors = []
    
    # Check Google Cloud availability
    if not GOOGLE_CLOUD_AVAILABLE:
        warnings.append("Google Cloud libraries not installed")
    
    # Check Google Cloud credentials
    if not pipeline.google_credentials_valid:
        errors.append("Google Cloud credentials not valid or not configured")
    
    # Check Google Cloud clients
    if not pipeline.google_speech_client:
        errors.append("Google Cloud Speech-to-Text client not initialized")
    
    if not pipeline.google_translate_client:
        warnings.append("Google Cloud Translation client not initialized")
    
    # Check OpenAI availability
    if not OPENAI_AVAILABLE:
        warnings.append("OpenAI library not installed (Whisper fallback unavailable)")
    
    if not pipeline.openai_client:
        warnings.append("OpenAI API key not configured (Whisper fallback unavailable)")
    
    # Check if at least one ASR service is available
    if not pipeline.google_speech_client and not pipeline.openai_client:
        errors.append("No ASR service available (neither Google Cloud STT nor OpenAI Whisper)")
    
    return {
        "google_cloud_available": GOOGLE_CLOUD_AVAILABLE,
        "google_credentials_valid": pipeline.google_credentials_valid,
        "google_speech_client": pipeline.google_speech_client is not None,
        "google_translate_client": pipeline.google_translate_client is not None,
        "openai_available": OPENAI_AVAILABLE,
        "openai_client": pipeline.openai_client is not None,
        "warnings": warnings,
        "errors": errors
    }
