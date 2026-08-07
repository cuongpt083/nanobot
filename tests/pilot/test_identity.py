"""Tests for IdentityHasher."""

import pytest

from nanobot.pilot.identity import IdentityHasher


def test_identity_hasher_basic() -> None:
    hasher = IdentityHasher("secret123")
    h1 = hasher.hash_identity("user", "user_123")
    assert isinstance(h1, str)
    assert len(h1) == 64  # SHA256 hex digest length


def test_domain_separation() -> None:
    hasher = IdentityHasher("secret123")
    h_user = hasher.hash_identity("user", "12345")
    h_session = hasher.hash_identity("session", "12345")
    assert h_user != h_session


def test_version_separation() -> None:
    hasher_v1 = IdentityHasher("secret123", version="v1")
    hasher_v2 = IdentityHasher("secret123", version="v2")
    h_v1 = hasher_v1.hash_identity("user", "12345")
    h_v2 = hasher_v2.hash_identity("user", "12345")
    assert h_v1 != h_v2


def test_secret_rotation() -> None:
    hasher1 = IdentityHasher("secret1")
    hasher2 = IdentityHasher("secret2")
    assert hasher1.hash_identity("user", "123") != hasher2.hash_identity("user", "123")


def test_repr_str_no_leak() -> None:
    secret = "SUPER_SECRET_KEY_999"
    hasher = IdentityHasher(secret)
    rep = repr(hasher)
    st = str(hasher)
    assert secret not in rep
    assert secret not in st
    assert "[REDACTED]" in rep


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        IdentityHasher("")
    hasher = IdentityHasher("secret")
    with pytest.raises(ValueError):
        hasher.hash_identity("", "val")
    with pytest.raises(ValueError):
        hasher.hash_identity("dom", "")
