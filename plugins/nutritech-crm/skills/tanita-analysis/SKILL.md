---
name: tanita-analysis
description: "Expert body composition analyzer for Tanita 9-metric scans: weight, body fat %, muscle mass, body water %, visceral fat, bone mass, BMR/RMR, metabolic age, and physique rating."
metadata: {"nanobot":{"emoji":"⚖️","category":"Healthcare & CRM"}}
---

# Tanita 9-Metric Body Composition Analysis Skill

Hướng dẫn AI Agent đọc hiểu, đánh giá và lập báo cáo tư vấn chuyên sâu dựa trên 9 chỉ số quét cơ thể Tanita từ máy chủ MCP `nutritech-crm`.

## 1. Phương thức truy xuất chỉ số Tanita

1. **Công cụ MCP:** `mcp_nutritech-crm_customer_get_tanita`
2. **Tham số:** `customerId` (lấy từ bước nhận diện khách hàng qua `customer_list`).
3. **Dữ liệu trả về:**
   - `weightKg`: Cân nặng hiện tại (kg).
   - `bodyFatPct`: Tỷ lệ phần trăm mỡ cơ thể (%).
   - `muscleMassKg`: Khối lượng cơ bắp (kg).
   - `waterPct`: Tỷ lệ phần trăm nước trong cơ thể (%).
   - `visceralFat`: Chỉ số mỡ nội tạng (thang điểm 1 - 59).
   - `boneMassKg`: Khối lượng khoáng chất của xương (kg).
   - `rmrKcal`: Mức chuyển hóa năng lượng khi nghỉ ngơi (BMR/RMR kcal).
   - `bioAge`: Tuổi chuyển hóa / tuổi sinh học (năm).
   - `physiqueRating`: Điểm phân loại thể hình (thang điểm 1 - 9).
   - `measuredAt`: Thời điểm thực hiện lần quét gần nhất.

## 2. Tiêu chuẩn Đánh giá 9 Chỉ số theo Chuẩn Y khoa

### 1. Tỷ lệ Mỡ Cơ Thể (Body Fat %)
- **Nữ giới:**
  - Dưới 20%: Thiếu mỡ (nguy cơ rối loạn nội tiết).
  - 21% - 32%: Khỏe mạnh / Chuẩn thể thao.
  - 33% - 38%: Thừa mỡ nhẹ.
  - Trên 39%: Béo phì (nguy cơ tim mạch, đái tháo đường).
- **Nam giới:**
  - Dưới 10%: Quá gầy / Vận động viên thể hình.
  - 11% - 21%: Khỏe mạnh / Chuẩn thể thao.
  - 22% - 26%: Thừa mỡ.
  - Trên 27%: Béo phì.

### 2. Tỷ lệ Nước Trong Cơ Thể (Body Water %)
- **Tiêu chuẩn tối thiểu:** Nữ $\ge 50\%$, Nam $\ge 55\%$.
- **Ý nghĩa:** Nước là môi trường diễn ra mọi chuyển hóa và đốt mỡ. Nếu nước $< 50\%$, hội viên đang mất nước tế bào, độc tố tích tụ và tốc độ giảm mỡ sẽ chậm.

### 3. Chỉ số Mỡ Nội Tạng (Visceral Fat)
- **1 - 9 (Mức Chuẩn):** Tốt, mỡ bám quanh nội tạng ở mức bảo vệ an toàn.
- **10 - 14 (Mức Nguy Cơ Cao):** Báo động nguy cơ gan nhiễm mỡ, xơ vữa động mạch, huyết áp cao.
- **15+ (Mức Nguy Hiểm Cực Kỳ Cao):** Cần điều chỉnh dinh dưỡng nghiêm ngặt ngay lập tức.

### 4. Khối lượng Cơ Bắp (Muscle Mass kg)
- Cơ bắp quyết định "cỗ máy đốt calo" tự nhiên của cơ thể. 1kg cơ bắp đốt nhiều gấp 3-4 lần 1kg mỡ khi nghỉ ngơi. Mục tiêu luôn là **Tăng cơ - Giảm mỡ**.

### 5. Tuổi Sinh Học (Metabolic Age)
- So sánh với Tuổi Thực tế của hội viên:
  - *Nhỏ hơn tuổi thực 3-5 tuổi:* Hệ trao đổi chất tuyệt vời.
  - *Bằng tuổi thực:* Bình thường.
  - *Lớn hơn tuổi thực:* Cơ thể đang lão hóa nhanh, mỡ thừa nhiều và thiếu cơ/nước.

### 6. Đánh giá Thể hình (Physique Rating 1 - 9)
- **1:** Béo phì tiềm ẩn (Hidden Obese - ngoài trông bình thường nhưng mỡ nhiều, cơ ít).
- **2:** Béo phì (Obese).
- **3:** Thể hình đẫm đà (Solidly Built).
- **4:** Thiếu tập luyện (Under-exercised).
- **5:** Chuẩn (Standard).
- **6:** Tiêu chuẩn cơ bắp (Standard Muscular).
- **7:** Mảnh khảnh (Thin).
- **8:** Mảnh khảnh cơ bắp (Thin & Muscular).
- **9:** Rất cơ bắp / Thể thao (Very Muscular).

## 3. Mẫu Cấu trúc Báo cáo Phân tích cho Coach

Khi người dùng yêu cầu phân tích chỉ số, hãy định dạng báo cáo chuyên nghiệp theo mẫu:

```markdown
📊 **BÁO CÁO PHÂN TÍCH CHỈ SỐ CƠ THỂ TANITA**
👤 Hội viên: **[Tên khách hàng]** | 📅 Ngày quét: `[measuredAt]`

1. ⚖️ **Cân nặng & Cơ bắp:**
   - Cân nặng: **[weightKg] kg**
   - Cơ bắp: **[muscleMassKg] kg** *(Cỗ máy đốt mỡ tự nhiên)*

2. 🔥 **Đánh giá Mỡ & Mỡ nội tạng:**
   - Tỷ lệ mỡ: **[bodyFatPct]%** 👉 [Phân loại: Chuẩn / Thừa mỡ / Béo phì]
   - Mỡ nội tạng: **Cấp [visceralFat]** 👉 [Mức 1-9 an toàn / Cấp 10-14 báo động]

3. 💧 **Môi trường tế bào:**
   - Tỷ lệ nước: **[waterPct]%** 👉 [Đủ / Thiếu nước, mục tiêu tối thiểu ...]
   - Tuổi sinh học: **[bioAge] tuổi** *(Tuổi thực: [tuổi_thực])*
   - Xếp hạng thể hình: **Nhóm [physiqueRating]**

💡 **LỜI KHUYÊN & GIẢI PHÁP TỪ COACH:**
- *Về Nước:* Uống tối thiểu [targetWater] Lít/ngày, chia nhỏ từng ngụm để tăng hydrat hóa tế bào.
- *Về Đạm (Protein):* Bổ sung đạm sạch thực vật vào bữa sáng và bữa phụ chiều để giữ và tăng khối cơ bắp.
- *Về Mỡ nội tạng:* Hạn chế tối đa tinh bột chuyển hóa nhanh, bia rượu, đồ chiên xào sau 18h.
```
