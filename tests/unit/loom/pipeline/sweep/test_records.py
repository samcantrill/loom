"""Unit tests for sweep contracts and model-level invariants."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from loom.serialization import PlainData
from loom.pipeline.sweep import (
    SWEEP_EXTRACTION_SCHEMA_VERSION,
    SWEEP_MANIFEST_SCHEMA_VERSION,
    SWEEP_FEEDBACK_SCHEMA_VERSION,
    SWEEP_DISPATCH_SCHEMA_VERSION,
    SWEEP_MANIFEST_FILE_NAME,
    TRIALS_MANIFEST_FILE_NAME,
    SweepDispatchRequest,
    SweepDispatchResult,
    SweepDispatchStatus,
    SweepExtractionRequest,
    SweepExtractionResult,
    SweepExtractionStatus,
    SweepFeedbackObservation,
    SweepFeedbackStatus,
    SweepManifest,
    SweepProtocolError,
    SweepProviderIdentity,
    SweepProviderContext,
    SweepTrialFeedbackRecord,
    SweepTrialRecord,
    TrialProposal,
    TrialsManifest,
    check_sweep_manifest_payload,
    check_trials_manifest_payload,
    read_sweep_manifest,
    read_trials_manifest,
    write_sweep_manifest,
    write_trials_manifest,
    unsupported_extraction,
)


def _sample_provider() -> SweepProviderIdentity:
    return SweepProviderIdentity(
        provider_name="provider-a",
        provider_type="fake",
        version="1",
        metadata={"region": "unit"},
    )


def test_sweep_records_round_trip_and_plain_metadata() -> None:
    context = SweepProviderContext(sweep_id="sweep-1", sweep_name="unit-sweep", metadata={"kind": "unit"})
    context_restored = SweepProviderContext.from_dict(context.to_dict())
    assert context_restored == context

    proposal = TrialProposal(
        provider_trial_id="provider-1",
        trial_index=0,
        overrides={"lr": 0.1, "flags": ["a", "b"]},
        metadata={"created_by": "unit"},
    )
    restored_proposal = TrialProposal.from_dict(proposal.to_dict())
    assert restored_proposal == proposal

    manifest = SweepManifest(
        sweep_id="sweep-1",
        provider=_sample_provider(),
        created_at="2020-01-01T00:00:00Z",
        sweep_name="unit-sweep",
        trial_count=1,
        metadata={"owner": "unit-test"},
    )
    assert manifest.schema_version == SWEEP_MANIFEST_SCHEMA_VERSION
    assert manifest.to_dict()["schema_version"] == SWEEP_MANIFEST_SCHEMA_VERSION


def test_dispatch_record_round_trip() -> None:
    request = SweepDispatchRequest(
        sweep_id="sweep-1",
        trial_id="trial-1",
        trial_index=0,
        requested_at="2020-01-01T00:00:00Z",
    )
    result = SweepDispatchResult(
        request=request,
        status=SweepDispatchStatus.ACCEPTED,
        dispatched_at="2020-01-01T00:00:01Z",
        result_metadata={"backend": "local"},
    )

    assert request.to_dict()["schema_version"] == SWEEP_DISPATCH_SCHEMA_VERSION
    assert result.to_dict()["status"] == "accepted"
    assert SweepDispatchResult.from_dict(result.to_dict()) == result


def test_feedback_record_carries_observations_and_status() -> None:
    observation = SweepFeedbackObservation(
        key="accuracy",
        value=0.95,
        metadata={"phase": "validation"},
    )
    record = SweepTrialFeedbackRecord(
        sweep_id="sweep-1",
        trial_id="trial-1",
        trial_index=0,
        status=SweepFeedbackStatus.SUCCEEDED,
        observed_at="2020-01-01T00:00:00Z",
        artifact_refs={"artifact": "ok"},
        observations=(observation,),
        metadata={"reason": "done"},
    )

    payload = record.to_dict()
    assert payload["schema_version"] == SWEEP_FEEDBACK_SCHEMA_VERSION
    assert payload["observations"] == [observation.to_dict()]
    assert SweepTrialFeedbackRecord.from_dict(payload) == record


def test_extraction_unsupported_record_is_plain_data() -> None:
    request = SweepExtractionRequest(
        sweep_id="sweep-1",
        trial_id="trial-1",
        trial_index=0,
        requested_at="2020-01-01T00:00:00Z",
    )
    result = unsupported_extraction(request, detail={"reason": "not implemented"})

    payload = result.to_dict()
    assert payload["schema_version"] == SWEEP_EXTRACTION_SCHEMA_VERSION
    assert payload["status"] == SweepExtractionStatus.UNSUPPORTED.value
    assert payload["extracted_payload"] is None
    diagnostics = cast("list[dict[str, object]]", payload["diagnostics"])
    assert diagnostics[0]["code"] == "unsupported_extraction"

    restored = SweepExtractionResult.from_dict(payload)
    assert restored == result


def test_manifest_payload_checks_differentiate_unsupported_and_malformed_records(
    tmp_path: Path,
) -> None:
    manifest = SweepManifest(
        sweep_id="sweep-1",
        provider=_sample_provider(),
        created_at="2020-01-01T00:00:00Z",
    )
    sweep_path = tmp_path / SWEEP_MANIFEST_FILE_NAME
    write_sweep_manifest(manifest, sweep_path)
    assert read_sweep_manifest(sweep_path) == manifest

    trials = TrialsManifest(
        sweep_id="sweep-1",
        trials=(
            SweepTrialRecord(
                trial_id="trial-1",
                trial_index=0,
                sweep_id="sweep-1",
                metadata={"index": 0},
            ),
        ),
    )
    trials_path = tmp_path / TRIALS_MANIFEST_FILE_NAME
    write_trials_manifest(trials, trials_path)
    assert read_trials_manifest(trials_path) == trials

    payload = {"unexpected": True}
    _, diagnostics = check_sweep_manifest_payload(payload, sweep_dir=str(tmp_path))
    assert diagnostics
    assert diagnostics[0].code == "sweep_schema_version_missing"

    payload = {"schema_version": SWEEP_MANIFEST_SCHEMA_VERSION, "unexpected": True}
    _, diagnostics = check_sweep_manifest_payload(payload, sweep_dir=str(tmp_path))
    assert diagnostics
    assert diagnostics[0].code == "malformed_sweep_manifest"

    payload = manifest.to_dict()
    payload["schema_version"] = SWEEP_MANIFEST_SCHEMA_VERSION + 1
    _, diagnostics = check_sweep_manifest_payload(payload, sweep_dir=str(tmp_path))
    assert diagnostics
    assert diagnostics[0].code == "unsupported_sweep_schema_version"

    payload = trials.to_dict()
    payload["schema_version"] = 0
    _, diagnostics = check_trials_manifest_payload(payload, sweep_dir=str(tmp_path))
    assert diagnostics
    assert diagnostics[0].code == "unsupported_trials_schema_version"


def test_feedback_and_dispatch_reject_non_plain_payloads() -> None:
    with pytest.raises(SweepProtocolError, match="plain"):
        SweepFeedbackObservation(
            key="x",
            value={},
            metadata=cast("dict[str, PlainData]", {"bad": cast("PlainData", {1: "one"})}),
        )

    with pytest.raises(SweepProtocolError, match="unknown field"):
        SweepDispatchRequest.from_dict(
            {
                "schema_version": SWEEP_DISPATCH_SCHEMA_VERSION,
                "sweep_id": "sweep-1",
                "trial_id": "trial-1",
                "trial_index": 0,
                "requested_at": "2020-01-01T00:00:00Z",
                "request_metadata": {},
                "future_field": True,
            }
        )

    with pytest.raises(SweepProtocolError, match="plain"):
        SweepDispatchRequest(
            sweep_id="sweep-1",
            trial_id="trial-1",
            trial_index=0,
            requested_at="2020-01-01T00:00:00Z",
            request_metadata={"bad": object()},  # type: ignore[arg-type]
        )
