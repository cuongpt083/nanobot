#!/usr/bin/env bash
# Manage the native Caddy service used to proxy the nanobot WebUI over a VPN.
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly TEMPLATE_PATH="${REPO_ROOT}/deploy/caddy/Caddyfile.nanobot"
readonly TARGET_PATH="/etc/caddy/Caddyfile"

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: scripts/caddy-webui.sh <action> [options]

Actions:
  install [--replace]  Render and install the Caddyfile, then enable/start Caddy.
  start                Start caddy.service.
  stop                 Stop caddy.service.
  restart              Restart caddy.service.
  status               Show caddy.service status.
  validate             Validate /etc/caddy/Caddyfile.
  logs [--follow]      Show the latest Caddy logs, optionally following them.

For install, set NANOBOT_LISTEN to the VPN host and HTTP port, for example:
  export NANOBOT_LISTEN='10.8.0.10:8080'
  sudo -E ./scripts/caddy-webui.sh install
EOF
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_root() {
    [[ "${EUID}" -eq 0 ]] || die "this action must be run with sudo"
}

validate_listen_address() {
    local listen_address="${1:-}"
    [[ "${listen_address}" =~ ^(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+):[0-9]{1,5}$ ]] || \
        die "NANOBOT_LISTEN must be host:port, for example 10.8.0.10:8080"

    local port="${listen_address##*:}"
    ((10#${port} >= 1 && 10#${port} <= 65535)) || die "NANOBOT_LISTEN port must be 1-65535"
}

install_config() {
    local replace_existing="${1:-}"
    [[ -z "${replace_existing}" || "${replace_existing}" == "--replace" ]] || {
        usage >&2
        die "install accepts only --replace"
    }

    require_root
    require_command caddy
    require_command systemctl
    [[ -f "${TEMPLATE_PATH}" ]] || die "template not found: ${TEMPLATE_PATH}"
    validate_listen_address "${NANOBOT_LISTEN:-}"

    if [[ -e "${TARGET_PATH}" && "${replace_existing}" != "--replace" ]]; then
        die "${TARGET_PATH} already exists; use install --replace only if replacing it is intentional"
    fi

    local temp_config
    temp_config="$(mktemp)"
    trap 'rm -f "${temp_config}"' RETURN
    sed "s|__NANOBOT_LISTEN__|${NANOBOT_LISTEN}|g" "${TEMPLATE_PATH}" >"${temp_config}"
    caddy validate --config "${temp_config}" --adapter caddyfile

    install -d -m 0755 /etc/caddy
    install -m 0644 "${temp_config}" "${TARGET_PATH}"
    systemctl enable caddy
    if systemctl is-active --quiet caddy; then
        systemctl reload caddy
    else
        systemctl start caddy
    fi
}

validate_config() {
    require_command caddy
    [[ -f "${TARGET_PATH}" ]] || die "Caddyfile not found: ${TARGET_PATH}; run install first"
    caddy validate --config "${TARGET_PATH}" --adapter caddyfile
}

main() {
    local action="${1:-}"
    shift || true

    case "${action}" in
        install) install_config "$@" ;;
        start|stop|restart|status)
            [[ "$#" -eq 0 ]] || die "${action} does not accept options"
            require_command systemctl
            systemctl "${action}" caddy
            ;;
        validate)
            [[ "$#" -eq 0 ]] || die "validate does not accept options"
            validate_config
            ;;
        logs)
            [[ "$#" -le 1 && ( "$#" -eq 0 || "$1" == "--follow" ) ]] || die "logs accepts only --follow"
            require_command journalctl
            if [[ "${1:-}" == "--follow" ]]; then
                journalctl -u caddy --follow
            else
                journalctl -u caddy -n 100 --no-pager
            fi
            ;;
        -h|--help|help) usage ;;
        *) usage >&2; die "unknown action: ${action:-<missing>}" ;;
    esac
}

main "$@"
