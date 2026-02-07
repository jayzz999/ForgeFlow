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
  deployed: 'Deployed!',
  failed: 'Issues found',
}

export default function ChatPanel({
  events, phase, onSend, onModify, onDemo, dag,
  clarification, onClarify, onSkipClarification, onReset,
}) {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const messagesEndRef = useRef(null)

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
    setMessages(chatMessages)
  }, [events])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, clarification])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim()) return

    // If in clarification mode, send as clarification answer
    if (phase === 'clarification' && clarification && onClarify) {
      setMessages(prev => [...prev, {
        id: Date.now(),
        type: 'user',
        text: input,
      }])
      onClarify(input, clarification.originalRequest)
      setInput('')
      return
    }

    setMessages(prev => [...prev, {
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

  // Task 8: Load demo prompt
  const loadDemo = () => {
    setInput("When V75 moves 2% in 5 min, alert #trading-alerts on Slack, log to Google Sheets, and create a Jira ticket")
  }

  const getEventIcon = (eventType) => {
    const icons = {
      'conversation.started': '💬',
      'conversation.analyzed': '🧠',
      'conversation.clarification_needed': '❓',
      'discovery.started': '🔍',
      'discovery.miss': '🔎',
      'discovery.partial': '📡',
      'api.discovered': '✅',
      'discovery.complete': '🔭',
      'planning.started': '🔨',
      'dag.planned': '🌳',
      'codegen.started': '💻',
      'code.generated': '📄',
      'security.started': '🛡️',
      'security.complete': '🔒',
      'testing.started': '🧪',
      'testing.generated': '📝',
      'testing.passed': '✅',
      'testing.partial': '⚠️',
      'execution.started': '🚀',
      'execution.success': '🎉',
      'execution.failed': '❌',
      'debug.started': '🔧',
      'debug.diagnosed': '🩺',
      'workflow.ready': '✅',
      'workflow.deployed': '🚀',
      'workflow.approval_required': '🎯',
      'modify.started': '✏️',
      'modify.complete': '✅',
      'tool.calling': '🔧',
      'timeout': '⏰',
    }
    return icons[eventType] || '⚙️'
  }

  const isWorking = phase !== 'idle' && phase !== 'deployed' && phase !== 'failed' && phase !== 'clarification'

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-forge-border glass">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-sm font-semibold">Conversation</h2>
            <p className="text-xs text-forge-muted mt-1">
              {phase === 'deployed'
                ? 'Type to modify the workflow'
                : phase === 'clarification'
                  ? 'Please answer the question below'
                  : 'Describe your workflow in plain English'
              }
            </p>
          </div>
          {/* Reset button — escape hatch for stuck states */}
          {(phase === 'failed' || isWorking) && onReset && (
            <button
              onClick={onReset}
              className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-400 hover:bg-red-500/20 transition-all"
              title="Reset and start over"
            >
              Reset
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && !clarification && (
          <div className="text-center py-12 text-forge-muted">
            <div className="text-4xl mb-4">🔥</div>
            <p className="text-sm font-medium">Welcome to ForgeFlow</p>
            <p className="text-xs mt-2 max-w-[280px] mx-auto leading-relaxed">
              Describe a workflow and I'll discover APIs, generate code,
              self-debug, and deploy — all autonomously.
            </p>
            {/* Demo buttons */}
            <div className="mt-6 flex flex-col gap-2 items-center">
              {onDemo && (
                <button
                  onClick={onDemo}
                  className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-green-500/20 to-emerald-500/20 border border-green-500/30 text-xs text-green-300 hover:from-green-500/30 hover:to-emerald-500/30 transition-all flex items-center gap-2"
                >
                  <span>🎬</span> Run Demo Mode
                  <span className="text-[10px] text-green-400/60">(cached)</span>
                </button>
              )}
              <button
                onClick={loadDemo}
                className="px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-500/20 to-purple-500/20 border border-indigo-500/30 text-xs text-indigo-300 hover:from-indigo-500/30 hover:to-purple-500/30 transition-all"
              >
                ▶ Load Demo Prompt
              </button>
            </div>
            <div className="mt-4 p-3 rounded-lg bg-forge-border/30 text-left text-xs glass">
              <p className="text-forge-muted mb-1">Or try:</p>
              <p className="text-forge-text italic">
                "When V75 moves 2% in 5 min, alert #trading-alerts on Slack,
                log to Google Sheets, and create a Jira ticket"
              </p>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`animate-slide-in ${
              msg.type === 'user'
                ? 'ml-8 bg-indigo-500/20 border border-indigo-500/30 rounded-xl rounded-br-sm p-3'
                : msg.eventType === 'tool.calling'
                  ? 'mr-4 ml-6 bg-amber-500/10 border border-amber-500/20 rounded-lg p-2 glass'
                  : 'mr-4 bg-forge-panel border border-forge-border rounded-xl rounded-bl-sm p-3 glass'
            }`}
          >
            {msg.type === 'system' && (
              <span className="mr-2">{getEventIcon(msg.eventType)}</span>
            )}
            <span className={`leading-relaxed ${msg.eventType === 'tool.calling' ? 'text-xs text-amber-300/80 font-mono' : 'text-sm'}`}>{msg.text}</span>
          </div>
        ))}

        {/* Clarification Card */}
        {clarification && phase === 'clarification' && (
          <div className="animate-slide-in mr-2 bg-gradient-to-br from-amber-500/10 to-orange-500/10 border border-amber-500/30 rounded-xl p-4 glass">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-lg">❓</span>
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
                Skip — proceed with defaults
              </button>
            )}
          </div>
        )}

        {isWorking && (
          <div className="flex items-center gap-2 text-forge-muted text-xs animate-pulse">
            <div className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce" />
            {PHASE_LABELS[phase] || 'Processing...'}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-forge-border">
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
            className="flex-1 bg-forge-bg border border-forge-border rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-indigo-500 transition-colors placeholder:text-forge-muted"
            disabled={isWorking}
          />
          <button
            type="submit"
            disabled={!input.trim() || isWorking}
            className={`px-4 py-2.5 rounded-xl text-sm font-medium transition-all shadow-lg ${
              phase === 'clarification'
                ? 'bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 shadow-amber-500/20'
                : 'bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 shadow-indigo-500/20'
            } disabled:opacity-40 disabled:cursor-not-allowed`}
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
