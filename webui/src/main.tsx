import ReactDOM from "react-dom/client";

import App from "./App";
import "./globals.css";
import { initializeI18n } from "./i18n";
import { initializeLoopbackRuntimeHost } from "./lib/runtime";
import { desktopPerf } from "./lib/perf";

desktopPerf.mark("webui_index_exec");

// `crypto.randomUUID` is only defined in secure contexts (HTTPS or localhost).
// LAN access over plain HTTP leaves it undefined, which crashes components that
// generate client-side message IDs. Shim a v4-ish fallback so call sites stay
// uniform across secure and non-secure contexts.
if (typeof globalThis.crypto !== "undefined" && !("randomUUID" in globalThis.crypto)) {
  Object.defineProperty(globalThis.crypto, "randomUUID", {
    value: () =>
      "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      }),
    configurable: true,
  });
}

const root = document.getElementById("root");
if (!root) throw new Error("root element missing");

initializeLoopbackRuntimeHost();

async function renderWebui(container: HTMLElement) {
  desktopPerf.mark("webui_i18n_init_start");
  await initializeI18n();
  desktopPerf.mark("webui_i18n_init_end");
  desktopPerf.measure("i18n_init", "webui_i18n_init_start", "webui_i18n_init_end");
  /* StrictMode disabled: dev double-invokes state updaters; delta accumulation must stay pure — see useNanobotStream. */
  desktopPerf.mark("webui_render_root_start");
  ReactDOM.createRoot(container).render(<App />);
  desktopPerf.mark("webui_render_root_end");
}

void renderWebui(root);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js", {
        updateViaCache: "none",
      })
      .catch(() => {
        // Service workers are progressive enhancement; registration failures
        // (unsupported proxies, blocked storage) must not break the app.
      });
  });
}
