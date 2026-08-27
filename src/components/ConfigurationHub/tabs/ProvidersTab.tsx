import React, { useState, useEffect } from 'react';
import {
  Key,
  Globe,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  ExternalLink,
  Shield,
  Sliders,
  Check,
  Eye,
  EyeOff,
  Cpu,
  Layers,
  Sparkles,
  Plus,
  Trash2,
  Tag,
  ChevronRight,
  Server,
  Bot
} from 'lucide-react';
import { NanobotFullConfig, ProviderItemConfig } from '../../../types';

interface ProvidersTabProps {
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => void;
}

interface ProviderTemplateMeta {
  type: string;
  name: string;
  description: string;
  defaultApiBase?: string;
  supportsProxy?: boolean;
  docsUrl: string;
  recommendedModels: string[];
  isLocal?: boolean;
}

const PROVIDER_TEMPLATES: Record<string, ProviderTemplateMeta> = {
  gemini: {
    type: 'gemini',
    name: 'Google Gemini',
    description: 'Ultra-fast multimodal reasoning with massive context windows (up to 2M tokens).',
    docsUrl: 'https://ai.google.dev/',
    recommendedModels: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash', 'gemini-2.0-flash-lite'],
  },
  openrouter: {
    type: 'openrouter',
    name: 'OpenRouter Gateway',
    description: 'Unified gateway providing access to Claude 3.7, GPT-4o, DeepSeek R1, Llama 3.3, and server tools.',
    docsUrl: 'https://openrouter.ai/docs',
    recommendedModels: [
      'anthropic/claude-3.7-sonnet',
      'anthropic/claude-3.5-sonnet',
      'openai/gpt-4o',
      'openai/gpt-4o-mini',
      'deepseek/deepseek-r1',
      'meta-llama/llama-3.3-70b-instruct',
    ],
  },
  anthropic: {
    type: 'anthropic',
    name: 'Anthropic Direct',
    description: 'Direct API access for Claude 3.7 Sonnet (hybrid reasoning), Claude 3.5 Sonnet, and Claude 3.5 Haiku.',
    docsUrl: 'https://docs.anthropic.com/',
    recommendedModels: [
      'claude-3-7-sonnet-20250219',
      'claude-3-5-sonnet-20241022',
      'claude-3-5-haiku-20241022',
      'claude-3-opus-20240229',
    ],
  },
  openai: {
    type: 'openai',
    name: 'OpenAI Direct',
    description: 'GPT-4o, GPT-4o-mini, o1 reasoning models, and standard OpenAI chat completions.',
    docsUrl: 'https://platform.openai.com/docs',
    recommendedModels: ['gpt-4o', 'gpt-4o-mini', 'o1', 'o3-mini', 'gpt-4.5-preview'],
  },
  deepseek: {
    type: 'deepseek',
    name: 'DeepSeek Direct',
    description: 'DeepSeek V3 chat and DeepSeek R1 chain-of-thought reasoning models.',
    defaultApiBase: 'https://api.deepseek.com',
    docsUrl: 'https://platform.deepseek.com/',
    recommendedModels: ['deepseek-chat', 'deepseek-reasoner'],
  },
  groq: {
    type: 'groq',
    name: 'Groq Cloud',
    description: 'Sub-second LPU inference for Llama 3.3 70B, DeepSeek R1 Distill, and Mixtral.',
    docsUrl: 'https://console.groq.com/',
    recommendedModels: ['llama-3.3-70b-versatile', 'deepseek-r1-distill-llama-70b', 'mixtral-8x7b-32768'],
  },
  mistral: {
    type: 'mistral',
    name: 'Mistral AI',
    description: 'Mistral Large, Codestral for coding agent workflows, and Pixtral vision models.',
    docsUrl: 'https://docs.mistral.ai/',
    recommendedModels: ['mistral-large-latest', 'codestral-latest', 'pixtral-large-latest'],
  },
  ollama: {
    type: 'ollama',
    name: 'Ollama (Local / Air-Gapped)',
    description: 'Zero cloud latency, offline privacy on host hardware (Llama 3.2, DeepSeek R1, Qwen).',
    defaultApiBase: 'http://localhost:11434/v1',
    docsUrl: 'https://ollama.com/',
    recommendedModels: ['llama3.2:latest', 'deepseek-r1:8b', 'qwen2.5-coder:7b', 'mistral:latest'],
    isLocal: true,
  },
  custom: {
    type: 'custom',
    name: 'Custom OpenAI-Compatible Endpoint',
    description: 'Connect any proxy, vLLM, LMStudio, TGI, or internal corporate LLM gateway.',
    defaultApiBase: 'http://127.0.0.1:8000/v1',
    docsUrl: 'https://github.com/cuongpt083/nanobot/blob/main/docs/providers.md',
    recommendedModels: ['custom-llm-v1'],
  },
};

export const ProvidersTab: React.FC<ProvidersTabProps> = ({ config, onUpdateConfig }) => {
  const providers = config.providers || {};
  const providerKeys = Object.keys(providers);

  // Template dropdown selection for adding new provider
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string>('gemini');

  // Currently active/editing provider key in the list
  const [selectedProviderKey, setSelectedProviderKey] = useState<string>(
    providerKeys.length > 0 ? providerKeys[0] : 'gemini',
  );

  const [showKeyMap, setShowKeyMap] = useState<Record<string, boolean>>({});
  const [testStatus, setTestStatus] = useState<{
    loading: boolean;
    providerKey?: string;
    result?: { status: string; latencyMs: number; message: string; modelsFound: number; models?: string[]; defaultModel?: string };
    error?: string;
  }>({ loading: false });

  // If selectedProviderKey is not in config, pick first available or template
  useEffect(() => {
    if (providerKeys.length > 0 && !providers[selectedProviderKey]) {
      setSelectedProviderKey(providerKeys[0]);
    }
  }, [providers, selectedProviderKey, providerKeys]);

  const currentProviderConfig: ProviderItemConfig = providers[selectedProviderKey] || {
    alias: '',
    providerType: selectedTemplateKey,
    apiKey: '',
    apiBase: PROVIDER_TEMPLATES[selectedTemplateKey]?.defaultApiBase || '',
    modelList: PROVIDER_TEMPLATES[selectedTemplateKey]?.recommendedModels || [],
  };

  const currentProviderType = currentProviderConfig.providerType || selectedProviderKey;
  const meta = PROVIDER_TEMPLATES[currentProviderType] ||
    PROVIDER_TEMPLATES[selectedTemplateKey] || {
      type: 'custom',
      name: currentProviderType,
      description: 'Configured LLM Provider adapter.',
      docsUrl: 'https://github.com/cuongpt083/nanobot/blob/main/docs/providers.md',
      recommendedModels: [],
    };

  const handleProviderFieldChange = (field: keyof ProviderItemConfig, value: any) => {
    const updated = {
      ...providers,
      [selectedProviderKey]: {
        ...currentProviderConfig,
        providerType: currentProviderType,
        [field]: value,
      },
    };
    onUpdateConfig({ providers: updated });
  };

  const handleAddProviderFromTemplate = () => {
    const templateMeta = PROVIDER_TEMPLATES[selectedTemplateKey];
    if (!templateMeta) return;

    // Create unique key for this provider
    let newKey = selectedTemplateKey;
    let counter = 1;
    while (providers[newKey]) {
      counter++;
      newKey = `${selectedTemplateKey}_${counter}`;
    }

    const defaultAlias = counter === 1 ? templateMeta.name : `${templateMeta.name} #${counter}`;

    const newProviderConfig: ProviderItemConfig = {
      id: newKey,
      alias: defaultAlias,
      name: defaultAlias,
      providerType: selectedTemplateKey,
      apiKey: templateMeta.isLocal ? '' : `\${${selectedTemplateKey.toUpperCase()}_API_KEY}`,
      apiBase: templateMeta.defaultApiBase || '',
      defaultModel: templateMeta.recommendedModels[0] || '',
      modelList: [...templateMeta.recommendedModels],
      status: templateMeta.isLocal ? 'configured' : 'unconfigured',
    };

    const updated = {
      ...providers,
      [newKey]: newProviderConfig,
    };

    onUpdateConfig({ providers: updated });
    setSelectedProviderKey(newKey);
    setTestStatus({ loading: false });
  };

  const handleDeleteProvider = (keyToDelete: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const updated = { ...providers };
    delete updated[keyToDelete];
    onUpdateConfig({ providers: updated });

    const remainingKeys = Object.keys(updated);
    if (selectedProviderKey === keyToDelete) {
      setSelectedProviderKey(remainingKeys[0] || 'gemini');
    }
  };

  const handleTestConnection = async (providerKey: string) => {
    setTestStatus({ loading: true, providerKey });
    try {
      const payload = {
        apiKey: currentProviderConfig.apiKey,
        apiBase: currentProviderConfig.apiBase,
        proxy: currentProviderConfig.proxy,
        providerType: currentProviderType,
        alias: currentProviderConfig.alias || meta.name,
      };

      const res = await fetch(`/api/config/providers/${providerKey}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (res.ok && data.success) {
        setTestStatus({ loading: false, providerKey, result: data });

        const discoveredModels: string[] = Array.isArray(data.models) && data.models.length > 0
          ? data.models
          : (currentProviderConfig.modelList || []);

        const chosenDefaultModel = (currentProviderConfig.defaultModel && discoveredModels.includes(currentProviderConfig.defaultModel))
          ? currentProviderConfig.defaultModel
          : (data.defaultModel || discoveredModels[0] || '');

        const resolvedAlias = currentProviderConfig.alias?.trim() || `${meta.name} (${chosenDefaultModel})`;

        // Update provider with active status, alias, exact discovered models, and default model
        const updatedProviders = {
          ...providers,
          [providerKey]: {
            ...providers[providerKey],
            alias: resolvedAlias,
            name: resolvedAlias,
            providerType: currentProviderType,
            status: 'active' as const,
            modelList: discoveredModels,
            defaultModel: chosenDefaultModel,
            lastTested: Date.now(),
            testLatencyMs: data.latencyMs,
          },
        };
        onUpdateConfig({ providers: updatedProviders });
      } else {
        setTestStatus({
          loading: false,
          providerKey,
          error: data.error || data.message || 'Kiểm tra kết nối thất bại',
        });
      }
    } catch (err: any) {
      setTestStatus({
        loading: false,
        providerKey,
        error: err.message || 'Lỗi kết nối kiểm tra endpoint provider',
      });
    }
  };

  const toggleShowKey = (provKey: string) => {
    setShowKeyMap((prev) => ({ ...prev, [provKey]: !prev[provKey] }));
  };

  const discoveredModelList = (testStatus.result && testStatus.providerKey === selectedProviderKey && Array.isArray(testStatus.result.models) && testStatus.result.models.length > 0)
    ? testStatus.result.models
    : (Array.isArray(currentProviderConfig.modelList) && currentProviderConfig.modelList.length > 0
        ? currentProviderConfig.modelList
        : meta.recommendedModels);

  const isLiveScanned = Boolean(
    (testStatus.result && testStatus.providerKey === selectedProviderKey && testStatus.result.models && testStatus.result.models.length > 0) ||
    (currentProviderConfig.status === 'active' && currentProviderConfig.lastTested && currentProviderConfig.modelList && currentProviderConfig.modelList.length > 0)
  );

  return (
    <div className="flex h-full gap-6 text-zinc-300">
      {/* Left Column: Template Dropdown & Configured Providers by Alias */}
      <div className="w-80 flex-shrink-0 border-r border-zinc-800/80 pr-4 space-y-4 overflow-y-auto flex flex-col justify-between">
        <div className="space-y-3.5">
          {/* Section 1: Template Selection Dropdown */}
          <div className="p-3 rounded-xl bg-zinc-950/70 border border-zinc-800/90 space-y-2.5 shadow-xs">
            <label className="block text-[11px] font-bold text-zinc-300 uppercase tracking-wider flex items-center gap-1.5">
              <Plus className="w-3.5 h-3.5 text-amber-400" />
              <span>Chọn Template Provider</span>
            </label>
            <div className="flex items-center gap-2">
              <select
                value={selectedTemplateKey}
                onChange={(e) => setSelectedTemplateKey(e.target.value)}
                className="flex-1 bg-zinc-900 border border-zinc-700/80 rounded-lg px-2.5 py-1.5 text-xs text-zinc-100 font-medium focus:outline-none focus:border-amber-500 cursor-pointer"
              >
                {Object.entries(PROVIDER_TEMPLATES).map(([tKey, item]) => (
                  <option key={tKey} value={tKey}>
                    {item.name} {item.isLocal ? '(Local)' : ''}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={handleAddProviderFromTemplate}
                className="px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-bold transition-colors cursor-pointer shadow-xs whitespace-nowrap"
                title="Khởi tạo Provider mới từ template được chọn"
              >
                + Thêm
              </button>
            </div>
            <p className="text-[10px] text-zinc-500 leading-relaxed">
              Chọn template để cấu hình API Key, Endpoint và đặt tên Alias riêng biệt.
            </p>
          </div>

          {/* Section 2: List of Configured Providers by Alias */}
          <div className="space-y-1.5">
            <div className="px-1 py-1 text-[11px] font-bold text-zinc-400 uppercase tracking-wider flex items-center justify-between">
              <span>Providers đã khai báo ({providerKeys.length})</span>
            </div>

            {providerKeys.length === 0 ? (
              <div className="p-4 rounded-xl bg-zinc-950/40 border border-dashed border-zinc-800 text-center text-xs text-zinc-500 space-y-1.5">
                <Bot className="w-6 h-6 mx-auto text-zinc-600 opacity-60" />
                <p className="font-medium text-zinc-400">Chưa có Provider nào</p>
                <p className="text-[10px]">Chọn template ở trên và bấm <strong>+ Thêm</strong> để bắt đầu cấu hình.</p>
              </div>
            ) : (
              providerKeys.map((key) => {
                const provConfig = providers[key] || {};
                const isSelected = selectedProviderKey === key;
                const provType = provConfig.providerType || key;
                const template = PROVIDER_TEMPLATES[provType] || { name: provType };
                const displayAlias = provConfig.alias || provConfig.name || template.name;
                const modelCount = provConfig.modelList?.length || 0;
                const activeModel = provConfig.defaultModel || provConfig.modelList?.[0];

                return (
                  <div
                    key={key}
                    onClick={() => {
                      setSelectedProviderKey(key);
                      setTestStatus({ loading: false });
                    }}
                    className={`group w-full p-2.5 rounded-xl transition-all cursor-pointer border flex items-center justify-between relative ${
                      isSelected
                        ? 'bg-amber-500/10 border-amber-500/60 shadow-xs'
                        : 'bg-zinc-950/50 hover:bg-zinc-900/80 border-zinc-800/70 text-zinc-300'
                    }`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 pr-2">
                      <div
                        className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                          provConfig.status === 'active'
                            ? 'bg-emerald-400 shadow-xs shadow-emerald-400/50 ring-2 ring-emerald-500/20'
                            : provConfig.status === 'error'
                            ? 'bg-rose-500 ring-2 ring-rose-500/20'
                            : provConfig.apiKey || provConfig.apiBase
                            ? 'bg-sky-400'
                            : 'bg-zinc-600'
                        }`}
                        title={`Trạng thái: ${provConfig.status || 'Chưa kiểm tra'}`}
                      />
                      <div className="truncate">
                        {/* Display the user-defined ALIAS as the primary title */}
                        <div className="text-xs font-bold text-zinc-100 truncate flex items-center gap-1.5">
                          <span className="truncate">{displayAlias}</span>
                        </div>
                        <div className="text-[10px] text-zinc-400 truncate flex items-center gap-1.5 mt-0.5">
                          <span className="px-1.5 py-0.2 rounded bg-zinc-800/90 text-zinc-400 font-mono text-[9px]">
                            {template.name}
                          </span>
                          {activeModel && (
                            <span className="text-amber-400/90 truncate font-mono text-[10px]">
                              {activeModel}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1 flex-shrink-0">
                      {modelCount > 0 && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono">
                          {modelCount}m
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={(e) => handleDeleteProvider(key, e)}
                        className="opacity-0 group-hover:opacity-100 p-1 hover:text-rose-400 text-zinc-500 transition-opacity cursor-pointer"
                        title="Xóa Provider này"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Quick summary info */}
        <div className="p-3 rounded-xl bg-zinc-950/40 border border-zinc-800/60 text-[11px] text-zinc-500">
          <p className="flex items-center gap-1.5 text-zinc-400 font-semibold mb-1">
            <Tag className="w-3.5 h-3.5 text-amber-400" />
            <span>Quy ước Alias Provider:</span>
          </p>
          <p>
            Mỗi Provider có thể đặt tên Alias tùy biến để dễ phân biệt tài khoản làm việc, cá nhân hoặc server nội bộ.
          </p>
        </div>
      </div>

      {/* Right Column: Provider Configuration & Model Discovery Editor */}
      <div className="flex-1 overflow-y-auto pr-2 space-y-5">
        {/* Header card with Provider Info & Test Trigger */}
        <div className="p-4 rounded-xl bg-zinc-950/70 border border-zinc-800 flex items-center justify-between shadow-xs">
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-bold text-zinc-100">
                {currentProviderConfig.alias || meta.name}
              </h4>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-zinc-800 text-amber-300 border border-zinc-700">
                Template: {meta.name}
              </span>
              {meta.isLocal && (
                <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-emerald-950 border border-emerald-800 text-emerald-300">
                  LOCAL
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-400 mt-1">{meta.description}</p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => handleTestConnection(selectedProviderKey)}
              disabled={testStatus.loading}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-xs font-bold text-zinc-950 transition-colors shadow-xs cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${testStatus.loading ? 'animate-spin' : ''}`} />
              <span>{testStatus.loading ? 'Đang kiểm tra & quét models...' : 'Test Connection & Fetch Models'}</span>
            </button>
            <a
              href={meta.docsUrl}
              target="_blank"
              rel="noreferrer"
              className="p-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors border border-zinc-700"
              title="Mở tài liệu hướng dẫn cấu hình"
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>

        {/* Test Result Alert Banner */}
        {testStatus.result && testStatus.providerKey === selectedProviderKey && (
          <div className="p-3.5 rounded-xl bg-emerald-950/40 border border-emerald-800/80 text-emerald-300 text-xs flex items-center justify-between shadow-xs">
            <div className="flex items-center gap-2.5">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
              <div>
                <div className="font-semibold text-emerald-200">{testStatus.result.message}</div>
                <div className="text-[11px] text-emerald-400/80 mt-0.5">
                  Đã tự động nạp danh sách {testStatus.result.modelsFound || testStatus.result.models?.length || 0} models vào cấu hình.
                </div>
              </div>
            </div>
            <span className="font-mono text-[11px] bg-emerald-900/60 border border-emerald-700/60 px-2.5 py-1 rounded text-emerald-200">
              {testStatus.result.latencyMs}ms latency
            </span>
          </div>
        )}

        {testStatus.error && testStatus.providerKey === selectedProviderKey && (
          <div className="p-3.5 rounded-xl bg-rose-950/40 border border-rose-800/80 text-rose-300 text-xs flex items-center gap-2.5 shadow-xs">
            <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <div>
              <div className="font-semibold text-rose-200">Không thể kết nối đến Provider</div>
              <div className="text-[11px] text-rose-400/80 mt-0.5">{testStatus.error}</div>
            </div>
          </div>
        )}

        {/* Form Controls */}
        <div className="space-y-4">
          {/* Field 1: Alias for Provider */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                <Tag className="w-3.5 h-3.5 text-amber-400" />
                <span>Tên Alias cho Provider (Gợi nhớ dễ nhận biết)</span>
              </label>
              <span className="text-[10px] text-zinc-500">Hiển thị trong Preset & Agent Chat</span>
            </div>
            <input
              type="text"
              value={currentProviderConfig.alias || ''}
              onChange={(e) => handleProviderFieldChange('alias', e.target.value)}
              placeholder={`VD: ${meta.name} Công Việc, OpenRouter Trả Phí, Local Server`}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-100 font-medium focus:outline-none focus:border-amber-500"
            />
          </div>

          {/* Field 2: Default Model for this Provider */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                <Cpu className="w-3.5 h-3.5 text-indigo-400" />
                <span>Model mặc định cho Provider này (Default Model)</span>
              </label>
              <span className="text-[10px] text-zinc-500">Chọn từ danh sách đã quét</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <select
                value={currentProviderConfig.defaultModel || (discoveredModelList[0] || '')}
                onChange={(e) => handleProviderFieldChange('defaultModel', e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-amber-300 font-semibold focus:outline-none focus:border-amber-500 cursor-pointer"
              >
                {discoveredModelList.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>

              <input
                type="text"
                value={currentProviderConfig.defaultModel || ''}
                onChange={(e) => handleProviderFieldChange('defaultModel', e.target.value)}
                placeholder="Hoặc nhập chính xác mã Model ID..."
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
              />
            </div>
            <p className="text-[10px] text-zinc-500">
              Model mặc định sẽ được ưu tiên khởi tạo khi tạo mới session trò chuyện hoặc Model Preset cho Provider này.
            </p>
          </div>

          {/* Field 3: API Key */}
          {!meta.isLocal && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                  <Key className="w-3.5 h-3.5 text-amber-400" />
                  <span>API Key / Secret Token</span>
                </label>
                <span className="text-[10px] text-zinc-500 font-mono">
                  Hỗ trợ định dạng ${'{ENV_VAR}'}
                </span>
              </div>

              <div className="relative">
                <input
                  type={showKeyMap[selectedProviderKey] ? 'text' : 'password'}
                  value={currentProviderConfig.apiKey || ''}
                  onChange={(e) => handleProviderFieldChange('apiKey', e.target.value)}
                  placeholder={`VD: sk-ant-..., sk-..., hoặc \${${currentProviderType.toUpperCase()}_API_KEY}`}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 pr-10 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey(selectedProviderKey)}
                  className="absolute right-2.5 top-2.5 text-zinc-500 hover:text-zinc-300 cursor-pointer"
                >
                  {showKeyMap[selectedProviderKey] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <p className="text-[10px] text-zinc-500">
                Khóa với định dạng <code className="text-amber-400/90">${'{VAR_NAME}'}</code> sẽ tự động đọc từ biến môi trường hệ thống của máy chủ.
              </p>
            </div>
          )}

          {/* Field 4: API Base URL */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                <Globe className="w-3.5 h-3.5 text-sky-400" />
                <span>API Base URL (Endpoint Máy Chủ)</span>
              </label>
              <span className="text-[10px] text-zinc-500">Để trống để dùng máy chủ mặc định</span>
            </div>
            <input
              type="text"
              value={currentProviderConfig.apiBase || ''}
              onChange={(e) => handleProviderFieldChange('apiBase', e.target.value)}
              placeholder={meta.defaultApiBase || 'Để trống cho endpoint chính thức của nhà cung cấp'}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
            />
          </div>

          {/* Field 5: Proxy URL */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-emerald-400" />
                <span>HTTP / SOCKS5 Proxy</span>
              </label>
              <span className="text-[10px] text-zinc-500">Tùy chọn (Optional)</span>
            </div>
            <input
              type="text"
              value={currentProviderConfig.proxy || ''}
              onChange={(e) => handleProviderFieldChange('proxy', e.target.value)}
              placeholder="VD: http://127.0.0.1:7890 hoặc socks5://127.0.0.1:1080"
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
            />
          </div>

          {/* Field 6: Discovered Models List Catalog */}
          <div className="pt-3 border-t border-zinc-800/80 space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                <span>
                  {isLiveScanned
                    ? `Danh sách Models từ Server (${discoveredModelList.length} models)`
                    : `Gợi ý Models (${discoveredModelList.length} models - Bấm 'Test Connection' để quét từ Endpoint)`}
                </span>
                {isLiveScanned && (
                  <span className="px-1.5 py-0.2 rounded bg-emerald-950/80 border border-emerald-800 text-emerald-300 font-mono text-[9px]">
                    LIVE SYNCED
                  </span>
                )}
              </div>
              <span className="text-[10px] text-zinc-500">Bấm vào model để đặt làm mặc định</span>
            </div>

            <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto p-2 rounded-lg bg-zinc-950 border border-zinc-800/80">
              {discoveredModelList.map((m) => {
                const isDefault = currentProviderConfig.defaultModel === m;
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => handleProviderFieldChange('defaultModel', m)}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-mono flex items-center gap-1 transition-colors cursor-pointer border ${
                      isDefault
                        ? 'bg-amber-500/20 border-amber-500/60 text-amber-300 font-semibold shadow-xs'
                        : 'bg-zinc-900 hover:bg-zinc-800 border-zinc-700/60 text-zinc-300'
                    }`}
                  >
                    {isDefault && <Check className="w-3 h-3 text-amber-400 stroke-[3]" />}
                    <span>{m}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
