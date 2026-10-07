"""Generate a ~300-message chat session fixture for WebView2 perf and F2 recall testing."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "docs" / "coworker" / "plans" / "chat-300-fixture.jsonl"

# 15 participants for the sequence diagram
PARTICIPANTS = [
    "ClientApp",
    "Gateway",
    "AuthService",
    "UserStore",
    "RoomManager",
    "AgentScheduler",
    "ContextService",
    "RecallFTS",
    "LLMProvider",
    "ToolExecutor",
    "SandboxWorker",
    "FileSystem",
    "ArtifactStore",
    "EventBus",
    "AuditLogger",
]


def make_mermaid_sequence_15() -> str:
    lines = ["```mermaid", "sequenceDiagram", "    autonumber"]
    for p in PARTICIPANTS:
        lines.append(f"    participant {p}")
    lines.extend(
        [
            "    ClientApp->>Gateway: POST /api/room/chat (Gửi tin nhắn yêu cầu)",
            "    Gateway->>AuthService: Xác thực JWT token và phân quyền persona",
            "    AuthService-->>Gateway: Phê duyệt (User: Cuong, Role: Lead)",
            "    Gateway->>RoomManager: Dispatch tin nhắn vào phòng 'coworker-core'",
            "    RoomManager->>AgentScheduler: Lập lịch phân công chuyên viên",
            "    AgentScheduler->>RecallFTS: Tra cứu ngữ cảnh và lịch sử liên quan",
            "    RecallFTS-->>AgentScheduler: Trả về 3 tài liệu khớp BM25",
            "    AgentScheduler->>ContextService: Đóng gói envelope ngữ cảnh rút gọn",
            "    ContextService-->>AgentScheduler: ContextEnvelope sẵn sàng",
            "    AgentScheduler->>LLMProvider: Stream prompt & tools definition",
            "    LLMProvider-->>ToolExecutor: Yêu cầu gọi tool exec_cmd & read_file",
            "    ToolExecutor->>SandboxWorker: Khởi tạo tiến trình thực thi sandbox",
            "    SandboxWorker->>FileSystem: Đọc file cấu hình config.yaml",
            "    FileSystem-->>SandboxWorker: Dữ liệu file",
            "    SandboxWorker-->>ToolExecutor: Kết quả thực thi",
            "    ToolExecutor->>ArtifactStore: Lưu trữ artifact output kết quả",
            "    ArtifactStore-->>EventBus: Phát sự kiện artifact_created",
            "    EventBus->>AuditLogger: Ghi log kiểm toán an toàn",
            "    EventBus-->>Gateway: SSE event stream cập nhật UI",
            "    Gateway-->>ClientApp: Hiển thị phản hồi hoàn tất",
            "```",
        ]
    )
    return "\n".join(lines)


def make_mermaid_graph() -> str:
    return """```mermaid
flowchart TD
    A[Bắt đầu tiếp nhận tác vụ] --> B{Phân loại nội dung}
    B -->|Tư vấn chiến lược| C[Persona: Tư vấn trưởng]
    B -->|Soạn thảo văn bản| D[Persona: Chuyên viên nội dung]
    B -->|Xử lý số liệu| E[Persona: Phân tích định lượng]
    C --> F[Điều phối subagent thực thi]
    D --> F
    E --> F
    F --> G[Kiểm tra chất lượng & Rubric]
    G --> H{Đạt chuẩn?}
    H -->|Đạt| I[Xuất kết quả cuối cho người dùng]
    H -->|Chưa đạt| F
```"""


def make_mermaid_state() -> str:
    return """```mermaid
stateDiagram-v2
    [*] --> KhoiTao : Tiếp nhận yêu cầu
    KhoiTao --> DangPhanTich : Tải bối cảnh & FTS index
    DangPhanTich --> PhanCong : Lập kế hoạch thực hiện
    PhanCong --> ThucThi : Điều phối guest runner
    ThucThi --> KiemDuyet : Thu nhận kết quả & envelope
    KiemDuyet --> HoanTat : Duyệt thành công
    KiemDuyet --> ThucThi : Yêu cầu chỉnh sửa (repair)
    HoanTat --> [*]
```"""


# Planted recall facts (Vietnamese with diacritics, stable keywords for Recall@5)
RECALL_FACTS = [
    (
        "RF01",
        "Mã hợp đồng triển khai giải pháp CRM Nutritech cho chi nhánh miền Nam là HD-NUTRI-2026-8899.",
    ),
    (
        "RF02",
        "Địa chỉ máy chủ cơ sở dữ liệu dự phòng PostgreSQL được chỉ định tại IP 192.168.10.245 cổng 5433.",
    ),
    (
        "RF03",
        "Chỉ số mỡ cơ thể mục tiêu của khách hàng Nguyễn Văn An là giảm từ 28% xuống 23% trong lộ trình 60 ngày.",
    ),
    (
        "RF04",
        "Khoá bí mật ký webhook thanh toán ZaloPay Sandbox cấu hình giá trị `k_zalopay_sandbox_9981az`.",
    ),
    (
        "RF05",
        "Ngân sách tối đa được duyệt cho chiến dịch quảng cáo TikTok EduTech quý 4 là 150 triệu đồng.",
    ),
    (
        "RF06",
        "Người chịu trách nhiệm duyệt mã nguồn cuối cùng của module Desktop Tauri là anh Hoàng Minh Tuấn.",
    ),
    (
        "RF07",
        "Cấu hình thời gian chờ kết nối cổng kiểm tra Gateway `_tcp_endpoint_reachable` được rút ngắn còn 50 mili-giây.",
    ),
    (
        "RF08",
        "Phiên bản thư viện stable-diffusion.cpp được ghim cho bộ sinh ảnh coworker là master-898-2bb7294.",
    ),
    (
        "RF09",
        "Đường dẫn tuyệt đối chứa bộ nhớ đệm WebView2 cần dọn dẹp khi cài đặt là thư mục EBWebView.",
    ),
    (
        "RF10",
        "Tỷ lệ hoa hồng cho chuyên viên tư vấn dinh dưỡng đối với gói VIP Chăm sóc cá nhân là 18%.",
    ),
    (
        "RF11",
        "Quy tắc đặt tên file ảnh tạm thời cho Image Pane quy định lưu tại thư mục OS tempdir `nanobot-image-versions`.",
    ),
    ("RF12", "Giới hạn ký tự tối đa của một bản tóm tắt envelope điều phối room là 1500 ký tự."),
    (
        "RF13",
        "Mã định danh sinh viên quốc tế của trường đối tác RMIT chuyển đổi tín chỉ là ID-STU-VN-2024.",
    ),
    (
        "RF14",
        "Quy trình Socratic Pedagogy bao gồm đúng 4 bước kiểm tra: INQUIRY, HINT_1, QUIZ, và PASSED.",
    ),
    (
        "RF15",
        "Mã số thuế của công ty Cổ phần Công nghệ Giáo dục Thế Hệ Mới ghi nhận là 0317892341.",
    ),
    (
        "RF16",
        "Ngưỡng số lượng tool call tối thiểu để kích hoạt bộ phản tư tạo skill nháp F1 là 5 tool calls.",
    ),
    ("RF17", "Giao thức WebSocket multiplex của Gateway sử dụng cổng dịch vụ mặc định là 8765."),
    (
        "RF18",
        "Tên model bộ nhớ đệm suy luận cục bộ được khuyến nghị cho tác vụ kiểm duyệt nhanh là Qwen2.5-Coder-7B-Instruct.",
    ),
    (
        "RF19",
        "Quy định mã hóa FTS5 cho bảng tìm kiếm sử dụng tokenizer `unicode61 remove_diacritics 2`.",
    ),
    (
        "RF20",
        "Email liên hệ khẩn cấp của đội ngũ trực vận hành hạ tầng đám mây là noc-alert@nanobot.internal.",
    ),
]


def generate_fixture(output_path: Path = OUTPUT_PATH) -> None:
    session_key = "eval:desktop-perf-p0:chat-300"
    base_time = datetime(2026, 10, 1, 8, 0, 0)

    records = []

    # 1. Header metadata
    metadata = {
        "_type": "metadata",
        "key": session_key,
        "created_at": base_time.isoformat(),
        "updated_at": (base_time + timedelta(hours=5)).isoformat(),
        "metadata": {
            "title": "Phiên kiểm thử tải WebView2 và Đánh giá Recall FTS5 (300 tin nhắn)",
            "persona": "coworker-lead",
            "eval_fixture": True,
        },
        "last_archived": 0,
        "last_consolidated": 0,
    }
    records.append(json.dumps(metadata, ensure_ascii=False))

    # Generate 300 messages (turns alternating user / assistant)
    # Total messages: 300. (i from 0 to 299)
    current_time = base_time
    fact_index = 0

    for i in range(300):
        current_time += timedelta(minutes=1)
        role = "user" if i % 2 == 0 else "assistant"
        msg_id = f"msg_{i + 1:03d}"

        # Inject Mermaid diagrams at specific points
        if i == 50:
            content = (
                f"[{msg_id}] Hãy vẽ lại sơ đồ quy trình phân loại và điều phối nghiệp vụ:\n\n"
                + make_mermaid_graph()
            )
        elif i == 150:
            content = (
                f"[{msg_id}] Sơ đồ kiến trúc tuần tự tổng thể với 15 thành phần tương tác trong hệ thống:\n\n"
                + make_mermaid_sequence_15()
            )
        elif i == 250:
            content = (
                f"[{msg_id}] Sơ đồ máy trạng thái biểu diễn vòng đời của một tác vụ phòng làm việc (Room Task):\n\n"
                + make_mermaid_state()
            )
        elif i % 15 == 1 and fact_index < len(RECALL_FACTS):
            # Plant recall fact
            rf_id, rf_text = RECALL_FACTS[fact_index]
            content = f"[{msg_id}] Ghi chú quan trọng [{rf_id}]: {rf_text} Vui lòng lưu thông tin này vào biên bản ghi nhớ hệ thống."
            fact_index += 1
        elif i % 20 == 0:
            # Markdown table
            content = f"""[{msg_id}] Bảng tổng hợp tiến độ kiểm tra các module tính năng:

| STT | Phân hệ | Tiến độ | Đánh giá rủi ro | Ghi chú kiểm thử |
|---|---|---|---|---|
| 1 | F3 Brief/Envelope | 85% | Thấp | Đã hoàn tất schema contract |
| 2 | F2 FTS5 Recall | 60% | Trung bình | Cần đo lường tokenizer không dấu |
| 3 | F1 Skill Learning | 40% | Trung bình | Cơ chế hook background |
| 4 | Editor Monaco | 90% | Rất thấp | Sẵn sàng cho G1/G2 |
| 5 | Image Konva | 50% | Cao | Tích hợp tempdir lưu phiên bản |
| 6 | Browser Local | 20% | Cao | Chạy headless không Docker |
"""
        elif i % 10 == 0:
            # Long code block
            content = f"""[{msg_id}] Đoạn mã xử lý chuẩn hóa dữ liệu đầu vào và kiểm tra hợp lệ:

```python
import hashlib
from typing import Any

def verify_checksum(payload: dict[str, Any], expected_hash: str) -> bool:
    \"\"\"Tính toán SHA-256 của payload được chuẩn hóa.\"\"\"
    raw_bytes = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    calculated = hashlib.sha256(raw_bytes).hexdigest()
    return calculated == expected_hash

# Ví dụ thực thi trên tập mẫu tin nhắn {i}
sample_data = {{"step": {i}, "status": "verified", "active": True}}
print(f"Checksum verification for step {i}: {{verify_checksum(sample_data, 'abc123')}}")
```
"""
        else:
            # Standard conversational text with technical and domain context
            if role == "user":
                content = f"[{msg_id}] Lượt hỏi {i + 1}: Nhờ trợ lý kiểm tra trạng thái của các tiến trình phụ, xác nhận phân bổ bộ nhớ và phản hồi tiến độ cập nhật hệ thống."
            else:
                content = f"[{msg_id}] Phản hồi {i + 1}: Tôi đã kiểm tra hệ thống. Mọi luồng xử lý đều đang vận hành trong ngưỡng an toàn, bộ nhớ ổn định và không phát hiện tắc nghẽn I/O tại tiến trình hiện hành."

        msg_obj = {"role": role, "content": content, "timestamp": current_time.isoformat()}
        records.append(json.dumps(msg_obj, ensure_ascii=False))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(records) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} records (1 metadata + 300 messages) to {output_path}")


if __name__ == "__main__":
    generate_fixture()
