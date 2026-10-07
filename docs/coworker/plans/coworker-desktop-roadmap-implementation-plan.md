# Implementation plan: Coworker Desktop local (Windows)

_Cập nhật: 07/10/2026 · Repo: `cuongpt083/nanobot`, nhánh `develop` · Mục tiêu: Desktop app Windows (Tauri webview → gateway `127.0.0.1`)_

Kế hoạch này gộp bốn đặc tả đã chỉnh cho **local Desktop**, xếp theo giá trị dùng thật và rủi ro. Không thiết kế remote use (VPS, SSH, Tailscale, WebUI điện thoại). Ước lượng 22–40 ngày công tùy phase có điều kiện (ảo hóa, time-to-chrome) và BrowserSkill.

Đặc tả nguồn:

- `docs/coworker/proposals/dac-ta-hermes-3-nang-luc.md` (F1, F2, F3)
- `docs/coworker/proposals/dac-ta-hieu-nang-desktop.md` (P1–P3)
- `docs/coworker/proposals/dac-ta-editor-image-pane.md` (G1–G4)
- `docs/coworker/proposals/dac-ta-browserskill-muc-2.md` (Browser P0–P4)

## Bảng theo dõi

| Phase | Việc | Ước lượng | Trạng thái | Cổng |
| --- | --- | --- | --- | --- |
| 0 | Baseline WebView2 + eval | 1–1,5 ngày | chưa | Có số đo ổn định, 2 lần chạy |
| 1 | F3 brief / envelope | 2–3 ngày | chưa | Token guest −40% vs `full`; envelope hợp lệ ≥ 90% |
| 2 | Mermaid P2a (ELK, pan/zoom, viewport) | 2–3 ngày | chưa | Sequence 15 participant đọc được; Ctrl+cuộn zoom sơ đồ |
| 3 | F2 FTS5 (chưa tóm tắt) | 2–3 ngày | chưa | Recall@5 ≥ 0,8; p95 < 200 ms |
| 4 | F1 draft (CLI `/skills review`) | 2,5–3,5 ngày | chưa | Nháp hợp lệ; không tự active |
| 5 | F2 summarize + UI duyệt skill | 2–3 ngày | chưa | Tóm tắt cache; duyệt nháp trên WebUI/Desktop |
| 6 | P2b ảo hóa / P3 time-to-chrome | 0–3 ngày | có điều kiện | Chỉ khi baseline còn jank / chờ lâu |
| 7 | Editor G1 (đọc/sửa/lưu + preview) | 3–4 ngày | chưa | Mở 1 MB < 1 s; không qua Tauri `invoke` |
| 8 | Editor G2 (staged / diff / hunk) | 3–4 ngày | chưa | Agent ghi đều qua bước duyệt |
| 9 | Image G3 (Konva + skill) | 4–5 ngày | chưa | Sửa nhiều vùng một lần gửi |
| 10 | BrowserSkill P0–P4 | 8–12 ngày | cuối | 0 session treo trước khi bật `interact` |

Đánh dấu `- [x]` trong từng phase khi xong và đã qua cổng. Không sang phase sau nếu cổng fail, trừ khi có quyết định dừng/bỏ rõ ràng.

## Lệch thứ tự so với Hermes

Đặc tả Hermes ghi F1 → F2 → F3. Plan này làm **F3 → F2 → F1 (nháp) → F2 tóm tắt + UI F1**.

Lý do, không phải quên spec:

1. F3 độc lập với F1/F2; phần lớn hạ tầng đã có (`_task_message`, `GUEST_OUTPUT_SCHEMA`, repair 1 lần, `_summon_coordinator` đã ưu tiên contract).
2. F3 cắt token ngay trên room đang dùng hàng ngày.
3. F1 tốt hơn khi có F2 (dò tác vụ tương tự); F1 `mode: auto` vẫn **không** làm.
4. Mermaid chèn giữa F3 và F2 vì đây là nỗi đau UI hiện hữu, lát riêng, rủi ro thấp.

## Vấn đề cần giải quyết

| # | Vấn đề hiện tại | Vị trí trong code | Phase |
| --- | --- | --- | --- |
| D0 | Chưa có số đo WebView2; không biết jank thật hay cảm giác | Desktop + `ThreadMessages` | 0 |
| D1 | Guest nhận "Recent user turns" + "Room so far" tới 24.000 ký tự | `scheduler._task_message` section 4–5 | 1 |
| D2 | Chat room vẫn đăng nguyên `guest.text`; coordinator đã đọc contract nhưng user/transcript vẫn đầy | `scheduler._handle_finished` `transcript.append` + `note(...)` | 1 |
| D3 | Envelope thiếu `status`, `key_points`, `transcript_ref`; schema cũ `summary` ≤ 1200 | `agents/contract.py` | 1 |
| D4 | Không có transcript delegation đầy đủ; `AgentThreadStore` cắt 4000 ký tự và chỉ lưu summary | `agents/thread.py` | 1 |
| D5 | `spawn` core trả nguyên `final_content` | `agent/subagent.py` `_announce_result` | 1 (lát 2, tùy chọn) |
| D6 | Mermaid chữ nhỏ, không pan/zoom riêng, chưa ELK. `MarkdownTextRenderer` không override mermaid — Streamdown tự render (chunk lazy `mermaid-*.js`). Chưa xác nhận option ELK / complete-block | Streamdown trong `MarkdownTextRenderer` | 2 |
| D7 | `search_sessions` vẫn substring + `_SEARCH_LIMIT=5` + excerpt 360 ký tự; **đã** xếp title trước message và không cắt scan ẩn (test `test_sessions.py`). Thiếu: BM25, độ mới, FTS5, tóm tắt | `WebuiSessionAccess.search`, `agent/tools/sessions.py` | 3 |
| D8 | Không tự tạo skill sau tác vụ phức tạp | `coworker/hook.py` `after_run` | 4 |
| D9 | Không có UI duyệt skill nháp | WebUI settings coworker | 5 |
| D10 | Không có chỗ sửa/duyệt file agent trong app | `file_preview.py` chỉ đọc, cap 384 KB, không `version` | 7–8 |
| D11 | Sửa ảnh bằng lời, không khoanh vùng | Image pane chưa có | 9 |
| D12 | Browser Mức 1 (nếu dùng) dễ treo session | Chưa có `nanobot/coworker/browser/` | 10 |

## Mục tiêu đo được

1. Sau khi eval cổng đạt: room guest `brief+user` (tối đa 2 user turn); coordinator và chat chỉ thấy envelope ≤ 1.500 ký tự. **Trước cổng, default config vẫn `full`** để không đổi hành vi đang dùng.
2. Sequence 15 participant đọc được chữ ở 100% zoom trang; Ctrl+cuộn zoom sơ đồ, cuộn thường cuộn trang.
3. `search_sessions` xếp hạng BM25+độ mới; p95 không tóm tắt < 200 ms trên ~10.000 tin.
4. Sau tác vụ ≥ 5 tool call thành công, có skill nháp để duyệt; không tự kích hoạt.
5. Mở/sửa/lưu file workspace từ Desktop; file/ảnh/stream không đi qua Tauri `invoke`.
6. (Sau G3) Một lần gửi sửa được nhiều vùng ảnh; ngoài vùng khoanh giữ nguyên khi bật ghép.
7. (Sau Browser P1) 0 session treo trên nhóm tiêm lỗi trước khi bật `interact`.

## Ngoài phạm vi

- Remote gateway, tunnel, Tailscale, mở WebUI ra mạng.
- F1 `mode: auto` (Phase 4 Hermes; chỉ xét sau 4 tuần duyệt nháp ≥ 60%).
- IM-17 (pane ảnh cho screenshot UI / BrowserSkill).
- Monaco-as-IDE: LSP, debugger, terminal, marketplace.
- LLM tự tính tọa độ / mask / ghép ảnh.
- Browser `interact` trước khi P1 đạt 0 session treo.
- Gỡ toàn bộ Pi coding subsystem. Hermes F3 ghi "Pi sẽ bị gỡ" — chỉ gỡ Pi khỏi Room guest backend (Lựa chọn A) để F3 bao phủ 100% delegation; hệ thống `/code` độc lập vẫn được giữ.
- Docker runtime cho BrowserSkill hoặc Desktop coworker (giữ kiến trúc local Windows thuần).
- Viết lại WebUI; tối ưu macOS/Linux trước Windows.

## Nguyên tắc

1. **Local loopback.** Webview ↔ gateway: HTTP + WebSocket `127.0.0.1`. Rust chỉ cửa sổ, tray, sidecar, `open_log_file` / `retry_gateway` / `open_external_url`.
2. **Merge-safe.** Logic mới trong `nanobot/coworker/` (`delegate/`, `recall/`, `learning/`, `browser/`) và `webui/`. Core chỉ nhận seam đã liệt kê.
3. **Tắt được, mặc định an toàn.** Mỗi khối có `enabled` trong `CoworkerConfig`. F1 mặc định `mode: draft`.
4. **Cưỡng chế bằng code.** Staged write, domain deny, session cleanup, IPC guardrail — không chỉ dặn prompt.
5. **Đo rồi mới tối ưu.** Không ảo hóa danh sách tin, không time-to-chrome đầy đủ, không chỉnh stream rAF trừ khi Phase 0 chứng minh jank.
6. **Nội dung lịch sử là dữ liệu.** Giữ `_UNTRUSTED_NOTICE` cho session cũ, skill nháp, envelope, nội dung trang browser.

## Câu hỏi mở (đã giải quyết & còn lại)

Các câu hỏi kiến trúc cốt lõi đã được giải quyết:

| # | Câu hỏi | Quyết định | Trạng thái |
| --- | --- | --- | --- |
| Q1 | Guest `backend: pi` có áp dụng brief/envelope F3? | **Lựa chọn A (Hẹp):** Gỡ backend Pi khỏi cơ chế Room guest (`room/scheduler.py`, bỏ `backend: "pi"` trên room agent). Mọi guest room đều chạy qua `AgentRuntime`, giúp F3 áp dụng 100%. Phân hệ `coding_agent` / lệnh `/code` độc lập vẫn giữ nguyên. | Đã chốt |
| Q2 | Staged write cho mọi file, hay chỉ file đang mở + ngoài thư mục nháp? | File nằm ngoài thư mục nháp (ví dụ `.coworker/drafts/`) **hoặc** file đang mở trong editor tab: **Bắt buộc staged write qua duyệt/diff**. Chỉ ghi trực tiếp nếu file nằm trong thư mục nháp **và** không có tab nào đang mở. Webview đồng bộ open tabs về gateway. | Đã chốt |
| Q3 | Lưu phiên bản ảnh trong workspace hay kho riêng? | Kho riêng tại OS temporary directory (`tempfile.gettempdir()/nanobot-image-versions/<session>/`), ngoài workspace. Vòng đời tạm thời (ephemeral), dọn theo session kết thúc/reboot/TTL, không lưu vĩnh viễn. Gateway cấp route đọc ảnh tạm có kiểm soát phạm vi an toàn. | Đã chốt |
| Q4 | Khôi phục hàng Docker Linux cho BrowserSkill? | **Không.** Bỏ hoàn toàn Docker. BrowserSkill chỉ chạy local trên Windows Desktop (headless/Chrome local). | Đã chốt |
| Q5 | `editor_context` bật mặc định? | Tắt mặc định, user opt-in. | Đề xuất |
| Q6 | Provider ảnh đầu tiên có nhận mask không? | Chốt trước khi viết Phase 9 `image_edit`. | Mở (Phase 9) |

## Not-to-do (PR vi phạm thì không merge)

| Không làm | Lý do |
| --- | --- |
| Đưa nội dung file, ảnh, stream chat qua Tauri `invoke` | IPC WebView2 chậm payload lớn |
| Mở port gateway / file API ra ngoài loopback | Lộ workspace |
| F1 `mode: auto` | Chưa đủ tín hiệu duyệt |
| Docker runtime / container cho BrowserSkill | Giữ kiến trúc local-only, nhẹ máy |
| Browser `interact` khi P1 chưa đạt 0 session treo | Tab mượn / session treo |
| LLM tính tọa độ, sinh mask, ghép ảnh | Hình học phải qua tool |
| Model ảnh vẽ chữ tiếng Việt | Dùng `render_text` |
| Thêm LSP / debugger / terminal vào editor pane | Không cạnh tranh VS Code |
| Sửa core ngoài seam đã thống nhất | Mất rebase upstream |
| Bắt cuộn chuột thường để zoom Mermaid | Không cuộn được chat |
| Coi webview là nguồn sự thật của file | Workspace gateway mới là SoT |
| Lưu vĩnh viễn các version ảnh vào workspace người dùng | Rác workspace; dùng OS tempdir với cơ chế dọn dẹp |

## Kiến trúc đích (tóm tắt)

```text
nanobot/coworker/
  delegate/           # F3: brief validate, envelope, read_delegation, transcript artifact
  recall/             # F2: FTS5 index, worker, summary cache
  learning/           # F1: queue, reflect, draft store, review commands
  browser/            # Phase 10: runner, registry, tools, help, hook
  agents/contract.py  # mở rộng schema
  room/scheduler.py   # context_policy; đăng envelope thay vì full text
  config.py           # learning, recall, room.context_policy, browser
webui/
  components/mermaid/ # wrapper ELK + panzoom + viewport (dùng chung chat + editor)
  components/editor/  # G1–G2 Monaco, lazy
  components/image/   # G3 Konva, lazy
desktop/              # không thêm invoke nội dung; P3 chỉ splash/skeleton nếu Phase 0 yêu cầu
```

Seam core (tối thiểu):

| Seam | File | Phase | Quy mô |
| --- | --- | --- | --- |
| `on_session_saved` / `on_session_deleted` | `session/manager.py` | 3 | ~15 dòng; nếu không muốn đụng core thì chỉ reconcile định kỳ |
| `SkillsLoader` bỏ `_drafts` / retired / persona khác | `agent/skills.py` | 4 | ~15 dòng |
| `SubagentManager.result_formatter` | `agent/subagent.py` | 1 lát 2 | ~20 dòng; **không bắt buộc** để đóng cổng F3 room |
| Shim tool coworker | `agent/tools/coworker.py` | 1, 7, 10 | import tool mới |

---

## Phase 0 – Baseline (1–1,5 ngày)

Nhánh: `feat/desktop-roadmap-p0`. Không viết tối ưu.

### 0.1 – Fixture WebView2

- [ ] Tạo session fixture ~300 tin: code block dài, ≥ 3 sơ đồ Mermaid (kể cả sequence 15 participant), markdown bảng.
- [ ] Script seed: sinh JSONL ~300 tin (code + ≥ 3 Mermaid, 1 sequence 15 participant) rồi nạp qua SDK / import session. Không đo tay một phiên ngẫu nhiên.
- [ ] Quy trình đo trên Desktop Windows (không chỉ `bun run dev`): WebView2 remote debugging (CDP, `remote-debugging-port`) **hoặc** `performance.mark` / `performance.measure` trong WebUI ghi ra log. Ghi đủ lệnh vào baseline JSON (`machine`, `commit`, `method`).

### 0.2 – Số đo (ghi `docs/coworker/plans/desktop-perf-baseline.json`)

Mỗi số: trung vị 3 lần, máy và commit.

| Metric | Định nghĩa |
| --- | --- |
| `time_to_splash_ms` | Click icon → splash hiện |
| `time_to_chrome_ms` | Click icon → sidebar + composer tương tác được |
| `time_to_interactive_ms` | Tới tin cuối cùng cuộn/chọn được |
| `scroll_fps_p1` | FPS cuộn phiên 300 tin (DevTools Performance) |
| `stream_fps_p1` | FPS khi stream tin có code + Mermaid |
| `composer_blocked` | Ô nhập có bị block khi stream không (có/không) |

Ngưỡng Phase 6 (chốt sau khi có số; giá trị dưới là **đề xuất**, sửa khi có baseline):

- Làm P2b ảo hóa nếu `scroll_fps_p1` < 45 hoặc cuộn giật nhìn thấy.
- Làm P2c stream nếu `stream_fps_p1` < 45 hoặc `composer_blocked`.
- Làm P3 đầy đủ nếu `time_to_chrome_ms` > 2500.

### 0.3 – Eval coworker

`scripts/coworker_eval.py` **đã có**, 6 kịch bản trong `tests/coworker/eval/scenarios/` (`crm-followup`, `edutech-course`, `nutritech-plan`, `persona-nutri`, `presale-design`, `script-update`). **Chưa có** `persona_delegation`, `recall_queries`, `repeat_tasks`.

- [ ] Chạy 6 kịch bản hiện có 2 lần, lưu `docs/coworker/plans/coworker-eval-baseline.json`.
- [ ] Skeleton YAML cho `recall_queries` (F2) và `repeat_tasks` (F1). **`persona_delegation` viết và chạy baseline `full` ở đầu Phase 1**, trước mọi đổi brief/envelope.
- [ ] Spike Streamdown (không đoán): `webui/src/components/` không có chữ `mermaid`; diagram đi qua chunk Streamdown. Đọc option mermaid của đúng phiên Streamdown đang ghim; thử `mode=streaming` với khối chưa đóng. Ghi `docs/coworker/plans/mermaid-streamdown-note.md` (5–15 dòng + cách override: prop Streamdown vs custom `code`/`pre`).

### Test / tiêu chí xong

- File baseline JSON đã commit (hoặc đính kèm PR) với 3 lần đo.
- Ghi chú Streamdown có bằng chứng (screenshot hoặc log render).
- Không đổi hành vi product.

---

## Phase 1 – F3 brief / envelope (2–3 ngày)

Nhánh: `feat/desktop-roadmap-p1-f3`. **Đây là delta**, không viết runtime mới.

Hiện trạng giữ:

- `_task_message` đã xếp section 0–5 và cắt đuôi khi > 24k.
- `GUEST_OUTPUT_SCHEMA` + repair 1 lần trong `AgentRuntime`.
- `_summon_coordinator` đã ưu tiên `summary` / `artifacts` / `open_questions`.
- Chat **vẫn** `note(full guest.text)` và `transcript.append(full reply)`.

Đã thống nhất gỡ Pi khỏi room guest (`_run_guest` không còn phân nhánh `CodingRunner`). Toàn bộ room guest chạy qua `AgentRuntime`, giúp F3 envelope & brief áp dụng đồng bộ cho mọi delegation. Nhánh `SubagentManager.run_inline` giữ raw text. `/code` và `coding_agent` độc lập vẫn giữ nguyên.

### 1.0 – Eval `persona_delegation` trước khi đổi hành vi (chặn)

`scripts/coworker_eval.py` default output là `agent-runtime-baseline.json`; 6 scenario hiện có **không** đo brief/envelope.

- [ ] Viết `tests/coworker/eval/scenarios/persona_delegation.yaml` (≥ 3 case; đủ 10 khi có thời gian): 2–3 persona, có `deliverable`.
- [ ] Chạy 2 lần với hành vi hiện tại (`context_turns=5` + Room so far). Lưu `docs/coworker/plans/f3-full-baseline.json` (token guest, token coordinator, quality).
- [ ] Chưa merge đổi `_task_message` / schema / `note()` cho tới khi file này có số.

### 1.1 – Config

- [ ] `RoomConfig.context_policy: Literal["brief", "brief+user", "full"] = "full"` — **giữ hành vi cũ** cho tới khi cổng 1 đạt, rồi mới đổi default sang `brief+user`.
- [ ] `RoomConfig.envelope_max_chars: int = 1500`.
- [ ] `RoomAgentConfig.budget` tùy chọn: `max_iterations` đã có; thêm `max_tokens`, `timeout_s` nếu chưa map vào `AgentRuntime`.

### 1.2 – Brief

- [ ] `room_delegate`: `task` = goal (bắt buộc như hiện tại); **`deliverable` bắt buộc**. Thiếu → lỗi tool, không chạy guest.
- [ ] `_task_message`:
  - `brief`: section 0–3 (assignment, coordinator context, shared state, upstream).
  - `brief+user`: thêm tối đa **2** user turn gần nhất (không dùng `context_turns=5`).
  - `full`: hành vi hiện tại (kể cả Room so far).
- [ ] Upstream `after` chỉ nhét envelope (summary + key_points + artifacts), không full text.

### 1.3 – Envelope

- [ ] Mở rộng schema, giữ field cũ:

```json
{
  "status": "done | partial | blocked | failed",
  "summary": "≤ 600 chars",
  "key_points": ["≤ 5 items, ≤ 160 chars"],
  "artifacts": ["..."],
  "open_questions": ["..."],
  "confidence": "high | medium | low",
  "transcript_ref": "delegation/<task_id>"
}
```

- [ ] Runtime tự điền `transcript_ref`, `tools_used`, `usage`, `stop_reason`.
- [ ] Hết `max_iterations` / `max_tokens` → envelope `status: partial`.
- [ ] Contract hỏng sau 1 lần repair → tự sinh envelope `partial` / `confidence: low` từ 600 ký tự đầu, không nhét full text vào chat.

### 1.4 – Transcript đầy đủ (bắt buộc trước `read_delegation`) + chat

`AgentThreadStore.append_turn` cắt `task`/`reply` ở 4000 ký tự và **không** lưu tool transcript. Spec "transcript luôn lưu đủ" **hiện sai**. Cổng tỉ lệ `read_delegation` ≤ 30% không đo được nếu chưa có file đầy đủ.

- [ ] Sau mỗi `AgentRuntime.run` thành công/thất bại: ghi `result.messages` (toàn bộ vòng tool) vào `.coworker/rooms/<room>/artifacts/<agent>/delegation/<task_id>.jsonl` (mỗi dòng một message; không cắt 4000). Markdown tóm tắt cạnh đó là tùy chọn.
- [ ] Không dùng `AgentThreadStore` làm SoT cho `read_delegation`.
- [ ] `transcript.append` và `note(...)` chỉ ghi summary + key_points (+ `transcript_ref`).
- [ ] Tool `read_delegation(task_id, query?)` **chỉ bật khi file jsonl đã có**: tối đa 4000 ký tự/lần; chặn path traversal; guest thread không index F2.
- [ ] Nếu chưa persist được `result.messages` → **hoãn** `read_delegation` và hoãn cổng 30%; vẫn được đóng cổng token/envelope.

### 1.5 – Spawn core (không chặn cổng)

- [ ] Nếu còn thời gian: seam `result_formatter` trên `SubagentManager`. Mặc định giữ hành vi cũ.
- [ ] Cổng Phase 1 **không** phụ thuộc lát này. Room `AgentRuntime` là đường chính.

### Test

- `test_f3_brief_policy.py`: `brief` không chứa "Room so far"; `brief+user` ≤ 2 user turns; thiếu `deliverable` fail.
- `test_f3_envelope.py`: schema mới parse; repair 1 lần; fallback partial.
- `test_f3_chat_projection.py`: `note` không chứa full guest text khi contract ok.
- `test_read_delegation.py`: đọc artifact theo `task_id`; path traversal bị chặn.
- Eval: so `f3-full-baseline.json` với cùng scenario `context_policy: brief+user` (chưa đổi default global).

### Cổng

- Token đầu vào trung vị lượt guest −40% so với baseline `full` ở 1.0.
- Envelope hợp lệ lần đầu ≥ 90% trên eval (hoặc fixture nếu eval LLM chưa sẵn).
- Có file jsonl transcript từng delegation; `read_delegation` đọc được. Tỉ lệ gọi ≤ 30% chỉ đo khi tool đã bật — theo dõi, không fail cứng lần đầu.
- Quality không giảm so với `f3-full-baseline.json` và 6 kịch bản hiện có.
- Default `context_policy` chỉ lật `brief+user` sau khi cổng token/quality đạt.

---

## Phase 2 – Mermaid P2a (2–3 ngày)

Nhánh: `feat/desktop-roadmap-p2-mermaid`. Dùng chung chat và preview editor sau này.

Phụ thuộc `mermaid-streamdown-note.md` ở 0.3. **Không** giả định ELK/complete-block là đổi config Streamdown.

### 2.0 – Spike (nửa ngày, làm trước wrapper)

- [ ] Xác nhận: Streamdown có prop mermaid (layout ELK, `useMaxWidth`) hay phải override component `code`/`pre` khi `language=mermaid`.
- [ ] Ghim phiên `mermaid` (và plugin ELK nếu tách) trong `webui/package.json`; ghi phiên vào note.
- [ ] Nếu Streamdown không cho đủ option → custom `MermaidPane`, không fork package.

### 2.1 – Wrapper

- [ ] Component `MermaidPane` (lazy): Mermaid + ELK mặc định cho flowchart và loại hỗ trợ; diagram tự khai báo layout thì giữ.
- [ ] Tắt `useMaxWidth` cho sequence/flowchart; sequence: `wrap: true`, `mirrorActors: false`.
- [ ] `@panzoom/panzoom`: **Ctrl+cuộn / pinch** zoom; kéo pan; nhấp đúp reset. Cuộn thường = cuộn trang. Không bind wheel thường.
- [ ] Thanh công cụ: zoom ±, fit width/height, fullscreen overlay, tải SVG/PNG, copy source.
- [ ] Lỗi cú pháp: báo kèm dòng, giữ bản render hợp lệ gần nhất.
- [ ] Intersection Observer: không layout khi ra ngoài viewport.
- [ ] Debounce; chỉ `mermaid.render` khi khối hoàn chỉnh (nếu 0.3 xác nhận Streamdown đang parse dở).

### 2.2 – Gắn vào chat

- [ ] `MarkdownTextRenderer` / Streamdown: override mermaid → `MermaidPane`. Không fork Streamdown.
- [ ] Theme dark/light theo app.
- [ ] Lazy: không kéo Mermaid/ELK vào bundle lần mở app đầu (đã có manual chunk mermaid trong vite — kiểm tra còn đúng).

### Test

- Unit: config mermaid (ELK, useMaxWidth off).
- Component: Ctrl+wheel không scroll parent; wheel thường scroll parent.
- Fixture sequence 15 participant: SVG width > container, chữ không scale theo maxWidth.
- Playwright (nếu CI cho phép): render 1 diagram + toolbar.

### Cổng

- Sequence 15 participant đọc được chữ ở 100% zoom trang.
- Ctrl+cuộn zoom sơ đồ; cuộn thường cuộn trang.
- Lỗi cú pháp không xóa bản render tốt trước đó.
- `time_to_chrome` không tệ hơn baseline ngoài sai số (Mermaid lazy).

Chưa làm PV-05 cửa sổ riêng, PV-06 sticky header sequence (G4 / Phase 9+).

---

## Phase 3 – F2 FTS5, chưa tóm tắt (2–3 ngày)

Nhánh: `feat/desktop-roadmap-p3-fts5`.

Tool `search_sessions` **giữ tên và field cũ**.

Khoảng trống còn lại (không phải "chưa xếp hạng gì"): substring chứ không BM25; limit 5; excerpt 360; mở từng JSONL. Đã có: ưu tiên title, không cutoff scan ẩn.

### 3.1 – Index

- [ ] `.coworker/recall/index.sqlite` theo namespace workspace.
- [ ] FTS5 `unicode61 remove_diacritics 2`: `content`, `title`; UNINDEXED: `session_key`, `message_index`, `role`, `ts`, `persona`, `project`.
- [ ] Index: user + assistant hiển thị; tool result 1000 ký tự đầu + tên tool. Bỏ system, ảnh, provider state.
- [ ] Không index: Dream, automation, guest threads, session user đánh dấu loại trừ.
- [ ] Trigram tokenizer: **tắt mặc định** (`recall.trigram: false`).

### 3.2 – Cập nhật

- [ ] Worker: sau save, index `message_index` mới hơn con trỏ.
- [ ] Reconcile 10 phút + lúc start: so `mtime` + size vs `index_state`.
- [ ] Xóa session → xóa dòng index.
- [ ] Seam `on_session_saved` / `on_session_deleted` nếu chấp nhận 15 dòng core; không thì chỉ reconcile.

### 3.3 – Tool

- [ ] Tham số mới (optional): `limit` 1–10, `since`, `scope` (`all|persona|project`). `summarize` **chưa** (Phase 5).
- [ ] Điểm: BM25 (title ×3) × `exp(-age_days / 30)` × 1,5 nếu cùng persona. Gộp theo session, tối đa 3 excerpt.
- [ ] Guest `scope` mặc định `persona`; agent chính `all`.
- [ ] `/recall reindex`.

### Test

- Index incremental; repair file (đổi size) → reindex.
- Tiếng Việt không dấu: "tom tat" khớp "tóm tắt".
- Guest không thấy session persona khác.
- Tương thích: caller cũ chỉ truyền `query` vẫn ra `session_key`, `excerpts`, `notice`.
- Microbench 10k messages: p95 < 200 ms (có thể fixture sinh).

### Cổng

- Recall@5 ≥ 0,8 trên bộ `recall_queries` (bổ sung nhãn; tối thiểu 10 query nếu chưa đủ 30).
- p95 < 200 ms không tóm tắt.
- Không đổi prompt đang dùng `search_sessions`.

---

## Phase 4 – F1 draft, CLI (2,5–3,5 ngày)

Nhánh: `feat/desktop-roadmap-p4-f1`. `mode: auto` **cấm**.

Tín hiệu "tác vụ tương tự": Phase 4 dùng khớp tên tool; nối F2 ở Phase 5.

### 4.1 – Trigger (không LLM)

- [ ] `SkillLearningHook` trong `after_run`, sau `_drive_workflow`.
- [ ] Ứng viên khi: không `cancelled|error|max_iterations`; tool calls ≥ 5; không Dream/cron/automation; persona không `learning: off`.
- [ ] Queue `.coworker/learning/queue.jsonl`; `max_drafts_per_day: 5`. Không chặn reply user.

### 4.2 – Pipeline nền

- [ ] Gom transcript (cắt tool result), tools, skills đã nạp.
- [ ] Đối chiếu `build_skills_summary()` + top-3 gần nghĩa.
- [ ] LLM coordinator → JSON `action: create|patch|skip`.
- [ ] `create` / `patch` theo khung `skill-creator`; `quick_validate.py`; lọc secret / PII / skill một-shot.
- [ ] Lưu `workspace/skills/_drafts/<name>/SKILL.md`; commit `GitStore` nếu Dream đã có git store, không thì file + sidecar meta.

### 4.3 – Vòng đời

- [ ] Frontmatter `nanobot.learning`: `status`, `version`, `origin_session`, `persona`, `uses`, `success`.
- [ ] Skill chỉ nạp cho persona tạo ra (main = `main`).
- [ ] `SkillsLoader`: bỏ `_drafts`, `retired`, persona khác.
- [ ] `/skills review`: list, show, approve, reject, edit. Approve mới `active`.

### Config

```yaml
coworker:
  learning:
    enabled: true
    mode: draft          # off | draft  (không có auto trong phase này)
    min_tool_calls: 5
    max_drafts_per_day: 5
    personas: []         # rỗng = mọi persona
```

### Test

- Trigger: 4 tool calls → không queue; 5 + success → queue; cancelled → không.
- Validate fail / secret → không lưu draft.
- Loader không đưa draft vào summary.
- `/skills review approve` → skill hiện cho đúng persona.

### Cổng

- Có nháp thật sau eval `repeat_tasks` (hoặc 1 phiên thủ công ≥ 5 tool).
- Không skill nào tự `active`.
- Chi phí phản tư ghi metrics (mục tiêu ≤ 15% token lượt gốc — theo dõi).

Tỉ lệ duyệt ≥ 40% đo sau khi có UI (Phase 5) và dùng thật; không fail CI.

---

## Phase 5 – F2 summarize + UI skill (2–3 ngày)

Nhánh: `feat/desktop-roadmap-p5-recall-ui`.

### 5.1 – Tóm tắt F2

- [ ] `search_sessions(summarize=true)`: ≤ 3 đoạn/session, ±2 tin, tổng ≤ 12k ký tự.
- [ ] Model coordinator; cite `message_index`.
- [ ] Cache `(session_key, indexed_count, hash(query))`, TTL 7 ngày.
- [ ] Dưới ngưỡng điểm → "không tìm thấy", không tóm tắt rác.
- [ ] Field mới: `summary` ≤ 400, `answer` ≤ 800.

### 5.2 – F1 dùng F2

- [ ] Tín hiệu "tác vụ tương tự ≥ 2 lần / 14 ngày" qua recall, không chỉ tên tool.

### 5.3 – UI duyệt skill

- [ ] Trang Skill trong settings coworker (WebUI = Desktop webview).
- [ ] List nháp: tên, persona, create/patch, ngày, link session, confidence, validate.
- [ ] Chi tiết: render markdown; patch hiện diff; Duyệt / Sửa rồi duyệt / Từ chối.
- [ ] Skill đang dùng: uses, success rate, Retire / Khôi phục.
- [ ] API cạnh `coworker/settings_api.py`.
- [ ] Badge số nháp trên nav.

### Test

- Cache hit không gọi LLM.
- Guest `summarize` vẫn `scope=persona`.
- API approve/reject + GitStore/file meta.
- Playwright: duyệt một nháp.

### Cổng

- Tóm tắt p95 cache miss < 6 s (đo thủ công/eval, không CI).
- `read_session` sau search giảm so với baseline (theo dõi ≥ 30%).
- Duyệt nháp trên Desktop loopback, không chỉ `bun run dev`.

---

## Phase 6 – Có điều kiện: ảo hóa / splash (0–3 ngày)

Nhánh: `feat/desktop-roadmap-p6-perf` — **chỉ mở khi Phase 0 vượt ngưỡng**.

### 6.1 – P2b ảo hóa

- [ ] Chỉ khi `scroll_fps_p1` dưới ngưỡng.
- [ ] `ThreadMessages` (~1000 dòng): chiều cao biến, neo cuộn lúc stream, quote, fork, activity cluster, find-in-page. Không virtualize mù.
- [ ] Cổng: cuộn 300 tin ≥ ngưỡng FPS; stream không block composer.

### 6.2 – P2c stream

- [ ] `useNanobotStream` đã rAF + `VISIBLE_STREAM_FLUSH_INTERVAL_MS = 50` / nền 1000 ms. **Không chỉnh** trừ khi `stream_fps_p1` hoặc composer bị block.

### 6.3 – P3 khởi động

- [ ] Lát rẻ luôn được phép: splash có skeleton + log `time_to_splash` / `time_to_chrome` / `time_to_interactive`.
- [ ] P3 đầy đủ (khung app trước bootstrap gateway) chỉ khi `time_to_chrome_ms` vượt ngưỡng. Việc này lớn (bundle WebUI vào Tauri hoặc đổi bootstrap) — spec riêng trước khi code.

### Cổng lát rẻ

- Số đo lặp lại được trên Desktop Windows, ghi đè/bổ sung baseline JSON.

---

## Phase 7 – Editor G1 (3–4 ngày)

Nhánh: `feat/desktop-roadmap-p7-editor-g1`.

`file_preview_payload` hiện **chỉ đọc**, cap `MAX_FILE_PREVIEW_BYTES = 384 KiB` text / 8 MiB ảnh, **không có `version`**. Endpoint ghi + `base_version` (hash nội dung, kèm mtime để debug) là **việc mới**. Watch / staged là G2.

Giữ test từ chối path ngoài workspace (`test_handle_file_preview_rejects_paths_outside_workspace`).

### 7.1 – Workspace file API (đọc + ghi user)

- [ ] `GET` list dir. Mọi path đi qua `WorkspaceScope` + `resolve_allowed_path` (không viết lại boundary).
- [ ] `GET` read: mở rộng preview: trả `version`; nới cap sửa text lên 5 MB **xem-only** trên file lớn hơn (ED-04).
- [ ] `PUT` write từ **user** (webview, HTTP loopback): body + `base_version`; lệch → 409 Conflict. Chưa chặn agent (G2). Không `invoke`.
- [ ] `POST` rename; `DELETE` luôn cần confirm phía client.
- [ ] Watch: sự kiện WS `fs.changed` (user|persona). Có thể polling ngắn nếu WS chưa sẵn.
- [ ] Loopback + bootstrap token; chặn `..`.

### 7.2 – Monaco pane

- [ ] Lazy load Monaco khi mở pane.
- [ ] Cây file: mở, tạo, đổi tên, xóa (confirm).
- [ ] Tab, dirty, khôi phục tab (localStorage keys, nội dung SoT = disk).
- [ ] ED-03: text → Monaco; `.md` → Monaco + preview (`MermaidPane`); ảnh → panel ảnh hiện có (Konva ở G3).
- [ ] Syntax, find/replace, multi-cursor, Ctrl+S, autosave option, theme app.
- [ ] Không `invoke` nội dung file.

### 7.3 – Preview markdown

- [ ] PV-01…04, PV-07, PV-09 (scroll sync) dùng chung renderer chat.
- [ ] Debounce preview ≤ 300 ms sau khi ngừng gõ.

### Test

- Write `base_version` lệch → 409.
- Path ngoài workspace → 403.
- 1 MB file đọc < 1 s trên máy local (đo, ghi vào PR).
- Unit: version đổi sau write.
- Playwright: mở, sửa, lưu, mở lại.
- Grep: không có `invoke` mang content trong `desktop/` + `webui/`.

### Cổng G1

- Sửa và lưu file workspace từ Desktop app local.
- Sequence 15 participant (đã có từ P2) trong preview editor.
- File/ảnh không qua Tauri `invoke`.

---

## Phase 8 – Editor G2 staged / diff (3–4 ngày)

Nhánh: `feat/desktop-roadmap-p8-editor-g2`. Chốt Q2 trước khi merge.

### 8.1 – Staged write

- [ ] Tool `file_write_staged`: ghi vùng chờ, kèm `base_version`.
- [ ] Agent **không** ghi file thật trừ `auto_accept` dirs (ED-11, mặc định tắt).
- [ ] `changes.list` / `changes.resolve` (hunk hoặc cả file).
- [ ] ED-16: version lệch → từ chối, agent phải đọc lại.

### 8.2 – Diff UI

- [ ] Monaco diff: side-by-side / inline.
- [ ] Accept/reject hunk và cả file.
- [ ] Danh sách chờ duyệt + tên persona.
- [ ] ED-15: tab đang mở bị agent sửa → badge + diff vs buffer user (không mất ký tự user).

### 8.3 – Chat ↔ editor

- [ ] ED-12: bôi đen → hỏi agent (path, line range, text).
- [ ] ED-13: `@file` trong chat mở tab.
- [ ] ED-14 `editor_context`: opt-in (Q5).

### Test

- Agent `write_file` thường bị chặn (hoặc chuyển staged) ngoài auto_accept — **cần seam tool filesystem**; ghi rõ file core/`coworker` hook.
- Accept một hunk không đụng hunk khác.
- Conflict: user typing vs staged apply.
- e2e: delegate ghi file → hiện diff → accept → disk đúng.

### Cổng G2

- Mọi file agent ghi ngoài thư mục nháp hoặc đang mở trong tab editor đều qua bước duyệt staged/diff.
- Ghi trực tiếp chỉ cho phép nếu trong thư mục nháp và không mở tab.
- Bôi đen hỏi agent: chat nhận đúng path + line range.

---

## Phase 9 – Image G3 (4–5 ngày)

Nhánh: `feat/desktop-roadmap-p9-image`. Chốt Q3, Q6 trước.

Không làm IM-17, không LLM mask/coords, không model vẽ chữ Việt.

### 9.1 – Konva pane (lazy)

- [ ] IM-01…10: zoom/pan, rect, ellipse, brush, pin, số thứ tự, undo, notes, `composite_to_original` default on.
- [ ] Tọa độ 0–1 theo ảnh gốc; mask PNG cùng size, vùng sửa trong suốt.

### 9.2 – Payload + tools

- [ ] Schema `nanobot.image-annotations/v1`.
- [ ] IM-11: gửi chat kèm mask, annotated image, JSON.
- [ ] Tools: `image_annotations_read`, `image_edit`, `image_composite`, `render_text`, `image_version_save`.
- [ ] Skill `image-region-edit` (built-in coworker): phân loại vùng, gộp không chồng, prompt EN, báo cáo theo số vùng.
- [ ] IM-12…14: version mới, slider trước/sau, gửi lại giữ region.

### Test

- JSON schema validate.
- Mask size = original; tọa độ lệch ≤ 1 px khi hiển thị scale.
- Composite: pixel ngoài vùng (+ feather) identical.
- `render_text` tiếng Việt có dấu (fixture font).
- Không có code LLM trả box/mask.

### Cổng G3

- Sửa nhiều vùng một lần gửi trên Desktop local.
- Agent báo đạt/chưa đạt theo số vùng.

G4 (sticky header sequence, version tree đầy đủ, IM-17, PV-08) **không** nằm trong roadmap lần này.

---

## Phase 10 – BrowserSkill Mức 2 (8–12 ngày)

Làm **cuối**. Local desktop only. Không Docker/VPS.

Nội bộ vẫn theo cổng đặc tả:

| Sub | Việc | Cổng |
| --- | --- | --- |
| P0 | Baseline Mức 1 (nếu đang dùng exec/`bsk`) | Có số session treo / miss help |
| P1 | Runner, registry, journal, hook dọn, tools read (`session/page/inspect/tabs list`), ảnh model | **0 session treo** trên nhóm tiêm lỗi |
| P2 | `interact`, tabs đầy đủ, persona policy, deny_domains VN, sensitive=`human` | 0 vi phạm red-team |
| P3 | Help bridge + đánh thức lượt | Thông báo < 5 s; wake ≥ 95% |
| P4 | Live view WebUI/Desktop + `/browser log` | Tự đánh giá 2 tuần |

- [ ] **Cấm** P2 `interact` nếu P1 chưa đạt 0 hung sessions.
- [ ] Live view loopback only; không đưa frame vào context model.
- [ ] F2 index log browser: chỉ tên thao tác + nhãn phần tử + domain + thời điểm. Không URL đầy đủ, không giá trị `fill`.

Chi tiết task lấy từ `dac-ta-browserskill-muc-2.md`; khi tới Phase 10, tách plan con nếu file này quá dài.

---

## Kiểm thử chung

Mỗi phase merge:

```text
uv run --no-sync pytest tests/coworker -q
uv run --no-sync ruff check nanobot/coworker nanobot/webui
cd webui && bun run test
```

Thêm:

- Phase 1+: `pytest tests/coworker/delegate tests/coworker/room -q` (đường dẫn chỉnh theo layout thật).
- Phase 2, 7–9: `bun run test` cho component mới + 1 lần chạy Desktop app local (ghi trong PR).
- Eval LLM không chặn CI; cổng quality chạy tay và lưu JSON cạnh baseline.

## Rủi ro

| Rủi ro | Ảnh hưởng | Giảm thiểu |
| --- | --- | --- |
| Brief quá mỏng | Guest `blocked` | Default `brief+user`; theo dõi `status: blocked` |
| Envelope thiếu chi tiết | Coordinator gọi `read_delegation` nhiều | Nới `key_points` trước khi nới context |
| FTS5 lệch sau repair | Search sai | Reconcile mtime+size; `/recall reindex` |
| Skill rác | Ồn | `max_drafts_per_day`, validate, 14 ngày xóa nháp |
| Monaco/Konva/Mermaid nặng | Mở app chậm | Lazy load; đo `time_to_chrome` sau mỗi phase UI |
| Staged write đụng `write_file` core | Agent vẫn ghi đè | Hook/policy chặn; test đỏ nếu còn đường tắt |
| Hermes vs Pi | Scope creep gỡ Pi | Đã chốt lựa chọn A: Chỉ gỡ Pi khỏi room guest, không gỡ /code subsystem |

## Cách follow tiến độ

1. Một nhánh git / phase; PR ghi cổng và số đo.
2. Cập nhật bảng đầu file: `chưa` → `đang` → `xong` / `bỏ`.
3. Tick `- [ ]` khi code + test + cổng xong, không tick khi mới viết.
4. Phase 6 để trống cho đến khi có `desktop-perf-baseline.json`.
5. Q1–Q6 chưa chốt thì không merge phase bị chặn.
6. Không commit plan này cùng code feature; commit docs khi chủ dự án chấp nhận ranking.

## Definition of Done (toàn roadmap)

Roadmap **chưa xong** khi mới hết F3. Mốc dùng hàng ngày:

- **Mốc A (sau Phase 5):** room gọn, search được session cũ, skill nháp duyệt được, Mermaid đọc được. Đây là mốc nên dừng và dùng thật 1–2 tuần.
- **Mốc B (sau Phase 8):** không cần VS Code để duyệt diff agent trên file text.
- **Mốc C (sau Phase 9):** sửa ảnh theo vùng trong app.
- **Mốc D (sau Browser P1+):** agent đọc trình duyệt không để session treo; `interact` là mốc sau nữa.

Sau Mốc A, ưu tiên dùng thật hơn là lao vào G1 nếu editor chưa đau.
)
