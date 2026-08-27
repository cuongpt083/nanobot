import React, { useState } from 'react';
import {
  Cpu,
  Plus,
  Trash2,
  Check,
  Sparkles,
  Zap,
  Sliders,
  ShieldAlert,
  Layers,
  ArrowRight,
  Flame
} from 'lucide-react';
import { NanobotFullConfig, ModelPresetItemConfig } from '../../../types';

interface ModelPresetsTabProps {
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => void;
}

export const ModelPresetsTab: React.FC<ModelPresetsTabProps> = ({
  config,
  onUpdateConfig,
}) => {
  const modelPresets = config.modelPresets || {};
  const activePresetId = config.agents?.defaults?.modelPreset || 'primary';
  const fallbackModels = config.agents?.defaults?.fallbackModels || [];

  const [editingPresetId, setEditingPresetId] = useState<string>(activePresetId);
  const [isCreating, setIsCreating] = useState<boolean>(false);

  const [newPresetForm, setNewPresetForm] = useState<Partial<ModelPresetItemConfig>>({
    id: '',
    name: '',
    provider: 'gemini',
    model: '',
    maxTokens: 8192,
    contextWindowTokens: 128000,
    temperature: 0.7,
    reasoningEffort: 'medium',
  });

  const handleSetActive = (id: string) => {
    onUpdateConfig({
      agents: {
        ...config.agents,
        defaults: {
          ...config.agents?.defaults,
          modelPreset: id,
        },
      },
    });
  };

  const handleToggleFallback = (presetKey: string) => {
    let updatedFallbacks = [...fallbackModels];
    if (updatedFallbacks.includes(presetKey)) {
      updatedFallbacks = updatedFallbacks.filter((k) => k !== presetKey);
    } else {
      updatedFallbacks.push(presetKey);
    }
    onUpdateConfig({
      agents: {
        ...config.agents,
        defaults: {
          ...config.agents?.defaults,
          fallbackModels: updatedFallbacks,
        },
      },
    });
  };

  const handleDeletePreset = (id: string) => {
    if (id === 'primary') return;
    const updated = { ...modelPresets };
    delete updated[id];
    onUpdateConfig({
      modelPresets: updated,
      agents: {
        ...config.agents,
        defaults: {
          ...config.agents?.defaults,
          modelPreset: activePresetId === id ? 'primary' : activePresetId,
          fallbackModels: fallbackModels.filter((k) => k !== id),
        },
      },
    });
    if (editingPresetId === id) {
      setEditingPresetId('primary');
    }
  };

  const handleSavePreset = (id: string, updates: Partial<ModelPresetItemConfig>) => {
    const updated = {
      ...modelPresets,
      [id]: {
        ...modelPresets[id],
        ...updates,
      },
    };
    onUpdateConfig({ modelPresets: updated });
  };

  const handleCreateNewPreset = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPresetForm.name || !newPresetForm.model) return;

    const id =
      newPresetForm.id?.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_') ||
      `preset_${Date.now()}`;

    const newPreset: ModelPresetItemConfig = {
      id,
      name: newPresetForm.name,
      provider: newPresetForm.provider || 'gemini',
      model: newPresetForm.model,
      maxTokens: Number(newPresetForm.maxTokens) || 8192,
      contextWindowTokens: Number(newPresetForm.contextWindowTokens) || 128000,
      temperature: Number(newPresetForm.temperature) || 0.7,
      reasoningEffort: newPresetForm.reasoningEffort,
    };

    onUpdateConfig({
      modelPresets: {
        ...modelPresets,
        [id]: newPreset,
      },
    });

    setIsCreating(false);
    setEditingPresetId(id);
    setNewPresetForm({
      id: '',
      name: '',
      provider: 'gemini',
      model: '',
      maxTokens: 8192,
      contextWindowTokens: 128000,
      temperature: 0.7,
    });
  };

  const selectedPreset = modelPresets[editingPresetId] || modelPresets['primary'];

  return (
    <div className="flex h-full gap-6 text-zinc-300">
      {/* Presets List */}
      <div className="w-80 flex-shrink-0 border-r border-zinc-800/80 pr-4 space-y-3 overflow-y-auto">
        <div className="flex items-center justify-between">
          <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
            Model Presets
          </div>
          <button
            onClick={() => setIsCreating(true)}
            className="flex items-center gap-1 px-2 py-1 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-semibold transition-colors cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New Preset</span>
          </button>
        </div>

        <div className="space-y-1.5">
          {Object.entries(modelPresets).map(([id, preset]) => {
            const isActive = activePresetId === id;
            const isSelected = editingPresetId === id && !isCreating;
            const isFallback = fallbackModels.includes(id);

            return (
              <div
                key={id}
                onClick={() => {
                  setEditingPresetId(id);
                  setIsCreating(false);
                }}
                className={`p-3 rounded-xl border transition-all cursor-pointer ${
                  isSelected
                    ? 'bg-amber-500/10 border-amber-500/60'
                    : 'bg-zinc-950/40 hover:bg-zinc-900 border-zinc-800/60'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="text-xs font-bold text-zinc-100 truncate flex items-center gap-1.5">
                    <span>{preset.name || id}</span>
                    {isActive && (
                      <span className="px-1.5 py-0.2 rounded bg-amber-500 text-zinc-950 font-semibold text-[9px]">
                        ACTIVE
                      </span>
                    )}
                  </div>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSetActive(id);
                    }}
                    className={`text-[10px] px-2 py-0.5 rounded transition-colors font-medium cursor-pointer ${
                      isActive
                        ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                        : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    {isActive ? 'Current Default' : 'Set as Active'}
                  </button>
                </div>

                <div className="flex items-center justify-between text-[11px] font-mono text-zinc-400">
                  <span className="text-amber-400/90">{preset.provider}</span>
                  <span className="truncate max-w-[140px] text-zinc-400">{preset.model}</span>
                </div>

                <div className="flex items-center justify-between mt-2 pt-2 border-t border-zinc-800/50 text-[10px]">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleToggleFallback(id);
                    }}
                    className={`flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors ${
                      isFallback
                        ? 'text-sky-400 bg-sky-950/60 border border-sky-800/60'
                        : 'text-zinc-500 hover:text-zinc-400'
                    }`}
                  >
                    <Layers className="w-3 h-3" />
                    <span>{isFallback ? 'In Fallback Chain' : '+ Fallback'}</span>
                  </button>

                  {id !== 'primary' && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeletePreset(id);
                      }}
                      className="text-zinc-600 hover:text-rose-400 transition-colors p-0.5"
                      title="Delete preset"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Fallback Chain Overview */}
        <div className="p-3 rounded-xl bg-zinc-950/60 border border-zinc-800/80 space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-200">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
            <span>Automatic Failover Chain</span>
          </div>
          <p className="text-[11px] text-zinc-400 leading-relaxed">
            If the primary model ({activePresetId}) hits rate limits (429) or context limits, Nanobot seamlessly degrades down the chain:
          </p>
          <div className="flex items-center gap-1 flex-wrap font-mono text-[10px]">
            <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold border border-amber-500/40">
              {activePresetId}
            </span>
            {fallbackModels.map((fb) => (
              <React.Fragment key={fb}>
                <ArrowRight className="w-3 h-3 text-zinc-500" />
                <span className="px-2 py-0.5 rounded bg-zinc-800 text-sky-300 border border-zinc-700">
                  {fb}
                </span>
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>

      {/* Preset Details / Creation Form */}
      <div className="flex-1 overflow-y-auto pr-2 space-y-5">
        {isCreating ? (
          /* Create Form */
          <form onSubmit={handleCreateNewPreset} className="space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <h4 className="text-sm font-bold text-zinc-100">Create New Model Preset</h4>
              <button
                type="button"
                onClick={() => setIsCreating(false)}
                className="text-xs text-zinc-400 hover:text-zinc-200"
              >
                Cancel
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Preset Display Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Claude 3.7 Coding Beast"
                  value={newPresetForm.name}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, name: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Provider</label>
                <select
                  value={newPresetForm.provider}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, provider: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                >
                  <option value="gemini">Google Gemini</option>
                  <option value="openrouter">OpenRouter Gateway</option>
                  <option value="anthropic">Anthropic Direct</option>
                  <option value="openai">OpenAI Direct</option>
                  <option value="deepseek">DeepSeek Direct</option>
                  <option value="groq">Groq Cloud</option>
                  <option value="mistral">Mistral AI</option>
                  <option value="ollama">Ollama (Local)</option>
                  <option value="custom">Custom Endpoint</option>
                </select>
              </div>

              <div className="space-y-1.5 col-span-2">
                <label className="text-xs font-semibold text-zinc-200">Model Identifier / ID</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. claude-3-7-sonnet-20250219 or deepseek/deepseek-r1"
                  value={newPresetForm.model}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, model: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 font-mono text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Max Generation Tokens</label>
                <input
                  type="number"
                  value={newPresetForm.maxTokens}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, maxTokens: Number(e.target.value) })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Context Window Limit</label>
                <input
                  type="number"
                  value={newPresetForm.contextWindowTokens}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, contextWindowTokens: Number(e.target.value) })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Sampling Temperature (0.0 - 2.0)</label>
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="2"
                  value={newPresetForm.temperature}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, temperature: Number(e.target.value) })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Reasoning Effort</label>
                <select
                  value={newPresetForm.reasoningEffort}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, reasoningEffort: e.target.value as any })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200"
                >
                  <option value="low">Low (Faster, standard CoT)</option>
                  <option value="medium">Medium (Balanced)</option>
                  <option value="high">High (Deep reasoning / coding)</option>
                </select>
              </div>
            </div>

            <div className="pt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsCreating(false)}
                className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-300"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-xs font-bold text-zinc-950"
              >
                Save Preset
              </button>
            </div>
          </form>
        ) : selectedPreset ? (
          /* Preset Editor */
          <div className="space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div>
                <h4 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
                  <span>{selectedPreset.name || editingPresetId}</span>
                  {activePresetId === editingPresetId && (
                    <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-mono">
                      Active Model
                    </span>
                  )}
                </h4>
                <div className="text-[11px] text-zinc-400 mt-0.5 font-mono">
                  modelPresets.{editingPresetId}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleSetActive(editingPresetId)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                    activePresetId === editingPresetId
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : 'bg-amber-500 hover:bg-amber-400 text-zinc-950'
                  }`}
                >
                  {activePresetId === editingPresetId ? '✓ Currently Active' : 'Switch to this Model'}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Preset Display Name</label>
                <input
                  type="text"
                  value={selectedPreset.name || ''}
                  onChange={(e) => handleSavePreset(editingPresetId, { name: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Provider</label>
                <select
                  value={selectedPreset.provider}
                  onChange={(e) => handleSavePreset(editingPresetId, { provider: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                >
                  <option value="gemini">Google Gemini</option>
                  <option value="openrouter">OpenRouter Gateway</option>
                  <option value="anthropic">Anthropic Direct</option>
                  <option value="openai">OpenAI Direct</option>
                  <option value="deepseek">DeepSeek Direct</option>
                  <option value="groq">Groq Cloud</option>
                  <option value="mistral">Mistral AI</option>
                  <option value="ollama">Ollama (Local)</option>
                  <option value="custom">Custom Endpoint</option>
                </select>
              </div>

              <div className="space-y-1.5 col-span-2">
                <label className="text-xs font-semibold text-zinc-200">Model Identifier / ID</label>
                <input
                  type="text"
                  value={selectedPreset.model}
                  onChange={(e) => handleSavePreset(editingPresetId, { model: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 font-mono text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Max Generation Tokens</label>
                <input
                  type="number"
                  value={selectedPreset.maxTokens || 8192}
                  onChange={(e) => handleSavePreset(editingPresetId, { maxTokens: Number(e.target.value) })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Context Window Limit (Tokens)</label>
                <input
                  type="number"
                  value={selectedPreset.contextWindowTokens || 128000}
                  onChange={(e) =>
                    handleSavePreset(editingPresetId, { contextWindowTokens: Number(e.target.value) })
                  }
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Temperature</label>
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="2"
                  value={selectedPreset.temperature ?? 0.7}
                  onChange={(e) =>
                    handleSavePreset(editingPresetId, { temperature: Number(e.target.value) })
                  }
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Reasoning Effort</label>
                <select
                  value={selectedPreset.reasoningEffort || 'medium'}
                  onChange={(e) =>
                    handleSavePreset(editingPresetId, { reasoningEffort: e.target.value as any })
                  }
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200"
                >
                  <option value="low">Low (Fast CoT)</option>
                  <option value="medium">Medium</option>
                  <option value="high">High (Deep reasoning)</option>
                </select>
              </div>
            </div>

            {/* Global Default System Prompt Override */}
            <div className="space-y-1.5 pt-3 border-t border-zinc-800">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-zinc-200">
                  Default Agent System Prompt (agents.defaults.systemPrompt)
                </label>
                <span className="text-[10px] text-zinc-500">Applies to all sessions using this gateway</span>
              </div>
              <textarea
                rows={3}
                value={config.agents?.defaults?.systemPrompt || ''}
                onChange={(e) =>
                  onUpdateConfig({
                    agents: {
                      ...config.agents,
                      defaults: {
                        ...config.agents?.defaults,
                        systemPrompt: e.target.value,
                      },
                    },
                  })
                }
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-300 font-mono focus:outline-none focus:border-amber-500"
                placeholder="Agent identity, directives, and system prompt instructions..."
              />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};
