import React, { useState, useEffect } from 'react';
import {
  X,
  Bot,
  Cpu,
  Wrench,
  Layers,
  Radio,
  Sparkles,
  Server,
  Code,
  Laptop,
  Check,
  Search,
  Save,
  RotateCcw,
  RefreshCw,
  CheckCircle2
} from 'lucide-react';
import {
  NanobotFullConfig,
  DesktopSettings,
  GatewayProcessState,
  GatewayLogEntry,
  MemoryFact,
  DesktopReleaseInfo
} from '../../types';
import { ProvidersTab } from './tabs/ProvidersTab';
import { ModelPresetsTab } from './tabs/ModelPresetsTab';
import { SkillsConfigTab } from './tabs/SkillsConfigTab';
import { ToolsConfigTab } from './tabs/ToolsConfigTab';
import { ChannelsConfigTab } from './tabs/ChannelsConfigTab';
import { MemoryConfigTab } from './tabs/MemoryConfigTab';
import { GatewayConfigTab } from './tabs/GatewayConfigTab';
import { RawConfigTab } from './tabs/RawConfigTab';
import { DesktopConfigTab } from './tabs/DesktopConfigTab';

export type ConfigTabKey =
  | 'providers'
  | 'models'
  | 'skills'
  | 'tools'
  | 'channels'
  | 'memory'
  | 'gateway'
  | 'raw-config'
  | 'desktop';

interface ConfigurationHubModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTab?: ConfigTabKey;
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => Promise<void> | void;
  desktopSettings: DesktopSettings;
  onUpdateDesktopSettings: (newSettings: Partial<DesktopSettings>) => void;
  gatewayState: GatewayProcessState;
  gatewayLogs: GatewayLogEntry[];
  onStartGateway: () => void;
  onStopGateway: () => void;
  onRestartGateway: () => void;
  onClearGatewayLogs: () => void;
  memoryFacts: MemoryFact[];
  onTriggerDream: () => void;
  onDeleteFact: (id: string) => void;
  onAddFact: (fact: Partial<MemoryFact>) => void;
  desktopReleases: DesktopReleaseInfo[];
  onOpenSetupWizard?: () => void;
}

const TABS: Array<{
  id: ConfigTabKey;
  label: string;
  icon: any;
  badge?: string;
}> = [
  { id: 'providers', label: 'AI Providers & Keys', icon: Bot },
  { id: 'models', label: 'Model Presets & Failover', icon: Cpu },
  { id: 'skills', label: 'Skills & Capabilities', icon: Wrench },
  { id: 'tools', label: 'Tools, Sandbox & MCP', icon: Layers },
  { id: 'channels', label: 'Chat Integrations', icon: Radio },
  { id: 'memory', label: 'Dream Memory Engine', icon: Sparkles },
  { id: 'gateway', label: 'Gateway Supervisor', icon: Server },
  { id: 'raw-config', label: 'Raw config.json', icon: Code },
  { id: 'desktop', label: 'Desktop & Installers', icon: Laptop },
];

export const ConfigurationHubModal: React.FC<ConfigurationHubModalProps> = ({
  isOpen,
  onClose,
  initialTab = 'providers',
  config,
  onUpdateConfig,
  desktopSettings,
  onUpdateDesktopSettings,
  gatewayState,
  gatewayLogs,
  onStartGateway,
  onStopGateway,
  onRestartGateway,
  onClearGatewayLogs,
  memoryFacts,
  onTriggerDream,
  onDeleteFact,
  onAddFact,
  desktopReleases,
  onOpenSetupWizard,
}) => {
  const [activeTab, setActiveTab] = useState<ConfigTabKey>(initialTab);
  const [workingConfig, setWorkingConfig] = useState<NanobotFullConfig>(config);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveSuccessMsg, setSaveSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    setWorkingConfig(config);
  }, [config]);

  if (!isOpen) return null;

  const currentTabObj = TABS.find((t) => t.id === activeTab) || TABS[0];
  const Icon = currentTabObj.icon;

  const handleTabUpdateConfig = (partial: Partial<NanobotFullConfig>) => {
    const updated = {
      ...workingConfig,
      ...partial,
      providers: { ...workingConfig.providers, ...(partial.providers || {}) },
      modelPresets: { ...workingConfig.modelPresets, ...(partial.modelPresets || {}) },
      agents: {
        ...workingConfig.agents,
        ...(partial.agents || {}),
        defaults: {
          ...workingConfig.agents?.defaults,
          ...(partial.agents?.defaults || {}),
        },
      },
      tools: { ...workingConfig.tools, ...(partial.tools || {}) },
      skills: { ...workingConfig.skills, ...(partial.skills || {}) },
    };
    setWorkingConfig(updated);
    onUpdateConfig(updated);
  };

  const handleSaveAllConfig = async () => {
    setIsSaving(true);
    setSaveSuccessMsg(null);
    try {
      await onUpdateConfig(workingConfig);
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(workingConfig),
      });
      if (res.ok) {
        setSaveSuccessMsg('Đã lưu thành công xuống ~/.nanobot/config.json!');
        setTimeout(() => setSaveSuccessMsg(null), 4000);
      }
    } catch (err) {
      console.error('Failed to save config:', err);
    } finally {
      setIsSaving(false);
    }
  };

  const handleResetConfig = () => {
    setWorkingConfig(config);
    setSaveSuccessMsg('Đã khôi phục lại cấu hình ban đầu');
    setTimeout(() => setSaveSuccessMsg(null), 3000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-950/80 backdrop-blur-md animate-fade-in">
      <div
        className="w-full max-w-5xl h-[88vh] bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-zinc-100"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Top Header */}
        <div className="h-14 border-b border-zinc-800/90 px-5 flex items-center justify-between flex-shrink-0 bg-zinc-950/60">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-400">
              <Icon className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-zinc-100">{currentTabObj.label}</h3>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">
                  nanobot-config
                </span>
              </div>
              <p className="text-[11px] text-zinc-400">
                Thiết lập hệ thống, API keys, Model Presets, Sandbox & Kênh kết nối
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Main Body (2 Columns) */}
        <div className="flex-1 flex overflow-hidden">
          {/* Left Navigation Sidebar */}
          <div className="w-64 border-r border-zinc-800/80 bg-zinc-950/40 p-3 flex flex-col justify-between overflow-y-auto">
            <div className="space-y-1">
              <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                Configuration Hub
              </div>
              {TABS.map((tab) => {
                const TabIcon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium transition-colors cursor-pointer ${
                      isActive
                        ? 'bg-amber-500/15 text-amber-300 font-semibold border border-amber-500/30 shadow-xs'
                        : 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <TabIcon className={`w-4 h-4 ${isActive ? 'text-amber-400' : 'text-zinc-400'}`} />
                      <span>{tab.label}</span>
                    </div>
                    {tab.badge && (
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">
                        {tab.badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* Bottom Version Pill */}
            <div className="p-3 rounded-xl bg-zinc-900/60 border border-zinc-800/60 text-[11px] font-mono text-zinc-400 flex items-center justify-between">
              <span>nanobot core</span>
              <span className="text-amber-400 font-bold">v0.3.0</span>
            </div>
          </div>

          {/* Right Main Content Area */}
          <div className="flex-1 bg-zinc-900/40 p-6 overflow-hidden flex flex-col">
            {activeTab === 'providers' && (
              <ProvidersTab config={workingConfig} onUpdateConfig={handleTabUpdateConfig} />
            )}
            {activeTab === 'models' && (
              <ModelPresetsTab config={workingConfig} onUpdateConfig={handleTabUpdateConfig} />
            )}
            {activeTab === 'skills' && (
              <SkillsConfigTab config={workingConfig} onUpdateConfig={handleTabUpdateConfig} />
            )}
            {activeTab === 'tools' && (
              <ToolsConfigTab config={workingConfig} onUpdateConfig={handleTabUpdateConfig} />
            )}
            {activeTab === 'channels' && (
              <ChannelsConfigTab config={workingConfig} onUpdateConfig={handleTabUpdateConfig} />
            )}
            {activeTab === 'memory' && (
              <MemoryConfigTab
                config={workingConfig}
                onUpdateConfig={handleTabUpdateConfig}
                memoryFacts={memoryFacts}
                onTriggerDream={onTriggerDream}
                onDeleteFact={onDeleteFact}
                onAddFact={onAddFact}
              />
            )}
            {activeTab === 'gateway' && (
              <GatewayConfigTab
                config={workingConfig}
                onUpdateConfig={handleTabUpdateConfig}
                gatewayState={gatewayState}
                logs={gatewayLogs}
                onStartGateway={onStartGateway}
                onStopGateway={onStopGateway}
                onRestartGateway={onRestartGateway}
                onClearLogs={onClearGatewayLogs}
                onOpenSetupWizard={onOpenSetupWizard}
              />
            )}
            {activeTab === 'raw-config' && (
              <RawConfigTab config={workingConfig} onUpdateConfig={(cfg) => handleTabUpdateConfig(cfg)} />
            )}
            {activeTab === 'desktop' && (
              <DesktopConfigTab
                settings={desktopSettings}
                onUpdateSettings={onUpdateDesktopSettings}
                releases={desktopReleases}
              />
            )}
          </div>
        </div>

        {/* Modal Bottom Sticky Action Bar with Save & Cancel */}
        <div className="h-16 border-t border-zinc-800/90 px-6 flex items-center justify-between flex-shrink-0 bg-zinc-950/90 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-xs font-mono text-zinc-400 bg-zinc-900 px-3 py-1.5 rounded-lg border border-zinc-800">
              <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>Đích lưu: <strong className="text-zinc-200">~/.nanobot/config.json</strong></span>
            </div>

            {saveSuccessMsg && (
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-950/80 border border-emerald-700/80 text-emerald-300 text-xs font-medium animate-fade-in shadow-xs">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                <span>{saveSuccessMsg}</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleResetConfig}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/80 border border-zinc-800 transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Khôi phục ban đầu</span>
            </button>

            <button
              onClick={handleSaveAllConfig}
              disabled={isSaving}
              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-zinc-950 font-bold text-xs shadow-lg shadow-amber-500/20 transition-all cursor-pointer disabled:opacity-50"
            >
              {isSaving ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Save className="w-3.5 h-3.5 stroke-[2.5]" />
              )}
              <span>{isSaving ? 'Đang lưu xuống đĩa...' : 'Lưu cấu hình xuống config.json'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
