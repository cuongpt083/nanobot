import React, { useState, useEffect } from 'react';
import {
  Settings2,
  Shield,
  FileCode,
  HardDrive,
  Cpu,
  Check,
  Save,
  Key,
  Globe,
  Sparkles,
  Bot,
  Layers,
  Terminal,
  ExternalLink,
  Eye,
  EyeOff
} from 'lucide-react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  systemPrompt: string;
  onSaveSystemPrompt: (prompt: string) => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  systemPrompt,
  onSaveSystemPrompt,
}) => {
  const [activeTab, setActiveTab] = useState<'providers' | 'persona' | 'sandbox'>('providers');
  const [prompt, setPrompt] = useState(systemPrompt);
  const [sandboxEnabled, setSandboxEnabled] = useState(true);
  const [autoDreamInterval, setAutoDreamInterval] = useState('2');
  const [workspaceDir, setWorkspaceDir] = useState('~/.nanobot/workspace');
  const [defaultModel, setDefaultModel] = useState('gemini-2.5-flash');
  const [configPath, setConfigPath] = useState('~/.nanobot/config.json');

  // API Keys state for LLM Providers
  const [keys, setKeys] = useState({
    gemini: '',
    openai: '',
    anthropic: '',
    deepseek: '',
    openrouter: '',
    groq: '',
  });
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [isSaved, setIsSaved] = useState(false);
  const [isLoadingSettings, setIsLoadingSettings] = useState(false);

  useEffect(() => {
    if (isOpen) {
      loadSettings();
    }
  }, [isOpen]);

  const loadSettings = async () => {
    setIsLoadingSettings(true);
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        if (data.configPath) setConfigPath(data.configPath);
        if (data.config?.providers) {
          setKeys({
            gemini: data.config.providers.gemini?.apiKey || '',
            openai: data.config.providers.openai?.apiKey || '',
            anthropic: data.config.providers.anthropic?.apiKey || '',
            deepseek: data.config.providers.deepseek?.apiKey || '',
            openrouter: data.config.providers.openrouter?.apiKey || '',
            groq: data.config.providers.groq?.apiKey || '',
          });
        }
        if (data.config?.agents?.defaults?.model) {
          setDefaultModel(data.config.agents.defaults.model);
        }
        if (data.config?.agents?.defaults?.workspace) {
          setWorkspaceDir(data.config.agents.defaults.workspace);
        }
      }
    } catch (e) {
      console.warn('Failed to load settings:', e);
    } finally {
      setIsLoadingSettings(false);
    }
  };

  if (!isOpen) return null;

  const toggleShowKey = (provider: string) => {
    setShowKeys((prev) => ({ ...prev, [provider]: !prev[provider] }));
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    onSaveSystemPrompt(prompt);

    // Save providers to ~/.nanobot/config.json via /api/settings
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          providers: {
            gemini: keys.gemini ? { apiKey: keys.gemini } : undefined,
            openai: keys.openai ? { apiKey: keys.openai } : undefined,
            anthropic: keys.anthropic ? { apiKey: keys.anthropic } : undefined,
            deepseek: keys.deepseek ? { apiKey: keys.deepseek } : undefined,
            openrouter: keys.openrouter ? { apiKey: keys.openrouter } : undefined,
            groq: keys.groq ? { apiKey: keys.groq } : undefined,
          },
          agents: {
            defaults: {
              model: defaultModel,
              workspace: workspaceDir,
            },
          },
          dream: {
            interval_h: parseInt(autoDreamInterval, 10) || 2,
          },
        }),
      });
    } catch (e) {
      console.error('Error saving settings to ~/.nanobot/config.json:', e);
    }

    setIsSaved(true);
    setTimeout(() => {
      setIsSaved(false);
      onClose();
    }, 800);
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center p-4 z-50 animate-in fade-in duration-150">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="p-5 border-b border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-amber-500/20 text-amber-400 border border-amber-500/30">
              <Settings2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-zinc-100">Nanobot Gateway & LLM Settings</h3>
              <p className="text-xs text-zinc-400 font-mono truncate max-w-md">
                Config: <span className="text-amber-400/90">{configPath}</span>
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="text-zinc-400 hover:text-zinc-200 text-sm p-1.5 rounded-lg hover:bg-zinc-800 cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 px-6 pt-3 border-b border-zinc-800/80 bg-zinc-950/40 text-xs">
          <button
            type="button"
            onClick={() => setActiveTab('providers')}
            className={`pb-2.5 px-3 font-semibold flex items-center gap-1.5 border-b-2 transition-all cursor-pointer ${
              activeTab === 'providers'
                ? 'border-amber-400 text-amber-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Key className="w-3.5 h-3.5" />
            <span>LLM Providers & API Keys</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('persona')}
            className={`pb-2.5 px-3 font-semibold flex items-center gap-1.5 border-b-2 transition-all cursor-pointer ${
              activeTab === 'persona'
                ? 'border-amber-400 text-amber-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <FileCode className="w-3.5 h-3.5" />
            <span>Agent Persona & Models</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('sandbox')}
            className={`pb-2.5 px-3 font-semibold flex items-center gap-1.5 border-b-2 transition-all cursor-pointer ${
              activeTab === 'sandbox'
                ? 'border-amber-400 text-amber-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Shield className="w-3.5 h-3.5" />
            <span>Sandbox & Memory</span>
          </button>
        </div>

        {/* Tab Content */}
        <form onSubmit={handleSave} className="p-6 space-y-5 overflow-y-auto flex-1 text-xs">
          {activeTab === 'providers' && (
            <div className="space-y-4">
              <div className="p-3.5 rounded-xl bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-400 leading-relaxed">
                Cấu hình API Key được lưu trực tiếp vào file <code className="text-amber-400 font-mono">~/.nanobot/config.json</code>.
                Nanobot Gateway và Agent Loop sẽ tự động sử dụng key này để phản hồi hội thoại.
              </div>

              {/* Gemini */}
              <div className="space-y-1.5">
                <label className="font-semibold text-zinc-200 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-sky-400" />
                    <span>Google Gemini API Key</span>
                  </span>
                  <span className="text-[10px] text-zinc-500 font-mono">GEMINI_API_KEY</span>
                </label>
                <div className="relative">
                  <input
                    type={showKeys.gemini ? 'text' : 'password'}
                    placeholder="AIzaSy..."
                    value={keys.gemini}
                    onChange={(e) => setKeys({ ...keys, gemini: e.target.value })}
                    className="w-full pl-3 pr-10 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                  />
                  <button
                    type="button"
                    onClick={() => toggleShowKey('gemini')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                  >
                    {showKeys.gemini ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              {/* OpenAI */}
              <div className="space-y-1.5">
                <label className="font-semibold text-zinc-200 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Bot className="w-3.5 h-3.5 text-emerald-400" />
                    <span>OpenAI API Key</span>
                  </span>
                  <span className="text-[10px] text-zinc-500 font-mono">OPENAI_API_KEY</span>
                </label>
                <div className="relative">
                  <input
                    type={showKeys.openai ? 'text' : 'password'}
                    placeholder="sk-proj-..."
                    value={keys.openai}
                    onChange={(e) => setKeys({ ...keys, openai: e.target.value })}
                    className="w-full pl-3 pr-10 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                  />
                  <button
                    type="button"
                    onClick={() => toggleShowKey('openai')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                  >
                    {showKeys.openai ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              {/* DeepSeek */}
              <div className="space-y-1.5">
                <label className="font-semibold text-zinc-200 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Cpu className="w-3.5 h-3.5 text-indigo-400" />
                    <span>DeepSeek API Key</span>
                  </span>
                  <span className="text-[10px] text-zinc-500 font-mono">DEEPSEEK_API_KEY</span>
                </label>
                <div className="relative">
                  <input
                    type={showKeys.deepseek ? 'text' : 'password'}
                    placeholder="sk-..."
                    value={keys.deepseek}
                    onChange={(e) => setKeys({ ...keys, deepseek: e.target.value })}
                    className="w-full pl-3 pr-10 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                  />
                  <button
                    type="button"
                    onClick={() => toggleShowKey('deepseek')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                  >
                    {showKeys.deepseek ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              {/* Anthropic Claude */}
              <div className="space-y-1.5">
                <label className="font-semibold text-zinc-200 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-amber-400" />
                    <span>Anthropic Claude API Key</span>
                  </span>
                  <span className="text-[10px] text-zinc-500 font-mono">ANTHROPIC_API_KEY</span>
                </label>
                <div className="relative">
                  <input
                    type={showKeys.anthropic ? 'text' : 'password'}
                    placeholder="sk-ant-..."
                    value={keys.anthropic}
                    onChange={(e) => setKeys({ ...keys, anthropic: e.target.value })}
                    className="w-full pl-3 pr-10 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                  />
                  <button
                    type="button"
                    onClick={() => toggleShowKey('anthropic')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                  >
                    {showKeys.anthropic ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              {/* OpenRouter */}
              <div className="space-y-1.5">
                <label className="font-semibold text-zinc-200 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Globe className="w-3.5 h-3.5 text-purple-400" />
                    <span>OpenRouter API Key (All-in-One Gateway)</span>
                  </span>
                  <span className="text-[10px] text-zinc-500 font-mono">OPENROUTER_API_KEY</span>
                </label>
                <div className="relative">
                  <input
                    type={showKeys.openrouter ? 'text' : 'password'}
                    placeholder="sk-or-..."
                    value={keys.openrouter}
                    onChange={(e) => setKeys({ ...keys, openrouter: e.target.value })}
                    className="w-full pl-3 pr-10 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                  />
                  <button
                    type="button"
                    onClick={() => toggleShowKey('openrouter')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                  >
                    {showKeys.openrouter ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'persona' && (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <label className="font-semibold text-zinc-200">Mô hình mặc định (Default Model Preset)</label>
                <select
                  value={defaultModel}
                  onChange={(e) => setDefaultModel(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-zinc-200 focus:outline-none focus:border-amber-500 font-mono"
                >
                  <option value="gemini-2.5-flash">Gemini 2.5 Flash (Nhanh & Tối ưu)</option>
                  <option value="gemini-2.5-pro">Gemini 2.5 Pro (Lập luận sâu)</option>
                  <option value="claude-3-7-sonnet-20250219">Claude 3.7 Sonnet (Agentic Coding)</option>
                  <option value="gpt-4o">GPT-4o</option>
                  <option value="gpt-4o-mini">GPT-4o Mini</option>
                  <option value="deepseek-chat">DeepSeek V3 (deepseek-chat)</option>
                  <option value="deepseek-reasoner">DeepSeek R1 (deepseek-reasoner)</option>
                  <option value="llama-3.3-70b-versatile">Groq Llama 3.3 70B</option>
                  <option value="ollama/llama3.2">Ollama Local (llama3.2)</option>
                </select>
              </div>

              {/* System Persona / SOUL.md */}
              <div className="space-y-2">
                <label className="block font-semibold text-zinc-200 flex items-center gap-2">
                  <FileCode className="w-4 h-4 text-amber-400" />
                  <span>System Prompt (`SOUL.md` Agent Persona)</span>
                </label>
                <textarea
                  rows={6}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  className="w-full p-3 rounded-lg bg-zinc-950 border border-zinc-800 font-mono text-zinc-200 focus:outline-none focus:border-amber-500 leading-relaxed"
                />
                <p className="text-[11px] text-zinc-500">
                  Quy định tính cách, ràng buộc an toàn và nguyên tắc trả lời của Nanobot cho mỗi lượt trò chuyện.
                </p>
              </div>
            </div>
          )}

          {activeTab === 'sandbox' && (
            <div className="space-y-4">
              {/* Sandbox & Security */}
              <div className="space-y-3">
                <h4 className="font-semibold text-zinc-200 flex items-center gap-2">
                  <Shield className="w-4 h-4 text-emerald-400" />
                  <span>Chính sách cách ly Sandbox</span>
                </h4>

                <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-950 border border-zinc-800">
                  <div>
                    <div className="font-medium text-zinc-200">Strict Command Path Isolation</div>
                    <div className="text-[11px] text-zinc-500">
                      Giới hạn thao tác tập tin và câu lệnh shell trong thư mục workspace được chỉ định.
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={sandboxEnabled}
                    onChange={(e) => setSandboxEnabled(e.target.checked)}
                    className="w-4 h-4 accent-amber-500 cursor-pointer"
                  />
                </div>
              </div>

              {/* Dream Consolidation Settings */}
              <div className="space-y-3 pt-3 border-t border-zinc-800">
                <h4 className="font-semibold text-zinc-200 flex items-center gap-2">
                  <HardDrive className="w-4 h-4 text-indigo-400" />
                  <span>Tần suất tổng hợp trí nhớ dài hạn (Dream Memory)</span>
                </h4>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-zinc-400 mb-1">Chu kỳ kích hoạt</label>
                    <select
                      value={autoDreamInterval}
                      onChange={(e) => setAutoDreamInterval(e.target.value)}
                      className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-zinc-200 focus:outline-none focus:border-amber-500"
                    >
                      <option value="1">Mỗi 1 giờ</option>
                      <option value="2">Mỗi 2 giờ (Khuyến nghị)</option>
                      <option value="6">Mỗi 6 giờ</option>
                      <option value="24">Mỗi 24 giờ</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-zinc-400 mb-1">Thư mục Workspace</label>
                    <input
                      type="text"
                      value={workspaceDir}
                      onChange={(e) => setWorkspaceDir(e.target.value)}
                      className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="pt-4 border-t border-zinc-800 flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-medium transition-colors cursor-pointer"
            >
              Hủy
            </button>
            <button
              type="submit"
              className="flex items-center gap-2 px-5 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold transition-colors shadow-md cursor-pointer"
            >
              {isSaved ? <Check className="w-4 h-4 stroke-[3]" /> : <Save className="w-4 h-4" />}
              <span>{isSaved ? 'Đã lưu!' : 'Lưu cấu hình'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

