import React, { useState, useEffect } from 'react';
import {
  Download,
  Laptop,
  Check,
  Copy,
  Terminal,
  Shield,
  Cpu,
  Layers,
  Sparkles,
  ExternalLink,
  HardDrive,
  FileCode,
  CheckCircle2,
  FolderTree
} from 'lucide-react';
import { DesktopReleaseInfo } from '../types';

export const DesktopInstallerView: React.FC = () => {
  const [releases, setReleases] = useState<DesktopReleaseInfo[]>([]);
  const [cliCommands, setCliCommands] = useState<Record<string, string>>({});
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [downloadingFile, setDownloadingFile] = useState<string | null>(null);

  useEffect(() => {
    fetchReleases();
  }, []);

  const fetchReleases = async () => {
    try {
      const res = await fetch('/api/desktop/releases');
      if (res.ok) {
        const data = await res.json();
        setReleases(data.releases || []);
        setCliCommands(data.quickInstallCli || {});
      }
    } catch (e) {
      console.error('Failed to fetch releases:', e);
    }
  };

  const handleCopy = (key: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleDownload = (filename: string) => {
    setDownloadingFile(filename);
    setTimeout(() => {
      setDownloadingFile(null);
      // Simulate file download trigger
      const element = document.createElement('a');
      const file = new Blob([`# Nanobot Desktop Binary Installer\nPackage: ${filename}\nVersion: 0.3.0`], {
        type: 'text/plain',
      });
      element.href = URL.createObjectURL(file);
      element.download = filename;
      document.body.appendChild(element);
      element.click();
      document.body.removeChild(element);
    }, 800);
  };

  return (
    <div className="h-full overflow-y-auto p-8 max-w-5xl mx-auto space-y-8 text-zinc-100">
      {/* Top Banner */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2.5 mb-2">
            <div className="p-2 rounded-xl bg-amber-500/20 text-amber-400 border border-amber-500/30">
              <Laptop className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-zinc-100">Nanobot Desktop App (Claude Desktop Alternative)</h2>
              <div className="text-xs text-zinc-400">Native Electron 34 • Model Context Protocol (MCP) • Global Alt+Space Hotkey</div>
            </div>
          </div>
          <p className="text-xs text-zinc-400 max-w-2xl leading-relaxed mt-2">
            Install Nanobot as a standalone desktop application for macOS, Windows, and Linux with native filesystem sandbox isolation, Claude Desktop MCP server parity, and instant background gateway syncing.
          </p>
        </div>
      </div>

      {/* Feature Highlights Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800 flex items-start gap-3">
          <div className="p-2.5 rounded-lg bg-amber-500/10 text-amber-400">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs font-bold text-zinc-100">Claude Desktop MCP Parity</div>
            <div className="text-[11px] text-zinc-400 mt-0.5">
              Supports stdio and SSE MCP servers with auto-sync to <code className="text-amber-400">claude_desktop_config.json</code>.
            </div>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800 flex items-start gap-3">
          <div className="p-2.5 rounded-lg bg-emerald-500/10 text-emerald-400">
            <Shield className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs font-bold text-zinc-100">Local OS Security Sandbox</div>
            <div className="text-[11px] text-zinc-400 mt-0.5">
              Strict path isolation, safe command filtering, and zero remote data leakage.
            </div>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-zinc-900/60 border border-zinc-800 flex items-start gap-3">
          <div className="p-2.5 rounded-lg bg-sky-500/10 text-sky-400">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs font-bold text-zinc-100">Alt + Space Quick Summon</div>
            <div className="text-[11px] text-zinc-400 mt-0.5">
              Spotlight-style floating agent palette accessible anywhere across your OS.
            </div>
          </div>
        </div>
      </div>

      {/* Official Desktop Releases */}
      <div className="space-y-4">
        <h3 className="text-sm font-bold text-zinc-200 uppercase tracking-wider flex items-center gap-2">
          <Download className="w-4 h-4 text-amber-400" />
          <span>Official Desktop Installers (v0.3.0)</span>
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {releases.map((rel) => (
            <div
              key={rel.filename}
              className="p-5 rounded-2xl bg-zinc-900/80 border border-zinc-800 flex flex-col justify-between space-y-4 hover:border-zinc-700 transition-all"
            >
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-zinc-100">{rel.platformName}</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">
                    {rel.size}
                  </span>
                </div>
                <div className="text-[11px] font-mono text-zinc-400">{rel.filename}</div>

                <div className="mt-3 space-y-1 text-[11px] text-zinc-400">
                  {rel.instructions.map((inst, i) => (
                    <div key={i} className="flex items-start gap-1.5">
                      <span className="text-amber-400 font-bold">•</span>
                      <span>{inst}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="pt-3 border-t border-zinc-800/80 flex items-center justify-between">
                <span className="text-[10px] font-mono text-zinc-500">SHA256 Verified</span>
                <button
                  id={`btn-dl-${rel.arch}`}
                  onClick={() => handleDownload(rel.filename)}
                  disabled={downloadingFile === rel.filename}
                  className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold text-xs rounded-lg transition-colors cursor-pointer disabled:opacity-50 shadow-xs"
                >
                  <Download className="w-3.5 h-3.5 stroke-[2.5]" />
                  <span>
                    {downloadingFile === rel.filename ? 'Downloading...' : 'Download Installer'}
                  </span>
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 1-Click CLI Setup */}
      <div className="p-6 rounded-2xl bg-zinc-900/60 border border-zinc-800 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-zinc-200 flex items-center gap-2">
            <Terminal className="w-4 h-4 text-emerald-400" />
            <span>Instant Terminal & Package Manager Commands</span>
          </h3>
          <span className="text-xs text-zinc-500 font-mono">No installer required</span>
        </div>

        <div className="space-y-2.5">
          {Object.entries(cliCommands).map(([key, cmd]) => (
            <div
              key={key}
              className="p-3 rounded-xl bg-zinc-950 border border-zinc-800 flex items-center justify-between gap-4 font-mono text-xs"
            >
              <div className="flex items-center gap-3 overflow-hidden">
                <span className="text-amber-400 font-bold uppercase text-[10px] w-14 flex-shrink-0">
                  {key}
                </span>
                <span className="text-zinc-300 truncate">{cmd}</span>
              </div>

              <button
                onClick={() => handleCopy(key, cmd)}
                className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200 p-1 rounded hover:bg-zinc-800 cursor-pointer flex-shrink-0"
              >
                {copiedKey === key ? (
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
                <span>{copiedKey === key ? 'Copied' : 'Copy'}</span>
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
