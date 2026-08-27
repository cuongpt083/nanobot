import React, { useState } from 'react';
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
  Sparkles
} from 'lucide-react';
import { NanobotFullConfig, ProviderItemConfig } from '../../../types';

interface ProvidersTabProps {
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => void;
}

const PROVIDER_METADATA: Record<
  string,
  {
    name: string;
    description: string;
    defaultApiBase?: string;
    supportsProxy?: boolean;
    docsUrl: string;
    recommendedModels: string[];
    isLocal?: boolean;
  }
> = {
  gemini: {
    name: 'Google Gemini',
    description: 'Ultra-fast multimodal reasoning with massive context windows (up to 2M tokens).',
    docsUrl: 'https://ai.google.dev/',
    recommendedModels: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash'],
  },
  openrouter: {
    name: 'OpenRouter Gateway',
    description: 'Unified gateway providing access to Claude 3.7, GPT-4o, DeepSeek R1, Llama 3.3, and server tools.',
    docsUrl: 'https://openrouter.ai/docs',
    recommendedModels: [
      'anthropic/claude-3.7-sonnet',
      'anthropic/claude-3.5-sonnet',
      'openai/gpt-4o',
      'deepseek/deepseek-r1',
      'meta-llama/llama-3.3-70b-instruct',
    ],
  },
  anthropic: {
    name: 'Anthropic Direct',
    description: 'Direct API access for Claude 3.7 Sonnet (hybrid reasoning), Claude 3.5 Sonnet, and Claude 3.5 Haiku.',
    docsUrl: 'https://docs.anthropic.com/',
    recommendedModels: [
      'claude-3-7-sonnet-20250219',
      'claude-3-5-sonnet-20241022',
      'claude-3-5-haiku-20241022',
    ],
  },
  openai: {
    name: 'OpenAI Direct',
    description: 'GPT-4o, GPT-4o-mini, o1 reasoning models, and standard OpenAI chat completions.',
    docsUrl: 'https://platform.openai.com/docs',
    recommendedModels: ['gpt-4o', 'gpt-4o-mini', 'o1', 'o3-mini'],
  },
  deepseek: {
    name: 'DeepSeek Direct',
    description: 'DeepSeek V3 chat and DeepSeek R1 chain-of-thought reasoning models.',
    defaultApiBase: 'https://api.deepseek.com',
    docsUrl: 'https://platform.deepseek.com/',
    recommendedModels: ['deepseek-chat', 'deepseek-reasoner'],
  },
  groq: {
    name: 'Groq Cloud',
    description: 'Sub-second LPU inference for Llama 3.3 70B, DeepSeek R1 Distill, and Mixtral.',
    docsUrl: 'https://console.groq.com/',
    recommendedModels: ['llama-3.3-70b-versatile', 'deepseek-r1-distill-llama-70b'],
  },
  mistral: {
    name: 'Mistral AI',
    description: 'Mistral Large, Codestral for coding agent workflows, and Pixtral vision models.',
    docsUrl: 'https://docs.mistral.ai/',
    recommendedModels: ['mistral-large-latest', 'codestral-latest'],
  },
  ollama: {
    name: 'Ollama (Local / Air-Gapped)',
    description: 'Zero cloud latency, offline privacy on host hardware (Llama 3.2, DeepSeek R1, Qwen).',
    defaultApiBase: 'http://localhost:11434/v1',
    docsUrl: 'https://ollama.com/',
    recommendedModels: ['llama3.2:latest', 'deepseek-r1:8b', 'qwen2.5-coder:7b'],
    isLocal: true,
  },
  custom: {
    name: 'Custom OpenAI-Compatible Endpoint',
    description: 'Connect any proxy, vLLM, LMStudio, TGI, or internal corporate LLM gateway.',
    defaultApiBase: 'http://127.0.0.1:8000/v1',
    docsUrl: 'https://github.com/cuongpt083/nanobot/blob/main/docs/providers.md',
    recommendedModels: ['custom-model'],
  },
};

export const ProvidersTab: React.FC<ProvidersTabProps> = ({ config, onUpdateConfig }) => {
  const [selectedProviderKey, setSelectedProviderKey] = useState<string>('gemini');
  const [showKeyMap, setShowKeyMap] = useState<Record<string, boolean>>({});
  const [testStatus, setTestStatus] = useState<{
    loading: boolean;
    providerKey?: string;
    result?: { status: string; latencyMs: number; message: string; modelsFound: number };
    error?: string;
  }>({ loading: false });

  const providers = config.providers || {};
  const currentProviderConfig = providers[selectedProviderKey] || {};
  const meta = PROVIDER_METADATA[selectedProviderKey] || {
    name: selectedProviderKey,
    description: 'Configured LLM Provider adapter.',
    docsUrl: 'https://github.com/cuongpt083/nanobot/blob/main/docs/providers.md',
    recommendedModels: [],
  };

  const handleProviderFieldChange = (key: string, value: any) => {
    const updatedProviders = {
      ...providers,
      [selectedProviderKey]: {
        ...currentProviderConfig,
        [key]: value,
      },
    };
    onUpdateConfig({ providers: updatedProviders });
  };

  const handleTestConnection = async (providerKey: string) => {
    setTestStatus({ loading: true, providerKey });
    try {
      const res = await fetch(`/api/config/providers/${providerKey}/test`, {
        method: 'POST',
      });
      const data = await res.json();
      if (res.ok) {
        setTestStatus({ loading: false, providerKey, result: data });
        // Update provider status in local config
        const updatedProviders = {
          ...providers,
          [providerKey]: {
            ...providers[providerKey],
            status: 'active' as const,
            lastTested: Date.now(),
            testLatencyMs: data.latencyMs,
          },
        };
        onUpdateConfig({ providers: updatedProviders });
      } else {
        setTestStatus({ loading: false, providerKey, error: data.error || 'Connection failed' });
      }
    } catch (err: any) {
      setTestStatus({ loading: false, providerKey, error: err.message || 'Network error testing provider' });
    }
  };

  const toggleShowKey = (provKey: string) => {
    setShowKeyMap((prev) => ({ ...prev, [provKey]: !prev[provKey] }));
  };

  return (
    <div className="flex h-full gap-6 text-zinc-300">
      {/* Left Provider List */}
      <div className="w-72 flex-shrink-0 border-r border-zinc-800/80 pr-4 space-y-1.5 overflow-y-auto">
        <div className="px-2 py-1 text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
          Configured Providers
        </div>

        {Object.entries(PROVIDER_METADATA).map(([key, item]) => {
          const provConfig = providers[key] || {};
          const isConfigured = Boolean(provConfig.apiKey || provConfig.apiBase);
          const isSelected = selectedProviderKey === key;

          return (
            <button
              key={key}
              onClick={() => {
                setSelectedProviderKey(key);
                setTestStatus({ loading: false });
              }}
              className={`w-full text-left p-2.5 rounded-xl transition-all cursor-pointer flex items-center justify-between border ${
                isSelected
                  ? 'bg-amber-500/10 border-amber-500/50 text-amber-300 font-medium'
                  : 'bg-zinc-950/40 hover:bg-zinc-900 border-zinc-800/60 text-zinc-300'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div
                  className={`w-2 h-2 rounded-full ${
                    provConfig.status === 'active' || (key === 'gemini' && isConfigured)
                      ? 'bg-emerald-400 shadow-xs shadow-emerald-400/50'
                      : isConfigured
                      ? 'bg-sky-400'
                      : 'bg-zinc-600'
                  }`}
                />
                <div className="truncate">
                  <div className="text-xs font-semibold text-zinc-200 truncate">{item.name}</div>
                  <div className="text-[10px] text-zinc-500 truncate font-mono">
                    {key === 'ollama' ? 'Local Daemon' : key}
                  </div>
                </div>
              </div>

              {item.isLocal && (
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono">
                  LOCAL
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Right Provider Editor Panel */}
      <div className="flex-1 overflow-y-auto pr-2 space-y-5">
        {/* Header card */}
        <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800/80 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-bold text-zinc-100">{meta.name}</h4>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">
                providers.{selectedProviderKey}
              </span>
            </div>
            <p className="text-xs text-zinc-400 mt-1">{meta.description}</p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => handleTestConnection(selectedProviderKey)}
              disabled={testStatus.loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs font-medium text-zinc-200 transition-colors border border-zinc-700 cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${testStatus.loading ? 'animate-spin text-amber-400' : ''}`} />
              <span>{testStatus.loading ? 'Testing...' : 'Test Connection'}</span>
            </button>
            <a
              href={meta.docsUrl}
              target="_blank"
              rel="noreferrer"
              className="p-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors border border-zinc-700"
              title="Open Provider Documentation"
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>

        {/* Test Result Alert */}
        {testStatus.result && testStatus.providerKey === selectedProviderKey && (
          <div className="p-3 rounded-lg bg-emerald-950/40 border border-emerald-800/60 text-emerald-300 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>{testStatus.result.message}</span>
            </div>
            <span className="font-mono text-[11px] bg-emerald-900/60 px-2 py-0.5 rounded text-emerald-200">
              {testStatus.result.latencyMs}ms latency
            </span>
          </div>
        )}

        {testStatus.error && testStatus.providerKey === selectedProviderKey && (
          <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-rose-300 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400" />
            <span>{testStatus.error}</span>
          </div>
        )}

        {/* Form Inputs */}
        <div className="space-y-4">
          {/* API Key */}
          {!meta.isLocal && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-zinc-200 flex items-center gap-1.5">
                  <Key className="w-3.5 h-3.5 text-amber-400" />
                  <span>API Key / Secret Token</span>
                </label>
                <span className="text-[11px] text-zinc-500 font-mono">
                  Supports ${'{ENV_VAR}'} format
                </span>
              </div>

              <div className="relative">
                <input
                  type={showKeyMap[selectedProviderKey] ? 'text' : 'password'}
                  value={currentProviderConfig.apiKey || ''}
                  onChange={(e) => handleProviderFieldChange('apiKey', e.target.value)}
                  placeholder={`e.g. sk-ant-..., sk-..., or \${${selectedProviderKey.toUpperCase()}_API_KEY}`}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 pr-10 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey(selectedProviderKey)}
                  className="absolute right-2.5 top-2.5 text-zinc-500 hover:text-zinc-300"
                >
                  {showKeyMap[selectedProviderKey] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <p className="text-[11px] text-zinc-500">
                Secrets with <code className="text-amber-400/90">${'{VAR_NAME}'}</code> are dynamically resolved at runtime from the system environment and never written unencrypted to disk.
              </p>
            </div>
          )}

          {/* API Base URL */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-zinc-200 flex items-center gap-1.5">
                <Globe className="w-3.5 h-3.5 text-sky-400" />
                <span>API Base URL (Endpoint)</span>
              </label>
              <span className="text-[10px] text-zinc-500">Optional for cloud defaults</span>
            </div>
            <input
              type="text"
              value={currentProviderConfig.apiBase || ''}
              onChange={(e) => handleProviderFieldChange('apiBase', e.target.value)}
              placeholder={meta.defaultApiBase || 'Leave empty for official default endpoint'}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
            />
          </div>

          {/* Proxy URL (optional) */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-zinc-200 flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-emerald-400" />
                <span>Provider HTTP/SOCKS5 Proxy</span>
              </label>
              <span className="text-[10px] text-zinc-500">Optional</span>
            </div>
            <input
              type="text"
              value={currentProviderConfig.proxy || ''}
              onChange={(e) => handleProviderFieldChange('proxy', e.target.value)}
              placeholder="e.g. http://127.0.0.1:7890 or socks5://127.0.0.1:1080"
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
            />
          </div>

          {/* Recommended Models Catalog */}
          <div className="pt-2 border-t border-zinc-800/80">
            <div className="text-xs font-semibold text-zinc-300 mb-2 flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-indigo-400" />
              <span>Recommended Models for this Provider:</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {meta.recommendedModels.map((m) => (
                <span
                  key={m}
                  className="px-2.5 py-1 rounded-lg bg-zinc-950 border border-zinc-800 text-[11px] font-mono text-zinc-300 flex items-center gap-1"
                >
                  <Sparkles className="w-3 h-3 text-amber-400/80" />
                  <span>{m}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
