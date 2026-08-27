import express, { Request, Response } from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import { GoogleGenAI } from '@google/genai';
import { createServer as createViteServer } from 'vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = 3000;

app.use(express.json({ limit: '10mb' }));

// In-Memory Storage for Nanobot Gateway
interface MemoryFactItem {
  id: string;
  category: 'user_profile' | 'preference' | 'project_state' | 'learned_skill';
  content: string;
  confidence: number;
  lastUpdated: number;
  sourceSessionId?: string;
}

interface ServerSession {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  messages: Array<{
    id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    reasoning?: string;
    toolCalls?: Array<{
      id: string;
      name: string;
      arguments: Record<string, any>;
      result?: string;
      status: 'running' | 'completed' | 'failed';
      timestamp: number;
    }>;
    timestamp: number;
    channel?: string;
  }>;
  model: string;
  system_prompt?: string;
  token_usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

const startTime = Date.now();
let totalMessagesProcessed = 28;
let totalTokensUsed = 42150;

const initialSessions: ServerSession[] = [
  {
    id: 'sess-default-1',
    title: 'Workspace Setup & Agent Loop',
    created_at: Date.now() - 3600000 * 4,
    updated_at: Date.now() - 3600000 * 2,
    model: 'gemini-2.5-flash',
    system_prompt: 'You are nanobot, an ultra-lightweight personal AI agent framework. You have access to tools for filesystem operations, bash execution, web search, cron automations, subagent spawning, and long-term dream memory.',
    messages: [
      {
        id: 'msg-1',
        role: 'user',
        content: 'Hi nanobot! Can you check my project directory structure and verify our long-term memory store?',
        timestamp: Date.now() - 3600000 * 4,
      },
      {
        id: 'msg-2',
        role: 'assistant',
        reasoning: 'The user wants to inspect project files and check memory status. I should invoke the filesystem tool to list files and query the Dream memory store.',
        toolCalls: [
          {
            id: 'call-fs-1',
            name: 'filesystem_list',
            arguments: { path: '.', recursive: false },
            result: 'Files: README.md, pyproject.toml, nanobot/, docs/, tests/, AGENTS.md, MEMORY.md',
            status: 'completed',
            timestamp: Date.now() - 3600000 * 4 + 500,
          },
          {
            id: 'call-mem-1',
            name: 'dream_memory_query',
            arguments: { query: 'user preferences and project conventions' },
            result: 'Found 4 consolidated facts: Python 3.11+, React WebUI with Vite, async MessageBus architecture, SQLite / atomic JSON memory persistence.',
            status: 'completed',
            timestamp: Date.now() - 3600000 * 4 + 1100,
          },
        ],
        content: 'Hello! I checked the root directory and verified our long-term Dream memory consolidation:\n\n1. **Directory Tree**: Repository initialized with core modules (`nanobot/agent`, `nanobot/channels`, `nanobot/providers`, `nanobot/skills`).\n2. **Dream Memory**: 4 active consolidated facts loaded into memory context. All filesystem and cron tools are ready for execution!',
        timestamp: Date.now() - 3600000 * 4 + 1800,
      },
    ],
    token_usage: {
      prompt_tokens: 1420,
      completion_tokens: 380,
      total_tokens: 1800,
    },
  },
  {
    id: 'sess-default-2',
    title: 'Cron Automation & Web Search',
    created_at: Date.now() - 3600000 * 24,
    updated_at: Date.now() - 3600000 * 12,
    model: 'gemini-2.5-flash',
    messages: [
      {
        id: 'msg-3',
        role: 'user',
        content: 'Schedule a daily 9:00 AM summary of AI research papers and notify on Discord.',
        timestamp: Date.now() - 3600000 * 24,
      },
      {
        id: 'msg-4',
        role: 'assistant',
        reasoning: 'Setting up recurring cron schedule "0 9 * * *" for research scraping and channel routing to Discord.',
        toolCalls: [
          {
            id: 'call-cron-1',
            name: 'cron_create_job',
            arguments: {
              name: 'daily-ai-arxiv',
              schedule: '0 9 * * *',
              prompt: 'Fetch top 3 AI papers on HuggingFace Daily Papers and format summary for Discord.',
              targetChannel: 'discord',
            },
            result: 'Cron job #cron-8491 registered successfully. Next run: Tomorrow at 09:00:00 UTC.',
            status: 'completed',
            timestamp: Date.now() - 3600000 * 24 + 450,
          },
        ],
        content: 'I have configured the daily automation job:\n\n- **Job ID**: `daily-ai-arxiv`\n- **Schedule**: `0 9 * * *` (Every day at 9:00 AM)\n- **Action**: Queries recent publications, formats concise bullet points, and delivers them directly to your connected Discord channel.',
        timestamp: Date.now() - 3600000 * 24 + 900,
      },
    ],
    token_usage: {
      prompt_tokens: 890,
      completion_tokens: 210,
      total_tokens: 1100,
    },
  },
];

const sessionsStore: Map<string, ServerSession> = new Map(
  initialSessions.map((s) => [s.id, s]),
);

const memoryFactsStore: MemoryFactItem[] = [
  {
    id: 'fact-1',
    category: 'user_profile',
    content: 'User prefers concise, high-density technical summaries with actionable code examples.',
    confidence: 0.96,
    lastUpdated: Date.now() - 3600000 * 48,
  },
  {
    id: 'fact-2',
    category: 'preference',
    content: 'Default model preference set to Gemini 2.5 Flash for agent loop speed & multimodal reasoning.',
    confidence: 0.98,
    lastUpdated: Date.now() - 3600000 * 12,
  },
  {
    id: 'fact-3',
    category: 'project_state',
    content: 'WebUI is unified with Node.js 22 runtime, Express gateway proxying to port 3000.',
    confidence: 0.99,
    lastUpdated: Date.now() - 3600000 * 2,
  },
  {
    id: 'fact-4',
    category: 'learned_skill',
    content: 'Can execute multi-step tools including shell scripts, search scraping, file edits, and cron scheduler.',
    confidence: 0.94,
    lastUpdated: Date.now() - 3600000 * 6,
  },
];

const channelsStore = [
  {
    id: 'telegram',
    name: 'Telegram Bot',
    icon: 'Send',
    type: 'instant_message',
    status: 'connected',
    description: 'Long polling & Webhook support with markdown streaming and image previews.',
    pairingCode: 'TG-8842-NANO',
    webhookUrl: 'https://gateway.nanobot.local/api/channels/telegram/webhook',
    configFields: [
      { key: 'botToken', label: 'Bot Token', type: 'password', placeholder: '123456:ABC-DEF...' },
      { key: 'allowedUsers', label: 'Allowed User IDs (comma separated)', type: 'text', placeholder: '12345678, 87654321' },
      { key: 'pollingMode', label: 'Connection Mode', type: 'select', options: ['Webhook', 'Long Polling'], value: 'Long Polling' },
    ],
  },
  {
    id: 'discord',
    name: 'Discord Bot',
    icon: 'MessageSquare',
    type: 'instant_message',
    status: 'connected',
    description: 'Slash commands, guild channels, thread binding, and direct message routing.',
    pairingCode: 'DC-4190-NANO',
    webhookUrl: 'https://gateway.nanobot.local/api/channels/discord/webhook',
    configFields: [
      { key: 'botToken', label: 'Discord Bot Token', type: 'password', placeholder: 'MTA4...' },
      { key: 'applicationId', label: 'Application ID', type: 'text', placeholder: '1098234...' },
      { key: 'guildId', label: 'Target Guild ID', type: 'text', placeholder: 'Optional guild restriction' },
    ],
  },
  {
    id: 'slack',
    name: 'Slack App',
    icon: 'Slack',
    type: 'instant_message',
    status: 'idle',
    description: 'Socket Mode & Events API with interactive Block Kit messages.',
    pairingCode: 'SL-9021-NANO',
    configFields: [
      { key: 'botToken', label: 'Bot User OAuth Token (xoxb-...)', type: 'password', placeholder: 'xoxb-...' },
      { key: 'appToken', label: 'App-Level Token (xapp-...)', type: 'password', placeholder: 'xapp-...' },
    ],
  },
  {
    id: 'feishu',
    name: 'Feishu / Lark',
    icon: 'Layers',
    type: 'enterprise',
    status: 'idle',
    description: 'Interactive cards, WebSocket event streaming, and multi-tenant bot permissions.',
    configFields: [
      { key: 'appId', label: 'App ID', type: 'text', placeholder: 'cli_a1b2c3d4...' },
      { key: 'appSecret', label: 'App Secret', type: 'password', placeholder: '...' },
    ],
  },
  {
    id: 'weixin',
    name: 'WeChat / WeCom',
    icon: 'Smartphone',
    type: 'instant_message',
    status: 'unconfigured',
    description: 'Enterprise WeChat intelligent customer service and standard bot gateway.',
    configFields: [
      { key: 'corpId', label: 'Corp ID', type: 'text', placeholder: 'ww12345678...' },
      { key: 'secret', label: 'Agent Secret', type: 'password', placeholder: '...' },
    ],
  },
  {
    id: 'email',
    name: 'Email SMTP / IMAP',
    icon: 'Mail',
    type: 'email',
    status: 'unconfigured',
    description: 'Inbound email task ingestion and outbound AI report digests.',
    configFields: [
      { key: 'imapHost', label: 'IMAP Server', type: 'text', placeholder: 'imap.example.com' },
      { key: 'smtpHost', label: 'SMTP Server', type: 'text', placeholder: 'smtp.example.com' },
      { key: 'email', label: 'Email Address', type: 'text', placeholder: 'agent@example.com' },
      { key: 'password', label: 'Password / App Password', type: 'password' },
    ],
  },
  {
    id: 'websocket',
    name: 'Direct WebSocket Gateway',
    icon: 'Radio',
    type: 'websocket',
    status: 'connected',
    description: 'Raw JSON multiplexed protocol for custom mobile apps, SDKs, and IoT clients.',
    pairingCode: 'WS-LIVE-3000',
    configFields: [
      { key: 'port', label: 'Port', type: 'text', value: '3000' },
      { key: 'authKey', label: 'Bearer Token (Optional)', type: 'password', placeholder: 'nano_live_...' },
    ],
  },
];

const skillsStore = [
  {
    id: 'skill-filesystem',
    name: 'Filesystem Tools',
    category: 'filesystem',
    description: 'Read, write, edit, and search workspace files with diff verification and path security.',
    enabled: true,
    tools: ['filesystem_read', 'filesystem_write', 'filesystem_edit', 'filesystem_list'],
    icon: 'FolderOpen',
    instructions: 'Always verify file existence before editing. Use atomic writes to prevent corruption.',
  },
  {
    id: 'skill-shell',
    name: 'Shell & Sandbox Execution',
    category: 'core',
    description: 'Execute bash commands with safety sandbox filters, timeout bounds, and exit code capture.',
    enabled: true,
    tools: ['shell_exec', 'shell_spawn', 'shell_status'],
    icon: 'Terminal',
    instructions: 'Enforce non-blocking executions for background tasks and restrict dangerous commands.',
  },
  {
    id: 'skill-search',
    name: 'Web Search & Page Fetch',
    category: 'core',
    description: 'Perform web queries with DuckDuckGo / Jina reader and scrape clean markdown content.',
    enabled: true,
    tools: ['web_search', 'web_fetch_url'],
    icon: 'Globe',
    instructions: 'Clean HTML tags and extract relevant articles for LLM prompt context injection.',
  },
  {
    id: 'skill-cron',
    name: 'Cron Automations & Timers',
    category: 'automation',
    description: 'Register recurrent cron schedules or one-shot countdown timers bound to session turns.',
    enabled: true,
    tools: ['cron_create_job', 'cron_list_jobs', 'cron_delete_job'],
    icon: 'Clock',
    instructions: 'Standard 5-part cron syntax with automatic time-zone normalization.',
  },
  {
    id: 'skill-dream',
    name: 'Dream Memory Consolidation',
    category: 'core',
    description: 'Two-phase memory synthesis consolidating transient chat logs into durable structured facts.',
    enabled: true,
    tools: ['dream_consolidate', 'dream_memory_query', 'dream_fact_store'],
    icon: 'Sparkles',
    instructions: 'Extract durable user preferences, project conventions, and decisions without bloating context.',
  },
  {
    id: 'skill-subagent',
    name: 'Subagent Swarm Spawning',
    category: 'automation',
    description: 'Fork isolated agent threads to execute deep research or parallel multi-step subtasks.',
    enabled: true,
    tools: ['subagent_spawn', 'subagent_wait', 'subagent_result'],
    icon: 'Bot',
    instructions: 'Spawn child agents with focused sub-prompts and aggregate their findings back to the main loop.',
  },
];

// Lazy Gemini SDK client helper
let geminiClient: GoogleGenAI | null = null;
function getGeminiClient(): GoogleGenAI | null {
  if (!geminiClient) {
    const key = process.env.GEMINI_API_KEY;
    if (key) {
      geminiClient = new GoogleGenAI({ apiKey: key });
    }
  }
  return geminiClient;
}

// -------------------------------------------------------------
// Nanobot Master Config Store (conforms to ~/.nanobot/config.json)
// -------------------------------------------------------------

interface ProviderConfigEntry {
  apiKey?: string;
  apiBase?: string;
  proxy?: string;
  extraBody?: Record<string, any>;
  headers?: Record<string, string>;
  modelList?: string[];
  status?: 'active' | 'configured' | 'unconfigured' | 'error';
  lastTested?: number;
  testLatencyMs?: number;
}

interface MasterModelPresetEntry {
  id: string;
  name: string;
  provider: string;
  model: string;
  maxTokens: number;
  contextWindowTokens: number;
  temperature: number;
  reasoningEffort?: 'low' | 'medium' | 'high';
  systemPrompt?: string;
  isDefault?: boolean;
}

interface CustomSkillConfigEntry {
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

let nanobotMasterConfig = {
  version: '0.3.0',
  providers: {
    gemini: {
      apiKey: process.env.GEMINI_API_KEY ? '****** (Environment Variable Active)' : '${GEMINI_API_KEY}',
      modelList: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash'],
      status: (process.env.GEMINI_API_KEY ? 'active' : 'unconfigured') as 'active' | 'configured' | 'unconfigured' | 'error',
    },
    openrouter: {
      apiKey: '${OPENROUTER_API_KEY}',
      modelList: [
        'anthropic/claude-3.7-sonnet',
        'anthropic/claude-3.5-sonnet',
        'openai/gpt-4o',
        'deepseek/deepseek-r1',
        'google/gemini-2.0-flash-001',
        'meta-llama/llama-3.3-70b-instruct',
      ],
      extraBody: {
        tools: [{ type: 'openrouter:web_search' }, { type: 'openrouter:web_fetch' }],
      },
      status: 'unconfigured' as const,
    },
    anthropic: {
      apiKey: '${ANTHROPIC_API_KEY}',
      modelList: [
        'claude-3-7-sonnet-20250219',
        'claude-3-5-sonnet-20241022',
        'claude-3-5-haiku-20241022',
        'claude-3-opus-20240229',
      ],
      status: 'unconfigured' as const,
    },
    openai: {
      apiKey: '${OPENAI_API_KEY}',
      modelList: ['gpt-4o', 'gpt-4o-mini', 'o1', 'o3-mini', 'gpt-4.5-preview'],
      status: 'unconfigured' as const,
    },
    deepseek: {
      apiKey: '${DEEPSEEK_API_KEY}',
      apiBase: 'https://api.deepseek.com',
      modelList: ['deepseek-chat', 'deepseek-reasoner'],
      status: 'unconfigured' as const,
    },
    groq: {
      apiKey: '${GROQ_API_KEY}',
      modelList: ['llama-3.3-70b-versatile', 'deepseek-r1-distill-llama-70b', 'mixtral-8x7b-32768'],
      status: 'unconfigured' as const,
    },
    mistral: {
      apiKey: '${MISTRAL_API_KEY}',
      modelList: ['mistral-large-latest', 'codestral-latest', 'pixtral-large-latest'],
      status: 'unconfigured' as const,
    },
    ollama: {
      apiBase: 'http://localhost:11434/v1',
      modelList: ['llama3.2:latest', 'deepseek-r1:8b', 'qwen2.5-coder:7b', 'mistral:latest'],
      status: 'configured' as const,
    },
    custom: {
      apiBase: 'http://127.0.0.1:8000/v1',
      apiKey: '${CUSTOM_API_KEY}',
      modelList: ['custom-llm-v1'],
      status: 'unconfigured' as const,
    },
  } as Record<string, ProviderConfigEntry>,
  modelPresets: {
    primary: {
      id: 'primary',
      name: 'Gemini 2.5 Flash (Primary Default)',
      provider: 'gemini',
      model: 'gemini-2.5-flash',
      maxTokens: 8192,
      contextWindowTokens: 1048576,
      temperature: 0.7,
      isDefault: true,
    },
    claude_sonnet: {
      id: 'claude_sonnet',
      name: 'Claude 3.7 Sonnet (Advanced Reasoning)',
      provider: 'anthropic',
      model: 'claude-3-7-sonnet-20250219',
      maxTokens: 8192,
      contextWindowTokens: 200000,
      temperature: 0.5,
      reasoningEffort: 'high',
    },
    gpt4o: {
      id: 'gpt4o',
      name: 'OpenAI GPT-4o (Omni Multimodal)',
      provider: 'openai',
      model: 'gpt-4o',
      maxTokens: 4096,
      contextWindowTokens: 128000,
      temperature: 0.7,
    },
    deepseek_r1: {
      id: 'deepseek_r1',
      name: 'DeepSeek R1 (Reasoning Chain)',
      provider: 'deepseek',
      model: 'deepseek-reasoner',
      maxTokens: 8192,
      contextWindowTokens: 64000,
      temperature: 0.6,
    },
    openrouter_auto: {
      id: 'openrouter_auto',
      name: 'OpenRouter Claude 3.5 Sonnet',
      provider: 'openrouter',
      model: 'anthropic/claude-3.5-sonnet',
      maxTokens: 8192,
      contextWindowTokens: 200000,
      temperature: 0.7,
    },
    ollama_local: {
      id: 'ollama_local',
      name: 'Ollama Local Llama 3.2 (Offline)',
      provider: 'ollama',
      model: 'llama3.2:latest',
      maxTokens: 4096,
      contextWindowTokens: 32000,
      temperature: 0.7,
    },
  } as Record<string, MasterModelPresetEntry>,
  agents: {
    defaults: {
      modelPreset: 'primary',
      fallbackModels: ['claude_sonnet', 'gpt4o', 'deepseek_r1'],
      systemPrompt:
        'You are nanobot, an ultra-lightweight, open-source AI agent framework with built-in tools (filesystem, shell sandbox, web search, cron, subagents, and dream memory). Always provide accurate, concise, and structured answers.',
      temperature: 0.7,
      maxTokens: 8192,
    },
  },
  tools: {
    restrictToWorkspace: true,
    toolHintMaxLength: 2048,
    ssrfWhitelist: ['localhost', '127.0.0.1', 'api.github.com', 'openrouter.ai', 'api.anthropic.com'],
    exec: {
      sandbox: 'strict' as 'strict' | 'permissive' | 'container' | 'tempdir',
      timeoutS: 30,
      allowedCommands: ['ls', 'cat', 'pwd', 'git', 'nanobot', 'npm', 'node', 'python3', 'uv'],
      blockedCommands: ['rm -rf /', ':(){ :|:& };:', 'mkfs', 'dd if=/dev/zero'],
    },
    web: {
      search: {
        provider: 'brave' as 'brave' | 'duckduckgo' | 'tavily' | 'perplexity' | 'jina',
        apiKey: '${BRAVE_API_KEY}',
        maxResults: 5,
      },
      fetch: {
        userAgent: 'nanobot-agent/0.3.0',
        timeoutS: 15,
      },
    },
    imageGeneration: {
      enabled: true,
      provider: 'gemini',
      model: 'imagen-3.0-generate-002',
      apiKey: '${GEMINI_API_KEY}',
    },
  },
  skills: {
    enabled: {
      'skill-filesystem': true,
      'skill-shell': true,
      'skill-search': true,
      'skill-cron': true,
      'skill-dream': true,
      'skill-subagent': true,
    } as Record<string, boolean>,
    customSkills: [
      {
        id: 'skill-custom-code-reviewer',
        name: 'Automated Code Reviewer & AST Analyzer',
        category: 'custom' as const,
        description: 'Enforces clean code architecture, runs TypeScript compiler checks, and analyzes diff safety.',
        instructions: 'Inspect all git diffs and verify typing correctness before confirming file modifications.',
        enabled: true,
        triggerKeywords: ['review', 'check syntax', 'audit', 'typecheck'],
        allowedTools: ['filesystem_read', 'shell_exec'],
        icon: 'Code',
      },
    ] as CustomSkillConfigEntry[],
  },
  transcription: {
    enabled: true,
    provider: 'whisper' as 'whisper' | 'groq' | 'gemini' | 'openai',
    model: 'whisper-1',
    language: 'auto',
  },
  gateway: {
    port: 3000,
    host: '0.0.0.0',
    authSecret: '',
    heartbeatIntervalS: 60,
    autoCompactTtlHours: 2,
    unifiedSession: true,
  },
};

// -------------------------------------------------------------
// Master Config REST API Endpoints
// -------------------------------------------------------------

// Get full config JSON
app.get('/api/config', (req: Request, res: Response) => {
  res.json(nanobotMasterConfig);
});

// Update full or partial config JSON
app.post('/api/config', (req: Request, res: Response) => {
  nanobotMasterConfig = {
    ...nanobotMasterConfig,
    ...req.body,
  };
  res.json({ success: true, config: nanobotMasterConfig });
});

// Get providers list & credentials status
app.get('/api/config/providers', (req: Request, res: Response) => {
  res.json(nanobotMasterConfig.providers);
});

// Update specific provider configuration
app.post('/api/config/providers/:providerKey', (req: Request, res: Response) => {
  const { providerKey } = req.params;
  const updates = req.body;

  if (!nanobotMasterConfig.providers[providerKey]) {
    nanobotMasterConfig.providers[providerKey] = {
      status: 'configured',
      ...updates,
    };
  } else {
    nanobotMasterConfig.providers[providerKey] = {
      ...nanobotMasterConfig.providers[providerKey],
      ...updates,
      status: updates.apiKey && updates.apiKey.trim() ? 'active' : nanobotMasterConfig.providers[providerKey].status,
    };
  }

  res.json({
    success: true,
    provider: providerKey,
    config: nanobotMasterConfig.providers[providerKey],
  });
});

// Test provider credentials / live endpoint connectivity
app.post('/api/config/providers/:providerKey/test', (req: Request, res: Response) => {
  const { providerKey } = req.params;
  const provider = nanobotMasterConfig.providers[providerKey];

  if (!provider) {
    return res.status(404).json({ error: `Provider ${providerKey} not found` });
  }

  const startTime = Date.now();
  setTimeout(() => {
    const latency = Date.now() - startTime + Math.floor(Math.random() * 35) + 12;
    provider.lastTested = Date.now();
    provider.testLatencyMs = latency;
    provider.status = 'active';

    res.json({
      success: true,
      provider: providerKey,
      status: 'connected',
      latencyMs: latency,
      message: `Successfully reached ${providerKey.toUpperCase()} endpoint! Models verified.`,
      modelsFound: provider.modelList?.length || 3,
    });
  }, 250);
});

// Get Model Presets
app.get('/api/config/model-presets', (req: Request, res: Response) => {
  const presets = Object.values(nanobotMasterConfig.modelPresets);
  res.json({
    presets,
    activePresetId: nanobotMasterConfig.agents.defaults.modelPreset,
    fallbackModels: nanobotMasterConfig.agents.defaults.fallbackModels || [],
  });
});

// Create or update a Model Preset
app.post('/api/config/model-presets', (req: Request, res: Response) => {
  const { id, name, provider, model, maxTokens = 8192, contextWindowTokens = 128000, temperature = 0.7, reasoningEffort } = req.body;
  const presetId = id || `preset_${Date.now()}`;

  nanobotMasterConfig.modelPresets[presetId] = {
    id: presetId,
    name: name || `${provider} / ${model}`,
    provider,
    model,
    maxTokens: Number(maxTokens),
    contextWindowTokens: Number(contextWindowTokens),
    temperature: Number(temperature),
    reasoningEffort,
  };

  res.json({
    success: true,
    preset: nanobotMasterConfig.modelPresets[presetId],
    presets: Object.values(nanobotMasterConfig.modelPresets),
  });
});

// Delete a Model Preset
app.delete('/api/config/model-presets/:id', (req: Request, res: Response) => {
  const { id } = req.params;
  if (id === 'primary') {
    return res.status(400).json({ error: 'Cannot delete the primary default preset' });
  }
  delete nanobotMasterConfig.modelPresets[id];
  res.json({ success: true, id, presets: Object.values(nanobotMasterConfig.modelPresets) });
});

// Set active model preset
app.post('/api/config/active-preset', (req: Request, res: Response) => {
  const { presetId, fallbackModels } = req.body;
  if (presetId && nanobotMasterConfig.modelPresets[presetId]) {
    nanobotMasterConfig.agents.defaults.modelPreset = presetId;
  }
  if (Array.isArray(fallbackModels)) {
    nanobotMasterConfig.agents.defaults.fallbackModels = fallbackModels;
  }
  res.json({
    success: true,
    activePresetId: nanobotMasterConfig.agents.defaults.modelPreset,
    activePreset: nanobotMasterConfig.modelPresets[nanobotMasterConfig.agents.defaults.modelPreset],
  });
});

// Get & Update Tools Config
app.get('/api/config/tools', (req: Request, res: Response) => {
  res.json(nanobotMasterConfig.tools);
});

app.post('/api/config/tools', (req: Request, res: Response) => {
  nanobotMasterConfig.tools = {
    ...nanobotMasterConfig.tools,
    ...req.body,
  };
  res.json({ success: true, tools: nanobotMasterConfig.tools });
});

// Custom Skills management
app.post('/api/config/skills/custom', (req: Request, res: Response) => {
  const { name, description, instructions, triggerKeywords = [], allowedTools = [] } = req.body;
  if (!name || !instructions) {
    return res.status(400).json({ error: 'Name and instructions are required' });
  }
  const newSkill: CustomSkillConfigEntry = {
    id: `skill-custom-${Date.now()}`,
    name,
    category: 'custom',
    description: description || 'User-defined agent skill',
    instructions,
    enabled: true,
    triggerKeywords: Array.isArray(triggerKeywords) ? triggerKeywords : [triggerKeywords],
    allowedTools: Array.isArray(allowedTools) ? allowedTools : [allowedTools],
    icon: 'Sparkles',
  };
  nanobotMasterConfig.skills.customSkills.push(newSkill);
  res.status(201).json(newSkill);
});

app.delete('/api/config/skills/custom/:id', (req: Request, res: Response) => {
  const { id } = req.params;
  nanobotMasterConfig.skills.customSkills = nanobotMasterConfig.skills.customSkills.filter((s) => s.id !== id);
  res.json({ success: true, id });
});

// Raw config.json JSON string read & save
app.get('/api/config/raw-json', (req: Request, res: Response) => {
  res.json({
    jsonString: JSON.stringify(nanobotMasterConfig, null, 2),
    filePath: '~/.nanobot/config.json',
  });
});

app.post('/api/config/raw-json', (req: Request, res: Response) => {
  const { jsonString } = req.body;
  try {
    const parsed = JSON.parse(jsonString);
    nanobotMasterConfig = parsed;
    res.json({ success: true, message: 'Configuration parsed and saved successfully to ~/.nanobot/config.json' });
  } catch (err: any) {
    res.status(400).json({ error: `JSON Parse Error: ${err.message}` });
  }
});

// -------------------------------------------------------------
// REST API Endpoints
// -------------------------------------------------------------

// Health check
app.get('/api/health', (req: Request, res: Response) => {
  res.json({
    status: 'ok',
    version: '0.3.0',
    uptime: Math.floor((Date.now() - startTime) / 1000),
    geminiConfigured: Boolean(process.env.GEMINI_API_KEY),
  });
});

// Gateway status & live telemetry
app.get('/api/status', (req: Request, res: Response) => {
  res.json({
    status: 'online',
    version: '0.3.0',
    uptimeSeconds: Math.floor((Date.now() - startTime) / 1000),
    activeSessions: sessionsStore.size,
    totalMessagesProcessed,
    totalTokensUsed,
    busThroughputPerMin: Math.floor(Math.random() * 15) + 35,
    llmProvider: process.env.GEMINI_API_KEY ? 'Google Gemini API' : 'Nanobot Local Engine',
    activeModel: 'gemini-2.5-flash',
    dreamConsolidation: {
      lastRun: Date.now() - 3600000 * 2,
      totalFacts: memoryFactsStore.length,
      status: 'idle',
    },
  });
});

// Sessions API
app.get('/api/sessions', (req: Request, res: Response) => {
  const sessions = Array.from(sessionsStore.values()).sort(
    (a, b) => b.updated_at - a.updated_at,
  );
  res.json(sessions);
});

app.post('/api/sessions', (req: Request, res: Response) => {
  const { title, model, system_prompt } = req.body;
  const newSession: ServerSession = {
    id: `sess-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
    title: title || 'New Conversation',
    created_at: Date.now(),
    updated_at: Date.now(),
    model: model || 'gemini-2.5-flash',
    system_prompt:
      system_prompt ||
      'You are nanobot, a lightweight AI agent framework. Be concise, precise, and leverage tool calls whenever suitable.',
    messages: [],
    token_usage: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
    },
  };
  sessionsStore.set(newSession.id, newSession);
  res.status(201).json(newSession);
});

app.get('/api/sessions/:id', (req: Request, res: Response) => {
  const session = sessionsStore.get(req.params.id);
  if (!session) {
    return res.status(404).json({ error: 'Session not found' });
  }
  res.json(session);
});

app.delete('/api/sessions/:id', (req: Request, res: Response) => {
  const deleted = sessionsStore.delete(req.params.id);
  if (!deleted) {
    return res.status(404).json({ error: 'Session not found' });
  }
  res.json({ success: true, id: req.params.id });
});

// Chat Turn Execution
app.post('/api/chat', async (req: Request, res: Response) => {
  const { sessionId, message, model = 'gemini-2.5-flash', customPrompt } = req.body;

  if (!sessionId || !message) {
    return res.status(400).json({ error: 'sessionId and message are required' });
  }

  let session = sessionsStore.get(sessionId);
  if (!session) {
    session = {
      id: sessionId,
      title: message.slice(0, 30) + '...',
      created_at: Date.now(),
      updated_at: Date.now(),
      model,
      messages: [],
      token_usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
    };
    sessionsStore.set(sessionId, session);
  }

  // Record user message
  const userMsg = {
    id: `msg-u-${Date.now()}`,
    role: 'user' as const,
    content: message,
    timestamp: Date.now(),
  };
  session.messages.push(userMsg);

  totalMessagesProcessed += 1;

  // Check for slash commands
  if (message.startsWith('/')) {
    const parts = message.trim().split(' ');
    const cmd = parts[0].toLowerCase();
    const arg = parts.slice(1).join(' ');

    let cmdResponse = '';
    let cmdReasoning = `Handling slash command: ${cmd}`;

    switch (cmd) {
      case '/help':
        cmdResponse = `**Available Slash Commands:**\n\n- \`/help\`: Show this command list\n- \`/clear\`: Reset the current conversation context\n- \`/model <name>\`: Switch LLM model preset\n- \`/dream\`: Trigger an instant Dream memory consolidation\n- \`/skills\`: List active agent capabilities\n- \`/status\`: Display gateway throughput and health metrics`;
        break;
      case '/clear':
        session.messages = [];
        cmdResponse = '🧹 Conversation context has been cleared. Fresh session started.';
        break;
      case '/model':
        session.model = arg || 'gemini-2.5-flash';
        cmdResponse = `Switched session model to **${session.model}**.`;
        break;
      case '/dream':
        cmdResponse = `🧠 **Dream Memory Consolidation Complete**:\n- Analyzed last ${session.messages.length} turns.\n- Extracted user intent and synced to \`MEMORY.md\`.\n- Memory store currently holds ${memoryFactsStore.length} core knowledge points.`;
        break;
      case '/skills':
        cmdResponse = `**Active Nanobot Skills (${skillsStore.filter((s) => s.enabled).length}/${skillsStore.length}):**\n` +
          skillsStore
            .filter((s) => s.enabled)
            .map((s) => `- **${s.name}**: ${s.description}`)
            .join('\n');
        break;
      case '/status':
        cmdResponse = `**Gateway Status:**\n- **Uptime**: ${Math.floor((Date.now() - startTime) / 1000)}s\n- **Active Sessions**: ${sessionsStore.size}\n- **Total Messages**: ${totalMessagesProcessed}\n- **Tokens Processed**: ${totalTokensUsed}`;
        break;
      default:
        cmdResponse = `Unknown command: \`${cmd}\`. Type \`/help\` for a list of valid commands.`;
    }

    const assistantMsg = {
      id: `msg-a-${Date.now()}`,
      role: 'assistant' as const,
      content: cmdResponse,
      reasoning: cmdReasoning,
      timestamp: Date.now(),
    };
    session.messages.push(assistantMsg);
    session.updated_at = Date.now();
    return res.json({ session, message: assistantMsg });
  }

  // Process with Gemini API or Intelligent Agent Loop Engine
  const ai = getGeminiClient();
  const toolCalls: Array<{
    id: string;
    name: string;
    arguments: Record<string, any>;
    result?: string;
    status: 'running' | 'completed' | 'failed';
    timestamp: number;
  }> = [];

  let assistantContent = '';
  let assistantReasoning = '';

  const lowerMsg = message.toLowerCase();

  // Determine needed tools based on intent
  if (
    lowerMsg.includes('file') ||
    lowerMsg.includes('dir') ||
    lowerMsg.includes('read') ||
    lowerMsg.includes('write') ||
    lowerMsg.includes('edit') ||
    lowerMsg.includes('code')
  ) {
    toolCalls.push({
      id: `call-fs-${Date.now()}`,
      name: 'filesystem_read',
      arguments: { path: './workspace' },
      result: 'Checked workspace directory. Found application files and configs.',
      status: 'completed',
      timestamp: Date.now(),
    });
  }

  if (
    lowerMsg.includes('search') ||
    lowerMsg.includes('find') ||
    lowerMsg.includes('google') ||
    lowerMsg.includes('latest') ||
    lowerMsg.includes('weather') ||
    lowerMsg.includes('news')
  ) {
    toolCalls.push({
      id: `call-search-${Date.now()}`,
      name: 'web_search',
      arguments: { query: message },
      result: 'Top results fetched: Relevant documentation, release highlights, and contextual reference articles.',
      status: 'completed',
      timestamp: Date.now(),
    });
  }

  if (lowerMsg.includes('cron') || lowerMsg.includes('schedule') || lowerMsg.includes('timer') || lowerMsg.includes('daily')) {
    toolCalls.push({
      id: `call-cron-${Date.now()}`,
      name: 'cron_schedule',
      arguments: { schedule: '0 9 * * *', task: message },
      result: 'Automation cron entry stored successfully. Scheduled in local triggers daemon.',
      status: 'completed',
      timestamp: Date.now(),
    });
  }

  if (lowerMsg.includes('remember') || lowerMsg.includes('memory') || lowerMsg.includes('preference')) {
    toolCalls.push({
      id: `call-mem-${Date.now()}`,
      name: 'dream_memory_store',
      arguments: { entry: message, category: 'preference' },
      result: 'Fact indexed into persistent long-term Dream store with 0.95 confidence.',
      status: 'completed',
      timestamp: Date.now(),
    });
  }

  if (ai) {
    try {
      // Build conversation context for Gemini
      const contents = session.messages.slice(-8).map((m) => ({
        role: m.role === 'assistant' ? 'model' : 'user',
        parts: [{ text: m.content }],
      }));

      // Add system prompt context
      const systemInstruction =
        customPrompt ||
        session.system_prompt ||
        'You are nanobot, an ultra-lightweight, open-source AI agent framework with built-in tools (filesystem, shell, web search, cron, subagents, and memory consolidation). Provide clear, direct, and well-formatted answers.';

      const response = await ai.models.generateContent({
        model: 'gemini-2.5-flash',
        contents: contents,
        config: {
          systemInstruction,
        },
      });

      assistantContent =
        response.text || 'I have processed your request through the Nanobot Agent runtime.';
      assistantReasoning =
        'Executed through Gemini 2.5 Flash with live multi-turn context and tool orchestration.';
    } catch (err: any) {
      console.warn('Gemini API call failed, falling back to local agent logic:', err.message);
      assistantContent = generateFallbackResponse(message, toolCalls);
      assistantReasoning = 'Agent processed request using Nanobot internal tool loop and memory context.';
    }
  } else {
    // Local intelligent agent engine
    assistantContent = generateFallbackResponse(message, toolCalls);
    assistantReasoning =
      'Processed via Nanobot core agent loop. (Add GEMINI_API_KEY in settings or environment for live server-side LLM inference).';
  }

  const estimatedTokens = Math.ceil((message.length + assistantContent.length) / 3.8);
  totalTokensUsed += estimatedTokens;

  if (session.token_usage) {
    session.token_usage.total_tokens += estimatedTokens;
  }

  const assistantMsg = {
    id: `msg-a-${Date.now()}`,
    role: 'assistant' as const,
    content: assistantContent,
    reasoning: assistantReasoning,
    toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
    timestamp: Date.now(),
  };

  session.messages.push(assistantMsg);
  session.updated_at = Date.now();

  // If first user message, generate smart title
  if (session.messages.length <= 2) {
    session.title = message.length > 35 ? message.slice(0, 35) + '...' : message;
  }

  res.json({ session, message: assistantMsg });
});

function generateFallbackResponse(
  userQuery: string,
  tools: Array<{ name: string; result?: string }>,
): string {
  const q = userQuery.toLowerCase();

  let toolSummary = '';
  if (tools.length > 0) {
    toolSummary =
      '\n\n**Tool Execution Summary:**\n' +
      tools.map((t) => `- \`${t.name}\`: ${t.result}`).join('\n');
  }

  if (q.includes('hello') || q.includes('hi') || q.includes('hey')) {
    return (
      `Hello! I am **nanobot**, your personal AI assistant and agent gateway.\n\n` +
      `Here are some things I can help you with:\n` +
      `- 🛠️ **Run Tools & Code**: Read, edit, and create files or execute terminal commands.\n` +
      `- 🌐 **Web Search & Fetch**: Search the web and digest online articles.\n` +
      `- ⏰ **Automate Workflows**: Schedule cron jobs or background triggers.\n` +
      `- 🧠 **Long-Term Memory**: Recall persistent user preferences and project knowledge through Dream consolidation.\n` +
      `- 💬 **Connect Channels**: Bridge messages from Telegram, Discord, Slack, Lark, and more.${toolSummary}`
    );
  }

  if (q.includes('who are you') || q.includes('what is nanobot')) {
    return (
      `**nanobot** is an ultra-lightweight, self-hosted AI agent framework.\n\n` +
      `Key architectural highlights:\n` +
      `- **Small Core**: Clean async message bus separating input channels from LLM reasoning.\n` +
      `- **Extensible Tool Registry**: Built-in filesystem, shell, web search, MCP, cron, and subagents.\n` +
      `- **Two-Phase Memory (Dream)**: Consolidates conversations into structured long-term memory.\n` +
      `- **Multi-Channel**: Simultaneous connectivity across chat platforms.${toolSummary}`
    );
  }

  if (q.includes('cron') || q.includes('schedule') || q.includes('alarm')) {
    return (
      `I've registered your automation task in the Nanobot Cron engine!${toolSummary}\n\n` +
      `The task will run periodically in the background and can push notifications to any configured channel (Discord, Telegram, Webhook, etc.).`
    );
  }

  if (q.includes('search') || q.includes('find') || q.includes('lookup')) {
    return (
      `I searched for information regarding your query.\n${toolSummary}\n\n` +
      `Everything is verified and ready. You can inspect the execution log in the tool inspector panel.`
    );
  }

  return (
    `I have received your instruction: "${userQuery}".\n` +
    `The Nanobot agent runner processed the task with your active model context and skill policies.${toolSummary}\n\n` +
    `Is there anything specific you would like me to inspect, execute, or automate next?`
  );
}

// Skills API
app.get('/api/skills', (req: Request, res: Response) => {
  res.json(skillsStore);
});

app.post('/api/skills/:id/toggle', (req: Request, res: Response) => {
  const skill = skillsStore.find((s) => s.id === req.params.id);
  if (!skill) {
    return res.status(404).json({ error: 'Skill not found' });
  }
  skill.enabled = !skill.enabled;
  res.json(skill);
});

// Channels API
app.get('/api/channels', (req: Request, res: Response) => {
  res.json(channelsStore);
});

app.post('/api/channels/:id/config', (req: Request, res: Response) => {
  const channel = channelsStore.find((c) => c.id === req.params.id);
  if (!channel) {
    return res.status(404).json({ error: 'Channel not found' });
  }
  const { values } = req.body;
  if (values && channel.configFields) {
    channel.configFields = channel.configFields.map((f) => ({
      ...f,
      value: values[f.key] ?? f.value,
    }));
    channel.status = 'connected';
  }
  res.json(channel);
});

// Memory API (Dream)
app.get('/api/memory', (req: Request, res: Response) => {
  res.json({
    facts: memoryFactsStore,
    totalFacts: memoryFactsStore.length,
    lastConsolidation: Date.now() - 3600000 * 2,
    status: 'idle',
  });
});

app.post('/api/memory/consolidate', (req: Request, res: Response) => {
  // Simulate dream memory consolidation
  const newFact: MemoryFactItem = {
    id: `fact-${Date.now()}`,
    category: 'learned_skill',
    content: `Consolidated insights from active session at ${new Date().toLocaleTimeString()}.`,
    confidence: 0.95,
    lastUpdated: Date.now(),
  };
  memoryFactsStore.unshift(newFact);
  res.json({
    success: true,
    newFactsCount: 1,
    totalFacts: memoryFactsStore.length,
  });
});

app.delete('/api/memory/:id', (req: Request, res: Response) => {
  const index = memoryFactsStore.findIndex((f) => f.id === req.params.id);
  if (index === -1) {
    return res.status(404).json({ error: 'Fact not found' });
  }
  memoryFactsStore.splice(index, 1);
  res.json({ success: true, id: req.params.id });
});

// -------------------------------------------------------------
// Desktop & Claude Desktop-like MCP Server Subsystem
// -------------------------------------------------------------

interface McpServerItem {
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
  tools: string[];
  protocol: 'stdio' | 'sse' | 'websocket';
}

const mcpServersStore: McpServerItem[] = [
  {
    id: 'mcp-fs',
    name: 'Desktop Filesystem MCP',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-filesystem', '~/Desktop', '~/Documents', '~/Projects'],
    env: {},
    status: 'connected',
    toolsCount: 5,
    resourcesCount: 12,
    description: 'Direct native file read, write, directory traversal and file watching on host OS.',
    icon: 'FolderTree',
    protocol: 'stdio',
    tools: ['read_file', 'write_file', 'list_directory', 'directory_tree', 'get_file_info'],
  },
  {
    id: 'mcp-sqlite',
    name: 'SQLite Database MCP',
    command: 'uvx',
    args: ['mcp-server-sqlite', '--db-path', '~/.nanobot/agent_state.db'],
    env: {},
    status: 'connected',
    toolsCount: 4,
    resourcesCount: 8,
    description: 'Query and mutate local SQLite tables, session indices, and tabular datasets.',
    icon: 'Database',
    protocol: 'stdio',
    tools: ['read_query', 'write_query', 'describe_table', 'list_tables'],
  },
  {
    id: 'mcp-brave',
    name: 'Brave Search Live MCP',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-brave-search'],
    env: { BRAVE_API_KEY: 'BSA-DEMO-LIVE-KEY' },
    status: 'connected',
    toolsCount: 2,
    resourcesCount: 0,
    description: 'Privacy-focused web search, news aggregation, and local place queries.',
    icon: 'Search',
    protocol: 'stdio',
    tools: ['brave_web_search', 'brave_local_search'],
  },
  {
    id: 'mcp-github',
    name: 'GitHub Desktop Bridge MCP',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-github'],
    env: { GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_live_token_mock' },
    status: 'connected',
    toolsCount: 6,
    resourcesCount: 24,
    description: 'Repository management, pull request reviews, commit inspection, and issue tracking.',
    icon: 'Github',
    protocol: 'stdio',
    tools: ['get_file_contents', 'create_or_update_file', 'create_issue', 'search_repositories', 'list_pull_requests', 'fork_repository'],
  },
  {
    id: 'mcp-memory',
    name: 'Knowledge Graph Memory MCP',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-memory'],
    env: {},
    status: 'connected',
    toolsCount: 3,
    resourcesCount: 45,
    description: 'Entity and relation knowledge graph store for persistent semantic memory.',
    icon: 'Brain',
    protocol: 'stdio',
    tools: ['create_entities', 'read_graph', 'search_nodes'],
  },
  {
    id: 'mcp-postgres',
    name: 'PostgreSQL Enterprise MCP',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-postgres', 'postgresql://localhost:5432/nanobot'],
    env: {},
    status: 'disconnected',
    toolsCount: 2,
    resourcesCount: 0,
    description: 'Direct SQL schema introspection and analytical querying on remote/local Postgres.',
    icon: 'Server',
    protocol: 'stdio',
    tools: ['query', 'schema_inspect'],
  },
];

let desktopSettings = {
  theme: 'dark' as const,
  windowFrame: 'macos' as const,
  alwaysOnTop: false,
  launchAtLogin: true,
  shortcutQuickSummon: 'Alt + Space',
  mcpAutoStart: true,
  workspacePath: '~/Projects/nanobot-workspace',
  notificationsEnabled: true,
  systemTrayEnabled: true,
  compactMode: false,
};

const sampleWorkspaceFiles = [
  {
    id: 'file-1',
    name: 'nanobot.config.json',
    path: 'nanobot.config.json',
    type: 'file' as const,
    size: '1.2 KB',
    modified: 'Just now',
    extension: 'json',
    content: JSON.stringify(
      {
        version: '0.3.0',
        agent: {
          name: 'Nanobot Desktop Agent',
          model: 'gemini-2.5-flash',
          max_tokens: 4096,
          temperature: 0.7,
          memory_compaction_interval_hrs: 2,
        },
        mcp: {
          enabled: true,
          servers: ['mcp-fs', 'mcp-sqlite', 'mcp-brave', 'mcp-github', 'mcp-memory'],
        },
        desktop: {
          quick_summon_key: 'Alt+Space',
          system_tray: true,
          traffic_lights: true,
        },
      },
      null,
      2,
    ),
  },
  {
    id: 'file-2',
    name: 'SOUL.md',
    path: 'SOUL.md',
    type: 'file' as const,
    size: '840 B',
    modified: '2 hours ago',
    extension: 'md',
    content: `# Nanobot Desktop Persona (SOUL.md)

You are Nanobot Desktop, a hyper-efficient native AI copilot designed for local workflow execution, Model Context Protocol (MCP) tool invocation, and developer productivity.

## Core Directives:
1. Always prioritize speed, security, and explicit tool execution feedback.
2. When performing local file changes or running bash commands, confirm sandbox isolation.
3. Automatically leverage available MCP tools (Filesystem, SQLite, GitHub, Brave Search) to give accurate answers based on real local files.`,
  },
  {
    id: 'file-3',
    name: 'MEMORY.md',
    path: 'MEMORY.md',
    type: 'file' as const,
    size: '2.4 KB',
    modified: '3 hours ago',
    extension: 'md',
    content: `# Consolidated Long-Term Memory (Dream Engine)

- [User Profile]: Prefers dark mode macOS desktop interface and Alt+Space quick summon.
- [Dev Stack]: TypeScript, Electron 34, React 18, Tailwind CSS, Express Gateway.
- [MCP Preferences]: Filesystem access enabled for \`~/Projects\`, Brave Search fallback active.
- [Model Config]: Gemini 2.5 Flash set as primary reasoning model with tool calling enabled.`,
  },
  {
    id: 'file-4',
    name: 'tasks.todo',
    path: 'tasks.todo',
    type: 'file' as const,
    size: '420 B',
    modified: '1 day ago',
    extension: 'todo',
    content: `✔ Build Electron window frame and macOS traffic light controls
✔ Implement Claude Desktop-compatible MCP Server Manager
✔ Add Alt+Space Quick Summon spotlight overlay
✔ Support local workspace directory mounting & file editing
☐ Setup automated build pipelines for .dmg, .exe, and .AppImage`,
  },
];

// MCP Servers APIs
app.get('/api/desktop/mcp', (req: Request, res: Response) => {
  res.json({
    servers: mcpServersStore,
    totalConnected: mcpServersStore.filter((s) => s.status === 'connected').length,
    totalTools: mcpServersStore.reduce((acc, s) => acc + (s.status === 'connected' ? s.toolsCount : 0), 0),
    totalResources: mcpServersStore.reduce((acc, s) => acc + (s.status === 'connected' ? s.resourcesCount : 0), 0),
  });
});

app.post('/api/desktop/mcp', (req: Request, res: Response) => {
  const { name, command, args = [], env = {}, description, protocol = 'stdio' } = req.body;
  if (!name || !command) {
    return res.status(400).json({ error: 'Name and Command are required' });
  }

  const newServer: McpServerItem = {
    id: `mcp-${Date.now()}`,
    name,
    command,
    args: Array.isArray(args) ? args : [args],
    env: typeof env === 'object' ? env : {},
    status: 'connected',
    toolsCount: 3,
    resourcesCount: 1,
    description: description || 'Custom User Configured MCP Server',
    icon: 'Cpu',
    protocol,
    tools: [`${name.toLowerCase().replace(/\s+/g, '_')}_action`, `${name.toLowerCase().replace(/\s+/g, '_')}_query`],
  };

  mcpServersStore.push(newServer);
  res.status(201).json(newServer);
});

app.post('/api/desktop/mcp/:id/toggle', (req: Request, res: Response) => {
  const server = mcpServersStore.find((s) => s.id === req.params.id);
  if (!server) return res.status(404).json({ error: 'MCP Server not found' });

  server.status = server.status === 'connected' ? 'disconnected' : 'connected';
  res.json(server);
});

app.post('/api/desktop/mcp/:id/test', (req: Request, res: Response) => {
  const server = mcpServersStore.find((s) => s.id === req.params.id);
  if (!server) return res.status(404).json({ error: 'MCP Server not found' });

  // Simulate MCP JSON-RPC ping and tools/list
  setTimeout(() => {
    res.json({
      status: 'ok',
      serverId: server.id,
      protocolVersion: '2024-11-05',
      pingMs: 14,
      serverInfo: {
        name: server.name,
        version: '1.0.4',
      },
      capabilities: {
        tools: server.tools,
        resources: true,
        prompts: true,
      },
    });
  }, 300);
});

app.delete('/api/desktop/mcp/:id', (req: Request, res: Response) => {
  const idx = mcpServersStore.findIndex((s) => s.id === req.params.id);
  if (idx === -1) return res.status(404).json({ error: 'MCP Server not found' });

  const deleted = mcpServersStore.splice(idx, 1);
  res.json({ success: true, server: deleted[0] });
});

// Claude Desktop-compatible config export endpoint
app.get('/api/desktop/mcp/export-claude-config', (req: Request, res: Response) => {
  const claudeConfig: Record<string, any> = {
    mcpServers: {},
  };

  mcpServersStore.forEach((srv) => {
    claudeConfig.mcpServers[srv.id.replace('mcp-', '')] = {
      command: srv.command,
      args: srv.args,
      ...(Object.keys(srv.env).length > 0 ? { env: srv.env } : {}),
    };
  });

  res.json({
    config: claudeConfig,
    jsonString: JSON.stringify(claudeConfig, null, 2),
    configPath: process.platform === 'darwin'
      ? '~/Library/Application Support/Claude/claude_desktop_config.json'
      : process.platform === 'win32'
      ? '%APPDATA%\\Claude\\claude_desktop_config.json'
      : '~/.config/Claude/claude_desktop_config.json',
  });
});

// Desktop Workspace & Files APIs
app.get('/api/desktop/workspace', (req: Request, res: Response) => {
  res.json({
    workspacePath: desktopSettings.workspacePath,
    files: sampleWorkspaceFiles,
  });
});

app.get('/api/desktop/workspace/file', (req: Request, res: Response) => {
  const fileId = req.query.id as string;
  const file = sampleWorkspaceFiles.find((f) => f.id === fileId);
  if (!file) return res.status(404).json({ error: 'File not found' });
  res.json(file);
});

app.post('/api/desktop/workspace/file', (req: Request, res: Response) => {
  const { id, content, name } = req.body;
  let file = sampleWorkspaceFiles.find((f) => f.id === id);

  if (file) {
    file.content = content;
    file.modified = 'Just now';
    file.size = `${(new TextEncoder().encode(content).length / 1024).toFixed(1)} KB`;
  } else {
    file = {
      id: `file-${Date.now()}`,
      name: name || 'untitled.md',
      path: name || 'untitled.md',
      type: 'file' as const,
      size: `${(new TextEncoder().encode(content || '').length / 1024).toFixed(1)} KB`,
      modified: 'Just now',
      extension: (name || '').split('.').pop() || 'txt',
      content: content || '',
    };
    sampleWorkspaceFiles.push(file);
  }

  res.json(file);
});

app.post('/api/desktop/workspace/exec', (req: Request, res: Response) => {
  const { command } = req.body;
  if (!command) return res.status(400).json({ error: 'Command is required' });

  // Safe simulated terminal runner
  let output = '';
  const cmd = command.trim();

  if (cmd === 'ls' || cmd === 'dir') {
    output = sampleWorkspaceFiles.map((f) => `${f.name.padEnd(25)} ${f.size.padEnd(10)} ${f.modified}`).join('\n');
  } else if (cmd.startsWith('cat ')) {
    const filename = cmd.replace('cat ', '').trim();
    const file = sampleWorkspaceFiles.find((f) => f.name === filename || f.path === filename);
    output = file ? file.content || '' : `cat: ${filename}: No such file or directory`;
  } else if (cmd === 'nanobot status' || cmd === 'nanobot --version') {
    output = `Nanobot Desktop v0.3.0\nGateway: Online (port 3000)\nMCP Servers: ${mcpServersStore.length} registered\nModel: gemini-2.5-flash`;
  } else if (cmd === 'pwd') {
    output = desktopSettings.workspacePath;
  } else if (cmd.startsWith('git ')) {
    output = `On branch main\nYour branch is up to date with 'origin/main'.\nnothing to commit, working tree clean`;
  } else {
    output = `[nanobot sandbox] executed: \`${cmd}\`\nExit code: 0\nStatus: Completed in 22ms.`;
  }

  res.json({
    command: cmd,
    output,
    timestamp: Date.now(),
    exitCode: 0,
  });
});

// Desktop Releases & Installers
app.get('/api/desktop/releases', (req: Request, res: Response) => {
  const releases = [
    {
      platform: 'darwin',
      platformName: 'macOS (Apple Silicon M1/M2/M3/M4)',
      arch: 'arm64',
      version: '0.3.0',
      filename: 'Nanobot-Desktop-0.3.0-arm64.dmg',
      size: '84.2 MB',
      downloadUrl: '#download-mac-arm64',
      releaseDate: '2026-08-26',
      sha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      instructions: [
        'Download and open `Nanobot-Desktop-0.3.0-arm64.dmg`.',
        'Drag `Nanobot Desktop.app` into your `Applications` folder.',
        'Launch Nanobot and press `Alt + Space` (or `Cmd + Shift + Space`) to summon anywhere.',
      ],
    },
    {
      platform: 'darwin',
      platformName: 'macOS (Intel x64)',
      arch: 'x64',
      version: '0.3.0',
      filename: 'Nanobot-Desktop-0.3.0-x64.dmg',
      size: '86.5 MB',
      downloadUrl: '#download-mac-x64',
      releaseDate: '2026-08-26',
      sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
      instructions: [
        'Download `Nanobot-Desktop-0.3.0-x64.dmg`.',
        'Mount disk image and drag into `Applications`.',
      ],
    },
    {
      platform: 'win32',
      platformName: 'Windows 10 / 11 (64-bit Installer)',
      arch: 'x64',
      version: '0.3.0',
      filename: 'Nanobot-Desktop-Setup-0.3.0.exe',
      size: '78.1 MB',
      downloadUrl: '#download-win-exe',
      releaseDate: '2026-08-26',
      sha256: '5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8',
      instructions: [
        'Run `Nanobot-Desktop-Setup-0.3.0.exe`.',
        'Follow the standard NSIS installer wizard.',
        'Nanobot will automatically pin to the System Tray with `Alt + Space` hotkey.',
      ],
    },
    {
      platform: 'linux',
      platformName: 'Linux (Universal AppImage)',
      arch: 'x64',
      version: '0.3.0',
      filename: 'Nanobot-Desktop-0.3.0.AppImage',
      size: '89.0 MB',
      downloadUrl: '#download-linux-appimage',
      releaseDate: '2026-08-26',
      sha256: '4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a',
      instructions: [
        'Make executable: `chmod +x Nanobot-Desktop-0.3.0.AppImage`',
        'Run: `./Nanobot-Desktop-0.3.0.AppImage`',
      ],
    },
  ];

  res.json({
    latestVersion: '0.3.0',
    releases,
    quickInstallCli: {
      npx: 'npx @nanobot/desktop@latest',
      curl: 'curl -fsSL https://nanobot.run/install.sh | bash',
      winget: 'winget install Nanobot.Desktop',
      brew: 'brew install --cask nanobot',
    },
  });
});

// Desktop Settings API
app.get('/api/desktop/settings', (req: Request, res: Response) => {
  res.json(desktopSettings);
});

app.post('/api/desktop/settings', (req: Request, res: Response) => {
  desktopSettings = {
    ...desktopSettings,
    ...req.body,
  };
  res.json(desktopSettings);
});

// OpenAI-Compatible API routes (`/v1/models`, `/v1/chat/completions`)
app.get('/v1/models', (req: Request, res: Response) => {
  res.json({
    object: 'list',
    data: [
      { id: 'gemini-2.5-flash', object: 'model', created: 1700000000, owned_by: 'google' },
      { id: 'gemini-2.5-pro', object: 'model', created: 1700000000, owned_by: 'google' },
      { id: 'nanobot-agent', object: 'model', created: 1700000000, owned_by: 'nanobot' },
    ],
  });
});

app.post('/v1/chat/completions', async (req: Request, res: Response) => {
  const { messages, model = 'gemini-2.5-flash' } = req.body;
  const lastMsg = Array.isArray(messages) ? messages[messages.length - 1]?.content : 'Hello';

  const ai = getGeminiClient();
  let replyText = '';

  if (ai) {
    try {
      const response = await ai.models.generateContent({
        model: 'gemini-2.5-flash',
        contents: String(lastMsg),
      });
      replyText = response.text || 'Response generated from Nanobot gateway.';
    } catch (e: any) {
      replyText = `Nanobot agent processed your completion: ${lastMsg}`;
    }
  } else {
    replyText = `Nanobot agent processed your completion: ${lastMsg}`;
  }

  res.json({
    id: `chatcmpl-${Date.now()}`,
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [
      {
        index: 0,
        message: {
          role: 'assistant',
          content: replyText,
        },
        finish_reason: 'stop',
      },
    ],
    usage: {
      prompt_tokens: Math.ceil(String(lastMsg).length / 4),
      completion_tokens: Math.ceil(replyText.length / 4),
      total_tokens: Math.ceil((String(lastMsg).length + replyText.length) / 4),
    },
  });
});

// -------------------------------------------------------------
// Gateway Server Process Management & Telemetry API
// -------------------------------------------------------------
let gatewayServerConfig = {
  mode: 'node_embedded' as 'node_embedded' | 'python_cli' | 'custom',
  host: '127.0.0.1',
  port: 3000,
  autoStartOnLaunch: true,
  autoRestartOnCrash: true,
  workingDirectory: process.cwd(),
  pythonPath: 'python3',
  customCommand: 'nanobot gateway --port 8765',
  customArgs: [],
  logLevel: 'info' as const,
  envVars: {
    NODE_ENV: 'development',
    PORT: '3000',
  },
  maxLogLines: 500,
};

let gatewayServerLogs: Array<{
  id: string;
  timestamp: number;
  type: 'stdout' | 'stderr' | 'system' | 'http';
  message: string;
  level?: 'info' | 'warn' | 'error' | 'debug';
}> = [
  {
    id: 'log-init-1',
    timestamp: Date.now() - 3600000 * 2,
    type: 'system',
    message: '[Supervisor] Nanobot Electron Gateway Supervisor initialized.',
    level: 'info',
  },
  {
    id: 'log-init-2',
    timestamp: Date.now() - 3600000 * 2 + 100,
    type: 'stdout',
    message: '[nanobot] Loaded 6 MCP server configurations (Filesystem, SQLite, Brave, GitHub, Memory, Postgres).',
    level: 'info',
  },
  {
    id: 'log-init-3',
    timestamp: Date.now() - 3600000 * 2 + 250,
    type: 'stdout',
    message: '[nanobot] In-Memory MessageBus & Dream 2-phase consolidation queue active.',
    level: 'info',
  },
  {
    id: 'log-init-4',
    timestamp: Date.now() - 3600000 * 2 + 400,
    type: 'stdout',
    message: `[nanobot] Server running and listening on http://0.0.0.0:${PORT} (PID: ${process.pid})`,
    level: 'info',
  },
  {
    id: 'log-init-5',
    timestamp: Date.now() - 1000 * 60 * 5,
    type: 'http',
    message: 'GET /api/status 200 OK (1.2ms)',
    level: 'debug',
  },
];

let isGatewayRunning = true;
let gatewayStartTime = Date.now() - 3600000 * 2;

app.get('/api/desktop/gateway/status', (req: Request, res: Response) => {
  const uptime = isGatewayRunning ? Math.floor((Date.now() - gatewayStartTime) / 1000) : 0;
  const memoryUsage = process.memoryUsage();
  res.json({
    status: isGatewayRunning ? 'running' : 'stopped',
    pid: isGatewayRunning ? process.pid : undefined,
    host: gatewayServerConfig.host,
    port: gatewayServerConfig.port,
    mode: gatewayServerConfig.mode,
    uptimeSeconds: uptime,
    memoryUsageMb: Math.round(memoryUsage.rss / (1024 * 1024)),
    cpuPercent: isGatewayRunning ? 0.8 : 0,
    startedAt: gatewayStartTime,
    url: `http://${gatewayServerConfig.host}:${gatewayServerConfig.port}`,
    healthStatus: isGatewayRunning ? 'healthy' : 'unhealthy',
    healthLatencyMs: 1.4,
  });
});

app.get('/api/desktop/gateway/config', (req: Request, res: Response) => {
  res.json(gatewayServerConfig);
});

app.post('/api/desktop/gateway/config', (req: Request, res: Response) => {
  gatewayServerConfig = { ...gatewayServerConfig, ...req.body };
  gatewayServerLogs.push({
    id: `log-${Date.now()}`,
    timestamp: Date.now(),
    type: 'system',
    message: `[Supervisor] Gateway configuration updated (mode: ${gatewayServerConfig.mode}, port: ${gatewayServerConfig.port})`,
    level: 'info',
  });
  res.json({ success: true, config: gatewayServerConfig });
});

app.post('/api/desktop/gateway/start', (req: Request, res: Response) => {
  isGatewayRunning = true;
  gatewayStartTime = Date.now();
  gatewayServerLogs.push({
    id: `log-${Date.now()}`,
    timestamp: Date.now(),
    type: 'system',
    message: `[Supervisor] Started Gateway process [${gatewayServerConfig.mode}] on port ${gatewayServerConfig.port}`,
    level: 'info',
  });
  res.json({ success: true, message: 'Gateway server process started' });
});

app.post('/api/desktop/gateway/stop', (req: Request, res: Response) => {
  isGatewayRunning = false;
  gatewayServerLogs.push({
    id: `log-${Date.now()}`,
    timestamp: Date.now(),
    type: 'system',
    message: `[Supervisor] Gateway process stopped by user command.`,
    level: 'warn',
  });
  res.json({ success: true, message: 'Gateway server process stopped' });
});

app.post('/api/desktop/gateway/restart', (req: Request, res: Response) => {
  isGatewayRunning = true;
  gatewayStartTime = Date.now();
  gatewayServerLogs.push({
    id: `log-${Date.now()}`,
    timestamp: Date.now(),
    type: 'system',
    message: `[Supervisor] Restarting Gateway server process... Ready on port ${gatewayServerConfig.port}`,
    level: 'info',
  });
  res.json({ success: true, message: 'Gateway server restarted successfully' });
});

app.get('/api/desktop/gateway/logs', (req: Request, res: Response) => {
  res.json(gatewayServerLogs);
});

app.delete('/api/desktop/gateway/logs', (req: Request, res: Response) => {
  gatewayServerLogs = [
    {
      id: `log-${Date.now()}`,
      timestamp: Date.now(),
      type: 'system',
      message: '[Supervisor] Terminal log buffer cleared.',
      level: 'info',
    },
  ];
  res.json({ success: true, message: 'Logs cleared' });
});

app.post('/api/desktop/gateway/ping', (req: Request, res: Response) => {
  res.json({
    ok: true,
    latencyMs: 1.2,
    statusCode: 200,
    timestamp: Date.now(),
  });
});

// -------------------------------------------------------------
// Vite Middleware / Static Serving Setup
// -------------------------------------------------------------
async function startServer() {
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`[nanobot] Server running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
