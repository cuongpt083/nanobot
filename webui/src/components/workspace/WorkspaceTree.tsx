import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, File, Folder, FilePlus, Pencil, Trash2 } from "lucide-react";

import {
  deleteWorkspaceFile,
  listWorkspaceDir,
  renameWorkspaceFile,
  saveWorkspaceFile,
  type WebUIMutationTransport,
  type WorkspaceDirEntry,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface WorkspaceTreeProps {
  sessionKey: string;
  token: string;
  client: WebUIMutationTransport;
  base?: string;
  activePath: string | null;
  onOpen: (path: string) => void;
  /** A file was renamed or deleted; the caller updates or closes any open tab for it. */
  onRenamed: (from: string, to: string) => void;
  onDeleted: (path: string) => void;
  onError: (message: string) => void;
}

const join = (folder: string, name: string) => (folder ? `${folder}/${name}` : name);

export function WorkspaceTree({
  sessionKey,
  token,
  client,
  base = "",
  activePath,
  onOpen,
  onRenamed,
  onDeleted,
  onError,
}: WorkspaceTreeProps) {
  const [children, setChildren] = useState<Record<string, WorkspaceDirEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [truncated, setTruncated] = useState(false);

  const load = useCallback(async (folder: string) => {
    try {
      const listing = await listWorkspaceDir(token, sessionKey, folder, base);
      setChildren((current) => ({ ...current, [folder]: listing.entries }));
      if (folder === "") setTruncated(listing.truncated);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Could not list the folder");
    }
  }, [base, onError, sessionKey, token]);

  useEffect(() => {
    void load("");
  }, [load]);

  const toggle = (folder: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(folder)) next.delete(folder);
      else next.add(folder);
      return next;
    });
    if (!children[folder]) void load(folder);
  };

  const createFile = async (folder: string) => {
    const name = window.prompt("New file name");
    if (!name?.trim()) return;
    const path = join(folder, name.trim());
    try {
      await saveWorkspaceFile(client, sessionKey, { path, content: "", baseVersion: null });
      await load(folder);
      onOpen(path);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Could not create the file");
    }
  };

  const rename = async (folder: string, entry: WorkspaceDirEntry) => {
    const name = window.prompt("Rename to", entry.name);
    if (!name?.trim() || name.trim() === entry.name) return;
    const from = join(folder, entry.name);
    try {
      const result = await renameWorkspaceFile(client, sessionKey, from, name.trim());
      onRenamed(from, result.path);
      await load(folder);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Could not rename the file");
    }
  };

  const remove = async (folder: string, entry: WorkspaceDirEntry) => {
    const path = join(folder, entry.name);
    if (!window.confirm(`Delete ${entry.name}? This cannot be undone.`)) return;
    try {
      await deleteWorkspaceFile(client, sessionKey, path, null);
      onDeleted(path);
      await load(folder);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Could not delete the file");
    }
  };

  const renderFolder = (folder: string, depth: number): React.ReactNode => {
    const entries = children[folder] ?? [];
    return entries.map((entry) => {
      const path = join(folder, entry.name);
      const isDir = entry.kind === "dir";
      const isOpen = isDir && expanded.has(path);
      return (
        <div key={path}>
          <div
            className={cn(
              "group flex items-center gap-1 rounded px-1 py-0.5 text-sm hover:bg-muted",
              activePath === path && "bg-muted font-medium",
            )}
            style={{ paddingLeft: `${depth * 12 + 4}px` }}
          >
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-1 text-left"
              onClick={() => (isDir ? toggle(path) : onOpen(path))}
              aria-expanded={isDir ? isOpen : undefined}
            >
              {isDir
                ? (isOpen ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />)
                : <span className="w-3.5 shrink-0" />}
              {isDir ? <Folder className="h-3.5 w-3.5 shrink-0" /> : <File className="h-3.5 w-3.5 shrink-0" />}
              <span className="truncate">{entry.name}</span>
            </button>
            {!isDir ? (
              <span className="hidden gap-0.5 group-hover:flex">
                <button type="button" aria-label={`Rename ${entry.name}`} className="p-0.5"
                  onClick={() => void rename(folder, entry)}>
                  <Pencil className="h-3 w-3" />
                </button>
                <button type="button" aria-label={`Delete ${entry.name}`} className="p-0.5"
                  onClick={() => void remove(folder, entry)}>
                  <Trash2 className="h-3 w-3" />
                </button>
              </span>
            ) : null}
          </div>
          {isOpen ? renderFolder(path, depth + 1) : null}
        </div>
      );
    });
  };

  return (
    <div className="flex h-full flex-col overflow-hidden text-sm">
      <div className="flex items-center justify-between border-b border-border/50 px-2 py-1">
        <span className="text-xs font-medium uppercase text-muted-foreground">Files</span>
        <button type="button" aria-label="New file" className="p-0.5" onClick={() => void createFile("")}>
          <FilePlus className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex-1 overflow-auto py-1">
        {renderFolder("", 0)}
        {truncated ? (
          <p className="px-3 py-2 text-xs text-muted-foreground">Only the first entries are shown.</p>
        ) : null}
      </div>
    </div>
  );
}
