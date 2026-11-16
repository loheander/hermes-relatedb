from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_register_creates_fresh_instance_each_call(plugin_module, fake_ctx):
    plugin_module.register(fake_ctx)
    plugin_module.register(fake_ctx)
    a, b = fake_ctx.providers
    assert a is not b
    assert a.name == "relatedb"


def test_instances_do_not_share_profile_state(plugin_module, profile_home):
    a = plugin_module.RelateDBMemoryProvider()
    b = plugin_module.RelateDBMemoryProvider()
    a.initialize("s1", hermes_home=str(profile_home))
    b.initialize("s2")
    assert a._session_id == "s1" and b._session_id == "s2"
    assert b._init_kwargs == {}


def test_import_does_not_need_hermes():
    code = (
        "import sys, importlib; "
        f"sys.path.insert(0, {str(ROOT)!r}); "
        "import relatedb_memory.provider as p; "
        "assert not any(m == 'agent' or m.startswith('agent.') for m in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_discovery_ast_check_passes():
    """Mirror Hermes's _defines_memory_provider: a register_memory_provider call."""
    tree = ast.parse((ROOT / "__init__.py").read_text())
    names = {
        getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert "register_memory_provider" in names


def test_manifest():
    data = yaml.safe_load((ROOT / "plugin.yaml").read_text())
    assert data["name"] == "relatedb"
    assert data["config_keys"] == ["memory.relatedb"]
    assert data["version"] and data["description"]


def test_internal_layout():
    for m in ("provider", "config", "store", "embedder", "schema"):
        assert (ROOT / "relatedb_memory" / f"{m}.py").is_file()


def test_register_cli_sets_dispatcher_on_hermes_parser():
    """Hermes passes register_cli its own parser and dispatches via ``args.func``."""
    import argparse

    import cli

    parser = argparse.ArgumentParser(prog="hermes relatedb")
    cli.register_cli(parser)
    args = parser.parse_args(["status", "--path", "/nonexistent"])
    assert args.func is cli.relatedb_command
    assert args._handler is cli._cmd_status
