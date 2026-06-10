import type { MCPTool, Message, SSEEvent } from './types'

// When deployed to Azure Static Web Apps the frontend and backend are on
// separate origins.  Set VITE_API_BASE_URL at build time to the Container App
// URL (e.g. https://myapi.azurecontainerapps.io).  Leave unset for local dev
// or when the backend serves the frontend from the same origin.
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

// ---- Tool catalogue ----

export async function fetchTools(): Promise<MCPTool[]> {
  const res = await fetch(`${API_BASE}/api/tools`)
  if (!res.ok) throw new Error(`GET /api/tools failed: ${res.status}`)
  return res.json()
}

// ---- Direct tool invocation ----

export async function callTool(
  name: string,
  args: Record<string, unknown>,
): Promise<{ isError: boolean; content: string }> {
  const res = await fetch(`${API_BASE}/api/tool/call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, arguments: args }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Tool call failed: ${text}`)
  }
  return res.json()
}

// ---- Streaming chat ----

/**
 * Stream a chat turn. Calls onEvent for each SSE event received.
 * Returns once the stream is finished or aborted.
 */
export async function streamChat(
  messages: Message[],
  userMessage: string,
  onEvent: (e: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, user_message: userMessage }),
    signal,
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Chat request failed: ${text}`)
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buf += decoder.decode(value, { stream: true })

    // SSE frames are separated by "\n\n"; each line is "data: {...}"
    const frames = buf.split('\n\n')
    buf = frames.pop() ?? ''   // last element may be incomplete

    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.slice(6)) as SSEEvent
            onEvent(event)
          } catch {
            // ignore malformed lines
          }
        }
      }
    }
  }
}
