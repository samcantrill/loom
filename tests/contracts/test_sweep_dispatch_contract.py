"""Contract tests for dispatch intent and outcome records."""

from __future__ import annotations

import pytest

from loom.pipeline.sweep import (
    SWEEP_DISPATCH_SCHEMA_VERSION,
    SweepDispatchRequest,
    SweepDispatchResult,
    SweepDispatchStatus,
    SweepProtocolError,
)

pytestmark = pytest.mark.contract


_TRIAL_COMMON = {
    "sweep_id": "sweep-1",
    "trial_id": "trial-1",
    "trial_index": 0,
    "requested_at": "2020-01-01T00:00:00Z",
}


def test_dispatch_request_result_contract_round_trip() -> None:
    request = SweepDispatchRequest(
        **_TRIAL_COMMON,
        run_uri="file:///runs/trial-1",
        provider_trial_id="provider-1",
        request_metadata={"source": "contract"},
    )
    result = SweepDispatchResult(
        request=request,
        status=SweepDispatchStatus.SUBMITTED,
        run_uri=request.run_uri,
        dispatched_at="2020-01-01T00:00:01Z",
        reason="accepted",
        result_metadata={"executor": "local"},
    )

    assert request.to_dict() == {
        "schema_version": SWEEP_DISPATCH_SCHEMA_VERSION,
        "sweep_id": "sweep-1",
        "trial_id": "trial-1",
        "trial_index": 0,
        "requested_at": "2020-01-01T00:00:00Z",
        "run_uri": "file:///runs/trial-1",
        "provider_trial_id": "provider-1",
        "request_metadata": {"source": "contract"},
    }
    assert result.to_dict() == {
        "schema_version": SWEEP_DISPATCH_SCHEMA_VERSION,
        "request": request.to_dict(),
        "status": "submitted",
        "run_uri": "file:///runs/trial-1",
        "dispatched_at": "2020-01-01T00:00:01Z",
        "reason": "accepted",
        "result_metadata": {"executor": "local"},
    }
    assert SweepDispatchResult.from_dict(result.to_dict()) == result


def test_dispatch_records_reject_unknown_status_values() -> None:
    request = SweepDispatchRequest(**_TRIAL_COMMON)

    with pytest.raises(SweepProtocolError, match="valid SweepDispatchStatus"):
        SweepDispatchResult.from_dict(
            {
                "schema_version": 1,
                "request": request.to_dict(),
                "status": "not-a-status",
            }
        )
