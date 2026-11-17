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
    ),
)
