import { useEffect, useRef } from 'react'
import type { Bubble } from '../types'
import MessageBubble from './MessageBubble'

interface Props { bubbles: Bubble[] }

export default function MessageList({ bubbles }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [bubbles])

  if (bubbles.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-slate-500 select-none">
        <div className="text-5xl mb-4">☁</div>
        <p className="text-lg font-medium">Azure MCP Agent</p>
        <p className="text-sm mt-1">Ask anything about your Azure resources</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1">
      {bubbles.map((b, i) => <MessageBubble key={i} bubble={b} />)}
      <div ref={bottomRef} />
    </div>
  )
}
