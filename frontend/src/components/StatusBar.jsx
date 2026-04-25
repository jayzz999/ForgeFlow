import React from 'react'

const PHASE_CONFIG = {
  idle: { label: 'Ready', color: 'text-forge-muted', icon: '⏸️' },
  collecting: { label: 'Analyzing Requirements', color: 'text-blue-400', icon: '💬' },
  clarification: { label: 'Awaiting Your Input', color: 'text-amber-400', icon: '❓' },
  planning: { label: 'Planning Workflow', color: 'text-purple-400', icon: '🔨' },
  generating: { label: 'Generating Code', color: 'text-indigo-400', icon: '💻' },
  testing: { label: 'Testing in Sandbox', color: 'text-yellow-400', icon: '🧪' },
  debugging: { label: 'Self-Debugging', color: 'text-orange-400', icon: '🔧' },
  deploying: { label: 'Deploying', color: 'text-green-400', icon: '🚀' },
  deployed: { label: 'Deployed', color: 'text-forge-success', icon: '✅' },
  failed: { label: 'Issues Found', color: 'text-forge-error', icon: '⚠️' },
}

export default function StatusBar({ phase, discoveredApis, debugHistory, events }) {
  const config = PHASE_CONFIG[phase] || PHASE_CONFIG.idle

  return (
    <div className="flex items-center gap-6 px-6 py-2 border-t border-forge-border bg-forge-panel text-xs">
      {/* Phase indicator */}
      <div className={`flex items-center gap-2 ${config.color}`}>
        <span>{config.icon}</span>
        <span className="font-medium">{config.label}</span>
      </div>

      <div className="w-px h-4 bg-forge-border" />

      {/* APIs discovered */}
      <div className="flex items-center gap-1.5 text-forge-muted">
        <span>🔍</span>
        <span>APIs: {discoveredApis.length}</span>
      </div>

      {/* Debug attempts */}
      {debugHistory.length > 0 && (
        <>
          <div className="w-px h-4 bg-forge-border" />
          <div className="flex items-center gap-1.5 text-orange-400">
            <span>🔧</span>
            <span>Debug: {debugHistory.length}/3</span>
          </div>
        </>
      )}

      {/* Events count */}
      <div className="w-px h-4 bg-forge-border" />
      <div className="flex items-center gap-1.5 text-forge-muted">
        <span>📊</span>
        <span>Events: {events.length}</span>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Branding */}
      <div className="text-forge-muted">
        ForgeFlow v1.0 — AI Talent Sprint
      </div>
    </div>
  )
}
