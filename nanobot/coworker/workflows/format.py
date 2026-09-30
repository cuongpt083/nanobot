"""Agent Workflow format: ``<dir>/workflow.md`` + ``<dir>/steps/*.md``.

Python port of AICoworker's graph-workflow format layer (wikilink-connected
markdown step graph). Workflow bundles stay file-compatible with AICoworker.

workflow.md frontmatter: ``name``, ``description``, ``start: "[[step-slug]]"``,
optional ``max_events``. Step frontmatter: ``type`` (task|decision|parallel|
join|human|end), ``title``, ``max_attempts``, ``on_fail`` (abort|continue).
Step body sections: ``## Next`` bullets ``- [[slug]] — when: <condition>`` and
``## Output`` with a ```json JSON-Schema (subset) for the step output.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanobot.coworker.transcript import as_dict, as_list

STEP_TYPES = ("task", "decision", "parallel", "join", "human", "end")
DEFAULT_MAX_ATTEMPTS = 10
DEFAULT_MAX_EVENTS = 1000

_FRONTMATTER = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
_NEXT_HEADING = re.compile(r"^##\s+Next\s*$", re.IGNORECASE | re.MULTILINE)
_OUTPUT_HEADING = re.compile(r"^##\s+Output\s*$", re.IGNORECASE | re.MULTILINE)
_JSON_FENCE = re.compile(r"```json\s*\r?\n([\s\S]*?)```")
_WHEN = re.compile(r"^\s*(?:—|–|--)?\s*when:\s*(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Edge:
    to: str
    label: str | None = None
    when: str | None = None
    extra_links: bool = False


@dataclass
class Step:
    slug: str
    file: Path
    type: str
    title: str
    max_attempts: int
    on_fail: str
    fm: dict[str, str]
    body: str
    next: list[Edge]
    output_schema: dict[str, Any] | None
    schema_error: str | None


@dataclass
class Workflow:
    dir: Path
    slug: str
    name: str
    description: str
    start: str | None
    max_events: int
    fm: dict[str, str]
    body: str
    steps: dict[str, Step] = field(default_factory=dict)


@dataclass
class Validation:
    ok: bool
    errors: list[str]
    warnings: list[str]


def parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    raw = raw.removeprefix("﻿")
    match = _FRONTMATTER.match(raw)
    if not match:
        return {}, raw
    fm: dict[str, str] = {}
    for line in match.group(1).splitlines():
        kv = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not kv:
            continue
        value = kv.group(2).strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fm[kv.group(1)] = value
    return fm, raw[match.end():]


def parse_wikilink(text: str) -> tuple[str, str | None] | None:
    match = _WIKILINK.search(text)
    if not match:
        return None
    return match.group(1).strip(), (match.group(2) or "").strip() or None


def parse_next_section(body: str) -> list[Edge]:
    heading = _NEXT_HEADING.search(body)
    if not heading:
        return []
    edges: list[Edge] = []
    for line in body[heading.end():].splitlines():
        if re.match(r"^#{1,6}\s", line):
            break
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        link = parse_wikilink(stripped)
        if link is None:
            continue
        after = stripped[stripped.index("]]") + 2:]
        when = _WHEN.match(after)
        edges.append(Edge(
            to=link[0],
            label=link[1],
            when=when.group(1).strip() if when else None,
            extra_links=stripped.count("[[") > 1,
        ))
    return edges


def parse_output_schema(body: str) -> tuple[dict[str, Any] | None, str | None]:
    heading = _OUTPUT_HEADING.search(body)
    if not heading:
        return None, None
    fence = _JSON_FENCE.search(body[heading.end():])
    if not fence:
        return None, None
    try:
        schema = as_dict(json.loads(fence.group(1)))
    except ValueError as exc:
        return None, f"invalid JSON in ## Output schema: {exc}"
    return (schema, None) if schema is not None else (None, "## Output schema must be a JSON object")


def _positive_int(value: str | None, default: int) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def load_step(path: Path, slug: str) -> Step:
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    schema, schema_error = parse_output_schema(body)
    return Step(
        slug=slug,
        file=path,
        type=(fm.get("type") or "task").lower(),
        title=fm.get("title") or re.sub(r"[-_]+", " ", slug).title(),
        max_attempts=_positive_int(fm.get("max_attempts"), DEFAULT_MAX_ATTEMPTS),
        on_fail=(fm.get("on_fail") or "abort").lower(),
        fm=fm,
        body=body,
        next=parse_next_section(body),
        output_schema=schema,
        schema_error=schema_error,
    )


def load_workflow(directory: Path) -> Workflow:
    directory = directory.expanduser().resolve()
    entry = directory / "workflow.md"
    if not entry.is_file():
        raise FileNotFoundError(f"workflow.md not found in {directory}")
    fm, body = parse_frontmatter(entry.read_text(encoding="utf-8"))
    start = parse_wikilink(fm["start"]) if fm.get("start") else None
    steps: dict[str, Step] = {}
    steps_dir = directory / "steps"
    if steps_dir.is_dir():
        for path in sorted(steps_dir.glob("*.md")):
            steps[path.stem] = load_step(path, path.stem)
    return Workflow(
        dir=directory,
        slug=directory.name,
        name=fm.get("name") or directory.name,
        description=fm.get("description", ""),
        start=start[0] if start else None,
        max_events=_positive_int(fm.get("max_events"), DEFAULT_MAX_EVENTS),
        fm=fm,
        body=body,
        steps=steps,
    )


def can_reach(wf: Workflow, source: str, target: str) -> bool:
    if source == target:
        return True
    seen: set[str] = set()
    stack = [source]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for edge in wf.steps[current].next if current in wf.steps else []:
            if edge.to == target:
                return True
            if edge.to not in seen:
                stack.append(edge.to)
    return False


def graph_fingerprint(wf: Workflow) -> str:
    """Hash of everything that affects run semantics; step prose is excluded."""
    parts = [f"start={wf.start}", f"max_events={wf.max_events}"]
    for slug in sorted(wf.steps):
        s = wf.steps[slug]
        edges = ",".join(f"{e.to}~{e.when or ''}" for e in s.next)
        schema = json.dumps(s.output_schema, separators=(",", ":")) if s.output_schema else ""
        parts.append(f"{slug}|{s.type}|{s.on_fail}|{s.max_attempts}|{edges}|{schema}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def validate_workflow(wf: Workflow, *, strict: bool = False) -> Validation:
    errors: list[str] = []
    warnings: list[str] = []

    def strict_issue(message: str) -> None:
        (errors if strict else warnings).append(message if strict else f"{message} (error under strict)")

    slugs = set(wf.steps)
    if not wf.start:
        errors.append('workflow.md frontmatter missing `start: "[[step-slug]]"`')
    elif wf.start not in slugs:
        errors.append(f"start step [[{wf.start}]] does not exist in steps/")
    for s in wf.steps.values():
        if s.type not in STEP_TYPES:
            errors.append(f'{s.slug}: unknown type "{s.type}" (allowed: {", ".join(STEP_TYPES)})')
        if s.on_fail not in ("abort", "continue"):
            errors.append(f'{s.slug}: on_fail must be "abort" or "continue"')
        if s.schema_error:
            errors.append(f"{s.slug}: {s.schema_error}")
        for edge in s.next:
            if edge.to not in slugs:
                errors.append(f"{s.slug}: Next links to missing step [[{edge.to}]]")
            if edge.extra_links:
                warnings.append(f"{s.slug}: a Next bullet contains multiple [[wikilinks]] — only the FIRST is an edge")
        if s.type == "end" and s.next:
            errors.append(f"{s.slug}: type end must not have Next links")
        if s.type == "decision":
            if len(s.next) < 2:
                errors.append(f"{s.slug}: decision needs >= 2 Next routes")
            if any(not e.when for e in s.next):
                warnings.append(f'{s.slug}: decision route without "when:" condition')
            props = as_dict((s.output_schema or {}).get("properties")) or {}
            route_enum = as_list((as_dict(props.get("route")) or {}).get("enum"))
            if not s.output_schema:
                strict_issue(f'{s.slug}: decision has no ## Output schema — small models need a "route" enum')
            elif route_enum is None:
                strict_issue(f"{s.slug}: ## Output schema has no properties.route.enum")
            else:
                targets = [e.to for e in s.next]
                for route in route_enum:
                    if route not in targets:
                        errors.append(f'{s.slug}: schema route enum value "{route}" is not a Next edge')
                for target in targets:
                    if target not in route_enum:
                        strict_issue(f'{s.slug}: Next edge "{target}" missing from schema route enum')
        if s.type == "parallel" and len(s.next) < 2:
            errors.append(f"{s.slug}: parallel needs >= 2 Next branches")
        if s.type in ("task", "human", "join") and len(s.next) > 1:
            warnings.append(f"{s.slug}: type {s.type} has {len(s.next)} Next links — consider type: decision")
        if s.type != "end" and not s.next:
            warnings.append(f"{s.slug}: no Next links and not type end — run will finish here")
    joins = [s.slug for s in wf.steps.values() if s.type == "join"]
    for i, a in enumerate(joins):
        for b in joins[i + 1:]:
            if can_reach(wf, a, b) and can_reach(wf, b, a):
                warnings.append(f"{a} + {b}: two joins on a shared cycle can block each other — avoid")
    if wf.start and wf.start in slugs:
        for slug in sorted(slugs):
            if slug != wf.start and not can_reach(wf, wf.start, slug):
                warnings.append(f"{slug}: unreachable from start")
    return Validation(ok=not errors, errors=errors, warnings=warnings)


def validate_against_schema(value: Any, schema: dict[str, Any] | None, path: str = "output") -> list[str]:
    """Minimal JSON-Schema subset: type, required, properties, additionalProperties:false, enum, items."""
    errs: list[str] = []
    if schema is None:
        return errs
    options = as_list(schema.get("enum"))
    if options is not None:
        encoded = json.dumps(value, sort_keys=True)
        if not any(json.dumps(e, sort_keys=True) == encoded for e in options):
            errs.append(f"{path}: must be one of {', '.join(json.dumps(e) for e in options)}")
        return errs
    expected = schema.get("type")
    actual = _json_type(value)
    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int | float) or int(value) != value:
            errs.append(f"{path}: must be an integer")
    elif expected == "number":
        if actual not in ("number", "integer"):
            errs.append(f"{path}: must be number, got {actual}")
            return errs
    elif expected and expected != actual:
        errs.append(f"{path}: must be {expected}, got {actual}")
        return errs
    obj = as_dict(value)
    if expected == "object" and obj is not None:
        props = as_dict(schema.get("properties")) or {}
        for req in as_list(schema.get("required")) or []:
            if req not in obj:
                errs.append(f"{path}.{req}: required field missing")
        for key, item in obj.items():
            if key in props:
                errs.extend(validate_against_schema(item, as_dict(props[key]), f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}.{key}: unknown field (allowed: {', '.join(props)})")
    items_schema = as_dict(schema.get("items"))
    array = as_list(value)
    if expected == "array" and array is not None and items_schema is not None:
        for i, item in enumerate(array):
            errs.extend(validate_against_schema(item, items_schema, f"{path}[{i}]"))
    return errs


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__
