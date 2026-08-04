from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "caddy-webui.sh"


def test_install_cleanup_trap_captures_temp_path_before_function_returns() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'trap \'rm -f "${temp_config}"\' RETURN' not in source
    assert "printf -v cleanup_command 'rm -f -- %q' \"${temp_config}\"" in source
    assert 'trap "${cleanup_command}" RETURN' in source
