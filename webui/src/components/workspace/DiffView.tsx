import { useEffect, useRef, useState } from "react";
import type * as Monaco from "monaco-editor";

import { loadMonaco, monacoLanguage } from "@/components/workspace/MonacoEditor";

type Editor = Monaco.editor.IStandaloneDiffEditor;

interface DiffViewProps {
  /** What is on disk now. */
  original: string;
  /** What the agent proposes. */
  modified: string;
  language: string;
  dark: boolean;
}

/** Read-only side-by-side diff of a proposal against the file on disk. Accept or reject happens outside. */
export function DiffView({ original, modified, language, dark }: DiffViewProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let disposed = false;
    let editor: Editor | null = null;
    let models: Monaco.editor.ITextModel[] = [];
    loadMonaco()
      .then((monaco) => {
        if (disposed || !hostRef.current) return;
        const lang = monacoLanguage(language);
        const originalModel = monaco.editor.createModel(original, lang);
        const modifiedModel = monaco.editor.createModel(modified, lang);
        models = [originalModel, modifiedModel];
        editor = monaco.editor.createDiffEditor(hostRef.current, {
          renderSideBySide: true,
          readOnly: true,
          automaticLayout: true,
          theme: dark ? "vs-dark" : "vs",
          minimap: { enabled: false },
        });
        editor.setModel({ original: originalModel, modified: modifiedModel });
      })
      .catch(() => {
        if (!disposed) setFailed(true);
      });
    return () => {
      disposed = true;
      editor?.dispose();
      models.forEach((model) => model.dispose());
    };
    // Re-created when the proposal itself changes; the editor is cheap to rebuild.
  }, [original, modified, language, dark]);

  if (failed) {
    return <div role="alert" className="p-4 text-sm text-red-600 dark:text-red-300">The diff could not be loaded.</div>;
  }
  return <div ref={hostRef} className="h-full min-h-[240px] w-full" data-testid="diff-host" />;
}
