import React, { useState, useEffect } from "react";
import { Sparkles } from "lucide-react";

interface ExpertUiToggleProps {
  onChange?: (enabled: boolean) => void;
}

export const EXPERT_UI_STORAGE_KEY = "nanobot_expert_mode_enabled";

export const ExpertUiToggle: React.FC<ExpertUiToggleProps> = ({ onChange }) => {
  const [enabled, setEnabled] = useState<boolean>(() => {
    try {
      return localStorage.getItem(EXPERT_UI_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(EXPERT_UI_STORAGE_KEY, enabled ? "true" : "false");
    } catch {
      // Ignore local storage errors
    }
    if (onChange) {
      onChange(enabled);
    }
  }, [enabled, onChange]);

  const handleToggle = () => {
    setEnabled((prev) => !prev);
  };

  return (
    <div className="flex items-center justify-between p-4 bg-card border rounded-lg shadow-sm">
      <div className="flex items-center space-x-3">
        <div className="p-2 bg-primary/10 rounded-md text-primary">
          <Sparkles className="w-5 h-5" />
        </div>
        <div>
          <h4 className="text-sm font-semibold flex items-center gap-2">
            Expert Mode UI
            <span className="text-xs px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground font-mono">
              Progressive Disclosure
            </span>
          </h4>
          <p className="text-xs text-muted-foreground mt-0.5">
            Reveal advanced SLM distillation controls, model presets, and telemetry panels.
          </p>
        </div>
      </div>

      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        onClick={handleToggle}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
          enabled ? "bg-primary" : "bg-muted"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-background transition-transform ${
            enabled ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
};
