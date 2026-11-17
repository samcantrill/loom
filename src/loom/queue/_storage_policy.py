"""Protected role storage selection, separate from empirical filesystem qualification."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import socket
from typing import Literal

from loom._sqlite_policy import SQLitePolicy
from .errors import QueueConfigError, QueueServiceError


@dataclass(frozen=True, slots=True)
class StoragePolicy:
    owner_host: str
    sqlite: SQLitePolicy
    durable_files: Literal["best_effort", "strict"] = "strict"

    def __post_init__(self):
        if (
            not isinstance(self.owner_host, str) or not self.owner_host
            or any(c.isspace() or c in "/\\\0" for c in self.owner_host)
        ):
            raise ValueError("storage owner_host must name the physical owner host")
        if not isinstance(self.sqlite, SQLitePolicy):
            raise ValueError("storage sqlite must be a SQLitePolicy")
        if self.durable_files not in ("strict", "best_effort"):
            raise ValueError("storage durable_files must be strict or best_effort")

    def require_owner(self):
        # Use the kernel hostname, not a DNS alias or a network lookup.
        if socket.gethostname().casefold() != self.owner_host.casefold():
            raise QueueServiceError("storage is bound to a different physical owner host")

    def to_dict(self):
        return asdict(self)


def parse_storage_policy(value) -> StoragePolicy | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"owner_host", "sqlite", "durable_files"}:
        raise QueueConfigError("storage requires owner_host, sqlite and durable_files")
    sqlite = value["sqlite"]
    if (
        not isinstance(sqlite, Mapping)
        or not {"journal_mode", "synchronous"} <= set(sqlite)
        or set(sqlite) - {"journal_mode", "synchronous", "busy_timeout_ms"}
    ):
        raise QueueConfigError("storage sqlite fields are unsupported")
    try:
        return StoragePolicy(value["owner_host"], SQLitePolicy(**sqlite), value["durable_files"])
    except (TypeError, ValueError) as exc:
        raise QueueConfigError(str(exc)) from exc
