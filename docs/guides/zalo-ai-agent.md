# Build a Zalo AI Agent with nanobot

This guide connects nanobot to Zalo through the `zalo` channel. The channel
links a **personal Zalo account** with QR login, using `zca-js` (the same
unofficial Web protocol as OpenClaw's `zalouser` extension). It uses the same
nanobot agent runtime, tools, memory, and workspace as the CLI and WebUI.

> **Warning:** Using Zalo automation may result in account suspension or ban.
> This is an unofficial integration. Use it at your own risk.

## What this guide builds

- Zalo optional dependencies installed
- a linked Zalo personal-account session
- the `zalo` channel enabled in `config.json`
- one pairing-approved Zalo sender

## Prerequisites

- A working local nanobot reply:

```bash
nanobot agent -m "Hello!"
```

- [Node.js 18+](https://nodejs.org/) and npm on the gateway host (`zca-js` runs
  as a local sidecar).
- A Zalo account and the Zalo mobile app (to scan the login QR).
- A machine that can keep `nanobot gateway` running.

## Enable the Zalo channel

```bash
nanobot plugins enable zalo
nanobot channels login zalo
```

Scan the QR code from the Zalo app on your phone. You can also start the same
QR flow from **Settings → Channels → Zalo** in the WebUI.

Merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "zalo": {
      "enabled": true,
      "groupPolicy": "mention"
    }
  }
}
```

Omitting `allowFrom` enables pairing-only mode for private chats. `groupPolicy`
defaults to `"mention"` so group chats stay quiet until the bot is addressed.

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

## Test a message

Send the bot a private Zalo message. It should return a pairing code.
Approve it from a trusted local surface:

```bash
nanobot agent -m "/pairing approve ABCD-EFGH"
```

Send the message again after approval.

## Security notes

- Treat `~/.nanobot/zalo-auth/credentials.json` as account access (mode 0700).
- Prefer pairing-only mode for first setup. Add `allowFrom` only when you want a
  static allowlist of numeric Zalo user IDs.
- Keep `groupPolicy` as `"mention"` before adding the account to groups.
- Avoid `allowFrom: ["*"]` unless the bot is intentionally public or isolated.
- Re-login with `nanobot channels login zalo --force` if the session expires.

## Troubleshooting

- If QR linking fails, rerun `nanobot channels login zalo`.
- If startup says Node.js is missing, install Node 18+ and npm, then retry.
- If a first private message returns a pairing code, approve it before testing
  normal replies.
- Group messages are ignored unless the bot is mentioned when `groupPolicy` is
  `"mention"`.

## Next: memory, automations, MCP tools

- [Chat Apps reference](../chat-apps.md)
- [Pairing](../configuration.md#pairing)
- [Secure local AI agent](./secure-local-ai-agent.md)
- [Deployment](../deployment.md)
