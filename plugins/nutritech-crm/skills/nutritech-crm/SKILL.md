---
name: nutritech-crm
description: "Comprehensive NutriTech CRM assistant for coaches: customer lookup, Bioclock check-in logging, meal calculations, task management, and communication scripts."
metadata: {"nanobot":{"emoji":"🥗","category":"Healthcare & CRM"}}
---

# NutriTech CRM Coaching Skill

Hướng dẫn quy trình cho AI Agent để kết nối, truy vấn dữ liệu và hỗ trợ Huấn luyện viên Dinh dưỡng (Coach) thông qua máy chủ MCP `nutritech-crm`.

## 1. Tìm kiếm và Nhận diện Khách hàng

Trước khi thực hiện bất kỳ hành động nào (check-in, tra cứu thực đơn, xem tiến độ), luôn xác định danh tính khách hàng:

1. **Công cụ sử dụng:** `mcp_nutritech-crm_customer_list`
2. **Tham số tìm kiếm:**
   - `search`: Họ tên tiếng Việt (có dấu hoặc không dấu) hoặc từ khóa.
   - `phone`: Số điện thoại của khách hàng (ví dụ: `0912345678`).
   - `birthDate`: Ngày sinh định dạng `YYYY-MM-DD` hoặc `DD/MM/YYYY`.
3. **Quy tắc:**
   - Nếu tìm thấy 1 khách hàng: Sử dụng `customerId` đó để tiếp tục quy trình.
   - Nếu có nhiều khách hàng trùng tên: Liệt kê danh sách kèm Số điện thoại / Mã khách hàng để người dùng xác nhận.
   - Nếu không tìm thấy: Nhắc người dùng kiểm tra lại thông tin hoặc gợi ý thêm Lead/Khách hàng mới trên CRM.

## 2. Ghi nhận Nhật ký Sức khỏe & Điểm Bioclock (Check-in)

Hàng ngày, hội viên gửi các chỉ số sinh hoạt. Agent cần trích xuất và ghi nhận qua MCP:

1. **Công cụ sử dụng:** `mcp_nutritech-crm_customer_log_checkin`
2. **Các chỉ số sinh hoạt chính (Bioclock Score):**
   - `customerId` (bắt buộc): ID khách hàng.
   - `date`: Ngày check-in (mặc định hôm nay `YYYY-MM-DD`).
   - `waterCups`: Số cốc nước đã uống (mỗi cốc tương đương 250ml. Nếu người dùng nhập 2L $\rightarrow$ quy đổi thành 8 cốc).
   - `mealsLogged`: Số bữa ăn đúng cấu trúc đã thực hiện (thang điểm 0 - 5 bữa).
   - `exerciseMinutes`: Số phút tập luyện/vận động trong ngày.
   - `lessonCompleted`: Trạng thái học bài dinh dưỡng trong ngày (`1` nếu đã học, `0` nếu chưa).
3. **Phản hồi:**
   - Thông báo tổng điểm Bioclock đạt được trên thang điểm 100.
   - Nhắc nhở các mục còn thiếu (ví dụ: chưa đủ lượng nước, cần bổ sung bữa ăn phụ).

## 3. Tra cứu Calo kỳ diệu & Cấu trúc 5 bữa ăn (Meal Planning)

1. **Công cụ sử dụng:** `mcp_nutritech-crm_customer_get_profile`
2. **Dữ liệu phân tích:**
   - `magicCalories`: Mức Calo kỳ diệu được cá nhân hóa cho hội viên.
   - `targetWaterLiters`: Mục tiêu lượng nước tối thiểu trong ngày (0.4L - 0.6L / 10kg trọng lượng).
   - `packageTier` & `program`: Gói dinh dưỡng (ví dụ: `co_nuoc_mo`, `dinh_duong_te_bao`).
3. **Cấu trúc 5 bữa ăn tiêu chuẩn:**
   - **Bữa 1 (Sáng 06:30 - 07:30):** Bữa ăn lành mạnh F1 + Protein (khoảng 200 - 250 kcal, giàu đạm thực vật).
   - **Bữa 2 (Phụ sáng 09:30):** Trái cây ít ngọt, sữa chua không đường hoặc trà thảo mộc.
   - **Bữa 3 (Trưa 11:30 - 12:30):** Cơm gạo lứt/khoai lang, ức gà/cá trắng, rau xanh lá đậm.
   - **Bữa 4 (Phụ chiều 15:30 - 16:00):** Đạm tinh chế / 1 ly F1 để chống hạ đường huyết lúc xế chiều.
   - **Bữa 5 (Tối 18:30 - 19:30):** Nhẹ nhàng, dễ tiêu, nhiều chất xơ, hạn chế tinh bột nhanh.

## 4. Quản lý Nhiệm vụ Chăm sóc Hàng ngày của Coach

1. **Xem nhiệm vụ hôm nay:** `mcp_nutritech-crm_task_list_today`
2. **Xem nhiệm vụ quá hạn:** `mcp_nutritech-crm_task_get_overdue`
3. **Hoàn thành nhiệm vụ:** `mcp_nutritech-crm_task_complete`
4. **Phân loại hành động theo chu kỳ chăm sóc:**
   - *Ngày 1, 3, 7, 10, 14, 21:* Các mốc vàng kiểm tra cân nặng và điều chỉnh thực đơn.
   - *Nhiệm vụ sinh nhật:* Chúc mừng và tặng quà/voucher cho hội viên.

## 5. Kịch bản Tư vấn & Xử lý Tình huống (Talking Points)

Khi Coach cần hướng dẫn hoặc hỗ trợ xử lý từ chối của hội viên:

1. **Công cụ sử dụng:** `mcp_nutritech-crm_skill_get` (ví dụ: `name: "objection-handling"`).
2. **Cấu trúc kịch bản 3 bước chuẩn mực:**
   - **Bước 1 (Đồng cảm & Khơi gợi):** Lắng nghe khó khăn của khách hàng, ghi nhận cảm xúc.
   - **Bước 2 (Khoa học & Đơn giản):** Giải thích nguyên lý cơ chế cơ thể ngắn gọn, dễ hiểu, không dùng thuật ngữ quá phức tạp.
   - **Bước 3 (Hành động cụ thể):** Đưa ra 1-2 hành động nhỏ hội viên có thể thực hiện ngay hôm nay.
