import React, { useState, useEffect, useMemo } from 'react';
import {
  Session,
  MemoryFact,
  DesktopSettings,
  NanobotFullConfig,
  GatewayProcessState,
  GatewayLogEntry,
  DesktopReleaseInfo,
  ModelPresetItemConfig
} from './types';
import { ChatView } from './components/ChatView';
import { DesktopHeader } from './components/DesktopHeader';
import { WorkspaceExplorerView } from './components/WorkspaceExplorerView';
import { QuickSummonModal } from './components/QuickSummonModal';
import { ConfigurationHubModal, ConfigTabKey } from './components/ConfigurationHub/ConfigurationHubModal';
import { InitialSetupWizardModal } from './components/InitialSetupWizardModal';
import { ErrorBoundary } from './components/ErrorBoundary';

export const App: React.FC = () => {
  // Navigation & Modal State
  const [activeMainView, setActiveMainView] = useState<'chat' | 'workspace'>('chat');
  const [isConfigOpen, setIsConfigOpen] = useState<boolean>(false);
  const [configInitialTab, setConfigInitialTab] = useState<ConfigTabKey>('providers');
  const [isQuickSummonOpen, setIsQuickSummonOpen] = useState<boolean>(false);
  const [isSetupWizardOpen, setIsSetupWizardOpen] = useState<boolean>(false);

  // Master Configuration State
  const [fullConfig, setFullConfig] = useState<NanobotFullConfig>({
    providers: {},
    modelPresets: {},
    agents: {
      defaults: {
        modelPreset: 'primary',
        temperature: 0.7,
        maxTokens: 8192,
      },
    },
    skills: {
      enabled: {},
      customSkills: [],
      soulPrompt: 'You are Nanobot Desktop, a hyper-efficient native AI copilot.',
    },
    tools: {
      restrictToWorkspace: false,
      exec: {
        sandbox: 'permissive',
        timeoutS: 30,
      },
      web: {
        search: {
          provider: 'duckduckgo',
        },
        fetch: {},
      },
      mcpServers: {},
    },
    channels: {},
    gateway: {
      port: 3000,
      host: '0.0.0.0',
      autoCompactTtlHours: 2,
      heartbeatIntervalS: 60,
    },
  });

  const [activeModelPresetId, setActiveModelPresetId] = useState<string>('primary');
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [memoryFacts, setMemoryFacts] = useState<MemoryFact[]>([]);
  const [isLoadingChat, setIsLoadingChat] = useState<boolean>(false);
  const [desktopReleases, setDesktopReleases] = useState<DesktopReleaseInfo[]>([]);

  // Gateway Process Supervisor State
  const [gatewayState, setGatewayState] = useState<GatewayProcessState>({
    status: 'running',
    port: 3000,
    host: '0.0.0.0',
    mode: 'node_embedded',
    uptimeSeconds: 340,
    memoryUsageMb: 85,
    cpuPercent: 1.2,
    url: 'http://localhost:3000',
    healthStatus: 'healthy',
  });

  const [gatewayLogs, setGatewayLogs] = useState<GatewayLogEntry[]>([
    {
      id: 'log-1',
      timestamp: Date.now() - 300000,
      type: 'system',
      message: '[Supervisor] Nanobot Gateway v0.3.0 initialized on 0.0.0.0:3000',
    },
    {
      id: 'log-2',
      timestamp: Date.now() - 240000,
      type: 'stdout',
      message: '[Providers] Registered providers: gemini, anthropic, openai, groq, deepseek, ollama',
    },
    {
      id: 'log-3',
      timestamp: Date.now() - 180000,
      type: 'stdout',
      message: '[Tools] Discovered built-in tools: filesystem, shell_sandbox, web_search, cron, memory_dream',
    },
    {
      id: 'log-4',
      timestamp: Date.now() - 60000,
      type: 'stdout',
      message: '[Gateway] Ready to accept inbound connections and agent loop events.',
    },
  ]);

  // Desktop Subsystem Settings
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

  const checkSetupStatus = async () => {
    try {
      if (window.nanobotDesktop?.setup?.getStatus) {
        const status = await window.nanobotDesktop.setup.getStatus();
        if (status.needsSetup) {
          setIsSetupWizardOpen(true);
        }
      } else {
        const res = await fetch('/api/setup/status');
        if (res.ok) {
          const status = await res.json();
          if (status.needsSetup) {
            setIsSetupWizardOpen(true);
          }
        }
      }
    } catch (err) {
      console.warn('[SetupCheck] Could not check setup status:', err);
    }
  };

  // Initial Data Fetching
  useEffect(() => {
    fetchFullConfig();
    fetchSessions();
    fetchMemory();
    fetchDesktopSettings();
    fetchDesktopReleases();
    fetchGatewayState();
    checkSetupStatus();
  }, []);

  // Listen for native desktop IPC menu triggers
  useEffect(() => {
    if (window.nanobotDesktop?.on) {
      const handleNewChat = () => {
        handleCreateSession();
        setActiveMainView('chat');
      };
      const handleOpenSettings = () => {
        openConfigHub('providers');
      };
      const handleWorkspaceSelected = (path: string) => {
        if (path) {
          handleUpdateDesktopSettings({ workspacePath: path });
          setActiveMainView('workspace');
        }
      };
      const handleNavigateTab = (tab: any) => {
        if (tab === 'chat' || tab === 'workspace') {
          setActiveMainView(tab);
        } else if (tab === 'setup' || tab === 'setup-wizard') {
          setIsSetupWizardOpen(true);
        } else if (tab) {
          openConfigHub(tab as ConfigTabKey);
        }
      };
      const handleTriggerDreamSync = () => {
        handleTriggerDream();
      };
      const handleReloadMcp = () => {
        fetchFullConfig();
      };

      window.nanobotDesktop.on('new-chat', handleNewChat);
      window.nanobotDesktop.on('open-settings', handleOpenSettings);
      window.nanobotDesktop.on('workspace-selected', handleWorkspaceSelected);
      window.nanobotDesktop.on('navigate-tab', handleNavigateTab);
      window.nanobotDesktop.on('trigger-dream-sync', handleTriggerDreamSync);
      window.nanobotDesktop.on('reload-mcp', handleReloadMcp);

      return () => {
        window.nanobotDesktop?.off('new-chat', handleNewChat);
        window.nanobotDesktop?.off('open-settings', handleOpenSettings);
        window.nanobotDesktop?.off('workspace-selected', handleWorkspaceSelected);
        window.nanobotDesktop?.off('navigate-tab', handleNavigateTab);
        window.nanobotDesktop?.off('trigger-dream-sync', handleTriggerDreamSync);
        window.nanobotDesktop?.off('reload-mcp', handleReloadMcp);
      };
    }
  }, []);

  // Global Alt+Space / Cmd+, / Cmd+N listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        openConfigHub('providers');
      }
      if (e.altKey && e.code === 'Space') {
        e.preventDefault();
        setIsQuickSummonOpen((prev) => !prev);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        e.preventDefault();
        handleCreateSession();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const openConfigHub = (tab: ConfigTabKey = 'providers') => {
    setConfigInitialTab(tab);
    setIsConfigOpen(true);
  };

  const fetchFullConfig = async () => {
    try {
      const res = await fetch('/api/config');
      if (res.ok) {
        const data = await res.json();
        setFullConfig(data);
        const preferredPresetId =
          data.agents?.defaults?.modelPreset ||
          Object.keys(data.modelPresets || {})[0] ||
          'primary';
        setActiveModelPresetId(preferredPresetId);
      }
    } catch (e) {
      console.warn('Failed to fetch full config:', e);
    }
  };

  const handleUpdateFullConfig = async (newPartialConfig: Partial<NanobotFullConfig>) => {
    const merged = { ...fullConfig, ...newPartialConfig };
    setFullConfig(merged);
    try {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(merged),
      });
    } catch (e) {
      console.error('Failed to update config:', e);
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

  const fetchMemory = async () => {
    try {
      const res = await fetch('/api/memory');
      if (res.ok) {
        const data = await res.json();
        setMemoryFacts(data.facts || []);
      }
    } catch (e) {
      console.warn('Failed to fetch memory:', e);
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

  const fetchDesktopReleases = async () => {
    try {
      const res = await fetch('/api/desktop/releases');
      if (res.ok) {
        const data = await res.json();
        setDesktopReleases(data.releases || []);
      }
    } catch (e) {
      console.warn('Failed to fetch desktop releases:', e);
    }
  };

  const fetchGatewayState = async () => {
    try {
      const res = await fetch('/api/desktop/gateway/status');
      if (res.ok) {
        const data = await res.json();
        setGatewayState(data);
      }
    } catch (e) {
      console.warn('Failed to fetch gateway process state:', e);
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

  // Gateway Supervisor Actions
  const handleStartGateway = async () => {
    try {
      const res = await fetch('/api/desktop/gateway/start', { method: 'POST' });
      if (res.ok) {
        const updated = await res.json();
        setGatewayState(updated);
        setGatewayLogs((prev) => [
          ...prev,
          {
            id: `log-${Date.now()}`,
            timestamp: Date.now(),
            type: 'system',
            message: `[Supervisor] Gateway process started (PID ${updated.pid})`,
          },
        ]);
      }
    } catch (e) {
      console.error('Failed to start gateway:', e);
    }
  };

  const handleStopGateway = async () => {
    try {
      const res = await fetch('/api/desktop/gateway/stop', { method: 'POST' });
      if (res.ok) {
        const updated = await res.json();
        setGatewayState(updated);
        setGatewayLogs((prev) => [
          ...prev,
          {
            id: `log-${Date.now()}`,
            timestamp: Date.now(),
            type: 'stderr',
            message: '[Supervisor] Gateway process stopped gracefully.',
          },
        ]);
      }
    } catch (e) {
      console.error('Failed to stop gateway:', e);
    }
  };

  const handleRestartGateway = async () => {
    try {
      const res = await fetch('/api/desktop/gateway/restart', { method: 'POST' });
      if (res.ok) {
        const updated = await res.json();
        setGatewayState(updated);
        setGatewayLogs((prev) => [
          ...prev,
          {
            id: `log-${Date.now()}`,
            timestamp: Date.now(),
            type: 'system',
            message: `[Supervisor] Gateway restarted successfully (PID ${updated.pid})`,
          },
        ]);
      }
    } catch (e) {
      console.error('Failed to restart gateway:', e);
    }
  };

  const handleClearGatewayLogs = () => {
    setGatewayLogs([]);
  };

  // Memory Actions
  const handleTriggerDream = async () => {
    try {
      const res = await fetch('/api/memory/consolidate', { method: 'POST' });
      if (res.ok) {
        await fetchMemory();
      }
    } catch (e) {
      console.error('Failed dream consolidation:', e);
    }
  };

  const handleDeleteFact = async (factId: string) => {
    try {
      const res = await fetch(`/api/memory/${factId}`, { method: 'DELETE' });
      if (res.ok) {
        setMemoryFacts((prev) => prev.filter((f) => f.id !== factId));
      }
    } catch (e) {
      console.error('Failed to delete fact:', e);
    }
  };

  const handleAddFact = async (factData: Partial<MemoryFact>) => {
    const newFact: MemoryFact = {
      id: `fact-${Date.now()}`,
      category: factData.category || 'user_profile',
      content: factData.content || '',
      confidence: factData.confidence || 0.9,
      lastUpdated: Date.now(),
    };
    setMemoryFacts((prev) => [newFact, ...prev]);
  };

  // Dynamically resolve active model preset from config / presets / providers
  const currentModelPreset: ModelPresetItemConfig = useMemo(() => {
    if (activeModelPresetId && fullConfig.modelPresets?.[activeModelPresetId]) {
      return fullConfig.modelPresets[activeModelPresetId];
    }
    const defaultPresetKey = fullConfig.agents?.defaults?.modelPreset;
    if (defaultPresetKey && fullConfig.modelPresets?.[defaultPresetKey]) {
      return fullConfig.modelPresets[defaultPresetKey];
    }
    const isDefaultPreset = Object.values(fullConfig.modelPresets || {}).find((p) => p.isDefault);
    if (isDefaultPreset) return isDefaultPreset;

    const firstPreset = Object.values(fullConfig.modelPresets || {})[0];
    if (firstPreset) return firstPreset;

    const firstProvider = Object.values(fullConfig.providers || {}).find(
      (p) => p.status === 'active' || p.apiKey || p.apiBase
    ) || Object.values(fullConfig.providers || {})[0];

    if (firstProvider) {
      return {
        id: 'primary',
        name: firstProvider.alias || firstProvider.name || firstProvider.id || 'Primary Model',
        model: firstProvider.defaultModel || firstProvider.modelList?.[0] || 'default-model',
        provider: firstProvider.id || 'custom',
        isDefault: true,
      };
    }

    return {
      id: 'primary',
      name: 'Primary Model',
      model: 'default-model',
      provider: 'custom',
    };
  }, [fullConfig, activeModelPresetId]);

  // Chat Actions
  const handleCreateSession = async () => {
    const modelToUse = currentModelPreset.model;
    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: 'New Workspace Thread',
          model: modelToUse,
          system_prompt: fullConfig.skills?.soulPrompt || 'You are Nanobot Desktop.',
        }),
      });
      if (res.ok) {
        const newSession: Session = await res.json();
        setSessions((prev) => [newSession, ...prev]);
        setActiveSessionId(newSession.id);
        setActiveMainView('chat');
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

  const handleChangeSessionModel = async (newModel: string, presetId?: string) => {
    if (presetId) {
      setActiveModelPresetId(presetId);
      handleUpdateFullConfig({
        agents: {
          ...fullConfig.agents,
          defaults: {
            ...fullConfig.agents?.defaults,
            modelPreset: presetId,
          },
        },
      });
    }
    if (activeSessionId) {
      setSessions((prev) =>
        prev.map((s) => (s.id === activeSessionId ? { ...s, model: newModel } : s))
      );
      try {
        await fetch(`/api/sessions/${activeSessionId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: newModel }),
        });
      } catch (e) {}
    }
  };

  const handleSendMessage = async (text: string) => {
    if (!activeSessionId) {
      if (sessions.length === 0) {
        await handleCreateSession();
      }
    }
    const targetSessionId = activeSessionId || sessions[0]?.id;
    if (!targetSessionId) return;

    setIsLoadingChat(true);
    const modelToUse = currentModelPreset.model;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId: targetSessionId,
          message: text,
          model: modelToUse,
          customPrompt: fullConfig.skills?.soulPrompt,
        }),
      });

      if (res.ok) {
        const { session: updatedSession } = await res.json();
        setSessions((prev) =>
          prev.map((s) => (s.id === updatedSession.id ? updatedSession : s)),
        );
      }
    } catch (e) {
      console.error('Chat error:', e);
    } finally {
      setIsLoadingChat(false);
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-zinc-950 text-zinc-100 font-sans select-none">
      {/* Desktop Native Window Header & Integrated Menu Bar */}
      <DesktopHeader
        settings={desktopSettings}
        onUpdateSettings={handleUpdateDesktopSettings}
        onOpenQuickSummon={() => setIsQuickSummonOpen(true)}
        onNewChat={handleCreateSession}
        onTriggerDream={handleTriggerDream}
        onOpenConfig={openConfigHub}
        activeModelPresetId={activeModelPresetId}
        modelPresets={fullConfig.modelPresets}
        onSelectModelPreset={(presetId) => {
          setActiveModelPresetId(presetId);
          handleUpdateFullConfig({
            agents: {
              ...fullConfig.agents,
              defaults: {
                ...fullConfig.agents.defaults,
                modelPreset: presetId,
              },
            },
          });
        }}
        gatewayRunning={gatewayState.status === 'running'}
        onOpenSetupWizard={() => setIsSetupWizardOpen(true)}
      />

      {/* Main Content Stage */}
      <main className="flex-1 flex min-h-0 overflow-hidden relative">
        <ErrorBoundary
          fallbackTitle="Đã xảy ra lỗi khi tải giao diện chức năng"
          onReset={() => {
            setActiveMainView('chat');
            fetchFullConfig();
          }}
        >
          {activeMainView === 'chat' ? (
            <ChatView
              sessions={sessions}
              activeSessionId={activeSessionId}
              onSelectSession={setActiveSessionId}
              onCreateSession={handleCreateSession}
              onDeleteSession={handleDeleteSession}
              onSendMessage={handleSendMessage}
              isLoading={isLoadingChat}
              activeModel={currentModelPreset.model}
              onChangeModel={handleChangeSessionModel}
              modelPresets={fullConfig.modelPresets}
              providers={fullConfig.providers}
            />
          ) : (
            <WorkspaceExplorerView workspacePath={desktopSettings.workspacePath} />
          )}
        </ErrorBoundary>
      </main>

      {/* Floating Quick Summon Spotlight */}
      <QuickSummonModal
        isOpen={isQuickSummonOpen}
        onClose={() => setIsQuickSummonOpen(false)}
        onSendToChat={(msg) => {
          setActiveMainView('chat');
          handleSendMessage(msg);
        }}
      />

      {/* Master Configuration Hub Modal (All 9 Suites) */}
      <ConfigurationHubModal
        isOpen={isConfigOpen}
        onClose={() => setIsConfigOpen(false)}
        initialTab={configInitialTab}
        config={fullConfig}
        onUpdateConfig={handleUpdateFullConfig}
        desktopSettings={desktopSettings}
        onUpdateDesktopSettings={handleUpdateDesktopSettings}
        gatewayState={gatewayState}
        gatewayLogs={gatewayLogs}
        onStartGateway={handleStartGateway}
        onStopGateway={handleStopGateway}
        onRestartGateway={handleRestartGateway}
        onClearGatewayLogs={handleClearGatewayLogs}
        memoryFacts={memoryFacts}
        onTriggerDream={handleTriggerDream}
        onDeleteFact={handleDeleteFact}
        onAddFact={handleAddFact}
        desktopReleases={desktopReleases}
        onOpenSetupWizard={() => setIsSetupWizardOpen(true)}
      />

      {/* Initial Environment Setup & Provisioning Wizard Modal */}
      <InitialSetupWizardModal
        isOpen={isSetupWizardOpen}
        onClose={() => setIsSetupWizardOpen(false)}
        onSetupCompleted={async () => {
          await fetchFullConfig();
          await fetchSessions();
          await fetchGatewayState();
        }}
      />
    </div>
  );
};

export default App;
