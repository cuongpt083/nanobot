export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, any>;
  result?: string;
  status: 'running' | 'completed' | 'failed';
  timestamp: number;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  reasoning?: string;
  toolCalls?: ToolCall[];
  timestamp: number;
  channel?: string;
}

export interface Session {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  messages: Message[];
  model: string;
  system_prompt?: string;
  memory_offset?: number;
  channel?: string;
  token_usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface ChannelInfo {
  id: string;
  name: string;
  icon: string;
  type: 'instant_message' | 'email' | 'websocket' | 'enterprise';
  status: 'connected' | 'idle' | 'unconfigured' | 'error';
  description: string;
  pairingCode?: string;
  webhookUrl?: string;
  configFields: {
    key: string;
    label: string;
    type: 'text' | 'password' | 'select';
    placeholder?: string;
    value?: string;
    options?: string[];
  }[];
}

export interface SkillInfo {
  id: string;
  name: string;
  category: 'core' | 'automation' | 'filesystem' | 'integration' | 'custom';
  description: string;
  enabled: boolean;
  tools: string[];
  icon: string;
  instructions: string;
  schema?: string;
}

export interface MemoryFact {
  id: string;
  category: 'user_profile' | 'preference' | 'project_state' | 'learned_skill';
  content: string;
  confidence: number;
  lastUpdated: number;
  sourceSessionId?: string;
}

export interface GatewayStatus {
  status: 'online' | 'standby' | 'syncing';
  version: string;
  uptimeSeconds: number;
  activeSessions: number;
  totalMessagesProcessed: number;
  totalTokensUsed: number;
  busThroughputPerMin: number;
  llmProvider: string;
  activeModel: string;
  dreamConsolidation: {
    lastRun: number;
    totalFacts: number;
    status: 'idle' | 'consolidating';
  };
}

export interface ModelPreset {
  id: string;
  name: string;
  provider: 'gemini' | 'anthropic' | 'openai' | 'ollama' | 'deepseek';
  contextWindow: string;
  capabilities: string[];
  description: string;
  isDefault?: boolean;
}

export interface McpServerConfig {
  id: string;
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  status: 'connected' | 'disconnected' | 'error' | 'connecting';
  toolsCount: number;
  resourcesCount: number;
  description: string;
  icon: string;
  tools?: string[];
  protocol: 'stdio' | 'sse' | 'websocket';
}

export interface DesktopSettings {
  theme: 'system' | 'dark' | 'light';
  windowFrame: 'macos' | 'windows' | 'frameless';
  alwaysOnTop: boolean;
  launchAtLogin: boolean;
  shortcutQuickSummon: string;
  mcpAutoStart: boolean;
  workspacePath: string;
  notificationsEnabled: boolean;
  systemTrayEnabled: boolean;
  compactMode: boolean;
}

export interface LocalFileItem {
  id: string;
  name: string;
  path: string;
  type: 'file' | 'dir';
  size?: string;
  modified?: string;
  content?: string;
  extension?: string;
  children?: LocalFileItem[];
}

export interface DesktopReleaseInfo {
  platform: 'darwin' | 'win32' | 'linux';
  platformName: string;
  arch: string;
  version: string;
  filename: string;
  size: string;
  downloadUrl: string;
  releaseDate: string;
  sha256: string;
  instructions: string[];
}

// -------------------------------------------------------------
// Nanobot Master Config Schema Types (matching ~/.nanobot/config.json)
// -------------------------------------------------------------

export interface ProviderItemConfig {
  id?: string;
  name?: string;
  alias?: string;
  providerType?: string;
  apiKey?: string;
  apiBase?: string;
  proxy?: string;
  defaultModel?: string;
  extraBody?: Record<string, any>;
  headers?: Record<string, string>;
  modelList?: string[];
  status?: 'active' | 'configured' | 'unconfigured' | 'error';
  lastTested?: number;
  testLatencyMs?: number;
}

export interface ModelPresetItemConfig {
  id?: string;
  name?: string;
  provider: string; // 'openrouter' | 'anthropic' | 'openai' | 'gemini' | 'deepseek' | 'groq' | 'mistral' | 'ollama' | 'custom' | etc.
  model: string;
  maxTokens?: number;
  contextWindowTokens?: number;
  temperature?: number;
  reasoningEffort?: 'low' | 'medium' | 'high';
  systemPrompt?: string;
  isDefault?: boolean;
}

export interface CustomSkillItem {
  id: string;
  name: string;
  category: 'core' | 'automation' | 'filesystem' | 'integration' | 'custom';
  description: string;
  instructions: string;
  enabled: boolean;
  triggerKeywords?: string[];
  allowedTools?: string[];
  icon?: string;
}

export interface NanobotFullConfig {
  version?: string;
  providers: Record<string, ProviderItemConfig>;
  modelPresets: Record<string, ModelPresetItemConfig>;
  agents: {
    defaults: {
      modelPreset: string;
      fallbackModels?: string[];
      systemPrompt?: string;
      temperature?: number;
      maxTokens?: number;
    };
  };
  tools: {
    restrictToWorkspace: boolean;
    toolHintMaxLength?: number;
    ssrfWhitelist?: string[];
    exec: {
      sandbox: 'strict' | 'permissive' | 'container' | 'tempdir';
      timeoutS: number;
      allowedCommands?: string[];
      blockedCommands?: string[];
    };
    web: {
      search: {
        provider: 'brave' | 'duckduckgo' | 'tavily' | 'perplexity' | 'jina';
        apiKey?: string;
        maxResults?: number;
      };
      fetch: {
        userAgent?: string;
        timeoutS?: number;
      };
    };
    imageGeneration?: {
      enabled: boolean;
      provider: string;
      model?: string;
      apiKey?: string;
    };
    mcpServers: Record<string, {
      command: string;
      args: string[];
      env?: Record<string, string>;
      url?: string;
      headers?: Record<string, string>;
    }>;
  };
  skills: {
    enabled: Record<string, boolean>;
    customSkills: CustomSkillItem[];
    soulPrompt?: string;
  };
  transcription?: {
    enabled: boolean;
    provider: 'whisper' | 'groq' | 'gemini' | 'openai';
    model?: string;
    language?: string;
  };
  channels: Record<string, {
    enabled: boolean;
    token?: string;
    botToken?: string;
    appToken?: string;
    appId?: string;
    appSecret?: string;
    corpId?: string;
    secret?: string;
    imapHost?: string;
    smtpHost?: string;
    email?: string;
    password?: string;
    allowFrom?: string[];
    pairingCode?: string;
    [key: string]: any;
  }>;
  gateway: {
    port: number;
    host: string;
    authSecret?: string;
    heartbeatIntervalS?: number;
    autoCompactTtlHours?: number;
    unifiedSession?: boolean;
  };
}

export type GatewayMode = 'node_embedded' | 'python_cli' | 'custom';

export interface GatewayProcessConfig {
  mode: GatewayMode;
  host: string;
  port: number;
  autoStartOnLaunch: boolean;
  autoRestartOnCrash: boolean;
  workingDirectory: string;
  pythonPath: string;
  customCommand: string;
  customArgs: string[];
  logLevel: 'debug' | 'info' | 'warn' | 'error';
  envVars: Record<string, string>;
  maxLogLines: number;
}

export interface GatewayProcessState {
  status: 'running' | 'stopped' | 'starting' | 'stopping' | 'error';
  pid?: number;
  host: string;
  port: number;
  mode: GatewayMode;
  uptimeSeconds: number;
  memoryUsageMb: number;
  cpuPercent: number;
  startedAt?: number;
  lastError?: string;
  url: string;
  healthStatus: 'healthy' | 'unhealthy' | 'checking' | 'unknown';
  healthLatencyMs?: number;
}

export interface GatewayLogEntry {
  id: string;
  timestamp: number;
  type: 'stdout' | 'stderr' | 'system' | 'http';
  message: string;
  level?: 'info' | 'warn' | 'error' | 'debug';
}

export type SetupStepId =
  | 'check_python'
  | 'create_directories'
  | 'setup_venv'
  | 'create_scripts'
  | 'init_config'
  | 'verify_gateway';

export type SetupStepStatus = 'pending' | 'running' | 'completed' | 'skipped' | 'error';

export interface SetupStepItem {
  id: SetupStepId;
  title: string;
  description: string;
  status: SetupStepStatus;
  details?: string;
  error?: string;
  durationMs?: number;
}

export interface SetupStatusResponse {
  isInstalled: boolean;
  needsSetup: boolean;
  homeDir: string;
  nanobotDir: string;
  workspaceDir: string;
  configExists: boolean;
  installedInfo?: {
    installedAt: number;
    version: string;
    platform: string;
    arch: string;
    pythonPath?: string;
    workspacePath: string;
  } | null;
  detectedPython?: {
    found: boolean;
    path?: string;
    version?: string;
    meetsRequirements: boolean;
  };
  steps: SetupStepItem[];
}

export interface SetupRunProgressEvent {
  stepId: SetupStepId;
  stepIndex: number;
  totalSteps: number;
  step: SetupStepItem;
  log?: string;
  completed?: boolean;
  success?: boolean;
  error?: string;
}

declare global {
  interface Window {
    nanobotDesktop?: {
      isElectron: boolean;
      getInfo: () => Promise<any>;
      selectFolder: () => Promise<string | null>;
      openExternal: (url: string) => Promise<boolean>;
      toggleSpotlight: () => Promise<boolean>;
      sendNotification: (payload: { title?: string; body: string }) => Promise<boolean>;
      minimizeWindow?: () => Promise<boolean>;
      maximizeWindow?: () => Promise<boolean>;
      closeWindow?: () => Promise<boolean>;
      isMaximized?: () => Promise<boolean>;
      setAlwaysOnTop?: (flag: boolean) => Promise<boolean>;
      gateway?: {
        getStatus: () => Promise<GatewayProcessState>;
        getConfig: () => Promise<GatewayProcessConfig>;
        saveConfig: (config: Partial<GatewayProcessConfig>) => Promise<any>;
        start: () => Promise<any>;
        stop: () => Promise<any>;
        restart: (config?: Partial<GatewayProcessConfig>) => Promise<any>;
        getLogs: () => Promise<GatewayLogEntry[]>;
        clearLogs: () => Promise<boolean>;
        ping: () => Promise<any>;
        onLog: (callback: (entry: GatewayLogEntry) => void) => () => void;
        onStatusChange: (callback: (state: GatewayProcessState) => void) => () => void;
      };
      setup?: {
        getStatus: () => Promise<SetupStatusResponse>;
        runSetup: (options?: { forceReinstall?: boolean }) => Promise<{ success: boolean; steps: SetupStepItem[]; error?: string }>;
        onProgress: (callback: (data: SetupRunProgressEvent) => void) => () => void;
      };
      on: (channel: string, callback: (...args: any[]) => void) => void;
      off: (channel: string, callback: (...args: any[]) => void) => void;
    };
  }
}


