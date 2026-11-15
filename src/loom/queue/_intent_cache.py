"""Bounded decoded intent reuse; current document bytes remain authoritative."""

from collections import OrderedDict
import hashlib
import os
from threading import Lock

from loom.pipeline.stores.local_runs import LocalRunStore


class ManagedIntentCache:
    """Coordinator-owned optimization, discarded on restart.

    No file-stat shortcut: every dependency is read and hashed on every lookup.
    Permissions and authority are checked by the normal owners after reuse.
    Entries are bounded by count and the total size of their source documents.
    """

    def __init__(self, *, max_entries=32, max_source_bytes=256 * 1024 * 1024):
        self._lock = Lock()
        self.max_entries = max_entries
        self.max_source_bytes = max_source_bytes
        self._entries = OrderedDict()
        self._source_bytes = 0

    @staticmethod
    def _documents(config, run_uri):
        from .errors import QueueServiceError

        store = LocalRunStore(config.run_store_root)
        root = store.local_run_dir(run_uri).resolve()
        if not root.is_relative_to(config.run_store_root.resolve()):
            raise QueueServiceError("run_uri is outside the configured local run store")
        store.open_run(run_uri)
        # Exact dependencies of load_managed_local_intent and its runtime loader.
        # Include optional documents so creation/deletion also invalidates reuse.
        names = (
            "run.json", "plan.json", "prepared_run.json",
            "config/managed_local_runtime.json", "config/composition_manifest.json",
        )
        fingerprint = []
        size = 0
        paths = [root / name for name in names]
        paths.append(store.local_config_path(run_uri, "resolved"))
        for path in paths:
            try:
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").digest()
                    length = os.fstat(stream.fileno()).st_size
            except FileNotFoundError:
                digest, length = None, 0
            fingerprint.append((str(path.resolve()), digest))
            size += length
        return tuple(fingerprint), size

    def load(self, config, run_uri, profiles):
        with self._lock:
            return self._load(config, run_uri, profiles)

    def _load(self, config, run_uri, profiles):
        from .local_daemon_execution import load_managed_local_intent, _validate_intent_bindings
        from .errors import QueueConflictError

        fingerprint, size = self._documents(config, run_uri)
        previous = self._entries.pop(run_uri, None)
        if previous is not None:
            self._source_bytes -= previous[2]
            if previous[0] == fingerprint:
                _validate_intent_bindings(config, previous[1], profiles)
                self._entries[run_uri] = previous
                self._source_bytes += previous[2]
                return previous[1]
        intent = load_managed_local_intent(config, run_uri, slurm_profiles=profiles)
        after, _ = self._documents(config, run_uri)
        if after != fingerprint:
            raise QueueConflictError("retained intent changed while loading")
        if size <= self.max_source_bytes:
            self._entries[run_uri] = (fingerprint, intent, size)
            self._source_bytes += size
            while (len(self._entries) > self.max_entries
                   or self._source_bytes > self.max_source_bytes):
                _, (_, _, discarded_size) = self._entries.popitem(last=False)
                self._source_bytes -= discarded_size
        return intent
