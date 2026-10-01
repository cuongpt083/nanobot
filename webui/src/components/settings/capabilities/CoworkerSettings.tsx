import { Loader2, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  NumberInput,
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
  StatusPill,
} from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, fetchCoworkerSettings, updateCoworkerSettings } from "@/lib/api";
import type {
  CoworkerBackendDetection,
  CoworkerEditableConfig,
  CoworkerRepoCheck,
  CoworkerRoomAgentConfig,
  CoworkerSettingsPayload,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

export type CoworkerTab = "advisor" | "team" | "coding" | "cache";
type Section = keyof CoworkerEditableConfig;

const SELECT_CLASS =
  "h-9 w-full rounded-full border border-input bg-background px-3 text-[13px] text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const BLANK_AGENT: CoworkerRoomAgentConfig = {
  id: "",
  name: "",
  emoji: "",
  bio: "",
  preset: null,
  backend: null,
  instructions: "",
};

export function splitLines(text: string): string[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean);
}

export function splitCommand(text: string): string[] {
  return text.trim().split(/\s+/).filter(Boolean);
}

/** Tabs whose draft differs from what the server has (used for the dirty dot and Save state). */
export function dirtySections(
  draft: CoworkerEditableConfig | null,
  saved: CoworkerEditableConfig | null,
): Set<Section> {
  const dirty = new Set<Section>();
  if (!draft || !saved) return dirty;
  (["advisor", "room", "coding", "context"] as const).forEach((section) => {
    if (JSON.stringify(draft[section]) !== JSON.stringify(saved[section])) dirty.add(section);
  });
  return dirty;
}

const TAB_SECTION: Record<CoworkerTab, Section> = {
  advisor: "advisor",
  team: "room",
  coding: "coding",
  cache: "context",
};

export function useCoworkerSettings() {
  const { client, token } = useClient();
  const [payload, setPayload] = useState<CoworkerSettingsPayload | null>(null);
  const [draft, setDraft] = useState<CoworkerEditableConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState<Section | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const next = await fetchCoworkerSettings(token);
      setPayload(next);
      setDraft(structuredClone(next.config));
    } catch (reason) {
      setLoadError(reason instanceof ApiError ? reason.message : "Could not load Coworker settings.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = useCallback(
    async (section: Section) => {
      if (!draft) return;
      setSaving(section);
      setSaveError(null);
      try {
        const next = await updateCoworkerSettings(client, { [section]: draft[section] });
        setPayload(next);
        // Only the saved section is replaced; unsaved edits in other tabs survive.
        setDraft((prev) => (prev ? { ...prev, [section]: structuredClone(next.config[section]) } : prev));
        setSavedAt(Date.now());
      } catch (reason) {
        setSaveError(reason instanceof ApiError ? reason.message : "Could not save Coworker settings.");
      } finally {
        setSaving(null);
      }
    },
    [client, draft],
  );

  const revert = useCallback(
    (section: Section) => {
      if (!payload) return;
      setDraft((prev) => (prev ? { ...prev, [section]: structuredClone(payload.config[section]) } : prev));
      setSaveError(null);
    },
    [payload],
  );

  const patch = useCallback(
    <S extends Section>(section: S, update: (value: CoworkerEditableConfig[S]) => CoworkerEditableConfig[S]) => {
      setDraft((prev) => (prev ? { ...prev, [section]: update(prev[section]) } : prev));
    },
    [],
  );

  return { payload, draft, loading, loadError, saving, saveError, savedAt, load, save, revert, patch };
}

type CoworkerSettingsState = ReturnType<typeof useCoworkerSettings>;

function Field({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <SettingsRow title={title} description={description}>
      {children}
    </SettingsRow>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (next: boolean) => void; label: string }) {
  return <ToggleButton checked={checked} onChange={onChange} ariaLabel={label} label={label} />;
}

function PresetSelect({
  value,
  presets,
  onChange,
  emptyLabel,
  label,
}: {
  value: string | null;
  presets: string[];
  onChange: (next: string | null) => void;
  emptyLabel: string;
  label: string;
}) {
  const known = value && !presets.includes(value) && value !== "off" ? [value, ...presets] : presets;
  return (
    <select
      aria-label={label}
      className={SELECT_CLASS}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value || null)}
    >
      <option value="">{emptyLabel}</option>
      {known.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
    </select>
  );
}

function AdvisorTab({ state }: { state: CoworkerSettingsState }) {
  const { t } = useTranslation();
  const { draft, payload, patch } = state;
  if (!draft || !payload) return null;
  const advisor = draft.advisor;
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });
  const set = (next: Partial<typeof advisor>) => patch("advisor", (prev) => ({ ...prev, ...next }));
  const presetValue = advisor.preset === "off" ? null : advisor.preset;
  return (
    <div className="settings-stack">
      <SettingsGroup>
        <Field
          title={tx("advisor.preset", "Advisor model")}
          description={tx(
            "advisor.presetHelp",
            "A stronger model the agent can consult for review. It only advises; it never edits or runs anything.",
          )}
        >
          <PresetSelect
            label={tx("advisor.preset", "Advisor model")}
            value={presetValue}
            presets={payload.presets}
            emptyLabel={tx("advisor.disabled", "Disabled")}
            onChange={(preset) => set({ preset })}
          />
        </Field>
        <Field title={tx("advisor.maxUses", "Consults per conversation")}>
          <NumberInput value={advisor.max_uses} min={1} max={200} onChange={(max_uses) => set({ max_uses })} />
        </Field>
        <Field title={tx("advisor.maxTokens", "Advice length limit")}>
          <NumberInput
            value={advisor.max_tokens}
            min={256}
            max={64000}
            suffix="tok"
            onChange={(max_tokens) => set({ max_tokens })}
          />
        </Field>
        <Field title={tx("advisor.timeout", "Consult timeout")}>
          <NumberInput
            value={advisor.timeout_seconds}
            min={10}
            max={1800}
            suffix="s"
            onChange={(timeout_seconds) => set({ timeout_seconds })}
          />
        </Field>
        <Field
          title={tx("advisor.nudge", "Remind the agent to ask")}
          description={tx(
            "advisor.nudgeHelp",
            "After substantial work, or a finished coding task, nudge the agent to consult the advisor once.",
          )}
        >
          <Toggle
            checked={advisor.review_nudge}
            label={tx("advisor.nudge", "Remind the agent to ask")}
            onChange={(review_nudge) => set({ review_nudge })}
          />
        </Field>
        <Field
          title={tx("advisor.firstGap", "First-consult reminder after")}
          description={tx("advisor.gapHelp", "Number of state-changing steps without consulting.")}
        >
          <NumberInput
            value={advisor.first_consult_gap}
            min={1}
            max={100}
            onChange={(first_consult_gap) => set({ first_consult_gap })}
          />
        </Field>
        <Field title={tx("advisor.reconsultGap", "Re-consult reminder after")}>
          <NumberInput
            value={advisor.reconsult_gap}
            min={3}
            max={200}
            onChange={(reconsult_gap) => set({ reconsult_gap })}
          />
        </Field>
        <Field
          title={tx("advisor.discussionGate", "Discussion gate")}
          description={tx(
            "advisor.discussionGateHelp",
            "Require advisor consultation on draft before long answers stand.",
          )}
        >
          <select
            className="rounded-lg border border-border/60 bg-bg-surface px-2.5 py-1.5 text-xs text-text-primary"
            value={advisor.discussion_gate ?? "brainstorm"}
            onChange={(e) => set({ discussion_gate: e.target.value as "off" | "brainstorm" | "always" })}
          >
            <option value="off">{tx("advisor.discussionGateOff", "Off")}</option>
            <option value="brainstorm">{tx("advisor.discussionGateBrainstorm", "Brainstorm mode only")}</option>
            <option value="always">{tx("advisor.discussionGateAlways", "Always")}</option>
          </select>
        </Field>
        <Field
          title={tx("advisor.discussionMinChars", "Minimum draft length")}
          description={tx("advisor.discussionMinCharsHelp", "Only gate drafts reaching this character count.")}
        >
          <NumberInput
            value={advisor.discussion_min_chars ?? 800}
            min={100}
            max={10000}
            suffix="chars"
            onChange={(discussion_min_chars) => set({ discussion_min_chars })}
          />
        </Field>
        <Field
          title={tx("advisor.stuckDetection", "Mechanical stuck detection")}
          description={tx(
            "advisor.stuckDetectionHelp",
            "When the same failure repeats, instruct the agent to consult the advisor before retrying.",
          )}
        >
          <Toggle
            checked={advisor.stuck_detection ?? true}
            label={tx("advisor.stuckDetection", "Mechanical stuck detection")}
            onChange={(stuck_detection) => set({ stuck_detection })}
          />
        </Field>
      </SettingsGroup>
    </div>
  );
}

function AgentCard({
  agent,
  presets,
  detection,
  onChange,
  onRemove,
}: {
  agent: CoworkerRoomAgentConfig;
  presets: string[];
  detection: CoworkerSettingsPayload["detection"];
  onChange: (next: CoworkerRoomAgentConfig) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });
  return (
    <div className="space-y-2 rounded-xl border border-border/60 p-3" data-agent={agent.id || "new"}>
      <div className="flex items-center gap-2">
        <Input
          aria-label={tx("team.emoji", "Emoji")}
          className="h-9 w-14 shrink-0 rounded-full text-center text-[13px]"
          value={agent.emoji}
          maxLength={4}
          onChange={(event) => onChange({ ...agent, emoji: event.target.value })}
        />
        <Input
          aria-label={tx("team.id", "Agent id")}
          className="h-9 min-w-0 flex-1 rounded-full font-mono text-[13px]"
          placeholder="researcher"
          value={agent.id}
          onChange={(event) => onChange({ ...agent, id: event.target.value.toLowerCase() })}
        />
        <Input
          aria-label={tx("team.name", "Display name")}
          className="h-9 min-w-0 flex-1 rounded-full text-[13px]"
          placeholder={tx("team.name", "Display name")}
          value={agent.name}
          onChange={(event) => onChange({ ...agent, name: event.target.value })}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={tx("team.remove", "Remove agent")}
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
      <Input
        aria-label={tx("team.bio", "Speciality")}
        className="h-9 rounded-full text-[13px]"
        placeholder={tx("team.bio", "Speciality (the coordinator uses this to pick who to delegate to)")}
        value={agent.bio}
        onChange={(event) => onChange({ ...agent, bio: event.target.value })}
      />
      <div className="grid gap-2 sm:grid-cols-2">
        <PresetSelect
          label={tx("team.preset", "Model")}
          value={agent.preset}
          presets={presets}
          emptyLabel={tx("team.ownerModel", "Same model as the coordinator")}
          onChange={(preset) => onChange({ ...agent, preset })}
        />
        <select
          aria-label={tx("team.backend", "Runs as")}
          className={SELECT_CLASS}
          value={agent.backend ?? ""}
          onChange={(event) =>
            onChange({ ...agent, backend: (event.target.value || null) as CoworkerRoomAgentConfig["backend"] })
          }
        >
          <option value="">{tx("team.plainAgent", "Chat agent")}</option>
          {(["pi", "agy"] as const).map((name) => (
            <option key={name} value={name}>
              {name === "pi" ? "Pi" : "agy"} {detection[name]?.found ? "" : `(${tx("coding.notFound", "not found")})`}
            </option>
          ))}
        </select>
      </div>
      <Textarea
        aria-label={tx("team.instructions", "Instructions")}
        className="min-h-16 text-[13px]"
        placeholder={tx("team.instructions", "Extra instructions for this teammate (optional)")}
        value={agent.instructions}
        onChange={(event) => onChange({ ...agent, instructions: event.target.value })}
      />
    </div>
  );
}

function TeamTab({ state }: { state: CoworkerSettingsState }) {
  const { t } = useTranslation();
  const { draft, payload, patch } = state;
  if (!draft || !payload) return null;
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });
  const room = draft.room;
  const setAgent = (index: number, next: CoworkerRoomAgentConfig) =>
    patch("room", (prev) => ({ ...prev, agents: prev.agents.map((a, i) => (i === index ? next : a)) }));
  return (
    <div className="settings-stack">
      <div className="settings-list-inset space-y-2">
        {room.agents.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            {tx("team.empty", "No teammates yet. Mention them in chat with @id once added.")}
          </p>
        ) : null}
        {room.agents.map((agent, index) => (
          <AgentCard
            key={index}
            agent={agent}
            presets={payload.presets}
            detection={payload.detection}
            onChange={(next) => setAgent(index, next)}
            onRemove={() =>
              patch("room", (prev) => ({ ...prev, agents: prev.agents.filter((_, i) => i !== index) }))
            }
          />
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => patch("room", (prev) => ({ ...prev, agents: [...prev.agents, { ...BLANK_AGENT }] }))}
        >
          <Plus className="mr-1 h-4 w-4" />
          {tx("team.add", "Add teammate")}
        </Button>
      </div>
      <SettingsGroup>
        <Field
          title={tx("team.maxChained", "Delegations per message")}
          description={tx("team.maxChainedHelp", "Stops agents from delegating to each other forever.")}
        >
          <NumberInput
            value={room.max_chained_turns}
            min={1}
            max={100}
            onChange={(max_chained_turns) => patch("room", (prev) => ({ ...prev, max_chained_turns }))}
          />
        </Field>
        <Field title={tx("team.guestTimeout", "Teammate time limit")}>
          <NumberInput
            value={room.guest_timeout_seconds}
            min={30}
            max={86400}
            suffix="s"
            onChange={(guest_timeout_seconds) => patch("room", (prev) => ({ ...prev, guest_timeout_seconds }))}
          />
        </Field>
      </SettingsGroup>
    </div>
  );
}

function DetectionPill({ info, fallbackName }: { info?: CoworkerBackendDetection; fallbackName: string }) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });
  if (!info?.found) {
    return <StatusPill tone="neutral">{`${fallbackName}: ${tx("coding.notFound", "not found")}`}</StatusPill>;
  }
  const detail = info.custom ? tx("coding.custom", "custom command") : (info.version ?? tx("coding.installed", "installed"));
  return <StatusPill tone="success">{`${fallbackName}: ${detail}`}</StatusPill>;
}

function RepoRow({
  repo,
  check,
  onChange,
  onRemove,
}: {
  repo: CoworkerEditableConfig["coding"]["repos"][number];
  check?: CoworkerRepoCheck;
  onChange: (next: CoworkerEditableConfig["coding"]["repos"][number]) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });
  return (
    <div className="space-y-2 rounded-xl border border-border/60 p-3" data-repo={repo.path || "new"}>
      <div className="flex items-center gap-2">
        <Input
          aria-label={tx("coding.repoPath", "Project folder path")}
          className="h-9 min-w-0 flex-1 rounded-full font-mono text-[13px]"
          placeholder="/home/me/project"
          value={repo.path}
          onChange={(event) => onChange({ ...repo, path: event.target.value })}
        />
        <Button type="button" variant="ghost" size="icon" aria-label={tx("coding.removeRepo", "Remove profile")} onClick={onRemove}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
      {check && repo.path === check.path ? (
        <p className={cn("text-[12px]", check.ok ? "text-emerald-600 dark:text-emerald-400" : "text-destructive")}>
          {check.ok
            ? check.kind === "directory"
              ? tx("coding.folderOk", "Folder without git (edited in place)")
              : `${tx("coding.repoOk", "Git repository")}${check.branch ? ` · ${check.branch}` : ""}`
            : check.error}
        </p>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-3">
        <Input
          aria-label={tx("coding.acceptance", "Acceptance command")}
          className="h-9 rounded-full font-mono text-[13px] sm:col-span-2"
          placeholder={tx("coding.acceptance", "Acceptance command, e.g. pytest -q")}
          value={repo.acceptance ?? ""}
          onChange={(event) => onChange({ ...repo, acceptance: event.target.value || null })}
        />
        <Input
          aria-label={tx("coding.baseRef", "Base branch")}
          className="h-9 rounded-full font-mono text-[13px]"
          placeholder="HEAD"
          value={repo.base_ref}
          onChange={(event) => onChange({ ...repo, base_ref: event.target.value })}
        />
      </div>
      <select
        aria-label={tx("coding.repoBackend", "Default backend for this repository")}
        className={SELECT_CLASS}
        value={repo.backend ?? ""}
        onChange={(event) => onChange({ ...repo, backend: (event.target.value || null) as typeof repo.backend })}
      >
        <option value="">{tx("coding.useDefaultBackend", "Use the global default backend")}</option>
        <option value="pi">Pi</option>
        <option value="agy">agy</option>
      </select>
    </div>
  );
}

function UnsandboxedToggle({
  backend,
  checked,
  onChange,
}: {
  backend: "pi" | "agy";
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });
  const [confirming, setConfirming] = useState(false);
  const title = `${backend === "pi" ? "Pi" : "agy"}: ${tx("coding.unsandboxed", "run without an OS sandbox")}`;
  return (
    <div>
      <Field
        title={title}
        description={tx(
          "coding.unsandboxedHelp",
          "The harness edits files and runs commands with your user's permissions. Only inside a git worktree.",
        )}
      >
        <Toggle
          checked={checked}
          label={title}
          onChange={(next) => {
            if (next) setConfirming(true);
            else onChange(false);
          }}
        />
      </Field>
      {confirming ? (
        <div role="alert" className="settings-list-inset mt-1 space-y-2 rounded-xl border border-destructive/40 p-3 text-[13px]">
          <p className="text-destructive">
            {tx(
              "coding.unsandboxedWarning",
              "Without a sandbox this backend can read and change anything your account can. Enable only on a machine you trust.",
            )}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              variant="destructive"
              onClick={() => {
                onChange(true);
                setConfirming(false);
              }}
            >
              {tx("coding.confirmUnsandboxed", "I understand, enable")}
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(false)}>
              {tx("cancel", "Cancel")}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function CodingTab({ state }: { state: CoworkerSettingsState }) {
  const { t } = useTranslation();
  const { draft, payload, patch } = state;
  if (!draft || !payload) return null;
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });
  const coding = draft.coding;
  const set = (next: Partial<typeof coding>) => patch("coding", (prev) => ({ ...prev, ...next }));
  const checks = new Map(payload.repos.map((r) => [r.path, r]));
  return (
    <div className="settings-stack">
      <SettingsGroup>
        <Field
          title={tx("coding.enabled", "Enable coding agents")}
          description={tx(
            "coding.enabledHelp",
            "Lets the agent hand multi-file work to Pi or agy in an isolated git worktree. Merging is always manual.",
          )}
        >
          <Toggle checked={coding.enabled} label={tx("coding.enabled", "Enable coding agents")} onChange={(enabled) => set({ enabled })} />
        </Field>
        <Field
          title={tx("coding.harnesses", "Installed harnesses")}
          description={tx("coding.harnessesHelp", "Log in and pick the model inside each tool; nanobot never handles their credentials.")}
        >
          <div className="flex flex-wrap justify-end gap-1.5">
            <DetectionPill info={payload.detection.pi} fallbackName="Pi" />
            <DetectionPill info={payload.detection.agy} fallbackName="agy" />
          </div>
        </Field>
        <Field title={tx("coding.defaultBackend", "Default backend")}>
          <SegmentedControl
            value={coding.default_backend}
            options={[
              { value: "pi", label: "Pi" },
              { value: "agy", label: "agy" },
            ]}
            onChange={(default_backend) => set({ default_backend })}
          />
        </Field>
      </SettingsGroup>

      <section>
        <SettingsSectionTitle>{tx("coding.repos", "Project profiles (optional)")}</SettingsSectionTitle>
        <div className="settings-list-inset space-y-2">
          <p className="text-[12px] text-muted-foreground">
            {tx(
              "coding.reposHelp",
              "The coding agent works in the project folder you pick for each chat. Add a profile to give a folder its own acceptance command, base branch or backend.",
            )}
          </p>
          {coding.repos.map((repo, index) => (
            <RepoRow
              key={index}
              repo={repo}
              check={checks.get(repo.path)}
              onChange={(next) =>
                patch("coding", (prev) => ({ ...prev, repos: prev.repos.map((r, i) => (i === index ? next : r)) }))
              }
              onRemove={() => patch("coding", (prev) => ({ ...prev, repos: prev.repos.filter((_, i) => i !== index) }))}
            />
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              patch("coding", (prev) => ({
                ...prev,
                repos: [...prev.repos, { path: "", acceptance: null, base_ref: "HEAD", backend: null }],
              }))
            }
          >
            <Plus className="mr-1 h-4 w-4" />
            {tx("coding.addRepo", "Add profile")}
          </Button>
        </div>
      </section>

      <section>
        <SettingsSectionTitle>{tx("coding.nonGitSection", "Projects without git")}</SettingsSectionTitle>
        <SettingsGroup>
          <Field
            title={tx("coding.nonGit", "When the project is not a git repository")}
            description={tx(
              "coding.nonGitHelp",
              "Documents, slides or a repository without commits cannot use a worktree. A snapshot is always taken first so changes can be undone.",
            )}
          >
            <SegmentedControl
              value={coding.non_git}
              options={[
                { value: "ask", label: tx("coding.nonGitAsk", "Ask") },
                { value: "direct", label: tx("coding.nonGitDirect", "Edit in place") },
                { value: "refuse", label: tx("coding.nonGitRefuse", "Refuse") },
              ]}
              onChange={(non_git) => set({ non_git })}
            />
          </Field>
          <Field
            title={tx("coding.snapshotMax", "Snapshot size limit")}
            description={tx(
              "coding.snapshotMaxHelp",
              "Above this size only a list of files is kept: changes can be listed but not restored.",
            )}
          >
            <NumberInput value={coding.snapshot_max_mb} min={1} max={100000} suffix="MB" onChange={(snapshot_max_mb) => set({ snapshot_max_mb })} />
          </Field>
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("coding.limits", "Limits and merging")}</SettingsSectionTitle>
        <SettingsGroup>
          <Field title={tx("coding.timeout", "Task time limit")}>
            <NumberInput value={coding.timeout_minutes} min={1} max={1440} suffix="min" onChange={(timeout_minutes) => set({ timeout_minutes })} />
          </Field>
          <Field title={tx("coding.idleTimeout", "Idle time limit")}>
            <NumberInput value={coding.idle_timeout_minutes} min={1} max={1440} suffix="min" onChange={(idle_timeout_minutes) => set({ idle_timeout_minutes })} />
          </Field>
          <Field title={tx("coding.concurrentSession", "Parallel tasks per chat")}>
            <NumberInput value={coding.max_concurrent_per_session} min={1} max={16} onChange={(max_concurrent_per_session) => set({ max_concurrent_per_session })} />
          </Field>
          <Field title={tx("coding.concurrentTotal", "Parallel tasks in total")}>
            <NumberInput value={coding.max_concurrent_total} min={1} max={32} onChange={(max_concurrent_total) => set({ max_concurrent_total })} />
          </Field>
          <Field
            title={tx("coding.fixRounds", "Fix rounds when acceptance fails")}
            description={tx("coding.fixRoundsHelp", "How many times the harness may retry after a failing acceptance command.")}
          >
            <NumberInput value={coding.fix_rounds} min={0} max={10} onChange={(fix_rounds) => set({ fix_rounds })} />
          </Field>
          <Field title={tx("coding.mergeStrategy", "Merge strategy")}>
            <SegmentedControl
              value={coding.merge_strategy}
              options={[
                { value: "squash", label: "squash" },
                { value: "no-ff", label: "no-ff" },
                { value: "ff-only", label: "ff-only" },
              ]}
              onChange={(merge_strategy) => set({ merge_strategy })}
            />
          </Field>
          <Field title={tx("coding.deleteBranch", "Delete branch after merge")}>
            <Toggle checked={coding.delete_branch_after_merge} label={tx("coding.deleteBranch", "Delete branch after merge")} onChange={(delete_branch_after_merge) => set({ delete_branch_after_merge })} />
          </Field>
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("coding.isolation", "Isolation")}</SettingsSectionTitle>
        <SettingsGroup>
          <Field
            title={tx("coding.sandbox", "OS sandbox")}
            description={tx("coding.sandboxHelp", "bwrap needs Linux; on other systems tasks run only when unsandboxed runs are allowed below.")}
          >
            <SegmentedControl
              value={coding.sandbox}
              options={[
                { value: "none", label: tx("coding.sandboxNone", "None") },
                { value: "bwrap", label: "bwrap" },
              ]}
              onChange={(sandbox) => set({ sandbox })}
            />
          </Field>
          <UnsandboxedToggle
            backend="pi"
            checked={coding.pi.allow_unsandboxed}
            onChange={(allow_unsandboxed) => patch("coding", (prev) => ({ ...prev, pi: { ...prev.pi, allow_unsandboxed } }))}
          />
          <UnsandboxedToggle
            backend="agy"
            checked={coding.agy.allow_unsandboxed}
            onChange={(allow_unsandboxed) => patch("coding", (prev) => ({ ...prev, agy: { ...prev.agy, allow_unsandboxed } }))}
          />
        </SettingsGroup>
      </section>

      <details className="settings-list-inset group text-[13px]">
        <summary className="cursor-pointer py-2 text-muted-foreground">{tx("coding.advanced", "Advanced backend options")}</summary>
        <div className="space-y-2 pb-2">
          <label className="block space-y-1">
            <span className="text-muted-foreground">{tx("coding.piCommand", "Pi command")}</span>
            <Input
              className="h-9 rounded-full font-mono text-[13px]"
              value={coding.pi.command.join(" ")}
              onChange={(event) => patch("coding", (prev) => ({ ...prev, pi: { ...prev.pi, command: splitCommand(event.target.value) } }))}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-muted-foreground">{tx("coding.agyCommand", "agy command")}</span>
            <Input
              className="h-9 rounded-full font-mono text-[13px]"
              value={coding.agy.command.join(" ")}
              onChange={(event) => patch("coding", (prev) => ({ ...prev, agy: { ...prev.agy, command: splitCommand(event.target.value) } }))}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-muted-foreground">{tx("coding.agyExtraArgs", "agy extra arguments (one per line)")}</span>
            <Textarea
              className="min-h-16 font-mono text-[13px]"
              value={coding.agy.extra_args.join("\n")}
              onChange={(event) => patch("coding", (prev) => ({ ...prev, agy: { ...prev.agy, extra_args: splitLines(event.target.value) } }))}
            />
          </label>
          <p className="text-[12px] text-muted-foreground">
            {tx("coding.noModelFlags", "Model, effort and login flags are not accepted here; set them inside the tool.")}
          </p>
        </div>
      </details>
    </div>
  );
}

function CacheTab({ state }: { state: CoworkerSettingsState }) {
  const { t } = useTranslation();
  const { draft, patch } = state;
  if (!draft) return null;
  const context = draft.context;
  const keepalive = context.keepalive;
  const trim = context.trim;
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });

  const setContext = (next: Partial<typeof context>) =>
    patch("context", (prev) => ({ ...prev, ...next }));
  const setKeepalive = (next: Partial<typeof keepalive>) =>
    patch("context", (prev) => ({ ...prev, keepalive: { ...prev.keepalive, ...next } }));
  const setTrim = (next: Partial<typeof trim>) =>
    patch("context", (prev) => ({ ...prev, trim: { ...prev.trim, ...next } }));

  return (
    <div className="settings-stack">
      <SettingsSectionTitle>{tx("cache.keepaliveTitle", "Prompt cache keep-warm")}</SettingsSectionTitle>
      <div className="settings-list-inset">
        <p className="text-[12px] text-muted-foreground">
          {tx(
            "cache.keepaliveCostNotice",
            "Keep-alive pings replay the prompt cache shortly before expiry to refresh TTL at cache-read prices (~0.1×–0.25× write price).",
          )}
        </p>
      </div>
      <SettingsGroup>
        <Field
          title={tx("cache.keepaliveEnabled", "Enable keep-warm by default")}
          description={tx("cache.keepaliveEnabledHelp", "Keep recent conversation prompt caches warm across turns.")}
        >
          <Toggle
            label={tx("cache.keepaliveEnabled", "Enable keep-warm by default")}
            checked={keepalive.enabled}
            onChange={(enabled) => setKeepalive({ enabled })}
          />
        </Field>
        <Field
          title={tx("cache.strategy", "Strategy")}
          description={tx("cache.strategyHelp", "Periodic ping for short TTLs (~5m), or 1-hour cache retention where supported.")}
        >
          <select
            aria-label={tx("cache.strategy", "Strategy")}
            className={SELECT_CLASS}
            value={keepalive.strategy}
            onChange={(e) => setKeepalive({ strategy: e.target.value as "ping" | "ttl1h" })}
          >
            <option value="ping">{tx("cache.strategyPing", "Periodic ping (~5 min)")}</option>
            <option value="ttl1h">{tx("cache.strategyTtl1h", "1-hour retention (Anthropic ttl1h)")}</option>
          </select>
        </Field>
        <Field title={tx("cache.windowMinutes", "Keep-warm window")} description={tx("cache.windowMinutesHelp", "Stop pinging if the user is idle longer than this window.")}>
          <NumberInput
            value={keepalive.window_minutes}
            min={1}
            max={240}
            suffix="min"
            onChange={(window_minutes) => setKeepalive({ window_minutes: window_minutes ?? 30 })}
          />
        </Field>
        <Field title={tx("cache.maxPings", "Maximum pings")} description={tx("cache.maxPingsHelp", "Upper limit on pings per turn to prevent unbounded cost.")}>
          <NumberInput
            value={keepalive.max_pings}
            min={1}
            max={20}
            onChange={(max_pings) => setKeepalive({ max_pings: max_pings ?? 4 })}
          />
        </Field>
        <Field title={tx("cache.leadSeconds", "Lead time")} description={tx("cache.leadSecondsHelp", "How many seconds before cache expiration to send the refresh ping.")}>
          <NumberInput
            value={keepalive.lead_seconds}
            min={5}
            max={600}
            suffix="s"
            onChange={(lead_seconds) => setKeepalive({ lead_seconds: lead_seconds ?? 60 })}
          />
        </Field>
      </SettingsGroup>

      <SettingsSectionTitle>{tx("cache.optimizeTitle", "Context Optimization")}</SettingsSectionTitle>
      <SettingsGroup>
        <Field
          title={tx("cache.optimize", "Auto-optimize context")}
          description={tx("cache.optimizeHelp", "Drop trivial acknowledgements, dead tool results, and compress heredocs.")}
        >
          <Toggle
            label={tx("cache.optimize", "Auto-optimize context")}
            checked={context.optimize}
            onChange={(optimize) => setContext({ optimize })}
          />
        </Field>
        <Field
          title={tx("cache.trimEnabled", "Block-aligned history trim")}
          description={tx("cache.trimEnabledHelp", "Keep only the most recent user turns, cutting at whole blocks.")}
        >
          <Toggle
            label={tx("cache.trimEnabled", "Block-aligned history trim")}
            checked={trim.enabled}
            onChange={(enabled) => setTrim({ enabled })}
          />
        </Field>
        {trim.enabled && (
          <Field title={tx("cache.trimMaxTurns", "Max user turns to keep")}>
            <NumberInput
              value={trim.max_turns}
              min={2}
              max={100}
              onChange={(max_turns) => setTrim({ max_turns: max_turns ?? 10 })}
            />
          </Field>
        )}
        <Field
          title={tx("cache.freezeSystemPrompt", "Freeze system prompt")}
          description={tx("cache.freezeSystemPromptHelp", "Prevent small system prompt changes from invalidating a warm cache.")}
        >
          <Toggle
            label={tx("cache.freezeSystemPrompt", "Freeze system prompt")}
            checked={context.freeze_system_prompt}
            onChange={(freeze_system_prompt) => setContext({ freeze_system_prompt })}
          />
        </Field>
        {context.freeze_system_prompt && (
          <Field title={tx("cache.freezeMaxHoldMinutes", "Max system freeze hold")}>
            <NumberInput
              value={context.freeze_max_hold_minutes}
              min={1}
              max={1440}
              suffix="min"
              onChange={(freeze_max_hold_minutes) =>
                setContext({ freeze_max_hold_minutes: freeze_max_hold_minutes ?? 60 })
              }
            />
          </Field>
        )}
        <Field
          title={tx("cache.cacheTtlSeconds", "Cache TTL override")}
          description={tx("cache.cacheTtlSecondsHelp", "Leave empty to use provider natural TTL (~300s).")}
        >
          <div className="relative w-full">
            <Input
              type="number"
              min={30}
              max={86400}
              placeholder="300"
              value={context.cache_ttl_seconds ?? ""}
              onChange={(e) => {
                const val = e.target.value.trim();
                setContext({ cache_ttl_seconds: val === "" ? null : Number(val) });
              }}
              className="h-9 w-full rounded-full text-[13px] pr-12"
            />
            <span className="pointer-events-none absolute inset-y-0 right-3 flex select-none items-center text-[12px] text-muted-foreground">
              s
            </span>
          </div>
        </Field>
      </SettingsGroup>
    </div>
  );
}

function CoworkerSettingsBody({ initialTab = "advisor" }: { initialTab?: CoworkerTab }) {
  const { t } = useTranslation();
  const state = useCoworkerSettings();
  const [tab, setTab] = useState<CoworkerTab>(initialTab);
  const tx = (key: string, fallback: string) => t(`coworker.settings.${key}`, { defaultValue: fallback });
  const dirty = useMemo(() => dirtySections(state.draft, state.payload?.config ?? null), [state.draft, state.payload]);
  const section = TAB_SECTION[tab];
  const isDirty = dirty.has(section);
  const dot = (s: Section) => (dirty.has(s) ? " •" : "");

  if (state.loading && !state.payload) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-[13px] text-muted-foreground" role="status">
        <Loader2 className="h-4 w-4 animate-spin" />
        {tx("loading", "Loading…")}
      </div>
    );
  }
  if (state.loadError || !state.draft) {
    return (
      <div className="settings-list-inset space-y-3 py-6 text-[13px]" role="alert">
        <p className="text-destructive">{state.loadError ?? tx("loadFailed", "Could not load Coworker settings.")}</p>
        <Button type="button" size="sm" variant="outline" onClick={() => void state.load()}>
          {tx("retry", "Retry")}
        </Button>
      </div>
    );
  }
  return (
    <div className="settings-stack">
      <div className="settings-list-inset">
        <SettingsSectionTitle>{tx("title", "Coworker")}</SettingsSectionTitle>
        <p className="mb-2 text-[12px] text-muted-foreground">{state.payload?.path}</p>
        <SegmentedControl
          ariaLabel={tx("title", "Coworker")}
          value={tab}
          options={[
            { value: "advisor", label: `${tx("tab.advisor", "Advisor")}${dot("advisor")}` },
            { value: "team", label: `${tx("tab.team", "Team")}${dot("room")}` },
            { value: "coding", label: `${tx("tab.coding", "Coding")}${dot("coding")}` },
            { value: "cache", label: `${tx("tab.cache", "Cache")}${dot("context")}` },
          ]}
          onChange={setTab}
        />
      </div>

      {tab === "advisor" ? <AdvisorTab state={state} /> : null}
      {tab === "team" ? <TeamTab state={state} /> : null}
      {tab === "coding" ? <CodingTab state={state} /> : null}
      {tab === "cache" ? <CacheTab state={state} /> : null}

      <div className="settings-list-inset flex flex-wrap items-center gap-2 pb-2">
        <Button type="button" size="sm" disabled={!isDirty || state.saving !== null} onClick={() => void state.save(section)}>
          {state.saving === section ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
          {tx("save", "Save")}
        </Button>
        <Button type="button" size="sm" variant="ghost" disabled={!isDirty || state.saving !== null} onClick={() => state.revert(section)}>
          {tx("revert", "Discard changes")}
        </Button>
        {state.saveError ? (
          <span role="alert" className="text-[13px] text-destructive">
            {state.saveError}
          </span>
        ) : state.savedAt && !isDirty ? (
          <span role="status" className="text-[13px] text-muted-foreground">
            {tx("saved", "Saved. Applies to new turns without a restart.")}
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** Capabilities row: opens the Coworker configuration in a dialog. */
export function CoworkerSettingsEntry({
  initialOpen = false,
  initialTab = "advisor",
}: {
  initialOpen?: boolean;
  initialTab?: CoworkerTab;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(initialOpen);
  useEffect(() => {
    if (initialOpen) setOpen(true);
  }, [initialOpen]);
  const title = t("coworker.settings.title", { defaultValue: "Coworker" });
  return (
    <section aria-label={title}>
      <Dialog open={open} onOpenChange={setOpen}>
        <SettingsGroup>
          <SettingsRow
            title={title}
            description={t("coworker.settings.entryHelp", {
              defaultValue: "Advisor model, teammate agents and coding harnesses (Pi, agy).",
            })}
          >
            <DialogTrigger asChild>
              <button
                type="button"
                className="shrink-0 rounded-lg px-2 py-1 text-[13px] leading-5 text-muted-foreground settings-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("settings.configure", { defaultValue: "Configure" })}
              </button>
            </DialogTrigger>
          </SettingsRow>
        </SettingsGroup>
        <DialogContent
          aria-describedby={undefined}
          className="settings-grid max-h-[85dvh] w-[min(calc(100vw-2rem),44rem)] max-w-none overflow-y-auto p-0 [--settings-surface:var(--background)]"
        >
          <DialogTitle className="sr-only">{title}</DialogTitle>
          <div className="pb-4 pt-8">{open ? <CoworkerSettingsBody initialTab={initialTab} /> : null}</div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
