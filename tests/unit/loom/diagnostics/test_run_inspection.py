from __future__ import annotations

import pytest

from loom.diagnostics import (
    RunInspectionAxis,
    RunInspectionAxisName,
    RunInspectionFailure,
    RunInspectionFailureCode,
    RunInspectionLocation,
    RunInspectionResult,
    RunInspectionStage,
    RunInspectionTruncation,
    RunLocationReachability,
    decode_run_inspection_response,
    inspect_run,
)


def test_result_codec_is_strict_and_round_trips() -> None:
    result = RunInspectionResult(
        run_uri="file:///tmp/run",
        as_of="2026-08-30T00:00:00Z",
        summary="SUCCEEDED",
        axes=(
            RunInspectionAxis(
                RunInspectionAxisName.LIFECYCLE,
                "authority",
                "available",
                "SUCCEEDED",
                3,
                "2026-08-30T00:00:00Z",
                "current",
            ),
        ),
        stages=(RunInspectionStage("train", "SUCCEEDED", 1),),
        locations=(
            RunInspectionLocation(
                "artifact:train:model",
                "file:///tmp/model",
                "artifact",
                "recorded",
                "model",
                "sha256:abc",
                RunLocationReachability.COORDINATOR_LOCAL,
            ),
        ),
        truncation=(RunInspectionTruncation("stages", 1, 1),),
    )
    assert RunInspectionResult.from_dict(result.to_dict()) == result
    payload = result.to_dict()
    payload["secret"] = "must not pass"
    with pytest.raises(ValueError, match="fields"):
        RunInspectionResult.from_dict(payload)


def test_closed_failure_contains_no_run_facts() -> None:
    result = inspect_run("not-a-uri")
    assert result == RunInspectionFailure(RunInspectionFailureCode.INVALID_REQUEST)
    assert decode_run_inspection_response(result.to_dict()) == result
    assert set(result.to_dict()) == {"schema_version", "code"}


def test_result_rejects_more_than_the_fixed_collection_limit() -> None:
    with pytest.raises(ValueError, match="at most 256"):
        RunInspectionResult(
            run_uri="file:///tmp/run",
            as_of="2026-08-30T00:00:00Z",
            summary="unknown",
            axes=(),
            stages=tuple(
                RunInspectionStage(f"stage-{index}", "UNKNOWN") for index in range(257)
            ),
            locations=(),
            truncation=(),
        )
