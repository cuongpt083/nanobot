import React, { useState, useEffect, useRef } from 'react';
import {
  Sparkles,
  Command,
  Search,
  ArrowRight,
  X,
  Bot,
  Terminal,
  FolderOpen,
  Cpu,
  CornerDownLeft,
  CheckCircle2,
  Clock
} from 'lucide-react';
import { ToolCall } from '../types';

interface QuickSummonModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSendToChat: (query: string) => void;
}

export const QuickSummonModal: React.FC<QuickSummonModalProps> = ({
  isOpen,
  onClose,
  onSendToChat,
}) => {
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState<string | null>(null);
  const [reasoning, setReasoning] = useState<string | null>(null);
  const [activeTools, setActiveTools] = useState<ToolCall[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setQuery('');
      setResponse(null);
      setReasoning(null);
      setActiveTools([]);
    }
  }, [isOpen]);

  // Handle global Alt+Space or Escape hotkey
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleExecute = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || isLoading) return;

    setIsLoading(true);
    setResponse(null);
    setReasoning(null);
    setActiveTools([]);

    try {
      // Direct fast API call
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId: 'sess-quick-summon',
          message: query,
          model: 'gemini-2.5-flash',
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setResponse(data.message.content);
        setReasoning(data.message.reasoning);
        setActiveTools(data.message.toolCalls || []);
      }
    } catch (err: any) {
      setResponse(`Error executing query: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenInMainChat = () => {
    onSendToChat(query);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-start justify-center pt-24 px-4 z-50 animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl bg-zinc-900/95 border border-zinc-700/80 rounded-2xl shadow-2xl overflow-hidden backdrop-blur-xl ring-1 ring-white/10"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Input Bar */}
        <form
          onSubmit={handleExecute}
          className="flex items-center gap-3 px-4 py-3.5 border-b border-zinc-800 bg-zinc-900/90"
        >
          <div className="p-1.5 rounded-lg bg-amber-500/10 text-amber-400">
            <Sparkles className="w-5 h-5" />
          </div>

          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask Nanobot anything, execute MCP tool, or search files..."
            className="flex-1 bg-transparent text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none font-medium"
          />

          <div className="flex items-center gap-2">
            {isLoading ? (
              <div className="w-4 h-4 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
            ) : (
              <button
                type="submit"
                className="p-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 transition-colors cursor-pointer shadow-xs"
                title="Run Query (Enter)"
              >
                <CornerDownLeft className="w-4 h-4 stroke-[2.5]" />
              </button>
            )}

            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </form>

        {/* Quick Suggestions / Tool Presets if query empty */}
        {!response && !isLoading && (
          <div className="p-4 space-y-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 px-1">
              Quick Desktop Actions
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setQuery('List all files and configs in my local workspace');
                  setTimeout(() => inputRef.current?.focus(), 20);
                }}
                className="p-2.5 rounded-xl bg-zinc-950/60 border border-zinc-800/80 hover:border-zinc-700 hover:bg-zinc-800/50 text-left transition-all flex items-center gap-2.5 group cursor-pointer"
              >
                <FolderOpen className="w-4 h-4 text-amber-400" />
                <div>
                  <div className="text-xs font-semibold text-zinc-200 group-hover:text-amber-300">
                    Inspect Workspace Files
                  </div>
                  <div className="text-[10px] text-zinc-500">MCP Filesystem query</div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => {
                  setQuery('Search the web for the latest Gemini 2.5 and Claude 3.7 updates');
                  setTimeout(() => inputRef.current?.focus(), 20);
                }}
                className="p-2.5 rounded-xl bg-zinc-950/60 border border-zinc-800/80 hover:border-zinc-700 hover:bg-zinc-800/50 text-left transition-all flex items-center gap-2.5 group cursor-pointer"
              >
                <Search className="w-4 h-4 text-sky-400" />
                <div>
                  <div className="text-xs font-semibold text-zinc-200 group-hover:text-sky-300">
                    Live Web Query
                  </div>
                  <div className="text-[10px] text-zinc-500">Brave Search MCP</div>
                </div>
              </button>
            </div>
          </div>
        )}

        {/* Live Response Card */}
        {response && (
          <div className="p-5 max-h-[380px] overflow-y-auto space-y-4 text-xs">
            {/* Tool Executions Badge */}
            {activeTools.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {activeTools.map((t) => (
                  <div
                    key={t.id}
                    className="px-2.5 py-1 rounded-lg bg-zinc-950 border border-zinc-800 text-[11px] font-mono text-amber-400 flex items-center gap-1.5"
                  >
                    <Cpu className="w-3.5 h-3.5" />
                    <span>{t.name}</span>
                    <span className="text-[10px] text-emerald-400 font-bold">✓</span>
                  </div>
                ))}
              </div>
            )}

            {/* Answer Content */}
            <div className="p-4 rounded-xl bg-zinc-950/80 border border-zinc-800/80 text-zinc-200 leading-relaxed font-sans whitespace-pre-wrap">
              {response}
            </div>

            {/* Bottom Actions */}
            <div className="flex items-center justify-between pt-2 border-t border-zinc-800 text-[11px] text-zinc-400">
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3 text-zinc-500" />
                Generated via Nanobot Local Engine
              </span>

              <button
                type="button"
                onClick={handleOpenInMainChat}
                className="flex items-center gap-1 text-amber-400 hover:text-amber-300 font-semibold cursor-pointer"
              >
                <span>Continue in Full Chat</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}

        {/* Footer shortcuts */}
        <div className="px-4 py-2 bg-zinc-950 border-t border-zinc-800/80 flex items-center justify-between text-[10px] text-zinc-500 font-mono">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400">
                ↵
              </kbd>{' '}
              Submit
            </span>
            <span>
              <kbd className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400">
                Esc
              </kbd>{' '}
              Dismiss
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span>Nanobot Desktop Gateway Connected</span>
          </div>
        </div>
      </div>
    </div>
  );
};
