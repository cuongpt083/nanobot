# Kết quả eval coworker (đã lưu trữ 2026-10-09)

Các file ở đây là đầu ra của `scripts/coworker_eval.py`. Kết luận và hạn chế nằm ở
`docs/coworker/tests/advisor-eval-conclusion.md`; lịch sử sửa harness ở `docs/coworker/tests/phase0-readiness.md`.
Mỗi kết quả có hai file: `*.json` (tổng hợp) và `*.json.runs.jsonl` (từng run, ghi ngay khi xong). Script từ chối ghi đè
`coworker-eval-baseline.json` (xem `PROTECTED_OUTPUTS`).

| File | Nội dung | Có dùng được không |
| --- | --- | --- |
| `coworker-eval-baseline.json` (+ `.log`) | Baseline v1: 7 kịch bản × 2 run, advisor bật | **Không tin được**: judge chấm tin nhắn bàn giao và chạy trong agent loop (parse lỗi 10/14); lượt review nhiều khả năng bị cắt (cả 12 run có ủy quyền đều có 0 lần sửa lại); số token có thể lẫn tiến trình khác vì dùng chung cơ sở dữ liệu (giả thuyết, chưa chứng minh) |
| `coworker-eval-v4-advisor-off.json` (+ runs) | Nhánh đối chứng (advisor tắt): 6 kịch bản × 3 run, harness đã sửa | **Dùng được**; `presale-design` không ổn định, `edutech-course` không có |
| `coworker-eval-v5-advisor-on.json.runs.jsonl` | Nhánh advisor bật sau Phase B, chỉ `crm-followup` (3) và `nutritech-plan` (1); bị dừng có chủ ý | Dùng được để so với v4 trên hai kịch bản đó; chưa có file tổng hợp vì chạy chưa xong |
| `coworker-eval-v4-advisor-current.json.runs.jsonl` | Nhánh advisor bật **trước** Phase B | **Không dùng**: advisor không được gọi lần nào, thực chất là nhánh tắt |
| `…v2-…`, `…v3-…`, `…smoke-on…`, `…check-edutech-off…`, `…phaseb-check…` | Lần chạy trung gian khi sửa harness (smoke 1 run, bị dừng, hoặc timeout do lỗi harness) | **Không dùng**; chỉ để truy vết |
| `agent-runtime-baseline-dryrun.json` | Đầu ra `--dry-run` (dữ liệu giả) | Không phải kết quả thật |

Chỉ bốn file đầu (baseline, v4-off, v5-on) đang được git theo dõi; các file trung gian còn lại chưa commit.
