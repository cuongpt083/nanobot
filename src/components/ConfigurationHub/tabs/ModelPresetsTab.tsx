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
  Flame,
  Tag,
  CheckCircle2,
  Bot
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
  const providers = config.providers || {};
  const activePresetId = config.agents?.defaults?.modelPreset || 'primary';
  const fallbackModels = config.agents?.defaults?.fallbackModels || [];

  const [editingPresetId, setEditingPresetId] = useState<string>(activePresetId);
  const [isCreating, setIsCreating] = useState<boolean>(false);

  // Determine provider options based on user's configured providers
  const configuredProviderEntries = Object.entries(providers);
  const defaultProviderKey = configuredProviderEntries[0]?.[0] || 'gemini';

  const [newPresetForm, setNewPresetForm] = useState<Partial<ModelPresetItemConfig>>({
    id: '',
    name: '',
    provider: defaultProviderKey,
    model: providers[defaultProviderKey]?.defaultModel || providers[defaultProviderKey]?.modelList?.[0] || 'gemini-2.5-flash',
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

  const handleDeletePreset = (id: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
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
      provider: newPresetForm.provider || defaultProviderKey,
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
      provider: defaultProviderKey,
      model: providers[defaultProviderKey]?.defaultModel || providers[defaultProviderKey]?.modelList?.[0] || 'gemini-2.5-flash',
      maxTokens: 8192,
      contextWindowTokens: 128000,
      temperature: 0.7,
    });
  };

  const selectedPreset = modelPresets[editingPresetId] || modelPresets['primary'];

  // Helper to get provider alias
  const getProviderDisplayLabel = (providerKey: string) => {
    const p = providers[providerKey];
    if (p) {
      return p.alias || p.name || providerKey;
    }
    return providerKey;
  };

  // Helper to get available models for a provider
  const getProviderModels = (providerKey: string): string[] => {
    const p = providers[providerKey];
    if (p && p.modelList && p.modelList.length > 0) {
      return p.modelList;
    }
    return [];
  };

  const currentEditingProviderKey = isCreating
    ? (newPresetForm.provider || defaultProviderKey)
    : (selectedPreset?.provider || defaultProviderKey);

  const availableModelsForCurrent = getProviderModels(currentEditingProviderKey);

  return (
    <div className="flex h-full gap-6 text-zinc-300">
      {/* Left Column: Concise & Clean Model Presets List */}
      <div className="w-84 flex-shrink-0 border-r border-zinc-800/80 pr-4 space-y-3.5 overflow-y-auto flex flex-col justify-between">
        <div className="space-y-3">
          {/* Header & Add Action */}
          <div className="flex items-center justify-between">
            <div className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider">
              Danh sách Model Presets ({Object.keys(modelPresets).length})
            </div>
            <button
              onClick={() => {
                setIsCreating(true);
                setNewPresetForm({
                  id: '',
                  name: '',
                  provider: defaultProviderKey,
                  model: providers[defaultProviderKey]?.defaultModel || providers[defaultProviderKey]?.modelList?.[0] || 'gemini-2.5-flash',
                  maxTokens: 8192,
                  contextWindowTokens: 128000,
                  temperature: 0.7,
                });
              }}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-bold transition-colors cursor-pointer shadow-xs"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Thêm Preset</span>
            </button>
          </div>

          {/* Concise Model Presets Item List */}
          <div className="space-y-2">
            {Object.entries(modelPresets).map(([id, preset]) => {
              const isActive = activePresetId === id;
              const isSelected = editingPresetId === id && !isCreating;
              const fallbackIndex = fallbackModels.indexOf(id);
              const isFallback = fallbackIndex !== -1;
              const providerLabel = getProviderDisplayLabel(preset.provider);

              return (
                <div
                  key={id}
                  onClick={() => {
                    setEditingPresetId(id);
                    setIsCreating(false);
                  }}
                  className={`p-2.5 rounded-xl border transition-all cursor-pointer relative group ${
                    isSelected
                      ? 'bg-amber-500/10 border-amber-500/60 shadow-xs ring-1 ring-amber-500/30'
                      : 'bg-zinc-950/50 hover:bg-zinc-900/80 border-zinc-800/70'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-xs font-bold text-zinc-100 truncate flex items-center gap-1.5 min-w-0 pr-2">
                      <span className="truncate">{preset.name || id}</span>
                      {isActive && (
                        <span className="px-1.5 py-0.2 rounded bg-amber-500 text-zinc-950 font-bold text-[9px] flex-shrink-0">
                          ACTIVE
                        </span>
                      )}
                    </div>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSetActive(id);
                      }}
                      className={`text-[10px] px-2 py-0.5 rounded transition-colors font-medium cursor-pointer flex-shrink-0 ${
                        isActive
                          ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 font-semibold'
                          : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200'
                      }`}
                      title={isActive ? 'Đang là model chính' : 'Đặt làm model mặc định'}
                    >
                      {isActive ? '✓ Mặc định' : 'Đặt mặc định'}
                    </button>
                  </div>

                  {/* Provider Alias & Model Name */}
                  <div className="flex items-center justify-between text-[11px] font-mono text-zinc-400 mt-1">
                    <span className="text-amber-400/90 truncate max-w-[120px] font-sans font-medium text-[11px]">
                      {providerLabel}
                    </span>
                    <span className="truncate max-w-[150px] text-zinc-300 bg-zinc-900/90 px-1.5 py-0.2 rounded border border-zinc-800/80 text-[10px]">
                      {preset.model}
                    </span>
                  </div>

                  {/* Bottom Actions: Fallback toggle & Delete */}
                  <div className="flex items-center justify-between mt-2 pt-1.5 border-t border-zinc-800/60 text-[10px]">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleToggleFallback(id);
                      }}
                      className={`flex items-center gap-1 px-1.5 py-0.5 rounded transition-colors cursor-pointer ${
                        isFallback
                          ? 'text-sky-300 bg-sky-950/80 border border-sky-800/80 font-medium'
                          : 'text-zinc-500 hover:text-zinc-400'
                      }`}
                      title="Thêm hoặc gỡ khỏi chuỗi dự phòng Failover"
                    >
                      <Layers className="w-3 h-3" />
                      <span>{isFallback ? `Failover #${fallbackIndex + 1}` : '+ Thêm Failover'}</span>
                    </button>

                    {id !== 'primary' && (
                      <button
                        onClick={(e) => handleDeletePreset(id, e)}
                        className="text-zinc-600 hover:text-rose-400 transition-colors p-1 cursor-pointer"
                        title="Xóa preset này"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Fallback Failover Chain Summary */}
        <div className="p-3 rounded-xl bg-zinc-950/60 border border-zinc-800/80 space-y-2 text-xs">
          <div className="flex items-center gap-1.5 font-bold text-zinc-200">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
            <span>Chuỗi tự động chuyển đổi (Failover Chain)</span>
          </div>
          <p className="text-[10px] text-zinc-400 leading-relaxed">
            Nếu Model chính gặp sự cố (Rate Limit 429 hoặc quá tải), Nanobot sẽ tuần tự fallback sang các models tiếp theo:
          </p>
          <div className="flex items-center gap-1 flex-wrap font-mono text-[10px] pt-1">
            <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold border border-amber-500/40">
              {modelPresets[activePresetId]?.name || activePresetId}
            </span>
            {fallbackModels.map((fb) => (
              <React.Fragment key={fb}>
                <ArrowRight className="w-3 h-3 text-zinc-500" />
                <span className="px-2 py-0.5 rounded bg-zinc-900 text-sky-300 border border-zinc-700 font-sans font-medium text-[10px]">
                  {modelPresets[fb]?.name || fb}
                </span>
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>

      {/* Right Column: Model Preset Editor or Creation Form */}
      <div className="flex-1 overflow-y-auto pr-2 space-y-5">
        {isCreating ? (
          /* Create New Preset Form */
          <form onSubmit={handleCreateNewPreset} className="space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <div>
                <h4 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
                  <Plus className="w-4 h-4 text-amber-400" />
                  <span>Tạo Model Preset Mới</span>
                </h4>
                <p className="text-xs text-zinc-400 mt-0.5">
                  Cấu hình preset model với provider và tham số inference riêng biệt.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsCreating(false)}
                className="px-3 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs text-zinc-300 transition-colors cursor-pointer"
              >
                Hủy
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5 col-span-2 md:col-span-1">
                <label className="text-xs font-bold text-zinc-200">Tên hiển thị Preset (Alias)</label>
                <input
                  type="text"
                  required
                  placeholder="VD: Claude 3.7 Coding Beast, Gemini Fast"
                  value={newPresetForm.name}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, name: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="space-y-1.5 col-span-2 md:col-span-1">
                <label className="text-xs font-bold text-zinc-200">Chọn Provider (Theo Alias)</label>
                <select
                  value={newPresetForm.provider}
                  onChange={(e) => {
                    const chosenProv = e.target.value;
                    const pModels = getProviderModels(chosenProv);
                    const defaultM = providers[chosenProv]?.defaultModel || pModels[0] || '';
                    setNewPresetForm({
                      ...newPresetForm,
                      provider: chosenProv,
                      model: defaultM || newPresetForm.model,
                    });
                  }}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500 cursor-pointer"
                >
                  {configuredProviderEntries.length > 0 ? (
                    configuredProviderEntries.map(([pKey, pVal]) => (
                      <option key={pKey} value={pKey}>
                        {pVal.alias || pVal.name || pKey} ({pKey})
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="gemini">Google Gemini</option>
                      <option value="openrouter">OpenRouter Gateway</option>
                      <option value="anthropic">Anthropic Direct</option>
                      <option value="openai">OpenAI Direct</option>
                      <option value="deepseek">DeepSeek Direct</option>
                      <option value="groq">Groq Cloud</option>
                      <option value="ollama">Ollama (Local)</option>
                    </>
                  )}
                </select>
              </div>

              <div className="space-y-1.5 col-span-2">
                <label className="text-xs font-bold text-zinc-200 flex items-center justify-between">
                  <span>Mã Model (Model Identifier / ID)</span>
                  {availableModelsForCurrent.length > 0 && (
                    <span className="text-[10px] text-zinc-400">
                      Chọn nhanh từ {availableModelsForCurrent.length} models đã quét
                    </span>
                  )}
                </label>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {availableModelsForCurrent.length > 0 && (
                    <select
                      value={newPresetForm.model || availableModelsForCurrent[0]}
                      onChange={(e) => setNewPresetForm({ ...newPresetForm, model: e.target.value })}
                      className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-amber-300 font-semibold focus:outline-none focus:border-amber-500 cursor-pointer"
                    >
                      {availableModelsForCurrent.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  )}
                  <input
                    type="text"
                    required
                    placeholder="VD: claude-3-7-sonnet-20250219 hoặc gemini-2.5-flash"
                    value={newPresetForm.model}
                    onChange={(e) => setNewPresetForm({ ...newPresetForm, model: e.target.value })}
                    className={`w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 font-mono text-xs text-zinc-200 focus:outline-none focus:border-amber-500 ${
                      availableModelsForCurrent.length === 0 ? 'col-span-2' : ''
                    }`}
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-bold text-zinc-200">Max Output Tokens</label>
                <input
                  type="number"
                  value={newPresetForm.maxTokens}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, maxTokens: Number(e.target.value) })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-bold text-zinc-200">Context Window Tokens</label>
                <input
                  type="number"
                  value={newPresetForm.contextWindowTokens}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, contextWindowTokens: Number(e.target.value) })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-bold text-zinc-200 flex items-center justify-between">
                  <span>Temperature ({newPresetForm.temperature})</span>
                  <span className="text-[10px] text-zinc-500">0.0 (Chính xác) - 1.0 (Sáng tạo)</span>
                </label>
                <input
                  type="range"
                  step="0.05"
                  min="0"
                  max="1.5"
                  value={newPresetForm.temperature}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, temperature: Number(e.target.value) })}
                  className="w-full accent-amber-500 cursor-pointer"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-bold text-zinc-200">Reasoning Effort</label>
                <select
                  value={newPresetForm.reasoningEffort}
                  onChange={(e) => setNewPresetForm({ ...newPresetForm, reasoningEffort: e.target.value as any })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 cursor-pointer"
                >
                  <option value="low">Low (Nhanh, suy luận cơ bản)</option>
                  <option value="medium">Medium (Cân bằng)</option>
                  <option value="high">High (Suy luận chuyên sâu / Lập trình phức tạp)</option>
                </select>
              </div>
            </div>

            <div className="pt-4 flex justify-end gap-2 border-t border-zinc-800">
              <button
                type="button"
                onClick={() => setIsCreating(false)}
                className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-300 cursor-pointer"
              >
                Hủy
              </button>
              <button
                type="submit"
                className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-xs font-bold text-zinc-950 cursor-pointer shadow-xs"
              >
                Lưu Preset
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
                    <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-mono border border-amber-500/40">
                      Model chính hiện tại
                    </span>
                  )}
                </h4>
                <div className="text-[11px] text-zinc-400 mt-0.5 font-mono">
                  Provider: <span className="text-amber-400">{getProviderDisplayLabel(selectedPreset.provider)}</span> • Model: <span className="text-zinc-200">{selectedPreset.model}</span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleSetActive(editingPresetId)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer shadow-xs ${
                    activePresetId === editingPresetId
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : 'bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold'
                  }`}
                >
                  {activePresetId === editingPresetId ? '✓ Đang kích hoạt' : 'Chuyển sang Model này'}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5 col-span-2 md:col-span-1">
                <label className="text-xs font-bold text-zinc-200">Tên hiển thị Preset (Alias)</label>
                <input
                  type="text"
                  value={selectedPreset.name || ''}
                  onChange={(e) => handleSavePreset(editingPresetId, { name: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="space-y-1.5 col-span-2 md:col-span-1">
                <label className="text-xs font-bold text-zinc-200">Provider (Theo Alias)</label>
                <select
                  value={selectedPreset.provider}
                  onChange={(e) => {
                    const chosenProv = e.target.value;
                    const pModels = getProviderModels(chosenProv);
                    const defaultM = providers[chosenProv]?.defaultModel || pModels[0] || '';
                    handleSavePreset(editingPresetId, {
                      provider: chosenProv,
                      model: defaultM || selectedPreset.model,
                    });
                  }}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500 cursor-pointer"
                >
                  {configuredProviderEntries.length > 0 ? (
                    configuredProviderEntries.map(([pKey, pVal]) => (
                      <option key={pKey} value={pKey}>
                        {pVal.alias || pVal.name || pKey} ({pKey})
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="gemini">Google Gemini</option>
                      <option value="openrouter">OpenRouter Gateway</option>
                      <option value="anthropic">Anthropic Direct</option>
                      <option value="openai">OpenAI Direct</option>
                      <option value="deepseek">DeepSeek Direct</option>
                      <option value="groq">Groq Cloud</option>
                      <option value="ollama">Ollama (Local)</option>
                    </>
                  )}
                </select>
              </div>

              <div className="space-y-1.5 col-span-2">
                <label className="text-xs font-bold text-zinc-200 flex items-center justify-between">
                  <span>Mã Model (Model Identifier / ID)</span>
                  {availableModelsForCurrent.length > 0 && (
                    <span className="text-[10px] text-zinc-400">
                      Chọn nhanh từ {availableModelsForCurrent.length} models đã quét của Provider
                    </span>
                  )}
                </label>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {availableModelsForCurrent.length > 0 && (
                    <select
                      value={selectedPreset.model}
                      onChange={(e) => handleSavePreset(editingPresetId, { model: e.target.value })}
                      className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-amber-300 font-semibold focus:outline-none focus:border-amber-500 cursor-pointer"
                    >
                      {availableModelsForCurrent.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  )}
                  <input
                    type="text"
                    value={selectedPreset.model || ''}
                    onChange={(e) => handleSavePreset(editingPresetId, { model: e.target.value })}
                    className={`w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 font-mono text-xs text-zinc-200 focus:outline-none focus:border-amber-500 ${
                      availableModelsForCurrent.length === 0 ? 'col-span-2' : ''
                    }`}
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-bold text-zinc-200">Max Generation Tokens</label>
                <input
                  type="number"
                  value={selectedPreset.maxTokens || 8192}
                  onChange={(e) => handleSavePreset(editingPresetId, { maxTokens: Number(e.target.value) })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-bold text-zinc-200">Context Window Limit</label>
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
                <label className="text-xs font-bold text-zinc-200 flex items-center justify-between">
                  <span>Temperature ({selectedPreset.temperature ?? 0.7})</span>
                  <span className="text-[10px] text-zinc-500">0.0 (Chính xác) - 1.0 (Sáng tạo)</span>
                </label>
                <input
                  type="range"
                  step="0.05"
                  min="0"
                  max="1.5"
                  value={selectedPreset.temperature ?? 0.7}
                  onChange={(e) =>
                    handleSavePreset(editingPresetId, { temperature: Number(e.target.value) })
                  }
                  className="w-full accent-amber-500 cursor-pointer"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-bold text-zinc-200">Reasoning Effort</label>
                <select
                  value={selectedPreset.reasoningEffort || 'medium'}
                  onChange={(e) =>
                    handleSavePreset(editingPresetId, { reasoningEffort: e.target.value as any })
                  }
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 cursor-pointer"
                >
                  <option value="low">Low (Nhanh, suy luận cơ bản)</option>
                  <option value="medium">Medium (Cân bằng)</option>
                  <option value="high">High (Suy luận chuyên sâu / Lập trình phức tạp)</option>
                </select>
              </div>
            </div>
          </div>
        ) : (
          <div className="p-8 text-center text-zinc-500 text-xs">
            Chọn một Model Preset từ danh sách bên trái để chỉnh sửa cấu hình.
          </div>
        )}
      </div>
    </div>
  );
};
