import pytest
from pydantic import ValidationError

from nanobot.channels.base import BaseChannel
from nanobot.config.schema import (
    ChannelsConfig,
    Config,
    PilotCaptureConfig,
    PilotConfig,
    PilotRetentionConfig,
)


def test_channels_config_show_reasoning_default_is_false():
    assert ChannelsConfig().show_reasoning is False

def test_base_channel_show_reasoning_default_is_false():
    class Dummy(BaseChannel):
        async def start(self): pass
        async def stop(self): pass
        async def send(self, msg): pass

    assert Dummy.show_reasoning is False

def test_pilot_capture_and_training_eligibility_default_disabled():
    cfg = PilotConfig()
    assert cfg.capture.enabled is False
    assert cfg.capture.queue_capacity == 1000

def test_pilot_routing_validates_preset_names():
    # If the presets are not in model_presets, it should fail
    # The validation happens at the Config level when 'pilot' is parsed.
    with pytest.raises(ValueError, match="preset 'unknown' not found"):
        Config.model_validate({
            "pilot": {
                "routing": {
                    "enabled": True,
                    "default": {"preset": "unknown"},
                    "reasoning": {"preset": "unknown"},
                    "tool_heavy": {"preset": "unknown"}
                }
            }
        })

def test_pilot_routing_rejects_tool_heavy_without_tool_support():
    with pytest.raises(ValueError, match="tool_heavy must support tools"):
        Config.model_validate({
            "model_presets": {
                "base": {"model": "foo"}
            },
            "pilot": {
                "routing": {
                    "enabled": True,
                    "default": {"preset": "base"},
                    "reasoning": {"preset": "base"},
                    "tool_heavy": {"preset": "base", "supports_tools": False}
                }
            }
        })

def test_gemini_pilot_candidates_accept_only_api_key():
    # Gemini does not have an OAuth field. We verify this via ProviderConfig.
    from nanobot.config.schema import ProviderConfig
    with pytest.raises(ValidationError):
        ProviderConfig.model_validate({"api_key": "sk-123", "oauth": "token"})

def test_pilot_retention_and_queue_limits_reject_unsafe_values():
    with pytest.raises(ValidationError):
        PilotRetentionConfig(session_days=0)
    with pytest.raises(ValidationError):
        PilotRetentionConfig(session_days=-1)

    with pytest.raises(ValidationError):
        PilotCaptureConfig(queue_capacity=9)
    with pytest.raises(ValidationError):
        PilotCaptureConfig(queue_capacity=100_001)

def test_pilot_capture_requires_hmac_secret_when_enabled():
    with pytest.raises(ValueError, match="hmac_secret"):
        Config.model_validate({
            "pilot": {
                "capture": {
                    "enabled": True,
                    "hmac_secret": ""
                }
            }
        })
