"""Internal implementation of the RelateDB memory provider."""


def register(ctx) -> None:
    """Register a fresh provider instance per load (multi-profile multiplexing)."""
    from .provider import RelateDBMemoryProvider

    ctx.register_memory_provider(RelateDBMemoryProvider())

