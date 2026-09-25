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


def test_rag_mcp_server_stdio_execution():
    import json
    import subprocess
    import sys

    proc = subprocess.Popen(
        [sys.executable, str(PLUGIN_DIR / "server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    init_msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"}
        }
    })
    tools_msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    })
    stdout, stderr = proc.communicate(input=f"{init_msg}\n{tools_msg}\n", timeout=10)
    assert proc.returncode == 0
    assert "rag_search" in stdout
    assert "rag_check_decision" in stdout
    assert "rag_health" in stdout


def test_rag_skill_metadata():
    from nanobot.agent.skills import parse_skill_metadata, valid_skill_metadata
    skill_file = PLUGIN_DIR / "skills" / "lightrag-query" / "SKILL.md"
    assert skill_file.exists()
    content = skill_file.read_text(encoding="utf-8")
    meta = parse_skill_metadata(content)
    assert meta is not None
    assert valid_skill_metadata(meta, "lightrag-query")
    assert "rag_search" in content
    assert "local" in content
    assert "global" in content
    assert "mix" in content


def test_rag_plugin_discovery_and_enable(tmp_path: Path):
    import shutil
    from nanobot.agent.plugins import (
        discover_agent_plugins,
        enabled_agent_plugin_skills,
        agent_plugin_mcp_servers,
        set_agent_plugin_enabled,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plugins_dir = workspace / "plugins"
    plugins_dir.mkdir()
    dest = plugins_dir / "rag"
    shutil.copytree(PLUGIN_DIR, dest)

    plugins = discover_agent_plugins(workspace)
    assert any(p.name == "rag" for p in plugins)

    set_agent_plugin_enabled(workspace, "rag", True)
    skills = enabled_agent_plugin_skills(workspace)
    assert any(name == "lightrag-query" for name, _ in skills)

    servers = agent_plugin_mcp_servers(workspace)
    assert "rag" in servers
    assert servers["rag"].command == "python"
