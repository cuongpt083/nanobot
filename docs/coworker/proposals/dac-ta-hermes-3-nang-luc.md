# Đặc tả tính năng: Port 3 năng lực từ Hermes Agent vào nanobot fork

2026-10-06 · Cuong Fam

## Bối cảnh và nguyên tắc chung

Bản đặc tả này mô tả ba năng lực port từ Hermes Agent vào fork `cuongpt083/nanobot`, theo thứ tự ưu tiên F1 → F2 → F3. Mỗi tính năng đều được dựng trên code đã có của nhánh `develop` (commit `2d332c2`, ngày 2026-10-06), không viết lại từ đầu.

| Mã | Tính năng | Đã có trong fork | Khoảng trống cần lấp |
| --- | --- | --- | --- |
| F1 | Tự tạo skill sau tác vụ phức tạp | `SkillsLoader` đọc `workspace/skills/<name>/SKILL.md`; skill `skill-creator` có `init_skill.py`, `quick_validate.py`; hook `after_run` trong `coworker/hook.py`; Dream có git-backed diff | Không có trigger tự động, không có vòng đời draft → active → retired |
| F2 | Tìm session cũ + tóm tắt | Tool `search_sessions` / `read_session`; `WebuiSessionAccess.search` | Quét tuyến tính, khớp chuỗi con, chỉ 5 kết quả, không xếp hạng, không tóm tắt |
| F3 | Subagent cô lập, trả kết quả gọn | `AgentRuntime` cho guest (system prompt, toolset, thread riêng); `GUEST_OUTPUT_SCHEMA` (summary ≤ 1200 ký tự); `SubagentManager.spawn` | Brief cho guest nạp cả "Room so far" và user turns (tới 24.000 ký tự); `spawn` trả nguyên `final_content` về agent chính |

Nguyên tắc thiết kế áp dụng cho cả ba:

- **Merge-safe**: logic mới đặt trong `nanobot/coworker/` (gói con mới `learning/`, `recall/`, `delegate/`). Core chỉ nhận seam tối thiểu, mỗi seam ghi rõ ở từng tính năng.
- **Tắt được, mặc định an toàn**: mỗi tính năng có cờ `enabled` trong `CoworkerConfig`. F1 mặc định `mode: draft` (tạo nháp, không tự kích hoạt).
- **Model cho bước LLM phụ**: phản tư (F1) và tóm tắt (F2) dùng model mặc định của coordinator, không cấu hình preset riêng.
- **Đo được**: mọi sự kiện ghi vào `metrics_store`. Mỗi tính năng có kịch bản riêng trong `scripts/coworker_eval.py`, ngưỡng thành công là median quality +0.5 so với baseline.
- **Nội dung lịch sử là dữ liệu, không phải chỉ thị**: giữ `_UNTRUSTED_NOTICE` cho mọi thứ đọc lại từ session, skill nháp hoặc kết quả subagent.

## F1 — Tự động tạo skill sau tác vụ phức tạp

Sau mỗi lượt có từ 5 tool call trở lên và kết thúc thành công, một bộ phản tư chạy nền quyết định tạo skill mới, vá skill cũ hoặc bỏ qua. Kết quả luôn là bản nháp; chỉ khi người dùng duyệt (hoặc đạt ngưỡng dùng thành công ở chế độ `auto`) skill mới được kích hoạt.

### Mục tiêu và phạm vi

- Biến quy trình lặp lại (kịch bản sales, bài marketing theo khung, checklist review thiết kế) thành skill tái dùng, giảm số tool call và tăng độ nhất quán từ lần thứ 2 trở đi.
- Không phạm vi: tự sửa system prompt hay persona; tự học từ tác vụ thất bại hoặc bị hủy.

### Trigger (không tốn LLM)

Thêm `SkillLearningHook` chạy trong `after_run` của `coworker/hook.py`, sau `_drive_workflow`. Một lượt thành ứng viên khi thỏa cả bốn điều kiện:

1. `stop_reason` không thuộc `cancelled`, `error`, `max_iterations`.
2. Số tool call ≥ `min_tool_calls` (mặc định 5, theo Hermes).
3. Không phải lượt của Dream, cron hay automation (`automation_turns`).
4. Persona hiện tại không tắt học (`learning: off` trong `RoomAgentConfig`).

Tín hiệu bổ sung tăng điểm ưu tiên: người dùng sửa kết quả ở lượt kế tiếp, hoặc cùng persona đã làm tác vụ tương tự ≥ 2 lần trong 14 ngày (dò qua F2). Ứng viên được ghi vào hàng đợi `.coworker/learning/queue.jsonl`, không chặn phản hồi cho người dùng.

### Pipeline phản tư (chạy nền)

1. **Gom bằng chứng**: transcript lượt (đã cắt tool result dài), danh sách tool đã dùng, skill đã nạp, phản hồi của người dùng nếu có.
2. **Đối chiếu skill sẵn có**: lấy `build_skills_summary()` cùng top-3 skill gần nghĩa nhất (khớp tên/mô tả).
3. **Quyết định** bằng LLM, dùng model mặc định của coordinator, đầu ra JSON theo schema: `action` ∈ {`create`, `patch`, `skip`}, `skill_name`, `reason`, `confidence`.
4. **Soạn**: `create` sinh `SKILL.md` theo khung của `skill-creator`; `patch` sinh diff cho skill đã có, kèm số phiên bản mới.
5. **Kiểm tra**: chạy `quick_validate.py`; lọc bí mật (API key, token, email, số điện thoại) và dữ liệu khách hàng cụ thể; từ chối nếu skill chỉ mô tả lại một tác vụ một lần.
6. **Lưu nháp** vào `workspace/skills/_drafts/<name>/SKILL.md`, commit qua `GitStore` như Dream để có diff và hoàn tác.

### Định dạng và vòng đời skill

Frontmatter giữ chuẩn hiện tại (`name`, `description`) và thêm khối `nanobot.learning`:

```yaml
nanobot:
  learning:
    status: draft        # draft | active | retired
    version: 1
    origin_session: "webui:abc123"
    persona: "marketer"  # bắt buộc; agent chính là "main"
    created_at: 2026-10-06
    uses: 0
    success: 0
```

| Chuyển trạng thái | Điều kiện | Ai thực hiện |
| --- | --- | --- |
| draft → active | Người dùng duyệt trên WebUI/Desktop hoặc qua `/skills review`, hoặc ở `mode: auto` đạt `promote_after` lượt dùng thành công (mặc định 3) | Người dùng / hệ thống |
| active → active (v+1) | Phản tư đề xuất `patch` và được duyệt | Người dùng |
| active → retired | Không dùng trong `retire_after_days` (mặc định 60) hoặc tỉ lệ thành công < 50% sau ≥ 5 lượt | Hệ thống, báo trong `/skills review` |
| draft → xóa | Người dùng từ chối, hoặc nháp quá 14 ngày không duyệt | Người dùng / hệ thống |

Skill luôn thuộc về persona đã tạo ra nó và chỉ được nạp cho persona đó; không có skill dùng chung giữa các persona, kể cả với subagent trong F3. Agent chính được tính là persona `main`.

### Giao diện duyệt skill nháp

WebUI và Desktop app có trang **Skill** trong cài đặt coworker, dùng chung một component và một API. Lệnh `/skills review` vẫn giữ cho các kênh chat không có giao diện.

| Khu vực | Nội dung | Hành động |
| --- | --- | --- |
| Danh sách nháp | Tên, persona, loại (tạo mới / vá), ngày tạo, liên kết tới session gốc, độ tin cậy của phản tư, kết quả kiểm tra (validate, lọc bí mật) | Mở chi tiết; huy hiệu số nháp chờ duyệt trên thanh điều hướng |
| Chi tiết nháp | `SKILL.md` đã render; với loại vá, diff so với phiên bản đang active; lý do phản tư đưa ra | **Duyệt**, **Sửa rồi duyệt** (editor markdown, chạy lại validate khi lưu), **Từ chối** (kèm lý do tuỳ chọn) |
| Skill đang dùng | Theo từng persona: phiên bản, số lượt dùng, tỉ lệ thành công, lần dùng gần nhất; đánh dấu skill sắp bị retire tự động | **Retire**, **Khôi phục**, xem lịch sử phiên bản |

- API mới đặt cạnh `coworker/settings_api.py`, phục vụ cả WebUI lẫn Desktop.
- Mọi thao tác duyệt, sửa, retire đều commit qua `GitStore`, nên hoàn tác được.
- Lý do từ chối được ghi vào `metrics_store` để tinh chỉnh trigger và bộ lọc ở các bước trên.

### Cấu hình

```yaml
coworker:
  learning:
    enabled: true
    mode: draft            # off | draft | auto
    min_tool_calls: 5
    promote_after: 3
    retire_after_days: 60
    max_drafts_per_day: 5
    personas: ["marketer", "sales"]   # rỗng = mọi persona
```

Phản tư dùng model mặc định của coordinator, nên không có khoá `preset`.

### Seam vào core

- `SkillsLoader`: bỏ qua thư mục `_drafts`, skill `status: retired` và skill thuộc persona khác khi dựng summary (khoảng 15 dòng).
- Ghi nhận lượt dùng skill: phát sự kiện khi skill được nạp vào context, để cập nhật `uses`/`success`.

### Chỉ số và tiêu chí chấp nhận

- Tỉ lệ nháp được duyệt ≥ 40% (thấp hơn nghĩa là trigger quá ồn).
- Trên bộ tác vụ lặp lại, lần chạy thứ 3 có số tool call giảm ≥ 20% và quality không giảm so với lần 1.
- Chi phí phản tư ≤ 15% tổng token của lượt gốc (trung vị).

### Rủi ro

- **Skill rác, trùng lặp**: giới hạn `max_drafts_per_day`, bước đối chiếu skill cũ, và hạn 14 ngày cho nháp.
- **Rò rỉ dữ liệu khách hàng giữa các persona**: bộ lọc ở bước 5, và skill chỉ được nạp cho persona đã tạo ra nó.
- **Prompt injection qua transcript**: transcript chỉ là dữ liệu đầu vào cho phản tư; skill sinh ra luôn qua người dùng duyệt ở `mode: draft`.

## F2 — Tìm kiếm full-text trên session cũ, kèm LLM tóm tắt

Thay vòng quét tuyến tính hiện tại bằng một chỉ mục SQLite FTS5 cập nhật tăng dần, xếp hạng bằng BM25 kết hợp độ mới, và thêm bước LLM tóm tắt có cache. Tool `search_sessions` giữ nguyên tên và kiểu kết quả cũ để không phá prompt đang dùng.

### Hiện trạng cần thay

`WebuiSessionAccess.search` so khớp chuỗi con trên tiêu đề, sau đó mở từng file JSONL để tìm trong tin nhắn, dừng khi đủ 5 kết quả. Cách này không xếp hạng theo mức liên quan, chậm dần theo số session, và trả excerpt thô 360 ký tự khiến agent phải gọi thêm `read_session` nhiều lần.

### Chỉ mục

- **Vị trí**: `.coworker/recall/index.sqlite`, theo namespace workspace của `JsonlSessionStore`.
- **Bảng `messages_fts`** (FTS5, tokenizer `unicode61 remove_diacritics 2`): cột `content`, `title`; cột không chỉ mục `session_key`, `message_index`, `role`, `ts`, `persona`, `project`.
- **Bảng `trigram_fts`** (tuỳ chọn, tokenizer `trigram`): cho truy vấn chuỗi con, mã lỗi, tên hàm.
- **Nội dung đưa vào**: tin nhắn `user` và `assistant` ở dạng hiển thị; tool result chỉ lấy 1.000 ký tự đầu kèm tên tool. Bỏ qua system prompt, payload ảnh và các bản ghi provider state.
- **Bỏ khỏi chỉ mục**: session Dream (`dream_session_key`), session tạm của automation, session người dùng đánh dấu không tìm kiếm, thread riêng của guest (`.coworker/agents/<id>/threads/`) và session nội bộ của subagent. Chỉ session chính được index.

`remove_diacritics 2` cho phép truy vấn "tom tat" khớp "tóm tắt", quan trọng với tiếng Việt gõ không dấu trên điện thoại.

### Cập nhật chỉ mục

1. **Theo sự kiện**: sau `JsonlSessionStore.save`, đẩy `session_key` vào hàng đợi; worker nền chỉ index các tin nhắn có `message_index` mới hơn con trỏ đã lưu.
2. **Đối soát định kỳ** (mặc định 10 phút, và khi khởi động): so `mtime` và kích thước file với bảng `index_state`; file đổi bất thường (repair, migrate, archive) thì index lại toàn session.
3. **Xoá**: `delete` của store kéo theo xoá mọi dòng của session đó.

Seam vào core: một callback `on_session_saved` / `on_session_deleted` trong `SessionManager` (khoảng 15 dòng). Nếu không muốn đụng core, cơ chế đối soát định kỳ một mình vẫn đủ đúng, chỉ trễ hơn.

### Xếp hạng

Điểm cuối = BM25 (FTS5, trọng số `title` gấp 3 `content`) × hệ số độ mới `exp(-tuổi_ngày / 30)` × hệ số persona (1,5 nếu cùng persona đang chạy). Gộp theo session, giữ tối đa 3 đoạn khớp tốt nhất mỗi session.

### Tool `search_sessions` (mở rộng, tương thích ngược)

| Tham số | Kiểu | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| `query` | string | bắt buộc | Từ khoá, hỗ trợ cụm `"..."` và `OR` của FTS5 |
| `limit` | int 1–10 | 5 | Số session trả về |
| `since` | date | không | Chỉ tìm từ ngày này |
| `scope` | `all` \| `persona` \| `project` | `all` | Giới hạn theo persona hoặc project hiện tại |
| `summarize` | bool | `false` | Bật tóm tắt LLM cho từng kết quả và một câu trả lời tổng |

Kết quả giữ các trường cũ (`session_key`, `session_ref`, `title`, `updated_at`, `excerpts`) và thêm `score`, `summary` (≤ 400 ký tự mỗi session), `answer` (≤ 800 ký tự, chỉ khi `summarize`). Trường `notice` vẫn là `_UNTRUSTED_NOTICE`.

### Tóm tắt bằng LLM

- Đầu vào: truy vấn + tối đa 3 đoạn khớp của mỗi session, mỗi đoạn mở rộng ±2 tin nhắn, tổng ≤ 12.000 ký tự.
- Dùng model mặc định của coordinator; yêu cầu trích dẫn `message_index` cho mỗi ý để agent có thể `read_session` đúng chỗ.
- Cache theo khoá `(session_key, số tin nhắn đã index, hash(query))` trong bảng `summary_cache`, TTL 7 ngày.
- Không tóm tắt khi kết quả không vượt ngưỡng điểm tối thiểu; trả về "không tìm thấy" thay vì tóm tắt nội dung không liên quan.

### Cấu hình

```yaml
coworker:
  recall:
    enabled: true
    reconcile_minutes: 10
    recency_half_life_days: 30
    trigram: false
    summary_cache_days: 7
    exclude_personas: []
```

### Chỉ số và tiêu chí chấp nhận

- Recall@5 ≥ 0,8 trên bộ 30 truy vấn có nhãn (gồm truy vấn tiếng Việt không dấu và tên kỹ thuật tiếng Anh).
- Độ trễ p95 không tóm tắt < 200 ms trên 10.000 tin nhắn; có tóm tắt < 6 s khi cache miss.
- Số lần gọi `read_session` sau mỗi `search_sessions` giảm ≥ 30% so với hiện tại.

### Rủi ro

- **Chỉ mục lệch với file sau repair/migrate**: đối soát theo `mtime` + kích thước, và lệnh `/recall reindex`.
- **Lộ nội dung giữa các persona**: `scope` mặc định của guest là `persona`; agent chính mới được `all`.
- **Injection qua nội dung cũ**: giữ `_UNTRUSTED_NOTICE`, và prompt tóm tắt yêu cầu bỏ qua mọi chỉ thị trong đoạn trích.

## F3 — Subagent có context cô lập, trả kết quả gọn về agent chính

Mỗi lần giao việc, subagent chỉ nhận một **brief** tường minh do agent chính soạn, và chỉ trả về một **envelope** có cấu trúc (≤ 1.500 ký tự). Transcript đầy đủ được lưu thành artifact để agent chính đọc thêm khi cần. Áp dụng cho cả guest trong room (`AgentRuntime`) lẫn `spawn` của core.

### Hiện trạng cần thay

- `_task_message` nạp mặc định "Recent user turns" và "Room so far" (tới 24.000 ký tự). Guest nhìn thấy gần như cả cuộc hội thoại, nên persona dễ trôi khỏi vai trò và tốn token.
- `GuestResult` có contract (`summary` ≤ 1.200 ký tự), nhưng room vẫn ghi `guest.text` đầy đủ vào transcript.
- `SubagentManager._announce_result` đưa nguyên `final_content` vào session chính qua `subagent_announce.md`, không giới hạn độ dài.

Guest dùng coding backend (`backend: pi`) nằm ngoài phạm vi F3: backend này không còn được duy trì và sẽ bị gỡ bỏ, nên không áp dụng brief hay envelope.

### Brief (đầu vào)

| Trường | Bắt buộc | Nội dung |
| --- | --- | --- |
| `goal` | có | Mục tiêu một câu, đo được |
| `deliverable` | có | Dạng đầu ra mong muốn (bảng so sánh, đoạn code, 3 phương án…) |
| `context` | không | Đoạn ngữ cảnh agent chính chọn lọc, ≤ 4.000 ký tự |
| `context_keys` | không | Khoá shared state cần đọc (đã có trong `Delegation`) |
| `inputs` | không | Envelope của các subagent chạy trước (không phải text đầy đủ) |
| `constraints` | không | Ràng buộc: ngôn ngữ, giới hạn phạm vi, những gì không được làm |
| `budget` | không | `max_iterations`, `max_tokens`, `timeout_s`; mặc định theo persona |

Các trường này mở rộng `Delegation` hiện có (đã có `task`, `context`, `context_keys`, `after`, `deliverable`). Phần còn lại của context subagent chỉ gồm system prompt của persona và thread riêng của persona (nếu `memory` ≠ `none`).

Thêm `room.context_policy` để chọn mức chia sẻ: `brief` (chỉ brief), `brief+user` (thêm tối đa 2 user turn gần nhất, mặc định), `full` (hành vi hiện tại, để so sánh khi eval).

### Envelope (đầu ra)

Mở rộng `GUEST_OUTPUT_SCHEMA`, giữ tương thích các trường cũ:

```json
{
  "status": "done | partial | blocked | failed",
  "summary": "≤ 600 ký tự, câu đầu là kết luận",
  "key_points": ["≤ 5 ý, mỗi ý ≤ 160 ký tự"],
  "artifacts": ["đường dẫn file đã tạo hoặc sửa"],
  "open_questions": ["điều cần agent chính hoặc người dùng quyết"],
  "confidence": "high | medium | low",
  "transcript_ref": "delegation/<task_id>"
}
```

Hệ thống tự điền `transcript_ref`, `tools_used`, `usage` và `stop_reason`; subagent không cần viết. Khi contract hỏng, giữ cơ chế `contract_repair_message` hiện có (một lần sửa), sau đó tự sinh envelope `status: partial`, `confidence: low` từ 600 ký tự đầu của câu trả lời.

### Luồng xử lý

1. Agent chính gọi `delegate` (room) hoặc `spawn` (core) với brief.
2. Runtime kiểm tra brief: thiếu `goal` hoặc `deliverable` thì trả lỗi ngay để agent chính soạn lại, không chạy subagent.
3. Subagent chạy với context cô lập và ngân sách riêng. Hết `max_iterations` hoặc `max_tokens` thì bắt buộc kết thúc bằng envelope `status: partial`.
4. Runtime lưu transcript đầy đủ vào `.coworker/rooms/<room>/artifacts/<agent>/delegation/<task_id>.md`.
5. Agent chính chỉ nhận envelope. Room transcript ghi `summary` + `key_points` thay cho `guest.text`.
6. Cần thêm chi tiết, agent chính gọi tool mới `read_delegation(task_id, query?)` để lấy đoạn transcript liên quan (tối đa 4.000 ký tự mỗi lần).

### Seam vào core

- `SubagentManager`: thêm tham số `result_formatter` (mặc định giữ hành vi cũ). Coworker đăng ký formatter dựng envelope và lưu transcript (khoảng 20 dòng).
- `subagent_announce.md`: thêm nhánh hiển thị envelope khi có.

### Cấu hình

```yaml
coworker:
  room:
    context_policy: brief+user   # brief | brief+user | full
    envelope_max_chars: 1500
  agents:
    - id: architect
      budget: { max_iterations: 40, max_tokens: 60000, timeout_s: 900 }
```

### Chỉ số và tiêu chí chấp nhận

- Token đầu vào trung vị của mỗi lượt guest giảm ≥ 40% so với `context_policy: full`, quality không giảm.
- Token mà agent chính tiêu thụ cho kết quả delegation giảm ≥ 60%.
- Tỉ lệ envelope hợp lệ ngay lần đầu ≥ 90%; tỉ lệ `read_delegation` được gọi ≤ 30% số delegation (cao hơn nghĩa là envelope thiếu thông tin).
- Đạt ngưỡng chung: median quality +0.5 so với baseline trên bộ tác vụ persona.

### Rủi ro

- **Brief quá mỏng, subagent thiếu ngữ cảnh**: kiểm tra brief ở bước 2; `brief+user` làm mặc định; theo dõi tỉ lệ `status: blocked`.
- **Mất chi tiết quan trọng trong envelope**: transcript luôn lưu đủ và `read_delegation` truy cập được.
- **Chi phí đọc lại**: nếu `read_delegation` bị gọi quá nhiều, tăng `key_points` hoặc nới `envelope_max_chars` trước khi nới context.

## Eval, lộ trình và quyết định

Triển khai theo đúng thứ tự ưu tiên F1 → F2 → F3, mỗi phase có cổng eval riêng; phase sau chỉ bắt đầu khi phase trước qua cổng hoặc đã có quyết định dừng rõ ràng.

### Bộ eval bổ sung cho `scripts/coworker_eval.py`

| Bộ | Dùng cho | Thiết kế | Đo |
| --- | --- | --- | --- |
| `repeat_tasks` | F1 | 8 tác vụ marketing/sales, mỗi tác vụ chạy 4 lần với biến thể đầu vào | Quality, tool call, token theo từng lần chạy |
| `recall_queries` | F2 | 30 truy vấn có nhãn session đúng, gồm tiếng Việt không dấu và thuật ngữ tiếng Anh | Recall@5, độ trễ p95, số lần gọi `read_session` |
| `persona_delegation` | F3 | 10 tác vụ cần 2–3 persona (brainstorm → system design → marketing) | Quality, token guest, token agent chính, tỉ lệ envelope hợp lệ |

Mỗi bộ chạy ở hai cấu hình: tính năng tắt (baseline) và bật. Quality chấm bằng LLM-as-a-judge hiện có; ngưỡng chung là median +0.5.

### Lộ trình

1. **Phase 0 — Baseline**: chạy ba bộ eval trên `develop` hiện tại, lưu kết quả vào `metrics_store`. Cổng: có số liệu baseline ổn định qua 2 lần chạy.
2. **Phase 1 — F1 ở `mode: draft`**: trigger, pipeline phản tư, giao diện duyệt skill nháp trên WebUI và Desktop, lệnh `/skills review`, seam `SkillsLoader`. Tín hiệu "tác vụ tương tự" tạm dùng khớp tên tool, chưa dùng F2. Cổng: tỉ lệ nháp được duyệt ≥ 40% và lần chạy thứ 3 giảm ≥ 20% tool call.
3. **Phase 2 — F2**: chỉ mục FTS5, đối soát, tool `search_sessions` mở rộng, tóm tắt có cache. Sau đó nối F1 sang dùng F2 để dò tác vụ tương tự. Cổng: Recall@5 ≥ 0,8, p95 < 200 ms.
4. **Phase 3 — F3**: brief, envelope, `context_policy`, `read_delegation`, seam `result_formatter`. Cổng: token guest giảm ≥ 40% và median quality +0.5 trên `persona_delegation`.
5. **Phase 4 — Bật `mode: auto` cho F1 (tuỳ chọn)**: chỉ khi tỉ lệ duyệt nháp duy trì ≥ 60% trong 4 tuần.

Phụ thuộc cần lưu ý: F1 hoạt động độc lập nhưng tốt hơn khi có F2; F3 độc lập với cả hai.

### Quyết định đã chốt

| Câu hỏi | Quyết định | Phản ánh ở mục |
| --- | --- | --- |
| Skill do F1 sinh có chia sẻ cho persona khác hoặc subagent F3? | Không; chỉ dùng cho persona đã tạo ra nó | F1: định dạng và vòng đời |
| F2 có index thread riêng của guest? | Không; chỉ index session chính | F2: chỉ mục |
| Model cho phản tư (F1) và tóm tắt (F2) | Model mặc định của coordinator | Nguyên tắc chung, F1, F2 |
| Coding backend Pi có áp dụng envelope F3? | Ngoài phạm vi; Pi không còn được duy trì và sẽ bị gỡ bỏ | F3: hiện trạng |
| Giao diện duyệt skill nháp | Có, trên WebUI và Desktop app | F1: giao diện duyệt skill nháp |
