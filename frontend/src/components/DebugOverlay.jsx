import React from 'react'

export default function DebugOverlay({ debugHistory }) {
  const latest = debugHistory[debugHistory.length - 1]
  if (!latest) return null

  return (
    <div className="fixed bottom-16 right-6 w-80 bg-forge-panel border border-orange-500/30 rounded-xl p-4 shadow-2xl animate-slide-in z-50">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-2 h-2 bg-orange-500 rounded-full animate-pulse" />
        <span className="text-xs font-bold text-orange-400">
          Self-Debug Active
        </span>
        <span className="text-xs text-forge-muted ml-auto">
          Attempt {debugHistory.length}/3
        </span>
      </div>

      <div className="space-y-2 text-xs">
        <div>
          <span className="text-forge-muted">Category: </span>
          <span className="text-yellow-300 font-mono">{latest.category}</span>
        </div>
        <div>
          <span className="text-forge-muted">Root Cause: </span>
          <span className="text-forge-text">{latest.root_cause}</span>
        </div>
        <div>
          <span className="text-forge-muted">Fix: </span>
          <span className="text-forge-success">{latest.fix}</span>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 text-[10px] text-forge-muted">
        <div className="w-full h-1 bg-forge-border rounded-full overflow-hidden">
          <div
            className="h-full bg-orange-500 rounded-full transition-all duration-500"
            style={{ width: `${(debugHistory.length / 3) * 100}%` }}
          />
        </div>
      </div>
    </div>
  )
}
