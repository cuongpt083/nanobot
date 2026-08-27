import React, { useState } from 'react';
import {
  Bot,
  Send,
  Terminal,
  Clock,
  Sparkles,
  Search,
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  Code,
  CheckCircle2,
  Radio,
  Cpu,
  CornerDownLeft,
  Settings2,
  FolderOpen
} from 'lucide-react';
import Markdown from 'react-markdown';
import { Session, Message, ToolCall } from '../types';

interface ChatViewProps {
  sessions: Session[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onCreateSession: () => void;
  onDeleteSession: (id: string) => void;
  onSendMessage: (text: string) => Promise<void>;
  isLoading: boolean;
  activeModel: string;
  onChangeModel: (model: string) => void;
}

export const ChatView: React.FC<ChatViewProps> = ({
  sessions,
  activeSessionId,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
  onSendMessage,
  isLoading,
  activeModel,
  onChangeModel,
}) => {
  const [inputText, setInputText] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedReasoning, setExpandedReasoning] = useState<Record<string, boolean>>({});
  const [expandedTools, setExpandedTools] = useState<Record<string, boolean>>({});

  const currentSession = sessions.find((s) => s.id === activeSessionId) || sessions[0];

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isLoading) return;
    const text = inputText;
    setInputText('');
    await onSendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const toggleReasoning = (msgId: string) => {
    setExpandedReasoning((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  const toggleTool = (toolId: string) => {
    setExpandedTools((prev) => ({ ...prev, [toolId]: !prev[toolId] }));
  };

  const quickPrompts = [
    { label: 'Check Workspace Files', prompt: 'List files in the workspace and inspect directory structure.' },
    { label: 'Schedule Daily Digest', prompt: 'Schedule a cron job every morning at 9am to fetch AI news.' },
    { label: 'Consolidate Dream Memory', prompt: '/dream' },
    { label: 'Gateway Health & Tools', prompt: '/status' },
  ];

  return (
    <div className="flex h-full w-full overflow-hidden bg-zinc-950">
      {/* Sessions Sidebar */}
      <aside className="w-72 flex-shrink-0 border-r border-zinc-800/80 bg-zinc-900/40 flex flex-col justify-between">
        <div className="p-3.5 border-b border-zinc-800/80">
          <button
            id="btn-new-session"
            onClick={onCreateSession}
            className="w-full flex items-center justify-center gap-2 px-3.5 py-2.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-sm transition-colors shadow-sm cursor-pointer"
          >
            <Plus className="w-4 h-4 stroke-[2.5]" />
            <span>New Session</span>
          </button>

          <div className="relative mt-3">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
            <input
              id="input-search-sessions"
              type="text"
              placeholder="Search conversations..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-8.5 pr-3 py-1.5 text-xs bg-zinc-950/60 border border-zinc-800 rounded-md text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-amber-500/50"
            />
          </div>
        </div>

        {/* Sessions List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {filteredSessions.map((session) => {
            const isActive = session.id === activeSessionId;
            return (
              <div
                key={session.id}
                id={`session-item-${session.id}`}
                onClick={() => onSelectSession(session.id)}
                className={`group relative flex items-center justify-between px-3 py-2.5 rounded-lg text-xs cursor-pointer transition-all ${
                  isActive
                    ? 'bg-zinc-800 text-zinc-100 font-medium shadow-sm'
                    : 'text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-200'
                }`}
              >
                <div className="flex items-center gap-2.5 truncate pr-2">
                  <Bot className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? 'text-amber-400' : 'text-zinc-500'}`} />
                  <span className="truncate">{session.title}</span>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {sessions.length > 1 && (
                    <button
                      id={`btn-delete-session-${session.id}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteSession(session.id);
                      }}
                      className="p-1 text-zinc-500 hover:text-red-400 rounded hover:bg-zinc-700/50"
                      title="Delete Session"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Sidebar Footer Stats */}
        <div className="p-3 border-t border-zinc-800/80 bg-zinc-950/30 text-[11px] text-zinc-500 flex items-center justify-between">
          <span className="flex items-center gap-1.5">
            <Radio className="w-3 h-3 text-emerald-400 animate-pulse" />
            <span>Agent Loop Idle</span>
          </span>
          <span className="font-mono text-zinc-400">
            {currentSession?.token_usage?.total_tokens ?? 0} tokens
          </span>
        </div>
      </aside>

      {/* Main Conversation Stream */}
      <section className="flex-1 flex flex-col min-w-0 bg-zinc-950 relative">
        {/* Active Session Top Bar */}
        <div className="px-6 py-3 border-b border-zinc-800/80 bg-zinc-900/20 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold text-zinc-100 truncate max-w-md">
              {currentSession?.title || 'Active Session'}
            </h2>
            <span className="px-2 py-0.5 text-[10px] font-mono bg-zinc-800 text-zinc-300 rounded border border-zinc-700">
              {currentSession?.model || activeModel}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <select
              id="select-model-picker"
              value={activeModel}
              onChange={(e) => onChangeModel(e.target.value)}
              className="bg-zinc-900 text-xs text-zinc-200 border border-zinc-700 rounded-md px-2.5 py-1.5 focus:outline-none focus:border-amber-500 cursor-pointer"
            >
              <option value="gemini-2.5-flash">Gemini 2.5 Flash (Fast / Multimodal)</option>
              <option value="gemini-2.5-pro">Gemini 2.5 Pro (Deep Reasoning)</option>
              <option value="claude-3-7-sonnet">Claude 3.7 Sonnet</option>
              <option value="gpt-4o">GPT-4o</option>
              <option value="ollama-local">Local Ollama / OpenSource</option>
            </select>
          </div>
        </div>

        {/* Message Thread */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {(!currentSession || currentSession.messages.length === 0) && (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto py-12">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-500/20 to-orange-500/10 border border-amber-500/30 flex items-center justify-center mb-4 shadow-lg">
                <Bot className="w-7 h-7 text-amber-400" />
              </div>
              <h3 className="text-lg font-bold text-zinc-100 mb-1">nanobot Agent Gateway</h3>
              <p className="text-xs text-zinc-400 mb-6 leading-relaxed">
                Your personal AI assistant runtime with native tool execution, filesystem access, cron automation, and Dream long-term memory.
              </p>

              <div className="grid grid-cols-2 gap-2.5 w-full text-left">
                {quickPrompts.map((item, idx) => (
                  <button
                    key={idx}
                    id={`btn-quick-prompt-${idx}`}
                    onClick={() => {
                      setInputText(item.prompt);
                    }}
                    className="p-3 rounded-lg bg-zinc-900/60 hover:bg-zinc-800/80 border border-zinc-800/80 hover:border-zinc-700 transition-all text-xs text-zinc-300 cursor-pointer group"
                  >
                    <div className="font-semibold text-zinc-200 group-hover:text-amber-400 mb-1">
                      {item.label}
                    </div>
                    <div className="text-[11px] text-zinc-500 truncate">{item.prompt}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {currentSession?.messages.map((msg) => {
            const isAssistant = msg.role === 'assistant';
            const isUser = msg.role === 'user';
            const isReasoningOpen = expandedReasoning[msg.id];

            return (
              <div
                key={msg.id}
                id={`message-row-${msg.id}`}
                className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-3xl ${
                  isUser ? 'ml-auto' : 'mr-auto'
                }`}
              >
                {/* Message Header */}
                <div className="flex items-center gap-2 mb-1.5 px-1 text-[11px] text-zinc-500">
                  <span className="font-medium text-zinc-400">
                    {isUser ? 'You' : 'nanobot Agent'}
                  </span>
                  <span>•</span>
                  <span>{new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                </div>

                {/* Reasoning Thought Box (for assistant) */}
                {isAssistant && msg.reasoning && (
                  <div className="w-full mb-3 rounded-lg border border-zinc-800 bg-zinc-900/60 overflow-hidden text-xs">
                    <button
                      id={`btn-toggle-reasoning-${msg.id}`}
                      onClick={() => toggleReasoning(msg.id)}
                      className="w-full flex items-center justify-between px-3 py-2 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40 transition-colors"
                    >
                      <span className="flex items-center gap-2 font-mono text-[11px] text-amber-400">
                        <Sparkles className="w-3.5 h-3.5" />
                        <span>Agent Reasoning Process</span>
                      </span>
                      {isReasoningOpen ? (
                        <ChevronDown className="w-3.5 h-3.5" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5" />
                      )}
                    </button>
                    {isReasoningOpen && (
                      <div className="p-3 pt-1 text-zinc-400 font-mono text-[11px] leading-relaxed border-t border-zinc-800/60 bg-zinc-950/40">
                        {msg.reasoning}
                      </div>
                    )}
                  </div>
                )}

                {/* Tool Executions (for assistant) */}
                {isAssistant && msg.toolCalls && msg.toolCalls.length > 0 && (
                  <div className="w-full mb-3 space-y-2">
                    {msg.toolCalls.map((tool) => {
                      const isToolOpen = expandedTools[tool.id];
                      return (
                        <div
                          key={tool.id}
                          id={`tool-card-${tool.id}`}
                          className="rounded-lg border border-zinc-800 bg-zinc-900/80 overflow-hidden text-xs"
                        >
                          <div
                            onClick={() => toggleTool(tool.id)}
                            className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-zinc-800/50"
                          >
                            <div className="flex items-center gap-2">
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                              <span className="font-mono font-medium text-zinc-200">{tool.name}</span>
                              <span className="text-[10px] text-emerald-400 bg-emerald-950/50 border border-emerald-800/60 px-1.5 py-0.2 rounded font-mono">
                                completed
                              </span>
                            </div>
                            <div className="flex items-center gap-2 text-zinc-500">
                              <span className="text-[10px] font-mono">Tool Call</span>
                              {isToolOpen ? (
                                <ChevronDown className="w-3.5 h-3.5" />
                              ) : (
                                <ChevronRight className="w-3.5 h-3.5" />
                              )}
                            </div>
                          </div>

                          {isToolOpen && (
                            <div className="p-3 border-t border-zinc-800 font-mono text-[11px] space-y-2 bg-zinc-950/60">
                              <div>
                                <div className="text-zinc-500 text-[10px] uppercase font-semibold mb-1">Arguments:</div>
                                <pre className="p-2 rounded bg-zinc-900 text-zinc-300 overflow-x-auto">
                                  {JSON.stringify(tool.arguments, null, 2)}
                                </pre>
                              </div>
                              {tool.result && (
                                <div>
                                  <div className="text-zinc-500 text-[10px] uppercase font-semibold mb-1">Result:</div>
                                  <pre className="p-2 rounded bg-zinc-900/90 text-emerald-300/90 overflow-x-auto whitespace-pre-wrap">
                                    {tool.result}
                                  </pre>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Message Content Bubble */}
                <div
                  className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    isUser
                      ? 'bg-amber-500 text-zinc-950 font-medium rounded-tr-sm shadow-md'
                      : 'bg-zinc-900/90 text-zinc-100 rounded-tl-sm border border-zinc-800/80 shadow-sm w-full'
                  }`}
                >
                  {isUser ? (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  ) : (
                    <div className="prose prose-invert prose-sm max-w-none text-zinc-200">
                      <Markdown>{msg.content}</Markdown>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {isLoading && (
            <div className="flex items-center gap-3 p-4 rounded-xl bg-zinc-900/60 border border-zinc-800/80 max-w-md">
              <div className="flex space-x-1.5">
                <div className="w-2 h-2 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '0ms' }}></div>
                <div className="w-2 h-2 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '150ms' }}></div>
                <div className="w-2 h-2 rounded-full bg-amber-400 animate-bounce" style={{ animationDelay: '300ms' }}></div>
              </div>
              <span className="text-xs text-zinc-400 font-mono">Agent executing reasoning loop & tools...</span>
            </div>
          )}
        </div>

        {/* Chat Input Bar */}
        <div className="p-4 border-t border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md">
          <form onSubmit={handleSubmit} className="relative flex flex-col rounded-xl border border-zinc-800 bg-zinc-900/90 shadow-lg focus-within:border-amber-500/60 transition-colors">
            <textarea
              id="input-chat-message"
              rows={2}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask nanobot to run tools, edit files, schedule cron jobs, or search... (Enter to send, Shift+Enter for new line)"
              className="w-full px-4 pt-3 pb-10 bg-transparent text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none resize-none"
            />

            <div className="absolute bottom-2.5 left-3 right-3 flex items-center justify-between text-xs text-zinc-500">
              <div className="flex items-center gap-2 text-[11px]">
                <span className="bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-400 font-mono">/help</span>
                <span className="bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-400 font-mono">/dream</span>
                <span className="bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-400 font-mono">/skills</span>
              </div>

              <button
                id="btn-send-message"
                type="submit"
                disabled={!inputText.trim() || isLoading}
                className="flex items-center gap-1.5 px-3.5 py-1.5 bg-amber-500 hover:bg-amber-400 disabled:opacity-40 disabled:hover:bg-amber-500 text-zinc-950 font-semibold rounded-lg text-xs transition-colors cursor-pointer"
              >
                <span>Send</span>
                <CornerDownLeft className="w-3.5 h-3.5 stroke-[2.5]" />
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
};
