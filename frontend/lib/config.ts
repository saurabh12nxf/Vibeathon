/**
 * Production configuration helper for Arogya-AI Frontend
 */

export interface AppConfig {
  backendUrl: string
  wsUrl: string
  supabase: {
    url: string
    anonKey: string
  }
  webrtc: RTCConfiguration
  mediaConstraints: MediaStreamConstraints
  isProduction: boolean
}

export const getConfig = (): AppConfig => {
  // Backend URL from environment or default
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
  
  // Supabase configuration
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''
  
  // WebSocket URL (convert HTTP/HTTPS to WS/WSS)
  const wsUrl = backendUrl.replace('https://', 'wss://').replace('http://', 'ws://')
  
  // Check if we're in production
  const isProduction = process.env.NODE_ENV === 'production'
  
  return {
    backendUrl,
    wsUrl,
    supabase: {
      url: supabaseUrl,
      anonKey: supabaseAnonKey,
    },
    // WebRTC configuration optimized for production
    webrtc: {
      iceServers: [
        // Google STUN servers (free and reliable)
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        { urls: 'stun:stun2.l.google.com:19302' },
        { urls: 'stun:stun3.l.google.com:19302' },
        
        // Additional STUN servers for better connectivity
        { urls: 'stun:stun.services.mozilla.com' },
        { urls: 'stun:stun.stunprotocol.org:3478' },
      ],
      iceCandidatePoolSize: 10,
      bundlePolicy: 'balanced',
      rtcpMuxPolicy: 'require',
    },
    // Media constraints optimized for production
    mediaConstraints: {
      video: {
        width: { ideal: 1280, max: 1920 },
        height: { ideal: 720, max: 1080 },
        frameRate: { ideal: 30, max: 60 },
        facingMode: 'user',
        aspectRatio: { ideal: 16/9 },
      },
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        sampleRate: 48000,
        channelCount: 1,
      }
    },
    isProduction,
  }
}

// Helper functions
export const isProduction = () => process.env.NODE_ENV === 'production'

export const getWebSocketUrl = (service: 'captions' | 'signaling', consultationId: string, userType: string) => {
  const { wsUrl } = getConfig()
  return `${wsUrl}/ws/${service}/${consultationId}/${userType}`
}

export const getApiUrl = (endpoint: string) => {
  const { backendUrl } = getConfig()
  return `${backendUrl}/api${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`
}

// Helper to check if HTTPS is available (required for WebRTC)
export const isHTTPS = () => {
  if (typeof window === 'undefined') return false
  return window.location.protocol === 'https:' || window.location.hostname === 'localhost'
}

// Helper function to show user-friendly error messages
export const getMediaErrorMessage = (error: DOMException) => {
  switch (error.name) {
    case 'NotAllowedError':
      return {
        title: 'Camera/Microphone Access Denied',
        message: 'Please allow camera and microphone access for video calls to work. Click the camera icon in your browser\'s address bar and select "Allow".',
        action: 'Grant Permissions'
      }
    case 'NotFoundError':
      return {
        title: 'No Camera or Microphone Found',
        message: 'Please connect your camera and microphone, then refresh the page.',
        action: 'Refresh Page'
      }
    case 'NotReadableError':
      return {
        title: 'Camera/Microphone Busy',
        message: 'Your camera or microphone is being used by another application. Please close other apps and try again.',
        action: 'Try Again'
      }
    case 'OverconstrainedError':
      return {
        title: 'Camera/Microphone Not Compatible',
        message: 'Your camera or microphone doesn\'t support the required settings. We\'ll try with basic settings.',
        action: 'Use Basic Settings'
      }
    case 'SecurityError':
      return {
        title: 'Security Error',
        message: 'Camera and microphone access requires HTTPS. Please ensure you\'re using a secure connection.',
        action: 'Check Connection'
      }
    default:
      return {
        title: 'Media Access Error',
        message: `An error occurred: ${error.message}. Please check your camera and microphone settings.`,
        action: 'Try Again'
      }
  }
}

// Configuration validation
export const validateConfig = () => {
  const config = getConfig()
  const issues: string[] = []
  
  if (!config.backendUrl || config.backendUrl === 'http://localhost:8000') {
    issues.push('Backend URL not configured for production')
  }
  
  if (!config.supabase.url) {
    issues.push('Supabase URL not configured')
  }
  
  if (!config.supabase.anonKey) {
    issues.push('Supabase anonymous key not configured')
  }
  
  if (config.isProduction && !isHTTPS()) {
    issues.push('HTTPS required for production WebRTC')
  }
  
  return {
    isValid: issues.length === 0,
    issues,
    config
  }
}

// Debug helper
export const logConfig = () => {
  if (!isProduction()) {
    const validation = validateConfig()
    console.log('🔍 App Configuration:', {
      ...validation.config,
      validation: validation.isValid ? '✅ Valid' : `❌ Issues: ${validation.issues.join(', ')}`
    })
  }
}