"""Private read-only SQLite admission shared by current storage owners."""

from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
import shutil
import sqlite3
import tempfile
from time import monotonic, sleep


@contextmanager
def inspect_sqlite_database(
    database: Path, *, timeout: float = 5.0
) -> Iterator[sqlite3.Connection]:
    """Read committed storage without changing the database or its sidecars.

    WAL reads can create sidecars or change shared-memory read marks even with
    mode=ro. Inspect a stable private copy of WAL storage instead, including its
    committed WAL frames. Interrupted rollback writes are recovered privately
    only when SQLite identifies an abandoned hot journal. Owners validate the
    schema here, then repeat admission in the original write transaction before
    mutation. Current writers perform ordinary SQLite recovery, not conversion.
    """
    database = Path(database).resolve()
    with ExitStack() as stack:
        try:
            with database.open("rb") as source:
                wal_mode = source.read(20)[18:20] == b"\x02\x02"
        except FileNotFoundError:
            wal_mode = False  # Let SQLite retain its missing-database error.
        if wal_mode:
            conn = _inspect_copy(stack, database, timeout=timeout)
        else:
            conn = stack.enter_context(closing(sqlite3.connect(
                database.as_uri() + "?mode=ro", uri=True, timeout=timeout,
            )))
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("BEGIN")
                conn.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchall()
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode != sqlite3.SQLITE_READONLY_ROLLBACK:
                    raise
                conn.close()
                conn = _inspect_copy(stack, database, timeout=timeout)
        yield conn


def _inspect_copy(
    stack: ExitStack, database: Path, *, timeout: float
) -> sqlite3.Connection:
    # Do not copy the shared-memory lock/index file: SQLite reconstructs it from
    # the copied WAL. Fingerprints ensure main pages and durable sidecars belong
    # to one stable snapshot, including when a concurrent writer checkpoints.
    deadline = monotonic() + timeout
    paths = (database, Path(str(database) + "-wal"), Path(str(database) + "-journal"))
    directory = Path(stack.enter_context(tempfile.TemporaryDirectory(
        prefix="loom-sqlite-inspection-",
    )))
    while True:
        for path in paths:
            (directory / path.name).unlink(missing_ok=True)
        before = _fingerprints(paths)
        try:
            for path, fingerprint in zip(paths, before, strict=True):
                if fingerprint is not None:
                    shutil.copyfile(path, directory / path.name)
        except FileNotFoundError:
            pass  # A concurrent checkpoint may remove a sidecar; compare below.
        after = _fingerprints(paths)
        if before == after and before[0] is not None:
            conn = stack.enter_context(closing(sqlite3.connect(
                directory / database.name, timeout=timeout,
            )))
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            return conn
        if monotonic() >= deadline:
            raise sqlite3.OperationalError("SQLite storage changed during inspection")
        sleep(min(0.01, max(0.0, deadline - monotonic())))


def _fingerprints(paths: tuple[Path, ...]) -> tuple[tuple[int, ...] | None, ...]:
    values: list[tuple[int, ...] | None] = []
    for path in paths:
        try:
            info = path.stat()
        except FileNotFoundError:
            values.append(None)
        else:
            values.append((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
    return tuple(values)
