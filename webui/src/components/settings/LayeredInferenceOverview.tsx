import React from "react";
import { Server, Cpu, Layers, ArrowRightLeft } from "lucide-react";

interface LayeredInferenceOverviewProps {
  status?: string;
  activeModelId?: string;
  teacherPreset?: string;
  phaseADecision?: "go" | "no_go" | "inconclusive";
}

export const LayeredInferenceOverview: React.FC<LayeredInferenceOverviewProps> = ({
  status: _status = "ready",
  activeModelId = "qwen3-4b-pilot-q5_k_m",
  teacherPreset = "deepseek-v4-flash",
  phaseADecision = "go",
}) => {
  const getDecisionBadge = () => {
    switch (phaseADecision) {
      case "go":
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-md bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">Gate: Passed (GO)</span>;
      case "no_go":
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-md bg-destructive/10 text-destructive border border-destructive/20">Gate: Failed (NO GO)</span>;
      default:
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-md bg-amber-500/10 text-amber-600 border border-amber-500/20">Gate: Inconclusive</span>;
    }
  };

  return (
    <div className="space-y-4">
      {/* Capability Banner */}
      <div className="p-4 border rounded-lg bg-card space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Layers className="w-5 h-5 text-primary" />
            <h3 className="text-base font-semibold">Layered Inference & SLM Runtime</h3>
          </div>
          {getDecisionBadge()}
        </div>

        <p className="text-xs text-muted-foreground">
          Deterministic model router routes simple queries to the local Student SLM model and delegates complex reasoning or tool tasks directly to the Teacher LLM preset.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
          <div className="p-3 bg-muted/40 rounded-md border flex items-center space-x-3">
            <Cpu className="w-4 h-4 text-muted-foreground" />
            <div>
              <div className="text-xs text-muted-foreground">Student SLM Model</div>
              <div className="text-xs font-mono font-medium">{activeModelId}</div>
            </div>
          </div>

          <div className="p-3 bg-muted/40 rounded-md border flex items-center space-x-3">
            <Server className="w-4 h-4 text-muted-foreground" />
            <div>
              <div className="text-xs text-muted-foreground">Teacher LLM Preset</div>
              <div className="text-xs font-mono font-medium">{teacherPreset}</div>
            </div>
          </div>

          <div className="p-3 bg-muted/40 rounded-md border flex items-center space-x-3">
            <ArrowRightLeft className="w-4 h-4 text-muted-foreground" />
            <div>
              <div className="text-xs text-muted-foreground">Routing Logic</div>
              <div className="text-xs font-medium">Simple &rarr; Student | Complex &rarr; Teacher</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
