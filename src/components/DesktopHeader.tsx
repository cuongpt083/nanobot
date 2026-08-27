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
  Laptop
} from 'lucide-react';
import { DesktopSettings } from '../types';

interface DesktopHeaderProps {
  settings: DesktopSettings;
  onUpdateSettings: (newSettings: Partial<DesktopSettings>) => void;
  onOpenQuickSummon: () => void;
  onNewChat: () => void;
  onTriggerDream: () => void;
  onSelectTab: (tab: any) => void;
  activeTab: string;
}

export const DesktopHeader: React.FC<DesktopHeaderProps> = ({
  settings,
  onUpdateSettings,
  onOpenQuickSummon,
  onNewChat,
  onTriggerDream,
  onSelectTab,
  activeTab,
}) => {
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const isMac = settings.windowFrame === 'macos';

  const handleMenuClick = (menu: string) => {
    setActiveMenu(activeMenu === menu ? null : menu);
  };

  return (
    <div className="bg-zinc-950 border-b border-zinc-800/90 select-none text-zinc-300 text-xs flex items-center justify-between px-3 py-1.5 z-30 relative">
      {/* Left: Window Controls & App Menus */}
      <div className="flex items-center gap-3">
        {/* macOS Traffic Lights */}
        {isMac ? (
          <div className="flex items-center gap-2 pr-2">
            <button
              title="Close Window (Cmd+W)"
              className="w-3 h-3 rounded-full bg-rose-500 hover:bg-rose-600 transition-colors cursor-pointer flex items-center justify-center group"
            >
              <X className="w-2 h-2 text-rose-950 opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
            <button
              title="Minimize Window (Cmd+M)"
              className="w-3 h-3 rounded-full bg-amber-500 hover:bg-amber-600 transition-colors cursor-pointer flex items-center justify-center group"
            >
              <Minus className="w-2 h-2 text-amber-950 opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
            <button
              title="Zoom Window"
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

        {/* Native App Menus */}
        <div className="flex items-center text-[11px]">
          {/* Nanobot Menu */}
          <div className="relative">
            <button
              id="menu-nanobot"
              onClick={() => handleMenuClick('nanobot')}
              className={`px-2.5 py-1 rounded hover:bg-zinc-800 transition-colors font-semibold text-zinc-100 ${
                activeMenu === 'nanobot' ? 'bg-zinc-800' : ''
              }`}
            >
              Nanobot
            </button>
            {activeMenu === 'nanobot' && (
              <div
                className="absolute top-full left-0 mt-1 w-56 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <div className="px-3 py-1.5 font-semibold text-zinc-100 border-b border-zinc-800/80">
                  Nanobot Desktop v0.3.0
                </div>
                <button
                  onClick={() => {
                    onSelectTab('desktop-installer');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-amber-500 hover:text-zinc-950 transition-colors flex items-center justify-between"
                >
                  <span>Check for Updates...</span>
                  <span className="text-[10px] opacity-70">Up to date</span>
                </button>
                <div className="my-1 border-t border-zinc-800/80" />
                <button
                  onClick={() => {
                    onUpdateSettings({
                      windowFrame: settings.windowFrame === 'macos' ? 'windows' : 'macos',
                    });
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between"
                >
                  <span>Window Theme</span>
                  <span className="text-[10px] font-mono uppercase text-amber-400">
                    {settings.windowFrame}
                  </span>
                </button>
                <button
                  onClick={() => {
                    onUpdateSettings({ alwaysOnTop: !settings.alwaysOnTop });
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between"
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
              id="menu-file"
              onClick={() => handleMenuClick('file')}
              className={`px-2.5 py-1 rounded hover:bg-zinc-800 transition-colors text-zinc-300 ${
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
                    onSelectTab('chat');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-amber-500 hover:text-zinc-950 transition-colors flex items-center justify-between"
                >
                  <span>New Conversation</span>
                  <span className="text-[10px] font-mono opacity-70">⌘N</span>
                </button>
                <button
                  onClick={() => {
                    onSelectTab('workspace');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between"
                >
                  <span>Open Local Workspace</span>
                  <span className="text-[10px] font-mono opacity-70">⌘O</span>
                </button>
              </div>
            )}
          </div>

          {/* Gateway & Server Menu */}
          <div className="relative">
            <button
              id="menu-gateway"
              onClick={() => handleMenuClick('gateway')}
              className={`px-2.5 py-1 rounded hover:bg-zinc-800 transition-colors text-zinc-300 ${
                activeMenu === 'gateway' ? 'bg-zinc-800' : ''
              }`}
            >
              Gateway & Server
            </button>
            {activeMenu === 'gateway' && (
              <div
                className="absolute top-full left-0 mt-1 w-60 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <button
                  onClick={() => {
                    onSelectTab('gateway-manager');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-amber-500 hover:text-zinc-950 transition-colors flex items-center justify-between"
                >
                  <span>Gateway Process Supervisor</span>
                  <span className="text-[10px] font-mono opacity-70">⇧⌘G</span>
                </button>
                <button
                  onClick={() => {
                    onSelectTab('gateway-manager');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between"
                >
                  <span>Live Terminal Logs</span>
                  <span className="text-[10px] font-mono opacity-70">:3000</span>
                </button>
              </div>
            )}
          </div>

          {/* MCP & Tools Menu */}
          <div className="relative">
            <button
              id="menu-mcp"
              onClick={() => handleMenuClick('mcp')}
              className={`px-2.5 py-1 rounded hover:bg-zinc-800 transition-colors text-zinc-300 ${
                activeMenu === 'mcp' ? 'bg-zinc-800' : ''
              }`}
            >
              MCP & Tools
            </button>
            {activeMenu === 'mcp' && (
              <div
                className="absolute top-full left-0 mt-1 w-60 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <button
                  onClick={() => {
                    onSelectTab('mcp');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-amber-500 hover:text-zinc-950 transition-colors flex items-center justify-between"
                >
                  <span>Model Context Protocol (MCP)</span>
                  <span className="text-[10px] font-mono opacity-70">⇧⌘M</span>
                </button>
                <button
                  onClick={() => {
                    onTriggerDream();
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between"
                >
                  <span>Consolidate Dream Memory</span>
                  <span className="text-[10px] font-mono opacity-70">⇧⌘D</span>
                </button>
                <button
                  onClick={() => {
                    onSelectTab('skills');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-zinc-800 transition-colors flex items-center justify-between"
                >
                  <span>Agent Skills Registry</span>
                  <span className="text-[10px] font-mono opacity-70">⌘K</span>
                </button>
              </div>
            )}
          </div>

          {/* Installers Menu */}
          <div className="relative">
            <button
              id="menu-installers"
              onClick={() => handleMenuClick('installers')}
              className={`px-2.5 py-1 rounded hover:bg-zinc-800 transition-colors text-zinc-300 ${
                activeMenu === 'installers' ? 'bg-zinc-800' : ''
              }`}
            >
              Desktop Package
            </button>
            {activeMenu === 'installers' && (
              <div
                className="absolute top-full left-0 mt-1 w-64 bg-zinc-900 border border-zinc-800 rounded-lg shadow-2xl py-1 z-50 text-xs text-zinc-300"
                onMouseLeave={() => setActiveMenu(null)}
              >
                <button
                  onClick={() => {
                    onSelectTab('desktop-installer');
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-3 py-1.5 hover:bg-amber-500 hover:text-zinc-950 transition-colors flex items-center justify-between"
                >
                  <span>Download .DMG / .EXE / .AppImage</span>
                  <span className="text-[10px] font-mono opacity-70">v0.3.0</span>
                </button>
                <div className="my-1 border-t border-zinc-800/80" />
                <div className="px-3 py-1 text-[10px] text-zinc-500">
                  Electron Native Sandbox Architecture
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Center Title Indicator */}
      <div className="hidden md:flex items-center gap-2 text-zinc-400 text-[11px] font-mono">
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        <span className="text-zinc-300 font-semibold">Nanobot Desktop Engine</span>
        <span className="text-zinc-600">|</span>
        <span className="text-zinc-500">Localhost:3000 • 5 MCP Active</span>
      </div>

      {/* Right Controls: Quick Summon & Windows Controls */}
      <div className="flex items-center gap-2">
        {/* Quick Summon Spotlight Button */}
        <button
          id="btn-quick-summon"
          onClick={onOpenQuickSummon}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-zinc-800 hover:bg-amber-500 hover:text-zinc-950 text-zinc-300 text-[11px] font-medium transition-colors border border-zinc-700 cursor-pointer shadow-xs"
          title="Summon Quick Assistant Overlay (Alt+Space)"
        >
          <Command className="w-3 h-3" />
          <span>Quick Summon</span>
          <kbd className="text-[9px] font-mono px-1 py-0.2 bg-zinc-950/60 rounded text-amber-300 border border-zinc-700/80">
            Alt + Space
          </kbd>
        </button>

        {/* Windows Style Chrome Controls if on Windows frame */}
        {!isMac && (
          <div className="flex items-center gap-1 text-zinc-400 pl-2">
            <button className="p-1 hover:bg-zinc-800 hover:text-zinc-200 rounded">
              <Minus className="w-3.5 h-3.5" />
            </button>
            <button className="p-1 hover:bg-zinc-800 hover:text-zinc-200 rounded">
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
            <button className="p-1 hover:bg-rose-600 hover:text-white rounded">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
