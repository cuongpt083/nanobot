# Phase 0: kết quả rà soát độ sẵn sàng của harness eval

Ngày rà soát: 2026-10-08. Chưa chạy eval nào (không gọi LLM). Thay thế phần "Still open"
của `eval-v2-resume-notes.md`; kế hoạch gốc: `docs/coworker/plans/advisor-room-integration.md` (mục 4).

## 1. Kết luận

Harness **đã sẵn sàng về mặt code và kiểm thử offline**. Còn lại một bước không thể kiểm
chứng mà không tốn token: một lần chạy thử nhỏ (smoke) để xác nhận các sửa lỗi trên model
thật. Chỉ chạy đầy đủ khi smoke đạt các tiêu chí ở mục 4.

Bằng chứng offline: `pytest tests/coworker` 527 passed, 3 skipped; `ruff` sạch; `--preflight`
OK cho cả hai nhánh (`--advisor-preset claude-sonnet-5-5` và `off`) trên cấu hình thật.

## 2. Lỗi tìm thấy trong harness (đã sửa)

| # | Vấn đề | Bằng chứng | Cách sửa |
|---|---|---|---|
| 1 | Chờ "settled" chỉ nhìn room, không tính lượt review `[auto-room]` của coordinator. Lượt này được inject qua bus sau khi room task đã xong, nên harness hủy `loop_task` trước khi review chạy | Cả 12 run baseline có ủy quyền đều có `revision_count = 0` (2 run persona-nutri không ủy quyền); test mới `test_settle_waits_for_a_slow_review_turn` tái hiện: chờ chỉ theo room trả về trước báo cáo cuối | `wait_room_settled(extra_busy, quiet_period)` + `turn_pending()` (cờ `turn_running_since` và hàng đợi bus), quiet 3s |
| 2 | Judge chấm tin nhắn bàn giao của lượt đầu, không phải báo cáo cuối của coordinator | `transcript = result.content` chỉ lấy lượt đầu | Thu `final_output` (tin nhắn assistant cuối) và đưa vào prompt judge cùng bài của specialist |
| 3 | Judge chạy trong `AgentLoop` đầy đủ, gọi được tool `advisor` | `eval3.err` ghi lại judge gọi `advisor` | `_judge_call`: gọi thẳng provider, không tool, system prompt riêng, thử lại một lần, lỗi thì ghi `judge_error` (không mặc định 3.0) |
| 4 | Token đo bằng chênh lệch trong `llm_usage.sqlite3` dùng chung với mọi tiến trình, không có cột session; gateway NextTutorBot đang chạy cùng lúc. Advisor và teammate dùng provider từ `snapshot_loader` nên không được gắn observer | Bảng `llm_calls` không có session; chỉ `loop.provider` được gắn observer | `UsageMeter` trong tiến trình, gắn cho cả provider của snapshot; lưu `tokens_by_model` để tách chi phí advisor |
| 5 | Eval chạy trong workspace và thư mục session thật của bạn | `~/.nanobot/sessions/a6003968…` chứa toàn bộ session `eval:*` và `eval:judge:*` cũ | Workspace tạm theo từng run; dọn thư mục session mồ côi (chỉ khi file `.workspace` khớp đúng thư mục tạm) |
| 6 | Kết quả chỉ ghi ở cuối: bị dừng giữa chừng là mất hết (xảy ra với lần v2 đầu). Một run lỗi làm hỏng cả đợt. Stdout không flush khi chuyển hướng | `docs/coworker/tests/eval-v2-resume-notes.md` | `RunLog` JSONL fsync sau mỗi run, `--resume` (khóa theo cấu hình và hash kịch bản), cô lập lỗi từng run, `line_buffering` |
| 7 | Đường ra mặc định là `agent-runtime-baseline.json` (có thể ghi đè baseline) | Ghi chú v2: "Never use the default --output" | Live run bắt buộc `--output`, từ chối file baseline được bảo vệ và file đã tồn tại (trừ `--resume`/`--force`) |
| 8 | Lỗi trong chính bản sửa: `MessageBus.inbound_size` là property, không phải hàm | Test mới bắt được `TypeError` | Đã sửa; test dùng chung `turn_pending` |

Ngoài ra: metadata có thêm `git_dirty`, cấu hình advisor hiệu lực, `label`, `workspace_mode`;
tóm tắt có `judge_error_total`, `timed_out_total`, `review_incomplete_total`.

## 3. Quy trình chạy

```bash
# 0) Không tốn token
uv run --no-sync pytest tests/coworker/eval -q
uv run --no-sync python -m scripts.coworker_eval --preflight --advisor-preset claude-sonnet-5-5

# 1) Smoke: 1 kịch bản có ủy quyền, 1 run, nhánh advisor bật (tốn token, nhỏ)
uv run --no-sync python -m scripts.coworker_eval -s crm-followup -r 1 \
  --advisor-preset claude-sonnet-5-5 --label smoke-on --keep-workspace \
  -o docs/coworker/plans/archive/eval/coworker-eval-smoke-on.json

# 2) Chỉ khi smoke đạt (mục 4): hai nhánh, 3 run mỗi kịch bản
uv run --no-sync python -m scripts.coworker_eval -r 3 --advisor-preset off \
  --label advisor-off -o docs/coworker/plans/archive/eval/coworker-eval-v2-advisor-off.json
uv run --no-sync python -m scripts.coworker_eval -r 3 --advisor-preset claude-sonnet-5-5 \
  --label advisor-current -o docs/coworker/plans/archive/eval/coworker-eval-v2-advisor-current.json
```

Khi chạy dài: dùng `Start-Process`, chuyển hướng **cả stdout và stderr** ra file, kiểm tra
tiến độ bằng lệnh riêng (không dùng lệnh `exec` có sleep dài, hết hạn ở 90 giây). Bị dừng thì
chạy lại đúng lệnh cũ kèm `--resume`; các run đã xong được dùng lại.

## 4. Tiêu chí đạt của smoke (go/no-go)

Đọc `coworker-eval-smoke-on.json` và `…smoke-on.json.runs.jsonl`:

| Kiểm tra | Mong đợi | Nếu sai |
|---|---|---|
| `summary.judge_error_total` | 0 | Judge vẫn lỗi: xem `judge_reasoning`/`judge_error`, chưa chạy đầy đủ |
| `review_injected` và `review_completed` của run có ủy quyền | Cả hai `true` | Lượt review vẫn bị cắt: tăng `--room-timeout` hoặc xem log, chưa chạy đầy đủ |
| `revision_count` | Có thể > 0 ở một số run (chỉ là tín hiệu, không bắt buộc) | — |
| `final_output` | Khác `content` (bản báo cáo sau review) | Judge vẫn chấm tin nhắn bàn giao |
| `tokens_by_model` | Có khóa của model advisor (`claude-sonnet-5-5`) ngoài model runner; tổng khớp `total_tokens` | Chi phí advisor chưa được đo |
| `timed_out` | `false` | Nếu `true`, tăng `--room-timeout` rồi chạy lại smoke |
| `~/.nanobot/sessions/a6003968…` | Không có file `eval:*` mới | Cô lập chưa hiệu lực |
| `git status` | Không có file mới do agent tạo ra trong repo | Workspace chưa cô lập |
| `--keep-workspace` | Thư mục tạm (đường dẫn trong `workspace`) chứa artifact của specialist ở `.coworker/rooms/…` | Ghi nhận vị trí artifact (còn mở ở findings #7) |
| Nhánh `off` (chạy thêm một smoke nếu muốn) | `tokens_by_model` không có model advisor | Nhánh đối chứng chưa thực sự tắt advisor |

Sau smoke, xóa thư mục tạm giữ lại bằng `--keep-workspace` (đường dẫn ghi trong JSON) và các
file `…smoke-*.json*` nếu không cần.

## 5. Chi phí và thời gian (ước lượng từ baseline cũ)

Baseline cũ: trung bình khoảng 150 giây mỗi run, khoảng 0,9 triệu token mỗi run (số token cũ
chưa đối chiếu được, xem mục 2 #4). 7 kịch bản × 3 run = 21 run mỗi nhánh, hai nhánh = 42 run,
chạy tuần tự (cấu hình coworker dùng override toàn cục nên không chạy song song được).
Dự kiến 2 đến 3 giờ cho cả hai nhánh. Lượt review nay hoàn tất nên mỗi run có thể dài hơn
một đến vài phút so với trước. Số token mới sẽ khác baseline cũ vì đã đo cả advisor và teammate.

## 6. Chưa kiểm chứng được nếu không chạy thật

- Workspace tạm cho `AgentLoop` đã được dựng thử offline (workspace khớp, observer gắn), nhưng
  chưa có một lượt agent thật trong đó (kịch bản persona có thể cần file mẫu trong workspace).
- Judge trực tiếp trên preset `claude-opus-5-5` với OAuth patcher: preset đã resolve, chưa gọi.
- Nguyên nhân lời khuyên advisor rò vào `content` (findings #4) vẫn chưa được điều tra; harness
  nay chấm báo cáo cuối nên ảnh hưởng của nó sẽ hiện rõ hơn trong số liệu.
- Kịch bản `persona-nutri` không có `expected_agents` (cố ý), routing accuracy luôn 1.0.
- Các cờ `room_review`/`room_planning` (Phase B/C) chưa tồn tại; nhánh "room" của A/B sẽ thêm sau.
