"""Inbound Zalo message normalization (zca-js / zalouser wire shape)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, cast

_ID_SUFFIX_RE = re.compile(r"_\d+$")

THREAD_TYPE_USER = 0
THREAD_TYPE_GROUP = 1
ZALO_TEXT_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class ZaloInbound:
    thread_id: str
    sender_id: str
    is_group: bool
    content: str
    sender_name: str = ""
    group_name: str = ""
    msg_id: str = ""
    mentioned: bool = False
    media: tuple[str, ...] = ()


def to_number_id(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return ""
        return _ID_SUFFIX_RE.sub("", trimmed)
    return ""


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return None


def _string(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value)) if float(value).is_integer() else str(value).strip()
    return ""


def _normalize_content(content: object) -> tuple[str, tuple[str, ...]]:
    if isinstance(content, str):
        return content.strip(), ()
    record = _as_mapping(content)
    if record is None:
        return "", ()
    title = _string(record.get("title"))
    description = _string(record.get("description"))
    href = _string(record.get("href")) or _string(record.get("url"))
    parts = [part for part in (title, description, href) if part]
    media = (href,) if href.startswith(("http://", "https://")) else ()
    return "\n".join(parts).strip(), media


def _mention_ids(raw_mentions: object) -> list[str]:
    if not isinstance(raw_mentions, list):
        return []
    ids: list[str] = []
    for entry in cast(list[object], raw_mentions):
        record = _as_mapping(entry)
        if record is None:
            continue
        uid = to_number_id(record.get("uid"))
        if uid:
            ids.append(uid)
    return ids


def _group_name(data: Mapping[str, Any]) -> str:
    for key in ("groupName", "gName", "idToName", "threadName", "roomName"):
        value = _string(data.get(key))
        if value:
            return value
    return ""


def normalize_inbound_message(
    message: Mapping[str, Any],
    own_user_id: str = "",
) -> ZaloInbound | None:
    """Convert a zca-js listener payload into a nanobot inbound message."""
    if bool(message.get("isSelf")):
        return None
    data = _as_mapping(message.get("data"))
    if data is None:
        return None

    is_group = int(message.get("type") or THREAD_TYPE_USER) == THREAD_TYPE_GROUP
    sender_id = to_number_id(data.get("uidFrom"))
    thread_id = (
        to_number_id(data.get("idTo"))
        if is_group
        else sender_id or to_number_id(data.get("idTo"))
    )
    if not thread_id or not sender_id:
        return None
    if own_user_id and sender_id == own_user_id:
        return None

    content, media = _normalize_content(data.get("content"))
    mention_ids = _mention_ids(data.get("mentions"))
    quoted = _as_mapping(data.get("quote"))
    quoted_owner = to_number_id(quoted.get("ownerId")) if quoted is not None else ""
    mentioned = bool(own_user_id) and (
        own_user_id in mention_ids or (quoted_owner != "" and quoted_owner == own_user_id)
    )
    return ZaloInbound(
        thread_id=thread_id,
        sender_id=sender_id,
        is_group=is_group,
        content=content,
        sender_name=_string(data.get("dName")),
        group_name=_group_name(data) if is_group else "",
        msg_id=_string(data.get("msgId")),
        mentioned=mentioned,
        media=media,
    )


def group_message_is_addressed(inbound: ZaloInbound, display_name: str = "") -> bool:
    """Return whether a group message should be handled under mention policy."""
    if inbound.mentioned:
        return True
    needle = display_name.strip()
    if not needle:
        return False
    text = inbound.content.casefold()
    return needle.casefold() in text or f"@{needle}".casefold() in text


__all__ = [
    "THREAD_TYPE_GROUP",
    "THREAD_TYPE_USER",
    "ZALO_TEXT_LIMIT",
    "ZaloInbound",
    "group_message_is_addressed",
    "normalize_inbound_message",
    "to_number_id",
]
