"""OS sandbox for coding harnesses (Linux ``bwrap``, macOS ``seatbelt``).

The harness (``agy``, ``pi``) runs with permissions auto-approved, so the only real boundary is the
operating system. ``coding.sandbox`` selects how the harness is started:

* ``bwrap`` (Linux, bubblewrap): the system is mounted read-only, the user's home is an empty tmpfs
  (no ``~/.ssh``, ``~/.aws``, shell rc files...), and only the project, the harness' own state
  directory (login credentials, sessions) and a worktree's git directory are writable.
* ``seatbelt`` (macOS, ``sandbox-exec``): there is no mount namespace, so the same layout is a
  deny-by-default profile: everything outside the system, the harness' tools, the project and its
  state is unreadable, and only the project / state / git directory are writable.

* ``wsl`` (Windows): the harness runs inside a WSL2 distro under the same ``bwrap`` layout. The
  project stays on the Windows drive (mounted via ``/mnt/<drive>``), but the harness, its tools and
  its login state (e.g. ``~/.gemini``) live in the distro, so ``agy``/``pi`` must be installed and
  logged in *inside* WSL. Windows files outside the project are not mounted and cannot be seen.

In every mode the network stays open (the harness must reach its model API) and a worktree's
``.git/hooks`` and ``.git/config`` are read-only, because they are shared with the user's checkout
and editing them would run code outside the sandbox later.

A requested sandbox that cannot be provided is refused loudly instead of running the harness
unwrapped.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from nanobot.agent.tools.sandbox import (
    SEATBELT_SYSTEM_READ_LITERALS,
    SEATBELT_SYSTEM_READ_SUBPATHS,
    SEATBELT_TRAVERSABLE_LITERALS,
    sbpl_quote,
    seatbelt_ancestors,
)


class SandboxUnavailableError(RuntimeError):
    """The configured sandbox cannot be used on this machine."""


@dataclass(frozen=True)
class SandboxPolicy:
    mode: str = "none"  # "none" | "bwrap" | "seatbelt" | "wsl"
    ro_binds: tuple[str, ...] = ()  # extra read-only paths (e.g. a node install under $HOME)
    rw_binds: tuple[str, ...] = ()  # extra writable paths
    distro: str | None = None  # wsl only: distro name (None = the default distro)

    @property
    def active(self) -> bool:
        return self.mode in ("bwrap", "seatbelt", "wsl")


# Environment of a Windows process that is meaningless (or wrong) inside Linux; also what
# ``_make_child_env`` forwards on Windows so native tools can find the profile and system dirs.
WINDOWS_ENV_KEYS = (
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "USERNAME",
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
)


_SYSTEM_RO = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64")
_ETC_RO = (
    "/etc/alternatives", "/etc/ssl", "/etc/pki", "/etc/ca-certificates", "/etc/crypto-policies",
    "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/host.conf", "/etc/passwd",
    "/etc/group", "/etc/localtime", "/etc/ld.so.cache", "/etc/os-release",
)
# macOS: package-manager and developer-tool trees the harness' tools usually live in.
_MAC_TOOLS_RO = (
    "/opt/homebrew", "/Applications/Xcode.app/Contents/Developer",
    "/private/etc/resolv.conf", "/private/etc/passwd", "/private/etc/group",
    "/private/etc/localtime", "/private/etc/hosts", "/private/etc/ssl",
)
_MAC_DEV_WRITE = ("/dev/null", "/dev/zero", "/dev/tty", "/dev/dtracehelper")
# git must not read a global config it cannot reach (macOS seatbelt would fail hard on EPERM).
_GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

_probe_results: dict[tuple[str, str | None], str] = {}


def _wsl_exe() -> str:
    return shutil.which("wsl.exe") or "wsl.exe"


def _wsl_prefix(distro: str | None) -> list[str]:
    return [_wsl_exe(), *(["-d", distro] if distro else [])]


def _wsl_run(distro: str | None, argv: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    """Run a Linux program in the distro without a shell. Output of Linux programs is UTF-8."""
    return subprocess.run(
        [*_wsl_prefix(distro), "--exec", *argv],
        capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
    )


def _probe(mode: str, distro: str | None = None) -> str:
    """'' when the sandbox really starts a process here, otherwise the reason it does not."""
    if mode == "wsl":
        if os.name != "nt":
            return "coding.sandbox is 'wsl', which is for Windows; use 'bwrap' on Linux."
        if shutil.which("wsl.exe") is None:
            return "wsl.exe not found: install WSL2 (`wsl --install`)."
        try:
            proc = _wsl_run(distro, ["bwrap", "--ro-bind", "/", "/", "--unshare-pid", "true"])
        except (OSError, subprocess.SubprocessError) as exc:
            return f"WSL cannot start: {exc}"
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).replace("\x00", "").strip()[:200]
            return (
                f"bwrap does not work in WSL distro {distro or '(default)'} "
                f"(`sudo apt install bubblewrap`; is the distro installed?): {detail}"
            )
        return ""
    if mode == "bwrap":
        if not sys.platform.startswith("linux"):
            return (
                f"coding.sandbox is 'bwrap', which only works on Linux (this is {sys.platform}). "
                "Use 'seatbelt' on macOS, run nanobot inside WSL2 on Windows, or set "
                "coding.sandbox to 'none' and enable 'run without an OS sandbox' for the backend."
            )
        exe = shutil.which("bwrap")
        if exe is None:
            return "bwrap is not installed (install the 'bubblewrap' package)."
        command = [exe, "--ro-bind", "/", "/", "--unshare-pid", "true"]
        hint = "user namespaces disabled?"
    else:
        if sys.platform != "darwin":
            return (
                f"coding.sandbox is 'seatbelt', which only works on macOS (this is {sys.platform}). "
                "Use 'bwrap' on Linux."
            )
        if not Path("/usr/bin/sandbox-exec").exists():
            return "/usr/bin/sandbox-exec is missing."
        command = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"]
        hint = "sandbox-exec refused to run"
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{mode} cannot start: {exc}"
    if proc.returncode != 0:
        return f"{mode} cannot start ({hint}): {proc.stderr.strip()[:200]}"
    return ""


def check_available(policy: SandboxPolicy) -> None:
    """Raise ``SandboxUnavailableError`` unless the sandbox can really start a process here."""
    if not policy.active:
        return
    key = (policy.mode, policy.distro)
    if key not in _probe_results:
        _probe_results[key] = _probe(policy.mode, policy.distro)
    if _probe_results[key]:
        raise SandboxUnavailableError(_probe_results[key])


@dataclass(frozen=True)
class GitLayout:
    """Where a linked worktree keeps its git data (``root`` has a ``.git`` *file*)."""

    root: Path
    gitdir: Path
    common: Path


def git_layout(cwd: Path) -> GitLayout | None:
    """Layout of the linked worktree containing ``cwd``; None for a plain dir or normal checkout."""
    for candidate in (cwd, *cwd.parents):
        dotgit = candidate / ".git"
        if dotgit.is_dir():
            return None
        if dotgit.is_file():
            try:
                text = dotgit.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if not text.startswith("gitdir:"):
                return None
            gitdir = Path(text.split(":", 1)[1].strip())
            if not gitdir.is_absolute():
                gitdir = candidate / gitdir
            gitdir = gitdir.resolve()
            common = gitdir
            commondir = gitdir / "commondir"
            if commondir.is_file():
                try:
                    common = (gitdir / commondir.read_text(encoding="utf-8").strip()).resolve()
                except OSError:
                    pass
            return GitLayout(candidate, gitdir, common)
    return None


def git_binds(cwd: Path) -> tuple[list[Path], list[Path]]:
    """Writable and read-only-overlay paths a linked git worktree needs.

    A worktree's ``.git`` is a file pointing into the main repository's ``.git/worktrees/<id>``;
    ``git commit`` there writes objects and refs in the main ``.git``. Hooks and config are shared
    with the user's checkout, so they are mounted back read-only.
    """
    layout = git_layout(cwd)
    if layout is None:
        for candidate in (cwd, *cwd.parents):
            if (candidate / ".git").is_dir():
                return [candidate], []
        return [cwd], []
    return [layout.root, layout.common], [layout.common / "hooks", layout.common / "config"]


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _tool_binds(args: list[str], env: dict[str, str], home: Path) -> list[str]:
    """Read-only paths the harness executable (and tools on PATH under $HOME) live in."""
    found: list[str] = []
    exe = shutil.which(args[0], path=env.get("PATH"))
    if exe:
        found.append(str(Path(exe).parent))
        found.append(str(Path(exe).resolve().parent))
    for entry in env.get("PATH", "").split(os.pathsep):
        if entry and _under(Path(entry), home):
            found.append(entry)
    return found


def scratch_dir() -> Path:
    """Per-user temp dir the macOS sandbox may write to instead of the shared ``$TMPDIR``."""
    path = Path(tempfile.gettempdir()).resolve() / f"nanobot-coding-{os.getuid() if hasattr(os, 'getuid') else 0}"
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def wrap_argv(
    args: list[str],
    *,
    policy: SandboxPolicy,
    cwd: Path,
    env: dict[str, str],
    state_dirs: Iterable[Path | str] = (),
    extra_rw: Iterable[Path | str | None] = (),
) -> list[str]:
    """Return ``args`` wrapped for the sandbox in ``policy`` (unchanged when inactive)."""
    if not policy.active:
        return args
    cwd = cwd.resolve()
    if policy.mode == "wsl":
        return _wrap_wsl(args, policy=policy, cwd=cwd, env=env, state_dirs=state_dirs, extra_rw=extra_rw)
    home = Path(env.get("HOME") or Path.home()).resolve()

    rw_roots, ro_overlays = git_binds(cwd)
    rw = _dedupe(
        [str(p) for p in rw_roots]
        + [str(cwd)]
        + [str(Path(p).expanduser()) for p in state_dirs]
        + [str(Path(p).expanduser()) for p in extra_rw if p]
        + list(policy.rw_binds)
    )
    ro = _dedupe(_tool_binds(args, env, home) + list(policy.ro_binds))
    if policy.mode == "seatbelt":
        return _wrap_seatbelt(args, ro=ro, rw=rw, overlays=ro_overlays)
    return _wrap_bwrap(
        args, cwd=str(cwd), home=str(home), ro=ro, rw=rw, overlays=[str(p) for p in ro_overlays],
        setenv={**_GIT_ENV, "HOME": str(home)},
    )


def _wrap_bwrap(
    args: list[str],
    *,
    cwd: str,
    home: str,
    ro: list[str],
    rw: list[str],
    overlays: list[str],
    setenv: dict[str, str],
) -> list[str]:
    out = ["bwrap", "--new-session", "--die-with-parent", "--unshare-pid", "--unshare-ipc"]
    for path in _SYSTEM_RO:
        out += ["--ro-bind-try", path, path]
    for path in _ETC_RO:
        out += ["--ro-bind-try", path, path]
    out += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", home]
    for path in ro:
        out += ["--ro-bind-try", path, path]
    for path in rw:
        # The project must exist; state dirs that do not exist yet are simply not mounted.
        flag = "--bind" if path == cwd else "--bind-try"
        out += [flag, path, path]
    for path in overlays:
        out += ["--ro-bind-try", path, path]
    for key, value in setenv.items():
        out += ["--setenv", key, value]
    out += ["--chdir", cwd, "--", *args]
    return out


# ---- Windows: bwrap inside a WSL2 distro --------------------------------------------------------

_WIN_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


@dataclass(frozen=True)
class WslInfo:
    home: str
    path: str
    exe: str
    exe_real: str


_wsl_info_cache: dict[tuple[str | None, str], WslInfo] = {}


def wsl_info(distro: str | None, exe: str) -> WslInfo:
    """Home, PATH and the location of ``exe`` as seen by a login shell inside the distro."""
    key = (distro, exe)
    cached = _wsl_info_cache.get(key)
    if cached is not None:
        return cached
    script = (
        'printf "@@HOME=%s\\n@@PATH=%s\\n" "$HOME" "$PATH"; p=$(command -v "$1") || exit 0; '
        'printf "@@EXE=%s\\n@@REAL=%s\\n" "$p" "$(readlink -f "$p")"'
    )
    proc = _wsl_run(distro, ["bash", "-lc", script, "bash", exe])
    found = {
        line[2:].split("=", 1)[0]: line.split("=", 1)[1]
        for line in proc.stdout.splitlines()
        if line.startswith("@@") and "=" in line
    }
    label = distro or "(default)"
    if "HOME" not in found:
        raise SandboxUnavailableError(f"cannot query WSL distro {label}: {proc.stderr.strip()[:200]}")
    if not found.get("EXE"):
        raise SandboxUnavailableError(
            f"'{exe}' is not installed inside WSL distro {label}. coding.sandbox='wsl' runs the "
            f"harness in WSL: install {exe} there and log in once (the Windows install is not used)."
        )
    info = WslInfo(found["HOME"], found.get("PATH", ""), found["EXE"], found.get("REAL") or found["EXE"])
    _wsl_info_cache[key] = info
    return info


def wsl_paths(distro: str | None, paths: list[str]) -> dict[str, str]:
    """Translate Windows paths to their WSL form (``C:\\x`` -> ``/mnt/c/x``) with ``wslpath``."""
    if not paths:
        return {}
    proc = _wsl_run(
        distro, ["sh", "-c", 'for p; do wslpath -u "$p"; done', "sh", *[p.replace("\\", "/") for p in paths]]
    )
    lines = proc.stdout.splitlines()
    if proc.returncode != 0 or len(lines) != len(paths):
        raise SandboxUnavailableError(f"wslpath failed for {paths}: {proc.stderr.strip()[:200]}")
    return dict(zip(paths, lines, strict=True))


def _wrap_wsl(
    args: list[str],
    *,
    policy: SandboxPolicy,
    cwd: Path,
    env: dict[str, str],
    state_dirs: Iterable[Path | str],
    extra_rw: Iterable[Path | str | None],
) -> list[str]:
    distro = policy.distro
    info = wsl_info(distro, args[0])
    home = info.home
    win_home = Path.home()

    def expand(value: str) -> str:
        return home + value[1:] if value == "~" or value.startswith("~/") else value

    layout = git_layout(cwd)
    rw_roots, overlays = git_binds(cwd)
    rw_raw = [str(p) for p in rw_roots] + [str(cwd)]
    for state in state_dirs:  # the harness' state lives in the distro, mirrored from the Windows ~
        path = Path(state)
        try:
            rw_raw.append(f"{home}/{path.relative_to(win_home).as_posix()}")
        except ValueError:
            rw_raw.append(str(path))
    rw_raw += [str(p) for p in extra_rw if p] + list(policy.rw_binds)

    tool_dirs = [
        str(PurePosixPath(info.exe).parent), str(PurePosixPath(info.exe_real).parent),
        *(e for e in info.path.split(":") if e.startswith(home + "/")),
    ]
    ro_raw = tool_dirs + list(policy.ro_binds)
    git_raw = [str(layout.gitdir), str(layout.common), str(layout.root)] if layout else []

    rw_raw, ro_raw = [expand(p) for p in rw_raw], [expand(p) for p in ro_raw]
    overlay_raw = [str(p) for p in overlays]
    windows = sorted({p for p in [*rw_raw, *ro_raw, *overlay_raw, *git_raw] if _WIN_PATH.match(p)})
    mapping = wsl_paths(distro, windows)

    def conv(p: str) -> str:
        return mapping.get(p, p)

    setenv = {
        k: v for k, v in env.items() if k not in WINDOWS_ENV_KEYS and k not in ("PATH", "HOME", "USER")
    }
    setenv |= {
        "HOME": home,
        "PATH": ":".join(e for e in info.path.split(":") if e and not e.startswith("/mnt/")),
        **_GIT_ENV,
    }
    if layout:  # a Windows worktree's ``.git`` file holds a Windows path git cannot follow here
        setenv |= {
            "GIT_DIR": conv(str(layout.gitdir)),
            "GIT_COMMON_DIR": conv(str(layout.common)),
            "GIT_WORK_TREE": conv(str(layout.root)),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
        }
    inner = _wrap_bwrap(
        args,
        cwd=conv(str(cwd)),
        home=home,
        ro=_dedupe(conv(p) for p in ro_raw),
        rw=_dedupe(conv(p) for p in rw_raw),
        overlays=[conv(p) for p in overlay_raw],
        setenv=setenv,
    )
    # ``--cd /``: do not depend on how WSL maps the (Windows) working directory of this process.
    return [*_wsl_prefix(distro), "--cd", "/", "--exec", *inner]


def seatbelt_profile(
    *, ro: list[str], rw: list[str], overlays: list[Path], scratch: Path
) -> str:
    """SBPL profile: deny by default, then allow only what the harness needs."""

    def sub(paths: Iterable[str]) -> str:
        return " ".join(f"(subpath {sbpl_quote(p)})" for p in paths)

    def lit(paths: Iterable[str]) -> str:
        return " ".join(f"(literal {sbpl_quote(p)})" for p in paths)

    readable = [*SEATBELT_SYSTEM_READ_SUBPATHS, *_MAC_TOOLS_RO, *ro]
    traversable = seatbelt_ancestors(
        *(Path(p) for p in [*readable, *rw, str(scratch)]),
        *(Path(p) for p in SEATBELT_SYSTEM_READ_LITERALS),
    )
    rules = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow sysctl-read)",
        "(allow mach*)",
        "(allow ipc*)",
        "(allow network*)",
        "(allow pseudo-tty)",
        "(allow user-preference-read)",
        "(allow signal (target same-sandbox))",
        # Ancestors stay searchable (metadata only) so deep allowed paths resolve; the rest of
        # $HOME can be neither listed nor read.
        '(allow file-read* (literal "/"))',
        "(allow file-read-metadata "
        + lit([*SEATBELT_TRAVERSABLE_LITERALS, *traversable])
        + ")",
        f"(allow file-read* {sub(readable)})",
        f"(allow file-read* {lit(SEATBELT_SYSTEM_READ_LITERALS)})",
        f"(allow file-write* {lit(_MAC_DEV_WRITE)})",
        f"(allow file-read* file-write* {sub([*rw, str(scratch)])})",
    ]
    for path in overlays:
        # Later rules win: hooks/config of the shared .git stay readable but not writable.
        rules.append(f"(deny file-write* (subpath {sbpl_quote(str(path))}))")
    return "\n".join(rules)


def _wrap_seatbelt(
    args: list[str], *, ro: list[str], rw: list[str], overlays: list[Path]
) -> list[str]:
    scratch = scratch_dir()
    profile = seatbelt_profile(ro=ro, rw=rw, overlays=overlays, scratch=scratch)
    env_args = [f"{k}={v}" for k, v in _GIT_ENV.items()] + [f"TMPDIR={scratch}"]
    # sandbox-exec has no --chdir; the child inherits the cwd the caller spawns it with.
    return ["/usr/bin/sandbox-exec", "-p", profile, "/usr/bin/env", *env_args, *args]
