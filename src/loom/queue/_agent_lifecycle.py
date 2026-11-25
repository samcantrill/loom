"""Bounded preparation for negotiated agent lifecycle exchanges."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from functools import partial
import hashlib
import json
import sqlite3
from threading import Lock
from typing import Any, TYPE_CHECKING

from loom.serialization import PlainData

from .agent_sessions import AgentProviderReleaseProof, AgentSession, AgentSessionService, AgentSessionView
from .errors import QueueServiceError
from ._phase_timing import reported_phases

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon, LocalDaemonPrincipal

LIFECYCLE_OPERATIONS = frozenset({"accept", "start_permit", "started", "release"})


class LifecyclePending(Exception):
    """Repeat the same authenticated request to advance its prepared transition."""


@dataclass
class _Work:
    pool: ThreadPoolExecutor
    future: Future[Callable[[bool], Any]]


class LifecyclePreparations:
    """The durable assignment owns effects. These bounded workers own disposable proofs."""

    def __init__(self) -> None:
        self._authority = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-agent-authority")
        self._storage = ThreadPoolExecutor(max_workers=2, thread_name_prefix="loom-agent-publication")
        self._lock = Lock()
        self._work: dict[tuple, _Work] = {}
        self._closed = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
        for pool in (self._authority, self._storage):
            pool.shutdown(wait=True)
        with self._lock:
            self._work.clear()

    def view(self, daemon: LocalDaemon, principal: LocalDaemonPrincipal, operation: str, payload: Mapping[str, object]):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                           allow_nan=False).encode()).digest()
        key = (principal, daemon._epoch, daemon._scheduling_epoch, operation, digest)
        return _LifecycleView(daemon, principal, partial(self._advance, daemon, key, operation))

    def _advance(self, daemon, key, operation, assignment_id, prepare):
        pool = self._storage if operation in {"accept", "release"} else self._authority
        guards = daemon._publication_guards

        def observe():
            with reported_phases("agent_lifecycle_preparation", operation_id=assignment_id) as timings:
                timings.related["operation"] = operation
                with guards.try_hold(assignment_id) as held:
                    if not held:
                        raise LifecyclePending()
                    return prepare()

        with self._lock:
            if self._closed:
                raise QueueServiceError("lifecycle preparation is stopping")
            work = self._work.get(key)
            if work is None:
                if sum(item.pool is pool and not item.future.done() for item in self._work.values()) >= 2:
                    raise LifecyclePending()
                # A disconnected caller can leave a completed preparation behind.
                # Eviction only requires a fresh observation of the durable effect.
                if len(self._work) >= 32:
                    oldest = next(k for k, item in self._work.items() if item.future.done())
                    del self._work[oldest]
                self._work[key] = _Work(pool, pool.submit(copy_context().run, observe))
                raise LifecyclePending()
            if not work.future.done():
                raise LifecyclePending()

        # The reserved HTTP handler never waits for another assignment action
        # or a SQLite writer. A later poll uses the same completed preparation.
        with guards.try_hold(assignment_id) as held:
            if not held:
                raise LifecyclePending()
            with self._lock:
                if self._work.get(key) is not work:
                    raise LifecyclePending()
                del self._work[key]
            finish = work.future.result()
            if (daemon._epoch, daemon._scheduling_epoch) != key[1:3]:
                raise LifecyclePending()
            try:
                return finish(False)
            except sqlite3.OperationalError as exc:
                if getattr(exc, "sqlite_errorcode", 0) & 255 != sqlite3.SQLITE_BUSY:
                    raise
                # The final transaction rolled back. A retry can reconstruct its
                # proof from durable authority even if a concurrent request won.
                with self._lock:
                    if not self._closed and len(self._work) < 32:
                        self._work.setdefault(key, work)
                raise LifecyclePending() from exc


class _LifecycleView(AgentSessionView):
    def __init__(self, daemon, principal, advance):
        super().__init__(daemon, principal)
        self._service = AgentSessionService(daemon, principal)
        self._advance = advance

    def accept_assignment(self, session_id: str, assignment_id: str, *, request_digest: str) -> Mapping[str, PlainData]:
        return self._advance(assignment_id, partial(self._service.prepare_accept, session_id, assignment_id,
                                                   request_digest=request_digest))

    def start_permit(self, session_id: str, assignment_id: str, *, fence: str) -> bool:
        return self._advance(assignment_id, partial(self._service.prepare_start_permit, session_id, assignment_id, fence=fence))

    def confirm_started(self, session_id: str, assignment_id: str, *, fence: str, process_execution_id: str) -> Mapping[str, PlainData]:
        return self._advance(assignment_id, partial(self._service.prepare_started, session_id, assignment_id,
                                                   fence=fence, process_execution_id=process_execution_id))

    def release_assignment(self, session_id: str, assignment_id: str, *, fence: str, availability_revision: str,
                           provider_release_proof: AgentProviderReleaseProof) -> AgentSession:
        return self._advance(assignment_id, partial(self._service.prepare_release, session_id, assignment_id,
                                                   fence=fence, availability_revision=availability_revision,
                                                   provider_release_proof=provider_release_proof))
