from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.tools.image_generation import ImageGenerationTool
from nanobot.config.loader import set_config_path
from nanobot.config.schema import ImageGenerationToolConfig, ProviderConfig
from nanobot.providers.image_generation import GeneratedImageResponse

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdacd\xfc\xff\x1f\x00\x03\x03"
    b"\x02\x00\xef\xbf\xa7\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class FakeImageClient:
    instances: list["FakeImageClient"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        self.instances.append(self)

    async def generate(self, **kwargs: Any) -> GeneratedImageResponse:
        self.calls.append(kwargs)
        return GeneratedImageResponse(images=[PNG_DATA_URL], content="", raw={})


@pytest.mark.asyncio
async def test_generate_image_tool_stores_artifact_and_source_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_config_path(tmp_path / "config.json")
    FakeImageClient.instances = []
    monkeypatch.setattr(
        "nanobot.agent.tools.image_generation.get_image_gen_provider",
        lambda name: FakeImageClient if name == "openrouter" else None,
    )
    ref = tmp_path / "ref.png"
    ref.write_bytes(PNG_BYTES)
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True, max_images_per_turn=2),
        provider_config=ProviderConfig(api_key="sk-or-test"),
    )

    result = await tool.execute(
        prompt="make this blue",
        reference_images=["ref.png"],
        aspect_ratio="16:9",
        image_size="2K",
        count=2,
    )

    payload = json.loads(result)
    artifacts = payload["artifacts"]
    assert len(artifacts) == 2
    assert Path(artifacts[0]["path"]).is_file()
    assert artifacts[0]["source_images"] == [str(ref.resolve())]
    assert artifacts[0]["model"] == "openai/gpt-5.4-image-2"

    fake = FakeImageClient.instances[0]
    assert fake.kwargs["api_key"] == "sk-or-test"
    assert len(fake.calls) == 2
    assert fake.calls[0]["aspect_ratio"] == "16:9"
    assert fake.calls[0]["image_size"] == "2K"


@pytest.mark.asyncio
async def test_generate_image_tool_reports_missing_key(tmp_path: Path) -> None:
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True),
        provider_config=ProviderConfig(),
    )

    result = await tool.execute(prompt="draw")

    assert result.startswith("Error: OpenRouter API key is not configured")


@pytest.mark.asyncio
async def test_generate_image_tool_selects_aihubmix_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_config_path(tmp_path / "config.json")
    FakeImageClient.instances = []
    monkeypatch.setattr(
        "nanobot.agent.tools.image_generation.get_image_gen_provider",
        lambda name: FakeImageClient if name == "aihubmix" else None,
    )
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(
            enabled=True,
            provider="aihubmix",
            model="gpt-image-2-free",
        ),
        provider_configs={
            "openrouter": ProviderConfig(api_key="sk-or-test"),
            "aihubmix": ProviderConfig(api_key="sk-ahm-test", extra_body={"quality": "low"}),
        },
    )

    result = await tool.execute(prompt="draw a poster", aspect_ratio="3:4")

    payload = json.loads(result)
    assert len(payload["artifacts"]) == 1
    fake = FakeImageClient.instances[0]
    assert fake.kwargs["api_key"] == "sk-ahm-test"
    assert fake.kwargs["extra_body"] == {"quality": "low"}
    assert fake.calls[0]["model"] == "gpt-image-2-free"
    assert fake.calls[0]["aspect_ratio"] == "3:4"


def test_image_generation_tool_passes_provider_proxy_to_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeImageClient.instances = []
    monkeypatch.setattr(
        "nanobot.agent.tools.image_generation.get_image_gen_provider",
        lambda name: FakeImageClient if name == "openai_codex" else None,
    )
    proxy = "http://127.0.0.1:23458"
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(
            enabled=True,
            provider="openai_codex",
            model="openai-codex/gpt-5.4",
        ),
        provider_configs={"openai_codex": ProviderConfig(proxy=proxy)},
    )

    client = tool._provider_client()

    assert client is not None
    assert FakeImageClient.instances[0].kwargs["proxy"] == proxy


@pytest.mark.asyncio
async def test_generate_image_tool_reports_missing_aihubmix_key(tmp_path: Path) -> None:
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True, provider="aihubmix"),
        provider_configs={"aihubmix": ProviderConfig()},
    )

    result = await tool.execute(prompt="draw")

    assert result.startswith("Error: AIHubMix API key is not configured")


@pytest.mark.asyncio
async def test_generate_image_tool_allows_ollama_without_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_config_path(tmp_path / "config.json")
    FakeImageClient.instances = []
    monkeypatch.setattr(
        "nanobot.agent.tools.image_generation.get_image_gen_provider",
        lambda name: FakeImageClient if name == "ollama" else None,
    )
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(
            enabled=True,
            provider="ollama",
            model="x/z-image-turbo",
        ),
        provider_configs={"ollama": ProviderConfig(api_base="http://localhost:11434/v1")},
    )

    result = await tool.execute(prompt="draw a cat")

    payload = json.loads(result)
    assert len(payload["artifacts"]) == 1

    fake = FakeImageClient.instances[0]
    assert fake.kwargs["api_key"] is None
    assert fake.kwargs["api_base"] == "http://localhost:11434/v1"
    assert fake.calls[0]["aspect_ratio"] == "1:1"
    assert fake.calls[0]["image_size"] == "1K"


@pytest.mark.asyncio
async def test_generate_image_tool_reports_missing_zhipu_key(tmp_path: Path) -> None:
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(
            enabled=True,
            provider="zhipu",
            model="glm-image",
        ),
        provider_configs={"zhipu": ProviderConfig(api_base="https://open.bigmodel.cn/api/paas/v4")},
    )

    result = await tool.execute(prompt="draw a cat")

    assert result.startswith("Error: Zhipu API key is not configured")


@pytest.mark.asyncio
async def test_generate_image_tool_rejects_reference_outside_workspace(tmp_path: Path) -> None:
    set_config_path(tmp_path / "config.json")
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(PNG_BYTES)
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True),
        provider_config=ProviderConfig(api_key="sk-or-test"),
    )

    result = await tool.execute(prompt="edit", reference_images=[str(outside)])

    assert "reference_images must be inside the workspace" in result


@pytest.mark.asyncio
async def test_generate_image_tool_resolves_named_custom_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_config_path(tmp_path / "config.json")
    from nanobot.config.schema import Config
    from nanobot.providers.image_generation import (
        CustomImageGenerationClient,
        get_image_gen_provider,
        image_gen_provider_configs,
    )

    # 1. Resolver check
    assert get_image_gen_provider("openrouter") is not None
    assert get_image_gen_provider("customer") is None
    assert get_image_gen_provider("unknown_provider") is None
    resolved_cls = get_image_gen_provider("custom-agy-17")
    assert resolved_cls is CustomImageGenerationClient

    # 2. image_gen_provider_configs check
    config = Config.model_validate({
        "providers": {
            "custom-agy-17": {
                "apiBase": "http://192.168.100.17:8000/v1",
                "apiKey": "sk-agy",
            }
        }
    })
    configs = image_gen_provider_configs(config)
    assert "custom-agy-17" in configs
    assert configs["custom-agy-17"].api_base == "http://192.168.100.17:8000/v1"

    # 3. Tool execution check with named custom provider
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True, provider="custom-agy-17", model="test-model"),
        provider_configs=configs,
    )

    async def fake_post(self: Any, url: str, **kwargs: Any) -> Any:
        assert url == "http://192.168.100.17:8000/v1/images/generations"
        class FakeResponse:
            status_code = 200
            def raise_for_status(self) -> None:
                pass
            def json(self) -> dict[str, Any]:
                return {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="}]}
        return FakeResponse()

    monkeypatch.setattr(CustomImageGenerationClient, "_http_post", fake_post)
    result = await tool.execute(prompt="a sunset")
    parsed = json.loads(result)
    assert "artifacts" in parsed
    assert len(parsed["artifacts"]) == 1
    assert parsed["artifacts"][0]["provider"] == "custom-agy-17"

