import { useState, useEffect, useCallback, useRef } from 'react'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'
const MAX_RECONNECT_ATTEMPTS = 5
const PIPELINE_TIMEOUT_MS = 180000 // 3 min timeout — pipeline should complete or clarify by then

export function useWebSocket() {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const [dag, setDag] = useState(null)
  const [code, setCode] = useState('')
  const [phase, setPhase] = useState('idle')
  const [discoveredApis, setDiscoveredApis] = useState([])
  const [debugHistory, setDebugHistory] = useState([])
  // Task 1: Incremental DAG steps
  const [dagSteps, setDagSteps] = useState([])
  // Task 2: Node statuses for visual drama
  const [nodeStatuses, setNodeStatuses] = useState({})
  // Clarification state
  const [clarification, setClarification] = useState(null) // {questions, currentPlan, originalRequest}
  const wsRef = useRef(null)
  const clientId = useRef(`client_${Date.now()}`)
  const reconnectAttempts = useRef(0)
  const reconnectTimeout = useRef(null)
  const intentionalClose = useRef(false)
  const pipelineTimeout = useRef(null)

  // Clear pipeline timeout
  const clearPipelineTimeout = useCallback(() => {
    if (pipelineTimeout.current) {
      clearTimeout(pipelineTimeout.current)
      pipelineTimeout.current = null
    }
  }, [])

  // Start pipeline timeout — auto-reset to idle if no events arrive
  const startPipelineTimeout = useCallback(() => {
    clearPipelineTimeout()
    pipelineTimeout.current = setTimeout(() => {
      setPhase(prev => {
        // Only reset if still in a working state
        if (prev !== 'idle' && prev !== 'deployed' && prev !== 'failed' && prev !== 'clarification') {
          console.warn('[WS] Pipeline timeout — resetting to idle')
          return 'failed'
        }
        return prev
      })
      setEvents(prev => [...prev, {
        event_type: 'timeout',
        message: '⚠️ Pipeline timed out. Please try again.',
        phase: 'failed',
        timestamp: new Date().toISOString(),
      }])
    }, PIPELINE_TIMEOUT_MS)
  }, [clearPipelineTimeout])

  const handleEvent = useCallback((event) => {
    setEvents(prev => [...prev, event])

    // Reset timeout on every event (pipeline is still alive)
    startPipelineTimeout()

    const { event_type, data } = event

    // Update phase from event
    if (event.phase) {
      setPhase(event.phase)
    }

    // ── Clarification handling ──
    if (event.type === 'clarification_needed' || event_type === 'conversation.clarification_needed') {
      setClarification({
        questions: event.questions || data?.questions || [],
        currentPlan: event.current_plan || data?.current_plan || [],
        originalRequest: event.original_request || '',
        confidence: data?.confidence || 0,
        assumedDefaults: data?.assumed_defaults || [],
      })
      setPhase('clarification')
      clearPipelineTimeout() // Don't timeout during clarification — user is thinking
      return
    }

    // Track discovered APIs
    if (event_type === 'api.discovered' && data) {
      setDiscoveredApis(prev => [...prev, data])
    }

    // ── Task 1: Incremental DAG building ──
    if (event_type === 'dag.step_added' && data?.step) {
      setDagSteps(prev => [...prev, data.step])
    }

    // Track full DAG (final)
    if (event_type === 'dag.planned' && data?.steps) {
      setDag(data)
      setDagSteps([]) // Clear incremental, use final
    }

    // Track code — use full_code if available
    if (event_type === 'code.generated' && data) {
      setCode(data.full_code || data.preview || '')
    }

    // Track debug history
    if (event_type === 'debug.diagnosed' && data) {
      setDebugHistory(prev => [...prev, data])
    }

    // ── Task 2: Node status changes ──
    if (event_type === 'node.status_changed' && data) {
      if (data.node_id === 'all') {
        setNodeStatuses(prev => {
          const updated = { ...prev }
          Object.keys(updated).forEach(k => updated[k] = data.status)
          return updated
        })
      } else {
        setNodeStatuses(prev => ({ ...prev, [data.node_id]: data.status }))
      }
    }

    // ── Task 7: Modification complete ──
    if (event_type === 'modify.complete' && data) {
      if (data.modified_code) setCode(data.modified_code)
      if (data.affected_nodes) {
        setNodeStatuses(prev => {
          const updated = { ...prev }
          data.affected_nodes.forEach(id => updated[id] = 'modified')
          return updated
        })
        // Clear modified status after 2s
        setTimeout(() => {
          setNodeStatuses(prev => {
            const updated = { ...prev }
            Object.keys(updated).forEach(k => {
              if (updated[k] === 'modified') updated[k] = 'success'
            })
            return updated
          })
        }, 2000)
      }
    }

    // Final result
    if (event.type === 'forge_complete') {
      if (event.dag) setDag(event.dag)
      if (event.code) setCode(event.code)
      setPhase(event.phase || 'deployed')
      clearPipelineTimeout() // Pipeline done
    }
  }, [startPipelineTimeout, clearPipelineTimeout])

  // ── WebSocket connection with auto-reconnect ──
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(`${WS_URL}/ws/${clientId.current}`)

    ws.onopen = () => {
      setConnected(true)
      reconnectAttempts.current = 0
      console.log('[WS] Connected')
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      handleEvent(data)
    }

    ws.onclose = () => {
      setConnected(false)
      console.log('[WS] Disconnected')

      // If we were in a working state, reset to failed so UI isn't frozen
      setPhase(prev => {
        if (prev !== 'idle' && prev !== 'deployed' && prev !== 'failed' && prev !== 'clarification') {
          console.warn('[WS] Connection lost during pipeline — resetting phase')
          return 'failed'
        }
        return prev
      })

      // Auto-reconnect with exponential backoff
      if (!intentionalClose.current && reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 8000)
        console.log(`[WS] Reconnecting in ${delay}ms (attempt ${reconnectAttempts.current + 1}/${MAX_RECONNECT_ATTEMPTS})`)
        reconnectTimeout.current = setTimeout(() => {
          reconnectAttempts.current += 1
          connect()
        }, delay)
      }
    }

    ws.onerror = (err) => {
      console.error('[WS] Error:', err)
    }

    wsRef.current = ws
  }, [handleEvent])

  useEffect(() => {
    connect()
    return () => {
      intentionalClose.current = true
      clearPipelineTimeout()
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current)
      wsRef.current?.close()
    }
  }, [connect, clearPipelineTimeout])

  const sendMessage = useCallback((message) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'forge',
        message,
      }))
      setPhase('collecting')
      setEvents([])
      setDiscoveredApis([])
      setDebugHistory([])
      setDag(null)
      setCode('')
      setDagSteps([])
      setNodeStatuses({})
      setClarification(null)
      startPipelineTimeout()
    }
  }, [startPipelineTimeout])

  // Send clarification response — user answered the questions
  const sendClarification = useCallback((answer, originalRequest) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'clarify',
        message: answer,
        original_request: originalRequest,
      }))
      setPhase('collecting')
      setClarification(null) // Clear clarification UI
      startPipelineTimeout()
    }
  }, [startPipelineTimeout])

  // Skip clarification — proceed with defaults
  const skipClarification = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN && clarification) {
      // Re-send as forge with the original request — pipeline will proceed with assumed defaults
      wsRef.current.send(JSON.stringify({
        type: 'clarify',
        message: 'Proceed with the defaults you suggested.',
        original_request: clarification.originalRequest,
      }))
      setPhase('collecting')
      setClarification(null)
      startPipelineTimeout()
    }
  }, [clarification, startPipelineTimeout])

  // Send demo mode request (replays cached events)
  const sendDemo = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'forge_demo' }))
      setPhase('collecting')
      setEvents([])
      setDiscoveredApis([])
      setDebugHistory([])
      setDag(null)
      setCode('')
      setDagSteps([])
      setNodeStatuses({})
      setClarification(null)
      startPipelineTimeout()
    }
  }, [startPipelineTimeout])

  // ── Task 7: Send modification ──
  const sendModification = useCallback((message) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'modify',
        message,
        dag: dag,
        code: code,
      }))
      setPhase('modifying')
      startPipelineTimeout()
    }
  }, [dag, code, startPipelineTimeout])

  // Manual reset — escape hatch for stuck states
  const resetState = useCallback(() => {
    setPhase('idle')
    setEvents([])
    setDiscoveredApis([])
    setDebugHistory([])
    setDag(null)
    setCode('')
    setDagSteps([])
    setNodeStatuses({})
    setClarification(null)
    clearPipelineTimeout()
  }, [clearPipelineTimeout])

  return {
    connected,
    events,
    dag,
    code,
    phase,
    discoveredApis,
    debugHistory,
    dagSteps,
    nodeStatuses,
    clarification,
    sendMessage,
    sendClarification,
    skipClarification,
    sendModification,
    sendDemo,
    resetState,
  }
}
