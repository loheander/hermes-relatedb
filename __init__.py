"""Hermes memory provider plugin: RelateDB bi-temporal memory.

Hermes loads this directory as a plugin (``$HERMES_HOME/plugins/relatedb``) and
calls ``register(ctx)``. Importing it must not require Hermes on ``sys.path``.
"""

try:
    from .relatedb_memory.provider import RelateDBMemoryProvider
except ImportError:  # imported as a bare module (e.g. by a test collector), not as a package
    from relatedb_memory.provider import RelateDBMemoryProvider


def register(ctx) -> None:
    """Register a fresh provider instance per load (multi-profile multiplexing)."""
    ctx.register_memory_provider(RelateDBMemoryProvider())
