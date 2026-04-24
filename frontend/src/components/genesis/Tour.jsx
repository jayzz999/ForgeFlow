import React, { useEffect, useRef, useState } from 'react'

const STEPS = [
  { ms: 5000,  text: '🥚 Meet Genesis. Watch this organism be born.',
    action: 'seed' },
  { ms: 8000,  text: '👁 It can perceive.', action: 'perceive' },
  { ms: 12000, text: '💭 And it dreams.', action: 'dream' },
  { ms: 10000, text: '✏ You can rewrite its past.', action: 'edit' },
  { ms: 6000,  text: '⭐ Promote a counterfactual to reality.', action: 'promote' },
  { ms: 8000,  text: '🪦 When it dies, its mind becomes inheritable.\nThis is digital evolution.',
    action: 'die' },
]

export default function Tour({ open, onClose, g }) {
  const [step, setStep] = useState(0)
  const [running, setRunning] = useState(false)
  const stateRef = useRef({ orgId: null, decisionId: null, branchId: null })

  useEffect(() => {
    if (!open) { setStep(0); setRunning(false); stateRef.current = {orgId:null,decisionId:null,branchId:null}; return }
    setRunning(true)
    let cancelled = false

    const runStep = async (i) => {
      if (cancelled || i >= STEPS.length) {
        if (!cancelled) { setRunning(false) }
        return
      }
      setStep(i)
      const s = STEPS[i]
      try {
        await doAction(s.action, stateRef.current, g)
      } catch (e) { console.error('[Tour] step failed:', e) }
      await new Promise(r => setTimeout(r, s.ms))
      runStep(i + 1)
    }
    runStep(0)
    return () => { cancelled = true }
  }, [open, g])

  if (!open) return null
  const s = STEPS[step]
  return (
    <div className="fixed inset-x-0 bottom-6 z-50 flex justify-center pointer-events-none">
      <div className="pointer-events-auto bg-forge-bg/95 backdrop-blur border border-purple-400/60 rounded-xl px-6 py-4 shadow-2xl shadow-purple-500/30 flex items-center gap-4 max-w-2xl">
        <div className="flex items-center gap-2 text-xs text-purple-300">
          <span>Tour {step+1}/{STEPS.length}</span>
          {running && <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />}
        </div>
        <div className="flex-1 text-sm whitespace-pre-line">{s.text}</div>
        <button onClick={onClose} className="text-forge-muted hover:text-forge-text text-xs px-2">Skip</button>
      </div>
    </div>
  )
}

async function doAction(name, state, g) {
  switch (name) {
    case 'seed': {
      const o = await g.seed({
        name: 'tour_subject',
        goal: 'Watch incoming events and respond helpfully.',
        constraints: ['be concise'],
        forbidden: ['leak PII'],
      })
      state.orgId = o.id
      return
    }
    case 'perceive':
      if (state.orgId) await g.perceive(state.orgId, {
        type: 'urgent_email',
        from: 'vip@bigcorp.com',
        subject: 'URGENT: account locked',
      })
      return
    case 'dream':
      if (state.orgId) await g.dream(state.orgId, 5)
      return
    case 'edit': {
      if (state.orgId && g.graph?.nodes?.length) {
        const real = g.graph.nodes.find(n => !n.is_dream && !n.shadow_branch)
        if (real) {
          state.decisionId = real.id
          const branch = await g.editDecision(state.orgId, real.id, {
            new_action: { tool: 'send_slack', args: { channel: '#vip', text: 'Escalated' } },
            new_reasoning: 'Tour edit: prefer escalation for VIP urgent emails.',
          })
          if (branch?.branch?.id) state.branchId = branch.branch.id
        }
      }
      return
    }
    case 'promote':
      if (state.orgId && state.branchId) await g.promoteBranch(state.orgId, state.branchId)
      return
    case 'die':
      if (state.orgId) await g.killOrganism(state.orgId)
      return
  }
}
