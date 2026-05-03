"""Same-run-directory resume checks for planning."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar, cast

from loom.artifacts import ArtifactRef
from loom.pipeline.specs import StageSpec
from loom.pipeline.status import StageStatus
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.errors import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactStoreError,
    ArtifactTypeMismatchError,
    CorruptStoreDocumentError,
    StoreError,
)
from loom.pipeline.stores.indexes import format_artifact_key
from loom.pipeline.stores.run_store import RunStore
from loom.serialization import PlainData

from .errors import ResumeStateError
from .models import (
    PlanAction,
    PlanReason,
    PlanReasonCode,
    ResumeCheck,
    ResumeOptions,
    StageFingerprintRecord,
)

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class DirectResumeResult:
    base_action: PlanAction
    final_action: PlanAction
    check: ResumeCheck


def check_stage_resume(
    stage: StageSpec,
    *,
    run_id: str,
    run_store: RunStore,
    artifact_store: ArtifactStore,
    current_fingerprint: StageFingerprintRecord | None,
    resume: ResumeOptions,
    eligible_to_run: bool,
) -> DirectResumeResult:
    """Check whether a single stage has reusable prior state."""

    if not resume.enabled:
        return _result(
            stage.name,
            base_action=PlanAction.RUN,
            eligible_to_run=eligible_to_run,
            status=None,
            attempt=None,
            prior_fingerprint=None,
            current_fingerprint=current_fingerprint,
            inputs={},
            outputs={},
            reasons=[
                _reason(
                    PlanReasonCode.RESUME_DISABLED, stage.name, "resume is disabled"
                )
            ],
        )

    status = _read_prior(run_store.read_stage_status, run_id, stage.name)
    if status is None:
        return _result(
            stage.name,
            base_action=PlanAction.RUN,
            eligible_to_run=eligible_to_run,
            status=None,
            attempt=None,
            prior_fingerprint=None,
            current_fingerprint=current_fingerprint,
            inputs={},
            outputs={},
            reasons=[
                _reason(
                    PlanReasonCode.NO_PRIOR_STATUS,
                    stage.name,
                    "no prior stage status exists",
                )
            ],
        )

    status_value = status.status.value
    if status.status != StageStatus.SUCCEEDED:
        code = (
            PlanReasonCode.PRIOR_STATUS_RUNNING
            if status.status == StageStatus.RUNNING
            else PlanReasonCode.PRIOR_STATUS_NOT_SUCCEEDED
        )
        return _result(
            stage.name,
            base_action=PlanAction.RUN,
            eligible_to_run=eligible_to_run,
            status=status_value,
            attempt=status.attempt,
            prior_fingerprint=None,
            current_fingerprint=current_fingerprint,
            inputs={},
            outputs={},
            reasons=[_reason(code, stage.name, f"prior status is {status_value}")],
        )

    prior_inputs = _read_prior(run_store.read_stage_inputs, run_id, stage.name)
    if prior_inputs is None:
        return _stale_result(
            stage.name,
            eligible_to_run,
            status_value,
            status.attempt,
            None,
            current_fingerprint,
            {},
            {},
            _reason(
                PlanReasonCode.MISSING_INPUTS,
                stage.name,
                "prior inputs.json is missing",
            ),
        )

    prior_fingerprint_data = _read_prior(
        run_store.read_stage_fingerprint, run_id, stage.name
    )
    if prior_fingerprint_data is None:
        return _stale_result(
            stage.name,
            eligible_to_run,
            status_value,
            status.attempt,
            None,
            current_fingerprint,
            prior_inputs,
            {},
            _reason(
                PlanReasonCode.MISSING_FINGERPRINT,
                stage.name,
                "prior fingerprint.json is missing",
            ),
        )
    prior_fingerprint = _parse_prior_fingerprint(stage.name, prior_fingerprint_data)

    prior_outputs = _read_prior(run_store.read_stage_outputs, run_id, stage.name)
    if prior_outputs is None:
        return _stale_result(
            stage.name,
            eligible_to_run,
            status_value,
            status.attempt,
            prior_fingerprint,
            current_fingerprint,
            prior_inputs,
            {},
            _reason(
                PlanReasonCode.MISSING_OUTPUTS,
                stage.name,
                "prior outputs.json is missing",
            ),
        )

    if current_fingerprint is None:
        return _stale_result(
            stage.name,
            eligible_to_run,
            status_value,
            status.attempt,
            prior_fingerprint,
            None,
            prior_inputs,
            prior_outputs,
            _reason(
                PlanReasonCode.MISSING_FINGERPRINT,
                stage.name,
                "current fingerprint is pending",
            ),
        )

    policy_reason = _fingerprint_policy_reason(
        stage.name, prior_fingerprint, current_fingerprint
    )
    if policy_reason is not None:
        return _stale_result(
            stage.name,
            eligible_to_run,
            status_value,
            status.attempt,
            prior_fingerprint,
            current_fingerprint,
            prior_inputs,
            prior_outputs,
            policy_reason,
        )
    if prior_fingerprint.fingerprint != current_fingerprint.fingerprint:
        return _stale_result(
            stage.name,
            eligible_to_run,
            status_value,
            status.attempt,
            prior_fingerprint,
            current_fingerprint,
            prior_inputs,
            prior_outputs,
            _reason(
                PlanReasonCode.FINGERPRINT_CHANGED,
                stage.name,
                "stage fingerprint changed",
            ),
        )

    output_reason = _output_spec_reason(stage, prior_outputs)
    if output_reason is not None:
        return _stale_result(
            stage.name,
            eligible_to_run,
            status_value,
            status.attempt,
            prior_fingerprint,
            current_fingerprint,
            prior_inputs,
            prior_outputs,
            output_reason,
        )

    _validate_artifact_index(run_store, run_id, stage.name, prior_outputs)

    reasons = [
        _reason(
            PlanReasonCode.FINGERPRINT_MATCH, stage.name, "prior fingerprint matches"
        )
    ]
    for output_name, ref in prior_outputs.items():
        validation_reason = _validate_artifact(artifact_store, stage, output_name, ref)
        if validation_reason is not None:
            return _stale_result(
                stage.name,
                eligible_to_run,
                status_value,
                status.attempt,
                prior_fingerprint,
                current_fingerprint,
                prior_inputs,
                prior_outputs,
                validation_reason,
            )
        reasons.append(
            _reason(
                PlanReasonCode.ARTIFACT_VALIDATED,
                stage.name,
                f"artifact {stage.name}.{output_name} validated",
                output_name=output_name,
            ),
        )

    check = ResumeCheck(
        stage_name=stage.name,
        action=PlanAction.REUSE,
        status=status_value,
        attempt=status.attempt,
        prior_fingerprint=prior_fingerprint,
        current_fingerprint=current_fingerprint,
        inputs=prior_inputs,
        outputs=prior_outputs,
        reasons=tuple(reasons),
    )
    return DirectResumeResult(
        base_action=PlanAction.REUSE, final_action=PlanAction.REUSE, check=check
    )


def _result(
    stage_name: str,
    *,
    base_action: PlanAction,
    eligible_to_run: bool,
    status: str | None,
    attempt: int | None,
    prior_fingerprint: StageFingerprintRecord | None,
    current_fingerprint: StageFingerprintRecord | None,
    inputs: dict[str, ArtifactRef],
    outputs: dict[str, ArtifactRef],
    reasons: list[PlanReason],
) -> DirectResumeResult:
    if base_action == PlanAction.REUSE:
        final_action = PlanAction.REUSE
    elif eligible_to_run:
        final_action = PlanAction.RUN
    else:
        final_action = PlanAction.BLOCKED
    check = ResumeCheck(
        stage_name=stage_name,
        action=final_action,
        status=status,
        attempt=attempt,
        prior_fingerprint=prior_fingerprint,
        current_fingerprint=current_fingerprint,
        inputs=inputs,
        outputs=outputs,
        reasons=tuple(reasons),
    )
    return DirectResumeResult(
        base_action=base_action, final_action=final_action, check=check
    )


def _stale_result(
    stage_name: str,
    eligible_to_run: bool,
    status: str | None,
    attempt: int | None,
    prior_fingerprint: StageFingerprintRecord | None,
    current_fingerprint: StageFingerprintRecord | None,
    inputs: dict[str, ArtifactRef],
    outputs: dict[str, ArtifactRef],
    reason: PlanReason,
) -> DirectResumeResult:
    return _result(
        stage_name,
        base_action=PlanAction.STALE,
        eligible_to_run=eligible_to_run,
        status=status,
        attempt=attempt,
        prior_fingerprint=prior_fingerprint,
        current_fingerprint=current_fingerprint,
        inputs=inputs,
        outputs=outputs,
        reasons=[reason],
    )


def _read_prior(method: Callable[[str, str], _T], run_id: str, stage_name: str) -> _T:
    try:
        return method(run_id, stage_name)  # type: ignore[misc]
    except CorruptStoreDocumentError as exc:
        raise ResumeStateError(f"corrupt prior state for {stage_name}: {exc}") from exc
    except StoreError as exc:
        raise ResumeStateError(
            f"could not read prior state for {stage_name}: {exc}"
        ) from exc


def _parse_prior_fingerprint(stage_name: str, data: object) -> StageFingerprintRecord:
    try:
        return StageFingerprintRecord.from_dict(data)
    except Exception as exc:
        raise ResumeStateError(
            f"malformed prior fingerprint for stage {stage_name!r}: {exc}"
        ) from exc


def _fingerprint_policy_reason(
    stage_name: str,
    prior: StageFingerprintRecord,
    current: StageFingerprintRecord,
) -> PlanReason | None:
    if (
        prior.schema_version != current.schema_version
        or prior.algorithm != current.algorithm
        or prior.policy_name != current.policy_name
        or prior.policy_version != current.policy_version
    ):
        return _reason(
            PlanReasonCode.FINGERPRINT_POLICY_CHANGED,
            stage_name,
            "stage fingerprint policy changed",
        )
    return None


def _output_spec_reason(
    stage: StageSpec, outputs: dict[str, ArtifactRef]
) -> PlanReason | None:
    if set(outputs) != set(stage.outputs):
        return _reason(
            PlanReasonCode.MISSING_OUTPUT_REF,
            stage.name,
            "prior outputs do not match declared outputs",
            details=cast(
                dict[str, PlainData],
                {"expected": sorted(stage.outputs), "actual": sorted(outputs)},
            ),
        )
    for output_name, output_spec in stage.outputs.items():
        ref = outputs[output_name]
        if ref.artifact_type != output_spec.artifact_type:
            return _reason(
                PlanReasonCode.OUTPUT_SPEC_MISMATCH,
                stage.name,
                f"artifact type mismatch for {stage.name}.{output_name}",
                output_name=output_name,
                details={
                    "expected": output_spec.artifact_type,
                    "actual": ref.artifact_type,
                },
            )
        if output_spec.codec_key is not None and ref.codec_key != output_spec.codec_key:
            return _reason(
                PlanReasonCode.OUTPUT_SPEC_MISMATCH,
                stage.name,
                f"codec mismatch for {stage.name}.{output_name}",
                output_name=output_name,
                details={"expected": output_spec.codec_key, "actual": ref.codec_key},
            )
    return None


def _validate_artifact_index(
    run_store: RunStore,
    run_id: str,
    stage_name: str,
    outputs: dict[str, ArtifactRef],
) -> None:
    try:
        index = run_store.read_artifact_index(run_id)
    except CorruptStoreDocumentError as exc:
        raise ResumeStateError(
            f"corrupt artifact index for run {run_id!r}: {exc}"
        ) from exc
    except StoreError as exc:
        raise ResumeStateError(
            f"could not read artifact index for run {run_id!r}: {exc}"
        ) from exc
    for output_name, ref in outputs.items():
        key = format_artifact_key(stage_name, output_name)
        if key in index and index[key] != ref:
            raise ResumeStateError(
                f"artifact index conflict for {key}: index ref differs from stage outputs",
            )


def _validate_artifact(
    artifact_store: ArtifactStore,
    stage: StageSpec,
    output_name: str,
    ref: ArtifactRef,
) -> PlanReason | None:
    try:
        artifact_store.validate(
            ref, expected_type=stage.outputs[output_name].artifact_type
        )
    except ArtifactNotFoundError as exc:
        return _reason(
            PlanReasonCode.ARTIFACT_MISSING,
            stage.name,
            str(exc),
            output_name=output_name,
        )
    except ArtifactChecksumMismatchError as exc:
        return _reason(
            PlanReasonCode.ARTIFACT_CHECKSUM_MISMATCH,
            stage.name,
            str(exc),
            output_name=output_name,
        )
    except (ArtifactTypeMismatchError, ArtifactStoreError) as exc:
        return _reason(
            PlanReasonCode.ARTIFACT_VALIDATION_FAILED,
            stage.name,
            str(exc),
            output_name=output_name,
            details={"error_type": type(exc).__name__},
        )
    return None


def _reason(
    code: PlanReasonCode,
    stage_name: str,
    message: str,
    *,
    output_name: str | None = None,
    details: Mapping[str, PlainData] | None = None,
) -> PlanReason:
    return PlanReason(
        code=code,
        message=message,
        stage_name=stage_name,
        output_name=output_name,
        details=details or {},
    )


__all__ = ["DirectResumeResult", "check_stage_resume"]
