import React, { useState } from 'react';
import {
  Cpu,
  Plus,
  Play,
  Copy,
  Check,
  Trash2,
  Power,
  RefreshCw,
  FolderTree,
  Database,
  Search,
  Github,
  Brain,
  Server,
  FileCode,
  ShieldCheck,
  Layers,
  Sparkles,
  ExternalLink,
  Code2
} from 'lucide-react';
import { McpServerConfig } from '../types';

interface McpServersViewProps {
  servers: McpServerConfig[];
  onToggleServer: (id: string) => Promise<void>;
  onAddServer: (server: Partial<McpServerConfig>) => Promise<void>;
  onDeleteServer: (id: string) => Promise<void>;
  onTestServer: (id: string) => Promise<any>;
}

export const McpServersView: React.FC<McpServersViewProps> = ({
  servers,
  onToggleServer,
  onAddServer,
  onDeleteServer,
  onTestServer,
}) => {
  const [selectedServer, setSelectedServer] = useState<McpServerConfig | null>(
    (servers && servers.length > 0 ? servers[0] : null),
  );
  const [isAddingServer, setIsAddingServer] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<any | null>(null);
  const [copiedConfig, setCopiedConfig] = useState(false);

  React.useEffect(() => {
    if (!selectedServer && servers && servers.length > 0) {
      setSelectedServer(servers[0]);
    } else if (selectedServer && servers && !servers.some((s) => s.id === selectedServer.id)) {
      setSelectedServer(servers[0] || null);
    }
  }, [servers, selectedServer]);

  // Form State for new server
  const [newName, setNewName] = useState('');
  const [newCommand, setNewCommand] = useState('npx');
  const [newArgs, setNewArgs] = useState('-y @modelcontextprotocol/server-puppeteer');
  const [newEnvKey, setNewEnvKey] = useState('');
  const [newEnvVal, setNewEnvVal] = useState('');
  const [newDescription, setNewDescription] = useState('');

  const getServerIcon = (iconName: string) => {
    switch (iconName) {
      case 'FolderTree':
        return <FolderTree className="w-5 h-5 text-amber-400" />;
      case 'Database':
        return <Database className="w-5 h-5 text-emerald-400" />;
      case 'Search':
        return <Search className="w-5 h-5 text-sky-400" />;
      case 'Github':
        return <Github className="w-5 h-5 text-purple-400" />;
      case 'Brain':
        return <Brain className="w-5 h-5 text-rose-400" />;
      case 'Server':
      default:
        return <Server className="w-5 h-5 text-indigo-400" />;
    }
  };

  const handleTest = async (server: McpServerConfig) => {
    setTestingId(server.id);
    setTestResult(null);
    try {
      const res = await onTestServer(server.id);
      setTestResult(res);
    } catch (e: any) {
      setTestResult({ error: e.message || 'Test failed' });
    } finally {
      setTestingId(null);
    }
  };

  const handleCreateServer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName || !newCommand) return;

    const env: Record<string, string> = {};
    if (newEnvKey.trim()) {
      env[newEnvKey.trim()] = newEnvVal.trim();
    }

    const args = newArgs
      .split(' ')
      .map((s) => s.trim())
      .filter(Boolean);

    await onAddServer({
      name: newName,
      command: newCommand,
      args,
      env,
      description: newDescription || 'Custom MCP Server configured in Nanobot Desktop',
      protocol: 'stdio',
      status: 'connected',
    });

    setIsAddingServer(false);
    setNewName('');
    setNewArgs('');
    setNewEnvKey('');
    setNewEnvVal('');
    setNewDescription('');
  };

  // Generate Claude Desktop Config format
  const generateClaudeDesktopConfig = () => {
    const config: Record<string, any> = { mcpServers: {} };
    servers.forEach((s) => {
      config.mcpServers[s.id.replace('mcp-', '')] = {
        command: s.command,
        args: s.args,
        ...(Object.keys(s.env || {}).length > 0 ? { env: s.env } : {}),
      };
    });
    return JSON.stringify(config, null, 2);
  };

  const handleCopyClaudeConfig = () => {
    navigator.clipboard.writeText(generateClaudeDesktopConfig());
    setCopiedConfig(true);
    setTimeout(() => setCopiedConfig(false), 2000);
  };

  return (
    <div className="h-full flex overflow-hidden bg-zinc-950 text-zinc-100">
      {/* Left Sidebar: Registered MCP Servers */}
      <div className="w-84 border-r border-zinc-800/80 bg-zinc-900/40 flex flex-col justify-between">
        <div className="p-4 border-b border-zinc-800/80">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
              <Cpu className="w-4 h-4 text-amber-400" />
              <span>Model Context Protocol</span>
            </h3>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-semibold border border-amber-500/30">
              {servers.filter((s) => s.status === 'connected').length} Active
            </span>
          </div>
          <p className="text-[11px] text-zinc-400 leading-relaxed">
            Claude Desktop-compatible MCP servers extending Nanobot with native OS, database, and API tools.
          </p>

          <button
            id="btn-add-mcp-server"
            onClick={() => setIsAddingServer(true)}
            className="mt-3 w-full py-1.5 px-3 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded-lg transition-colors flex items-center justify-center gap-1.5 cursor-pointer shadow-xs"
          >
            <Plus className="w-3.5 h-3.5 stroke-[3]" />
            <span>Add MCP Server</span>
          </button>
        </div>

        {/* Server List */}
        <div className="flex-1 overflow-y-auto p-2.5 space-y-2">
          {servers.map((server) => {
            const isSelected = selectedServer?.id === server.id;
            const isConnected = server.status === 'connected';

            return (
              <div
                key={server.id}
                id={`mcp-card-${server.id}`}
                onClick={() => {
                  setSelectedServer(server);
                  setTestResult(null);
                }}
                className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                  isSelected
                    ? 'bg-zinc-800/90 border-amber-500/60 shadow-md ring-1 ring-amber-500/30'
                    : 'bg-zinc-900/50 border-zinc-800/70 hover:bg-zinc-850 hover:border-zinc-700'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <div className="p-2 rounded-lg bg-zinc-800/80 border border-zinc-700">
                      {getServerIcon(server.icon)}
                    </div>
                    <div>
                      <div className="text-xs font-bold text-zinc-100 flex items-center gap-1.5">
                        <span>{server.name}</span>
                      </div>
                      <div className="text-[10px] font-mono text-zinc-400 mt-0.5">
                        {server.command} {server.args[0] || ''}
                      </div>
                    </div>
                  </div>

                  <span
                    className={`px-1.5 py-0.5 rounded text-[9px] font-mono uppercase font-semibold ${
                      isConnected
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                        : 'bg-zinc-800 text-zinc-500 border border-zinc-700'
                    }`}
                  >
                    {server.status}
                  </span>
                </div>

                <div className="mt-2.5 flex items-center justify-between text-[10px] font-mono text-zinc-400 pt-2 border-t border-zinc-800/60">
                  <span>{server.toolsCount} Tools exposed</span>
                  <span>{server.resourcesCount} Resources</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Sync with Claude Desktop Box */}
        <div className="p-3 border-t border-zinc-800/80 bg-zinc-950/60">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-semibold text-zinc-300 flex items-center gap-1">
              <Code2 className="w-3.5 h-3.5 text-amber-400" />
              <span>Claude Desktop Config</span>
            </span>
            <button
              onClick={handleCopyClaudeConfig}
              className="text-[10px] text-amber-400 hover:text-amber-300 flex items-center gap-1 font-mono cursor-pointer"
            >
              {copiedConfig ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
              <span>{copiedConfig ? 'Copied!' : 'Copy JSON'}</span>
            </button>
          </div>
          <p className="text-[10px] text-zinc-500 line-clamp-2">
            Paste into <code className="text-zinc-300">claude_desktop_config.json</code> to mirror all MCP tools.
          </p>
        </div>
      </div>

      {/* Right Details & Configuration Panel */}
      <div className="flex-1 overflow-y-auto p-8 max-w-4xl space-y-6">
        {isAddingServer ? (
          /* Add Server Form */
          <div className="bg-zinc-900/80 border border-zinc-800 rounded-2xl p-6 space-y-5">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <div>
                <h3 className="text-base font-bold text-zinc-100">Register New MCP Server</h3>
                <p className="text-xs text-zinc-400">
                  Connect any Model Context Protocol stdio or SSE process to Nanobot.
                </p>
              </div>
              <button
                onClick={() => setIsAddingServer(false)}
                className="text-zinc-500 hover:text-zinc-300 text-xs px-2 py-1 bg-zinc-800 rounded"
              >
                Cancel
              </button>
            </div>

            <form onSubmit={handleCreateServer} className="space-y-4 text-xs">
              <div>
                <label className="block text-zinc-300 font-semibold mb-1">Server Name</label>
                <input
                  type="text"
                  required
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. Puppeteer Browser MCP"
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-zinc-100 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-zinc-300 font-semibold mb-1">Executable (Command)</label>
                  <input
                    type="text"
                    required
                    value={newCommand}
                    onChange={(e) => setNewCommand(e.target.value)}
                    placeholder="npx, uvx, node, python"
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 font-mono text-zinc-100 focus:outline-none focus:border-amber-500"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-zinc-300 font-semibold mb-1">Arguments</label>
                  <input
                    type="text"
                    value={newArgs}
                    onChange={(e) => setNewArgs(e.target.value)}
                    placeholder="-y @modelcontextprotocol/server-puppeteer"
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 font-mono text-zinc-100 focus:outline-none focus:border-amber-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-zinc-300 font-semibold mb-1">Environment Key (Optional)</label>
                  <input
                    type="text"
                    value={newEnvKey}
                    onChange={(e) => setNewEnvKey(e.target.value)}
                    placeholder="API_KEY / TOKEN"
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 font-mono text-zinc-100 focus:outline-none focus:border-amber-500"
                  />
                </div>
                <div>
                  <label className="block text-zinc-300 font-semibold mb-1">Environment Value</label>
                  <input
                    type="password"
                    value={newEnvVal}
                    onChange={(e) => setNewEnvVal(e.target.value)}
                    placeholder="Secret value"
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 font-mono text-zinc-100 focus:outline-none focus:border-amber-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-zinc-300 font-semibold mb-1">Description</label>
                <textarea
                  rows={2}
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="Automates headless Chrome navigation and DOM scraping."
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-zinc-100 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsAddingServer(false)}
                  className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold"
                >
                  Save & Connect MCP Server
                </button>
              </div>
            </form>
          </div>
        ) : selectedServer ? (
          /* Selected Server Details */
          <>
            <div className="flex items-start justify-between pb-4 border-b border-zinc-800/80">
              <div className="flex items-center gap-3.5">
                <div className="p-3.5 rounded-xl bg-zinc-900 border border-zinc-700/80">
                  {getServerIcon(selectedServer.icon)}
                </div>
                <div>
                  <div className="flex items-center gap-2.5">
                    <h2 className="text-lg font-bold text-zinc-100">{selectedServer.name}</h2>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase font-bold ${
                        selectedServer.status === 'connected'
                          ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                          : 'bg-zinc-800 text-zinc-400'
                      }`}
                    >
                      {selectedServer.status}
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-zinc-800 text-zinc-400 uppercase">
                      {selectedServer.protocol}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 mt-1">{selectedServer.description}</p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  id={`btn-toggle-${selectedServer.id}`}
                  onClick={() => onToggleServer(selectedServer.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer ${
                    selectedServer.status === 'connected'
                      ? 'bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700'
                      : 'bg-emerald-600 hover:bg-emerald-500 text-white'
                  }`}
                >
                  <Power className="w-3.5 h-3.5" />
                  <span>{selectedServer.status === 'connected' ? 'Disconnect' : 'Connect'}</span>
                </button>

                <button
                  onClick={() => onDeleteServer(selectedServer.id)}
                  className="p-2 rounded-lg bg-zinc-800 hover:bg-rose-950 hover:text-rose-300 text-zinc-400 transition-colors cursor-pointer"
                  title="Remove MCP Server"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Launch Command Configuration */}
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">
                Spawn Command Specification
              </h4>
              <div className="p-3.5 rounded-xl bg-zinc-900 border border-zinc-800 font-mono text-xs text-emerald-400/90 flex items-center justify-between">
                <span>
                  {selectedServer.command} {(selectedServer.args || []).join(' ')}
                </span>
                <span className="text-[10px] text-zinc-500 bg-zinc-950 px-2 py-1 rounded">
                  IPC stdio
                </span>
              </div>
            </div>

            {/* Exposed MCP Tools */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">
                  Discovered MCP Tools ({selectedServer.tools?.length || selectedServer.toolsCount})
                </h4>
                <span className="text-[11px] text-zinc-500 font-mono">
                  Schema: 2024-11-05 (MCP v1)
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2.5">
                {(selectedServer.tools || ['default_action', 'default_query']).map((toolName) => (
                  <div
                    key={toolName}
                    className="p-3 rounded-lg bg-zinc-900/90 border border-zinc-800 flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-amber-400" />
                      <span className="text-xs font-mono text-zinc-200">{toolName}</span>
                    </div>
                    <span className="text-[10px] text-emerald-400 bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-800/60 font-mono">
                      ready
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Live MCP JSON-RPC Ping & Test */}
            <div className="space-y-3 p-5 rounded-xl border border-zinc-800 bg-zinc-900/40">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-semibold text-zinc-200 flex items-center gap-2">
                    <Play className="w-3.5 h-3.5 text-amber-400" />
                    <span>Live MCP Handshake & Tool Ping</span>
                  </h4>
                  <p className="text-[11px] text-zinc-500 mt-0.5">
                    Validates protocol handshake, JSON-RPC 2.0 transport, and response latency.
                  </p>
                </div>

                <button
                  id="btn-test-mcp-handshake"
                  onClick={() => handleTest(selectedServer)}
                  disabled={testingId === selectedServer.id}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded-lg transition-colors disabled:opacity-50 cursor-pointer shadow-xs"
                >
                  <RefreshCw
                    className={`w-3.5 h-3.5 ${
                      testingId === selectedServer.id ? 'animate-spin' : ''
                    }`}
                  />
                  <span>{testingId === selectedServer.id ? 'Ping Testing...' : 'Test Connection'}</span>
                </button>
              </div>

              {testResult && (
                <div className="mt-3 p-3.5 rounded-lg bg-zinc-950 border border-zinc-800 font-mono text-[11px] text-emerald-400/90 whitespace-pre-wrap leading-relaxed">
                  {JSON.stringify(testResult, null, 2)}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="h-full flex items-center justify-center text-zinc-500 text-xs">
            Select an MCP Server from the left to inspect tools and handshake status.
          </div>
        )}
      </div>
    </div>
  );
};
