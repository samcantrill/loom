"""Bounded, metadata-only inspection of one run.

This module is deliberately the only owner of the public inspection shape.  It
accepts already-targeted lower-owner facts and never asks lower packages to
know about diagnostics.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, TypeAlias, TypeVar, cast

from loom.pipeline.stores.run_uri import validate_run_uri
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp


RUN_INSPECTION_SCHEMA_VERSION = 1
MAX_INSPECTION_RUN_URI_BYTES = 4 * 1024
MAX_INSPECTION_RECORDS = 256
MAX_INSPECTION_RESPONSE_BYTES = 1024 * 1024


class RunInspectionError(ValueError):
    """Raised when an inspection model or request is invalid."""


class RunInspectionAxisName(StrEnum):
    ADMISSION = "admission"
    LIFECYCLE = "lifecycle"
    SCHEDULING = "scheduling"
    ASSIGNMENT = "assignment"
    EXTERNAL_SCHEDULER = "external_scheduler"
    TRANSFER_RESULT = "transfer_result"
    CANCELLATION = "cancellation"
    MATERIALIZATION = "materialization"
    SERVICE_HEALTH = "service_health"


class RunInspectionFailureCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


class RunLocationReachability(StrEnum):
    COORDINATOR_LOCAL = "coordinator_local"
    SHARED_UNKNOWN = "shared_unknown"
    EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class RunInspectionAxis:
    name: RunInspectionAxisName
    owner: str
    availability: str
    state: str
    revision: int | str | None
    observed_at: str | None
    freshness: str
    code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", RunInspectionAxisName(self.name))
        for field in ("owner", "availability", "state", "freshness"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise RunInspectionError(f"axis {field} must be a non-empty string")
        if self.revision is not None and (
            isinstance(self.revision, bool) or not isinstance(self.revision, (int, str))
        ):
            raise RunInspectionError("axis revision must be an int, string, or None")
        for field in ("observed_at", "code"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value):
                raise RunInspectionError(
                    f"axis {field} must be a non-empty string or None"
                )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "name": self.name.value,
            "owner": self.owner,
            "availability": self.availability,
            "state": self.state,
            "revision": self.revision,
            "observed_at": self.observed_at,
            "freshness": self.freshness,
            "code": self.code,
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunInspectionAxis":
        value = _exact_mapping(
            data,
            {
                "name",
                "owner",
                "availability",
                "state",
                "revision",
                "observed_at",
                "freshness",
                "code",
            },
            "axis",
        )
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class RunInspectionStage:
    stage_name: str
    state: str
    attempt: int | None = None

    def __post_init__(self) -> None:
        for field in ("stage_name", "state"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise RunInspectionError(f"stage {field} must be a non-empty string")
        if self.attempt is not None and (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise RunInspectionError("stage attempt must be a positive integer or None")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "state": self.state,
            "attempt": self.attempt,
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunInspectionStage":
        return cls(**_exact_mapping(data, {"stage_name", "state", "attempt"}, "stage"))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class RunInspectionLocation:
    logical_id: str
    uri: str
    kind: str
    availability: str
    artifact_type: str | None
    checksum: str | None
    reachability: RunLocationReachability

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reachability", RunLocationReachability(self.reachability)
        )
        for field in ("logical_id", "uri", "kind", "availability"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise RunInspectionError(f"location {field} must be a non-empty string")
        for field in ("artifact_type", "checksum"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value):
                raise RunInspectionError(
                    f"location {field} must be a non-empty string or None"
                )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "logical_id": self.logical_id,
            "uri": self.uri,
            "kind": self.kind,
            "availability": self.availability,
            "artifact_type": self.artifact_type,
            "checksum": self.checksum,
            "reachability": self.reachability.value,
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunInspectionLocation":
        return cls(
            **cast(
                Any,
                _exact_mapping(
                    data,
                    {
                        "logical_id",
                        "uri",
                        "kind",
                        "availability",
                        "artifact_type",
                        "checksum",
                        "reachability",
                    },
                    "location",
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class RunInspectionTruncation:
    collection: str
    total_count: int
    returned_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.collection, str) or not self.collection:
            raise RunInspectionError("truncation collection must be a non-empty string")
        for field in ("total_count", "returned_count"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RunInspectionError(f"truncation {field} must be non-negative")
        if self.returned_count > self.total_count:
            raise RunInspectionError(
                "truncation returned_count must not exceed total_count"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "collection": self.collection,
            "total_count": self.total_count,
            "returned_count": self.returned_count,
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunInspectionTruncation":
        return cls(
            **cast(
                Any,
                _exact_mapping(
                    data, {"collection", "total_count", "returned_count"}, "truncation"
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class RunInspectionResult:
    run_uri: str
    as_of: str
    summary: str
    axes: tuple[RunInspectionAxis, ...]
    stages: tuple[RunInspectionStage, ...]
    locations: tuple[RunInspectionLocation, ...]
    truncation: tuple[RunInspectionTruncation, ...]
    schema_version: int = RUN_INSPECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUN_INSPECTION_SCHEMA_VERSION:
            raise RunInspectionError("unsupported run inspection schema version")
        object.__setattr__(self, "run_uri", _run_uri(self.run_uri))
        if (
            not isinstance(self.as_of, str)
            or not self.as_of
            or not isinstance(self.summary, str)
            or not self.summary
        ):
            raise RunInspectionError(
                "result as_of and summary must be non-empty strings"
            )
        for field, kind in (
            ("axes", RunInspectionAxis),
            ("stages", RunInspectionStage),
            ("locations", RunInspectionLocation),
            ("truncation", RunInspectionTruncation),
        ):
            values = tuple(getattr(self, field))
            if not all(isinstance(value, kind) for value in values):
                raise RunInspectionError(f"{field} contains an invalid value")
            if len(values) > MAX_INSPECTION_RECORDS:
                raise RunInspectionError(
                    f"{field} may contain at most {MAX_INSPECTION_RECORDS} records"
                )
            object.__setattr__(self, field, values)
        names = tuple(axis.name for axis in self.axes)
        if len(names) != len(set(names)):
            raise RunInspectionError("axes must have unique names")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "as_of": self.as_of,
            "summary": self.summary,
            "axes": [item.to_dict() for item in self.axes],
            "stages": [item.to_dict() for item in self.stages],
            "locations": [item.to_dict() for item in self.locations],
            "truncation": [item.to_dict() for item in self.truncation],
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunInspectionResult":
        value = _exact_mapping(
            data,
            {
                "schema_version",
                "run_uri",
                "as_of",
                "summary",
                "axes",
                "stages",
                "locations",
                "truncation",
            },
            "result",
        )
        return cls(
            schema_version=_integer(value["schema_version"], "schema_version"),
            run_uri=cast(str, value["run_uri"]),
            as_of=cast(str, value["as_of"]),
            summary=cast(str, value["summary"]),
            axes=_decode_sequence(value["axes"], RunInspectionAxis.from_dict, "axes"),
            stages=_decode_sequence(
                value["stages"], RunInspectionStage.from_dict, "stages"
            ),
            locations=_decode_sequence(
                value["locations"], RunInspectionLocation.from_dict, "locations"
            ),
            truncation=_decode_sequence(
                value["truncation"], RunInspectionTruncation.from_dict, "truncation"
            ),
        )


@dataclass(frozen=True, slots=True)
class RunInspectionFailure:
    code: RunInspectionFailureCode
    schema_version: int = RUN_INSPECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", RunInspectionFailureCode(self.code))
        if self.schema_version != RUN_INSPECTION_SCHEMA_VERSION:
            raise RunInspectionError("unsupported run inspection schema version")

    def to_dict(self) -> dict[str, PlainData]:
        return {"schema_version": self.schema_version, "code": self.code.value}

    @classmethod
    def from_dict(cls, data: object) -> "RunInspectionFailure":
        value = _exact_mapping(data, {"schema_version", "code"}, "failure")
        return cls(
            schema_version=_integer(value["schema_version"], "schema_version"),
            code=cast(RunInspectionFailureCode, value["code"]),
        )


RunInspectionResponse: TypeAlias = RunInspectionResult | RunInspectionFailure


class RunInspectionProjection:
    """Project exact lower-owner facts into the stable public result."""

    def __init__(
        self,
        *,
        run_store: Any | None = None,
        daemon: Any | None = None,
        queue_service: Any | None = None,
    ) -> None:
        self._run_store = run_store
        self._daemon = daemon
        self._queue_service = queue_service

    def inspect(self, run_uri: str) -> RunInspectionResponse:
        try:
            run_uri = _run_uri(run_uri)
        except Exception:
            return RunInspectionFailure(RunInspectionFailureCode.INVALID_REQUEST)
        try:
            return self._inspect(run_uri)
        except FileNotFoundError:
            return RunInspectionFailure(RunInspectionFailureCode.NOT_FOUND)
        except LookupError:
            return RunInspectionFailure(RunInspectionFailureCode.NOT_FOUND)
        except OSError:
            return RunInspectionFailure(RunInspectionFailureCode.UNAVAILABLE)
        except Exception:
            return RunInspectionFailure(RunInspectionFailureCode.INTERNAL)

    def _inspect(self, run_uri: str) -> RunInspectionResult:
        # Importing the legacy facade here keeps ``loom.diagnostics`` cheap and lets
        # authority-backed stores keep their existing targeted read path.
        from .inspection import _authoritative_read, _default_run_store

        authoritative = _authoritative_read(run_uri, run_store=self._run_store)
        snapshot = None if authoritative is None else authoritative.snapshot
        local_store = (
            (
                getattr(self._run_store, "local_store", self._run_store)
                if self._run_store is not None
                else _default_run_store(run_uri)
            )
            if authoritative is None
            else authoritative.local_store
        )
        axes = _empty_axes()
        stages: list[RunInspectionStage] = []
        locations: list[RunInspectionLocation] = []
        if snapshot is not None:
            axes[RunInspectionAxisName.LIFECYCLE] = RunInspectionAxis(
                RunInspectionAxisName.LIFECYCLE,
                "authority",
                "available",
                snapshot.status.value,
                snapshot.revision.sequence,
                snapshot.revision.created_at,
                "current",
            )
            for stage in snapshot.stages:
                attempt = stage.attempts[-1].attempt if stage.attempts else None
                stages.append(
                    RunInspectionStage(stage.stage_name, stage.status.value, attempt)
                )
                for fact in stage.artifact_facts:
                    artifact = fact.artifact
                    locations.append(
                        _artifact_location(
                            f"artifact:{stage.stage_name}:{fact.artifact_name}",
                            artifact,
                        )
                    )
        else:
            # A service-less local run can still expose artifact references. This
            # indexed read is intentionally the only fallback, never a queue scan.
            index = local_store.read_artifact_index(run_uri)
            for logical_id, artifact in index.items():
                locations.append(_artifact_location(f"artifact:{logical_id}", artifact))
            axes[RunInspectionAxisName.LIFECYCLE] = RunInspectionAxis(
                RunInspectionAxisName.LIFECYCLE,
                "authority",
                "unavailable",
                "unavailable",
                None,
                None,
                "unavailable",
                "authority_unavailable",
            )
        if self._daemon is not None:
            admission = self._daemon.admission_for_run_uri(run_uri)
            axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
                RunInspectionAxisName.ADMISSION,
                "coordinator",
                "available",
                admission.state.value,
                None,
                admission.accepted_at,
                "current",
            )
        elif self._queue_service is not None:
            self._project_service_less_queue(run_uri, local_store, axes, locations)
        else:
            axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
                RunInspectionAxisName.ADMISSION,
                "coordinator",
                "unavailable",
                "unavailable",
                None,
                None,
                "unavailable",
                "queue_unavailable",
            )
        all_stages, stages = _bounded(sorted(stages, key=lambda item: item.stage_name))
        all_locations, locations = _bounded(
            sorted(locations, key=lambda item: item.logical_id), "locations"
        )
        truncation = (
            RunInspectionTruncation("stages", len(all_stages), len(stages)),
            RunInspectionTruncation("locations", len(all_locations), len(locations)),
        )
        result = RunInspectionResult(
            run_uri=run_uri,
            as_of=utc_timestamp(),
            summary=_summary(axes[RunInspectionAxisName.LIFECYCLE]),
            axes=tuple(axes[name] for name in RunInspectionAxisName),
            stages=tuple(stages),
            locations=tuple(locations),
            truncation=truncation,
        )
        return _fit_response(result)

    def _project_service_less_queue(
        self,
        run_uri: str,
        local_store: Any,
        axes: dict[RunInspectionAxisName, RunInspectionAxis],
        locations: list[RunInspectionLocation],
    ) -> None:
        """Read one retained operation and one queue primary key, never a scan."""
        operation = local_store.latest_submitted_operation(run_uri)
        if operation is None:
            axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
                RunInspectionAxisName.ADMISSION, "queue", "unavailable", "unavailable",
                None, None, "unavailable", "queue_reference_unavailable"
            )
            return
        queue = operation.backend_metadata.get("queue")
        queue_item_id = queue.get("queue_item_id") if isinstance(queue, Mapping) else None
        if not isinstance(queue_item_id, str):
            axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
                RunInspectionAxisName.ADMISSION, "queue", "unavailable", "unavailable",
                None, operation.updated_at, "unavailable", "queue_reference_missing"
            )
            return
        queue_service = self._queue_service
        assert queue_service is not None
        item = queue_service.read_item(queue_item_id)
        if item is None or item.run_uri != run_uri:
            axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
                RunInspectionAxisName.ADMISSION, "queue", "unavailable", "unavailable",
                None, operation.updated_at, "unavailable", "queue_reference_mismatch"
            )
            return
        axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
            RunInspectionAxisName.ADMISSION, "queue", "available", item.status.value,
            item.dispatch_attempt, item.updated_at, "current"
        )
        axes[RunInspectionAxisName.SCHEDULING] = RunInspectionAxis(
            RunInspectionAxisName.SCHEDULING, "queue", "available", item.status.value,
            item.dispatch_attempt, item.updated_at, "current"
        )
        handle = item.dispatch_handle
        if handle is not None:
            recorded_item_id = handle.evidence.get("queue_item_id")
            if recorded_item_id is not None and recorded_item_id != queue_item_id:
                raise LookupError("dispatch handle queue reference mismatches")
            axes[RunInspectionAxisName.ASSIGNMENT] = RunInspectionAxis(
                RunInspectionAxisName.ASSIGNMENT, "queue", "available", "DISPATCHED",
                handle.dispatch_attempt, handle.dispatched_at, "current"
            )
        manifest = _read_slurm_manifest(local_store, run_uri, operation)
        if manifest is not None:
            if manifest.queue_item_id != queue_item_id:
                raise LookupError("retained manifest queue reference mismatches")
            axes[RunInspectionAxisName.EXTERNAL_SCHEDULER] = RunInspectionAxis(
                RunInspectionAxisName.EXTERNAL_SCHEDULER, "slurm", "available",
                manifest.submission_status.value, operation.updated_at, manifest.updated_at,
                "current"
            )
            for job in manifest.submitted_jobs:
                for stream, path in (("stdout", job.stdout_relative_path), ("stderr", job.stderr_relative_path)):
                    if path is not None:
                        locations.append(RunInspectionLocation(
                            f"log:{job.logical_key}:{stream}", path, "log", "recorded",
                            None, None, RunLocationReachability.SHARED_UNKNOWN
                        ))


def inspect_run(
    run_uri: str, *, run_store: Any | None = None, daemon: Any | None = None,
    queue_service: Any | None = None,
) -> RunInspectionResponse:
    """Return one safe, bounded inspection result or a closed failure."""
    return RunInspectionProjection(run_store=run_store, daemon=daemon, queue_service=queue_service).inspect(run_uri)


def projection_callable(
    *, run_store: Any | None = None, daemon: Any | None = None,
    queue_service: Any | None = None,
) -> Callable[[str], Mapping[str, PlainData]]:
    """Return the plain-data callback accepted by lower transports."""
    projection = RunInspectionProjection(run_store=run_store, daemon=daemon, queue_service=queue_service)
    return lambda run_uri: projection.inspect(run_uri).to_dict()


def decode_run_inspection_response(data: object) -> RunInspectionResponse:
    mapping = _mapping(data, "response")
    return (
        RunInspectionResult.from_dict(mapping)
        if "run_uri" in mapping
        else RunInspectionFailure.from_dict(mapping)
    )


def _empty_axes() -> dict[RunInspectionAxisName, RunInspectionAxis]:
    return {
        name: RunInspectionAxis(
            name,
            "unavailable",
            "unavailable",
            "unavailable",
            None,
            None,
            "unavailable",
            "owner_unavailable",
        )
        for name in RunInspectionAxisName
    }


def _artifact_location(logical_id: str, artifact: Any) -> RunInspectionLocation:
    uri = str(artifact.uri)
    return RunInspectionLocation(
        logical_id,
        uri,
        "artifact",
        "recorded",
        str(artifact.artifact_type),
        artifact.checksum,
        RunLocationReachability.EXTERNAL
        if not uri.startswith("file:")
        else RunLocationReachability.COORDINATOR_LOCAL,
    )


_T = TypeVar("_T")


def _bounded(values: list[_T], collection: str = "") -> tuple[list[_T], list[_T]]:
    return values, values[:MAX_INSPECTION_RECORDS]


def _summary(axis: RunInspectionAxis) -> str:
    return axis.state if axis.availability == "available" else "unavailable"


def _read_slurm_manifest(local_store: Any, run_uri: str, operation: Any) -> Any | None:
    """Read the one run-local manifest named by the retained operation."""
    if operation.backend != "slurm":
        return None
    from loom.pipeline.executors.slurm.live import read_slurm_live_manifest
    from loom.pipeline.executors.slurm.paths import resolve_slurm_generated_artifact_path

    paths = getattr(local_store, "paths", local_store)
    path = resolve_slurm_generated_artifact_path(
        paths, run_uri, operation.manifest_relative_path
    ).local_path
    return read_slurm_live_manifest(json.loads(path.read_text(encoding="utf-8")))


def _fit_response(result: RunInspectionResult) -> RunInspectionResult:
    """Keep the encoded public response below the fixed transport budget."""
    stages = list(result.stages)
    locations = list(result.locations)
    while True:
        truncation = (
            RunInspectionTruncation("stages", result.truncation[0].total_count, len(stages)),
            RunInspectionTruncation("locations", result.truncation[1].total_count, len(locations)),
        )
        candidate = RunInspectionResult(result.run_uri, result.as_of, result.summary,
            result.axes, tuple(stages), tuple(locations), truncation)
        if len(json.dumps(candidate.to_dict(), separators=(",", ":")).encode("utf-8")) <= MAX_INSPECTION_RESPONSE_BYTES:
            return candidate
        if locations:
            locations.pop()
        elif stages:
            stages.pop()
        else:
            return candidate


def _run_uri(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > MAX_INSPECTION_RUN_URI_BYTES
    ):
        raise RunInspectionError("run_uri must be at most 4 KiB")
    return validate_run_uri(value)


def _mapping(data: object, name: str) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise RunInspectionError(f"{name} must be a mapping")
    return data


def _exact_mapping(data: object, fields: set[str], name: str) -> dict[str, object]:
    value = dict(_mapping(data, name))
    if set(value) != fields:
        raise RunInspectionError(f"{name} fields are invalid")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunInspectionError(f"{name} must be an integer")
    return value


def _decode_sequence(
    value: object, decoder: Callable[[object], Any], name: str
) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise RunInspectionError(f"{name} must be a list")
    return tuple(decoder(item) for item in value)


__all__ = [
    "MAX_INSPECTION_RECORDS",
    "MAX_INSPECTION_RESPONSE_BYTES",
    "MAX_INSPECTION_RUN_URI_BYTES",
    "RUN_INSPECTION_SCHEMA_VERSION",
    "RunInspectionAxis",
    "RunInspectionAxisName",
    "RunInspectionError",
    "RunInspectionFailure",
    "RunInspectionFailureCode",
    "RunInspectionLocation",
    "RunInspectionProjection",
    "RunInspectionResponse",
    "RunInspectionResult",
    "RunInspectionStage",
    "RunInspectionTruncation",
    "RunLocationReachability",
    "decode_run_inspection_response",
    "inspect_run",
    "projection_callable",
]
