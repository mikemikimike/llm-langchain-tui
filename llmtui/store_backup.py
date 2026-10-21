"""Single live vector store + automatic backup (issue #24).

Replaces the old dev/prod split: ingest builds into MILVUS_DB_PATH; before a
wipe the live store is MOVED (not copied) into MILVUS_BACKUP_DIR, keeping
only the last backup. restore.py swaps a backup back into place.

The move is the whole safety net: the store is rebuildable from the PDFs,
so the backup is a safety net, not an archive (last-1 retention is
deliberate).
"""

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pymilvus import MilvusClient

from llmtui.config import (
    EMBEDDING_MODEL_KEY,
    MILVUS_BACKUP_DIR,
    MILVUS_COLLECTION_NAME,
    MILVUS_DB_PATH,
    MILVUS_GRPC_OPTIONS,
)

# the tag read from a backup's collection property; backups built before
# the tagging exists (or with no collection at all) fall back to this
UNTAGGED = "untagged"


def _close_server() -> None:
    """Stop the embedded milvus-lite server for the live db, if any.

    client.close() only drops the connection; the in-process server thread
    keeps the DB dir alive and recreates files on the next connection.
    """

    try:
        from milvus_lite.server_manager import server_manager_instance
    except ImportError:
        return
    # release_server keys its registry on os.path.abspath -- pass exactly that
    # form, or the lookup misses and the server keeps the DB dir alive
    server_manager_instance.release_server(os.path.abspath(MILVUS_DB_PATH))


def _backup_name(backup_dir: Path) -> str:
    """milvus-<timestamp>-<embedding-entry-name> for the live store.

    The entry name comes from the collection property ingest writes, so a
    glance at the backup folder shows which model built it.
    """

    name = UNTAGGED
    try:
        client = MilvusClient(uri=MILVUS_DB_PATH, grpc_options=MILVUS_GRPC_OPTIONS)
        try:
            if client.has_collection(MILVUS_COLLECTION_NAME):
                desc = client.describe_collection(MILVUS_COLLECTION_NAME) or {}
                value = (desc.get("properties") or {}).get(EMBEDDING_MODEL_KEY)
                if isinstance(value, str) and value:
                    name = value
        finally:
            client.close()
    except Exception:
        pass  # unreadable store is still backed up, just untagged
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"milvus-{stamp}-{name}"


def backup_store(
    live: str | Path = MILVUS_DB_PATH,
    backup_dir: str | Path = MILVUS_BACKUP_DIR,
    keep: str | Path | None = None,
) -> Path:
    """Move the live store into backup_dir, keeping only the last backup.

    A move, not a copy: atomic, and it leaves no stale live store behind.
    The previous backup, if any, is deleted (last-1 retention) -- except
    the one named in `keep` (restore.py passes the backup it is moving
    back, so pruning does not eat its own lunch).
    """

    live = Path(live)
    backup_dir = Path(backup_dir)
    if not live.exists():
        raise FileNotFoundError(f"no live store at {live} to back up")
    _close_server()
    backup_dir.mkdir(parents=True, exist_ok=True)
    # prune first, then move: pruning after would keep the "newest" name and
    # could delete the backup we just made (same-second collision suffixes)
    _prune(backup_dir, keep=Path(keep) if keep else None)
    dest = backup_dir / _backup_name(backup_dir)
    while dest.exists():
        dest = backup_dir / f"{dest.name}-1"
    live.rename(dest)
    return dest


def _prune(backup_dir: Path, keep: Path | None) -> None:
    """Last-1 retention: drop every backup except the newest one."""

    backups = sorted(backup_dir.glob("milvus-*"), reverse=True)
    for old in backups:
        if old == keep:
            continue
        if old.is_dir():
            shutil.rmtree(old)
        else:
            old.unlink()


@dataclass
class Backup:
    path: Path
    embedding_model: str  # UNTAGGED when the store has no recorded tag


def list_backups(backup_dir: str | Path = MILVUS_BACKUP_DIR) -> list[Backup]:
    """The backups in backup_dir, oldest first (name is timestamp-prefixed)."""

    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    out: list[Backup] = []
    for path in sorted(backup_dir.glob("milvus-*")):
        if not path.is_dir():
            continue
        name = UNTAGGED
        try:
            client = MilvusClient(uri=str(path), grpc_options=MILVUS_GRPC_OPTIONS)
            try:
                if client.has_collection(MILVUS_COLLECTION_NAME):
                    desc = client.describe_collection(MILVUS_COLLECTION_NAME) or {}
                    value = (desc.get("properties") or {}).get(EMBEDDING_MODEL_KEY)
                    if isinstance(value, str) and value:
                        name = value
            finally:
                client.close()
        except Exception:
            pass
        out.append(Backup(path=path, embedding_model=name))
    return out


def restore_backup(
    backup: str | Path,
    live: str | Path = MILVUS_DB_PATH,
    backup_dir: str | Path = MILVUS_BACKUP_DIR,
) -> Path:
    """Swap a backup into the live location.

    The current live store is backed up first, so a restore is itself
    reversible. The restored dir is removed from backup_dir (it is now the
    live store).
    """

    backup = Path(backup)
    live = Path(live)
    if not backup.is_dir():
        raise FileNotFoundError(f"no backup at {backup}")
    if live.exists():
        backup_store(live, backup_dir, keep=backup)
    _close_server()
    backup.rename(live)
    return live
