# Provider `google-antigravity` (Antigravity OAuth) — thiết kế

> Trạng thái: **đã triển khai** (P0–P5).
> Tiền đề: hạ tầng Anthropic OAuth Patcher Proxy (`docs/plan-anthropic-patcher-proxy.md`).
> Nguồn đối chiếu: `aicoworker-2026.6.28` + bundle `pi-ai`
> (`…/node_modules/@mariozechner/pi-ai/dist/providers/google-gemini-cli.js`,
> `…/dist/utils/oauth/google-antigravity.js`, `…/dist/providers/google-shared.js`)
> và bản cài `agy` trên máy (`~/.gemini/antigravity-cli`).

## 0. Cảnh báo tuân thủ

Provider **mạo danh client `agy`** (User-Agent, `Client-Metadata`, project UUID, client
secret dùng chung của Gemini CLI) để dùng gói thuê bao Google trên ứng dụng bên thứ ba.
Có thể **vi phạm điều khoản của Google** và rủi ro khoá tài khoản. Cách hợp lệ: Google AI
Studio / Vertex AI bằng API key. Mặc định **tắt**; chỉ dùng trên tài khoản bạn sở hữu.

## 1. Kiến trúc đã chọn: direct provider + adapter rules (KHÔNG proxy)

```
AgentRunner → AntigravityProvider ──(OAuth Bearer + agy headers)──► daily-cloudcode-pa.googleapis.com
                    ├─ AntigravityAdapter (data-driven identity/override)
                    └─ AntigravityOAuthStore (access/refresh/expires/project_id/email) ── ProactiveRefresher
```

pi-ai dựng request + set header agy ngay trong client (không proxy); aicoworker vẫn phải vá
thêm source (`AGE`/`AGM`/`AGS`) để sống sót qua thay đổi của Google ⇒ độ bền đến từ **lớp
override data-driven**, không phải proxy. Vì ta sở hữu client, mọi thứ proxy làm được đều
làm inline, tránh thêm listener/port + SSE reframing.

## 2. Thành phần

| Thành phần | File |
|---|---|
| Adapter (hằng số + `AntigravityAdapter` + `build_adapter`) | `nanobot/providers/antigravity_adapter.py` |
| OAuth (PKCE, storage + lock, refresh, login flow, project discovery, catalog, refresher, status listener) | `nanobot/providers/antigravity_oauth.py` |
| Provider (convert messages/tools, dựng wrapper, SSE, endpoint fallback) | `nanobot/providers/antigravity_provider.py` |
| Registry spec `google_antigravity` (`backend="antigravity"`, `is_oauth=True`) | `nanobot/providers/registry.py` |
| `AntigravitySettings` + `ProviderConfig.antigravity` + `ProvidersConfig.google_antigravity` | `nanobot/config/schema.py` |
| Factory nhánh `antigravity` + OAuth signature | `nanobot/providers/factory.py` |
| Catalog dispatch | `nanobot/providers/oauth_model_catalog.py` |
| CLI `provider login/logout google-antigravity` | `nanobot/cli/provider.py` |
| WebUI status/login/complete/logout | `nanobot/webui/settings_models.py` + `webui/src/**` |
| Lifecycle refresher | `nanobot/cli/gateway_runtime.py`, `nanobot/cli/commands.py` |
| Test | `tests/providers/test_antigravity_{adapter,oauth,provider,wiring}.py` |

## 3. Wire format (đã xác minh)

- **Endpoint**: `https://daily-cloudcode-pa.googleapis.com` + fallback `https://cloudcode-pa.googleapis.com`
  (đổi trong `providers.google_antigravity.antigravity.endpoint` / `endpointFallbacks`).
- **Headers**: `Authorization: Bearer`, `Content-Type: application/json`, `Accept: text/event-stream`,
  `User-Agent: antigravity/<version> <os>/<arch>`, `Client-Metadata`; thêm
  `anthropic-beta: interleaved-thinking-2025-05-14` cho model `claude-*` có reasoning.
- **Body**: `{project, model, request:{contents, systemInstruction, generationConfig, tools, toolConfig},
  requestType:"agent", userAgent:"antigravity", requestId}`. `systemInstruction` bọc thêm
  prelude Antigravity + câu `Please ignore following [ignore]…[/ignore]`.
- **Tools**: `parametersJsonSchema`, riêng `claude-*` dùng `parameters`.
- **Thinking**: Gemini-3 → `thinkingLevel` LOW/MEDIUM/HIGH; cũ hơn → `thinkingBudget`;
  tắt → level thấp nhất (Gemini 3) hoặc budget 0 (2.x).
- **SSE**: mỗi `data:` là `{"response": <GenerateContentResponse>}`; part `text`/`thought`/
  `functionCall`; usage từ `usageMetadata` (trừ `cachedContentTokenCount`).

## 4. OAuth (đã xác minh)

- Google OAuth2 + PKCE S256, form-encoded; redirect cố định `http://localhost:51121/oauth-callback`.
- Client id/secret dùng chung của Gemini CLI; scopes gồm `.../auth/aicode`.
- Project: `loadCodeAssist` → mượn cache `agy` → fallback. Token lưu tại
  `~/.nanobot/auth/antigravity.json` (`{access, refresh, expires, project_id, email}`) với file lock.
- `ProactiveRefresher` refresh trước hạn; status listener phát `refreshed`/`reauth_required`.

## 5. Dùng

```bash
nanobot provider login google-antigravity --set-main
```

```jsonc
{
  "providers": {
    "google_antigravity": {
      "antigravity": { "userAgentVersion": "1.21.9", "endpoint": "https://daily-cloudcode-pa.googleapis.com" }
    }
  },
  "agents": { "defaults": { "model": "google-antigravity/gemini-3-pro-low", "provider": "google_antigravity" } }
}
```

> Dùng tiền tố `google-antigravity/` trong model. Model trần `gemini-*` sẽ khớp spec `gemini`
> trước (keyword "gemini") nên phải định tuyến qua prefix hoặc `provider`.

## 6. Rủi ro

- Google đổi UA version / endpoint / model id / scope → chỉnh trong `antigravity` config, không cần sửa code.
  Thay đổi *cấu trúc* wrapper vẫn cần code.
- Catalog lấy từ `fetchAvailableModels` (gồm cả Claude/GPT-OSS có `displayName`); bỏ `tab_*` và model ẩn.
- Rủi ro ToS/tài khoản như §0.
