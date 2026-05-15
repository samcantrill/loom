"""Store-owned artifact payload materialization records and local copy behavior."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

from loom.artifacts import (
    ArtifactLocationKind,
    ArtifactLocationSummary,
    ArtifactRef,
    ArtifactStoreRef,
)
from loom.fingerprints import compare_digests, hash_bytes, validate_digest
from loom.io.uris import UnsupportedURIError, get_uri_scheme, path_to_file_uri, uri_to_path
from loom.operations import (
    OperationAdapterIdentity,
    OperationDiagnostic,
    OperationDiagnosticSeverity,
    OperationEvidenceCheck,
    OperationEvidenceRecord,
    OperationEvidenceStatus,
    OperationResult,
    OperationStatus,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from .read_models import MaterializedRef, MaterializedRefKind


class ArtifactMaterializationError(ValueError):
    """Raised when artifact materialization records are invalid."""


class LocalMaterializationPolicy(StrEnum):
    """Local artifact materialization policies understood by Stage 16."""

    COPY = "copy"
    HARDLINK = "hardlink"
    SYMLINK = "symlink"
    REFLINK = "reflink"
    MOVE = "move"
    CACHE_PROMOTE = "cache_promote"


@dataclass(frozen=True, slots=True)
class ArtifactMaterializationRequest:
    """Request for explicit local artifact payload materialization."""

    artifact: ArtifactRef
    target_path: str | Path
    policy: LocalMaterializationPolicy | str = LocalMaterializationPolicy.COPY
    overwrite: bool = False
    verify_checksum: bool = True
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", _coerce_artifact(self.artifact))
        object.__setattr__(
            self,
            "target_path",
            _path_string(self.target_path, "target_path"),
        )
        object.__setattr__(self, "policy", _coerce_policy(self.policy, "policy"))
        if not isinstance(self.overwrite, bool):
            raise ArtifactMaterializationError("overwrite must be a bool")
        if not isinstance(self.verify_checksum, bool):
            raise ArtifactMaterializationError("verify_checksum must be a bool")
        object.__setattr__(self, "details", _plain_mapping(self.details, "details"))

    def to_dict(self) -> dict[str, PlainData]:
        policy = cast(LocalMaterializationPolicy, self.policy)
        target_path = cast(str, self.target_path)
        return {
            "artifact": self.artifact.to_dict(),
            "target_path": target_path,
            "policy": policy.value,
            "overwrite": self.overwrite,
            "verify_checksum": self.verify_checksum,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ArtifactMaterializationRequest":
        mapping = _mapping(data, "ArtifactMaterializationRequest")
        _reject_unknown(
            mapping,
            {
                "artifact",
                "target_path",
                "policy",
                "overwrite",
                "verify_checksum",
                "details",
            },
            "ArtifactMaterializationRequest",
        )
        return cls(
            artifact=ArtifactRef.from_dict(_required(mapping, "artifact")),
            target_path=_path_string(_required(mapping, "target_path"), "target_path"),
            policy=_coerce_policy(
                mapping.get("policy", LocalMaterializationPolicy.COPY.value),
                "policy",
            ),
            overwrite=_bool(mapping.get("overwrite", False), "overwrite"),
            verify_checksum=_bool(
                mapping.get("verify_checksum", True),
                "verify_checksum",
            ),
            details=_plain_mapping(mapping.get("details", {}), "details"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactMaterializationResult:
    """Result of an explicit local artifact materialization operation."""

    request: ArtifactMaterializationRequest
    operation: OperationResult
    source_uri: str
    target_uri: str | None = None
    location: ArtifactLocationSummary | None = None
    materialized_ref: MaterializedRef | None = None
    bytes_copied: int | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request, ArtifactMaterializationRequest):
            raise ArtifactMaterializationError(
                "request must be an ArtifactMaterializationRequest"
            )
        if not isinstance(self.operation, OperationResult):
            raise ArtifactMaterializationError("operation must be an OperationResult")
        object.__setattr__(
            self,
            "source_uri",
            _non_empty_string(self.source_uri, "source_uri"),
        )
        if self.target_uri is not None:
            object.__setattr__(
                self,
                "target_uri",
                _non_empty_string(self.target_uri, "target_uri"),
            )
        if self.location is not None and not isinstance(
            self.location,
            ArtifactLocationSummary,
        ):
            raise ArtifactMaterializationError(
                "location must be an ArtifactLocationSummary or None"
            )
        if self.materialized_ref is not None and not isinstance(
            self.materialized_ref,
            MaterializedRef,
        ):
            raise ArtifactMaterializationError(
                "materialized_ref must be a MaterializedRef or None"
            )
        if self.bytes_copied is not None and (
            not isinstance(self.bytes_copied, int)
            or isinstance(self.bytes_copied, bool)
            or self.bytes_copied < 0
        ):
            raise ArtifactMaterializationError(
                "bytes_copied must be a non-negative int or None"
            )
        object.__setattr__(self, "details", _plain_mapping(self.details, "details"))

    @property
    def succeeded(self) -> bool:
        """Return whether the materialization operation succeeded."""

        return self.operation.status is OperationStatus.SUCCEEDED

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "request": self.request.to_dict(),
            "operation": self.operation.to_dict(),
            "source_uri": self.source_uri,
            "target_uri": self.target_uri,
            "location": None if self.location is None else self.location.to_summary(),
            "materialized_ref": None
            if self.materialized_ref is None
            else self.materialized_ref.to_dict(),
            "bytes_copied": self.bytes_copied,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ArtifactMaterializationResult":
        mapping = _mapping(data, "ArtifactMaterializationResult")
        _reject_unknown(
            mapping,
            {
                "request",
                "operation",
                "source_uri",
                "target_uri",
                "location",
                "materialized_ref",
                "bytes_copied",
                "details",
            },
            "ArtifactMaterializationResult",
        )
        location_data = mapping.get("location")
        materialized_ref_data = mapping.get("materialized_ref")
        return cls(
            request=ArtifactMaterializationRequest.from_dict(
                _required(mapping, "request")
            ),
            operation=OperationResult.from_dict(_required(mapping, "operation")),
            source_uri=_non_empty_string(_required(mapping, "source_uri"), "source_uri"),
            target_uri=_optional_string(mapping.get("target_uri"), "target_uri"),
            location=None
            if location_data is None
            else ArtifactLocationSummary.from_dict(location_data),
            materialized_ref=None
            if materialized_ref_data is None
            else MaterializedRef.from_dict(materialized_ref_data),
            bytes_copied=_optional_non_negative_int(
                mapping.get("bytes_copied"),
                "bytes_copied",
            ),
            details=_plain_mapping(mapping.get("details", {}), "details"),
        )


def materialize_artifact_locally(
    request: ArtifactMaterializationRequest,
) -> ArtifactMaterializationResult:
    """Materialize one local artifact payload using the copy policy only."""

    if not isinstance(request, ArtifactMaterializationRequest):
        raise ArtifactMaterializationError(
            "request must be an ArtifactMaterializationRequest"
        )
    policy = cast(LocalMaterializationPolicy, request.policy)
    if policy is not LocalMaterializationPolicy.COPY:
        return _unsupported_policy_result(request)

    source_result = _source_path(request.artifact)
    target_path = Path(request.target_path).expanduser().resolve(strict=False)
    target_uri = path_to_file_uri(target_path)
    if source_result.operation is not None:
        return ArtifactMaterializationResult(
            request=request,
            operation=source_result.operation,
            source_uri=request.artifact.uri,
            target_uri=target_uri,
        )
    source_path = source_result.path
    assert source_path is not None

    blocked = _target_blocker(request, source_path, target_path)
    if blocked is not None:
        return ArtifactMaterializationResult(
            request=request,
            operation=blocked,
            source_uri=request.artifact.uri,
            target_uri=target_uri,
        )

    source_checksum = _file_checksum(source_path)
    expected_checksum = _expected_checksum(request.artifact.checksum)
    checksum_failure = _checksum_failure_result(
        request,
        expected_checksum=expected_checksum,
        actual_checksum=source_checksum,
    )
    if checksum_failure is not None:
        return ArtifactMaterializationResult(
            request=request,
            operation=checksum_failure,
            source_uri=request.artifact.uri,
            target_uri=target_uri,
        )

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
    except OSError as exc:
        return ArtifactMaterializationResult(
            request=request,
            operation=_failed_result(
                request,
                code="artifact_materialization.copy_failed",
                message="artifact payload copy failed",
                details={"error_type": type(exc).__name__, "error": str(exc)},
            ),
            source_uri=request.artifact.uri,
            target_uri=target_uri,
        )

    target_checksum = _file_checksum(target_path)
    size_bytes = target_path.stat().st_size
    evidence = _success_evidence(
        request,
        expected_checksum=expected_checksum,
        source_checksum=source_checksum,
        target_checksum=target_checksum,
        size_bytes=size_bytes,
    )
    operation = OperationResult(
        operation="artifact.materialize.local.copy",
        status=OperationStatus.SUCCEEDED,
        adapter=_LOCAL_ADAPTER,
        diagnostics=(),
        evidence=evidence,
        details={
            "policy": LocalMaterializationPolicy.COPY.value,
            "source_uri": request.artifact.uri,
            "target_uri": target_uri,
            "bytes_copied": size_bytes,
        },
    )
    location = artifact_materialization_location(
        request.artifact,
        target_path,
        checksum=target_checksum,
        size_bytes=size_bytes,
        details={"policy": LocalMaterializationPolicy.COPY.value},
    )
    materialized_ref = artifact_materialized_ref(
        request.artifact,
        target_path,
        checksum=target_checksum,
        details={"policy": LocalMaterializationPolicy.COPY.value},
    )
    return ArtifactMaterializationResult(
        request=request,
        operation=operation,
        source_uri=request.artifact.uri,
        target_uri=target_uri,
        location=location,
        materialized_ref=materialized_ref,
        bytes_copied=size_bytes,
    )


def artifact_materialization_location(
    artifact: ArtifactRef,
    target_path: str | Path,
    *,
    checksum: str | None = None,
    size_bytes: int | None = None,
    details: Mapping[str, PlainData] | None = None,
) -> ArtifactLocationSummary:
    """Project a derived materialized artifact location summary."""

    artifact = _coerce_artifact(artifact)
    path = Path(_path_string(target_path, "target_path")).expanduser().resolve(
        strict=False
    )
    normalized_checksum = None if checksum is None else _validate_checksum(checksum)
    return ArtifactLocationSummary(
        kind=ArtifactLocationKind.MATERIALIZED,
        authority="derived",
        uri=path_to_file_uri(path),
        display_uri=str(path),
        store=ArtifactStoreRef(kind="local", display_uri=str(path.parent)),
        checksum=normalized_checksum,
        size_bytes=_optional_non_negative_int(size_bytes, "size_bytes"),
        details={
            "artifact_id": artifact.artifact_id,
            "source_uri": artifact.uri,
            **dict(details or {}),
        },
    )


def artifact_materialized_ref(
    artifact: ArtifactRef,
    target_path: str | Path,
    *,
    checksum: str | None = None,
    details: Mapping[str, PlainData] | None = None,
) -> MaterializedRef:
    """Project a derived read-model materialized artifact payload reference."""

    artifact = _coerce_artifact(artifact)
    path = Path(_path_string(target_path, "target_path")).expanduser().resolve(
        strict=False
    )
    normalized_checksum = None if checksum is None else _validate_checksum(checksum)
    return MaterializedRef(
        kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
        uri=path_to_file_uri(path),
        exists=path.exists(),
        checksum=normalized_checksum,
        metadata={
            "artifact_id": artifact.artifact_id,
            "source_uri": artifact.uri,
            **dict(details or {}),
        },
    )


@dataclass(frozen=True, slots=True)
class _SourcePathResult:
    path: Path | None = None
    operation: OperationResult | None = None


_LOCAL_ADAPTER = OperationAdapterIdentity(
    name="local-artifact-materialization",
    kind="local",
    version="1",
)


def _source_path(artifact: ArtifactRef) -> _SourcePathResult:
    if get_uri_scheme(artifact.uri) not in {None, "file"}:
        return _SourcePathResult(
            operation=_failed_result(
                artifact,
                code="artifact_materialization.unsupported_source_uri",
                message="artifact source URI is not local",
                status=OperationStatus.BLOCKED,
                details={"source_uri": artifact.uri},
            )
        )
    try:
        path = uri_to_path(artifact.uri).expanduser().resolve(strict=False)
    except (RuntimeError, UnsupportedURIError, ValueError) as exc:
        return _SourcePathResult(
            operation=_failed_result(
                artifact,
                code="artifact_materialization.invalid_source_uri",
                message="artifact source URI could not be resolved",
                details={"source_uri": artifact.uri, "error": str(exc)},
            )
        )
    if not path.exists():
        return _SourcePathResult(
            operation=_failed_result(
                artifact,
                code="artifact_materialization.source_missing",
                message="artifact source path does not exist",
                details={"source_uri": artifact.uri, "source_path": str(path)},
            )
        )
    if not path.is_file():
        return _SourcePathResult(
            operation=_failed_result(
                artifact,
                code="artifact_materialization.source_not_file",
                message="local materialization supports regular files only",
                status=OperationStatus.BLOCKED,
                details={"source_uri": artifact.uri, "source_path": str(path)},
            )
        )
    return _SourcePathResult(path=path)


def _target_blocker(
    request: ArtifactMaterializationRequest,
    source_path: Path,
    target_path: Path,
) -> OperationResult | None:
    if source_path == target_path:
        return _failed_result(
            request,
            code="artifact_materialization.same_source_and_target",
            message="artifact source and target paths are the same",
            status=OperationStatus.BLOCKED,
            details={"target_path": str(target_path)},
        )
    if target_path.exists() and target_path.is_dir():
        return _failed_result(
            request,
            code="artifact_materialization.target_is_directory",
            message="artifact materialization target is a directory",
            status=OperationStatus.BLOCKED,
            details={"target_path": str(target_path)},
        )
    if target_path.exists() and not request.overwrite:
        return _failed_result(
            request,
            code="artifact_materialization.target_exists",
            message="artifact materialization target already exists",
            status=OperationStatus.BLOCKED,
            details={"target_path": str(target_path)},
        )
    return None


def _success_evidence(
    request: ArtifactMaterializationRequest,
    *,
    expected_checksum: str | None,
    source_checksum: str,
    target_checksum: str,
    size_bytes: int,
) -> OperationEvidenceRecord:
    checks: list[OperationEvidenceCheck] = [
        OperationEvidenceCheck(
            name="copy_checksum_match",
            status=OperationEvidenceStatus.PROVEN
            if compare_digests(source_checksum, target_checksum)
            else OperationEvidenceStatus.FAILED,
            message="source and target byte checksums match",
            details={
                "source_checksum": source_checksum,
                "target_checksum": target_checksum,
            },
        )
    ]
    if request.verify_checksum:
        if expected_checksum is None:
            checks.append(
                OperationEvidenceCheck(
                    name="expected_checksum_available",
                    status=OperationEvidenceStatus.UNPROVEN,
                    message="artifact did not provide an expected byte checksum",
                    details={},
                )
            )
        else:
            checks.append(
                OperationEvidenceCheck(
                    name="expected_checksum_match",
                    status=OperationEvidenceStatus.PROVEN,
                    message="artifact checksum matched materialized bytes",
                    details={
                        "expected_checksum": expected_checksum,
                        "actual_checksum": target_checksum,
                    },
                )
            )
    return OperationEvidenceRecord(
        status=OperationEvidenceStatus.PROVEN
        if all(check.status is OperationEvidenceStatus.PROVEN for check in checks)
        else OperationEvidenceStatus.UNPROVEN,
        checks=tuple(checks),
        adapter=_LOCAL_ADAPTER,
        details={
            "policy": LocalMaterializationPolicy.COPY.value,
            "size_bytes": size_bytes,
        },
    )


def _checksum_failure_result(
    request: ArtifactMaterializationRequest,
    *,
    expected_checksum: str | None,
    actual_checksum: str,
) -> OperationResult | None:
    if not request.verify_checksum or expected_checksum is None:
        return None
    if compare_digests(actual_checksum, expected_checksum):
        return None
    return OperationResult(
        operation="artifact.materialize.local.copy",
        status=OperationStatus.FAILED,
        adapter=_LOCAL_ADAPTER,
        diagnostics=(
            OperationDiagnostic(
                code="artifact_materialization.checksum_mismatch",
                message="artifact source checksum does not match expected checksum",
                severity=OperationDiagnosticSeverity.ERROR,
                details={
                    "artifact_id": request.artifact.artifact_id,
                    "expected_checksum": expected_checksum,
                    "actual_checksum": actual_checksum,
                },
            ),
        ),
        evidence=OperationEvidenceRecord(
            status=OperationEvidenceStatus.FAILED,
            checks=(
                OperationEvidenceCheck(
                    name="expected_checksum_match",
                    status=OperationEvidenceStatus.FAILED,
                    message="artifact source checksum did not match expected checksum",
                    details={
                        "expected_checksum": expected_checksum,
                        "actual_checksum": actual_checksum,
                    },
                ),
            ),
            adapter=_LOCAL_ADAPTER,
            details={"policy": LocalMaterializationPolicy.COPY.value},
        ),
        details={
            "artifact_id": request.artifact.artifact_id,
            "policy": LocalMaterializationPolicy.COPY.value,
        },
    )


def _unsupported_policy_result(
    request: ArtifactMaterializationRequest,
) -> ArtifactMaterializationResult:
    policy = cast(LocalMaterializationPolicy, request.policy)
    operation = OperationResult.unsupported(
        "artifact.materialize.local",
        reason=f"local materialization policy {policy.value!r} is not supported in Stage 16",
        adapter=_LOCAL_ADAPTER,
        details={
            "policy": policy.value,
            "artifact_id": request.artifact.artifact_id,
            "target_path": cast(str, request.target_path),
        },
    )
    return ArtifactMaterializationResult(
        request=request,
        operation=operation,
        source_uri=request.artifact.uri,
        target_uri=path_to_file_uri(
            Path(request.target_path).expanduser().resolve(strict=False)
        ),
    )


def _failed_result(
    owner: ArtifactMaterializationRequest | ArtifactRef,
    *,
    code: str,
    message: str,
    status: OperationStatus = OperationStatus.FAILED,
    details: Mapping[str, PlainData] | None = None,
) -> OperationResult:
    artifact = owner.artifact if isinstance(owner, ArtifactMaterializationRequest) else owner
    return OperationResult(
        operation="artifact.materialize.local.copy",
        status=status,
        adapter=_LOCAL_ADAPTER,
        diagnostics=(
            OperationDiagnostic(
                code=code,
                message=message,
                severity=OperationDiagnosticSeverity.ERROR,
                details={
                    "artifact_id": artifact.artifact_id,
                    **dict(details or {}),
                },
            ),
        ),
        evidence=OperationEvidenceRecord(
            status=OperationEvidenceStatus.FAILED
            if status is OperationStatus.FAILED
            else OperationEvidenceStatus.UNPROVEN,
            checks=(),
            adapter=_LOCAL_ADAPTER,
            details={"artifact_id": artifact.artifact_id, **dict(details or {})},
        ),
        details={"artifact_id": artifact.artifact_id, **dict(details or {})},
    )


def _file_checksum(path: Path) -> str:
    return hash_bytes(path.read_bytes())


def _expected_checksum(checksum: str | None) -> str | None:
    return None if checksum is None else _validate_checksum(checksum)


def _validate_checksum(checksum: str) -> str:
    try:
        return validate_digest(checksum)
    except Exception as exc:
        raise ArtifactMaterializationError(
            f"invalid checksum syntax {checksum!r}: {exc}"
        ) from exc


def _coerce_artifact(value: object) -> ArtifactRef:
    if isinstance(value, ArtifactRef):
        return value
    if isinstance(value, Mapping):
        return ArtifactRef.from_dict(value)
    raise ArtifactMaterializationError("artifact must be an ArtifactRef")


def _coerce_policy(value: object, field: str) -> LocalMaterializationPolicy:
    if isinstance(value, LocalMaterializationPolicy):
        return value
    if isinstance(value, str):
        try:
            return LocalMaterializationPolicy(value)
        except ValueError as exc:
            raise ArtifactMaterializationError(
                f"{field} must be one of: {', '.join(_policy_values())}"
            ) from exc
    raise ArtifactMaterializationError(
        f"{field} must be one of: {', '.join(_policy_values())}"
    )


def _policy_values() -> tuple[str, ...]:
    return tuple(policy.value for policy in LocalMaterializationPolicy)


def _path_string(value: object, field: str) -> str:
    if isinstance(value, Path):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise ArtifactMaterializationError(f"{field} must be a path string")
    if not text:
        raise ArtifactMaterializationError(f"{field} must be a non-empty path string")
    return text


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactMaterializationError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field)


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactMaterializationError(f"{field} must be a bool")
    return value


def _optional_non_negative_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ArtifactMaterializationError(f"{field} must be a non-negative int")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise ArtifactMaterializationError(f"{field} must be a mapping")
    try:
        frozen = freeze_plain_data(value, path=field)
    except Exception as exc:
        raise ArtifactMaterializationError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise ArtifactMaterializationError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ArtifactMaterializationError(f"{field} must be a mapping")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], key: str) -> object:
    try:
        return mapping[key]
    except KeyError as exc:
        raise ArtifactMaterializationError(f"{key} is required") from exc


def _reject_unknown(
    mapping: Mapping[str, object],
    allowed: set[str],
    field: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise ArtifactMaterializationError(
            f"{field} received unknown fields: {', '.join(sorted(unknown))}"
        )


__all__ = [
    "ArtifactMaterializationError",
    "LocalMaterializationPolicy",
    "ArtifactMaterializationRequest",
    "ArtifactMaterializationResult",
    "materialize_artifact_locally",
    "artifact_materialization_location",
    "artifact_materialized_ref",
]
