'use client'

/**
 * Web Speech API Fallback Component
 * 
 * This is a simpler, browser-native alternative that runs entirely in the frontend.
 * Use this as a fallback if the backend STT service has issues during your demo.
 * 
 * Pros:
 * - 100% free, no API keys needed
 * - Works offline (after initial setup)
 * - Very fast (no network latency)
 * 
 * Cons:
 * - Only works in Chrome/Edge (not Firefox/Safari)
 * - No translation (would need to add separately)
 * - No medical lexicon lookup
 * - Lower accuracy than Google Cloud STT
 */

import { useEffect, useRef, useState } from 'react'
import { Card } from '@/components/ui/card'
import { Subtitles, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Caption {
  speaker: 'doctor' | 'patient'
  text: string
  timestamp: number
  id: string
}

interface LiveCaptionsWebSpeechProps {
  consultationId: string
  userType: 'doctor' | 'patient'
  localStream: MediaStream | null
  enabled: boolean
  onToggle: () => void
}

export default function LiveCaptionsWebSpeech({
  consultationId,
  userType,
  localStream,
  enabled,
  onToggle
}: LiveCaptionsWebSpeechProps) {
  const [captions, setCaptions] = useState<Caption[]>([])
  const [isListening, setIsListening] = useState(false)
  const [isSupported, setIsSupported] = useState(false)
  const recognitionRef = useRef<any>(null)
  const captionsEndRef = useRef<HTMLDivElement>(null)

  // Check if Web Speech API is supported
  useEffect(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    setIsSupported(!!SpeechRecognition)
    
    if (!SpeechRecognition) {
      console.warn('Web Speech API not supported in this browser. Use Chrome or Edge.')
    }
  }, [])

  // Auto-scroll to latest caption
  useEffect(() => {
    if (captionsEndRef.current) {
      captionsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [captions])

  // Setup speech recognition
  useEffect(() => {
    if (!enabled || !localStream || !isSupported) {
      // Stop recognition if disabled
      if (recognitionRef.current) {
        recognitionRef.current.stop()
        recognitionRef.current = null
        setIsListening(false)
      }
      return
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SpeechRecognition) {
      console.error('Web Speech API not available')
      return
    }

    const recognition = new SpeechRecognition()
    recognitionRef.current = recognition

    // Configure recognition
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = userType === 'patient' ? 'hi-IN' : 'en-IN' // Hindi for patient, English for doctor

    recognition.onstart = () => {
      console.log('✅ Web Speech API started')
      setIsListening(true)
    }

    recognition.onresult = (event: any) => {
      let interimTranscript = ''
      let finalTranscript = ''

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript
        if (event.results[i].isFinal) {
          finalTranscript += transcript + ' '
        } else {
          interimTranscript += transcript
        }
      }

      // Add final transcript as caption
      if (finalTranscript.trim()) {
        const newCaption: Caption = {
          speaker: userType,
          text: finalTranscript.trim(),
          timestamp: Date.now(),
          id: `${userType}-${Date.now()}-${Math.random()}`
        }
        
        setCaptions(prev => [...prev.slice(-9), newCaption]) // Keep last 10 captions
        console.log('📝 Caption:', newCaption.text)
      }
    }

    recognition.onerror = (event: any) => {
      console.error('Speech recognition error:', event.error)
      if (event.error === 'no-speech') {
        // This is normal, just restart
        try {
          recognition.start()
        } catch (e) {
          // Already started, ignore
        }
      } else if (event.error === 'audio-capture') {
        console.error('No microphone found')
        setIsListening(false)
      } else if (event.error === 'not-allowed') {
        console.error('Microphone permission denied')
        setIsListening(false)
      }
    }

    recognition.onend = () => {
      console.log('Speech recognition ended')
      setIsListening(false)
      
      // Auto-restart if still enabled
      if (enabled && localStream) {
        try {
          recognition.start()
        } catch (e) {
          console.error('Failed to restart recognition:', e)
        }
      }
    }

    // Start recognition
    try {
      recognition.start()
    } catch (e) {
      console.error('Failed to start recognition:', e)
    }

    // Cleanup
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop()
        recognitionRef.current = null
      }
      setIsListening(false)
    }
  }, [enabled, localStream, isSupported, userType])

  if (!isSupported) {
    return (
      <Card className="p-4 bg-yellow-50 border-yellow-200">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-yellow-800">
              ⚠️ Web Speech API not supported in this browser.
            </p>
            <p className="text-xs text-yellow-600 mt-1">
              Please use Chrome or Edge for Web Speech API, or use the backend STT service.
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onToggle}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </Card>
    )
  }

  return (
    <Card className="p-4 bg-white border border-gray-200 shadow-lg">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Subtitles className="h-5 w-5 text-blue-600" />
          <h3 className="font-semibold text-gray-800">Live Captions (Web Speech API)</h3>
          {isListening && (
            <span className="px-2 py-1 text-xs bg-green-100 text-green-800 rounded-full">
              ● Listening
            </span>
          )}
        </div>
        <Button variant="ghost" size="sm" onClick={onToggle}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="max-h-48 overflow-y-auto space-y-2">
        {captions.length === 0 ? (
          <p className="text-sm text-gray-500 text-center py-4">
            {isListening ? 'Listening...' : 'Starting...'}
          </p>
        ) : (
          captions.map((caption) => (
            <div
              key={caption.id}
              className={`p-2 rounded-lg ${
                caption.speaker === 'doctor'
                  ? 'bg-blue-50 border-l-4 border-blue-500'
                  : 'bg-green-50 border-l-4 border-green-500'
              }`}
            >
              <div className="text-xs font-semibold text-gray-600 mb-1">
                {caption.speaker === 'doctor' ? '👨‍⚕️ Doctor' : '👤 Patient'}
              </div>
              <div className="text-sm text-gray-800">{caption.text}</div>
            </div>
          ))
        )}
        <div ref={captionsEndRef} />
      </div>

      <div className="mt-3 text-xs text-gray-500">
        <p>⚡ Using browser-native Web Speech API (Chrome/Edge only)</p>
      </div>
    </Card>
  )
}


