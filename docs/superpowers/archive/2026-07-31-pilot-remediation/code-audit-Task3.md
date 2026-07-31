# Code Audit - Pilot Tasks 1-3

**Scope:** Review source-quality and completeness of the first three pilot workstreams:
- Task 1 - Typed pilot configuration and secure defaults (commit 33217b7d)
- Task 2 - Server-side presentation policy (commit da35ca35)
- Task 3 - Remove client reasoning surfaces (commit c84063e0)

**Audit date:** 2026-07-30  
**Branch:** feature/product-first-pilot  
**Auditor:** Claude Code

---

## 1. Executive summary

| Task | Status | Verdict |
|------|--------|---------|
| 1 - Pilot config | Complete | Good. Pydantic contracts and validation match the plan. |
| 2 - Presentation policy | Partial | Core guard works, but mutates OutboundMessage in place and has weak redaction patterns. |
| 3 - Reasoning removal | Incomplete / broken | AgentActivityCluster.tsx is syntactically broken (WebUI does not compile); several files listed in the plan were not modified; residual reasoning references remain in production code. |

**Bottom line:** Do not proceed to Task 4 until the broken WebUI file, in-place mutation bug, and missing Task 3 files are fixed.

---

## 2. What was verified

- Diff review of commits 33217b7d, da35ca35, c84063e0.
- Python tests:
  - tests/config/test_pilot_config.py tests/pilot/test_presentation.py - 21 passed
  - tests/channels/test_channel_manager_reasoning.py tests/channels/test_channel_manager_delta_coalescing.py - 30 passed
  - tests/channels/test_channel_plugins.py test_channel_validation.py test_base_channel.py - 135 passed
- TypeScript compile (npx tsc --noEmit in webui/): failed on AgentActivityCluster.tsx.
- Lint: uv run ruff check on changed Python files - 24 warnings/errors.
- Residual-reasoning search across webui/src, nanobot/channels/websocket, nanobot/channels/telegram.

---

## 3. Detailed findings

### 3.1 Task 1 - Pilot config (commit 33217b7d)

**Quality: good.**

- ChannelsConfig.show_reasoning and BaseChannel.show_reasoning correctly changed to False.
- New Pydantic models (PilotModelClassConfig, PilotRoutingConfig, PilotCaptureConfig, PilotRetentionConfig, PilotConfig) match the plan.
- Validators check HMAC secret when capture enabled, validate routing preset names, and reject tool_heavy without tool support.

**Concerns:**
- ProviderConfig.model_config = ConfigDict(extra=forbid) is a broad change. If any existing code or config passes extra fields into ProviderConfig, it will now raise ValidationError. Verify all provider init paths before release.

---

### 3.2 Task 2 - Server-side presentation policy (commit da35ca35)

**Quality: partial; needs refactor.**

#### 3.2.1 In-place mutation of OutboundMessage

nanobot/channels/manager.py:806-813:

```python
res = self.presentation_policy.sanitize(msg.content, msg.metadata or {})
msg.content = res.content
msg.metadata = res.metadata
```

Plan requires sanitizing copied metadata. Current code mutates the original OutboundMessage. This can affect retries, logging, and capture hooks that may reference the same object later.

**Fix:** sanitize on a copy before sending, or sanitize before constructing the final outbound event.

#### 3.2.2 permits_event called after sanitize, awkward signature

permits_event(event_type, show_reasoning) receives an event object, then imports ProgressEvent inside and checks isinstance. Naming is confusing (event_type vs event object). Also, because it runs after sanitize, reasoning content is still processed (and may trigger counter/metrics) even though the event will be dropped.

**Fix:** Determine event type from the event name or class before any content processing; reject reasoning events early when show_reasoning is False.

#### 3.2.3 Weak redaction patterns

nanobot/pilot/presentation.py:27-34 patterns:
- sk-[a-zA-Z0-9_-]+ over-matches normal text and under-matches real API key shapes.
- Windows path regex only matches C:\ style.
- No general POSIX path redaction.
- No handling for BEGIN PRIVATE KEY blocks, URL credentials, or cookie forms beyond a narrow prefix.

**Fix:** Use a dedicated redactor module (planned for Task 10) even for the presentation guard, or at minimum widen the regex set and add tests for false positives.

#### 3.2.4 Lint errors

- W293 blank lines with whitespace in manager.py and schema.py.
- F401 unused import typing.Any in tests/pilot/test_presentation.py.
- Total: 24 ruff findings, all auto-fixable.

#### 3.2.5 Test gap

test_presentation_sanitizes_metadata has an expected_dropped parameter that is never used. It only checks that forbidden keys are absent in general, not that the specific expected key was dropped per case.

---

### 3.3 Task 3 - Remove client reasoning surfaces (commit c84063e0)

**Quality: incomplete and broken.**

#### 3.3.1 Critical: AgentActivityCluster.tsx does not compile

TypeScript errors:
- src/components/thread/AgentActivityCluster.tsx(381,28): error TS1005: ',' expected.
- src/components/thread/AgentActivityCluster.tsx(398,3): error TS1128: Declaration or statement expected.

The removal of the isReasoningOnlyAssistant branch left orphaned JSX attributes:

```tsx
messages.forEach((message, index) => {
    text={message.reasoning ?? ""}
    streaming={active && !!message.reasoningStreaming}
  />,
);
return;
```

Also, hasVisibleActivity is declared twice because the old hasNonReasoningActivity variable was renamed without removing the original declaration.

**Fix:** Fully remove or complete the messages.forEach branch; remove the duplicate hasVisibleActivity declaration; rerun npx tsc --noEmit until clean.

#### 3.3.2 Missing file modifications listed in the plan

Plan Task 3 listed to modify:
- nanobot/webui/transcript.py - not touched; still contains attach_reasoning_chunk, close_reasoning, prune_reasoning_only, etc.
- tests/utils/test_webui_transcript.py - not touched; still tests reasoning flows.
- nanobot/channels/websocket/tests/test_websocket_channel.py - not touched; still tests send_reasoning_delta/end.
- Create tests/pilot/test_reasoning_client_canaries.py - not created.

#### 3.3.3 Residual reasoning references in production code

Search found reasoning references in:
- webui/src/lib/activity-timeline.ts - reasoningStreaming still used.
- webui/src/components/thread/ThreadMessages.tsx:347 - checks p.reasoning || p.reasoningStreaming.
- webui/src/lib/nanobot-client.ts:54 - handles reasoning_delta.
- webui/src/hooks/useNanobotStream.ts - many reasoning helper functions remain.
- webui/src/components/MessageBubble.tsx:705 - references message.reasoningStreaming.

Plan expects production matches to be limited to explicit ignore/no-op code and tests. Many of these are still active logic, not just compatibility no-ops.

#### 3.3.4 Telegram runtime not modified

Plan listed modifying nanobot/channels/telegram/runtime.py. The commit did not touch it. Telegram channel may not have had reasoning send methods, but the plan expected a no-op change there. Verify whether the base class default is sufficient.

---

## 4. Test results

| Test | Result |
|------|--------|
| pytest tests/config/test_pilot_config.py tests/pilot/test_presentation.py | 21 passed |
| pytest tests/channels/test_channel_manager_reasoning.py tests/channels/test_channel_manager_delta_coalescing.py | 30 passed |
| pytest tests/channels/test_channel_plugins.py test_channel_validation.py test_base_channel.py | 135 passed |
| npx tsc --noEmit | Failed on AgentActivityCluster.tsx |
| uv run ruff check on changed files | 24 findings |

---

## 5. Recommendations (priority order)

1. **Fix AgentActivityCluster.tsx syntax** - highest priority; blocks all WebUI work.
2. **Stop mutating OutboundMessage** in ChannelManager._send_once.
3. **Improve PresentationPolicy** - no in-place mutation, better redaction, clearer event filtering.
4. **Fix ruff findings** - run uv run ruff check --fix.
5. **Complete Task 3** - update nanobot/webui/transcript.py, tests/utils/test_webui_transcript.py, websocket channel tests, create tests/pilot/test_reasoning_client_canaries.py, and remove or isolate residual production reasoning references.
6. **Re-run full gate** - Python tests, ruff, basedpyright, and WebUI build/test before declaring Task 3 done.

---

## 6. Traceability to plan

- Plan Task 2 acceptance: presentation guard drops reasoning events and sanitizes content. Partially met, but implementation mutates state and redaction is weak.
- Plan Task 3 acceptance: no reasoning in WebUI/Telegram payloads, canary tests, legacy frames ignored. Not met due to broken WebUI and missing files/tests.

