import React, { useEffect, useState } from 'react'
import SkillLineageGraph from './SkillLineageGraph'

export default function SkillLibrary({ skills, onClose, getSkill, getSkillLineage,
                                       deleteSkill, onSeedFromSkill }) {
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [lineage, setLineage] = useState(null)

  useEffect(() => {
    if (!selected) { setDetail(null); setLineage(null); return }
    let alive = true
    Promise.all([getSkill(selected), getSkillLineage(selected)]).then(([d, l]) => {
      if (!alive) return
      setDetail(d); setLineage(l)
    })
    return () => { alive = false }
  }, [selected, getSkill, getSkillLineage])

  return (
    <div className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm flex">
      <div className="m-auto bg-forge-bg border border-purple-500/40 rounded-2xl w-[1000px] max-w-[95vw] max-h-[90vh] flex flex-col shadow-2xl shadow-purple-500/20">
        <div className="flex items-center justify-between p-4 border-b border-forge-border">
          <div className="flex items-center gap-2">
            <span className="text-2xl">📚</span>
            <h2 className="text-lg font-semibold">Skill Library</h2>
            <span className="text-xs text-forge-muted">{skills.length} skill{skills.length===1?'':'s'} in pool</span>
          </div>
          <button onClick={onClose} className="text-forge-muted hover:text-forge-text px-2">✕</button>
        </div>
        <div className="flex-1 grid grid-cols-2 overflow-hidden">
          {/* Left: list */}
          <div className="border-r border-forge-border overflow-auto p-2 space-y-1">
            {skills.length === 0 && (
              <div className="text-xs text-forge-muted italic text-center py-8">
                No skills yet. Let an organism live, then die.
              </div>
            )}
            {skills.map(s => (
              <button
                key={s.skill_id}
                onClick={() => setSelected(s.skill_id)}
                className={`w-full text-left p-2 rounded text-xs ${
                  selected===s.skill_id ? 'bg-purple-500/20 border border-purple-400/40' : 'hover:bg-forge-border/40'
                }`}
              >
                <div className="font-medium">🧬 {s.name}</div>
                <div className="text-[10px] text-forge-muted truncate">{s.description}</div>
                <div className="flex items-center gap-2 mt-1 text-[10px] text-forge-muted">
                  <span>gen {s.generation}</span>
                  <span>·</span>
                  <span>fitness {(s.fitness_at_death*100).toFixed(0)}%</span>
                  <span>·</span>
                  <span>{s.n_decisions_distilled} decisions</span>
                </div>
              </button>
            ))}
          </div>
          {/* Right: detail */}
          <div className="overflow-auto p-4">
            {!selected && (
              <div className="text-forge-muted text-sm italic">Select a skill to inspect.</div>
            )}
            {detail && (
              <div className="space-y-3 text-xs">
                <div>
                  <div className="text-base font-semibold">🧬 {detail.name}</div>
                  <div className="text-forge-muted text-[11px]">{detail.description}</div>
                </div>
                <div className="flex flex-wrap gap-2 text-[10px]">
                  <Chip>gen {detail.generation}</Chip>
                  <Chip>fitness {(detail.fitness_at_death*100).toFixed(0)}%</Chip>
                  <Chip>{detail.n_decisions_distilled} decisions distilled</Chip>
                  <Chip>{detail.parent_skills.length} parent skills</Chip>
                </div>
                {lineage && lineage.nodes?.length > 0 && (
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-forge-muted mb-1">Lineage</div>
                    <SkillLineageGraph lineage={lineage} />
                  </div>
                )}
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-forge-muted mb-1">Skill body</div>
                  <pre className="whitespace-pre-wrap font-sans text-[11px] bg-forge-border/30 p-3 rounded leading-relaxed">{detail.body}</pre>
                </div>
                <div className="flex gap-2 pt-2 border-t border-forge-border">
                  <button
                    onClick={() => onSeedFromSkill(detail.skill_id)}
                    className="flex-1 px-3 py-1.5 rounded bg-purple-500/30 hover:bg-purple-500/50 border border-purple-400 text-purple-100 text-xs"
                  >🧬 Seed organism with this</button>
                  <button
                    onClick={() => { if (confirm('Delete this skill from the pool?')) deleteSkill(detail.skill_id).then(() => setSelected(null)) }}
                    className="px-3 py-1.5 rounded bg-red-500/20 hover:bg-red-500/40 border border-red-500/40 text-red-300 text-xs"
                  >🗑 Delete</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Chip({ children }) {
  return <span className="px-2 py-0.5 rounded-full bg-forge-border/50 border border-forge-border text-forge-text/80">{children}</span>
}
