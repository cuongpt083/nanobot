#!/usr/bin/env bash
set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NANOBOT_ROOT="$(cd "$PLUGIN_DIR/../.." && pwd)"
CRM_LITE_DIR="/home/cuongpt/nutritech-crm-lite"

echo "=== Cài đặt & Kích hoạt NutriTech CRM Plugin cho Nanobot ==="
echo "📁 Thư mục Plugin: $PLUGIN_DIR"
echo "📁 Thư mục Nanobot: $NANOBOT_ROOT"

# 1. Kiểm tra Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Lỗi: Node.js chưa được cài đặt trên hệ thống."
    exit 1
fi
echo "✓ Node.js: $(node -v)"

# 2. Kiểm tra bản build nutritech-crm-lite MCP server
if [ -d "$CRM_LITE_DIR" ]; then
    if [ ! -f "$CRM_LITE_DIR/dist/mcp/index.js" ]; then
        echo "⚙️ Đang biên dịch nutritech-crm-lite (npm run build)..."
        (cd "$CRM_LITE_DIR" && npm run build)
    fi
    echo "✓ nutritech-crm-lite MCP server sẵn sàng ($CRM_LITE_DIR/dist/mcp/index.js)."
else
    echo "⚠️ Cảnh báo: Không tìm thấy thư mục CRM tại $CRM_LITE_DIR"
fi

# 3. Kích hoạt Plugin cho các Workspace của nanobot
PYTHON_BIN="$NANOBOT_ROOT/.venv/bin/python3"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

$PYTHON_BIN - <<EOF
from pathlib import Path
from nanobot.agent.plugins import set_agent_plugin_enabled

workspaces = [
    Path("$NANOBOT_ROOT"),
    Path.home() / ".nanobot" / "workspace",
]

for ws in workspaces:
    ws.mkdir(parents=True, exist_ok=True)
    plugin_target = ws / "plugins" / "nutritech-crm"
    if not plugin_target.exists():
        plugin_target.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copytree(Path("$PLUGIN_DIR"), plugin_target)
        print(f"✓ Đã sao chép plugin vào workspace: {plugin_target}")

    try:
        set_agent_plugin_enabled(ws, "nutritech-crm", True)
        print(f"✓ Đã kích hoạt plugin cho workspace: {ws}")
    except Exception as exc:
        print(f"⚠️ Không thể kích hoạt tự động cho {ws}: {exc}")
EOF

echo ""
echo "✅ NutriTech CRM plugin cho nanobot đã được cài đặt và kích hoạt thành công!"
echo "👉 Các kỹ năng sẵn sàng: 'nutritech-crm', 'tanita-analysis'"
echo "👉 Các công cụ MCP sẵn sàng: 25+ tools từ nutritech-crm-lite"
