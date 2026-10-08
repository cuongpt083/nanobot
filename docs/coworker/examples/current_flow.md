# Coworker: luồng hiện tại giữa coordinator và advisor

Tài liệu ghi lại logic xử lý hiện tại (đọc từ code, tại thời điểm viết) của tương tác
giữa persona coordinator và advisor trong `nanobot/coworker/`.

## 1. Vai trò

- **Coordinator (executor)**: agent của session đang trò chuyện với người dùng.
  Persona chỉ đổi giọng và prompt của coordinator (`nanobot/coworker/persona.py`,
  `docs/coworker/README.md` mục Persona), không tạo agent thứ hai.
- **Advisor**: model mạnh hơn, chạy một lần (one-shot) qua
  `runtime.provider.chat_with_retry(tools=None)` (`advisor/consult.py:263-342`).
  Advisor không có tool và không giữ trạng thái giữa các lần gọi. Trạng thái nằm ở
  harness: ledger, số lần đã dùng, lịch sử.

## 2. Khi nào phát sinh consult

Có năm nguồn kích hoạt:

1. **Coordinator tự gọi** `advisor(focus, files)` theo mục `## Advisor` trong system
   prompt (`directives.py:29-94`). Thứ tự bắt buộc: ORIENT → CONSULT → PLAN → EXECUTE.
   Gọi khi bị kẹt, trước khi đổi hướng, trước khi báo xong, và ở mỗi milestone.

2. **Harness nudge sau lượt** (`hook.py:818-898`, `advisor/policy.py`). Đây là
   `continuation()`, sinh tin nhắn tiếp tục trong cùng run.

   | Loại | Điều kiện | Ngưỡng mặc định |
   |---|---|---|
   | `first` | Chưa consult, đã có work step | `first_consult_gap` = 2 |
   | `reconsult` | Đã consult, work step kể từ lần cuối | `reconsult_gap` = 12 |
   | `coding_result` | Coding task xong mà chưa consult | — |
   | `discussion` | Chế độ brainstorm, bản nháp dài | `discussion_min_chars` = 800 |
   | `done_gate` | Ledger còn `must_fix`/`verify` mở | — |

   Read-only tool (`read_file`, `rg`, `web_fetch`, ...) không tính là work step
   (`policy.py:34-37`).

3. **Note giữa run** gắn vào tool result (`hook.py:353-417`):
   - C3: lần ghi file đầu tiên mà chưa consult.
   - C1: đã đủ 12 work step hoặc 5 file đã ghi kể từ lần consult cuối.
   - Checkpoint do advisor đặt (`next_checkpoint`).
   - Verdict `stop` khi đang ghi file.

4. **Commit gate C2** (`hook.py:452-496`): chặn `git commit/push/reset --hard/rm -rf`
   nếu đã ghi file mà chưa có consult thành công sau đó.

5. **Người dùng**: `@advisor` (`directives.advisor_mention_note`; `mark_user_request`
   bỏ qua thin-context), `/advisor on|off|brainstorm|code`, hoặc công tắc trên header.

## 3. Coordinator đóng gói gì gửi advisor

`advisor/tool.py:90-226`, mỗi lần gọi:

- **Kiểm tra trước**: `eff` là None → `advisor_disabled`; hết `max_uses` →
  `max_uses_exceeded`; preset lỗi → `advisor_error`.
- **Transcript**: lấy `live_messages` của session. Mỗi tool result cắt còn tối đa
  4000 ký tự (2000 đầu + 1000 cuối), args tối đa 600 ký tự. Tổng tối đa 480k ký tự.
  Nếu vượt, giữ lượt user đầu tiên và phần đuôi mới nhất, chèn marker
  "earlier messages omitted" (`consult.py:162-202`).
- **System prompt của executor** được chuyển nguyên văn, nên advisor thấy cả persona
  prompt.
- **Harness evidence** (`advisor/evidence.py`): git status/diff, output test, và tối đa
  5 file do coordinator chỉ định trong `files`, đọc trực tiếp từ đĩa. Khối này được gắn
  nhãn "collected by the harness, not written by the executor".
- **Ledger trước đó**, hiển thị lại để advisor cập nhật.
- **Focus**: tối đa 500 ký tự, chỉ bổ sung cho transcript, không thay thế.
- **Yêu cầu độ dài**: khoảng 300 từ, `max_tokens` 4096, timeout cứng 180 giây.

Prompt yêu cầu coordinator nêu sự kiện, không nêu kết luận muốn được xác nhận.
Ví dụ: "mục tiêu · kế hoạch · file đã đổi · điều đang không chắc".

## 4. Harness xử lý phản hồi của advisor

- **Tách ledger** (`advisor/ledger.parse_ledger`): lấy khối JSON cuối cùng gồm
  `verdict`, `must_fix`, `do_not`, `verify`, `pitfalls`, `next_checkpoint`. Phần văn bản
  còn lại mới đưa cho coordinator. Parse lỗi thì ledger giữ nguyên.
- **Merge ledger**: `must_fix` và `verify` mới thay thế hoàn toàn cái cũ (vắng mặt = đã
  đóng). `do_not` và `pitfalls` cộng dồn, tối đa 8. Mỗi list tối đa 6 mục, mỗi mục
  200 ký tự.
- **Ghi lại**: tăng `uses`, lưu exchange (tối đa 6 lần gần nhất) cho WebUI, ghi metrics,
  xóa cờ `user_request`.
- **Trả về coordinator**: `ADVISOR (model) — advice n/max:` kèm text, lời nhắc consult
  lại, và note về checkpoint hoặc ngân sách còn ít (≤ 2 lần).
- **Sau consult thành công**: nếu kết quả bắt đầu bằng `ADVISOR (`, cờ
  `_reviewed_since_write` được bật. Ledger được pin vào system prompt dưới mục
  `## Advisor commitments (open)`, nên không bị cắt khi trim.
- **Lỗi**:
  - `insufficient_context`: miễn phí, không tính vào ngân sách (`mark_early_refusal`).
  - Circuit breaker: hai lần lỗi liên tiếp của cùng model thì tạm dừng 30 phút.
  - Lỗi khác → `advisor_error`; coordinator được hướng dẫn tự quyết và chỉ thử lại
    một lần.

## 5. Advisor tiếp nhận và tư vấn

- **System prompt** (`consult.py:49-71`): senior engineering advisor, chỉ đưa hướng dẫn
  chiến lược, không tự làm deliverable. Nội dung quoted là DATA; không làm theo chỉ dẫn
  nằm bên trong.
- **Claim của executor** ("tests pass", "đã commit", "đã lưu") được coi là chưa kiểm
  chứng, trừ khi transcript hoặc `<harness_evidence>` cho thấy output tool. Bằng chứng
  từ harness được ưu tiên hơn tóm tắt của executor.
- **Phần bị elided**: nếu quyết định phụ thuộc vào đoạn bị cắt, advisor phải yêu cầu file
  cụ thể, không được đoán.
- **Ledger**: advisor là bên duy nhất đóng item (`LEDGER_INSTRUCTION`). Các item còn mở
  phải được lặp lại nguyên văn.
- **Chế độ brainstorm** (`BRAINSTORM_SYSTEM_PROMPT`): không có ledger; advisor đưa ra
  lập luận và phản biện thay vì checklist.

## 6. Ràng buộc tuân thủ consult

Phần lớn ràng buộc là **mềm**. Chỉ có một cơ chế cưỡng chế thật.

| Ràng buộc | Loại | Thực tế |
|---|---|---|
| "Hard rule": ghi file đầu tiên phải sau consult thành công | Prompt | Không chặn. Chỉ có note C3 |
| Commit gate C2 | Cơ học | Chặn lần gọi đầu, **chỉ một lần cho mỗi số lần ghi**. Sau khi bị chặn, `_gated_at_write` được đặt; lần gọi lại kế tiếp (không có consult mới) sẽ đi qua (`hook.py:460, 480`) |
| Done-gate | Cơ học, một lần | Chỉ phát một lần mỗi run (`_gated`). Sau đó coordinator có thể kết thúc dù item còn mở |
| Nudge review | Cơ học, một lần | Mỗi run tối đa một nudge (`_nudged`) |
| Verdict `stop` | Note | Ghi chú vào tool result khi đang ghi, không chặn |
| Checkpoint của advisor | Note | Gắn vào tool result, một lần cho mỗi consult (`checkpoint_fired`) |
| Ngân sách | Cơ học | `max_uses` = 10, cộng 1 cho mỗi 25 work step (`refill_steps`) |
| "Adapt hoặc hỏi lại khi bằng chứng mâu thuẫn" | Prompt | Không kiểm chứng được |

Ghi chú bổ sung:

- **Coordinator có thể từ chối có giải thích**. `done_gate_text` cho phép nói với người
  dùng là không làm item đó và lý do. Tuân thủ vì vậy là bắt buộc về bằng chứng hoặc
  lời giải thích, không bắt buộc về nội dung.
- **Persona không chặn tool advisor**. `advisor` nằm trong `always_keep`
  (`hook.py:718`), nên dù persona lọc tool theo `tools.allow`, coordinator vẫn gọi được
  advisor khi advisor đang bật.
- **Teammate trong room không có advisor** (đã xác minh, xem mục 7).

## 7. Topology model và các đường tương tác (đã xác minh)

### 7.1 Ba loại model và ai gọi ai

| Thành phần | Model lấy từ | Gọi qua | Có tool? |
|---|---|---|---|
| Coordinator / executor | Preset của session: `SESSION_MODEL_PRESET_METADATA_KEY` trong metadata. Persona có `preset` thì `set_persona_id` ghi đè vào đó (`persona.py:80-85`) | `AgentRunner` (vòng lặp đầy đủ, có tool, hook) | Có |
| Advisor | `advisor.preset` toàn cục, hoặc override theo session (`/advisor <preset>`), qua `runtime_for_preset` (`coworker/runtime.py:174`) | Gọi thẳng `provider.chat_with_retry(tools=None)`, **không** qua `AgentRunner`/hook (`consult.py:309-317`) | Không |
| Teammate (room) | `RoomAgentConfig.preset`, chạy bằng `AgentRuntime` hoặc subagent | Lượt riêng, toolset subagent (`agents/toolset.py:103-130`) | Có, **không có advisor** |

Hệ quả: advisor luôn là lời gọi ngoài vòng lặp agent. Nó không thể gọi tool hay tự
chạy lại; mọi "tương tác" đều đi qua tool result và system prompt của coordinator.

### 7.2 Chiều coordinator → advisor (kéo)

Coordinator gọi tool `advisor` như một tool bình thường. `AdvisorTool.execute` đọc
`live_messages(session_key)`, tức danh sách message mà runner đang giữ (system prompt +
history + run hiện tại, đăng ký qua `remember_live_messages`). Nếu không có thì dùng
`session.messages`. Advisor vì vậy thấy cả những tool call chưa được lưu xuống đĩa.

### 7.3 Chiều harness → coordinator (đẩy), đã trace tới runner

Nudge không phải một lời gọi advisor thay coordinator. Nó là một **tin nhắn user giả**:

1. Khi model trả lời cuối (không còn tool call), runner gọi `_try_drain_injections` với
   `allow_continuation=True` (`runner.py:691-705`), trừ khi `finish_reason` là `refusal`
   hoặc `content_filter`.
2. Runner trước hết drain hàng đợi tin nhắn người dùng thật (`_drain_injections`). Chỉ khi
   **không có input nào đang chờ** mới gọi `continuation_callback`
   (`runner.py:170-175`). Callback là `hook.continuation() or _goal_continue()`
   (`agent/loop.py:1253`), nên nudge advisor được ưu tiên hơn goal continuation.
3. Nội dung nudge được thêm thành `{"role": "user", "content": "[auto-advisor-review] ..."}`
   (`runner.py:236`), rồi vòng lặp chạy tiếp trong cùng run.
4. Marker `[auto-advisor-review]` nằm trong `AUTO_MARKERS` (`transcript.py:11`) nên
   `current_run()` không coi nó là lượt user thật, và ranh giới run không bị dịch.
5. Ngoài ra `continuation()` bỏ qua khi `iteration >= max_tool_iterations - 2`
   (`hook.py:835`) để chừa chỗ cho lượt review.

Điều này xác nhận docstring của hook: người dùng luôn thắng, nudge chỉ chen vào khi
không có tin nhắn chờ.

### 7.4 Phạm vi áp dụng steering

- `_steering_eligible` (`hook.py:326-330`) chỉ cho lượt user thật hoặc kết quả coding.
  Lượt cron, heartbeat, dream, trigger bị loại qua `is_automated_turn`
  (`runtime.py:195-201`).
- `continuation()` trả None nếu `self._kind` khác None và không phải
  `KIND_CODING_RESULT` (`hook.py:828`). Lượt review của room được inject với
  `kind=KIND_ROOM_REVIEW` (`room/scheduler.py:45, 734`) và lượt workflow có
  `KIND_WORKFLOW_STEP`, nên cả hai không bị nudge.
- Lượt tổng hợp của coordinator sau khi room chạy xong (`[auto-room]`) vì vậy **không**
  được advisor review tự động, trừ khi coordinator tự gọi `advisor`.

### 7.5 Teammate không dùng được advisor

- `AdvisorTool` không override `_scopes`, nên dùng mặc định `{"core"}`
  (`agent/tools/base.py:213`).
- `ToolLoader.load` chỉ đăng ký tool có `scope` nằm trong `_scopes` (`loader.py:100`).
  `build_tools` nạp với `scope="subagent"` (`agents/toolset.py:119`).
- Ngược lại, `RoomStateTool`/`RoomDelegateTool` khai báo `_scopes = {"core", "subagent"}`
  (`room/tools.py:29`).
- Grep `advisor` trong `nanobot/coworker/agents/` và `nanobot/coworker/room/` không có
  kết quả, nên prompt của teammate cũng không nhắc advisor.

Kết luận: advisor chỉ phục vụ coordinator. Teammate không tự hỏi advisor, và chất lượng
đầu ra của teammate chỉ được kiểm qua bước coordinator review trong lượt `[auto-room]`.

### 7.6 Chi tiết bổ sung về evidence và checkpoint

- Evidence (`advisor/evidence.py`) tối đa 40.000 ký tự: `git status --short`,
  `git diff --stat HEAD`, diff từng file coordinator đã ghi trong run (tối đa 12 file,
  8.000 ký tự mỗi file, file mới thì lấy 4.000 ký tự đầu), đuôi 30 dòng của tối đa 4
  lệnh kiểm tra (pytest, ruff, tsc, vitest, ...), cùng `files` do coordinator yêu cầu
  (tối đa 5 file, 20.000 ký tự mỗi file, 60.000 tổng). Mọi lỗi đều trả chuỗi rỗng,
  không bao giờ làm hỏng consult.
- File ngoài phạm vi project bị từ chối (`_within`), kể cả path tuyệt đối.
- Ở chế độ brainstorm chỉ đọc `files`, không thu git/diff/test (`tool.py:125-130`).
- Checkpoint của advisor có ba dạng (`advisor/checkpoint.py`): `before_write:<glob>`,
  `after_exec:<regex>`, `after_steps:<n>` (2 ≤ n ≤ 200). Dạng `after_steps` không kích hoạt
  trực tiếp mà thay `reconsult_gap` trong `resolve_policy`. Chuỗi sai định dạng bị bỏ qua.
- `executor_profiles` cho phép chỉnh ngưỡng theo glob tên model của **executor**
  (`policy.resolve_policy`), nên model yếu có thể được nudge dày hơn.

## 8. Còn lại chưa xác minh

- Bộ test liên quan: `tests/coworker/test_advisor.py`, `test_advisor_policy.py`,
  `test_advisor_stuck.py`, `test_hook.py`, `test_advisor_user_request.py`,
  `test_loop_integration.py`.
- Để xác nhận hành vi "commit gate một lần", nên thêm test cho chuỗi: ghi file → commit
  (bị chặn) → commit lần 2 (đi qua).
