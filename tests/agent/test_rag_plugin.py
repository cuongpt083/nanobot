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
