"""What a browser session may do, decided before bsk is called (BrowserSkill Mức 2, Phần chính sách).

Two checks, both on the nanobot side: a URL may not be on a denied domain (mail, banking, payment), and a
persona gets the ``interact`` mode only if it is listed for it. The decisions of the proposal are the defaults:
marketer, designer and sales may interact; every other persona reads only.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# Mail services. The proposal also names the ten largest banks and the e-wallets and payment gateways; those
# lists are not in the repository yet and must be filled in from the user's list (see the Phase 10 plan).
DEFAULT_DENY_DOMAINS: tuple[str, ...] = (
    "gmail.com",
    "mail.google.com",
    "outlook.com",
    "outlook.live.com",
    "outlook.office.com",
)

DEFAULT_INTERACT_PERSONAS: tuple[str, ...] = ("marketer", "designer", "sales")
MODE_READ = "read"
MODE_INTERACT = "interact"


class PolicyError(ValueError):
    """The request is refused by policy. The message is safe to show to the model."""


def host_of(url: str) -> str:
    """The lower-cased host of an http(s) URL. Raises ``PolicyError`` for anything else."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PolicyError("only http and https URLs can be opened")
    return parts.hostname.lower().rstrip(".")


def is_denied(host: str, deny_domains: tuple[str, ...] | list[str]) -> bool:
    """True when the host is a denied domain or one of its subdomains."""
    return any(host == domain or host.endswith("." + domain) for domain in (d.lower() for d in deny_domains))


def check_url(url: str, deny_domains: tuple[str, ...] | list[str]) -> str:
    host = host_of(url)
    if is_denied(host, deny_domains):
        raise PolicyError(f"{host} is on the list of sites the browser may not open")
    return host


def mode_for(persona_id: str | None, interact_personas: tuple[str, ...] | list[str]) -> str:
    """``interact`` for a listed persona, ``read`` for everyone else (including the main agent)."""
    if persona_id and persona_id.lower() in {p.lower() for p in interact_personas}:
        return MODE_INTERACT
    return MODE_READ
