import shutil
from pathlib import Path
import pytest
from nanobot.agent.plugins import (
    _load_manifest,
    _plugin_mcp_servers,
    discover_agent_plugins,
    enabled_agent_plugin_skills,
    agent_plugin_mcp_servers,
    set_agent_plugin_enabled,
    AgentPlugin,
)
from nanobot.agent.skills import parse_skill_metadata, valid_skill_metadata

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


def test_nutritech_crm_skill_metadata():
    skill_file = PLUGIN_DIR / "skills" / "nutritech-crm" / "SKILL.md"
    assert skill_file.exists()
    content = skill_file.read_text(encoding="utf-8")
    meta = parse_skill_metadata(content)
    assert meta is not None
    assert valid_skill_metadata(meta, "nutritech-crm")
    assert "mcp_nutritech-crm_customer_list" in content
    assert "mcp_nutritech-crm_customer_log_checkin" in content
    assert "mcp_nutritech-crm_customer_get_profile" in content


def test_tanita_analysis_skill_metadata():
    skill_file = PLUGIN_DIR / "skills" / "tanita-analysis" / "SKILL.md"
    assert skill_file.exists()
    content = skill_file.read_text(encoding="utf-8")
    meta = parse_skill_metadata(content)
    assert meta is not None
    assert valid_skill_metadata(meta, "tanita-analysis")
    assert "mcp_nutritech-crm_customer_get_tanita" in content
    assert "Mỡ nội tạng" in content or "visceral" in content.lower()
    assert "Tuổi sinh học" in content or "metabolic age" in content.lower()


def test_nutritech_plugin_discovery_and_enable(tmp_path: Path):
    # Copy plugin to tmp workspace
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    shutil.copytree(PLUGIN_DIR, plugins_dir / "nutritech-crm")

    # 1. Discover plugins
    discovered = discover_agent_plugins(tmp_path)
    assert any(p.name == "nutritech-crm" for p in discovered)

    # 2. Enable plugin
    set_agent_plugin_enabled(tmp_path, "nutritech-crm", True)

    # 3. Check enabled skills
    skills = enabled_agent_plugin_skills(tmp_path)
    skill_names = [s[0] for s in skills]
    assert "nutritech-crm" in skill_names
    assert "tanita-analysis" in skill_names

    # 4. Check enabled MCP servers
    servers = agent_plugin_mcp_servers(tmp_path)
    assert "nutritech-crm" in servers
    assert servers["nutritech-crm"].command == "node"
