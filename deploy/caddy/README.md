# Native Caddy proxy for the nanobot WebUI

Use this setup when the WebUI is reachable only over a trusted VPN or local network. Caddy serves
plain HTTP and forwards all WebUI HTTP and WebSocket traffic to nanobot at
`127.0.0.1:8765`.

## Before installation

1. Install Caddy natively on your Linux server (`sudo apt install caddy`) or macOS (`brew install caddy`).
2. Make nanobot listen only on loopback and protect remote bootstrap with a
   secret in `~/.nanobot/config.json`:

   ```json
   {
     "channels": {
       "websocket": {
         "enabled": true,
         "host": "127.0.0.1",
         "port": 8765,
         "tokenIssueSecret": "replace-with-a-long-random-secret",
         "websocketRequiresToken": true
       }
     }
   }
   ```

3. Start nanobot and confirm the local UI is available at
   `http://127.0.0.1:8765` on the machine.

## Install the proxy

Choose a host address and unused HTTP port (e.g. `127.0.0.1:8080` or `10.8.0.10:8080`).

### On macOS:

```bash
export NANOBOT_LISTEN='127.0.0.1:8080'
./scripts/caddy-webui.sh install
```

### On Linux (Debian / Ubuntu):

```bash
export NANOBOT_LISTEN='10.8.0.10:8080'
sudo -E ./scripts/caddy-webui.sh install
```

The script renders `deploy/caddy/Caddyfile.nanobot`, validates the rendered
file, installs it to the target Caddyfile location (`/etc/caddy/Caddyfile` on Linux, or Homebrew's `etc/Caddyfile` on macOS), and starts/reloads Caddy.

If target `Caddyfile` already belongs to another service, use `--replace` only when replacing the whole file is intentional:

```bash
./scripts/caddy-webui.sh install --replace
```

Open the WebUI at:

```text
http://127.0.0.1:8080
```

Enter the configured `tokenIssueSecret` in the WebUI login screen. The browser
will use `ws://` through the same HTTP address; Caddy forwards that WebSocket to
nanobot automatically.

## Operations

```bash
./scripts/caddy-webui.sh status
./scripts/caddy-webui.sh start
./scripts/caddy-webui.sh stop
./scripts/caddy-webui.sh restart
./scripts/caddy-webui.sh validate
./scripts/caddy-webui.sh logs
./scripts/caddy-webui.sh logs --follow
```

## Security boundary

This configuration deliberately has no HTTPS/TLS. Do not expose its HTTP port
to the Internet or any untrusted LAN. Restrict the port to the VPN interface or
VPN client network using your firewall, and keep `tokenIssueSecret` private.
