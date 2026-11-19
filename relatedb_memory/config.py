"""Profile-scoped configuration and store path resolution.

Resolution order, highest first: scoped environment (read through
``agent.secret_scope.get_secret`` so one profile never sees another's value
under multiplexing), the ``memory.relatedb-memory`` mapping in
``<hermes_home>/config.yaml``, then the defaults below. Everything here is a
pure function of ``hermes_home``; there is no module-level mutable state, so
providers for different profiles can resolve concurrently.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

log = logging.getLogger(__name__)

SNAPSHOT_FORMATS = ("rl", "parquet", "json")
DIRECTORY_FORMATS = ("parquet", "json")

DEFAULT_SNAPSHOT_FORMAT = "parquet"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_PREFETCH_TOP_K = 8
DEFAULT_AUTO_EXTRACT = True
DEFAULT_CAPTURED_SHARE = 0.5

CONFIG_FILENAME = "config.yaml"
PROVIDER_NAME = "relatedb-memory"
CONFIG_SECTION = ("memory", PROVIDER_NAME)

#: config key -> scoped environment variable
ENV_VARS = {
    "db_path": "RELATEDB_DB_PATH",
    "snapshot_format": "RELATEDB_SNAPSHOT_FORMAT",
    "embedding_model": "RELATEDB_EMBEDDING_MODEL",
    "prefetch_top_k": "RELATEDB_PREFETCH_TOP_K",
    "auto_extract": "RELATEDB_AUTO_EXTRACT",
    "captured_share": "RELATEDB_CAPTURED_SHARE",
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class RelateDBConfig:
    """Resolved settings for one profile."""

    hermes_home: Path
    db_path: Path
    snapshot_format: str = DEFAULT_SNAPSHOT_FORMAT
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    prefetch_top_k: int = DEFAULT_PREFETCH_TOP_K
    auto_extract: bool = DEFAULT_AUTO_EXTRACT
    captured_share: float = DEFAULT_CAPTURED_SHARE


def default_db_path(hermes_home: str | os.PathLike[str], snapshot_format: str) -> Path:
    home = Path(hermes_home)
    return home / "memory" if snapshot_format in DIRECTORY_FORMATS else home / "memory.rl"


def validate_db_path_for_format(
    db_path: str | os.PathLike[str],
    snapshot_format: str,
    *,
    hermes_home: str | os.PathLike[str] | None = None,
) -> None:
    """Ensure ``db_path`` matches ``snapshot_format``: ``.rl`` file for ``rl``, directory for ``json``/``parquet``."""
    raw = str(db_path).strip()
    p = Path(raw).expanduser()
    resolved = (Path(hermes_home).expanduser() / p) if (hermes_home is not None and not p.is_absolute()) else p

    if snapshot_format == "rl":
        if raw.endswith(("/", "\\")) or p.suffix.lower() != ".rl":
            raise ValueError(f"db_path must be a file ending in '.rl' when snapshot_format is 'rl', got {raw!r}")
        if resolved.exists() and resolved.is_dir():
            raise ValueError(f"db_path must be a file (not an existing directory) when snapshot_format is 'rl', got {raw!r}")
    elif snapshot_format in DIRECTORY_FORMATS:
        if p.suffix.lower() == ".rl":
            raise ValueError(
                f"db_path must be a directory (not a '.rl' file) when snapshot_format is {snapshot_format!r}, got {raw!r}"
            )
        if resolved.exists() and not resolved.is_dir():
            raise ValueError(
                f"db_path must be a directory (not an existing file) when snapshot_format is {snapshot_format!r}, got {raw!r}"
            )
def _scoped_getter() -> Callable[[str], str | None]:
    try:
        from agent.secret_scope import get_secret
    except ImportError:  # Hermes absent: plain process environment
        return os.environ.get
    return lambda name: get_secret(name, None)


def _parse_bool(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"{key} must be a boolean, got {value!r}")


def _parse_top_k(value: Any, key: str = "prefetch_top_k") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a positive integer, got {value!r}")
    try:
        number = int(str(value).strip()) if not isinstance(value, int) else value
    except ValueError:
        raise ValueError(f"{key} must be a positive integer, got {value!r}") from None
    if number < 1:
        raise ValueError(f"{key} must be a positive integer, got {value!r}")
    return number


def _parse_share(value: Any, key: str = "captured_share") -> float:
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number between 0 and 1, got {value!r}")
    try:
        number = float(str(value).strip()) if not isinstance(value, (int, float)) else float(value)
    except ValueError:
        raise ValueError(f"{key} must be a number between 0 and 1, got {value!r}") from None
    if not 0 <= number <= 1:
        raise ValueError(f"{key} must be a number between 0 and 1, got {value!r}")
    return number


def _parse_format(value: Any, key: str = "snapshot_format") -> str:
    text = str(value).strip().lower()
    if text not in SNAPSHOT_FORMATS:
        raise ValueError(f"{key} must be one of {', '.join(SNAPSHOT_FORMATS)}, got {value!r}")
    return text


def _parse_text(value: Any, key: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{key} must not be empty")
    return text


def config_path(hermes_home: str | os.PathLike[str]) -> Path:
    return Path(hermes_home) / CONFIG_FILENAME


def read_yaml_section(hermes_home: str | os.PathLike[str]) -> dict[str, Any]:
    """The ``memory.relatedb-memory`` mapping of ``<hermes_home>/config.yaml`` ({} when absent or invalid)."""
    path = config_path(hermes_home)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("relatedb: ignoring unreadable %s: %s", path, exc)
        return {}
    for part in CONFIG_SECTION:
        data = data.get(part) if isinstance(data, dict) else None
    return dict(data) if isinstance(data, dict) else {}


def resolve_config(
    hermes_home: str | os.PathLike[str],
    *,
    env_get: Callable[[str], str | None] | None = None,
) -> RelateDBConfig:
    """Resolve the settings of the profile rooted at ``hermes_home``.

    Raises ``ValueError`` for an invalid value so a typo surfaces instead of
    silently falling back to a different store.
    """
    home = Path(hermes_home).expanduser()
    get = env_get or _scoped_getter()
    section = read_yaml_section(home)

    def pick(key: str) -> Any:
        raw = get(ENV_VARS[key])
        if raw is not None and str(raw).strip() != "":
            return raw
        value = section.get(key)
        return None if value is None or str(value).strip() == "" else value

    fmt_raw = pick("snapshot_format")
    fmt = DEFAULT_SNAPSHOT_FORMAT if fmt_raw is None else _parse_format(fmt_raw)

    path_raw = pick("db_path")
    if path_raw is None:
        db_path = default_db_path(home, fmt)
    else:
        validate_db_path_for_format(path_raw, fmt, hermes_home=home)
        db_path = Path(str(path_raw).strip()).expanduser()
        if not db_path.is_absolute():
            db_path = home / db_path

    model_raw = pick("embedding_model")
    top_k_raw = pick("prefetch_top_k")
    auto_raw = pick("auto_extract")
    share_raw = pick("captured_share")
    return RelateDBConfig(
        hermes_home=home,
        db_path=db_path,
        snapshot_format=fmt,
        embedding_model=DEFAULT_EMBEDDING_MODEL if model_raw is None else _parse_text(model_raw, "embedding_model"),
        prefetch_top_k=DEFAULT_PREFETCH_TOP_K if top_k_raw is None else _parse_top_k(top_k_raw),
        auto_extract=DEFAULT_AUTO_EXTRACT if auto_raw is None else _parse_bool(auto_raw, "auto_extract"),
        captured_share=DEFAULT_CAPTURED_SHARE if share_raw is None else _parse_share(share_raw),
    )


_VALIDATORS: dict[str, Callable[[Any, str], Any]] = {
    "db_path": _parse_text,
    "snapshot_format": lambda v, k: _parse_format(v, k),
    "embedding_model": _parse_text,
    "prefetch_top_k": lambda v, k: _parse_top_k(v, k),
    "auto_extract": _parse_bool,
    "captured_share": _parse_share,
}


def validate_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and coerce known keys; ``None`` or blank means unset (cleared). Unknown keys are dropped."""
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key not in _VALIDATORS:
            continue
        out[key] = None if value is None or str(value).strip() == "" else _VALIDATORS[key](value, key)
    return out


def write_yaml_section(hermes_home: str | os.PathLike[str], values: Mapping[str, Any]) -> None:
    """Merge validated ``values`` into ``memory.relatedb-memory``, keeping every other key; ``None`` clears a key."""
    clean = validate_values(values)
    path = config_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a YAML mapping; refusing to overwrite it")
    memory = data.get("memory")
    if memory is None:
        memory = data["memory"] = {}
    if not isinstance(memory, dict):
        raise ValueError(f"{path}: 'memory' is not a mapping; refusing to overwrite it")
    section = memory.get(PROVIDER_NAME)
    if not isinstance(section, dict):
        section = memory[PROVIDER_NAME] = {}
    effective_fmt_raw = clean["snapshot_format"] if "snapshot_format" in clean else section.get("snapshot_format")
    effective_fmt = DEFAULT_SNAPSHOT_FORMAT if effective_fmt_raw is None else _parse_format(effective_fmt_raw)
    effective_path = clean["db_path"] if "db_path" in clean else section.get("db_path")
    if effective_path is not None and str(effective_path).strip() != "":
        validate_db_path_for_format(effective_path, effective_fmt, hermes_home=hermes_home)
    for key, value in clean.items():
        if value is None:
            section.pop(key, None)
        else:
            section[key] = value
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
