import React from 'react';
import {
  Laptop,
  Command,
  Bell,
  Download,
  CheckCircle2,
  ExternalLink,
  Shield,
  Layers,
  Sparkles
} from 'lucide-react';
import { DesktopSettings, DesktopReleaseInfo } from '../../../types';

interface DesktopConfigTabProps {
  settings: DesktopSettings;
  onUpdateSettings: (newSettings: Partial<DesktopSettings>) => void;
  releases: DesktopReleaseInfo[];
}

export const DesktopConfigTab: React.FC<DesktopConfigTabProps> = ({
  settings,
  onUpdateSettings,
  releases,
}) => {
  return (
    <div className="flex flex-col h-full space-y-5 text-zinc-300 overflow-y-auto pr-1">
      {/* Desktop App Preferences */}
      <div className="space-y-4 max-w-2xl">
        <h4 className="text-xs font-bold text-zinc-100 uppercase tracking-wider">
          Window & System Appearance
        </h4>

        <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-200">Window Header Style</label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => onUpdateSettings({ windowFrame: 'macos' })}
                className={`p-3 text-left rounded-xl border transition-all cursor-pointer ${
                  settings.windowFrame === 'macos'
                    ? 'bg-amber-500/10 border-amber-500 text-amber-300 font-bold'
                    : 'bg-zinc-900/60 border-zinc-800 text-zinc-400'
                }`}
              >
                <div className="text-xs">macOS Traffic Lights</div>
                <div className="text-[10px] text-zinc-500 mt-0.5">Native red/yellow/green control pills</div>
              </button>

              <button
                type="button"
                onClick={() => onUpdateSettings({ windowFrame: 'windows' })}
                className={`p-3 text-left rounded-xl border transition-all cursor-pointer ${
                  settings.windowFrame === 'windows'
                    ? 'bg-amber-500/10 border-amber-500 text-amber-300 font-bold'
                    : 'bg-zinc-900/60 border-zinc-800 text-zinc-400'
                }`}
              >
                <div className="text-xs">Modern Frameless</div>
                <div className="text-[10px] text-zinc-500 mt-0.5">Sleek minimalist desktop banner</div>
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-zinc-800/60">
            <div>
              <div className="text-xs font-semibold text-zinc-200">Keep Window Always on Top</div>
              <div className="text-[10px] text-zinc-500">Pin floating agent window above other desktop apps</div>
            </div>
            <button
              onClick={() => onUpdateSettings({ alwaysOnTop: !settings.alwaysOnTop })}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                settings.alwaysOnTop ? 'bg-amber-500' : 'bg-zinc-800'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-zinc-950 transition-transform ${
                  settings.alwaysOnTop ? 'translate-x-4.5' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-zinc-800/60">
            <div>
              <div className="text-xs font-semibold text-zinc-200">System Notification Alerts</div>
              <div className="text-[10px] text-zinc-500">Notify when background subagents or cron jobs complete</div>
            </div>
            <button
              onClick={() => onUpdateSettings({ notificationsEnabled: !settings.notificationsEnabled })}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                settings.notificationsEnabled ? 'bg-amber-500' : 'bg-zinc-800'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-zinc-950 transition-transform ${
                  settings.notificationsEnabled ? 'translate-x-4.5' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
        </div>
      </div>

      {/* Desktop Releases & Native Installers */}
      <div className="space-y-3 pt-2">
        <h4 className="text-xs font-bold text-zinc-100 uppercase tracking-wider flex items-center gap-1.5">
          <Download className="w-3.5 h-3.5 text-amber-400" />
          <span>Standalone Desktop Installers</span>
        </h4>

        <div className="grid grid-cols-3 gap-3">
          {releases.map((rel) => (
            <div
              key={rel.platform}
              className="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800/80 space-y-2 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-zinc-200">{rel.platformName}</span>
                  <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400">
                    {rel.arch}
                  </span>
                </div>
                <div className="text-[10px] text-zinc-500 mt-1 font-mono">{rel.filename} ({rel.size})</div>
              </div>

              <button
                onClick={() => window.open(rel.downloadUrl, '_blank')}
                className="w-full py-1.5 rounded-lg bg-zinc-800 hover:bg-amber-500 hover:text-zinc-950 text-zinc-300 text-xs font-semibold transition-colors flex items-center justify-center gap-1 cursor-pointer"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Download {rel.platformName}</span>
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
