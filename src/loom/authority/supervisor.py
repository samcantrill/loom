"""Explicit local authority supervisor lifecycle helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TextIO, cast

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityDeploymentProfile,
    AuthorityProtocolReadiness,
    AuthorityReadinessState,
    AuthorityReference,
    AuthorityRegistryError,
    AuthorityRegistryRecord,
    AuthorityRegistryValidationResult,
    AuthorityRegistryValidationStatus,
    AuthorityServiceHealthState,
    read_authority_registry_record,
    validate_authority_registry,
    write_authority_registry_record,
)
from loom.serialization import DeserializationError, PlainData, json_loads
from loom.serialization.errors import PlainDataError
from loom.timestamps import utc_timestamp

from ._repository import (
    AuthorityRepository,
    AuthorityRepositoryCompatibilityError,
    AuthorityRepositoryError,
    AuthorityRepositoryIdentity,
    generate_service_generation,
)
from ._service_locks import (
    AuthorityLifecycleLocks,
    AuthorityServiceLockError,
    AuthorityServiceLocks,
)


AUTHORITY_SUPERVISOR_STATE_FILE = "supervisor.json"
AUTHORITY_SUPERVISOR_LOG_FILE = "supervisor.log"
AUTHORITY_SUPERVISOR_WORKSPACE_DEFAULT_DIR = ".loom/authority/service"
DEFAULT_AUTHORITY_SUPERVISOR_HOST = "127.0.0.1"
DEFAULT_AUTHORITY_SUPERVISOR_PORT = 8765
DEFAULT_AUTHORITY_SUPERVISOR_TIMEOUT_SECONDS = 10.0


class AuthoritySupervisorError(RuntimeError):
    """Raised when an explicit authority supervisor lifecycle command fails."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "authority_supervisor.error",
        context: Mapping[str, PlainData] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = {} if context is None else dict(context)


class AuthoritySupervisorProcessState(StrEnum):
    """Observed local supervisor process state."""

    RUNNING = "running"
    STOPPED = "stopped"
    STALE = "stale"
    UNKNOWN = "unknown"


class AuthoritySupervisorRepositoryState(StrEnum):
    """Observed private repository compatibility state."""

    READY = "ready"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"
    ERROR = "error"


class AuthoritySupervisorReadiness(StrEnum):
    """Observed service readiness state."""

    READY = "ready"
    UNREADY = "unready"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AuthoritySupervisorState:
    """Persisted local supervisor process facts."""

    pid: int
    endpoint: str
    state_dir: Path
    workspace_root: Path
    workspace_id: str
    service_generation: str
    host: str
    port: int
    started_at: str
    updated_at: str
    process_start_ticks: str | None = None
    process_boot_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "pid", _positive_int(self.pid, "pid"))
        object.__setattr__(self, "endpoint", _non_empty(self.endpoint, "endpoint"))
        object.__setattr__(self, "state_dir", Path(self.state_dir))
        object.__setattr__(self, "workspace_root", Path(self.workspace_root))
        object.__setattr__(
            self, "workspace_id", _non_empty(self.workspace_id, "workspace_id")
        )
        object.__setattr__(
            self,
            "service_generation",
            _non_empty(self.service_generation, "service_generation"),
        )
        object.__setattr__(self, "host", _non_empty(self.host, "host"))
        object.__setattr__(self, "port", _port(self.port))
        object.__setattr__(
            self, "started_at", _non_empty(self.started_at, "started_at")
        )
        object.__setattr__(
            self, "updated_at", _non_empty(self.updated_at, "updated_at")
        )
        if self.process_start_ticks is not None:
            object.__setattr__(
                self,
                "process_start_ticks",
                _non_empty(self.process_start_ticks, "process_start_ticks"),
            )
        if self.process_boot_id is not None:
            object.__setattr__(
                self,
                "process_boot_id",
                _non_empty(self.process_boot_id, "process_boot_id"),
            )

    def to_dict(self) -> dict[str, PlainData]:
        """Return persisted process state as plain data."""

        return {
            "pid": self.pid,
            "endpoint": self.endpoint,
            "state_dir": str(self.state_dir),
            "workspace_root": str(self.workspace_root),
            "workspace_id": self.workspace_id,
            "service_generation": self.service_generation,
            "host": self.host,
            "port": self.port,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "process_start_ticks": self.process_start_ticks,
            "process_boot_id": self.process_boot_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthoritySupervisorState":
        """Parse persisted process state."""

        mapping = _mapping(data, "AuthoritySupervisorState")
        _reject_unknown(
            mapping,
            {
                "pid",
                "endpoint",
                "state_dir",
                "workspace_root",
                "workspace_id",
                "service_generation",
                "host",
                "port",
                "started_at",
                "updated_at",
                "process_start_ticks",
                "process_boot_id",
            },
            "AuthoritySupervisorState",
        )
        return cls(
            pid=_positive_int(_required(mapping, "pid"), "pid"),
            endpoint=_non_empty(_required(mapping, "endpoint"), "endpoint"),
            state_dir=Path(_non_empty(_required(mapping, "state_dir"), "state_dir")),
            workspace_root=Path(
                _non_empty(_required(mapping, "workspace_root"), "workspace_root")
            ),
            workspace_id=_non_empty(_required(mapping, "workspace_id"), "workspace_id"),
            service_generation=_non_empty(
                _required(mapping, "service_generation"),
                "service_generation",
            ),
            host=_non_empty(_required(mapping, "host"), "host"),
            port=_port(_required(mapping, "port")),
            started_at=_non_empty(_required(mapping, "started_at"), "started_at"),
            updated_at=_non_empty(_required(mapping, "updated_at"), "updated_at"),
            process_start_ticks=_optional_non_empty(mapping, "process_start_ticks"),
            process_boot_id=_optional_non_empty(mapping, "process_boot_id"),
        )


@dataclass(frozen=True, slots=True)
class AuthoritySupervisorCommandResult:
    """CLI-facing authority supervisor command result."""

    command: str
    ok: bool
    state_dir: Path | None = None
    workspace_root: Path | None = None
    workspace_id: str | None = None
    endpoint: str | None = None
    pid: int | None = None
    process_state: AuthoritySupervisorProcessState = (
        AuthoritySupervisorProcessState.UNKNOWN
    )
    readiness: AuthoritySupervisorReadiness = AuthoritySupervisorReadiness.UNKNOWN
    repository_state: AuthoritySupervisorRepositoryState = (
        AuthoritySupervisorRepositoryState.ERROR
    )
    registry_status: AuthorityRegistryValidationStatus | None = None
    service_generation: str | None = None
    registry_generation: str | None = None
    generation_matches: bool | None = None
    diagnostics: tuple[Mapping[str, PlainData], ...] = ()

    def to_dict(self) -> dict[str, PlainData]:
        """Return command result as plain data."""

        return {
            "command": self.command,
            "ok": self.ok,
            "state_dir": None if self.state_dir is None else str(self.state_dir),
            "workspace_root": None
            if self.workspace_root is None
            else str(self.workspace_root),
            "workspace_id": self.workspace_id,
            "endpoint": self.endpoint,
            "pid": self.pid,
            "process_state": self.process_state.value,
            "readiness": self.readiness.value,
            "repository_state": self.repository_state.value,
            "registry_status": None
            if self.registry_status is None
            else self.registry_status.value,
            "service_generation": self.service_generation,
            "registry_generation": self.registry_generation,
            "generation_matches": self.generation_matches,
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


def start_authority_supervisor(
    *,
    state_dir: str | Path | None = None,
    use_workspace_default: bool = False,
    workspace_root: str | Path = ".",
    workspace_id: str | None = None,
    host: str = DEFAULT_AUTHORITY_SUPERVISOR_HOST,
    port: int = DEFAULT_AUTHORITY_SUPERVISOR_PORT,
    timeout_seconds: float = DEFAULT_AUTHORITY_SUPERVISOR_TIMEOUT_SECONDS,
    service_generation: str | None = None,
) -> AuthoritySupervisorCommandResult:
    """Start the local repository-backed FastAPI authority service."""

    resolved_workspace_root = Path(workspace_root).resolve()
    resolved_workspace_id = _workspace_id(workspace_id, resolved_workspace_root)
    resolved_state_dir = _resolve_state_dir_option(
        state_dir=state_dir,
        workspace_root=resolved_workspace_root,
        use_workspace_default=use_workspace_default,
        command="start",
    )
    resolved_port = _port(port)
    try:
        with AuthorityLifecycleLocks.acquire(
            state_dir=resolved_state_dir,
            workspace_root=resolved_workspace_root,
        ):
            return _start_authority_supervisor_locked(
                state_dir=resolved_state_dir,
                workspace_root=resolved_workspace_root,
                workspace_id=resolved_workspace_id,
                host=host,
                port=resolved_port,
                timeout_seconds=timeout_seconds,
                service_generation=service_generation,
            )
    except AuthorityServiceLockError as exc:
        raise AuthoritySupervisorError(
            "authority supervisor lifecycle command is already in progress",
            code="authority_supervisor.lifecycle_locked",
            context={
                "state_dir": str(resolved_state_dir),
                "workspace_root": str(resolved_workspace_root),
            },
        ) from exc


def _start_authority_supervisor_locked(
    *,
    state_dir: Path,
    workspace_root: Path,
    workspace_id: str,
    host: str,
    port: int,
    timeout_seconds: float,
    service_generation: str | None,
    rotate_generation: bool = False,
) -> AuthoritySupervisorCommandResult:
    """Start one service while the caller serializes its state root and workspace."""

    resolved_state_dir = state_dir
    resolved_workspace_root = workspace_root
    resolved_workspace_id = workspace_id
    resolved_port = port
    existing = _read_state_if_present(resolved_state_dir)
    if existing is not None and _state_process_state(existing) is (
        AuthoritySupervisorProcessState.RUNNING
    ):
        raise AuthoritySupervisorError(
            "authority supervisor is already running",
            code="authority_supervisor.already_running",
            context=existing.to_dict(),
        )
    _reject_second_workspace_authority(
        workspace_root=resolved_workspace_root,
        workspace_id=resolved_workspace_id,
        state_dir=resolved_state_dir,
    )

    endpoint = _endpoint(host, resolved_port)
    resolved_workspace_root.mkdir(parents=True, exist_ok=True)
    try:
        service_locks = AuthorityServiceLocks.acquire(
            state_dir=resolved_state_dir,
            workspace_root=resolved_workspace_root,
        )
    except AuthorityServiceLockError as exc:
        raise AuthoritySupervisorError(
            "authority service root is already owned",
            code="authority_supervisor.service_owned",
            context={
                "state_dir": str(resolved_state_dir),
                "workspace_root": str(resolved_workspace_root),
            },
        ) from exc

    process: subprocess.Popen[bytes] | None = None
    try:
        repository = AuthorityRepository(resolved_state_dir)
        identity = (
            rotate_authority_repository_generation(resolved_state_dir)
            if rotate_generation
            else repository.initialize(service_generation=service_generation)
        )
        log_handle = _open_log(resolved_state_dir)
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "loom.authority._server",
                    "--state-dir",
                    str(resolved_state_dir),
                    "--workspace-root",
                    str(resolved_workspace_root),
                    "--workspace-id",
                    resolved_workspace_id,
                    "--host",
                    host,
                    "--port",
                    str(resolved_port),
                    "--state-lock-fd",
                    str(service_locks.state_lock_fd),
                    "--workspace-lock-fd",
                    str(service_locks.workspace_lock_fd),
                ],
                cwd=str(resolved_workspace_root),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                pass_fds=(
                    service_locks.state_lock_fd,
                    service_locks.workspace_lock_fd,
                ),
            )
        except OSError as exc:
            raise AuthoritySupervisorError(
                f"failed to launch authority supervisor: {exc}",
                code="authority_supervisor.launch_failed",
                context={
                    "state_dir": str(resolved_state_dir),
                    "workspace_root": str(resolved_workspace_root),
                    "endpoint": endpoint,
                },
            ) from exc
        finally:
            log_handle.close()

        assert process is not None
        try:
            readiness = _wait_until_ready(
                endpoint,
                timeout_seconds=timeout_seconds,
                process=process,
            )
        except Exception as exc:
            _cleanup_started_process(process)
            raise AuthoritySupervisorError(
                f"authority supervisor did not become ready: {exc}",
                code="authority_supervisor.not_ready",
                context={"endpoint": endpoint, "state_dir": str(resolved_state_dir)},
            ) from exc

        now = utc_timestamp()
        state = AuthoritySupervisorState(
            pid=process.pid,
            endpoint=endpoint,
            state_dir=resolved_state_dir,
            workspace_root=resolved_workspace_root,
            workspace_id=resolved_workspace_id,
            service_generation=identity.service_generation,
            host=host,
            port=resolved_port,
            started_at=now,
            updated_at=now,
            process_start_ticks=_captured_process_start_ticks(process.pid),
            process_boot_id=_process_boot_id(),
        )
        try:
            _write_state(state)
            registry_record = _registry_record_from_readiness(
                state=state,
                identity=identity,
                readiness=readiness,
                health_state=AuthorityServiceHealthState.READY,
            )
            write_authority_registry_record(resolved_workspace_root, registry_record)
        except Exception as exc:
            _cleanup_started_process(process)
            raise AuthoritySupervisorError(
                f"failed publishing authority supervisor state: {exc}",
                code="authority_supervisor.publish_failed",
                context={
                    "endpoint": endpoint,
                    "state_dir": str(resolved_state_dir),
                    "workspace_root": str(resolved_workspace_root),
                },
            ) from exc
        return _result_from_observations(
            command="start",
            state=state,
            identity=identity,
            registry=validate_authority_registry(
                resolved_workspace_root,
                expected_workspace_id=resolved_workspace_id,
                expected_generation=identity.service_generation,
            ),
            readiness=AuthoritySupervisorReadiness.READY,
            process_state=AuthoritySupervisorProcessState.RUNNING,
            diagnostics=(
                _diagnostic(
                    "authority_supervisor.started",
                    "authority supervisor started and registry was updated",
                    severity="info",
                ),
            ),
        )
    finally:
        # The child inherited these open file descriptions and therefore retains
        # ownership after this launcher returns or is itself interrupted.
        service_locks.close()


def inspect_authority_supervisor(
    *,
    state_dir: str | Path | None = None,
    use_workspace_default: bool = False,
    workspace_root: str | Path = ".",
    workspace_id: str | None = None,
    command: str = "status",
) -> AuthoritySupervisorCommandResult:
    """Inspect local authority supervisor process and registry state."""

    resolved_workspace_root = Path(workspace_root).resolve()
    resolved_workspace_id = _workspace_id(workspace_id, resolved_workspace_root)
    state = _resolve_state(
        state_dir=state_dir,
        use_workspace_default=use_workspace_default,
        workspace_root=resolved_workspace_root,
    )
    if state is None:
        registry = validate_authority_registry(
            resolved_workspace_root,
            expected_workspace_id=resolved_workspace_id,
        )
        return AuthoritySupervisorCommandResult(
            command=command,
            ok=False,
            workspace_root=resolved_workspace_root,
            workspace_id=resolved_workspace_id,
            process_state=AuthoritySupervisorProcessState.UNKNOWN,
            readiness=AuthoritySupervisorReadiness.UNKNOWN,
            repository_state=AuthoritySupervisorRepositoryState.MISSING,
            registry_status=registry.status,
            diagnostics=(
                _diagnostic(
                    "authority_supervisor.state_missing",
                    "authority supervisor state is missing",
                    detail={"workspace_root": str(resolved_workspace_root)},
                ),
                *_registry_diagnostics(registry),
            ),
        )

    identity, repository_state, repository_diagnostics = _read_identity(state.state_dir)
    process_state = _state_process_state(state)
    readiness = _readiness_for_state(state, process_state=process_state)
    expected_generation = identity.service_generation if identity is not None else None
    registry = validate_authority_registry(
        state.workspace_root,
        expected_workspace_id=state.workspace_id,
        expected_generation=expected_generation,
    )
    ok = (
        process_state is AuthoritySupervisorProcessState.RUNNING
        and readiness is AuthoritySupervisorReadiness.READY
        and repository_state is AuthoritySupervisorRepositoryState.READY
        and registry.status is AuthorityRegistryValidationStatus.VALID
    )
    return _result_from_observations(
        command=command,
        state=state,
        identity=identity,
        registry=registry,
        readiness=readiness,
        process_state=process_state,
        repository_state=repository_state,
        diagnostics=(
            *repository_diagnostics,
            *_registry_diagnostics(registry),
        ),
        ok=ok,
    )


def stop_authority_supervisor(
    *,
    state_dir: str | Path | None = None,
    use_workspace_default: bool = False,
    workspace_root: str | Path = ".",
    workspace_id: str | None = None,
    timeout_seconds: float = 5.0,
) -> AuthoritySupervisorCommandResult:
    """Stop the local authority supervisor process if it is running."""

    resolved_workspace_root = Path(workspace_root).resolve()
    resolved_workspace_id = _workspace_id(workspace_id, resolved_workspace_root)
    requested_state_dir = _optional_state_dir(
        state_dir=state_dir,
        workspace_root=resolved_workspace_root,
        use_workspace_default=use_workspace_default,
    )
    try:
        with AuthorityLifecycleLocks.acquire(
            state_dir=requested_state_dir,
            workspace_root=resolved_workspace_root,
        ):
            return _stop_authority_supervisor_locked(
                state_dir=state_dir,
                use_workspace_default=use_workspace_default,
                workspace_root=resolved_workspace_root,
                workspace_id=resolved_workspace_id,
                timeout_seconds=timeout_seconds,
            )
    except AuthorityServiceLockError as exc:
        raise AuthoritySupervisorError(
            "authority supervisor lifecycle command is already in progress",
            code="authority_supervisor.lifecycle_locked",
            context={"workspace_root": str(resolved_workspace_root)},
        ) from exc


def _stop_authority_supervisor_locked(
    *,
    state_dir: str | Path | None,
    use_workspace_default: bool,
    workspace_root: Path,
    workspace_id: str,
    timeout_seconds: float,
) -> AuthoritySupervisorCommandResult:
    """Stop one service while the caller serializes its state root and workspace."""

    state = _resolve_state(
        state_dir=state_dir,
        use_workspace_default=use_workspace_default,
        workspace_root=workspace_root,
    )
    if state is None:
        try:
            AuthorityServiceLocks.ensure_unowned(
                state_dir=_optional_state_dir(
                    state_dir=state_dir,
                    use_workspace_default=use_workspace_default,
                    workspace_root=workspace_root,
                ),
                workspace_root=workspace_root,
            )
        except AuthorityServiceLockError:
            return AuthoritySupervisorCommandResult(
                command="stop",
                ok=False,
                workspace_root=workspace_root,
                workspace_id=workspace_id,
                process_state=AuthoritySupervisorProcessState.UNKNOWN,
                diagnostics=(
                    _diagnostic(
                        "authority_supervisor.bootstrap_pending",
                        "authority service is owned but has not published its identity",
                        severity="warning",
                    ),
                ),
            )
        return AuthoritySupervisorCommandResult(
            command="stop",
            ok=True,
            workspace_root=workspace_root,
            workspace_id=workspace_id,
            process_state=AuthoritySupervisorProcessState.STOPPED,
            readiness=AuthoritySupervisorReadiness.UNAVAILABLE,
            repository_state=AuthoritySupervisorRepositoryState.MISSING,
            registry_status=validate_authority_registry(workspace_root).status,
            diagnostics=(
                _diagnostic(
                    "authority_supervisor.already_stopped",
                    "authority supervisor state is missing",
                    severity="warning",
                ),
            ),
        )

    stopped = _terminate_process(state, timeout_seconds=timeout_seconds)
    ownership_changed = False
    service_locks: AuthorityServiceLocks | None = None
    if stopped:
        try:
            service_locks = AuthorityServiceLocks.acquire(
                state_dir=state.state_dir, workspace_root=state.workspace_root
            )
        except AuthorityServiceLockError:
            # A replacement bootstrap owns these files after the recorded exit.
            ownership_changed = True
            stopped = False
    if not stopped:
        identity, repository_state, repository_diagnostics = _read_identity(
            state.state_dir
        )
        registry = validate_authority_registry(
            state.workspace_root,
            expected_workspace_id=state.workspace_id,
            expected_generation=identity.service_generation
            if identity is not None
            else None,
        )
        return _result_from_observations(
            command="stop",
            state=state,
            identity=identity,
            registry=registry,
            readiness=AuthoritySupervisorReadiness.UNAVAILABLE,
            process_state=AuthoritySupervisorProcessState.UNKNOWN,
            repository_state=repository_state,
            diagnostics=(
                _diagnostic(
                    "authority_supervisor.stop_ownership_unverified"
                    if ownership_changed
                    else "authority_supervisor.stop_identity_unverified",
                    "authority service root is owned after the recorded process exited"
                    if ownership_changed
                    else "authority supervisor identity cannot safely authorize a signal",
                    severity="warning",
                ),
                *repository_diagnostics,
                *_registry_diagnostics(registry),
            ),
            ok=False,
        )

    assert service_locks is not None
    try:
        return _record_stopped_supervisor(state)
    finally:
        service_locks.close()


def _record_stopped_supervisor(
    state: AuthoritySupervisorState,
) -> AuthoritySupervisorCommandResult:
    """Publish exit while root ownership excludes a replacement bootstrap."""

    _mark_registry_unavailable(state)
    updated_state = AuthoritySupervisorState(
        pid=state.pid,
        endpoint=state.endpoint,
        state_dir=state.state_dir,
        workspace_root=state.workspace_root,
        workspace_id=state.workspace_id,
        service_generation=state.service_generation,
        host=state.host,
        port=state.port,
        started_at=state.started_at,
        updated_at=utc_timestamp(),
        process_start_ticks=state.process_start_ticks,
        process_boot_id=state.process_boot_id,
    )
    _write_state(updated_state)
    identity, repository_state, repository_diagnostics = _read_identity(state.state_dir)
    registry = validate_authority_registry(
        state.workspace_root,
        expected_workspace_id=state.workspace_id,
        expected_generation=identity.service_generation
        if identity is not None
        else None,
    )
    return _result_from_observations(
        command="stop",
        state=updated_state,
        identity=identity,
        registry=registry,
        readiness=AuthoritySupervisorReadiness.UNAVAILABLE,
        process_state=AuthoritySupervisorProcessState.STOPPED,
        repository_state=repository_state,
        diagnostics=(
            _diagnostic(
                "authority_supervisor.stopped",
                "authority supervisor stopped",
                severity="info",
            ),
            *repository_diagnostics,
            *_registry_diagnostics(registry),
        ),
        ok=True,
    )


def restart_authority_supervisor(
    *,
    state_dir: str | Path | None = None,
    use_workspace_default: bool = False,
    workspace_root: str | Path = ".",
    workspace_id: str | None = None,
    host: str = DEFAULT_AUTHORITY_SUPERVISOR_HOST,
    port: int = DEFAULT_AUTHORITY_SUPERVISOR_PORT,
    timeout_seconds: float = DEFAULT_AUTHORITY_SUPERVISOR_TIMEOUT_SECONDS,
) -> AuthoritySupervisorCommandResult:
    """Restart the local supervisor with a new service generation."""

    resolved_workspace_root = Path(workspace_root).resolve()
    resolved_state_dir = _resolve_state_dir_option(
        state_dir=state_dir,
        workspace_root=resolved_workspace_root,
        use_workspace_default=use_workspace_default,
        command="restart",
    )
    resolved_workspace_id = _workspace_id(workspace_id, resolved_workspace_root)
    resolved_port = _port(port)
    try:
        with AuthorityLifecycleLocks.acquire(
            state_dir=resolved_state_dir,
            workspace_root=resolved_workspace_root,
        ):
            stopped = _stop_authority_supervisor_locked(
                state_dir=resolved_state_dir,
                use_workspace_default=False,
                workspace_root=resolved_workspace_root,
                workspace_id=resolved_workspace_id,
                timeout_seconds=5.0,
            )
            if not stopped.ok:
                raise AuthoritySupervisorError(
                    "authority supervisor could not be stopped safely for restart",
                    code="authority_supervisor.restart_stop_unverified",
                    context=stopped.to_dict(),
                )
            result = _start_authority_supervisor_locked(
                state_dir=resolved_state_dir,
                workspace_root=resolved_workspace_root,
                workspace_id=resolved_workspace_id,
                host=host,
                port=resolved_port,
                timeout_seconds=timeout_seconds,
                service_generation=None,
                rotate_generation=True,
            )
    except AuthorityServiceLockError as exc:
        raise AuthoritySupervisorError(
            "authority supervisor lifecycle command is already in progress",
            code="authority_supervisor.lifecycle_locked",
            context={
                "state_dir": str(resolved_state_dir),
                "workspace_root": str(resolved_workspace_root),
            },
        ) from exc
    return AuthoritySupervisorCommandResult(
        command="restart",
        ok=result.ok,
        state_dir=result.state_dir,
        workspace_root=result.workspace_root,
        workspace_id=result.workspace_id,
        endpoint=result.endpoint,
        pid=result.pid,
        process_state=AuthoritySupervisorProcessState.RUNNING,
        readiness=AuthoritySupervisorReadiness.READY,
        repository_state=AuthoritySupervisorRepositoryState.READY,
        registry_status=AuthorityRegistryValidationStatus.VALID,
        service_generation=result.service_generation,
        registry_generation=result.registry_generation,
        generation_matches=result.generation_matches,
        diagnostics=(
            _diagnostic(
                "authority_supervisor.restarted",
                "authority supervisor restarted with a new service generation",
                severity="info",
            ),
            *result.diagnostics,
        ),
    )


def rotate_authority_repository_generation(
    state_dir: str | Path,
    *,
    service_generation: str | None = None,
) -> AuthorityRepositoryIdentity:
    """Rotate a private authority repository service generation."""

    repository = AuthorityRepository(state_dir)
    generation = service_generation or generate_service_generation()
    now = utc_timestamp()
    with repository.transaction() as conn:
        conn.execute(
            """
            INSERT INTO repository_metadata(key, value)
            VALUES ('service_generation', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (generation,),
        )
        conn.execute(
            """
            INSERT INTO repository_metadata(key, value)
            VALUES ('updated_at', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (now,),
        )
    return repository.read_identity()


def supervisor_state_path(state_dir: str | Path) -> Path:
    """Return the local supervisor state-file path for a service state dir."""

    return Path(state_dir) / AUTHORITY_SUPERVISOR_STATE_FILE


def workspace_default_supervisor_state_dir(workspace_root: str | Path) -> Path:
    """Return the explicit workspace-default supervisor state directory."""

    return Path(workspace_root).resolve() / AUTHORITY_SUPERVISOR_WORKSPACE_DEFAULT_DIR


def _result_from_observations(
    *,
    command: str,
    state: AuthoritySupervisorState,
    identity: AuthorityRepositoryIdentity | None,
    registry: AuthorityRegistryValidationResult,
    readiness: AuthoritySupervisorReadiness,
    process_state: AuthoritySupervisorProcessState,
    repository_state: AuthoritySupervisorRepositoryState = (
        AuthoritySupervisorRepositoryState.READY
    ),
    diagnostics: Sequence[Mapping[str, PlainData]] = (),
    ok: bool = True,
) -> AuthoritySupervisorCommandResult:
    registry_generation = (
        None if registry.record is None else registry.record.service_generation
    )
    service_generation = None if identity is None else identity.service_generation
    generation_matches = (
        None
        if registry_generation is None or service_generation is None
        else registry_generation == service_generation
    )
    return AuthoritySupervisorCommandResult(
        command=command,
        ok=ok,
        state_dir=state.state_dir,
        workspace_root=state.workspace_root,
        workspace_id=state.workspace_id,
        endpoint=state.endpoint,
        pid=state.pid,
        process_state=process_state,
        readiness=readiness,
        repository_state=repository_state,
        registry_status=registry.status,
        service_generation=service_generation or state.service_generation,
        registry_generation=registry_generation,
        generation_matches=generation_matches,
        diagnostics=tuple(diagnostics),
    )


def _registry_record_from_readiness(
    *,
    state: AuthoritySupervisorState,
    identity: AuthorityRepositoryIdentity,
    readiness: AuthorityProtocolReadiness,
    health_state: AuthorityServiceHealthState,
) -> AuthorityRegistryRecord:
    return AuthorityRegistryRecord(
        reference=AuthorityReference(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
            reference_id="local-authority-supervisor",
            endpoint=state.endpoint,
            workspace_id=state.workspace_id,
            state_path=str(state.state_dir),
            metadata={"pid": state.pid},
        ),
        service_generation=identity.service_generation,
        workspace_id=state.workspace_id,
        state_dir=str(state.state_dir),
        protocol_version=readiness.version,
        capabilities=readiness.capabilities,
        created_at=state.started_at,
        updated_at=utc_timestamp(),
        service_health_state=health_state,
        diagnostics_metadata={
            "pid": state.pid,
            "repository_schema_version": identity.schema_version,
        },
    )


def _publish_supervisor_bootstrap(
    *,
    state_dir: Path,
    workspace_root: Path,
    workspace_id: str,
    host: str,
    port: int,
    identity: AuthorityRepositoryIdentity,
    readiness: AuthorityProtocolReadiness,
    tls: bool = False,
) -> AuthoritySupervisorState:
    """Publish a child-owned service identity before it begins accepting requests."""

    now = utc_timestamp()
    state = AuthoritySupervisorState(
        pid=os.getpid(),
        endpoint=_endpoint(host, port).replace("http://", "https://", 1)
        if tls
        else _endpoint(host, port),
        state_dir=state_dir,
        workspace_root=workspace_root,
        workspace_id=workspace_id,
        service_generation=identity.service_generation,
        host=host,
        port=port,
        started_at=now,
        updated_at=now,
        process_start_ticks=_captured_process_start_ticks(os.getpid()),
        process_boot_id=_process_boot_id(),
    )
    _write_state(state)
    write_authority_registry_record(
        workspace_root,
        _registry_record_from_readiness(
            state=state,
            identity=identity,
            readiness=readiness,
            health_state=AuthorityServiceHealthState.UNKNOWN,
        ),
    )
    return state


def _wait_until_ready(
    endpoint: str,
    *,
    timeout_seconds: float,
    process: subprocess.Popen[bytes] | None = None,
) -> AuthorityProtocolReadiness:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise AuthoritySupervisorError(
                "authority supervisor process exited during startup",
                code="authority_supervisor.exited_during_startup",
                context={
                    "endpoint": endpoint,
                    "returncode": process.returncode,
                },
            )
        try:
            return _fetch_readiness(endpoint)
        except Exception as exc:  # noqa: BLE001 - retain the last readiness failure.
            last_error = exc
            time.sleep(0.1)
    if last_error is not None:
        raise last_error
    raise TimeoutError("timed out waiting for authority readiness")


def _fetch_readiness(endpoint: str) -> AuthorityProtocolReadiness:
    request = urllib.request.Request(f"{endpoint.rstrip('/')}/ready")
    with urllib.request.urlopen(request, timeout=1.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    readiness = AuthorityProtocolReadiness.from_dict(payload)
    if not readiness.ready:
        raise AuthoritySupervisorError(
            "authority service is not ready",
            code="authority_supervisor.unready",
            context={"endpoint": endpoint, "readiness": readiness.to_dict()},
        )
    return readiness


def _readiness_for_state(
    state: AuthoritySupervisorState,
    *,
    process_state: AuthoritySupervisorProcessState,
) -> AuthoritySupervisorReadiness:
    if process_state is not AuthoritySupervisorProcessState.RUNNING:
        return AuthoritySupervisorReadiness.UNAVAILABLE
    try:
        readiness = _fetch_readiness(state.endpoint)
    except Exception:
        return AuthoritySupervisorReadiness.UNAVAILABLE
    if readiness.readiness is AuthorityReadinessState.READY:
        return AuthoritySupervisorReadiness.READY
    return AuthoritySupervisorReadiness.UNREADY


def _write_state(state: AuthoritySupervisorState) -> None:
    from loom.pipeline.stores.atomic import atomic_write_json

    atomic_write_json(supervisor_state_path(state.state_dir), state.to_dict())


def _read_state_if_present(state_dir: Path) -> AuthoritySupervisorState | None:
    path = supervisor_state_path(state_dir)
    if not path.exists():
        return None
    try:
        payload = json_loads(path.read_text(encoding="utf-8"), path=str(path))
    except (OSError, DeserializationError, PlainDataError) as exc:
        raise AuthoritySupervisorError(
            f"authority supervisor state is invalid: {path}",
            code="authority_supervisor.invalid_state",
            context={"path": str(path)},
        ) from exc
    return AuthoritySupervisorState.from_dict(payload)


def _resolve_state(
    *,
    state_dir: str | Path | None,
    use_workspace_default: bool,
    workspace_root: Path,
) -> AuthoritySupervisorState | None:
    resolved_state_dir = _optional_state_dir(
        state_dir=state_dir,
        workspace_root=workspace_root,
        use_workspace_default=use_workspace_default,
    )
    if resolved_state_dir is not None:
        return _read_state_if_present(resolved_state_dir)
    try:
        record = read_authority_registry_record(workspace_root)
    except AuthorityRegistryError:
        return None
    return _read_state_if_present(Path(record.state_dir).resolve())


def _read_identity(
    state_dir: Path,
) -> tuple[
    AuthorityRepositoryIdentity | None,
    AuthoritySupervisorRepositoryState,
    tuple[Mapping[str, PlainData], ...],
]:
    try:
        identity = AuthorityRepository(state_dir).read_identity()
    except AuthorityRepositoryCompatibilityError as exc:
        return (
            None,
            AuthoritySupervisorRepositoryState.INCOMPATIBLE,
            (
                _diagnostic(
                    "authority_supervisor.repository_incompatible",
                    str(exc),
                    detail=cast(Mapping[str, PlainData], exc.failure.to_dict()),
                ),
            ),
        )
    except AuthorityRepositoryError as exc:
        return (
            None,
            AuthoritySupervisorRepositoryState.ERROR,
            (
                _diagnostic(
                    "authority_supervisor.repository_error",
                    str(exc),
                    detail={"state_dir": str(state_dir)},
                ),
            ),
        )
    return identity, AuthoritySupervisorRepositoryState.READY, ()


def _registry_diagnostics(
    registry: AuthorityRegistryValidationResult,
) -> tuple[Mapping[str, PlainData], ...]:
    return tuple(diagnostic.to_dict() for diagnostic in registry.diagnostics)


def _mark_registry_unavailable(state: AuthoritySupervisorState) -> None:
    try:
        record = read_authority_registry_record(state.workspace_root)
    except AuthorityRegistryError:
        return
    if Path(record.state_dir).resolve() != state.state_dir.resolve():
        return
    updated = AuthorityRegistryRecord(
        reference=record.reference,
        service_generation=record.service_generation,
        workspace_id=record.workspace_id,
        state_dir=record.state_dir,
        protocol_version=record.protocol_version,
        capabilities=record.capabilities,
        allocation_scope=record.allocation_scope,
        allocation_id=record.allocation_id,
        created_at=record.created_at,
        updated_at=utc_timestamp(),
        expires_at=record.expires_at,
        service_health_state=AuthorityServiceHealthState.UNAVAILABLE,
        diagnostics_metadata=record.diagnostics_metadata,
    )
    write_authority_registry_record(state.workspace_root, updated)


def _terminate_process(
    state: AuthoritySupervisorState,
    *,
    timeout_seconds: float,
) -> bool:
    """Terminate only the exact persisted process and confirm its exit."""

    matching = _matching_process_is_live(state)
    if matching is False:
        # A missing PID or changed start identity proves this service has ended.
        return True
    if matching is None:
        # Legacy records have only a numeric PID. Never turn that into signal
        # authority; the PID may now belong to another process.
        return False
    pidfd = _open_verified_pidfd(state)
    if pidfd is None:
        return False
    try:
        if _pidfd_exited(pidfd):
            _reap_exited_child(state.pid)
            return True
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        except ProcessLookupError:
            _reap_exited_child(state.pid)
            return True
        if _wait_for_pidfd_exit(pidfd, time.monotonic() + timeout_seconds):
            _reap_exited_child(state.pid)
            return True
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        except ProcessLookupError:
            _reap_exited_child(state.pid)
            return True
        stopped = _wait_for_pidfd_exit(pidfd, time.monotonic() + 2.0)
        if stopped:
            _reap_exited_child(state.pid)
        return stopped
    finally:
        os.close(pidfd)


def _state_process_state(
    state: AuthoritySupervisorState,
) -> AuthoritySupervisorProcessState:
    matching = _matching_process_is_live(state)
    if matching is True:
        return AuthoritySupervisorProcessState.RUNNING
    if matching is False:
        return AuthoritySupervisorProcessState.STALE
    return AuthoritySupervisorProcessState.UNKNOWN


def _matching_process_is_live(state: AuthoritySupervisorState) -> bool | None:
    if state.process_start_ticks is None or state.process_boot_id is None:
        return False if not _process_running(state.pid) else None
    try:
        start_ticks = _process_start_ticks(state.pid)
    except ProcessLookupError:
        return False
    boot_id = _process_boot_id()
    if start_ticks is None or boot_id is None:
        return None
    return start_ticks == state.process_start_ticks and boot_id == state.process_boot_id


def _open_verified_pidfd(state: AuthoritySupervisorState) -> int | None:
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return None
    try:
        pidfd = os.pidfd_open(state.pid)
    except (OSError, ProcessLookupError):
        return None
    try:
        if _matching_process_is_live(state) is not True:
            os.close(pidfd)
            return None
    except BaseException:
        os.close(pidfd)
        raise
    return pidfd


def _pidfd_exited(pidfd: int) -> bool:
    return bool(select.select([pidfd], [], [], 0)[0])


def _wait_for_pidfd_exit(pidfd: int, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if _pidfd_exited(pidfd):
            return True
        time.sleep(0.05)
    return _pidfd_exited(pidfd)


def _reap_exited_child(pid: int) -> None:
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


def _process_start_ticks(pid: int) -> str | None:
    """Read Linux's immutable process start identity when the host exposes it."""

    stat_path = Path(f"/proc/{pid}/stat")
    try:
        value = stat_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if _process_running(pid):
            return None
        raise ProcessLookupError(pid) from exc
    except OSError:
        return None
    closing_parenthesis = value.rfind(")")
    fields = value[closing_parenthesis + 2 :].split()
    if closing_parenthesis < 0 or len(fields) <= 19:
        return None
    return fields[19]


def _captured_process_start_ticks(pid: int) -> str | None:
    try:
        return _process_start_ticks(pid)
    except ProcessLookupError:
        return None


def _process_boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8")
    except OSError:
        return None
    value = value.strip()
    return value or None


def _cleanup_started_process(process: subprocess.Popen[bytes]) -> None:
    """Use the launcher's unreaped child ownership to clean a failed startup."""

    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def _process_running(pid: int) -> bool:
    try:
        waited, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        waited = 0
    if waited == pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _open_log(state_dir: Path) -> TextIO:
    state_dir.mkdir(parents=True, exist_ok=True)
    return (state_dir / AUTHORITY_SUPERVISOR_LOG_FILE).open("a", encoding="utf-8")


def _endpoint(host: str, port: int) -> str:
    return f"http://{_non_empty(host, 'host')}:{_port(port)}"


def _explicit_state_dir(value: str | Path | None) -> Path:
    if value is None:
        raise AuthoritySupervisorError(
            "authority supervisor command requires --state-dir or --use-workspace-default",
            code="authority_supervisor.state_dir_required",
        )
    path = Path(value).expanduser().resolve()
    if not str(path):
        raise AuthoritySupervisorError(
            "authority supervisor state directory must be non-empty",
            code="authority_supervisor.invalid_state_dir",
        )
    return path


def _resolve_state_dir_option(
    *,
    state_dir: str | Path | None,
    workspace_root: Path,
    use_workspace_default: bool,
    command: str,
) -> Path:
    resolved = _optional_state_dir(
        state_dir=state_dir,
        workspace_root=workspace_root,
        use_workspace_default=use_workspace_default,
    )
    if resolved is None:
        raise AuthoritySupervisorError(
            f"authority supervisor {command} requires --state-dir or "
            "--use-workspace-default",
            code="authority_supervisor.state_dir_required",
        )
    return resolved


def _optional_state_dir(
    *,
    state_dir: str | Path | None,
    workspace_root: Path,
    use_workspace_default: bool,
) -> Path | None:
    if state_dir is not None and use_workspace_default:
        raise AuthoritySupervisorError(
            "--state-dir and --use-workspace-default are mutually exclusive",
            code="authority_supervisor.state_dir_conflict",
            context={"state_dir": str(state_dir)},
        )
    if use_workspace_default:
        return workspace_default_supervisor_state_dir(workspace_root)
    if state_dir is None:
        return None
    return _explicit_state_dir(state_dir)


def _reject_second_workspace_authority(
    *,
    workspace_root: Path,
    workspace_id: str,
    state_dir: Path,
) -> None:
    registry = validate_authority_registry(
        workspace_root,
        expected_workspace_id=workspace_id,
    )
    if registry.status is not AuthorityRegistryValidationStatus.VALID:
        return
    if registry.record is None:
        return
    if Path(registry.record.state_dir).resolve() == state_dir.resolve():
        return
    existing_state = _read_state_if_present(Path(registry.record.state_dir).resolve())
    if existing_state is None:
        return
    if (
        _state_process_state(existing_state)
        is not AuthoritySupervisorProcessState.RUNNING
    ):
        return
    if (
        _readiness_for_state(
            existing_state,
            process_state=AuthoritySupervisorProcessState.RUNNING,
        )
        is not AuthoritySupervisorReadiness.READY
    ):
        return
    raise AuthoritySupervisorError(
        "workspace already has a live authority supervisor",
        code="authority_supervisor.workspace_authority_exists",
        context={
            "workspace_root": str(workspace_root),
            "workspace_id": workspace_id,
            "existing_state_dir": registry.record.state_dir,
            "requested_state_dir": str(state_dir),
        },
    )


def _workspace_id(value: str | None, workspace_root: Path) -> str:
    if value is not None and value:
        return value
    return f"workspace:{workspace_root.resolve()}"


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: str = "error",
    detail: Mapping[str, PlainData] | None = None,
) -> Mapping[str, PlainData]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "detail": {} if detail is None else dict(detail),
    }


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthoritySupervisorError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthoritySupervisorError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise AuthoritySupervisorError(f"{field} is required")
    return mapping[field]


def _optional_non_empty(mapping: Mapping[str, object], field: str) -> str | None:
    value = mapping.get(field)
    if value is None:
        return None
    return _non_empty(value, field)


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise AuthoritySupervisorError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthoritySupervisorError(f"{field} must be a non-empty string")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthoritySupervisorError(f"{field} must be a positive integer")
    return value


def _port(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > 65535
    ):
        raise AuthoritySupervisorError("port must be an integer from 1 to 65535")
    return value


__all__ = [
    "AUTHORITY_SUPERVISOR_LOG_FILE",
    "AUTHORITY_SUPERVISOR_STATE_FILE",
    "AUTHORITY_SUPERVISOR_WORKSPACE_DEFAULT_DIR",
    "DEFAULT_AUTHORITY_SUPERVISOR_HOST",
    "DEFAULT_AUTHORITY_SUPERVISOR_PORT",
    "AuthoritySupervisorCommandResult",
    "AuthoritySupervisorError",
    "AuthoritySupervisorProcessState",
    "AuthoritySupervisorReadiness",
    "AuthoritySupervisorRepositoryState",
    "AuthoritySupervisorState",
    "inspect_authority_supervisor",
    "restart_authority_supervisor",
    "rotate_authority_repository_generation",
    "start_authority_supervisor",
    "stop_authority_supervisor",
    "supervisor_state_path",
    "workspace_default_supervisor_state_dir",
]
