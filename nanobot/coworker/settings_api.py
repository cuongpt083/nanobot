"""Settings backend for the WebUI Coworker page (advisor, team, coding).

Reads and writes ``coworker.json`` (see :mod:`nanobot.coworker.config`). The WebUI route layer
stays a thin wrapper: everything that can be tested without a server lives here.

Write rules:
- Only the ``advisor``, ``room``, ``coding`` and ``context`` sections are editable; a submitted section replaces
  that section wholesale (the form always sends the complete section).
- The result must validate as :class:`CoworkerConfig`; preset names must exist; every coding repo
  must be an absolute path to a git repository.
- The file is written atomically (temp file + ``os.replace``). Keys this code does not know about
  are preserved, and an existing file that is not valid JSON is never overwritten.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nanobot.coworker import config as coworker_config
from nanobot.coworker.advisor.state import OFF
from nanobot.coworker.config import CoworkerConfig, coworker_config_path, load_coworker_config
from nanobot.coworker.transcript import as_dict

EDITABLE_SECTIONS = ("advisor", "room", "coding", "context")
DETECT_TIMEOUT_S = 3.0
GIT_TIMEOUT_S = 3.0
_KNOWN_BACKENDS = ("pi", "agy")
_MAX_ERRORS = 5


class CoworkerSettingsError(ValueError):
    """User-facing validation failure."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ---------- detection ----------

def _binary_stem(command: list[str]) -> str:
    return Path(command[0]).stem.lower() if command else ""


def detect_backend(name: str, command: list[str]) -> dict[str, Any]:
    """Locate a harness binary and, for the known CLIs only, ask it for ``--version``.

    Custom commands (tests point them at scripts) are reported but never executed here.
    """
    result: dict[str, Any] = {"name": name, "command": command, "found": False, "path": None,
                              "version": None, "custom": _binary_stem(command) != name}
    if not command:
        return result
    binary = command[0]
    located = shutil.which(binary) or (binary if Path(binary).is_file() else None)
    if located is None:
        return result
    result.update(found=True, path=str(located))
    if result["custom"]:
        return result
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, known binary name, short timeout
            [*command, "--version"],
            capture_output=True,
            text=True,
            timeout=DETECT_TIMEOUT_S,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        text = (proc.stdout or proc.stderr or "").strip()
        result["version"] = text.splitlines()[0][:80] if proc.returncode == 0 and text else None
    except (OSError, subprocess.SubprocessError):
        result["version"] = None
    return result


def detect_backends(cfg: CoworkerConfig) -> dict[str, dict[str, Any]]:
    return {
        "pi": detect_backend("pi", cfg.coding.pi.command),
        "agy": detect_backend("agy", cfg.coding.agy.command),
    }


# ---------- repos ----------

def check_repo(path: str) -> dict[str, Any]:
    """Validate a configured project path: absolute and an existing directory.

    ``kind`` says whether it is a git work tree or a plain folder (edited in place by the coding
    agent); both are valid project profiles.
    """
    info: dict[str, Any] = {"path": path, "ok": False, "error": None, "branch": None, "kind": None}
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        info["error"] = "path must be absolute"
        return info
    if not candidate.is_dir():
        info["error"] = "directory not found"
        return info
    try:
        top = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--show-toplevel"],
            cwd=candidate, capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
            stdin=subprocess.DEVNULL, check=False,
        )
        if top.returncode != 0:
            info.update(ok=True, kind="directory")
            return info
        branch = subprocess.run(  # noqa: S603
            ["git", "symbolic-ref", "--short", "-q", "HEAD"],  # works on unborn branches; detached → ""
            cwd=candidate, capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
            stdin=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        info.update(ok=True, kind="directory")  # no usable git: still a folder the user can pick
        return info
    info.update(ok=True, kind="git", branch=branch.stdout.strip() or None)
    return info


# ---------- payload ----------

def coworker_settings_payload(preset_names: Iterable[str], *, detect: bool = True) -> dict[str, Any]:
    cfg = load_coworker_config()
    return {
        "config": {name: getattr(cfg, name).model_dump(mode="json") for name in EDITABLE_SECTIONS},
        "path": str(coworker_config_path()),
        "presets": sorted(set(preset_names) | {"default"}),
        "detection": detect_backends(cfg) if detect else {},
        "repos": [check_repo(r.path) for r in cfg.coding.repos],
    }


# ---------- update ----------

def _format_validation(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors()[:_MAX_ERRORS]:
        loc = ".".join(str(p) for p in err["loc"])
        message = str(err["msg"]).removeprefix("Value error, ")
        parts.append(f"{loc}: {message}")
    return "; ".join(parts) or "invalid configuration"


def _check_presets(cfg: CoworkerConfig, preset_names: set[str]) -> None:
    known = preset_names | {"default"}
    if cfg.advisor.preset and cfg.advisor.preset != OFF and cfg.advisor.preset not in known:
        raise CoworkerSettingsError(f"advisor.preset: unknown model preset {cfg.advisor.preset!r}")
    seen: set[str] = set()
    for index, agent in enumerate(cfg.room.agents):
        if agent.id in seen:
            raise CoworkerSettingsError(f"room.agents[{index}].id: duplicate agent id {agent.id!r}")
        seen.add(agent.id)
        if agent.preset and agent.preset not in known:
            raise CoworkerSettingsError(
                f"room.agents[{index}].preset: unknown model preset {agent.preset!r}"
            )


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SECRET_ENV = re.compile(r"(API[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)", re.IGNORECASE)


def _check_pass_env(cfg: CoworkerConfig) -> None:
    """Harnesses authenticate on their own; the WebUI must not forward secrets to them."""
    for backend in ("pi", "agy"):
        for name in getattr(cfg.coding, backend).pass_env:
            if not _ENV_NAME.fullmatch(name):
                raise CoworkerSettingsError(f"coding.{backend}.pass_env: {name!r} is not a variable name")
            if _SECRET_ENV.search(name):
                raise CoworkerSettingsError(
                    f"coding.{backend}.pass_env: {name!r} looks like a credential; "
                    "log in inside the harness instead of forwarding secrets"
                )


def _check_repos(cfg: CoworkerConfig) -> None:
    seen: set[str] = set()
    for index, repo in enumerate(cfg.coding.repos):
        if repo.path in seen:
            raise CoworkerSettingsError(f"coding.repos[{index}].path: duplicate repository")
        seen.add(repo.path)
        checked = check_repo(repo.path)
        if not checked["ok"]:
            raise CoworkerSettingsError(f"coding.repos[{index}].path: {checked['error']}")


def _deep_merge(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """``new`` wins; nested dicts merge so keys unknown to the schema survive; lists are replaced."""
    merged = dict(base)
    for key, value in new.items():
        current = as_dict(merged.get(key))
        incoming = as_dict(value)
        if current is not None and incoming is not None:
            merged[key] = _deep_merge(current, incoming)
        else:
            merged[key] = value
    return merged


def _read_raw(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise CoworkerSettingsError(f"cannot read {path}: {exc}", status=500) from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise CoworkerSettingsError(
            f"{path} is not valid JSON; fix or remove it before saving from the WebUI", status=409
        ) from exc
    result = as_dict(data)
    if result is None:
        raise CoworkerSettingsError(f"{path} must contain a JSON object", status=409)
    return result


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise CoworkerSettingsError(f"cannot write {path}: {exc}", status=500) from exc


def update_coworker_settings(
    values: dict[str, Any],
    preset_names: Iterable[str],
    *,
    detect: bool = True,
) -> dict[str, Any]:
    """Validate and persist submitted sections; return the fresh settings payload."""
    unknown = sorted(set(values) - set(EDITABLE_SECTIONS))
    if unknown:
        raise CoworkerSettingsError(f"unknown section(s): {', '.join(unknown)}")
    submitted = {k: v for k, v in values.items() if v is not None}
    for name, section in submitted.items():
        if not isinstance(section, dict):
            raise CoworkerSettingsError(f"{name}: must be an object")
    if not submitted:
        raise CoworkerSettingsError("nothing to update")

    names = set(preset_names)
    current = load_coworker_config()
    merged: dict[str, Any] = {name: getattr(current, name).model_dump(mode="json") for name in EDITABLE_SECTIONS}
    merged.update(submitted)
    try:
        new = CoworkerConfig.model_validate(merged)
    except ValidationError as exc:
        raise CoworkerSettingsError(_format_validation(exc)) from exc
    _check_presets(new, names)
    if "coding" in submitted:
        _check_pass_env(new)
        _check_repos(new)

    path = coworker_config_path()
    raw = _read_raw(path)
    for name in submitted:
        dumped = getattr(new, name).model_dump(mode="json", by_alias=True)
        existing = as_dict(raw.get(name))
        raw[name] = _deep_merge(existing, dumped) if existing is not None else dumped
    _write_atomic(path, raw)
    coworker_config.invalidate_coworker_config_cache()
    return coworker_settings_payload(names, detect=detect)
