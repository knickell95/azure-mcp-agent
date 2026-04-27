import { useRef, useState } from 'react'
import { streamChat } from '../api'
import { useConversation } from '../store/conversation'
import MessageList from './MessageList'

export default function ChatPanel() {
  const { state, dispatch } = useConversation()
  const [input, setInput] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  async function send() {
    const text = input.trim()
    if (!text || state.streaming) return
    setInput('')

    dispatch({ type: 'USER_MSG', text })
    dispatch({ type: 'STREAM_START' })

    abortRef.current = new AbortController()

    try {
      await streamChat(
        state.history,
        text,
        (event) => {
          switch (event.type) {
            case 'text':        return dispatch({ type: 'TEXT_DELTA',  delta: event.delta })
            case 'tool_call':   return dispatch({ type: 'TOOL_CALL',   id: event.id, name: event.name, input: event.input })
            case 'tool_result': return dispatch({ type: 'TOOL_RESULT', id: event.id, content: event.content, isError: event.is_error })
            case 'done':        return dispatch({ type: 'STREAM_DONE' })
            case 'error':       return dispatch({ type: 'STREAM_ERROR', message: event.message })
          }
        },
        abortRef.current.signal,
      )
    } catch (err: unknown) {
      if ((err as Error).name !== 'AbortError') {
        dispatch({ type: 'STREAM_ERROR', message: String(err) })
      }
    }
  }

  function stop() {
    abortRef.current?.abort()
    dispatch({ type: 'STREAM_DONE' })
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex flex-col h-full">
      <MessageList bubbles={state.bubbles} />

      {/* Input bar */}
      <div className="border-t border-slate-700 px-4 py-3 flex gap-2 items-end">
        <textarea
          className="flex-1 resize-none rounded-xl bg-slate-700 text-slate-100 placeholder-slate-400
                     px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 max-h-40"
          rows={1}
          placeholder="Ask about your Azure resources… (Enter to send, Shift+Enter for newline)"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={state.streaming}
        />
        {state.streaming ? (
          <button
            onClick={stop}
            className="shrink-0 px-4 py-2.5 rounded-xl bg-red-600 hover:bg-red-500 text-white text-sm font-medium transition-colors"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={send}
            disabled={!input.trim()}
            className="shrink-0 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40
                       disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
          >
            Send
          </button>
        )}
      </div>
    </div>
  )
}
