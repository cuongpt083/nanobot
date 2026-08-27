import React, { useState } from 'react';
import {
  Maximize2,
  Minimize2,
  X,
  Minus,
  Sparkles,
  Command,
  HardDrive,
  Cpu,
  Shield,
  Layers,
  ChevronDown,
  Monitor,
  ExternalLink,
  Laptop,
  Bot,
  Wrench,
  Radio,
  Server,
  Settings,
  HelpCircle,
  FolderTree,
  Activity
} from 'lucide-react';
import { DesktopSettings, ModelPresetItemConfig } from '../types';
import { ConfigTabKey } from './ConfigurationHub/ConfigurationHubModal';

interface DesktopHeaderProps {
  settings: DesktopSettings;
  onUpdateSettings: (newSettings: Partial<DesktopSettings>) => void;
  onOpenQuickSummon: () => void;
  onNewChat: () => void;
  onTriggerDream: () => void;
  onOpenConfig: (tab?: ConfigTabKey) => void;
  activeModelPresetId?: string;
  modelPresets?: Record<string, ModelPresetItemConfig>;
  onSelectModelPreset?: (presetId: string) => void;
  gatewayRunning?: boolean;
}

export const DesktopHeader: React.FC<DesktopHeaderProps> = ({
  settings,
  onUpdateSettings,
  onOpenQuickSummon,
  onNewChat,
  onTriggerDream,
  onOpenConfig,
  activeModelPresetId = 'primary',
  modelPresets = {},
  onSelectModelPreset,
  gatewayRunning = true,
}) => {
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState<boolean>(false);
  const isMac = settings.windowFrame === 'macos';

  const handleMenuClick = (menu: string) => {
    setActiveMenu(activeMenu === menu ? null : menu);
  };

  const currentPreset = modelPresets[activeModelPresetId] || {
    id: activeModelPresetId,
    name: 'Gemini 2.5 Flash',
    provider: 'gemini',
    model: 'gemini-2.5-flash',
  };

  const handleMinimize = async () => {
    if (window.nanobotDesktop?.minimizeWindow) {
      await window.nanobotDesktop.minimizeWindow();
    } else {
      onUpdateSettings({ compactMode: !settings.compactMode });
    }
  };

  const handleMaximize = async () => {
    if (window.nanobotDesktop?.maximizeWindow) {
      await window.nanobotDesktop.maximizeWindow();
    }
  };

  const handleClose = async () => {
    if (window.nanobotDesktop?.closeWindow) {
      await window.nanobotDesktop.closeWindow();
    }
  };

  const handleToggleAlwaysOnTop = async () => {
    const newVal = !settings.alwaysOnTop;
    onUpdateSettings({ alwaysOnTop: newVal });
    if (window.nanobotDesktop?.setAlwaysOnTop) {
      await window.nanobotDesktop.setAlwaysOnTop(newVal);
    }
  };

  return (
    <div className="bg-zinc-950 border-b border-zinc-800/90 select-none text-zinc-300 text-xs flex items-center justify-between px-3 py-1.5 z-30 relative">
      {/* Left: Window Controls & Native Menus */}
      <div className="flex items-center gap-3">
        {/* macOS Traffic Lights */}
        {isMac ? (
          <div className="flex items-center gap-2 pr-2">
            <button
              onClick={handleClose}
              title="Close Window"
              className="w-3 h-3 rounded-full bg-rose-500 hover:bg-rose-600 transition-colors cursor-pointer flex items-center justify-center group"
            >
              <X className="w-2 h-2 text-rose-950 opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
            <button
              onClick={handleMinimize}
              title="Minimize Window"
              className="w-3 h-3 rounded-full bg-amber-500 hover:bg-amber-600 transition-colors cursor-pointer flex items-center justify-center group"
            >
              <Minus className="w-2 h-2 text-amber-950 opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
            <button
              onClick={handleMaximize}
              title="Zoom / Maximize Window"
              className="w-3 h-3 rounded-full bg-emerald-500 hover:bg-emerald-600 transition-colors cursor-pointer flex items-center justify-center group"
            >
              <Maximize2 className="w-2 h-2 text-emerald-950 opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-1 text-[11px] font-semibold text-amber-400 pl-1">
            <Laptop className="w-3.5 h-3.5" />
            <span>NANOBOT DESKTOP</span>
          </div>
        )}

        {/* Native Desktop Menus */}
        <div className="flex items-center text-[11px]">
          {/* Nanobot Menu */}
          <div className="relative">
            <button
              onClick={() => handleMenuClick('nanobot')}
              className={`px-2 py-0.5 rounded hover:bg-zinc-800 transition-colors font-semibold text-zinc-100 ${
                activeMenu === 'nanobot' ? 'bg-zinc-800' : ''
              }`}
            >
              Nanobot
            </button>
            {activeMenu === 'nanobot' && (
              <div
                className="absolute top-full left-0 mt-1 w-60 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <div className="px-3 py-1.5 font-semibold text-zinc-100 border-b border-zinc-800/80">
                  Nanobot Desktop v0.3.0
                </div>
                <button
                  onClick={() => {
                    onOpenConfig('providers');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-amber-500 hover:text-zinc-950 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Preferences & Settings...</span>
                  <span className="text-[10px] font-mono opacity-70">⌘,</span>
                </button>
                <button
                  onClick={() => {
                    onOpenQuickSummon();
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Quick Summon Bar</span>
                  <span className="text-[10px] font-mono opacity-70">Alt+Space</span>
                </button>
                <div className="my-1 border-t border-zinc-800/80" />
                <button
                  onClick={() => {
                    onOpenConfig('desktop');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Desktop App Settings</span>
                  <span className="text-[10px] font-mono text-amber-400">{settings.windowFrame}</span>
                </button>
                <button
                  onClick={() => {
                    handleToggleAlwaysOnTop();
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Always on Top</span>
                  <span className="text-[10px]">{settings.alwaysOnTop ? '✓' : ''}</span>
                </button>
              </div>
            )}
          </div>

          {/* File Menu */}
          <div className="relative">
            <button
              onClick={() => handleMenuClick('file')}
              className={`px-2 py-0.5 rounded hover:bg-zinc-800 transition-colors text-zinc-300 ${
                activeMenu === 'file' ? 'bg-zinc-800' : ''
              }`}
            >
              File
            </button>
            {activeMenu === 'file' && (
              <div
                className="absolute top-full left-0 mt-1 w-52 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <button
                  onClick={() => {
                    onNewChat();
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-amber-500 hover:text-zinc-950 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>New Chat Thread</span>
                  <span className="text-[10px] font-mono opacity-70">⌘N</span>
                </button>
                <button
                  onClick={() => {
                    onTriggerDream();
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Consolidate Memory (Dream)</span>
                  <span className="text-[10px] font-mono opacity-70">⌘D</span>
                </button>
              </div>
            )}
          </div>

          {/* AI Providers & Models Menu */}
          <div className="relative">
            <button
              onClick={() => handleMenuClick('models')}
              className={`px-2 py-0.5 rounded hover:bg-zinc-800 transition-colors text-zinc-300 ${
                activeMenu === 'models' ? 'bg-zinc-800' : ''
              }`}
            >
              Model & Providers
            </button>
            {activeMenu === 'models' && (
              <div
                className="absolute top-full left-0 mt-1 w-64 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <div className="px-3 py-1 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
                  Active Model Presets
                </div>
                {Object.entries(modelPresets).map(([key, preset]) => (
                  <button
                    key={key}
                    onClick={() => {
                      onSelectModelPreset?.(key);
                      setActiveMenu(null);
                    }}
                    className={`w-full text-left px-3 py-1.5 transition-colors flex items-center justify-between cursor-pointer ${
                      activeModelPresetId === key
                        ? 'bg-amber-500/20 text-amber-300 font-semibold'
                        : 'hover:bg-zinc-800 text-zinc-300'
                    }`}
                  >
                    <span className="truncate">{preset.name || key}</span>
                    {activeModelPresetId === key && <span>✓</span>}
                  </button>
                ))}
                <div className="my-1 border-t border-zinc-800/80" />
                <button
                  onClick={() => {
                    onOpenConfig('providers');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer text-amber-400 font-medium"
                >
                  <span>Configure API Keys & Providers...</span>
                </button>
                <button
                  onClick={() => {
                    onOpenConfig('models');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Manage Model Presets & Fallbacks...</span>
                </button>
              </div>
            )}
          </div>

          {/* Skills & Tools Menu */}
          <div className="relative">
            <button
              onClick={() => handleMenuClick('skills')}
              className={`px-2 py-0.5 rounded hover:bg-zinc-800 transition-colors text-zinc-300 ${
                activeMenu === 'skills' ? 'bg-zinc-800' : ''
              }`}
            >
              Skills & Tools
            </button>
            {activeMenu === 'skills' && (
              <div
                className="absolute top-full left-0 mt-1 w-60 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <button
                  onClick={() => {
                    onOpenConfig('skills');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Skills & Capabilities...</span>
                </button>
                <button
                  onClick={() => {
                    onOpenConfig('tools');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Execution Sandbox & Web Search...</span>
                </button>
                <button
                  onClick={() => {
                    onOpenConfig('tools');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Model Context Protocol (MCP)...</span>
                </button>
              </div>
            )}
          </div>

          {/* Gateway & Server Menu */}
          <div className="relative">
            <button
              onClick={() => handleMenuClick('gateway')}
              className={`px-2 py-0.5 rounded hover:bg-zinc-800 transition-colors text-zinc-300 ${
                activeMenu === 'gateway' ? 'bg-zinc-800' : ''
              }`}
            >
              Gateway
            </button>
            {activeMenu === 'gateway' && (
              <div
                className="absolute top-full left-0 mt-1 w-64 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <button
                  onClick={() => {
                    onOpenConfig('gateway');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-amber-500 hover:text-zinc-950 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Gateway Process Supervisor</span>
                  <span className="text-[10px] font-mono opacity-70">:3000</span>
                </button>
                <button
                  onClick={() => {
                    onOpenConfig('channels');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Channels & Integrations...</span>
                </button>
                <button
                  onClick={() => {
                    onOpenConfig('raw-config');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span>Direct config.json Editor...</span>
                </button>
              </div>
            )}
          </div>

          {/* Help Menu */}
          <div className="relative">
            <button
              onClick={() => handleMenuClick('help')}
              className={`px-2 py-0.5 rounded hover:bg-zinc-800 transition-colors text-zinc-300 ${
                activeMenu === 'help' ? 'bg-zinc-800' : ''
              }`}
            >
              Help
            </button>
            {activeMenu === 'help' && (
              <div
                className="absolute top-full left-0 mt-1 w-56 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <a
                  href="https://github.com/cuongpt083/nanobot/blob/main/docs/providers.md"
                  target="_blank"
                  rel="noreferrer"
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between"
                >
                  <span>Providers Reference</span>
                  <ExternalLink className="w-3 h-3 text-zinc-500" />
                </a>
                <a
                  href="https://github.com/cuongpt083/nanobot/blob/main/docs/configuration.md"
                  target="_blank"
                  rel="noreferrer"
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between"
                >
                  <span>Configuration Guide</span>
                  <ExternalLink className="w-3 h-3 text-zinc-500" />
                </a>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right Controls: Quick Model Selector & Master Settings Button */}
      <div className="flex items-center gap-2.5">
        {/* Model Selector Dropdown Pill */}
        <div className="relative">
          <button
            onClick={() => setIsModelDropdownOpen(!isModelDropdownOpen)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-200 text-xs font-medium cursor-pointer transition-colors"
          >
            <Bot className="w-3.5 h-3.5 text-amber-400" />
            <span className="truncate max-w-[140px]">{currentPreset.name || currentPreset.model}</span>
            <ChevronDown className="w-3 h-3 text-zinc-500" />
          </button>

          {isModelDropdownOpen && (
            <div
              className="absolute top-full right-0 mt-1 w-64 bg-zinc-900 border border-zinc-800 rounded-xl shadow-2xl py-1 z-50 text-xs text-zinc-300"
              onMouseLeave={() => setIsModelDropdownOpen(false)}
            >
              <div className="px-3 py-1 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
                Select Active Model Preset
              </div>
              {Object.entries(modelPresets).map(([key, preset]) => (
                <button
                  key={key}
                  onClick={() => {
                    onSelectModelPreset?.(key);
                    setIsModelDropdownOpen(false);
                  }}
                  className={`w-full text-left px-3 py-2 transition-colors flex items-center justify-between cursor-pointer ${
                    activeModelPresetId === key
                      ? 'bg-amber-500/15 text-amber-300 font-semibold border-l-2 border-amber-500'
                      : 'hover:bg-zinc-800 text-zinc-300'
                  }`}
                >
                  <div>
                    <div className="text-xs font-bold text-zinc-200">{preset.name || key}</div>
                    <div className="text-[10px] text-zinc-400 font-mono">{preset.provider} • {preset.model}</div>
                  </div>
                  {activeModelPresetId === key && <span className="text-amber-400">✓</span>}
                </button>
              ))}

              <div className="my-1 border-t border-zinc-800/80" />
              <button
                onClick={() => {
                  onOpenConfig('models');
                  setIsModelDropdownOpen(false);
                }}
                className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors text-amber-400 text-xs font-medium cursor-pointer"
              >
                + Add / Manage Model Presets...
              </button>
            </div>
          )}
        </div>

        {/* Gateway Health Indicator */}
        <button
          onClick={() => onOpenConfig('gateway')}
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-zinc-900/80 hover:bg-zinc-800 border border-zinc-800/80 text-[11px] font-mono text-zinc-400 cursor-pointer transition-colors"
          title="Click to inspect Gateway Server Supervisor"
        >
          <Activity
            className={`w-3 h-3 ${
              gatewayRunning ? 'text-emerald-400 animate-pulse' : 'text-zinc-600'
            }`}
          />
          <span>:3000</span>
        </button>

        {/* Master Configuration Button */}
        <button
          onClick={() => onOpenConfig('providers')}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300 text-xs font-semibold cursor-pointer transition-all shadow-xs"
          title="Open Master Configuration Suite (⌘,)"
        >
          <Settings className="w-3.5 h-3.5" />
          <span>Config</span>
        </button>

        {/* Windows Style Chrome Controls if on Windows frame */}
        {!isMac && (
          <div className="flex items-center gap-1 text-zinc-400 pl-2">
            <button
              id="btn-win-minimize"
              onClick={handleMinimize}
              title="Minimize Window"
              className="p-1 hover:bg-zinc-800 hover:text-zinc-200 rounded cursor-pointer"
            >
              <Minus className="w-3.5 h-3.5" />
            </button>
            <button
              id="btn-win-maximize"
              onClick={handleMaximize}
              title="Maximize / Restore Window"
              className="p-1 hover:bg-zinc-800 hover:text-zinc-200 rounded cursor-pointer"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
            <button
              id="btn-win-close"
              onClick={handleClose}
              title="Close Window"
              className="p-1 hover:bg-rose-600 hover:text-white rounded cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
