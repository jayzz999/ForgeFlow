import React from 'react'

// Pulsing core that visualizes the organism's intent + state.
// State drives color + animation: PERCEIVING (calm), ACTING (glow), DREAMING (shimmer).
export default function OrganismNucleus({ organism, acting, dreaming, connected }) {
  if (!organism) {
    return (
      <div className="flex flex-col items-center justify-center p-6 rounded-2xl border border-forge-border glass">
        <div className="w-32 h-32 rounded-full bg-forge-border/30 animate-pulse" />
        <p className="mt-4 text-xs text-forge-muted">No organism alive</p>
      </div>
    )
  }

  const state = dreaming ? 'DREAMING' : acting ? 'ACTING' : 'PERCEIVING'
  const stateColor = {
    DREAMING: 'from-fuchsia-500 via-purple-500 to-indigo-500',
    ACTING: 'from-amber-400 via-orange-500 to-red-500',
    PERCEIVING: 'from-cyan-400 via-sky-500 to-indigo-500',
  }[state]
  const stateRing = {
    DREAMING: 'shadow-[0_0_60px_rgba(192,38,211,0.5)]',
    ACTING: 'shadow-[0_0_60px_rgba(251,146,60,0.6)]',
    PERCEIVING: 'shadow-[0_0_40px_rgba(56,189,248,0.4)]',
  }[state]

  return (
    <div className="flex flex-col items-center p-6 rounded-2xl border border-forge-border glass relative overflow-hidden">
      {/* ambient field */}
      <div className="absolute inset-0 opacity-30 pointer-events-none">
        <div className={`absolute -inset-10 bg-gradient-to-br ${stateColor} blur-3xl ${dreaming ? 'animate-pulse' : ''}`} />
      </div>

      {/* nucleus */}
      <div className="relative">
        <div className={`w-36 h-36 rounded-full bg-gradient-to-br ${stateColor} ${stateRing} flex items-center justify-center transition-all duration-500 ${acting ? 'scale-110' : 'scale-100'}`}>
          <div className="w-28 h-28 rounded-full bg-forge-bg/60 backdrop-blur flex items-center justify-center">
            <div className={`w-20 h-20 rounded-full bg-gradient-to-br ${stateColor} animate-pulse`} />
          </div>
        </div>
        {/* orbiting dream particles */}
        {dreaming && (
          <>
            <div className="absolute inset-0 rounded-full border border-fuchsia-400/40 animate-ping" />
            <div className="absolute -inset-4 rounded-full border border-purple-400/20 animate-ping" style={{animationDelay: '0.5s'}} />
          </>
        )}
      </div>

      <div className="relative mt-5 text-center max-w-sm">
        <div className="text-xs uppercase tracking-widest text-forge-muted">{state}</div>
        <div className="text-base font-semibold mt-1 truncate">{organism.name || organism.id}</div>
        <div className="mt-2 text-xs text-forge-text/80 italic line-clamp-3">"{organism.intent?.goal}"</div>

        {/* constraints / forbidden chips */}
        {(organism.intent?.constraints?.length || organism.intent?.forbidden?.length) ? (
          <div className="mt-3 flex flex-wrap gap-1 justify-center">
            {organism.intent.constraints?.slice(0, 3).map((c, i) => (
              <span key={`c${i}`} className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-300">
                {c}
              </span>
            ))}
            {organism.intent.forbidden?.slice(0, 3).map((c, i) => (
              <span key={`f${i}`} className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/10 border border-red-500/30 text-red-300">
                ⛔ {c}
              </span>
            ))}
          </div>
        ) : null}

        {/* heartbeat */}
        <div className="mt-3 flex items-center justify-center gap-2 text-[10px] text-forge-muted">
          <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
          {connected ? 'heartbeat ok' : 'severed'}
          <span className="opacity-50">·</span>
          <span>{organism.id?.slice(0, 12)}</span>
        </div>
      </div>
    </div>
  )
}
