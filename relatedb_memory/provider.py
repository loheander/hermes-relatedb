"""RelateDB memory provider entry point."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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

    @property
    def name(self) -> str:
        return "relatedb"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id
        self._init_kwargs = dict(kwargs)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return []
