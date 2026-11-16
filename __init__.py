"""Hermes memory provider plugin: RelateDB bi-temporal memory.

Hermes loads this directory as a plugin (``$HERMES_HOME/plugins/relatedb-memory``) and
calls ``register(ctx)``. Importing it must not require Hermes on ``sys.path``.
"""

from pathlib import Path

try:
    from .relatedb_memory.provider import RelateDBMemoryProvider
except ImportError:  # imported as a bare module (e.g. by a test collector), not as a package
    from relatedb_memory.provider import RelateDBMemoryProvider


def register(ctx) -> None:
    """Register a fresh provider instance per load (multi-profile multiplexing)."""
    ctx.register_memory_provider(RelateDBMemoryProvider())
    register_skill = getattr(ctx, "register_skill", None)
    skill_path = Path(__file__).resolve().parent / "skills" / "relatedb-memory" / "SKILL.md"
    if callable(register_skill) and skill_path.is_file():
        register_skill("relatedb-memory", skill_path)
