/**
 * The file and selection open in the workspace editor, offered to the next message in the same
 * session when the user has opted in (ED-14). Off by default; the choice is per browser.
 */

export interface EditorContext {
  path: string;
  start_line?: number;
  end_line?: number;
  /** Selected text, bounded; only present when there is a selection. */
  selection?: string;
}

export const EDITOR_CONTEXT_SELECTION_MAX_CHARS = 4_000;
const STORAGE_KEY = "nanobot.shareEditorContext";

interface Published {
  sessionKey: string;
  context: EditorContext;
}

let published: Published | null = null;

function readShared(): boolean {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

let shared = readShared();

export function isEditorContextShared(): boolean {
  return shared;
}

export function setEditorContextShared(value: boolean): void {
  shared = value;
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    // Storage can be blocked; the choice then lasts for this page only.
  }
}

/** Record what the editor shows for a session, or clear it (``null``) when the editor closes. */
export function publishEditorContext(sessionKey: string, context: EditorContext | null): void {
  published = context ? { sessionKey, context } : null;
}

/** The context to attach to a message in ``sessionKey``: only when shared and for that session. */
export function readSharedEditorContext(sessionKey: string | null): EditorContext | null {
  if (!shared || !sessionKey || !published || published.sessionKey !== sessionKey) return null;
  return published.context;
}
