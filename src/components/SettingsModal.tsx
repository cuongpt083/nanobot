import React, { useState } from 'react';
import {
  Settings2,
  Sliders,
  Shield,
  FileCode,
  HardDrive,
  Cpu,
  Check,
  Save,
  Key
} from 'lucide-react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  systemPrompt: string;
  onSaveSystemPrompt: (prompt: string) => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  systemPrompt,
  onSaveSystemPrompt,
}) => {
  const [prompt, setPrompt] = useState(systemPrompt);
  const [sandboxEnabled, setSandboxEnabled] = useState(true);
  const [autoDreamInterval, setAutoDreamInterval] = useState('2');
  const [workspaceDir, setWorkspaceDir] = useState('./workspace');
  const [isSaved, setIsSaved] = useState(false);

  if (!isOpen) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    onSaveSystemPrompt(prompt);
    setIsSaved(true);
    setTimeout(() => {
      setIsSaved(false);
      onClose();
    }, 800);
  };

  return (
    <div className="fixed inset-0 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4 z-50">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
        <div className="p-5 border-b border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Settings2 className="w-5 h-5 text-amber-400" />
            <div>
              <h3 className="text-base font-bold text-zinc-100">Nanobot Gateway Settings</h3>
              <p className="text-xs text-zinc-400">Agent loop policies, persona, and runtime sandboxing</p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-300 text-sm p-1 rounded-lg hover:bg-zinc-800"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSave} className="p-6 space-y-5 overflow-y-auto flex-1 text-xs">
          {/* System Persona / SOUL.md */}
          <div className="space-y-2">
            <label className="block font-semibold text-zinc-200 flex items-center gap-2">
              <FileCode className="w-4 h-4 text-amber-400" />
              <span>System Prompt (`SOUL.md` Agent Persona)</span>
            </label>
            <textarea
              rows={5}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              className="w-full p-3 rounded-lg bg-zinc-950 border border-zinc-800 font-mono text-zinc-200 focus:outline-none focus:border-amber-500 leading-relaxed"
            />
            <p className="text-[11px] text-zinc-500">
              Defines the baseline personality, safety constraints, and execution guidelines for every session turn.
            </p>
          </div>

          {/* Sandbox & Security */}
          <div className="space-y-3 pt-3 border-t border-zinc-800">
            <h4 className="font-semibold text-zinc-200 flex items-center gap-2">
              <Shield className="w-4 h-4 text-emerald-400" />
              <span>Tool Execution Sandbox Policy</span>
            </h4>

            <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-950 border border-zinc-800">
              <div>
                <div className="font-medium text-zinc-200">Strict Command Path Isolation</div>
                <div className="text-[11px] text-zinc-500">
                  Restrict filesystem mutations and shell commands to the designated workspace root.
                </div>
              </div>
              <input
                type="checkbox"
                checked={sandboxEnabled}
                onChange={(e) => setSandboxEnabled(e.target.checked)}
                className="w-4 h-4 accent-amber-500 cursor-pointer"
              />
            </div>
          </div>

          {/* Dream Consolidation Settings */}
          <div className="space-y-3 pt-3 border-t border-zinc-800">
            <h4 className="font-semibold text-zinc-200 flex items-center gap-2">
              <HardDrive className="w-4 h-4 text-indigo-400" />
              <span>Dream Memory Consolidation Frequency</span>
            </h4>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-zinc-400 mb-1">Trigger Consolidation Every</label>
                <select
                  value={autoDreamInterval}
                  onChange={(e) => setAutoDreamInterval(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-zinc-200 focus:outline-none focus:border-amber-500"
                >
                  <option value="1">1 hour</option>
                  <option value="2">2 hours (Recommended)</option>
                  <option value="6">6 hours</option>
                  <option value="24">24 hours</option>
                </select>
              </div>

              <div>
                <label className="block text-zinc-400 mb-1">Workspace Root Directory</label>
                <input
                  type="text"
                  value={workspaceDir}
                  onChange={(e) => setWorkspaceDir(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
                />
              </div>
            </div>
          </div>

          <div className="pt-4 border-t border-zinc-800 flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex items-center gap-2 px-5 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold transition-colors shadow-md"
            >
              {isSaved ? <Check className="w-4 h-4 stroke-[3]" /> : <Save className="w-4 h-4" />}
              <span>{isSaved ? 'Saved!' : 'Save Settings'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
