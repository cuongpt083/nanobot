# Hướng Dẫn Cấu Hình MCP Servers & RAG Plugin Trong Nanobot
# Guide: Configuring MCP Servers & RAG Plugin in Nanobot

Tài liệu này hướng dẫn chi tiết cách thiết lập, tích hợp các công cụ MCP (Model Context Protocol) nội bộ và Agent Plugin (LightRAG Knowledge Base & Nutritech CRM) vào Nanobot, bao gồm cấu hình SSRF Whitelist, xử lý môi trường thực thi và quản lý lifecycle plugin.

---

## 1. Kiến Trúc Tổng Quan (Architecture Overview)

Nanobot hỗ trợ mở rộng năng lực thông qua 2 cơ chế chính:
1. **Direct MCP Servers** (`~/.nanobot/config.json`): Khai báo trực tiếp dưới `tools.mcpServers`, hỗ trợ các phương thức vận chuyển:
   - `sse` / `streamableHttp`: Kết nối qua HTTP/SSE tới remote/local service.
   - `stdio`: Khởi chạy tiến trình con (subprocess qua stdin/stdout JSON-RPC).
2. **Agent Plugins v1** (`<workspace>/plugins/*`): Đóng gói trọn vẹn gồm:
   - `plugin.json`: Metadata, danh mục, quyền hạn.
   - `mcp.json`: Khai báo MCP server chạy theo plugin.
   - `skills/`: Hướng dẫn prompt (SKILL.md) nạp vào LLM để nhận diện và gọi tool tối ưu.

```
                    ┌─────────────────────────┐
                    │      Nanobot Agent      │
                    │   (LLM + ToolRegistry)  │
                    └────────────┬────────────┘
                                 │
         ┌───────────────────────┴───────────────────────┐
         ▼                                               ▼
┌─────────────────────────┐                     ┌─────────────────────────┐
│     Direct MCP Server   │                     │      Agent Plugin       │
│      (nutritech-crm)    │                     │          (rag)          │
├─────────────────────────┤                     ├─────────────────────────┤
│ Type: SSE               │                     │ Type: Stdio (server.py) │
│ URL: 192.168.100.16     │                     │ Subprocess: Python      │
│ Port: 3456/mcp/sse      │                     │ Skill: lightrag-query   │
└────────────┬────────────┘                     └────────────┬────────────┘
             │ (SSRF Whitelist Checked)                      │ (HTTP REST Client)
             ▼                                               ▼
┌─────────────────────────┐                     ┌─────────────────────────┐
│     Nutritech CRM       │                     │    LightRAG Remote      │
│     Backend Service     │                     │   192.168.100.16:9621   │
└─────────────────────────┘                     └─────────────────────────┘
```

---

## 2. Cấu Hình SSRF Whitelist Cho Mạng Nội Bộ (Local Network)

Nanobot tích hợp cơ chế bảo vệ SSRF (Server-Side Request Forgery) mặc định chặn toàn bộ các dải IP riêng RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) và loopback khi thực hiện kết nối HTTP/SSE MCP hoặc Web Fetch.

Để cho phép kết nối tới các dịch vụ MCP nội bộ (như CRM hoặc RAG), cần bổ sung dải mạng vào `tools.ssrfWhitelist` trong `~/.nanobot/config.json`:

```json
{
  "tools": {
    "ssrfWhitelist": [
      "192.168.100.0/24"
    ]
  }
}
```

> [!TIP]
> Luôn giữ CIDR ở phạm vi hẹp nhất có thể (ví dụ: `192.168.100.16/32` hoặc `192.168.100.0/24`) để hạn chế rủi ro an toàn mạng.

---

## 3. Cấu Hình MCP Server Direct: Nutritech CRM (SSE)

Nutritech CRM chạy dưới dạng HTTP SSE MCP Server tại địa chỉ mạng nội bộ. Khai báo trực tiếp trong `~/.nanobot/config.json` dưới mục `"tools" -> "mcpServers"`:

```json
{
  "tools": {
    "mcpServers": {
      "nutritech-crm": {
        "type": "sse",
        "url": "http://192.168.100.16:3456/mcp/sse",
        "toolTimeout": 30,
        "enabledTools": [
          "*"
        ]
      }
    }
  }
}
```

- Khi khởi chạy, Nanobot sẽ probe kết nối tới URL này (đã được whitelist SSRF) và đăng ký toàn bộ 92 công cụ quản lý CRM vào ToolRegistry của Agent.

---

## 4. Cấu Hình Plugin: LightRAG Knowledge Base & Laya Decision (Stdio)

Plugin `rag` cung cấp công cụ truy vấn đồ thị tri thức LightRAG kết hợp cổng quyết định Laya.

### 4.1. Cấu trúc Plugin (`plugins/rag`)
- `plugin.json`: Khai báo manifest plugin.
- `mcp.json`: Khai báo MCP server `lightrag` kiểu stdio.
- `server.py`: MCP Server chính (cung cấp `rag_search`, `rag_check_decision`, `rag_health`).
- `lightrag_client.py`: Async HTTP Client giao tiếp với LightRAG API (`/query`, `/health`).
- `laya_client.py`: Cổng quyết định và Circuit Breaker.
- `skills/lightrag-query/SKILL.md`: Kỹ năng hướng dẫn Agent chọn 5 mode truy vấn (`mix`, `local`, `global`, `hybrid`, `naive`) và trích dẫn nguồn.

### 4.2. Cài đặt Plugin vào Workspace
Chạy script cài đặt để đồng bộ plugin vào thư mục workspace của Nanobot:
```bash
bash ~/nanobot/plugins/rag/install.sh ~/.nanobot/workspace
```

Thư mục đích: `~/.nanobot/workspace/plugins/rag`

### 4.3. Cấu hình biến môi trường trong `mcp.json`
Chỉnh sửa file `~/.nanobot/workspace/plugins/rag/mcp.json`:
```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "lightrag": {
      "type": "stdio",
      "command": "python",
      "args": ["${PLUGIN_ROOT}/server.py"],
      "env": {
        "LIGHTRAG_BASE_URL": "http://192.168.100.16:9621",
        "LIGHTRAG_API_KEY": "<YOUR_LIGHTRAG_API_KEY>",
        "LIGHTRAG_WORKSPACE": "shared_business",
        "LAYA_ENABLED": "false",
        "LAYA_SERVICE_URL": "http://localhost:8000/v1/decide",
        "LAYA_THRESHOLD": "0.70",
        "LAYA_TIMEOUT_SECONDS": "0.50"
      }
    }
  }
}
```

**Chi tiết các tham số:**
- `LIGHTRAG_BASE_URL`: Endpoint của remote server LightRAG (ví dụ: `http://192.168.100.16:9621`).
- `LIGHTRAG_API_KEY`: API Key (được tự động gửi trong header `X-API-Key`).
- `LIGHTRAG_WORKSPACE`: Tên workspace đồ thị tri thức (gửi qua header `LIGHTRAG-WORKSPACE`).
- `LAYA_ENABLED`: `"false"` nếu không dùng Laya Decision Model (gọi thẳng LightRAG); `"true"` nếu có triển khai Laya tại `LAYA_SERVICE_URL`.

---

## 5. Lưu Ý Kỹ Thuật Quan Trọng (Troubleshooting & Best Practices)

### 5.1. Môi trường thực thi Python cho MCP Stdio (`httpx` dependency)
Trong `mcp.json`, lệnh khởi chạy là `"command": "python"`. Trên môi trường máy chủ Linux:
- Thường chỉ có `/usr/bin/python3`, thiếu alias `python`.
- Python hệ thống thường không có thư viện `httpx` (gây lỗi `ModuleNotFoundError: No module named 'httpx'`).
- Môi trường ảo của Nanobot tại `~/.local/share/uv/tools/nanobot-ai/bin/python` đã có sẵn đầy đủ `httpx`, `mcp`, `pydantic`.

**Giải pháp:** Tạo script wrapper tại `~/.local/bin/python`:
```bash
cat << 'EOF' > ~/.local/bin/python
#!/bin/sh
exec ~/.local/share/uv/tools/nanobot-ai/bin/python "$@"
EOF
chmod +x ~/.local/bin/python
```

### 5.2. Cơ chế bảo vệ tính toàn vẹn Plugin (SHA256 Package Fingerprint)
Nanobot tự động tính toán mã băm SHA256 cho toàn bộ các file trong thư mục plugin để đảm bảo an toàn. 

> [!WARNING]
> Mỗi khi chỉnh sửa bất kỳ file nào trong thư mục plugin (ví dụ: cập nhật API key trong `mcp.json`), checksum thay đổi khiến Nanobot **tự động vô hiệu hóa** plugin (`enabled: false`) cho đến khi được cập nhật lại chữ ký kích hoạt.

Để kích hoạt lại plugin sau khi sửa cấu hình:
```bash
~/.local/share/uv/tools/nanobot-ai/bin/python -c "
from pathlib import Path
from nanobot.agent.plugins import set_agent_plugin_enabled
set_agent_plugin_enabled(Path('~/.nanobot/workspace'), 'rag', True)
print('Plugin re-enabled successfully!')
"
```

### 5.3. Khởi động lại Gateway
Sau khi chỉnh sửa `config.json`, `mcp.json` hoặc kích hoạt plugin, **bắt buộc khởi động lại Nanobot Gateway** để Gateway spawn lại các tiến trình MCP con:

```bash
# Dừng và khởi động lại gateway chạy nền bền vững
nanobot gateway restart || nanobot gateway --background
```

Kiểm tra nhật ký kết nối MCP trong `~/.nanobot/logs/gateway.log`:
```text
MCP server 'rag': connected, 3 capabilities registered
MCP server 'nutritech-crm': connected, 92 capabilities registered
MCP connected servers: ['nutritech-crm', 'rag']
```

---

## 6. Kiểm Tra Và Xác Nhận (Verification)

### 6.1. Kiểm tra Health Check qua CLI
Chạy kiểm tra trạng thái kết nối tới remote server LightRAG qua tool `rag_health`:
```bash
python -c "
import asyncio, sys
sys.path.insert(0, '/home/cuongpt/.nanobot/workspace/plugins/rag')
from server import handle_tool_call
print(asyncio.run(handle_tool_call('rag_health', {})))
"
```
Kết quả thành công sẽ trả về:
```json
{
  "status": "online",
  "lightrag": {
    "base_url": "http://192.168.100.16:9621",
    "reachable": true,
    "status_code": 200,
    "latency_ms": 73.12
  }
}
```

### 6.2. Kiểm tra trong Chat WebUI / CLI
Trong giao diện chat (`http://127.0.0.1:8765` hoặc `nanobot agent`):
- Hỏi: *"Kiểm tra trạng thái kết nối hệ thống RAG"* (Agent sẽ gọi `mcp_rag_rag_health`).
- Hỏi câu hỏi nghiệp vụ: *"Hãy tra cứu kiến thức về chính sách tư vấn trong tài liệu"* (Agent sẽ đọc kỹ năng trong `lightrag-query` SKILL.md, tự động chọn mode truy vấn tối ưu như `mix` hoặc `local`, sau đó trích dẫn nguồn tài liệu trả về từ LightRAG).
