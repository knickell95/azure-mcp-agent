import type { Bubble } from '../types'
import ToolCallCard from './ToolCallCard'

interface Props { bubble: Bubble }

export default function MessageBubble({ bubble }: Props) {
  if (bubble.kind === 'tool') return <ToolCallCard bubble={bubble} />

  const isUser = bubble.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} my-1`}>
      <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
        isUser
          ? 'bg-blue-600 text-white rounded-br-sm'
          : 'bg-slate-700 text-slate-100 rounded-bl-sm'
      }`}>
        {bubble.text || <span className="opacity-40 animate-pulse">▍</span>}
      </div>
    </div>
  )
}
