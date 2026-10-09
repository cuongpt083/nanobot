/// <reference types="vite/client" />
import { useEffect, useRef, useState } from "react";
import type * as Monaco from "monaco-editor";

type MonacoModule = typeof Monaco;
type Editor = Monaco.editor.IStandaloneCodeEditor;

let monacoReady: Promise<MonacoModule> | null = null;

/**
 * Only the core editor API and monarch tokenizers load here. The full ``monaco-editor`` entry also
 * pulls in TypeScript, CSS, HTML and JSON language services with their own multi-megabyte workers,
 * which a read-and-edit pane does not use. JSON has no monarch tokenizer and shows as plain text.
 */
const LANGUAGE_MODULES: Record<string, () => Promise<unknown>> = {
  bash: () => import("monaco-editor/languages/definitions/shell/register"),
  css: () => import("monaco-editor/languages/definitions/css/register"),
  dockerfile: () => import("monaco-editor/languages/definitions/dockerfile/register"),
  html: () => import("monaco-editor/languages/definitions/html/register"),
  ini: () => import("monaco-editor/languages/definitions/ini/register"),
  javascript: () => import("monaco-editor/languages/definitions/javascript/register"),
  markdown: () => import("monaco-editor/languages/definitions/markdown/register"),
  python: () => import("monaco-editor/languages/definitions/python/register"),
  scss: () => import("monaco-editor/languages/definitions/scss/register"),
  typescript: () => import("monaco-editor/languages/definitions/typescript/register"),
  xml: () => import("monaco-editor/languages/definitions/xml/register"),
  yaml: () => import("monaco-editor/languages/definitions/yaml/register"),
};

export function loadMonaco(): Promise<MonacoModule> {
  if (!monacoReady) {
    monacoReady = (async () => {
      const [monaco, worker] = await Promise.all([
        import("monaco-editor/editor/editor.api"),
        import("monaco-editor/editor/editor.worker?worker"),
        ...Object.values(LANGUAGE_MODULES).map((load) => load()),
      ]);
      (globalThis as { MonacoEnvironment?: unknown }).MonacoEnvironment = {
        getWorker: () => new worker.default(),
      };
      return monaco as unknown as MonacoModule;
    })();
    // A failed download must not poison every later attempt in the session.
    monacoReady.catch(() => {
      monacoReady = null;
    });
  }
  return monacoReady;
}

export function monacoLanguage(language: string): string {
  const aliases: Record<string, string> = { jsx: "javascript", tsx: "typescript", sh: "bash", toml: "ini" };
  const mapped = aliases[language] ?? language;
  return mapped in LANGUAGE_MODULES ? mapped : "plaintext";
}

interface MonacoEditorProps {
  value: string;
  language: string;
  dark: boolean;
  onChange: (text: string) => void;
  onSave: () => void;
}

export function MonacoEditor({ value, language, dark, onChange, onSave }: MonacoEditorProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<Editor | null>(null);
  const monacoRef = useRef<MonacoModule | null>(null);
  const onChangeRef = useRef(onChange);
  const onSaveRef = useRef(onSave);
  const [failed, setFailed] = useState(false);
  onChangeRef.current = onChange;
  onSaveRef.current = onSave;

  useEffect(() => {
    let disposed = false;
    let editor: Editor | null = null;
    loadMonaco()
      .then((monaco) => {
        if (disposed || !hostRef.current) return;
        monacoRef.current = monaco;
        editor = monaco.editor.create(hostRef.current, {
          value,
          language: monacoLanguage(language),
          theme: dark ? "vs-dark" : "vs",
          automaticLayout: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 13,
          tabSize: 2,
          wordWrap: "on",
        });
        editor.onDidChangeModelContent(() => onChangeRef.current(editor?.getValue() ?? ""));
        editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => onSaveRef.current());
        editorRef.current = editor;
      })
      .catch(() => {
        if (!disposed) setFailed(true);
      });
    return () => {
      disposed = true;
      editor?.dispose();
      editorRef.current = null;
    };
    // The editor is created once per mount; later prop changes are applied by the effects below.
  }, []);

  // Replace the text only when it differs from the editor's own, so typing never moves the cursor.
  useEffect(() => {
    const editor = editorRef.current;
    if (editor && editor.getValue() !== value) editor.setValue(value);
  }, [value]);

  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    const model = editor?.getModel();
    if (monaco && model) monaco.editor.setModelLanguage(model, monacoLanguage(language));
  }, [language]);

  useEffect(() => {
    monacoRef.current?.editor.setTheme(dark ? "vs-dark" : "vs");
  }, [dark]);

  if (failed) {
    return (
      <div role="alert" className="p-4 text-sm text-red-600 dark:text-red-300">
        The code editor could not be loaded. The file can still be read in the preview.
      </div>
    );
  }
  return <div ref={hostRef} className="h-full min-h-[240px] w-full" data-testid="monaco-host" />;
}
