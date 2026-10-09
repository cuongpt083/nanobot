/**
 * Changes to project files that the gateway reports (fs.changed): a small bus, so the editor can re-read a file
 * the moment it changes without the client and the editor knowing about each other.
 */

export interface WorkspaceChange {
  sessionKey: string;
  path: string;
}

type Handler = (change: WorkspaceChange) => void;

const handlers = new Set<Handler>();

export function onWorkspaceChange(handler: Handler): () => void {
  handlers.add(handler);
  return () => {
    handlers.delete(handler);
  };
}

export function emitWorkspaceChange(change: WorkspaceChange): void {
  for (const handler of [...handlers]) {
    try {
      handler(change);
    } catch {
      // One listener failing must not stop the others from hearing the change.
    }
  }
}
