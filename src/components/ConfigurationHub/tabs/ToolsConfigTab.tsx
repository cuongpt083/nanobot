import React, { useState } from 'react';
import {
  Wrench,
  Shield,
  Search,
  Cpu,
  Plus,
  Trash2,
  CheckCircle2,
  AlertCircle,
  FolderLock,
  Terminal,
  Globe,
  Image as ImageIcon,
  Mic,
  Key,
  Layers,
  Sparkles,
  RefreshCw
} from 'lucide-react';
import { NanobotFullConfig } from '../../../types';

interface ToolsConfigTabProps {
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => void;
}

const MCP_PRESETS = [
  {
    name: 'GitHub MCP Server',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-github'],
    env: { GITHUB_PERSONAL_ACCESS_TOKEN: '${GITHUB_TOKEN}' },
    description: 'Inspect repositories, issues, branches, and PRs directly from agent turns.',
  },
  {
    name: 'PostgreSQL / SQL MCP',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-postgres', 'postgresql://localhost/nanobot'],
    env: {},
    description: 'Query database schemas, inspect tables, and run read-only analytical SQL.',
  },
  {
    name: 'Playwright Headless Browser',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-puppeteer'],
    env: {},
    description: 'Render complex client-side dynamic websites, take screenshots, and extract DOM.',
  },
  {
    name: 'Memory Knowledge Graph MCP',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-memory'],
    env: {},
    description: 'Persistent knowledge graph store with entity relations and graph traversal.',
  },
];

export const ToolsConfigTab: React.FC<ToolsConfigTabProps> = ({
  config,
  onUpdateConfig,
}) => {
  const tools = config.tools || {
    restrictToWorkspace: true,
    exec: { sandbox: 'strict', timeoutS: 30, allowedCommands: [], blockedCommands: [] },
    web: { search: { provider: 'brave', apiKey: '', maxResults: 5 }, fetch: { timeoutS: 15 } },
    mcpServers: {},
  };

  const [activeSubSection, setActiveSubSection] = useState<'sandbox' | 'web' | 'mcp' | 'media'>('sandbox');
  const [newMcpServerName, setNewMcpServerName] = useState<string>('');
  const [newMcpCommand, setNewMcpCommand] = useState<string>('');
  const [newMcpArgs, setNewMcpArgs] = useState<string>('');

  const mcpServers = tools.mcpServers || {};

  const handleUpdateTools = (partialTools: any) => {
    onUpdateConfig({
      tools: {
        ...tools,
        ...partialTools,
      },
    });
  };

  const handleAddMcpServer = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMcpServerName || !newMcpCommand) return;

    const serverKey = newMcpServerName.toLowerCase().replace(/[^a-z0-9_]/g, '_');
    const argsArray = newMcpArgs.split(' ').filter(Boolean);

    const updatedMcp = {
      ...mcpServers,
      [serverKey]: {
        command: newMcpCommand,
        args: argsArray,
        env: {},
      },
    };

    handleUpdateTools({ mcpServers: updatedMcp });
    setNewMcpServerName('');
    setNewMcpCommand('');
    setNewMcpArgs('');
  };

  const handleAddPresetMcp = (preset: (typeof MCP_PRESETS)[0]) => {
    const serverKey = preset.name.toLowerCase().replace(/[^a-z0-9_]/g, '_');
    const updatedMcp = {
      ...mcpServers,
      [serverKey]: {
        command: preset.command,
        args: preset.args,
        env: preset.env,
      },
    };
    handleUpdateTools({ mcpServers: updatedMcp });
  };

  const handleDeleteMcp = (key: string) => {
    const updated = { ...mcpServers };
    delete updated[key];
    handleUpdateTools({ mcpServers: updated });
  };

  return (
    <div className="flex flex-col h-full space-y-4 text-zinc-300">
      {/* Sub Tabs */}
      <div className="flex items-center gap-2 border-b border-zinc-800 pb-3">
        <button
          onClick={() => setActiveSubSection('sandbox')}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer flex items-center gap-1.5 ${
            activeSubSection === 'sandbox'
              ? 'bg-amber-500 text-zinc-950 font-bold'
              : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
          }`}
        >
          <FolderLock className="w-3.5 h-3.5" />
          <span>Workspace & Sandbox</span>
        </button>

        <button
          onClick={() => setActiveSubSection('web')}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer flex items-center gap-1.5 ${
            activeSubSection === 'web'
              ? 'bg-amber-500 text-zinc-950 font-bold'
              : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
          }`}
        >
          <Search className="w-3.5 h-3.5" />
          <span>Web Search & Scraping</span>
        </button>

        <button
          onClick={() => setActiveSubSection('mcp')}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer flex items-center gap-1.5 ${
            activeSubSection === 'mcp'
              ? 'bg-amber-500 text-zinc-950 font-bold'
              : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
          }`}
        >
          <Cpu className="w-3.5 h-3.5" />
          <span>MCP Servers ({Object.keys(mcpServers).length})</span>
        </button>

        <button
          onClick={() => setActiveSubSection('media')}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer flex items-center gap-1.5 ${
            activeSubSection === 'media'
              ? 'bg-amber-500 text-zinc-950 font-bold'
              : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
          }`}
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span>Image & Audio Transcription</span>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto pr-1">
        {activeSubSection === 'sandbox' && (
          <div className="space-y-5 max-w-2xl">
            {/* Workspace Restriction */}
            <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="p-2 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    <FolderLock className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-xs font-bold text-zinc-100">Restrict File Ops to Workspace Root</h4>
                    <p className="text-[11px] text-zinc-400">
                      When enabled, agent filesystem tools cannot read or mutate files outside the current project root directory.
                    </p>
                  </div>
                </div>

                <button
                  onClick={() =>
                    handleUpdateTools({ restrictToWorkspace: !tools.restrictToWorkspace })
                  }
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                    tools.restrictToWorkspace ? 'bg-amber-500' : 'bg-zinc-800'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-zinc-950 transition-transform ${
                      tools.restrictToWorkspace ? 'translate-x-4.5' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>
            </div>

            {/* Shell Sandbox Policy */}
            <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 space-y-4">
              <div className="flex items-center gap-2">
                <Terminal className="w-4 h-4 text-emerald-400" />
                <h4 className="text-xs font-bold text-zinc-100">Execution Sandbox Policy</h4>
              </div>

              <div className="grid grid-cols-2 gap-3">
                {[
                  {
                    id: 'strict',
                    name: 'Strict Sandbox',
                    desc: 'Restricted commands, blocks destructive patterns (rm -rf, mkfs, dd).',
                  },
                  {
                    id: 'permissive',
                    name: 'Permissive Developer',
                    desc: 'Allows general dev commands with interactive approval on high risk.',
                  },
                  {
                    id: 'tempdir',
                    name: 'Isolated Temp Directory',
                    desc: 'Executes commands inside an isolated disposable temporary folder.',
                  },
                  {
                    id: 'container',
                    name: 'Docker Container Backend',
                    desc: 'Routes all shell execution into a disposable container instance.',
                  },
                ].map((mode) => (
                  <button
                    key={mode.id}
                    onClick={() =>
                      handleUpdateTools({
                        exec: {
                          ...tools.exec,
                          sandbox: mode.id,
                        },
                      })
                    }
                    className={`p-3 text-left rounded-xl border transition-all cursor-pointer ${
                      tools.exec?.sandbox === mode.id
                        ? 'bg-amber-500/10 border-amber-500 text-amber-300 font-medium'
                        : 'bg-zinc-900/60 border-zinc-800 hover:border-zinc-700 text-zinc-300'
                    }`}
                  >
                    <div className="text-xs font-bold">{mode.name}</div>
                    <div className="text-[10px] text-zinc-400 mt-1">{mode.desc}</div>
                  </button>
                ))}
              </div>

              <div className="space-y-1.5 pt-2">
                <label className="text-xs font-semibold text-zinc-200">Execution Timeout (Seconds)</label>
                <input
                  type="number"
                  value={tools.exec?.timeoutS || 30}
                  onChange={(e) =>
                    handleUpdateTools({
                      exec: {
                        ...tools.exec,
                        timeoutS: Number(e.target.value),
                      },
                    })
                  }
                  className="w-full max-w-xs bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>
            </div>
          </div>
        )}

        {activeSubSection === 'web' && (
          <div className="space-y-4 max-w-2xl">
            <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 space-y-4">
              <div className="flex items-center gap-2">
                <Search className="w-4 h-4 text-sky-400" />
                <h4 className="text-xs font-bold text-zinc-100">Web Search Engine Provider</h4>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Search Engine Provider</label>
                <select
                  value={tools.web?.search?.provider || 'brave'}
                  onChange={(e) =>
                    handleUpdateTools({
                      web: {
                        ...tools.web,
                        search: {
                          ...tools.web?.search,
                          provider: e.target.value as any,
                        },
                      },
                    })
                  }
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200"
                >
                  <option value="brave">Brave Search API (Recommended for structured snippets)</option>
                  <option value="duckduckgo">DuckDuckGo (Free, no API key required)</option>
                  <option value="tavily">Tavily AI Search (Built for AI Agents)</option>
                  <option value="perplexity">Perplexity Sonar Search</option>
                  <option value="jina">Jina Search & Reader</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-zinc-200 flex items-center gap-1">
                    <Key className="w-3 h-3 text-amber-400" />
                    <span>Search Engine API Key</span>
                  </label>
                  <span className="text-[10px] text-zinc-500 font-mono">Supports ${'{BRAVE_API_KEY}'}</span>
                </div>
                <input
                  type="password"
                  value={tools.web?.search?.apiKey || ''}
                  onChange={(e) =>
                    handleUpdateTools({
                      web: {
                        ...tools.web,
                        search: {
                          ...tools.web?.search,
                          apiKey: e.target.value,
                        },
                      },
                    })
                  }
                  placeholder="e.g. BSA... or ${BRAVE_API_KEY}"
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">Max Search Results</label>
                <input
                  type="number"
                  value={tools.web?.search?.maxResults || 5}
                  onChange={(e) =>
                    handleUpdateTools({
                      web: {
                        ...tools.web,
                        search: {
                          ...tools.web?.search,
                          maxResults: Number(e.target.value),
                        },
                      },
                    })
                  }
                  className="w-full max-w-xs bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>
            </div>
          </div>
        )}

        {activeSubSection === 'mcp' && (
          <div className="space-y-5">
            {/* Quick Presets */}
            <div className="space-y-2">
              <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                Quick-Add Popular MCP Servers
              </div>
              <div className="grid grid-cols-2 gap-3">
                {MCP_PRESETS.map((preset) => (
                  <div
                    key={preset.name}
                    className="p-3 rounded-xl bg-zinc-950/60 border border-zinc-800/80 flex items-center justify-between gap-3"
                  >
                    <div>
                      <div className="text-xs font-bold text-zinc-200">{preset.name}</div>
                      <div className="text-[10px] text-zinc-400 mt-0.5">{preset.description}</div>
                    </div>
                    <button
                      onClick={() => handleAddPresetMcp(preset)}
                      className="px-2.5 py-1.5 rounded-lg bg-zinc-800 hover:bg-amber-500 hover:text-zinc-950 text-zinc-300 text-xs font-semibold transition-colors cursor-pointer flex-shrink-0"
                    >
                      + Add
                    </button>
                  </div>
                ))}
              </div>
            </div>

            {/* Custom MCP Server Form */}
            <form
              onSubmit={handleAddMcpServer}
              className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 space-y-3"
            >
              <div className="text-xs font-bold text-zinc-100 flex items-center gap-1.5">
                <Plus className="w-3.5 h-3.5 text-amber-400" />
                <span>Add Custom MCP Server</span>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <input
                  type="text"
                  required
                  placeholder="Server Key / Name (e.g. sqlite)"
                  value={newMcpServerName}
                  onChange={(e) => setNewMcpServerName(e.target.value)}
                  className="bg-zinc-900 border border-zinc-800 rounded-lg p-2 text-xs text-zinc-200"
                />
                <input
                  type="text"
                  required
                  placeholder="Command (e.g. npx or python3)"
                  value={newMcpCommand}
                  onChange={(e) => setNewMcpCommand(e.target.value)}
                  className="bg-zinc-900 border border-zinc-800 rounded-lg p-2 text-xs font-mono text-zinc-200"
                />
                <input
                  type="text"
                  placeholder="Arguments (e.g. -y @mcp/sqlite ./db.sqlite)"
                  value={newMcpArgs}
                  onChange={(e) => setNewMcpArgs(e.target.value)}
                  className="bg-zinc-900 border border-zinc-800 rounded-lg p-2 text-xs font-mono text-zinc-200"
                />
              </div>
              <div className="flex justify-end">
                <button
                  type="submit"
                  className="px-3.5 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-bold cursor-pointer"
                >
                  Register MCP Server
                </button>
              </div>
            </form>

            {/* Configured MCP Servers List */}
            <div className="space-y-2">
              <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                Active MCP Servers ({Object.keys(mcpServers).length})
              </div>
              {Object.keys(mcpServers).length === 0 ? (
                <div className="p-6 text-center text-xs text-zinc-500 rounded-xl bg-zinc-950/40 border border-zinc-800">
                  No Model Context Protocol servers configured.
                </div>
              ) : (
                Object.entries(mcpServers).map(([key, server]) => (
                  <div
                    key={key}
                    className="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800 flex items-center justify-between"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-xs shadow-emerald-400/50" />
                      <div>
                        <div className="text-xs font-bold text-zinc-200">{key}</div>
                        <div className="text-[10px] font-mono text-zinc-400 mt-0.5">
                          {server.command} {server.args?.join(' ')}
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={() => handleDeleteMcp(key)}
                      className="p-1.5 rounded-lg hover:bg-rose-950 text-zinc-500 hover:text-rose-400 transition-colors"
                      title="Delete MCP Server"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {activeSubSection === 'media' && (
          <div className="space-y-4 max-w-2xl">
            {/* Image Generation */}
            <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ImageIcon className="w-4 h-4 text-pink-400" />
                  <h4 className="text-xs font-bold text-zinc-100">Image Generation Capability</h4>
                </div>
                <button
                  onClick={() =>
                    handleUpdateTools({
                      imageGeneration: {
                        ...tools.imageGeneration,
                        enabled: !tools.imageGeneration?.enabled,
                      },
                    })
                  }
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                    tools.imageGeneration?.enabled ? 'bg-amber-500' : 'bg-zinc-800'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-zinc-950 transition-transform ${
                      tools.imageGeneration?.enabled ? 'translate-x-4.5' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-zinc-200">Image Provider</label>
                  <select
                    value={tools.imageGeneration?.provider || 'gemini'}
                    onChange={(e) =>
                      handleUpdateTools({
                        imageGeneration: {
                          ...tools.imageGeneration,
                          provider: e.target.value,
                        },
                      })
                    }
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200"
                  >
                    <option value="gemini">Google Imagen 3</option>
                    <option value="openai">OpenAI DALL-E 3</option>
                    <option value="flux">Black Forest Labs Flux</option>
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-zinc-200">Model ID</label>
                  <input
                    type="text"
                    value={tools.imageGeneration?.model || 'imagen-3.0-generate-002'}
                    onChange={(e) =>
                      handleUpdateTools({
                        imageGeneration: {
                          ...tools.imageGeneration,
                          model: e.target.value,
                        },
                      })
                    }
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                  />
                </div>
              </div>
            </div>

            {/* Audio Transcription */}
            <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Mic className="w-4 h-4 text-emerald-400" />
                  <h4 className="text-xs font-bold text-zinc-100">Audio Transcription (Whisper)</h4>
                </div>
                <button
                  onClick={() =>
                    onUpdateConfig({
                      transcription: {
                        ...config.transcription,
                        enabled: !config.transcription?.enabled,
                        provider: config.transcription?.provider || 'whisper',
                      },
                    })
                  }
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                    config.transcription?.enabled ? 'bg-amber-500' : 'bg-zinc-800'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-zinc-950 transition-transform ${
                      config.transcription?.enabled ? 'translate-x-4.5' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-zinc-200">Transcription Engine</label>
                  <select
                    value={config.transcription?.provider || 'whisper'}
                    onChange={(e) =>
                      onUpdateConfig({
                        transcription: {
                          ...config.transcription,
                          provider: e.target.value as any,
                          enabled: true,
                        },
                      })
                    }
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200"
                  >
                    <option value="whisper">OpenAI Whisper-1</option>
                    <option value="groq">Groq Whisper Large v3 (Ultra-fast)</option>
                    <option value="gemini">Google Gemini Audio</option>
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-zinc-200">Language Detection</label>
                  <input
                    type="text"
                    value={config.transcription?.language || 'auto'}
                    onChange={(e) =>
                      onUpdateConfig({
                        transcription: {
                          ...config.transcription,
                          language: e.target.value,
                          enabled: true,
                          provider: config.transcription?.provider || 'whisper',
                        },
                      })
                    }
                    placeholder="auto or en, vi, es, fr"
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                  />
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
