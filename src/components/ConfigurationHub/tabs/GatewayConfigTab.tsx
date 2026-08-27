import React, { useState } from 'react';
import {
  Server,
  Play,
  Square,
  RotateCw,
  Activity,
  Terminal,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Cpu,
  Clock,
  HardDrive,
  ShieldAlert
} from 'lucide-react';
import { NanobotFullConfig, GatewayProcessState, GatewayLogEntry, GatewayProcessConfig } from '../../../types';

interface GatewayConfigTabProps {
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => void;
  gatewayState: GatewayProcessState;
  logs: GatewayLogEntry[];
  onStartGateway: () => void;
  onStopGateway: () => void;
  onRestartGateway: () => void;
  onClearLogs: () => void;
  onOpenSetupWizard?: () => void;
}

export const GatewayConfigTab: React.FC<GatewayConfigTabProps> = ({
  config,
  onUpdateConfig,
  gatewayState,
  logs,
  onStartGateway,
  onStopGateway,
  onRestartGateway,
  onClearLogs,
  onOpenSetupWizard,
}) => {
  const [logFilter, setLogFilter] = useState<'all' | 'stdout' | 'stderr'>('all');

  const filteredLogs = logs.filter((l) => {
    if (logFilter === 'all') return true;
    return l.type === logFilter;
  });

  return (
    <div className="flex flex-col h-full space-y-4 text-zinc-300">
      {/* Supervisor Control Banner */}
      <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800/80 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className={`w-3 h-3 rounded-full ${
              gatewayState.status === 'running'
                ? 'bg-emerald-400 shadow-sm shadow-emerald-400 animate-pulse'
                : 'bg-zinc-600'
            }`}
          />
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-bold text-zinc-100">Nanobot Gateway Supervisor</h4>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300">
                Port {gatewayState.port || 3000}
              </span>
            </div>
            <p className="text-xs text-zinc-400 mt-0.5">
              Status: <span className={`font-semibold capitalize ${gatewayState.status === 'running' ? 'text-emerald-400' : gatewayState.status === 'starting' ? 'text-amber-400' : 'text-zinc-500'}`}>{gatewayState.status || 'stopped'}</span>
              {gatewayState.pid && <span> • PID: <strong className="text-zinc-300 font-mono">{gatewayState.pid}</strong></span>}
              <span> • Uptime: <strong className="text-zinc-300 font-mono">{gatewayState.uptimeSeconds || 0}s</strong></span>
              {gatewayState.memoryUsageMb ? <span> • RAM: <strong className="text-zinc-300 font-mono">{gatewayState.memoryUsageMb} MB</strong></span> : null}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {onOpenSetupWizard && (
            <button
              onClick={onOpenSetupWizard}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 text-xs font-semibold transition-colors cursor-pointer border border-amber-500/30"
              title="Mở trình Cài đặt Môi trường & Dependencies"
            >
              <span>Setup Wizard</span>
            </button>
          )}

          {gatewayState.status === 'running' ? (
            <>
              <button
                onClick={onRestartGateway}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-zinc-200 transition-colors cursor-pointer border border-zinc-700"
              >
                <RotateCw className="w-3.5 h-3.5" />
                <span>Restart</span>
              </button>
              <button
                onClick={onStopGateway}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 text-xs font-semibold transition-colors cursor-pointer border border-rose-500/30"
              >
                <Square className="w-3.5 h-3.5" />
                <span>Stop Gateway</span>
              </button>
            </>
          ) : (
            <button
              onClick={onStartGateway}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-zinc-950 text-xs font-bold transition-colors cursor-pointer"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Start Gateway</span>
            </button>
          )}
        </div>
      </div>

      {/* Network & Host Configuration */}
      <div className="grid grid-cols-3 gap-3">
        <div className="p-3 rounded-xl bg-zinc-950/40 border border-zinc-800 space-y-1">
          <label className="text-xs font-semibold text-zinc-200">Gateway Port</label>
          <input
            type="number"
            value={config.gateway?.port || 3000}
            onChange={(e) =>
              onUpdateConfig({
                gateway: { ...config.gateway, port: Number(e.target.value) },
              })
            }
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2 text-xs font-mono text-zinc-200"
          />
        </div>

        <div className="p-3 rounded-xl bg-zinc-950/40 border border-zinc-800 space-y-1">
          <label className="text-xs font-semibold text-zinc-200">Host Binding</label>
          <input
            type="text"
            value={config.gateway?.host || '0.0.0.0'}
            onChange={(e) =>
              onUpdateConfig({
                gateway: { ...config.gateway, host: e.target.value },
              })
            }
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2 text-xs font-mono text-zinc-200"
          />
        </div>

        <div className="p-3 rounded-xl bg-zinc-950/40 border border-zinc-800 space-y-1">
          <label className="text-xs font-semibold text-zinc-200">Heartbeat Interval (s)</label>
          <input
            type="number"
            value={config.gateway?.heartbeatIntervalS || 60}
            onChange={(e) =>
              onUpdateConfig({
                gateway: { ...config.gateway, heartbeatIntervalS: Number(e.target.value) },
              })
            }
            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-2 text-xs font-mono text-zinc-200"
          />
        </div>
      </div>

      {/* Terminal Logs Output */}
      <div className="flex-1 flex flex-col min-h-0 rounded-xl bg-zinc-950 border border-zinc-800 overflow-hidden">
        <div className="h-9 bg-zinc-900/80 border-b border-zinc-800 px-3 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <Terminal className="w-3.5 h-3.5 text-amber-400" />
            <span className="font-mono font-semibold text-zinc-200">Gateway Terminal Output</span>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={logFilter}
              onChange={(e) => setLogFilter(e.target.value as any)}
              className="bg-zinc-950 border border-zinc-800 rounded px-2 py-0.5 text-[11px] text-zinc-300"
            >
              <option value="all">All Logs ({logs.length})</option>
              <option value="stdout">stdout</option>
              <option value="stderr">stderr</option>
            </select>

            <button
              onClick={onClearLogs}
              className="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
              title="Clear Logs"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="flex-1 p-3 overflow-y-auto font-mono text-[11px] space-y-1 select-text bg-zinc-950">
          {filteredLogs.length === 0 ? (
            <div className="text-zinc-600 text-center py-6">No gateway log entries recorded.</div>
          ) : (
            filteredLogs.map((log) => (
              <div
                key={log.id}
                className={`leading-relaxed ${
                  log.type === 'stderr'
                    ? 'text-rose-400'
                    : log.type === 'system'
                    ? 'text-amber-400 font-semibold'
                    : 'text-zinc-300'
                }`}
              >
                <span className="text-zinc-600 select-none mr-2">
                  [{new Date(log.timestamp).toLocaleTimeString()}]
                </span>
                <span>{log.message}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
