# Plan: thông báo trạng thái Anthropic OAuth lên WebUI

> Trạng thái: đã được duyệt. Mục tiêu: người dùng thấy rõ khi token Anthropic OAuth
> được refresh thành công và khi cần đăng nhập lại.

## Phạm vi

- Phát 2 trạng thái: `refreshed` (thành công) và `reauth_required` (refresh token chết / hết hạn).
- Kênh: event WebSocket server→client mới `oauth_status_updated`, broadcast tới mọi WebUI socket đã xác thực.
- UI: `refreshed` → toast tạm; `reauth_required` → banner persistent, có nút mở Settings → Models.
- Kèm 2 sửa lỗi liên quan:
  - Refresher được start cả khi chưa có token (bắt được login sau khi gateway đã chạy).
  - `AnthropicProvider` map reauth → `error_kind="oauth_auth_required"` để tín hiệu cấp-turn hoạt động.

## Task

- **T-P0** — `anthropic_oauth.py`: thêm listener registry (`add_anthropic_oauth_listener`) + phát
  `refreshed`/`reauth_required` (dedup theo refresh token). `start_proactive_refresher` luôn start.
- **T-P1** — `anthropic_provider.py`: `_handle_error` dò `__cause__` để nhận
  `AnthropicOAuthReauthRequiredError` → `error_kind="oauth_auth_required"`, `error_should_retry=False`.
- **T-P2** — `channels/websocket/runtime.py`: `send_oauth_status_updated(...)` broadcast.
- **T-P3** — `cli/gateway_runtime.py`: đăng ký listener → schedule broadcast; huỷ khi shutdown.
- **T-P4** — WebUI: `types.ts` thêm event; `nanobot-client.ts` thêm `onOAuthStatus`;
  component `OAuthStatusNotice` + i18n (en/vi).
- **T-P5** — Tests: pytest (listener, broadcaster, provider error-kind, refresher start) + vitest.

## Kiểm chứng

- `uv run --no-sync basedpyright`, `ruff check`, `pytest tests/providers`.
- `bun run test` (NODE_ENV=test) cho vitest, `tsc`, eslint.
