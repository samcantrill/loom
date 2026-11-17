"""Rebuildable collection membership and immutable ordering facts, never status."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import cast

from .errors import RunProjectionError


def index_path(root: Path) -> Path:
    return root / ".loom_catalog" / "discovery.sqlite"


@contextmanager
def connection(root: Path, *, create: bool = False):
    path = index_path(root)
    conn = None
    try:
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=5)
        else:
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in ({0, 1} if create else {1}):
            raise RunProjectionError("unsupported discovery index schema; explicit refresh required")
        # This index is also used on qualified shared filesystems. Never select
        # WAL or spill temporary sorting files into an implicit host /tmp.
        conn.execute("PRAGMA temp_store=MEMORY")
        if create:
            with conn:
                conn.execute("CREATE TABLE IF NOT EXISTS discovery_metadata ("
                             "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                             "revision INTEGER NOT NULL, refreshed INTEGER NOT NULL)")
                conn.execute("INSERT OR IGNORE INTO discovery_metadata VALUES(1,0,0)")
                conn.execute("CREATE TABLE IF NOT EXISTS discovery_runs ("
                             "run_uri TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
                             "revision INTEGER NOT NULL, pending INTEGER NOT NULL)")
                conn.execute("PRAGMA user_version=1")
        yield conn
    except (OSError, sqlite3.DatabaseError) as error:
        raise RunProjectionError("run discovery index unavailable; refresh the collection index") from error
    finally:
        if conn is not None:
            conn.close()


def register(root: Path, run_uri: str, created_at: str, *, published: bool) -> None:
    """Retain creation intent before file publication, then acknowledge it.

    An interrupted writer can leave a pending row. Readers must consult the
    actual run document; this row cannot establish execution or publication.
    """
    with connection(root, create=True) as conn, conn:
        conn.execute("UPDATE discovery_metadata SET revision=revision+1 WHERE singleton=1")
        revision = conn.execute("SELECT revision FROM discovery_metadata").fetchone()[0]
        conn.execute(
            "INSERT INTO discovery_runs VALUES(?,?,?,?) ON CONFLICT(run_uri) DO UPDATE SET "
            "created_at=excluded.created_at, revision=excluded.revision, "
            "pending=MIN(discovery_runs.pending, excluded.pending)",
            (run_uri, created_at, revision, int(not published)),
        )


def refresh(root: Path) -> tuple[dict[str, str], ...]:
    """Explicitly discover external copies/deletions without a write lock during IO.

    Registrations newer than the scan's watermark win over the scan. Missing
    pending writes are retained: refresh cannot prove an interrupted writer will
    not finish. Their unavailable document remains visible in query coverage.
    """
    from .local_runs import LocalRunStore
    from .run_uri import path_to_run_uri
    from .errors import StoreError

    if not root.is_dir():
        raise RunProjectionError("collection is unavailable; existing index retained")
    with connection(root, create=True) as conn:
        watermark = conn.execute("SELECT revision FROM discovery_metadata").fetchone()[0]
    store = LocalRunStore(root)
    found: dict[str, str] = {}
    warnings: list[dict[str, str]] = []
    # Failure to enumerate must not prune the existing index.
    try:
        for path in root.iterdir():
            if path.name == ".loom_catalog":
                continue
            uri = path_to_run_uri(path)
            try:
                if not path.is_dir():
                    continue
                found[uri] = cast(str, store.read_run_document(uri)["created_at"])
            except (OSError, ValueError, LookupError, StoreError):
                warnings.append({"code": "discovery_record_unavailable", "run_uri": uri})
    except OSError as error:
        raise RunProjectionError("collection enumeration failed; existing index retained") from error
    unavailable = {warning["run_uri"] for warning in warnings}
    with connection(root, create=True) as conn, conn:
        conn.execute("UPDATE discovery_metadata SET revision=revision+1 WHERE singleton=1")
        revision = conn.execute("SELECT revision FROM discovery_metadata").fetchone()[0]
        for uri, created_at in found.items():
            conn.execute(
                "INSERT INTO discovery_runs VALUES(?,?,?,0) ON CONFLICT(run_uri) DO UPDATE SET "
                "created_at=excluded.created_at, revision=excluded.revision, pending=0 "
                "WHERE discovery_runs.revision <= ?",
                (uri, created_at, revision, watermark),
            )
        stale = conn.execute("SELECT run_uri FROM discovery_runs WHERE revision <= ? AND pending=0", (watermark,)).fetchall()
        for row in stale:
            if row[0] not in found and row[0] not in unavailable:
                conn.execute("DELETE FROM discovery_runs WHERE run_uri=? AND revision<=?", (row[0], watermark))
        conn.execute("UPDATE discovery_metadata SET refreshed=? WHERE singleton=1", (int(not warnings),))
    return tuple(warnings)
