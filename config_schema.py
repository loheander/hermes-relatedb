"""Dashboard config schema for the relatedb-memory provider.

Hermes loads this file by path, so it may import only
``plugins.memory.config_schema``. The defaults repeat those in
``relatedb_memory.config``; a test keeps the two in sync.
"""

from plugins.memory.config_schema import (
    KIND_BOOL,
    KIND_NUMBER,
    KIND_SELECT,
    KIND_TEXT,
    STORAGE_PROVIDER,
    ProviderConfigSchema,
    ProviderField,
    ProviderFieldOption,
)

CONFIG_SCHEMA = ProviderConfigSchema(
    name="relatedb-memory",
    label="RelateDB",
    storage=STORAGE_PROVIDER,
    fields=(
        ProviderField(
            key="snapshot_format",
            label="Snapshot format",
            kind=KIND_SELECT,
            default="parquet",
            description="How the store is persisted.",
            options=(
                ProviderFieldOption("parquet", "Parquet directory", "A directory of Parquet files."),
                ProviderFieldOption("json", "JSON directory", "A diffable directory store."),
                ProviderFieldOption("rl", "Single file (rl)", "One memory.rl file."),
            ),
            inline=True,
        ),
        ProviderField(
            key="db_path",
            label="Store path",
            kind=KIND_TEXT,
            description="Relative paths resolve against the profile's HERMES_HOME. Must be a directory for parquet/json or a .rl file for rl.",
            placeholder="<hermes_home>/memory/",
            inline=True,
        ),
        ProviderField(
            key="embedding_model",
            label="Embedding model",
            kind=KIND_TEXT,
            default="BAAI/bge-small-en-v1.5",
            description="fastembed model used for local vector recall (384-dim by default).",
            group="Recall",
        ),
        ProviderField(
            key="prefetch_top_k",
            label="Facts per turn",
            kind=KIND_NUMBER,
            default="8",
            description="Maximum facts injected on turn prefetch.",
            group="Recall",
        ),
        ProviderField(
            key="auto_extract",
            label="Auto-extract facts",
            kind=KIND_BOOL,
            default="true",
            description="Extract facts from turns in the background.",
            group="Recall",
        ),
        ProviderField(
            key="captured_share",
            label="Captured share of recall",
            kind=KIND_NUMBER,
            default="0.5",
            description="Largest share of the facts per turn that captured transcript turns may fill (0 to 1).",
            group="Recall",
        ),
        ProviderField(
            key="dedupe",
            label="Collapse near-duplicates",
            kind=KIND_BOOL,
            default="true",
            description="Flag near-duplicate facts on write and return one hit per duplicate cluster in recall.",
            group="Recall",
        ),
        ProviderField(
            key="dedupe_threshold",
            label="Duplicate threshold",
            kind=KIND_NUMBER,
            default="0.92",
            description="Cosine similarity at or above which two facts count as duplicates (0 to 1).",
            group="Recall",
        ),
        ProviderField(
            key="mirror_builtin_memory",
            label="Mirror USER.md/MEMORY.md",
            kind=KIND_BOOL,
            default="true",
            description=(
                "Mirror writes made with the built-in memory tool (USER.md, MEMORY.md) into the graph: "
                "relatedb's view of what the model chose to remember, with history and relatedb_as_of. "
                "Turn off to avoid a second copy of what Hermes already injects; relatedb then no longer "
                "sees memory-tool writes and relatedb_remember is the only explicit write path. "
                "Facts already mirrored stay until forgotten."
            ),
            group="Recall",
        ),
    ),
)
