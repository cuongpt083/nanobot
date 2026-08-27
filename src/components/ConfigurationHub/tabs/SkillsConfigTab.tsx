import React, { useState } from 'react';
import {
  Wrench,
  Sparkles,
  Plus,
  Trash2,
  CheckCircle2,
  FolderTree,
  Terminal,
  Search,
  Clock,
  Bot,
  Image as ImageIcon,
  Mic,
  Code,
  Sliders,
  Shield
} from 'lucide-react';
import { NanobotFullConfig, CustomSkillItem } from '../../../types';

interface SkillsConfigTabProps {
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => void;
}

const BUILTIN_SKILLS_INFO = [
  {
    id: 'skill-filesystem',
    name: 'Filesystem Tools',
    icon: FolderTree,
    description: 'Read, write, edit, list directory trees, and apply unified git-diff patches.',
    tools: ['filesystem_read', 'filesystem_write', 'filesystem_edit', 'filesystem_list'],
    category: 'filesystem',
  },
  {
    id: 'skill-shell',
    name: 'Bash Shell & Sandbox',
    icon: Terminal,
    description: 'Execute commands, manage background tasks, inspect terminal logs within sandbox policy.',
    tools: ['shell_exec', 'shell_spawn', 'shell_status', 'shell_kill'],
    category: 'core',
  },
  {
    id: 'skill-search',
    name: 'Web Search & Fetch',
    icon: Search,
    description: 'Real-time search across Brave Search, DuckDuckGo, Tavily, and Jina Reader fetch.',
    tools: ['web_search', 'web_fetch', 'jina_reader'],
    category: 'integration',
  },
  {
    id: 'skill-cron',
    name: 'Cron & Scheduled Tasks',
    icon: Clock,
    description: '5-field cron jobs, background timers, and heartbeat automated proactive routines.',
    tools: ['cron_schedule', 'cron_list', 'cron_cancel'],
    category: 'automation',
  },
  {
    id: 'skill-dream',
    name: 'Dream Memory Consolidation',
    icon: Sparkles,
    description: 'Two-phase memory extraction, auto-compaction of user preferences and project facts.',
    tools: ['memory_record_fact', 'memory_search', 'dream_consolidate'],
    category: 'core',
  },
  {
    id: 'skill-subagent',
    name: 'Subagent Swarm Spawning',
    icon: Bot,
    description: 'Fork isolated agent threads to run multi-step subtasks or deep research in parallel.',
    tools: ['subagent_spawn', 'subagent_wait', 'subagent_result'],
    category: 'automation',
  },
  {
    id: 'skill-image-gen',
    name: 'Image Generation',
    icon: ImageIcon,
    description: 'Synthesize images, banners, and diagrams using Google Imagen 3, DALL-E, or Flux.',
    tools: ['image_generate', 'image_edit'],
    category: 'integration',
  },
  {
    id: 'skill-transcription',
    name: 'Voice Audio Transcription',
    icon: Mic,
    description: 'Transcribe voice notes, audio attachments, and meeting clips using Whisper or Groq.',
    tools: ['transcription_audio'],
    category: 'integration',
  },
];

export const SkillsConfigTab: React.FC<SkillsConfigTabProps> = ({
  config,
  onUpdateConfig,
}) => {
  const skillsConfig = config.skills || { enabled: {}, customSkills: [] };
  const enabledMap = skillsConfig.enabled || {};
  const customSkills = skillsConfig.customSkills || [];

  const [activeSubTab, setActiveSubTab] = useState<'builtin' | 'custom'>('builtin');
  const [selectedSkillId, setSelectedSkillId] = useState<string>('skill-filesystem');
  const [isCreatingCustom, setIsCreatingCustom] = useState<boolean>(false);

  const [newCustomSkill, setNewCustomSkill] = useState<{
    name: string;
    description: string;
    instructions: string;
    triggerKeywords: string;
    allowedTools: string;
  }>({
    name: '',
    description: '',
    instructions: '',
    triggerKeywords: 'review, check, lint',
    allowedTools: 'filesystem_read, shell_exec',
  });

  const handleToggleBuiltin = (skillId: string) => {
    const currentState = enabledMap[skillId] ?? true;
    onUpdateConfig({
      skills: {
        ...skillsConfig,
        enabled: {
          ...enabledMap,
          [skillId]: !currentState,
        },
      },
    });
  };

  const handleToggleCustom = (customId: string) => {
    const updated = customSkills.map((s) =>
      s.id === customId ? { ...s, enabled: !s.enabled } : s
    );
    onUpdateConfig({
      skills: {
        ...skillsConfig,
        customSkills: updated,
      },
    });
  };

  const handleDeleteCustom = (customId: string) => {
    const updated = customSkills.filter((s) => s.id !== customId);
    onUpdateConfig({
      skills: {
        ...skillsConfig,
        customSkills: updated,
      },
    });
  };

  const handleCreateCustom = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCustomSkill.name || !newCustomSkill.instructions) return;

    const newSkill: CustomSkillItem = {
      id: `skill-custom-${Date.now()}`,
      name: newCustomSkill.name,
      category: 'custom',
      description: newCustomSkill.description || 'User-defined agent capability',
      instructions: newCustomSkill.instructions,
      enabled: true,
      triggerKeywords: newCustomSkill.triggerKeywords.split(',').map((s) => s.trim()),
      allowedTools: newCustomSkill.allowedTools.split(',').map((s) => s.trim()),
    };

    onUpdateConfig({
      skills: {
        ...skillsConfig,
        customSkills: [...customSkills, newSkill],
      },
    });

    setIsCreatingCustom(false);
    setNewCustomSkill({
      name: '',
      description: '',
      instructions: '',
      triggerKeywords: '',
      allowedTools: '',
    });
    setActiveSubTab('custom');
  };

  return (
    <div className="flex flex-col h-full space-y-4 text-zinc-300">
      {/* Top Filter Buttons */}
      <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveSubTab('builtin')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer ${
              activeSubTab === 'builtin'
                ? 'bg-amber-500 text-zinc-950 shadow-xs'
                : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Built-in Skills ({BUILTIN_SKILLS_INFO.length})
          </button>
          <button
            onClick={() => setActiveSubTab('custom')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer ${
              activeSubTab === 'custom'
                ? 'bg-amber-500 text-zinc-950 shadow-xs'
                : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Custom Skills & Plugins ({customSkills.length})
          </button>
        </div>

        {activeSubTab === 'custom' && (
          <button
            onClick={() => setIsCreatingCustom(true)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-bold transition-colors cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Create Custom Skill</span>
          </button>
        )}
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-y-auto">
        {activeSubTab === 'builtin' ? (
          <div className="grid grid-cols-2 gap-3.5">
            {BUILTIN_SKILLS_INFO.map((skill) => {
              const Icon = skill.icon;
              const isEnabled = enabledMap[skill.id] ?? true;

              return (
                <div
                  key={skill.id}
                  className={`p-4 rounded-xl border transition-all ${
                    isEnabled
                      ? 'bg-zinc-950/60 border-zinc-800 hover:border-zinc-700'
                      : 'bg-zinc-950/20 border-zinc-900 opacity-60'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <div
                        className={`w-9 h-9 rounded-xl flex items-center justify-center ${
                          isEnabled
                            ? 'bg-amber-500/15 border border-amber-500/30 text-amber-400'
                            : 'bg-zinc-900 text-zinc-600'
                        }`}
                      >
                        <Icon className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="text-xs font-bold text-zinc-100">{skill.name}</div>
                        <div className="text-[10px] text-zinc-500 font-mono">{skill.id}</div>
                      </div>
                    </div>

                    {/* Toggle Switch */}
                    <button
                      onClick={() => handleToggleBuiltin(skill.id)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                        isEnabled ? 'bg-amber-500' : 'bg-zinc-800'
                      }`}
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-zinc-950 transition-transform ${
                          isEnabled ? 'translate-x-4.5' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>

                  <p className="text-xs text-zinc-400 mt-2.5 leading-relaxed">
                    {skill.description}
                  </p>

                  <div className="mt-3 pt-2.5 border-t border-zinc-800/60 flex flex-wrap gap-1.5">
                    {skill.tools.map((t) => (
                      <span
                        key={t}
                        className="px-2 py-0.5 rounded bg-zinc-900 border border-zinc-800 text-[10px] font-mono text-zinc-400"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : isCreatingCustom ? (
          /* Custom Skill Creation Form */
          <form
            onSubmit={handleCreateCustom}
            className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 space-y-4 max-w-2xl"
          >
            <div className="flex items-center justify-between pb-2 border-b border-zinc-800">
              <h4 className="text-sm font-bold text-zinc-100">Create Custom Agent Skill</h4>
              <button
                type="button"
                onClick={() => setIsCreatingCustom(false)}
                className="text-xs text-zinc-400 hover:text-zinc-200"
              >
                Cancel
              </button>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-zinc-200">Skill Name</label>
              <input
                type="text"
                required
                placeholder="e.g. Python Security & Static Linter"
                value={newCustomSkill.name}
                onChange={(e) => setNewCustomSkill({ ...newCustomSkill, name: e.target.value })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-zinc-200">Short Description</label>
              <input
                type="text"
                placeholder="e.g. Runs ruff and bandit checks before completing tasks"
                value={newCustomSkill.description}
                onChange={(e) => setNewCustomSkill({ ...newCustomSkill, description: e.target.value })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-zinc-200">
                Instruction Guidelines (Injected into context when triggered)
              </label>
              <textarea
                rows={4}
                required
                placeholder="Step-by-step instructions the agent should adhere to when executing this skill..."
                value={newCustomSkill.instructions}
                onChange={(e) => setNewCustomSkill({ ...newCustomSkill, instructions: e.target.value })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs text-zinc-200 font-mono focus:outline-none focus:border-amber-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">
                  Trigger Keywords (Comma separated)
                </label>
                <input
                  type="text"
                  value={newCustomSkill.triggerKeywords}
                  onChange={(e) => setNewCustomSkill({ ...newCustomSkill, triggerKeywords: e.target.value })}
                  placeholder="e.g. security, bandit, ruff, audit"
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-zinc-200">
                  Allowed Tools (Comma separated)
                </label>
                <input
                  type="text"
                  value={newCustomSkill.allowedTools}
                  onChange={(e) => setNewCustomSkill({ ...newCustomSkill, allowedTools: e.target.value })}
                  placeholder="e.g. shell_exec, filesystem_read"
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
                />
              </div>
            </div>

            <div className="pt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsCreatingCustom(false)}
                className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs text-zinc-300"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-xs font-bold text-zinc-950"
              >
                Save Skill
              </button>
            </div>
          </form>
        ) : (
          /* Custom Skills List */
          <div className="space-y-3">
            {customSkills.length === 0 ? (
              <div className="p-8 text-center rounded-xl bg-zinc-950/40 border border-zinc-800/80 space-y-3">
                <Code className="w-8 h-8 text-zinc-600 mx-auto" />
                <div className="text-sm font-semibold text-zinc-300">No Custom Skills Created Yet</div>
                <p className="text-xs text-zinc-500 max-w-sm mx-auto">
                  Create custom skills to teach Nanobot domain-specific instructions, workflows, or tool chains.
                </p>
                <button
                  onClick={() => setIsCreatingCustom(true)}
                  className="px-3.5 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-bold cursor-pointer"
                >
                  Create Your First Custom Skill
                </button>
              </div>
            ) : (
              customSkills.map((skill) => (
                <div
                  key={skill.id}
                  className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 flex items-start justify-between gap-4"
                >
                  <div className="space-y-2 flex-1">
                    <div className="flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-amber-400" />
                      <div className="text-xs font-bold text-zinc-100">{skill.name}</div>
                      <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono">
                        {skill.id}
                      </span>
                    </div>

                    <p className="text-xs text-zinc-400">{skill.description}</p>

                    <div className="p-2.5 rounded-lg bg-zinc-900/80 border border-zinc-800/80 text-[11px] font-mono text-zinc-300">
                      {skill.instructions}
                    </div>

                    <div className="flex items-center gap-2 pt-1">
                      <span className="text-[10px] text-zinc-500">Keywords:</span>
                      {skill.triggerKeywords?.map((k) => (
                        <span key={k} className="text-[10px] px-1.5 py-0.2 rounded bg-zinc-800 text-amber-300">
                          {k}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => handleToggleCustom(skill.id)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                        skill.enabled ? 'bg-amber-500' : 'bg-zinc-800'
                      }`}
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-zinc-950 transition-transform ${
                          skill.enabled ? 'translate-x-4.5' : 'translate-x-1'
                        }`}
                      />
                    </button>

                    <button
                      onClick={() => handleDeleteCustom(skill.id)}
                      className="p-1.5 rounded-lg bg-zinc-800 hover:bg-rose-950 text-zinc-400 hover:text-rose-400 transition-colors"
                      title="Delete Custom Skill"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
};
