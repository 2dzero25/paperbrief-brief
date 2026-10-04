"""Seam: the committed dev-environment files (pyproject.toml, .mcp.json, .claude/settings.json, AGENTS.md)."""
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_required_dependencies_are_declared():
    cfg = pyproject()
    deps = " ".join(cfg["project"]["dependencies"] + [d for g in cfg["dependency-groups"].values() for d in g])
    for name in ["mineru[full]>=4.0.10,<4.1", "fastapi", "httpx", "openai", "pydantic", "pytest", "pyright", "torch", "torchvision"]:
        assert name in deps


def test_lock_targets_windows_and_both_linux_arches():
    envs = " ".join(pyproject()["tool"]["uv"]["environments"])
    assert "win32" in envs and "x86_64" in envs and "aarch64" in envs


def test_windows_only_cuda_index_and_linux_only_nccl_override():
    uv = pyproject()["tool"]["uv"]
    for pkg in ("torch", "torchvision"):
        (src,) = uv["sources"][pkg]
        assert src["index"] == "pytorch-cu128" and "win32" in src["marker"]
    assert any(o.startswith("nvidia-nccl-cu12") and "linux" in o for o in uv["override-dependencies"])


def test_mcp_servers_are_configured_without_dashboard_popup():
    servers = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert {"context7", "deepwiki", "mcpdoc", "serena"} <= servers.keys()
    mcpdoc = " ".join(servers["mcpdoc"]["args"])
    assert "openai" in mcpdoc.lower() and "astral.sh/uv" in mcpdoc
    serena = servers["serena"]["args"]
    assert serena[serena.index("--open-web-dashboard") + 1] == "false"


def test_pyright_lsp_plugin_is_enabled_for_the_project():
    settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"]["pyright-lsp@claude-plugins-official"] is True


def test_agents_md_documents_commands_and_keeps_existing_sections():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for needle in ["uv sync", "uv run pytest", "uv run pyright", "Context7", "DeepWiki", "mcpdoc", "Serena", "## Agent skills", "## Code Review Rules"]:
        assert needle in text
