#!/usr/bin/env bash
# Stop, update, and start a nanobot source checkout.
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly NANOBOT_HOME_DIR="${NANOBOT_HOME:-${HOME}/.nanobot}"
readonly VENV_DIR="${NANOBOT_VENV_DIR:-${NANOBOT_HOME_DIR}/.venv}"
readonly VENV_PYTHON="${VENV_DIR}/bin/python"
readonly VENV_PIP="${VENV_DIR}/bin/pip"

SERVICE_NAME="${NANOBOT_SERVICE_NAME:-}"
PULL_SOURCE=1
BUILD_WEBUI=1
INSTALL_CHANNELS=0
TIMEOUT=20

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

info() {
    printf '\n==> %s\n' "$*"
}

usage() {
    cat <<'EOF'
Usage: scripts/nanobot-update.sh <action> [options]

Actions:
  update       Stop nanobot, pull the current branch, sync dependencies,
               rebuild the WebUI, and start nanobot again.
  start        Start the gateway in the background.
  stop         Stop the gateway, whether background or foreground.
  restart      Stop and start the gateway.
  status       Show gateway status.
  logs         Follow gateway logs.

Options:
  --no-pull              Do not run git pull (update only dependencies/build).
  --no-webui             Do not rebuild the WebUI.
  --install-channels     Install dependencies for all channel plugins.
  --timeout SECONDS      Gateway stop timeout (default: 20).
  -h, --help             Show this help.

Environment:
  NANOBOT_VENV_DIR      Python virtual environment (default: ~/.nanobot/.venv).
  NANOBOT_HOME          Nanobot data directory used for the default venv path.
  NANOBOT_SERVICE_NAME   Use a systemd user service instead of the built-in
                         background gateway, for example nanobot-gateway.
  NANOBOT_SKIP_WEBUI_BUILD=1  Equivalent to --no-webui.
EOF
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

run_python() {
    if [[ -x "${VENV_PYTHON}" ]]; then
        "${VENV_PYTHON}" "$@"
    elif command -v uv >/dev/null 2>&1 && [[ -f "${REPO_ROOT}/uv.lock" ]]; then
        (cd -- "${REPO_ROOT}" && uv run --no-sync python "$@")
    else
        require_command python3
        (cd -- "${REPO_ROOT}" && python3 "$@")
    fi
}

run_pip() {
    if [[ -x "${VENV_PIP}" ]]; then
        "${VENV_PIP}" "$@"
    elif [[ -x "${VENV_PYTHON}" ]]; then
        "${VENV_PYTHON}" -m pip "$@"
    else
        require_command python3
        (cd -- "${REPO_ROOT}" && python3 -m pip "$@")
    fi
}

run_nanobot() {
    if [[ -x "${VENV_PYTHON}" ]]; then
        (cd -- "${REPO_ROOT}" && "${VENV_PYTHON}" -m nanobot "$@")
    elif command -v uv >/dev/null 2>&1 && [[ -f "${REPO_ROOT}/uv.lock" ]]; then
        (cd -- "${REPO_ROOT}" && uv run --no-sync nanobot "$@")
    elif command -v nanobot >/dev/null 2>&1; then
        nanobot "$@"
    else
        run_python -m nanobot "$@"
    fi
}

service_action() {
    local action="$1"
    if [[ -n "${SERVICE_NAME}" ]]; then
        require_command systemctl
        systemctl --user "${action}" "${SERVICE_NAME}"
    else
        case "${action}" in
            start) run_nanobot gateway --background ;;
            stop) run_nanobot gateway stop --timeout "${TIMEOUT}" ;;
            restart) run_nanobot gateway restart --timeout "${TIMEOUT}" ;;
            status) run_nanobot gateway status ;;
            logs) run_nanobot gateway logs ;;
            *) die "unsupported action: ${action}" ;;
        esac
    fi
}

repo_gateway_pids() {
    local pid args cwd
    while read -r pid args; do
        [[ "${pid}" =~ ^[0-9]+$ ]] || continue
        [[ "${pid}" -ne "$$" ]] || continue
        [[ -r "/proc/${pid}/cmdline" ]] || continue
        [[ "${args}" == *nanobot* && "${args}" == *gateway* ]] || continue
        [[ "${args}" != *nanobot-update.sh* ]] || continue
        cwd="$(readlink "/proc/${pid}/cwd" 2>/dev/null || true)"
        [[ "${cwd}" == "${REPO_ROOT}" || "${args}" == *"${REPO_ROOT}"* ]] || continue
        printf '%s\n' "${pid}"
    done < <(ps -eo pid=,args=)
}

stop_repo_gateway_processes() {
    local pid state
    local -a pids=()
    mapfile -t pids < <(repo_gateway_pids)
    ((${#pids[@]} > 0)) || return 0

    info "Stopping foreground gateway process(es): ${pids[*]}"
    for pid in "${pids[@]}"; do
        kill -TERM "${pid}" 2>/dev/null || true
    done

    local deadline=$((SECONDS + TIMEOUT))
    while (( SECONDS < deadline )); do
        local remaining=0
        for pid in "${pids[@]}"; do
            if kill -0 "${pid}" 2>/dev/null; then
                state="$(ps -o stat= -p "${pid}" 2>/dev/null | tr -d ' ' || true)"
                [[ "${state}" == Z* ]] || remaining=1
            fi
        done
        (( remaining == 0 )) && return 0
        sleep 1
    done

    for pid in "${pids[@]}"; do
        if kill -0 "${pid}" 2>/dev/null; then
            printf 'Warning: gateway PID %s did not stop; sending SIGKILL.\n' "${pid}" >&2
            kill -KILL "${pid}" 2>/dev/null || true
        fi
    done
}

stop_gateway() {
    if [[ -n "${SERVICE_NAME}" ]]; then
        service_action stop
        return 0
    fi

    # The built-in runtime handles --background processes via its state file.
    # Foreground launches have no state file, so discover only gateway processes
    # whose cwd/arguments belong to this checkout and stop those as a fallback.
    local -a foreground_pids=()
    mapfile -t foreground_pids < <(repo_gateway_pids)
    local runtime_status=0
    service_action stop || runtime_status=$?
    if ((${#foreground_pids[@]} > 0)); then
        stop_repo_gateway_processes
        return 0
    fi
    return "${runtime_status}"
}

sync_dependencies() {
    if [[ -x "${VENV_PIP}" || -x "${VENV_PYTHON}" ]]; then
        info "Installing Python dependencies with ${VENV_DIR}"
        (cd -- "${REPO_ROOT}" && run_pip install -e '.[dev]')
    elif command -v uv >/dev/null 2>&1 && [[ -f "${REPO_ROOT}/uv.lock" ]]; then
        info "Syncing Python dependencies with uv"
        (cd -- "${REPO_ROOT}" && uv sync --all-extras --dev)
    else
        info "Installing Python dependencies with pip"
        (cd -- "${REPO_ROOT}" && run_pip install -e '.[dev]')
    fi

    if (( INSTALL_CHANNELS )); then
        info "Installing channel dependencies"
        (cd -- "${REPO_ROOT}" && run_python -m scripts.install_channel_dependencies --all-channels)
    fi
}

build_webui() {
    (( BUILD_WEBUI )) || return 0
    [[ "${NANOBOT_SKIP_WEBUI_BUILD:-0}" == "1" ]] && return 0

    if command -v bun >/dev/null 2>&1; then
        info "Installing WebUI dependencies and building WebUI with bun"
        (cd -- "${REPO_ROOT}/webui" && bun install --frozen-lockfile && bun run build)
    elif command -v npm >/dev/null 2>&1; then
        info "Installing WebUI dependencies and building WebUI with npm"
        (cd -- "${REPO_ROOT}/webui" && npm ci && npm run build)
    else
        die "bun or npm is required to rebuild the WebUI; use --no-webui to skip it"
    fi
}

update() {
    stop_gateway

    if (( PULL_SOURCE )); then
        require_command git
        info "Pulling source code"
        (cd -- "${REPO_ROOT}" && git pull --ff-only)
    fi

    sync_dependencies
    build_webui

    info "Starting nanobot"
    service_action start
    service_action status
}

main() {
    local action="${1:-update}"
    if [[ $# -gt 0 ]]; then
        shift
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --no-pull) PULL_SOURCE=0 ;;
            --no-webui) BUILD_WEBUI=0 ;;
            --install-channels) INSTALL_CHANNELS=1 ;;
            --timeout)
                [[ $# -ge 2 ]] || die "--timeout requires a value"
                [[ "$2" =~ ^[0-9]+$ ]] || die "--timeout must be a non-negative integer"
                TIMEOUT="$2"
                shift
                ;;
            -h|--help) usage; return 0 ;;
            *) usage >&2; die "unknown option: $1" ;;
        esac
        shift
    done

    cd -- "${REPO_ROOT}"
    case "${action}" in
        update) update ;;
        start|status|logs) service_action "${action}" ;;
        stop) stop_gateway ;;
        restart)
            stop_gateway
            service_action start
            ;;
        -h|--help|help) usage ;;
        *) usage >&2; die "unknown action: ${action}" ;;
    esac
}

main "$@"
