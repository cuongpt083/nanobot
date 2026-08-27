from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.channels.zalo.connect import ZaloConnectStore
from nanobot.channels.zalo.runtime import ZaloChannel
from nanobot.config.loader import save_config
from nanobot.config.schema import Config


@pytest.mark.asyncio
async def test_zalo_connect_store_completes_qr_login(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "zalo-state"
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({"channels": {"zalo": {"stateDir": str(state_dir)}}}),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    async def fake_start(self: ZaloChannel, **_kwargs: Any) -> str:
        self._own_user_id = "zalo-user"
        return "zalo-qr-payload"

    async def fake_poll(self: ZaloChannel) -> dict[str, Any]:
        return {"status": "succeeded", "message": "Zalo is connected.", "account": "zalo-user"}

    monkeypatch.setattr(ZaloChannel, "connect_start_qr", fake_start)
    monkeypatch.setattr(ZaloChannel, "connect_poll_qr", fake_poll)
    monkeypatch.setattr(ZaloChannel, "connect_close", AsyncMock())

    store = ZaloConnectStore()
    started = await store.start()
    assert started["status"] == "pending"
    assert started["qr_url"] == "zalo-qr-payload"

    completed = await store.poll(started["session_id"])
    assert completed["status"] == "succeeded"
    assert completed["account"] == "zalo-user"


@pytest.mark.asyncio
async def test_zalo_connect_store_reports_already_connected(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "zalo-state"
    state_dir.mkdir()
    (state_dir / "credentials.json").write_text(
        '{"imei":"i","cookie":[{"n":1}],"userAgent":"ua"}',
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({"channels": {"zalo": {"stateDir": str(state_dir)}}}),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    store = ZaloConnectStore()
    started = await store.start()
    assert started["status"] == "succeeded"
    assert started["session_id"] == ""
