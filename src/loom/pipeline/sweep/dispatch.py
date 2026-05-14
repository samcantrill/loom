"""Adapter-neutral dispatch intent and dispatch outcome records."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from loom.serialization import PlainData, PlainDataError, ensure_plain_data
from loom.timestamps import utc_timestamp

from .errors import SweepProtocolError

if TYPE_CHECKING:
    from loom.pipeline.execution import RunRequest

    from .runner import SweepPlan
    from .trials import SweepTrialRecord


class SweepDispatchStatus(StrEnum):
    """Lifecycle outcomes for a dispatch attempt."""

    PLANNED = "planned"
    ACCEPTED = "accepted"
    QUEUED = "queued"
    SUBMITTED = "submitted"
    DISPATCHED = "dispatched"
    REJECTED = "rejected"
    FAILED = "failed"


class SweepRunStatus(StrEnum):
    """Aggregate outcome for direct sweep dispatch."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


SWEEP_DISPATCH_SCHEMA_VERSION = 1


def _required(mapping: Mapping[str, object], field_name: str) -> object:
    if field_name not in mapping:
        raise SweepProtocolError(f"missing required field {field_name!r}")
    return mapping[field_name]


def _reject_unknown(mapping: Mapping[str, object], allowed: set[str], *, object_name: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SweepProtocolError(
            f"{object_name} payload has unknown field(s): {fields}"
        )


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SweepProtocolError(f"{field_name} must be a string when set")
    if not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty string when set")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SweepProtocolError(f"{field_name} must be a non-negative integer")
    return value


def _plain_mapping(value: object, field_name: str) -> dict[str, PlainData]:
    if not isinstance(value, Mapping):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    try:
        normalized = ensure_plain_data(value, path=field_name)
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError(f"{field_name} must contain plain data") from exc
    if not isinstance(normalized, dict):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    return dict(normalized)


@dataclass(frozen=True, slots=True)
class SweepDispatchRequest:
    """Adapter-neutral planned sweep dispatch intent."""

    sweep_id: str
    trial_id: str
    trial_index: int
    requested_at: str
    schema_version: int = SWEEP_DISPATCH_SCHEMA_VERSION
    run_uri: str | None = None
    provider_trial_id: str | None = None
    request_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SWEEP_DISPATCH_SCHEMA_VERSION:
            raise SweepProtocolError(
                "SweepDispatchRequest.schema_version must be 1"
            )
        object.__setattr__(self, "sweep_id", _text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "trial_id", _text(self.trial_id, "trial_id"))
        object.__setattr__(
            self,
            "trial_index",
            _non_negative_int(self.trial_index, "trial_index"),
        )
        object.__setattr__(
            self, "requested_at", _text(self.requested_at, "requested_at")
        )
        object.__setattr__(self, "run_uri", _optional_text(self.run_uri, "run_uri"))
        object.__setattr__(
            self,
            "provider_trial_id",
            _optional_text(self.provider_trial_id, "provider_trial_id"),
        )
        object.__setattr__(
            self,
            "request_metadata",
            _plain_mapping(self.request_metadata, "request_metadata"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "sweep_id": self.sweep_id,
            "trial_id": self.trial_id,
            "trial_index": self.trial_index,
            "requested_at": self.requested_at,
            "run_uri": self.run_uri,
            "provider_trial_id": self.provider_trial_id,
            "request_metadata": dict(self.request_metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepDispatchRequest":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepDispatchRequest payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "sweep_id",
                "trial_id",
                "trial_index",
                "requested_at",
                "run_uri",
                "provider_trial_id",
                "request_metadata",
            },
            object_name="SweepDispatchRequest",
        )
        return cls(
            schema_version=_non_negative_int(
                _required(data, "schema_version"), "schema_version"
            ),
            sweep_id=_text(_required(data, "sweep_id"), "sweep_id"),
            trial_id=_text(_required(data, "trial_id"), "trial_id"),
            trial_index=_non_negative_int(
                _required(data, "trial_index"), "trial_index"
            ),
            requested_at=_text(_required(data, "requested_at"), "requested_at"),
            run_uri=_optional_text(data.get("run_uri"), "run_uri"),
            provider_trial_id=_optional_text(
                data.get("provider_trial_id"),
                "provider_trial_id",
            ),
            request_metadata=_plain_mapping(
                data.get("request_metadata", {}), "request_metadata"
            ),
        )


@dataclass(frozen=True, slots=True)
class SweepDispatchResult:
    """Adapter-neutral sweep dispatch outcome."""

    request: SweepDispatchRequest
    status: SweepDispatchStatus
    schema_version: int = SWEEP_DISPATCH_SCHEMA_VERSION
    run_uri: str | None = None
    dispatched_at: str | None = None
    reason: str | None = None
    result_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SWEEP_DISPATCH_SCHEMA_VERSION:
            raise SweepProtocolError(
                "SweepDispatchResult.schema_version must be 1"
            )
        if not isinstance(self.request, SweepDispatchRequest):
            raise SweepProtocolError("request must be a SweepDispatchRequest")
        object.__setattr__(
            self,
            "status",
            SweepDispatchStatus(self.status),
        )
        object.__setattr__(self, "run_uri", _optional_text(self.run_uri, "run_uri"))
        if self.dispatched_at is not None:
            object.__setattr__(
                self, "dispatched_at", _text(self.dispatched_at, "dispatched_at")
            )
        if self.reason is not None:
            object.__setattr__(self, "reason", _text(self.reason, "reason"))
        else:
            object.__setattr__(self, "reason", None)
        object.__setattr__(
            self,
            "result_metadata",
            _plain_mapping(self.result_metadata, "result_metadata"),
        )

    @property
    def sweep_id(self) -> str:
        return self.request.sweep_id

    @property
    def trial_id(self) -> str:
        return self.request.trial_id

    @property
    def trial_index(self) -> int:
        return self.request.trial_index

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "run_uri": self.run_uri,
            "dispatched_at": self.dispatched_at,
            "reason": self.reason,
            "result_metadata": dict(self.result_metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepDispatchResult":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepDispatchResult payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "request",
                "status",
                "run_uri",
                "dispatched_at",
                "reason",
                "result_metadata",
            },
            object_name="SweepDispatchResult",
        )
        request = data.get("request")
        if not isinstance(request, Mapping):
            raise SweepProtocolError("request must be a mapping")
        status = data.get("status")
        if status is None:
            raise SweepProtocolError("status is required")
        return cls(
            schema_version=_non_negative_int(
                _required(data, "schema_version"), "schema_version"
            ),
            request=SweepDispatchRequest.from_dict(request),
            status=cast_status(status, "status"),
            run_uri=_optional_text(data.get("run_uri"), "run_uri"),
            dispatched_at=_optional_text(data.get("dispatched_at"), "dispatched_at"),
            reason=_optional_text(data.get("reason"), "reason"),
            result_metadata=_plain_mapping(data.get("result_metadata", {}), "result_metadata"),
        )


def _normalize_results(values: Sequence[object], *, field: str) -> tuple[SweepDispatchResult, ...]:
    normalized: list[SweepDispatchResult] = []
    for index, value in enumerate(values):
        if isinstance(value, SweepDispatchResult):
            normalized.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepProtocolError(f"{field}[{index}] must be a mapping or SweepDispatchResult")
        normalized.append(SweepDispatchResult.from_dict(value))
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class DirectSweepTrialResult:
    """Direct-dispatch outcome for one planned trial."""

    dispatch_result: SweepDispatchResult
    run_result: object | None = None
    required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.dispatch_result, SweepDispatchResult):
            raise SweepProtocolError("dispatch_result must be SweepDispatchResult")
        if not isinstance(self.required, bool):
            raise SweepProtocolError("required must be a bool")

    @property
    def sweep_id(self) -> str:
        return self.dispatch_result.sweep_id

    @property
    def trial_id(self) -> str:
        return self.dispatch_result.trial_id

    @property
    def run_uri(self) -> str | None:
        return self.dispatch_result.run_uri

    @property
    def run_status(self) -> str | None:
        return _run_status_value(self.run_result)

    @property
    def early_stopped(self) -> bool:
        return (
            self.run_status == "CANCELLED"
            and _run_result_reason_code(self.run_result) == "early_stop"
        )

    @property
    def failed(self) -> bool:
        return self.dispatch_result.status == SweepDispatchStatus.FAILED or (
            self.required and self.run_status == "FAILED"
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "dispatch_result": self.dispatch_result.to_dict(),
            "run_uri": self.run_uri,
            "run_status": self.run_status,
            "required": self.required,
            "early_stopped": self.early_stopped,
            "failed": self.failed,
        }


@dataclass(frozen=True, slots=True)
class DirectSweepRunResult:
    """Aggregate result for direct sequential sweep dispatch."""

    sweep_id: str
    status: SweepRunStatus
    trial_results: Sequence[DirectSweepTrialResult]
    started_at: str
    finished_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sweep_id", _text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "status", SweepRunStatus(self.status))
        object.__setattr__(
            self,
            "trial_results",
            _normalize_direct_trial_results(self.trial_results),
        )
        object.__setattr__(self, "started_at", _text(self.started_at, "started_at"))
        object.__setattr__(self, "finished_at", _text(self.finished_at, "finished_at"))

    @property
    def trial_count(self) -> int:
        return len(self.trial_results)

    @property
    def succeeded_count(self) -> int:
        return sum(1 for result in self.trial_results if result.run_status == "SUCCEEDED")

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.trial_results if result.failed)

    @property
    def early_stopped_count(self) -> int:
        return sum(1 for result in self.trial_results if result.early_stopped)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "sweep_id": self.sweep_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "trial_count": self.trial_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "early_stopped_count": self.early_stopped_count,
            "trial_results": [result.to_dict() for result in self.trial_results],
        }


def build_dispatch_requests(
    plan: "SweepPlan",
    *,
    requested_at: str | None = None,
) -> tuple[SweepDispatchRequest, ...]:
    """Build direct/queue-neutral dispatch intents from a finite sweep plan."""

    timestamp = requested_at or utc_timestamp()
    requests: list[SweepDispatchRequest] = []
    for trial in plan.trials:
        requests.append(
            SweepDispatchRequest(
                sweep_id=plan.sweep_id,
                trial_id=trial.trial_id,
                trial_index=trial.trial_index,
                requested_at=timestamp,
                run_uri=trial.run_uri,
                provider_trial_id=trial.provider_trial_id,
                request_metadata=_trial_request_metadata(trial),
            )
        )
    return tuple(requests)


def build_trial_run_request(
    template: "RunRequest",
    trial: "SweepTrialRecord",
    dispatch_request: SweepDispatchRequest,
    *,
    open_existing: bool = False,
) -> "RunRequest":
    """Return a `RunRequest` for one planned trial without applying overrides."""

    from loom.pipeline.execution import FailurePolicy, RunRequest
    from loom.pipeline.runtime import parse_run_options

    if not isinstance(template, RunRequest):
        raise SweepProtocolError("template must be RunRequest")
    if dispatch_request.trial_id != trial.trial_id:
        raise SweepProtocolError("dispatch request trial_id does not match trial")
    if dispatch_request.sweep_id != trial.sweep_id:
        raise SweepProtocolError("dispatch request sweep_id does not match trial")
    if trial.run_uri is None:
        raise SweepProtocolError("direct dispatch requires planned trial run_uri")
    option_data = parse_run_options(template.options).to_dict()
    option_data["run_uri"] = trial.run_uri
    metadata = {
        **dict(template.metadata),
        "sweep_id": trial.sweep_id,
        "trial_id": trial.trial_id,
        "trial_index": trial.trial_index,
        "provider_trial_id": trial.provider_trial_id,
        "proposal_overrides": dict(trial.proposal_overrides),
        "dispatch_request": dispatch_request.to_dict(),
    }
    return RunRequest(
        config=template.config,
        pipeline=template.pipeline,
        run_uri=trial.run_uri,
        open_existing=open_existing,
        options=option_data,
        selectors=template.selectors,
        resume=template.resume,
        fingerprint_context=template.fingerprint_context,
        config_snapshots=template.config_snapshots,
        provenance_options=template.provenance_options,
        command=template.command,
        project_root=template.project_root,
        failure_policy=FailurePolicy(stop_on_first_failure=True),
        metadata=metadata,
    )


def run_sweep_direct(
    plan: "SweepPlan",
    *,
    runner: Any,
    request_template: "RunRequest",
    request_factory: Callable[["SweepTrialRecord", SweepDispatchRequest], "RunRequest"] | None = None,
    runner_factory: Callable[["SweepTrialRecord", SweepDispatchRequest, "RunRequest"], Any] | None = None,
    sweep_dir: str | None = None,
    open_existing: bool = False,
    requested_at: str | None = None,
) -> DirectSweepRunResult:
    """Run planned trials sequentially through a `PipelineRunner`-like object."""

    from .runner import check_existing_sweep_plan, write_sweep_plan

    if sweep_dir is not None:
        compatibility = check_existing_sweep_plan(sweep_dir, expected_plan=plan)
        if compatibility.diagnostics:
            codes = ", ".join(
                diagnostic.code for diagnostic in compatibility.diagnostics
            )
            raise SweepProtocolError(f"incompatible existing sweep plan: {codes}")
        if compatibility.sweep_manifest is None or compatibility.trials_manifest is None:
            write_sweep_plan(plan, sweep_dir)

    started_at = requested_at or utc_timestamp()
    dispatch_requests = build_dispatch_requests(plan, requested_at=started_at)
    trial_results: list[DirectSweepTrialResult] = []
    for trial, dispatch_request in zip(plan.trials, dispatch_requests, strict=True):
        try:
            base_request = (
                request_factory(trial, dispatch_request)
                if request_factory is not None
                else request_template
            )
            run_request = build_trial_run_request(
                base_request,
                trial,
                dispatch_request,
                open_existing=open_existing,
            )
            trial_runner = (
                runner_factory(trial, dispatch_request, run_request)
                if runner_factory is not None
                else runner
            )
            run_result = trial_runner.run(run_request)
        except Exception as exc:  # noqa: BLE001 - dispatch failures are per-trial.
            dispatch_result = SweepDispatchResult(
                request=dispatch_request,
                status=SweepDispatchStatus.FAILED,
                run_uri=dispatch_request.run_uri,
                dispatched_at=utc_timestamp(),
                reason=str(exc) or type(exc).__name__,
                result_metadata={
                    "exception_type": f"{type(exc).__module__}.{type(exc).__name__}",
                },
            )
            trial_results.append(
                DirectSweepTrialResult(
                    dispatch_result=dispatch_result,
                    run_result=None,
                )
            )
            continue

        dispatch_result = SweepDispatchResult(
            request=dispatch_request,
            status=SweepDispatchStatus.DISPATCHED,
            run_uri=run_request.run_uri,
            dispatched_at=getattr(run_result, "finished_at", utc_timestamp()),
            result_metadata={
                "run_status": _run_status_value(run_result),
            },
        )
        trial_results.append(
            DirectSweepTrialResult(
                dispatch_result=dispatch_result,
                run_result=run_result,
            )
        )

    failed = any(result.failed for result in trial_results)
    return DirectSweepRunResult(
        sweep_id=plan.sweep_id,
        status=SweepRunStatus.FAILED if failed else SweepRunStatus.SUCCEEDED,
        trial_results=tuple(trial_results),
        started_at=started_at,
        finished_at=utc_timestamp(),
    )


def _normalize_direct_trial_results(
    values: Sequence[DirectSweepTrialResult],
) -> tuple[DirectSweepTrialResult, ...]:
    normalized: list[DirectSweepTrialResult] = []
    for value in values:
        if not isinstance(value, DirectSweepTrialResult):
            raise SweepProtocolError(
                "trial_results must contain DirectSweepTrialResult values"
            )
        normalized.append(value)
    return tuple(normalized)


def _trial_request_metadata(trial: "SweepTrialRecord") -> dict[str, PlainData]:
    return {
        "proposal_overrides": dict(trial.proposal_overrides),
        "trial_metadata": dict(trial.metadata),
    }


def _run_status_value(run_result: object | None) -> str | None:
    if run_result is None:
        return None
    raw = getattr(run_result, "status", None)
    value = getattr(raw, "value", raw)
    return value if isinstance(value, str) else None


def _run_result_reason_code(run_result: object | None) -> str | None:
    raw_metadata = getattr(run_result, "metadata", None)
    if not isinstance(raw_metadata, Mapping):
        return None
    raw_reason = raw_metadata.get("reason")
    if isinstance(raw_reason, Mapping):
        code = raw_reason.get("code")
        return code if isinstance(code, str) else None
    code = raw_metadata.get("reason_code")
    return code if isinstance(code, str) else None


def cast_status(value: object, field_name: str) -> SweepDispatchStatus:
    if isinstance(value, SweepDispatchStatus):
        return value
    if not isinstance(value, str):
        raise SweepProtocolError(f"{field_name} must be a SweepDispatchStatus")
    try:
        return SweepDispatchStatus(value)
    except ValueError as exc:
        raise SweepProtocolError(
            f"{field_name} must be a valid SweepDispatchStatus"
        ) from exc


__all__ = [
    "SWEEP_DISPATCH_SCHEMA_VERSION",
    "SweepDispatchRequest",
    "SweepDispatchResult",
    "SweepDispatchStatus",
]
