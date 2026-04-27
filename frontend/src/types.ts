// ---- MCP Tool ----
export interface MCPTool {
  name: string
  description: string | null
  inputSchema: Record<string, unknown>
}

// ---- Conversation messages (Anthropic format, serialised for backend) ----
export interface TextContent {
  type: 'text'
  text: string
}
export interface ToolUseContent {
  type: 'tool_use'
  id: string
  name: string
  input: Record<string, unknown>
}
export interface ToolResultContent {
  type: 'tool_result'
  tool_use_id: string
  content: string
  is_error: boolean
}
export type ContentBlock = TextContent | ToolUseContent | ToolResultContent

export interface Message {
  role: 'user' | 'assistant'
  content: string | ContentBlock[]
}

// ---- SSE events emitted by POST /api/chat ----
export type SSEEvent =
  | { type: 'text';        delta: string }
  | { type: 'tool_call';   id: string; name: string; input: Record<string, unknown> }
  | { type: 'tool_result'; id: string; content: string; is_error: boolean }
  | { type: 'done' }
  | { type: 'error';       message: string }

// ---- Rendered "bubble" inside the chat UI ----
export interface TextBubble   { kind: 'text';   role: 'user' | 'assistant'; text: string }
export interface ToolBubble   { kind: 'tool';   id: string; name: string; input: Record<string, unknown>; result?: string; isError?: boolean }
export type Bubble = TextBubble | ToolBubble
