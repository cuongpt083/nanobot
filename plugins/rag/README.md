# Nanobot RAG Plugin (LightRAG & Laya Integration)

Plugin cung cấp công cụ truy vấn tri thức RAG cho Nanobot kết nối tới máy chủ **LightRAG Server** và tích hợp cổng quyết định **Laya Decision Model**.

## Cấu hình Biến môi trường trong `mcp.json`:
- `LIGHTRAG_BASE_URL`: URL máy chủ LightRAG (mặc định: `http://localhost:9621`)
- `LIGHTRAG_API_KEY`: API Key nếu LightRAG Server yêu cầu xác thực
- `LIGHTRAG_WORKSPACE`: Workspace header (`LIGHTRAG-WORKSPACE`)
- `LAYA_ENABLED`: Bật/tắt Laya gating (`true`/`false`)
- `LAYA_SERVICE_URL`: Endpoint dịch vụ Laya (mặc định: `http://localhost:8000/v1/decide`)
- `LAYA_THRESHOLD`: Ngưỡng tin cậy kích hoạt RAG (mặc định: `0.70`)
- `LAYA_TIMEOUT_SECONDS`: Strict timeout cho Laya (mặc định: `0.50`)
