"""Restore a backed-up vector store into the live location (issue #24).

Usage: uv run python scripts/restore.py

The current live store is backed up first, so a restore is itself
reversible. Run this with the TUI closed -- milvus-lite locks the db dir,
and a live connection would recreate the files on top of the restore.
"""

import sys
from pathlib import Path

# this is run straight from a shell, so the project root has to go on the path
# before anything under llmtui can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llmtui.config import MILVUS_BACKUP_DIR, MILVUS_DB_PATH
from llmtui.store_backup import list_backups, restore_backup


def main() -> None:
    backups = list_backups(MILVUS_BACKUP_DIR)
    if not backups:
        sys.exit(f"No backups found in {MILVUS_BACKUP_DIR}.")

    print("Backups (oldest first):")
    for i, b in enumerate(backups, start=1):
        print(f"  {i}. {b.path.name}  (embedding: {b.embedding_model})")
    while True:
        choice = input("Which one to restore? ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(backups):
            break
        print(f"Enter a number between 1 and {len(backups)}.")
    backup = backups[int(choice) - 1]

    print()
    print(f"WARNING: close the TUI first -- milvus-lite locks {MILVUS_DB_PATH}.")
    if Path(MILVUS_DB_PATH).exists():
        print(
            f"The current live store will be moved to {MILVUS_BACKUP_DIR} "
            "(last-1 retention), so this restore is reversible."
        )
    confirm = input("Restore now? (y/N): ")
    if confirm.strip().lower() != "y":
        sys.exit("Aborting.")

    dest = restore_backup(backup.path, MILVUS_DB_PATH, MILVUS_BACKUP_DIR)
    print(f"Restored {backup.path.name} to {dest}")


if __name__ == "__main__":
    main()
