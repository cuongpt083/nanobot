from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop, TurnContext, TurnKind
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings
from nanobot.providers.factory import ProviderSnapshot


def _config(workspace: Path) -> Config:
    return Config.model_validate(
        {
            "agents": {"defaults": {"workspace": str(workspace), "model": "default-model"}},
            "modelPresets": {
                "fast": {"model": "fast-model"},
                "reasoner": {"model": "reasoner-model"},
                "tools": {"model": "tools-model"},
            },
            "pilot": {
                "enabled": True,
                "routing": {
                    "enabled": True,
                    "default": {"preset": "fast"},
                    "reasoning": {"preset": "reasoner"},
                    "toolHeavy": {"preset": "tools"},
                },
            },
        }
    )


def _loop(config: Config) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "default-model"
    provider.generation = GenerationSettings()

    def load_preset(name: str) -> ProviderSnapshot:
        preset = config.model_presets[name]
        return ProviderSnapshot(
            provider=provider,
            model=preset.model,
            context_window_tokens=preset.context_window_tokens,
            signature=(name, preset.model),
            model_preset=name,
        )

    loop = AgentLoop.from_config(
        config,
        bus=MessageBus(),
        provider=provider,
        preset_snapshot_loader=load_preset,
    )
    loop.tools = MagicMock()
    return loop


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "tool_names", "expected_preset"),
    [
        ("hello", (), "fast"),
        ("Solve the integral of x", (), "reasoner"),
        ("run it", ("bash",), "tools"),
    ],
)
async def test_pilot_routes_turns_to_the_configured_preset(
    tmp_path: Path,
    content: str,
    tool_names: tuple[str, ...],
    expected_preset: str,
) -> None:
    loop = _loop(_config(tmp_path))
    loop.tools.tool_names = list(tool_names)
    msg = InboundMessage(channel="websocket", sender_id="user", chat_id="chat", content=content)
    session_key = msg.session_key
    ctx = TurnContext(
        msg=msg,
        session_key=session_key,
        turn_id="turn-1",
        runtime=None,
        kind=TurnKind.USER,
        delivery=loop.turn_delivery_factory.create(msg, session_key),
        session=loop.sessions.get_or_create(session_key),
        ephemeral=True,
    )

    await loop._build_turn(ctx)

    assert ctx.require_runtime().model_preset == expected_preset
    assert ctx.attributes["routing_decision"]["primary_preset"] == expected_preset
