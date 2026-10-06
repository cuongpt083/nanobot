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

import asyncio
import functools
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from loguru import logger
from pydantic import ValidationError
from pydantic.alias_generators import to_camel, to_snake

from nanobot.coworker import config as coworker_config
from nanobot.coworker import metrics_store
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


def coworker_metrics_payload(
    *,
    timezone_name: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Read-only 30-day cache / keep-warm / optimize history for the settings Cache tab."""
    return metrics_store.metrics_payload(days=days, timezone_name=timezone_name)


# ---------- per-phase Pi models ----------

_PHASE_MODELS_TTL_S = 600.0
_phase_models_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_PHASE_NAMES = ("plan", "implement", "review")


def _default_thinking_levels() -> list[str]:
    return ["off", "minimal", "low", "medium", "high", "xhigh", "max"]


async def _fetch_phase_models_async() -> dict[str, Any]:
    from nanobot.coworker.coding.backends.base import sandbox_policy_for
    from nanobot.coworker.coding.pi.client import PiClient
    from nanobot.coworker.coding.pi.version import resolve_pi_binary
    from nanobot.coworker.coding.runtime import SessionSpec

    cfg = load_coworker_config()
    pi_cfg = cfg.coding.pi
    resolved = resolve_pi_binary(list(pi_cfg.command))
    binary = resolved[0] if resolved else "pi"
    if not (shutil.which(binary) or Path(binary).exists()):
        return {
            "models": [],
            "thinking_levels": _default_thinking_levels(),
            "error": "Pi binary not found; run `/code doctor`.",
        }

    client = PiClient(
        config=pi_cfg,
        sandbox_policy=sandbox_policy_for(cfg),
        timeout_minutes=cfg.coding.timeout_minutes,
        idle_timeout_minutes=cfg.coding.idle_timeout_minutes,
    )
    try:
        await client.start(cwd=Path.cwd(), session=SessionSpec(task_id="ct-phase-models"))
        raw_models = await client.available_models()
        try:
            levels = await client.available_thinking_levels()
        except Exception:
            levels = []
    except Exception as exc:
        return {
            "models": [],
            "thinking_levels": _default_thinking_levels(),
            "error": f"{exc} (run `/code doctor`)",
        }
    finally:
        try:
            await client.close()
        except Exception:
            pass

    options: list[dict[str, Any]] = []
    for model in raw_models:
        provider = str(model.get("provider") or "")
        model_id = str(model.get("id") or model.get("modelId") or model.get("model") or "")
        if not model_id:
            continue
        value = f"{provider}/{model_id}" if provider else model_id
        options.append({"value": value, "label": value, "provider": provider, "model_id": model_id})
    return {
        "models": options,
        "thinking_levels": levels or _default_thinking_levels(),
        "error": None,
    }


def coworker_phase_models_payload(*, refresh: bool = False, detect: bool = True) -> dict[str, Any]:
    """Available Pi models / thinking levels for the per-phase pickers (10-minute cache)."""
    if not detect:
        return {"models": [], "thinking_levels": _default_thinking_levels(), "error": None}
    now = time.time()
    cached = _phase_models_cache.get("payload")
    if (
        not refresh
        and cached is not None
        and (now - float(_phase_models_cache.get("at", 0.0))) < _PHASE_MODELS_TTL_S
    ):
        return cast(dict[str, Any], cached)
    try:
        payload = asyncio.run(_fetch_phase_models_async())
    except Exception as exc:
        payload = {"models": [], "thinking_levels": _default_thinking_levels(), "error": str(exc)}
    _phase_models_cache["at"] = now
    _phase_models_cache["payload"] = payload
    return payload


def _check_phase_models(cfg: CoworkerConfig) -> list[str]:
    """Validate ``coding.pi.phases.*.model`` format; warn about values missing from the cache."""
    phases = getattr(cfg.coding.pi, "phases", None)
    if phases is None:
        return []
    cached = _phase_models_cache.get("payload")
    known: set[str] | None = None
    if isinstance(cached, dict):
        models = cast("dict[str, Any]", cached).get("models")
        if models:
            known = {str(m.get("value")) for m in cast("list[dict[str, Any]]", models)}
    warnings: list[str] = []
    for phase_name in _PHASE_NAMES:
        phase = getattr(phases, phase_name, None)
        model = getattr(phase, "model", None) if phase is not None else None
        if not model:
            continue
        if "/" not in model:
            raise CoworkerSettingsError(
                f"coding.pi.phases.{phase_name}.model: must be 'provider/modelId' (got {model!r})"
            )
        if known is not None and model not in known:
            warnings.append(
                f"coding.pi.phases.{phase_name}.model: {model!r} is not in the current model list"
            )
    implement_model = getattr(getattr(phases, "implement", None), "model", None)
    review_model = getattr(getattr(phases, "review", None), "model", None)
    if implement_model and review_model and implement_model == review_model:
        warnings.append(
            "coding.pi.phases.review.model matches implement.model; "
            "use a different (ideally stronger) model so the reviewer stays independent"
        )
    return warnings


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


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return cast(list[object], value)
    return []


@functools.lru_cache(maxsize=1)
def _known_tool_names() -> set[str]:
    """Discover all built-in and plugin tool names statically without running full runtime init."""
    from nanobot.agent.tools.loader import ToolLoader

    names: set[str] = set()
    for tool_cls in ToolLoader().discover():
        prop = getattr(tool_cls, "name", None)
        if isinstance(prop, property) and prop.fget is not None:
            try:
                val = prop.fget(None)  # Constant tool names define property getters callable without self
                if isinstance(val, str):
                    names.add(val)
            except Exception:
                pass
        elif isinstance(prop, str):
            names.add(prop)
    return names


def _check_agents(cfg: CoworkerConfig, workspace: Path | None = None) -> list[str]:
    """Validate room agents configuration.

    - Warns (returns warning strings) if an agent's `home` directory does not exist yet.
    - Raises CoworkerSettingsError if `home` tries to escape workspace or non-glob pattern in tools.allow
      matches no known tools. (Patterns with '*' or '?' or 'mcp:*' are skipped if unmatched to allow dynamic tools).
    """
    from nanobot.coworker.agents.toolset import matches_any, matches_tool_name, pattern_to_glob

    warnings: list[str] = []
    known_tools = _known_tool_names()

    for i, agent in enumerate(cfg.room.agents):
        # 1. home check
        if agent.home:
            if workspace is not None:
                # home is already validated relative without '..' by pydantic
                full_home = (workspace / agent.home).resolve()
                try:
                    full_home.relative_to(workspace.resolve())
                except ValueError:
                    raise CoworkerSettingsError(
                        f"room.agents[{i}].home: path {agent.home!r} escapes workspace"
                    )
                if not full_home.exists():
                    warnings.append(
                        f"room.agents[{i}] ({agent.id}): home directory '{agent.home}' does not exist"
                    )
        if matches_any("room_state", agent.tools.deny):
            warnings.append(
                f"room.agents[{i}] ({agent.id}): tools.deny removes room_state"
            )
        if not agent.home and (agent.tools.allow or agent.tools.deny):
            warnings.append(
                f"room.agents[{i}] ({agent.id}): tools.allow/deny apply only with home; "
                "legacy guests keep the default subagent toolset"
            )
        # 2. tools.allow check against known tools (same matcher as guest toolset)
        if agent.tools.allow and known_tools:
            for pattern in agent.tools.allow:
                glob = pattern_to_glob(pattern)
                has_wildcard = any(ch in glob for ch in ("*", "?", "[", "]"))
                is_mcp = pattern.startswith(("mcp:", "mcp_"))
                matches = any(matches_tool_name(t, pattern) for t in known_tools)
                if not matches and not has_wildcard and not is_mcp:
                    raise CoworkerSettingsError(
                        f"room.agents[{i}].tools.allow: pattern {pattern!r} does not match any known tool"
                    )

    if warnings:
        for w in warnings:
            logger.warning("Coworker room agent config warning: {}", w)
    return warnings


def _merge_by_id(base: list[object], new: list[object]) -> list[object] | None:
    """Merge lists of {"id": ...} dicts by id; None if either list isn't id-keyed."""
    base_items = [as_dict(x) for x in base]
    new_items = [as_dict(x) for x in new]
    if any(d is None or "id" not in d for d in (*base_items, *new_items)):
        return None
    by_id: dict[object, dict[str, Any]] = {d["id"]: d for d in base_items if d is not None}
    out: list[object] = []
    for d in new_items:
        if d is None:
            continue
        prev = by_id.get(d["id"])
        out.append(_deep_merge(prev, d) if prev is not None else d)
    return out


def _deep_merge(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """``new`` wins; nested dicts merge so keys unknown to the schema survive; lists are replaced."""
    merged = dict(base)
    for key, value in new.items():
        current = as_dict(merged.get(key))
        incoming = as_dict(value)
        if current is not None and incoming is not None:
            merged[key] = _deep_merge(current, incoming)
        elif isinstance(value, list) and isinstance(merged.get(key), list):
            combined = _merge_by_id(cast(list[object], merged[key]), cast(list[object], value))
            merged[key] = combined if combined is not None else value
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
    workspace: Path | None = None,
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
    path = coworker_config_path()
    raw = _read_raw(path)
    current = load_coworker_config()
    merged: dict[str, Any] = {name: getattr(current, name).model_dump(mode="json") for name in EDITABLE_SECTIONS}

    # Pre-merge incoming room.agents with existing raw entries so keys omitted by the WebUI
    # form (e.g. home, tools, skills, memory...) are not wiped by model defaults.
    if "room" in submitted and isinstance(submitted["room"], dict):
        sub_room_dict: dict[str, Any] = dict(cast(dict[str, Any], submitted["room"]))
        raw_agents = sub_room_dict.get("agents")
        if isinstance(raw_agents, list):
            raw_room = as_dict(raw.get("room")) or {}
            raw_agents_list = _as_list(raw_room.get("agents"))
            raw_by_id: dict[str, dict[str, Any]] = {}
            for item in raw_agents_list:
                d = as_dict(item)
                if d and isinstance(d.get("id"), str):
                    raw_by_id[d["id"]] = d
            premerged_agents: list[object] = []
            for agent_item in cast(list[object], raw_agents):
                ad = as_dict(agent_item)
                if ad and isinstance(ad.get("id"), str) and ad["id"] in raw_by_id:
                    # Clean out keys from raw base that have a snake/camel equivalent in incoming ad
                    base_dict = dict(raw_by_id[ad["id"]])
                    for submitted_k in list(ad.keys()):
                        snake_k = to_snake(submitted_k)
                        camel_k = to_camel(submitted_k)
                        if snake_k != submitted_k:
                            base_dict.pop(snake_k, None)
                        if camel_k != submitted_k:
                            base_dict.pop(camel_k, None)
                    premerged_agents.append(_deep_merge(base_dict, ad))
                else:
                    premerged_agents.append(agent_item)
            sub_room_dict["agents"] = premerged_agents
        submitted["room"] = sub_room_dict

    merged.update(submitted)
    try:
        new = CoworkerConfig.model_validate(merged)
    except ValidationError as exc:
        raise CoworkerSettingsError(_format_validation(exc)) from exc
    _check_presets(new, names)
    if "room" in submitted:
        _check_agents(new, workspace)
    if "coding" in submitted:
        _check_pass_env(new)
        _check_repos(new)
        for warning in _check_phase_models(new):
            logger.warning("Coworker coding config warning: {}", warning)

    for name in submitted:
        dumped = getattr(new, name).model_dump(mode="json", by_alias=True)
        existing = as_dict(raw.get(name))
        raw[name] = _deep_merge(existing, dumped) if existing is not None else dumped
    _write_atomic(path, raw)
    coworker_config.invalidate_coworker_config_cache()
    return coworker_settings_payload(names, detect=detect)
