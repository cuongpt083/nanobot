"""coding.sandbox = "wsl": bwrap inside a WSL2 distro (WSL itself is mocked, runs on any OS)."""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

import pytest

from nanobot.coworker.coding import sandbox
from nanobot.coworker.coding.sandbox import (
    SandboxPolicy,
    SandboxUnavailableError,
    check_available,
    wrap_argv,
)

WSL = SandboxPolicy(mode="wsl", distro="Ubuntu")


def _after(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


def _setenv(argv: list[str]) -> dict[str, str]:
    return {argv[i + 1]: argv[i + 2] for i, a in enumerate(argv) if a == "--setenv"}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "_probe_results", {})
    monkeypatch.setattr(sandbox, "_wsl_info_cache", {})


@pytest.fixture
def fake_wsl(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """A distro with home /home/me and agy in ~/.local/bin; records the wslpath requests."""
    asked: list[list[str]] = []
    monkeypatch.setattr(
        sandbox,
        "wsl_info",
        lambda distro, exe: sandbox.WslInfo(
            home="/home/me",
            path="/home/me/.local/bin:/usr/bin:/mnt/c/Windows:/snap/bin",
            exe="/home/me/.local/bin/agy",
            exe_real="/home/me/.local/share/agy/agy",
        ),
    )

    def fake_paths(distro: str | None, paths: list[str]) -> dict[str, str]:
        asked.append(paths)
        return {p: "/mnt/" + p[0].lower() + p[2:].replace("\\", "/") for p in paths}

    monkeypatch.setattr(sandbox, "wsl_paths", fake_paths)
    return asked


def test_runs_bwrap_in_the_distro_with_a_translated_project(
    fake_wsl: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows-flavoured paths on any OS: pathlib calls that touch the disk are neutralised.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: PureWindowsPath("C:/Users/Admin")))  # type: ignore[arg-type]
    monkeypatch.setattr(sandbox, "git_layout", lambda cwd: None)
    monkeypatch.setattr(sandbox, "git_binds", lambda cwd: ([cwd], []))
    project = _FakePath("C:\\Users\\Admin\\temp\\proj")
    env = {
        "PATH": "C:\\Windows", "HOME": "C:\\Users\\Admin", "USERPROFILE": "C:\\Users\\Admin",
        "SYSTEMROOT": "C:\\Windows", "TERM": "dumb", "MY_KEY": "v",
    }
    prompt = 'multi\nline "quoted" $HOME'
    argv = wrap_argv(
        ["agy", "-p", prompt], policy=WSL, cwd=project, env=env,  # type: ignore[arg-type]
        state_dirs=[PureWindowsPath("C:/Users/Admin/.gemini")],
    )
    assert argv[1:6] == ["-d", "Ubuntu", "--cd", "/", "--exec"] and argv[6] == "bwrap"
    assert argv[-3:] == ["agy", "-p", prompt]  # no shell in between: the prompt is untouched
    assert _after(argv, "--chdir") == ["/mnt/c/Users/Admin/temp/proj"]
    writable = _after(argv, "--bind") + _after(argv, "--bind-try")
    assert "/mnt/c/Users/Admin/temp/proj" in writable
    assert "/home/me/.gemini" in writable  # login state lives in the distro, not on Windows
    assert "/home/me" in _after(argv, "--tmpfs")
    assert "/home/me/.local/bin" in _after(argv, "--ro-bind-try")
    setenv = _setenv(argv)
    assert setenv["HOME"] == "/home/me"
    assert "/mnt/" not in setenv["PATH"] and "/usr/bin" in setenv["PATH"]  # Windows PATH not exposed
    assert "USERPROFILE" not in setenv and "SYSTEMROOT" not in setenv
    assert setenv["MY_KEY"] == "v" and setenv["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert fake_wsl and all(re.match(r"^[A-Za-z]:", p) for p in fake_wsl[0])  # only Windows paths


class _FakePath:
    """Just enough of ``Path`` for ``wrap_argv`` to treat a Windows path on any OS."""

    def __init__(self, text: str) -> None:
        self._text = text

    def resolve(self) -> _FakePath:
        return self

    def __str__(self) -> str:
        return self._text


def test_worktree_points_git_at_translated_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    gitdir = repo / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    monkeypatch.setattr(
        sandbox, "wsl_info",
        lambda d, e: sandbox.WslInfo("/home/me", "/usr/bin", "/usr/bin/agy", "/usr/bin/agy"),
    )
    monkeypatch.setattr(sandbox, "_WIN_PATH", re.compile(r"^(/|[A-Za-z]:)"))  # tmp paths count as Windows
    monkeypatch.setattr(sandbox, "wsl_paths", lambda d, paths: {p: "/mnt/x/" + p.lstrip("/") for p in paths})

    argv = wrap_argv(["agy"], policy=WSL, cwd=worktree, env={})

    def mapped(path: Path) -> str:
        return "/mnt/x/" + str(path.resolve()).lstrip("/")

    setenv = _setenv(argv)
    assert setenv["GIT_DIR"] == mapped(gitdir)
    assert setenv["GIT_COMMON_DIR"] == mapped(repo / ".git")
    assert setenv["GIT_WORK_TREE"] == mapped(worktree)
    assert setenv["GIT_CONFIG_KEY_0"] == "safe.directory"
    assert mapped(repo / ".git" / "hooks") in _after(argv, "--ro-bind-try")  # still read-only


def test_missing_harness_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        stdout = "@@HOME=/home/me\n@@PATH=/usr/bin\n"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(sandbox, "_wsl_run", lambda *a, **k: Proc())
    with pytest.raises(SandboxUnavailableError, match="not installed inside WSL"):
        sandbox.wsl_info("Ubuntu", "agy")


def test_info_survives_login_shell_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        stdout = (
            "Welcome to Ubuntu!\n@@HOME=/home/me\n@@PATH=/usr/bin\n"
            "@@EXE=/usr/bin/agy\n@@REAL=/opt/agy/bin/agy\n"
        )
        stderr = ""
        returncode = 0

    monkeypatch.setattr(sandbox, "_wsl_run", lambda *a, **k: Proc())
    info = sandbox.wsl_info("Ubuntu", "agy")
    assert (info.home, info.exe, info.exe_real) == ("/home/me", "/usr/bin/agy", "/opt/agy/bin/agy")


def test_wsl_is_refused_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox.os, "name", "posix")
    with pytest.raises(SandboxUnavailableError, match="for Windows"):
        check_available(WSL)
