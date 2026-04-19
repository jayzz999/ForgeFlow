import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'

// ── Helpers ───────────────────────────────────────────────────

function getLang(filename) {
  if (!filename) return 'text'
  if (filename.endsWith('.py')) return 'python'
  if (filename.endsWith('.yaml') || filename.endsWith('.yml')) return 'yaml'
  if (filename.endsWith('.json')) return 'json'
  if (filename.endsWith('.sh')) return 'bash'
  if (filename.endsWith('.md')) return 'markdown'
  if (filename === 'Dockerfile') return 'docker'
  if (filename === 'Makefile') return 'makefile'
  return 'text'
}

function fileLabel(f) {
  const parts = f.split('/')
  return parts[parts.length - 1]
}

function fileIcon(filename) {
  if (!filename) return '📄'
  const base = fileLabel(filename)
  if (base.endsWith('.py')) return '🐍'
  if (base === 'Dockerfile') return '🐳'
  if (base === 'docker-compose.yml') return '🐳'
  if (base === 'k8s-deployment.yaml') return '☸️'
  if (base === 'Makefile') return '⚙️'
  if (base === 'requirements.txt') return '📦'
  if (base === 'README.md') return '📖'
  if (base === '.env.example') return '🔑'
  if (base === 'dag.json') return '🔀'
  if (base.endsWith('.sh')) return '🖥️'
  return '📄'
}

const FILE_ORDER = [
  'workflow.py', 'requirements.txt', 'Dockerfile', 'docker-compose.yml',
  'k8s-deployment.yaml', 'Makefile', 'run.sh', 'README.md',
  '.env.example', 'test_workflow.py', 'dag.json',
]

function sortFiles(files) {
  return [...files].sort((a, b) => {
    const ia = FILE_ORDER.indexOf(a)
    const ib = FILE_ORDER.indexOf(b)
    if (ia !== -1 && ib !== -1) return ia - ib
    if (ia !== -1) return -1
    if (ib !== -1) return 1
    return a.localeCompare(b)
  })
}

// ── Terminal output renderer ──────────────────────────────────

function Terminal({ output, title, success }) {
  const ref = useRef(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [output])

  const lines = (output || '').split('\n')

  return (
    <div className="rounded-xl border border-forge-border overflow-hidden">
      <div className={`flex items-center gap-2 px-3 py-2 text-xs font-mono border-b border-forge-border ${
        success === true ? 'bg-green-900/20 text-green-400' :
        success === false ? 'bg-red-900/20 text-red-400' :
        'bg-forge-bg/60 text-forge-muted'
      }`}>
        <span>{success === true ? '✅' : success === false ? '❌' : '💻'}</span>
        <span>{title}</span>
        {success !== undefined && (
          <span className={`ml-auto px-2 py-0.5 rounded-full text-[10px] ${
            success ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
          }`}>
            {success ? 'SUCCESS' : 'FAILED'}
          </span>
        )}
      </div>
      <div
        ref={ref}
        className="bg-black/60 p-3 overflow-auto max-h-72 font-mono text-[11px] leading-relaxed"
      >
        {lines.length === 0 || (lines.length === 1 && !lines[0]) ? (
          <span className="text-forge-muted italic">(no output)</span>
        ) : (
          lines.map((line, i) => (
            <div key={i} className={
              line.startsWith('[ERROR]') || line.startsWith('Error') || line.startsWith('Traceback')
                ? 'text-red-400'
                : line.startsWith('[PASS]') || line.startsWith('✅') || line.includes('success')
                ? 'text-green-400'
                : line.startsWith('[WARN]') || line.startsWith('⚠️')
                ? 'text-yellow-400'
                : line.startsWith('===')
                ? 'text-indigo-300 font-bold'
                : 'text-gray-300'
            }>
              {line || '\u00A0'}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────

export default function CodePanel({
  code,
  debugHistory,
  workflowId,
  generatedFiles = [],
  sandboxOutput,
}) {
  // Main tab: 'code' | 'output' | 'debug'
  const [mainTab, setMainTab] = useState('code')
  const [selectedFile, setSelectedFile] = useState('workflow.py')
  const [fileCache, setFileCache] = useState({})
  const [fetchingFile, setFetchingFile] = useState(false)

  // Live run state
  const [running, setRunning] = useState(false)
  const [liveOutput, setLiveOutput] = useState(null) // {stdout, stderr, success, execution_time}

  // Streaming for workflow.py
  const [visibleLines, setVisibleLines] = useState(0)
  const [isStreaming, setIsStreaming] = useState(false)
  const prevCodeRef = useRef('')
  const containerRef = useRef(null)

  const sortedFiles = sortFiles(generatedFiles)
  const hasFiles = sortedFiles.length > 0

  // Show output tab badge when sandbox output arrives
  const outputToShow = liveOutput || sandboxOutput

  // Reset when workflow changes
  useEffect(() => {
    if (!workflowId) {
      setSelectedFile('workflow.py')
      setFileCache({})
      setLiveOutput(null)
    }
  }, [workflowId])

  // Streaming effect when new code arrives
  useEffect(() => {
    if (code && code !== prevCodeRef.current && code.length > 50) {
      prevCodeRef.current = code
      setVisibleLines(0)
      setIsStreaming(true)
      setSelectedFile('workflow.py')
      setMainTab('code')

      const totalLines = code.split('\n').length
      let current = 0
      const interval = setInterval(() => {
        current += 2
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

  useEffect(() => {
    if (isStreaming && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [visibleLines, isStreaming])

  // Fetch a file from the backend
  const fetchFile = useCallback(async (filename) => {
    if (!workflowId || filename === 'workflow.py') return
    if (fileCache[filename] !== undefined) return
    setFetchingFile(true)
    try {
      const res = await fetch(`/api/workflows/${workflowId}/files/${encodeURIComponent(filename)}`)
      if (res.ok) {
        const data = await res.json()
        setFileCache(prev => ({ ...prev, [filename]: data.content }))
      } else {
        setFileCache(prev => ({ ...prev, [filename]: `# Could not load ${filename}` }))
      }
    } catch {
      setFileCache(prev => ({ ...prev, [filename]: `# Error loading ${filename}` }))
    } finally {
      setFetchingFile(false)
    }
  }, [workflowId, fileCache])

  useEffect(() => {
    if (selectedFile !== 'workflow.py') fetchFile(selectedFile)
  }, [selectedFile, fetchFile])

  // Run the workflow live with real credentials
  const handleRunNow = async () => {
    if (!workflowId || running) return
    setRunning(true)
    setLiveOutput(null)
    setMainTab('output')
    try {
      const res = await fetch(`/api/workflows/${workflowId}/run`, { method: 'POST' })
      const data = await res.json()
      setLiveOutput({
        stdout: data.stdout || '',
        stderr: data.stderr || '',
        success: data.success,
        execution_time: data.execution_time,
        source: 'live',
      })
    } catch (err) {
      setLiveOutput({
        stdout: '',
        stderr: `Failed to run workflow: ${err.message}`,
        success: false,
        execution_time: 0,
        source: 'live',
      })
    } finally {
      setRunning(false)
    }
  }

  // What to show in the code/files view
  const displayedContent = (() => {
    if (selectedFile === 'workflow.py') {
      return isStreaming ? code.split('\n').slice(0, visibleLines).join('\n') : code
    }
    if (fileCache[selectedFile] !== undefined) return fileCache[selectedFile]
    if (fetchingFile) return '# Loading...'
    return ''
  })()

  return (
    <div className="h-full flex flex-col bg-forge-panel">

      {/* ── Top tabs ── */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-forge-border shrink-0">
        <button
          onClick={() => setMainTab('code')}
          className={`px-3 py-1 text-xs rounded-lg transition-colors ${
            mainTab === 'code'
              ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30'
              : 'text-forge-muted hover:text-forge-text'
          }`}
        >
          📝 Code
        </button>

        <button
          onClick={() => setMainTab('output')}
          className={`px-3 py-1 text-xs rounded-lg transition-colors flex items-center gap-1 ${
            mainTab === 'output'
              ? 'bg-green-500/20 text-green-300 border border-green-500/30'
              : 'text-forge-muted hover:text-forge-text'
          }`}
        >
          💻 Output
          {outputToShow && (
            <span className={`w-1.5 h-1.5 rounded-full ${
              outputToShow.success ? 'bg-green-400' : 'bg-red-400'
            }`} />
          )}
        </button>

        {debugHistory.length > 0 && (
          <button
            onClick={() => setMainTab('debug')}
            className={`px-3 py-1 text-xs rounded-lg transition-colors ${
              mainTab === 'debug'
                ? 'bg-red-500/20 text-red-300 border border-red-500/30'
                : 'text-forge-muted hover:text-forge-text'
            }`}
          >
            🔧 Debug ({debugHistory.length})
          </button>
        )}

        {/* Run button + stats */}
        <div className="ml-auto flex items-center gap-2">
          {isStreaming && (
            <span className="text-xs text-indigo-400 animate-pulse">Streaming...</span>
          )}
          {code && selectedFile === 'workflow.py' && mainTab === 'code' && (
            <span className="text-xs text-forge-muted">{code.split('\n').length} lines</span>
          )}
          {workflowId && (
            <button
              onClick={handleRunNow}
              disabled={running}
              className={`flex items-center gap-1.5 text-xs px-3 py-1 rounded-lg border transition-colors ${
                running
                  ? 'bg-forge-border/30 border-forge-border text-forge-muted cursor-wait'
                  : 'bg-green-500/20 hover:bg-green-500/30 border-green-500/30 text-green-400'
              }`}
            >
              {running ? (
                <>
                  <span className="animate-spin inline-block">⟳</span> Running...
                </>
              ) : (
                <>▶ Run Now</>
              )}
            </button>
          )}
        </div>
      </div>

      {/* ── File tabs row (Code tab only) ── */}
      {mainTab === 'code' && hasFiles && (
        <div className="flex items-center gap-1 px-3 py-1.5 border-b border-forge-border bg-forge-bg/40 overflow-x-auto shrink-0">
          <span className="text-[10px] text-forge-muted shrink-0 mr-1">Files:</span>
          {sortedFiles.map(file => (
            <button
              key={file}
              title={file}
              onClick={() => setSelectedFile(file)}
              className={`shrink-0 flex items-center gap-1 px-2 py-0.5 text-[11px] rounded transition-colors whitespace-nowrap ${
                selectedFile === file
                  ? 'bg-indigo-500/25 text-indigo-300 border border-indigo-500/40'
                  : 'text-forge-muted hover:text-forge-text hover:bg-forge-border/40 border border-transparent'
              }`}
            >
              <span>{fileIcon(file)}</span>
              <span>{fileLabel(file)}</span>
            </button>
          ))}
        </div>
      )}

      {/* ── Content ── */}
      <div className="flex-1 overflow-auto p-4" ref={containerRef}>

        {/* Code / Files tab */}
        {mainTab === 'code' && (
          <div className="relative">
            {displayedContent ? (
              <SyntaxHighlighter
                language={getLang(selectedFile)}
                style={vscDarkPlus}
                customStyle={{ background: 'transparent', fontSize: '0.75rem', margin: 0, padding: 0 }}
                showLineNumbers
                lineNumberStyle={{ color: '#334155', fontSize: '0.65rem' }}
              >
                {displayedContent}
              </SyntaxHighlighter>
            ) : (
              <div className="text-forge-muted italic text-sm text-center py-12">
                <div className="text-3xl mb-3">{'</>'}</div>
                {hasFiles ? 'Select a file tab above' : 'Generated code will appear here...'}
              </div>
            )}
            {isStreaming && selectedFile === 'workflow.py' && (
              <span className="animate-blink text-indigo-400 text-lg font-bold">|</span>
            )}
          </div>
        )}

        {/* Output tab */}
        {mainTab === 'output' && (
          <div className="space-y-4">
            {/* Explanation banner */}
            <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4">
              <div className="flex items-start gap-3">
                <span className="text-2xl">🚀</span>
                <div>
                  <p className="text-xs font-semibold text-indigo-300 mb-1">Where did ForgeFlow deploy this?</p>
                  <p className="text-xs text-forge-muted leading-relaxed">
                    Your workflow was saved as a self-contained project at:
                  </p>
                  {workflowId && (
                    <code className="block mt-1.5 text-[11px] bg-black/40 rounded px-2 py-1 text-green-400 font-mono">
                      workflows/{workflowId}/
                    </code>
                  )}
                  <p className="text-xs text-forge-muted mt-2 leading-relaxed">
                    It includes <strong className="text-forge-text">workflow.py</strong>, Dockerfile, docker-compose, k8s manifests, Makefile, README, and requirements.txt — everything needed to run it anywhere.
                    Click <strong className="text-green-400">▶ Run Now</strong> to execute it live with your real credentials, or <strong className="text-green-400">📦 Download Project</strong> to get the full ZIP.
                  </p>
                </div>
              </div>
            </div>

            {/* Running spinner */}
            {running && (
              <div className="rounded-xl border border-forge-border p-6 text-center">
                <div className="text-2xl animate-spin inline-block mb-2">⟳</div>
                <p className="text-xs text-forge-muted">Installing dependencies and running workflow.py...</p>
                <p className="text-[10px] text-forge-muted/60 mt-1">This may take up to 2 minutes on first run</p>
              </div>
            )}

            {/* Live run output */}
            {liveOutput && !running && (
              <Terminal
                output={liveOutput.stdout + (liveOutput.stderr ? '\n\n── STDERR ──\n' + liveOutput.stderr : '')}
                title={`Live run • ${liveOutput.execution_time}s`}
                success={liveOutput.success}
              />
            )}

            {/* Sandbox output (from pipeline) */}
            {sandboxOutput && !liveOutput && !running && (
              <Terminal
                output={sandboxOutput.stdout + (sandboxOutput.stderr ? '\n\n── STDERR ──\n' + sandboxOutput.stderr : '')}
                title={`Sandbox execution (pipeline run) • ${sandboxOutput.execution_time?.toFixed(2)}s`}
                success={sandboxOutput.success}
              />
            )}

            {/* Idle state */}
            {!outputToShow && !running && (
              <div className="text-center py-12 text-forge-muted">
                <div className="text-4xl mb-3">💻</div>
                <p className="text-sm">No output yet.</p>
                {workflowId && (
                  <p className="text-xs mt-1">
                    Click <span className="text-green-400 font-medium">▶ Run Now</span> above to execute with real credentials
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {/* Debug tab */}
        {mainTab === 'debug' && (
          <div className="space-y-4">
            {debugHistory.map((d, i) => (
              <div key={i} className="border border-forge-border rounded-xl p-4 glass">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-bold text-red-400">Attempt {i + 1}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    d.category === 'SCHEMA_MISMATCH' ? 'bg-yellow-500/20 text-yellow-300' :
                    d.category === 'AUTH_ERROR'       ? 'bg-red-500/20 text-red-300' :
                    d.category === 'IMPORT_ERROR'     ? 'bg-purple-500/20 text-purple-300' :
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
