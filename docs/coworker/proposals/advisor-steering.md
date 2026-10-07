# Đề xuất: Advisor dẫn hướng coordinator — bắt lệch sớm, giữ đúng hướng

- Status: **draft, chưa triển khai**. Viết 2026-10-07. Branch: `develop`.
- Phạm vi: `nanobot/coworker/advisor/*`, `nanobot/coworker/hook.py`, `nanobot/coworker/directives.py`,
  một điểm mở rộng nhỏ ở `nanobot/agent/hook.py` + `runner.py` (chỉ cho C2).
- Liên quan: `docs/coworker/plans/advisor-interaction.md` (nudge trong run, discussion gate, stuck — đã làm).

## 1. Vấn đề

Hai kiểu hỏng mà người dùng gặp:

1. **Đi sai từ đầu** — coordinator ghi/commit trước khi advisor thấy hướng đi → advisor bắt làm lại.
2. **Trôi dần** — advisor đã chỉ hướng đúng, nhưng sau vài chục tool call coordinator quên/lệch, lặp lại
   đúng lỗi đã được nhắc, hoặc báo cáo "xong" trong khi checklist của advisor còn mở.

## 2. Bằng chứng (phiên `websocket:f68722dc…`, 2026-10-07, executor `gemini-3.8-flash-tiered`, advisor `claude-opus-5-5`)

| # | Quan sát | Nguồn | Nguyên nhân trong code |
|---|----------|-------|------------------------|
| E1 | Advisor nhiều lần nói không nhìn thấy nội dung: "I can't see the saved plan body because it was elided" (advice 6/10); "the Phase 0.5 body … were elided" (9/10); "partly elided" (Phase 0, 2/10); "You only saw the head and tail of each spec" (1/10) | log `advisor consult`, transcript webui | `consult.py`: `TOOL_ARGS_MAX_CHARS=600` cắt nội dung `write_file`/`apply_patch`; `TOOL_RESULT_MAX_CHARS=4000` cắt kết quả `read_file`. Advisor review một bản ghi mà **không thấy bản ghi** |
| E2 | Commit doc lúc ~13:08 **trước** khi consult; advisor (8/10, 13:09) phát hiện doc "still internally inconsistent" → thêm 1 vòng sửa + commit follow-up | log 13:07–13:09 | "Hard rule" pre-write chỉ là prompt (`directives.ADVISOR`); không có gì chặn `git commit` |
| E3 | Run Phase 0.5: 137 tool call giữa consult 9/10 (13:33) và 10/10 (13:51); kết quả 10/10: "Not ready to commit … WebUI will break at runtime. This is the biggest miss" | transcript | Nudge chỉ chạy qua `continuation()` — tức **khi model định kết thúc run** — và latch 1 lần/run (`self._nudged`). Không có checkpoint giữa run |
| E4 | Cùng một lỗi lặp lại sau khi advisor đã chỉ ra: grep `working_dir` = file → WinError 267 (advice 2/10, rồi "same error as before" ở 4/10) | transcript | `StuckTracker` chỉ sống trong 1 run và reset khi gọi advisor; bài học không được giữ |
| E5 | Báo cáo "Phase 0.5 đã hoàn thành trọn vẹn… spike committed" trong khi `mermaid-streamdown-note.md` vẫn untracked (advisor Phase 0, 2/10 chỉ ra) | transcript + `git status` | Không có đối chiếu giữa checklist của advisor và câu trả lời cuối |
| E6 | `focus` thường là câu dẫn dắt kèm tự khẳng định: "tests passing. Review before commit", "Is everything sound?" | log `Tool call: advisor` | Advisor buộc phải tin lời executor về những gì nó không thấy (xem E1) |
| E7 | Advice dạng văn xuôi dài, nhiều mục must-fix; executor làm một phần rồi kết thúc | transcript | Không có cấu trúc (verdict / must_fix / do_not); advice nằm trong tool result → bị trim history theo `max_turns` ở các turn sau |

Kết luận: advisor **đúng** gần như mọi lần — vấn đề nằm ở (a) advisor thiếu dữ liệu thật về thứ đã ghi,
(b) không có cơ chế buộc/giữ executor theo lời khuyên, (c) checkpoint đến quá muộn.

## 3. Đề xuất

Ưu tiên theo lợi ích / chi phí. Nhóm A–B–C1 không cần sửa upstream.

### A. Advisor nhìn đúng dữ liệu (input quality)

**A1. Evidence pack tự động** (`consult.py` — M). Khi consult ở mode coding, harness tự gắn thêm khối
`<harness_evidence>` (không do executor viết):
- `git status --short` và `git diff --stat` của project scope (nếu là git repo);
- diff thật của các file executor đã ghi trong run hiện tại (lấy từ tool call `write_file`/`edit_file`/
  `apply_patch`), cap ~40k ký tự, ưu tiên file mới nhất;
- N lệnh `exec` gần nhất dạng test/lint/build (`pytest|ruff|tsc|vitest|bun run|basedpyright`) kèm exit code
  và 30 dòng cuối output.
Giữ nguyên elision cho transcript; evidence pack thay thế phần bị cắt quan trọng nhất. → sửa E1, E6.

**A2. `files` trong advisor tool** (`tool.py` — S). Thêm tham số tùy chọn `files: string[]` (≤5 đường dẫn,
qua `resolve_allowed_path`/`WorkspaceScope`, cap 60k tổng): harness đọc nội dung **hiện tại** từ đĩa và gắn
nguyên văn. Dùng khi nhờ review plan/spec vừa viết. → sửa "I can't see the saved plan body".

**A3. Advisor không tin lời tự khai** (`ADVISOR_SYSTEM_PROMPT` — S). Thêm: "Treat executor claims (tests pass,
committed, done) as unverified unless the transcript or harness evidence shows the tool output. Say which
claims you could not verify." Directive phía executor: `focus` theo khuôn
`goal · current plan · what changed · what I'm unsure about` thay vì "is everything sound?". → E6.

### B. Giữ đúng hướng sau khi đã có lời khuyên (adherence)

**B1. Advice ledger có cấu trúc** (`consult.py`, `state.py`, `hook.py` — M). Advisor kết thúc câu trả lời bằng
một khối JSON (parse lỏng, lỗi parse → bỏ qua, không fail consult):

```json
{"verdict": "proceed|revise|stop",
 "must_fix": ["..."], "do_not": ["..."], "verify": ["..."], "pitfalls": ["..."],
 "next_checkpoint": "consult again before editing WebUI settings / after the test suite runs"}
```

Harness lưu vào `session_state["advisor"]["ledger"]` (id ổn định cho từng mục), và:
- ghim một section ngắn **"Advisor commitments (open)"** vào system prompt qua `_append_system` — tồn tại qua
  trim/compaction (khác với tool result). Chỉ thay đổi khi ledger đổi → ảnh hưởng cache có giới hạn;
- consult kế tiếp gửi kèm ledger để advisor đóng/mở lại từng mục (advisor là bên duy nhất đóng mục, không phải
  executor tự tick) → không có tool mới cho executor;
- `pitfalls` (vd. "rg: working_dir phải là thư mục") giữ suốt phiên → sửa E4.
→ sửa E4, E5, E7.

**B2. Done-gate theo ledger** (`policy.py`, `hook.continuation` — S). Khi executor định kết thúc run mà ledger
còn `must_fix`/`verify` mở → continuation: liệt kê mục còn mở, yêu cầu làm hoặc nói rõ lý do bỏ qua với người
dùng. Ưu tiên hơn nudge "reconsult" thông thường. → E5.

**B3. Verdict `revise`/`stop` có hệ quả** (S). Sau verdict `stop`, note vào tool result kế tiếp của bất kỳ write
nào: "advisor said stop: <lý do> — resolve or consult again". Mềm (chỉ nhắc), không chặn.

**B4. Advisor tự hẹn checkpoint kế tiếp** (`policy.py`, `hook.py` — S). Trường `next_checkpoint` trong ledger
là điều kiện advisor muốn được hỏi lại. Harness hỗ trợ ba dạng, parse lỏng, không khớp thì chỉ ghim nguyên văn:
- `before_write:<glob>` — ghi vào path khớp (vd. `webui/src/**`) → note C1 trên tool result của lần ghi đó;
- `after_exec:<regex>` — sau lệnh khớp (vd. `pytest|vitest`) → note trên kết quả lệnh;
- `after_steps:<n>` — ghi đè `reconsult_gap` cho tới consult kế tiếp.
Advisor là bên hiểu rủi ro của bước tiếp theo nhất, nên đây là tín hiệu "khi nào consult" rẻ và đúng chỗ hơn một
bộ phân loại bên ngoài (xem §7).

### C. Bắt lệch sớm (timing)

**C1. Checkpoint giữa run** (`hook.py` — S, không cần upstream). Ngoài nudge cuối run: khi `scan_run().gap`
vượt `reconsult_gap` **trong lúc run vẫn đang chạy**, chèn note vào tool result kế tiếp (cùng kỹ thuật
`_annotate_stuck`, byte-ổn định theo `tool_call_id`): "N work steps since last consult — call advisor now".
Thêm ngưỡng theo **số file khác nhau đã ghi** (vd. ≥5) vì drift thường đi theo bề rộng thay đổi. → E3.

**C2. Gate cứng trước hành động khó đảo ngược** (upstream nhỏ + `hook.py` — M). Mở rộng
`AgentHook.before_execute_tool` để có thể trả về một `ToolResult` thay thế (short-circuit), runner dùng nó thay
vì chạy tool. Coworker hook chặn **một lần** khi:
- `exec` khớp `git commit|git push|git reset --hard|rm -rf` (hoặc tool `git_commit`), và
- chưa có consult thành công **sau lần ghi file cuối cùng** trong run,
trả về `{"status":"advisor_review_required", ...}` hướng dẫn gọi advisor (kèm A1 evidence). Lần gọi lại sau
consult (hoặc khi hết budget/advisor lỗi/breaker mở) → cho qua. Cờ `advisor.commit_gate` (mặc định bật khi
advisor bật). → E2.

**C3. Plan-before-write rẻ** (S). Directive đã yêu cầu ORIENT → CONSULT → PLAN → EXECUTE. Đo thay vì tin:
nếu write đầu tiên của run xảy ra khi chưa có consult thành công → C1 note ngay trên write đó (không chặn).
Kết hợp ledger: verdict của consult đầu là "kế hoạch đã duyệt".

### D. Ngân sách & chính sách theo model

**D1. Ngân sách hồi theo việc** (`state.py` — S). 10 consult/phiên cạn trong ~6 giờ (log 2026-10-07: 10/10 lúc
13:51). Thay bằng: `max_uses` theo **lượt người dùng** + trần phiên, hoặc +1 consult mỗi `reconsult_gap` work
steps. Cảnh báo trong tool result khi còn ≤2.

**D2. Chính sách theo executor model** (`config.py` — S). Map `executor_profiles: {"<model glob>": {reconsult_gap,
commit_gate, first_consult_gap}}`. Executor yếu (flash-tier) → `reconsult_gap` 6, gate bật; executor mạnh → nới.
Executor trong log đổi giữa grok-4.6 và gemini flash cùng một phiên — profile phải tra theo model của **run**.

## 4. Thứ tự triển khai

| Phase | Hạng mục | Upstream? | Ước lượng |
|-------|----------|-----------|-----------|
| 0 | Đo token theo tool (§5) | Không | 0.5 ngày |
| 1 | A1 evidence pack, A2 `files`, A3 prompt | Không | 1–1.5 ngày |
| 2 | B1 ledger + section ghim, B2 done-gate, B4 `next_checkpoint` | Không | 2–2.5 ngày |
| 3 | C1 checkpoint giữa run, C3 | Không | 0.5 ngày |
| 4 | C2 commit gate (hook short-circuit) | Có (nhỏ, cộng thêm) | 1 ngày |
| 5 | D1, D2 | Không | 0.5–1 ngày |

Mỗi phase có cờ tắt riêng trong `coworker.json` → rollback không cần revert.

## 5. Đo lường

Ghi vào `coworker_metrics.sqlite3` mỗi consult: `verdict`, số `must_fix`, số mục ledger còn mở khi run kết thúc,
`work_steps_since_last_consult`, có/không evidence pack. Chỉ số chính:
- **Tỷ lệ làm lại**: % consult có verdict `revise|stop` xảy ra *sau* khi đã ghi file (mục tiêu: giảm);
- **Mục mở lúc kết thúc**: số `must_fix` chưa đóng khi executor trả lời cuối (mục tiêu: ~0);
- **Lỗi lặp sau khi được nhắc**: cùng failure signature xuất hiện sau khi đã có trong `pitfalls`;
- **"elided" trong advice**: số advice chứa "elided|can't see" (proxy cho E1; mục tiêu: ~0).
- **Checkpoint của advisor có được tôn trọng**: % `next_checkpoint` được kích hoạt và executor consult ngay sau đó.

**Đo token theo tool** (Phase 0, làm trước mọi thứ). Mỗi iteration ghi thêm vào `coworker_metrics.sqlite3`:
tên tool, số ký tự/ước lượng token của tool result đưa vào context, và cờ elided. Số liệu tham chiếu từ log
2026-10-06…07: `read_file` 1315, `rg` 1087, `exec` 708 lần so với tổng ghi (`apply_patch` 320, `edit_file` 150,
`write_file` 46) — đọc/tìm gấp ~5 lần ghi, nhưng chưa biết phần token thực tế. Số liệu này quyết định có làm
§7.1 hay không.

Kịch bản eval: tái hiện Phase 0.5 (gỡ field config + WebUI dùng field đó) với executor flash — đạt nếu advisor
bắt được lỗi WebUI **trước** commit.

## 6. Rủi ro

- **Chi phí token advisor tăng** (A1/A2): đã ~100–340k ký tự/consult. Evidence pack có cap và thay phần bị elide,
  không cộng dồn vô hạn; theo dõi `promptChars`.
- **Cache prompt executor** (B1): section ghim đổi khi ledger đổi. Chỉ đổi sau consult (vốn đã là điểm gãy
  nhịp), giữ section ngắn (≤1.5k ký tự).
- **Gate gây vòng lặp** (C2): chỉ chặn một lần mỗi "lần ghi cuối"; luôn cho qua khi advisor không khả dụng.
- **JSON ledger không parse được** với advisor model khác: bỏ qua lặng lẽ, hành vi như hiện tại.
- **Executor yếu bỏ qua note** (C1/B3): đó là lý do C2 tồn tại cho hành động khó đảo ngược.

## 7. Đã cân nhắc, chưa làm

**7.1. Engine code search (trigram / graph).**
- Trigram index (kiểu zoekt): **không**. `rg` trên repo cỡ nanobot đã ở mức mili giây. Chi phí nằm ở số vòng LLM
  và token của kết quả, không ở tốc độ tìm.
- Graph/symbol: **có điều kiện**. Log cho thấy cặp lặp lại `rg "def X\("` → `read_file(offset)`. Nếu số liệu
  §5 cho thấy `read_file`/`rg` chiếm phần lớn token, làm tool nhẹ thay vì engine:
  `code_outline(path)` (class/hàm + số dòng), `read_symbol(name)` (đúng thân hàm), `find_refs(name)`; dựng bằng
  Python `ast` cho `.py`, tree-sitter cho TS/TSX, cache theo mtime, không daemon.

**7.2. Decision model ngoài (Cloudflare Clef) quyết định khi nào consult.** Clef/Clef-flash (Cloudflare,
2026-10-01, open source) chấm điểm song song các lựa chọn theo schema — về hình thức hợp với "consult hay
không". Chưa dùng vì:
- các lỗi quan sát được (E1–E3, E5) là advisor thiếu dữ liệu, thiếu cơ chế buộc và checkpoint muộn — không phải
  quyết định thời điểm sai;
- độ trễ (~2,2 s/quyết định trong bài thử của Cloudflare) nếu gọi mỗi bước, so với luật đếm bước ~0 ms và
  tất định;
- thêm phụ thuộc runtime và việc gửi transcript ra ngoài; mô hình mới, chưa có đánh giá cho miền này.
Lộ trình nếu cần: sau khi B4 và §5 có dữ liệu có nhãn (consult nào dẫn tới `revise` sau khi đã ghi), chạy Clef ở
**shadow mode** (chỉ log, không ảnh hưởng hành vi) tại 2–3 điểm: trước write đầu tiên, trước commit, trước câu
trả lời cuối. Chỉ bật thật nếu vượt luật hiện tại trên dữ liệu đó.
