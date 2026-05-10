import React, { useState, useRef, useEffect } from 'react'

const PHASE_LABELS = {
  idle: 'Ready',
  collecting: 'Analyzing...',
  clarification: 'Awaiting your input',
  planning: 'Planning...',
  generating: 'Generating code...',
  testing: 'Testing...',
  debugging: 'Self-debugging...',
  modifying: 'Modifying...',
  deploying: 'Deploying...',
  deployed: 'Deployed',
  failed: 'Issues found',
}

const RELIABLE_DEMO_PROMPT = 'Automate new hire onboarding from an uploaded HR sheet. Draft welcome email, Slack announcement, IT request, and tracking row. Dry run first.'

export default function ChatPanel({
  events, phase, onSend, onModify, onDemo, dag,
  clarification, onClarify, onSkipClarification, onReset,
  initialInput,
}) {
  const [input, setInput] = useState('')
  const [userMessages, setUserMessages] = useState([])
  const [systemMessages, setSystemMessages] = useState([])
  const messagesEndRef = useRef(null)

  useEffect(() => {
    if (initialInput) setInput(initialInput)
  }, [initialInput])

  // Convert events to chat messages
  useEffect(() => {
    const chatMessages = events
      .filter(e => e.message && e.event_type !== 'node.status_changed' && e.event_type !== 'dag.step_added')
      .map((e, i) => ({
        id: i,
        type: 'system',
        text: e.message,
        eventType: e.event_type,
        timestamp: e.timestamp,
      }))
    setSystemMessages(chatMessages)
  }, [events])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [userMessages, systemMessages, clarification])

  useEffect(() => {
    if (phase === 'idle' && events.length === 0) {
      setUserMessages([])
      setSystemMessages([])
    }
  }, [events.length, phase])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim()) return

    // If in clarification mode, send as clarification answer
    if (phase === 'clarification' && clarification && onClarify) {
      setUserMessages(prev => [...prev, {
        id: Date.now(),
        type: 'user',
        text: input,
      }])
      onClarify(input, clarification.originalRequest)
      setInput('')
      return
    }

    setUserMessages(prev => [...prev, {
      id: Date.now(),
      type: 'user',
      text: input,
    }])

    // Task 7: If already deployed with a DAG, treat as modification
    if (phase === 'deployed' && dag && onModify) {
      onModify(input)
    } else {
      onSend(input)
    }
    setInput('')
  }

  const loadDemo = () => {
    setInput(RELIABLE_DEMO_PROMPT)
  }

  const isWorking = phase !== 'idle' && phase !== 'deployed' && phase !== 'failed' && phase !== 'clarification' && phase !== 'awaiting_credentials'

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-forge-border bg-forge-panel p-4">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-sm font-semibold text-forge-text">Conversation</h2>
            <p className="text-xs text-forge-muted mt-1">
              {phase === 'deployed'
                ? 'Type to modify the workflow'
                : phase === 'clarification'
                  ? 'Please answer the question below'
                  : phase === 'awaiting_credentials'
                    ? 'Add credentials or use draft-first Runtime/Judge Demo'
                  : 'Describe your workflow in plain English'
              }
            </p>
          </div>
          {/* Reset button — escape hatch for stuck states */}
          {(phase === 'failed' || phase === 'awaiting_credentials' || isWorking) && onReset && (
            <button
              onClick={onReset}
              className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-1.5 text-xs text-red-300 transition-colors hover:bg-red-400/15"
              title="Reset and start over"
            >
              Reset
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto bg-forge-bg p-4">
        {userMessages.length === 0 && systemMessages.length === 0 && !clarification && (
          <div className="rounded-lg border border-forge-border bg-forge-panel p-5 text-forge-muted">
            <div className="mb-3 inline-flex rounded-lg border border-sky-400/20 bg-sky-400/10 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.14em] text-sky-300">
              Builder
            </div>
            <p className="text-sm font-semibold text-forge-text">Plain English to automation</p>
            <p className="mt-2 max-w-[310px] text-xs leading-5">
              Describe a workflow and ForgeFlow will discover connectors, generate code, test it, and prepare a safe deployment path.
            </p>
            <div className="mt-5 flex flex-col items-start gap-2">
              {onDemo && (
                <button
                  onClick={onDemo}
                  className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-4 py-2 text-xs font-medium text-emerald-200 transition-colors hover:bg-emerald-400/15"
                >
                  Run demo mode
                  <span className="text-[10px] text-emerald-300/70">(cached)</span>
                </button>
              )}
              <button
                onClick={loadDemo}
                className="rounded-lg border border-forge-border px-4 py-2 text-xs text-forge-text transition-colors hover:border-sky-400/40 hover:text-sky-200"
              >
                Load prompt
              </button>
            </div>
            <div className="mt-4 rounded-lg border border-forge-border bg-forge-bg/60 p-3 text-left text-xs">
              <p className="mb-1 text-forge-muted">Try:</p>
              <p className="leading-5 text-forge-text">{RELIABLE_DEMO_PROMPT}</p>
            </div>
          </div>
        )}

        {userMessages.map((msg) => (
          <div
            key={msg.id}
            className="animate-slide-in rounded-lg border border-sky-400/25 bg-sky-400/10 p-3 text-sky-100"
          >
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-sky-300">Prompt</div>
            <span className="text-sm leading-relaxed">{msg.text}</span>
          </div>
        ))}

        {systemMessages.map((msg) => (
          <div
            key={msg.id}
            className={`animate-slide-in ${
              msg.eventType === 'tool.calling'
                ? 'mr-4 ml-6 rounded-lg border border-amber-400/20 bg-amber-400/10 p-2 text-amber-200'
                : 'mr-4 rounded-lg border border-forge-border bg-forge-panel p-3 text-forge-text'
            }`}
          >
            <span className="mr-2 inline-block h-2 w-2 rounded-full bg-sky-300 align-middle" />
            <span className={`leading-relaxed ${msg.eventType === 'tool.calling' ? 'text-xs text-amber-300/80 font-mono' : 'text-sm'}`}>{msg.text}</span>
          </div>
        ))}

        {/* Clarification Card */}
        {clarification && phase === 'clarification' && (
          <div className="animate-slide-in mr-2 rounded-lg border border-amber-400/30 bg-amber-400/10 p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-sm font-semibold text-amber-300">Quick Question</span>
            </div>

            {/* Questions */}
            <div className="space-y-2 mb-3">
              {clarification.questions.map((q, i) => (
                <p key={i} className="text-sm text-forge-text leading-relaxed">
                  {q}
                </p>
              ))}
            </div>

            {/* Current Plan Preview */}
            {clarification.currentPlan?.length > 0 && (
              <div className="mb-3 p-2 rounded-lg bg-forge-bg/50 border border-forge-border">
                <p className="text-[10px] text-forge-muted mb-1 uppercase tracking-wider">Current Plan (assumed)</p>
                {clarification.currentPlan.map((step, i) => (
                  <p key={i} className="text-xs text-forge-text/70">
                    <span className="text-indigo-400">{i + 1}.</span> {step.action}
                    {step.service && <span className="text-emerald-400/60 ml-1">({step.service})</span>}
                  </p>
                ))}
              </div>
            )}

            {/* Skip button */}
            {onSkipClarification && (
              <button
                onClick={onSkipClarification}
                className="text-xs text-forge-muted hover:text-forge-text transition-colors underline underline-offset-2"
              >
                Skip - proceed with defaults
              </button>
            )}
          </div>
        )}

        {isWorking && (
          <div className="flex items-center gap-2 text-forge-muted text-xs animate-pulse">
            <div className="h-2 w-2 animate-bounce rounded-full bg-sky-300" />
            {PHASE_LABELS[phase] || 'Processing...'}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="border-t border-forge-border bg-forge-panel p-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              phase === 'deployed' ? 'Modify your workflow...'
                : phase === 'clarification' ? 'Type your answer...'
                  : 'Describe your workflow...'
            }
            className="flex-1 rounded-lg border border-forge-border bg-forge-bg px-4 py-2.5 text-sm text-forge-text transition-colors placeholder:text-forge-muted focus:border-sky-400/60 focus:outline-none"
            disabled={isWorking}
          />
          <button
            type="submit"
            disabled={!input.trim() || isWorking}
            className={`rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors ${
              phase === 'clarification'
                ? 'bg-amber-300 text-slate-950 hover:bg-amber-200'
                : 'bg-sky-300 text-slate-950 hover:bg-sky-200'
            } disabled:cursor-not-allowed disabled:opacity-40`}
          >
            {phase === 'clarification' ? 'Answer'
              : phase === 'deployed' ? 'Modify'
                : 'Forge'}
          </button>
        </div>
      </form>
    </div>
  )
}
