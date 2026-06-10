import { createContext, useContext, useReducer, type ReactNode } from 'react'
import type { Bubble, Message } from '../types'

interface State {
  /** Flat list of renderable bubbles for the current session */
  bubbles: Bubble[]
  /** Full Anthropic-format history sent to the backend on each turn */
  history: Message[]
  streaming: boolean
}

type Action =
  | { type: 'USER_MSG';        text: string }
  | { type: 'STREAM_START' }
  | { type: 'TEXT_DELTA';      delta: string }
  | { type: 'TOOL_CALL';       id: string; name: string; input: Record<string, unknown> }
  | { type: 'TOOL_RESULT';     id: string; content: string; isError: boolean }
  | { type: 'STREAM_DONE' }
  | { type: 'STREAM_ERROR';    message: string }
  | { type: 'CLEAR' }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'USER_MSG': {
      const userMsg: Message = { role: 'user', content: action.text }
      return {
        ...state,
        bubbles: [...state.bubbles, { kind: 'text', role: 'user', text: action.text }],
        history: [...state.history, userMsg],
      }
    }

    case 'STREAM_START':
      // Append an empty assistant text bubble that will be filled by TEXT_DELTA
      return {
        ...state,
        streaming: true,
        bubbles: [...state.bubbles, { kind: 'text', role: 'assistant', text: '' }],
      }

    case 'TEXT_DELTA': {
      const bubbles = [...state.bubbles]
      const last = bubbles[bubbles.length - 1]
      if (last?.kind === 'text' && last.role === 'assistant') {
        bubbles[bubbles.length - 1] = { ...last, text: last.text + action.delta }
      } else {
        // Text arrived after a tool card — start a new assistant text bubble
        bubbles.push({ kind: 'text', role: 'assistant', text: action.delta })
      }
      return { ...state, bubbles }
    }

    case 'TOOL_CALL':
      return {
        ...state,
        bubbles: [...state.bubbles, { kind: 'tool', id: action.id, name: action.name, input: action.input }],
      }

    case 'TOOL_RESULT': {
      const bubbles = state.bubbles.map(b =>
        b.kind === 'tool' && b.id === action.id
          ? { ...b, result: action.content, isError: action.isError }
          : b,
      )
      return { ...state, bubbles }
    }

    case 'STREAM_DONE': {
      // Build assistant history entry from what was streamed
      const assistantText = state.bubbles
        .filter(b => b.kind === 'text' && b.role === 'assistant')
        .map(b => (b as { text: string }).text)
        .join('')
      const assistantMsg: Message = { role: 'assistant', content: assistantText }
      return { ...state, streaming: false, history: [...state.history, assistantMsg] }
    }

    case 'STREAM_ERROR': {
      const bubbles = [...state.bubbles, { kind: 'text' as const, role: 'assistant' as const, text: `⚠ ${action.message}` }]
      return { ...state, streaming: false, bubbles }
    }

    case 'CLEAR':
      return { bubbles: [], history: [], streaming: false }

    default:
      return state
  }
}

const initial: State = { bubbles: [], history: [], streaming: false }

const ConvContext = createContext<{
  state: State
  dispatch: React.Dispatch<Action>
} | null>(null)

export function ConversationProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial)
  return <ConvContext.Provider value={{ state, dispatch }}>{children}</ConvContext.Provider>
}

export function useConversation() {
  const ctx = useContext(ConvContext)
  if (!ctx) throw new Error('useConversation must be used inside ConversationProvider')
  return ctx
}
