import React, { useState, useEffect } from 'react';
import {
  Code,
  Check,
  AlertCircle,
  Save,
  RotateCcw,
  Sparkles,
  Copy,
  CheckCheck
} from 'lucide-react';
import { NanobotFullConfig } from '../../../types';

interface RawConfigTabProps {
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: NanobotFullConfig) => void;
}

export const RawConfigTab: React.FC<RawConfigTabProps> = ({
  config,
  onUpdateConfig,
}) => {
  const [jsonText, setJsonText] = useState<string>('');
  const [parseError, setParseError] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean>(false);
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false);

  useEffect(() => {
    setJsonText(JSON.stringify(config, null, 2));
  }, [config]);

  const handleFormat = () => {
    try {
      const parsed = JSON.parse(jsonText);
      setJsonText(JSON.stringify(parsed, null, 2));
      setParseError(null);
    } catch (err: any) {
      setParseError(err.message);
    }
  };

  const handleApply = () => {
    try {
      const parsed = JSON.parse(jsonText);
      onUpdateConfig(parsed);
      setParseError(null);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
    } catch (err: any) {
      setParseError(err.message);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(jsonText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-col h-full space-y-3 text-zinc-300">
      {/* Top Banner */}
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-xs font-bold text-zinc-100 flex items-center gap-2">
            <Code className="w-4 h-4 text-amber-400" />
            <span>Direct JSON Configuration (~/.nanobot/config.json)</span>
          </h4>
          <p className="text-[11px] text-zinc-500">
            Edit schema fields directly with runtime syntax validation.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-xs text-zinc-300 transition-colors border border-zinc-800"
          >
            {copied ? <CheckCheck className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'Copied' : 'Copy JSON'}</span>
          </button>
          <button
            onClick={handleFormat}
            className="px-3 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 text-xs text-zinc-300 transition-colors border border-zinc-800 cursor-pointer"
          >
            Prettify JSON
          </button>
          <button
            onClick={handleApply}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-bold transition-colors cursor-pointer"
          >
            {saveSuccess ? <Check className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
            <span>{saveSuccess ? 'Saved to Disk' : 'Apply Changes'}</span>
          </button>
        </div>
      </div>

      {parseError && (
        <div className="p-2.5 rounded-lg bg-rose-950/50 border border-rose-800/80 text-rose-300 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-rose-400" />
          <span>Invalid JSON: {parseError}</span>
        </div>
      )}

      {/* Code Editor Area */}
      <div className="flex-1 min-h-0 rounded-xl bg-zinc-950 border border-zinc-800 overflow-hidden flex flex-col">
        <textarea
          value={jsonText}
          onChange={(e) => {
            setJsonText(e.target.value);
            try {
              JSON.parse(e.target.value);
              setParseError(null);
            } catch (err: any) {
              setParseError(err.message);
            }
          }}
          spellCheck={false}
          className="flex-1 w-full bg-zinc-950 p-4 font-mono text-xs text-zinc-200 resize-none focus:outline-none leading-relaxed"
        />
      </div>
    </div>
  );
};
