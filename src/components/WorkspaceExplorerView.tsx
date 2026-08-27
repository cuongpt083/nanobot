import React, { useState, useEffect } from 'react';
import {
  FolderOpen,
  FileCode,
  Save,
  Check,
  Play,
  Terminal,
  Plus,
  Trash2,
  HardDrive,
  RefreshCw,
  FolderTree,
  Shield,
  Layers,
  Code
} from 'lucide-react';
import { LocalFileItem } from '../types';

interface WorkspaceExplorerViewProps {
  workspacePath: string;
}

export const WorkspaceExplorerView: React.FC<WorkspaceExplorerViewProps> = ({
  workspacePath,
}) => {
  const [files, setFiles] = useState<LocalFileItem[]>([]);
  const [selectedFile, setSelectedFile] = useState<LocalFileItem | null>(null);
  const [fileContent, setFileContent] = useState('');
  const [isSaved, setIsSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Terminal state
  const [terminalInput, setTerminalInput] = useState('nanobot status');
  const [terminalLogs, setTerminalLogs] = useState<
    Array<{ command: string; output: string; time: string }>
  >([
    {
      command: 'nanobot status',
      output: 'Nanobot Desktop v0.3.0\nGateway: Online (port 3000)\nMCP Servers: 5 connected\nModel: gemini-2.5-flash',
      time: new Date().toLocaleTimeString(),
    },
  ]);
  const [isExecutingCmd, setIsExecutingCmd] = useState(false);

  useEffect(() => {
    fetchWorkspace();
  }, []);

  const fetchWorkspace = async () => {
    try {
      const res = await fetch('/api/desktop/workspace');
      if (res.ok) {
        const data = await res.json();
        setFiles(data.files || []);
        if (data.files && data.files.length > 0 && !selectedFile) {
          setSelectedFile(data.files[0]);
          setFileContent(data.files[0].content || '');
        }
      }
    } catch (e) {
      console.error('Failed to fetch workspace:', e);
    }
  };

  const handleSelectFile = (file: LocalFileItem) => {
    setSelectedFile(file);
    setFileContent(file.content || '');
    setIsSaved(false);
  };

  const handleSaveFile = async () => {
    if (!selectedFile) return;
    setIsSaving(true);
    try {
      const res = await fetch('/api/desktop/workspace/file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: selectedFile.id,
          name: selectedFile.name,
          content: fileContent,
        }),
      });
      if (res.ok) {
        const updated = await res.json();
        setFiles((prev) => prev.map((f) => (f.id === updated.id ? updated : f)));
        setIsSaved(true);
        setTimeout(() => setIsSaved(false), 2000);
      }
    } catch (e) {
      console.error('Failed to save file:', e);
    } finally {
      setIsSaving(false);
    }
  };

  const handleRunCommand = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!terminalInput.trim() || isExecutingCmd) return;

    const cmd = terminalInput;
    setIsExecutingCmd(true);
    setTerminalInput('');

    try {
      const res = await fetch('/api/desktop/workspace/exec', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd }),
      });
      if (res.ok) {
        const data = await res.json();
        setTerminalLogs((prev) => [
          ...prev,
          {
            command: cmd,
            output: data.output,
            time: new Date().toLocaleTimeString(),
          },
        ]);
      }
    } catch (e: any) {
      setTerminalLogs((prev) => [
        ...prev,
        {
          command: cmd,
          output: `Execution error: ${e.message}`,
          time: new Date().toLocaleTimeString(),
        },
      ]);
    } finally {
      setIsExecutingCmd(false);
    }
  };

  return (
    <div className="h-full flex overflow-hidden bg-zinc-950 text-zinc-100">
      {/* File Tree Drawer */}
      <div className="w-72 border-r border-zinc-800/80 bg-zinc-900/40 flex flex-col justify-between">
        <div className="p-4 border-b border-zinc-800/80">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-xs font-bold text-zinc-100 flex items-center gap-2">
              <FolderTree className="w-4 h-4 text-amber-400" />
              <span>Workspace Files</span>
            </h3>
            <span className="text-[10px] font-mono text-zinc-500">Local Mount</span>
          </div>
          <div className="text-[10px] font-mono text-zinc-400 bg-zinc-950 px-2 py-1 rounded border border-zinc-800 mt-2 truncate">
            {workspacePath}
          </div>
        </div>

        {/* File items list */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {files.map((file) => {
            const isSelected = selectedFile?.id === file.id;

            return (
              <div
                key={file.id}
                onClick={() => handleSelectFile(file)}
                className={`p-2.5 rounded-lg border cursor-pointer transition-all flex items-center justify-between ${
                  isSelected
                    ? 'bg-zinc-800/90 border-amber-500/50 text-zinc-100'
                    : 'bg-zinc-900/30 border-transparent text-zinc-400 hover:bg-zinc-850 hover:text-zinc-200'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <FileCode className={`w-4 h-4 flex-shrink-0 ${isSelected ? 'text-amber-400' : 'text-zinc-500'}`} />
                  <span className="text-xs font-mono truncate">{file.name}</span>
                </div>
                <span className="text-[10px] font-mono text-zinc-500 flex-shrink-0">{file.size}</span>
              </div>
            );
          })}
        </div>

        {/* Sandbox Isolation Status */}
        <div className="p-3 border-t border-zinc-800/80 bg-zinc-950/60 text-[11px] text-zinc-500 flex items-center gap-2">
          <Shield className="w-3.5 h-3.5 text-emerald-400" />
          <span>Restricted to sandbox root</span>
        </div>
      </div>

      {/* Center: File Editor & Terminal Sandbox */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Editor Toolbar */}
        <div className="h-12 border-b border-zinc-800 bg-zinc-900/60 flex items-center justify-between px-5">
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold font-mono text-zinc-200">
              {selectedFile ? selectedFile.name : 'Select a file'}
            </span>
            {selectedFile && (
              <span className="text-[10px] font-mono text-zinc-500">
                Modified: {selectedFile.modified}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleSaveFile}
              disabled={isSaving || !selectedFile}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-bold text-xs rounded-lg transition-colors cursor-pointer disabled:opacity-50 shadow-xs"
            >
              {isSaved ? <Check className="w-3.5 h-3.5 stroke-[3]" /> : <Save className="w-3.5 h-3.5" />}
              <span>{isSaved ? 'Saved to Disk' : isSaving ? 'Saving...' : 'Save File'}</span>
            </button>
          </div>
        </div>

        {/* Editor Code Area */}
        <div className="flex-1 p-4 bg-zinc-950 overflow-hidden flex flex-col">
          <textarea
            value={fileContent}
            onChange={(e) => {
              setFileContent(e.target.value);
              setIsSaved(false);
            }}
            placeholder="Select or write file content..."
            className="w-full flex-1 bg-zinc-900/50 border border-zinc-800 rounded-xl p-4 font-mono text-xs text-zinc-200 focus:outline-none focus:border-amber-500/80 leading-relaxed resize-none"
          />
        </div>

        {/* Bottom Embedded Terminal Sandbox */}
        <div className="h-56 border-t border-zinc-800 bg-zinc-950 flex flex-col">
          <div className="h-8 bg-zinc-900/90 border-b border-zinc-800 px-4 flex items-center justify-between text-[11px] font-mono text-zinc-400">
            <div className="flex items-center gap-2">
              <Terminal className="w-3.5 h-3.5 text-amber-400" />
              <span>Desktop Shell Bridge (`bash` / `cmd`)</span>
            </div>
            <span className="text-[10px] text-zinc-500">Host OS: Localhost sandbox</span>
          </div>

          {/* Terminal output logs */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2 font-mono text-[11px]">
            {terminalLogs.map((log, idx) => (
              <div key={idx} className="space-y-1">
                <div className="text-zinc-400 flex items-center gap-1.5">
                  <span className="text-amber-400 font-bold">$</span>
                  <span>{log.command}</span>
                  <span className="text-[9px] text-zinc-600 ml-auto">{log.time}</span>
                </div>
                <pre className="text-emerald-400/90 pl-3.5 whitespace-pre-wrap leading-relaxed">
                  {log.output}
                </pre>
              </div>
            ))}
          </div>

          {/* Terminal command input */}
          <form
            onSubmit={handleRunCommand}
            className="h-10 border-t border-zinc-800/80 bg-zinc-900/40 px-3 flex items-center gap-2"
          >
            <span className="text-amber-400 font-mono font-bold text-xs">$</span>
            <input
              type="text"
              value={terminalInput}
              onChange={(e) => setTerminalInput(e.target.value)}
              placeholder="Run sandbox command (ls, cat, nanobot status, git...)"
              className="flex-1 bg-transparent text-xs font-mono text-zinc-200 focus:outline-none placeholder-zinc-600"
            />
            <button
              type="submit"
              disabled={isExecutingCmd}
              className="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-mono rounded cursor-pointer"
            >
              {isExecutingCmd ? '...' : 'Execute'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
