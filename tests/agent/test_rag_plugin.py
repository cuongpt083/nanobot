from pathlib import Path
import pytest
from nanobot.agent.plugins import (
    _load_manifest,
    _plugin_mcp_servers,
)

PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugins" / "rag"


def test_rag_manifest_is_valid():
    plugin = _load_manifest(PLUGIN_DIR)
    assert plugin is not None
    assert plugin.name == "rag"
    assert plugin.display_name == "LightRAG Knowledge Base"
    assert "Knowledge" in plugin.category or "RAG" in plugin.category


def test_rag_mcp_servers_config(tmp_path: Path):
    plugin = _load_manifest(PLUGIN_DIR)
    assert plugin is not None
    servers = _plugin_mcp_servers(tmp_path, plugin)
    assert "lightrag" in servers
    assert servers["lightrag"].type == "stdio"
    assert servers["lightrag"].command == "python"
    assert any("server.py" in arg for arg in servers["lightrag"].args)
    assert servers["lightrag"].env.get("LAYA_ENABLED") == "true"


@pytest.mark.asyncio
async def test_laya_client_decision_true(monkeypatch):
    import sys
    sys.path.insert(0, str(PLUGIN_DIR))
    from laya_client import LayaClient
    import httpx

    client = LayaClient(service_url="http://fake-laya/v1/decide", threshold=0.7)

    async def mock_post(*args, **kwargs):
        class MockResp:
            status_code = 200
            def json(self):
                return {"should_preseed": True, "confidence": 0.95, "latency_ms": 15.0}
        return MockResp()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    should_ret, conf, reason = await client.should_retrieve("Tìm hiểu chế độ ăn keto")
    assert should_ret is True
    assert conf == 0.95
    assert client.circuit_status == "closed"


@pytest.mark.asyncio
async def test_laya_client_circuit_breaker(monkeypatch):
    import sys
    sys.path.insert(0, str(PLUGIN_DIR))
    from laya_client import LayaClient
    import httpx

    client = LayaClient(service_url="http://fake-laya/v1/decide", failure_threshold=3, cooldown_seconds=10.0)

    async def mock_timeout(*args, **kwargs):
        raise httpx.TimeoutException("Timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_timeout)

    for _ in range(3):
        should_ret, conf, reason = await client.should_retrieve("Hello")
        assert should_ret is True  # Fail-soft default

    assert client.circuit_status == "open"

    # Circuit open should bypass call immediately
    should_ret, conf, reason = await client.should_retrieve("Any message")
    assert should_ret is True
    assert "circuit_open" in reason


@pytest.mark.asyncio
async def test_lightrag_client_query_success(monkeypatch):
    import sys
    sys.path.insert(0, str(PLUGIN_DIR))
    from lightrag_client import LightRagClient
    import httpx

    client = LightRagClient(base_url="http://fake-lightrag", api_key="secret-key")

    async def mock_post(*args, **kwargs):
        assert kwargs["json"]["mode"] == "mix"
        assert kwargs["json"]["only_need_context"] is True
        assert kwargs["headers"].get("X-API-Key") == "secret-key"

        class MockResp:
            status_code = 200
            def json(self):
                return {
                    "response": "Keto is a high-fat, low-carbohydrate diet.",
                    "references": [
                        {"file": "nutrition_guide.pdf", "chunk": 1},
                        {"file": "keto_manual.md"}
                    ]
                }
        return MockResp()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await client.query("What is keto?", mode="mix")
    assert result["retrieved"] is True
    assert "high-fat" in result["content"]
    assert "nutrition_guide.pdf" in result["sources"]
    assert "keto_manual.md" in result["sources"]


@pytest.mark.asyncio
async def test_lightrag_client_error_handling(monkeypatch):
    import sys
    sys.path.insert(0, str(PLUGIN_DIR))
    from lightrag_client import LightRagClient
    import httpx

    client = LightRagClient(base_url="http://fake-lightrag")

    async def mock_post(*args, **kwargs):
        class MockResp:
            status_code = 401
            text = "Unauthorized"
        return MockResp()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await client.query("What is keto?")
    assert result["retrieved"] is False
    assert "401" in result["error"]
