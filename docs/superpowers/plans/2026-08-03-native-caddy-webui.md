# Native Caddy WebUI Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native Caddy configuration and Bash utility for an HTTP-only nanobot WebUI endpoint on a private VPN.

**Architecture:** Caddy accepts HTTP at `NANOBOT_LISTEN`, with automatic HTTPS disabled, and proxies HTTP/WebSocket traffic to `127.0.0.1:8765`. A Bash wrapper renders the placeholder, validates the result, and controls `caddy.service` through systemd.

**Tech Stack:** Caddyfile, Bash, systemd, Ubuntu/Debian.

## Global Constraints

- No TLS certificates or automatic HTTPS.
- nanobot stays bound to `127.0.0.1:8765`.
- `NANOBOT_LISTEN` must be `host:port`, such as `10.8.0.10:8080`.
- The script does not install packages, open firewall ports, or modify nanobot configuration.
- A non-empty `channels.websocket.tokenIssueSecret` is required before VPN exposure.

---

### Task 1: Add the HTTP-only Caddy configuration

**Files:**
- Create: `deploy/caddy/Caddyfile.nanobot`
- Test: Caddy's built-in validation after replacing `__NANOBOT_LISTEN__`.

**Interfaces:**
- Consumes: the `NANOBOT_LISTEN` value rendered by Task 2.
- Produces: HTTP and WebSocket proxying to `127.0.0.1:8765`.

- [ ] **Step 1: Verify the intended test initially fails**

Run `sudo caddy validate --config deploy/caddy/Caddyfile.nanobot --adapter caddyfile` before the file exists. Expected: non-zero exit.

- [ ] **Step 2: Add the minimal Caddyfile**

```caddyfile
{
    auto_https off
}

http://__NANOBOT_LISTEN__ {
    reverse_proxy 127.0.0.1:8765 {
        header_up Host {host}
        header_up X-Forwarded-Proto {scheme}
    }
}
```

- [ ] **Step 3: Validate a rendered file**

Run `sed 's|__NANOBOT_LISTEN__|10.8.0.10:8080|g' deploy/caddy/Caddyfile.nanobot | sudo tee /tmp/nanobot.Caddyfile >/dev/null` followed by `sudo caddy validate --config /tmp/nanobot.Caddyfile --adapter caddyfile`. Expected: success.

- [ ] **Step 4: Commit**

Run `git add deploy/caddy/Caddyfile.nanobot && git commit -m "feat: add internal caddy webui proxy config"`.

### Task 2: Add the Caddy systemd management utility

**Files:**
- Create: `scripts/caddy-webui.sh`
- Test: `bash -n scripts/caddy-webui.sh`.

**Interfaces:**
- Consumes: `install|start|stop|restart|status|validate|logs`; `install` consumes `NANOBOT_LISTEN`.
- Produces: `/etc/caddy/Caddyfile` and caddy systemd lifecycle operations.

- [ ] **Step 1: Verify the initial test fails**

Run `bash -n scripts/caddy-webui.sh` before the script exists. Expected: non-zero exit.

- [ ] **Step 2: Implement the utility**

Use `set -euo pipefail`; reject missing/unknown actions; resolve repository root from the script location; require Caddy and systemd; require root and a non-empty `NANOBOT_LISTEN` only for install; replace only the known placeholder; validate a temporary config before moving it to `/etc/caddy/Caddyfile`; enable/reload Caddy. Map the remaining actions to `systemctl` and `journalctl`.

- [ ] **Step 3: Verify**

Run `bash -n scripts/caddy-webui.sh` and `scripts/caddy-webui.sh invalid-action`. Expected: syntax success; invalid action exits non-zero and prints usage.

- [ ] **Step 4: Commit**

Run `git add scripts/caddy-webui.sh && git commit -m "feat: add caddy webui management script"`.

### Task 3: Document Debian/Ubuntu deployment and operation

**Files:**
- Create: `deploy/caddy/README.md`
- Test: documentation acceptance search.

**Interfaces:**
- Consumes: native Caddy installation and Task 2's utility.
- Produces: copyable installation, security, deployment, and operation instructions.

- [ ] **Step 1: Define acceptance checks**

The guide must include native Caddy installation, `tokenIssueSecret`, `NANOBOT_LISTEN`, install/status actions, the HTTP URL, and VPN/firewall restriction.

- [ ] **Step 2: Write the guide**

Include `sudo apt install -y caddy`, `export NANOBOT_LISTEN='10.8.0.10:8080'`, `sudo -E ./scripts/caddy-webui.sh install`, and `./scripts/caddy-webui.sh status`. State that clients open the HTTP VPN address while nanobot remains on `127.0.0.1:8765`.

- [ ] **Step 3: Verify documentation coverage**

Run `rg -n "apt install|tokenIssueSecret|NANOBOT_LISTEN|install|status|http://|VPN" deploy/caddy/README.md`. Expected: every required topic is present.

- [ ] **Step 4: Commit**

Run `git add deploy/caddy/README.md && git commit -m "docs: explain native caddy webui deployment"`.
