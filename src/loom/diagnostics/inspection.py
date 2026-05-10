"""Diagnostics facades for persisted local run status and logs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from loom.artifacts import ArtifactRef
from loom.pipeline.stores import parse_artifact_key
from loom.serialization import PlainData, ensure_plain_data, thaw_plain_data


DEFAULT_LOG_TAIL_LINES = 100
LOG_STREAMS = ("stdout", "stderr")


class DiagnosticsInspectionError(ValueError):
    """Raised when persisted diagnostics state cannot be inspected."""


@dataclass(frozen=True, slots=True)
class SubmittedOperationSummary:
    submission_id: str
    backend: str
    mode: str
    state: str
    created_at: str
    updated_at: str
    manifest_relative_path: str
    summary_counts: Mapping[str, int] = field(default_factory=dict)
    active: bool = False

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "submission_id": self.submission_id,
            "backend": self.backend,
            "mode": self.mode,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "manifest_relative_path": self.manifest_relative_path,
            "summary_counts": dict(self.summary_counts),
            "active": self.active,
        }


@dataclass(frozen=True, slots=True)
class StageStatusSummary:
    stage_name: str
    status: str | None = None
    attempt: int | None = None
    message: str | None = None
    failure: Mapping[str, PlainData] | None = None
    input_count: int = 0
    output_count: int = 0
    provenance_available: bool = False
    log_paths: Mapping[str, str | None] = field(default_factory=dict)
    log_available: Mapping[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "status": self.status,
            "attempt": self.attempt,
            "message": self.message,
            "failure": None if self.failure is None else dict(self.failure),
            "input_count": self.input_count,
            "output_count": self.output_count,
            "provenance_available": self.provenance_available,
            "log_paths": dict(self.log_paths),
            "log_available": dict(self.log_available),
        }


@dataclass(frozen=True, slots=True)
class RunStatusSummary:
    run_uri: str
    status: str | None = None
    message: str | None = None
    artifact_count: int = 0
    submitted_operations: tuple[SubmittedOperationSummary, ...] = ()
    stages: tuple[StageStatusSummary, ...] = ()

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "status": self.status,
            "message": self.message,
            "artifact_count": self.artifact_count,
            "submitted_operations": [
                operation.to_dict() for operation in self.submitted_operations
            ],
            "stages": [stage.to_dict() for stage in self.stages],
        }


@dataclass(frozen=True, slots=True)
class LogStreamSummary:
    stream: str
    path: str
    available: bool
    content: str | None = None
    line_count: int = 0
    displayed_line_count: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stream": self.stream,
            "path": self.path,
            "available": self.available,
            "content": self.content,
            "line_count": self.line_count,
            "displayed_line_count": self.displayed_line_count,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class StageLogsSummary:
    run_uri: str
    stage_name: str
    streams: tuple[LogStreamSummary, ...]
    paths_only: bool = False

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "paths_only": self.paths_only,
            "streams": [stream.to_dict() for stream in self.streams],
        }


@dataclass(frozen=True, slots=True)
class ArtifactSummary:
    key: str
    artifact_id: str
    stage_name: str
    output_name: str
    uri: str
    artifact_type: str
    codec_key: str | None = None
    schema_version: int = 1
    checksum: str | None = None
    fingerprint: str | None = None
    producer_stage: str | None = None
    created_at: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    provenance_available: bool = False

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "key": self.key,
            "artifact_id": self.artifact_id,
            "stage_name": self.stage_name,
            "output_name": self.output_name,
            "uri": self.uri,
            "artifact_type": self.artifact_type,
            "codec_key": self.codec_key,
            "schema_version": self.schema_version,
            "checksum": self.checksum,
            "fingerprint": self.fingerprint,
            "producer_stage": self.producer_stage,
            "created_at": self.created_at,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
            "provenance_available": self.provenance_available,
        }


@dataclass(frozen=True, slots=True)
class RunArtifactsSummary:
    run_uri: str
    artifacts: tuple[ArtifactSummary, ...] = ()

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "artifact_count": self.artifact_count,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class ArtifactDetailSummary:
    run_uri: str
    artifact: ArtifactSummary
    stage_provenance: Mapping[str, PlainData] | None = None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "artifact": self.artifact.to_dict(),
            "stage_provenance": None
            if self.stage_provenance is None
            else thaw_plain_data(self.stage_provenance, path="stage_provenance"),
        }


def inspect_run_status(
    run_uri: str, *, run_store: Any | None = None
) -> RunStatusSummary:
    """Inspect run status through authoritative facts when available."""

    authoritative = _authoritative_read(run_uri, run_store=run_store)
    if authoritative is not None:
        snapshot, local_store = authoritative
        return RunStatusSummary(
            run_uri=snapshot.run_uri,
            status=snapshot.status.value,
            message=None,
            artifact_count=sum(len(stage.artifact_facts) for stage in snapshot.stages),
            submitted_operations=tuple(
                SubmittedOperationSummary(
                    submission_id=record.submission_id,
                    backend=record.backend,
                    mode=record.mode,
                    state=record.state.value,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    manifest_relative_path=record.manifest_relative_path,
                    summary_counts=record.summary_counts,
                    active=record.active,
                )
                for record in snapshot.submitted_operations
            ),
            stages=tuple(
                _authoritative_stage_summary(local_store, snapshot.run_uri, stage)
                for stage in snapshot.stages
            ),
        )

    raise _local_lifecycle_unsupported(run_uri)


def inspect_run_artifacts(
    run_uri: str, *, run_store: Any | None = None
) -> RunArtifactsSummary:
    """Inspect artifact metadata through authoritative facts when available."""

    authoritative = _authoritative_read(run_uri, run_store=run_store)
    if authoritative is not None:
        snapshot, local_store = authoritative
        artifacts = tuple(
            _artifact_summary(
                local_store,
                run_uri=run_uri,
                key=f"{stage.stage_name}.{fact.artifact_name}",
                artifact_ref=fact.artifact,
            )
            for stage in snapshot.stages
            for fact in stage.artifact_facts
        )
        return RunArtifactsSummary(
            run_uri=snapshot.run_uri,
            artifacts=tuple(sorted(artifacts, key=lambda artifact: artifact.key)),
        )

    store = _default_run_store(run_uri) if run_store is None else run_store
    _open_run(store, run_uri)
    artifacts = tuple(
        _artifact_summary(
            store,
            run_uri=run_uri,
            key=key,
            artifact_ref=artifact_ref,
        )
        for key, artifact_ref in sorted(store.read_artifact_index(run_uri).items())
    )
    return RunArtifactsSummary(run_uri=run_uri, artifacts=artifacts)


def inspect_run_artifact(
    run_uri: str, artifact_id: str, *, run_store: Any | None = None
) -> ArtifactDetailSummary:
    """Inspect one persisted artifact reference by artifact ID."""

    if not artifact_id:
        raise DiagnosticsInspectionError("artifact_id must be a non-empty string")
    summary = inspect_run_artifacts(run_uri, run_store=run_store)
    match: ArtifactSummary | None = None
    duplicate_keys: list[str] = []
    for artifact in summary.artifacts:
        if artifact.artifact_id != artifact_id:
            continue
        if match is None:
            match = artifact
        else:
            if not duplicate_keys:
                duplicate_keys.append(match.key)
            duplicate_keys.append(artifact.key)

    if match is None:
        raise DiagnosticsInspectionError(
            f"unknown artifact {artifact_id!r} for run {run_uri}"
        )
    if duplicate_keys:
        keys = ", ".join(duplicate_keys)
        raise DiagnosticsInspectionError(
            f"ambiguous artifact {artifact_id!r} for run {run_uri}: {keys}"
        )

    artifact = match
    store = _default_run_store(run_uri) if run_store is None else run_store
    provenance = _plain_mapping_or_none(
        store.read_stage_provenance(run_uri, artifact.stage_name)
    )
    return ArtifactDetailSummary(
        run_uri=summary.run_uri,
        artifact=artifact,
        stage_provenance=provenance,
    )


def inspect_stage_logs(
    run_uri: str,
    stage_name: str,
    *,
    streams: Iterable[str] = LOG_STREAMS,
    tail: int = DEFAULT_LOG_TAIL_LINES,
    paths_only: bool = False,
    run_store: Any | None = None,
) -> StageLogsSummary:
    """Inspect bounded persisted stage logs through public store APIs."""

    if tail <= 0:
        raise DiagnosticsInspectionError("tail must be a positive integer")
    selected = _normalize_streams(streams)
    store = _default_run_store(run_uri) if run_store is None else run_store
    stages = set(store.list_run_stages(run_uri))
    if stage_name not in stages:
        raise DiagnosticsInspectionError(
            f"unknown stage {stage_name!r} for run {run_uri}"
        )

    summaries = tuple(
        _stream_summary(
            store,
            run_uri=run_uri,
            stage_name=stage_name,
            stream=stream,
            tail=tail,
            paths_only=paths_only,
        )
        for stream in selected
    )
    if not paths_only and not any(summary.available for summary in summaries):
        names = ", ".join(selected)
        raise DiagnosticsInspectionError(
            f"no log content found for stage {stage_name!r} stream(s): {names}"
        )
    return StageLogsSummary(
        run_uri=run_uri,
        stage_name=stage_name,
        streams=summaries,
        paths_only=paths_only,
    )


def _artifact_summary(
    store: Any,
    *,
    run_uri: str,
    key: str,
    artifact_ref: ArtifactRef,
) -> ArtifactSummary:
    stage_name, output_name = parse_artifact_key(key)
    provenance = store.read_stage_provenance(run_uri, stage_name)
    return ArtifactSummary(
        key=key,
        artifact_id=artifact_ref.artifact_id,
        stage_name=stage_name,
        output_name=output_name,
        uri=artifact_ref.uri,
        artifact_type=artifact_ref.artifact_type,
        codec_key=artifact_ref.codec_key,
        schema_version=artifact_ref.schema_version,
        checksum=artifact_ref.checksum,
        fingerprint=artifact_ref.fingerprint,
        producer_stage=artifact_ref.producer_stage,
        created_at=artifact_ref.created_at,
        metadata=artifact_ref.metadata,
        provenance_available=provenance is not None,
    )


def _authoritative_stage_summary(
    store: Any, run_uri: str, stage: object
) -> StageStatusSummary:
    stage_name = str(getattr(stage, "stage_name"))
    status = getattr(stage, "status")
    attempts = tuple(getattr(stage, "attempts"))
    latest_attempt = attempts[-1] if attempts else None
    reason = getattr(stage, "reason")
    stdout_content = _safe_read_stage_log(store, run_uri, stage_name, "stdout")
    stderr_content = _safe_read_stage_log(store, run_uri, stage_name, "stderr")
    return StageStatusSummary(
        stage_name=stage_name,
        status=None if status is None else status.value,
        attempt=None if latest_attempt is None else latest_attempt.attempt,
        message=None if reason is None else reason.message,
        failure=_safe_plain_mapping(
            lambda: store.read_stage_failure(run_uri, stage_name)
        ),
        input_count=len(_safe_mapping(lambda: store.read_stage_inputs(run_uri, stage_name))),
        output_count=len(tuple(getattr(stage, "artifact_facts"))),
        provenance_available=_safe_plain_mapping(
            lambda: store.read_stage_provenance(run_uri, stage_name)
        )
        is not None,
        log_paths={
            "stdout": _optional_str(store.local_stage_log_path(run_uri, stage_name, "stdout")),
            "stderr": _optional_str(store.local_stage_log_path(run_uri, stage_name, "stderr")),
        },
        log_available={
            "stdout": stdout_content is not None,
            "stderr": stderr_content is not None,
        },
    )


def _stream_summary(
    store: Any,
    *,
    run_uri: str,
    stage_name: str,
    stream: str,
    tail: int,
    paths_only: bool,
) -> LogStreamSummary:
    path = str(store.local_stage_log_path(run_uri, stage_name, stream))
    if paths_only:
        content = store.read_stage_log(run_uri, stage_name, stream)
        return LogStreamSummary(stream=stream, path=path, available=content is not None)

    content = store.read_stage_log(run_uri, stage_name, stream)
    if content is None:
        return LogStreamSummary(stream=stream, path=path, available=False)

    lines = content.splitlines()
    displayed = lines[-tail:]
    rendered = "\n".join(displayed)
    if content.endswith("\n") and rendered:
        rendered += "\n"
    return LogStreamSummary(
        stream=stream,
        path=path,
        available=True,
        content=rendered,
        line_count=len(lines),
        displayed_line_count=len(displayed),
        truncated=len(lines) > len(displayed),
    )


def _normalize_streams(streams: Iterable[str]) -> tuple[str, ...]:
    selected = tuple(streams)
    if not selected:
        raise DiagnosticsInspectionError("at least one log stream is required")
    unknown = sorted(set(selected) - set(LOG_STREAMS))
    if unknown:
        names = ", ".join(unknown)
        raise DiagnosticsInspectionError(f"unknown log stream(s): {names}")
    return tuple(stream for stream in LOG_STREAMS if stream in selected)


def _default_run_store(run_uri: str | None = None) -> Any:
    from loom.pipeline.stores import LocalRunStore

    if run_uri is None:
        return LocalRunStore()
    try:
        from loom.pipeline.stores import run_uri_to_path

        return LocalRunStore(run_uri_to_path(run_uri).parent)
    except Exception:
        return LocalRunStore()


def _authoritative_read(
    run_uri: str, *, run_store: Any | None
) -> tuple[Any, Any] | None:
    authority_store = getattr(run_store, "authority_store", None)
    local_store = getattr(run_store, "local_store", None)
    force_authoritative = authority_store is not None
    if authority_store is None:
        try:
            from loom.pipeline.stores import (
                AuthorityBackendKind,
                authority_config_from_env,
            )
            from loom.pipeline.stores.schema_policy import AuthoritySchemaFailureKind

            config = authority_config_from_env()
            if config.backend_kind is AuthorityBackendKind.TRANSITIONAL_SQLITE:
                raise DiagnosticsInspectionError(
                    "transitional SQLite authority is no longer a supported "
                    "runtime backend"
                )
            if config.backend_kind not in {
                AuthorityBackendKind.CO_LOCATED_SERVICE,
                AuthorityBackendKind.MANAGED_SERVICE,
                AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
            }:
                return None
            from loom.pipeline.stores.service_authority import (
                create_service_authority_store,
            )

            authority_store = create_service_authority_store(config)
            check = authority_store.check_schema(run_uri)
            if (
                check.failure is not None
                and check.failure.kind is AuthoritySchemaFailureKind.MISSING
            ):
                if _authority_marker_exists(run_uri):
                    raise DiagnosticsInspectionError(
                        f"authoritative backend is missing for run {run_uri}"
                    )
                return None
            if check.failure is not None:
                raise DiagnosticsInspectionError(
                    f"authoritative backend is unavailable for run {run_uri}: "
                    f"{check.failure.message}"
                )
        except DiagnosticsInspectionError:
            raise
        except Exception as exc:
            if _authority_marker_exists(run_uri):
                raise DiagnosticsInspectionError(
                    f"authoritative backend is unavailable for run {run_uri}: {exc}"
                ) from exc
            return None
    if local_store is None:
        local_store = _default_run_store(run_uri)
    try:
        from loom.pipeline.stores import (
            AuthoritativeReadOptions,
            LocalMaterializationRequest,
            read_authoritative_run,
        )

        snapshot = read_authoritative_run(
            authority_store,
            run_uri,
            options=AuthoritativeReadOptions(include_materialized_refs=True),
            local_paths=local_store,
            local_materialization=LocalMaterializationRequest(),
        )
    except Exception:
        if force_authoritative:
            raise
        if _authority_marker_exists(run_uri):
            raise DiagnosticsInspectionError(
                f"authoritative backend is unavailable for run {run_uri}"
            )
        return None
    if snapshot.warnings:
        raise DiagnosticsInspectionError(
            f"authoritative backend is unavailable for run {run_uri}"
        )
    return snapshot, local_store


def _authority_marker_exists(run_uri: str) -> bool:
    try:
        from loom.pipeline.stores import run_uri_to_path

        return (run_uri_to_path(run_uri) / ".loom").exists()
    except Exception:
        return False


def _local_lifecycle_unsupported(run_uri: str) -> DiagnosticsInspectionError:
    return DiagnosticsInspectionError(
        "local-only lifecycle state is not supported for status inspection; "
        f"run {run_uri} has no authoritative lifecycle backend"
    )


def _open_run(store: Any, run_uri: str) -> None:
    open_run = getattr(store, "open_run", None)
    if callable(open_run):
        open_run(run_uri)


def _plain_mapping_or_none(value: object) -> Mapping[str, PlainData] | None:
    if value is None:
        return None
    normalized = ensure_plain_data(value, path="failure")
    if not isinstance(normalized, dict):
        return {"value": normalized}
    return normalized


def _safe_mapping(read: Any) -> Mapping[str, Any]:
    try:
        value = read()
    except Exception:
        return {}
    return value if isinstance(value, Mapping) else {}


def _safe_plain_mapping(read: Any) -> Mapping[str, PlainData] | None:
    try:
        return _plain_mapping_or_none(read())
    except Exception:
        return None


def _safe_read_stage_log(
    store: Any, run_uri: str, stage_name: str, stream: str
) -> str | None:
    try:
        return store.read_stage_log(run_uri, stage_name, stream)
    except Exception:
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = [
    "ArtifactDetailSummary",
    "ArtifactSummary",
    "DEFAULT_LOG_TAIL_LINES",
    "LOG_STREAMS",
    "DiagnosticsInspectionError",
    "LogStreamSummary",
    "RunStatusSummary",
    "RunArtifactsSummary",
    "StageLogsSummary",
    "StageStatusSummary",
    "inspect_run_artifact",
    "inspect_run_artifacts",
    "inspect_run_status",
    "inspect_stage_logs",
]
