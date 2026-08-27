import React, { useState } from 'react';
import {
  Sparkles,
  Brain,
  Trash2,
  RefreshCw,
  Tag,
  ShieldCheck,
  Zap,
  Info,
  Clock
} from 'lucide-react';
import { MemoryFact } from '../types';

interface DreamMemoryViewProps {
  facts: MemoryFact[];
  onConsolidate: () => Promise<void>;
  onDeleteFact: (factId: string) => Promise<void>;
  isConsolidating: boolean;
}

export const DreamMemoryView: React.FC<DreamMemoryViewProps> = ({
  facts,
  onConsolidate,
  onDeleteFact,
  isConsolidating,
}) => {
  const [activeCategory, setActiveCategory] = useState<string>('all');

  const categories = [
    { id: 'all', label: 'All Knowledge' },
    { id: 'user_profile', label: 'User Profile' },
    { id: 'preference', label: 'Preferences' },
    { id: 'project_state', label: 'Project State' },
    { id: 'learned_skill', label: 'Learned Skills' },
  ];

  const filteredFacts = facts.filter(
    (f) => activeCategory === 'all' || f.category === activeCategory,
  );

  const getCategoryColor = (cat: string) => {
    switch (cat) {
      case 'user_profile':
        return 'bg-blue-950/70 text-blue-300 border-blue-800/80';
      case 'preference':
        return 'bg-amber-950/70 text-amber-300 border-amber-800/80';
      case 'project_state':
        return 'bg-emerald-950/70 text-emerald-300 border-emerald-800/80';
      case 'learned_skill':
        return 'bg-purple-950/70 text-purple-300 border-purple-800/80';
      default:
        return 'bg-zinc-800 text-zinc-300 border-zinc-700';
    }
  };

  return (
    <div className="h-full overflow-y-auto p-8 max-w-5xl mx-auto space-y-6">
      {/* Top Banner */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Brain className="w-6 h-6 text-amber-400" />
            <h2 className="text-xl font-bold text-zinc-100">Dream Long-Term Memory Engine</h2>
          </div>
          <p className="text-xs text-zinc-400 max-w-2xl leading-relaxed">
            Nanobot uses a two-phase Dream memory consolidation algorithm to extract durable knowledge and preferences from sessions into <code className="text-amber-400 font-mono">MEMORY.md</code> without bloating prompt context.
          </p>
        </div>

        <button
          id="btn-trigger-dream"
          onClick={onConsolidate}
          disabled={isConsolidating}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-zinc-950 font-semibold text-xs rounded-lg transition-all shadow-md disabled:opacity-50 cursor-pointer"
        >
          <Sparkles className={`w-4 h-4 ${isConsolidating ? 'animate-spin' : ''}`} />
          <span>{isConsolidating ? 'Consolidating Dream...' : 'Run Dream Consolidation'}</span>
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800/80 flex items-center gap-3">
          <div className="p-3 rounded-lg bg-amber-500/10 text-amber-400">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-zinc-500">Active Facts Indexed</div>
            <div className="text-lg font-bold text-zinc-100 font-mono">{facts.length}</div>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800/80 flex items-center gap-3">
          <div className="p-3 rounded-lg bg-emerald-500/10 text-emerald-400">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-zinc-500">Durability Guarantee</div>
            <div className="text-xs font-semibold text-emerald-400">Atomic fsync() Writes</div>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800/80 flex items-center gap-3">
          <div className="p-3 rounded-lg bg-indigo-500/10 text-indigo-400">
            <Zap className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-zinc-500">Compaction Efficiency</div>
            <div className="text-xs font-semibold text-indigo-300">84% Prompt Token Savings</div>
          </div>
        </div>
      </div>

      {/* Category Pills */}
      <div className="flex items-center gap-2 border-b border-zinc-800/80 pb-3">
        {categories.map((c) => (
          <button
            key={c.id}
            id={`btn-cat-${c.id}`}
            onClick={() => setActiveCategory(c.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
              activeCategory === c.id
                ? 'bg-amber-500 text-zinc-950 font-semibold'
                : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Facts List */}
      <div className="space-y-3">
        {filteredFacts.length === 0 ? (
          <div className="p-12 text-center text-zinc-500 text-xs rounded-xl bg-zinc-900/30 border border-zinc-800">
            No memory entries found in this category. Click &quot;Run Dream Consolidation&quot; to synthesize active chats.
          </div>
        ) : (
          filteredFacts.map((fact) => (
            <div
              key={fact.id}
              id={`memory-fact-${fact.id}`}
              className="p-4 rounded-xl bg-zinc-900/70 border border-zinc-800 flex items-start justify-between gap-4 hover:border-zinc-700 transition-colors"
            >
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-mono border uppercase ${getCategoryColor(
                      fact.category,
                    )}`}
                  >
                    {fact.category.replace('_', ' ')}
                  </span>
                  <span className="text-[11px] font-mono text-zinc-500">
                    Confidence: {(fact.confidence * 100).toFixed(0)}%
                  </span>
                  <span className="text-[11px] text-zinc-600">•</span>
                  <span className="text-[11px] text-zinc-500 flex items-center gap-1 font-mono">
                    <Clock className="w-3 h-3" />
                    {new Date(fact.lastUpdated).toLocaleDateString()}
                  </span>
                </div>

                <p className="text-xs text-zinc-200 leading-relaxed font-sans">{fact.content}</p>
              </div>

              <button
                id={`btn-delete-fact-${fact.id}`}
                onClick={() => onDeleteFact(fact.id)}
                className="p-2 text-zinc-500 hover:text-red-400 rounded-lg hover:bg-zinc-800 transition-colors cursor-pointer"
                title="Forget Fact"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
