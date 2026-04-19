import React, { useState, useEffect } from 'react'

// Slide-in panel showing full decision details + edit modal.
// On edit submit, calls onEdit(decisionId, { new_action, new_reasoning }) which
// returns a CounterfactualBranch.
export default function DecisionInspector({ decision, onClose, onEdit, onPromoteBranch, branches }) {
  const [editing, setEditing] = useState(false)
  const [reasoning, setReasoning] = useState('')
  const [actionJson, setActionJson] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (decision) {
      setReasoning(decision.reasoning || '')
      setActionJson(JSON.stringify(decision.action || {}, null, 2))
      setEditing(false)
      setError(null)
    }
  }, [decision])

  if (!decision) return null

  const matchingBranch = branches?.find(b => b.edited_decision_id === decision.id)

  const submitEdit = async () => {
    setSubmitting(true); setError(null)
    let parsed
    try { parsed = JSON.parse(actionJson) }
    catch (e) { setError('Action JSON invalid: ' + e.message); setSubmitting(false); return }
    try {
      await onEdit(decision.id, { new_action: parsed, new_reasoning: reasoning })
      setEditing(false)
    } catch (e) {
      setError(e.message || 'Edit failed')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="absolute top-0 right-0 h-full w-[480px] bg-forge-bg/95 backdrop-blur-xl border-l border-forge-border z-30 flex flex-col shadow-2xl">
      <div className="flex items-center justify-between p-4 border-b border-forge-border">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-forge-muted">
            {decision.shadow_branch ? '🌌 Shadow Decision' :
             decision.is_dream ? '💭 Dreamt Decision' :
             decision.edited ? '✏ Edited Decision' : '⚡ Real Decision'}
          </div>
          <div className="font-mono text-xs mt-1 text-forge-muted">{decision.id}</div>
        </div>
        <button
          onClick={onClose}
          className="text-forge-muted hover:text-forge-text px-2"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-auto p-4 space-y-4 text-xs">
        <Section label="TRIGGER">
          <pre className="font-mono whitespace-pre-wrap bg-forge-border/30 p-2 rounded">{JSON.stringify(decision.trigger, null, 2)}</pre>
        </Section>

        <Section label="REASONING">
          {editing ? (
            <textarea
              className="w-full h-32 bg-forge-border/30 rounded p-2 text-forge-text border border-forge-border focus:outline-none focus:border-indigo-400"
              value={reasoning}
              onChange={(e) => setReasoning(e.target.value)}
            />
          ) : (
            <p className="text-forge-text/90 whitespace-pre-wrap leading-relaxed">{decision.reasoning || '—'}</p>
          )}
        </Section>

        <Section label="ACTION">
          {editing ? (
            <textarea
              className="w-full h-40 bg-forge-border/30 rounded p-2 text-forge-text border border-forge-border focus:outline-none focus:border-indigo-400 font-mono"
              value={actionJson}
              onChange={(e) => setActionJson(e.target.value)}
            />
          ) : (
            <pre className="font-mono whitespace-pre-wrap bg-forge-border/30 p-2 rounded">{JSON.stringify(decision.action, null, 2)}</pre>
          )}
        </Section>

        {decision.result && (
          <Section label="RESULT">
            <pre className="font-mono whitespace-pre-wrap bg-forge-border/30 p-2 rounded text-forge-text/80">{JSON.stringify(decision.result, null, 2)}</pre>
          </Section>
        )}

        {decision.alternatives_considered?.length > 0 && (
          <Section label="ALTERNATIVES CONSIDERED">
            <ul className="space-y-1">
              {decision.alternatives_considered.map((a, i) => (
                <li key={i} className="text-forge-muted italic">• {typeof a === 'string' ? a : JSON.stringify(a)}</li>
              ))}
            </ul>
          </Section>
        )}

        {matchingBranch && (
          <Section label="↳ COUNTERFACTUAL BRANCH">
            <div className="bg-purple-500/10 border border-purple-400/40 rounded p-3 space-y-2">
              <div className="font-mono text-[10px] text-purple-300">{matchingBranch.id}</div>
              {matchingBranch.summary && (
                <p className="text-purple-100 italic">{matchingBranch.summary}</p>
              )}
              <div className="text-forge-muted text-[10px]">
                {matchingBranch.downstream_replays?.length || 0} downstream replays · {matchingBranch.promoted ? 'promoted' : 'shadow'}
              </div>
              {!matchingBranch.promoted && (
                <button
                  onClick={() => onPromoteBranch(matchingBranch.id)}
                  className="w-full mt-1 px-3 py-1.5 rounded bg-purple-500/30 hover:bg-purple-500/50 border border-purple-400 text-purple-100 text-xs font-medium"
                >
                  ⭐ Promote to canonical reality
                </button>
              )}
            </div>
          </Section>
        )}

        {error && <div className="text-red-400 text-xs">{error}</div>}
      </div>

      <div className="border-t border-forge-border p-3 flex gap-2">
        {editing ? (
          <>
            <button
              onClick={() => setEditing(false)}
              disabled={submitting}
              className="flex-1 px-3 py-2 rounded bg-forge-border/50 hover:bg-forge-border text-xs"
            >Cancel</button>
            <button
              onClick={submitEdit}
              disabled={submitting}
              className="flex-1 px-3 py-2 rounded bg-amber-500/30 hover:bg-amber-500/50 border border-amber-400 text-amber-100 text-xs font-medium"
            >
              {submitting ? 'Replaying causality...' : '✏ Rewrite history'}
            </button>
          </>
        ) : (
          <button
            onClick={() => setEditing(true)}
            disabled={decision.is_dream || decision.shadow_branch}
            className="flex-1 px-3 py-2 rounded bg-amber-500/20 hover:bg-amber-500/40 border border-amber-500/40 text-amber-200 text-xs disabled:opacity-30 disabled:cursor-not-allowed"
            title={decision.is_dream || decision.shadow_branch ? 'Cannot edit dream/shadow decisions' : 'Edit this past decision'}
          >
            ✏ Edit this past decision
          </button>
        )}
      </div>
    </div>
  )
}

function Section({ label, children }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-forge-muted mb-1">{label}</div>
      {children}
    </div>
  )
}
