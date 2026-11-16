"""RelateDB memory provider entry point."""

from __future__ import annotations

import importlib.util
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from . import config as _config


try:  # Hermes runtime is optional at import time.
    from agent.memory_provider import MemoryProvider as _Base
except ImportError:  # pragma: no cover - exercised when Hermes is absent

    class _Base(ABC):  # type: ignore[no-redef]
        """Minimal stand-in so the package imports without Hermes Agent."""

        @property
        @abstractmethod
        def name(self) -> str: ...

        @abstractmethod
        def is_available(self) -> bool: ...

        @abstractmethod
        def initialize(self, session_id: str, **kwargs: Any) -> None: ...

        @abstractmethod
        def get_tool_schemas(self) -> list[dict[str, Any]]: ...


class RelateDBMemoryProvider(_Base):
    """Per-instance state only; no module-level mutable profile state."""

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._init_kwargs: dict[str, Any] = {}
        self._config: _config.RelateDBConfig | None = None

    @property
    def name(self) -> str:
        return "relatedb"

    def is_available(self) -> bool:
        """True when the ``relate`` module or CLI is present; never imports it or touches the network."""
        return self._relate_installed()

    @staticmethod
    def _relate_installed() -> bool:
        try:
            if importlib.util.find_spec("relate") is not None:
                return True
        except (ImportError, ValueError):
            pass
        return shutil.which("relate") is not None

    def unavailable_reason(self) -> str:
        if self._relate_installed():
            return ""
        return "relate-db is not installed: run `pip install relate-db` (or `uv add relate-db`) in the Hermes environment."

    @property
    def config(self) -> _config.RelateDBConfig:
        if self._config is None:
            raise RuntimeError("relatedb provider not initialized with hermes_home")
        return self._config

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id
        self._init_kwargs = dict(kwargs)
        hermes_home = kwargs.get("hermes_home")
        # Bind strictly to the profile Hermes passes in; never fall back to ~/.hermes.
        self._config = _config.resolve_config(hermes_home) if hermes_home else None

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return []

    # -- setup / dashboard configuration --

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "snapshot_format",
                "description": "Store format: rl (single file), parquet or json (directory)",
                "default": _config.DEFAULT_SNAPSHOT_FORMAT,
                "choices": list(_config.SNAPSHOT_FORMATS),
            },
            {
                "key": "db_path",
                "description": "Store path (blank: <hermes_home>/memory.rl, or memory/ for directory formats)",
                "default": "",
            },
            {
                "key": "embedding_model",
                "description": "model2vec embedding model",
                "default": _config.DEFAULT_EMBEDDING_MODEL,
            },
            {
                "key": "prefetch_top_k",
                "description": "Maximum facts injected per turn",
                "default": _config.DEFAULT_PREFETCH_TOP_K,
                "type": "integer",
                "minimum": 1,
            },
            {
                "key": "auto_extract",
                "description": "Extract facts from turns in the background",
                "default": _config.DEFAULT_AUTO_EXTRACT,
                "type": "boolean",
            },
        ]

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        _config.write_yaml_section(hermes_home, values)

    def read_config_fields(self, hermes_home: str) -> dict[str, Any]:
        stored = _config.read_yaml_section(hermes_home)
        values = {k: v for k, v in stored.items() if k in _config.ENV_VARS}
        resolved = _config.resolve_config(hermes_home)
        return {"values": values, "placeholders": {"db_path": str(resolved.db_path)}}

    def write_config_fields(self, values: dict[str, Any], hermes_home: str) -> None:
        _config.write_yaml_section(hermes_home, values)

    # -- backup and profile lifecycle (work on an uninitialized instance) --

    def backup_paths(self) -> list[str]:
        """Store path when it lives outside HERMES_HOME; paths inside it are backed up by Hermes itself."""
        cfg = self._config
        if cfg is None:
            return []
        try:
            cfg.db_path.resolve().relative_to(cfg.hermes_home.resolve())
        except ValueError:
            return [str(cfg.db_path)]
        return []

    def on_profile_created(self, profile_name: str, hermes_home: str) -> None:
        cfg = _config.resolve_config(hermes_home)
        target = cfg.db_path if cfg.snapshot_format in _config.DIRECTORY_FORMATS else cfg.db_path.parent
        Path(target).mkdir(parents=True, exist_ok=True)

    def on_profile_renamed(self, old_name: str, new_name: str, hermes_home: str) -> None:
        """Nothing to re-key: the store path is derived from ``hermes_home``, not the profile name."""
