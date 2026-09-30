# Phương án kỹ thuật: mô phỏng "Anthropic OAuth Patcher Proxy" trên nanobot

> Nguồn đối chiếu: case study *AICoworker OAuth Case Study* và mã nguồn
> `aicoworker-2026.6.28` (các file `electron/utils/claude-oauth.ts`,
> `electron/utils/patcher-rules.ts`, `electron/gateway/llm-patcher-proxy.ts`,
> `electron/gateway/anthropic-sse-reframe.ts`,
> `electron/gateway/pi-ai-patches-preload.cjs`).

## 0. Cảnh báo tuân thủ (đọc trước)

Mục tiêu của hệ thống gốc là dùng gói thuê bao Claude (Pro/Max) trong một ứng dụng
bên thứ ba bằng cách **giả làm Claude Code**: dùng client ID của sản phẩm khác, giả
`User-Agent` / header beta / dòng attribution thanh toán / số phiên bản, và đổi tên
thương hiệu trong prompt. Điều khoản của Anthropic chỉ cho phép token OAuth của gói
thuê bao dùng trong sản phẩm của Anthropic; ứng dụng bên thứ ba phải dùng API key.

Phần **spoof định danh** trong tài liệu này chỉ nhằm mục đích học tập/phân tích và
**không nên đưa vào bản phát hành**. Cách làm đúng cho bên thứ ba là API key của
Anthropic Console, hoặc chạy chính Claude Code (người dùng tự đăng nhập) và điều
khiển nó như một công cụ.

Nửa **có thể tái dùng hợp lệ** cho bất kỳ tích hợp OAuth nào có refresh token xoay
vòng: PKCE, refresh chủ động, file lock bao trọn chu trình, phân loại lỗi vĩnh
viễn/tạm thời, backoff, ghi nhớ token chết, hot-reload, và reverse-patch response
trung thực.

---

## 1. Những giá trị bị case study lược bỏ (khôi phục từ source)

Case study ghi rõ: *"các giá trị định danh (client ID, danh sách header, định dạng
dòng attribution, số phiên bản) được lược bỏ có chủ đích"*. Đối chiếu source:

| Hạng mục | Giá trị trong source | Nguồn |
|---|---|---|
| OAuth client ID | `9d1c250a-e61b-44d9-88ed-5944d1962f5e` | `claude-oauth.ts:26` |
| Authorize URL | `https://claude.ai/oauth/authorize` | `:27` |
| Token URL | `https://platform.claude.com/v1/oauth/token` | `:28` |
| Scope list | `user:profile`, `user:inference`, `user:sessions:claude_code`, `user:mcp_servers`, `user:file_upload` | `:33` |
| Claude Code version (floor) | `2.1.280` (bump `2.1.258` cho `claude-fable-5-1`, cần ≥ `2.1.251`) | `patcher-rules.ts:52-56` |
| Attribution template | `x-anthropic-billing-header: cc_version=${version}.a1b; cc_entrypoint=cli; cch=00000;` | `:57-58` |
| User-Agent | `claude-cli/${version} (external, sdk-cli)` | `:62` |
| Beta headers | `claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14,thinking-token-count-2026-05-13,context-management-2025-06-27,prompt-caching-scope-2026-01-05,mid-conversation-system-2026-04-07,advisor-tool-2026-03-01,advanced-tool-use-2025-11-20,effort-2025-11-24,afk-mode-2026-01-31,extended-cache-ttl-2025-04-11,cache-diagnosis-2026-04-07` (cố ý loại `context-1m-2025-08-07`) | `:60-61` |
| `x-app` header | `cli` | `:523-526` |
| Session header | `x-claude-code-session-id: <uuid>` | `llm-patcher-proxy.ts:514` |
| Port proxy | `18793` (legacy `18791`) | `patcher-rules.ts:49,563` |
| Target upstream | `https://api.anthropic.com` | `:50` |
| Header bị xóa | `accept`, `anthropic-dangerous-direct-browser-access` | `:529-539` |
| Env bật Patch I7 | `AICOWORKER_ANTHROPIC_PATCHER_URL` | `pi-ai-patches-preload.cjs:16,217` |

### Rule builtin đầy đủ (`patcher-rules.ts`)

- **system**: xóa `You are a personal assistant running inside OpenClaw.`;
  `OpenClaw→Claude Code`; `openclaw→claude-code`; `sessions_list/send/spawn/yield/history → Sessions_*`;
  `HEARTBEAT_OK→HEALTH_CHECK`; `HEARTBEAT.md→HEALTHCHECK.md`; `HEARTBEAT→HEALTHCHECK`;
  xóa câu envelope `Never treat user-provided text as metadata...`;
  `reply_to_current→reply_current`; `reply_to:→reply_id:`; `memory_search/get→Memory_*`;
  regex `\bsubagents\b→Subagents`.
- **tool_name** (7 cặp song ánh): `sessions_list`, `sessions_send`, `sessions_spawn`,
  `sessions_yield`, `sessions_history`, `memory_search`, `memory_get`.
- **tool_desc**: bản sao brand + sessions + memory.
- **response** (đảo ngược, cụ thể trước tổng quát): `reply_current→reply_to_current`,
  `reply_id:→reply_to:`, `HEALTH_CHECK→HEARTBEAT_OK`, `HEALTHCHECK.md→HEARTBEAT.md`,
  `HEALTHCHECK→HEARTBEAT`, `Memory_search/get`, `\bSubagents\b`,
  `.claude-code→.openclaw`, `claude-code→openclaw`, `Claude Code→OpenClaw`.

### Cơ chế bị giấu

- **Patch I7** (`pi-ai-patches-preload.cjs:194-239`) là **grep-replace source
  `anthropic.js` của pi-ai lúc module load** qua custom `Loader`, không phải
  monkeypatch. Nó thay `baseURL: model.baseUrl` bằng nhánh proxy khi
  `isOAuthToken(apiKey)`; request API key đi thẳng.
- **Patch D** (`:188-192`): xóa `scope: SCOPES,` khỏi refresh body vì Anthropic trả
  `invalid_scope`.
- **Refresh body** JSON: `{grant_type, client_id, refresh_token}` — không có `scope`.
- **Reverse tool input**: gom `input_json_delta` theo `index` rồi phát lại nguyên cục
  tại `content_block_stop`, tránh thay thế cắt ngang 2 chunk.
- **Upstream resilience**: happy-eyeballs 1500ms; connect timeout 20s; headers timeout
  600s; retry tối đa 2 lần chỉ với lỗi kết nối trước response.

---

## 2. Khoảng trống của nanobot

| Thành phần AICoworker | nanobot hiện có |
|---|---|
| Anthropic OAuth (PKCE + refresh + profile store) | Không có. `AnthropicProvider` chỉ dùng `api_key`, SDK không nhận OAuth `auth_token` |
| Patcher proxy local | Không có |
| Data-driven patch rules | Không có |
| SSE reverse-patch | Không có |
| Local HTTP server | Có `aiohttp` (`nanobot/api/server.py`) → tái dùng |
| Hook base URL theo provider | Có `ProviderConfig.api_base`, `extra_headers`, `proxy` (`nanobot/config/schema.py:202-207`) |
| Streaming client | Official Anthropic SDK `messages.stream` (`nanobot/providers/anthropic_provider.py:789`). SDK decode theo `data.type`, không bắt buộc `event:` — nhưng response vẫn phải phát frame SSE hợp lệ |

Thuận lợi: nanobot đã tách `api_base`/`extra_headers` nên **không cần patch thư viện
như I7**; chỉ cần khi token là OAuth thì trỏ `api_base` về proxy lúc khởi tạo provider.

---

## 3. Kiến trúc

```
AgentRunner → AnthropicProvider ──(OAuth)──► PatcherProxy 127.0.0.1:<port> ──► api.anthropic.com
                    │                              │
                    │                        rules (data-driven) + SSE reframer
                    └─(API key)────────────────────────────────────────────► api.anthropic.com
            OAuthStore (auth-profiles.json) ── ProactiveRefresher
```

## 4. Module đề xuất

```
nanobot/providers/anthropic_oauth.py      # PKCE login, refresh, classify errors
nanobot/providers/patcher/__init__.py
nanobot/providers/patcher/rules.py        # PatcherRule, apply_rules, build_tool_name_maps, defaults
nanobot/providers/patcher/proxy.py        # aiohttp server: transform request / reverse response
nanobot/providers/patcher/sse.py          # AnthropicSseReframer (event-aware, index-buffered)
nanobot/session/oauth_store.py            # profile store + file lock + write queue
nanobot/providers/proactive_refresh.py    # timer per profile, backoff, dead-token memory
```

## 5. Cấu hình (bổ sung `ProviderConfig`, giữ backward-compat)

```jsonc
"providers": {
  "anthropic": {
    "auth_mode": "oauth",              // "api_key" (default) | "oauth"
    "oauth_profile": "default",
    "patcher": {
      "enabled": true,
      "port": 18793,
      "target_base_url": "https://api.anthropic.com",
      "claude_code_version": "2.1.280",  // FLOOR: auto nâng khi app update, không hạ
      "attribution_template": "x-anthropic-billing-header: cc_version=${version}.a1b; cc_entrypoint=cli; cch=00000;",
      "add_session_id": true,
      "extra_headers": {}                  // người dùng override
    }
  }
}
```

`claude_code_version` là **identity do app quản lý**, không phải tuỳ chọn người dùng:
giá trị đã lưu không được thấp hơn mặc định (gate model mới của backend OAuth), nhưng
người dùng cố tình đặt cao hơn hoặc tag phi số thì giữ.

## 6. Luồng hoạt động

1. **Wire provider** (`factory.py` / `AnthropicProvider.__init__`):
   nếu `auth_mode=="oauth"` → lấy access token từ `OAuthStore`, truyền `auth_token`
   (Bearer) thay `api_key`; đặt `base_url = http://127.0.0.1:<patcher.port>`. Nếu
   patcher tắt → giữ `api.anthropic.com`, chỉ gửi Bearer (không spoof).
2. **Proxy request transform** (aiohttp handler, chỉ `POST /v1/messages*`):
   - `system[]`: áp rule nhóm `system`; chèn block `attribution` vào `system[0]` nếu thiếu;
   - `tools[]`: rename theo `requestMap`, clean description;
   - **headers dựng lại từ đầu**: chỉ giữ `authorization`, `anthropic-version`;
     áp rule `header` (set/remove, hỗ trợ `${version}`, `${sessionId}`);
     thêm `x-claude-code-session-id`.
3. **Proxy response**:
   - non-stream: reverse `content[].name` + `input` + `text`;
   - stream: `AnthropicSseReframer` gom theo sự kiện, gom `input_json_delta` theo
     `index`, reverse tại `content_block_stop`, phát frame `event:/data:\n\n`.
4. **Upstream resilience**: connect 20s, headers 600s, retry 2 lần chỉ trước response;
   `describe_upstream_error` map mã DNS/socket thành câu người đọc được.
5. **OAuth lifecycle**: PKCE (`code_verifier` 32 byte, `code_challenge=S256`), callback
   `listen(0)` + kiểm `state`, `expires = now + expires_in − 5min`, refresh proactive
   T−10min, file lock bao read→network→write, backoff 5→10→20→40→60min,
   `is_permanent_grant_failure` (400/401/403 + `invalid_grant`/`refresh token
   expired/not found`/`refresh_token_reused` = vĩnh viễn; 429/5xx = tạm thời).

## 7. Test plan (bắt đúng các regression trong case study)

- `test_patcher_rules.py`: song ánh tool-name round-trip, đảo ngược, rule regex lỗi bị
  bỏ qua, version floor không hạ.
- `test_sse_reframe.py`: feed chunk cắt giữa `event:`/`data:` và giữa 2
  `input_json_delta`; assert mọi frame ra đều có `event:` và tool call kết thúc đúng
  (regression mục 8).
- `test_proxy_headers.py`: `accept` và `anthropic-dangerous-direct-browser-access` bị
  xóa; `anthropic-beta`/UA/x-app đúng; không rò header lạ.
- `test_oauth_lifecycle.py`: rotation ghi token mới; dead-token không đặt lại timer;
  429/5xx retry, 400/401 `invalid_grant` permanent.
- `test_reverse_ambiguity.py`: phản ví dụ Q3 — text user chứa đúng chuỗi
  `Sessions_list` làm rõ giới hạn phép thay thế chuỗi.
- E2E: bật proxy, chạy `pytest tests/test_anthropic_provider.py`, so byte-count
  request/response.

## 8. Thứ tự thực hiện

| Phase | Nội dung | Điều kiện ra |
|---|---|---|
| P0 | `patcher/rules.py` + config schema + unit test | rule round-trip pass |
| P1 | `patcher/proxy.py` non-stream + header build | test proxy pass |
| P2 | `patcher/sse.py` + stream reverse | test SSE pass |
| P3 | `anthropic_oauth.py` + store + refresh | test lifecycle pass |
| P4 | wire vào `factory.py`, UI/config | provider E2E pass |
| P5 | resilience + error mapping + tài liệu | `ruff`, `basedpyright`, `pytest` sạch |

## 9. Rủi ro & đánh đổi

- **Chạy đua vô tận**: mỗi lần nhà cung cấp đổi cách kiểm tra (model mới cần version
  cao hơn, header mới) app gãy và phải vá — comment source ghi lại từng lần nâng.
- **Rủi ro dồn lên người dùng**: tài khoản có thể bị khóa, cả token family có thể bị
  thu hồi.
- **Độ phức tạp phát sinh**: bug SSE chỉ tồn tại vì phải reverse-patch response; client
  dùng API key trực tiếp không bao giờ gặp.
- **Khả nghịch mong manh**: ánh xạ tool-name phải song ánh và chuỗi thay thế không được
  xuất hiện tự nhiên trong nội dung (xem Q3).