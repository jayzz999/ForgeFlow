import React from 'react'

export default function InheritancePicker({ skills, selected, onChange }) {
  const toggle = (id) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])

  if (skills.length === 0) {
    return (
      <div className="text-[10px] text-forge-muted italic">
        No skills in the pool yet. Inheritance will activate once organisms have lived and died.
      </div>
    )
  }
  return (
    <div className="space-y-1 max-h-32 overflow-auto">
      {skills.map(s => {
        const on = selected.includes(s.skill_id)
        return (
          <button
            key={s.skill_id}
            type="button"
            onClick={() => toggle(s.skill_id)}
            className={`w-full text-left p-1.5 rounded text-[11px] flex items-center gap-2 ${
              on ? 'bg-purple-500/30 border border-purple-400/60' : 'bg-forge-border/30 hover:bg-forge-border/50 border border-forge-border'
            }`}
          >
            <span className="text-sm">{on ? '✓' : '🧬'}</span>
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate">{s.name}</div>
              <div className="text-[10px] text-forge-muted truncate">
                gen {s.generation} · fitness {(s.fitness_at_death*100).toFixed(0)}%
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}
