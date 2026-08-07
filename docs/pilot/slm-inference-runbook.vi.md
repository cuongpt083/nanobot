# Hướng Dẫn Triển Khai & Vận Hành SLM Inference (Vietnamese Runbook)

Tài liệu này cung cấp quy trình chi tiết cho đội ngũ DevOps và SRE để triển khai, xác minh, giám sát và xử lý sự cố hệ thống **Layered Inference & SLM Runtime** (Giai đoạn A) cũng như lộ trình triển khai tiếp theo (Giai đoạn B) trong nanobot.

---

## 1. Tổng Quan Lộ Trình Triển Khai Theo Giai Đoạn

```
+-----------------------------------------------------------------------------------+
| GIAI ĐOẠN A (ĐÃ TRIỂN KHAI HÔM NAY): Layered Inference Runtime                    |
| - Student Model (Base): Qwen3-4B-Instruct-2507 (Q5_K_M GGUF) qua ArtifactRegistry |
| - Teacher Preset: deepseek-v4-flash (có thể cấu hình)                            |
| - Phân luồng: Tác vụ đơn giản -> Student Direct | Tác vụ phức tạp/Tool -> Teacher  |
| - Fallback: Tự động chuyển sang Teacher khi Student bị lỗi/timeout/down           |
+-----------------------------------------------------------------------------------+
                                        |
                 Quyết định Value Gate Phase A (go / no_go)
                                        |
+-----------------------------------------------------------------------------------+
| GIAI ĐOẠN B (SẼ TRIỂN KHAI TIẾP THEO - Sau khi Phase A đạt kết quả 'go'):         |
| - Data Curation: Exporter dùng composite cursor & capture-time consent           |
| - Tự động hóa Distillation: Fine-tune QLoRA, Merge FP16, Quantize GGUF           |
| - Background Coordinator & Operations API (E.27.2, E.28)                          |
| - WebUI Control Plane cho Ops (E.29b-e)                                           |
+-----------------------------------------------------------------------------------+
```

---

## 2. Yêu Cầu Phần Cứng & Môi Trường

Trước khi bật dịch vụ Student SLM trên máy chủ, DevOps cần xác minh tài nguyên hệ thống:

| Tài nguyên | Khuyến nghị | Tối thiểu |
| :--- | :--- | :--- |
| **RAM / VRAM** | 8 GB RAM (CPU) hoặc 6 GB VRAM (GPU) | 4 GB RAM (CPU, chậm hơn) |
| **Dung lượng đĩa**| 10 GB trống (cho file GGUF & log) | 5 GB trống |
| **Môi trường Python** | Python 3.11+ có cài `llama-cpp-python` | Python 3.11+ |

---

## 3. Cài Đặt Môi Trường & Đặt File Model

### 3.1 Cài đặt `llama-cpp-python`

Cho máy chủ chạy bằng CPU:
```bash
uv pip install llama-cpp-python
```

Cho máy chủ có GPU NVIDIA (CUDA):
```bash
CMAKE_ARGS="-DGGML_CUDA=on" uv pip install llama-cpp-python --no-cache-dir
```

### 3.2 Đặt File Model & Đăng Ký Artifact

Model được tham chiếu **duy nhất** qua `active_model_id` (Logical ID) trong `ArtifactRegistry`. 

Đặt file model GGUF đã quantize vào đường dẫn `~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf`:

```bash
mkdir -p ~/.nanobot/models/
cp /path/to/qwen3-4b-pilot-q5_k_m.gguf ~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf
```

---

## 4. Cấu Hình Hệ Thống

Cập nhật file `~/.nanobot/config.json` để bật cấu hình `pilot.student`:

```json
{
  "pilot": {
    "enabled": true,
    "student": {
      "enabled": true,
      "active_model_id": "qwen3-4b-pilot-q5_k_m",
      "teacher_preset": "deepseek-v4-flash",
      "context_length": 4096,
      "max_tokens": 2048,
      "temperature": 0.7,
      "concurrent_instances": 1,
      "complexity_threshold": 0.5
    }
  }
}
```

> [!NOTE]
> Đường dẫn file đĩa local và binary toolchain hoàn toàn bảo mật trong nội bộ server (`ArtifactRegistry`). WebUI và các payload API **không bao giờ** nhận hoặc trả về trực tiếp đường dẫn file đĩa.

---

## 5. Kiểm Tra & Giám Sát Sức Khỏe (Health Check)

### 5.1 Kiểm tra API Health Endpoint

Khởi chạy nanobot gateway và gọi endpoint kiểm tra sức khỏe:

```bash
curl -s http://localhost:8765/api/pilot/health | jq .
```

**Kết quả mong đợi:**
```json
{
  "status": "ok",
  "student": {
    "status": "ok",
    "active_model_id": "qwen3-4b-pilot-q5_k_m",
    "context_length": 4096,
    "is_available": true,
    "queue_depth": 0
  },
  "capabilities": {
    "layered_inference": {
      "available": true,
      "enabled": true,
      "status": "ok",
      "read_allowed": true
    }
  }
}
```

### 5.2 Kiểm tra Tự động (Automated Verification)

Chạy bộ unit & integration test của hệ thống:

```bash
uv run pytest tests/pilot/distillation/test_registry.py tests/providers/test_student_provider.py tests/pilot/test_student.py tests/pilot/test_complexity.py tests/pilot/test_orchestrator.py -v
```

---

## 6. Các Bước Triển Khai Tiếp Theo Cho Đội Ngũ DevOps (Phase B Roadmap)

Sau khi giai đoạn thử nghiệm Phase A đưa ra kết quả `go` (`scripts/pilot_evaluate.py`), đội ngũ DevOps sẽ tiến hành triển khai Phase B theo các bước sau:

1. **Triển khai Governed Data Exporter (Task E.20 Rework):** Cấu hình script export `scripts/pilot_export.py` chạy theo cron job định kỳ với composite cursor `(created_at_ms, turn_id)` để trích xuất dữ liệu huấn luyện đã được người dùng đồng ý (consent).
2. **Triển khai Distillation Pipeline (Task E.21 - E.22):** Thiết lập môi trường huấn luyện QLoRA (`scripts/pilot_finetune.py`) chạy dưới dạng tiến trình con (child process) độc lập để không ảnh hưởng tới gateway event loop.
3. **Triển khai Background Coordinator & Operations API (Task E.27.2 - E.28):** Mở các API quản lý tiến trình ngầm (`POST /api/pilot/operations/jobs`) và SSE stream theo dõi sự kiện realtime (`/api/pilot/operations/events`).
4. **Mở Quyền Điều Hành Trên WebUI Ops Control (Task E.29b-e):** Kích hoạt bảng điều khiển dành riêng cho DevOps trên WebUI để bấm nút trigger pipeline, theo dõi tiến độ fine-tuning và xác thực model artifact.

---

## 7. Quy Trình Xử Lý Sự Cố (Troubleshooting & Emergency Ops)

### Trạng thái A: Model không khả dụng (`is_available: false`)
* **Hiện tượng:** Response `/api/pilot/health` trả về `student.status == "degraded"` hoặc có lỗi `load_error`.
* **Hành vi hệ thống:** Orchestrator tự động chuyển toàn bộ request (bất kể đơn giản hay phức tạp) sang Teacher LLM (`deepseek-v4-flash`). Người dùng cuối **không** nhận thông báo lỗi.
* **Cách khắc phục:** Kiểm tra file model tại `~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf` và chạy lại `uv sync` để đảm bảo `llama-cpp-python` đã cài đặt đúng.

### Trạng thái B: Tràn bộ nhớ (OOM) trên máy chủ RAM thấp
* **Hiện tượng:** Tiến trình Gateway bị OS OOM Killer dừng khi có tải cao.
* **Cách khắc phục:** Sửa `context_length` xuống `2048` trong `~/.nanobot/config.json` và đảm bảo `concurrent_instances` đặt là `1`.
