import { useState } from 'react'
import { callTool } from '../api'
import type { MCPTool } from '../types'

interface Props { tool: MCPTool; onClose: () => void }

type FieldSchema = { type?: string; description?: string; enum?: string[]; default?: unknown }

function getProperties(schema: Record<string, unknown>): Record<string, FieldSchema> {
  return (schema.properties as Record<string, FieldSchema>) ?? {}
}

function getRequired(schema: Record<string, unknown>): string[] {
  return (schema.required as string[]) ?? []
}

export default function ToolForm({ tool, onClose }: Props) {
  const props = getProperties(tool.inputSchema)
  const required = getRequired(tool.inputSchema)

  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(props).map(([k, v]) => [k, String(v.default ?? '')])
    )
  )
  const [result, setResult] = useState<{ isError: boolean; content: string } | null>(null)
  const [running, setRunning] = useState(false)

  function set(key: string, val: string) {
    setValues(v => ({ ...v, [key]: val }))
  }

  async function run() {
    setRunning(true)
    setResult(null)
    try {
      // Attempt to parse JSON values; fall back to plain string
      const args = Object.fromEntries(
        Object.entries(values)
          .filter(([, v]) => v !== '')
          .map(([k, v]) => {
            try { return [k, JSON.parse(v)] } catch { return [k, v] }
          })
      )
      const res = await callTool(tool.name, args)
      setResult(res)
    } catch (err) {
      setResult({ isError: true, content: String(err) })
    } finally {
      setRunning(false)
    }
  }

  const hasFields = Object.keys(props).length > 0

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
        <div>
          <p className="text-xs text-slate-400 uppercase tracking-wide mb-0.5">Tool</p>
          <h2 className="text-sm font-semibold text-slate-100 font-mono">{tool.name}</h2>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-200 text-lg leading-none">✕</button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {/* Description */}
        {tool.description && (
          <p className="text-sm text-slate-400 leading-relaxed">{tool.description}</p>
        )}

        {/* Fields */}
        {hasFields && (
          <div className="space-y-3">
            {Object.entries(props).map(([key, field]) => (
              <div key={key}>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  {key}
                  {required.includes(key) && <span className="text-red-400 ml-1">*</span>}
                  {field.description && (
                    <span className="ml-2 text-slate-500 font-normal">{field.description}</span>
                  )}
                </label>
                {field.enum ? (
                  <select
                    value={values[key] ?? ''}
                    onChange={e => set(key, e.target.value)}
                    className="w-full rounded-lg bg-slate-700 text-slate-100 text-sm px-3 py-2
                               focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">— select —</option>
                    {field.enum.map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={values[key] ?? ''}
                    onChange={e => set(key, e.target.value)}
                    placeholder={field.type === 'object' || field.type === 'array' ? 'JSON…' : ''}
                    className="w-full rounded-lg bg-slate-700 text-slate-100 text-sm px-3 py-2
                               focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-500"
                  />
                )}
              </div>
            ))}
          </div>
        )}

        {!hasFields && (
          <p className="text-xs text-slate-500 italic">This tool takes no arguments.</p>
        )}

        {/* Run button */}
        <button
          onClick={run}
          disabled={running}
          className="w-full py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50
                     text-white text-sm font-medium transition-colors"
        >
          {running ? 'Running…' : 'Run tool'}
        </button>

        {/* Result */}
        {result && (
          <div className={`rounded-lg border text-xs font-mono p-3 whitespace-pre-wrap break-all ${
            result.isError
              ? 'border-red-700 bg-red-900/20 text-red-300'
              : 'border-slate-600 bg-slate-800 text-slate-300'
          }`}>
            {(() => {
              try { return JSON.stringify(JSON.parse(result.content), null, 2) }
              catch { return result.content }
            })()}
          </div>
        )}
      </div>
    </div>
  )
}
