import { File, Folder } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { FileListEntry } from "@/lib/file-mention";
import { cn } from "@/lib/utils";

interface FileMentionPaletteProps {
  folder: string;
  candidates: FileListEntry[];
  selectedIndex: number;
  onHover: (index: number) => void;
  onChoose: (entry: FileListEntry) => void;
}

/** Project files and folders offered after ``@path`` in the composer. Keyboard use is handled by the composer. */
export function FileMentionPalette({ folder, candidates, selectedIndex, onHover, onChoose }: FileMentionPaletteProps) {
  const { t } = useTranslation();
  return (
    <div role="listbox" aria-label={t("thread.composer.fileMentions", { defaultValue: "Project files" })}
      className="absolute bottom-full left-0 right-0 z-20 mb-2 max-h-64 overflow-auto rounded-md border border-border bg-popover p-1 text-sm shadow-md">
      {candidates.map((entry, index) => {
        const path = folder ? `${folder}/${entry.name}` : entry.name;
        const isFolder = entry.kind === "dir";
        return (
          <button key={path} type="button" role="option" aria-selected={index === selectedIndex}
            onMouseEnter={() => onHover(index)}
            onMouseDown={(event) => {
              event.preventDefault();
              onChoose(entry);
            }}
            className={cn("flex w-full items-center gap-2 rounded px-2 py-1 text-left",
              index === selectedIndex ? "bg-muted" : "text-muted-foreground")}>
            {isFolder ? <Folder className="h-3.5 w-3.5 shrink-0" aria-hidden /> : <File className="h-3.5 w-3.5 shrink-0" aria-hidden />}
            <span className="truncate">{path}{isFolder ? "/" : ""}</span>
          </button>
        );
      })}
    </div>
  );
}
