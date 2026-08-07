#!/bin/sh
set -eu

package="nanobot-ai"
main_source="https://github.com/HKUDS/nanobot.git"
install_target="$package"
install_source="PyPI"
source_url=""
source_ref=""
dry_run="0"
nanobot_runner=""
nanobot_python=""
nanobot_executable=""

info() {
  printf '%s\n' "$*"
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

install_failure_hint() {
  printf '%s\n' "Error: could not install nanobot from $install_source." >&2
  printf '%s\n' "If pip mentioned externally-managed-environment, use uv, pipx, or a virtual environment instead of system pip." >&2
  printf '%s\n' "You can also run manually:" >&2
  printf '  %s\n' "uv tool install --force --upgrade $install_target" >&2
  printf '  %s\n' "$python_bin -m venv ~/.nanobot/venv" >&2
  printf '  %s\n' "~/.nanobot/venv/bin/python3 -m pip install --upgrade $install_target" >&2
  printf '%s\n' "Then start setup with:" >&2
  printf '  %s\n' "nanobot onboard --wizard" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: install.sh [--dev] [--source GIT_URL [--ref REF]] [--dry-run]

By default this installs or upgrades nanobot-ai from PyPI.
Use --dev to install from the upstream main branch on GitHub.
Use --source and --ref to install an explicit Git repository revision. Pin --ref to a commit SHA for deployments.
Use --dry-run to print what would happen without installing or starting setup.
EOF
}

check_python_version() {
  candidate="$1"
  [ -n "$candidate" ] || return 1
  executable=""
  if command -v "$candidate" >/dev/null 2>&1; then
    executable="$(command -v "$candidate")"
  elif [ -x "$candidate" ]; then
    executable="$candidate"
  fi

  if [ -n "$executable" ]; then
    if "$executable" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
    then
      printf '%s\n' "$executable"
      return 0
    fi
  fi
  return 1
}

find_python() {
  if command -v uv >/dev/null 2>&1; then
    uv_py="$(uv python find ">=3.11" 2>/dev/null || true)"
    if [ -n "$uv_py" ]; then
      res="$(check_python_version "$uv_py")" && { printf '%s\n' "$res"; return 0; }
    fi
  fi

  for name in python3.13 python3.12 python3.11 python3 python; do
    res="$(check_python_version "$name")" && { printf '%s\n' "$res"; return 0; }
  done

  for path in \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 \
    /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3 \
    "$HOME/.local/share/uv/python"/*/bin/python3 \
    "$HOME/.pyenv/shims/python3"
  do
    res="$(check_python_version "$path")" && { printf '%s\n' "$res"; return 0; }
  done

  return 1
}

python_is_virtual_env() {
  "$python_bin" - <<'PY'
import sys
raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)
PY
}

ensure_pip() {
  target_python="$1"
  if "$target_python" -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  info "pip was not found for $target_python. Trying ensurepip..."
  "$target_python" -m ensurepip --upgrade >/dev/null 2>&1
}

run_nanobot() {
  case "$nanobot_runner" in
    uv)
      uv tool run --from "$install_target" nanobot "$@"
      ;;
    pipx)
      pipx run --spec "$install_target" nanobot "$@"
      ;;
    python)
      "$nanobot_python" -m nanobot "$@"
      ;;
    executable)
      "$nanobot_executable" "$@"
      ;;
    *)
      fail "nanobot was installed, but no runner was configured"
      ;;
  esac
}

nanobot_try_command() {
  case "$nanobot_runner" in
    uv)
      printf '%s\n' "uv tool run --from $install_target nanobot"
      ;;
    pipx)
      printf '%s\n' "pipx run --spec $install_target nanobot"
      ;;
    python)
      printf '%s\n' "$nanobot_python -m nanobot"
      ;;
    executable)
      printf '%s\n' "$nanobot_executable"
      ;;
  esac
}

is_fresh_nanobot_install() {
  [ -n "${HOME:-}" ] || return 1
  [ ! -e "$HOME/.nanobot/config.json" ]
}

has_browser_session() {
  if [ -n "${SSH_CONNECTION:-}${SSH_TTY:-}" ]; then
    return 1
  fi
  if ! : 2>/dev/null < /dev/tty; then
    return 1
  fi

  case "$(uname -s)" in
    Darwin)
      command -v launchctl >/dev/null 2>&1 &&
        launchctl print "gui/$(id -u)" >/dev/null 2>&1
      ;;
    *)
      [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]
      ;;
  esac
}

install_with_active_python() {
  info "Detected an active virtual environment. Installing into it..."
  ensure_pip "$python_bin" || return 1
  "$python_bin" -m pip install --upgrade "$install_target" || return 1
  nanobot_runner="python"
  nanobot_python="$python_bin"
}

install_with_uv() {
  info "Installing or upgrading nanobot from $install_source with uv tool..."
  uv tool install --python "$python_bin" --force --upgrade "$install_target" || return 1
  tool_dir="$(uv tool dir 2>/dev/null)" || return 1
  nanobot_executable="$tool_dir/$package/bin/nanobot"
  [ -x "$nanobot_executable" ] || return 1
  nanobot_runner="executable"
}

install_with_pipx() {
  info "Installing or upgrading nanobot from $install_source with pipx..."
  pipx install --python "$python_bin" --force "$install_target" || return 1
  pipx_home="$(pipx environment --value PIPX_HOME 2>/dev/null)" || return 1
  nanobot_executable="$pipx_home/venvs/$package/bin/nanobot"
  [ -x "$nanobot_executable" ] || return 1
  nanobot_runner="executable"
}

write_managed_wrapper() {
  bin_dir="${NANOBOT_BIN_DIR:-$HOME/.local/bin}"
  wrapper="$bin_dir/nanobot"
  mkdir -p "$bin_dir" || return 0

  if [ -e "$wrapper" ] && ! grep -q "Generated by nanobot installer" "$wrapper" 2>/dev/null; then
    info "Not updating $wrapper because it already exists."
    return 0
  fi

  cat > "$wrapper" <<EOF
#!/bin/sh
# Generated by nanobot installer.
exec "$nanobot_python" -m nanobot "\$@"
EOF
  chmod +x "$wrapper" || return 0

  if ! command -v nanobot >/dev/null 2>&1; then
    info "Installed a nanobot launcher at $wrapper."
    info "Add $bin_dir to PATH to run nanobot directly."
  fi
}

install_with_managed_venv() {
  [ -n "${HOME:-}" ] || fail "HOME is not set; cannot create a managed virtual environment"

  venv_dir="${NANOBOT_VENV:-$HOME/.nanobot/venv}"
  venv_python="$venv_dir/bin/python3"
  if [ ! -x "$venv_python" ]; then
    venv_python="$venv_dir/bin/python"
  fi

  if [ ! -x "$venv_python" ]; then
    info "Creating a dedicated virtual environment at $venv_dir..."
    mkdir -p "$(dirname "$venv_dir")"
    "$python_bin" -m venv "$venv_dir" || return 1
  fi

  "$venv_python" - <<'PY' >/dev/null 2>&1 || fail "The managed venv uses Python older than 3.11. Remove it or set NANOBOT_VENV to a new path."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

  info "Installing or upgrading nanobot from $install_source in $venv_dir..."
  ensure_pip "$venv_python" || return 1
  "$venv_python" -m pip install --upgrade "$install_target" || return 1

  nanobot_runner="python"
  nanobot_python="$venv_python"
  write_managed_wrapper
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dev)
      source_url="$main_source"
      source_ref="main"
      ;;
    --source)
      shift
      [ "$#" -gt 0 ] || fail "--source requires a Git URL"
      source_url="$1"
      ;;
    --ref)
      shift
      [ "$#" -gt 0 ] || fail "--ref requires a branch, tag, or commit SHA"
      source_ref="$1"
      ;;
    --dry-run)
      dry_run="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
  shift
done

if [ -n "$source_ref" ] && [ -z "$source_url" ]; then
  fail "--ref requires --source"
fi

if [ -n "$source_url" ]; then
  case "$source_url" in
    https://*.git|http://*.git|ssh://*.git|git://*.git|git@*:*/*.git) ;;
    *) fail "--source must be a Git repository URL ending in .git" ;;
  esac
  install_target="git+$source_url"
  if [ -n "$source_ref" ]; then
    install_target="$install_target@$source_ref"
  fi
  install_source="Git source $source_url @ $source_ref"
fi

python_bin="${PYTHON:-}"

if [ -n "$python_bin" ]; then
  command -v "$python_bin" >/dev/null 2>&1 || fail "PYTHON=$python_bin was not found"
  "$python_bin" - <<'PY' >/dev/null 2>&1 || fail "nanobot requires Python 3.11 or newer"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
else
  python_bin="$(find_python)" || fail "Python 3.11 or newer was not found. Install Python first, then rerun this command."
fi

info "Using Python: $("$python_bin" --version 2>&1)"

if [ "$dry_run" = "1" ]; then
  info "Dry run: would install or upgrade nanobot from $install_source."
  if python_is_virtual_env; then
    info "Dry run: active virtual environment detected; would run: $python_bin -m pip install --upgrade $install_target"
    info "Dry run: would run nanobot as: $python_bin -m nanobot"
  elif command -v uv >/dev/null 2>&1; then
    info "Dry run: would run: uv tool install --python $python_bin --force --upgrade $install_target"
    info "Dry run: would run nanobot from: <uv-tool-dir>/$package/bin/nanobot"
  elif command -v pipx >/dev/null 2>&1; then
    info "Dry run: would run: pipx install --python $python_bin --force $install_target"
    info "Dry run: would run nanobot from: <pipx-home>/venvs/$package/bin/nanobot"
  else
    venv_dir="${NANOBOT_VENV:-$HOME/.nanobot/venv}"
    info "Dry run: would create or reuse a dedicated virtual environment: $venv_dir"
    info "Dry run: would run: $venv_dir/bin/python -m pip install --upgrade $install_target"
    info "Dry run: would run nanobot as: $venv_dir/bin/python -m nanobot"
  fi
  if [ "${NANOBOT_SKIP_WIZARD:-}" = "1" ]; then
    info "Dry run: would skip automatic setup because NANOBOT_SKIP_WIZARD=1."
  elif is_fresh_nanobot_install && has_browser_session; then
    info "Dry run: would start the WebUI for this fresh desktop install."
    info "Dry run: would fall back to the setup wizard for older releases."
  else
    info "Dry run: would run the setup wizard."
  fi
  info "Dry run: no changes made."
  exit 0
fi

if [ -n "$source_url" ]; then
  command -v git >/dev/null 2>&1 || fail "Git is required to install from --source"
  if [ "${NANOBOT_SKIP_WEBUI_BUILD:-}" != "1" ] && ! command -v bun >/dev/null 2>&1 && ! command -v npm >/dev/null 2>&1; then
    fail "Source installs build the bundled WebUI; install bun or npm, or set NANOBOT_SKIP_WEBUI_BUILD=1 for headless use"
  fi
fi

if python_is_virtual_env; then
  install_with_active_python || install_failure_hint
else
  installed="0"

  if command -v uv >/dev/null 2>&1; then
    if install_with_uv; then
      installed="1"
    else
      info "uv tool install failed. Trying the next isolated install method..."
    fi
  fi

  if [ "$installed" != "1" ] && command -v pipx >/dev/null 2>&1; then
    if install_with_pipx; then
      installed="1"
    else
      info "pipx install failed. Trying the managed virtual environment..."
    fi
  fi

  if [ "$installed" != "1" ]; then
    info "Using a dedicated virtual environment to avoid system pip."
    install_with_managed_venv || install_failure_hint
  fi
fi

info "Installed nanobot:"
run_nanobot --version

if [ "${NANOBOT_SKIP_WIZARD:-}" = "1" ]; then
  info "Skipping automatic setup because NANOBOT_SKIP_WIZARD=1."
  info "Run this later: $(nanobot_try_command) webui"
  exit 0
fi

if is_fresh_nanobot_install && has_browser_session; then
  if run_nanobot webui --help >/dev/null 2>&1; then
    info "Starting nanobot WebUI..."
    info "Configure your first provider and model in Settings > Models."
    info "Run this later: $(nanobot_try_command) webui"
    run_nanobot webui --yes
    exit 0
  fi
  info "The installed release does not support nanobot webui yet."
  info "Falling back to the setup wizard..."
fi

if [ -t 0 ]; then
  info "Starting setup wizard..."
  run_nanobot onboard --wizard
elif : 2>/dev/null < /dev/tty; then
  info "Starting setup wizard..."
  run_nanobot onboard --wizard < /dev/tty
else
  info "Skipping setup wizard because no interactive terminal is available."
  info "Run this later: $(nanobot_try_command) onboard --wizard"
fi

info "Done. Try: $(nanobot_try_command) agent -m \"Hello!\""
