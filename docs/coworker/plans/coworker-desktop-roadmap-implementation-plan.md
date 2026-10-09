# Implementation plan: Coworker Desktop local (Windows)

_Cập nhật: 09/10/2026 · Repo: `cuongpt083/nanobot`, nhánh `develop` · Mục tiêu: Desktop app Windows (Tauri webview → gateway `127.0.0.1`)_

Kế hoạch này gộp bốn đặc tả đã chỉnh cho **local Desktop**, xếp theo giá trị dùng thật và rủi ro. Không thiết kế remote use (VPS, SSH, Tailscale, WebUI điện thoại). Ước lượng 23–42 ngày (đã cộng pane ảnh IM-17 vào Phase 10) công tùy phase có điều kiện (ảo hóa, time-to-chrome) và BrowserSkill.

Đặc tả nguồn:

- `docs/coworker/proposals/dac-ta-hermes-3-nang-luc.md` (F1, F2, F3)
- `docs/coworker/proposals/dac-ta-hieu-nang-desktop.md` (P1–P3)
- `docs/coworker/proposals/dac-ta-editor-image-pane.md` (G1–G4)
- `docs/coworker/proposals/dac-ta-browserskill-muc-2.md` (Browser P0–P4)

## Bảng theo dõi

| Phase | Việc | Ước lượng | Trạng thái | Cổng |
| --- | --- | --- | --- | --- |
| 0 | Baseline WebView2 + eval | 1–1,5 ngày | một phần (chờ số đo & eval run) | Có số đo ổn định, 2 lần chạy |
| 0.5 | Gỡ Pi room guest (Lựa chọn A) + dọn tàn dư agy | 1–1,5 ngày | xong (`abff70c8`) | Toàn bộ room guest chạy AgentRuntime; tests room xanh, 156 coding tests pass |
| 1 | F3 brief / envelope | 2–3 ngày | chưa | Token guest −40% vs `full`; envelope hợp lệ ≥ 90% |
| 2 | Mermaid P2a (ELK, pan/zoom, viewport) | 2–3 ngày | đã code và test (nhánh `feat/desktop-roadmap-p2-mermaid`); chưa kiểm chứng trên trình duyệt | Sequence 15 participant đọc được; Ctrl+cuộn zoom sơ đồ |
| 3 | F2 FTS5 (chưa tóm tắt) | 2–3 ngày | chưa | Recall@5 ≥ 0,8; p95 < 200 ms |
| 4 | F1 draft (CLI `/skills review`) | 2,5–3,5 ngày | chưa | Nháp hợp lệ; không tự active |
| 5 | F2 summarize + UI duyệt skill | 2–3 ngày | chưa | Tóm tắt cache; duyệt nháp trên WebUI/Desktop |
| 6 | P2b ảo hóa / P3 time-to-chrome | 0–3 ngày | có điều kiện | Chỉ khi baseline còn jank / chờ lâu |
| 7 | Editor G1 (đọc/sửa/lưu + preview) | 3–4 ngày | đã code và test (nhánh `feat/desktop-roadmap-p7-editor-g1`); chưa kiểm chứng trên trình duyệt; chưa có watch `fs.changed` | Mở 1 MB < 1 s; không qua Tauri `invoke` |
| 8 | Editor G2 (staged / diff / hunk) | 3–4 ngày | chưa (UI #4; kèm cập nhật advisor) | File ngoài drafts hoặc tab đang mở đều qua staged review |
| 9 | Image G3 (Konva + skill) | 4–5 ngày | đã code và test (nhánh `feat/desktop-roadmap-p9-image`); chưa kiểm chứng trên Desktop; IM-12…14 làm một phần (khóa hình học vùng đã đạt và cây phiên bản chưa có) | Sửa nhiều vùng một lần gửi; version ảnh lưu OS tempdir |
| 10 | BrowserSkill P0–P4 (local-only, no Docker) + pane ảnh IM-17 | 9–14 ngày | bước 1 (phía nanobot, P1 một phần) đã code và test với bsk giả lập; kiểm chứng hợp đồng bsk thật đã làm cho luồng không cần trình duyệt; chưa có daemon + extension + Chrome thật | 0 session treo trước khi bật `interact` |

Đánh dấu `- [x]` trong từng phase khi xong và đã qua cổng. Không sang phase sau nếu cổng fail, trừ khi có quyết định dừng/bỏ rõ ràng.

## Cập nhật 09/10/2026: thứ tự ưu tiên hiện tại

Quyết định: sau khi rà soát chất lượng thông tin giữa coordinator và advisor, **làm giao diện trước** (Mermaid, Editor, Image).
F3, F2, F1 (Phase 1, 3, 4, 5) được **hoãn, không hủy**; số phase giữ nguyên để không vỡ tham chiếu.

Thứ tự đề xuất cho nhánh giao diện:

| # | Phase | Việc | Phụ thuộc |
| --- | --- | --- | --- |
| 1 | 2 | `MermaidPane` trong chat | Spike 2.0 đã có kết luận (Hướng A), còn kiểm chứng ELK |
| 2 | 7.1 | Workspace file API: đọc có `version`, ghi có `base_version` | Không |
| 3 | 7.2–7.3 | Monaco và preview markdown (dùng lại `MermaidPane`) | Phase 2, 7.1 |
| 4 | 8 | Staged write và diff | Phase 7; cần cập nhật advisor (mục 8.4) |
| 4 | 9 | Image Konva, chạy song song với Phase 8 được | Chỉ cần 7.1 (đặc tả `dac-ta-editor-image-pane.md`, giai đoạn 3) và chốt Q6 |

Hệ quả cần biết:

- Phase 5.3 (UI duyệt skill) sẽ dùng lại renderer markdown của Phase 2 và diff Monaco của Phase 8, nên rẻ hơn nếu nhánh giao diện chạy trước.
- Lộ trình gốc khuyên dùng thật 1–2 tuần sau Mốc A trước khi vào editor. Thứ tự mới bỏ qua Mốc A; thay vào đó dùng thật Mermaid (Phase 2) rồi mới quyết định có vào Phase 7 không.
- Phase 8 đổi cách agent ghi file, nên phải cập nhật steering của advisor cùng lúc (mục 8.4).


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
| D6 | `MarkdownTextRenderer` không truyền `plugins` cho Streamdown và ghi đè `components.code`, nên mọi khối `language-*` (kể cả `mermaid`) đi vào `CodeBlock`: sơ đồ hiện như code đã tô màu, không phải sơ đồ (theo code và `mermaid-streamdown-note.md`; chưa kiểm tra bằng UI chạy thật). Chưa có pan/zoom riêng, ELK, và `mermaid` 11.16.0 chỉ là phụ thuộc gián tiếp của Streamdown | `MarkdownTextRenderer.tsx` (`components.code`) | 2 |
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
- Monaco-as-IDE: LSP, debugger, terminal, marketplace.
- LLM tự tính tọa độ / mask / ghép ảnh.
- Browser `interact` trước khi P1 đạt 0 session treo.
- Gỡ toàn bộ Pi coding subsystem. Hermes F3 ghi "Pi sẽ bị gỡ" — ngoài phạm vi; chỉ gỡ Pi khỏi Room guest backend (Phase 0.5) để F3 bao phủ 100% room delegation, còn phân hệ `/code` và `coding_agent` độc lập vẫn giữ nguyên.
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
| Q6 | Provider ảnh đầu tiên có nhận mask không? | **Không phụ thuộc vào provider.** Model sửa cả ảnh, `image_composite` giữ pixel ngoài vùng khoanh bằng mask dựng từ hình học trên server. Nếu sau này có provider nhận mask thì chỉ bổ sung tham số. | Đã chốt |

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

- [x] Tạo session fixture ~300 tin: code block dài, ≥ 3 sơ đồ Mermaid (kể cả sequence 15 participant), markdown bảng (`docs/coworker/plans/chat-300-fixture.jsonl`).
- [x] Script seed: sinh JSONL ~300 tin (code + ≥ 3 Mermaid, 1 sequence 15 participant) rồi nạp qua SDK / import session (`scripts/gen_chat_fixture.py`).
- [ ] Quy trình đo trên Desktop Windows (không chỉ `bun run dev`): WebView2 remote debugging (CDP, `remote-debugging-port`) **hoặc** `performance.mark` / `performance.measure` trong WebUI ghi ra log. Ghi đủ lệnh vào baseline JSON (`machine`, `commit`, `method`).

### 0.2 – Số đo (ghi `docs/coworker/plans/desktop-perf-baseline.json`)

Mỗi số: trung vị 3 lần, máy và commit. (Chờ người dùng đo trên WebView2 thực tế).

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

`scripts/coworker_eval.py` **đã có**, bao gồm 7 kịch bản trong `tests/coworker/eval/scenarios/` (`crm-followup`, `edutech-course`, `nutritech-plan`, `persona-nutri`, `persona_delegation`, `presale-design`, `script-update`).

- [ ] Chạy cả 7 kịch bản hiện có 2 lần (bao gồm `persona_delegation`), lưu `docs/coworker/plans/archive/eval/coworker-eval-baseline.json` với runner `gemini-3.8-flash-tiered`, advisor `claude-sonnet-5-5`, judge `claude-opus-5-5`.
- [x] Skeleton YAML cho `recall_queries` (F2) và `repeat_tasks` (F1). `persona_delegation` đã được bổ sung vào bộ kịch bản đánh giá baseline.
- [x] Spike Streamdown (không đoán): `webui/src/components/` không có chữ `mermaid`; diagram đi qua chunk Streamdown. Đọc option mermaid của đúng phiên Streamdown đang ghim; thử `mode=streaming` với khối chưa đóng. Ghi `docs/coworker/plans/mermaid-streamdown-note.md` (commit `7db5ba87`).

### Test / tiêu chí xong

- File baseline JSON đã commit (hoặc đính kèm PR) với 3 lần đo.
- Ghi chú Streamdown có bằng chứng (screenshot hoặc log render).
- Không đổi hành vi product.

---

## Phase 0.5 – Gỡ Pi Room Guest & Dọn Dẹp "agy" (1–1,5 ngày)

Nhánh: `feat/desktop-roadmap-p0-5-pi-guest-cleanup`.

Mục tiêu: Đưa toàn bộ room guest về chạy qua `AgentRuntime`, chuẩn bị tiền đề cho Phase 1 (F3 brief/envelope) bao phủ 100% room delegation mà không bị phân nhánh `CodingRunner`. Giữ nguyên phân hệ `/code` và `coding_agent` độc lập.

### 0.5.1 – Gỡ Pi khỏi Room Guest
- [x] Bỏ trường `backend` trong `RoomAgentConfig` (`nanobot/coworker/config.py`).
- [x] Xóa nhánh xử lý `CodingRunner` trong `_run_guest` (`nanobot/coworker/room/scheduler.py`). Toàn bộ delegation gọi `AgentRuntime`.
- [x] Cập nhật các test liên quan tới room guest runner.

### 0.5.2 – Dọn dẹp tàn dư "agy"
- [x] Xóa cấu hình / hằng số `"agy"` còn sót ở `nanobot/coworker/hook.py`, `status.py`, `settings_api.py`, `config.py`, `backends/base.py`.
- [x] Giữ nguyên Pi là backend duy nhất cho `/code` CLI (`CodingRunner`, `backends/pi.py`, `nanobot-bridge.ts`).

### Cổng Phase 0.5
- [x] Toàn bộ test của room pass (test_room, test_room_dag, test_room_delegate_v2).
- [x] 188 tests của coding subsystem pass: `uv run --no-sync pytest tests/coworker/coding -q`.

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

Đã có kết quả (`mermaid-streamdown-note.md`, đối chiếu lại 09/10/2026): Streamdown 2.5.0 chỉ render Mermaid qua `plugins.mermaid`; `MarkdownTextRenderer`
không truyền plugin và còn ghi đè `components.code`, nên hiện khối `language-mermaid` đi vào `CodeBlock`. `mermaid` 11.16.0 có trong `node_modules`
chỉ như phụ thuộc gián tiếp của Streamdown (`^11.12.2`). Chưa cài `elkjs`, `@mermaid-js/layout-elk`, `@panzoom/panzoom`.

- [x] Xác nhận Streamdown có prop mermaid hay phải override: **chọn Hướng A**, bắt `language === "mermaid"` trong `components.code` của `MarkdownTextRenderer` và render `MermaidPane` lazy.
- [x] Không fork Streamdown: dùng `MermaidPane` tự viết.
- [x] Thêm `mermaid` làm phụ thuộc trực tiếp và ghim chính xác `11.16.0` (cùng bản mà Streamdown đang dùng; không có bản trùng).
- [x] Kiểm chứng ELK: **dùng `@mermaid-js/layout-elk@0.2.3`**, peer `mermaid ^11.0.2`, phụ thuộc `elkjs`. Bản `1.x` yêu cầu `mermaid ^12` nên **không dùng được** với Streamdown (ghim `^11`). Đăng ký qua `mermaid.registerLayoutLoaders(elk.default)`.
- [x] Thêm `@panzoom/panzoom@4.6.2` (không có phụ thuộc). Đo chunk: xem mục "Kết quả Phase 2" bên dưới.

### 2.1 – Wrapper

- [x] Component `MermaidPane` (lazy): `webui/src/components/mermaid/MermaidPane.tsx`; mermaid và ELK được import động qua `mermaid-loader.ts`. Ghi đè tuỳ diagram (frontmatter `layout`) vẫn đúng vì mermaid đọc frontmatter sau cấu hình chung.
- [x] `useMaxWidth` tắt cho flowchart và sequence; sequence `wrap: true`, `mirrorActors: false` (`mermaid-config.ts`).
- [x] Ctrl+cuộn zoom (`zoomWithWheel`, chỉ khi `ctrlKey`), chụm và kéo pan qua Panzoom; nhấp đúp reset. Cuộn thường không bị chặn. Không dùng bind wheel mặc định của Panzoom (v4 không gắn wheel).
- [x] Thanh công cụ: zoom ±, fit (reset), toàn màn hình (Esc để thoát), tải SVG, tải PNG, copy source. **Chưa có** "fit width/height" riêng: chỉ có reset về 100%.
- [x] Lỗi cú pháp: báo dòng khi mermaid có nêu; giữ SVG hợp lệ gần nhất trên màn hình.
- [x] Không layout khi ngoài viewport (IntersectionObserver, rootMargin 200px).
- [x] Debounce 150 ms; khối đang stream chỉ hiện mã nguồn, không render (`streaming` từ `MarkdownTextRenderer`).

### 2.2 – Gắn vào chat

- [x] `MarkdownTextRenderer`: khối `mermaid` được chặn ở override `pre` (trước `isRenderedCodeBlock`, vì một diagram trong `<pre>` là HTML không hợp lệ) và ở `code`. Không fork Streamdown.
- [x] Theme dark/light theo `useThemeValue()` (`mermaid.initialize` mỗi lần render).
- [x] Lazy: đã đo, xem bên dưới. Đã **bỏ** quy tắc gộp `markdown-diagrams` cho mermaid vì nó gom mọi loại diagram thành một file 8 MB.

### Test

- [x] Unit: config mermaid (ELK, useMaxWidth off, strict, theme) — `mermaid-config.test.ts`.
- [x] Component: Ctrl+wheel zoom, wheel thường không bị chặn; render khi đang stream bị hoãn; lỗi giữ SVG cũ và báo dòng; toolbar — `mermaid-pane.test.tsx` (mock mermaid và panzoom).
- [x] Định tuyến: fence `mermaid` tới `MermaidPane`, ngôn ngữ khác không đổi — `markdown-mermaid-routing.test.tsx`.
- [ ] Fixture sequence 15 participant: SVG width > container, chữ không scale. **Chưa làm** (cần trình duyệt thật; happy-dom không có layout).
- [ ] Playwright: render một diagram và toolbar. **Chưa làm.**
- [x] Hồi quy: `markdown-text-renderer`, `advisor-consult-row`, `coworker-message-card` vẫn xanh.
- Hồi quy: thẻ advisor (`AdvisorConsultRow`) và `CoworkerMessageCard` dùng `MarkdownText`; giữ xanh `markdown-text-renderer.test.tsx`, `advisor-consult-row.test.tsx`, `coworker-message-card.test.tsx`. Hiện chưa có test nào render sơ đồ (chỉ có quy tắc chunk trong `vite-config.test.ts`).

### Cổng

- [ ] Sequence 15 participant đọc được chữ ở 100% zoom trang. **Chưa kiểm chứng** (không có trình duyệt).
- [ ] Ctrl+cuộn zoom sơ đồ; cuộn thường cuộn trang. Có test đơn vị; **chưa kiểm chứng** trên Desktop.
- [x] Lỗi cú pháp không xóa bản render tốt trước đó (test đơn vị).
- [ ] `time_to_chrome` không tệ hơn baseline. **Bỏ qua theo quyết định của bạn** (baseline hiệu năng chưa đo). Lưu ý: shell không đổi kích thước, xem bên dưới.

### Kết quả Phase 2 (đo ngày 09/10/2026)

- **Shell** (`index-*.js`): 528 KB trước và sau (không đổi).
- **`MarkdownTextRenderer`** (tải cùng luồng chat): 5 KB → 12 KB gzip (MermaidPane và Panzoom).
- **Mermaid khi có diagram đầu tiên**: core khoảng 131 KB gzip, ELK (`render`) khoảng 602 KB gzip, cộng chunk của loại diagram và cytoscape nếu cần. Chỉ tải khi trang có diagram.
- Tổng JS (toàn bộ chunk lazy) tăng từ 4,2 MB lên 12,2 MB raw; không phải tất cả đều được tải.
- Build WebUI thành công; `tsc` sạch; lint sạch cho các file đã đổi.
- Bộ test WebUI: 2207 pass, 11 fail. Cả 11 đều **có sẵn trên `develop`** (i18n `zh-CN` và service worker), không liên quan Phase 2.

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
- [ ] Dùng lại renderer markdown (Phase 2) và diff Monaco (Phase 8) nếu đã có; nếu chưa, bản đầu dùng `MarkdownText` và diff dạng văn bản.
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

### Hiện trạng giao diện (đối chiếu 09/10/2026)

- `FilePreviewPanel` (trong khung tab `PreviewPane` bên phải) chỉ **đọc**: file text hiển thị bằng `CodeBlock` (tô màu, có cảnh báo "bị cắt" khi vượt cap), `.md` cũng chỉ hiện như code, **chưa render markdown**; ảnh mở bằng `ImageLightbox` với `data_url`.
- `ImageLightbox` và `ZoomableImage` đã có zoom/pan (Ctrl+cuộn, pinch, kéo) và duyệt nhiều ảnh. Đây là "panel ảnh hiện có" của ED-03 cho tới khi có Konva (G3); không viết lại.
- Chưa có `monaco-editor` / `@monaco-editor/react`: thêm lazy trong phase này và đo `time_to_chrome` ngay sau khi thêm.
- Preview markdown (7.3) dùng `MarkdownTextRenderer` hiện có cộng `MermaidPane` của Phase 2, nên Phase 2 phải xong trước.

### 7.1 – Workspace file API (đọc + ghi user)

- [x] `GET` list dir (`/api/sessions/{key}/workspace/list`). Mọi path đi qua `resolve_allowed_path` với gốc là project; link trỏ ra ngoài bị ẩn.
- [x] `GET` read (`/workspace/read`): trả `version` (sha256 rút gọn). Sửa được tới 5 MiB; file lớn hơn trả 413 (chưa có chế độ xem-only cho file lớn, ED-04 để sau).
- [x] Ghi từ user: **đi qua WebSocket đã xác thực** (mutation `session.workspace.write`), không phải HTTP thường, theo cách mọi mutation WebUI khác của repo làm. Lệch `base_version` → 409 kèm `current_version`. Không chặn agent (G2).
- [x] Rename (`session.workspace.rename`, cùng thư mục, không ghi đè); delete (`session.workspace.delete`, chỉ file, có kiểm version). Confirm ở phía client.
- [ ] Watch: sự kiện WS `fs.changed` (user|persona). **Chưa làm.** Hiện chỉ phát hiện xung đột khi lưu (409); file đổi bên ngoài không tự làm mới.
- [x] Xác thực bằng token API; `..` và đường dẫn tuyệt đối ra ngoài project bị từ chối (403), đã có test.

### 7.2 – Monaco pane

- [x] Monaco tải lazy khi mở editor. Chỉ nạp core và định nghĩa tokenizer cần dùng; **không** kéo dịch vụ ngôn ngữ TypeScript/JSON/CSS/HTML (ban đầu kéo theo 6,9 MB worker, đã bỏ).
- [x] Cây file: mở, mở rộng thư mục (lazy), tạo, đổi tên, xóa (confirm). Tên file nhập bằng hộp thoại trình duyệt tạm thời; cần thay bằng ô nhập inline.
- [x] Tab, dirty (•), đóng tab hỏi trước khi bỏ thay đổi. **Chưa** khôi phục tab sau khi tải lại trang (localStorage).
- [x] ED-03: text → Monaco; `.md` → Monaco + preview markdown (dùng `MarkdownText`, có `MermaidPane` cho khối mermaid); ảnh vẫn ở panel ảnh hiện có (Konva ở G3).
- [x] Syntax (tokenizer), Ctrl+S, theme sáng/tối theo app; find/replace và multi-cursor có sẵn trong Monaco. **Chưa** autosave.
- [x] Không `invoke` nội dung file: đọc và ghi đều qua HTTP/WebSocket của gateway.

### 7.3 – Preview markdown

- [x] Preview dùng chung renderer chat (`MarkdownText`). **Chưa** PV-07, PV-09 (scroll sync).
- [x] Debounce preview 300 ms; mở file khác thì hiện ngay, không chờ.

### Test

- Write `base_version` lệch → 409.
- Path ngoài workspace → 403.
- 1 MB file đọc < 1 s trên máy local (đo, ghi vào PR).
- Unit: version đổi sau write.
- Playwright: mở, sửa, lưu, mở lại.
- Grep: không có `invoke` mang content trong `desktop/` + `webui/`.

### Kết quả Phase 7 (đo ngày 09/10/2026)

- **Lệch khỏi plan:** (1) ghi đi qua WebSocket mutation, không HTTP loopback, theo đúng cách repo làm; (2) JSON hiển thị như văn bản thường, vì Monaco chỉ có tokenizer JSON qua dịch vụ ngôn ngữ (đã bỏ để giữ bundle nhỏ).
- **Test:** `tests/webui/test_workspace_files.py` 14 pass (1 bỏ qua do symlink cần quyền trên Windows). WebUI: `workspace-editor.test.tsx` 8 pass, `file-preview-edit-entry.test.tsx` 2 pass. Toàn bộ WebUI: 2217 pass, 11 fail, cùng 11 lỗi có sẵn của Phase 2.
- **Bundle:** shell (`index`) 528 KB, không đổi. Editor: `editor.api` 2,7 MB raw (695 KB gzip) và worker 81 KB gzip, chỉ tải khi mở editor; khoảng 780 KB gzip cho lần mở đầu tiên.
- **Chưa kiểm chứng:** mở, sửa, lưu và mở lại trong trình duyệt thật; Playwright; hành vi Monaco thật (test dùng stub). Đây là việc cần làm trước khi coi Phase 7 là xong.
- **Chưa làm:** watch `fs.changed`, khôi phục tab sau khi tải lại, autosave, PV-07/PV-09, xem-only cho file trên 5 MiB, ô nhập inline thay hộp thoại trình duyệt.

### Cổng G1

- Sửa và lưu file workspace từ Desktop app local.
- Sequence 15 participant (đã có từ P2) trong preview editor.
- File/ảnh không qua Tauri `invoke`.

---

## Phase 8 – Editor G2 staged / diff (3–4 ngày)

Nhánh: `feat/desktop-roadmap-p8-editor-g2`. **Trạng thái: làm một phần.** Phần ghi có duyệt và diff đã code và test; chat↔editor (8.3), duyệt từng hunk, và kiểm chứng trên trình duyệt thật chưa làm.

### 8.1 – Staged write

- [x] Tool `file_write_staged` (`nanobot/coworker/staged/tools.py`): ghi vào hàng chờ kèm `base_version`, không ghi lên đĩa cho tới khi người dùng chấp nhận.
- [x] Quy tắc (`nanobot/coworker/staged/guard.py`, gắn trong `CoworkerHook.before_execute_tool`): ghi trực tiếp chỉ được vào `.coworker/drafts/` và file không mở trong tab. `apply_patch` không đọc được đường dẫn thì bị chặn. Cờ `coworker.staging.enabled` **mặc định tắt**; khi tắt, tool bị ẩn và guard không chạy.
- [x] `changes` (đọc, `GET .../workspace/changes`) và `resolve` (`session.workspace.resolve`, accept hoặc reject cả file). Hunk-level chưa làm.
- [x] ED-16: version lệch → 409, đề xuất giữ ở trạng thái chờ, agent phải đọc lại. Đã test.
- [x] Đề xuất mới cho cùng một đường dẫn thay thế đề xuất cũ (`superseded`).

### 8.2 – Diff UI

- [x] Monaco diff side-by-side, chỉ đọc (`DiffView.tsx`). Chế độ inline chưa làm.
- [x] Accept / reject cả file (`ChangeReview.tsx`). Accept hunk chưa làm.
- [x] Danh sách chờ duyệt có tên persona (`by`) trong nút đếm và trên màn duyệt.
- [x] ED-15: tab đang mở có đề xuất của agent → chấm cam trên tab; danh sách đề xuất làm mới mỗi 4 s (không cần tải lại). Hiện chỉ phát hiện đề xuất; thay đổi trực tiếp trên đĩa không được theo dõi (chưa có `fs.changed`).

### 8.3 – Chat ↔ editor

- [x] ED-12: bôi đen trong editor → menu chuột phải "Hỏi agent về đoạn này" đưa vào ô soạn tin trích dẫn kèm đường dẫn và dòng (`From notes.md, lines 2-3:`). Người dùng vẫn phải tự gửi. Chưa có phím tắt.
- [~] ED-13: file trong tin nhắn chat mở ở editor (text mở thẳng ở chế độ sửa; nút "Quay lại xem trước" đổi về chế độ xem). **Chưa** có `@` gợi ý file trong ô soạn tin.
- [x] ED-14 `editor_context`: công tắc "Chia sẻ với agent" trong editor, **tắt mặc định**, nhớ theo trình duyệt. Khi bật, tin nhắn gửi kèm đường dẫn file đang mở và đoạn đang chọn (tối đa 4 000 ký tự), chỉ trong session đó. Backend đưa vào như dữ liệu, chỉ với kết nối WebUI tin cậy.

### 8.4 – Advisor và steering (phụ thuộc chéo)

- [x] Thêm `file_write_staged` vào `WRITE_TOOLS` (`nanobot/coworker/advisor/evidence.py`). `params_paths` đọc khóa `path` chung nên đường dẫn được nhận dạng.
- [ ] Gói evidence đọc nội dung đang chờ duyệt cho các file chưa được chấp nhận (ghi "chưa áp dụng"). **Chưa làm**; evidence hiện vẫn dựa vào `git diff`.
- [ ] Test: một lần ghi staged được đếm là bước làm việc và là "write" cho commit gate. **Chưa có test riêng**; mới có test guard và test tập `WRITE_TOOLS` gián tiếp.
- Xem `advisor-room-integration.md` (mục 11) cho các vị trí artifact liên quan.

### Kết quả Phase 8 (đo ngày 09/10/2026)

- **Lệch khỏi plan:** duyệt đi qua WebSocket mutation (`session.workspace.resolve`, `session.workspace.tabs`), giống Phase 7; danh sách đề xuất là GET. Tên persona lấy từ `get_persona_id`, mặc định `coordinator`.
- **Test:** `tests/coworker/test_staged_writes.py` 17 pass (store: đề xuất, xung đột, thay thế, accept, reject, ngoài project; guard qua `CoworkerHook`). WebUI: `staged-change-review.test.tsx` 6 pass; `workspace-editor.test.tsx` 8 pass; `file-preview-edit-entry.test.tsx` 2 pass. Toàn bộ WebUI vẫn đúng 11 lỗi có sẵn (i18n zh-CN, sw.test.ts).
- **Đợt 8.3 / ED-15 (cùng ngày):** `tests/webui/test_editor_context.py` 5 pass; `test_websocket_channel.py` có 2 test mới (đường tin cậy và không tin cậy); `nanobot-client.test.ts` 85 pass (có test `editor_context`); `workspace-editor-agent.test.tsx` 7 pass (hỏi agent, chia sẻ, badge và làm mới). Toàn bộ pytest coworker/webui/websocket: 1437 pass, 4 lỗi có sẵn. Toàn bộ WebUI: 11 lỗi có sẵn.
- **Thay đổi hành vi cần xác nhận:** (1) text mở từ chat giờ vào editor ngay (trước là xem trước); (2) câu bọc trích dẫn ở backend đổi từ "earlier assistant response" thành "earlier reply or a project file", vì trích dẫn từ editor không phải phản hồi của assistant.
- **Chưa có test:** route WebSocket `session.workspace.resolve` và `session.workspace.tabs` (chỉ kiểm tra qua store và hàm); luồng agent thật ghi tệp đề xuất rồi người dùng duyệt.
- **Chưa kiểm chứng:** trình duyệt thật; agent thật chọn `file_write_staged` khi cờ bật.

### Test

- Agent `write_file` thường bị chặn ngoài thư mục nháp: **đã test** qua hook (`_staging_block`).
- Accept một hunk không đụng hunk khác: **chưa** (chưa có hunk).
- Conflict: user đang gõ và có đề xuất được chấp nhận: **đã test** (banner, không ghi đè).
- e2e: delegate ghi file → hiện diff → accept → disk đúng: **chưa**.

### Cổng G2

- [x] Mọi file agent ghi ngoài thư mục nháp hoặc đang mở trong tab editor đều đi qua bước duyệt (khi cờ bật).
- [x] Ghi trực tiếp chỉ cho phép trong thư mục nháp và khi không mở tab.
- [x] Bôi đen hỏi agent: chat nhận đúng path + line range (đã test).

**Kết luận:** các điều kiện của G2 đã có trong code và test. Chưa đóng G2 vì: (1) chưa kiểm chứng trên trình duyệt thật; (2) duyệt từng hunk chưa làm; (3) ED-13 chưa có `@` gợi ý file; (4) theo dõi thay đổi trực tiếp trên đĩa chưa làm. Giữ `coworker.staging.enabled` tắt mặc định cho đến khi kiểm chứng xong.

---

## Phase 9 – Image G3 (4–5 ngày)

Nhánh: `feat/desktop-roadmap-p9-image`. Chốt Q3, Q6 trước.

Không làm IM-17 (chuyển sang Phase 10, mục P4-ảnh), không LLM mask/coords, không model vẽ chữ Việt.

Phụ thuộc (theo đặc tả, giai đoạn 3): chỉ cần workspace file API của Phase 7.1, nên chạy song song với Phase 8 được.
Hiện trạng (09/10/2026): chưa cài `konva` / `react-konva`; viewer ảnh hiện có (`ImageLightbox`, `ZoomableImage`) chỉ để xem, chưa có công cụ khoanh vùng;
Q6 (provider ảnh đầu tiên có nhận mask không) vẫn mở và chặn `image_edit`.

### 9.1 – Konva pane (lazy)

- [x] IM-01…10: zoom (lăn chuột), pan, Fit, rect, ellipse, brush, pin, eraser, số thứ tự theo thứ tự tạo với màu riêng, undo/redo (nút và Ctrl+Z / Ctrl+Y), ghi chú từng vùng và chung, chọn ghi chú làm nổi vùng (IM-08), công tắc "chỉ sửa trong vùng khoanh" (bật mặc định). IM-03: kéo vùng để di chuyển (giữ kích thước, không ra khỏi ảnh); hình chữ nhật và ellipse có 4 tay cầm góc để đổi kích thước; Delete xóa vùng đang chọn. IM-04: cọ có 3 cỡ (S/M/L); tẩy là nét cọ có `erase: true`, xóa phần đã đánh dấu theo đúng thứ tự vẽ (server dựng mask theo thứ tự). Tay cầm chỉ có ở hình chữ nhật và ellipse, không có ở cọ và ghim.
- [~] Tọa độ 0–1 theo ảnh gốc: đã có. **Lệch khỏi plan:** không gửi mask PNG. Nét cọ gửi dưới dạng các điểm và bán kính; server dựng mask (`raster.region_mask`), nên không có file mask nhị phân nào đi qua request.

### 9.2 – Payload + tools

- [x] Schema `nanobot.image-annotations/v1`: validate ở server (`nanobot/coworker/image/annotations.py`), 25 test backend, cùng giới hạn (50 vùng, 1 000 ký tự, 2 000 điểm cọ) phía client.
- [x] IM-11: gửi chat. Ghi file annotation vào workspace cạnh ảnh (`<tên>.annotations.json`, có kiểm phiên bản) rồi gửi một tin nhắn yêu cầu sửa, kèm đường dẫn ảnh và file annotation. Kèm **ảnh đánh dấu** (annotated PNG): ảnh gốc ở kích thước thật (tối đa 1 600 px) với từng vùng vẽ đúng màu và số, vẽ bằng canvas theo cùng bảng màu của pane (`components/image/annotated-image.ts`). Agent cũng đọc ảnh gốc và file annotation qua `image_annotations_read`.
- [x] Tools: `image_annotations_read`, `image_edit`, `image_composite`, `render_text`, `image_version_save` (`nanobot/coworker/image/tools.py`), ẩn khi `coworker.image.enabled` tắt (mặc định tắt). `image_edit` dùng lại tool sinh ảnh hiện có; **chưa kiểm chứng với provider thật**.
- [x] Kho lưu phiên bản ảnh: thư mục tạm `nanobot-image-versions/<hash phiên>/`, ngoài workspace, dọn theo phiên hoặc TTL 24 giờ; route GET `/api/sessions/{key}/image-versions/{id}` chỉ phục vụ id hợp lệ của đúng phiên. **Lưu ý:** ảnh do `image_edit` sinh ra vẫn nằm trong thư mục artifact của tool sinh ảnh, không phải thư mục tạm; cần quyết định nếu muốn gom vào kho này.
- [x] Skill `image-region-edit` (`nanobot/skills/image-region-edit/SKILL.md`): 7 bước của đặc tả, báo cáo theo số vùng.
- [x] IM-12…14: **IM-12** kết quả là phiên bản mới (route liệt kê phiên bản theo ảnh gốc); so sánh trước/sau bằng thanh trượt, và "Mark up" quay lại vẽ mà không mất phiên bản. **IM-13** báo cáo theo vùng do agent gửi kèm `image_composite` / `image_version_save` (đạt, chưa đạt, một phần, kèm lý do), hiện cạnh từng ghi chú. **IM-14** "Gửi lại" chỉ nhắc các vùng chưa đạt; ghi chú vùng đã đạt bị khóa. Vùng đã đạt được khóa cả ghi chú lẫn hình học khi gửi lại (không kéo, không đổi kích thước, không xóa). 

### Test

- JSON schema validate.
- Mask size = original; tọa độ lệch ≤ 1 px khi hiển thị scale.
- Composite: pixel ngoài vùng (+ feather) identical.
- `render_text` tiếng Việt có dấu (fixture font).
- Không có code LLM trả box/mask.

### Cổng G3

- [ ] Sửa nhiều vùng một lần gửi trên Desktop local. **Chưa kiểm chứng:** không có trình duyệt hay Desktop trong môi trường làm việc; cần chạy thật trước khi đóng cổng.
- [~] Agent báo đạt/chưa đạt theo số vùng: có trong skill, chưa chạy thật với model.


### Kết quả Phase 9 (đo ngày 09/10/2026)

- **Phụ thuộc:** nhánh tạo từ `feat/desktop-roadmap-p8-editor-g2`, vì pane dùng workspace API của 7.1 và file editor đã có.
- **Thư viện:** `konva` 10.7.0 và `react-konva` 18.2.16 (ghim chính xác). Bản react-konva 19 cần React 19, repo đang dùng React 18. Konva 10.7.1 mới ra 4 ngày nên chưa dùng (quy tắc tối thiểu 2 tuần). Pillow khai báo trực tiếp trong `pyproject.toml`; trước đó đi qua dependency gián tiếp.
- **Bundle:** pane tải lazy, chunk khoảng 305 KB raw (khoảng 95 KB gzip); shell `index` tăng khoảng 1 KB.
- **Test:** `tests/coworker/test_image_review.py` 28 pass (gồm tẩy); `annotation-model.test.ts` 15 pass; `image-review-pane.test.tsx` 9 pass. Toàn bộ WebUI: 11 lỗi có sẵn, cộng một test theo thời gian (`image-gallery`, `LinearPanel`) chỉ fail khi chạy song song và pass khi chạy riêng. Pytest coworker/webui: 4 lỗi có sẵn.
- **Chưa kiểm chứng:** trình duyệt thật (vẽ, zoom, gửi); provider sinh ảnh thật với `image_edit`; agent thật làm theo skill; route ảnh phiên bản chưa có test HTTP riêng.
- **Cờ:** `coworker.image.enabled` tắt mặc định. Pane vẫn gửi được khi cờ tắt, nhưng agent sẽ không có tool để đọc chú thích; cần bật cờ trước khi dùng thật.
- **Chưa làm:** kiểm chứng trên trình duyệt; route liệt kê phiên bản chưa có test HTTP riêng.
- **IM-15 (cây phiên bản):** làm xong. Cây lấy từ các file `<tên>.vN.<ext>` cạnh ảnh gốc; mỗi file có cha là ảnh nguồn của nó, ghi trong `<tên>.vN.annotations.json`. Bấm một nút trên cây thì mở file đó trong preview. Sửa một phiên bản cũ sẽ ghi vào `<tên>.vN.edit.annotations.json` và tạo `vN+1` làm nhánh con của nó.
- **IM-16 (lưu vào workspace):** làm xong bằng mutation `session.image_version.save`, vì API ghi workspace hiện chỉ nhận text. Phiên bản được ghi thành `<tên>.vN.<ext>` với N lớn hơn mọi số đang có trong thư mục, kèm annotation là chính yêu cầu đã tạo ra nó. Không bao giờ ghi đè file đã có.

G4 (sticky header sequence, version tree đầy đủ, PV-08) **không** nằm trong roadmap lần này. IM-17 đã chuyển vào Phase 10.

---

## Phase 10 – BrowserSkill Mức 2 + pane ảnh IM-17 (9–14 ngày)

Làm **cuối**. Local desktop only. Không Docker/VPS.

### Trạng thái (09/10/2026)

- **Nguồn:** BrowserSkill được clone tại `C:\Users\Admin\Workspaces\BrowserSkill` (commit `7ba5ea9d`; commit `3f10983` của đặc tả có trong lịch sử). `bsk` đã build từ nguồn này (`cargo build -p bsk`, thư mục build nằm ngoài clone).
- **Đã làm (bước 1, phía nanobot), trong `nanobot/coworker/browser/`:** `runner.py` (gọi `bsk --json …`, đọc envelope lỗi, timeout và hủy đều kill tiến trình), `journal.py` (ghi và fsync trước khi start/stop; đọc lại được sau khi crash), `registry.py` (quyền sở hữu theo `(session key, agent)`, giới hạn 2/khóa và 5 toàn cục, prepare → start → claim, start không claim được thì dừng lại ngay, dọn cuối lượt, session giữ mở có hạn idle, khôi phục từ journal), `policy.py` (domain cấm kể cả subdomain, chỉ http/https, chế độ `interact` theo persona), `tools.py` (`browser_session`, `browser_page`, `browser_inspect`, `browser_interact`). Hook: `on_finally` dọn session của lượt (chạy cả khi hủy hoặc lỗi). Cấu hình `coworker.browser`, mặc định tắt.
- **Test:** `tests/coworker/browser/` — 27 test với `fake_bsk.py` (thứ tự prepare → start → claim, lỗi, timeout, giới hạn, cô lập sở hữu, journal, chính sách, tool) và 1 test hợp đồng thật chạy khi có `BSK_BIN`. Toàn bộ `tests/coworker`: 634 pass.
- **Đã kiểm chứng với bsk 0.3.2 thật (daemon cô lập, không có trình duyệt):**
  - `session request <token> --prepare` → `state: prepared`.
  - `session start --request-id <token>` không có extension → `no_browser_connected`, mất khoảng 30 giây vì bsk chờ extension, và request chuyển sang `closed`.
  - `session request <token> --cancel` và `session request <token>` đều trả `closed`.
  - Start không có `--request-id` chạy đồng bộ skill vào thư mục harness; nanobot luôn truyền `--request-id`.
  - Client không được tự khởi động daemon trong môi trường này (`BSK_AUTO_START=0`); thông báo lỗi của bsk chỉ dẫn chạy `bsk daemon start --foreground`.
- **Khác với đặc tả (đã ghi nhận):**
  - Đặc tả có `keepOpen` cho `session start`, nhưng bsk không có cờ này; nanobot tự giữ session mở theo cấu hình và idle limit.
  - Tên lệnh thật là `navigate-back`, `navigate-forward`, `get-html`, `scroll-to`… `browser_interact` dùng `click`, `hover`, `fill --value`, `press <key>`, `select --value`.
  - Đặc tả yêu cầu bảng `deny_domains` đầy đủ (ngân hàng, ví, cổng thanh toán); hiện chỉ có mail. Danh sách này cần lấy từ người dùng.
- **Đóng gói với Desktop (đã thử):** nanobot đọc đường dẫn bsk theo thứ tự: `coworker.browser.bskPath`, rồi `NANOBOT_BSK_PATH` (Desktop đặt khi khởi chạy sidecar, trỏ vào resources), rồi PATH. Daemon: `bsk daemon start` từ tiến trình con đã breakaway vẫn bị bsk từ chối trong môi trường làm việc (đang nằm trong Job Object của host, không breakaway được). Cần thử trên bản cài Desktop thật và trên terminal độc lập trước khi kết luận.
- **Chưa làm:** `browser_tabs` (kể cả `borrow`), `browser_assist` (kể cả `request-help` và help bridge), live view và `/browser log` (P4), đồng bộ skill `browser-skill` vào `nanobot/coworker/browser/skill/`, mục nhắc chạy nền cho idle sweep (hiện chạy lúc kết thúc lượt).
- **Chưa kiểm chứng:** extension Chrome thật, Agent Window, các cổng đo P0 (baseline 1–2 tuần), P1 (0 session treo trên bộ tiêm lỗi), P2 red-team, P3 (thông báo < 5 giây).

Cổng P1 chưa đạt vì chưa có bộ tiêm lỗi chạy với trình duyệt thật.

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

### Pane ảnh (IM-17) – P4

Phụ thuộc: **Phase 9 phải xong trước** (9.1, khung Konva). Đây là cùng một pane với Phase 9; chỉ khác hành động nút gửi.

- [ ] Pane ảnh hiển thị ảnh chụp từ `browser_*` và ảnh chụp màn hình UI, có zoom/pan. Chưa có khung Konva thì tạm dùng `ImageLightbox` (chỉ xem, không khoanh vùng).
- [ ] Với ảnh chụp, nút gửi tạo **tin góp ý** gồm ảnh, chú thích khoanh vùng (nếu có) và đường dẫn ảnh. Không tạo yêu cầu sửa ảnh.
- [x] **Quyết định (chốt):** ảnh chụp từ BrowserSkill **chỉ xem**, không sửa, không khoanh vùng. Lưu trong thư mục tạm riêng `tempfile.gettempdir()/nanobot-browser-screenshots/<session>/`, tách khỏi kho phiên bản ảnh do người dùng tạo ở Phase 9 (`nanobot-image-versions/`), và **không** vào workspace. Ephemeral: dọn theo session kết thúc, reboot hoặc TTL, giống kho Phase 9.
- [x] Đã xác nhận: với ảnh BrowserSkill, pane không có công cụ chỉnh sửa, và nút gửi "góp ý" chỉ áp dụng cho ảnh chụp màn hình UI. Nếu muốn gửi ảnh chụp browser cho agent thì đó là hành động riêng, chưa có trong plan.
- [ ] Khung hình live không đưa vào context model (đã ghi ở trên); chỉ ảnh được người dùng gửi mới vào tin.

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

> Cập nhật 09/10/2026: thứ tự giao diện trước (xem mục "Cập nhật 09/10/2026" đầu file) thay thế khuyến nghị trên và đưa Mermaid lên trước F3, F2, F1. Mốc A khi đó chỉ đạt sau khi F3, F2, F1 được làm lại; Mốc B (sau Phase 8) và Mốc C (sau Phase 9) giữ nguyên điều kiện.
)
