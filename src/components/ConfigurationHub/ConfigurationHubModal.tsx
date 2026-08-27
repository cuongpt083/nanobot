import React, { useState } from 'react';
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
  Search
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
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => void;
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
}) => {
  const [activeTab, setActiveTab] = useState<ConfigTabKey>(initialTab);

  if (!isOpen) return null;

  const currentTabObj = TABS.find((t) => t.id === activeTab) || TABS[0];
  const Icon = currentTabObj.icon;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-950/80 backdrop-blur-md animate-fade-in">
      <div
        className="w-full max-w-5xl h-[85vh] bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-zinc-100"
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
                Manage LLM models, provider credentials, agent skills, execution tools, and gateway server
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer border border-zinc-700"
              title="Close Settings (Esc)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body (Sidebar + Content Panel) */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          {/* Left Navigation Sidebar */}
          <div className="w-60 bg-zinc-950/60 border-r border-zinc-800/80 p-3 flex flex-col justify-between flex-shrink-0 overflow-y-auto">
            <div className="space-y-1">
              <div className="px-3 py-1.5 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
                Configuration Suites
              </div>
              {TABS.map((tab) => {
                const TabIcon = tab.icon;
                const isSelected = activeTab === tab.id;

                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-medium transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-amber-500 text-zinc-950 font-bold shadow-xs'
                        : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
                    }`}
                  >
                    <TabIcon className={`w-4 h-4 ${isSelected ? 'text-zinc-950' : 'text-zinc-400'}`} />
                    <span className="truncate">{tab.label}</span>
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
              <ProvidersTab config={config} onUpdateConfig={onUpdateConfig} />
            )}
            {activeTab === 'models' && (
              <ModelPresetsTab config={config} onUpdateConfig={onUpdateConfig} />
            )}
            {activeTab === 'skills' && (
              <SkillsConfigTab config={config} onUpdateConfig={onUpdateConfig} />
            )}
            {activeTab === 'tools' && (
              <ToolsConfigTab config={config} onUpdateConfig={onUpdateConfig} />
            )}
            {activeTab === 'channels' && (
              <ChannelsConfigTab config={config} onUpdateConfig={onUpdateConfig} />
            )}
            {activeTab === 'memory' && (
              <MemoryConfigTab
                config={config}
                onUpdateConfig={onUpdateConfig}
                memoryFacts={memoryFacts}
                onTriggerDream={onTriggerDream}
                onDeleteFact={onDeleteFact}
                onAddFact={onAddFact}
              />
            )}
            {activeTab === 'gateway' && (
              <GatewayConfigTab
                config={config}
                onUpdateConfig={onUpdateConfig}
                gatewayState={gatewayState}
                logs={gatewayLogs}
                onStartGateway={onStartGateway}
                onStopGateway={onStopGateway}
                onRestartGateway={onRestartGateway}
                onClearLogs={onClearGatewayLogs}
              />
            )}
            {activeTab === 'raw-config' && (
              <RawConfigTab config={config} onUpdateConfig={(cfg) => onUpdateConfig(cfg)} />
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
      </div>
    </div>
  );
};
