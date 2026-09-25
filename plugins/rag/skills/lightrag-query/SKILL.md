---
name: lightrag-query
description: "Expert knowledge retrieval skill for querying domain knowledge bases via LightRAG with multi-mode selection (mix, local, global, hybrid, naive) and Laya gating."
---

# Kỹ Năng Truy Vấn Tri Thức LightRAG & Cổng Quyết Định Laya

Kỹ năng này trang bị cho Agent khả năng tra cứu tri thức chuyên sâu từ đồ thị tri thức và cơ sở dữ liệu vector của LightRAG, đồng thời hiểu cơ chế kiểm soát cổng Laya.

---

## 1. Khi Nào Cần Tra Cứu Tri Thức

Hãy gọi tool `rag_search` khi:
- Người dùng hỏi về các chính sách, tài liệu nội bộ, thông số kỹ thuật, hồ sơ sản phẩm, hoặc hướng dẫn chuyên môn.
- Cần dẫn chứng cụ thể từ tài liệu tri thức đã được lập chỉ mục trong LightRAG.

**KHÔNG** gọi `rag_search` khi:
- Người dùng chỉ chào hỏi ("Xin chào", "Hello", "Cảm ơn", "Tạm biệt").
- Các câu hỏi toán học đơn giản, đố vui, hoặc xử lý văn bản cơ bản không cần kiến thức ngoài.

---

## 2. Quy Tắc Lựa Chọn Mode 5 Tầng của LightRAG

Khi gọi `rag_search(query, mode=...)`, hãy phân tích mục đích câu hỏi để chọn mode tối ưu:

| Mode | Mục tiêu | Ví dụ áp dụng |
|---|---|---|
| **`local`** | **Thực thể cụ thể (Entity-focused):** Tập trung sâu vào 1 khái niệm, thông số, con người, thuật ngữ hẹp. | *"Chỉ số mỡ nội tạng mức 9 có ý nghĩa gì?"*, *"Công dụng chính của Curcumin?"* |
| **`global`** | **Khái quát & Mối quan hệ (Relationship-focused):** Câu hỏi tổng hợp, xu hướng lớn, bức tranh toàn cảnh, so sánh vĩ mô. | *"Tóm tắt các nguyên nhân chính gây tăng cân trong nhóm phụ nữ sau sinh"*, *"Bức tranh toàn cảnh về thị trường dinh dưỡng"* |
| **`mix`** *(Mặc định)* | **Toàn diện (Knowledge Graph + Vector Chunks):** Kết hợp cả thực thể và mối quan hệ đa chiều. | Khuyên dùng cho hầu hết các câu hỏi thông thường. |
| **`hybrid`** | Kết hợp vector và đồ thị mức trung bình. | Khi cần cân bằng giữa tìm kiếm ngữ nghĩa và thực thể. |
| **`naive`** | **Vector-only:** Tìm kiếm vector thuần túy. | Áp dụng cho các tài liệu phi cấu trúc không có quan hệ thực thể rõ rệt. |

---

## 3. Xử Lý Kết Quả Từ Laya Gating

Tool `rag_search` tích hợp sẵn mô hình quyết định Laya:
- Nếu kết quả trả về `retrieved: false` và `decision: "skipped"`:
  - Đây là tín hiệu Laya xác định câu hỏi không cần tra cứu tài liệu chuyên sâu.
  - Agent trả lời tự nhiên bằng kiến thức tổng quát của bản thân.
  - Chỉ gọi lại `rag_search(query, bypass_decision=true)` nếu người dùng kiên quyết yêu cầu trích xuất từ tài liệu.

---

## 4. Chuẩn Trích Dẫn Nguồn (Citations)

1. Mọi câu trả lời tri thức phải dựa trên nội dung trong `content`. Không tự suy diễn thông tin trái ngược với tài liệu.
2. Kết thúc câu trả lời bằng phần trích dẫn nguồn rõ ràng:
   ```markdown
   📚 **Nguồn tài liệu tham khảo:**
   - [Tên tài liệu / Chương 1]
   - [Tên tài liệu 2]
   ```
