"""Read-only diagnostics for authoritative run backends."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from loom.pipeline.stores import (
    AuthoritativeReadOptions,
    AuthorityBackendKind,
    AuthorityConfig,
    BackendCapability,
    BackendCapabilitySet,
    BackendRevision,
    CapabilityScope,
    DiagnosticSeverity,
    LocalMaterializationRequest,
    LocalRunStore,
    PerRunAuthorityStore,
    StoreDiagnostic,
    UnsupportedCapabilityCode,
    read_authoritative_run,
    run_uri_to_path,
)
from loom.pipeline.stores.read_models import StageLifecycleSnapshot
from loom.pipeline.stores.schema_policy import (
    AuthoritySchemaCheck,
    AuthoritySchemaFailureKind,
)
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError


class BackendDiagnosticsError(ValueError):
    """Raised when backend diagnostics cannot answer from authority state."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "backend_diagnostics.error",
        diagnostics: Sequence[StoreDiagnostic] = (),
        context: Mapping[str, PlainData] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = tuple(diagnostics)
        self.context = dict(context or {})

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "message": str(self),
            "code": self.code,
            "context": dict(self.context),
            "diagnostics": [
                diagnostic.to_dict() for diagnostic in self.diagnostics
            ],
        }


@dataclass(frozen=True, slots=True)
class BackendInspectionResult:
    """Plain-data diagnostics for one authoritative run."""

    run_uri: str
    backend_name: str
    schema: Mapping[str, PlainData]
    revision: Mapping[str, PlainData]
    status: str
    counts: Mapping[str, int]
    stages: tuple[Mapping[str, PlainData], ...] = ()
    submitted_operations: tuple[Mapping[str, PlainData], ...] = ()
    cleanup_candidates: tuple[Mapping[str, PlainData], ...] = ()
    recovery_records: tuple[Mapping[str, PlainData], ...] = ()
    materialized_refs: tuple[Mapping[str, PlainData], ...] = ()
    warnings: tuple[Mapping[str, PlainData], ...] = ()

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "backend_name": self.backend_name,
            "schema": dict(self.schema),
            "revision": dict(self.revision),
            "status": self.status,
            "counts": dict(self.counts),
            "stages": [dict(stage) for stage in self.stages],
            "submitted_operations": [
                dict(operation) for operation in self.submitted_operations
            ],
            "cleanup_candidates": [
                dict(candidate) for candidate in self.cleanup_candidates
            ],
            "recovery_records": [
                dict(record) for record in self.recovery_records
            ],
            "materialized_refs": [dict(ref) for ref in self.materialized_refs],
            "warnings": [dict(warning) for warning in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class BackendCapabilitiesResult:
    """Plain-data diagnostics for one authoritative backend capability set."""

    run_uri: str
    backend_name: str
    schema: Mapping[str, PlainData]
    capabilities: tuple[Mapping[str, PlainData], ...]
    diagnostics: tuple[Mapping[str, PlainData], ...] = ()
    requirements: Mapping[str, bool] = field(default_factory=dict)

    @property
    def has_error_diagnostics(self) -> bool:
        return any(
            diagnostic.get("severity") == DiagnosticSeverity.ERROR.value
            for diagnostic in self.diagnostics
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "backend_name": self.backend_name,
            "schema": dict(self.schema),
            "capabilities": [
                dict(capability) for capability in self.capabilities
            ],
            "diagnostics": [
                dict(diagnostic) for diagnostic in self.diagnostics
            ],
            "requirements": dict(self.requirements),
        }


def inspect_backend(
    run_uri: str,
    *,
    stage_name: str | None = None,
    verify_materialization: bool = False,
    projection_revision: BackendRevision | str | None = None,
    authority_store: PerRunAuthorityStore | None = None,
    authority_config: AuthorityConfig | None = None,
) -> BackendInspectionResult:
    """Inspect one authoritative run without mutating backend state."""

    resolved_run_uri = _validate_run_uri(run_uri)
    store = authority_store or _default_authority_store(authority_config)
    schema = _require_supported_schema(store, resolved_run_uri)
    capability_set = store.capabilities()
    snapshot = read_authoritative_run(
        store,
        resolved_run_uri,
        options=AuthoritativeReadOptions(
            include_materialized_refs=True,
            verify_materialization=verify_materialization,
            verify_materialization_checksums=False,
            projection_revision=_parse_projection_revision(projection_revision),
        ),
        local_paths=LocalRunStore(run_uri_to_path(resolved_run_uri).parent),
        local_materialization=LocalMaterializationRequest(),
    )
    stages = tuple(
        stage for stage in snapshot.stages
        if stage_name is None or stage.stage_name == stage_name
    )
    if stage_name is not None and not stages:
        raise BackendDiagnosticsError(
            f"unknown stage {stage_name!r} for run {resolved_run_uri}",
            code="backend_diagnostics.unknown_stage",
            context={"run_uri": resolved_run_uri, "stage_name": stage_name},
        )
    recovery_records = store.scan_recovery(resolved_run_uri)
    cleanup_candidates = store.list_cleanup_candidates(resolved_run_uri)
    active_leases = tuple(
        stage.active_lease for stage in snapshot.stages if stage.active_lease is not None
    )
    commits = tuple(
        stage.latest_commit for stage in snapshot.stages if stage.latest_commit is not None
    )
    artifact_facts = tuple(
        fact for stage in snapshot.stages for fact in stage.artifact_facts
    )
    attempts = tuple(attempt for stage in snapshot.stages for attempt in stage.attempts)
    return BackendInspectionResult(
        run_uri=resolved_run_uri,
        backend_name=capability_set.backend_name,
        schema=schema.to_dict(),
        revision=snapshot.revision.to_dict(),
        status=snapshot.status.value,
        counts={
            "stages": len(snapshot.stages),
            "attempts": len(attempts),
            "active_leases": len(active_leases),
            "submitted_operations": len(snapshot.submitted_operations),
            "commits": len(commits),
            "artifact_facts": len(artifact_facts),
            "cleanup_candidates": len(cleanup_candidates),
            "recovery_records": len(recovery_records),
            "materialized_refs": len(snapshot.materialized_refs),
            "warnings": len(snapshot.warnings),
        },
        stages=tuple(_stage_detail(stage) for stage in stages),
        submitted_operations=tuple(
            operation.to_dict() for operation in snapshot.submitted_operations
        ),
        cleanup_candidates=tuple(
            candidate.to_dict() for candidate in cleanup_candidates
        ),
        recovery_records=tuple(record.to_dict() for record in recovery_records),
        materialized_refs=tuple(ref.to_dict() for ref in snapshot.materialized_refs),
        warnings=tuple(warning.to_dict() for warning in snapshot.warnings),
    )


def inspect_backend_capabilities(
    run_uri: str,
    *,
    require_shared_filesystem: bool = False,
    require_remote: bool = False,
    authority_store: PerRunAuthorityStore | None = None,
    authority_config: AuthorityConfig | None = None,
) -> BackendCapabilitiesResult:
    """Inspect backend capabilities and optional environment assumptions."""

    resolved_run_uri = _validate_run_uri(run_uri)
    store = authority_store or _default_authority_store(authority_config)
    schema = _require_supported_schema(store, resolved_run_uri)
    capability_set = store.capabilities()
    diagnostics = _requirement_diagnostics(
        capability_set,
        require_shared_filesystem=require_shared_filesystem,
        require_remote=require_remote,
    )
    return BackendCapabilitiesResult(
        run_uri=resolved_run_uri,
        backend_name=capability_set.backend_name,
        schema=schema.to_dict(),
        capabilities=tuple(record.to_dict() for record in capability_set.records),
        diagnostics=tuple(diagnostic.to_dict() for diagnostic in diagnostics),
        requirements={
            "shared_filesystem": require_shared_filesystem,
            "remote": require_remote,
        },
    )


def parse_projection_revision(value: str | None) -> BackendRevision | None:
    """Parse a CLI projection revision value in ``SEQUENCE:TOKEN`` form."""

    return _parse_projection_revision(value)


def _validate_run_uri(run_uri: str) -> str:
    from loom.pipeline.stores import validate_run_uri

    return validate_run_uri(run_uri)


def _default_authority_store(
    authority_config: AuthorityConfig | None = None,
) -> PerRunAuthorityStore:
    if authority_config is None:
        from loom.pipeline.stores import authority_config_from_env

        config = authority_config_from_env()
    else:
        config = authority_config
    if config.backend_kind is AuthorityBackendKind.TRANSITIONAL_SQLITE:
        from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore

        return SQLitePerRunAuthorityStore()
    if config.backend_kind in {
        AuthorityBackendKind.CO_LOCATED_SERVICE,
        AuthorityBackendKind.MANAGED_SERVICE,
        AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
    }:
        from loom.pipeline.stores.service_authority import create_service_authority_store

        return create_service_authority_store(config)
    raise BackendDiagnosticsError(
        f"backend diagnostics cannot inspect authority backend {config.backend_kind.value}",
        code="backend_diagnostics.unsupported_backend",
        context={"backend_kind": config.backend_kind.value},
    )


def _require_supported_schema(
    store: PerRunAuthorityStore, run_uri: str
) -> AuthoritySchemaCheck:
    try:
        check = store.check_schema(run_uri)
    except Exception as exc:
        diagnostic = StoreDiagnostic(
            code="authority_schema_unavailable",
            message=str(exc) or "authoritative backend schema is unavailable",
            severity=DiagnosticSeverity.ERROR,
            detail={"run_uri": run_uri},
        )
        raise BackendDiagnosticsError(
            diagnostic.message,
            code="backend_diagnostics.schema_unavailable",
            diagnostics=(diagnostic,),
            context={"run_uri": run_uri},
        ) from exc
    if check.failure is None:
        return check
    diagnostic = check.failure.to_diagnostic()
    marker_exists = _authority_marker_exists(run_uri)
    if check.failure.kind is AuthoritySchemaFailureKind.MISSING:
        message = (
            "authoritative backend is missing"
            if marker_exists
            else "run has no authoritative backend"
        )
    else:
        message = check.failure.message
    raise BackendDiagnosticsError(
        message,
        code=f"backend_diagnostics.schema_{check.failure.kind.value}",
        diagnostics=(diagnostic,),
        context={"run_uri": run_uri, "authority_marker_exists": marker_exists},
    )


def _authority_marker_exists(run_uri: str) -> bool:
    try:
        return (run_uri_to_path(run_uri) / ".loom").exists()
    except Exception:
        return False


def _parse_projection_revision(
    value: BackendRevision | str | None,
) -> BackendRevision | None:
    if value is None or isinstance(value, BackendRevision):
        return value
    if not isinstance(value, str) or ":" not in value:
        raise BackendDiagnosticsError(
            "projection revision must be SEQUENCE:TOKEN",
            code="backend_diagnostics.invalid_projection_revision",
            context={"projection_revision": str(value)},
        )
    sequence_text, token = value.split(":", 1)
    try:
        sequence = int(sequence_text)
    except ValueError as exc:
        raise BackendDiagnosticsError(
            "projection revision sequence must be an integer",
            code="backend_diagnostics.invalid_projection_revision",
            context={"projection_revision": value},
        ) from exc
    try:
        return BackendRevision(sequence=sequence, token=token)
    except Exception as exc:
        raise BackendDiagnosticsError(
            str(exc),
            code="backend_diagnostics.invalid_projection_revision",
            context={"projection_revision": value},
        ) from exc


def _stage_detail(stage: StageLifecycleSnapshot) -> Mapping[str, PlainData]:
    detail = _plain_mapping(stage.to_dict(), "stage")
    attempts = detail.get("attempts")
    if isinstance(attempts, Sequence) and not isinstance(attempts, str):
        detail["attempt_count"] = len(attempts)
    artifacts = detail.get("artifact_facts")
    if isinstance(artifacts, Sequence) and not isinstance(artifacts, str):
        detail["artifact_count"] = len(artifacts)
    return detail


def _requirement_diagnostics(
    capability_set: BackendCapabilitySet,
    *,
    require_shared_filesystem: bool,
    require_remote: bool,
) -> tuple[StoreDiagnostic, ...]:
    diagnostics: list[StoreDiagnostic] = []
    if require_shared_filesystem:
        diagnostics.append(
            StoreDiagnostic(
                code=UnsupportedCapabilityCode.UNSAFE_SHARED_FILESYSTEM.value,
                message=(
                    f"backend {capability_set.backend_name!r} does not prove "
                    "shared-filesystem safety"
                ),
                severity=DiagnosticSeverity.ERROR,
                detail={"backend_name": capability_set.backend_name},
            )
        )
    if require_remote:
        unsupported = capability_set.require(
            BackendCapability.CROSS_RUN_COORDINATION,
            scope=CapabilityScope.CROSS_RUN,
        )
        if unsupported is not None:
            diagnostics.append(
                StoreDiagnostic(
                    code=UnsupportedCapabilityCode.UNSAFE_REMOTE_COORDINATION.value,
                    message=unsupported.message,
                    severity=DiagnosticSeverity.ERROR,
                    detail={
                        "backend_name": capability_set.backend_name,
                        "required_capability": unsupported.capability.value,
                        "scope": unsupported.scope.value,
                        **dict(unsupported.detail),
                    },
                )
            )
    return tuple(diagnostics)


def _plain_mapping(value: object, path: str) -> dict[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=path)
    except PlainDataError as exc:
        raise BackendDiagnosticsError(
            f"{path} is not plain-data compatible: {exc}",
            code="backend_diagnostics.serialization_error",
            context={"path": path},
        ) from exc
    if not isinstance(normalized, Mapping):
        raise BackendDiagnosticsError(
            f"{path} must serialize to a mapping",
            code="backend_diagnostics.serialization_error",
            context={"path": path},
        )
    return dict(normalized)


__all__ = [
    "BackendCapabilitiesResult",
    "BackendDiagnosticsError",
    "BackendInspectionResult",
    "inspect_backend",
    "inspect_backend_capabilities",
    "parse_projection_revision",
]
