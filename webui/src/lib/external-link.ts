/**
 * Opens an external URL in the system's default browser.
 * When running inside a native desktop shell (such as Tauri), delegates
 * to the native host command so that links open externally rather than
 * being blocked by the webview.
 */
export function openExternalUrl(url: string): void {
  if (!url) return;

  // 1. If running in Tauri native desktop environment:
  const tauri = (
    window as unknown as {
      __TAURI__?: {
        core?: {
          invoke: (
            cmd: string,
            args: Record<string, unknown>,
          ) => Promise<unknown>;
        };
      };
    }
  ).__TAURI__;

  if (tauri?.core?.invoke) {
    tauri.core.invoke("open_external_url", { url }).catch((err) => {
      console.warn("Failed to open external URL via Tauri command:", err);
      try {
        const win = window.open(url, "_blank", "noopener,noreferrer");
        if (win) win.opener = null;
      } catch {}
    });
    return;
  }

  // 2. Standard browser environment:
  try {
    const win = window.open(url, "_blank", "noopener,noreferrer");
    if (win) win.opener = null;
  } catch (err) {
    console.warn("window.open failed:", err);
  }
}
