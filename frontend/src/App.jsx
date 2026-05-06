import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowRight,
  Blocks,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Cloud,
  Database,
  FileSpreadsheet,
  Gauge,
  Gamepad2,
  GitBranch,
  History,
  Home,
  KeyRound,
  Layers3,
  LayoutDashboard,
  LockKeyhole,
  Play,
  PlugZap,
  Rocket,
  Server,
  Search,
  ShieldCheck,
  Sparkles,
  TimerReset,
  Upload,
  Workflow,
  Wrench,
} from 'lucide-react'
import { useWebSocket } from './hooks/useWebSocket'
import { useProviderStatus } from './hooks/useForgeFlow'
import ChatPanel from './components/ChatPanel'
import WorkflowCanvas from './components/WorkflowCanvas'
import StatusBar from './components/StatusBar'
import ApiDiscoveryBadge from './components/ApiDiscoveryBadge'
import DebugOverlay from './components/DebugOverlay'

const CodePanel = lazy(() => import('./components/CodePanel'))

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', Icon: LayoutDashboard },
  { id: 'builder', label: 'Builder', Icon: Workflow },
  { id: 'appbuilder', label: 'App Builder', Icon: Gamepad2 },
  { id: 'runtime', label: 'Runtime', Icon: Activity },
  { id: 'judge', label: 'Judge Demo', Icon: Sparkles },
  { id: 'connectors', label: 'Connectors', Icon: Blocks },
  { id: 'schemas', label: 'Schemas', Icon: FileSpreadsheet },
  { id: 'approvals', label: 'Approvals', Icon: ClipboardCheck },
  { id: 'triggers', label: 'Triggers', Icon: TimerReset },
  { id: 'deployments', label: 'Deployments', Icon: Server },
  { id: 'runs', label: 'Run History', Icon: History },
  { id: 'ingestions', label: 'Ingestions', Icon: PlugZap },
  { id: 'evals', label: 'Evals', Icon: Gauge },
  { id: 'templates', label: 'Templates', Icon: Layers3 },
  { id: 'roadmap', label: 'Roadmap', Icon: GitBranch },
]

const API_URL = import.meta.env.VITE_API_URL || ''

function useApiResource(path, fallback) {
  const [data, setData] = useState(fallback)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refetch = useCallback(() => {
    let alive = true
    setLoading(true)
    setError(null)
    fetch(`${API_URL}${path}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((payload) => {
        if (alive) setData(payload)
      })
      .catch((err) => {
        if (alive) setError(err.message)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [path])

  useEffect(() => refetch(), [refetch])

  return { data, loading, error, refetch, setData }
}

function LogoMark() {
  return (
    <div className="flex items-center gap-3">
      <div className="grid h-9 w-9 place-items-center rounded-lg border border-sky-400/30 bg-sky-400/15 text-sm font-bold text-sky-200 shadow-lg shadow-sky-950/30">
        FF
      </div>
      <div>
        <div className="text-sm font-semibold text-forge-text">ForgeFlow</div>
        <div className="text-[11px] text-forge-muted">Automation engineer</div>
      </div>
    </div>
  )
}

function Metric({ label, value, Icon, tone = 'sky' }) {
  const tones = {
    sky: 'border-sky-400/20 bg-sky-400/10 text-sky-300',
    green: 'border-emerald-400/20 bg-emerald-400/10 text-emerald-300',
    amber: 'border-amber-400/20 bg-amber-400/10 text-amber-300',
    slate: 'border-slate-400/20 bg-slate-400/10 text-slate-300',
  }
  return (
    <div className="rounded-lg border border-forge-border bg-forge-panel p-4">
      <div className={`mb-4 grid h-9 w-9 place-items-center rounded-lg border ${tones[tone]}`}>
        <Icon size={18} />
      </div>
      <div className="text-2xl font-semibold text-forge-text">{value}</div>
      <div className="mt-1 text-xs text-forge-muted">{label}</div>
    </div>
  )
}

function SectionTitle({ eyebrow, title, description }) {
  return (
    <div className="mb-5">
      <div className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-sky-300">{eyebrow}</div>
      <h2 className="text-2xl font-semibold tracking-tight text-forge-text">{title}</h2>
      {description && <p className="mt-2 max-w-3xl text-sm leading-6 text-forge-muted">{description}</p>}
    </div>
  )
}

function LandingPage({ onOpenApp }) {
  return (
    <div className="min-h-screen bg-[#070a0f] text-forge-text">
      <header className="fixed inset-x-0 top-0 z-20 border-b border-white/10 bg-[#070a0f]/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <LogoMark />
          <nav className="hidden items-center gap-6 text-xs text-forge-muted md:flex">
            <a href="#how" className="hover:text-forge-text">How it works</a>
            <a href="#platform" className="hover:text-forge-text">Platform</a>
            <a href="#trust" className="hover:text-forge-text">Trust</a>
          </nav>
          <button
            onClick={onOpenApp}
            className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-400/15 px-4 py-2 text-sm font-medium text-emerald-200 hover:bg-emerald-400/20"
          >
            Open app <ArrowRight size={16} />
          </button>
        </div>
      </header>

      <main>
        <section className="relative min-h-[92vh] overflow-hidden pt-24">
          <div className="absolute inset-0 automation-field" aria-hidden="true" />
          <div className="relative mx-auto grid min-h-[calc(92vh-6rem)] max-w-7xl content-center px-6 pb-16">
            <div className="max-w-4xl">
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-sky-300/20 bg-black/30 px-3 py-1 text-xs text-sky-200">
                <Sparkles size={14} /> Prompt to discovered systems to verified deployment
              </div>
              <h1 className="max-w-5xl text-5xl font-semibold leading-[1.03] tracking-tight text-white md:text-7xl">
                Plain English to Production Automation
              </h1>
              <p className="mt-6 max-w-2xl text-base leading-7 text-slate-300 md:text-lg">
                ForgeFlow turns business processes into grounded automations by inspecting schemas, checking credentials, composing capabilities, testing code, previewing risky actions, and deploying runnable projects.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <button
                  onClick={onOpenApp}
                  className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-5 py-3 text-sm font-semibold text-slate-950 hover:bg-sky-200"
                >
                  Build an automation <Rocket size={17} />
                </button>
                <a
                  href="#platform"
                  className="inline-flex items-center gap-2 rounded-lg border border-white/15 bg-white/5 px-5 py-3 text-sm font-medium text-white hover:bg-white/10"
                >
                  Explore platform <ChevronRight size={17} />
                </a>
              </div>
            </div>
          </div>
        </section>

        <section id="how" className="border-y border-white/10 bg-[#0a1118] px-6 py-16">
          <div className="mx-auto max-w-7xl">
            <SectionTitle
              eyebrow="Operating Model"
              title="The user stays in simple English. ForgeFlow does the engineering."
              description="The internal pipeline expands a request into discovery, validation, planning, generation, tests, approval, deployment, and monitoring."
            />
            <div className="grid gap-3 md:grid-cols-4">
              {[
                ['Discover', 'Inspect APIs, MCP tools, files, schemas, and credentials before planning.', Search],
                ['Validate', 'Map fields and permissions to typed capabilities with risk levels.', ShieldCheck],
                ['Generate', 'Compose known actions first, then write custom glue code only when needed.', Wrench],
                ['Operate', 'Deploy, run, log, retry, and keep approval gates visible.', Activity],
              ].map(([title, body, Icon]) => (
                <div key={title} className="rounded-lg border border-white/10 bg-white/[0.03] p-5">
                  <Icon className="mb-4 text-sky-300" size={22} />
                  <h3 className="text-sm font-semibold text-white">{title}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-400">{body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="platform" className="px-6 py-16">
          <div className="mx-auto max-w-7xl">
            <SectionTitle
              eyebrow="Product Surface"
              title="A full automation workspace, not a code editor clone."
              description="Dashboard, builder, connector center, schema explorer, approval inbox, run history, templates, and deployment status live in one place."
            />
            <div className="grid gap-3 md:grid-cols-3">
              {NAV_ITEMS.slice(0, 6).map(({ label, Icon }) => (
                <div key={label} className="flex items-center gap-3 rounded-lg border border-white/10 bg-[#0d121b] p-4">
                  <div className="grid h-10 w-10 place-items-center rounded-lg bg-sky-400/10 text-sky-300">
                    <Icon size={19} />
                  </div>
                  <span className="text-sm font-medium">{label}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="trust" className="border-t border-white/10 bg-[#0a1118] px-6 py-16">
          <div className="mx-auto max-w-7xl">
            <SectionTitle
              eyebrow="Trust Layer"
              title="No hallucinated schemas. No silent external actions."
              description="ForgeFlow should ask for missing data, inspect real sources, and require approval before sending, posting, writing, deleting, or changing access."
            />
            <button
              onClick={onOpenApp}
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-400/15 px-5 py-3 text-sm font-medium text-emerald-200 hover:bg-emerald-400/20"
            >
              Enter workspace <ArrowRight size={16} />
            </button>
          </div>
        </section>
      </main>
    </div>
  )
}

function DashboardView({ overview, providerStatus, onNavigate }) {
  const metrics = overview?.metrics || {}
  const recent = overview?.recent_runs || []

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Command Center"
        title="Automation workspace"
        description="A product-grade overview of what is connected, what has been generated, and what needs attention before production."
      />
      <PreflightPanel onBuild={() => onNavigate('builder')} />
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Generated workflows" value={metrics.total_workflows ?? 0} Icon={Workflow} tone="sky" />
        <Metric label="Connected services" value={`${metrics.configured_services ?? 0}/${metrics.available_services ?? 0}`} Icon={KeyRound} tone="green" />
        <Metric label="Recent successful runs" value={metrics.recent_successful_runs ?? 0} Icon={CheckCircle2} tone="green" />
        <Metric label="Pending approvals" value={metrics.approval_queue ?? 0} Icon={ClipboardCheck} tone="amber" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Recent automations</h3>
            <button onClick={() => onNavigate('runs')} className="text-xs text-sky-300 hover:text-sky-200">View runs</button>
          </div>
          <div className="space-y-2">
            {(overview?.workflows || []).slice(0, 6).map((workflow) => (
              <div key={workflow.id} className="flex items-center justify-between rounded-lg border border-forge-border bg-forge-bg/50 px-3 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{workflow.name}</div>
                  <div className="mt-1 text-xs text-forge-muted">{workflow.id} · {workflow.status}</div>
                </div>
                <span className="rounded-full bg-emerald-400/10 px-2 py-1 text-[11px] text-emerald-300">deployed</span>
              </div>
            ))}
            {(overview?.workflows || []).length === 0 && <EmptyState title="No workflows yet" body="Use the builder to create the first automation." />}
          </div>
        </div>

        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Runtime readiness</h3>
          <div className="mt-4 space-y-3">
            <ReadinessRow label="LLM provider" value={providerStatus?.llm?.provider || 'checking'} ok={providerStatus?.llm?.configured} />
            <ReadinessRow label="Embeddings" value={providerStatus?.embeddings?.provider || 'local'} ok={providerStatus?.embeddings?.configured} />
            <ReadinessRow label="Approval policy" value="enabled in UI" ok />
            <ReadinessRow label="Cloud deploy" value="planned" ok={false} />
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Latest run signals</h3>
          <button onClick={() => onNavigate('builder')} className="inline-flex items-center gap-1 text-xs text-sky-300 hover:text-sky-200">Open builder <ArrowRight size={14} /></button>
        </div>
        <RunList runs={recent} />
      </div>
    </div>
  )
}

function PreflightPanel({ onBuild }) {
  const [prompt, setPrompt] = useState('Automate HR onboarding from an uploaded Excel sheet, draft a welcome email, post a Slack announcement, and append tracking data.')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const runPreflight = async () => {
    if (!prompt.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(`${API_URL}/api/preflight`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setResult(payload)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-lg border border-sky-400/20 bg-sky-400/5 p-5">
      <div className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-sky-200">
            <Search size={17} /> Prompt preflight
          </div>
          <p className="mb-4 text-xs leading-5 text-forge-muted">
            Check schemas, credentials, and approval risks before generation so ForgeFlow asks for missing facts instead of guessing.
          </p>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            className="h-24 w-full resize-none rounded-lg border border-forge-border bg-forge-bg p-3 text-sm leading-6 outline-none focus:border-sky-400"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <button onClick={runPreflight} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200 disabled:opacity-50">
              <Gauge size={16} /> {loading ? 'Checking...' : 'Run preflight'}
            </button>
            <button onClick={onBuild} className="inline-flex items-center gap-2 rounded-lg border border-forge-border px-4 py-2 text-sm text-forge-text hover:bg-forge-border/50">
              Open builder <ArrowRight size={16} />
            </button>
          </div>
          {error && <p className="mt-3 text-xs text-red-300">{error}</p>}
        </div>
        <div className="rounded-lg border border-forge-border bg-forge-panel p-4">
          {!result ? (
            <EmptyState title="No preflight yet" body="Run a check to see likely connectors, missing credentials, schema needs, and approval gates." />
          ) : (
            <div className="space-y-4">
              <ReadinessRow label="Recommendation" value={result.recommendation} ok={!result.questions?.length} />
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Detected services</div>
                <div className="flex flex-wrap gap-2">
                  {result.detected_services.map((service) => (
                    <span key={service.service} className={`rounded-full px-2 py-1 text-[11px] ${service.configured ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>
                      {service.name}: {service.configured ? 'connected' : 'missing'}
                    </span>
                  ))}
                  {result.detected_services.length === 0 && <span className="text-xs text-forge-muted">No known connector detected yet</span>}
                </div>
              </div>
              {result.questions?.length > 0 && (
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Questions to ask</div>
                  <div className="space-y-2">
                    {result.questions.map((question) => <p key={question} className="rounded-lg bg-forge-bg px-3 py-2 text-xs leading-5 text-forge-muted">{question}</p>)}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ReadinessRow({ label, value, ok }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-forge-border bg-forge-bg/50 px-3 py-2">
      <span className="text-xs text-forge-muted">{label}</span>
      <span className={`inline-flex items-center gap-1 text-xs ${ok ? 'text-emerald-300' : 'text-amber-300'}`}>
        {ok ? <CheckCircle2 size={14} /> : <Wrench size={14} />} {value}
      </span>
    </div>
  )
}

function BuilderView(props) {
  const {
    connected,
    events,
    dag,
    code,
    phase,
    discoveredApis,
    debugHistory,
    dagSteps,
    nodeStatuses,
    clarification,
    deployedWorkflowId,
    generatedFiles,
    sandboxOutput,
    sendMessage,
    sendClarification,
    skipClarification,
    sendModification,
    sendDemo,
    resetState,
  } = props
  const [showCode, setShowCode] = useState(true)

  const handleDownload = () => {
    if (deployedWorkflowId) window.open(`/api/workflows/${deployedWorkflowId}/download`, '_blank')
  }

  return (
    <div className="flex h-full min-h-[740px] flex-col overflow-hidden rounded-lg border border-forge-border bg-forge-bg">
      <div className="flex items-center justify-between border-b border-forge-border bg-forge-panel px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">Automation Builder</h2>
          <p className="mt-1 text-xs text-forge-muted">Prompt, discover, test, deploy, and run from one workspace.</p>
        </div>
        <div className="flex items-center gap-3">
          {phase === 'deployed' && deployedWorkflowId && (
            <button onClick={handleDownload} className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-400/15 px-3 py-2 text-xs text-emerald-200 hover:bg-emerald-400/20">
              <Cloud size={14} /> Download Project
            </button>
          )}
          <div className={`flex items-center gap-2 text-xs ${connected ? 'text-forge-success' : 'text-forge-error'}`}>
            <div className={`h-2 w-2 rounded-full ${connected ? 'bg-forge-success' : 'bg-forge-error'}`} />
            {connected ? 'Connected' : 'Disconnected'}
          </div>
          <button onClick={() => setShowCode(!showCode)} className="rounded-lg border border-forge-border bg-forge-border/40 px-3 py-2 text-xs hover:bg-forge-border">
            {showCode ? 'Hide Code' : 'Show Code'}
          </button>
        </div>
      </div>

      {discoveredApis.length > 0 && (
        <div className="flex items-center gap-2 overflow-x-auto border-b border-forge-border bg-forge-panel/70 px-4 py-2">
          <span className="shrink-0 text-xs text-forge-muted">APIs Discovered:</span>
          {discoveredApis.map((api, i) => <ApiDiscoveryBadge key={i} api={api} />)}
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="flex w-[400px] min-w-[350px] flex-col border-r border-forge-border">
          <ChatPanel
            events={events}
            phase={phase}
            onSend={sendMessage}
            onModify={sendModification}
            onDemo={sendDemo}
            dag={dag}
            clarification={clarification}
            onClarify={sendClarification}
            onSkipClarification={skipClarification}
            onReset={resetState}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <div className={`${showCode ? 'h-1/2' : 'flex-1'} min-h-[260px] border-b border-forge-border`}>
            <WorkflowCanvas dag={dag} dagSteps={dagSteps} phase={phase} nodeStatuses={nodeStatuses} />
          </div>
          {showCode && (
            <div className="h-1/2 min-h-0 overflow-hidden">
              <Suspense fallback={<div className="h-full p-4 text-sm text-forge-muted">Loading code view...</div>}>
                <CodePanel
                  code={code}
                  debugHistory={debugHistory}
                  workflowId={deployedWorkflowId}
                  generatedFiles={generatedFiles}
                  sandboxOutput={sandboxOutput}
                />
              </Suspense>
            </div>
          )}
        </div>
      </div>

      {debugHistory.length > 0 && phase === 'testing' && <DebugOverlay debugHistory={debugHistory} />}
    </div>
  )
}

function AppBuilderView({ builds, onBuildsRefresh }) {
  const [prompt, setPrompt] = useState('Build a playable tic tac toe game app with score tracking, a reset button, and a clean responsive UI.')
  const [build, setBuild] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const generateApp = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/app-builder/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setBuild(payload.build)
      onBuildsRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const latest = build || builds?.builds?.[0]

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="App Builder Mode"
        title="Plain English to runnable software"
        description="This lane is for apps, games, websites, and product interfaces. It should not be forced through the automation workflow DAG."
      />
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Software prompt</h3>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={7}
            className="mt-4 w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm leading-6 outline-none focus:border-sky-400/50"
          />
          <button onClick={generateApp} disabled={loading} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200 disabled:opacity-50">
            <Gamepad2 size={16} /> {loading ? 'Generating...' : 'Generate app'}
          </button>
          {error && <div className="mt-4 rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-300">{error}</div>}
          {latest && (
            <div className="mt-5 space-y-3">
              <ReadinessRow label="Detected lane" value={latest.intent?.lane || 'app_builder'} ok={latest.intent?.lane === 'app_builder'} />
              <ReadinessRow label="Runnable artifact" value={latest.entry} ok />
              <ReadinessRow label="Generated files" value={String(latest.files?.length || 0)} ok />
            </div>
          )}
        </div>

        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Live preview</h3>
          {!latest ? <EmptyState title="No app generated" body="Generate a Tic Tac Toe app to test the new software-building lane." /> : (
            <iframe
              title={`${latest.title} preview`}
              srcDoc={latest.preview_html}
              sandbox="allow-scripts"
              className="mt-4 h-[520px] w-full rounded-lg border border-forge-border bg-white"
            />
          )}
        </div>
      </div>

      {latest && (
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
            <h3 className="text-sm font-semibold">Generated files</h3>
            <div className="mt-4 space-y-2">
              {latest.files.map((file) => (
                <div key={file.path} className="flex items-center justify-between rounded-lg border border-forge-border bg-forge-bg/50 px-3 py-2">
                  <span className="font-mono text-xs text-forge-text">{file.path}</span>
                  <span className="text-xs text-forge-muted">{file.size} bytes</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
            <h3 className="text-sm font-semibold">What this proves</h3>
            <div className="mt-4 space-y-2">
              {(latest.next_steps || []).map((step) => <ReadinessRow key={step} label={step} value="next" ok={step.includes('Preview')} />)}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ConnectorsView({ providerStatus, capabilities, connectorLifecycle, onRefresh }) {
  const services = providerStatus?.services || {}
  const [oauthResult, setOauthResult] = useState(null)
  const [oauthError, setOauthError] = useState(null)
  const [callbackForm, setCallbackForm] = useState({ state: '', code: '', exchange: false })
  const [credentialForm, setCredentialForm] = useState({ service: 'slack', label: 'Local Slack token', kind: 'access_token', secret: '' })
  const [rotationForm, setRotationForm] = useState({ credential_id: '', secret: '' })
  const [testingService, setTestingService] = useState(null)

  const startOAuth = async (service) => {
    setOauthError(null)
    setOauthResult(null)
    try {
      const res = await fetch(`${API_URL}/api/connectors/oauth/${service}/start`)
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setOauthResult(payload)
      setCallbackForm({ state: payload.state, code: '', exchange: false })
      onRefresh()
    } catch (err) {
      setOauthError(err.message)
    }
  }

  const completeOAuth = async () => {
    setOauthError(null)
    try {
      const res = await fetch(`${API_URL}/api/connectors/oauth/callback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...callbackForm, exchange: Boolean(callbackForm.exchange) }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setOauthResult(payload)
      onRefresh()
    } catch (err) {
      setOauthError(err.message)
    }
  }

  const storeCredential = async () => {
    setOauthError(null)
    try {
      const res = await fetch(`${API_URL}/api/vault/credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(credentialForm),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setOauthResult({ service: payload.service, status: 'credential_encrypted', scopes: [], auth_url: null })
      setCredentialForm({ ...credentialForm, secret: '' })
      onRefresh()
    } catch (err) {
      setOauthError(err.message)
    }
  }

  const rotateCredential = async () => {
    setOauthError(null)
    try {
      const res = await fetch(`${API_URL}/api/vault/credentials/${rotationForm.credential_id}/rotate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ secret: rotationForm.secret, metadata: { rotated_from_ui: true } }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setOauthResult({ service: payload.service, status: 'credential_rotated', scopes: [], auth_url: null })
      setRotationForm({ credential_id: '', secret: '' })
      onRefresh()
    } catch (err) {
      setOauthError(err.message)
    }
  }

  const testConnector = async (service, live = false) => {
    if (live && !window.confirm(`Run a read-only live probe for ${service}? This sends the stored credential to the provider to verify access.`)) return
    setOauthError(null)
    setTestingService(service)
    try {
      const res = await fetch(`${API_URL}/api/connectors/${service}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ live }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setOauthResult({ service, status: payload.test.status, scopes: [], auth_url: null, test: payload.test })
      onRefresh()
    } catch (err) {
      setOauthError(err.message)
    } finally {
      setTestingService(null)
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Connector Center"
        title="Know what is connected before generating code"
        description="ForgeFlow should detect missing credentials and ask for access before producing automations that depend on external systems."
      />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {Object.entries(services).map(([key, service]) => (
          <div key={key} className="rounded-lg border border-forge-border bg-forge-panel p-4">
            <div className="mb-4 flex items-center justify-between">
              <div className="grid h-9 w-9 place-items-center rounded-lg bg-sky-400/10 text-sky-300">
                <Blocks size={18} />
              </div>
              <span className={`rounded-full px-2 py-1 text-[11px] ${service.configured ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>
                {service.configured ? 'connected' : 'missing'}
              </span>
            </div>
            <h3 className="text-sm font-semibold">{service.name}</h3>
            <p className="mt-2 min-h-10 text-xs leading-5 text-forge-muted">
              Requires {service.required_env?.length ? service.required_env.join(', ') : 'no credentials'}
            </p>
            {service.oauth_supported && (
              <button
                onClick={() => startOAuth(key)}
                className="mt-4 inline-flex items-center gap-2 rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:border-sky-400/40 hover:text-sky-200"
              >
                <KeyRound size={14} /> Start OAuth
              </button>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <button onClick={() => testConnector(key, false)} disabled={testingService === key} className="inline-flex items-center gap-2 rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:border-sky-400/40 hover:text-sky-200 disabled:opacity-50">
                <ShieldCheck size={14} /> Dry check
              </button>
              {!['schema', 'approval'].includes(key) && (
                <button onClick={() => testConnector(key, true)} disabled={testingService === key} className="inline-flex items-center gap-2 rounded-lg border border-amber-400/30 px-3 py-2 text-xs text-amber-200 hover:bg-amber-400/10 disabled:opacity-50">
                  <Activity size={14} /> Live probe
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {(oauthResult || oauthError) && (
        <div className={`rounded-lg border p-4 text-sm ${oauthError ? 'border-red-400/30 bg-red-400/10 text-red-300' : 'border-sky-400/30 bg-sky-400/10 text-sky-100'}`}>
          {oauthError ? oauthError : (
            <div className="space-y-2">
              <div className="font-medium">{oauthResult.service} authorization {oauthResult.status}</div>
              {oauthResult.auth_url && <div className="break-all text-xs text-forge-muted">{oauthResult.auth_url}</div>}
              {oauthResult.scopes && <div className="text-xs text-forge-muted">Scopes: {oauthResult.scopes.join(', ')}</div>}
              {oauthResult.missing_env?.length ? <div className="text-xs text-amber-200">Missing OAuth env: {oauthResult.missing_env.join(', ')}</div> : null}
              {oauthResult.token_exchange?.stored_credentials?.length ? (
                <div className="text-xs text-emerald-200">Stored tokens: {oauthResult.token_exchange.stored_credentials.map((item) => item.kind).join(', ')}</div>
              ) : null}
              {oauthResult.test && (
                <div className="rounded-lg border border-forge-border bg-forge-bg/60 p-3 text-xs text-forge-muted">
                  Test mode: {oauthResult.test.mode} · {oauthResult.test.error || oauthResult.test.response?.message || 'completed'}
                </div>
              )}
              <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
                <input value={callbackForm.state} onChange={(event) => setCallbackForm({ ...callbackForm, state: event.target.value })} className="rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-xs text-forge-text outline-none" placeholder="state" />
                <input value={callbackForm.code} onChange={(event) => setCallbackForm({ ...callbackForm, code: event.target.value })} className="rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-xs text-forge-text outline-none" placeholder="provider auth code" />
                <button onClick={completeOAuth} className="rounded-lg border border-sky-400/30 px-3 py-2 text-xs text-sky-200">Record callback</button>
              </div>
              <label className="inline-flex items-center gap-2 text-xs text-forge-muted">
                <input type="checkbox" checked={callbackForm.exchange} onChange={(event) => setCallbackForm({ ...callbackForm, exchange: event.target.checked })} />
                Exchange code server-side and store returned tokens when OAuth client env is configured
              </label>
            </div>
          )}
        </div>
      )}

      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <h3 className="mb-4 text-sm font-semibold">Connector lifecycle</h3>
        <div className="grid gap-2 md:grid-cols-2">
          {(connectorLifecycle?.connectors || []).map((connector) => (
            <div key={connector.service} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">{connector.metadata?.name || connector.service}</div>
                <span className={`rounded-full px-2 py-1 text-[11px] ${connector.env_status?.configured ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>{connector.status}</span>
              </div>
              <p className="mt-2 text-xs text-forge-muted">Auth: {connector.auth_type} · Missing: {connector.env_status?.missing?.join(', ') || 'none'}</p>
              {connector.metadata?.vault_credential && <p className="mt-1 text-xs text-emerald-300">Vault credential available</p>}
            </div>
          ))}
        </div>
        {(connectorLifecycle?.oauth_sessions || []).length > 0 && (
          <div className="mt-5">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Recent OAuth sessions</h4>
            <div className="space-y-2">
              {connectorLifecycle.oauth_sessions.map((session) => (
                <div key={session.state} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3 text-xs text-forge-muted">
                  {session.service} · {session.status} · {session.state}
                </div>
              ))}
            </div>
          </div>
        )}
        {(connectorLifecycle?.connector_tests || []).length > 0 && (
          <div className="mt-5">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Recent connector tests</h4>
            <div className="grid gap-2 md:grid-cols-2">
              {connectorLifecycle.connector_tests.slice(0, 8).map((test) => (
                <div key={test.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3 text-xs text-forge-muted">
                  <div className="flex items-center justify-between gap-2">
                    <span>{test.service} · {test.mode}</span>
                    <span className={`rounded-full px-2 py-1 text-[10px] ${test.status === 'failed' ? 'bg-red-400/10 text-red-300' : test.status === 'connected' || test.status === 'ready' ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>{test.status}</span>
                  </div>
                  <div className="mt-1 truncate">{test.error || test.response?.message || test.created_at}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Encrypted credential vault</h3>
          <div className="mt-4 space-y-3">
            <input value={credentialForm.service} onChange={(event) => setCredentialForm({ ...credentialForm, service: event.target.value })} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" placeholder="service" />
            <input value={credentialForm.label} onChange={(event) => setCredentialForm({ ...credentialForm, label: event.target.value })} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" placeholder="label" />
            <input value={credentialForm.kind} onChange={(event) => setCredentialForm({ ...credentialForm, kind: event.target.value })} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" placeholder="kind" />
            <input value={credentialForm.secret} onChange={(event) => setCredentialForm({ ...credentialForm, secret: event.target.value })} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" placeholder="secret value" type="password" />
            <button onClick={storeCredential} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
              <LockKeyhole size={16} /> Store encrypted
            </button>
          </div>
        </div>
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Stored credentials</h3>
          {(connectorLifecycle?.credentials || []).length === 0 ? <EmptyState title="No vault credentials" body="Store connector tokens locally without exposing raw secret values in the UI." /> : (
            <div className="mt-4 space-y-2">
              {connectorLifecycle.credentials.map((credential) => (
                <div key={credential.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium">{credential.label}</div>
                    <span className="rounded-full bg-emerald-400/10 px-2 py-1 text-[11px] text-emerald-300">{credential.kind}</span>
                  </div>
                  <p className="mt-2 text-xs text-forge-muted">{credential.service} · {credential.masked}</p>
                </div>
              ))}
            </div>
          )}
          <div className="mt-5 rounded-lg border border-forge-border bg-forge-bg/50 p-3">
            <h4 className="text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Rotate credential</h4>
            <div className="mt-3 grid gap-2 md:grid-cols-[1fr_1fr_auto]">
              <input value={rotationForm.credential_id} onChange={(event) => setRotationForm({ ...rotationForm, credential_id: event.target.value })} className="rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-xs outline-none focus:border-sky-400/50" placeholder="credential id" />
              <input value={rotationForm.secret} onChange={(event) => setRotationForm({ ...rotationForm, secret: event.target.value })} className="rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-xs outline-none focus:border-sky-400/50" placeholder="new secret" type="password" />
              <button onClick={rotateCredential} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">Rotate</button>
            </div>
          </div>
          {(connectorLifecycle?.credential_audit || []).length > 0 && (
            <div className="mt-5">
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Rotation audit</h4>
              <div className="space-y-2">
                {connectorLifecycle.credential_audit.slice(0, 6).map((item) => (
                  <div key={item.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3 text-xs text-forge-muted">
                    {item.service} · {item.action} · {item.created_at}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <h3 className="mb-4 text-sm font-semibold">Capability registry</h3>
        <div className="grid gap-2 md:grid-cols-2">
          {(capabilities?.capabilities || []).map((capability) => (
            <div key={capability.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">{capability.label}</div>
                <span className="rounded-full bg-slate-400/10 px-2 py-1 text-[11px] text-slate-300">{capability.risk}</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-forge-muted">{capability.description}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function SchemaExplorerView() {
  const [schema, setSchema] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const inspectFile = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setLoading(true)
    setError(null)
    setSchema(null)
    const body = new FormData()
    body.append('file', file)
    try {
      const res = await fetch(`${API_URL}/api/schemas/inspect`, { method: 'POST', body })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setSchema(payload.schema)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Schema Explorer"
        title="Ground automations in real files"
        description="Upload CSV or XLSX data so ForgeFlow can inspect columns, sample rows, and field mappings before it plans a workflow."
      />
      <div className="rounded-lg border border-dashed border-sky-400/30 bg-sky-400/5 p-8">
        <label className="flex cursor-pointer flex-col items-center justify-center text-center">
          <Upload className="mb-4 text-sky-300" size={28} />
          <span className="text-sm font-medium">Upload CSV or XLSX</span>
          <span className="mt-2 max-w-md text-xs leading-5 text-forge-muted">ForgeFlow reads headers and a small sample locally through the backend. It does not invent columns.</span>
          <input type="file" accept=".csv,.xlsx" className="hidden" onChange={inspectFile} />
        </label>
      </div>

      {loading && <div className="rounded-lg border border-forge-border bg-forge-panel p-4 text-sm text-forge-muted">Inspecting schema...</div>}
      {error && <div className="rounded-lg border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-300">{error}</div>}
      {schema && (
        <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
          <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
            <h3 className="text-sm font-semibold">{schema.filename}</h3>
            <p className="mt-1 text-xs text-forge-muted">{schema.file_type.toUpperCase()} · {schema.columns.length} columns</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {schema.columns.map((column) => (
                <span key={column} className="rounded-md border border-forge-border bg-forge-bg px-2 py-1 text-xs">{column}</span>
              ))}
            </div>
            <h4 className="mt-5 text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Suggested mappings</h4>
            <div className="mt-3 space-y-2">
              {Object.entries(schema.mapping_suggestions || {}).map(([target, column]) => (
                <ReadinessRow key={target} label={target} value={column} ok />
              ))}
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border border-forge-border bg-forge-panel">
            <div className="border-b border-forge-border px-4 py-3 text-sm font-semibold">Sample rows</div>
            <div className="overflow-auto">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-forge-bg text-forge-muted">
                  <tr>{schema.columns.map((column) => <th key={column} className="px-3 py-2 font-medium">{column}</th>)}</tr>
                </thead>
                <tbody>
                  {schema.sample_rows.map((row, idx) => (
                    <tr key={idx} className="border-t border-forge-border">
                      {schema.columns.map((column) => <td key={column} className="max-w-[220px] truncate px-3 py-2 text-forge-text">{row[column]}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ApprovalsView({ approvals, onRefresh }) {
  const [form, setForm] = useState({
    title: 'Preview outbound Slack message',
    workflow_id: 'workflow-demo',
    action_type: 'slack.postMessage',
    risk: 'external_write',
    preview: '{ "channel": "#ops", "text": "Draft message awaiting approval" }',
  })
  const [error, setError] = useState(null)

  const createApproval = async () => {
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/approvals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: form.title,
          workflow_id: form.workflow_id,
          action_type: form.action_type,
          risk: form.risk,
          preview: JSON.parse(form.preview || '{}'),
        }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
    } catch (err) {
      setError(err.message)
    }
  }

  const decide = async (approvalId, decision) => {
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/approvals/${approvalId}/${decision}`, { method: 'POST' })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Approval Inbox"
        title="External actions should pause here"
        description="Emails, Slack posts, record writes, deletions, and permission changes should be previewed and approved before execution."
      />
      <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Create action preview</h3>
          <div className="mt-4 space-y-3">
            {[
              ['title', 'Title'],
              ['workflow_id', 'Workflow ID'],
              ['action_type', 'Action type'],
              ['risk', 'Risk'],
            ].map(([key, label]) => (
              <label key={key} className="block text-xs text-forge-muted">
                {label}
                <input
                  value={form[key]}
                  onChange={(event) => setForm({ ...form, [key]: event.target.value })}
                  className="mt-1 w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm text-forge-text outline-none focus:border-sky-400/50"
                />
              </label>
            ))}
            <label className="block text-xs text-forge-muted">
              Preview JSON
              <textarea
                value={form.preview}
                onChange={(event) => setForm({ ...form, preview: event.target.value })}
                rows={5}
                className="mt-1 w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 font-mono text-xs text-forge-text outline-none focus:border-sky-400/50"
              />
            </label>
            <button onClick={createApproval} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
              <ClipboardCheck size={16} /> Queue approval
            </button>
            {error && <div className="text-xs text-red-300">{error}</div>}
          </div>
        </div>

        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Pending approvals</h3>
          {(approvals?.pending || []).length === 0 ? (
            <EmptyState title="No approvals waiting" body="Generated workflows will place risky external actions here before they run." />
          ) : (
            <div className="mt-4 space-y-3">
              {(approvals?.pending || []).map((item) => (
                <div key={item.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="text-sm font-medium">{item.title}</div>
                      <div className="mt-1 text-xs text-forge-muted">{item.workflow_id || 'unassigned'} · {item.action_type}</div>
                    </div>
                    <span className="rounded-full bg-amber-400/10 px-2 py-1 text-[11px] text-amber-300">{item.risk}</span>
                  </div>
                  <pre className="mt-3 max-h-28 overflow-auto rounded-lg bg-black/20 p-3 text-xs text-forge-muted">{JSON.stringify(item.preview || {}, null, 2)}</pre>
                  <div className="mt-3 flex gap-2">
                    <button onClick={() => decide(item.id, 'approve')} className="rounded-lg bg-emerald-300 px-3 py-2 text-xs font-semibold text-slate-950">Approve</button>
                    <button onClick={() => decide(item.id, 'reject')} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-forge-text">Reject</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {(approvals?.policy || []).map((item) => (
          <div key={item} className="flex items-start gap-3 rounded-lg border border-forge-border bg-forge-panel p-4">
            <ShieldCheck className="mt-0.5 text-emerald-300" size={18} />
            <p className="text-sm leading-6 text-forge-muted">{item}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function RunsView({ runs, observability, onRefresh }) {
  const [selectedRun, setSelectedRun] = useState(null)
  const [queueForm, setQueueForm] = useState({ workflow_id: 'workflow-demo', priority: 5, max_attempts: 3 })
  const [queueError, setQueueError] = useState(null)
  const [workerStatus, setWorkerStatus] = useState(null)
  const queue = runs?.queue || []

  const loadWorkerStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/runs/queue/worker`)
      const payload = await res.json()
      if (res.ok) setWorkerStatus(payload)
    } catch {
      setWorkerStatus(null)
    }
  }, [])

  useEffect(() => {
    loadWorkerStatus()
  }, [loadWorkerStatus])

  const enqueue = async () => {
    setQueueError(null)
    try {
      const res = await fetch(`${API_URL}/api/runs/queue`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(queueForm),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
    } catch (err) {
      setQueueError(err.message)
    }
  }

  const processQueue = async (queueId) => {
    setQueueError(null)
    try {
      const res = await fetch(`${API_URL}/api/runs/queue/${queueId}/process`, { method: 'POST' })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
    } catch (err) {
      setQueueError(err.message)
    }
  }

  const processDueQueue = async () => {
    setQueueError(null)
    try {
      const res = await fetch(`${API_URL}/api/runs/queue/process-due`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 5 }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
      loadWorkerStatus()
    } catch (err) {
      setQueueError(err.message)
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Operations"
        title="Run history"
        description="Every generated automation needs a visible audit trail: inputs, tests, status, logs, retries, and replay."
      />
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <RunList runs={runs?.runs || []} onRefresh={onRefresh} onSelectRun={setSelectedRun} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Queue workflow run</h3>
          <div className="mt-4 space-y-3">
            <input value={queueForm.workflow_id} onChange={(event) => setQueueForm({ ...queueForm, workflow_id: event.target.value })} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" />
            <input value={queueForm.priority} onChange={(event) => setQueueForm({ ...queueForm, priority: Number(event.target.value) })} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" type="number" />
            <input value={queueForm.max_attempts} onChange={(event) => setQueueForm({ ...queueForm, max_attempts: Number(event.target.value) })} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" type="number" />
            <button onClick={enqueue} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
              <TimerReset size={16} /> Enqueue
            </button>
            {queueError && <div className="text-xs text-red-300">{queueError}</div>}
          </div>
        </div>
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Durable queue</h3>
              <p className="mt-1 text-xs text-forge-muted">
                Worker {workerStatus?.enabled ? 'enabled' : 'manual'} · {workerStatus?.due?.length ?? 0} due now
              </p>
            </div>
            <button onClick={processDueQueue} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">Process due</button>
          </div>
          {queue.length === 0 ? <EmptyState title="Queue empty" body="Queued workflow runs will retry and keep failure reasons." /> : (
            <div className="mt-4 space-y-2">
              {queue.map((item) => (
                <div key={item.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                  <div className="grid gap-2 md:grid-cols-[1fr_auto_auto]">
                    <div className="text-sm">{item.workflow_id}</div>
                    <span className="text-xs text-forge-muted">{item.status}</span>
                    <button onClick={() => processQueue(item.id)} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">Process</button>
                  </div>
                  {item.last_error && <p className="mt-2 text-xs text-amber-200">{item.last_error}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Reliability signals</h3>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <Metric label="Queued" value={observability?.queue?.queued ?? 0} Icon={TimerReset} tone="sky" />
            <Metric label="Running" value={observability?.queue?.running ?? 0} Icon={Activity} tone="green" />
            <Metric label="Dead letters" value={observability?.queue?.dead_letter ?? 0} Icon={Wrench} tone="amber" />
          </div>
        </div>
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Alerts and observability</h3>
          {(observability?.events || []).length === 0 ? <EmptyState title="No events yet" body="Queue, trigger, runtime, deployment, and repair events are recorded here." /> : (
            <div className="mt-4 max-h-72 space-y-2 overflow-auto">
              {observability.events.slice(0, 10).map((event) => (
                <div key={event.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium">{event.subject}</div>
                    <span className={`rounded-full px-2 py-1 text-[11px] ${event.severity === 'error' ? 'bg-red-400/10 text-red-300' : 'bg-sky-400/10 text-sky-200'}`}>{event.severity}</span>
                  </div>
                  <div className="mt-1 text-xs text-forge-muted">{event.source} · {event.event_type} · {event.created_at}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {selectedRun && (
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Run log detail</h3>
          <div className="mt-2 text-xs text-forge-muted">{selectedRun.run_id} · attempt {selectedRun.attempt} · return {selectedRun.return_code}</div>
          <pre className="mt-4 max-h-72 overflow-auto rounded-lg bg-black/30 p-4 text-xs text-forge-muted">{`STDOUT\n${selectedRun.stdout || ''}\n\nSTDERR\n${selectedRun.stderr || ''}`}</pre>
        </div>
      )}
    </div>
  )
}

function RunList({ runs, onRefresh, onSelectRun }) {
  const [retrying, setRetrying] = useState(null)
  const [error, setError] = useState(null)

  const retryRun = async (runId) => {
    setRetrying(runId)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/runs/${runId}/retry`, { method: 'POST' })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setRetrying(null)
    }
  }

  const loadRun = async (runId) => {
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/runs/${runId}`)
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onSelectRun(payload)
    } catch (err) {
      setError(err.message)
    }
  }

  if (!runs?.length) return <EmptyState title="No runs recorded" body="Run a workflow to populate operational history." />
  return (
    <div className="space-y-2">
      {runs.map((run) => (
        <div key={run.run_id || run.workflow_id} className="grid gap-3 rounded-lg border border-forge-border bg-forge-bg/50 p-3 md:grid-cols-[1fr_auto_auto_auto] md:items-center">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{run.name}</div>
            <div className="mt-1 text-xs text-forge-muted">{run.workflow_id} · {run.created_at}</div>
          </div>
          <span className={`rounded-full px-2 py-1 text-[11px] ${run.success ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>
            {run.success ? 'success' : 'needs review'}
          </span>
          <span className="text-xs text-forge-muted">{run.tests_passed}/{run.tests_total} tests</span>
          {run.run_id && (
            <div className="flex gap-2">
              <button onClick={() => loadRun(run.run_id)} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">Logs</button>
              <button onClick={() => retryRun(run.run_id)} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">
                {retrying === run.run_id ? 'Retrying...' : 'Retry'}
              </button>
            </div>
          )}
        </div>
      ))}
      {error && <div className="rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-300">{error}</div>}
    </div>
  )
}

function TriggersView({ triggers, onRefresh }) {
  const [form, setForm] = useState({
    workflow_id: 'workflow-demo',
    trigger_type: 'webhook',
    config: '{ "path": "/webhooks/hr-onboarding", "method": "POST" }',
  })
  const [error, setError] = useState(null)

  const createTrigger = async () => {
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/triggers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflow_id: form.workflow_id,
          trigger_type: form.trigger_type,
          config: JSON.parse(form.config || '{}'),
          status: 'paused',
        }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
    } catch (err) {
      setError(err.message)
    }
  }

  const setTriggerState = async (triggerId, action) => {
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/triggers/${triggerId}/${action}`, { method: 'POST' })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
    } catch (err) {
      setError(err.message)
    }
  }

  const invokeTrigger = async (triggerId) => {
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/webhooks/${triggerId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: 'manual-ui-test', sent_at: new Date().toISOString() }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Trigger Engine"
        title="Make automations start from events, not button clicks"
        description="Register webhook, schedule, and manual triggers against generated workflows before they are activated in production."
      />
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Create trigger</h3>
          <div className="mt-4 space-y-3">
            <input value={form.workflow_id} onChange={(event) => setForm({ ...form, workflow_id: event.target.value })} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" placeholder="workflow_id" />
            <select value={form.trigger_type} onChange={(event) => setForm({ ...form, trigger_type: event.target.value })} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50">
              <option value="webhook">webhook</option>
              <option value="schedule">schedule</option>
              <option value="manual">manual</option>
            </select>
            <textarea value={form.config} onChange={(event) => setForm({ ...form, config: event.target.value })} rows={6} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 font-mono text-xs outline-none focus:border-sky-400/50" />
            <button onClick={createTrigger} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
              <TimerReset size={16} /> Save trigger
            </button>
            {error && <div className="text-xs text-red-300">{error}</div>}
          </div>
        </div>
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Registered triggers</h3>
          {(triggers?.triggers || []).length === 0 ? (
            <EmptyState title="No triggers yet" body="Create a trigger when a workflow should run from a webhook, schedule, or manual launch." />
          ) : (
            <div className="mt-4 space-y-2">
              {(triggers?.triggers || []).map((trigger) => (
                <div key={trigger.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium">{trigger.workflow_id}</div>
                    <span className="rounded-full bg-slate-400/10 px-2 py-1 text-[11px] text-slate-300">{trigger.status}</span>
                  </div>
                  <div className="mt-1 text-xs text-forge-muted">{trigger.trigger_type} · {trigger.created_at}</div>
                  <pre className="mt-3 max-h-24 overflow-auto rounded-lg bg-black/20 p-3 text-xs text-forge-muted">{JSON.stringify(trigger.config || {}, null, 2)}</pre>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button onClick={() => setTriggerState(trigger.id, trigger.status === 'active' ? 'pause' : 'activate')} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">
                      {trigger.status === 'active' ? 'Pause' : 'Activate'}
                    </button>
                    <button onClick={() => invokeTrigger(trigger.id)} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">
                      Invoke webhook
                    </button>
                    <span className="rounded-lg bg-forge-panel px-3 py-2 text-xs text-forge-muted">POST /api/webhooks/{trigger.id}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <h3 className="text-sm font-semibold">Trigger events</h3>
        {(triggers?.events || []).length === 0 ? <EmptyState title="No trigger events" body="Webhook and schedule invocations will appear here with run links." /> : (
          <div className="mt-4 space-y-2">
            {triggers.events.map((event) => (
              <div key={event.id} className="grid gap-2 rounded-lg border border-forge-border bg-forge-bg/50 p-3 md:grid-cols-[1fr_auto_auto]">
                <div className="text-sm">{event.workflow_id}</div>
                <span className="text-xs text-forge-muted">{event.status}</span>
                <span className="text-xs text-forge-muted">{event.created_at}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function DeploymentsView({ targets, plans, onPlansRefresh }) {
  const [workflowId, setWorkflowId] = useState('workflow-demo')
  const [target, setTarget] = useState('local_docker')
  const [plan, setPlan] = useState(null)
  const [error, setError] = useState(null)
  const [dispatching, setDispatching] = useState(false)
  const targetList = targets?.targets || []

  const createPlan = async () => {
    setError(null)
    setPlan(null)
    try {
      const res = await fetch(`${API_URL}/api/deploy/plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow_id: workflowId, target }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setPlan(payload)
      onPlansRefresh()
    } catch (err) {
      setError(err.message)
    }
  }

  const activatePlan = async (planId) => {
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/deploy/plans/${planId}/activate`, { method: 'POST' })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setPlan(payload)
      onPlansRefresh()
    } catch (err) {
      setError(err.message)
    }
  }

  const dispatchPlan = async (planId) => {
    setError(null)
    setDispatching(true)
    try {
      const res = await fetch(`${API_URL}/api/deploy/plans/${planId}/dispatch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'dry_run' }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setPlan((current) => ({ ...(current || {}), job: payload.job }))
      onPlansRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setDispatching(false)
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Deployment Targets"
        title="Convert generated projects into planned production releases"
        description="Deployment plans validate files, secrets, tests, artifacts, and activation steps before anything is promoted."
      />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {targetList.map((item) => (
          <div key={item.id} className="rounded-lg border border-forge-border bg-forge-panel p-4">
            <Cloud className="mb-4 text-sky-300" size={20} />
            <div className="text-sm font-semibold">{item.label || item.name}</div>
            <p className="mt-2 min-h-16 text-xs leading-5 text-forge-muted">{item.description}</p>
            <span className={`mt-3 inline-flex rounded-full px-2 py-1 text-[11px] ${item.status === 'available' ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>{item.status}</span>
            {item.env_status?.missing?.length ? <div className="mt-2 text-[11px] text-amber-200">Needs {item.env_status.missing.join(', ')}</div> : null}
            <div className="mt-3 space-y-1">
              {(item.provider_health?.checks || []).map((check) => (
                <div key={check.id} className={`text-[11px] ${check.status === 'pass' ? 'text-emerald-300' : 'text-amber-200'}`}>{check.label}: {check.detail}</div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Create deployment plan</h3>
          <div className="mt-4 space-y-3">
            <input value={workflowId} onChange={(event) => setWorkflowId(event.target.value)} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" />
            <select value={target} onChange={(event) => setTarget(event.target.value)} className="w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50">
              {targetList.map((item) => <option key={item.id} value={item.id}>{item.label || item.name}</option>)}
            </select>
            <button onClick={createPlan} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
              <Rocket size={16} /> Plan release
            </button>
            {error && <div className="text-xs text-red-300">{error}</div>}
          </div>
        </div>
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Plan detail</h3>
          {!plan ? <EmptyState title="No deployment plan selected" body="Pick a workflow and target to generate a promotion checklist." /> : (
            <div className="mt-4 space-y-3">
              <div className="text-sm font-medium">{plan.plan.workflow_id} to {plan.plan.target}</div>
              {plan.plan.steps.map((step) => <ReadinessRow key={step} label={step} value="required" ok />)}
              {(plan.plan.readiness?.blocking || []).map((blocker) => <ReadinessRow key={blocker} label={blocker} value="blocking" ok={false} />)}
              <div className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Artifacts</div>
                {Object.keys(plan.plan.artifacts || {}).map((name) => <div key={name} className="text-xs text-sky-200">{name}</div>)}
              </div>
              <div className="rounded-lg bg-amber-400/10 p-3 text-xs text-amber-200">{plan.plan.next_action}</div>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => activatePlan(plan.id)} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">Activate plan</button>
                <button onClick={() => dispatchPlan(plan.id)} className="rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">{dispatching ? 'Preparing...' : 'Prepare provider dispatch'}</button>
              </div>
              {plan.job && (
                <div className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Provider dispatch</div>
                  <div className="text-xs text-forge-muted">{plan.job.status} · {plan.job.provider_request?.provider} · {plan.job.provider_request?.operation}</div>
                  {plan.job.blockers?.length ? <div className="mt-2 text-xs text-amber-200">Blocked by {plan.job.blockers.join(', ')}</div> : null}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <h3 className="text-sm font-semibold">Recent deployment plans</h3>
        {(plans?.plans || []).length === 0 ? <EmptyState title="No deployment plans" body="Generate a deployment plan to track production readiness." /> : (
          <div className="mt-4 space-y-2">
            {plans.plans.map((item) => (
              <div key={item.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                <div className="grid gap-2 md:grid-cols-[1fr_auto_auto]">
                  <div className="text-sm">{item.workflow_id} to {item.target}</div>
                  <span className="text-xs text-forge-muted">{item.status}</span>
                  <span className="text-xs text-forge-muted">{item.created_at}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {Object.keys(item.plan?.artifacts || {}).map((name) => <span key={name} className="rounded bg-sky-400/10 px-2 py-1 text-[11px] text-sky-200">{name}</span>)}
                  {(item.plan?.readiness?.blocking || []).map((blocker) => <span key={blocker} className="rounded bg-amber-400/10 px-2 py-1 text-[11px] text-amber-200">{blocker}</span>)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <h3 className="text-sm font-semibold">Deployment activations</h3>
        {(plans?.activations || []).length === 0 ? <EmptyState title="No activations yet" body="Activating a plan records the target, artifacts, and readiness blockers." /> : (
          <div className="mt-4 space-y-2">
            {plans.activations.map((activation) => (
              <div key={activation.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                <div className="grid gap-2 md:grid-cols-[1fr_auto_auto]">
                  <div className="text-sm">{activation.workflow_id} to {activation.target}</div>
                  <span className="text-xs text-forge-muted">{activation.status}</span>
                  <span className="text-xs text-forge-muted">{activation.created_at}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {Object.keys(activation.artifacts || {}).map((name) => <span key={name} className="rounded bg-sky-400/10 px-2 py-1 text-[11px] text-sky-200">{name}</span>)}
                  {(activation.blockers || []).map((blocker) => <span key={blocker} className="rounded bg-amber-400/10 px-2 py-1 text-[11px] text-amber-200">{blocker}</span>)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <h3 className="text-sm font-semibold">Provider dispatch jobs</h3>
        {(plans?.jobs || []).length === 0 ? <EmptyState title="No dispatch jobs yet" body="Preparing a provider dispatch records the exact external action envelope before any live deploy call." /> : (
          <div className="mt-4 space-y-2">
            {plans.jobs.map((job) => (
              <div key={job.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                <div className="grid gap-2 md:grid-cols-[1fr_auto_auto]">
                  <div className="text-sm">{job.workflow_id} to {job.target}</div>
                  <span className="text-xs text-forge-muted">{job.status}</span>
                  <span className="text-xs text-forge-muted">{job.created_at}</span>
                </div>
                <div className="mt-2 text-xs text-forge-muted">{job.provider_request?.provider} · {job.provider_request?.operation}</div>
                {(job.blockers || []).length ? <div className="mt-2 text-xs text-amber-200">{job.blockers.join(', ')}</div> : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function IngestionsView({ ingestions, onCapabilitiesRefresh, onIngestionsRefresh }) {
  const [searchPrompt, setSearchPrompt] = useState('Find an API to create customer support tickets and update CRM contacts.')
  const [discovery, setDiscovery] = useState(null)
  const [openApiText, setOpenApiText] = useState('{\n  "openapi": "3.0.0",\n  "info": { "title": "HR Platform", "version": "1.0" },\n  "paths": {\n    "/candidates": { "get": { "operationId": "listCandidates", "summary": "List candidates" } },\n    "/employees": { "post": { "operationId": "createEmployee", "summary": "Create employee" } }\n  }\n}')
  const [mcpText, setMcpText] = useState('{\n  "name": "hr-records-mcp",\n  "tools": [\n    { "name": "lookup_employee", "description": "Find an employee by email", "input_schema": { "email": "string" } },\n    { "name": "create_onboarding_task", "description": "Create an onboarding task", "input_schema": { "employee_id": "string" } }\n  ]\n}')
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)

  const searchApis = async () => {
    setMessage(null)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/discovery/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: searchPrompt, include_public: true }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setDiscovery(payload)
      setMessage(`Found ${payload.local_capabilities.length} local matches and ${payload.public_apis.length} public OpenAPI candidates`)
    } catch (err) {
      setError(err.message)
    }
  }

  const importCandidate = async (candidate) => {
    setMessage(null)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/discovery/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url: candidate.source_url }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setMessage(`${payload.ingestion.name} imported ${payload.capabilities.length} capabilities from ${candidate.title}`)
      onCapabilitiesRefresh()
      onIngestionsRefresh()
    } catch (err) {
      setError(err.message)
    }
  }

  const ingest = async (kind) => {
    setMessage(null)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/${kind === 'openapi' ? 'openapi' : 'mcp'}/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: kind === 'openapi' ? openApiText : mcpText,
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setMessage(`${payload.name} imported ${payload.capabilities.length} capabilities`)
      onCapabilitiesRefresh()
      onIngestionsRefresh()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Adapter Ingestion"
        title="Teach ForgeFlow tools before the user writes prompts"
        description="Import OpenAPI specs and MCP tool manifests so planning uses real operations, input schemas, and risk labels instead of hallucinated connectors."
      />
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <h3 className="text-sm font-semibold">Real API discovery</h3>
        <p className="mt-2 text-sm leading-6 text-forge-muted">Search imported capabilities and the public APIs.guru OpenAPI directory, then import a selected spec into ForgeFlow.</p>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <input value={searchPrompt} onChange={(event) => setSearchPrompt(event.target.value)} className="rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm outline-none focus:border-sky-400/50" />
          <button onClick={searchApis} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
            <Search size={16} /> Search APIs
          </button>
        </div>
        {discovery && (
          <div className="mt-5 grid gap-4 xl:grid-cols-2">
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Local capability matches</h4>
              <div className="mt-3 space-y-2">
                {discovery.local_capabilities.length === 0 ? <EmptyState title="No local matches" body="Import an OpenAPI spec or MCP manifest to expand local planning." /> : discovery.local_capabilities.map((item) => (
                  <div key={item.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">{item.label}</div>
                      <span className="rounded-full bg-emerald-400/10 px-2 py-1 text-[11px] text-emerald-300">{Math.round(item.score * 100)}%</span>
                    </div>
                    <p className="mt-2 text-xs text-forge-muted">{item.description}</p>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-[0.16em] text-forge-muted">Public OpenAPI candidates</h4>
              <div className="mt-3 space-y-2">
                {discovery.public_apis.length === 0 ? <EmptyState title="No public candidates" body={discovery.public_error || 'Try a system or provider name such as Stripe, GitHub, Twilio, Zendesk, or HubSpot.'} /> : discovery.public_apis.map((item) => (
                  <div key={item.source_url} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">{item.title}</div>
                      <span className="rounded-full bg-sky-400/10 px-2 py-1 text-[11px] text-sky-200">{Math.round(item.score * 100)}%</span>
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs text-forge-muted">{item.description}</p>
                    <button onClick={() => importCandidate(item)} className="mt-3 rounded-lg border border-forge-border px-3 py-2 text-xs text-forge-muted hover:text-sky-200">Import OpenAPI spec</button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">OpenAPI upload/import</h3>
          <textarea value={openApiText} onChange={(event) => setOpenApiText(event.target.value)} rows={14} className="mt-4 w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 font-mono text-xs outline-none focus:border-sky-400/50" />
          <button onClick={() => ingest('openapi')} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
            <Upload size={16} /> Import OpenAPI
          </button>
        </div>
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">MCP adapter manifest</h3>
          <textarea value={mcpText} onChange={(event) => setMcpText(event.target.value)} rows={14} className="mt-4 w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 font-mono text-xs outline-none focus:border-sky-400/50" />
          <button onClick={() => ingest('mcp')} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
            <PlugZap size={16} /> Import MCP
          </button>
        </div>
      </div>
      {(message || error) && <div className={`rounded-lg border p-4 text-sm ${error ? 'border-red-400/30 bg-red-400/10 text-red-300' : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'}`}>{error || message}</div>}
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <h3 className="text-sm font-semibold">Imported adapters</h3>
        {(ingestions?.ingestions || []).length === 0 ? <EmptyState title="No adapters imported" body="Import an OpenAPI spec or MCP manifest to add grounded capabilities." /> : (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {(ingestions?.ingestions || []).map((item) => (
              <div key={item.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium">{item.name}</div>
                  <span className="rounded-full bg-sky-400/10 px-2 py-1 text-[11px] text-sky-300">{item.source_type}</span>
                </div>
                <div className="mt-2 text-xs text-forge-muted">{item.capabilities.length} capabilities · {item.created_at}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function RuntimeView({ specs, adapters, runtimeRuns, onSpecsRefresh, onRunsRefresh, onGapsRefresh }) {
  const [prompt, setPrompt] = useState('Automate HR onboarding from an Excel sheet, draft a Gmail welcome email, post a Slack announcement, and append a Google Sheets tracking row.')
  const [activeSpec, setActiveSpec] = useState(null)
  const [conversation, setConversation] = useState(null)
  const [autopilot, setAutopilot] = useState(null)
  const [exports, setExports] = useState([])
  const [validations, setValidations] = useState([])
  const [repairs, setRepairs] = useState([])
  const [executionPlan, setExecutionPlan] = useState(null)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const askConversation = async () => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/challenge/conversation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setConversation(payload.conversation)
      setMessage(`Found ${payload.conversation.process_steps.length} business steps and ${payload.conversation.questions.length} clarification questions`)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const runAutopilot = async () => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/autopilot/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, platforms: ['forgeflow', 'n8n', 'zapier', 'github_actions'] }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      const result = payload.autopilot
      setAutopilot(result)
      setConversation(result.conversation)
      setActiveSpec(result.spec)
      setExports(result.exports)
      setValidations(result.validations)
      setRepairs(result.repair ? [result.repair] : [])
      setExecutionPlan(null)
      setMessage(`Autopilot ${result.readiness.verdict}: ${result.spec.steps.length} steps, ${result.exports.length} exports, dry-run ${result.dry_run.status}`)
      onSpecsRefresh()
      onRunsRefresh()
      onGapsRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const compileSpec = async () => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/specs/compile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setActiveSpec(payload.spec)
      setExecutionPlan(null)
      setMessage(`Compiled ${payload.spec.steps.length} steps with ${payload.spec.approval_gates.length} approval gates`)
      onSpecsRefresh()
      onGapsRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const dryRunSpec = async (specId) => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/runtime/specs/${specId}/dry-run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ inputs: { source: 'runtime-ui' } }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setMessage(`Dry-run ${payload.run.status}: ${payload.run.steps.length} step ledger entries`)
      onRunsRefresh()
      onGapsRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const planExecution = async (specId) => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/runtime/specs/${specId}/execution-plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: false, inputs: { source: 'runtime-ui-plan' } }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setExecutionPlan(payload.plan)
      setMessage(`Execution plan ${payload.plan.ready ? 'ready' : 'blocked'}: ${payload.plan.steps.length} connector steps checked`)
      onGapsRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const executeLiveSpec = async (specId) => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/runtime/specs/${specId}/execute-live`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: true, inputs: { source: 'runtime-ui-approved' } }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setMessage(`Live execution ${payload.run.status}: ${payload.run.steps.length} step ledger entries`)
      onRunsRefresh()
      onGapsRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const exportSpec = async (specId, platform) => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/specs/${specId}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setExports((items) => [payload.export, ...items].slice(0, 6))
      setMessage(`Exported ${payload.export.platform} artifact`)
      onGapsRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const validateAdapter = async (adapterId) => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/connectors/adapters/${adapterId}/validate`, { method: 'POST' })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setValidations((items) => [payload.validation, ...items.filter((item) => item.adapter_id !== adapterId)].slice(0, 8))
      setMessage(`${adapterId} validation: ${payload.validation.status}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const repairRun = async (runId) => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/runtime/runs/${runId}/repair`, { method: 'POST' })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setRepairs((items) => [payload.repair, ...items].slice(0, 6))
      setMessage(`Repair plan created with ${payload.repair.actions.length} actions`)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const runHrDemo = async () => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      const res = await fetch(`${API_URL}/api/demo/hr-onboarding`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setConversation(payload.conversation)
      setActiveSpec(payload.spec)
      setExports(payload.exports)
      setValidations(payload.validations)
      setRepairs([payload.repair])
      setExecutionPlan(null)
      setMessage(`HR onboarding demo generated ${payload.spec.steps.length} steps, ${payload.exports.length} exports, and a ${payload.run.status} dry-run`)
      onSpecsRefresh()
      onRunsRefresh()
      onGapsRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const latestSpec = activeSpec || specs?.specs?.[0]
  const runs = runtimeRuns?.runs || []

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Prompt to production loop"
        title="Business request to tested automation"
        description="Collect missing facts in plain English, compile a grounded spec, validate connectors, export to workflow platforms, dry-run every step, and repair blocked runs."
      />
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Requirement conversation</h3>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={6}
            className="mt-4 w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm leading-6 outline-none focus:border-sky-400/50"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <button onClick={runAutopilot} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200 disabled:opacity-50">
              <Sparkles size={16} /> Run autopilot
            </button>
            <button onClick={askConversation} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-forge-border px-4 py-2 text-sm text-forge-muted hover:text-sky-200 disabled:opacity-50">
              <Search size={16} /> Ask smart questions
            </button>
            <button onClick={compileSpec} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-forge-border px-4 py-2 text-sm text-forge-muted hover:text-sky-200 disabled:opacity-50">
              <Workflow size={16} /> Compile spec
            </button>
            {latestSpec && (
              <button onClick={() => dryRunSpec(latestSpec.id)} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-forge-border px-4 py-2 text-sm text-forge-muted hover:text-sky-200 disabled:opacity-50">
                <Play size={16} /> Dry-run spec
              </button>
            )}
            {latestSpec && (
              <button onClick={() => planExecution(latestSpec.id)} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-forge-border px-4 py-2 text-sm text-forge-muted hover:text-sky-200 disabled:opacity-50">
                <ShieldCheck size={16} /> Plan live run
              </button>
            )}
            {latestSpec && (
              <button onClick={() => executeLiveSpec(latestSpec.id)} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-2 text-sm text-amber-200 hover:bg-amber-400/15 disabled:opacity-50">
                <ShieldCheck size={16} /> Execute approved live
              </button>
            )}
            <button onClick={runHrDemo} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-4 py-2 text-sm text-emerald-200 hover:bg-emerald-400/15 disabled:opacity-50">
              <Rocket size={16} /> Run HR demo
            </button>
          </div>
          {(message || error) && <div className={`mt-4 rounded-lg border p-3 text-xs ${error ? 'border-red-400/30 bg-red-400/10 text-red-300' : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'}`}>{error || message}</div>}
          {conversation && (
            <div className="mt-4 rounded-lg border border-forge-border bg-forge-bg/50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-forge-muted">Plain-English plan</div>
              <div className="mt-3 space-y-2">
                {conversation.process_steps.map((step) => <div key={step} className="text-sm text-forge-text">{step}</div>)}
              </div>
              {conversation.questions.length ? (
                <div className="mt-4 rounded-lg bg-amber-400/10 p-3">
                  <div className="text-xs font-medium text-amber-200">Questions before live execution</div>
                  <div className="mt-2 space-y-1">
                    {conversation.questions.map((question) => <div key={question} className="text-xs text-amber-100">{question}</div>)}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Autopilot verdict</h3>
          {!autopilot ? <EmptyState title="No autopilot run yet" body="Run autopilot to chain discovery, compile, validation, dry-run, export, repair, and readiness in one pass." /> : (
            <div className="mt-4 space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded bg-sky-400/10 px-2 py-1 text-[11px] text-sky-200">{autopilot.readiness.verdict}</span>
                <span className="rounded bg-forge-bg px-2 py-1 text-[11px] text-forge-muted">{autopilot.readiness.score}% readiness</span>
                <span className={`rounded px-2 py-1 text-[11px] ${autopilot.readiness.live_execution_ready ? 'bg-emerald-400/10 text-emerald-200' : 'bg-amber-400/10 text-amber-200'}`}>
                  {autopilot.readiness.live_execution_ready ? 'live ready' : 'live blocked'}
                </span>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <Metric label="Discovered APIs" value={autopilot.discovery.public_apis.length + autopilot.discovery.local_capabilities.length} Icon={Search} tone="sky" />
                <Metric label="Validated connectors" value={autopilot.validations.length} Icon={ShieldCheck} tone="emerald" />
                <Metric label="Exports" value={autopilot.exports.length} Icon={Cloud} tone="amber" />
              </div>
              <div className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-forge-muted">Production contract</div>
                <div className="mt-3 grid gap-2 md:grid-cols-2">
                  <ReadinessRow label="Generated from prompt" value={autopilot.production_contract.generated_from_prompt ? 'yes' : 'no'} ok={autopilot.production_contract.generated_from_prompt} />
                  <ReadinessRow label="Grounded capabilities" value={autopilot.production_contract.uses_grounded_capabilities ? 'yes' : 'no'} ok={autopilot.production_contract.uses_grounded_capabilities} />
                  <ReadinessRow label="Approval-first writes" value={autopilot.production_contract.requires_human_approval_for_writes ? 'yes' : 'not needed'} ok />
                  <ReadinessRow label="Safe live deploy" value={autopilot.production_contract.safe_to_deploy_live ? 'yes' : 'not yet'} ok={autopilot.production_contract.safe_to_deploy_live} />
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-forge-muted">Next required actions</div>
                <div className="mt-3 space-y-2">
                  {autopilot.readiness.next_actions.length === 0 ? (
                    <div className="rounded-lg border border-emerald-400/20 bg-emerald-400/10 p-3 text-xs text-emerald-200">No blockers. Ready for approved live execution.</div>
                  ) : autopilot.readiness.next_actions.map((action) => (
                    <div key={`${action.type}-${action.connector_id || action.source_url || action.label}`} className={`rounded-lg border p-3 ${action.blocking ? 'border-amber-400/20 bg-amber-400/10' : 'border-forge-border bg-forge-bg/50'}`}>
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium">{action.label}</div>
                        <span className="text-[11px] text-forge-muted">{action.blocking ? 'blocking' : 'recommended'}</span>
                      </div>
                      <p className="mt-2 text-xs leading-5 text-forge-muted">{action.detail}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Latest spec</h3>
          {!latestSpec ? <EmptyState title="No spec compiled" body="Compile a prompt to see the canonical goal, connectors, steps, tests, and approval gates." /> : (
            <div className="mt-4 space-y-3">
              <div className="text-sm font-medium">{latestSpec.goal}</div>
              <div className="flex flex-wrap gap-2">
                <span className="rounded bg-sky-400/10 px-2 py-1 text-[11px] text-sky-200">{latestSpec.status}</span>
                <span className="rounded bg-forge-bg px-2 py-1 text-[11px] text-forge-muted">{latestSpec.steps.length} steps</span>
                <span className="rounded bg-forge-bg px-2 py-1 text-[11px] text-forge-muted">{latestSpec.approval_gates.length} gates</span>
              </div>
              <div className="space-y-2">
                {latestSpec.steps.map((step) => (
                  <div key={step.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">{step.name}</div>
                      <span className="text-xs text-forge-muted">{step.connector_id}</span>
                    </div>
                    <p className="mt-2 text-xs text-forge-muted">{step.purpose}</p>
                  </div>
                ))}
              </div>
              {latestSpec.questions?.length ? (
                <div className="rounded-lg bg-amber-400/10 p-3 text-xs text-amber-200">{latestSpec.questions.length} missing facts before live execution</div>
              ) : null}
              <div className="flex flex-wrap gap-2 pt-1">
                {['forgeflow', 'n8n', 'zapier', 'github_actions'].map((platform) => (
                  <button key={platform} onClick={() => exportSpec(latestSpec.id, platform)} disabled={loading} className="rounded-lg border border-forge-border px-3 py-1.5 text-xs text-forge-muted hover:text-sky-200 disabled:opacity-50">
                    Export {platform.replace('_', ' ')}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {executionPlan && (
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Live execution plan</h3>
              <p className="mt-1 text-xs text-forge-muted">Credential, field, approval, request, and compensation checks before any provider call.</p>
            </div>
            <span className={`rounded-full px-2 py-1 text-[11px] ${executionPlan.ready ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>
              {executionPlan.ready ? 'ready' : `${executionPlan.blockers.length} blockers`}
            </span>
          </div>
          <div className="mt-4 grid gap-3 xl:grid-cols-2">
            {executionPlan.steps.map((step) => (
              <div key={step.step_id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium">{step.name}</div>
                  <span className={`rounded-full px-2 py-1 text-[11px] ${step.ready ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>{step.ready ? 'ready' : 'blocked'}</span>
                </div>
                <p className="mt-2 text-xs text-forge-muted">{step.connector_id}</p>
                <div className="mt-3 grid gap-2 md:grid-cols-3">
                  <ReadinessRow label="Credentials" value={step.credentials_ready ? 'ready' : 'missing'} ok={step.credentials_ready} />
                  <ReadinessRow label="Approval" value={step.approval_required ? (step.approval_ready ? 'approved' : 'needed') : 'not needed'} ok={step.approval_ready} />
                  <ReadinessRow label="Fields" value={step.missing_fields.length ? step.missing_fields.join(', ') : 'ready'} ok={!step.missing_fields.length} />
                </div>
                {step.request_preview && (
                  <div className="mt-3 rounded-lg border border-forge-border bg-forge-panel p-3 text-xs text-forge-muted">
                    <div>{step.request_preview.method} {step.request_preview.url}</div>
                    <div className="mt-1">Headers: {step.request_preview.headers.join(', ') || 'none'}</div>
                  </div>
                )}
                {step.blockers.length > 0 && (
                  <div className="mt-3 space-y-1">
                    {step.blockers.map((blocker, index) => <div key={`${step.step_id}-${blocker.type}-${index}`} className="text-xs text-amber-200">{blocker.type}</div>)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {(exports.length > 0 || repairs.length > 0) && (
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
            <h3 className="text-sm font-semibold">Executable exports</h3>
            {exports.length === 0 ? <EmptyState title="No exports yet" body="Export the latest spec to ForgeFlow, n8n, Zapier, or GitHub Actions." /> : (
              <div className="mt-4 space-y-3">
                {exports.map((item) => (
                  <div key={item.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">{item.platform}</div>
                      <span className="rounded-full bg-sky-400/10 px-2 py-1 text-[11px] text-sky-200">{item.artifact?.format}</span>
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs text-forge-muted">{JSON.stringify(item.artifact).slice(0, 180)}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
            <h3 className="text-sm font-semibold">Self-repair plans</h3>
            {repairs.length === 0 ? <EmptyState title="No repair plan yet" body="Repair a blocked run to turn errors into credential, approval, or debugging actions." /> : (
              <div className="mt-4 space-y-3">
                {repairs.map((repair) => (
                  <div key={repair.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">{repair.status}</div>
                      <span className="text-xs text-forge-muted">{repair.actions.length} actions</span>
                    </div>
                    <div className="mt-2 space-y-1">
                      {repair.actions.slice(0, 3).map((action) => <div key={`${repair.id}-${action.type}-${action.step_id || action.message}`} className="text-xs text-forge-muted">{action.message}</div>)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Typed connector adapters</h3>
          <div className="mt-4 space-y-2">
            {(adapters?.adapters || []).slice(0, 12).map((adapter) => (
              <div key={adapter.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium">{adapter.label}</div>
                  <span className={`rounded-full px-2 py-1 text-[11px] ${adapter.status === 'ready' ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>{adapter.status}</span>
                </div>
                <p className="mt-2 text-xs text-forge-muted">{adapter.methods.join(' · ')}</p>
                <button onClick={() => validateAdapter(adapter.id)} disabled={loading} className="mt-3 rounded-lg border border-forge-border px-3 py-1.5 text-xs text-forge-muted hover:text-sky-200 disabled:opacity-50">
                  Validate
                </button>
              </div>
            ))}
          </div>
          {validations.length ? (
            <div className="mt-4 rounded-lg bg-forge-bg/60 p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-forge-muted">Latest validations</div>
              <div className="mt-2 space-y-1">
                {validations.slice(0, 4).map((item) => <div key={item.id} className="text-xs text-forge-muted">{item.adapter_id}: {item.status}</div>)}
              </div>
            </div>
          ) : null}
        </div>

        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Runtime ledger</h3>
          {runs.length === 0 ? <EmptyState title="No runtime runs" body="Dry-run a compiled spec to record step-level execution state." /> : (
            <div className="mt-4 space-y-3">
              {runs.map((run) => (
                <div key={run.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium">{run.spec_id}</div>
                    <span className="rounded-full bg-sky-400/10 px-2 py-1 text-[11px] text-sky-200">{run.status}</span>
                  </div>
                  <div className="mt-1 text-xs text-forge-muted">{run.mode} · {run.started_at}</div>
                  <button onClick={() => repairRun(run.id)} disabled={loading} className="mt-3 rounded-lg border border-forge-border px-3 py-1.5 text-xs text-forge-muted hover:text-sky-200 disabled:opacity-50">
                    Repair / explain blockers
                  </button>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    {run.steps.map((step) => (
                      <div key={step.id} className="rounded-lg border border-forge-border bg-forge-panel px-3 py-2">
                        <div className="text-xs font-medium">{step.step_id}</div>
                        <div className="mt-1 text-[11px] text-forge-muted">{step.connector_id} · {step.status}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function EvalsView({ evals, onRefresh }) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const latestRun = evals?.runs?.[0]

  const runSuite = async () => {
    setRunning(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/evals/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ suite: 'core' }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      onRefresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Evaluation Lab"
        title="Measure prompt-to-automation quality before claiming coverage"
        description="Run deterministic preflight evals against core business automation fixtures so regressions are visible."
      />
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Core suite</h3>
          <p className="mt-2 text-sm leading-6 text-forge-muted">{evals?.suites?.[0]?.cases?.length || 0} cases covering HR onboarding, incident routing, and CSV enrichment.</p>
          <button onClick={runSuite} className="mt-5 inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
            <Gauge size={16} /> {running ? 'Running...' : 'Run evals'}
          </button>
          {error && <div className="mt-3 text-xs text-red-300">{error}</div>}
        </div>
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Latest score</h3>
          {!latestRun ? <EmptyState title="No eval run yet" body="Run the core suite to create a quality baseline." /> : (
            <div className="mt-4 space-y-3">
              <div className="text-4xl font-semibold text-forge-text">{Math.round(latestRun.score * 100)}%</div>
              {latestRun.cases.map((item) => (
                <div key={item.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium">{item.id}</div>
                    <span className={`rounded-full px-2 py-1 text-[11px] ${item.passed ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>{Math.round(item.score * 100)}%</span>
                  </div>
                  <p className="mt-2 text-xs text-forge-muted">Detected: {item.detected.join(', ') || 'none'}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function TemplatesView({ templates, onNavigate }) {
  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Reusable Patterns"
        title="Successful workflows should become templates"
        description="Templates make ForgeFlow faster and more reliable because common business processes start from proven plans."
      />
      <div className="grid gap-3 md:grid-cols-3">
        {(templates?.templates || []).map((template) => (
          <div key={template.id} className="rounded-lg border border-forge-border bg-forge-panel p-5">
            <div className="mb-4 inline-flex rounded-full bg-sky-400/10 px-2 py-1 text-[11px] text-sky-300">{template.category}</div>
            <h3 className="text-sm font-semibold">{template.name}</h3>
            <p className="mt-3 min-h-24 text-xs leading-5 text-forge-muted">{template.prompt}</p>
            <div className="mt-4 flex flex-wrap gap-1">
              {template.connectors.map((connector) => <span key={connector} className="rounded bg-forge-bg px-2 py-1 text-[10px] text-forge-muted">{connector}</span>)}
            </div>
            <button onClick={() => onNavigate('builder')} className="mt-5 inline-flex items-center gap-2 text-xs text-sky-300 hover:text-sky-200">
              Open builder <ArrowRight size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function JudgeDemoView() {
  const [prompt, setPrompt] = useState('I need to automate employee onboarding from an HR Excel sheet: send a welcome email, post a Slack announcement, create an IT access request, append the tracking sheet, schedule training, test it, and wait for approval before anything live.')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const runDemo = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/demo/judge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const payload = await res.json()
      if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`)
      setResult(payload)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const score = result?.scorecard ? Math.round((result.scorecard.filter((item) => item.passed).length / result.scorecard.length) * 100) : 0

  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Live Challenge Demo"
        title="Plain English to safe staging automation"
        description="Run the full judged story: conversation, grounded HR schema, connector checks, draft-first execution payloads, approvals, exports, worker readiness, and deployment readiness."
      />
      <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Business prompt</h3>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={7}
            className="mt-4 w-full rounded-lg border border-forge-border bg-forge-bg px-3 py-2 text-sm leading-6 outline-none focus:border-sky-400/50"
          />
          <button onClick={runDemo} disabled={loading} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200 disabled:opacity-50">
            <Rocket size={16} /> {loading ? 'Running...' : 'Run judge demo'}
          </button>
          {error && <div className="mt-4 rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-300">{error}</div>}
          {result && (
            <div className="mt-5 space-y-3">
              <Metric label="Demo readiness" value={`${score}%`} Icon={Gauge} tone={result.complete ? 'green' : 'amber'} />
              {result.scorecard.map((item) => (
                <ReadinessRow key={item.id} label={item.label} value={item.passed ? 'pass' : 'needs work'} ok={item.passed} />
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
          <h3 className="text-sm font-semibold">Staging workspace</h3>
          {!result ? <EmptyState title="No demo run yet" body="Run the judge demo to see safe destinations and approval-first execution." /> : (
            <div className="mt-4 space-y-3">
              <div className="grid gap-3 md:grid-cols-3">
                <Metric label="Automation steps" value={result.demo.spec.steps.length} Icon={Workflow} tone="sky" />
                <Metric label="Exports" value={result.demo.exports.length} Icon={Cloud} tone="green" />
                <Metric label="Safe destinations" value={`${result.staging_profile.ready_destinations}/${result.staging_profile.total_destinations}`} Icon={ShieldCheck} tone="amber" />
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {result.staging_profile.destinations.map((item) => (
                  <div key={item.service} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">{item.label}</div>
                      <span className={`rounded-full px-2 py-1 text-[11px] ${item.configured ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>{item.mode}</span>
                    </div>
                    <p className="mt-2 text-xs text-forge-muted">{item.destination}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {result && (
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
            <h3 className="text-sm font-semibold">Draft-first execution plan</h3>
            <div className="mt-4 space-y-3">
              {result.draft_first_plan.map((step) => (
                <div key={step.step_id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium">{step.order}. {step.step_name}</div>
                    <span className="rounded-full bg-sky-400/10 px-2 py-1 text-[11px] text-sky-200">{step.mode}</span>
                  </div>
                  <p className="mt-2 text-xs text-forge-muted">{step.connector_id} {'->'} {step.destination}</p>
                  <p className="mt-2 line-clamp-2 text-xs text-forge-muted">{JSON.stringify(step.payload_preview).slice(0, 220)}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
              <h3 className="text-sm font-semibold">Connector checks</h3>
              <div className="mt-4 grid gap-2 md:grid-cols-2">
                {result.connector_checks.map((check) => (
                  <ReadinessRow key={check.id} label={check.service} value={check.status} ok={['ready', 'ready_to_probe', 'connected'].includes(check.status)} />
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
              <h3 className="text-sm font-semibold">Worker and deployment readiness</h3>
              <div className="mt-4 space-y-2">
                <ReadinessRow label="Queue worker controls" value={result.worker.enabled ? 'on' : 'available'} ok />
                <ReadinessRow label="Due queue items" value={String(result.worker.due_count)} ok={result.worker.due_count === 0} />
                {result.deployment.targets.map((target) => (
                  <ReadinessRow key={target.id} label={target.name} value={target.status} ok={target.status === 'pass'} />
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
              <h3 className="text-sm font-semibold">Demo script</h3>
              <div className="mt-3 space-y-2">
                {result.judge_script.map((item) => <div key={item} className="text-xs leading-5 text-forge-muted">{item}</div>)}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function RoadmapView({ gaps }) {
  const phases = [
    ['Grounding', 'MCP adapter, OpenAPI ingestion, file/database schema discovery, credential broker, smart missing-info questions.'],
    ['Reliability', 'Typed capability planner, deterministic tests, live credential checks, approval preview, failure self-repair.'],
    ['Production', 'Cloud deployments, triggers, queues, run history, retries, alerts, rollback, audit logs.'],
    ['Learning', 'Template memory, organization-specific mappings, reusable connectors, model/provider routing by task.'],
  ]
  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Brainstorm Pass"
        title="What still makes ForgeFlow truly different"
        description="The product should beat code agents by owning the complete automation lifecycle, not just generating source files."
      />
      <div className="grid gap-3 md:grid-cols-2">
        {phases.map(([title, body], idx) => (
          <div key={title} className="rounded-lg border border-forge-border bg-forge-panel p-5">
            <div className="mb-3 text-xs text-sky-300">Phase {idx + 1}</div>
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="mt-3 text-sm leading-6 text-forge-muted">{body}</p>
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Product readiness self-check</h3>
          <span className="rounded-full bg-sky-400/10 px-3 py-1 text-xs text-sky-200">{gaps?.score ?? 0}%</span>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {(gaps?.checks || []).map((check) => (
            <div key={check.id} className="rounded-lg border border-forge-border bg-forge-bg/50 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">{check.label}</div>
                <span className={`rounded-full px-2 py-1 text-[11px] ${check.status === 'pass' ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>{check.status}</span>
              </div>
              <p className="mt-2 text-xs text-forge-muted">{check.detail}</p>
            </div>
          ))}
        </div>
        {gaps?.next?.length ? (
          <div className="mt-5 space-y-2">
            {gaps.next.map((item) => <ReadinessRow key={item} label={item} value="next" ok={false} />)}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function EmptyState({ title, body }) {
  return (
    <div className="rounded-lg border border-dashed border-forge-border bg-forge-bg/40 p-8 text-center">
      <div className="text-sm font-medium text-forge-text">{title}</div>
      <p className="mt-2 text-xs leading-5 text-forge-muted">{body}</p>
    </div>
  )
}

function AppWorkspace({ onLanding }) {
  const ws = useWebSocket()
  const { status: providerStatus, error: providerError } = useProviderStatus()
  const [activeView, setActiveView] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get('view')
    return NAV_ITEMS.some((item) => item.id === requested) ? requested : 'dashboard'
  })
  const overview = useApiResource('/api/product/overview', { metrics: {}, workflows: [], recent_runs: [] })
  const capabilities = useApiResource('/api/capabilities', { capabilities: [] })
  const approvals = useApiResource('/api/approvals', { pending: [], policy: [] })
  const runs = useApiResource('/api/runs', { runs: [] })
  const templates = useApiResource('/api/templates', { templates: [] })
  const appBuilds = useApiResource('/api/app-builder/builds', { builds: [] })
  const triggers = useApiResource('/api/triggers', { triggers: [] })
  const deploymentTargets = useApiResource('/api/deploy/targets', { targets: [] })
  const deploymentPlans = useApiResource('/api/deploy/plans', { plans: [] })
  const ingestions = useApiResource('/api/ingestions', { ingestions: [] })
  const connectorLifecycle = useApiResource('/api/connectors', { connectors: [], oauth_sessions: [] })
  const connectorAdapters = useApiResource('/api/connectors/adapters', { adapters: [] })
  const specs = useApiResource('/api/specs', { specs: [] })
  const runtimeRuns = useApiResource('/api/runtime/runs', { runs: [] })
  const observability = useApiResource('/api/observability', { events: [], alerts: [], queue: {} })
  const gaps = useApiResource('/api/product/gaps', { score: 0, checks: [], blockers: [], next: [] })
  const evals = useApiResource('/api/evals/suites', { suites: [], runs: [] })

  const activeLabel = useMemo(() => NAV_ITEMS.find((item) => item.id === activeView)?.label || 'Workspace', [activeView])
  const navigateView = useCallback((view) => {
    setActiveView(view)
    const url = new URL(window.location.href)
    url.searchParams.set('view', view)
    window.history.replaceState({}, '', url)
  }, [])

  return (
    <div className="flex h-screen bg-forge-bg text-forge-text">
      <aside className="flex w-64 shrink-0 flex-col border-r border-forge-border bg-forge-panel">
        <div className="border-b border-forge-border p-4">
          <LogoMark />
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV_ITEMS.map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => navigateView(id)}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${
                activeView === id ? 'bg-sky-400/15 text-sky-200' : 'text-forge-muted hover:bg-forge-border/60 hover:text-forge-text'
              }`}
            >
              <Icon size={17} /> {label}
            </button>
          ))}
        </nav>
        <div className="border-t border-forge-border p-3">
          <button onClick={onLanding} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-forge-muted hover:bg-forge-border/60 hover:text-forge-text">
            <Home size={17} /> Landing page
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-forge-border bg-forge-panel px-6 py-4">
          <div>
            <div className="text-xs text-forge-muted">ForgeFlow product workspace</div>
            <h1 className="text-lg font-semibold">{activeLabel}</h1>
          </div>
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${ws.connected ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-300' : 'border-red-400/20 bg-red-400/10 text-red-300'}`}>
              <span className={`h-2 w-2 rounded-full ${ws.connected ? 'bg-emerald-300' : 'bg-red-300'}`} />
              {ws.connected ? 'connected' : 'disconnected'}
            </span>
            <button onClick={() => navigateView('builder')} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
              <Play size={16} /> Build
            </button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-auto p-6">
          {activeView === 'dashboard' && <DashboardView overview={overview.data} providerStatus={providerStatus} onNavigate={navigateView} />}
          {activeView === 'builder' && <BuilderView {...ws} />}
          {activeView === 'appbuilder' && <AppBuilderView builds={appBuilds.data} onBuildsRefresh={appBuilds.refetch} />}
          {activeView === 'runtime' && <RuntimeView specs={specs.data} adapters={connectorAdapters.data} runtimeRuns={runtimeRuns.data} onSpecsRefresh={specs.refetch} onRunsRefresh={runtimeRuns.refetch} onGapsRefresh={gaps.refetch} />}
          {activeView === 'judge' && <JudgeDemoView />}
          {activeView === 'connectors' && <ConnectorsView providerStatus={providerStatus} capabilities={capabilities.data} connectorLifecycle={connectorLifecycle.data} onRefresh={connectorLifecycle.refetch} />}
          {activeView === 'schemas' && <SchemaExplorerView />}
          {activeView === 'approvals' && <ApprovalsView approvals={approvals.data} onRefresh={approvals.refetch} />}
          {activeView === 'triggers' && <TriggersView triggers={triggers.data} onRefresh={triggers.refetch} />}
          {activeView === 'deployments' && <DeploymentsView targets={deploymentTargets.data} plans={deploymentPlans.data} onPlansRefresh={deploymentPlans.refetch} />}
          {activeView === 'runs' && <RunsView runs={runs.data} observability={observability.data} onRefresh={() => { runs.refetch(); observability.refetch() }} />}
          {activeView === 'ingestions' && <IngestionsView ingestions={ingestions.data} onCapabilitiesRefresh={capabilities.refetch} onIngestionsRefresh={ingestions.refetch} />}
          {activeView === 'evals' && <EvalsView evals={evals.data} onRefresh={evals.refetch} />}
          {activeView === 'templates' && <TemplatesView templates={templates.data} onNavigate={navigateView} />}
          {activeView === 'roadmap' && <RoadmapView gaps={gaps.data} />}
        </main>

        <StatusBar
          phase={ws.phase}
          discoveredApis={ws.discoveredApis}
          debugHistory={ws.debugHistory}
          events={ws.events}
          providerStatus={providerStatus}
          providerError={providerError}
        />
      </div>
    </div>
  )
}

export default function App() {
  const [surface, setSurface] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get('view')
    return NAV_ITEMS.some((item) => item.id === requested) ? 'app' : 'landing'
  })
  return surface === 'landing'
    ? <LandingPage onOpenApp={() => setSurface('app')} />
    : <AppWorkspace onLanding={() => setSurface('landing')} />
}
