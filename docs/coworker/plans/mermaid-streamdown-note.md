# Streamdown Mermaid Spike Note (Phase 0 Spike)

Phiên bản kiểm tra: `streamdown@2.5.0` (ghim trong `webui/package.json`).

## 1. Cơ chế render Mermaid trong Streamdown 2.5.0

Streamdown 2.5.0 có hỗ trợ Mermaid tích hợp sẵn nhưng hoạt động qua kiến trúc plugin (`plugins.mermaid` / `DiagramPlugin`), không tự động kích hoạt mặc định:
- Khi gặp fenced code block với `language="mermaid"`, component `MarkdownCode` của Streamdown kiểm tra:
  ```ts
  let d = useMermaidPlugin(); // de() lấy từ context Ve (plugins)
  if (m === "mermaid" && d) {
    // render qua Mermaid block tích hợp với download, copy, fullscreen, panZoom
  }
  ```
- Nếu `plugins.mermaid` không được truyền vào `<Streamdown plugins={{ mermaid: ... }} />`, nhánh này bị bỏ qua và rơi xuống render `code` block thông thường.

## 2. Điểm nghẽn hiện tại trong WebUI (`MarkdownTextRenderer.tsx`)

Trong `webui/src/components/MarkdownTextRenderer.tsx`, prop `components.code` đã bị ghi đè hoàn toàn:
```tsx
const components = useMemo<Components>(() => ({
  code({ className: cls, children: kids, node: _node, ...props }) {
    const match = /language-(\w+)/.exec(cls || "");
    if (match) {
      return <CodeBlock language={match[1]} code={code} ... />;
    }
    // ...
  }
}), [...]);
```
Do đó, ngay cả khi Streamdown có plugin Mermaid, `components.code` tùy chỉnh trong `MarkdownTextRenderer` vẫn tóm lấy toàn bộ code block có class `language-mermaid` và đưa vào `<CodeBlock />` (Shiki highlight văn bản thuần túy) chứ không hiển thị diagram!

## 3. Hành vi khi `mode="streaming"` với khối chưa đóng (Incomplete Code Fence)

- Streamdown có hook `useIsCodeFenceIncomplete()` (được gán từ context `et.Provider value={isIncomplete}`).
- Trong chế độ `mode="streaming"`:
  - Khi code fence chưa đóng (ví dụ đang stream ```` ```mermaid\ngraph TD\nA --> ````), `isIncomplete = true`.
  - Nếu cố gắng gọi `mermaid.render()` trên đoạn cú pháp chưa đóng hoặc dở dang, Mermaid engine sẽ throw cú pháp error (`Parse error on line...`).
  - Trong Streamdown's `MermaidComponent`: component bắt lỗi và hiển thị container lỗi màu đỏ (`Mermaid Error: ...`) hoặc fallback component.
  - **Khuyến nghị cho Phase 2 (P2a)**:
    - Trong `MarkdownTextRenderer.tsx`, kiểm tra `match[1] === "mermaid"`.
    - Khi đang stream (`streaming={true}` hoặc fence chưa đóng / cú pháp chưa hoàn chỉnh), hiển thị skeleton loader / raw preview có animation nhẹ thay vì render Mermaid ngay lập tức.
    - Chỉ kích hoạt render SVG Mermaid khi code fence đã hoàn thành hoặc sau một khoảng debounce ổn định cú pháp.

## 4. Cách override đề xuất cho Phase 2 (P2a)

Có 2 hướng tiếp cận:
1. **Hướng A (Khuyên dùng - Custom `code` component trong `MarkdownTextRenderer.tsx`)**:
   - Bắt `if (match && match[1] === "mermaid")` ngay trong `components.code`.
   - Render component chuyên biệt `<MermaidBlock code={code} isStreaming={streaming} />` sử dụng lazy import `mermaid`.
   - **Ưu điểm**: Kiểm soát 100% theme, zoom/pan, xử lý streaming/lỗi cú pháp chưa hoàn chỉnh, và không phụ thuộc vào cấu hình plugin phức tạp hay bundle size của Streamdown core. Chunk `mermaid` được code-split hoàn toàn độc lập.
2. **Hướng B (Streamdown `plugins.mermaid` / `plugins.renderers`)**:
   - Truyền plugin vào `plugins` của Streamdown và nhường quyền xử lý tag `code` khi `language === "mermaid"`.
   - Bất lợi: Vẫn phải cấu hình `MermaidConfig` và giải quyết xung đột với `components.code` override hiện tại.

## 5. Đối chiếu hiện trạng (09/10/2026)

- `MarkdownTextRenderer.tsx` không truyền `plugins` cho `<Streamdown>` và `components.code` bắt mọi khối `language-*`, nên khối `mermaid` hiện đi vào
  `CodeBlock` và hiện như code. Mục D6 cũ của roadmap ("Streamdown tự render") không đúng với code và đã được sửa.
- Test duy nhất nhắc mermaid là `vite-config.test.ts` (quy tắc chunk `markdown-diagrams` cho `streamdown/dist/mermaid-*`). Không có test render sơ đồ.
- `mermaid` 11.16.0 chỉ là phụ thuộc gián tiếp của Streamdown 2.5.0 (`^11.12.2`). `elkjs`, `@mermaid-js/layout-elk`, `@panzoom/panzoom` chưa cài.
- Quyết định cho Phase 2: Hướng A (mục 4). Chưa kiểm chứng: ELK, kích thước chunk. Ghi chú này không kèm ảnh chụp hay log render, trong khi cổng Phase 0.3 của roadmap yêu cầu có bằng chứng.
