# Eval Phase 0 và Phase B: kết luận và trạng thái dừng

Ngày: 2026-10-08. Eval đã được dừng theo quyết định của người dùng vì lợi ích của advisor chưa rõ ràng
so với chi phí. Tài liệu này ghi lại số liệu, kết luận, hạn chế và cách chạy tiếp.

## 1. Kết luận

**Chưa có bằng chứng advisor cải thiện chất lượng một cách phân biệt được so với biến động giữa các run, và
chi phí tăng rõ ràng.** Đây là "lợi ích chưa rõ", không phải "advisor vô ích": dữ liệu chỉ phủ hai kịch bản,
3 run mỗi bên, với một judge duy nhất.

## 2. Số liệu (cùng cấu hình, runner `gemini-3.8-flash-tiered`, advisor `claude-sonnet-5-5`, `max_parallel = 1`)

Nhánh `off`: `coworker-eval-v4-advisor-off.json`. Nhánh `on`: `coworker-eval-v5-advisor-on.json` (sau Phase B). Các file nằm trong `docs/coworker/plans/archive/eval/` (xem README ở đó).

| Kịch bản | Nhánh | n | Điểm từng run | TB (sd) | Token TB | Thời gian TB | Lời gọi advisor thành công |
|---|---|---|---|---|---|---|---|
| crm-followup | off | 3 | 4.3, 4.3, 4.2 | 4.27 (0.05) | 121k | 143 giây | — |
| crm-followup | on | 3 | 4.3, 4.6, 4.6 | 4.50 (0.14) | 270k | 156 giây | 2, 3, 2 |
| nutritech-plan | off | 3 | 4.5, 4.4, 4.0 | 4.30 (0.22) | 364k | 517 giây | — |
| nutritech-plan | on | 1 (dừng) | 4.5 | — | 561k | 574 giây | 1 |

Chi phí advisor: token của chính model advisor chỉ 20–34k mỗi run (khoảng 10% tổng). Phần tăng còn lại đến
từ các lượt coordinator thêm sau lời khuyên, kể cả giao lại việc cho teammate. Vì vậy chi phí tăng khoảng
1,5 đến 2,2 lần không thể quy hết cho model advisor.

## 3. Vì sao chưa kết luận được

- `crm-followup`: điểm tăng 0,23 nhưng chỉ 3 run mỗi bên, điểm nhánh `off` sát trần thang, và sd của nhánh `on` lớn hơn.
- `nutritech-plan`: nhánh `on` chỉ có 1 run (4.5) nằm trong dải của nhánh `off` (4.0–4.5).
- Hai kịch bản mà advisor có nhiều cơ hội nhất (`edutech-course`, `presale-design`) không hoàn tất hoặc không ổn định
  ở cấu hình hiện tại, nên chưa đo được.
- Một judge duy nhất (`claude-opus-5-5`), không chấm lặp lại, không chấm mù (judge biết đang chấm gì).

## 4. Các phát hiện về hệ thống, độc lập với advisor

1. **Trước Phase B advisor không bao giờ được gọi trong luồng room.** Coordinator chỉ dùng `room_state`, `room_delegate`,
   `agents_list`, nên `work_total = 0` và nudge không kích hoạt; lượt review `[auto-room]` còn bị loại khỏi nudge.
   Các run `on` ở v4 vì vậy không khác nhánh `off`.
2. **Kịch bản nhiều chuyên viên chạy quá lâu ở cấu hình mặc định.** `edutech-course` (3 chuyên viên, tuần tự) mất
   18–22 phút và không hoàn tất trong ngân sách 900 giây. `presale-design` không ổn định (3.8, 1.8, 1.4; một run timeout).
3. **Provider không ổn định**: `MALFORMED_FUNCTION_CALL` và lỗi kết nối của `gemini-3.8-flash-tiered` làm tăng thời gian.
4. Lỗi trong `scheduler.clear_room` (xóa theo `session_key` thay vì `room_id`), đã sửa.

## 5. Thay đổi mã đã làm

- `scripts/coworker_eval.py`: settle hai giai đoạn (teammate, review), hủy room khi kết thúc run, judge gọi trực tiếp
  provider (không tool), đo token trong tiến trình, workspace tạm theo từng run, checkpoint JSONL và `--resume`,
  bảo vệ file baseline, đếm sự cố provider, đếm lời gọi advisor (`advisor_calls`, `advisor_ok`, `advisor_nudges`),
  `--room-timeout` (mặc định 900), `--review-timeout` (mặc định 600), `--preflight`.
- `nanobot/coworker/hook.py`, `advisor/policy.py`, `advisor/tool.py` (Phase B): nudge `room_review` một lần cho lượt review,
  bỏ từ chối "thiếu ngữ cảnh" ở lượt review, nội dung nudge riêng.
- `nanobot/coworker/room/scheduler.py`: sửa khóa trong `clear_room`.
- Test: `tests/coworker/eval/test_eval_harness.py`, `tests/coworker/test_hook.py`. `tests/coworker`: 532 passed, 3 skipped
  tại thời điểm cuối. Chưa commit.

Nudge `room_review` chỉ được kiểm chứng bằng test và quan sát hạn chế: trong các run `on` coordinator thường tự gọi
advisor trong lượt review, và có 1–2 nudge mỗi run ở `crm-followup`.

## 6. Nếu muốn quay lại

- Muốn biết advisor có tác động hay không mà không tốn nhiều run: đọc output advisor và báo cáo cuối của vài run
  `on` (tối thiểu `nutritech-plan` và `crm-followup`) và so với bản bàn giao. Dữ liệu đã nằm trong `final_output` và
  `specialist_outputs` của từng run.
- Muốn bằng chứng định lượng: cần nhiều run hơn (hiệu ứng khoảng 0,2 điểm với sd khoảng 0,15 cần vài chục run mỗi bên),
  judge lặp lại hoặc nhiều judge, và kịch bản khó hơn mà điểm `off` còn thấp. Chạy `nutritech-plan` nhánh `on` tiếp tục:
  `--resume` với cùng tham số và file `v5`.
- Phase A, C trong `docs/coworker/plans/advisor-room-integration.md` (evidence nhận biết loại tác vụ, advisor lập kế hoạch
  ủy quyền) chưa làm.

## 7. File liên quan

`docs/coworker/plans/archive/eval/`: `coworker-eval-v4-advisor-off.json`, `…v5-advisor-on.json` (và `.runs.jsonl`), các file `v2`, `v3`,
`smoke`, `check`, `phaseb-check` là dữ liệu trung gian; chỉ `v4-off` và `v5-on` được dùng ở bảng trên.
