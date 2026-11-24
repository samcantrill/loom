"""Scientific/control sweep assertions through real native preparation and workers."""

import io
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


def test_cli_observation_skips_unaccepted_request_and_recovers_later_acceptance(
    tmp_path, monkeypatch
):
    import loom
    from loom.cli.main import main
    from loom.coordinator import CoordinatorClient

    selection = _selection(tmp_path)
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="partial-acceptance",
            run_uri_root=(tmp_path / "runs").as_uri(),
            trials=(
                ManualTrialSpec(overrides={"pipeline.name": "first"}),
                ManualTrialSpec(overrides={"pipeline.name": "second"}),
            ),
        )
    )
    native_run = loom.run
    accepted = []

    def lose_response(request, **kwargs):
        if request.preparation.run_name == "trial-0001":
            raise ConnectionError("connection lost before acceptance")
        result = native_run(request, **{**kwargs, "wait": True})
        assert result.observation.admission is not None
        accepted.append(result.observation.admission.admission_id)
        raise ConnectionError("accepted response lost before sweep persistence")

    root = tmp_path / "sweep"
    monkeypatch.setattr(loom, "run", lose_response)
    first = run_sweep(
        plan,
        request_template=RunRequest(_request(), "template"),
        deployment=selection,
        sweep_dir=root, wait=False,
    )
    assert [t.outcome.value for t in first.trials] == ["unknown", "unknown"]
    before = _records(root)["trial-0001"]
    monkeypatch.setattr(
        CoordinatorClient,
        "start_run",
        lambda *a, **kw: pytest.fail("observer submitted work"),
    )
    stdout, stderr = io.StringIO(), io.StringIO()
    assert (
        main(
            [
                "sweep",
                "status",
                str(root),
                "--deployment",
                str(selection),
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    ), stderr.getvalue()
    summary = json.loads(stdout.getvalue())["result"]
    assert summary["counts"]["unknown"] == 1
    assert summary["counts"]["succeeded"] == 1
    assert _records(root)["trial-0001"] == before
    assert (
        _records(root)["trial-0002"]["observation"]["admission"]["admission_id"]
        == accepted[0]
    )


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


def test_waiting_window_refills_while_first_trial_is_running(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import time
    from loom import _run

    selection = _selection(tmp_path)
    agent = tmp_path / "agent.json"
    config = json.loads(agent.read_text())
    config["resident_profiles"][0]["cpu_capacity"] = 3
    coordinator = tmp_path / "coordinator.json"
    service = json.loads(coordinator.read_text())
    service["preparation"]["profiles"]["existing-project"]["configuration_policy"] = "local"
    coordinator.write_text(json.dumps(service))
    agent.write_text(json.dumps(config))
    first = json.loads((tmp_path / "projects" / "pipeline.yaml").read_text())["pipeline"]["stages"][0]
    first["factory"]["_target_"] = "tests.support.pipeline_execution_stages.ReleaseStage"
    marker = tmp_path / "marker"
    first["config"] = {"marker_dir": str(marker), "timeout_seconds": 90}
    plan = plan_sweep(ManualSweepSpec(
        sweep_id="window", run_uri_root=(tmp_path / "runs").as_uri(), trials=(
            ManualTrialSpec(overrides={"pipeline.stages": [first]}),
            ManualTrialSpec(overrides={"pipeline.name": "second"}),
            ManualTrialSpec(overrides={"pipeline.name": "third"}),
        ),
    ))
    root = tmp_path / "sweep"
    send = _run._start_exact
    sent = []

    def start(available, request, **kwargs):
        trial = request.preparation.run_name
        if trial == "trial-0002":
            end = time.monotonic() + 35
            while not (marker / "produce.started").exists():
                assert time.monotonic() < end, "first worker failed to start"
                time.sleep(0.05)
        if trial == "trial-0003":
            rows = _records(root)
            assert rows["trial-0002"]["observation"]["admission"]["state"] == "SUCCEEDED"
            assert not (marker / "release").exists()
        sent.append(trial)
        return send(available, request, **kwargs)

    monkeypatch.setattr(_run, "_start_exact", start)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_sweep, plan, request_template=RunRequest(_request(), "template"),
                             deployment=selection, sweep_dir=root, max_in_flight=2, timeout_seconds=85)
        try:
            end = time.monotonic() + 65
            while not future.done() and time.monotonic() < end:
                if (root / "sweep.json").is_file():
                    rows = json.loads((root / "sweep.json").read_text())["metadata"].get("native_runs", {})
                    if (rows.get("trial-0003", {}).get("observation", {}).get("admission") or {}).get("state") == "SUCCEEDED":
                        break
                time.sleep(0.05)
            if future.done():
                future.result()
            assert sent == ["trial-0001", "trial-0002", "trial-0003"]
            assert (marker / "produce.started").exists()
            assert _records(root)["trial-0003"]["observation"]["admission"]["state"] == "SUCCEEDED"
        finally:
            marker.mkdir(exist_ok=True)
            (marker / "release").touch()
        assert future.result(timeout=30).succeeded_count == 3
    rows = _records(root)
    assert rows["trial-0001"]["cleanup"]["coordinator"]["state"] == "stopped"
    assert rows["trial-0002"]["cleanup"]["coordinator"]["state"] == "retained-for-other-work"


@pytest.mark.parametrize("after_acceptance", [False, True])
def test_window_recovers_interrupted_send_and_preserves_unsent_trials(tmp_path, monkeypatch, after_acceptance):
    from loom import _run
    from loom.cli.sweep import build_sweep_status_result
    import sqlite3

    selection = _selection(tmp_path)
    root = tmp_path / "sweep"
    plan = plan_sweep(ManualSweepSpec(sweep_id="restart", run_uri_root=(tmp_path / "runs").as_uri(),
                                     trials=(ManualTrialSpec(overrides={}), ManualTrialSpec(overrides={}))))
    template = RunRequest(_request(), "template")
    send = _run._start_exact
    attempts = []

    def interrupt(available, request, **kwargs):
        attempts.append(request)
        if len(attempts) == 1:
            if after_acceptance:
                send(available, request, **kwargs)
            raise KeyboardInterrupt
        return send(available, request, **kwargs)

    monkeypatch.setattr(_run, "_start_exact", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run_sweep(plan, request_template=template, deployment=selection, sweep_dir=root, max_in_flight=2)
    saved = _records(root)
    assert list(saved) == ["trial-0001"]
    from loom.serialization import thaw_plain_data
    assert thaw_plain_data(saved["trial-0001"]["request"]) == attempts[0].to_dict()

    status = build_sweep_status_result(root, deployment=selection)
    assert len(attempts) == 1
    assert [t.metadata["submission_state"] for t in status.trials] == [
        "accepted" if after_acceptance else "intent_retained", "unselected",
    ]
    resumed = run_sweep(plan, request_template=template, deployment=selection, sweep_dir=root, max_in_flight=2)
    assert resumed.succeeded_count == 2
    assert _records(root)["trial-0001"]["request"] == saved["trial-0001"]["request"]
    if after_acceptance:
        assert len(attempts) == 2  # The passive read established acceptance; only B is sent.
    else:
        assert len(attempts) == 3 and attempts[0] == attempts[1]
    with sqlite3.connect(tmp_path / "deployment" / "coordinator" / "control.sqlite") as db:
        for row in _records(root).values():
            request = row["request"]
            assert db.execute("SELECT COUNT(*) FROM preparation_operations WHERE operation_id=?",
                              (request["preparation"]["operation_id"],)).fetchone() == (1,)
            assert db.execute("SELECT COUNT(*) FROM managed_admissions WHERE queue_item_id=?",
                              (request["queue_item_id"],)).fetchone() == (1,)
