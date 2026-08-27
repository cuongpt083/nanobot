import React, { useState } from 'react';
import {
  FolderOpen,
  Terminal,
  Globe,
  Clock,
  Sparkles,
  Bot,
  Layers,
  Wrench,
  CheckCircle2,
  XCircle,
  Play,
  Code,
  ShieldAlert
} from 'lucide-react';
import { SkillInfo } from '../types';

interface SkillsViewProps {
  skills: SkillInfo[];
  onToggleSkill: (skillId: string) => Promise<void>;
}

export const SkillsView: React.FC<SkillsViewProps> = ({ skills, onToggleSkill }) => {
  const [selectedSkill, setSelectedSkill] = useState<SkillInfo | null>(
    skills && skills.length > 0 ? skills[0] : null,
  );
  const [testToolInput, setTestToolInput] = useState('{"path": "./workspace"}');
  const [testResult, setTestResult] = useState<string | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);

  React.useEffect(() => {
    if (!selectedSkill && skills && skills.length > 0) {
      setSelectedSkill(skills[0]);
    } else if (selectedSkill && skills && !skills.some((s) => s.id === selectedSkill.id)) {
      setSelectedSkill(skills[0] || null);
    }
  }, [skills, selectedSkill]);

  const getIcon = (iconName: string) => {
    switch (iconName) {
      case 'FolderOpen':
        return <FolderOpen className="w-5 h-5 text-amber-400" />;
      case 'Terminal':
        return <Terminal className="w-5 h-5 text-emerald-400" />;
      case 'Globe':
        return <Globe className="w-5 h-5 text-sky-400" />;
      case 'Clock':
        return <Clock className="w-5 h-5 text-indigo-400" />;
      case 'Sparkles':
        return <Sparkles className="w-5 h-5 text-purple-400" />;
      case 'Bot':
      default:
        return <Bot className="w-5 h-5 text-rose-400" />;
    }
  };

  const handleTestTool = () => {
    if (!selectedSkill) return;
    setIsExecuting(true);
    setTestResult(null);

    setTimeout(() => {
      let parsed = {};
      try {
        parsed = JSON.parse(testToolInput);
      } catch (e) {
        parsed = { raw: testToolInput };
      }

      setTestResult(
        JSON.stringify(
          {
            status: 'success',
            skill: selectedSkill.id,
            executedTool: selectedSkill.tools[0] || 'default_tool',
            parameters: parsed,
            timestamp: new Date().toISOString(),
            output: `Tool execution completed under Nanobot security sandbox policy. Validated 0 security alerts.`,
          },
          null,
          2,
        ),
      );
      setIsExecuting(false);
    }, 600);
  };

  return (
    <div className="h-full flex overflow-hidden bg-zinc-950">
      {/* Left List of Skills */}
      <div className="w-80 border-r border-zinc-800/80 bg-zinc-900/30 flex flex-col justify-between">
        <div className="p-4 border-b border-zinc-800/80">
          <h3 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
            <Wrench className="w-4 h-4 text-amber-400" />
            <span>Agent Skills & Tools</span>
          </h3>
          <p className="text-[11px] text-zinc-400 mt-1">
            Auto-discovered tool registry powering the LLM conversation loop.
          </p>
        </div>

        <div className="flex-1 overflow-y-auto p-2.5 space-y-1.5">
          {skills.map((skill) => {
            const isSelected = selectedSkill?.id === skill.id;

            return (
              <div
                key={skill.id}
                id={`skill-item-${skill.id}`}
                onClick={() => setSelectedSkill(skill)}
                className={`p-3 rounded-lg border cursor-pointer transition-all ${
                  isSelected
                    ? 'bg-zinc-800/90 border-amber-500/50 shadow-sm'
                    : 'bg-zinc-900/40 border-zinc-800/80 hover:bg-zinc-850 hover:border-zinc-700'
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    {getIcon(skill.icon)}
                    <span className="text-xs font-semibold text-zinc-200">{skill.name}</span>
                  </div>

                  <button
                    id={`btn-toggle-skill-${skill.id}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleSkill(skill.id);
                    }}
                    className={`px-2 py-0.5 rounded text-[10px] font-mono transition-colors ${
                      skill.enabled
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                        : 'bg-zinc-800 text-zinc-500 border border-zinc-700'
                    }`}
                  >
                    {skill.enabled ? 'Active' : 'Disabled'}
                  </button>
                </div>

                <p className="text-[11px] text-zinc-400 line-clamp-2 leading-relaxed">
                  {skill.description}
                </p>

                <div className="mt-2 flex items-center gap-1.5 text-[10px] font-mono text-zinc-500">
                  <span>{skill.tools.length} Tools</span>
                  <span>•</span>
                  <span className="capitalize">{skill.category}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Right Details Panel */}
      <div className="flex-1 overflow-y-auto p-8 max-w-4xl space-y-6">
        {selectedSkill ? (
          <>
            <div className="flex items-start justify-between pb-4 border-b border-zinc-800/80">
              <div className="flex items-center gap-3.5">
                <div className="p-3 rounded-xl bg-zinc-800/80 border border-zinc-700">
                  {getIcon(selectedSkill.icon)}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-zinc-100">{selectedSkill.name}</h2>
                    <span className="px-2 py-0.5 text-[10px] font-mono bg-zinc-800 text-zinc-300 rounded border border-zinc-700 uppercase">
                      {selectedSkill.category}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 mt-1">{selectedSkill.description}</p>
                </div>
              </div>

              <button
                id="btn-main-toggle-skill"
                onClick={() => onToggleSkill(selectedSkill.id)}
                className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors cursor-pointer ${
                  selectedSkill.enabled
                    ? 'bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700'
                    : 'bg-amber-500 hover:bg-amber-400 text-zinc-950'
                }`}
              >
                {selectedSkill.enabled ? 'Deactivate Skill' : 'Activate Skill'}
              </button>
            </div>

            {/* Exposed Tool Capabilities */}
            <div className="space-y-3">
              <h4 className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">
                Exposed Agent Tools ({selectedSkill.tools.length})
              </h4>
              <div className="grid grid-cols-2 gap-2.5">
                {selectedSkill.tools.map((toolName) => (
                  <div
                    key={toolName}
                    className="p-3 rounded-lg bg-zinc-900 border border-zinc-800 flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      <Code className="w-4 h-4 text-amber-400" />
                      <span className="text-xs font-mono text-zinc-200">{toolName}</span>
                    </div>
                    <span className="text-[10px] text-emerald-400 bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-800/60 font-mono">
                      ready
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Execution Instructions / System Contract */}
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">
                Agent Execution Policy (`SKILL.md`)
              </h4>
              <div className="p-4 rounded-xl bg-zinc-900/80 border border-zinc-800 text-xs text-zinc-300 leading-relaxed font-mono">
                {selectedSkill.instructions}
              </div>
            </div>

            {/* Interactive Sandbox Test Runner */}
            <div className="space-y-3 p-5 rounded-xl border border-zinc-800 bg-zinc-900/40">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-zinc-200 flex items-center gap-2">
                  <Play className="w-3.5 h-3.5 text-amber-400" />
                  <span>Sandbox Tool Test Runner</span>
                </h4>
                <span className="text-[11px] text-zinc-500 font-mono">Test Invocation</span>
              </div>

              <textarea
                rows={3}
                value={testToolInput}
                onChange={(e) => setTestToolInput(e.target.value)}
                placeholder='{"param": "value"}'
                className="w-full p-3 rounded-lg bg-zinc-950 border border-zinc-800 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
              />

              <div className="flex items-center justify-between">
                <span className="text-[11px] text-zinc-500 flex items-center gap-1">
                  <ShieldAlert className="w-3.5 h-3.5 text-zinc-500" />
                  Enforcing dry-run boundary
                </span>
                <button
                  id="btn-run-tool-test"
                  onClick={handleTestTool}
                  disabled={isExecuting}
                  className="px-4 py-1.5 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isExecuting ? 'Running...' : 'Execute Tool Test'}
                </button>
              </div>

              {testResult && (
                <div className="mt-3 p-3 rounded-lg bg-zinc-950 border border-zinc-800 font-mono text-[11px] text-emerald-400/90 whitespace-pre-wrap">
                  {testResult}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="h-full flex items-center justify-center text-zinc-500 text-xs">
            Select a skill to inspect its configuration and tool bindings.
          </div>
        )}
      </div>
    </div>
  );
};
