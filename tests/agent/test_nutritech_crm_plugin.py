from pathlib import Path
import pytest
from nanobot.agent.plugins import (
    _load_manifest,
    _plugin_mcp_servers,
    AgentPlugin,
)

PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugins" / "nutritech-crm"


def test_nutritech_manifest_is_valid():
    plugin = _load_manifest(PLUGIN_DIR)
    assert plugin is not None
    assert plugin.name == "nutritech-crm"
    assert plugin.display_name == "NutriTech CRM"
    assert "Healthcare" in plugin.category or "CRM" in plugin.category


def test_nutritech_mcp_servers_config(tmp_path: Path):
    plugin = _load_manifest(PLUGIN_DIR)
    assert plugin is not None
    servers = _plugin_mcp_servers(tmp_path, plugin)
    assert "nutritech-crm" in servers
    assert servers["nutritech-crm"].type == "stdio"
    assert "dist/mcp/index.js" in " ".join(servers["nutritech-crm"].args)
