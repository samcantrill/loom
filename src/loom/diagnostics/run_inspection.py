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
from pathlib import Path
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
    code: str | None = None

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
        if self.code is not None and (not isinstance(self.code, str) or not self.code):
            raise RunInspectionError("stage code must be a non-empty string or None")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "state": self.state,
            "attempt": self.attempt,
            "code": self.code,
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunInspectionStage":
        return cls(
            **cast(
                Any,
                _exact_mapping(
                    data,
                    {"stage_name", "state", "attempt", "code"},
                    "stage",
                ),
            )
        )


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
    queue_item_id: str | None = None
    admission_id: str | None = None
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
        for field in ("queue_item_id", "admission_id"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value):
                raise RunInspectionError(
                    f"result {field} must be a non-empty string or None"
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
        if set(names) != set(RunInspectionAxisName):
            raise RunInspectionError("axes must contain every run inspection axis")
        by_name = {axis.name: axis for axis in self.axes}
        object.__setattr__(
            self,
            "axes",
            tuple(by_name[name] for name in RunInspectionAxisName),
        )
        by_collection = {item.collection: item for item in self.truncation}
        if set(by_collection) != {"stages", "locations"} or len(by_collection) != len(
            self.truncation
        ):
            raise RunInspectionError(
                "truncation must contain stages and locations exactly once"
            )
        for collection, returned_count in (
            ("stages", len(self.stages)),
            ("locations", len(self.locations)),
        ):
            if by_collection[collection].returned_count != returned_count:
                raise RunInspectionError(
                    f"truncation {collection} returned_count is inconsistent"
                )
        object.__setattr__(
            self,
            "truncation",
            (by_collection["stages"], by_collection["locations"]),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "as_of": self.as_of,
            "summary": self.summary,
            "queue_item_id": self.queue_item_id,
            "admission_id": self.admission_id,
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
                "queue_item_id",
                "admission_id",
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
            queue_item_id=cast(str | None, value["queue_item_id"]),
            admission_id=cast(str | None, value["admission_id"]),
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

        authority_unavailable = False
        try:
            authoritative = _authoritative_read(run_uri, run_store=self._run_store)
        except Exception:
            # Inspection is an observational join.  One unavailable owner must
            # not erase facts from the other exact owners of a known run.
            authoritative = None
            authority_unavailable = True
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
        local_known = snapshot is not None
        materialization_available = snapshot is not None
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
                reason = getattr(stage, "reason", None)
                code = getattr(reason, "code", None)
                stages.append(
                    RunInspectionStage(
                        stage.stage_name,
                        stage.status.value,
                        attempt,
                        code if isinstance(code, str) and code else None,
                    )
                )
                _append_stage_log_locations(
                    local_store,
                    run_uri,
                    stage.stage_name,
                    locations,
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
            opener = getattr(local_store, "open_run", None)
            if callable(opener):
                try:
                    opener(run_uri)
                except (FileNotFoundError, LookupError):
                    pass
                else:
                    local_known = True
            try:
                index = local_store.read_artifact_index(run_uri)
            except (FileNotFoundError, LookupError, OSError):
                index = {}
            else:
                materialization_available = local_known or not callable(opener)
                local_known = local_known or not callable(opener)
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
        admission_id: str | None = None
        queue_item_id: str | None = None
        owner_known = False
        if self._daemon is not None:
            admission_id, queue_item_id, owner_known = self._project_managed(
                run_uri,
                axes,
                stages,
            )
        elif self._queue_service is not None:
            queue_item_id, owner_known = self._project_service_less_queue(
                run_uri,
                local_store,
                axes,
                locations,
            )
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
        if not local_known and not owner_known:
            if authority_unavailable:
                raise OSError("authority is unavailable")
            raise FileNotFoundError(run_uri)
        artifact_count = sum(item.kind == "artifact" for item in locations)
        axes[RunInspectionAxisName.MATERIALIZATION] = RunInspectionAxis(
            RunInspectionAxisName.MATERIALIZATION,
            "materialization",
            "available" if materialization_available else "unavailable",
            (
                "populated"
                if artifact_count
                else "empty"
                if materialization_available
                else "unavailable"
            ),
            None,
            None,
            "current" if materialization_available else "unavailable",
            None if materialization_available else "owner_unavailable",
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
            queue_item_id=queue_item_id,
            admission_id=admission_id,
        )
        return _fit_response(result)

    def _project_managed(
        self,
        run_uri: str,
        axes: dict[RunInspectionAxisName, RunInspectionAxis],
        stages: list[RunInspectionStage],
    ) -> tuple[str | None, str | None, bool]:
        """Project one indexed managed admission and its targeted owner detail."""

        daemon = self._daemon
        assert daemon is not None
        from loom.queue import AdmissionNotFoundError

        try:
            admission = daemon.admission_for_run_uri(run_uri)
        except (AdmissionNotFoundError, FileNotFoundError, LookupError):
            axes[RunInspectionAxisName.ADMISSION] = _unavailable_axis(
                RunInspectionAxisName.ADMISSION,
                "coordinator",
                "admission_not_found",
            )
            return None, None, False
        except Exception:
            axes[RunInspectionAxisName.ADMISSION] = _unavailable_axis(
                RunInspectionAxisName.ADMISSION,
                "coordinator",
                "owner_unavailable",
            )
            return None, None, False
        axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
            RunInspectionAxisName.ADMISSION,
            "coordinator",
            "available",
            admission.state.value,
            None,
            admission.accepted_at,
            "current",
        )
        try:
            detail = daemon.admission(admission.admission_id)
        except Exception:
            return admission.admission_id, admission.queue_item_id, True
        owners = detail.owners
        for owner_key, axis_name in (
            ("scheduling", RunInspectionAxisName.SCHEDULING),
            ("assignment", RunInspectionAxisName.ASSIGNMENT),
            ("slurm", RunInspectionAxisName.EXTERNAL_SCHEDULER),
            ("execution", RunInspectionAxisName.TRANSFER_RESULT),
            ("cancellation", RunInspectionAxisName.CANCELLATION),
            ("service", RunInspectionAxisName.SERVICE_HEALTH),
        ):
            owner = owners.get(owner_key)
            if isinstance(owner, Mapping):
                axes[axis_name] = _owner_axis(axis_name, owner)
        authority = detail.authority
        lifecycle = axes[RunInspectionAxisName.LIFECYCLE]
        if lifecycle.availability != "available":
            axes[RunInspectionAxisName.LIFECYCLE] = _owner_axis(
                RunInspectionAxisName.LIFECYCLE,
                authority,
            )
            raw_stages = authority.get("stages")
            if isinstance(raw_stages, Mapping):
                for stage_name, state in sorted(raw_stages.items()):
                    if isinstance(stage_name, str) and isinstance(state, str):
                        stages.append(RunInspectionStage(stage_name, state))
        return admission.admission_id, admission.queue_item_id, True

    def _project_service_less_queue(
        self,
        run_uri: str,
        local_store: Any,
        axes: dict[RunInspectionAxisName, RunInspectionAxis],
        locations: list[RunInspectionLocation],
    ) -> tuple[str | None, bool]:
        """Read one retained operation and one queue primary key, never a scan."""
        try:
            operation = local_store.latest_submitted_operation(run_uri)
        except Exception:
            axes[RunInspectionAxisName.ADMISSION] = _unavailable_axis(
                RunInspectionAxisName.ADMISSION,
                "queue",
                "queue_reference_unavailable",
            )
            return None, False
        if operation is None:
            axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
                RunInspectionAxisName.ADMISSION,
                "queue",
                "unavailable",
                "unavailable",
                None,
                None,
                "unavailable",
                "queue_reference_unavailable",
            )
            return None, False
        queue = operation.backend_metadata.get("queue")
        queue_item_id = (
            queue.get("queue_item_id") if isinstance(queue, Mapping) else None
        )
        if not isinstance(queue_item_id, str):
            axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
                RunInspectionAxisName.ADMISSION,
                "queue",
                "unavailable",
                "unavailable",
                None,
                operation.updated_at,
                "unavailable",
                "queue_reference_missing",
            )
            return None, True
        queue_service = self._queue_service
        assert queue_service is not None
        try:
            item = queue_service.read_item(queue_item_id)
        except Exception:
            axes[RunInspectionAxisName.ADMISSION] = _unavailable_axis(
                RunInspectionAxisName.ADMISSION,
                "queue",
                "owner_unavailable",
                observed_at=operation.updated_at,
            )
            return queue_item_id, True
        if item is None or item.run_uri != run_uri:
            axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
                RunInspectionAxisName.ADMISSION,
                "queue",
                "unavailable",
                "unavailable",
                None,
                operation.updated_at,
                "unavailable",
                "queue_reference_mismatch",
            )
            return queue_item_id, True
        axes[RunInspectionAxisName.ADMISSION] = RunInspectionAxis(
            RunInspectionAxisName.ADMISSION,
            "queue",
            "available",
            item.status.value,
            item.dispatch_attempt,
            item.updated_at,
            "current",
        )
        axes[RunInspectionAxisName.SCHEDULING] = RunInspectionAxis(
            RunInspectionAxisName.SCHEDULING,
            "queue",
            "available",
            item.status.value,
            item.dispatch_attempt,
            item.updated_at,
            "current",
        )
        handle = item.dispatch_handle
        if handle is not None:
            recorded_item_id = handle.evidence.get("queue_item_id")
            if recorded_item_id != queue_item_id:
                axes[RunInspectionAxisName.ADMISSION] = _unavailable_axis(
                    RunInspectionAxisName.ADMISSION,
                    "queue",
                    "queue_reference_mismatch",
                    observed_at=operation.updated_at,
                )
                axes[RunInspectionAxisName.SCHEDULING] = _unavailable_axis(
                    RunInspectionAxisName.SCHEDULING,
                    "queue",
                    "queue_reference_mismatch",
                    observed_at=operation.updated_at,
                )
                return queue_item_id, True
            axes[RunInspectionAxisName.ASSIGNMENT] = RunInspectionAxis(
                RunInspectionAxisName.ASSIGNMENT,
                "queue",
                "available",
                "DISPATCHED",
                handle.dispatch_attempt,
                handle.dispatched_at,
                "current",
            )
        try:
            manifest = _read_slurm_manifest(local_store, run_uri, operation)
        except Exception:
            axes[RunInspectionAxisName.EXTERNAL_SCHEDULER] = _unavailable_axis(
                RunInspectionAxisName.EXTERNAL_SCHEDULER,
                "slurm",
                "owner_unavailable",
                observed_at=operation.updated_at,
            )
            return queue_item_id, True
        if manifest is not None:
            if manifest.queue_item_id != queue_item_id:
                axes[RunInspectionAxisName.EXTERNAL_SCHEDULER] = _unavailable_axis(
                    RunInspectionAxisName.EXTERNAL_SCHEDULER,
                    "slurm",
                    "queue_reference_mismatch",
                    observed_at=operation.updated_at,
                )
                return queue_item_id, True
            snapshots = tuple(manifest.status_snapshots)
            latest_snapshot = snapshots[-1] if snapshots else None
            axes[RunInspectionAxisName.EXTERNAL_SCHEDULER] = RunInspectionAxis(
                RunInspectionAxisName.EXTERNAL_SCHEDULER,
                "slurm",
                "available",
                (
                    latest_snapshot.state
                    if latest_snapshot is not None
                    else manifest.submission_status.value
                ),
                len(snapshots),
                (
                    latest_snapshot.captured_at
                    if latest_snapshot is not None
                    else manifest.updated_at
                ),
                "current",
            )
            axes[RunInspectionAxisName.TRANSFER_RESULT] = RunInspectionAxis(
                RunInspectionAxisName.TRANSFER_RESULT,
                "submitted-operation",
                "available",
                operation.state.value,
                None,
                operation.updated_at,
                "current",
            )
            cancellations = tuple(manifest.cancellation_attempts)
            axes[RunInspectionAxisName.CANCELLATION] = RunInspectionAxis(
                RunInspectionAxisName.CANCELLATION,
                "slurm",
                "available",
                cancellations[-1].outcome if cancellations else "not_requested",
                len(cancellations),
                cancellations[-1].attempted_at
                if cancellations
                else manifest.updated_at,
                "current",
            )
            for job in manifest.submitted_jobs:
                for stream, path in (
                    ("stdout", job.stdout_relative_path),
                    ("stderr", job.stderr_relative_path),
                ):
                    if path is not None:
                        locations.append(
                            _slurm_log_location(
                                local_store,
                                run_uri,
                                job.logical_key,
                                stream,
                                path,
                            )
                        )
        return queue_item_id, True


def inspect_run(
    run_uri: str,
    *,
    run_store: Any | None = None,
    daemon: Any | None = None,
    queue_service: Any | None = None,
) -> RunInspectionResponse:
    """Return one safe, bounded inspection result or a closed failure."""
    return RunInspectionProjection(
        run_store=run_store,
        daemon=daemon,
        queue_service=queue_service,
    ).inspect(run_uri)


def projection_callable(
    *,
    run_store: Any | None = None,
    daemon: Any | None = None,
    queue_service: Any | None = None,
) -> Callable[[str], Mapping[str, PlainData]]:
    """Return the plain-data callback accepted by lower transports."""
    projection = RunInspectionProjection(
        run_store=run_store,
        daemon=daemon,
        queue_service=queue_service,
    )
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


def _unavailable_axis(
    name: RunInspectionAxisName,
    owner: str,
    code: str,
    *,
    observed_at: str | None = None,
) -> RunInspectionAxis:
    return RunInspectionAxis(
        name,
        owner,
        "unavailable",
        "unavailable",
        None,
        observed_at,
        "unavailable",
        code,
    )


def _owner_axis(
    name: RunInspectionAxisName,
    owner: Mapping[str, object],
) -> RunInspectionAxis:
    owner_name = owner.get("owner")
    availability = owner.get("availability")
    state = owner.get("state")
    observed_at = owner.get("observed_at")
    freshness = owner.get("freshness")
    diagnostic = owner.get("diagnostic")
    safe_availability: str = (
        availability
        if isinstance(availability, str)
        and availability in {"available", "unavailable", "degraded"}
        else "unavailable"
    )
    safe_freshness: str = (
        freshness
        if isinstance(freshness, str)
        and freshness in {"current", "stale", "unavailable", "unknown"}
        else "unavailable"
    )
    return RunInspectionAxis(
        name,
        owner_name if isinstance(owner_name, str) and owner_name else "unavailable",
        safe_availability,
        state if isinstance(state, str) and state else "unavailable",
        _axis_revision(owner.get("revision")),
        observed_at if isinstance(observed_at, str) and observed_at else None,
        safe_freshness,
        (
            diagnostic
            if isinstance(diagnostic, str)
            and diagnostic
            and diagnostic
            in {
                "agent_journal_unavailable",
                "authority_unavailable",
                "execution_store_unavailable",
                "owner_status_unavailable",
            }
            else "owner_unavailable"
            if safe_availability != "available"
            else None
        ),
    )


def _axis_revision(value: object) -> int | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, Mapping):
        sequence = value.get("sequence")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            return sequence
    return None


def _append_stage_log_locations(
    local_store: Any,
    run_uri: str,
    stage_name: str,
    locations: list[RunInspectionLocation],
) -> None:
    locator = getattr(local_store, "local_stage_log_path", None)
    if not callable(locator):
        return
    for stream in ("stdout", "stderr"):
        try:
            path = Path(cast(str | Path, locator(run_uri, stage_name, stream)))
            available = path.is_file()
            uri = path.resolve(strict=False).as_uri()
        except (OSError, TypeError, ValueError):
            continue
        locations.append(
            RunInspectionLocation(
                f"log:{stage_name}:{stream}",
                uri,
                "log",
                "available" if available else "recorded",
                None,
                None,
                RunLocationReachability.COORDINATOR_LOCAL,
            )
        )


def _slurm_log_location(
    local_store: Any,
    run_uri: str,
    logical_key: str,
    stream: str,
    relative_path: str,
) -> RunInspectionLocation:
    from loom.pipeline.executors.slurm.paths import (
        resolve_slurm_generated_artifact_path,
    )

    paths = getattr(local_store, "paths", local_store)
    path = resolve_slurm_generated_artifact_path(
        paths,
        run_uri,
        relative_path,
    ).local_path
    try:
        available = path.is_file()
    except OSError:
        available = False
    return RunInspectionLocation(
        f"log:{logical_key}:{stream}",
        path.resolve(strict=False).as_uri(),
        "log",
        "available" if available else "recorded",
        None,
        None,
        RunLocationReachability.SHARED_UNKNOWN,
    )


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
    from loom.pipeline.executors.slurm.paths import (
        resolve_slurm_generated_artifact_path,
    )

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
            RunInspectionTruncation(
                "stages",
                result.truncation[0].total_count,
                len(stages),
            ),
            RunInspectionTruncation(
                "locations",
                result.truncation[1].total_count,
                len(locations),
            ),
        )
        candidate = RunInspectionResult(
            run_uri=result.run_uri,
            as_of=result.as_of,
            summary=result.summary,
            axes=result.axes,
            stages=tuple(stages),
            locations=tuple(locations),
            truncation=truncation,
            queue_item_id=result.queue_item_id,
            admission_id=result.admission_id,
        )
        encoded = json.dumps(
            {"ok": True, "result": candidate.to_dict()},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) <= MAX_INSPECTION_RESPONSE_BYTES:
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
