import React from 'react'
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Cpu,
  Database,
  Hammer,
  HelpCircle,
  MessageSquareText,
  PackageCheck,
  Search,
  Wrench,
} from 'lucide-react'

const PHASE_CONFIG = {
  idle: { label: 'Ready', color: 'text-forge-muted', Icon: Activity },
  collecting: { label: 'Analyzing Requirements', color: 'text-blue-400', Icon: MessageSquareText },
  clarification: { label: 'Awaiting Your Input', color: 'text-amber-400', Icon: HelpCircle },
  awaiting_credentials: { label: 'Credentials Required', color: 'text-amber-400', Icon: AlertTriangle },
  planning: { label: 'Planning Workflow', color: 'text-purple-400', Icon: Hammer },
  generating: { label: 'Generating Code', color: 'text-indigo-400', Icon: Cpu },
  testing: { label: 'Testing in Sandbox', color: 'text-yellow-400', Icon: PackageCheck },
  debugging: { label: 'Self-Debugging', color: 'text-orange-400', Icon: Wrench },
  deploying: { label: 'Deploying', color: 'text-green-400', Icon: PackageCheck },
  deployed: { label: 'Deployed', color: 'text-forge-success', Icon: CheckCircle2 },
  failed: { label: 'Issues Found', color: 'text-forge-error', Icon: AlertTriangle },
}

export default function StatusBar({ phase, discoveredApis, debugHistory, events, providerStatus, providerError }) {
  const config = PHASE_CONFIG[phase] || PHASE_CONFIG.idle
  const PhaseIcon = config.Icon
  const llm = providerStatus?.llm
  const embeddings = providerStatus?.embeddings
  const providerReady = Boolean(llm?.configured)

  return (
    <div className="flex items-center gap-4 px-6 py-2 border-t border-forge-border bg-forge-panel text-xs overflow-x-auto">
      {/* Phase indicator */}
      <div className={`flex items-center gap-2 ${config.color} shrink-0`}>
        <PhaseIcon size={14} strokeWidth={2.2} />
        <span className="font-medium">{config.label}</span>
      </div>

      <div className="w-px h-4 bg-forge-border shrink-0" />

      {/* APIs discovered */}
      <div className="flex items-center gap-1.5 text-forge-muted shrink-0">
        <Search size={14} />
        <span>APIs: {discoveredApis.length}</span>
      </div>

      {/* Debug attempts */}
      {debugHistory.length > 0 && (
        <>
          <div className="w-px h-4 bg-forge-border shrink-0" />
          <div className="flex items-center gap-1.5 text-orange-400 shrink-0">
            <Wrench size={14} />
            <span>Debug: {debugHistory.length}/3</span>
          </div>
        </>
      )}

      {/* Events count */}
      <div className="w-px h-4 bg-forge-border shrink-0" />
      <div className="flex items-center gap-1.5 text-forge-muted shrink-0">
        <BarChart3 size={14} />
        <span>Events: {events.length}</span>
      </div>

      <div className="w-px h-4 bg-forge-border shrink-0" />
      <div
        className={`flex items-center gap-1.5 shrink-0 ${providerReady ? 'text-forge-success' : 'text-forge-warn'}`}
        title={providerError || (llm ? `${llm.provider} / ${llm.model}` : 'Loading provider status')}
      >
        {providerReady ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
        <span className="uppercase">{llm?.provider || 'provider'}</span>
        <span className="text-forge-muted max-w-[180px] truncate">{llm?.model || 'checking'}</span>
        {llm?.fallback_provider && (
          <span className="text-forge-muted hidden lg:inline">fallback: {llm.fallback_provider}</span>
        )}
      </div>

      <div className="flex items-center gap-1.5 text-forge-muted shrink-0" title="Embedding provider">
        <Database size={14} />
        <span>{embeddings?.provider || 'local'}</span>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Branding */}
      <div className="text-forge-muted shrink-0">
        ForgeFlow v1.0
      </div>
    </div>
  )
}
