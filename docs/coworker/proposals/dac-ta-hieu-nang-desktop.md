# Đặc tả: Hiệu năng Desktop app local

2026-10-07 · Cuong Fam

## Mục tiêu

Cải thiện cảm giác dùng nanobot trên Desktop app Windows (Tauri + WebView2 + gateway local). Không thiết kế remote use (VPS, SSH tunnel, Tailscale).

Ba hướng, theo hiệu quả:

1. Không đưa dữ liệu lớn qua IPC của Tauri.
2. Sửa các lỗi render kinh điển của app chat.
3. Hiện khung app ngay, rồi mới chờ gateway.

## Hiện trạng (đã đối chiếu code)

| Hạng mục | Hiện trạng | Việc còn lại |
| --- | --- | --- |
| IPC Tauri | Webview đã mở `http://127.0.0.1:<port>`. `invoke` chỉ còn `open_log_file`, `retry_gateway`, `open_external_url` | Guardrail: không thêm file, ảnh, stream chat vào `invoke`. Nếu bắt buộc stream native, dùng Tauri Channel + payload nhị phân |
| Stream token | `useNanobotStream` đã gom delta qua `requestAnimationFrame`, tối thiểu 50 ms khi tab hiện / 1 s khi nền | Đã đạt; chỉ chỉnh nếu baseline còn jank lúc stream |
| Markdown / Mermaid | Streamdown `mode=streaming\|static`; Mermaid tách chunk lazy | ELK, pan/zoom, Intersection Observer. Việc "chỉ render khi khối hoàn chỉnh" cần kiểm chứng trên Streamdown trước khi coi là khoảng trống |
| Danh sách tin | `ThreadMessages` render toàn bộ unit, không ảo hóa | Ảo hóa phiên dài (hàng trăm tin, code block, sơ đồ) |
| Khởi động | Splash native, poll `/webui/bootstrap`, rồi mới hiện webview chat | Hiện khung cửa sổ (sidebar + composer trống) ngay; gateway và lịch sử tải sau |

Trước khi nhận "giật" hay "mở chậm", đo baseline trên WebView2: phiên ~300 tin có code + Mermaid (thời gian tới splash, tới khung app, tới tin cuối cùng tương tác được; FPS khi cuộn và khi stream).

## P1 — Không đưa payload lớn qua Tauri IPC

Trên Windows, IPC WebView2 là điểm yếu (tham chiếu đo cộng đồng: ~200 ms cho 10 MB nhị phân, so với ~5 ms trên macOS). Kiến trúc đúng với Desktop local:

- Webview ↔ gateway: HTTP + WebSocket loopback cho chat, file, ảnh.
- Rust chỉ: cửa sổ, tray, thông báo, mở file/URL local, spawn/tắt sidecar.

Editor pane và image pane phải dùng workspace file API của gateway, không `invoke` nội dung file. Chi tiết: `dac-ta-editor-image-pane.md`.

**Cổng:** grep/`invoke` trong `desktop/` và `webui/` không mang nội dung workspace; mở file 1 MB và ảnh vài MB không đi qua Rust.

## P2 — Render chat (tách hai lát)

Không gộp ảo hóa với Mermaid. `ThreadMessages.tsx` (~1.000 dòng) dính chiều cao biến đổi, neo cuộn khi stream, quote, fork, activity cluster và tìm trong trang.

- **P2a Mermaid / Markdown:** ELK, tắt `useMaxWidth`, pan/zoom, debounce, chỉ render khi khối hoàn chỉnh và nằm trong viewport. Streamdown đã tách chunk Mermaid; cần đo xem khối đang stream còn parse lại cả tin không.
- **P2b Ảo hóa danh sách tin:** chỉ làm nếu baseline WebView2 cho thấy giật thật khi cuộn phiên ~300 tin.
- **P2c Stream:** đã rAF + 50 ms; không làm trừ khi baseline còn jank lúc stream.
- **Lazy load** Monaco, Konva, Mermaid — khớp editor pane.

**Cổng P2a:** sequence 15 participant đọc được chữ; Ctrl+cuộn zoom sơ đồ, cuộn thường cuộn trang.
**Cổng P2b:** cuộn phiên 300 tin không tụt dưới ngưỡng FPS baseline; stream không block ô nhập.

## P3 — Khởi động cảm nhận nhanh

Hiện tại webview chỉ điều hướng tới URL gateway sau `/webui/bootstrap` (có `bootstrapSecret`). Hiện đúng khung app (sidebar + composer) trước gateway là việc lớn: phải đóng gói WebUI vào frontend Tauri hoặc đổi luồng bootstrap.

Lát rẻ trước: splash có khung xương + đo time-to-splash / time-to-chrome / time-to-interactive. Chỉ làm P3 đầy đủ nếu baseline chứng minh cảm giác chờ là vấn đề.

**Cổng lát rẻ:** có số đo ổn định trên Desktop Windows.
**Cổng P3 đầy đủ:** time-to-chrome giảm rõ; time-to-interactive không tệ hơn baseline ngoài sai số đo.

## Ngoài phạm vi

- Remote gateway, tunnel, Tailscale.
- WebUI trên điện thoại (mở gateway ra mạng là remote use).
- Viết lại toàn bộ WebUI.
- Tối ưu macOS/Linux trước Windows.

## Lộ trình

1. Đo baseline WebView2 (không viết tối ưu mù).
2. P2a Mermaid (ELK, pan/zoom, viewport) — lát riêng, rủi ro thấp.
3. P2c stream rAF chỉ nếu baseline còn jank khi stream.
4. P2b ảo hóa chỉ nếu baseline còn jank khi cuộn.
5. P3 lát rẻ (splash + số đo); P3 đầy đủ sau khi có số.
6. P1 là guardrail cho mọi pane mới (editor, ảnh, live view trình duyệt), không phải hạng mục làm.
