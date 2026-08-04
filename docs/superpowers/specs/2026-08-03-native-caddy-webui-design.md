# Native Caddy reverse proxy for nanobot WebUI

## Goal

Provide a native Caddy deployment for a nanobot WebUI on Ubuntu or Debian over
an internal VPN. Caddy is the only listener reachable over the VPN; nanobot
remains bound to `127.0.0.1:8765`.

## Deliverables

- `deploy/caddy/Caddyfile.nanobot`: HTTP virtual host with a listen address and
  port supplied by `NANOBOT_LISTEN`, proxying all HTTP and WebSocket traffic to
  `127.0.0.1:8765`.
- `scripts/caddy-webui.sh`: Bash utility exposing `install`, `start`, `stop`,
  `restart`, `status`, `validate`, and `logs` actions through the native Caddy
  systemd service.
- `deploy/caddy/README.md`: Debian/Ubuntu installation, DNS, nanobot security,
  and operating instructions.

## Deployment flow

1. The operator installs Caddy from its official Debian/Ubuntu package source.
2. The operator sets `NANOBOT_LISTEN` and runs the utility's `install` action
   with `sudo`.
3. The utility installs the supplied Caddyfile as `/etc/caddy/Caddyfile`,
   validates it with `caddy validate`, then enables and reloads `caddy.service`.
4. Browsers connect to `http://<vpn-address>:<port>`; Caddy forwards HTTP and
   WebSocket traffic to nanobot's loopback WebUI/WebSocket server.

## Security and error handling

- The Caddyfile explicitly disables automatic HTTPS and forwards the original
  `Host` and `X-Forwarded-Proto` headers, so nanobot returns the correct `ws://`
  endpoint.
- The script refuses unknown actions, requires a non-empty `NANOBOT_LISTEN` for
  installation, checks that Caddy and systemd are available, and validates the
  configuration before activating it.
- The script never installs packages, opens firewall ports, or changes nanobot
  configuration. The operator must configure a non-empty WebSocket
  `tokenIssueSecret` in nanobot before VPN exposure.

## Verification

- Shell syntax check: `bash -n scripts/caddy-webui.sh`.
- Caddy syntax check after installation: `sudo caddy validate --config
  /etc/caddy/Caddyfile --adapter caddyfile`.
- Service check: `sudo systemctl status caddy` and browser/WebSocket access at
  the configured internal HTTP address.
