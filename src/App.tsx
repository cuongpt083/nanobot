import React, { useState, useEffect } from 'react';
import {
  Bot,
  MessageSquare,
  Radio,
  Wrench,
  Sparkles,
  Server,
  Settings2,
  Terminal,
  Cpu,
  Zap,
  Activity,
  Layers,
  HelpCircle,
  ExternalLink,
  Laptop,
  FolderTree,
  Download,
  Command
} from 'lucide-react';
import {
  Session,
  ChannelInfo,
  SkillInfo,
  MemoryFact,
  GatewayStatus,
  McpServerConfig,
  DesktopSettings
} from './types';
import { ChatView } from './components/ChatView';
import { ChannelsView } from './components/ChannelsView';
import { SkillsView } from './components/SkillsView';
import { DreamMemoryView } from './components/DreamMemoryView';
import { ApiPlayground } from './components/ApiPlayground';
import { SettingsModal } from './components/SettingsModal';
import { DesktopHeader } from './components/DesktopHeader';
import { McpServersView } from './components/McpServersView';
import { WorkspaceExplorerView } from './components/WorkspaceExplorerView';
import { DesktopInstallerView } from './components/DesktopInstallerView';
import { QuickSummonModal } from './components/QuickSummonModal';
import { GatewayManagerView } from './components/GatewayManagerView';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<
    'chat' | 'channels' | 'skills' | 'memory' | 'api' | 'mcp' | 'workspace' | 'desktop-installer' | 'gateway-manager'
  >('chat');
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [gatewayStatus, setGatewayStatus] = useState<GatewayStatus | null>(null);

  // Desktop Subsystem State
  const [mcpServers, setMcpServers] = useState<McpServerConfig[]>([]);
  const [desktopSettings, setDesktopSettings] = useState<DesktopSettings>({
    theme: 'dark',
    windowFrame: 'macos',
    alwaysOnTop: false,
    launchAtLogin: true,
    shortcutQuickSummon: 'Alt + Space',
    mcpAutoStart: true,
    workspacePath: '~/Projects/nanobot-workspace',
    notificationsEnabled: true,
    systemTrayEnabled: true,
    compactMode: false,
  });
  const [isQuickSummonOpen, setIsQuickSummonOpen] = useState(false);

  const [activeModel, setActiveModel] = useState<string>('gemini-2.5-flash');
  const [systemPrompt, setSystemPrompt] = useState<string>(
    'You are Nanobot Desktop, a hyper-efficient native AI copilot designed for local workflow execution, Model Context Protocol (MCP) tool invocation, and developer productivity. Provide clear, direct, and well-formatted answers.',
  );
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isLoadingChat, setIsLoadingChat] = useState(false);
  const [isConsolidatingMemory, setIsConsolidatingMemory] = useState(false);

  // Initial Data Fetching
  useEffect(() => {
    fetchStatus();
    fetchSessions();
    fetchChannels();
    fetchSkills();
    fetchMemory();
    fetchMcpServers();
    fetchDesktopSettings();
  }, []);

  // Global Alt+Space / Cmd+K Hotkey Listener for Quick Summon
  useEffect(() => {
    const handleGlobalKeys = (e: KeyboardEvent) => {
      if ((e.altKey && e.code === 'Space') || (e.metaKey && e.shiftKey && e.code === 'KeyK')) {
        e.preventDefault();
        setIsQuickSummonOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleGlobalKeys);
    return () => window.removeEventListener('keydown', handleGlobalKeys);
  }, []);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        setGatewayStatus(data);
      }
    } catch (e) {
      console.warn('Failed to fetch gateway status:', e);
    }
  };

  const fetchSessions = async () => {
    try {
      const res = await fetch('/api/sessions');
      if (res.ok) {
        const data: Session[] = await res.json();
        setSessions(data);
        if (data.length > 0 && !activeSessionId) {
          setActiveSessionId(data[0].id);
        }
      }
    } catch (e) {
      console.warn('Failed to fetch sessions:', e);
    }
  };

  const fetchChannels = async () => {
    try {
      const res = await fetch('/api/channels');
      if (res.ok) {
        const data = await res.json();
        setChannels(data);
      }
    } catch (e) {
      console.warn('Failed to fetch channels:', e);
    }
  };

  const fetchSkills = async () => {
    try {
      const res = await fetch('/api/skills');
      if (res.ok) {
        const data = await res.json();
        setSkills(data);
      }
    } catch (e) {
      console.warn('Failed to fetch skills:', e);
    }
  };

  const fetchMemory = async () => {
    try {
      const res = await fetch('/api/memory');
      if (res.ok) {
        const data = await res.json();
        setFacts(data.facts || []);
      }
    } catch (e) {
      console.warn('Failed to fetch memory:', e);
    }
  };

  const fetchMcpServers = async () => {
    try {
      const res = await fetch('/api/desktop/mcp');
      if (res.ok) {
        const data = await res.json();
        setMcpServers(data.servers || []);
      }
    } catch (e) {
      console.warn('Failed to fetch MCP servers:', e);
    }
  };

  const fetchDesktopSettings = async () => {
    try {
      const res = await fetch('/api/desktop/settings');
      if (res.ok) {
        const data = await res.json();
        setDesktopSettings(data);
      }
    } catch (e) {
      console.warn('Failed to fetch desktop settings:', e);
    }
  };

  const handleUpdateDesktopSettings = async (newSettings: Partial<DesktopSettings>) => {
    const updated = { ...desktopSettings, ...newSettings };
    setDesktopSettings(updated);
    try {
      await fetch('/api/desktop/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updated),
      });
    } catch (e) {
      console.error('Failed to save desktop settings:', e);
    }
  };

  const handleToggleMcpServer = async (serverId: string) => {
    try {
      const res = await fetch(`/api/desktop/mcp/${serverId}/toggle`, { method: 'POST' });
      if (res.ok) {
        const updated = await res.json();
        setMcpServers((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      }
    } catch (e) {
      console.error('Failed to toggle MCP server:', e);
    }
  };

  const handleAddMcpServer = async (serverData: Partial<McpServerConfig>) => {
    try {
      const res = await fetch('/api/desktop/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(serverData),
      });
      if (res.ok) {
        const created = await res.json();
        setMcpServers((prev) => [...prev, created]);
      }
    } catch (e) {
      console.error('Failed to add MCP server:', e);
    }
  };

  const handleDeleteMcpServer = async (serverId: string) => {
    try {
      const res = await fetch(`/api/desktop/mcp/${serverId}`, { method: 'DELETE' });
      if (res.ok) {
        setMcpServers((prev) => prev.filter((s) => s.id !== serverId));
      }
    } catch (e) {
      console.error('Failed to delete MCP server:', e);
    }
  };

  const handleTestMcpServer = async (serverId: string) => {
    const res = await fetch(`/api/desktop/mcp/${serverId}/test`, { method: 'POST' });
    return await res.json();
  };

  const handleCreateSession = async () => {
    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: 'New Desktop Session',
          model: activeModel,
          system_prompt: systemPrompt,
        }),
      });
      if (res.ok) {
        const newSession: Session = await res.json();
        setSessions((prev) => [newSession, ...prev]);
        setActiveSessionId(newSession.id);
      }
    } catch (e) {
      console.error('Failed to create session:', e);
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (res.ok) {
        const remaining = sessions.filter((s) => s.id !== sessionId);
        setSessions(remaining);
        if (activeSessionId === sessionId) {
          setActiveSessionId(remaining[0]?.id || '');
        }
      }
    } catch (e) {
      console.error('Failed to delete session:', e);
    }
  };

  const handleSendMessage = async (text: string) => {
    if (!activeSessionId) return;
    setIsLoadingChat(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId: activeSessionId,
          message: text,
          model: activeModel,
          customPrompt: systemPrompt,
        }),
      });

      if (res.ok) {
        const { session: updatedSession } = await res.json();
        setSessions((prev) =>
          prev.map((s) => (s.id === updatedSession.id ? updatedSession : s)),
        );
        fetchStatus();
      }
    } catch (e) {
      console.error('Chat error:', e);
    } finally {
      setIsLoadingChat(false);
    }
  };

  const handleToggleSkill = async (skillId: string) => {
    try {
      const res = await fetch(`/api/skills/${skillId}/toggle`, { method: 'POST' });
      if (res.ok) {
        const updated = await res.json();
        setSkills((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      }
    } catch (e) {
      console.error('Failed to toggle skill:', e);
    }
  };

  const handleSaveChannelConfig = async (channelId: string, values: Record<string, string>) => {
    try {
      const res = await fetch(`/api/channels/${channelId}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values }),
      });
      if (res.ok) {
        const updated = await res.json();
        setChannels((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      }
    } catch (e) {
      console.error('Failed to save channel config:', e);
    }
  };

  const handleConsolidateDream = async () => {
    setIsConsolidatingMemory(true);
    try {
      const res = await fetch('/api/memory/consolidate', { method: 'POST' });
      if (res.ok) {
        await fetchMemory();
      }
    } catch (e) {
      console.error('Failed dream consolidation:', e);
    } finally {
      setIsConsolidatingMemory(false);
    }
  };

  const handleDeleteFact = async (factId: string) => {
    try {
      const res = await fetch(`/api/memory/${factId}`, { method: 'DELETE' });
      if (res.ok) {
        setFacts((prev) => prev.filter((f) => f.id !== factId));
      }
    } catch (e) {
      console.error('Failed to delete fact:', e);
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-zinc-950 text-zinc-100 font-sans">
      {/* Desktop Native Window Header & App Menu Bar */}
      <DesktopHeader
        settings={desktopSettings}
        onUpdateSettings={handleUpdateDesktopSettings}
        onOpenQuickSummon={() => setIsQuickSummonOpen(true)}
        onNewChat={handleCreateSession}
        onTriggerDream={handleConsolidateDream}
        onSelectTab={setActiveTab}
        activeTab={activeTab}
      />

      {/* Main App Navigation Bar */}
      <header className="h-13 border-b border-zinc-800 bg-zinc-900/90 backdrop-blur-md flex items-center justify-between px-4 flex-shrink-0 z-20">
        {/* Brand & System Pulse */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-400 font-bold shadow-inner">
              <Bot className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 leading-none">
                <span className="font-bold text-xs text-zinc-100 tracking-tight">nanobot</span>
                <span className="px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 text-[9px] font-mono font-medium">
                  desktop
                </span>
              </div>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="flex items-center gap-1 bg-zinc-950/60 p-1 rounded-lg border border-zinc-800/80">
            <button
              id="tab-chat"
              onClick={() => setActiveTab('chat')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer ${
                activeTab === 'chat'
                  ? 'bg-amber-500 text-zinc-950 font-semibold shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Agent Chat</span>
            </button>

            <button
              id="tab-gateway"
              onClick={() => setActiveTab('gateway-manager')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer ${
                activeTab === 'gateway-manager'
                  ? 'bg-amber-500 text-zinc-950 font-semibold shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <Server className="w-3.5 h-3.5" />
              <span>Gateway Server</span>
            </button>

            <button
              id="tab-mcp"
              onClick={() => setActiveTab('mcp')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer ${
                activeTab === 'mcp'
                  ? 'bg-amber-500 text-zinc-950 font-semibold shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <Cpu className="w-3.5 h-3.5" />
              <span>MCP Servers</span>
            </button>

            <button
              id="tab-workspace"
              onClick={() => setActiveTab('workspace')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer ${
                activeTab === 'workspace'
                  ? 'bg-amber-500 text-zinc-950 font-semibold shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <FolderTree className="w-3.5 h-3.5" />
              <span>Workspace</span>
            </button>

            <button
              id="tab-channels"
              onClick={() => setActiveTab('channels')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer ${
                activeTab === 'channels'
                  ? 'bg-amber-500 text-zinc-950 font-semibold shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <Radio className="w-3.5 h-3.5" />
              <span>Channels</span>
            </button>

            <button
              id="tab-skills"
              onClick={() => setActiveTab('skills')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer ${
                activeTab === 'skills'
                  ? 'bg-amber-500 text-zinc-950 font-semibold shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <Wrench className="w-3.5 h-3.5" />
              <span>Skills</span>
            </button>

            <button
              id="tab-memory"
              onClick={() => setActiveTab('memory')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer ${
                activeTab === 'memory'
                  ? 'bg-amber-500 text-zinc-950 font-semibold shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Dream Memory</span>
            </button>

            <button
              id="tab-installer"
              onClick={() => setActiveTab('desktop-installer')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer ${
                activeTab === 'desktop-installer'
                  ? 'bg-amber-500 text-zinc-950 font-semibold shadow-sm'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
              }`}
            >
              <Download className="w-3.5 h-3.5" />
              <span>Installers</span>
            </button>
          </nav>
        </div>

        {/* Right Status & Global Settings */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => setActiveTab('gateway-manager')}
            className="hidden lg:flex items-center gap-3 text-xs font-mono px-3 py-1.5 rounded-lg bg-zinc-950 hover:bg-zinc-900 border border-zinc-800 text-zinc-400 cursor-pointer transition-colors"
            title="Open Gateway Server Manager"
          >
            <span className="flex items-center gap-1.5 text-emerald-400">
              <Activity className="w-3.5 h-3.5 animate-pulse" />
              <span>Gateway :3000</span>
            </span>
            <span>•</span>
            <span>{mcpServers.filter((s) => s.status === 'connected').length} MCP</span>
          </button>

          <button
            id="btn-open-settings"
            onClick={() => setIsSettingsOpen(true)}
            className="p-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-zinc-100 transition-colors cursor-pointer border border-zinc-700"
            title="Gateway Settings"
          >
            <Settings2 className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 overflow-hidden relative">
        {activeTab === 'gateway-manager' && (
          <GatewayManagerView onRefreshGlobalStatus={fetchStatus} />
        )}
        {activeTab === 'chat' && (
          <ChatView
            sessions={sessions}
            activeSessionId={activeSessionId}
            onSelectSession={setActiveSessionId}
            onCreateSession={handleCreateSession}
            onDeleteSession={handleDeleteSession}
            onSendMessage={handleSendMessage}
            isLoading={isLoadingChat}
            activeModel={activeModel}
            onChangeModel={setActiveModel}
          />
        )}

        {activeTab === 'mcp' && (
          <McpServersView
            servers={mcpServers}
            onToggleServer={handleToggleMcpServer}
            onAddServer={handleAddMcpServer}
            onDeleteServer={handleDeleteMcpServer}
            onTestServer={handleTestMcpServer}
          />
        )}

        {activeTab === 'workspace' && (
          <WorkspaceExplorerView workspacePath={desktopSettings.workspacePath} />
        )}

        {activeTab === 'channels' && (
          <ChannelsView
            channels={channels}
            onSaveChannelConfig={handleSaveChannelConfig}
          />
        )}

        {activeTab === 'skills' && (
          <SkillsView skills={skills} onToggleSkill={handleToggleSkill} />
        )}

        {activeTab === 'memory' && (
          <DreamMemoryView
            facts={facts}
            onConsolidate={handleConsolidateDream}
            onDeleteFact={handleDeleteFact}
            isConsolidating={isConsolidatingMemory}
          />
        )}

        {activeTab === 'api' && <ApiPlayground />}

        {activeTab === 'desktop-installer' && <DesktopInstallerView />}
      </main>

      {/* Quick Summon Spotlight Floating Overlay */}
      <QuickSummonModal
        isOpen={isQuickSummonOpen}
        onClose={() => setIsQuickSummonOpen(false)}
        onSendToChat={(msg) => {
          setActiveTab('chat');
          handleSendMessage(msg);
        }}
      />

      {/* Global Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        systemPrompt={systemPrompt}
        onSaveSystemPrompt={setSystemPrompt}
      />
    </div>
  );
};

export default App;
