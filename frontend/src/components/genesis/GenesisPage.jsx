import React, { useState } from 'react'
import { useGenesis } from '../../hooks/useGenesis'
import OrganismNucleus from './OrganismNucleus'
import CausalGraph from './CausalGraph'
import DecisionInspector from './DecisionInspector'
import DreamStream from './DreamStream'
import SkillLibrary from './SkillLibrary'
import { ORGANISM_TEMPLATES } from './templates'
import InheritancePicker from './InheritancePicker'

export default function GenesisPage({ onBack }) {
  const g = useGenesis()
  const {
    connected, organisms, activeId, setActiveId, graph, branches, eventLog,
    acting, dreaming, seed, perceive, dream, editDecision, promoteBranch, killOrganism,
    addSource, removeSource,
    skills, getSkill, getSkillLineage, deleteSkill,
  } = g

  const [selectedDecision, setSelectedDecision] = useState(null)
  const [showSeedModal, setShowSeedModal] = useState(false)
  const [showLibrary, setShowLibrary] = useState(false)
  const [seedFromSkillId, setSeedFromSkillId] = useState(null)
  const [perceiveJson, setPerceiveJson] = useState('{\n  "type": "test_event",\n  "payload": {}\n}')
  const [perceiveError, setPerceiveError] = useState(null)

  const activeOrganism = organisms.find(o => o.id === activeId)

  const handleEdit = async (decisionId, payload) => {
    await editDecision(activeId, decisionId, payload)
    // graph auto-refreshes via WS event
  }
  const handlePromote = async (branchId) => {
    await promoteBranch(activeId, branchId)
  }

  const sendPerceive = async () => {
    setPerceiveError(null)
    let parsed
    try { parsed = JSON.parse(perceiveJson) }
    catch (e) { setPerceiveError(e.message); return }
    await perceive(activeId, parsed)
  }

  return (
    <div className="h-screen flex flex-col bg-forge-bg text-forge-text overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-forge-border glass">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-xs text-forge-muted hover:text-forge-text">← ForgeFlow</button>
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-fuchsia-500 via-purple-500 to-indigo-500 flex items-center justify-center font-bold text-sm shadow-lg shadow-purple-500/30">
            G
          </div>
          <h1 className="text-lg font-semibold tracking-tight">Genesis</h1>
          <span className="text-xs text-forge-muted px-2 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/30 text-purple-300">
            Living Digital Organisms
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-2 text-xs ${connected ? 'text-forge-success' : 'text-forge-error'}`}>
            <div className={`w-2 h-2 rounded-full ${connected ? 'bg-forge-success animate-pulse' : 'bg-forge-error'}`} />
            {connected ? 'Connected' : 'Disconnected'}
          </div>
          <button
            onClick={() => setShowLibrary(true)}
            className="text-xs px-3 py-1.5 rounded-lg bg-forge-border/50 hover:bg-purple-500/20 border border-forge-border"
            title="Browse the Skill pool"
          >📚 Skills ({skills.length})</button>
          <button
            onClick={() => setShowSeedModal(true)}
            className="text-xs px-3 py-1.5 rounded-lg bg-gradient-to-r from-fuchsia-500/20 to-indigo-500/20 hover:from-fuchsia-500/40 hover:to-indigo-500/40 border border-purple-500/40 text-purple-200"
          >
            🌱 Seed Organism
          </button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden relative">
        {/* Left rail: organism list + nucleus + controls */}
        <div className="w-[340px] min-w-[300px] border-r border-forge-border flex flex-col">
          <div className="p-3 border-b border-forge-border">
            <div className="text-[10px] uppercase tracking-widest text-forge-muted mb-2">Organisms ({organisms.length})</div>
            <div className="space-y-1 max-h-40 overflow-auto">
              {organisms.map(o => (
                <button
                  key={o.id}
                  onClick={() => setActiveId(o.id)}
                  className={`w-full text-left px-2 py-1.5 rounded text-xs flex items-center justify-between group ${
                    o.id === activeId ? 'bg-purple-500/20 border border-purple-400/40' : 'hover:bg-forge-border/40'
                  }`}
                >
                  <div className="truncate">
                    <div className="font-medium truncate">{o.name || o.id}</div>
                    <div className="text-[10px] text-forge-muted truncate italic">{o.intent?.goal}</div>
                  </div>
                  <span
                    className="text-forge-muted hover:text-red-400 opacity-0 group-hover:opacity-100 ml-2"
                    onClick={(e) => { e.stopPropagation(); if (confirm('Let this organism die?')) killOrganism(o.id) }}
                  >🗑</span>
                </button>
              ))}
              {organisms.length === 0 && (
                <div className="text-xs text-forge-muted italic text-center py-4">No life yet. Seed one.</div>
              )}
            </div>
          </div>

          <div className="p-3 border-b border-forge-border">
            <OrganismNucleus
              organism={activeOrganism}
              acting={acting}
              dreaming={dreaming}
              connected={connected}
            />
          </div>

          {activeOrganism && (
            <SourceRail
              organism={activeOrganism}
              onAdd={(s) => addSource(activeId, s)}
              onRemove={(i) => removeSource(activeId, i)}
            />
          )}

          {activeOrganism && (
            <div className="p-3 border-b border-forge-border space-y-2">
              <div className="text-[10px] uppercase tracking-widest text-forge-muted">Inject perception</div>
              <textarea
                className="w-full h-24 bg-forge-border/30 rounded p-2 text-[11px] font-mono border border-forge-border focus:outline-none focus:border-purple-400"
                value={perceiveJson}
                onChange={e => setPerceiveJson(e.target.value)}
              />
              {perceiveError && <div className="text-[10px] text-red-400">{perceiveError}</div>}
              <div className="flex gap-2">
                <button
                  onClick={sendPerceive}
                  className="flex-1 px-2 py-1.5 rounded bg-cyan-500/20 hover:bg-cyan-500/40 border border-cyan-400/40 text-cyan-200 text-xs"
                >👁 Perceive</button>
                <button
                  onClick={() => dream(activeId, 5)}
                  className="flex-1 px-2 py-1.5 rounded bg-fuchsia-500/20 hover:bg-fuchsia-500/40 border border-fuchsia-400/40 text-fuchsia-200 text-xs"
                >💭 Dream ×5</button>
              </div>
            </div>
          )}

          <div className="flex-1 overflow-hidden">
            <DreamStream events={eventLog} />
          </div>
        </div>

        {/* Center: causal graph */}
        <div className="flex-1 relative bg-forge-bg/40">
          {activeId ? (
            <CausalGraph graph={graph} onSelectDecision={setSelectedDecision} />
          ) : (
            <div className="h-full flex items-center justify-center text-forge-muted">
              <div className="text-center">
                <div className="text-4xl mb-3">🧬</div>
                <div className="text-sm">Select or seed an organism to see its causal graph</div>
              </div>
            </div>
          )}

          {/* Branch counter */}
          {branches.length > 0 && (
            <div className="absolute top-3 left-3 px-3 py-1.5 rounded-full bg-purple-500/20 border border-purple-400/40 text-purple-200 text-xs">
              🌌 {branches.length} counterfactual branch{branches.length === 1 ? '' : 'es'}
            </div>
          )}

          {/* Inspector slide-in */}
          {selectedDecision && (
            <DecisionInspector
              decision={selectedDecision}
              branches={branches}
              onClose={() => setSelectedDecision(null)}
              onEdit={handleEdit}
              onPromoteBranch={handlePromote}
            />
          )}
        </div>
      </div>

      {showSeedModal && (
        <SeedModal
          skills={skills}
          prefillSkillId={seedFromSkillId}
          onClose={() => { setShowSeedModal(false); setSeedFromSkillId(null) }}
          onSeed={async (data) => { await seed(data); setShowSeedModal(false); setSeedFromSkillId(null) }}
        />
      )}

      {showLibrary && (
        <SkillLibrary
          skills={skills}
          getSkill={getSkill}
          getSkillLineage={getSkillLineage}
          deleteSkill={deleteSkill}
          onClose={() => setShowLibrary(false)}
          onSeedFromSkill={(id) => { setSeedFromSkillId(id); setShowLibrary(false); setShowSeedModal(true) }}
        />
      )}
    </div>
  )
}

// ── Seed Modal ──────────────────────────────────────────────
function SeedModal({ onClose, onSeed, skills, prefillSkillId }) {
  const [name, setName] = useState('')
  const [goal, setGoal] = useState('')
  const [constraintsText, setConstraintsText] = useState('')
  const [forbiddenText, setForbiddenText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [template, setTemplate] = useState(null)
  const [inheritIds, setInheritIds] = useState(prefillSkillId ? [prefillSkillId] : [])

  const applyTemplate = (t) => {
    setTemplate(t.id)
    setName(t.id === 'blank' ? '' : t.id)
    setGoal(t.goal)
    setConstraintsText((t.constraints || []).join('\n'))
    setForbiddenText((t.forbidden || []).join('\n'))
  }

  const submit = async () => {
    if (!goal.trim()) return
    setSubmitting(true)
    try {
      await onSeed({
        name: name.trim(),
        goal: goal.trim(),
        constraints: constraintsText.split('\n').map(s => s.trim()).filter(Boolean),
        forbidden: forbiddenText.split('\n').map(s => s.trim()).filter(Boolean),
        inherit_from: inheritIds,
      })
    } finally { setSubmitting(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-forge-bg border border-purple-500/40 rounded-2xl p-6 w-[480px] shadow-2xl shadow-purple-500/20">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-2xl">🌱</span>
          <h2 className="text-lg font-semibold">Seed a new organism</h2>
        </div>
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap gap-2 mb-3">
            {ORGANISM_TEMPLATES.map(t => (
              <button key={t.id} type="button" onClick={() => applyTemplate(t)}
                      className={`text-xs px-2 py-1 rounded-full border ${
                        template===t.id ? 'bg-purple-500/30 border-purple-400 text-purple-100'
                                        : 'bg-forge-border/40 border-forge-border hover:bg-forge-border/60'
                      }`}>
                {t.icon} {t.name}
              </button>
            ))}
          </div>
          <Field label="Name (optional)">
            <input
              className="w-full bg-forge-border/30 rounded p-2 border border-forge-border focus:outline-none focus:border-purple-400"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. customer_pulse"
            />
          </Field>
          <Field label="Intent (the soul)">
            <textarea
              className="w-full h-20 bg-forge-border/30 rounded p-2 border border-forge-border focus:outline-none focus:border-purple-400"
              value={goal}
              onChange={e => setGoal(e.target.value)}
              placeholder="Watch every customer email and act helpfully without ever spamming."
            />
          </Field>
          <Field label="Constraints (one per line)">
            <textarea
              className="w-full h-16 bg-forge-border/30 rounded p-2 border border-forge-border focus:outline-none focus:border-purple-400 font-mono text-xs"
              value={constraintsText}
              onChange={e => setConstraintsText(e.target.value)}
              placeholder="respond within 5 minutes&#10;use polite tone"
            />
          </Field>
          <Field label="Forbidden (one per line)">
            <textarea
              className="w-full h-16 bg-forge-border/30 rounded p-2 border border-forge-border focus:outline-none focus:border-purple-400 font-mono text-xs"
              value={forbiddenText}
              onChange={e => setForbiddenText(e.target.value)}
              placeholder="never share PII&#10;never make promises about pricing"
            />
          </Field>
          <Field label="Inherit skills (DNA from past organisms)">
            <InheritancePicker skills={skills} selected={inheritIds} onChange={setInheritIds} />
          </Field>
        </div>
        <div className="flex gap-2 mt-5">
          <button onClick={onClose} className="flex-1 px-3 py-2 rounded bg-forge-border/50 hover:bg-forge-border text-sm">Cancel</button>
          <button
            onClick={submit}
            disabled={submitting || !goal.trim()}
            className="flex-1 px-3 py-2 rounded bg-gradient-to-r from-fuchsia-500 to-indigo-500 hover:opacity-90 text-white text-sm font-medium disabled:opacity-30"
          >{submitting ? 'Crystallizing...' : '🌱 Birth organism'}</button>
        </div>
      </div>
    </div>
  )
}

// ── Perception Sources Rail ─────────────────────────────────
function SourceRail({ organism, onAdd, onRemove }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState('interval')
  const [type, setType] = useState('tick')
  const [interval, setInterval] = useState(60)
  const [url, setUrl] = useState('')

  const submit = async () => {
    const src = { kind, type, interval_s: Number(interval) || 60 }
    if (kind === 'http_poll') src.url = url
    await onAdd(src)
    setOpen(false); setUrl(''); setType('tick'); setKind('interval'); setInterval(60)
  }

  const sources = organism.perception_sources || []

  return (
    <div className="p-3 border-b border-forge-border">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] uppercase tracking-widest text-forge-muted">Perception sources ({sources.length})</div>
        <button
          onClick={() => setOpen(o => !o)}
          className="text-[10px] px-1.5 py-0.5 rounded border border-forge-border text-forge-muted hover:text-forge-text"
        >{open ? '−' : '+'}</button>
      </div>
      <div className="space-y-1">
        {sources.map((s, i) => (
          <div key={i} className="flex items-center gap-2 px-2 py-1 rounded bg-forge-border/30 text-[11px] group">
            <span className="text-cyan-300">
              {s.kind === 'interval' ? '⏱' : s.kind === 'http_poll' ? '🌐' : '📬'}
            </span>
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate">{s.type || s.kind}</div>
              <div className="text-[10px] text-forge-muted truncate">
                {s.kind === 'http_poll' && s.url}
                {s.kind === 'webhook' && s.token && `POST /api/genesis/webhook/${s.token}`}
                {s.kind === 'interval' && `every ${s.interval_s}s`}
                {s.kind === 'http_poll' && ` · every ${s.interval_s}s`}
              </div>
            </div>
            <button
              onClick={() => onRemove(i)}
              className="text-forge-muted hover:text-red-400 opacity-0 group-hover:opacity-100"
            >✕</button>
          </div>
        ))}
        {sources.length === 0 && !open && (
          <div className="text-[10px] text-forge-muted italic">No sources. Add one to make this organism live autonomously.</div>
        )}
      </div>
      {open && (
        <div className="mt-2 space-y-2 text-xs">
          <select
            value={kind}
            onChange={e => setKind(e.target.value)}
            className="w-full bg-forge-border/30 rounded p-1.5 border border-forge-border focus:outline-none focus:border-purple-400"
          >
            <option value="interval">⏱ interval (heartbeat tick)</option>
            <option value="http_poll">🌐 http_poll (poll a URL)</option>
            <option value="webhook">📬 webhook (token route)</option>
          </select>
          <input
            value={type}
            onChange={e => setType(e.target.value)}
            placeholder="event type label"
            className="w-full bg-forge-border/30 rounded p-1.5 border border-forge-border focus:outline-none focus:border-purple-400"
          />
          {kind === 'http_poll' && (
            <input
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="https://..."
              className="w-full bg-forge-border/30 rounded p-1.5 border border-forge-border focus:outline-none focus:border-purple-400 font-mono"
            />
          )}
          {kind !== 'webhook' && (
            <input
              type="number" min={5}
              value={interval}
              onChange={e => setInterval(e.target.value)}
              placeholder="interval seconds"
              className="w-full bg-forge-border/30 rounded p-1.5 border border-forge-border focus:outline-none focus:border-purple-400"
            />
          )}
          <button
            onClick={submit}
            className="w-full px-2 py-1.5 rounded bg-purple-500/30 hover:bg-purple-500/50 border border-purple-400 text-purple-100"
          >Attach source</button>
        </div>
      )}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-forge-muted mb-1">{label}</div>
      {children}
    </div>
  )
}
