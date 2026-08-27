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

declare global {
  interface Window {
    nanobotDesktop?: {
      isElectron: boolean;
      getInfo: () => Promise<any>;
      selectFolder: () => Promise<string | null>;
      openExternal: (url: string) => Promise<boolean>;
      toggleSpotlight: () => Promise<boolean>;
      sendNotification: (payload: { title?: string; body: string }) => Promise<boolean>;
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
      on: (channel: string, callback: (...args: any[]) => void) => void;
      off: (channel: string, callback: (...args: any[]) => void) => void;
    };
  }
}


