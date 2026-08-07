"""HMAC identity pseudonymization with domain separation."""

from __future__ import annotations

import hashlib
import hmac


class IdentityHasher:
    """HMAC-SHA256 identity pseudonymizer with domain separation."""

    def __init__(self, secret: str, version: str = "v1") -> None:
        if not secret or not isinstance(secret, str):
            raise ValueError("hmac_secret must be a non-empty string")
        self._secret_bytes = secret.encode("utf-8")
        self._version = version

    def hash_identity(self, domain: str, value: str) -> str:
        """Return hex digest for HMAC-SHA256(secret, f'{version}:{domain}:{value}')."""
        if not domain:
            raise ValueError("domain must be non-empty")
        if not value:
            raise ValueError("value must be non-empty")
        msg = f"{self._version}:{domain}:{value}".encode("utf-8")
        return hmac.new(self._secret_bytes, msg, hashlib.sha256).hexdigest()

    def __repr__(self) -> str:
        return f"IdentityHasher(version={self._version!r}, secret=[REDACTED])"

    def __str__(self) -> str:
        return f"IdentityHasher(version={self._version})"
