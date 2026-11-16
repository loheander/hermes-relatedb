from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class FakePluginContext:
    """Records memory provider registrations like Hermes's collector."""

    def __init__(self) -> None:
        self.providers: list[object] = []

    def register_memory_provider(self, provider: object) -> None:
        self.providers.append(provider)


@pytest.fixture
def fake_ctx() -> FakePluginContext:
    return FakePluginContext()


@pytest.fixture
def profile_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


@pytest.fixture
def plugin_module():
    """Load the root package the way Hermes does: as a directory plugin."""
    name = "_hermes_user_plugin_relatedb"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
            del sys.modules[key]
