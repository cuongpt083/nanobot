"""Load and render agent system prompt templates (Jinja2) under nanobot/templates/.

Agent prompts live in ``templates/agent/`` (pass names like ``agent/identity.md``).
Shared copy lives under ``agent/_snippets/`` and is included via
``{% include 'agent/_snippets/....md' %}``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

_RAW_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"


def _clean_path_for_loader(path: Path | str) -> str:
    path_str = str(path)
    # On Windows, Path.resolve() or sys.path can carry the extended-length verbatim
    # prefix (\\?\ or \\?\UNC\). Jinja2's FileSystemLoader internally uses posixpath.join
    # which introduces forward slashes ('/'). Windows Win32 APIs strictly forbid '/'
    # in verbatim '\\?\' paths, causing TemplateNotFound for all templates.
    unc_prefix = "\\\\?\\UNC\\"
    verbatim_prefix = "\\\\?\\"
    if path_str.startswith(unc_prefix):
        return "\\\\" + path_str[len(unc_prefix) :]
    if path_str.startswith(verbatim_prefix):
        return path_str[len(verbatim_prefix) :]
    return path_str


_TEMPLATES_ROOT = Path(_clean_path_for_loader(_RAW_TEMPLATES_ROOT))


@lru_cache
def _environment() -> Environment:
    # Plain-text prompts: do not HTML-escape variable values.
    return Environment(
        loader=FileSystemLoader(_clean_path_for_loader(_TEMPLATES_ROOT)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(name: str, *, strip: bool = False, **kwargs: Any) -> str:
    """Render ``name`` (e.g. ``agent/identity.md``, ``agent/platform_policy.md``) under ``templates/``.

    Use ``strip=True`` for single-line user-facing strings when the file ends
    with a trailing newline you do not want preserved.
    """
    text = _environment().get_template(name).render(**kwargs)
    return text.rstrip() if strip else text
