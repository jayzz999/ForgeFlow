import React, { Suspense, lazy, useEffect, useMemo, useState } from 'react'
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
  GitBranch,
  History,
  Home,
  KeyRound,
  Layers3,
  LayoutDashboard,
  LockKeyhole,
  Play,
  Rocket,
  Search,
  ShieldCheck,
  Sparkles,
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
  { id: 'connectors', label: 'Connectors', Icon: Blocks },
  { id: 'schemas', label: 'Schemas', Icon: FileSpreadsheet },
  { id: 'approvals', label: 'Approvals', Icon: ClipboardCheck },
  { id: 'runs', label: 'Run History', Icon: History },
  { id: 'templates', label: 'Templates', Icon: Layers3 },
  { id: 'roadmap', label: 'Roadmap', Icon: GitBranch },
]

const API_URL = import.meta.env.VITE_API_URL || ''

function useApiResource(path, fallback) {
  const [data, setData] = useState(fallback)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
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

  return { data, loading, error }
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

function ConnectorsView({ providerStatus, capabilities }) {
  const services = providerStatus?.services || {}
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
          </div>
        ))}
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

function ApprovalsView({ approvals }) {
  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Approval Inbox"
        title="External actions should pause here"
        description="Emails, Slack posts, record writes, deletions, and permission changes should be previewed and approved before execution."
      />
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <h3 className="text-sm font-semibold">Pending approvals</h3>
        {(approvals?.pending || []).length === 0 ? (
          <EmptyState title="No approvals waiting" body="Generated workflows will place risky external actions here before they run." />
        ) : null}
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

function RunsView({ runs }) {
  return (
    <div className="space-y-8">
      <SectionTitle
        eyebrow="Operations"
        title="Run history"
        description="Every generated automation needs a visible audit trail: inputs, tests, status, logs, retries, and replay."
      />
      <div className="rounded-lg border border-forge-border bg-forge-panel p-5">
        <RunList runs={runs?.runs || []} />
      </div>
    </div>
  )
}

function RunList({ runs }) {
  if (!runs?.length) return <EmptyState title="No runs recorded" body="Run a workflow to populate operational history." />
  return (
    <div className="space-y-2">
      {runs.map((run) => (
        <div key={run.workflow_id} className="grid gap-3 rounded-lg border border-forge-border bg-forge-bg/50 p-3 md:grid-cols-[1fr_auto_auto] md:items-center">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{run.name}</div>
            <div className="mt-1 text-xs text-forge-muted">{run.workflow_id} · {run.created_at}</div>
          </div>
          <span className={`rounded-full px-2 py-1 text-[11px] ${run.success ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'}`}>
            {run.success ? 'success' : 'needs review'}
          </span>
          <span className="text-xs text-forge-muted">{run.tests_passed}/{run.tests_total} tests</span>
        </div>
      ))}
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

function RoadmapView() {
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
  const [activeView, setActiveView] = useState('dashboard')
  const overview = useApiResource('/api/product/overview', { metrics: {}, workflows: [], recent_runs: [] })
  const capabilities = useApiResource('/api/capabilities', { capabilities: [] })
  const approvals = useApiResource('/api/approvals', { pending: [], policy: [] })
  const runs = useApiResource('/api/runs', { runs: [] })
  const templates = useApiResource('/api/templates', { templates: [] })

  const activeLabel = useMemo(() => NAV_ITEMS.find((item) => item.id === activeView)?.label || 'Workspace', [activeView])

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
              onClick={() => setActiveView(id)}
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
            <button onClick={() => setActiveView('builder')} className="inline-flex items-center gap-2 rounded-lg bg-sky-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-200">
              <Play size={16} /> Build
            </button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-auto p-6">
          {activeView === 'dashboard' && <DashboardView overview={overview.data} providerStatus={providerStatus} onNavigate={setActiveView} />}
          {activeView === 'builder' && <BuilderView {...ws} />}
          {activeView === 'connectors' && <ConnectorsView providerStatus={providerStatus} capabilities={capabilities.data} />}
          {activeView === 'schemas' && <SchemaExplorerView />}
          {activeView === 'approvals' && <ApprovalsView approvals={approvals.data} />}
          {activeView === 'runs' && <RunsView runs={runs.data} />}
          {activeView === 'templates' && <TemplatesView templates={templates.data} onNavigate={setActiveView} />}
          {activeView === 'roadmap' && <RoadmapView />}
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
  const [surface, setSurface] = useState('landing')
  return surface === 'landing'
    ? <LandingPage onOpenApp={() => setSurface('app')} />
    : <AppWorkspace onLanding={() => setSurface('landing')} />
}
