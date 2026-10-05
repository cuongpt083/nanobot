"""Key management and authentication for Nanobot LLM Proxy."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from nanobot.config.paths import get_runtime_subdir


@dataclass
class ProxyApiKey:
    id: str
    name: str
    key_hash: str
    created_at: int
    budget_period: str = "none"  # "5h" | "daily" | "weekly" | "monthly" | "lifetime" | "none"
    budget_tokens: int | None = None
    allowed_providers: list[str] | None = None
    last_used_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("key_hash", None)
        return d


class KeyStore:
    """Manages LLM Proxy API keys with hashed storage."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self.dir = storage_dir or get_runtime_subdir("llm_proxy")
        self._keys: dict[str, ProxyApiKey] = {}
        self._load()

    @property
    def _file(self) -> Path:
        return self.dir / "keys.json"

    def _load(self) -> None:
        if self._file.is_file():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                for k, v in data.items():
                    self._keys[k] = ProxyApiKey(**v)
            except Exception:
                self._keys = {}
        else:
            self._keys = {}

    def _save(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            data = {k: v.to_dict() for k, v in self._keys.items()}
            self._file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def hash_secret(secret: str) -> str:
        return hashlib.sha256(secret.strip().encode("utf-8")).hexdigest()

    def create_key(
        self,
        name: str,
        budget_period: str = "none",
        budget_tokens: int | None = None,
        allowed_providers: list[str] | None = None,
    ) -> tuple[str, ProxyApiKey]:
        """Create a new API key. Returns (plaintext_secret, ProxyApiKey)."""
        random_part = secrets.token_urlsafe(24)
        secret = f"sk-nano-{random_part}"
        key_hash = self.hash_secret(secret)
        key_id = f"key_{secrets.token_hex(6)}"

        key = ProxyApiKey(
            id=key_id,
            name=name or "Unnamed Key",
            key_hash=key_hash,
            created_at=int(time.time() * 1000),
            budget_period=budget_period,
            budget_tokens=budget_tokens,
            allowed_providers=allowed_providers,
        )
        self._keys[key_id] = key
        self._save()
        return secret, key

    def validate_secret(self, secret: str) -> ProxyApiKey | None:
        """Validate an incoming Bearer secret against known hashes."""
        if not secret:
            return None
        incoming_hash = self.hash_secret(secret)
        for key in self._keys.values():
            if key.key_hash == incoming_hash:
                key.last_used_at = int(time.time() * 1000)
                self._save()
                return key
        return None

    def list_keys(self) -> list[dict[str, Any]]:
        return [k.to_public_dict() for k in self._keys.values()]

    def delete_key(self, key_id: str) -> bool:
        if key_id in self._keys:
            del self._keys[key_id]
            self._save()
            return True
        return False
