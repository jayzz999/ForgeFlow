import React from 'react'

// Live ticker of organism events (dreams, percepts, edits, branches).
// Each event styled by type. Newest on top.
const STYLES = {
  'organism.seeded':         { icon: '🥚', color: 'text-emerald-300', label: 'Born' },
  'organism.perceiving':     { icon: '👁',  color: 'text-cyan-300',    label: 'Perceived' },
  'organism.reasoning':      { icon: '🧠', color: 'text-indigo-300',  label: 'Reasoned' },
  'organism.acted':          { icon: '⚡', color: 'text-amber-300',   label: 'Acted' },
  'organism.dreaming_start': { icon: '😴', color: 'text-purple-300',  label: 'Dreaming starts' },
  'organism.dreamt':         { icon: '💭', color: 'text-fuchsia-300', label: 'Dreamt' },
  'organism.dreaming_end':   { icon: '🌅', color: 'text-purple-200',  label: 'Dreaming ends' },
  'organism.edited':         { icon: '✏', color: 'text-amber-300',   label: 'Past edited' },
  'organism.branch_created': { icon: '🌌', color: 'text-purple-300',  label: 'Branch created' },
  'organism.branch_promoted':{ icon: '⭐', color: 'text-yellow-300',  label: 'Branch promoted' },
  'organism.died':           { icon: '🪦', color: 'text-red-300',     label: 'Died' },
}

function summarize(e) {
  switch (e.type) {
    case 'organism.acted':
      return e.decision?.action?.tool || e.decision?.action?.type || ''
    case 'organism.dreamt':
      return `${e.i}/${e.of} — ${e.perception?.type || ''}`
    case 'organism.reasoning':
      return (e.reasoning || '').slice(0, 80)
    case 'organism.perceiving':
      return e.perception?.type || ''
    case 'organism.branch_created':
      return e.branch?.summary?.slice(0, 80) || e.branch?.id
    case 'organism.branch_promoted':
      return `${e.branch_id} → canonical`
    case 'organism.seeded':
      return e.organism?.name || e.organism_id
    default:
      return ''
  }
}

export default function DreamStream({ events }) {
  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b border-forge-border text-[10px] uppercase tracking-widest text-forge-muted flex items-center justify-between">
        <span>Stream of consciousness</span>
        <span>{events.length} event{events.length === 1 ? '' : 's'}</span>
      </div>
      <div className="flex-1 overflow-auto p-2 space-y-1">
        {events.length === 0 && (
          <div className="text-forge-muted text-xs italic p-3 text-center">
            silence... waiting for the organism to wake
          </div>
        )}
        {events.map((e, i) => {
          const style = STYLES[e.type] || { icon: '•', color: 'text-forge-text', label: e.type }
          const summary = summarize(e)
          return (
            <div
              key={`${e.ts}-${i}`}
              className={`text-[11px] flex items-start gap-2 px-2 py-1.5 rounded hover:bg-forge-border/30 ${i === 0 ? 'animate-fade-in' : ''}`}
            >
              <span className="text-sm mt-0.5">{style.icon}</span>
              <div className="flex-1 min-w-0">
                <div className={`font-medium ${style.color}`}>{style.label}</div>
                {summary && (
                  <div className="text-forge-muted truncate">{summary}</div>
                )}
              </div>
              <span className="text-[9px] text-forge-muted/60 mt-0.5 shrink-0">
                {new Date(e.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
