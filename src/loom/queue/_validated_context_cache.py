"""Bounded disposable contexts, authorized by freshly captured retained bytes."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from loom.pipeline.stores.local_runs import LocalRunStore
from loom.serialization import stable_json_dumps

if TYPE_CHECKING:
    from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile
    from .local_daemon import LocalDaemonConfig


class _CapturedRunStore(LocalRunStore):
    """Keep each read's bytes only until validation and decoding have completed."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self._documents: dict[Path, bytes | None] = {}
        self._digests: dict[Path, str | None] = {}
        self._errors: dict[Path, OSError] = {}
        self._used: set[Path] = set()

    def _capture(self, path: Path) -> str | None:
        if path not in self._documents:
            try:
                content = super()._read_document_bytes(path)
            except FileNotFoundError:
                content = None
            except OSError as exc:
                # Re-raise through the original loader's error boundary below.
                self._errors[path] = exc
                content = None
            self._documents[path] = content
            self._digests[path] = (
                None if content is None else hashlib.sha256(content).hexdigest()
            )
        return self._digests[path]

    def _read_document_bytes(self, path: Path) -> bytes:
        self._capture(path)
        self._used.add(path)
        if path in self._errors:
            raise self._errors[path]
        content = self._documents[path]
        if content is None:
            raise FileNotFoundError(path)
        return content

    def dependencies(self) -> tuple[tuple[Path, str | None], ...]:
        return tuple((path, self._digests[path]) for path in sorted(self._used))


@dataclass(frozen=True, slots=True)
class _Entry[T]:
    dependencies: tuple[tuple[Path, str | None], ...]
    context: T


class ValidatedContextCache[T]:
    """Reuse checked contexts only while every consumed document is unchanged.

    IO and decoding never hold the cache lock. Concurrent loads can repeat work,
    but installed entries remain bounded. Entries keep digests and the needed
    context, never captured document bytes or decoded composition provenance.
    """

    def __init__(self, max_entries: int = 16) -> None:
        if max_entries < 1:
            raise ValueError("context cache capacity must be positive")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, _Entry[T]] = OrderedDict()
        self._lock = Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def load(
        self,
        config: LocalDaemonConfig,
        run_uri: str,
        *,
        slurm_profiles: Mapping[tuple[str, str], SlurmReadyStageProfile] | None,
        decode: Callable[[LocalRunStore], T],
    ) -> T:
        store = _CapturedRunStore(config.run_store_root)
        key = _authorization_key(config, run_uri, store, slurm_profiles)
        with self._lock:
            previous = self._entries.get(key)
        if previous is not None:
            # Capture once, then either reuse the validated context or decode
            # these same bytes. No second filesystem read can change the proof.
            current = tuple(
                (path, store._capture(path)) for path, _ in previous.dependencies
            )
            if not store._errors and current == previous.dependencies:
                with self._lock:
                    if self._entries.get(key) is previous:
                        self._entries.move_to_end(key)
                return previous.context
        context = decode(store)
        entry = _Entry(store.dependencies(), context)
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return context


def _authorization_key(
    config: LocalDaemonConfig,
    run_uri: str,
    store: LocalRunStore,
    slurm_profiles: Mapping[tuple[str, str], SlurmReadyStageProfile] | None,
) -> str:
    profiles = (
        {(item.profile_id, item.configuration_fingerprint): item
         for item in config.slurm_profiles}
        if slurm_profiles is None else slurm_profiles
    )
    launch = config.resident_worker_launch_profile
    value = {
        "root": str(config.run_store_root.resolve()),
        "run_uri": run_uri,
        "run_path": str(store.local_run_dir(run_uri).resolve()),
        "machine_id": config.machine_id,
        "local_binding": None if launch is None else launch.fingerprint,
        "allowed_targets": sorted({config.machine_id} | {
            rule.agent_id for rule in config.agent_policy.agents
        }),
        "slurm_profiles": [
            [list(identity), profile.configuration_fingerprint, profile.descriptor.to_dict()]
            for identity, profile in sorted(profiles.items())
        ],
    }
    return hashlib.sha256(stable_json_dumps(value).encode("utf-8")).hexdigest()
