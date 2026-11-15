"""Bounded worker projections; freshly read evidence bytes remain authoritative."""

from collections import OrderedDict
import hashlib
import json
from pathlib import Path
from threading import Lock

from loom._preparation_report import _decoded_mapping, _regular_bytes
from loom.queue.errors import QueueConflictError
from loom.serialization import stable_json_bytes


class WorkerContractCache:
    """Keep only small validated projections, never whole composed reports."""

    def __init__(self, max_entries=32, max_bytes=8 * 1024 * 1024):
        self._lock = Lock()
        self._entries = OrderedDict()
        self._size = 0
        self.max_entries = max_entries
        self.max_bytes = max_bytes

    @staticmethod
    def fingerprint(path, entry, resolved):
        primary = _regular_bytes(path)
        report = _decoded_mapping(primary)
        documents = [(str(path), hashlib.sha256(primary).digest())]
        for name in ("composition", "requested_composition"):
            if name not in report:
                continue
            composition = report[name]
            if not isinstance(composition, dict):
                raise QueueConflictError("preparation composition evidence must be a mapping")
            reference = composition.get("evidence_ref")
            uri = reference.get("uri") if isinstance(reference, dict) else None
            if (not isinstance(uri, str) or not uri or Path(uri).name != uri
                    or uri in {".", ".."} or any(char in uri for char in "\\:\x00")):
                raise QueueConflictError("preparation composition reference must be a contained filename")
            companion = path.parent / uri
            if any(name == str(companion) for name, _ in documents):
                continue
            documents.append((str(companion), hashlib.sha256(_regular_bytes(companion)).digest()))
        # Namespace/reference and the complete ordered configuration are part
        # of the validation boundary, including absence of the configuration.
        return (stable_json_bytes(entry), tuple(documents),
                None if resolved is None else hashlib.sha256(resolved.encode()).digest())

    def load(self, key, fingerprint, loader):
        before = fingerprint()
        with self._lock:
            cached = self._entries.pop(key, None)
            if cached is not None:
                self._size -= len(cached[1])
                if cached[0] == before:
                    self._entries[key] = cached
                    self._size += len(cached[1])
                    # Every caller owns a fresh mutable projection.
                    return json.loads(cached[1])
        projection = loader()
        if fingerprint() != before:
            raise QueueConflictError("retained worker contract evidence changed while loading")
        encoded = stable_json_bytes(projection)
        if len(encoded) <= self.max_bytes:
            with self._lock:
                prior = self._entries.pop(key, None)
                if prior is not None:
                    self._size -= len(prior[1])
                self._entries[key] = (before, encoded)
                self._size += len(encoded)
                while len(self._entries) > self.max_entries or self._size > self.max_bytes:
                    _, (_, removed) = self._entries.popitem(last=False)
                    self._size -= len(removed)
        return projection
