"""Contract tests for sweep collection records."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus
from loom.pipeline.sweep import (
    SWEEP_COLLECTION_SCHEMA_VERSION,
    ManualSweepSpec,
    ManualTrialSpec,
    SweepCollectionResult,
    SweepProtocolError,
    collect_sweep_results,
    plan_sweep,
)

pytestmark = pytest.mark.contract


def test_sweep_collection_contract_preserves_metadata_only_shape() -> None:
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="collection-contract",
            run_uri_root="file:///tmp/collection-contract",
            trials=(ManualTrialSpec(overrides={"pipeline.seed": 1}),),
        ),
        created_at="2026-05-14T00:00:00Z",
    )
    result = collect_sweep_results(
        plan,
        run_statuses={
            "file:///tmp/collection-contract/trial-0001": SimpleNamespace(
                status=RunStatus.SUCCEEDED,
                metadata={},
            )
        },
        artifact_reader=lambda _run_uri: {
            "build.out": ArtifactRef(
                artifact_id="build/out",
                uri="file:///tmp/collection-contract/trial-0001/artifacts/out.json",
                artifact_type="json",
                metadata={"label": "generic"},
            )
        },
        include_unsupported_extraction=True,
        collected_at="2026-05-14T00:00:01Z",
    )

    payload = result.to_dict()

    assert payload["schema_version"] == SWEEP_COLLECTION_SCHEMA_VERSION
    assert payload["trial_count"] == 1
    assert payload["artifact_count"] == 1
    trial = payload["trials"][0]
    assert trial["proposal_overrides"] == {"pipeline.seed": 1}
    assert trial["status"]["outcome"] == "succeeded"
    assert trial["artifacts"][0]["artifact_id"] == "build/out"
    assert "payload" not in trial["artifacts"][0]
    assert "metric" not in trial
    assert trial["extraction_result"]["status"] == "unsupported"
    assert SweepCollectionResult.from_dict(payload) == result


def test_sweep_collection_rejects_non_plain_metadata() -> None:
    with pytest.raises(SweepProtocolError, match="must contain plain data"):
        SweepCollectionResult.from_dict(
            {
                "schema_version": 1,
                "sweep_id": "collection-contract",
                "collected_at": "2026-05-14T00:00:01Z",
                "trial_count": 0,
                "artifact_count": 0,
                "trials": [],
                "diagnostics": [
                    {
                        "code": "bad",
                        "message": "bad",
                        "trial_id": None,
                        "detail": {"value": object()},
                    }
                ],
            }
        )
