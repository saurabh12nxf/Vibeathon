'use client'

import { useEffect, useRef, useState } from 'react'
import { Card } from '@/components/ui/card'
import { Subtitles, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Caption {
  speaker: 'doctor' | 'patient'
  original_text: string
  translated_text: string
  timestamp: number
  id: string
}

interface LiveCaptionsProps {
  consultationId: string
  userType: 'doctor' | 'patient'
  localStream: MediaStream | null
  enabled: boolean
  onToggle: () => void
}

// Task 7: Error types for comprehensive error handling
type ErrorType = 
  | 'microphone_permission' 
  | 'connection_error' 
  | 'stt_failure' 
  | 'api_quota_exceeded'
  | null

interface ErrorState {
  type: ErrorType
  message: string
  details?: string
}

export default function LiveCaptions({
  consultationId,
  userType,
  localStream,
  enabled,
  onToggle
}: LiveCaptionsProps) {
  // Debug: Log when component mounts/updates
  console.log('🎬 LiveCaptions component rendered:', {
    consultationId,
    userType,
    hasLocalStream: !!localStream,
    enabled,
    audioTracks: localStream?.getAudioTracks().length || 0
  })
  
  const [captions, setCaptions] = useState<Caption[]>([])
  const [isConnected, setIsConnected] = useState(false)
  // Task 7: Add error state for comprehensive error handling
  const [error, setError] = useState<ErrorState | null>(null)
  const [sttFailureCount, setSttFailureCount] = useState(0) // Track consecutive STT failures
  const wsRef = useRef<WebSocket | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const captionsEndRef = useRef<HTMLDivElement>(null)
  const setupTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const audioChunkCountRef = useRef(0)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const chunkQueueRef = useRef<Blob[]>([]) // Queue chunks if WebSocket is not ready
  const reconnectAttemptsRef = useRef(0) // Track reconnection attempts for exponential backoff
  const maxReconnectAttempts = 10 // Maximum reconnection attempts
  const isCleanupRef = useRef(false) // Track if we're in cleanup mode
  const connectWebSocketRef = useRef<(() => Promise<WebSocket | null>) | null>(null) // Store connect function for retry button
  
  // Task 8.1: Track audio chunk timing to verify 3-second interval
  const lastChunkTimeRef = useRef<number>(0)
  const chunkIntervalsRef = useRef<number[]>([])
  
  // Task 8.1: Track latency from speech to caption display
  const speechStartTimeRef = useRef<number>(0)
  const captionLatenciesRef = useRef<number[]>([])
  
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
  // Properly convert HTTP/HTTPS URLs to WebSocket URLs
  // Replace http:// with ws:// and https:// with wss://
  const wsUrl = backendUrl.startsWith('https://')
    ? backendUrl.replace(/^https:\/\//, 'wss://')
    : backendUrl.replace(/^http:\/\//, 'ws://')
  
  // Debug logging
  useEffect(() => {
    console.log('🔍 LiveCaptions Debug Info:', {
      enabled,
      hasLocalStream: !!localStream,
      consultationId,
      userType,
      backendUrl,
      wsUrl,
      audioTracks: localStream?.getAudioTracks().length || 0
    })
  }, [enabled, localStream, consultationId, userType, backendUrl, wsUrl])

  // Auto-scroll to latest caption
  useEffect(() => {
    if (captionsEndRef.current) {
      captionsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [captions])

  // Setup caption WebSocket and audio streaming
  useEffect(() => {
    if (!enabled || !localStream) {
      // Cleanup if disabled
      isCleanupRef.current = true
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop()
        mediaRecorderRef.current = null
      }
      return
    }

    // Reset cleanup flag when enabled
    isCleanupRef.current = false
    
    // CRITICAL FIX: Add periodic health check to ensure MediaRecorder stays active
    const healthCheckInterval = setInterval(() => {
      if (!enabled || !localStream || isCleanupRef.current) {
        return
      }
      
      const recorder = mediaRecorderRef.current
      const ws = wsRef.current
      const audioTrack = localStream.getAudioTracks()[0]
      
      console.log('🔄 Health check:', {
        recorderState: recorder?.state || 'null',
        wsState: ws?.readyState || 'null',
        trackState: audioTrack?.readyState || 'null',
        trackEnabled: audioTrack?.enabled || false,
        isConnected
      })
      
      // Restart MediaRecorder if it stopped unexpectedly
      if ((!recorder || recorder.state === 'inactive') && 
          audioTrack?.readyState === 'live' && 
          ws?.readyState === WebSocket.OPEN) {
        console.warn('⚠️ Health check: MediaRecorder inactive, restarting...')
        setupMediaRecorder()
      }
      
      // Send ping to keep WebSocket alive
      if (ws?.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ type: 'ping' }))
        } catch (e) {
          console.warn('Failed to send ping:', e)
        }
      }
    }, 10000) // Check every 10 seconds
    
    /**
     * Calculate exponential backoff delay for WebSocket reconnection
     * 
     * WebSocket Reconnection Strategy (Task 3.2):
     * - Uses exponential backoff to avoid overwhelming the server
     * - Starts with 1 second delay, doubles each attempt
     * - Caps at 30 seconds maximum delay
     * - Prevents connection storms during server issues
     * 
     * Example progression: 1s → 2s → 4s → 8s → 16s → 30s (capped)
     * 
     * @param attempts - Number of reconnection attempts so far
     * @returns Delay in milliseconds before next reconnection attempt
     */
    const getReconnectDelay = (attempts: number): number => {
      // Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 30s
      const baseDelay = 1000
      const maxDelay = 30000
      const delay = Math.min(baseDelay * Math.pow(2, attempts), maxDelay)
      console.log(`🔄 Reconnect attempt ${attempts + 1}, delay: ${delay}ms`)
      return delay
    }

    // Store message handler for reuse during reconnection
    const messageHandler = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        
        if (data.type === 'caption') {
          // Task 8.1: Calculate latency from speech start to caption display
          const captionReceivedTime = Date.now()
          if (speechStartTimeRef.current > 0) {
            const latency = captionReceivedTime - speechStartTimeRef.current
            captionLatenciesRef.current.push(latency)
            
            // Keep only last 10 latencies for average calculation
            if (captionLatenciesRef.current.length > 10) {
              captionLatenciesRef.current.shift()
            }
            
            // Calculate average latency
            const avgLatency = captionLatenciesRef.current.reduce((a, b) => a + b, 0) / captionLatenciesRef.current.length
            
            // Task 8.1: Ensure captions appear within 5 seconds (Requirement 7.1)
            if (latency > 5000) {
              console.warn(`⚠️ Caption latency exceeded 5s: ${(latency / 1000).toFixed(2)}s (avg: ${(avgLatency / 1000).toFixed(2)}s)`)
            } else {
              console.log(`⏱️ Caption latency: ${(latency / 1000).toFixed(2)}s (avg: ${(avgLatency / 1000).toFixed(2)}s) ✅`)
            }
            
            // Reset speech start time for next caption
            speechStartTimeRef.current = 0
          }
          
          const newCaption: Caption = {
            speaker: data.speaker,
            original_text: data.original_text || '',
            translated_text: data.translated_text || data.original_text || '',
            timestamp: Date.now(),
            id: `${data.speaker}-${Date.now()}-${Math.random()}`
          }
          
          console.log('📝 Caption received:', {
            speaker: newCaption.speaker,
            original: newCaption.original_text.substring(0, 50),
            translated: newCaption.translated_text.substring(0, 50),
            connectionState: wsRef.current?.readyState
          })
          
          // Task 7.3: Reset STT failure count on successful caption
          setSttFailureCount(0)
          setError(null) // Clear any previous errors
          
          setCaptions(prev => {
            const updated = [...prev, newCaption]
            return updated.slice(-10)
          })
          
          // CRITICAL FIX: Ensure MediaRecorder is still running after receiving caption
          if (mediaRecorderRef.current?.state === 'inactive' && enabled && localStream) {
            console.warn('⚠️ MediaRecorder stopped after caption received, restarting...')
            setTimeout(() => {
              if (enabled && localStream && !isCleanupRef.current) {
                setupMediaRecorder()
              }
            }, 100)
          }
          
        } else if (data.type === 'connected') {
          console.log('✅ Caption service connected:', data.message)
          // Clear connection errors on successful connection
          setError(null)
        } else if (data.type === 'error') {
          console.error('❌ Caption service error:', data.message)
          
          // Task 7.3: Handle different error types from backend
          if (data.message?.includes('STT') || data.message?.includes('transcription')) {
            setSttFailureCount(prev => prev + 1)
            console.error(`❌ STT failure count: ${sttFailureCount + 1}`)
            
            // Task 7.3: Show error after 3 consecutive failures
            if (sttFailureCount >= 2) {
              setError({
                type: 'stt_failure',
                message: 'Speech recognition is having trouble',
                details: 'Try speaking more clearly or check your microphone'
              })
            }
          } else if (data.message?.includes('quota') || data.message?.includes('limit')) {
            // Task 7.3: Display API quota exceeded message
            setError({
              type: 'api_quota_exceeded',
              message: 'Caption service temporarily unavailable',
              details: 'API quota exceeded. Please try again later.'
            })
          } else {
            // Generic error - don't let it stop the caption flow
            console.error('❌ Backend error (continuing):', data.message)
          }
        } else if (data.type === 'pong') {
          console.log('🏓 Pong received - connection alive')
        } else {
          console.log('📨 Received caption message:', data.type, data)
        }
      } catch (err) {
        console.error('Error parsing caption message:', err, 'Raw data:', event.data)
        // Don't let parsing errors stop the caption flow
      }
    }
    
    /**
     * Check if backend server is reachable before connecting WebSocket
     */
    const checkBackendHealth = async (): Promise<boolean> => {
      try {
        const healthUrl = `${backendUrl}/health`
        console.log(`🏥 Checking backend health: ${healthUrl}`)
        
        // Create an AbortController for timeout (more compatible than AbortSignal.timeout)
        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 3000) // 3 second timeout
        
        try {
          const response = await fetch(healthUrl, {
            method: 'GET',
            headers: {
              'Content-Type': 'application/json',
            },
            signal: controller.signal
          })
          
          clearTimeout(timeoutId)
          
          if (response.ok) {
            console.log('✅ Backend server is reachable')
            return true
          } else {
            console.warn(`⚠️ Backend returned status ${response.status}`)
            return false
          }
        } catch (fetchError: any) {
          clearTimeout(timeoutId)
          throw fetchError
        }
      } catch (error: any) {
        console.error('❌ Backend health check failed:', error)
        if (error.name === 'AbortError' || error.name === 'TimeoutError') {
          console.error('⏱️ Backend health check timed out - server may not be running')
        } else if (error.message?.includes('Failed to fetch') || error.message?.includes('NetworkError')) {
          console.error('🌐 Network error - backend server is not reachable')
        }
        return false
      }
    }
    
    /**
     * Establish WebSocket connection with automatic reconnection
     * 
     * WebSocket Connection Management (Task 3.1, 3.2):
     * 1. Checks backend health before connecting
     * 2. Creates WebSocket connection to caption service
     * 3. Handles connection lifecycle (open, message, error, close)
     * 4. Implements automatic reconnection with exponential backoff
     * 5. Manages chunk queue during disconnection (max 10 chunks)
     * 6. Coordinates with MediaRecorder to ensure audio capture continues
     * 
     * Connection Flow:
     * - Health check: Verify backend is running
     * - onopen: Send queued chunks, start/restart MediaRecorder
     * - onmessage: Process caption data from backend
     * - onerror: Log error, set connection error state
     * - onclose: Trigger automatic reconnection (if not in cleanup mode)
     * 
     * @returns WebSocket instance or null if backend is not reachable
     */
    const connectWebSocket = async (): Promise<WebSocket | null> => {
      // First, check if backend is reachable
      const isBackendHealthy = await checkBackendHealth()
      
      if (!isBackendHealthy) {
        console.error('❌ Backend server is not reachable. Cannot connect WebSocket.')
        setError({
          type: 'connection_error',
          message: 'Backend server is not running',
          details: `Cannot connect to ${backendUrl}. Please start the backend server by running: cd backend && python run.py`
        })
        setIsConnected(false)
        return null
      }
      
      const wsEndpoint = `${wsUrl}/ws/captions/${consultationId}/${userType}`
      console.log(`🔌 Connecting to WebSocket (attempt ${reconnectAttemptsRef.current + 1})...`)
      console.log(`🔗 WebSocket URL: ${wsEndpoint}`)
      
      let ws: WebSocket
      try {
        ws = new WebSocket(wsEndpoint)
      } catch (error) {
        console.error('❌ Failed to create WebSocket:', error)
        setError({
          type: 'connection_error',
          message: 'Failed to create WebSocket connection',
          details: `Invalid WebSocket URL: ${wsEndpoint}. Please check your backend URL configuration.`
        })
        setIsConnected(false)
        return null
      }
      
      wsRef.current = ws

      ws.onopen = () => {
        console.log('✅ Caption WebSocket connected')
        setIsConnected(true)
        reconnectAttemptsRef.current = 0 // Reset reconnection counter on successful connection
        setError(null) // Clear any previous errors
        
        // Task 3.2: Send any queued chunks after successful connection
        if (chunkQueueRef.current.length > 0) {
          console.log(`📤 Sending ${chunkQueueRef.current.length} queued chunks after connection`)
          const chunksToSend = [...chunkQueueRef.current]
          chunkQueueRef.current = []
          
          chunksToSend.forEach((chunk, index) => {
            if (ws.readyState === WebSocket.OPEN) {
              try {
                ws.send(chunk)
                console.log(`📤 Sent queued chunk ${index + 1}/${chunksToSend.length}`)
              } catch (e) {
                console.error('Error sending queued chunk:', e)
                // Re-queue failed chunks
                chunkQueueRef.current.push(chunk)
              }
            }
          })
        }
        
        // Task 3.3: Check if MediaRecorder needs to be started/restarted
        if (!mediaRecorderRef.current || mediaRecorderRef.current.state === 'inactive') {
          console.log('🎬 Starting MediaRecorder after WebSocket connection')
          setTimeout(() => {
            setupMediaRecorder()
          }, 500)
        }
      }

      ws.onmessage = messageHandler

      ws.onerror = (error) => {
        // WebSocket error events don't provide detailed error info in browsers
        // The actual error information is available in the onclose event
        console.error('❌ Caption WebSocket error event triggered')
        console.error('🔍 WebSocket connection state:', ws.readyState)
        console.error('🔗 WebSocket URL:', wsEndpoint)
        
        // Get more details from the WebSocket object
        const wsState = {
          readyState: ws.readyState,
          url: ws.url,
          protocol: ws.protocol,
          extensions: ws.extensions
        }
        console.error('📊 WebSocket state:', wsState)
        
        setIsConnected(false)
        
        // Don't set error here - let onclose handle it with more details
        // The onclose event will have the close code and reason
      }

      ws.onclose = (event) => {
        const closeInfo = {
          code: event.code,
          reason: event.reason || 'No reason provided',
          wasClean: event.wasClean,
          reconnectAttempts: reconnectAttemptsRef.current
        }
        console.log('🔌 Caption WebSocket closed', closeInfo)
        
        // WebSocket close codes: https://developer.mozilla.org/en-US/docs/Web/API/CloseEvent/code
        const closeCodeMessages: { [key: number]: string } = {
          1000: 'Normal closure',
          1001: 'Going away',
          1002: 'Protocol error',
          1003: 'Unsupported data',
          1006: 'Abnormal closure (no close frame)',
          1007: 'Invalid frame payload data',
          1008: 'Policy violation',
          1009: 'Message too big',
          1010: 'Missing extension',
          1011: 'Internal error',
          1012: 'Service restart',
          1013: 'Try again later',
          1014: 'Bad gateway',
          1015: 'TLS handshake failure'
        }
        
        const closeMessage = closeCodeMessages[event.code] || `Unknown close code: ${event.code}`
        console.log(`📋 Close reason: ${closeMessage}`)
        
        setIsConnected(false)
        
        // Task 3.1: Don't reconnect if we're in cleanup mode
        if (isCleanupRef.current) {
          console.log('🛑 Skipping reconnection - component is cleaning up')
          return
        }
        
        // Provide better error messages based on close code
        let errorDetails = 'Connection lost. '
        if (event.code === 1006) {
          errorDetails = 'Connection failed. The backend server might not be running or the URL is incorrect. '
          console.error('❌ WebSocket connection failed - likely causes:')
          console.error('   1. Backend server is not running')
          console.error('   2. Incorrect backend URL in environment variables')
          console.error('   3. Firewall or network blocking the connection')
          console.error(`   4. WebSocket URL: ${wsEndpoint}`)
        } else if (!event.wasClean) {
          errorDetails = `Connection closed unexpectedly (code: ${event.code}). `
        }
        
        // Task 3.2: Implement automatic reconnection with exponential backoff
        if (enabled && localStream && reconnectAttemptsRef.current < maxReconnectAttempts) {
          const delay = getReconnectDelay(reconnectAttemptsRef.current)
          reconnectAttemptsRef.current++
          
          console.log(`🔄 Scheduling WebSocket reconnection (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts}) in ${delay}ms...`)
          
          // Task 7.2: Show connection error with retry info and helpful details
          setError({
            type: 'connection_error',
            message: event.code === 1006 ? 'Cannot connect to caption service' : 'Connection lost',
            details: `${errorDetails}Reconnecting... (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})`
          })
          
          reconnectTimeoutRef.current = setTimeout(async () => {
            // Double-check conditions before reconnecting
            if (enabled && localStream && !isCleanupRef.current && 
                (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED)) {
              await connectWebSocket()
            } else {
              console.log('🛑 Skipping reconnection - conditions no longer met')
            }
          }, delay)
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          console.error(`❌ Max reconnection attempts (${maxReconnectAttempts}) reached. Please refresh the page.`)
          console.error(`🔗 Failed WebSocket URL: ${wsEndpoint}`)
          console.error('💡 Troubleshooting:')
          console.error('   1. Check if backend server is running: http://localhost:8000/docs')
          console.error('   2. Verify NEXT_PUBLIC_BACKEND_URL in .env.local')
          console.error('   3. Check browser console for CORS or network errors')
          
          // Task 7.2: Display error when max reconnection attempts reached with helpful details
          setError({
            type: 'connection_error',
            message: 'Cannot connect to caption service',
            details: `${errorDetails}Maximum reconnection attempts reached. Please check: 1) Backend server is running, 2) Backend URL is correct, 3) No firewall blocking connection.`
          })
        }
      }

      return ws
    }

    /**
     * Setup MediaRecorder for audio capture
     * 
     * MediaRecorder Setup Logic (Task 2.1, 2.2, 2.3, 3.1, 3.3):
     * 
     * 1. Validation Phase:
     *    - Check localStream availability (microphone permission)
     *    - Verify audio tracks exist
     *    - Validate WebSocket connection state
     *    - Wait for WebSocket if not ready (up to 5 seconds)
     * 
     * 2. Audio Track Readiness Checks (Task 2.3):
     *    - Verify track is in 'live' state
     *    - Retry up to 4 times if track not ready (500ms intervals)
     *    - Ensure track is enabled
     *    - Add 1-second delay to ensure track is producing data
     * 
     * 3. MediaRecorder Configuration:
     *    - Determine best supported audio format (WebM/Opus preferred)
     *    - Create MediaRecorder with appropriate MIME type
     *    - Set up event handlers for state transitions
     *    - Configure 3-second timeslice for optimal STT accuracy
     * 
     * 4. Audio Chunk Handling (Task 2.2):
     *    - Validate chunk size (skip < 100 bytes)
     *    - Track consecutive empty chunks
     *    - Send chunks via WebSocket or queue if disconnected
     *    - Log warnings after 3+ consecutive empty chunks
     * 
     * 5. State Monitoring (Task 2.1):
     *    - Log all state transitions (start, stop, pause, resume, error)
     *    - Periodic state checks every 5 seconds
     *    - Track audio track properties throughout lifecycle
     * 
     * 6. Error Recovery (Task 3.3):
     *    - Detect unexpected stops
     *    - Restart MediaRecorder if conditions are met
     *    - Wait for WebSocket reconnection before restart
     *    - Prevent restart during cleanup
     */
    const setupMediaRecorder = async () => {
      try {
        console.log('🎬 Starting MediaRecorder setup...')
        
        // Task 7.1: Check if localStream has audio tracks (microphone permission)
        if (!localStream) {
          console.error('❌ No local stream available')
          setError({
            type: 'microphone_permission',
            message: 'Microphone not available',
            details: 'Please ensure you have granted microphone permissions'
          })
          return
        }
        
        const audioTracks = localStream.getAudioTracks()
        if (audioTracks.length === 0) {
          console.error('❌ No audio tracks in stream - microphone permission may be denied')
          setError({
            type: 'microphone_permission',
            message: 'Microphone access denied',
            details: 'Please grant microphone permissions in your browser settings'
          })
          return
        }
        
        // Task 3.1: Validate WebSocket connection state before proceeding
        const ws = wsRef.current
        if (!ws) {
          console.error('❌ WebSocket not available for MediaRecorder setup')
          return
        }

        if (ws.readyState !== WebSocket.OPEN) {
          console.log('⏳ WebSocket not ready, waiting for connection before starting MediaRecorder...')
          // Wait up to 5 seconds for WebSocket
          let attempts = 0
          const maxAttempts = 10
          
          while (attempts < maxAttempts) {
            const currentWs = wsRef.current
            if (!currentWs) {
              console.error('❌ WebSocket reference lost during wait')
              return
            }
            if (currentWs.readyState === WebSocket.OPEN) {
              console.log(`✅ WebSocket ready after ${attempts * 500}ms`)
              break
            }
            await new Promise(resolve => setTimeout(resolve, 500))
            attempts++
          }
          
          // Final validation
          const finalWs = wsRef.current
          if (!finalWs || finalWs.readyState !== WebSocket.OPEN) {
            console.error('❌ WebSocket not ready after waiting, aborting MediaRecorder setup', {
              hasWs: !!finalWs,
              state: finalWs?.readyState
            })
            return
          }
        }
        
        console.log('✅ WebSocket connection validated, proceeding with MediaRecorder setup')

        const audioTrack = localStream.getAudioTracks()[0]
        if (!audioTrack) {
          console.error('❌ No audio track available for captions')
          // Task 7.1: Set microphone permission error
          setError({
            type: 'microphone_permission',
            message: 'No microphone detected',
            details: 'Please check your microphone connection and permissions'
          })
          return
        }

        // Task 2.3: Implement audio track readiness checks
        console.log('🔍 Checking audio track readiness...')
        console.log('📊 Audio track initial state:', {
          readyState: audioTrack.readyState,
          enabled: audioTrack.enabled,
          muted: audioTrack.muted,
          label: audioTrack.label,
          kind: audioTrack.kind
        })

        // Check if track is actually active
        const initialTrackState = audioTrack.readyState
        if (initialTrackState !== 'live') {
          console.warn('⚠️ Audio track not in "live" state:', initialTrackState)
          
          // Task 2.3: Add retry logic if track is not ready
          let retryCount = 0
          const maxRetries = 4
          
          while (audioTrack.readyState !== 'live' && retryCount < maxRetries) {
            retryCount++
            console.log(`⏳ Retry ${retryCount}/${maxRetries}: Waiting 500ms for audio track to become live...`)
            await new Promise(resolve => setTimeout(resolve, 500))
            console.log(`📊 Audio track state after retry ${retryCount}:`, audioTrack.readyState)
          }
          
          const finalTrackState = audioTrack.readyState
          if (finalTrackState !== 'live') {
            console.error('❌ Audio track failed to become live after', maxRetries, 'retries. Current state:', finalTrackState)
            return
          }
          
          console.log('✅ Audio track is now live after', retryCount, 'retries')
        }

        // Verify track is enabled
        if (!audioTrack.enabled) {
          console.warn('⚠️ Audio track is disabled, enabling...')
          audioTrack.enabled = true
          console.log('✅ Audio track enabled')
        }

        // Task 2.3: Add delay before starting MediaRecorder to ensure track is producing data
        console.log('⏳ Waiting 1000ms to ensure audio track is producing data...')
        await new Promise(resolve => setTimeout(resolve, 1000))
        
        // Verify track is still live after delay
        console.log('🔍 Audio track state after delay:', {
          readyState: audioTrack.readyState,
          enabled: audioTrack.enabled,
          muted: audioTrack.muted
        })
        
        // Check if audio track is still active
        const trackState = audioTrack.readyState
        if (trackState !== 'live') {
          console.error('❌ Audio track no longer live after delay:', trackState)
          return
        }
        
        console.log('✅ Audio track readiness checks passed')

        // Create a new MediaStream with only audio
        const audioStream = new MediaStream([audioTrack])
        
        // Determine the best audio format with better fallback
        // IMPORTANT: Prefer OGG Opus over WebM because:
        // 1. OGG creates complete, self-contained chunks (each chunk is a valid OGG file)
        // 2. WebM creates streaming chunks without headers (FFmpeg can't parse them)
        // 3. Google Cloud STT works better with complete audio files
        let mimeType: string | undefined = undefined
        const supportedTypes = [
          'audio/ogg;codecs=opus',  // PREFERRED: Complete chunks with headers
          'audio/webm;codecs=opus', // Fallback: Streaming chunks (may need buffering)
          'audio/webm',
          'audio/mp4'
        ]
        
        for (const type of supportedTypes) {
          if (MediaRecorder.isTypeSupported(type)) {
            mimeType = type
            console.log(`✅ Selected audio format: ${type}`)
            break
          }
        }
        
        // If no specific type is supported, try without MIME type (browser default)
        if (!mimeType) {
          console.warn('⚠️ No specific audio format supported, using browser default')
          console.warn('   This may cause issues with audio transcription')
        }
        
        console.log(`🎤 Using audio format: ${mimeType || 'browser default'}`)
        
        // Create MediaRecorder with optional MIME type
        const options: MediaRecorderOptions = {}
        if (mimeType) {
          options.mimeType = mimeType
        }
        
        // Stop any existing recorder first
        if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
          try {
            mediaRecorderRef.current.stop()
          } catch (e) {
            console.warn('Error stopping existing MediaRecorder:', e)
          }
        }
        
        const mediaRecorder = new MediaRecorder(audioStream, options)
        mediaRecorderRef.current = mediaRecorder
        
        // Task 2.1: Add comprehensive logging for MediaRecorder state transitions
        console.log('📹 MediaRecorder created:', {
          state: mediaRecorder.state,
          mimeType: mediaRecorder.mimeType,
          audioBitsPerSecond: mediaRecorder.audioBitsPerSecond
        })
        
        // Task 2.2: Track consecutive empty chunks with proper validation
        let consecutiveEmptyChunks = 0
        const MIN_CHUNK_SIZE = 100 // Skip chunks smaller than 100 bytes
        const MAX_EMPTY_CHUNKS = 3 // Allow a few empty chunks at start
        let firstChunkReceived = false
        let isRecorderActive = true // Track if recorder should be active
        
        // Stream audio chunks to backend at 3-second intervals for better STT accuracy
        mediaRecorder.ondataavailable = (event) => {
          // Task 8.1: Track chunk timing to verify 3-second interval
          const currentTime = Date.now()
          if (lastChunkTimeRef.current > 0) {
            const interval = currentTime - lastChunkTimeRef.current
            chunkIntervalsRef.current.push(interval)
            
            // Keep only last 10 intervals for average calculation
            if (chunkIntervalsRef.current.length > 10) {
              chunkIntervalsRef.current.shift()
            }
            
            // Calculate average interval
            const avgInterval = chunkIntervalsRef.current.reduce((a, b) => a + b, 0) / chunkIntervalsRef.current.length
            
            // Log if interval deviates significantly from 3000ms
            if (Math.abs(interval - 3000) > 500) {
              console.warn(`⚠️ Chunk interval deviation: ${interval}ms (expected: 3000ms, avg: ${avgInterval.toFixed(0)}ms)`)
            } else {
              console.log(`⏱️ Chunk interval: ${interval}ms (avg: ${avgInterval.toFixed(0)}ms)`)
            }
          }
          lastChunkTimeRef.current = currentTime
          
          // Task 8.1: Record speech start time for latency tracking
          if (!speechStartTimeRef.current) {
            speechStartTimeRef.current = currentTime
          }
          
          // Task 2.2: Implement proper validation for audio chunk size
          if (event.data && event.data.size >= MIN_CHUNK_SIZE) {
            audioChunkCountRef.current++
            const chunkSize = event.data.size
            consecutiveEmptyChunks = 0 // Reset counter on valid chunk
            
            // Task 2.1: Log first audio chunk reception to confirm data flow
            if (!firstChunkReceived) {
              firstChunkReceived = true
              console.log('✅ First audio chunk received!', {
                size: chunkSize,
                type: event.data.type,
                timestamp: new Date().toISOString()
              })
            }
            
            // Always check current WebSocket reference (may have reconnected)
            const currentWs = wsRef.current
            if (currentWs && currentWs.readyState === WebSocket.OPEN) {
              try {
                // Send binary audio chunk
                currentWs.send(event.data)
                console.log(`📤 Sent audio chunk #${audioChunkCountRef.current}: ${chunkSize} bytes`)
                
                // Send any queued chunks
                if (chunkQueueRef.current.length > 0) {
                  console.log(`📤 Sending ${chunkQueueRef.current.length} queued chunks`)
                  chunkQueueRef.current.forEach(chunk => {
                    try {
                      if (currentWs.readyState === WebSocket.OPEN) {
                        currentWs.send(chunk)
                      }
                    } catch (e) {
                      console.error('Error sending queued chunk:', e)
                    }
                  })
                  chunkQueueRef.current = []
                }
              } catch (sendError) {
                console.error('Error sending audio chunk:', sendError)
                // Queue chunk for later
                chunkQueueRef.current.push(event.data)
                console.log(`📦 Queued chunk #${audioChunkCountRef.current} (will send when WebSocket reconnects)`)
              }
            } else {
              // Task 3.2: Queue chunk with max 10 chunks limit
              const wsState = currentWs ? currentWs.readyState : 'NO_WS'
              
              if (chunkQueueRef.current.length < 10) {
                chunkQueueRef.current.push(event.data)
                console.log(`📦 Queued chunk #${audioChunkCountRef.current} (queue: ${chunkQueueRef.current.length}/10, WebSocket state: ${wsState})`)
              } else {
                console.warn(`⚠️ Chunk queue full (10/10), dropping chunk #${audioChunkCountRef.current}`)
              }
            }
          } else {
            // Task 2.2: Add counter for consecutive empty chunks
            consecutiveEmptyChunks++
            const chunkSize = event.data?.size || 0
            
            // Task 2.2: Log warnings only after threshold exceeded (3+ empty chunks)
            if (consecutiveEmptyChunks > MAX_EMPTY_CHUNKS) {
              console.warn(`⚠️ Empty/small audio chunk #${consecutiveEmptyChunks} (size: ${chunkSize} bytes, threshold: ${MIN_CHUNK_SIZE} bytes)`)
              console.warn('🔍 Audio track may not be producing data. Diagnostics:', {
                hasAudioTrack: !!localStream?.getAudioTracks()[0],
                trackState: localStream?.getAudioTracks()[0]?.readyState,
                trackEnabled: localStream?.getAudioTracks()[0]?.enabled,
                trackMuted: localStream?.getAudioTracks()[0]?.muted,
                consecutiveEmptyChunks
              })
              console.warn('💡 Check microphone permissions and audio settings.')
            } else {
              console.log(`ℹ️ Empty/small chunk #${consecutiveEmptyChunks} (size: ${chunkSize} bytes, normal during startup)`)
            }
          }
        }
        
        // Task 2.1: Add detailed console logs for MediaRecorder state transitions
        mediaRecorder.onerror = (error) => {
          console.error('❌ MediaRecorder error event:', error)
          console.error('📊 MediaRecorder state on error:', {
            state: mediaRecorderRef.current?.state,
            mimeType: mediaRecorderRef.current?.mimeType,
            chunksSent: audioChunkCountRef.current,
            errorType: (error as any)?.error?.name,
            errorMessage: (error as any)?.error?.message
          })
          
          // Task 7.1: Check if error is related to microphone permissions
          const errorName = (error as any)?.error?.name || ''
          if (errorName.includes('NotAllowed') || errorName.includes('Permission')) {
            setError({
              type: 'microphone_permission',
              message: 'Microphone access denied',
              details: 'Please grant microphone permissions in your browser settings'
            })
          }
          
          // Try to recover by stopping and restarting
          if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
            try {
              mediaRecorderRef.current.stop()
            } catch (e) {
              console.error('❌ Error stopping MediaRecorder after error:', e)
            }
          }
        }
        
        mediaRecorder.onstart = () => {
          console.log('✅ MediaRecorder started - Audio recording active for captions')
          isRecorderActive = true
          console.log('📊 MediaRecorder state:', {
            state: mediaRecorder.state,
            mimeType: mediaRecorder.mimeType,
            audioBitsPerSecond: mediaRecorder.audioBitsPerSecond
          })
          // Task 2.1: Log audio track properties at start
          const track = localStream.getAudioTracks()[0]
          console.log('🎤 Audio track properties at start:', {
            readyState: track.readyState,
            enabled: track.enabled,
            muted: track.muted,
            label: track.label,
            settings: track.getSettings()
          })
        }
        
        mediaRecorder.onstop = () => {
          console.log('🛑 MediaRecorder stopped - Audio recording stopped for captions')
          console.log('📊 Recording session summary:', {
            totalChunksSent: audioChunkCountRef.current,
            chunksQueued: chunkQueueRef.current.length,
            finalState: mediaRecorderRef.current?.state,
            isRecorderActive
          })
          
          // Mark recorder as inactive
          isRecorderActive = false
          
          // Task 3.3: Check why MediaRecorder stopped
          const audioTrack = localStream?.getAudioTracks()[0]
          console.log('🔍 Audio track state on stop:', {
            hasStream: !!localStream,
            hasTrack: !!audioTrack,
            trackState: audioTrack?.readyState,
            trackEnabled: audioTrack?.enabled,
            trackMuted: audioTrack?.muted,
            enabled: enabled,
            isCleanup: isCleanupRef.current
          })
          
          // Task 3.3: Only restart if stopped unexpectedly (not during cleanup)
          if (isCleanupRef.current) {
            console.log('🛑 MediaRecorder stopped during cleanup - not restarting')
            return
          }
          
          // Task 3.3: Restart MediaRecorder only if it stopped unexpectedly
          if (enabled && localStream && audioTrack?.readyState === 'live') {
            console.warn('⚠️ MediaRecorder stopped unexpectedly. Checking conditions for restart...')
            
            // Task 3.3: Add proper state checks before restart attempts
            const shouldRestart = 
              enabled && 
              localStream && 
              audioTrack?.readyState === 'live' &&
              !isCleanupRef.current &&
              mediaRecorderRef.current?.state === 'inactive'
            
            if (!shouldRestart) {
              console.log('🛑 Conditions not met for MediaRecorder restart:', {
                enabled,
                hasStream: !!localStream,
                trackLive: audioTrack?.readyState === 'live',
                notCleanup: !isCleanupRef.current,
                recorderInactive: mediaRecorderRef.current?.state === 'inactive'
              })
              return
            }
            
            // Task 3.3: Wait for WebSocket to be ready before restarting
            setTimeout(() => {
              // Re-check conditions after delay
              if (!enabled || !localStream || isCleanupRef.current) {
                console.log('🛑 Conditions changed, aborting MediaRecorder restart')
                return
              }
              
              const currentWs = wsRef.current
              if (currentWs && currentWs.readyState === WebSocket.OPEN) {
                console.log('🔄 Restarting MediaRecorder (WebSocket is ready)...')
                isRecorderActive = true
                setupMediaRecorder()
              } else {
                console.log('⏳ WebSocket not ready, waiting before restarting MediaRecorder...')
                // Task 3.3: Wait for WebSocket reconnection before restarting MediaRecorder
                let checkCount = 0
                const maxChecks = 20 // 10 seconds max
                const checkInterval = setInterval(() => {
                  checkCount++
                  const ws = wsRef.current
                  
                  if (!enabled || !localStream || isCleanupRef.current) {
                    clearInterval(checkInterval)
                    console.log('🛑 Conditions changed, stopping WebSocket wait')
                    return
                  }
                  
                  if (ws && ws.readyState === WebSocket.OPEN) {
                    clearInterval(checkInterval)
                    console.log('🔄 WebSocket ready, restarting MediaRecorder...')
                    isRecorderActive = true
                    setupMediaRecorder()
                  } else if (checkCount >= maxChecks) {
                    clearInterval(checkInterval)
                    console.error('❌ WebSocket not ready after 10 seconds, giving up on MediaRecorder restart')
                  }
                }, 500)
              }
            }, 1500)
          } else {
            console.log('🛑 MediaRecorder stopped intentionally or conditions not met for restart')
          }
        }
        
        // Task 2.1: Add detailed console logs for MediaRecorder state transitions
        mediaRecorder.onpause = () => {
          console.warn('⏸️ MediaRecorder paused - this should not happen in continuous mode')
          console.warn('📊 MediaRecorder state on pause:', {
            state: mediaRecorder.state,
            chunksSent: audioChunkCountRef.current
          })
        }
        
        mediaRecorder.onresume = () => {
          console.log('▶️ MediaRecorder resumed')
          console.log('📊 MediaRecorder state on resume:', {
            state: mediaRecorder.state,
            chunksSent: audioChunkCountRef.current
          })
        }
        
        // Check state before starting
        if (mediaRecorder.state === 'inactive') {
          // Task 2.2: Ensure MediaRecorder uses appropriate timeslice (3000ms)
          // Start recording with 3-second timeslices
          // This gives Google Cloud STT more context to work with
          // Using timeslice ensures continuous recording with regular chunks
          try {
            // Use 3 seconds to avoid empty first chunks
            // This gives the audio track more time to start producing data
            const TIMESLICE_MS = 3000
            mediaRecorder.start(TIMESLICE_MS)
            console.log(`✅ MediaRecorder.start() called with ${TIMESLICE_MS}ms timeslice`)
            console.log('📊 MediaRecorder initial state:', {
              state: mediaRecorder.state,
              mimeType: mediaRecorder.mimeType,
              timeslice: TIMESLICE_MS
            })
            console.log('🎤 Audio track state at start:', {
              readyState: audioTrack.readyState,
              enabled: audioTrack.enabled,
              muted: audioTrack.muted,
              label: audioTrack.label,
              kind: audioTrack.kind
            })
            
            // Task 2.1: Add periodic state monitoring (every 5 seconds)
            const stateCheckInterval = setInterval(() => {
              if (mediaRecorderRef.current) {
                const state = mediaRecorderRef.current.state
                const track = localStream?.getAudioTracks()[0]
                
                console.log('🔄 Periodic state check:', {
                  mediaRecorderState: state,
                  chunksSent: audioChunkCountRef.current,
                  chunksQueued: chunkQueueRef.current.length,
                  audioTrackState: track?.readyState,
                  audioTrackEnabled: track?.enabled,
                  audioTrackMuted: track?.muted,
                  wsConnected: wsRef.current?.readyState === WebSocket.OPEN
                })
                
                if (state === 'inactive' || state === 'paused') {
                  console.warn(`⚠️ MediaRecorder state changed to: ${state}`)
                  if (state === 'inactive') {
                    clearInterval(stateCheckInterval)
                  }
                }
              } else {
                console.warn('⚠️ MediaRecorder reference lost during state check')
                clearInterval(stateCheckInterval)
              }
            }, 5000) // Check every 5 seconds
            
            // Store interval ref for cleanup
            ;(mediaRecorder as any)._stateCheckInterval = stateCheckInterval
          } catch (startError: any) {
            console.error('❌ Error starting MediaRecorder:', startError)
            console.error('📊 Error details:', {
              name: startError?.name,
              message: startError?.message,
              stack: startError?.stack
            })
            // Try without timeslice parameter as fallback
            try {
              mediaRecorder.start()
              console.log('✅ MediaRecorder started without timeslice (fallback)')
            } catch (fallbackError) {
              console.error('❌ Failed to start MediaRecorder even without timeslice:', fallbackError)
            }
          }
        } else {
          console.warn(`⚠️ MediaRecorder not in inactive state: ${mediaRecorder.state}`)
        }

      } catch (err: any) {
        console.error('Error setting up audio capture:', err)
        console.error('Error details:', {
          name: err?.name,
          message: err?.message,
          stack: err?.stack
        })
      }
    }

    // Store connect function in ref so it's accessible from retry button
    connectWebSocketRef.current = connectWebSocket
    
    // Task 3.1: Connect WebSocket first, MediaRecorder will start after connection
    // Use async IIFE to handle the async connectWebSocket function
    ;(async () => {
      const ws = await connectWebSocket()
      if (!ws) {
        console.error('❌ Failed to establish WebSocket connection - backend may not be running')
      }
    })()

    // Task 3.1: Cleanup function with proper resource management
    return () => {
      console.log('🧹 Cleaning up LiveCaptions component...')
      isCleanupRef.current = true
      
      // Clear health check interval
      if (healthCheckInterval) {
        clearInterval(healthCheckInterval)
      }
      
      // Clear all timeouts
      if (setupTimeoutRef.current) {
        clearTimeout(setupTimeoutRef.current)
        setupTimeoutRef.current = null
      }
      
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      
      // Task 3.1: Close WebSocket connection
      if (wsRef.current) {
        const ws = wsRef.current
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          console.log('🔌 Closing WebSocket connection...')
          ws.close()
        }
        wsRef.current = null
      }
      
      // Task 3.1: Stop and cleanup MediaRecorder
      try {
        if (mediaRecorderRef.current) {
          const recorder = mediaRecorderRef.current
          
          // Clear state check interval if it exists
          if ((recorder as any)._stateCheckInterval) {
            clearInterval((recorder as any)._stateCheckInterval)
          }
          
          // Stop recording if active
          if (recorder.state === 'recording' || recorder.state === 'paused') {
            console.log('🛑 Stopping MediaRecorder...')
            recorder.stop()
          }
          
          mediaRecorderRef.current = null
        }
      } catch (err) {
        console.error('Error cleaning up MediaRecorder:', err)
      }
      
      // Clear chunk queue and reset counters
      chunkQueueRef.current = []
      audioChunkCountRef.current = 0
      reconnectAttemptsRef.current = 0
      
      console.log('✅ LiveCaptions cleanup complete')
    }
  }, [enabled, localStream, consultationId, userType, wsUrl])

  if (!enabled) {
    return null
  }

  return (
    <div className="fixed bottom-24 left-1/2 transform -translate-x-1/2 w-full max-w-3xl px-4 z-40">
      <Card className="bg-black/80 backdrop-blur-md border-slate-700/50 p-4 rounded-lg shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Subtitles className="w-4 h-4 text-blue-400" />
            <span className="text-white text-sm font-medium">Live Captions</span>
            {/* Task 3.2: Connection status indicator */}
            {isConnected ? (
              <div className="flex items-center gap-1">
                <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                <span className="text-green-400 text-xs">Connected</span>
              </div>
            ) : (
              <div className="flex items-center gap-1">
                <div className="w-2 h-2 bg-yellow-400 rounded-full animate-pulse" />
                <span className="text-yellow-400 text-xs">Connecting...</span>
              </div>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggle}
            className="text-white hover:bg-slate-700"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* Captions Display */}
        {/* Task 6.3: Implement proper caption display logic */}
        <div className="space-y-2 max-h-32 overflow-y-auto scrollbar-thin scrollbar-thumb-slate-600 scrollbar-track-transparent">
          {captions.length === 0 ? (
            <div className="text-slate-400 text-sm text-center py-2">
              {isConnected ? 'Listening...' : 'Connecting...'}
            </div>
          ) : (
            captions.map((caption) => {
              // Task 6.3: Determine if this is the user's own caption
              const isOwnCaption = caption.speaker === userType
              
              // Task 6.3: Show original text for own speech, translated text for other speaker
              const displayText = isOwnCaption ? caption.original_text : caption.translated_text
              
              // Task 6.3: Show both texts when different (for other speaker)
              const showBothTexts = !isOwnCaption && 
                                   caption.original_text !== caption.translated_text &&
                                   caption.original_text.trim() !== '' &&
                                   caption.translated_text.trim() !== ''
              
              // Task 6.3: Add proper speaker labels (Requirement 5.3)
              const speakerLabel = isOwnCaption 
                ? 'You' 
                : (caption.speaker === 'doctor' ? 'Doctor' : 'Patient')
              
              // Task 6.3: Add proper speaker colors (Requirement 5.1, 5.2, 5.5)
              const speakerColor = caption.speaker === 'doctor' ? 'text-blue-400' : 'text-green-400'
              const borderColor = caption.speaker === 'doctor' ? 'border-blue-400' : 'border-green-400'
              const bgColor = isOwnCaption
                ? (caption.speaker === 'doctor' ? 'bg-blue-900/30' : 'bg-green-900/30')
                : 'bg-slate-800/30'
              
              return (
                <div
                  key={caption.id}
                  className={`p-2 rounded ${bgColor} border-l-2 ${borderColor}`}
                >
                  <div className="flex items-start gap-2">
                    {/* Task 6.3: Speaker label with proper color (Requirement 5.1, 5.2, 5.4) */}
                    <span className={`text-xs font-semibold ${speakerColor} whitespace-nowrap`}>
                      {caption.speaker === 'doctor' ? '👨‍⚕️' : '🧑'} {speakerLabel}:
                    </span>
                    <div className="flex-1">
                      {/* Task 6.3: Display main text (original for self, translated for others) */}
                      {/* Requirement 4.1, 4.2: Display captions with speaker identification */}
                      <p className="text-white text-sm leading-relaxed">
                        {displayText}
                      </p>
                      {/* Task 6.3: Display both texts when different (Requirement 4.3) */}
                      {/* Show original text in smaller font for other speaker's captions */}
                      {showBothTexts && (
                        <p className="text-slate-400 text-xs mt-1 italic">
                          Original: {caption.original_text}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )
            })
          )}
          <div ref={captionsEndRef} />
        </div>

        {/* Task 3.2: Enhanced status with reconnection info */}
        {!isConnected && !error && (
          <div className="mt-2 text-yellow-400 text-xs text-center">
            {reconnectAttemptsRef.current > 0 
              ? `Reconnecting to caption service (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})...`
              : 'Connecting to caption service...'}
          </div>
        )}

        {/* Task 7: Comprehensive error handling UI */}
        {error && (
          <div className="mt-3 p-3 bg-red-900/30 border border-red-500/50 rounded-lg">
            <div className="flex items-start gap-2">
              <span className="text-red-400 text-lg">⚠️</span>
              <div className="flex-1">
                <p className="text-red-400 text-sm font-semibold">{error.message}</p>
                {error.details && (
                  <p className="text-red-300 text-xs mt-1">{error.details}</p>
                )}
                
                {/* Task 7.1: Microphone permission error handling */}
                {error.type === 'microphone_permission' && (
                  <div className="mt-2 space-y-2">
                    <p className="text-slate-300 text-xs">
                      To enable captions, you need to grant microphone access:
                    </p>
                    <ol className="text-slate-300 text-xs list-decimal list-inside space-y-1 ml-2">
                      <li>Click the camera/microphone icon in your browser's address bar</li>
                      <li>Select "Always allow" for microphone access</li>
                      <li>Refresh the page and try again</li>
                    </ol>
                    <div className="flex gap-2 mt-2">
                      {/* Task 7.1: Retry button */}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setError(null)
                          // Trigger re-setup by toggling
                          window.location.reload()
                        }}
                        className="text-xs bg-red-900/50 border-red-500/50 text-red-200 hover:bg-red-900/70"
                      >
                        Retry
                      </Button>
                      {/* Task 7.1: Link to browser settings */}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          // Open browser-specific settings help
                          const isChrome = /Chrome/.test(navigator.userAgent)
                          const isEdge = /Edg/.test(navigator.userAgent)
                          const isFirefox = /Firefox/.test(navigator.userAgent)
                          
                          let url = 'https://support.google.com/chrome/answer/2693767'
                          if (isEdge) {
                            url = 'https://support.microsoft.com/en-us/microsoft-edge/camera-and-microphone-permissions-in-microsoft-edge-dc8c9d8f-8e0e-4c1e-9c3e-0e3e0e3e0e3e'
                          } else if (isFirefox) {
                            url = 'https://support.mozilla.org/en-US/kb/how-manage-your-camera-and-microphone-permissions'
                          }
                          
                          window.open(url, '_blank')
                        }}
                        className="text-xs bg-red-900/50 border-red-500/50 text-red-200 hover:bg-red-900/70"
                      >
                        Browser Settings Help
                      </Button>
                    </div>
                  </div>
                )}

                {/* Task 7.2: Connection error handling */}
                {error.type === 'connection_error' && (
                  <div className="mt-2 space-y-2">
                    <p className="text-slate-300 text-xs font-semibold">Troubleshooting steps:</p>
                    <ol className="text-slate-300 text-xs list-decimal list-inside space-y-1 ml-2">
                      <li>
                        <strong>Start the backend server:</strong>
                        <div className="ml-4 mt-1 p-2 bg-slate-900/50 rounded font-mono text-xs">
                          cd backend<br />
                          python run.py
                        </div>
                      </li>
                      <li>Verify backend is running at: <code className="bg-slate-900/50 px-1 rounded">{backendUrl}</code></li>
                      <li>Check backend health: <a href={`${backendUrl}/health`} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">{backendUrl}/health</a></li>
                      <li>Check if firewall is blocking the connection</li>
                      <li>Try refreshing the page after starting the backend</li>
                    </ol>
                    {/* Task 7.2: Retry mechanism */}
                    <div className="flex gap-2 mt-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={async () => {
                          setError(null)
                          reconnectAttemptsRef.current = 0
                          // Close existing connection if any
                          if (wsRef.current) {
                            wsRef.current.close()
                            wsRef.current = null
                          }
                          // Wait a bit then reconnect using the stored function
                          setTimeout(async () => {
                            if (connectWebSocketRef.current) {
                              await connectWebSocketRef.current()
                            }
                          }, 1000)
                        }}
                        className="text-xs bg-red-900/50 border-red-500/50 text-red-200 hover:bg-red-900/70"
                      >
                        Retry Connection
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          window.open(`${backendUrl}/docs`, '_blank')
                        }}
                        className="text-xs bg-blue-900/50 border-blue-500/50 text-blue-200 hover:bg-blue-900/70"
                      >
                        Open API Docs
                      </Button>
                    </div>
                  </div>
                )}

                {/* Task 7.3: STT failure error feedback */}
                {error.type === 'stt_failure' && (
                  <div className="mt-2 space-y-2">
                    <p className="text-slate-300 text-xs">
                      The speech recognition service is having trouble understanding the audio.
                    </p>
                    <p className="text-slate-300 text-xs font-semibold">Try these tips:</p>
                    <ul className="text-slate-300 text-xs list-disc list-inside space-y-1 ml-2">
                      <li>Speak more clearly and at a moderate pace</li>
                      <li>Reduce background noise</li>
                      <li>Check your microphone quality</li>
                      <li>Move closer to your microphone</li>
                    </ul>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setError(null)
                        setSttFailureCount(0)
                      }}
                      className="text-xs bg-red-900/50 border-red-500/50 text-red-200 hover:bg-red-900/70 mt-2"
                    >
                      Dismiss
                    </Button>
                  </div>
                )}

                {/* Task 7.3: API quota exceeded error */}
                {error.type === 'api_quota_exceeded' && (
                  <div className="mt-2 space-y-2">
                    <p className="text-slate-300 text-xs">
                      The caption service has reached its usage limit for today.
                    </p>
                    <p className="text-slate-300 text-xs">
                      Please try again later or contact your administrator.
                    </p>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setError(null)
                      }}
                      className="text-xs bg-red-900/50 border-red-500/50 text-red-200 hover:bg-red-900/70 mt-2"
                    >
                      Dismiss
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
