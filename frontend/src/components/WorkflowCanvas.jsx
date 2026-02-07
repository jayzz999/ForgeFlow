import React, { useCallback, useEffect, useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

const NODE_COLORS = {
  trigger: { bg: '#6366f1', border: '#818cf8' },
  api_call: { bg: '#0ea5e9', border: '#38bdf8' },
  condition: { bg: '#f59e0b', border: '#fbbf24' },
  delay: { bg: '#64748b', border: '#94a3b8' },
  default: { bg: '#6366f1', border: '#818cf8' },
}

const STATUS_COLORS = {
  pending: '#64748b',
  running: '#f59e0b',
  success: '#22c55e',
  failed: '#ef4444',
  fixing: '#f97316',
  retrying: '#f59e0b',
  modified: '#8b5cf6',
}

function CustomNode({ data }) {
  const colors = NODE_COLORS[data.stepType] || NODE_COLORS.default
  const statusColor = STATUS_COLORS[data.status] || STATUS_COLORS.pending

  // Task 2: Determine animation class based on status
  const animClass =
    data.status === 'failed' ? 'animate-fail-flash' :
    data.status === 'fixing' ? 'animate-fixing' :
    data.status === 'success' ? 'animate-success-glow' :
    data.status === 'running' ? 'node-active' :
    data.status === 'modified' ? 'animate-success-glow' :
    ''

  return (
    <div
      className={`px-4 py-3 rounded-xl border-2 min-w-[180px] animate-node-appear backdrop-blur-sm ${animClass}`}
      style={{
        background: `linear-gradient(135deg, ${colors.bg}20, ${colors.bg}08)`,
        borderColor: data.status === 'failed' ? '#ef4444' :
                     data.status === 'success' ? '#22c55e' :
                     data.status === 'fixing' ? '#f97316' :
                     data.status === 'modified' ? '#8b5cf6' :
                     colors.border,
      }}
    >
      <div className="flex items-center gap-2 mb-1">
        <div
          className="w-2 h-2 rounded-full shrink-0"
          style={{ background: statusColor }}
        />
        <span className="text-xs font-semibold text-white truncate flex-1">
          {data.label}
        </span>
        {/* Task 6: Status icons */}
        {data.status === 'success' && (
          <span className="text-green-400 text-sm shrink-0">✓</span>
        )}
        {data.status === 'running' && (
          <span className="text-yellow-400 text-sm shrink-0 animate-spin-slow">⟳</span>
        )}
        {data.status === 'failed' && (
          <span className="text-red-400 text-sm shrink-0">✕</span>
        )}
        {data.status === 'fixing' && (
          <span className="text-orange-400 text-sm shrink-0">🔧</span>
        )}
      </div>
      {data.service && (
        <div className="text-[10px] text-slate-400 mt-1">
          {data.service} → {data.endpoint}
        </div>
      )}
      {data.description && (
        <div className="text-[10px] text-slate-500 mt-1 truncate max-w-[200px]">
          {data.description}
        </div>
      )}
    </div>
  )
}

const nodeTypes = { custom: CustomNode }

function buildNodesAndEdges(steps, phase, nodeStatuses) {
  const newNodes = []
  const newEdges = []

  // Layout: organize by dependency depth
  const depthMap = {}
  const calculateDepth = (stepId, visited = new Set()) => {
    if (visited.has(stepId)) return 0
    visited.add(stepId)
    const step = steps.find(s => s.id === stepId)
    if (!step || !step.depends_on || step.depends_on.length === 0) return 0
    return 1 + Math.max(...step.depends_on.map(d => calculateDepth(d, visited)))
  }

  steps.forEach(s => {
    depthMap[s.id] = calculateDepth(s.id)
  })

  // Group by depth level
  const byDepth = {}
  Object.entries(depthMap).forEach(([id, depth]) => {
    if (!byDepth[depth]) byDepth[depth] = []
    byDepth[depth].push(id)
  })

  // Position nodes
  const X_SPACING = 280
  const Y_SPACING = 120
  const START_X = 50

  Object.entries(byDepth).forEach(([depth, stepIds]) => {
    const d = parseInt(depth)
    const totalWidth = stepIds.length * Y_SPACING
    const startY = Math.max(50, (400 - totalWidth) / 2)

    stepIds.forEach((stepId, idx) => {
      const step = steps.find(s => s.id === stepId)
      if (!step) return

      newNodes.push({
        id: step.id,
        type: 'custom',
        position: {
          x: START_X + d * (X_SPACING + 50),
          y: startY + idx * Y_SPACING,
        },
        data: {
          label: step.name,
          stepType: step.step_type || 'api_call',
          status: nodeStatuses[step.id] || step.status || 'pending',
          service: step.api?.service,
          endpoint: step.api?.endpoint,
          description: step.description,
        },
      })

      // Create edges from dependencies
      if (step.depends_on) {
        step.depends_on.forEach(dep => {
          newEdges.push({
            id: `${dep}-${step.id}`,
            source: dep,
            target: step.id,
            animated: phase === 'testing' || phase === 'generating',
            style: { stroke: '#6366f1', strokeWidth: 2 },
          })
        })
      }
    })
  })

  return { newNodes, newEdges }
}

export default function WorkflowCanvas({ dag, dagSteps, phase, nodeStatuses = {} }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  // Task 1: Build incrementally from dagSteps
  useEffect(() => {
    if (!dagSteps || dagSteps.length === 0) return
    // If final dag already present, skip incremental
    if (dag?.steps) return

    const { newNodes, newEdges } = buildNodesAndEdges(dagSteps, phase, nodeStatuses)
    setNodes(newNodes)
    setEdges(newEdges)
  }, [dagSteps, dag, nodeStatuses])

  // Build from final DAG
  useEffect(() => {
    if (!dag?.steps) {
      // Only show placeholder if no dagSteps either
      if (!dagSteps || dagSteps.length === 0) {
        setNodes([{
          id: 'placeholder',
          type: 'custom',
          position: { x: 200, y: 150 },
          data: {
            label: 'Waiting for workflow...',
            stepType: 'default',
            status: 'pending',
            description: 'Describe your workflow to see the DAG',
          },
        }])
        setEdges([])
      }
      return
    }

    const { newNodes, newEdges } = buildNodesAndEdges(dag.steps, phase, nodeStatuses)
    setNodes(newNodes)
    setEdges(newEdges)
  }, [dag, phase, nodeStatuses])

  return (
    <div className="h-full w-full relative bg-gradient-to-br from-forge-bg via-forge-bg to-indigo-950/20">
      {/* Canvas Label */}
      <div className="absolute top-3 left-4 z-10 text-xs text-forge-muted font-medium">
        Workflow Canvas
        {dag?.steps && (
          <span className="ml-2 text-indigo-400">
            {dag.steps.length} steps
          </span>
        )}
        {!dag?.steps && dagSteps.length > 0 && (
          <span className="ml-2 text-indigo-400 animate-pulse">
            Building... {dagSteps.length} steps
          </span>
        )}
      </div>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-left"
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1a1a2e" gap={20} size={1} />
        <Controls
          showInteractive={false}
          className="!bg-forge-panel !border-forge-border !rounded-xl"
        />
      </ReactFlow>
    </div>
  )
}
