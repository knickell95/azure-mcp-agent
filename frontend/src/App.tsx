import { useState } from 'react'
import ChatPanel from './components/ChatPanel'
import ToolBrowser from './components/ToolBrowser'
import { ConversationProvider, useConversation } from './store/conversation'

function Header({ sidebarOpen, onToggle }: { sidebarOpen: boolean; onToggle: () => void }) {
  const { dispatch } = useConversation()
  return (
    <header className="flex items-center gap-3 px-4 py-3 border-b border-slate-700 shrink-0">
      <button
        onClick={onToggle}
        title="Toggle tool browser"
        className="text-slate-400 hover:text-slate-200 transition-colors text-sm font-mono px-2 py-1 rounded hover:bg-slate-700"
      >
        {sidebarOpen ? '◀ Tools' : '▶ Tools'}
      </button>
      <span className="text-slate-200 font-semibold text-sm">Azure MCP Agent</span>
      <div className="ml-auto">
        <button
          onClick={() => dispatch({ type: 'CLEAR' })}
          className="text-xs text-slate-500 hover:text-slate-300 transition-colors px-2 py-1 rounded hover:bg-slate-700"
        >
          New chat
        </button>
      </div>
    </header>
  )
}

function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="flex flex-col h-screen bg-slate-900 text-slate-100">
      <Header sidebarOpen={sidebarOpen} onToggle={() => setSidebarOpen(o => !o)} />
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar — tool browser */}
        {sidebarOpen && (
          <aside className="w-72 shrink-0 border-r border-slate-700 overflow-hidden flex flex-col">
            <ToolBrowser />
          </aside>
        )}
        {/* Main — chat */}
        <main className="flex-1 overflow-hidden flex flex-col">
          <ChatPanel />
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ConversationProvider>
      <Layout />
    </ConversationProvider>
  )
}
