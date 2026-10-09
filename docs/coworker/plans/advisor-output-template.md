# Phác thảo: mẫu đầu ra của advisor và thay đổi ledger

Trạng thái: **đã triển khai sau hai cờ, mặc định tắt**; đã thử với model thật trên 12 ca (mục 10), chưa đo tác động lên kết quả công việc. Phạm vi: chất lượng nội dung advisor trả về
(định nghĩa hoàn thành, hướng dẫn thực hiện). Không đổi thời điểm hay quy trình consult.

## 1. Vì sao

Đo trên 191 lời khuyên thật (12 session): 100% có danh sách bước, 61% nêu lệnh kiểm chứng, nhưng chỉ
**9% có tiêu chí hoàn thành rõ ràng**. Prompt hiện chỉ xin "bước tiếp theo cụ thể", giới hạn khoảng 300 từ
và gọi đó là "điểm khởi đầu, không phải kế hoạch đầy đủ" (`ADVISOR_BREVITY`). Ledger hiện có
`must_fix`, `verify`, `do_not`, `pitfalls`, `next_checkpoint`; `verify` chỉ liệt kê điều còn mở sau
review, không đặt đích trước khi làm. Hệ quả: coordinator tự quyết lúc nào "xong", và done-gate
chỉ bắt được lỗi đã thấy, không bắt được phần chưa ai định nghĩa.

## 2. Mẫu đầu ra (phần văn bản coordinator đọc)

Chế độ coding, thứ tự cố định, mỗi phần có ngân sách:

```text
Verdict: proceed | revise | stop — một câu lý do.
Goal (hiểu của advisor): một câu mô tả việc cần làm. Nếu khác điều coordinator đang làm, nói rõ.

Definition of done (3–6 điều kiện, mỗi điều kiểm chứng được):
1. <hành vi hoặc trạng thái quan sát được> — kiểm bằng: <lệnh | file | quan sát>
...

How to (tối đa 8 bước có thứ tự):
1. <hành động> trên <file/lệnh> → kết quả mong đợi
...

Risks / Do not: <tối đa 4 mục>
Unverified: <khẳng định của executor mà advisor không kiểm chứng được>
```

Quy tắc nội dung (đưa vào system prompt của advisor):
- Definition of done mô tả **đích**, không mô tả cách làm; mỗi điều kiện phải có cách kiểm.
- How to ở mức bước và đích đến, **không viết sản phẩm hộ** (giữ câu "Do NOT produce the full deliverable").
- Thiếu thông tin để đặt một điều kiện: ghi vào Unverified hoặc nêu file cần đọc, không bịa.
- Bỏ giới hạn 300 từ chung; thay bằng ngân sách theo phần (tổng khoảng 400 từ, không tính JSON).

Chế độ brainstorm giữ nguyên (không có ledger, không áp dụng mẫu này).

## 3. Thay đổi ledger

Thêm bốn trường, giữ nguyên các trường cũ. Ledger cũ vẫn nạp được (trường vắng = rỗng).

```json
{
  "verdict": "proceed|revise|stop",
  "goal": "string|null",
  "done_when": [{"text": "string", "check": "string|null", "status": "open|met|unknown"}],
  "steps": ["string"],
  "must_fix": [], "verify": [], "do_not": [], "pitfalls": [],
  "unverified": ["string"],
  "next_checkpoint": "string|null"
}
```

Giới hạn: `goal` ≤ 200 ký tự; `done_when` ≤ 6 mục, `text` và `check` ≤ 160; `steps` ≤ 8 mục ≤ 200;
`unverified` ≤ 6 mục ≤ 200. Mục có `done_when` không phải object (chuỗi thuần) được chấp nhận và chuẩn hóa
thành `{text, check: null, status: "open"}`.

Phân vai để các danh sách không chồng nhau:
- `must_fix`: lỗi đã thấy trong thứ **đã có**.
- `verify`: thứ cần kiểm trước khi tin vào việc **đã làm**.
- `done_when`: tiêu chí hoàn thành của **cả nhiệm vụ**, nhìn về phía trước.
- `steps`: kế hoạch thực hiện; chỉ lưu và hiển thị, **không ghim** (nhanh lỗi thời).

### Quy tắc hợp nhất khác với `must_fix`

`must_fix` và `verify` được thay hoàn toàn mỗi lần (vắng mặt = đã đóng). `done_when` **không** làm vậy, vì
vắng mặt không có nghĩa là hoàn thành:
- Lần consult mới có `done_when` → thay danh sách, giữ `status` do advisor đặt (`met` khi bằng chứng cho thấy đã đạt).
- Lần consult mới **không** có `done_when` → giữ nguyên danh sách cũ, không xóa.
- `goal` cũng giữ nguyên nếu lần mới không nêu.
- Chỉ advisor đổi `status`; coordinator không tự đóng điều kiện (giống nguyên tắc "chỉ advisor đóng item").

## 4. Điểm chạm trong code

| File | Thay đổi |
|---|---|
| `advisor/consult.py` | `LEDGER_INSTRUCTION` thêm bốn trường và quy tắc phân vai; thêm `OUTPUT_TEMPLATE` nối vào system prompt khi bật cờ; thay `ADVISOR_BREVITY` bằng ngân sách theo phần khi bật cờ |
| `advisor/ledger.py` | `parse_ledger` chuẩn hóa `done_when`/`steps`/`goal`/`unverified`; `merge` theo quy tắc ở mục 3; `render` thêm phần Goal, Definition of done (đánh dấu `[x] [ ] [?]`), Steps, Unverified; `has_content` và `open_count` thêm tham số `include_done_when` |
| `advisor/state.py` | `apply_ledger` không đổi chữ ký; cần giữ `done_when` khi lần mới không có |
| `directives.py` | `advisor_commitments` ghim thêm Goal và các `done_when` chưa `met` (ưu tiên sau `must_fix`, vẫn nằm trong `COMMITMENTS_MAX_CHARS`) |
| `advisor/policy.py` | `done_gate_applies` tính thêm `done_when` chưa `met` **chỉ khi** bật cờ gate; `done_gate_text` nêu từng điều kiện và yêu cầu bằng chứng hoặc lý do |
| `advisor/tool.py`, `metrics_store/` | Ghi `has_done_when`, `n_done_when`, `n_steps`, `has_goal` để đo độ đầy đủ |
| `config.py` | Hai cờ độc lập, mặc định tắt (mục 5) |

## 5. Cờ cấu hình

| Cờ | Mặc định | Tác dụng |
|---|---|---|
| `advisor.output_template` | `False` | Dùng mẫu đầu ra và schema ledger mới, ghim `goal` và `done_when` |
| `advisor.done_gate_done_when` | `False` | Done-gate tính `done_when` chưa `met` (cần `output_template` bật) |

Tách hai cờ để đo riêng ảnh hưởng của nội dung (mẫu) và ảnh hưởng của cưỡng chế (gate).

## 6. Kiểm thử

- `test_advisor_ledger.py` (mới hoặc mở rộng): parse đủ trường; chuỗi thuần thành object; giới hạn độ dài và số mục; JSON hỏng không làm mất ledger cũ; ledger cũ (không có trường mới) vẫn nạp.
- Hợp nhất: vắng `done_when` thì giữ; có thì thay; `status: met` được giữ; `goal` giữ khi vắng.
- `render` và `advisor_commitments`: thứ tự ưu tiên, cắt đúng ngân sách, không ghim `steps`.
- Done-gate: chỉ tính `done_when` khi cờ gate bật; vẫn chỉ phát một lần mỗi run.
- Cờ tắt: prompt và hành vi y hệt hiện tại (test snapshot prompt).

## 7. Cách đo hiệu quả

1. **Offline, không tốn model:** parse thử mọi lời khuyên đã lưu (đường cơ sở: 9% có tiêu chí hoàn thành) và kiểm tra ledger cũ vẫn nạp được.
2. **Mẫu nhỏ, tốn model:** phát lại 10–15 lời gọi advisor đã lưu qua prompt mới. Đo: tỷ lệ có `done_when` hợp lệ, số bước, độ dài, và chấm theo rubric cố định hai câu hỏi: mỗi điều kiện có kiểm chứng được không, và how-to có thực hiện được mà không phải đoán không. Chi phí khoảng 10–15 lần gọi với transcript thật.
3. Chỉ sau đó mới cân nhắc đo end-to-end bằng eval.

## 8. Rủi ro và quyết định đã chọn (có thể đổi)

- **Lời khuyên dài hơn:** thêm khoảng 100–150 từ mỗi lần. Chấp nhận khi bật cờ; đo lại độ dài ở bước 7.2.
- **Advisor đặt tiêu chí sai hoặc quá chung:** `unknown` và `Unverified` là lối thoát; rubric ở bước 7.2 bắt riêng lỗi này.
- **Model yếu bỏ qua:** ghim `done_when` vào system prompt và done-gate (cờ riêng) là cơ chế duy nhất cưỡng chế; chưa tự chạy `check`.
- **Không tự chạy `check`:** việc harness chạy lệnh trong `check` để tự đóng điều kiện thuộc "ledger kiểm chứng được", để sau.
- **Quyết định đã chọn:** cờ mặc định tắt; `done_when` không bị xóa khi vắng mặt; gate cưỡng chế dưới cờ riêng; `steps` không ghim.
- **Liên hệ Phase C của `advisor-room-integration`:** mỗi `done_when` có thể thành `acceptance[]` khi ủy quyền cho teammate; chưa làm.

## 9. Đã triển khai: khác với phác thảo

- Hai cờ `advisor.output_template` và `advisor.done_gate_done_when` như thiết kế. Mặc định tắt: với cờ tắt, prompt,
  ledger và nội dung ghim không đổi (toàn bộ test cũ vẫn pass, kèm test render nguyên văn cho ledger cũ).
- **Độ đầy đủ được ghi vào lịch sử exchange của session (`shape`) và log, không vào `metrics_store`.** Bảng
  `advisor_consults` có cột cố định, thêm chỉ số cần migration; để sau nếu cần xem trên dashboard. `shape` đo trên
  *chính lời đáp* (trước khi hợp nhất), vì ledger đã hợp nhất sẽ che việc advisor quên nêu định nghĩa hoàn thành.
- `done_when` rỗng (`[]`) được coi như "không nhắc tới" chứ không phải xóa; chỉ một danh sách không rỗng mới thay thế.
- Mục có `status` thiếu hoặc không hợp lệ kế thừa trạng thái của mục cùng `text` ở lần trước, nếu không có thì `open`.
  `unknown` được tính là chưa đạt.
- Lời đáp trước (gồm `steps`) được đưa lại cho advisor trong mục "Open advisor ledger"; `steps` không bao giờ được ghim.
- `COMMITMENTS_MAX_CHARS` tăng từ 1500 lên 2000 để chứa Goal và các điều kiện chưa đạt.
- Chưa làm: chấm thử bằng model trên 10–15 lời gọi đã lưu (mục 7.2), tự chạy lệnh trong `check`, hiển thị cờ trong Settings
  (các cờ steering khác cũng chưa có trong Settings API/WebUI).

## 10. Thử với model thật (2026-10-08)

Cách làm: 12 lời gọi advisor thật đã lưu (7 session; chọn các ca có transcript ≤ 120k ký tự và ≥ 3 lời gọi công cụ
trước đó), phát lại hai lần với **cùng đầu vào**, chỉ khác cờ `output_template`; advisor `claude-sonnet-5-5`. Giám khảo
`claude-opus-5-5` chấm mù (thứ tự X/Y ngẫu nhiên) theo bốn tiêu chí 1–5. Tổng khoảng 0,69M token advisor và 0,07M token giám khảo.

| Chỉ số | Mẫu tắt | Mẫu bật |
|---|---|---|
| Có cụm "định nghĩa hoàn thành" trong lời khuyên | 0/12 | 12/12 |
| Ledger parse được; có `goal`; 3–6 `done_when`; ≥ 1 và ≤ 8 `steps` | (không có trường) | 12/12 ở cả bốn kiểm tra |
| Số `done_when` mỗi lời đáp (đều có `check`) | — | 4 đến 5 |
| Số từ phần văn bản (trung vị) | 325 | 487 (+50%) |
| Giám khảo: `dod` / `howto` / `grounded` / `useful` | 2,17 / 3,33 / 3,17 / 3,33 | 4,67 / 4,08 / 2,83 / 4,00 |
| Được chọn là tốt hơn | 1 | 11 |
| Khẳng định bị gắn cờ là bịa, trên 100 từ | 0,58 | 0,57 |

Diễn giải:
- Mẫu làm được điều nó nhắm tới: định nghĩa hoàn thành xuất hiện ở mọi lời đáp và how-to cụ thể hơn (+0,75), tuân thủ cấu trúc 12/12.
- Chi phí: thêm khoảng 160 từ mỗi lần consult.
- Tính có căn cứ **không cải thiện** (3,17 xuống 2,83). Số khẳng định bị gắn cờ tăng (23 lên 33) nhưng tỷ lệ theo độ dài gần như
  bằng nhau, nên phần lớn do lời khuyên dài hơn. Ca duy nhất giám khảo chọn nhánh đối chứng là một ca mẫu bật trích số dòng
  không có trong transcript và đánh giá sai một lỗi.

Hạn chế (quan trọng khi đọc số liệu):
- `dod` gần như chắc chắn thắng vì nhánh đối chứng không được yêu cầu nêu định nghĩa hoàn thành; chỉ số có ý nghĩa hơn là
  `howto`, `useful` và `grounded`.
- Giám khảo chỉ thấy phần cuối 6000 ký tự của transcript, nên nhiều cờ "bịa" có thể là dương tính giả; giám khảo cùng hãng với advisor;
  dấu hiệu cấu trúc (các đề mục) làm việc chấm mù không hoàn toàn mù.
- n = 12, một lần chạy, chọn lệch về ca nhỏ, trộn ca code và ca thảo luận; chưa có người chấm.
- Chưa đo điều quan trọng nhất: coordinator có làm việc tốt hơn (ít sửa lại, báo hoàn thành đúng hơn) khi nhận lời khuyên theo mẫu và
  khi `done_when` được ghim hay không.
