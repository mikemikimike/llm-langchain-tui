"""App configuration, loaded from config.json and validated at import.

A missing key, a mistyped value, or a whole missing section raises at import
with the offending key in the message — the same fail-fast contract the old
.env reader had, nothing travels far before it breaks.

Relative paths in config.json are resolved against the project root, so app.py
and anything in scripts/ find db/ and prompts/ regardless of the directory
they were launched from.

config.json is gitignored (it can hold secrets, e.g. the Obsidian API key);
config.example.json is the committed template. Copy it to config.json to run.

Everything provider/model related lives in models.json (see
llmtui/models_config.py, step 2 of SPEC-provider-migration.md) — nothing
here knows about providers.
"""

import json
import os
from pathlib import Path

# milvus-lite forks a server subprocess out of this process, and gRPC writes a
# fork-guard warning to stderr the first time that happens -- which lands mid-TUI,
# rendered straight into the prompt area. the warning is harmless and gRPC's C
# core reads this at import time, so it is set here, before anything imports it
os.environ.setdefault("GRPC_VERBOSITY", "NONE")

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

# overridable so tests can point at their own config
CONFIG_PATH: Path = Path(
    os.getenv("LLMTUI_CONFIG", PROJECT_ROOT / "config" / "config.json")
)


def _load() -> dict:
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"{CONFIG_PATH} not found. Copy config/config.example.json to"
            " config/config.json and fill in your values."
        )
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{CONFIG_PATH} is not valid JSON: {e}") from None


_cfg = _load()


def _section(name: str) -> dict:
    section = _cfg.get(name)
    if not isinstance(section, dict):
        raise RuntimeError(f"{CONFIG_PATH}: missing or malformed section {name!r}")
    return section


def _get(section: dict, key: str) -> str:
    value = section.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise RuntimeError(f"{CONFIG_PATH}: {key!r} is missing or empty")
    return value.strip() if isinstance(value, str) else value


def _path(section: dict, key: str) -> str:
    """Absolute path as a string, resolved against the project root."""

    return str(PROJECT_ROOT / _get(section, key))


def _int(section: dict, key: str) -> int:
    value = _get(section, key)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise RuntimeError(
            f"{CONFIG_PATH}: {key!r} must be a whole number, got {value!r}"
        ) from None


# paths
_paths = _section("paths")
SQLITE_DB_PATH: str = _path(_paths, "sqlite_db")
MILVUS_DEV_DB_PATH: str = _path(_paths, "milvus_dev_db")
MILVUS_PROD_DB_PATH: str = _path(_paths, "milvus_prod_db")
SYSTEM_PROMPT_PATH: str = _path(_paths, "system_prompt")
SELF_NAME_PROMPT_PATH: str = _path(_paths, "self_name_prompt")
OBSIDIAN_CERT_PATH: str = _path(_paths, "obsidian_cert")

# milvus index configuration, shared by ingest and search so the schemas match
_milvus = _section("milvus")
DENSE_METRIC_TYPE: str = _get(_milvus, "dense_metric_type")
DENSE_INDEX_TYPE: str = _get(_milvus, "dense_index_type")
SPARSE_METRIC_TYPE: str = _get(_milvus, "sparse_metric_type")
SPARSE_INDEX_TYPE: str = _get(_milvus, "sparse_index_type")

# fixed by langchain_milvus, not user-configurable: the name it gives its
# collection, and the property key ingest.py uses to record which embeddings
# entry built the store. shared by ingest and search so the two can't drift
MILVUS_COLLECTION_NAME: str = "LangChainCollection"
EMBEDDING_MODEL_KEY: str = "embedding_model"

MILVUS_GRPC_OPTIONS: dict = {
    "grpc.keepalive_permit_without_calls": False,
    "grpc.keepalive_time_ms": 300_000,
}

# agent behaviour
_agent = _section("agent")
# searches allowed per user turn
MAX_TOOL_CALLS: int = _int(_agent, "max_tool_calls")
DISPLAY_THINKING: bool = bool(_get(_agent, "display_thinking"))

# obsidian / mcp
_obsidian = _section("obsidian")
OBSIDIAN_API_KEY: str = _get(_obsidian, "api_key")

# the pdf library itself. citations resolve against this directory; ingest.py
# reads the same directory from its argv, so the two must stay in sync. Milvus
# metadata holds basenames only, so same-named PDFs in different subdirs collide
_library = _section("library")
LIBRARY_DIR: str = _path(_library, "pdf_dir")

# where inspect_context.py leaves its rendered pages. not in config.json
# because nothing else reads it and it is not a knob worth turning
CONTEXT_DUMP_DIR: str = str(PROJECT_ROOT / "resources" / "context_inspection")
