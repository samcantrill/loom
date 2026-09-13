"""Scientific/control sweep assertions through real native preparation and workers."""

import json
from typing import Any, cast
from pathlib import Path

import pytest

from loom.coordinator import RunRequest
from loom.pipeline.sweep import ManualSweepSpec, ManualTrialSpec, plan_sweep, run_sweep
from tests.integration.queue.test_service_lifetime import _selection
from tests.integration.queue.test_preparation_operations import _request

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize(
    "target,expected",
    [
        ("FailingStage", "failed"),
        ("EarlyStopStage", "early_stopped"),
    ],
)
def test_native_trials_continue_with_preserved_outcomes(
    tmp_path: Path, target, expected
):
    selection = _selection(tmp_path)
    stage = json.loads((tmp_path / "projects" / "pipeline.yaml").read_text())[
        "pipeline"
    ]["stages"][0]
    stage["factory"]["_target_"] = "tests.support.pipeline_execution_stages." + target
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="native-sweep",
            run_uri_root=(tmp_path / "runs").as_uri(),
            trials=(
                ManualTrialSpec(overrides={"pipeline.stages": [stage]}),
                ManualTrialSpec(overrides={"pipeline.name": "second"}),
            ),
        )
    )
    result = run_sweep(
        plan,
        request_template=RunRequest(_request(), "template"),
        deployment=selection,
        sweep_dir=tmp_path / "sweep",
    )
    assert [trial.outcome.value for trial in result.trials] == [expected, "succeeded"]
    assert result.status.value == ("failed" if expected == "failed" else "succeeded")
    retained = json.loads((tmp_path / "sweep" / "sweep.json").read_text())["metadata"][
        "native_runs"
    ]
    assert all(r["observation"]["admission"]["admission_id"] for r in retained.values())
    assert all(
        r["cleanup"]["coordinator"]["state"] == "stopped" for r in retained.values()
    )
    again = run_sweep(
        plan,
        request_template=RunRequest(_request(), "template"),
        deployment=selection,
        sweep_dir=tmp_path / "sweep",
    )
    assert [t.metadata["admission_id"] for t in again.trials] == [
        t.metadata["admission_id"] for t in result.trials
    ]


def test_lost_native_response_recovers_same_admission(tmp_path, monkeypatch):
    import loom

    selection = _selection(tmp_path)
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="lost-response",
            run_uri_root=(tmp_path / "runs").as_uri(),
            trials=(ManualTrialSpec(overrides={}),),
        )
    )
    native_run = loom.run
    sent = []

    def lose_response(request, **kwargs):
        sent.append(request)
        result = native_run(request, **kwargs)
        if len(sent) == 1:
            assert result.observation.admission is not None
            lost.append(result.observation.admission.admission_id)
            raise ConnectionError(
                "native acceptance response lost before sweep persistence"
            )
        return result

    lost = []
    monkeypatch.setattr(loom, "run", lose_response)
    first = run_sweep(
        plan,
        request_template=RunRequest(_request(), "template"),
        deployment=selection,
        sweep_dir=tmp_path / "sweep",
    )
    assert first.trials[0].outcome.value == "unknown"
    recovered = run_sweep(
        plan,
        request_template=RunRequest(_request(), "template"),
        deployment=selection,
        sweep_dir=tmp_path / "sweep",
    )
    assert sent[0] == sent[1]
    assert recovered.trials[0].metadata["admission_id"] == lost[0]


def test_collection_preserves_committed_outputs_across_explicit_retry(tmp_path):
    from loom.cli.sweep import build_sweep_collect_result
    from loom.deployment import ensure_available, load_deployment
    from loom.pipeline.sweep import retry_sweep_trial

    selection = _selection(tmp_path)
    coordinator = tmp_path / "coordinator.json"
    config = json.loads(coordinator.read_text())
    config["preparation"]["profiles"]["existing-project"]["configuration_policy"] = (
        "local"
    )
    coordinator.write_text(json.dumps(config))
    project = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(project.read_text())
    first = authored["pipeline"]["stages"][0]
    second = {
        **first,
        "name": "second",
        "depends_on": ["produce"],
        "factory": {
            "_target_": "tests.support.pipeline_execution_stages.FailOnceThenProduceStage"
        },
        "config": {"marker_path": str(tmp_path / "failed-once")},
    }
    authored["pipeline"]["stages"].append(second)
    project.write_text(json.dumps(authored))
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="reuse",
            run_uri_root=(tmp_path / "runs").as_uri(),
            trials=(ManualTrialSpec(overrides={}),),
        )
    )
    template = RunRequest(_request(), "template")
    root = tmp_path / "sweep"
    result = run_sweep(
        plan, request_template=template, deployment=selection, sweep_dir=root
    )
    assert result.failed_count == 1
    before = build_sweep_collect_result(root)
    assert before.artifact_count == 1
    record = _records(root)["trial-0001"]
    available = ensure_available(
        load_deployment(selection), attachment_id="explicit-sweep-retry"
    )
    try:
        failed = available.client.admission_for_queue_item(
            record["request"]["queue_item_id"]
        )
        retry_sweep_trial(
            root,
            "trial-0001",
            client=available.client,
            retry_failed_revision=failed.revision,
        )
        observed = available.client.observe_run(
            record["request"]["preparation"]["operation_id"], timeout_seconds=30
        )
        assert observed.admission is not None
        assert observed.admission.state.value == "SUCCEEDED"
        detail = available.client.admission(failed.admission_id)
        attempts = cast(list[dict[str, Any]], detail.authority["attempts"])
        assert len([a for a in attempts if a["stage_name"] == "produce"]) == 1
        assert len([a for a in attempts if a["stage_name"] == "second"]) == 2
    finally:
        available.release()
        available.client.close()
    result = run_sweep(
        plan, request_template=template, deployment=selection, sweep_dir=root
    )
    assert result.succeeded_count == 1
    after = build_sweep_collect_result(root)
    assert after.artifact_count == 2
    assert after.trials[0].artifacts[0] == before.trials[0].artifacts[0]


def _records(root) -> dict[str, Any]:
    from loom.pipeline.sweep import read_sweep_plan

    manifest = read_sweep_plan(root).sweep_manifest
    assert manifest is not None
    return cast(dict[str, Any], manifest.metadata["native_runs"])
