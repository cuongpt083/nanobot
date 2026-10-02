# Ideas: Antigravity OAuth "agy mock" patcher proxy cho nanobot

> Trạng thái: **ideas / pre-spec** — các câu hỏi O1–O5 đã được giải quyết và thiết kế
> đã được triển khai; xem [`docs/plan-google-antigravity-provider.md`](./plan-google-antigravity-provider.md).
> Ghi chú: thiết kế triển khai chọn **direct provider + adapter rules (không proxy)** thay vì
> local patcher proxy như bản ideas này; lý do & đánh đổi ở §1.1 của tài liệu triển khai.
> Nguồn đối chiếu: mã nguồn `aicoworker-2026.6.28`
> (`electron/utils/antigravity-oauth.ts`, `electron/gateway/pi-ai-patches-preload.cjs`,
> `electron/gateway/manager.ts`, `gateway-source/src/agents/models-config.providers.google-antigravity.test.ts`)
> và khảo sát `nanobot`.
>
> ⚠️ Mục đích hệ thống gốc là dùng gói thuê bao Google (Antigravity/Gemini AI) trong ứng dụng
> bên thứ ba bằng cách giả làm client `agy`. Việc này có thể vi phạm điều khoản của Google.
> Tài liệu phục vụ học tập/nghiên cứu tương thích trên tài khoản bạn sở hữu. Cách hợp lệ cho
> bên thứ ba là dùng Google AI Studio / Vertex AI bằng API key hoặc service account.

---

## 1. Ý tưởng

Xây dựng một **provider Antigravity OAuth** cho nanobot, trong đó mọi request chat đi qua một
**patcher proxy cục bộ** đóng vai "client `agy`" y như `Anthropic OAuth Patcher Proxy` đã làm
cho Claude Code:

```
AgentRunner → AntigravityProvider ──(OAuth)──► AgyPatcherProxy 127.0.0.1:<port> ──► daily-cloudcode-pa.googleapis.com
                     │                                      │
                     │                            rewrite header/body + reverse response
                     └─(API key / Vertex)──────────────────────────────────────────────► Google API
              AntigravityOAuthStore (token + project uuid) ── ProactiveRefresher
```

Mục tiêu:
- Đăng nhập Google OAuth một lần, tự refresh token nền, giữ phiên sống 24/7.
- Mọi request tới `cloudcode-pa` được sửa cho **không thể phân biệt với `agy` trên đường truyền**
  (User-Agent, Client-Metadata, project, model id, request metadata).
- Response được reverse-patch để runtime nanobot hiểu bình thường.

---

## 2. Khác biệt cốt lõi so với Anthropic patcher proxy

Đây là lý do **không port 1-1** được:

| Khía cạnh | Anthropic | Google Antigravity |
|---|---|---|
| Giao thức | Anthropic Messages API (JSON + SSE `event:`) | Gemini/cloudcode `v1internal:generateContent/streamGenerateContent` (JSON + SSE `data:`) |
| Endpoint | `api.anthropic.com` | `daily-cloudcode-pa.googleapis.com` (KHÔNG `.sandbox.`) |
| Client ID | Claude Code (`9d1c…`) | Gemini CLI dùng chung (`1071006060591-…`; cấu hình qua env/config, không ship trong source) |
| Client secret | không có | **có** (`GOCSPX-…`) |
| Redirect | loopback port động | aicoworker: `localhost:51121` cố định; URL bạn quan sát: `https://antigravity.google/oauth-callback` |
| "project" | không có | **UUID do client sinh**, phải được đăng ký qua `loadCodeAssist`; UUID lạ → 403 |
| Mạo danh chính | header beta/UA/attribution, đổi branding prompt | **`User-Agent: antigravity/<ver> <os>/<arch>`** + `Client-Metadata` + project + model id |
| Cách aicoworker làm | HTTP proxy (`llm-patcher-proxy.ts`) | **KHÔNG proxy** — patch pi-ai (`AGE`, `AGM`) + env `PI_AI_ANTIGRAVITY_VERSION=1.0.0` |
| Điểm cần cài local | không | **có ích**: mượn project UUID đã đăng ký của `agy` |

Kết luận: với Antigravity, "patcher proxy" là **thiết kế mới**, và **cài `agy` local có giá trị
thật** (để mượn `project` — khác Anthropic).

---

## 3. Bề mặt mạo danh `agy` (đã khôi phục từ source)

### 3.1 Header quan trọng

```http
Authorization: Bearer <access_token>
Content-Type: application/json
User-Agent: antigravity/1.0.0 <platform>/<arch>      # CRITICAL — quyết định tier
Client-Metadata: {"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}
```

Comment trong `antigravity-oauth.ts` xác nhận:
- UA `google-api-nodejs-client/...` → tier "Gemini Code Assist" (cần GCP project thật).
- UA `antigravity/X.Y.Z <os>/<arch>` → tier "Antigravity" (nhận UUID client sinh / mượn từ agy).
- Version hiện tại agy báo `1.0.0`; override qua env `PI_AI_ANTIGRAVITY_VERSION`.

### 3.2 OAuth

- `AUTH_URL`: `https://accounts.google.com/o/oauth2/v2/auth`
- `TOKEN_URL`: `https://oauth2.googleapis.com/token`
- `REVOKE_URL`: `https://oauth2.googleapis.com/revoke`
- `USERINFO_URL`: `https://www.googleapis.com/oauth2/v1/userinfo?alt=json`
- PKCE S256; token endpoint nhận `application/x-www-form-urlencoded` (khác Anthropic JSON).
- Scopes (theo `antigravity-oauth.ts`): `openid`, `email`, `profile`,
  `.../auth/cloud-platform`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`,
  `.../auth/aicode` (**quan trọng** — thiếu → 403 `cloudaicompanion.companions.generateCode`),
  `.../auth/cclog`, `.../auth/experimentsandconfigs`.
- Redirect: aicoworker dùng `http://localhost:51121/oauth-callback` cổng cố định (Google yêu cầu
  URI đã đăng ký). URL bạn quan sát dùng `https://antigravity.google/oauth-callback` ⇒ phiên bản
  agy mới hơn dùng web-redirect. **Cần chốt dùng redirect nào** (xem §6).

### 3.3 Project ID

- `resolveProjectId()`:
  1. dùng lại `projectId` của profile cũ;
  2. nếu chưa có → **mượn từ agy local** (theo thứ tự: `~/.gemini/antigravity-cli/cache/default_project_id.txt`,
     `~/.antigravitycli/<UUID>.json`, `~/.gemini/config/projects/*.json`);
  3. không có → `randomUUID()` (gần như chắc chắn 403, log rõ để user biết cần cài agy).
- Sau đó POST `v1internal:loadCodeAssist` với body:
  ```json
  {"cloudaicompanionProject":"<id>","metadata":{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}}
  ```
  để đăng ký/làm mới; server có thể trả `cloudaicompanionProject` thay thế.

### 3.4 Endpoint chat

```
POST https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse
POST https://daily-cloudcode-pa.googleapis.com/v1internal:generateContent
POST https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist
```

### 3.5 Model ID

- pi-ai/agy dùng tên có hậu tố routing; ví dụ `gemini-3-pro` → `gemini-3-pro-low`;
  `gemini-3.1-pro-high` bị backend trả 400 → đổi sang `gemini-pro-agent`.
- aicoworker có Patch AGM remap id. Cần bảng map tương ứng trong proxy.

### 3.6 Body chat (cần xác minh)

Wrapper của `streamGenerateContent` nằm trong package npm `pi-ai` (không có trong source
aicoworker), nên **chưa đọc được chính xác**. Dự kiến gồm các field kiểu:

```jsonc
{
  "project": "<projectId>",
  "model": "<normalizedModelId>",
  "request": { "contents": [...], "systemInstruction": ..., "tools": [...], "generationConfig": {...} },
  "requestId": "<uuid>",
  "requestType": "agent",      // hoặc "chat"
  "userAgent": "antigravity",
  "user_prompt_id": "<uuid>"
}
```

> Việc xác minh shape này là một **hạng mục điều tra riêng** (xem §7, O1): đọc log agy
> `~/.gemini/antigravity-cli/log/cli-*.log` hoặc cài `pi-ai` để đọc source, trước khi viết client.

---

## 4. Cách thức hoạt động dự kiến

### 4.1 Đăng nhập
1. CLI/WebUI khởi tạo PKCE + callback server.
2. Mở URL authorize tới Google với client_id/scope/redirect đã chốt.
3. Nhận `code` → đổi token (form-encoded) → lưu `{access, refresh, expires, project_id, email}`.
4. Gọi `loadCodeAssist` để đăng ký project; lưu lại project thực tế.

### 4.2 Refresh chủ động
- Tái dùng mô hình `ProactiveRefresher` của Anthropic: refresh trước hạn, file lock liên tiến trình,
  phân loại lỗi vĩnh viễn/tạm thời, backoff, ghi nhớ token chết.
- Google refresh token cũng xoay vòng và có thể bị revoke ⇒ cùng nguyên tắc "một nguồn sự thật".

### 4.3 Request qua proxy
1. Provider (OAuth mode) trỏ `base_url` về `http://127.0.0.1:<port>`.
2. Proxy:
   - dựng lại header: giữ `Authorization`, set `User-Agent` agy, `Client-Metadata`, xóa header
     nhận diện client khác;
   - inject `project`, `requestId`/`user_prompt_id` (uuid mỗi request), `requestType`, `userAgent`;
   - normalize model id theo bảng map; có thể áp rule body (system/contents) nếu cần.
3. Forward tới `daily-cloudcode-pa.googleapis.com` (connect timeout riêng, headers timeout cao,
   retry chỉ trước khi có response — học từ proxy Anthropic).

### 4.4 Reverse response
- Gemini SSE là `data: {json}` (không có `event:`); cần re-framer riêng nhưng đơn giản hơn.
- Reverse model id (`gemini-pro-agent` → tên catalog nanobot) và các trường đã đổi nếu có.
- Bỏ yêu cầu `event:` — nhưng vẫn phải phát frame hợp lệ cho client Google SDK/nanobot.

### 4.5 Catalog model
- `v1internal` có `fetchAvailableModels`; proxy/provider lọc và chuẩn hoá về catalog nanobot.

---

## 5. Thành phần cần can thiệp trên nanobot

| # | Thành phần | File dự kiến | Việc |
|---|---|---|---|
| 1 | OAuth Antigravity | `nanobot/providers/antigravity_oauth.py` | PKCE, token exchange (form-encoded), refresh, storage `auth/antigravity.json`, project resolve (`loadCodeAssist` + borrow từ agy), `AnthropicOAuthLoginFlow`-style flow |
| 2 | Provider | `nanobot/providers/antigravity_provider.py` | client `cloudcode-pa`, convert messages → Gemini `contents`, streaming SSE, tool calls, thinking |
| 3 | Patcher engine | mở rộng `nanobot/providers/patcher/` (rules đã data-driven) | thêm category/rule cho Gemini; hoặc tách `patcher/agy_rules.py` |
| 4 | Proxy | `nanobot/providers/patcher/agy_proxy.py` | rewrite header/body agy, forward, reverse; resilience |
| 5 | SSE re-framer | `nanobot/providers/patcher/agy_sse.py` | Gemini-style `data:` frames |
| 6 | Registry | `nanobot/providers/registry.py` | `ProviderSpec` `google_antigravity` (backend mới `antigravity`, `is_oauth`) |
| 7 | Config | `nanobot/config/schema.py` | `AgyPatcherSettings` (port, endpoint, ua version, client id/secret, redirect…) + `ProviderConfig.auth_mode` |
| 8 | Factory | `nanobot/providers/factory.py` | build provider + lazy start proxy (như Anthropic) |
| 9 | CLI | `nanobot/cli/provider.py` | `provider login/logout google-antigravity` |
| 10 | WebUI | `nanobot/webui/settings_models.py`, `webui/src/lib/provider-brand.ts`, `ProviderSettings.tsx` | OAuth status/login/complete/logout, brand, advanced fields |
| 11 | Lifecycle | `nanobot/cli/gateway_runtime.py`, `nanobot/cli/commands.py` | start/stop `ProactiveRefresher` cho Antigravity |
| 12 | Setup toolchain (tuỳ chọn) | `scripts/setup_dev_toolchain.*` | cài `agy` để mượn project id + tiện onboarding (không bắt buộc cho login) |
| 13 | Tài liệu/test | `docs/`, `tests/providers/` | plan + test như Anthropic |

Có thể **tái dùng tối đa hạ tầng đã có**: `ProactiveRefresher` pattern, file lock + atomic write,
data-driven rules engine, proxy resilience constants, `AnthropicOAuthLoginFlow` shape.

---

## 6. Câu hỏi mở / quyết định cần chốt

| # | Câu hỏi | Lựa chọn | Khuyến nghị |
|---|---|---|---|
| Q1 | Redirect URI | `localhost:51121` (aicoworker) vs `https://antigravity.google/oauth-callback` (agy mới) | Điều tra agy đang cài trên máy để lấy chính xác; có thể hỗ trợ cả hai |
| Q2 | Bắt buộc cài `agy` local? | Không (login vẫn được, project random → 403) vs Có (mượn project chắc chắn chạy) | Không bắt buộc, nhưng setup script mượn project nếu có; cảnh báo rõ khi thiếu |
| Q3 | Backend provider | `openai_compat` giả lập vs backend `antigravity` mới | Backend mới — vì giao thức Gemini cloudcode khác hoàn toàn |
| Q4 | Proxy vs inline rewrite | HTTP proxy (đúng yêu cầu) vs rewrite trong client | Proxy, để đồng bộ kiến trúc với Anthropic |
| Q5 | Tái dùng rules Anthropic | Chung `patcher/rules.py` vs tách `agy_rules.py` | Tách module rule để không lẫn khái niệm Anthropic/Gemini, nhưng dùng chung engine |
| Q6 | Phạm vi model | Chỉ Gemini vs Gemini + Claude-on-Antigravity | Bám catalog `fetchAvailableModels`, không hardcode |

---

## 7. Điều tra cần làm trước khi viết spec

- **O1** — Xác minh body wrapper `streamGenerateContent`/`generateContent` (đọc log agy,
  hoặc cài `pi-ai`/`@mariozechner/*` để đọc source provider Antigravity).
- **O2** — Xác minh redirect + client_id/secret mà agy bản đang cài dùng (introspect token qua
  `https://oauth2.googleapis.com/tokeninfo?access_token=…`, như comment aicoworker đã làm).
- **O3** — Xác minh danh sách scope thực tế và yêu cầu `aicode`.
- **O4** — Xác minh vị trí file project UUID trên máy này (Windows) — agy có thể không tạo symlink.
- **O5** — Xác minh SSE shape của `streamGenerateContent?alt=sse` (data-only hay có event).

---

## 8. Rủi ro

- **Vi phạm điều khoản**: mạo danh client `agy`, dùng client secret của người khác, mượn project UUID.
- **Chạy đua vô tận**: Google đổi UA/version/model/endpoint → phải vá liên tục (aicoworker đã bump
  version nhiều lần).
- **Rủi ro tài khoản**: có thể bị hạn chế/khóa; project UUID mượn có thể hỏng.
- **Phức tạp**: giao thức Gemini cloudcode nội bộ, không tài liệu hoá công khai; wrapper body chưa
  xác minh được từ source hiện có.

---

## 9. Bước tiếp theo

Sau khi chốt §6 + hoàn tất §7, viết design doc đầy đủ (theo brainstorming) rồi plan triển khai
theo phase giống `docs/plan-anthropic-patcher-proxy.md`:
P0 OAuth+project → P1 provider client → P2 proxy+SSE → P3 registry/config/CLI/WebUI → P4 lifecycle → P5 tests/docs.
