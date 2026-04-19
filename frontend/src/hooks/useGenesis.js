import { useCallback, useEffect, useRef, useState } from 'react'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8001'
const HTTP_BASE = import.meta.env.VITE_API_BASE || ''  // empty = same origin (vite proxy)

// Tiny event bus on top of WebSocket. The page subscribes to whatever
// types it needs.
export function useGenesis() {
  const [connected, setConnected] = useState(false)
  const [organisms, setOrganisms] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [branches, setBranches] = useState([])
  const [eventLog, setEventLog] = useState([])  // last 100 events for the side rail
  const [acting, setActing] = useState(false)
  const [dreaming, setDreaming] = useState(false)
  const wsRef = useRef(null)

  // ── WebSocket ─────────────────────────────────────────────────
  useEffect(() => {
    const clientId = `gen_${Date.now()}`
    const ws = new WebSocket(`${WS_URL}/ws/${clientId}`)
    wsRef.current = ws
    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)
    ws.onmessage = (ev) => {
      try {
        const e = JSON.parse(ev.data)
        if (!e.type || !e.type.startsWith('organism.')) return
        setEventLog(log => [e, ...log].slice(0, 100))
        if (e.type === 'organism.perceiving') setActing(true)
        if (e.type === 'organism.acted') setActing(false)
        if (e.type === 'organism.dreaming_start') setDreaming(true)
        if (e.type === 'organism.dreaming_end') setDreaming(false)
        // If event is for the active organism, refresh graph
        if (activeId && e.organism_id === activeId &&
            (e.type === 'organism.acted'
             || e.type === 'organism.dreamt'
             || e.type === 'organism.branch_created'
             || e.type === 'organism.branch_promoted')) {
          loadCausality(activeId)
          loadBranches(activeId)
        }
        if (e.type === 'organism.seeded') {
          loadOrganisms()
        }
      } catch {}
    }
    return () => ws.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId])

  // ── REST helpers ──────────────────────────────────────────────
  const loadOrganisms = useCallback(async () => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/organisms`)
    const j = await r.json()
    setOrganisms(j.organisms || [])
  }, [])

  const loadCausality = useCallback(async (id) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/organisms/${id}/causality?include_dreams=true&include_shadows=true`)
    setGraph(await r.json())
  }, [])

  const loadBranches = useCallback(async (id) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/organisms/${id}/branches`)
    const j = await r.json()
    setBranches(j.branches || [])
  }, [])

  const seed = useCallback(async ({ goal, name, constraints = [], forbidden = [] }) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/seed`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, name, constraints, forbidden }),
    })
    const j = await r.json()
    await loadOrganisms()
    setActiveId(j.organism.id)
    return j.organism
  }, [loadOrganisms])

  const perceive = useCallback(async (id, perception) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/organisms/${id}/perceive`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ perception }),
    })
    return await r.json()
  }, [])

  const dream = useCallback(async (id, n = 5) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/organisms/${id}/dream`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ n }),
    })
    return await r.json()
  }, [])

  const editDecision = useCallback(async (orgId, decisionId, payload) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/organisms/${orgId}/edit/${decisionId}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return await r.json()
  }, [])

  const promoteBranch = useCallback(async (orgId, branchId) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/organisms/${orgId}/branches/${branchId}/promote`, {
      method: 'POST',
    })
    return await r.json()
  }, [])

  const addSource = useCallback(async (orgId, source) => {
    const r = await fetch(`${HTTP_BASE}/api/genesis/organisms/${orgId}/sources`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(source),
    })
    const j = await r.json()
    await loadOrganisms()
    return j
  }, [loadOrganisms])

  const removeSource = useCallback(async (orgId, index) => {
    await fetch(`${HTTP_BASE}/api/genesis/organisms/${orgId}/sources/${index}`, { method: 'DELETE' })
    await loadOrganisms()
  }, [loadOrganisms])

  const killOrganism = useCallback(async (id) => {
    await fetch(`${HTTP_BASE}/api/genesis/organisms/${id}`, { method: 'DELETE' })
    if (activeId === id) setActiveId(null)
    await loadOrganisms()
  }, [activeId, loadOrganisms])

  // initial load
  useEffect(() => { loadOrganisms() }, [loadOrganisms])
  useEffect(() => {
    if (activeId) {
      loadCausality(activeId)
      loadBranches(activeId)
    } else {
      setGraph({ nodes: [], edges: [] })
      setBranches([])
    }
  }, [activeId, loadCausality, loadBranches])

  return {
    // state
    connected, organisms, activeId, graph, branches, eventLog, acting, dreaming,
    // actions
    setActiveId, seed, perceive, dream, editDecision, promoteBranch, killOrganism,
    addSource, removeSource,
    refreshGraph: () => activeId && loadCausality(activeId),
    refreshOrganisms: loadOrganisms,
  }
}
