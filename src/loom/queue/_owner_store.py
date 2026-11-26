"""Open an existing native owner store and verify its retained role binding."""

from pathlib import Path
import sqlite3

from loom._sqlite_policy import SQLitePolicy, connect_existing


def _connect_existing_sqlite(path: Path, *, sqlite_policy: SQLitePolicy | None = None) -> sqlite3.Connection:
    if sqlite_policy is not None:
        return connect_existing(path, policy=sqlite_policy, isolation_level="")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)


def _verify_owner_store_binding(conn: sqlite3.Connection, *, role: str, stable_id: str) -> None:
    rows = tuple(
        tuple(row) for row in conn.execute("SELECT role, stable_id FROM local_daemon_owner_identity")
    )
    if rows != ((role, stable_id),):
        raise sqlite3.DatabaseError("retained daemon owner identity is invalid")
