/**
 * Typing a project file path after ``@`` in the composer (ED-13). A bare ``@`` belongs to the app and session
 * mentions, so a file suggestion is offered only once the token looks like a path (it has a ``/`` or a ``.``).
 */

export interface FileMentionQuery {
  /** The folder typed so far, project-relative, without a trailing slash; empty for the project root. */
  folder: string;
  /** The part of the name typed after the last slash. */
  prefix: string;
  /** Offset of the ``@`` in the text, and the caret offset at the end of the token. */
  start: number;
  end: number;
}

export interface FileListEntry {
  name: string;
  kind: string;
}

const MAX_SUGGESTIONS = 8;

export function fileMentionAt(value: string, caret: number): FileMentionQuery | null {
  const before = value.slice(0, Math.min(Math.max(caret, 0), value.length));
  const match = /(?:^|\s)@([^\s@]*)$/.exec(before);
  if (!match) return null;
  const token = match[1];
  if (!token.includes("/") && !token.includes(".")) return null;
  const slash = token.lastIndexOf("/");
  return {
    folder: slash >= 0 ? token.slice(0, slash) : "",
    prefix: slash >= 0 ? token.slice(slash + 1) : token,
    start: before.length - token.length - 1,
    end: before.length,
  };
}

/** The text with the token replaced by the chosen path. A folder keeps the slash so the menu opens inside it. */
export function applyFileMention(
  value: string,
  query: FileMentionQuery,
  path: string,
  isFolder: boolean,
): { value: string; cursor: number } {
  const insert = isFolder ? `@${path}/` : `@${path} `;
  const next = value.slice(0, query.start) + insert + value.slice(query.end);
  return { value: next, cursor: query.start + insert.length };
}

/** Entries whose name starts with ``prefix`` (case-insensitive), folders first. Hidden names need a dot prefix. */
export function filterEntries(entries: FileListEntry[], prefix: string): FileListEntry[] {
  const wanted = prefix.toLowerCase();
  return entries
    .filter((entry) => entry.name.toLowerCase().startsWith(wanted))
    .filter((entry) => !entry.name.startsWith(".") || wanted.startsWith("."))
    .sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name, undefined, { numeric: true });
    })
    .slice(0, MAX_SUGGESTIONS);
}
