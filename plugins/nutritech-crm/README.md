# NutriTech CRM Plugin for Nanobot (`nutritech-crm`)

Plugin tích hợp NutriTech CRM (Model Context Protocol) dành cho hệ thống AI Agent `nanobot`.

## 1. Giới thiệu

Plugin này trang bị cho `nanobot`:
- **Kết nối MCP trực tiếp:** Cung cấp đầy đủ 25+ tools từ máy chủ `nutritech-crm-lite` (tra cứu khách hàng, phân tích chỉ số cơ thể Tanita, nhật ký check-in Bioclock, tính calo kỳ diệu, quản lý nhiệm vụ HLV).
- **Bộ Agent Skills chuyên sâu (`skills/`):**
  - `skills/nutritech-crm/SKILL.md`: Quy trình chăm sóc hội viên toàn diện cho Coach.
  - `skills/tanita-analysis/SKILL.md`: Hướng dẫn chuyên gia phân tích 9 chỉ số quét cơ thể Tanita theo chuẩn y khoa.

## 2. Cài đặt và kích hoạt

### Cách 1: Chạy script kích hoạt tự động (Khuyến nghị)
```bash
cd ~/nanobot/plugins/nutritech-crm
bash install.sh
```

### Cách 2: Kích hoạt bằng Python API của nanobot
```python
from pathlib import Path
from nanobot.agent.plugins import set_agent_plugin_enabled

workspace = Path.home() / ".nanobot" / "workspace"
set_agent_plugin_enabled(workspace, "nutritech-crm", True)
```

## 3. Cấu hình kết nối HTTP / SSE từ xa (Tùy chọn)

Nếu NutriTech CRM chạy trong Docker container hoặc server từ xa tại `http://localhost:3000/mcp/sse`, bạn có thể thêm cấu hình vào file `nanobot.json` (hoặc `~/.nanobot/config.json`):

```json
{
  "tools": {
    "mcp_servers": {
      "nutritech-crm-http": {
        "type": "streamableHttp",
        "url": "http://localhost:3000/mcp/sse"
      }
    }
  }
}
```
