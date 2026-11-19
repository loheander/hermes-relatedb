from __future__ import annotations

import importlib.util
import sys
import threading
import types
from pathlib import Path

import pytest
import yaml

from relatedb_memory import config as cfg

ROOT = Path(__file__).resolve().parent.parent


def write_cfg(home: Path, section: dict) -> None:
    (home / "config.yaml").write_text(yaml.safe_dump({"memory": {"relatedb-memory": section}}))


def resolve(home: Path, env: dict | None = None):
    env = env or {}
    return cfg.resolve_config(home, env_get=env.get)


# -- defaults --


def test_defaults(tmp_path):
    c = resolve(tmp_path)
    assert c.db_path == tmp_path / "memory"
    assert c.snapshot_format == "parquet"
    assert c.embedding_model == "BAAI/bge-small-en-v1.5"
    assert c.prefetch_top_k == 8
    assert c.auto_extract is True


def test_rl_format_defaults_to_memory_rl(tmp_path):
    write_cfg(tmp_path, {"snapshot_format": "rl"})
    c = resolve(tmp_path)
    assert c.db_path == tmp_path / "memory.rl"
    assert c.snapshot_format == "rl"


@pytest.mark.parametrize("fmt", ["json", "parquet"])
def test_directory_formats_default_to_memory_dir(tmp_path, fmt):
    write_cfg(tmp_path, {"snapshot_format": fmt})
    c = resolve(tmp_path)
    assert c.db_path == tmp_path / "memory"
    assert c.snapshot_format == fmt


def test_malformed_yaml_falls_back_to_defaults(tmp_path):
    (tmp_path / "config.yaml").write_text("memory: [unclosed")
    assert resolve(tmp_path).db_path == tmp_path / "memory"


# -- config.yaml overrides --


def test_yaml_overrides(tmp_path):
    write_cfg(
        tmp_path,
        {"snapshot_format": "rl", "embedding_model": "m/x", "prefetch_top_k": 3, "auto_extract": False, "db_path": "stores/a.rl"},
    )
    c = resolve(tmp_path)
    assert (c.embedding_model, c.prefetch_top_k, c.auto_extract) == ("m/x", 3, False)
    assert c.db_path == tmp_path / "stores" / "a.rl"  # relative resolves against hermes_home


def test_absolute_db_path_kept(tmp_path):
    write_cfg(tmp_path, {"db_path": "/var/lib/memory"})
    assert resolve(tmp_path).db_path == Path("/var/lib/memory")


# -- env overrides --


def test_env_beats_yaml(tmp_path):
    write_cfg(tmp_path, {"prefetch_top_k": 3, "snapshot_format": "json"})
    env = {
        "RELATEDB_PREFETCH_TOP_K": "12",
        "RELATEDB_SNAPSHOT_FORMAT": "parquet",
        "RELATEDB_AUTO_EXTRACT": "no",
        "RELATEDB_EMBEDDING_MODEL": "e/m",
        "RELATEDB_DB_PATH": "/data/g",
    }
    c = resolve(tmp_path, env)
    assert (c.prefetch_top_k, c.snapshot_format, c.auto_extract) == (12, "parquet", False)
    assert c.embedding_model == "e/m" and c.db_path == Path("/data/g")


def test_blank_env_is_ignored(tmp_path):
    write_cfg(tmp_path, {"prefetch_top_k": 3})
    assert resolve(tmp_path, {"RELATEDB_PREFETCH_TOP_K": "  "}).prefetch_top_k == 3


def test_env_read_through_scoped_secret(tmp_path, monkeypatch):
    seen = []
    scope = types.ModuleType("agent.secret_scope")
    scope.get_secret = lambda name, default=None: (seen.append(name), {"RELATEDB_PREFETCH_TOP_K": "5"}.get(name, default))[1]
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.secret_scope", scope)
    monkeypatch.setenv("RELATEDB_PREFETCH_TOP_K", "99")  # process env must not leak past the scope
    assert cfg.resolve_config(tmp_path).prefetch_top_k == 5
    assert "RELATEDB_PREFETCH_TOP_K" in seen


@pytest.mark.parametrize(
    "section",
    [
        {"snapshot_format": "csv"},
        {"prefetch_top_k": 0},
        {"prefetch_top_k": "many"},
        {"auto_extract": "maybe"},
        {"prefetch_top_k": True},
        {"snapshot_format": "rl", "db_path": "memory/"},
        {"snapshot_format": "rl", "db_path": "memory"},
        {"snapshot_format": "parquet", "db_path": "memory.rl"},
        {"snapshot_format": "json", "db_path": "memory.rl"},
    ],
)
def test_invalid_values_raise(tmp_path, section):
    write_cfg(tmp_path, section)
    with pytest.raises(ValueError):
        resolve(tmp_path)


def test_existing_filesystem_type_mismatch_raises(tmp_path):
    (tmp_path / "dir.rl").mkdir()
    write_cfg(tmp_path, {"snapshot_format": "rl", "db_path": "dir.rl"})
    with pytest.raises(ValueError):
        resolve(tmp_path)

    (tmp_path / "plain_file").write_text("x")
    write_cfg(tmp_path, {"snapshot_format": "parquet", "db_path": "plain_file"})
    with pytest.raises(ValueError):
        resolve(tmp_path)


# -- save_config / dashboard round trip --


def test_save_config_merges_and_preserves(plugin_module, tmp_path):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"model": "x", "memory": {"provider": "relatedb-memory", "relatedb-memory": {"prefetch_top_k": 4}}}))
    plugin_module.RelateDBMemoryProvider().save_config({"snapshot_format": "json", "prefetch_top_k": "6", "bogus": 1}, str(tmp_path))
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert data["model"] == "x" and data["memory"]["provider"] == "relatedb-memory"
    assert data["memory"]["relatedb-memory"] == {"prefetch_top_k": 6, "snapshot_format": "json"}



def test_write_config_fields_none_clears_and_creates_file(plugin_module, tmp_path):
    p = plugin_module.RelateDBMemoryProvider()
    p.write_config_fields({"embedding_model": "a/b", "auto_extract": False}, str(tmp_path))
    p.write_config_fields({"embedding_model": None}, str(tmp_path))
    assert p.read_config_fields(str(tmp_path))["values"] == {"auto_extract": False}


def test_save_config_rejects_invalid_without_writing(plugin_module, tmp_path):
    with pytest.raises(ValueError):
        plugin_module.RelateDBMemoryProvider().save_config({"snapshot_format": "csv"}, str(tmp_path))
    assert not (tmp_path / "config.yaml").exists()


@pytest.mark.parametrize(
    "values",
    [
        {"snapshot_format": "rl", "db_path": "memory/"},
        {"snapshot_format": "parquet", "db_path": "memory.rl"},
        {"snapshot_format": "json", "db_path": "memory.rl"},
    ],
)
def test_save_config_rejects_path_format_mismatch(plugin_module, tmp_path, values):
    with pytest.raises(ValueError):
        plugin_module.RelateDBMemoryProvider().save_config(values, str(tmp_path))
    assert not (tmp_path / "config.yaml").exists()


def test_setup_schema_matches_defaults(plugin_module):
    fields = {f["key"]: f for f in plugin_module.RelateDBMemoryProvider().get_config_schema()}
    assert fields["snapshot_format"]["choices"] == ["rl", "parquet", "json"]
    assert fields["snapshot_format"]["default"] == "parquet"
    assert fields["db_path"]["default_from"]["map"] == {"parquet": "memory/", "json": "memory/", "rl": "memory.rl"}
    assert fields["prefetch_top_k"]["default"] == 8 and fields["auto_extract"]["default"] is True


# -- profile isolation --


def test_two_homes_resolve_isolated_paths_concurrently(plugin_module, tmp_path):
    homes = [tmp_path / "a", tmp_path / "b"]
    for h, k in zip(homes, (3, 9)):
        h.mkdir()
        write_cfg(h, {"prefetch_top_k": k})
    providers = [plugin_module.RelateDBMemoryProvider() for _ in homes]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def run(p, h):
        try:
            barrier.wait()
            for _ in range(200):
                p.initialize("s", hermes_home=str(h))
                assert p.config.db_path == h / "memory" and p.config.prefetch_top_k == (3 if h == homes[0] else 9)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(p, h)) for p, h in zip(providers, homes)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert providers[0].config.db_path != providers[1].config.db_path


def test_config_requires_hermes_home(plugin_module):
    p = plugin_module.RelateDBMemoryProvider()
    p.initialize("s")
    with pytest.raises(RuntimeError):
        p.config


# -- availability, backup, lifecycle --


def test_available_when_relate_importable(plugin_module):
    p = plugin_module.RelateDBMemoryProvider()
    assert p.is_available() is True and p.unavailable_reason() == ""


def test_unavailable_without_relate(plugin_module, monkeypatch):
    import relatedb_memory.provider as prov

    monkeypatch.setattr(prov.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(prov.shutil, "which", lambda name: None)
    p = plugin_module.RelateDBMemoryProvider()
    assert p.is_available() is False
    assert "relate-db" in p.unavailable_reason() and "install" in p.unavailable_reason()


def test_cli_alone_counts_as_available(plugin_module, monkeypatch):
    import relatedb_memory.provider as prov

    monkeypatch.setattr(prov.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(prov.shutil, "which", lambda name: "/usr/bin/relate")
    assert plugin_module.RelateDBMemoryProvider().is_available() is True


def test_backup_paths(plugin_module, tmp_path):
    p = plugin_module.RelateDBMemoryProvider()
    assert p.backup_paths() == []  # uninitialized
    p.initialize("s", hermes_home=str(tmp_path / "h"))
    assert p.backup_paths() == []  # inside HERMES_HOME
    out = tmp_path / "elsewhere" / "memory"
    (tmp_path / "h").mkdir()
    write_cfg(tmp_path / "h", {"db_path": str(out)})
    p.initialize("s", hermes_home=str(tmp_path / "h"))
    assert p.backup_paths() == [str(out)]


def test_profile_lifecycle(plugin_module, tmp_path):
    p = plugin_module.RelateDBMemoryProvider()
    home = tmp_path / "profiles" / "work"
    write_dir = home
    write_dir.mkdir(parents=True)
    write_cfg(home, {"snapshot_format": "json"})
    p.on_profile_created("work", str(home))
    assert (home / "memory").is_dir()
    p.on_profile_renamed("work", "play", str(home))  # no-op, must not raise


# -- config_schema.py --


@pytest.fixture
def schema_module(monkeypatch):
    """Load config_schema.py by path, as Hermes does, using the real base module when present."""
    try:
        import plugins.memory.config_schema  # noqa: F401
    except ImportError:
        pkg = types.ModuleType("plugins")
        pkg.__path__ = []
        sub = types.ModuleType("plugins.memory")
        sub.__path__ = []
        base = types.ModuleType("plugins.memory.config_schema")
        from dataclasses import dataclass, field

        @dataclass(frozen=True)
        class ProviderFieldOption:
            value: str
            label: str
            description: str = ""

        @dataclass(frozen=True)
        class ProviderField:
            key: str
            label: str
            kind: str = "text"
            default: str = ""
            description: str = ""
            placeholder: str = ""
            options: tuple = ()
            inline: bool = False
            group: str = ""

        @dataclass(frozen=True)
        class ProviderConfigSchema:
            name: str
            label: str
            storage: str = "flat_json"
            fields: tuple = field(default_factory=tuple)

        base.__dict__.update(
            KIND_TEXT="text", KIND_SELECT="select", KIND_BOOL="bool", KIND_NUMBER="number",
            STORAGE_PROVIDER="provider", ProviderField=ProviderField,
            ProviderFieldOption=ProviderFieldOption, ProviderConfigSchema=ProviderConfigSchema,
        )
        for name, mod in (("plugins", pkg), ("plugins.memory", sub), ("plugins.memory.config_schema", base)):
            monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("_hermes_memory_config_schema.relatedb", ROOT / "config_schema.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_schema_loads_by_path_without_runtime(schema_module):
    before = {m for m in sys.modules if m.startswith("relatedb_memory")}
    schema = schema_module.CONFIG_SCHEMA
    assert schema.name == "relatedb-memory" and schema.storage == "provider"
    assert {m for m in sys.modules if m.startswith("relatedb_memory")} == before


def test_schema_imports_only_hermes_schema_module():
    import ast

    tree = ast.parse((ROOT / "config_schema.py").read_text())
    mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert mods == ["plugins.memory.config_schema"]


def test_schema_defaults_match_runtime(schema_module):
    fields = {f.key: f for f in schema_module.CONFIG_SCHEMA.fields}
    assert set(fields) == set(cfg.ENV_VARS)
    assert fields["embedding_model"].default == cfg.DEFAULT_EMBEDDING_MODEL
    assert fields["snapshot_format"].default == cfg.DEFAULT_SNAPSHOT_FORMAT
    assert int(fields["prefetch_top_k"].default) == cfg.DEFAULT_PREFETCH_TOP_K
    assert (fields["auto_extract"].default == "true") is cfg.DEFAULT_AUTO_EXTRACT
    assert {o.value for o in fields["snapshot_format"].options} == set(cfg.SNAPSHOT_FORMATS)


def test_captured_share_default_env_and_validation(tmp_path):
    assert resolve(tmp_path, {}).captured_share == cfg.DEFAULT_CAPTURED_SHARE == 0.5
    assert resolve(tmp_path, {"RELATEDB_CAPTURED_SHARE": "0.25"}).captured_share == 0.25
    for bad in ("2", "-0.1", "lots"):
        with pytest.raises(ValueError, match="captured_share"):
            resolve(tmp_path, {"RELATEDB_CAPTURED_SHARE": bad})
