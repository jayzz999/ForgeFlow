import React, { useState, useEffect } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import ChatPanel from './components/ChatPanel'
import WorkflowCanvas from './components/WorkflowCanvas'
import CodePanel from './components/CodePanel'
import StatusBar from './components/StatusBar'
import ApiDiscoveryBadge from './components/ApiDiscoveryBadge'
import DebugOverlay from './components/DebugOverlay'

// ── Celebration Overlay ──────────────────────────────────────
function CelebrationOverlay({ show }) {
  if (!show) return null

  const confettiColors = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#0ea5e9', '#8b5cf6', '#ec4899']

  return (
    <div className="fixed inset-0 z-50 pointer-events-none flex items-center justify-center">
      {/* Confetti particles */}
      <div className="confetti-container">
        {Array.from({ length: 60 }).map((_, i) => (
          <div
            key={i}
            className="confetti-piece"
            style={{
              left: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 3}s`,
              animationDuration: `${2 + Math.random() * 2}s`,
              backgroundColor: confettiColors[i % confettiColors.length],
              width: `${6 + Math.random() * 8}px`,
              height: `${6 + Math.random() * 8}px`,
              borderRadius: Math.random() > 0.5 ? '50%' : '2px',
            }}
          />
        ))}
      </div>
      {/* Center badge */}
      <div className="animate-celebration-badge glass border-2 border-forge-success rounded-2xl p-8 text-center shadow-2xl shadow-green-500/20 pointer-events-auto">
        <div className="text-6xl mb-4">🚀</div>
        <h2 className="text-2xl font-bold text-forge-success mb-2">Workflow Deployed!</h2>
        <p className="text-forge-muted text-sm">Saved as executable project</p>
      </div>
    </div>
  )
}

export default function App() {
  const {
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
  } = useWebSocket()

  const [showCode, setShowCode] = useState(true)
  const [deployedWorkflowId, setDeployedWorkflowId] = useState(null)

  // Celebration state
  const [showCelebration, setShowCelebration] = useState(false)
  useEffect(() => {
    if (phase === 'deployed') {
      setShowCelebration(true)
      const timer = setTimeout(() => setShowCelebration(false), 4000)
      return () => clearTimeout(timer)
    }
  }, [phase])

  // Capture workflow ID from deployed event
  useEffect(() => {
    const deployEvent = events.find(e => e.event_type === 'workflow.deployed')
    if (deployEvent?.data?.workflow_id) {
      setDeployedWorkflowId(deployEvent.data.workflow_id)
    }
  }, [events])

  const handleDownload = () => {
    if (deployedWorkflowId) {
      window.open(`/api/workflows/${deployedWorkflowId}/download`, '_blank')
    }
  }

  return (
    <div className="h-screen flex flex-col bg-forge-bg text-forge-text overflow-hidden">
      {/* Celebration */}
      <CelebrationOverlay show={showCelebration} />

      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-forge-border glass">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center font-bold text-sm shadow-lg shadow-indigo-500/20">
            FF
          </div>
          <h1 className="text-lg font-semibold tracking-tight">ForgeFlow</h1>
          <span className="text-xs text-forge-muted px-2 py-0.5 rounded-full bg-forge-border/50 border border-forge-border">
            AI Workflow Generator
          </span>
          <span className="text-[10px] text-indigo-400/60 hidden sm:inline">
            Built for Deriv AI Talent Sprint
          </span>
        </div>
        <div className="flex items-center gap-3">
          {/* Download button — only when deployed */}
          {phase === 'deployed' && deployedWorkflowId && (
            <button
              onClick={handleDownload}
              className="text-xs px-3 py-1.5 rounded-lg bg-green-500/20 hover:bg-green-500/30 border border-green-500/30 text-green-400 transition-colors flex items-center gap-1.5"
            >
              <span>📦</span> Download Project
            </button>
          )}
          <div className={`flex items-center gap-2 text-xs ${connected ? 'text-forge-success' : 'text-forge-error'}`}>
            <div className={`w-2 h-2 rounded-full ${connected ? 'bg-forge-success animate-pulse' : 'bg-forge-error'}`} />
            {connected ? 'Connected' : 'Disconnected'}
          </div>
          <button
            onClick={() => setShowCode(!showCode)}
            className="text-xs px-3 py-1.5 rounded-lg bg-forge-border/50 hover:bg-indigo-500/20 border border-forge-border transition-colors"
          >
            {showCode ? 'Hide Code' : 'Show Code'}
          </button>
        </div>
      </header>

      {/* API Discovery Badges */}
      {discoveredApis.length > 0 && (
        <div className="px-6 py-2 border-b border-forge-border glass flex items-center gap-2 overflow-x-auto">
          <span className="text-xs text-forge-muted shrink-0">APIs Discovered:</span>
          {discoveredApis.map((api, i) => (
            <ApiDiscoveryBadge key={i} api={api} />
          ))}
        </div>
      )}

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat Panel - Left */}
        <div className="w-[400px] min-w-[350px] border-r border-forge-border flex flex-col">
          <ChatPanel
            events={events}
            phase={phase}
            onSend={sendMessage}
            onModify={sendModification}
            onDemo={sendDemo}
            dag={dag}
            clarification={clarification}
            onClarify={sendClarification}
            onSkipClarification={skipClarification}
            onReset={resetState}
          />
        </div>

        {/* Right Panel - Canvas + Code */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Workflow Canvas */}
          <div className={`${showCode ? 'h-1/2' : 'flex-1'} border-b border-forge-border`}>
            <WorkflowCanvas
              dag={dag}
              dagSteps={dagSteps}
              phase={phase}
              nodeStatuses={nodeStatuses}
            />
          </div>

          {/* Code Panel */}
          {showCode && (
            <div className="h-1/2 overflow-hidden">
              <CodePanel code={code} debugHistory={debugHistory} />
            </div>
          )}
        </div>
      </div>

      {/* Debug Overlay */}
      {debugHistory.length > 0 && phase === 'testing' && (
        <DebugOverlay debugHistory={debugHistory} />
      )}

      {/* Status Bar */}
      <StatusBar
        phase={phase}
        discoveredApis={discoveredApis}
        debugHistory={debugHistory}
        events={events}
      />
    </div>
  )
}
