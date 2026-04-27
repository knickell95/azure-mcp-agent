import { useState } from 'react'
import type { ToolBubble } from '../types'

interface Props { bubble: ToolBubble }

export default function ToolCallCard({ bubble }: Props) {
  const [open, setOpen] = useState(false)
  const pending = bubble.result === undefined

  return (
    <div className="my-2 rounded-lg border border-slate-700 bg-slate-800/60 text-sm font-mono overflow-hidden">
      {/* Header row */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-slate-700/40 transition-colors"
      >
        <span className={`text-xs px-1.5 py-0.5 rounded font-semibold ${
          pending              ? 'bg-yellow-500/20 text-yellow-300' :
          bubble.isError       ? 'bg-red-500/20   text-red-300'    :
                                 'bg-green-500/20  text-green-300'
        }`}>
          {pending ? '…' : bubble.isError ? 'ERR' : 'OK'}
        </span>
        <span className="text-slate-200 font-semibold">{bubble.name}</span>
        <span className="ml-auto text-slate-500 text-xs">{open ? '▲' : '▼'}</span>
      </button>

      {/* Expandable body */}
      {open && (
        <div className="border-t border-slate-700 divide-y divide-slate-700">
          <section className="px-3 py-2">
            <p className="text-xs text-slate-500 mb-1 uppercase tracking-wide">Input</p>
            <pre className="text-xs text-slate-300 whitespace-pre-wrap break-all">
              {JSON.stringify(bubble.input, null, 2)}
            </pre>
          </section>
          {bubble.result !== undefined && (
            <section className="px-3 py-2">
              <p className="text-xs text-slate-500 mb-1 uppercase tracking-wide">Result</p>
              <pre className={`text-xs whitespace-pre-wrap break-all ${bubble.isError ? 'text-red-300' : 'text-slate-300'}`}>
                {(() => {
                  try { return JSON.stringify(JSON.parse(bubble.result!), null, 2) }
                  catch { return bubble.result }
                })()}
              </pre>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
