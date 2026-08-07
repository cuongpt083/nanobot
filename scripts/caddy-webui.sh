#!/usr/bin/env bash
# Manage the native Caddy service used to proxy the nanobot WebUI over a VPN (Linux & macOS).
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly TEMPLATE_PATH="${REPO_ROOT}/deploy/caddy/Caddyfile.nanobot"

is_macos() {
    [[ "$(uname -s)" == "Darwin" ]]
}

get_brew_prefix() {
    if command -v brew >/dev/null 2>&1; then
        brew --prefix
    elif [[ -d "/opt/homebrew" ]]; then
        echo "/opt/homebrew"
    elif [[ -d "/usr/local" ]]; then
        echo "/usr/local"
    else
        echo ""
    fi
}

get_target_path() {
    if is_macos; then
        local prefix
        prefix="$(get_brew_prefix)"
        if [[ -n "${prefix}" ]]; then
            if [[ -d "${prefix}/etc/caddy" ]]; then
                echo "${prefix}/etc/caddy/Caddyfile"
            else
                echo "${prefix}/etc/Caddyfile"
            fi
        else
            echo "/etc/caddy/Caddyfile"
        fi
    else
        echo "/etc/caddy/Caddyfile"
    fi
}

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: scripts/caddy-webui.sh <action> [options]

Actions:
  install [--replace]  Render and install the Caddyfile, then enable/start Caddy.
  start                Start Caddy service.
  stop                 Stop Caddy service.
  restart              Restart Caddy service.
  status               Show Caddy service status.
  validate             Validate target Caddyfile.
  logs [--follow]      Show the latest Caddy logs, optionally following them.

For install, set NANOBOT_LISTEN to the VPN host and HTTP port, for example:
  export NANOBOT_LISTEN='10.8.0.10:8080'
EOF
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_root_if_needed() {
    local target_path
    target_path="$(get_target_path)"
    if [[ "${target_path}" == /etc/* && "${EUID}" -ne 0 ]]; then
        die "this action requires sudo because target path is ${target_path}"
    fi
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

    require_root_if_needed
    require_command caddy
    [[ -f "${TEMPLATE_PATH}" ]] || die "template not found: ${TEMPLATE_PATH}"
    validate_listen_address "${NANOBOT_LISTEN:-}"

    local target_path
    target_path="$(get_target_path)"

    if [[ -e "${target_path}" && "${replace_existing}" != "--replace" ]]; then
        die "${target_path} already exists; use install --replace only if replacing it is intentional"
    fi

    local temp_config cleanup_command
    temp_config="$(mktemp)"
    printf -v cleanup_command 'rm -f -- %q' "${temp_config}"
    trap "${cleanup_command}" RETURN
    sed "s|__NANOBOT_LISTEN__|${NANOBOT_LISTEN}|g" "${TEMPLATE_PATH}" >"${temp_config}"
    caddy validate --config "${temp_config}" --adapter caddyfile

    mkdir -p "$(dirname "${target_path}")"
    cp "${temp_config}" "${target_path}"
    chmod 0644 "${target_path}"

    if is_macos; then
        if command -v brew >/dev/null 2>&1; then
            brew services start caddy || brew services restart caddy || true
            caddy reload --config "${target_path}" 2>/dev/null || true
        else
            caddy reload --config "${target_path}" 2>/dev/null || caddy start --config "${target_path}"
        fi
    else
        require_command systemctl
        systemctl enable caddy
        if systemctl is-active --quiet caddy; then
            systemctl reload caddy
        else
            systemctl start caddy
        fi
    fi

    trap - RETURN
    rm -f -- "${temp_config}"
}

validate_config() {
    require_command caddy
    local target_path
    target_path="$(get_target_path)"
    [[ -f "${target_path}" ]] || die "Caddyfile not found: ${target_path}; run install first"
    caddy validate --config "${target_path}" --adapter caddyfile
}

manage_service() {
    local action="$1"
    local target_path
    target_path="$(get_target_path)"

    if is_macos; then
        if command -v brew >/dev/null 2>&1; then
            case "${action}" in
                start) brew services start caddy ;;
                stop) brew services stop caddy ;;
                restart) brew services restart caddy ;;
                status) brew services info caddy ;;
            esac
        else
            case "${action}" in
                start) caddy start --config "${target_path}" ;;
                stop) caddy stop ;;
                restart) caddy stop && caddy start --config "${target_path}" ;;
                status) caddy validate --config "${target_path}" ;;
            esac
        fi
    else
        require_command systemctl
        systemctl "${action}" caddy
    fi
}

show_logs() {
    local follow="${1:-}"
    if is_macos; then
        local prefix
        prefix="$(get_brew_prefix)"
        local log_file=""
        for candidate in \
            "${prefix}/var/log/caddy.log" \
            "${prefix}/var/log/caddy/caddy.log" \
            "${HOME}/Library/Logs/Caddy/caddy.log"
        do
            if [[ -f "${candidate}" ]]; then
                log_file="${candidate}"
                break
            fi
        done

        if [[ -n "${log_file}" ]]; then
            if [[ "${follow}" == "--follow" ]]; then
                tail -f "${log_file}"
            else
                tail -n 100 "${log_file}"
            fi
        else
            die "Caddy log file not found. Try running: brew services info caddy"
        fi
    else
        require_command journalctl
        if [[ "${follow}" == "--follow" ]]; then
            journalctl -u caddy --follow
        else
            journalctl -u caddy -n 100 --no-pager
        fi
    fi
}

main() {
    local action="${1:-}"
    shift || true

    case "${action}" in
        install) install_config "$@" ;;
        start|stop|restart|status)
            [[ "$#" -eq 0 ]] || die "${action} does not accept options"
            manage_service "${action}"
            ;;
        validate)
            [[ "$#" -eq 0 ]] || die "validate does not accept options"
            validate_config
            ;;
        logs)
            [[ "$#" -le 1 && ( "$#" -eq 0 || "$1" == "--follow" ) ]] || die "logs accepts only --follow"
            show_logs "${1:-}"
            ;;
        -h|--help|help) usage ;;
        *) usage >&2; die "unknown action: ${action:-<missing>}" ;;
    esac
}

main "$@"
