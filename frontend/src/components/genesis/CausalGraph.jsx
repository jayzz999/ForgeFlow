import React, { useMemo, useCallback } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState, MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

// Layout: simple level-based layout using parent_ids depth.
function layout(nodes, edges) {
  const idToNode = Object.fromEntries(nodes.map(n => [n.id, n]))
  const depth = {}
  const visit = (id, d = 0, seen = new Set()) => {
    if (seen.has(id)) return
    seen.add(id)
    depth[id] = Math.max(depth[id] ?? 0, d)
    edges.filter(e => e.source === id).forEach(e => visit(e.target, d + 1, seen))
  }
  // roots = nodes with no incoming edges
  const incoming = new Set(edges.map(e => e.target))
  nodes.filter(n => !incoming.has(n.id)).forEach(r => visit(r.id, 0))

  const byDepth = {}
  nodes.forEach(n => {
    const d = depth[n.id] ?? 0
    byDepth[d] = byDepth[d] || []
    byDepth[d].push(n)
  })

  const X_GAP = 240, Y_GAP = 130
  return nodes.map(n => {
    const d = depth[n.id] ?? 0
    const col = byDepth[d].indexOf(n)
    const cnt = byDepth[d].length
    return {
      ...n,
      position: { x: d * X_GAP, y: (col - (cnt - 1) / 2) * Y_GAP + 200 },
    }
  })
}

const flavorStyle = (n) => {
  if (n.shadow_branch) {
    return { bg: 'bg-purple-500/15', border: 'border-purple-400/60', label: '🌌 shadow', text: 'text-purple-200' }
  }
  if (n.is_dream) {
    return { bg: 'bg-fuchsia-500/10', border: 'border-fuchsia-400/40 border-dashed', label: '💭 dream', text: 'text-fuchsia-200' }
  }
  if (n.edited) {
    return { bg: 'bg-amber-500/15', border: 'border-amber-400/60', label: '✏ edited', text: 'text-amber-200' }
  }
  return { bg: 'bg-emerald-500/15', border: 'border-emerald-400/50', label: '⚡ real', text: 'text-emerald-100' }
}

function NodeCard({ data }) {
  const s = flavorStyle(data)
  return (
    <div
      onClick={() => data.onSelect?.(data.raw)}
      className={`px-3 py-2 rounded-lg border ${s.bg} ${s.border} ${s.text} text-[11px] cursor-pointer hover:scale-105 transition-transform w-52 backdrop-blur`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-[9px] uppercase tracking-wider opacity-80">{s.label}</span>
        <span className="text-[9px] opacity-50">{data.raw.id?.slice(2, 8)}</span>
      </div>
      <div className="font-semibold truncate">
        {data.raw.action?.tool || data.raw.trigger?.type || 'noop'}
      </div>
      <div className="text-[10px] opacity-70 line-clamp-2 mt-0.5">
        {data.raw.reasoning?.slice(0, 90) || '—'}
      </div>
    </div>
  )
}

const nodeTypes = { causal: NodeCard }

export default function CausalGraph({ graph, onSelectDecision }) {
  const flowNodes = useMemo(() => {
    const raw = (graph?.nodes || []).map(n => ({
      id: n.id,
      type: 'causal',
      data: { raw: n, onSelect: onSelectDecision },
      position: { x: 0, y: 0 },
    }))
    const flowEdges = (graph?.edges || []).map(e => ({
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      animated: e.kind === 'dream' || e.kind === 'shadow',
      style: {
        stroke: e.kind === 'shadow' ? '#a855f7'
              : e.kind === 'dream' ? '#e879f9'
              : '#34d399',
        strokeWidth: 1.5,
        strokeDasharray: e.kind === 'dream' ? '4 4' : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed },
    }))
    return { nodes: layout(raw, flowEdges), edges: flowEdges }
  }, [graph, onSelectDecision])

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowNodes.edges)

  // sync when graph changes
  React.useEffect(() => {
    setNodes(flowNodes.nodes)
    setEdges(flowNodes.edges)
  }, [flowNodes, setNodes, setEdges])

  if (!graph?.nodes?.length) {
    return (
      <div className="flex items-center justify-center h-full text-forge-muted text-sm">
        No decisions yet. Perceive something, or let it dream.
      </div>
    )
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.2}
      maxZoom={1.5}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={24} size={1} color="#3f3f46" />
      <Controls className="!bg-forge-bg !border-forge-border" showInteractive={false} />
      <MiniMap
        className="!bg-forge-bg/60 !border-forge-border"
        nodeColor={(n) => {
          const r = n.data?.raw
          if (!r) return '#52525b'
          if (r.shadow_branch) return '#a855f7'
          if (r.is_dream) return '#e879f9'
          if (r.edited) return '#fbbf24'
          return '#10b981'
        }}
        maskColor="rgba(0,0,0,0.6)"
      />
    </ReactFlow>
  )
}
