"""Unit tests for metadata-first sweep collection."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus
from loom.pipeline.sweep import (
    ManualSweepSpec,
    ManualTrialSpec,
    SweepCollectionResult,
    SweepTrialOutcome,
    collect_sweep_results,
    plan_sweep,
)


def test_collect_sweep_results_reports_status_artifact_refs_and_extraction() -> None:
    plan = _plan()
    run_statuses = {
        "file:///tmp/collect/trial-0001": SimpleNamespace(
            status=RunStatus.SUCCEEDED,
            metadata={},
        )
    }

    result = collect_sweep_results(
        plan,
        run_statuses=run_statuses,
        artifact_reader=lambda _run_uri: {
            "build.data": ArtifactRef(
                artifact_id="build/data",
                uri="file:///tmp/collect/trial-0001/artifacts/build/data.json",
                artifact_type="json",
                codec_key="json.v1",
                metadata={"rows": 2},
            )
        },
        include_unsupported_extraction=True,
        collected_at="2026-05-14T00:00:00Z",
    )

    assert result.sweep_id == "collect"
    assert result.trial_count == 2
    assert result.artifact_count == 2
    assert result.trials[0].status.outcome is SweepTrialOutcome.SUCCEEDED
    assert result.trials[0].artifacts[0].artifact_id == "build/data"
    assert result.trials[0].extraction_result is not None
    assert result.trials[0].extraction_result.status.value == "unsupported"
    assert result.trials[1].status.outcome is SweepTrialOutcome.PENDING
    assert SweepCollectionResult.from_dict(result.to_dict()) == result


def test_collect_sweep_results_turns_artifact_reader_failures_into_diagnostics() -> None:
    plan = _plan()

    def fail(_run_uri: str) -> Mapping[str, object] | None:
        raise RuntimeError("missing artifact index")

    result = collect_sweep_results(
        plan,
        artifact_reader=fail,
        collected_at="2026-05-14T00:00:00Z",
    )

    assert result.artifact_count == 0
    assert len(result.diagnostics) == 2
    assert result.diagnostics[0].code == "artifact_collection_failed"
    assert result.trials[0].diagnostics[0].trial_id == "trial-0001"


def _plan():
    return plan_sweep(
        ManualSweepSpec(
            sweep_id="collect",
            run_uri_root="file:///tmp/collect",
            trials=(
                ManualTrialSpec(overrides={"pipeline.variant": "a"}),
                ManualTrialSpec(overrides={"pipeline.variant": "b"}),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )
