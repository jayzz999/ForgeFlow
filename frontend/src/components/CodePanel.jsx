import React, { useState, useEffect, useRef } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'

export default function CodePanel({ code, debugHistory }) {
  const [tab, setTab] = useState('code')
  // Task 3: Typewriter streaming effect
  const [visibleLines, setVisibleLines] = useState(0)
  const [isStreaming, setIsStreaming] = useState(false)
  const prevCodeRef = useRef('')
  const containerRef = useRef(null)

  const codeLines = code ? code.split('\n') : []

  useEffect(() => {
    // Detect new code arriving
    if (code && code !== prevCodeRef.current && code.length > 50) {
      prevCodeRef.current = code
      setVisibleLines(0)
      setIsStreaming(true)

      const totalLines = code.split('\n').length
      let current = 0
      const interval = setInterval(() => {
        current += 2 // Reveal 2 lines at a time for speed
        setVisibleLines(current)
        if (current >= totalLines) {
          clearInterval(interval)
          setIsStreaming(false)
          setVisibleLines(totalLines)
        }
      }, 25)

      return () => clearInterval(interval)
    }
  }, [code])

  // Auto-scroll during streaming
  useEffect(() => {
    if (isStreaming && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [visibleLines, isStreaming])

  const displayedCode = isStreaming
    ? codeLines.slice(0, visibleLines).join('\n')
    : code

  return (
    <div className="h-full flex flex-col bg-forge-panel">
      {/* Tabs */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-forge-border">
        <button
          onClick={() => setTab('code')}
          className={`px-3 py-1 text-xs rounded-lg transition-colors ${
            tab === 'code'
              ? 'bg-indigo-500/20 text-indigo-300'
              : 'text-forge-muted hover:text-forge-text'
          }`}
        >
          Generated Code
        </button>
        {debugHistory.length > 0 && (
          <button
            onClick={() => setTab('debug')}
            className={`px-3 py-1 text-xs rounded-lg transition-colors ${
              tab === 'debug'
                ? 'bg-red-500/20 text-red-300'
                : 'text-forge-muted hover:text-forge-text'
            }`}
          >
            Debug Log ({debugHistory.length})
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          {isStreaming && (
            <span className="text-xs text-indigo-400 animate-pulse">
              Streaming...
            </span>
          )}
          {code && (
            <span className="text-xs text-forge-muted">
              {code.split('\n').length} lines
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4" ref={containerRef}>
        {tab === 'code' && (
          <div className="relative">
            {displayedCode ? (
              <SyntaxHighlighter
                language="python"
                style={vscDarkPlus}
                customStyle={{
                  background: 'transparent',
                  fontSize: '0.75rem',
                  margin: 0,
                  padding: 0,
                }}
                showLineNumbers
                lineNumberStyle={{ color: '#334155', fontSize: '0.65rem' }}
              >
                {displayedCode}
              </SyntaxHighlighter>
            ) : (
              <div className="text-forge-muted italic text-sm text-center py-12">
                <div className="text-3xl mb-3">{'</>'}</div>
                Generated Python code will appear here...
              </div>
            )}
            {isStreaming && (
              <span className="animate-blink text-indigo-400 text-lg font-bold">|</span>
            )}
          </div>
        )}

        {tab === 'debug' && (
          <div className="space-y-4">
            {debugHistory.map((d, i) => (
              <div
                key={i}
                className="border border-forge-border rounded-xl p-4 animate-slide-in glass"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-bold text-red-400">
                    Attempt {i + 1}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    d.category === 'SCHEMA_MISMATCH' ? 'bg-yellow-500/20 text-yellow-300' :
                    d.category === 'AUTH_ERROR' ? 'bg-red-500/20 text-red-300' :
                    d.category === 'IMPORT_ERROR' ? 'bg-purple-500/20 text-purple-300' :
                    'bg-blue-500/20 text-blue-300'
                  }`}>
                    {d.category}
                  </span>
                </div>
                <p className="text-xs text-forge-muted mb-2">
                  <strong>Root Cause:</strong> {d.root_cause}
                </p>
                <p className="text-xs text-forge-success">
                  <strong>Fix:</strong> {d.fix}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
