# Implementation plan — Advisor tự nhiên + cấu hình chat (agent, advisor, keep-warm cache)

- Status: **draft, chưa triển khai** (chưa sửa code). Viết 2026-09-30. Branch: `develop`.
- Nguồn đối chiếu: `C:\Users\Admin\Workspaces\aicoworker-2026.6.28` — `gateway-source/src/gateway/advisor-consult.ts`,
  `agents/pi-embedded-runner/run/attempt.ts` (nudge trong run), `electron/openclaw-bundled/directives/advisor.cjs`,
  `src/pages/Chat/ChatToolbar.tsx` (toolbar + popup token), `gateway/cache-keepalive-runner.ts`,
  `agents/pi-embedded-runner/cache-keepalive.ts`.
- Commit style: `feat(coworker): …`, `fix(coworker): …`, `feat(webui): …`.

## 1. Mục tiêu

1. Executor tự tham vấn advisor đúng lúc, **trong cùng một câu trả lời**, không cần người dùng `@advisor`.
2. Người dùng thấy được cuộc trao đổi executor ↔ advisor ngay trong thread.
3. Trên giao diện chat: cấu hình advisor (model, mode, ngân sách), **keep-warm prompt cache theo phiên** (ping / 1h),
   auto-optimize theo phiên, trạng thái cache ấm/nguội — ngang aicoworker.
4. Sửa các lỗi đã phát hiện khi rà soát.

Ngoài phạm vi: buffer stream để giấu bản nháp trước khi advisor review; lưu payload request ra đĩa (xem D9).

## 2. Chẩn đoán (tóm tắt)

| # | Vấn đề | Bằng chứng |
|---|--------|-----------|
| P-A | Review nudge chạy sau run, thành turn mới qua bus → câu trả lời tách đôi, race với tin nhắn kế tiếp | `coworker/hook.py` `after_run` → `_maybe_nudge_advisor` → `inject_turn`; aicoworker dùng `activeSession.prompt()` trong run (`attempt.ts:3399`) |
| P-B | Directive advisor bị rút gọn so với bản A/B-tested | `coworker/directives.py` `ADVISOR` vs `advisor.cjs` |
| P-C | Thảo luận không có work tool → không bao giờ nudge; brainstorm tắt nudge | `hook.py` `_maybe_nudge_advisor` |
| P-D | `@advisor` ở coding mode bị thin-context refusal trên phiên mới | `advisor/tool.py` (`allow_thin=…`) |
| P-E | "Kẹt" chỉ dựa vào prompt | — |
| P-F | UI không hiện trao đổi advisor tại chỗ | `AgentActivityCluster.tsx` |
| P-G | Keep-warm chỉ toàn cục, TTL một giá trị, không kickstart/re-warm/backoff, trạng thái sơ sài, không có UI trên chat | `coworker/context/keepalive.py`, `status.py` |
| P-H | Advisor không có bộ đếm ngân sách + nút cấp thêm trên UI | `CoworkerAdvisorControl.tsx`, `commands.py` |
| P-I | Global settings không cho sửa phần `context` (keep-warm, optimize, trim) | `coworker/settings_api.py:33` `EDITABLE_SECTIONS = ("advisor","room","coding")` |

**Lỗi thật (bug):**

| # | Lỗi | Bằng chứng | Hệ quả |
|---|-----|-----------|--------|
| BUG-1 | `_READ_ONLY_TOOLS` dùng tên không tồn tại (`glob`, `search`, `sessions_list`, `session_messages`) | `hook.py:57`; tên thật: `find_files`, `rg`, `list_sessions`, `read_session`, `search_sessions`, `list_exec_sessions` | Tool đọc bị đếm là "work" → nudge sai |
| BUG-2 | Ping keep-alive gọi `provider.chat(...)` **không có** `ProviderCallContext(session_id)` | runner đặt `session_id=spec.session_key` (`agent/runner.py:399`); Codex suy `prompt_cache_key` từ `session_id` (`openai_codex_provider.py:120`); opencode affinity header (`openai_compat_provider.py:915`) | Ping đi sang shard cache khác → không làm ấm cache của phiên, chỉ tốn tiền |
| BUG-3 | 2 lỗi ping liên tiếp là dừng hẳn tới turn thật kế tiếp | `keepalive._ping_loop` | Keep-warm "chết im" sau lỗi mạng thoáng qua |

## 3. Quyết định thiết kế đã chốt

| ID | Quyết định | Lý do / bằng chứng |
|----|-----------|--------------------|
| D1 | Nudge trong run qua `AgentRunSpec.continuation_callback` (đã có, dùng cho goal). Thêm `AgentHook.continuation()`; loop gọi `hook.continuation() or _goal_continue()` | `runner.py:225`, `loop.py:1186,1252`; continuation chỉ chạy khi **không** có tin nhắn user chờ (`_try_drain_injections`) → tin người dùng luôn được ưu tiên |
| D2 | Chip nudge khi đang stream: **không** thêm event mới qua WS. Status coworker thêm `advisor.review_nudge {at, kind}`; strip participants hiện "advisor đang review"; history có message `[auto-advisor-review]` → `coworkerRefreshKey` + `CoworkerMessageCard` đã render chip khi thread nạp lại | Chiếu event mới phải sửa `agent/turn_delivery.py` (upstream, phức tạp); WebUI đã poll status khi `turnActive` |
| D3 | Thẻ advisor inline lấy dữ liệu từ `ToolProgressEvent` của tool `advisor`: `arguments.focus` + `result` (toàn văn) — **không** cần backend mới | `utils/progress_events.py:132` gửi `"result": result` khi phase end; `WebSearchRun` đã đọc `event.result` từ `message.toolEvents` |
| D4 | Ping gọi `provider.chat_with_context(provider_context=ProviderCallContext(session_id=key), …)` | `LLMProvider.chat_with_context` mặc định delegate `chat` (`providers/base.py:1359`); Codex/compat override để dùng session_id. `AnthropicProvider.chat` **không** nhận `provider_context` |
| D5 | TTL 1h (Anthropic): thêm `ProviderCallContext.cache_retention`; thêm hook `AgentHook.adjust_provider_context(context, pc) -> pc` gọi 1 dòng trong `runner._request_model`; `AnthropicProvider` override `chat_with_context`/`chat_stream_with_context` để đọc retention → `_apply_cache_control(ttl="1h")` | Thay đổi upstream nhỏ, cộng thêm, có test; không đụng loop |
| D6 | UI keep-warm/optimize đặt trong **`CoworkerHeaderControls`** (pill cache + popover), dùng chung poll status | `ComposerUsagePopover` không có session/status; header đã có poll `useCoworkerStatus` |
| D7 | Gom các route phiên coworker vào module mới `nanobot/coworker/session_api.py`; `ws_http.py` chỉ đổi regex thành `/api/sessions/{key}/coworker/(advisor\|keepalive\|context)` và một dispatcher | Merge safety: diff `ws_http.py` nhỏ |
| D8 | Mở section `context` trong global settings + tab "Cache" ở `CoworkerSettings.tsx` | P-I |
| D9 | **Không** ghi payload request ra đĩa để ping sau restart (aicoworker có). Chỉ persist `last_llm_call_at/provider/model` vào session metadata để trạng thái đúng sau restart | Payload nhiều MB, chứa output tool/dữ liệu nhạy cảm (`.agent/security.md`) |
| D10 | Tham số ping (max_tokens, reasoning_effort, temperature) giữ nguyên như request thật | Anthropic: đổi tham số thinking làm mất cache của messages |
| D11 | Guard continuation theo iteration: bỏ nudge khi `context.iteration >= max_tool_iterations - 2` (đọc `agents.defaults.max_tool_iterations`) | Continuation được thêm kể cả khi `drain_callback=False` (`runner.py:172`) |
| D12 | Advisor bật/tắt giữa phiên: áp dụng **ngay** (như aicoworker) + cảnh báo vỡ cache khi đang ấm. Auto-optimize: **latch** tới khi cache nguội | Người dùng bật advisor là muốn dùng liền; optimize không gấp |

Quyết định **còn mở** (cần người dùng): G — agent selector / persona theo phiên (xem WS-G).

## 4. Ràng buộc chung

- Logic mới trong `nanobot/coworker/`; file upstream (`agent/hook.py`, `agent/loop.py`, `agent/runner.py`,
  `providers/*.py`, `webui/ws_http.py`, `ThreadShell.tsx`, `AgentActivityCluster.tsx`) chỉ sửa nhỏ, cộng thêm, mỗi
  thay đổi có test riêng.
- Python 3.11, ruff (E,F,I,N,W, 100 cột), basedpyright strict; pytest `asyncio_mode=auto`; test dùng clock giả, không
  `sleep` thật.
- Cache-safety: mọi nội dung chèn vào payload phải xác định theo nội dung/trạng thái đã persist.
- Mọi tính năng mới có cờ config để tắt (rollback không cần revert).

---

## 5. Danh sách task

Ký hiệu cỡ: **S** ≤ nửa ngày, **M** ~1 ngày, **L** 2–3 ngày.

### WS-0 — Sửa lỗi nền

#### T0.1 Ping keep-alive dùng đúng cache key (BUG-2) — S
- `coworker/context/keepalive.py`:
  - `_ping_loop`: thay `cap.provider.chat(...)` bằng
    `cap.provider.chat_with_context(provider_context=ProviderCallContext(session_id=session_key), messages=…, tools=…, model=…, max_tokens=…, temperature=…, reasoning_effort=…)`.
  - Comment D10 cạnh lời gọi.
- Test `tests/coworker/test_keepalive.py` (mới): provider giả ghi kwargs → assert `provider_context.session_id == key`;
  provider giả không override `chat_with_context` vẫn chạy (delegate `chat`).
- Xong khi: test xanh; `ruff`, `basedpyright` sạch.

#### T0.2 Module chính sách advisor + sửa tên tool (BUG-1) — M
- Mới `nanobot/coworker/advisor/policy.py`:
  ```python
  ADVISOR_REVIEW_MARKER = "[auto-advisor-review]"
  KIND_ADVISOR_REVIEW = "advisor_review"
  READ_ONLY_TOOLS: frozenset[str] = frozenset({
      "read_file", "list_dir", "find_files", "rg", "grep", "web_search", "web_fetch",
      "list_sessions", "read_session", "search_sessions", "list_exec_sessions",
  })
  def is_work_tool(name: str) -> bool  # không thuộc NON_EVIDENCE_TOOLS ∪ READ_ONLY_TOOLS

  @dataclass(frozen=True)
  class RunScan: consulted: bool; gap: int; work_total: int
  def scan_run(messages: list[dict[str, Any]]) -> RunScan
      # từ consult._current_run(messages); duyệt tool_calls của assistant theo thứ tự;
      # "advisor" → consulted=True, gap=0; work tool → gap+=1, work_total+=1

  NudgeKind = Literal["first", "reconsult", "coding_result", "discussion"]
  @dataclass(frozen=True)
  class NudgeDecision: kind: NudgeKind; gap: int
  def decide_review_nudge(scan, *, first_gap, reconsult_gap, coding_result: bool) -> NudgeDecision | None
  def review_nudge_text(decision: NudgeDecision) -> str   # luôn bắt đầu bằng ADVISOR_REVIEW_MARKER
  ```
  Text "first"/"reconsult" port nguyên văn `attempt.ts:3407-3414` (kể cả "Do not skip the advisor call.");
  "coding_result" giữ text hiện có ở `hook.py`.
- `hook.py`: xoá `_READ_ONLY_TOOLS`, `ADVISOR_REVIEW_MARKER`, `KIND_ADVISOR_REVIEW` cục bộ → import từ `policy`
  (re-export tên cũ để import bên ngoài không vỡ).
- Test `tests/coworker/test_advisor_policy.py` (mới):
  - không tool → gap 0; 3×`write_file` → gap 3; `advisor` giữa chừng reset gap; `rg`/`find_files` không tính;
  - message `[auto-advisor-review]` không làm mốc run;
  - `decide_review_nudge`: gap 1 < first_gap 2 → None; gap 2 → first; consulted + gap 12 → reconsult;
    coding_result chưa consult → coding_result; đã consult → None;
  - mọi tên trong `READ_ONLY_TOOLS` tồn tại trong registry của fixture loop (test chống đổi tên sau này).

### WS-ADV — Tương tác advisor

#### T1.1 Hook continuation (upstream) — S
- `nanobot/agent/hook.py`:
  - `AgentHook.continuation(self) -> str | None: return None`
  - `CompositeHook.continuation`: duyệt `self._hooks`, try/except log như `transform_request`, trả text khác rỗng đầu tiên.
- `nanobot/agent/loop.py` (1 dòng): `continuation_callback=lambda: hook.continuation() or _goal_continue(),`
- Test `tests/agent/test_hook_continuation.py` (mới): first-non-None; hook ném lỗi bị bỏ qua; không hook nào → None.
- Test `tests/agent/test_loop_*` hiện có vẫn xanh (goal continuation không đổi hành vi).

#### T1.2 Nudge trong run — M (phụ thuộc T0.2, T1.1)
- `coworker/hook.py` `CoworkerHook`:
  - `__init__`: `self._nudged = False`, `self._iter_ctx: AgentHookContext | None = None`.
  - `before_iteration`: thêm `self._iter_ctx = context`.
  - `continuation()` (sync):
    1. `if self._nudged or not self._key: return None`
    2. `cfg = load_coworker_config()`; `if not cfg.advisor.review_nudge: return None`
    3. Loại: `is_automated_turn`, kind khác `None`/`coding_result`, turn không genuine (không có `_genuine_text` và
       không phải `coding_result`).
    4. D11: `if self._iter_ctx and self._iter_ctx.iteration >= max_iter - 2: return None`.
    5. `session = get_session(key)`; `eff = advisor_state.effective(session)`; budget; breaker (logic hiện có).
    6. `scan = policy.scan_run(self._iter_ctx.messages)`; `decision = policy.decide_review_nudge(...)`.
    7. Có → `self._nudged = True`; `advisor_state.record_review_nudge(session, kind=…, now=time.time())`; log;
       `return policy.review_nudge_text(decision)`.
  - `after_run`: bỏ lời gọi `_maybe_nudge_advisor`; xoá hàm này và `_NUDGE_KINDS`.
- `advisor/state.py`: `record_review_nudge(session, *, kind, now)` → `slot["review_nudge"] = {"at", "kind"}`.
- `status.py`: `advisor.review_nudge` trong payload.
- Test `tests/coworker/test_hook.py` (thay test nudge cũ):
  - genuine turn + 2 `write_file` chưa consult → text marker; gọi lần 2 → None;
  - consult rồi 12 work tool → reconsult; breaker mở / hết budget / advisor off / `cron:` key / workflow step → None;
  - `coding_result` chưa consult → text diff; iteration sát max → None.
- Test `tests/coworker/test_loop_integration.py`: provider giả trả final → runner gọi LLM thêm lần nữa **cùng run**;
  `bus.inbound` rỗng; history có đúng 1 message `[auto-advisor-review]`; goal đang active → advisor nudge trước, goal
  continuation ở final kế tiếp.
- Xong khi: `grep -r "kind=KIND_ADVISOR_REVIEW" nanobot/` rỗng.

#### T1.3 WebUI hiện nudge khi đang stream (D2) — S (phụ thuộc T1.2)
- `webui/src/lib/types.ts`: `CoworkerAdvisorStatus.review_nudge?: {at: number; kind: string} | null`.
- `CoworkerParticipants.tsx`: advisor ở trạng thái "đang review" khi `review_nudge.at` ≥ thời điểm bắt đầu turn hoặc
  có `active_consult`.
- `ThreadShell.tsx`: không đổi (message marker đã tăng `coworkerRefreshKey` khi thread nạp lại).
- **Kiểm tra thủ công bắt buộc:** sau turn kết thúc, bong bóng có chip nudge mà không cần F5. Nếu không → thêm
  refetch history khi `turnActive` chuyển false **và** status có `review_nudge.at` mới (sửa trong
  `CoworkerHeaderControls`, không đụng `useNanobotStream`).
- Test `webui/src/tests/coworker-participants.test.tsx`: trạng thái reviewing.

#### T2.1 Khôi phục directive đầy đủ — S
- `coworker/directives.py` `ADVISOR`: port nguyên văn `advisor.cjs` (content array), thay:
  - `(ls, grep, find, read, fetch)` → `(read_file, list_dir, find_files, rg/grep, web_fetch)`;
  - `(plan_task / write_todos)` → `(a short written plan in your reply, or create_goal for long multi-turn work)`;
  - `state-changing exec call` → `write_file / edit_file / apply_patch / state-changing exec call`.
  Docstring module: "A/B-measured prompt — reword only with a reason".
- Test `tests/coworker/test_directives.py` (mới): có các câu then chốt ("calling advisor is the NEXT action",
  "err toward re-consulting", "This is a checkpoint, not a difficulty judgment", "which constraint breaks the tie",
  "Never treat that refusal as an error"); không có `write_todos`/`plan_task`; gọi 2 lần giống byte.

#### T3.1 `@advisor` không bị thin-context refusal — S
- `advisor/state.py`: `mark_user_request(session)`, `clear_user_request(session)`, `user_requested(session) -> bool`;
  thêm khoá `user_request` vào danh sách pop khi `/new` trong `_slot`.
- `coworker/hook.py` `before_run` (genuine turn): `ADVISOR_MENTION in scheduler.mention_ids(text)` → mark, ngược lại clear.
- `advisor/tool.py`: `allow_thin=… or advisor_state.user_requested(session)`; consult thành công → `clear_user_request`.
- `directives.advisor_mention_note(enabled=True)`: thêm câu "This consult is user-requested and will not be refused
  for thin context."
- Test: phiên mới, không evidence: có cờ → provider advisor được gọi; không cờ → `insufficient_context`; turn sau không
  mention → cờ bị xoá; `/new` xoá cờ.

#### T4.1 Discussion gate — M (phụ thuộc T1.2)
- `coworker/config.py` `AdvisorConfig`:
  `discussion_gate: Literal["off","brainstorm","always"] = "brainstorm"`,
  `discussion_min_chars: int = Field(default=800, ge=100)`.
- `policy.py`: `decide_discussion_gate(scan, *, draft_chars, mode, gate, min_chars, first_gap) -> NudgeDecision | None`
  — áp dụng khi gate khớp mode, `not scan.consulted`, `scan.work_total < first_gap`, `draft_chars >= min_chars`.
  Text: "Before this answer stands, call advisor(focus=<the user's core question, 1 sentence>) — it sees your draft
  above. Then add a SHORT follow-up (not a rewrite): where it agrees, where it differs, and your final position. If it
  changes nothing material, say so in one line."
- `hook.continuation()`: sau review nudge, thử discussion gate với
  `draft_chars = len((self._iter_ctx.response.content if self._iter_ctx and self._iter_ctx.response else "") or "")`.
- `directives.ADVISOR_BRAINSTORM`: thêm câu harness sẽ yêu cầu review bản nháp; đổi "Do not paste verbatim" thành
  "You may quote the advisor's key point in one short attributed line — never paste the whole advice."
- `settings_api.py` + `CoworkerSettings.tsx` (tab Advisor): select gate + ô số min chars; i18n en/vi.
- Test: policy tổ hợp gate/mode/draft/work; hook brainstorm draft 1000 → discussion; 200 → None; gate off → None;
  `test_settings_api.py` round-trip field mới.

#### T5.1 Phát hiện kẹt — M (phụ thuộc T0.2)
- Mới `coworker/advisor/stuck.py`:
  ```python
  def failure_signature(tool_name: str, args: dict[str, Any], result: Any) -> str | None
      # lỗi = getattr(result, "is_error", False) hoặc (tool in {"exec","exec_session"} và "Exit code: N", N != 0)
      # exec → "exec:" + command gộp khoảng trắng
      # khác → f"{tool}:" + dòng lỗi đầu, bỏ số/đường dẫn/hex/timestamp, cắt 160
  class StuckTracker:
      def record(self, signature: str | None) -> bool   # True khi signature xuất hiện lần 2 kể từ reset
      def reset(self) -> None
  ```
- `advisor/state.py`: `add_stuck_id(session, call_id)` (list tối đa 50, pop khi `/new`), `stuck_ids(session)`.
- `coworker/hook.py`:
  - `self._stuck = StuckTracker()`;
  - `after_execute_tool` / `on_execute_tool_error`: tool `advisor` → reset; ngược lại nếu advisor bật, mode coding,
    còn budget, `cfg.advisor.stuck_detection` → `record`; True → `add_stuck_id(session, tool_call.id)`.
  - `transform_request`: `_annotate_stuck(messages, stuck_ids)` sau `_annotate_mentions` — message `role="tool"` có
    `tool_call_id` thuộc tập → append
    `"\n\n[nanobot: same failure as an earlier attempt — call advisor(focus=\"<what failed and what you tried>\") before another fix attempt.]"`.
- `AdvisorConfig.stuck_detection: bool = True` (+ settings API/UI).
- Test `tests/coworker/test_advisor_stuck.py`: chuẩn hoá signature; exit 0 không lỗi; lần 2 → True; reset sau advisor;
  annotate đúng message, byte-stable qua 2 lần transform, không annotate khi advisor off.

#### T6.1 Thẻ tham vấn inline (D3) — M
- Mới `webui/src/components/thread/activity/advisor-consult-model.ts`:
  `parseAdvisorResult(result: unknown) -> {kind: "advice", model, n, max, text} | {kind: "status", status, fallback} | null`
  (advice: regex `^ADVISOR \((.+?)\) — advice (\d+)/(\d+):\n\n([\s\S]*?)\n\n---\n`; status: JSON có `status`).
- Mới `webui/src/components/thread/activity/AdvisorConsultRow.tsx`:
  running → "Đang hỏi advisor · {focus}" + đồng hồ; advice → thẻ câu hỏi (focus) + lời khuyên markdown thu gọn 4 dòng,
  `n/max`, model; status → chip ("chưa đủ ngữ cảnh", "hết ngân sách", "lỗi advisor").
- `AgentActivityCluster.tsx`: tạo `advisorRunsByLine` từ `message.toolEvents` (name `advisor`), dispatch giống
  `WebSearchRun` (khối `lines.forEach`, ~15 dòng cộng thêm).
- i18n `coworker.advisorConsult.*` (en + vi đầy đủ; locale khác `defaultValue`).
- Test `webui/src/tests/advisor-consult-row.test.tsx`: parse advice/status/rác; render running/advice/status.

#### T7.1 Ngân sách advisor + cảnh báo cache (A1, A2, A3) — S
- `advisor/state.py`: `reset_uses(session)`.
- `coworker/session_api.py` (T-KW5) route advisor: nhận thêm `reset_uses: bool`.
- `commands.py`: `/advisor reset`; cập nhật `_ADVISOR_USAGE`.
- `CoworkerAdvisorControl.tsx`: chip `uses/max ⟲` (đỏ khi hết, click = reset); dòng cảnh báo khi
  `status.caching.is_warm` và người dùng đổi on/off/mode/preset: "Thay đổi này làm lần gửi kế tiếp tính giá ghi cache
  đầy đủ."; rà nhãn "Tự động (mặc định: X)" / "Tắt cho phiên này".
- Test: `test_advisor_switch.py` (reset), `coworker-advisor-control.test.tsx` (chip, cảnh báo).

### WS-KW — Keep-warm prompt cache

#### T-KW1 Cài đặt keep-warm theo phiên — S
- Mới `coworker/context/keepalive_state.py`:
  ```python
  Strategy = Literal["ping", "ttl1h"]
  @dataclass(frozen=True)
  class KeepWarmSetting:
      enabled: bool; strategy: Strategy; window_min: int; set_at: float
      source: Literal["session", "global"]
  def effective(session) -> KeepWarmSetting        # session_state["keepalive"] ?? cfg.context.keepalive
  def apply(session, *, enabled: bool | None, strategy: Strategy | None = None,
            window_min: int | None = None) -> KeepWarmSetting   # enabled=None → xoá override; ghi set_at=now
  def clamp_window(v: int | None) -> int            # 1..120, mặc định 30
  ```
- `config.py` `KeepaliveConfig`: thêm `strategy: Literal["ping","ttl1h"] = "ping"`.
- `hook.transform_request`: điều kiện capture dùng `keepalive_state.effective(session).enabled`.
- Test `tests/coworker/test_keepalive_state.py`: kế thừa toàn cục; override; clear; clamp; `set_at` cập nhật.

#### T-KW2 Chính sách TTL theo provider — S
- Mới `coworker/context/cache_policy.py`:
  ```python
  @dataclass(frozen=True)
  class CacheTtlPolicy: ttl_s: float; lead_s: float; ping_cap: int; guaranteed: bool
  def provider_family(provider) -> tuple[str, str]  # (provider_name, backend) từ provider.provider_name + registry.find_by_name
  def resolve(provider, model: str, *, retention: Literal["short","long"] = "short",
              ttl_override: int | None = None) -> CacheTtlPolicy | None
  def supports_ttl1h(provider) -> bool               # backend == "anthropic" và provider_name == "anthropic"
  ```
  Bảng: Anthropic family (backend anthropic, hoặc model chứa `claude`) 300/3600·60·6·guaranteed (guaranteed chỉ khi
  direct); `openai`, `openai_codex` 300·60·4·False; gemini/google/antigravity 240·45·2·False; xai/grok 240·45·2·False;
  khác → `None`. `ttl_override` (config `cache_ttl_seconds`) thắng `ttl_s`.
- Test `tests/coworker/test_cache_policy.py`: mỗi họ provider (dùng spec thật trong `providers/registry.py`), override,
  None cho provider lạ.

#### T-KW3 Runner keep-warm theo tick (BUG-3) — L (phụ thuộc T0.1, T-KW1, T-KW2)
- Viết lại `coworker/context/keepalive.py`:
  - `_Capture` thêm: `session_id`, `last_touch`, `real_at`, `pings`, `failures`, `last_failure_at`, `last_error`,
    `pinging`, `in_flight`, `set_at_seen`, `forced_long`, `spent{pings,input,output,cache_read,cache_write}`.
  - `capture(...)` chỉ ghi capture (không tạo task riêng) + `ensure_runner()`.
  - `mark_in_flight(session_key, flag)`: gọi từ `CoworkerHook.transform_request` (True) và `after_iteration`/`on_finally` (False).
  - Runner: một task tick 15s (`spawn_background`), tự dừng khi `_captures` rỗng. Hàm thuần
    `evaluate(cap, setting, policy, now) -> Literal["none","kickstart","rewarm","ping"]` (để test không cần async):
    ```
    if cap.pinging or cap.in_flight or not setting.enabled or policy is None: none
    if setting.set_at > cap.last_touch and cap.failures < 2: kickstart
    if setting.strategy == "ttl1h" and supports_ttl1h: none
    if now - cap.real_at > window: none
    if cap.pings >= min(policy.ping_cap, cfg.max_pings): none
    if cap.failures >= 2 and now - cap.last_failure_at < 120: none      # backoff
    expires = cap.last_touch + policy.ttl_s
    if now > expires + 20: rewarm                                       # restart window
    if now >= expires - policy.lead_s: ping
    ```
    Re-enable (`set_at` mới) xoá park một lần (như `failuresResetForSetAt`).
  - `_send_ping(cap, *, kickstart, retention)`: D4 + D10; thành công → `last_touch=now`, `optimizer.touch`, kickstart/
    rewarm → `real_at=now, pings=1`, ngược lại `pings+=1`; `failures=0`; cộng `spent` từ `usage`
    (`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`). Lỗi → `failures+=1`,
    `last_failure_at`, `last_error` (≤200 ký tự).
  - `cancel_all()` giữ nguyên hợp đồng.
- Test `tests/coworker/test_keepalive.py` (mở rộng, clock giả): kickstart khi `set_at` mới; ping tới hạn; rewarm
  restart counter; cap chặn; backoff 120s rồi thử lại; re-enable xoá park; ttl1h không ping định kỳ; `in_flight` chặn;
  hết window dừng; runner tự dừng khi không còn capture.

#### T-KW4 Trạng thái keep-warm — M (phụ thuộc T-KW3)
- `keepalive.status_for(session) -> dict` (snake_case): `known, enabled, source, strategy, effective_strategy,
  window_min, provider, model, guaranteed, real_turn_at, last_touch_at, ttl_s, expires_at, ttl1h_supported,
  ttl1h_armed, pings, ping_cap, can_ping, next_ping_at, est_tokens_per_ping, spent, parked, last_error, run_active`.
  - `est_tokens_per_ping` = `metrics.snapshot(key)["last"]["input_tokens"]`.
  - Không có capture (vừa restart) → dùng `session_state["cache"] = {last_llm_call_at, provider, model}`; `can_ping=False`.
- `CoworkerHook.after_iteration`: ghi `session_state["cache"]` (D9).
- `status.py`: `caching.keepalive = status_for(session)`; `is_warm/remaining_seconds/ttl_seconds` tính từ `expires_at`.
- `webui/src/lib/types.ts`: `CoworkerKeepaliveStatus`; mở rộng `CoworkerCachingStatus`.
- Test `test_status.py`: shape; restart (không capture) → `known` từ metadata, `can_ping=false`; `is_warm` theo policy.

#### T-KW5 API phiên coworker gom một chỗ (D7) — M
- Mới `nanobot/coworker/session_api.py`:
  ```python
  class SessionApiError(Exception): status: int
  def apply_advisor(session, payload) -> None      # chuyển logic từ ws_http._handle_session_coworker_advisor (+ reset_uses)
  def apply_keepalive(session, payload) -> None    # {enabled: bool|None, strategy?, window_min?}; ttl1h khi provider không hỗ trợ → 400
  def apply_context(session, payload) -> None      # {optimize?: bool|None, trim?: bool|None} (T-KW8)
  SECTIONS = {"advisor": apply_advisor, "keepalive": apply_keepalive, "context": apply_context}
  ```
- `webui/ws_http.py`: regex mutation `^/api/sessions/[^/]+/(delete|coworker/(advisor|keepalive|context))$`; route
  dispatcher `_handle_session_coworker_section(request, key, section)` giữ nguyên các kiểm tra token/mutation/key hiện có,
  gọi `SECTIONS[section]` trong `asyncio.to_thread`, `manager.save`, trả `coworker_session_status`; action WS
  `session.coworker.{advisor,keepalive,context}`.
- `webui/src/lib/api.ts`: `setCoworkerKeepalive`, `setCoworkerContext` theo mẫu `setCoworkerAdvisor`.
- Test: `tests/coworker/test_session_api.py` (mới) cho từng section + lỗi validate; test ws hiện có cho advisor vẫn xanh
  (`nanobot/channels/websocket/tests/…` nếu có route test).

#### T-KW6 Optimizer dùng TTL hiệu lực — S (phụ thuộc T-KW2, T-KW4)
- `coworker/hook.transform_request`: `ttl = cache_policy.resolve(runtime.provider, runtime.model,
  retention="long" if ttl1h_armed else "short", ttl_override=ctx_cfg.cache_ttl_seconds).ttl_s` (fallback
  `optimizer.DEFAULT_TTL_S` khi None) → `OptimizePolicy.ttl_s` và `keepalive.capture`.
- Test `test_optimizer.py`: TTL 3600 → không re-decide trước 1h; 300 → re-decide sau 5 phút.

#### T-KW7 UI pill cache + popover (D6) — L (phụ thuộc T-KW4, T-KW5)
- Mới `webui/src/components/coworker/CoworkerCachePill.tsx`:
  - Pill: ấm = cam + đếm ngược `expires_at - now` (tiền tố `~` khi `guaranteed=false`) + 🔥 nếu keep-warm bật;
    nguội = xanh ❄️; `run_active` → "ấm (đang chạy)"; `known=false` → ẩn.
  - Tick 1s khi popover mở, 15s khi đóng (không thêm poll: dùng `feed.status` từ `CoworkerHeaderControls`).
- Mới `CoworkerKeepWarmSection.tsx` (trong popover):
  switch (tri-state: kế thừa / bật / tắt — nhãn "theo cài đặt chung" khi `source=global`); select chiến lược (`ttl1h`
  chỉ khi `status.caching.keepalive.provider` hỗ trợ — backend trả `ttl1h_supported`); select cửa sổ 15/30/60/120;
  dòng trạng thái: `⏳ còn {left} · {pings}/{cap} ping` | `⏹ hết cửa sổ` | `⏹ đủ {cap} ping, để nguội` |
  `ttl1h: đã giữ 1 giờ / sẽ áp dụng từ lần gửi kế`; tooltip ⓘ: token/ping, tổng đã tiêu, lần ping kế; cảnh báo đỏ khi
  `parked` kèm `last_error`.
- Mới `CoworkerAutoOptimizeSection.tsx` (T-KW8).
- `CoworkerHeaderControls.tsx`: gắn `<CoworkerCachePill …/>` sau `CoworkerAdvisorControl`.
- i18n `coworker.cache.*`, `coworker.keepWarm.*` (en + vi đầy đủ).
- Test `webui/src/tests/coworker-cache-pill.test.tsx`: ấm/nguội/đang chạy/ẩn; switch gọi `setCoworkerKeepalive` đúng
  payload; `ttl1h` ẩn/hiện; dòng trạng thái các nhánh; parked.

#### T-KW8 Auto-optimize theo phiên + latch (D12) — M
- `session_state["context"] = {"optimize": bool|None, "trim": bool|None, "latched": {...}}`.
- `optimizer.optimize_payload`: nhận `requested` và trả/ghi `latched` — giá trị mới chỉ được chép vào `latched` khi `cold`.
- `hook.transform_request`: `optimize`/`trim` hiệu lực = `latched`; directive `WASTED` + tool `mark_context_wasted`
  theo `latched` (không đổi giữa lúc ấm).
- `status.py`: `caching.optimize = {enabled, latched, pending, source, dropped, rewritten, trimmed, saved_messages}`.
- UI `CoworkerAutoOptimizeSection`: switch; "⏳ sẽ áp dụng khi cache nguội" khi `pending`; số message đã gọn.
- Test: bật khi ấm → payload không đổi tới khi cold; tắt tương tự; directive/tool theo latched.

#### T-KW9 Global settings: tab Cache (D8) — M
- `settings_api.py`: thêm `"context"` vào `EDITABLE_SECTIONS`; validate (window 1..240, max_pings 1..20, ttl ≥ 30).
- `CoworkerSettings.tsx`: tab "Cache": keep-warm mặc định (bật, chiến lược, cửa sổ, max pings, lead), optimize, trim
  (max turns), freeze system prompt, TTL override. Có dòng giải thích chi phí (ping ≈ đọc lại toàn prompt ở giá cache).
- Test `test_settings_api.py`, `webui/src/tests/coworker-settings*.test.tsx`.

#### T-KW10 TTL 1 giờ cho Anthropic (D5) — M (phụ thuộc T-KW3)
- `providers/base.py` `ProviderCallContext`: `cache_retention: Literal["short","long"] | None = None`.
- `agent/hook.py`: `AgentHook.adjust_provider_context(self, context, provider_context) -> ProviderCallContext`
  (mặc định trả nguyên); `CompositeHook` pipeline có cô lập lỗi.
- `agent/runner.py` `_request_model`: sau `provider_context = replace(…, response_preset=…)` thêm
  `provider_context = hook.adjust_provider_context(context, provider_context)`.
- `providers/anthropic_provider.py`: override `chat_with_context` / `chat_stream_with_context` → truyền
  `cache_ttl="1h"` khi `cache_retention == "long"` xuống `_build_kwargs` → `_apply_cache_control(marker={"type":
  "ephemeral","ttl":"1h"})`. Mặc định không đổi byte request hiện tại.
- `CoworkerHook.adjust_provider_context`: phiên có `strategy="ttl1h"` và `supports_ttl1h` → `cache_retention="long"`;
  keepalive kickstart ping cũng dùng `long` (chuyển cache đang ấm sang 1h với giá đọc); đánh dấu `ttl1h_armed` khi
  request thật đầu tiên sau `set_at` thành công.
- Test: `tests/providers/test_anthropic_cache_ttl.py` (payload có `ttl: "1h"` chỉ khi long; mặc định giữ nguyên);
  `tests/agent/test_hook_provider_context.py`; `test_keepalive.py` ttl1h kickstart.

### WS-G — Agent trên chat (cần quyết định trước khi làm)

- Model theo phiên: **đã có** (`ModelPresetBadge`, `session.metadata.model_preset`) — không làm.
- Agent selector: aicoworker có nhiều agent danh tính sở hữu phiên; nanobot chỉ có một agent + room teammates
  (`RoomAgentConfig`: name, emoji, bio, preset, instructions).
  - **Phương án 1 — Không port.**
  - **Phương án 2 — Persona theo phiên (T-G1, M):** `session_state["persona"] = agent_id`; `transform_request` chèn
    section `## Persona` từ `instructions` (deterministic); đặt model preset phiên = `preset` của persona khi chọn;
    header hiện emoji + tên; cảnh báo vỡ cache khi đổi giữa phiên; route `session.coworker.persona` qua `session_api`.
    Không có workspace/memory riêng.
  - Đề xuất: Phương án 2, làm sau cùng.

### WS-DOC — Tài liệu & kiểm thử thủ công

#### T-DOC1 — S
- `docs/coworker/README.md`: luồng advisor mới, keep-warm (chiến lược, chi phí, giới hạn), bảng config mới
  (`advisor.discussion_gate`, `discussion_min_chars`, `stuck_detection`, `context.keepalive.strategy`).
- Cập nhật mục "Status" của file plan này khi từng milestone xong.

#### Kịch bản E2E thủ công (gateway + WebUI, executor model yếu, advisor model mạnh)
1. Sửa bug nhiều file, không mention → advisor gọi sau orient và trước khi báo xong; **một** bong bóng; chip nudge.
2. Test fail cùng lỗi 2 lần → tool result có note; hành động kế là `advisor`.
3. Brainstorm, câu hỏi chiến lược → có review + phần bổ sung "đồng ý / khác ở…".
4. Phiên mới, "@advisor nên dùng Postgres hay SQLite?" ở coding mode → không bị refuse.
5. Gửi tin nhắn mới ngay khi agent vừa trả lời → tin người dùng được xử lý trước, không có turn review lạc chỗ.
6. Bật advisor giữa run → dùng được ngay; popover cảnh báo cache.
7. Advisor model sai → breaker mở → không nudge, không treo.
8. Keep-warm Anthropic: bật → kickstart; để yên 20 phút → pill cam suốt, ping ≤ 6, `cache_read` tăng, `cache_write` nhỏ.
9. Keep-warm Codex: bật → log provider cho thấy `prompt_cache_key` của ping = của request thật; hit rate turn kế ≥ 80%.
10. `ttl1h`: bật → turn kế có `ttl:"1h"`; sau 30 phút không ping, turn kế vẫn hit cache.
11. Rút mạng khi ping → parked + lỗi hiện đỏ; có mạng lại → tự thử lại sau 120s.
12. Restart gateway giữa lúc ấm → pill vẫn đúng (từ metadata), `can_ping=false`, ping chạy lại sau turn thật.
13. Bật auto-optimize khi ấm → "sẽ áp dụng khi nguội"; sau TTL → áp dụng.

## 6. Milestone & thứ tự

| Milestone | Task | Kết quả người dùng thấy | Trạng thái |
|-----------|------|-------------------------|------------|
| M1 | T0.1, T0.2 | Keep-warm Codex/opencode thật sự giữ ấm; nudge không còn bắn do tool đọc | [x] Hoàn thành |
| M2 | T1.1, T1.2, T1.3, T2.1, T3.1 | Advisor tự được gọi trong cùng câu trả lời; `@advisor` luôn chạy | [x] Hoàn thành |
| M3 | T-KW1 → T-KW7 | Pill cache ấm/nguội + bật keep-warm theo phiên trên chat | [x] Hoàn thành |
| M4 | T7.1, T-KW8, T-KW9 | Ngân sách advisor trên UI; auto-optimize theo phiên; tab Cache global | [x] Hoàn thành |
| M5 | T-KW10 | Chiến lược cache 1 giờ cho Anthropic | [x] Hoàn thành |
| M6 | T4.1, T5.1, T6.1 | Advisor tham gia thảo luận; phát hiện kẹt; thẻ trao đổi inline | [x] Hoàn thành |
| M7 | T-G1 (nếu chọn), T-DOC1 | Persona theo phiên; tài liệu | [x] T-DOC1 hoàn thành |

Mỗi milestone: `ruff check nanobot/`, `uv run --no-sync basedpyright`, `pytest tests/coworker tests/agent -q`
(+ `tests/providers` ở M5), `cd webui && bun run test && bun run build` khi có thay đổi WebUI; chạy các kịch bản E2E
liên quan.

## 7. Cờ tắt (rollback không cần revert)

| Tính năng | Cờ |
|-----------|----|
| Review nudge trong run | `coworker.advisor.review_nudge=false` |
| Discussion gate | `coworker.advisor.discussion_gate="off"` |
| Stuck detection | `coworker.advisor.stuck_detection=false` |
| Keep-warm | tắt theo phiên trên UI / `coworker.context.keepalive.enabled=false` |
| TTL 1h | chọn chiến lược `ping` |
| Auto-optimize | tắt theo phiên / `coworker.context.optimize=false` |

## 8. Rủi ro

| Rủi ro | Giảm thiểu |
|--------|-----------|
| Continuation vượt `max_iterations` | D11 + test |
| Model yếu phớt lờ nudge | Đo trong E2E (tỉ lệ turn nudge mà không gọi advisor); nếu cao, cân nhắc hard gate — ngoài phạm vi |
| Discussion gate tốn ngân sách advisor | Mặc định chỉ brainstorm, `min_chars`, one-shot/run, tôn trọng `max_uses` |
| Ping tốn tiền vô ích | Ping cap theo provider (≈ nửa điểm hoà vốn), window, backoff, không ping provider không có policy, không ping khi đang in-flight |
| Merge conflict upstream (`agent/hook.py`, `loop.py`, `runner.py`, `anthropic_provider.py`, `ws_http.py`, `AgentActivityCluster.tsx`) | Mỗi chỗ ≤ ~20 dòng cộng thêm, có test riêng; logic nằm trong `coworker/` |
| `ttl1h` sai provider (Bedrock/OpenRouter) | `supports_ttl1h` chỉ Anthropic direct; API trả 400 khi không hỗ trợ |
| Cache bust khi đổi advisor/persona giữa phiên | Cảnh báo trên UI (D12) |

## 9. Checklist commit

1. `fix(coworker): keep-alive pings reuse the session cache key` (T0.1)
2. `refactor(coworker): extract advisor nudge policy, fix read-only tool names` (T0.2)
3. `feat(agent): hook-provided run continuation` (T1.1)
4. `feat(coworker): in-run advisor review nudge` (T1.2, T1.3)
5. `feat(coworker): restore full advisor timing directive` (T2.1)
6. `fix(coworker): user-requested @advisor bypasses thin-context refusal` (T3.1)
7. `feat(coworker): per-session keep-warm with provider TTL policy` (T-KW1–T-KW4, T-KW6)
8. `feat(coworker): session coworker API sections` (T-KW5)
9. `feat(webui): cache pill and keep-warm controls` (T-KW7)
10. `feat(coworker): advisor budget reset and cache warnings` (T7.1)
11. `feat(coworker): per-session auto-optimize with cold-cache latch` (T-KW8)
12. `feat(webui): coworker cache settings tab` (T-KW9)
13. `feat(providers): anthropic 1h prompt cache retention` (T-KW10)
14. `feat(coworker): advisor discussion gate` (T4.1)
15. `feat(coworker): mechanical stuck detection for advisor` (T5.1)
16. `feat(webui): inline advisor consult card` (T6.1)
17. `feat(coworker): per-session persona` (T-G1, nếu chọn)
18. `docs(coworker): advisor interaction and keep-warm` (T-DOC1)
