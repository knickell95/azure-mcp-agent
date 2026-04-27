import { useEffect, useState } from 'react'
import { fetchTools } from '../api'
import type { MCPTool } from '../types'
import ToolForm from './ToolForm'

export default function ToolBrowser() {
  const [tools, setTools] = useState<MCPTool[]>([])
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<MCPTool | null>(null)
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading')

  useEffect(() => {
    fetchTools()
      .then(t => { setTools(t); setStatus('ok') })
      .catch(() => setStatus('error'))
  }, [])

  const filtered = tools.filter(t =>
    !filter ||
    t.name.toLowerCase().includes(filter.toLowerCase()) ||
    (t.description ?? '').toLowerCase().includes(filter.toLowerCase())
  )

  if (selected) {
    return <ToolForm tool={selected} onClose={() => setSelected(null)} />
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm font-semibold text-slate-200">Tools</span>
          <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
            status === 'ok'      ? 'bg-green-500/20 text-green-400' :
            status === 'error'   ? 'bg-red-500/20   text-red-400'   :
                                   'bg-yellow-500/20 text-yellow-400'
          }`}>
            {status === 'ok' ? `${tools.length} tools` : status}
          </span>
        </div>
        <input
          type="text"
          placeholder="Filter tools…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="w-full rounded-lg bg-slate-700 text-slate-100 text-xs px-3 py-1.5
                     focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-500"
        />
      </div>

      {/* Tool list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.map(tool => (
          <button
            key={tool.name}
            onClick={() => setSelected(tool)}
            className="w-full text-left px-4 py-2.5 border-b border-slate-700/50
                       hover:bg-slate-700/40 transition-colors group"
          >
            <p className="text-xs font-mono font-medium text-slate-200 group-hover:text-blue-400 transition-colors truncate">
              {tool.name}
            </p>
            {tool.description && (
              <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{tool.description}</p>
            )}
          </button>
        ))}
        {filtered.length === 0 && status === 'ok' && (
          <p className="text-xs text-slate-500 text-center mt-8">No tools match "{filter}"</p>
        )}
      </div>
    </div>
  )
}
