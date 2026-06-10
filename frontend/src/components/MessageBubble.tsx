import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Bubble } from '../types'
import ToolCallCard from './ToolCallCard'

interface Props { bubble: Bubble }

export default function MessageBubble({ bubble }: Props) {
  if (bubble.kind === 'tool') return <ToolCallCard bubble={bubble} />

  const isUser = bubble.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} my-1`}>
      <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed break-words ${
        isUser
          ? 'bg-blue-600 text-white rounded-br-sm'
          : 'bg-slate-700 text-slate-100 rounded-bl-sm'
      }`}>
        {!bubble.text
          ? <span className="opacity-40 animate-pulse">▍</span>
          : isUser
            ? <span className="whitespace-pre-wrap">{bubble.text}</span>
            : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // Tables
                  table: ({ children }) => (
                    <div className="overflow-x-auto my-2">
                      <table className="text-xs border-collapse w-full">{children}</table>
                    </div>
                  ),
                  thead: ({ children }) => (
                    <thead className="bg-slate-600 text-slate-200">{children}</thead>
                  ),
                  th: ({ children }) => (
                    <th className="px-3 py-1.5 text-left font-semibold border border-slate-500 whitespace-nowrap">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="px-3 py-1.5 border border-slate-600 whitespace-nowrap">
                      {children}
                    </td>
                  ),
                  tr: ({ children }) => (
                    <tr className="even:bg-slate-800/40">{children}</tr>
                  ),
                  // Text formatting
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  strong: ({ children }) => (
                    <strong className="font-semibold text-slate-50">{children}</strong>
                  ),
                  // Lists
                  ul: ({ children }) => (
                    <ul className="list-disc list-inside mb-2 space-y-0.5">{children}</ul>
                  ),
                  ol: ({ children }) => (
                    <ol className="list-decimal list-inside mb-2 space-y-0.5">{children}</ol>
                  ),
                  li: ({ children }) => <li className="leading-snug">{children}</li>,
                  // Code
                  code: ({ children, className }) => {
                    const isBlock = className?.includes('language-')
                    return isBlock
                      ? <code className="block bg-slate-900 rounded p-2 text-xs font-mono overflow-x-auto my-1 whitespace-pre">{children}</code>
                      : <code className="bg-slate-900 rounded px-1 py-0.5 text-xs font-mono">{children}</code>
                  },
                  // Headings
                  h1: ({ children }) => <h1 className="text-base font-bold mb-1 mt-2">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-sm font-bold mb-1 mt-2">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-1">{children}</h3>,
                  // Blockquote
                  blockquote: ({ children }) => (
                    <blockquote className="border-l-2 border-slate-500 pl-3 text-slate-400 my-1">
                      {children}
                    </blockquote>
                  ),
                }}
              >
                {bubble.text}
              </ReactMarkdown>
            )
        }
      </div>
    </div>
  )
}
