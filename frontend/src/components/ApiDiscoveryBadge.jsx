import React from 'react'

const SERVICE_COLORS = {
  'Slack': { bg: 'bg-purple-500/20', text: 'text-purple-300', border: 'border-purple-500/30' },
  'Gmail': { bg: 'bg-red-500/20', text: 'text-red-300', border: 'border-red-500/30' },
  'Jira': { bg: 'bg-blue-500/20', text: 'text-blue-300', border: 'border-blue-500/30' },
  'Google Sheets': { bg: 'bg-green-500/20', text: 'text-green-300', border: 'border-green-500/30' },
  'Deriv': { bg: 'bg-orange-500/20', text: 'text-orange-300', border: 'border-orange-500/30' },
}

const DEFAULT_COLORS = { bg: 'bg-indigo-500/20', text: 'text-indigo-300', border: 'border-indigo-500/30' }

export default function ApiDiscoveryBadge({ api }) {
  const service = api.service || 'Unknown'
  const endpoint = api.endpoint || ''
  const colors = SERVICE_COLORS[service] || DEFAULT_COLORS

  return (
    <div
      className={`flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs shrink-0 animate-slide-in ${colors.bg} ${colors.text} ${colors.border}`}
    >
      <span>✅</span>
      <span className="font-medium">{service}</span>
      {endpoint && (
        <span className="opacity-60">→ {endpoint}</span>
      )}
    </div>
  )
}
