"""bwrap wrapping of coding harnesses (argv construction is platform independent)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from nanobot.coworker.coding import sandbox
from nanobot.coworker.coding.sandbox import (
    SandboxPolicy,
    SandboxUnavailableError,
    check_available,
    git_binds,
    wrap_argv,
)

BWRAP = SandboxPolicy(mode="bwrap")
SEATBELT = SandboxPolicy(mode="seatbelt")
WSL = SandboxPolicy(mode="wsl", distro="Ubuntu")


def _pairs(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


def test_inactive_policy_leaves_argv_alone(tmp_path: Path) -> None:
    args = ["agy", "-p", "x"]
    assert wrap_argv(args, policy=SandboxPolicy(), cwd=tmp_path, env={}) is args


def test_project_and_state_are_the_only_writable_paths(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    state = tmp_path / "state"
    argv = wrap_argv(
        ["agy", "-p", "x"], policy=BWRAP, cwd=project, env={"HOME": str(tmp_path / "home")},
        state_dirs=[state],
    )
    assert argv[0] == "bwrap" and argv[-3:] == ["agy", "-p", "x"]
    assert argv[argv.index("--") - 2 :][:2] == ["--chdir", str(project.resolve())]
    writable = _pairs(argv, "--bind") + _pairs(argv, "--bind-try")
    assert str(project.resolve()) in writable and str(state) in writable
    assert not any(p in writable for p in ("/", "/usr", "/etc", str(tmp_path / "home")))
    assert "--die-with-parent" in argv and "--unshare-pid" in argv
    # Home is hidden behind a tmpfs (no ~/.ssh ...), and the network namespace is left shared.
    assert str((tmp_path / "home").resolve()) in _pairs(argv, "--tmpfs")
    assert "--unshare-net" not in argv


def test_home_tmpfs_comes_before_the_binds_under_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "proj"
    project.mkdir(parents=True)
    argv = wrap_argv(["x"], policy=BWRAP, cwd=project, env={"HOME": str(home)})
    assert argv.index(str(home.resolve())) < len(argv) - argv[::-1].index(str(project.resolve()))
    assert argv.index("--tmpfs") < argv.index("--bind")


def test_extra_binds_from_policy(tmp_path: Path) -> None:
    ro, rw = tmp_path / "nvm", tmp_path / "cache"
    policy = SandboxPolicy(mode="bwrap", ro_binds=(str(ro),), rw_binds=(str(rw),))
    argv = wrap_argv(["pi"], policy=policy, cwd=tmp_path, env={"HOME": str(tmp_path)})
    assert str(ro) in _pairs(argv, "--ro-bind-try")
    assert str(rw) in _pairs(argv, "--bind-try")


def test_worktree_gets_main_git_dir_but_hooks_and_config_stay_readonly(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    common = repo / ".git"
    gitdir = common / "worktrees" / "wt1"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = tmp_path / "wt1"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    sub = worktree / "pkg"
    sub.mkdir()

    rw, ro = git_binds(sub)
    assert worktree in rw and common.resolve() in rw
    assert common.resolve() / "hooks" in ro and common.resolve() / "config" in ro

    argv = wrap_argv(["agy"], policy=BWRAP, cwd=sub, env={"HOME": str(tmp_path / "h")})
    last_rw = max(i for i, a in enumerate(argv) if a in ("--bind", "--bind-try"))
    hooks_ro = argv.index(str(common.resolve() / "hooks"))
    assert hooks_ro > last_rw  # overlay is applied after the writable mounts
    assert argv[hooks_ro - 1] == "--ro-bind-try"


def test_plain_directory_has_no_git_overlays(tmp_path: Path) -> None:
    assert git_binds(tmp_path) == ([tmp_path], [])


def test_path_entries_under_home_are_readable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    tools = home / ".local" / "bin"
    tools.mkdir(parents=True)
    argv = wrap_argv(
        ["agy"], policy=BWRAP, cwd=tmp_path, env={"HOME": str(home), "PATH": f"{tools}{os.pathsep}/usr/bin"}
    )
    assert str(tools) in _pairs(argv, "--ro-bind-try")


@pytest.fixture(autouse=True)
def _fresh_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "_probe_results", {})


def test_wrong_platform_is_refused_not_run_unwrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox.sys, "platform", "win32")
    with pytest.raises(SandboxUnavailableError, match="only works on Linux"):
        check_available(BWRAP)
    with pytest.raises(SandboxUnavailableError, match="only works on macOS"):
        check_available(SEATBELT)
    check_available(SandboxPolicy())  # no sandbox requested: nothing to check


def test_missing_bwrap_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox.shutil, "which", lambda *_a, **_k: None)
    with pytest.raises(SandboxUnavailableError, match="not installed"):
        check_available(BWRAP)


def test_seatbelt_argv_is_a_deny_by_default_profile(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    state = tmp_path / "home" / ".gemini"
    argv = wrap_argv(
        ["agy", "-p", "x"], policy=SEATBELT, cwd=project, env={"HOME": str(tmp_path / "home")},
        state_dirs=[state],
    )
    assert argv[0] == "/usr/bin/sandbox-exec" and argv[1] == "-p"
    assert argv[-3:] == ["agy", "-p", "x"] and argv[3] == "/usr/bin/env"
    assert any(a.startswith("TMPDIR=") for a in argv) and "GIT_CONFIG_GLOBAL=/dev/null" in argv
    profile = argv[2]
    assert profile.splitlines()[:2] == ["(version 1)", "(deny default)"]
    writable = next(line for line in profile.splitlines() if "file-write*" in line and "subpath" in line)
    assert sandbox.sbpl_quote(str(project.resolve())) in writable
    assert sandbox.sbpl_quote(str(state)) in writable
    assert "(allow file-read* (subpath \"/\"" not in profile  # no blanket read
    assert str(tmp_path / "home") + '"' not in "".join(  # the home directory itself is not granted
        line for line in profile.splitlines() if "file-read*" in line and "subpath" in line
    )


def test_seatbelt_keeps_git_hooks_and_config_readonly(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    gitdir = repo / ".git" / "worktrees" / "wt1"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = tmp_path / "wt1"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    argv = wrap_argv(["agy"], policy=SEATBELT, cwd=worktree, env={"HOME": str(tmp_path / "h")})
    lines = argv[2].splitlines()
    hooks = sandbox.sbpl_quote(str((repo / ".git").resolve() / "hooks"))
    deny = max(i for i, line in enumerate(lines) if line.startswith("(deny file-write*") and hooks in line)
    grant = max(i for i, line in enumerate(lines) if line.startswith("(allow file-read* file-write*"))
    assert deny > grant  # last matching rule wins


@pytest.mark.skipif(os.name == "nt", reason="quotes are not valid in Windows file names")
def test_seatbelt_quotes_hostile_paths(tmp_path: Path) -> None:
    evil = tmp_path / 'a"b)(allow file-write* (subpath "/"))'
    evil.mkdir()
    argv = wrap_argv(["x"], policy=SEATBELT, cwd=evil, env={"HOME": str(tmp_path)})
    assert '(allow file-write* (subpath "/"))' not in argv[2].replace('\\"', "")


@pytest.mark.skipif(not sys.platform.startswith("linux") or not shutil.which("bwrap"), reason="needs bwrap")
def test_real_bwrap_confines_writes(tmp_path: Path) -> None:
    try:
        check_available(BWRAP)
    except SandboxUnavailableError as exc:
        pytest.skip(str(exc))
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id").write_text("secret", encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()
    script = f"touch inside; touch '{home}/escaped'; test ! -e '{home}/.ssh/id'"
    argv = wrap_argv(["sh", "-c", script], policy=BWRAP, cwd=project, env={"HOME": str(home)})
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert (project / "inside").exists()  # the project is writable
    assert not (home / "escaped").exists()  # home is a throwaway tmpfs
    assert (home / ".ssh" / "id").read_text(encoding="utf-8") == "secret"
    assert proc.returncode == 0, proc.stderr  # ~/.ssh is invisible inside
