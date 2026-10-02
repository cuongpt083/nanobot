from pathlib import Path

from nanobot.utils.prompt_templates import _clean_path_for_loader, render_template


def test_clean_path_for_loader_strips_windows_verbatim_prefix() -> None:
    assert _clean_path_for_loader(r"\\?\C:\foo\bar") == r"C:\foo\bar"
    assert _clean_path_for_loader(r"\\?\UNC\server\share\path") == r"\\server\share\path"
    assert _clean_path_for_loader(r"C:\normal\path") == r"C:\normal\path"
    assert _clean_path_for_loader("/posix/path") == "/posix/path"
    assert _clean_path_for_loader(Path(r"C:\normal\path")) == r"C:\normal\path"


def test_render_template_platform_policy() -> None:
    result = render_template("agent/platform_policy.md", system="Windows")
    assert "Platform Policy (Windows)" in result
    assert "You are running on Windows" in result
