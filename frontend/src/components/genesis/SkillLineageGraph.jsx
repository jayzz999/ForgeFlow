import React, { useMemo } from 'react'
import {
  ReactFlow, Background, MarkerType,
  useNodesState, useEdgesState,
} from '@xyflow/react'

export default function SkillLineageGraph({ lineage }) {
  const data = useMemo(() => {
    const nodes = (lineage?.nodes || []).map((n, i) => ({
      id: n.id,
      data: { label: n.kind === 'skill'
                       ? `🧬 ${n.name} (gen ${n.generation})`
                       : `🦠 ${n.name?.slice(0, 12)}` },
      position: { x: (i % 4) * 180, y: Math.floor(i / 4) * 90 },
      style: {
        background: n.kind === 'skill' ? 'rgba(168,85,247,0.18)' : 'rgba(16,185,129,0.18)',
        border: `1px solid ${n.kind === 'skill' ? 'rgba(168,85,247,0.6)' : 'rgba(16,185,129,0.6)'}`,
        color: '#e5e7eb', fontSize: 11, padding: 6, borderRadius: 6,
      },
    }))
    const edges = (lineage?.edges || []).map((e, i) => ({
      id: `e${i}`, source: e.source, target: e.target,
      style: { stroke: e.kind === 'distilled_from' ? '#10b981' : '#a855f7' },
      markerEnd: { type: MarkerType.ArrowClosed },
    }))
    return { nodes, edges }
  }, [lineage])

  const [nodes, , onNodesChange] = useNodesState(data.nodes)
  const [edges, , onEdgesChange] = useEdgesState(data.edges)
  return (
    <div className="h-64 border border-forge-border rounded">
      <ReactFlow nodes={nodes} edges={edges}
                 onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
                 fitView proOptions={{ hideAttribution: true }}>
        <Background gap={16} size={1} color="#3f3f46" />
      </ReactFlow>
    </div>
  )
}
