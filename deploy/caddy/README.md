# Native Caddy proxy for the nanobot WebUI

Use this setup when the WebUI is reachable only over a trusted VPN. Caddy serves
plain HTTP and forwards all WebUI HTTP and WebSocket traffic to nanobot at
`127.0.0.1:8765`.

## Before installation

1. Install Caddy natively on the Debian/Ubuntu server using Caddy's official
   installation instructions. Confirm `caddy version` and `systemctl status caddy`
   work before continuing.
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
   `http://127.0.0.1:8765` on the server.

## Install the proxy

Choose a VPN address and unused HTTP port. The address must be reachable only
from the VPN; enforce that with your VPN routing and host firewall. For example:

```bash
export NANOBOT_LISTEN='10.8.0.10:8080'
sudo -E ./scripts/caddy-webui.sh install
```

The script renders `deploy/caddy/Caddyfile.nanobot`, validates the rendered
file, installs it as `/etc/caddy/Caddyfile`, enables `caddy.service`, and starts
or reloads it.

If `/etc/caddy/Caddyfile` already belongs to another service, do not overwrite
it. Merge the nanobot site into that existing Caddyfile instead. Use the
following only when replacing the whole file is intentional:

```bash
sudo -E ./scripts/caddy-webui.sh install --replace
```

Open the WebUI at:

```text
http://10.8.0.10:8080
```

Enter the configured `tokenIssueSecret` in the WebUI login screen. The browser
will use `ws://` through the same HTTP address; Caddy forwards that WebSocket to
nanobot automatically.

## Operations

```bash
./scripts/caddy-webui.sh status
sudo ./scripts/caddy-webui.sh start
sudo ./scripts/caddy-webui.sh stop
sudo ./scripts/caddy-webui.sh restart
./scripts/caddy-webui.sh validate
sudo ./scripts/caddy-webui.sh logs
sudo ./scripts/caddy-webui.sh logs --follow
```

## Security boundary

This configuration deliberately has no HTTPS/TLS. Do not expose its HTTP port
to the Internet or any untrusted LAN. Restrict the port to the VPN interface or
VPN client network using your firewall, and keep `tokenIssueSecret` private.
