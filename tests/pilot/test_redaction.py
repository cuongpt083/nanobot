"""Tests for Redactor."""

from nanobot.pilot.redaction import Redactor


def test_redact_private_key() -> None:
    redactor = Redactor()
    raw = "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...\n-----END PRIVATE KEY-----"
    res = redactor.redact_string(raw)
    assert "[REDACTED]" in res.data
    assert "MIIEvg" not in res.data
    assert "private_key" in res.rule_codes


def test_redact_api_key_and_bearer() -> None:
    redactor = Redactor()
    raw = "Header Bearer eyJhbGciOi... with key sk-abcdef1234567890"
    res = redactor.redact_string(raw)
    assert "sk-abcdef1234567890" not in res.data
    assert "Bearer" not in res.data or "[REDACTED]" in res.data
    assert "api_key" in res.rule_codes or "bearer" in res.rule_codes


def test_redact_paths() -> None:
    redactor = Redactor()
    posix = "File at /var/log/syslog"
    win = r"File at C:\Users\Admin\secrets.txt"
    r_posix = redactor.redact_string(posix)
    r_win = redactor.redact_string(win)
    assert "/var/log/syslog" not in r_posix.data
    assert "posix_path" in r_posix.rule_codes
    assert r"C:\Users\Admin\secrets.txt" not in r_win.data
    assert "windows_path" in r_win.rule_codes


def test_redact_exception() -> None:
    redactor = Redactor()
    raw = "Error occurred: Exception: Secret db password failed"
    res = redactor.redact_string(raw)
    assert "Secret db password failed" not in res.data
    assert "exception_text" in res.rule_codes


def test_size_trimmed() -> None:
    redactor = Redactor(max_chars=10)
    res = redactor.redact_string("Hello World 1234567890")
    assert "[TRUNCATED]" in res.data
    assert "size_trimmed" in res.rule_codes
    assert len(res.data) <= 30  # 10 + len('...[TRUNCATED]')


def test_redact_structure_nested() -> None:
    redactor = Redactor()
    nested = {
        "user": "alice",
        "api_key": "sk-1234567890123456",
        "details": {
            "token": "secret_token_abc",
            "logs": ["Path /tmp/foo.txt", "Normal log"],
        },
    }
    res = redactor.redact_structure(nested)
    data = res.data
    assert data["user"] == "alice"
    assert data["api_key"] == "[REDACTED]"
    assert data["details"]["token"] == "[REDACTED]"
    assert "/tmp/foo.txt" not in data["details"]["logs"][0]
    assert "tool_argument" in res.rule_codes
    assert "posix_path" in res.rule_codes
