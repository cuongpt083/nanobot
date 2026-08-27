import React, { useState, useEffect, useRef } from 'react';
import {
  Server,
  Play,
  Square,
  RotateCw,
  Activity,
  Terminal as TerminalIcon,
  Settings,
  Cpu,
  HardDrive,
  Clock,
  ShieldCheck,
  Zap,
  CheckCircle2,
  AlertCircle,
  Copy,
  Trash2,
  Filter,
  Search,
  ExternalLink,
  Folder,
  Layers,
  ArrowRight,
  Code2,
  Laptop
} from 'lucide-react';
import { GatewayProcessConfig, GatewayProcessState, GatewayLogEntry, GatewayMode } from '../types';

interface GatewayManagerViewProps {
  onRefreshGlobalStatus?: () => void;
}

export const GatewayManagerView: React.FC<GatewayManagerViewProps> = ({ onRefreshGlobalStatus }) => {
  const [config, setConfig] = useState<GatewayProcessConfig>({
    mode: 'node_embedded',
    host: '127.0.0.1',
    port: 3000,
    autoStartOnLaunch: true,
    autoRestartOnCrash: true,
    workingDirectory: typeof process !== 'undefined' && process?.cwd ? process.cwd() : '~/nanobot',
    pythonPath: 'python3',
    customCommand: 'nanobot gateway --port 8765',
    customArgs: [],
    logLevel: 'info',
    envVars: {
      NODE_ENV: 'development',
      PORT: '3000',
    },
    maxLogLines: 500,
  });

  const [state, setState] = useState<GatewayProcessState>({
    status: 'running',
    pid: 14208,
    host: '127.0.0.1',
    port: 3000,
    mode: 'node_embedded',
    uptimeSeconds: 7320,
    memoryUsageMb: 84,
    cpuPercent: 0.8,
    url: 'http://127.0.0.1:3000',
    healthStatus: 'healthy',
    healthLatencyMs: 1.2,
  });

  const [logs, setLogs] = useState<GatewayLogEntry[]>([]);
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [isRestarting, setIsRestarting] = useState(false);
  const [isPinging, setIsPinging] = useState(false);
  const [activeTab, setActiveTab] = useState<'terminal' | 'config' | 'architecture'>('terminal');

  // Terminal state
  const [logFilter, setLogFilter] = useState<'all' | 'stdout' | 'stderr' | 'system' | 'http'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [copiedNotification, setCopiedNotification] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [newEnvKey, setNewEnvKey] = useState('');
  const [newEnvValue, setNewEnvValue] = useState('');

  const terminalEndRef = useRef<HTMLDivElement>(null);

  // Load Initial Configuration & Status
  useEffect(() => {
    fetchGatewayStatus();
    fetchGatewayConfig();
    fetchGatewayLogs();

    // Check if running under Electron IPC
    if (window.nanobotDesktop?.gateway) {
      const unsubLog = window.nanobotDesktop.gateway.onLog((entry: GatewayLogEntry) => {
        setLogs((prev) => [...prev.slice(-499), entry]);
      });

      const unsubStatus = window.nanobotDesktop.gateway.onStatusChange((newState: GatewayProcessState) => {
        setState(newState);
      });

      return () => {
        unsubLog?.();
        unsubStatus?.();
      };
    } else {
      // Periodic status and logs poller for Web preview
      const interval = setInterval(() => {
        fetchGatewayStatus();
      }, 3000);
      return () => clearInterval(interval);
    }
  }, []);

  // Auto-scroll terminal
  useEffect(() => {
    if (autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const fetchGatewayStatus = async () => {
    try {
      if (window.nanobotDesktop?.gateway) {
        const data = await window.nanobotDesktop.gateway.getStatus();
        if (data) setState(data);
      } else {
        const res = await fetch('/api/desktop/gateway/status');
        if (res.ok) {
          const data = await res.json();
          setState(data);
        }
      }
    } catch (e) {
      console.warn('Failed to fetch gateway status:', e);
    }
  };

  const fetchGatewayConfig = async () => {
    try {
      if (window.nanobotDesktop?.gateway) {
        const data = await window.nanobotDesktop.gateway.getConfig();
        if (data) setConfig(data);
      } else {
        const res = await fetch('/api/desktop/gateway/config');
        if (res.ok) {
          const data = await res.json();
          setConfig(data);
        }
      }
    } catch (e) {
      console.warn('Failed to fetch gateway config:', e);
    }
  };

  const fetchGatewayLogs = async () => {
    try {
      if (window.nanobotDesktop?.gateway) {
        const data = await window.nanobotDesktop.gateway.getLogs();
        if (Array.isArray(data)) setLogs(data);
      } else {
        const res = await fetch('/api/desktop/gateway/logs');
        if (res.ok) {
          const data = await res.json();
          setLogs(data);
        }
      }
    } catch (e) {
      console.warn('Failed to fetch gateway logs:', e);
    }
  };

  const handleStart = async () => {
    setIsStarting(true);
    try {
      if (window.nanobotDesktop?.gateway) {
        await window.nanobotDesktop.gateway.start();
      } else {
        await fetch('/api/desktop/gateway/start', { method: 'POST' });
      }
      await fetchGatewayStatus();
      await fetchGatewayLogs();
      onRefreshGlobalStatus?.();
    } catch (e) {
      console.error('Start error:', e);
    } finally {
      setIsStarting(false);
    }
  };

  const handleStop = async () => {
    setIsStopping(true);
    try {
      if (window.nanobotDesktop?.gateway) {
        await window.nanobotDesktop.gateway.stop();
      } else {
        await fetch('/api/desktop/gateway/stop', { method: 'POST' });
      }
      await fetchGatewayStatus();
      await fetchGatewayLogs();
      onRefreshGlobalStatus?.();
    } catch (e) {
      console.error('Stop error:', e);
    } finally {
      setIsStopping(false);
    }
  };

  const handleRestart = async () => {
    setIsRestarting(true);
    try {
      if (window.nanobotDesktop?.gateway) {
        await window.nanobotDesktop.gateway.restart(config);
      } else {
        await fetch('/api/desktop/gateway/restart', { method: 'POST' });
      }
      await fetchGatewayStatus();
      await fetchGatewayLogs();
      onRefreshGlobalStatus?.();
    } catch (e) {
      console.error('Restart error:', e);
    } finally {
      setIsRestarting(false);
    }
  };

  const handlePingHealth = async () => {
    setIsPinging(true);
    try {
      if (window.nanobotDesktop?.gateway) {
        const res = await window.nanobotDesktop.gateway.ping();
        if (res?.ok) {
          setState((prev) => ({
            ...prev,
            healthStatus: 'healthy',
            healthLatencyMs: res.latencyMs || 1.2,
          }));
        }
      } else {
        const res = await fetch('/api/desktop/gateway/ping', { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          setState((prev) => ({
            ...prev,
            healthStatus: 'healthy',
            healthLatencyMs: data.latencyMs || 1.2,
          }));
        }
      }
    } catch (e) {
      setState((prev) => ({ ...prev, healthStatus: 'unhealthy' }));
    } finally {
      setIsPinging(false);
    }
  };

  const handleSaveConfig = async () => {
    try {
      if (window.nanobotDesktop?.gateway) {
        await window.nanobotDesktop.gateway.saveConfig(config);
      } else {
        await fetch('/api/desktop/gateway/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });
      }
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e) {
      console.error('Save config error:', e);
    }
  };

  const handleSelectWorkingDirectory = async () => {
    if (window.nanobotDesktop?.selectFolder) {
      const selected = await window.nanobotDesktop.selectFolder();
      if (selected) {
        setConfig((prev) => ({ ...prev, workingDirectory: selected }));
      }
    }
  };

  const handleClearLogs = async () => {
    try {
      if (window.nanobotDesktop?.gateway) {
        await window.nanobotDesktop.gateway.clearLogs();
      } else {
        await fetch('/api/desktop/gateway/logs', { method: 'DELETE' });
      }
      setLogs([]);
    } catch (e) {
      console.error('Clear logs error:', e);
    }
  };

  const handleCopyLogs = () => {
    if (!logs || logs.length === 0) return;
    const text = logs
      .map((l) => `[${new Date(l.timestamp).toLocaleTimeString()}] [${(l.type || 'stdout').toUpperCase()}] ${l.message}`)
      .join('\n');
    navigator.clipboard.writeText(text);
    setCopiedNotification(true);
    setTimeout(() => setCopiedNotification(false), 2500);
  };

  const handleAddEnvVar = () => {
    if (!newEnvKey.trim()) return;
    setConfig((prev) => ({
      ...prev,
      envVars: {
        ...(prev.envVars || {}),
        [newEnvKey.trim()]: newEnvValue,
      },
    }));
    setNewEnvKey('');
    setNewEnvValue('');
  };

  const handleRemoveEnvVar = (key: string) => {
    setConfig((prev) => {
      const updated = { ...(prev.envVars || {}) };
      delete updated[key];
      return { ...prev, envVars: updated };
    });
  };

  const formatUptime = (secs: number) => {
    if (!secs) return '0s';
    const hours = Math.floor(secs / 3600);
    const mins = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (hours > 0) return `${hours}h ${mins}m ${s}s`;
    if (mins > 0) return `${mins}m ${s}s`;
    return `${s}s`;
  };

  const filteredLogs = (logs || []).filter((l) => {
    if (!l) return false;
    if (logFilter !== 'all' && l.type !== logFilter) return false;
    if (searchQuery.trim() && !l.message?.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  const isRunning = state.status === 'running';

  return (
    <div className="flex-1 flex flex-col h-full bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Header Banner & Live State */}
      <div className="border-b border-zinc-800 bg-zinc-900/70 p-5 flex-shrink-0">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/10 border border-amber-500/40 flex items-center justify-center text-amber-400 shadow-inner flex-shrink-0 mt-0.5">
              <Server className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-zinc-100">Gateway Server Supervisor</h1>
                <span
                  className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-mono font-medium ${
                    isRunning
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : state.status === 'starting'
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                  }`}
                >
                  <span
                    className={`w-2 h-2 rounded-full ${
                      isRunning
                        ? 'bg-emerald-400 animate-pulse'
                        : state.status === 'starting'
                        ? 'bg-amber-400 animate-ping'
                        : 'bg-rose-400'
                    }`}
                  />
                  {state.status.toUpperCase()}
                </span>
                <span className="text-xs text-zinc-500 font-mono">
                  {state.mode === 'node_embedded'
                    ? 'Node.js Embedded Engine'
                    : state.mode === 'python_cli'
                    ? 'Python nanobot Gateway'
                    : 'Custom Process'}
                </span>
              </div>
              <p className="text-xs text-zinc-400 mt-1 max-w-2xl">
                Quản lý vòng đời tiến trình máy chủ Gateway (Node/Python) tích hợp ngay trong Electron Desktop.
                Không còn phải mở 2 terminal rời rạc để chạy <code className="text-amber-300 bg-zinc-800 px-1 py-0.5 rounded text-[11px]">npm run</code> và Electron app.
              </p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2 flex-wrap">
            {isRunning ? (
              <button
                id="btn-stop-gateway"
                onClick={handleStop}
                disabled={isStopping || isRestarting}
                className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-rose-600/90 hover:bg-rose-600 text-white font-medium text-xs transition-all shadow-sm disabled:opacity-50 cursor-pointer"
              >
                <Square className="w-3.5 h-3.5 fill-current" />
                <span>{isStopping ? 'Stopping...' : 'Stop Gateway'}</span>
              </button>
            ) : (
              <button
                id="btn-start-gateway"
                onClick={handleStart}
                disabled={isStarting || isRestarting}
                className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition-all shadow-sm disabled:opacity-50 cursor-pointer"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>{isStarting ? 'Starting...' : 'Start Gateway'}</span>
              </button>
            )}

            <button
              id="btn-restart-gateway"
              onClick={handleRestart}
              disabled={isRestarting || isStarting || isStopping}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 font-medium text-xs transition-all disabled:opacity-50 cursor-pointer"
            >
              <RotateCw className={`w-3.5 h-3.5 ${isRestarting ? 'animate-spin text-amber-400' : ''}`} />
              <span>{isRestarting ? 'Restarting...' : 'Restart'}</span>
            </button>

            <button
              id="btn-ping-health"
              onClick={handlePingHealth}
              disabled={isPinging}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 font-medium text-xs transition-all cursor-pointer"
              title="Ping http://host:port/api/health"
            >
              <Activity className={`w-3.5 h-3.5 ${isPinging ? 'animate-pulse text-emerald-400' : 'text-emerald-400'}`} />
              <span>Ping Health ({state.healthLatencyMs}ms)</span>
            </button>
          </div>
        </div>

        {/* Real-Time Metrics Strip */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mt-4 pt-4 border-t border-zinc-800/80 text-xs">
          <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-zinc-800/80 flex flex-col">
            <span className="text-[10px] text-zinc-400 uppercase font-mono tracking-wider flex items-center gap-1">
              <Laptop className="w-3 h-3 text-amber-400" /> Host & Port
            </span>
            <span className="text-zinc-100 font-mono font-medium text-xs mt-1 truncate">
              {state.host}:{state.port}
            </span>
          </div>

          <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-zinc-800/80 flex flex-col">
            <span className="text-[10px] text-zinc-400 uppercase font-mono tracking-wider flex items-center gap-1">
              <Cpu className="w-3 h-3 text-cyan-400" /> Process PID
            </span>
            <span className="text-zinc-100 font-mono font-medium text-xs mt-1">
              {state.pid ? `#${state.pid}` : 'None (Idle)'}
            </span>
          </div>

          <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-zinc-800/80 flex flex-col">
            <span className="text-[10px] text-zinc-400 uppercase font-mono tracking-wider flex items-center gap-1">
              <Clock className="w-3 h-3 text-purple-400" /> Uptime
            </span>
            <span className="text-zinc-100 font-mono font-medium text-xs mt-1">
              {formatUptime(state.uptimeSeconds)}
            </span>
          </div>

          <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-zinc-800/80 flex flex-col">
            <span className="text-[10px] text-zinc-400 uppercase font-mono tracking-wider flex items-center gap-1">
              <HardDrive className="w-3 h-3 text-emerald-400" /> Memory RSS
            </span>
            <span className="text-zinc-100 font-mono font-medium text-xs mt-1">
              {state.memoryUsageMb} MB
            </span>
          </div>

          <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-zinc-800/80 flex flex-col">
            <span className="text-[10px] text-zinc-400 uppercase font-mono tracking-wider flex items-center gap-1">
              <ShieldCheck className="w-3 h-3 text-emerald-400" /> Health API
            </span>
            <span className="text-emerald-400 font-mono font-medium text-xs mt-1 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> 200 OK ({state.healthLatencyMs}ms)
            </span>
          </div>

          <div className="p-2.5 rounded-lg bg-zinc-950/60 border border-zinc-800/80 flex flex-col">
            <span className="text-[10px] text-zinc-400 uppercase font-mono tracking-wider flex items-center gap-1">
              <Zap className="w-3 h-3 text-amber-400" /> Auto-Start
            </span>
            <span className="text-amber-300 font-mono font-medium text-xs mt-1">
              {config.autoStartOnLaunch ? 'Enabled (Instant)' : 'Manual'}
            </span>
          </div>
        </div>
      </div>

      {/* Sub-Navigation Tabs */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-5 bg-zinc-900/40">
        <div className="flex items-center gap-2 pt-2 pb-0">
          <button
            onClick={() => setActiveTab('terminal')}
            className={`flex items-center gap-2 px-3.5 py-2 text-xs font-medium border-b-2 transition-all cursor-pointer ${
              activeTab === 'terminal'
                ? 'border-amber-500 text-amber-400 font-semibold'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <TerminalIcon className="w-3.5 h-3.5" />
            <span>Live Terminal Logs</span>
            <span className="px-1.5 py-0.2 rounded-full bg-zinc-800 text-zinc-400 text-[10px] font-mono">
              {logs.length}
            </span>
          </button>

          <button
            onClick={() => setActiveTab('config')}
            className={`flex items-center gap-2 px-3.5 py-2 text-xs font-medium border-b-2 transition-all cursor-pointer ${
              activeTab === 'config'
                ? 'border-amber-500 text-amber-400 font-semibold'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Settings className="w-3.5 h-3.5" />
            <span>Process Configuration & Env</span>
          </button>

          <button
            onClick={() => setActiveTab('architecture')}
            className={`flex items-center gap-2 px-3.5 py-2 text-xs font-medium border-b-2 transition-all cursor-pointer ${
              activeTab === 'architecture'
                ? 'border-amber-500 text-amber-400 font-semibold'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Unified Architecture</span>
          </button>
        </div>

        {/* Tab-specific quick action */}
        {activeTab === 'terminal' && (
          <div className="flex items-center gap-2 py-1.5">
            <button
              onClick={handleCopyLogs}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs transition-colors cursor-pointer"
            >
              <Copy className="w-3 h-3" />
              <span>{copiedNotification ? 'Copied!' : 'Copy'}</span>
            </button>
            <button
              onClick={handleClearLogs}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs transition-colors cursor-pointer"
            >
              <Trash2 className="w-3 h-3" />
              <span>Clear</span>
            </button>
          </div>
        )}
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-5">
        {/* TAB 1: LIVE TERMINAL LOGS */}
        {activeTab === 'terminal' && (
          <div className="flex flex-col h-full space-y-3">
            {/* Terminal Controls Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 bg-zinc-900 p-3 rounded-lg border border-zinc-800">
              <div className="flex items-center gap-2">
                <Filter className="w-3.5 h-3.5 text-zinc-400" />
                <span className="text-xs text-zinc-400">Filter:</span>
                {(['all', 'stdout', 'stderr', 'system', 'http'] as const).map((type) => (
                  <button
                    key={type}
                    onClick={() => setLogFilter(type)}
                    className={`px-2 py-0.5 rounded text-[11px] font-mono capitalize transition-colors cursor-pointer ${
                      logFilter === type
                        ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 font-semibold'
                        : 'bg-zinc-800/80 text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    {type}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-3">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search logs..."
                    className="bg-zinc-950 border border-zinc-800 rounded-md pl-8 pr-3 py-1 text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-amber-500 font-mono w-48"
                  />
                </div>

                <label className="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={autoScroll}
                    onChange={(e) => setAutoScroll(e.target.checked)}
                    className="rounded border-zinc-700 bg-zinc-900 text-amber-500 focus:ring-0"
                  />
                  <span>Auto-scroll</span>
                </label>
              </div>
            </div>

            {/* Terminal Window Box */}
            <div className="flex-1 min-h-[380px] bg-zinc-950 border border-zinc-800/90 rounded-xl p-4 font-mono text-xs overflow-y-auto shadow-2xl relative">
              <div className="flex items-center justify-between pb-2 mb-3 border-b border-zinc-900 text-[11px] text-zinc-500 select-none">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-rose-500/70 inline-block" />
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500/70 inline-block" />
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/70 inline-block" />
                  <span className="ml-2 text-zinc-400">nanobot-gateway :: {state.host}:{state.port} (stdout/stderr)</span>
                </div>
                <span>Showing {filteredLogs.length} events</span>
              </div>

              {filteredLogs.length === 0 ? (
                <div className="text-zinc-600 italic py-12 text-center">
                  No log entries matched your current filter.
                </div>
              ) : (
                <div className="space-y-1.5">
                  {filteredLogs.map((log) => {
                    const timeStr = new Date(log.timestamp).toLocaleTimeString();
                    let badgeColor = 'text-zinc-400 bg-zinc-800';
                    if (log.type === 'stderr') badgeColor = 'text-rose-400 bg-rose-950/60 border border-rose-800/40';
                    if (log.type === 'stdout') badgeColor = 'text-emerald-400 bg-emerald-950/40 border border-emerald-800/30';
                    if (log.type === 'system') badgeColor = 'text-amber-400 bg-amber-950/40 border border-amber-800/30';
                    if (log.type === 'http') badgeColor = 'text-cyan-400 bg-cyan-950/40 border border-cyan-800/30';

                    return (
                      <div key={log.id} className="flex items-start gap-2.5 leading-relaxed hover:bg-zinc-900/50 px-1 py-0.5 rounded transition-colors">
                        <span className="text-zinc-600 select-none flex-shrink-0 text-[10px]">{timeStr}</span>
                        <span className={`text-[10px] px-1.5 py-0.2 rounded font-semibold uppercase flex-shrink-0 ${badgeColor}`}>
                          {log.type}
                        </span>
                        <span
                          className={`flex-1 break-all whitespace-pre-wrap ${
                            log.type === 'stderr'
                              ? 'text-rose-300'
                              : log.type === 'system'
                              ? 'text-amber-200'
                              : log.type === 'http'
                              ? 'text-cyan-300'
                              : 'text-zinc-300'
                          }`}
                        >
                          {log.message}
                        </span>
                      </div>
                    );
                  })}
                  <div ref={terminalEndRef} />
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 2: CONFIGURATION & ENVIRONMENT */}
        {activeTab === 'config' && (
          <div className="max-w-4xl space-y-6">
            {saveSuccess && (
              <div className="p-3.5 rounded-lg bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 text-xs flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span>Cấu hình Gateway đã được lưu và cập nhật thành công! Khởi động lại Gateway để áp dụng đầy đủ.</span>
              </div>
            )}

            {/* Mode Selection */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-zinc-100 mb-1">Chế độ thực thi Gateway (Execution Mode)</h3>
              <p className="text-xs text-zinc-400 mb-4">
                Chọn cách Electron khởi chạy hoặc kết nối với Nanobot Agent Gateway Backend.
              </p>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <button
                  type="button"
                  onClick={() => setConfig((prev) => ({ ...prev, mode: 'node_embedded' }))}
                  className={`p-4 rounded-xl border text-left transition-all cursor-pointer ${
                    config.mode === 'node_embedded'
                      ? 'bg-amber-500/10 border-amber-500/80 ring-1 ring-amber-500/30'
                      : 'bg-zinc-950/60 border-zinc-800 hover:border-zinc-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-semibold text-xs text-zinc-100">Node.js Engine (Tích hợp)</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-500/20 text-amber-300">Khuyên dùng</span>
                  </div>
                  <p className="text-[11px] text-zinc-400 leading-relaxed">
                    Chạy trực tiếp bundle TypeScript/CJS Express Server tích hợp bên trong ứng dụng Electron mà không cần bất kỳ môi trường ngoài nào.
                  </p>
                </button>

                <button
                  type="button"
                  onClick={() => setConfig((prev) => ({ ...prev, mode: 'python_cli' }))}
                  className={`p-4 rounded-xl border text-left transition-all cursor-pointer ${
                    config.mode === 'python_cli'
                      ? 'bg-amber-500/10 border-amber-500/80 ring-1 ring-amber-500/30'
                      : 'bg-zinc-950/60 border-zinc-800 hover:border-zinc-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-semibold text-xs text-zinc-100">Python Nanobot Core</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-800 text-zinc-400">Python CLI</span>
                  </div>
                  <p className="text-[11px] text-zinc-400 leading-relaxed">
                    Khởi chạy qua Python package <code className="text-amber-300 font-mono">python -m nanobot gateway</code> hỗ trợ đầy đủ WebSocket channel bus.
                  </p>
                </button>

                <button
                  type="button"
                  onClick={() => setConfig((prev) => ({ ...prev, mode: 'custom' }))}
                  className={`p-4 rounded-xl border text-left transition-all cursor-pointer ${
                    config.mode === 'custom'
                      ? 'bg-amber-500/10 border-amber-500/80 ring-1 ring-amber-500/30'
                      : 'bg-zinc-950/60 border-zinc-800 hover:border-zinc-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-semibold text-xs text-zinc-100">Custom Command</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-800 text-zinc-400">Tùy biến</span>
                  </div>
                  <p className="text-[11px] text-zinc-400 leading-relaxed">
                    Thực thi một lệnh tùy chỉnh do bạn chỉ định (ví dụ: <code className="text-amber-300 font-mono">docker run</code> hoặc custom wrapper script).
                  </p>
                </button>
              </div>
            </div>

            {/* Network & Lifecycle Settings */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
              <h3 className="text-sm font-semibold text-zinc-100">Thiết lập mạng & Khởi động</h3>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1.5">Host Binding</label>
                  <select
                    value={config.host}
                    onChange={(e) => setConfig((prev) => ({ ...prev, host: e.target.value }))}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-amber-500 font-mono"
                  >
                    <option value="127.0.0.1">127.0.0.1 (Localhost an toàn - Khuyên dùng)</option>
                    <option value="0.0.0.0">0.0.0.0 (Mở cho toàn bộ mạng nội bộ LAN)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1.5">Cổng Port</label>
                  <input
                    type="number"
                    value={config.port}
                    onChange={(e) => setConfig((prev) => ({ ...prev, port: parseInt(e.target.value) || 3000 }))}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-amber-500 font-mono"
                  />
                </div>
              </div>

              {/* Working Directory */}
              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">Thư mục làm việc (Working Directory)</label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={config.workingDirectory}
                    onChange={(e) => setConfig((prev) => ({ ...prev, workingDirectory: e.target.value }))}
                    className="flex-1 bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-amber-500 font-mono"
                  />
                  <button
                    type="button"
                    onClick={handleSelectWorkingDirectory}
                    className="flex items-center gap-1 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  >
                    <Folder className="w-3.5 h-3.5 text-amber-400" />
                    <span>Duyệt thư mục...</span>
                  </button>
                </div>
              </div>

              {/* Automation Toggles */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t border-zinc-800">
                <label className="flex items-start gap-3 p-3 rounded-lg bg-zinc-950/60 border border-zinc-800 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={config.autoStartOnLaunch}
                    onChange={(e) => setConfig((prev) => ({ ...prev, autoStartOnLaunch: e.target.checked }))}
                    className="mt-0.5 rounded border-zinc-700 bg-zinc-900 text-amber-500 focus:ring-0"
                  />
                  <div>
                    <span className="text-xs font-medium text-zinc-200 block">Tự động chạy khi mở Electron Desktop</span>
                    <span className="text-[11px] text-zinc-400">Không cần mở terminal riêng để khởi động Gateway</span>
                  </div>
                </label>

                <label className="flex items-start gap-3 p-3 rounded-lg bg-zinc-950/60 border border-zinc-800 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={config.autoRestartOnCrash}
                    onChange={(e) => setConfig((prev) => ({ ...prev, autoRestartOnCrash: e.target.checked }))}
                    className="mt-0.5 rounded border-zinc-700 bg-zinc-900 text-amber-500 focus:ring-0"
                  />
                  <div>
                    <span className="text-xs font-medium text-zinc-200 block">Tự động khôi phục khi gặp sự cố (Auto-Restart)</span>
                    <span className="text-[11px] text-zinc-400">Tự động hồi sinh tiến trình sau 2 giây nếu bị crash</span>
                  </div>
                </label>
              </div>
            </div>

            {/* Environment Variables Manager */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-zinc-100">Biến môi trường (Environment Variables)</h3>
                  <p className="text-xs text-zinc-400">Truyền trực tiếp API keys và cấu hình vào tiến trình Gateway.</p>
                </div>
              </div>

              <div className="space-y-2">
                {Object.entries(config.envVars || {}).map(([key, value]) => (
                  <div key={key} className="flex items-center gap-2">
                    <input
                      type="text"
                      value={key}
                      disabled
                      className="w-1/3 bg-zinc-950 border border-zinc-800/80 rounded-lg px-3 py-1.5 text-xs text-amber-400 font-mono"
                    />
                    <input
                      type="password"
                      value={value}
                      onChange={(e) => {
                        const val = e.target.value;
                        setConfig((prev) => ({
                          ...prev,
                          envVars: { ...prev.envVars, [key]: val },
                        }));
                      }}
                      placeholder="Value or secret..."
                      className="flex-1 bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                    />
                    <button
                      type="button"
                      onClick={() => handleRemoveEnvVar(key)}
                      className="p-1.5 text-zinc-500 hover:text-rose-400 transition-colors"
                      title="Xóa biến"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}

                {/* Add new Env Row */}
                <div className="flex items-center gap-2 pt-2">
                  <input
                    type="text"
                    value={newEnvKey}
                    onChange={(e) => setNewEnvKey(e.target.value)}
                    placeholder="Tên biến (e.g. GEMINI_API_KEY)"
                    className="w-1/3 bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                  />
                  <input
                    type="text"
                    value={newEnvValue}
                    onChange={(e) => setNewEnvValue(e.target.value)}
                    placeholder="Giá trị"
                    className="flex-1 bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                  />
                  <button
                    type="button"
                    onClick={handleAddEnvVar}
                    className="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition-colors cursor-pointer"
                  >
                    + Thêm
                  </button>
                </div>
              </div>
            </div>

            {/* Save Button */}
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={handleSaveConfig}
                className="px-5 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold text-xs shadow-lg transition-all cursor-pointer"
              >
                Lưu cấu hình Gateway
              </button>
            </div>
          </div>
        )}

        {/* TAB 3: UNIFIED ARCHITECTURE OVERVIEW */}
        {activeTab === 'architecture' && (
          <div className="max-w-4xl space-y-6">
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
              <h3 className="text-base font-bold text-zinc-100 mb-2">So sánh kiến trúc thực thi</h3>
              <p className="text-xs text-zinc-400 mb-6 leading-relaxed">
                Trước đây bạn phải chạy 2 terminal riêng biệt: một cho server backend và một cho Electron Desktop.
                Với cơ chế <strong>Gateway Supervisor</strong> mới, Electron Desktop tự động đóng vai trò là Orchestrator quản lý toàn bộ vòng đời tiến trình.
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Old Approach */}
                <div className="p-4 rounded-xl bg-zinc-950/80 border border-zinc-800/80">
                  <div className="flex items-center justify-between mb-3 text-xs font-semibold text-rose-400">
                    <span>Cách cũ (2 tiến trình rời rạc)</span>
                    <span className="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 text-[10px]">Dual Process</span>
                  </div>
                  <div className="space-y-2 text-xs font-mono text-zinc-400">
                    <div className="p-2.5 rounded bg-zinc-900 border border-zinc-800 text-[11px]">
                      <span className="text-zinc-500 select-none">Terminal 1 $ </span>
                      <span className="text-amber-300">npm run dev</span>
                      <div className="text-[10px] text-zinc-500 mt-1">Chạy Express / Vite server trên port 3000</div>
                    </div>
                    <div className="p-2.5 rounded bg-zinc-900 border border-zinc-800 text-[11px]">
                      <span className="text-zinc-500 select-none">Terminal 2 $ </span>
                      <span className="text-amber-300">npm run electron:dev</span>
                      <div className="text-[10px] text-zinc-500 mt-1">Chạy Electron Desktop kết nối vào localhost:3000</div>
                    </div>
                  </div>
                </div>

                {/* New Approach */}
                <div className="p-4 rounded-xl bg-gradient-to-br from-amber-500/10 via-zinc-900 to-zinc-950 border border-amber-500/40">
                  <div className="flex items-center justify-between mb-3 text-xs font-semibold text-amber-400">
                    <span>Cách mới (Tất cả trong 1 - Unified Desktop)</span>
                    <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[10px]">All-In-One</span>
                  </div>
                  <div className="space-y-2 text-xs font-mono text-zinc-300">
                    <div className="p-2.5 rounded bg-zinc-950 border border-amber-500/30 text-[11px]">
                      <span className="text-zinc-500 select-none">Chỉ 1 lệnh duy nhất $ </span>
                      <span className="text-emerald-400 font-bold">npm run electron</span>
                      <div className="text-[10px] text-zinc-400 mt-1">
                        Electron tự động spawn Gateway process ngầm, kiểm tra health ping 200 OK, và mở giao diện ứng dụng.
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-emerald-400 pt-1">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Không lo xung đột cổng hoặc quên khởi động server</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Package.json snippet */}
              <div className="mt-6 p-4 rounded-xl bg-zinc-950 border border-zinc-800">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-zinc-300">Cấu hình Scripts trong package.json:</span>
                  <Code2 className="w-4 h-4 text-zinc-500" />
                </div>
                <pre className="text-xs font-mono text-zinc-300 bg-zinc-900/90 p-3 rounded-lg overflow-x-auto border border-zinc-800">
{`"scripts": {
  "electron": "electron electron/main.cjs",
  "desktop:start": "npm run electron",
  "electron:dev": "NODE_ENV=development electron electron/main.cjs",
  "electron:build": "npm run build && electron-builder --config electron/electron-builder.json"
}`}
                </pre>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
