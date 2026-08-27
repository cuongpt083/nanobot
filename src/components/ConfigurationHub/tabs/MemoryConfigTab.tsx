import React, { useState } from 'react';
import {
  Sparkles,
  Search,
  Plus,
  Trash2,
  CheckCircle2,
  RefreshCw,
  Clock,
  BookOpen,
  Database
} from 'lucide-react';
import { NanobotFullConfig, MemoryFact } from '../../../types';

interface MemoryConfigTabProps {
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => void;
  memoryFacts: MemoryFact[];
  onTriggerDream: () => void;
  onDeleteFact: (id: string) => void;
  onAddFact: (fact: Partial<MemoryFact>) => void;
}

export const MemoryConfigTab: React.FC<MemoryConfigTabProps> = ({
  config,
  onUpdateConfig,
  memoryFacts,
  onTriggerDream,
  onDeleteFact,
  onAddFact,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [newFactContent, setNewFactContent] = useState<string>('');
  const [newFactCategory, setNewFactCategory] = useState<MemoryFact['category']>('user_profile');

  const filteredFacts = memoryFacts.filter((f) =>
    f.content.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFactContent.trim()) return;
    onAddFact({
      category: newFactCategory,
      content: newFactContent.trim(),
      confidence: 0.95,
    });
    setNewFactContent('');
  };

  return (
    <div className="flex flex-col h-full space-y-4 text-zinc-300">
      {/* Overview Card */}
      <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800/80 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-zinc-100">Dream Memory Engine</h4>
            <p className="text-xs text-zinc-400 mt-0.5">
              Consolidates long-term user facts and project constraints into durable knowledge (<code className="text-amber-400 font-mono">MEMORY.md</code>).
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onTriggerDream}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-bold transition-colors cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Trigger Dream Consolidation</span>
          </button>
        </div>
      </div>

      {/* Settings Row */}
      <div className="grid grid-cols-2 gap-4">
        <div className="p-3.5 rounded-xl bg-zinc-950/40 border border-zinc-800 space-y-1.5">
          <label className="text-xs font-semibold text-zinc-200 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-sky-400" />
            <span>Auto-Compaction Interval (Hours)</span>
          </label>
          <input
            type="number"
            value={config.gateway?.autoCompactTtlHours || 2}
            onChange={(e) =>
              onUpdateConfig({
                gateway: {
                  ...config.gateway,
                  autoCompactTtlHours: Number(e.target.value),
                },
              })
            }
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2 text-xs font-mono text-zinc-200"
          />
        </div>

        <div className="p-3.5 rounded-xl bg-zinc-950/40 border border-zinc-800 space-y-1.5">
          <label className="text-xs font-semibold text-zinc-200 flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5 text-emerald-400" />
            <span>Total Consolidated Facts</span>
          </label>
          <div className="text-sm font-mono font-bold text-zinc-100 pt-1">
            {memoryFacts.length} Active Records
          </div>
        </div>
      </div>

      {/* Add New Fact Input */}
      <form onSubmit={handleAdd} className="flex gap-2">
        <select
          value={newFactCategory}
          onChange={(e) => setNewFactCategory(e.target.value as any)}
          className="bg-zinc-950 border border-zinc-800 rounded-lg px-3 text-xs text-zinc-200"
        >
          <option value="user_profile">User Profile</option>
          <option value="preference">Preference</option>
          <option value="project_state">Project State</option>
          <option value="learned_skill">Learned Skill</option>
        </select>
        <input
          type="text"
          placeholder="Inject a new persistent fact directly into Dream Memory..."
          value={newFactContent}
          onChange={(e) => setNewFactContent(e.target.value)}
          className="flex-1 bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-zinc-200 cursor-pointer"
        >
          + Add Fact
        </button>
      </form>

      {/* Facts Table */}
      <div className="flex-1 overflow-y-auto space-y-2 border border-zinc-800/80 rounded-xl p-3 bg-zinc-950/40">
        {filteredFacts.map((fact) => (
          <div
            key={fact.id}
            className="p-3 rounded-lg bg-zinc-900/60 border border-zinc-800/80 flex items-center justify-between gap-4"
          >
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase font-mono px-1.5 py-0.2 rounded bg-zinc-800 text-amber-400">
                  {fact.category}
                </span>
                <span className="text-[10px] text-zinc-500 font-mono">
                  {Math.round(fact.confidence * 100)}% confidence
                </span>
              </div>
              <div className="text-xs text-zinc-200 font-medium">{fact.content}</div>
            </div>

            <button
              onClick={() => onDeleteFact(fact.id)}
              className="p-1.5 rounded hover:bg-rose-950 text-zinc-500 hover:text-rose-400 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};
