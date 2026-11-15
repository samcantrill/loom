"""Explicit SQLite connection durability for storage owners.

Owners supply exclusive initialization/upgrade locking. This policy neither
certifies a filesystem nor permits multiple deployment owners on shared state.
Unconfigured stores keep their existing connection paths and defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Literal


_JOURNAL = {"wal": "WAL", "delete": "DELETE"}
_SYNC = {"full": ("FULL", 2), "extra": ("EXTRA", 3)}


class _ClosingConnection(sqlite3.Connection):
    """Store-owned transactional contexts must release their file descriptors."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


@dataclass(frozen=True, slots=True)
class SQLitePolicy:
    journal_mode: Literal["wal", "delete"]
    synchronous: Literal["full", "extra"]
    busy_timeout_ms: int = 30_000

    def __post_init__(self) -> None:
        if not isinstance(self.journal_mode, str) or self.journal_mode not in _JOURNAL:
            raise ValueError("SQLite journal_mode must be 'wal' or 'delete'")
        if not isinstance(self.synchronous, str) or self.synchronous not in _SYNC:
            raise ValueError("SQLite synchronous must be 'full' or 'extra'")
        if type(self.busy_timeout_ms) is not int or not 1 <= self.busy_timeout_ms <= 300_000:
            raise ValueError("SQLite busy_timeout_ms must be an integer in 1..300000")


def connect_existing(
    path: Path, *, policy: SQLitePolicy | None, isolation_level: str | None,
    factory: type[sqlite3.Connection] | None = None,
) -> sqlite3.Connection:
    """Open existing state without creating it or changing its journal mode.

    The caller closes the returned connection. Explicit policy uses a
    transaction context that also closes, unless an owner supplies its own
    connection subclass (which retains responsibility for closing it).
    """
    return _connect(path, policy=policy, isolation_level=isolation_level, initialize=False, factory=factory)


def initialize_database(
    path: Path, *, policy: SQLitePolicy | None, isolation_level: str | None,
    factory: type[sqlite3.Connection] | None = None,
) -> sqlite3.Connection:
    """Initialize under the owner's lock, or verify an already initialized file.

    Mode conversion of populated state belongs to a stopped-owner migration,
    never ordinary startup. The caller creates/qualifies the parent directory.
    """
    return _connect(path, policy=policy, isolation_level=isolation_level, initialize=True, factory=factory)


def _connect(path, *, policy, isolation_level, initialize, factory):
    if policy is not None and not isinstance(policy, SQLitePolicy):
        raise TypeError("sqlite_policy must be a SQLitePolicy")
    mode = "rwc" if initialize else "rw"
    conn = sqlite3.connect(
        Path(path).resolve().as_uri() + f"?mode={mode}",
        uri=True,
        timeout=5.0 if policy is None else policy.busy_timeout_ms / 1000,
        isolation_level=isolation_level,
        factory=factory or (_ClosingConnection if policy is not None else sqlite3.Connection),
    )
    try:
        if policy is not None:
            observed = conn.execute("PRAGMA journal_mode").fetchone()[0].lower()
            if observed != policy.journal_mode:
                populated = (
                    conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
                    or conn.execute("PRAGMA user_version").fetchone()[0]
                )
                if not initialize or populated:
                    raise sqlite3.OperationalError(
                        f"SQLite journal mode is {observed}, expected {policy.journal_mode}; "
                        "a stopped-owner migration is required"
                    )
                observed = conn.execute(
                    "PRAGMA journal_mode=" + _JOURNAL[policy.journal_mode]
                ).fetchone()[0].lower()
                if observed != policy.journal_mode:
                    raise sqlite3.OperationalError("SQLite did not establish the selected journal mode")
            sync_sql, sync_value = _SYNC[policy.synchronous]
            conn.execute("PRAGMA synchronous=" + sync_sql)
            conn.execute(f"PRAGMA busy_timeout={policy.busy_timeout_ms}")
            if (
                conn.execute("PRAGMA synchronous").fetchone()[0] != sync_value
                or conn.execute("PRAGMA busy_timeout").fetchone()[0] != policy.busy_timeout_ms
            ):
                raise sqlite3.OperationalError("SQLite did not establish the selected connection policy")
        return conn
    except BaseException:
        conn.close()
        raise
