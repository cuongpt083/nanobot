import React, { useState, useEffect, useRef } from 'react';
import {
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Terminal,
  FolderTree,
  FileCode,
  Layers,
  Cpu,
  RefreshCw,
  X,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  PlayCircle,
  Bot,
  Key,
  Globe,
  Shield,
  MessageSquare,
  Search,
  Mic,
  ArrowRight,
  ArrowLeft,
  Tag,
  Eye,
  EyeOff,
  Send
} from 'lucide-react';
import { SetupStepItem, SetupStatusResponse, ProviderItemConfig } from '../types';

interface InitialSetupWizardModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSetupCompleted?: () => void;
}

interface ProviderTemplateMeta {
  key: string;
  name: string;
  defaultApiBase?: string;
  recommendedModels: string[];
  isLocal?: boolean;
}

const PROVIDER_TEMPLATES: Record<string, ProviderTemplateMeta> = {
  gemini: {
    key: 'gemini',
    name: 'Google Gemini',
    defaultApiBase: 'https://generativelanguage.googleapis.com/v1beta/openai',
    recommendedModels: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash'],
  },
  openrouter: {
    key: 'openrouter',
    name: 'OpenRouter Gateway',
    defaultApiBase: 'https://openrouter.ai/api/v1',
    recommendedModels: [
      'anthropic/claude-3.7-sonnet',
      'openai/gpt-4o',
      'deepseek/deepseek-r1',
      'google/gemini-2.0-flash-001',
      'meta-llama/llama-3.3-70b-instruct',
    ],
  },
  anthropic: {
    key: 'anthropic',
    name: 'Anthropic Claude',
    defaultApiBase: 'https://api.anthropic.com/v1',
    recommendedModels: ['claude-3-7-sonnet-20250219', 'claude-3-5-haiku-20241022', 'claude-3-5-sonnet-20241022'],
  },
  openai: {
    key: 'openai',
    name: 'OpenAI Direct',
    defaultApiBase: 'https://api.openai.com/v1',
    recommendedModels: ['gpt-4o', 'gpt-4o-mini', 'o3-mini', 'o1'],
  },
  deepseek: {
    key: 'deepseek',
    name: 'DeepSeek API',
    defaultApiBase: 'https://api.deepseek.com',
    recommendedModels: ['deepseek-chat', 'deepseek-reasoner'],
  },
  groq: {
    key: 'groq',
    name: 'Groq Cloud LPU',
    defaultApiBase: 'https://api.groq.com/openai/v1',
    recommendedModels: ['llama-3.3-70b-versatile', 'deepseek-r1-distill-llama-70b', 'mixtral-8x7b-32768'],
  },
  mistral: {
    key: 'mistral',
    name: 'Mistral AI',
    defaultApiBase: 'https://api.mistral.ai/v1',
    recommendedModels: ['mistral-large-latest', 'codestral-latest', 'pixtral-large-latest'],
  },
  ollama: {
    key: 'ollama',
    name: 'Ollama (Local Daemon)',
    defaultApiBase: 'http://localhost:11434/v1',
    recommendedModels: ['llama3.2:latest', 'deepseek-r1:8b', 'qwen2.5-coder:7b', 'mistral:latest'],
    isLocal: true,
  },
  custom: {
    key: 'custom',
    name: 'Custom OpenAI-Compatible',
    defaultApiBase: 'http://192.168.100.17:8787/v1',
    recommendedModels: ['gemini-3.7-flash-medium', 'custom-model-v1', 'default-model'],
  },
};

export const InitialSetupWizardModal: React.FC<InitialSetupWizardModalProps> = ({
  isOpen,
  onClose,
  onSetupCompleted,
}) => {
  // Navigation Tabs: 'environment' (Phase 1) | 'onboarding' (Phase 2)
  const [activePhase, setActivePhase] = useState<'environment' | 'onboarding'>('environment');
  const [onboardingSubTab, setOnboardingSubTab] = useState<'llm' | 'channels' | 'tools'>('llm');

  // Phase 1: Environment Provisioning State
  const [loadingStatus, setLoadingStatus] = useState<boolean>(true);
  const [isRunningEnvSetup, setIsRunningEnvSetup] = useState<boolean>(false);
  const [statusData, setStatusData] = useState<SetupStatusResponse | null>(null);
  const [steps, setSteps] = useState<SetupStepItem[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [isLogExpanded, setIsLogExpanded] = useState<boolean>(false);
  const [copiedLog, setCopiedLog] = useState<boolean>(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Phase 2: Onboarding Form State (Required LLM Model + Optional Channels & Tools)
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string>('gemini');
  const [alias, setAlias] = useState<string>('Google Gemini Primary');
  const [apiKey, setApiKey] = useState<string>('${GEMINI_API_KEY}');
  const [apiBase, setApiBase] = useState<string>('');
  const [showKey, setShowKey] = useState<boolean>(false);
  const [defaultModel, setDefaultModel] = useState<string>('gemini-2.5-flash');
  const [scannedModels, setScannedModels] = useState<string[]>(PROVIDER_TEMPLATES.gemini.recommendedModels);

  // Testing status
  const [testing, setTesting] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<{
    success?: boolean;
    latencyMs?: number;
    message?: string;
    modelsFound?: number;
    error?: string;
  } | null>(null);

  // Optional Channels
  const [telegramToken, setTelegramToken] = useState<string>('');
  const [discordToken, setDiscordToken] = useState<string>('');
  const [slackToken, setSlackToken] = useState<string>('');

  // Optional Tools
  const [webSearchProvider, setWebSearchProvider] = useState<'duckduckgo' | 'brave' | 'tavily'>('duckduckgo');
  const [sandboxMode, setSandboxMode] = useState<'permissive' | 'strict'>('permissive');

  // Fetch initial setup status
  const fetchStatus = async () => {
    setLoadingStatus(true);
    try {
      if (window.nanobotDesktop?.setup?.getStatus) {
        const data = await window.nanobotDesktop.setup.getStatus();
        setStatusData(data);
        setSteps(data.steps || []);
        if (data.isInstalled && !data.needsSetup) {
          setActivePhase('onboarding');
        }
      } else {
        const res = await fetch('/api/setup/status');
        if (res.ok) {
          const data = await res.json();
          setStatusData(data);
          setSteps(data.steps || []);
          if (data.isInstalled && !data.needsSetup) {
            setActivePhase('onboarding');
          }
        }
      }
    } catch (err: any) {
      console.warn('[SetupWizard] Could not fetch setup status:', err.message);
    } finally {
      setLoadingStatus(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchStatus();
    }
  }, [isOpen]);

  // Handle template selection change in Onboarding
  const handleTemplateChange = (templateKey: string) => {
    setSelectedTemplateKey(templateKey);
    const tmpl = PROVIDER_TEMPLATES[templateKey];
    if (tmpl) {
      setAlias(`${tmpl.name} Primary`);
      setApiKey(tmpl.isLocal ? '' : `\${${templateKey.toUpperCase()}_API_KEY}`);
      setApiBase(tmpl.defaultApiBase || '');
      setScannedModels(tmpl.recommendedModels);
      setDefaultModel(tmpl.recommendedModels[0] || '');
      setTestResult(null);
    }
  };

  // Test provider connection & fetch models live
  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);

    const providerKey = selectedTemplateKey;
    const payload = {
      apiKey,
      apiBase,
      providerType: selectedTemplateKey,
      alias,
      defaultModel,
    };

    try {
      const res = await fetch(`/api/config/providers/${providerKey}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (res.ok && data.success) {
        setTestResult({
          success: true,
          latencyMs: data.latencyMs,
          message: data.message || `Kết nối thành công! Tìm thấy ${data.modelsFound || data.models?.length || 0} models.`,
          modelsFound: data.modelsFound || data.models?.length || 0,
        });

        if (Array.isArray(data.models) && data.models.length > 0) {
          setScannedModels(data.models);
          if (!data.models.includes(defaultModel)) {
            setDefaultModel(data.defaultModel || data.models[0] || '');
          }
        }
      } else {
        setTestResult({
          success: false,
          error: data.error || data.message || 'Không thể kết nối đến endpoint.',
        });
      }
    } catch (err: any) {
      setTestResult({
        success: false,
        error: err.message || 'Lỗi mạng khi kiểm tra kết nối endpoint.',
      });
    } finally {
      setTesting(false);
    }
  };

  // Run Phase 1 setup
  const handleStartEnvSetup = async (forceReinstall = false) => {
    setIsRunningEnvSetup(true);
    setIsLogExpanded(true);
    setLogs([`[${new Date().toLocaleTimeString()}] Bắt đầu tiến trình thiết lập môi trường Nanobot...`]);

    try {
      let resultData: any = null;
      if (window.nanobotDesktop?.setup?.runSetup) {
        resultData = await window.nanobotDesktop.setup.runSetup({ forceReinstall });
      } else {
        const res = await fetch('/api/setup/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ forceReinstall }),
        });
        resultData = await res.json();
      }

      if (resultData) {
        if (Array.isArray(resultData.steps)) {
          setSteps(resultData.steps);
        }
        if (Array.isArray(resultData.logs)) {
          setLogs((prev) => [...prev, ...resultData.logs]);
        }
      }

      await fetchStatus();
    } catch (err: any) {
      setLogs((prev) => [...prev, `[LỖI] Quá trình thiết lập gặp sự cố: ${err.message}`]);
    } finally {
      setIsRunningEnvSetup(false);
    }
  };

  // Complete Onboarding & Save Configuration
  const handleFinishOnboarding = async () => {
    const providerKey = selectedTemplateKey;
    const modelToUse = defaultModel || scannedModels[0] || 'default-model';
    const aliasToUse = alias.trim() || `${PROVIDER_TEMPLATES[selectedTemplateKey]?.name || providerKey} Primary`;

    // 1. Save Provider
    const providerPayload: Partial<ProviderItemConfig> = {
      id: providerKey,
      name: aliasToUse,
      alias: aliasToUse,
      providerType: selectedTemplateKey,
      apiKey,
      apiBase,
      defaultModel: modelToUse,
      modelList: scannedModels,
      status: testResult?.success ? 'active' : 'configured',
      lastTested: Date.now(),
      testLatencyMs: testResult?.latencyMs || 25,
    };

    try {
      await fetch(`/api/config/providers/${providerKey}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(providerPayload),
      });

      // 2. Create/Update Model Preset
      const presetId = 'primary';
      await fetch('/api/config/model-presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: presetId,
          name: `${aliasToUse} (${modelToUse})`,
          provider: providerKey,
          model: modelToUse,
          isDefault: true,
          maxTokens: 8192,
          contextWindowTokens: 128000,
          temperature: 0.7,
        }),
      });

      // 3. Save Optional channels & tools if entered
      const channelsUpdate: Record<string, any> = {};
      if (telegramToken.trim()) {
        channelsUpdate.telegram = { enabled: true, botToken: telegramToken.trim() };
      }
      if (discordToken.trim()) {
        channelsUpdate.discord = { enabled: true, botToken: discordToken.trim() };
      }
      if (slackToken.trim()) {
        channelsUpdate.slack = { enabled: true, botToken: slackToken.trim() };
      }

      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          providers: { [providerKey]: providerPayload },
          modelPresets: {
            [presetId]: {
              id: presetId,
              name: `${aliasToUse} (${modelToUse})`,
              provider: providerKey,
              model: modelToUse,
              isDefault: true,
              maxTokens: 8192,
              contextWindowTokens: 128000,
              temperature: 0.7,
            },
          },
          agents: {
            defaults: {
              modelPreset: presetId,
            },
          },
          tools: {
            exec: { sandbox: sandboxMode },
            web: { search: { provider: webSearchProvider } },
          },
          channels: channelsUpdate,
        }),
      });

      if (onSetupCompleted) {
        onSetupCompleted();
      }
      onClose();
    } catch (err: any) {
      console.error('[Onboarding] Error saving configuration:', err);
      onClose();
    }
  };

  const handleCopyLogs = () => {
    navigator.clipboard.writeText(logs.join('\n'));
    setCopiedLog(true);
    setTimeout(() => setCopiedLog(false), 2000);
  };

  if (!isOpen) return null;

  const completedCount = steps.filter((s) => s.status === 'completed').length;
  const totalCount = steps.length || 6;
  const isEnvDone = completedCount === totalCount && totalCount > 0;
  const isLlmConfigured = Boolean(
    (testResult?.success || apiKey || apiBase) && defaultModel
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="bg-zinc-900 border border-zinc-700/80 rounded-2xl w-full max-w-4xl shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        {/* Modal Top Header */}
        <div className="px-6 py-3.5 border-b border-zinc-800 flex items-center justify-between bg-zinc-950/90">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-400 shadow-sm">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-zinc-100">
                  Khởi tạo & Cấu hình Nanobot Desktop
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-zinc-800 text-zinc-300 border border-zinc-700">
                  v0.3.0
                </span>
              </div>
              <p className="text-xs text-zinc-400 mt-0.5">
                Thiết lập tự động môi trường `HOME/.nanobot` và Onboarding kết nối AI Model.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Phase Navigation Tabs */}
            <div className="flex items-center bg-zinc-950 p-1 rounded-xl border border-zinc-800">
              <button
                onClick={() => setActivePhase('environment')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors cursor-pointer ${
                  activePhase === 'environment'
                    ? 'bg-amber-500 text-zinc-950 shadow-sm'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <FolderTree className="w-3.5 h-3.5" />
                <span>1. Cài đặt Môi trường</span>
                {isEnvDone && <Check className="w-3.5 h-3.5 stroke-[3]" />}
              </button>

              <button
                onClick={() => setActivePhase('onboarding')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors cursor-pointer ${
                  activePhase === 'onboarding'
                    ? 'bg-amber-500 text-zinc-950 shadow-sm'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Bot className="w-3.5 h-3.5" />
                <span>2. Cấu hình Onboarding</span>
                <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber-950/80 text-amber-300 border border-amber-800">
                  Bắt buộc
                </span>
              </button>
            </div>

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors cursor-pointer"
              title="Đóng cửa sổ"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-5 overflow-y-auto flex-1 text-xs">
          {/* ============================================================ */}
          {/* PHASE 1: ENVIRONMENT PROVISIONING                            */}
          {/* ============================================================ */}
          {activePhase === 'environment' && (
            <div className="space-y-4 animate-in fade-in duration-150">
              {/* Target Location Card */}
              <div className="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800/80 flex items-center justify-between">
                <div className="space-y-1">
                  <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
                    Thư mục cài đặt hệ thống (Home Directory):
                  </div>
                  <div className="font-mono text-zinc-200 text-xs flex items-center gap-2">
                    <span className="text-amber-400 font-semibold">{statusData?.nanobotDir || '~/.nanobot'}</span>
                    <span className="text-zinc-500">•</span>
                    <span className="text-zinc-400">Workspace: {statusData?.workspaceDir || '~/.nanobot/workspace'}</span>
                  </div>
                </div>

                {statusData?.detectedPython?.found && (
                  <span className="px-2.5 py-1 rounded-md bg-emerald-950/60 border border-emerald-800/80 text-emerald-300 font-mono text-[11px] flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Python {statusData.detectedPython.version}</span>
                  </span>
                )}
              </div>

              {/* Progress Bar */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-zinc-400 text-xs">
                  <span className="font-medium">Tiến độ thiết lập các thành phần hệ thống:</span>
                  <span className="font-mono text-amber-400 font-bold">
                    {completedCount} / {totalCount} bước hoàn tất
                  </span>
                </div>
                <div className="w-full bg-zinc-950 rounded-full h-2 overflow-hidden border border-zinc-800">
                  <div
                    className="h-full bg-gradient-to-r from-amber-500 to-emerald-400 transition-all duration-500 rounded-full"
                    style={{ width: `${(completedCount / totalCount) * 100}%` }}
                  />
                </div>
              </div>

              {/* Steps List */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                {steps.map((step, idx) => {
                  const isStepRunning = step.status === 'running';
                  const isStepDone = step.status === 'completed';
                  const isStepError = step.status === 'error';

                  return (
                    <div
                      key={step.id}
                      className={`p-3 rounded-xl border transition-all ${
                        isStepRunning
                          ? 'bg-amber-950/20 border-amber-500/60 shadow-xs'
                          : isStepDone
                          ? 'bg-zinc-950/70 border-zinc-800 hover:border-zinc-700'
                          : isStepError
                          ? 'bg-rose-950/20 border-rose-800/80'
                          : 'bg-zinc-950/40 border-zinc-800/60 opacity-80'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-0.5 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[10px] font-mono text-amber-400 font-bold">#{idx + 1}</span>
                            <span className="font-bold text-zinc-100">{step.title}</span>
                          </div>
                          <p className="text-[11px] text-zinc-400 leading-relaxed">
                            {step.description}
                          </p>
                          {step.details && (
                            <div className="text-[10px] text-emerald-400/90 font-mono mt-1 flex items-center gap-1">
                              <Check className="w-3 h-3 text-emerald-400" />
                              <span>{step.details}</span>
                            </div>
                          )}
                        </div>

                        {/* Step Status Badge */}
                        <div className="flex-shrink-0">
                          {isStepRunning && (
                            <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[10px] font-medium flex items-center gap-1 border border-amber-500/40 animate-pulse">
                              <Loader2 className="w-3 h-3 animate-spin" />
                              <span>Chạy...</span>
                            </span>
                          )}
                          {isStepDone && (
                            <span className="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 text-[10px] font-medium flex items-center gap-1 border border-emerald-800">
                              <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                              <span>Xong</span>
                            </span>
                          )}
                          {isStepError && (
                            <span className="px-2 py-0.5 rounded bg-rose-950/60 text-rose-300 text-[10px] font-medium flex items-center gap-1 border border-rose-800">
                              <AlertCircle className="w-3 h-3 text-rose-400" />
                              <span>Lỗi</span>
                            </span>
                          )}
                          {step.status === 'pending' && (
                            <span className="px-2 py-0.5 rounded bg-zinc-900 text-zinc-500 text-[10px] border border-zinc-800">
                              Chờ
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Collapsible Terminal Output Console */}
              <div className="border border-zinc-800 rounded-xl overflow-hidden bg-zinc-950">
                <button
                  type="button"
                  onClick={() => setIsLogExpanded(!isLogExpanded)}
                  className="w-full px-4 py-2 bg-zinc-900/90 hover:bg-zinc-900 border-b border-zinc-800 flex items-center justify-between text-xs font-semibold text-zinc-300 transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <Terminal className="w-3.5 h-3.5 text-amber-400" />
                    <span>Live Installation Terminal Logs</span>
                    <span className="text-[10px] text-zinc-500 font-mono">({logs.length} dòng)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCopyLogs();
                      }}
                      className="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
                      title="Sao chép nhật ký"
                    >
                      {copiedLog ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    </button>
                    {isLogExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                  </div>
                </button>

                {isLogExpanded && (
                  <div className="p-3 font-mono text-[11px] text-zinc-300 max-h-36 overflow-y-auto space-y-1 select-text bg-black/60">
                    {logs.length === 0 ? (
                      <div className="text-zinc-600 italic">Chưa có nhật ký nào được ghi lại.</div>
                    ) : (
                      logs.map((line, i) => (
                        <div
                          key={i}
                          className={`${
                            line.includes('LỖI') || line.includes('error')
                              ? 'text-rose-400'
                              : line.includes('✓') || line.includes('THÀNH CÔNG')
                              ? 'text-emerald-400 font-semibold'
                              : line.includes('!')
                              ? 'text-amber-400'
                              : 'text-zinc-300'
                          }`}
                        >
                          {line}
                        </div>
                      ))
                    )}
                    <div ref={logEndRef} />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ============================================================ */}
          {/* PHASE 2: ONBOARDING WIZARD                                   */}
          {/* ============================================================ */}
          {activePhase === 'onboarding' && (
            <div className="space-y-4 animate-in fade-in duration-150">
              {/* Onboarding Sub-Navigation */}
              <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setOnboardingSubTab('llm')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 cursor-pointer transition-colors ${
                      onboardingSubTab === 'llm'
                        ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <Bot className="w-3.5 h-3.5 text-amber-400" />
                    <span>1. AI Model & Provider</span>
                    <span className="px-1.5 py-0.2 rounded bg-amber-500/30 text-amber-300 text-[9px] font-mono">
                      Bắt buộc
                    </span>
                  </button>

                  <button
                    onClick={() => setOnboardingSubTab('channels')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${
                      onboardingSubTab === 'channels'
                        ? 'bg-zinc-800 text-zinc-100 border border-zinc-700'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <MessageSquare className="w-3.5 h-3.5 text-sky-400" />
                    <span>2. Kênh Chat (Channels)</span>
                    <span className="text-[9px] text-zinc-500 italic">Tùy chọn</span>
                  </button>

                  <button
                    onClick={() => setOnboardingSubTab('tools')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${
                      onboardingSubTab === 'tools'
                        ? 'bg-zinc-800 text-zinc-100 border border-zinc-700'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    <Search className="w-3.5 h-3.5 text-emerald-400" />
                    <span>3. Web Search & Sandbox</span>
                    <span className="text-[9px] text-zinc-500 italic">Tùy chọn</span>
                  </button>
                </div>

                <span className="text-[11px] text-zinc-500">
                  Có thể bấm <strong className="text-amber-400">Hoàn tất</strong> ngay sau khi chọn Model
                </span>
              </div>

              {/* Sub-tab 1: LLM Provider & Model (REQUIRED) */}
              {onboardingSubTab === 'llm' && (
                <div className="space-y-4">
                  {/* Provider Template Selector Dropdown */}
                  <div className="p-3.5 rounded-xl bg-zinc-950/70 border border-zinc-800 space-y-2">
                    <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                      <Cpu className="w-3.5 h-3.5 text-amber-400" />
                      <span>Chọn Nhà cung cấp AI (Provider Template)</span>
                    </label>
                    <select
                      value={selectedTemplateKey}
                      onChange={(e) => handleTemplateChange(e.target.value)}
                      className="w-full bg-zinc-900 border border-zinc-700 rounded-lg p-2.5 text-xs text-zinc-100 font-semibold focus:outline-none focus:border-amber-500 cursor-pointer"
                    >
                      {Object.values(PROVIDER_TEMPLATES).map((tmpl) => (
                        <option key={tmpl.key} value={tmpl.key}>
                          {tmpl.name} {tmpl.isLocal ? '(Local Offline)' : ''}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Provider Alias & Credentials */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {/* Alias */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                        <Tag className="w-3.5 h-3.5 text-amber-400" />
                        <span>Tên gợi nhớ (Alias)</span>
                      </label>
                      <input
                        type="text"
                        value={alias}
                        onChange={(e) => setAlias(e.target.value)}
                        placeholder="VD: Google Gemini Cá Nhân, Local Server"
                        className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-100 font-medium focus:outline-none focus:border-amber-500"
                      />
                    </div>

                    {/* API Key */}
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                          <Key className="w-3.5 h-3.5 text-amber-400" />
                          <span>API Key / Secret Token</span>
                        </label>
                        <span className="text-[10px] text-zinc-500 font-mono">Hỗ trợ ${'{ENV_VAR}'}</span>
                      </div>
                      <div className="relative">
                        <input
                          type={showKey ? 'text' : 'password'}
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          placeholder="Nhập API key hoặc để trống cho local server"
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 pr-9 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
                        />
                        <button
                          type="button"
                          onClick={() => setShowKey(!showKey)}
                          className="absolute right-2.5 top-2.5 text-zinc-500 hover:text-zinc-300 cursor-pointer"
                        >
                          {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* API Base URL */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                        <Globe className="w-3.5 h-3.5 text-sky-400" />
                        <span>API Base URL (Endpoint Server)</span>
                      </label>
                      <span className="text-[10px] text-zinc-500">Để trống để dùng endpoint cloud mặc định</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={apiBase}
                        onChange={(e) => setApiBase(e.target.value)}
                        placeholder="VD: http://192.168.100.17:8787/v1 hoặc để trống"
                        className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500 flex-1"
                      />
                      <button
                        type="button"
                        disabled={testing}
                        onClick={handleTestConnection}
                        className="px-4 py-2.5 bg-amber-500 hover:bg-amber-400 text-zinc-950 rounded-lg font-bold text-xs flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50 flex-shrink-0 shadow-sm"
                      >
                        {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                        <span>Kiểm tra & Quét Models</span>
                      </button>
                    </div>
                  </div>

                  {/* Test Result Alert Banner */}
                  {testResult?.success && (
                    <div className="p-3 rounded-xl bg-emerald-950/50 border border-emerald-800/80 text-emerald-300 text-xs flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                        <div>
                          <div className="font-semibold text-emerald-200">{testResult.message}</div>
                          <div className="text-[11px] text-emerald-400/80">
                            Đã nạp {testResult.modelsFound || scannedModels.length} models trực tiếp từ endpoint.
                          </div>
                        </div>
                      </div>
                      <span className="font-mono text-[11px] bg-emerald-900/60 border border-emerald-700/60 px-2 py-0.5 rounded text-emerald-200">
                        {testResult.latencyMs}ms
                      </span>
                    </div>
                  )}

                  {testResult?.error && (
                    <div className="p-3 rounded-xl bg-rose-950/50 border border-rose-800/80 text-rose-300 text-xs flex items-center gap-2">
                      <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
                      <div>
                        <div className="font-semibold text-rose-200">Không thể kết nối đến Endpoint</div>
                        <div className="text-[11px] text-rose-400/80 mt-0.5">{testResult.error}</div>
                      </div>
                    </div>
                  )}

                  {/* Model Selection Dropdown & Pills */}
                  <div className="space-y-2 pt-2 border-t border-zinc-800/80">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                        <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                        <span>Chọn Model mặc định (Default Model) ({scannedModels.length} models)</span>
                      </label>
                      <span className="text-[10px] text-zinc-500">Bấm vào model bên dưới để chọn nhanh</span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      <select
                        value={defaultModel}
                        onChange={(e) => setDefaultModel(e.target.value)}
                        className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-amber-300 font-semibold focus:outline-none focus:border-amber-500 cursor-pointer"
                      >
                        {scannedModels.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>

                      <input
                        type="text"
                        value={defaultModel}
                        onChange={(e) => setDefaultModel(e.target.value)}
                        placeholder="Hoặc nhập mã Model ID..."
                        className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
                      />
                    </div>

                    {/* Interactive Model Pills */}
                    <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto p-2 rounded-lg bg-zinc-950 border border-zinc-800/80">
                      {scannedModels.map((m) => {
                        const isDefault = defaultModel === m;
                        return (
                          <button
                            key={m}
                            type="button"
                            onClick={() => setDefaultModel(m)}
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
              )}

              {/* Sub-tab 2: Chat Channels (OPTIONAL) */}
              {onboardingSubTab === 'channels' && (
                <div className="space-y-4">
                  <div className="p-3 rounded-xl bg-zinc-950/60 border border-zinc-800 text-xs text-zinc-400 leading-relaxed">
                    Bạn có thể cấu hình kết nối bot để nhận và trả lời tin nhắn từ Telegram, Discord hoặc Slack. Mục này là <strong className="text-zinc-200">tùy chọn</strong> và có thể cấu hình lại sau trong mục <strong>Settings → Channels</strong>.
                  </div>

                  <div className="space-y-3">
                    {/* Telegram */}
                    <div className="p-3 rounded-xl bg-zinc-950 border border-zinc-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                          <Send className="w-3.5 h-3.5 text-sky-400" />
                          <span>Telegram Bot Token</span>
                        </label>
                        <span className="text-[10px] text-zinc-500">Từ @BotFather</span>
                      </div>
                      <input
                        type="password"
                        value={telegramToken}
                        onChange={(e) => setTelegramToken(e.target.value)}
                        placeholder="VD: 123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
                        className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
                      />
                    </div>

                    {/* Discord */}
                    <div className="p-3 rounded-xl bg-zinc-950 border border-zinc-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                          <MessageSquare className="w-3.5 h-3.5 text-indigo-400" />
                          <span>Discord Bot Token</span>
                        </label>
                        <span className="text-[10px] text-zinc-500">Từ Discord Developer Portal</span>
                      </div>
                      <input
                        type="password"
                        value={discordToken}
                        onChange={(e) => setDiscordToken(e.target.value)}
                        placeholder="VD: MTEzNDU2Nzg5MDEyMzQ1Njc4OQ..."
                        className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
                      />
                    </div>

                    {/* Slack */}
                    <div className="p-3 rounded-xl bg-zinc-950 border border-zinc-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                          <MessageSquare className="w-3.5 h-3.5 text-emerald-400" />
                          <span>Slack Bot Token (xoxb-...)</span>
                        </label>
                        <span className="text-[10px] text-zinc-500">Từ Slack API Apps</span>
                      </div>
                      <input
                        type="password"
                        value={slackToken}
                        onChange={(e) => setSlackToken(e.target.value)}
                        placeholder="VD: xoxb-1234567890-..."
                        className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Sub-tab 3: Tools & Search (OPTIONAL) */}
              {onboardingSubTab === 'tools' && (
                <div className="space-y-4">
                  <div className="p-3 rounded-xl bg-zinc-950/60 border border-zinc-800 text-xs text-zinc-400 leading-relaxed">
                    Cấu hình công cụ tìm kiếm trên Internet và chế độ bảo mật thực thi lệnh. Bạn có thể thay đổi bất kỳ lúc nào trong <strong>Settings → Tools</strong>.
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {/* Web Search */}
                    <div className="p-3 rounded-xl bg-zinc-950 border border-zinc-800 space-y-2">
                      <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                        <Search className="w-3.5 h-3.5 text-amber-400" />
                        <span>Công cụ Tìm kiếm Web</span>
                      </label>
                      <select
                        value={webSearchProvider}
                        onChange={(e) => setWebSearchProvider(e.target.value as any)}
                        className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-100 font-semibold focus:outline-none focus:border-amber-500 cursor-pointer"
                      >
                        <option value="duckduckgo">DuckDuckGo (Miễn phí, Không cần API Key)</option>
                        <option value="brave">Brave Search API</option>
                        <option value="tavily">Tavily AI Search</option>
                      </select>
                      <p className="text-[10px] text-zinc-500">
                        DuckDuckGo cho phép Agent tự động tìm kiếm thông tin thời gian thực mà không cần đăng ký tài khoản.
                      </p>
                    </div>

                    {/* Sandbox Mode */}
                    <div className="p-3 rounded-xl bg-zinc-950 border border-zinc-800 space-y-2">
                      <label className="text-xs font-bold text-zinc-200 flex items-center gap-1.5">
                        <Shield className="w-3.5 h-3.5 text-emerald-400" />
                        <span>Chế độ Shell Sandbox</span>
                      </label>
                      <select
                        value={sandboxMode}
                        onChange={(e) => setSandboxMode(e.target.value as any)}
                        className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-100 font-semibold focus:outline-none focus:border-amber-500 cursor-pointer"
                      >
                        <option value="permissive">Permissive (Cho phép đọc & ghi trong Workspace)</option>
                        <option value="strict">Strict (Chỉ cho phép các lệnh an toàn cơ bản)</option>
                      </select>
                      <p className="text-[10px] text-zinc-500">
                        Permissive cho phép Agent tạo file mã nguồn, chạy thử nghiệm và kiểm tra ngữ cảnh dự án.
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-4 border-t border-zinc-800 bg-zinc-950 flex items-center justify-between">
          <div className="flex items-center gap-2 text-zinc-500 text-xs">
            <ExternalLink className="w-3.5 h-3.5" />
            <a
              href="https://github.com/cuongpt083/nanobot/blob/main/docs/quick-start.md"
              target="_blank"
              rel="noreferrer"
              className="hover:text-amber-400 transition-colors underline underline-offset-2"
            >
              Xem tài liệu quick-start.md
            </a>
          </div>

          <div className="flex items-center gap-3">
            {activePhase === 'environment' ? (
              <>
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/80 transition-colors cursor-pointer"
                >
                  Bỏ qua & Cài đặt sau
                </button>

                <button
                  type="button"
                  disabled={isRunningEnvSetup}
                  onClick={() => handleStartEnvSetup(isEnvDone)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-zinc-800 hover:bg-zinc-700 text-zinc-200 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                >
                  {isRunningEnvSetup ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Đang cài đặt...</span>
                    </>
                  ) : (
                    <>
                      <RefreshCw className="w-3.5 h-3.5" />
                      <span>{isEnvDone ? 'Chạy lại Cài đặt Môi trường' : 'Bắt đầu Cài đặt Tự động'}</span>
                    </>
                  )}
                </button>

                <button
                  type="button"
                  onClick={() => setActivePhase('onboarding')}
                  className="px-5 py-2 rounded-xl text-xs font-bold bg-amber-500 hover:bg-amber-400 text-zinc-950 flex items-center gap-2 shadow-md cursor-pointer transition-colors"
                >
                  <span>Tiếp tục: Cấu hình Model & Provider</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setActivePhase('environment')}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/80 flex items-center gap-1.5 transition-colors cursor-pointer"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Quay lại Môi trường</span>
                </button>

                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/80 transition-colors cursor-pointer"
                >
                  Đóng & Cấu hình sau
                </button>

                <button
                  type="button"
                  onClick={handleFinishOnboarding}
                  className="px-6 py-2.5 rounded-xl text-xs font-bold bg-gradient-to-r from-amber-500 to-emerald-400 hover:from-amber-400 hover:to-emerald-300 text-zinc-950 flex items-center gap-2 shadow-lg shadow-amber-500/10 cursor-pointer transition-all"
                >
                  <Check className="w-4 h-4 stroke-[3]" />
                  <span>Hoàn tất Onboarding & Bắt đầu sử dụng</span>
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
