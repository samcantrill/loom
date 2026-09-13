"""Request-before-send persistence, exact replay and observer-only controls."""

from dataclasses import replace
import json
from typing import Any, cast
from types import SimpleNamespace

import pytest

from loom.coordinator import RunRequest
from loom.queue.preparation import PreparationSource, PrepareRunRequest
from loom.pipeline.sweep import (
    ManualSweepSpec,
    ManualTrialSpec,
    plan_sweep,
    run_sweep,
    read_sweep_plan,
    write_sweep_plan,
    SweepProtocolError,
    cancel_sweep_trial,
    retry_sweep_trial,
)


def _plan():
    return plan_sweep(
        ManualSweepSpec(
            sweep_id="native",
            run_uri_root="file:///runs",
            trials=(
                ManualTrialSpec(overrides={"pipeline.name": "first"}),
                ManualTrialSpec(overrides={"pipeline.name": "second"}),
            ),
        )
    )


def _template():
    return RunRequest(
        PrepareRunRequest(
            "template",
            "template",
            PreparationSource("shared", "project", ".", (".",)),
            "pipeline.yaml",
            "local",
            ("overlay.yaml",),
            ("pipeline.name=base",),
            {"tags": {"purpose": "science"}},
        ),
        "template",
    )


def _outcome(request, state="SUCCEEDED", early_stop=False):
    data = {
        "operation_id": request.preparation.operation_id,
        "operation": {"state": "applied"},
        "admission": {
            "admission_id": "admission-" + request.queue_item_id,
            "queue_item_id": request.queue_item_id,
            "state": state,
            "run_uri": request.preparation.run_options["run_uri"],
        },
        "inspection": {"stages": [{"code": "early_stop" if early_stop else None}]},
    }
    return SimpleNamespace(
        observation=SimpleNamespace(to_dict=lambda: data), cleanup={}
    )


def test_persist_before_lost_response_and_replay_preserves_intent(
    tmp_path, monkeypatch
):
    import loom

    sent = []

    def run(request, **kwargs):
        manifest = json.loads((tmp_path / "sweep.json").read_text())
        record = manifest["metadata"]["native_runs"][request.preparation.run_name]
        assert record["request"] == request.to_dict()
        sent.append(request)
        if len(sent) == 1:
            raise ConnectionError("accepted response lost")
        return _outcome(request)

    monkeypatch.setattr(loom, "run", run)
    plan = _plan()
    run_sweep(
        plan,
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    write_sweep_plan(
        plan, tmp_path
    )  # A plan refresh must not erase accepted identities.
    result = run_sweep(
        plan,
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    assert sent[:2] == sent[2:]
    assert [r.preparation.overrides for r in sent[:2]] == [
        ("pipeline.name=base", 'pipeline.name="first"'),
        ("pipeline.name=base", 'pipeline.name="second"'),
    ]
    assert all(r.preparation.source == _template().preparation.source for r in sent)
    assert all(r.preparation.preparation_profile == "local" for r in sent)
    assert all(
        r.preparation.run_options["tags"] == {"purpose": "science"} for r in sent
    )
    trials = read_sweep_plan(tmp_path).trials_manifest
    assert trials is not None
    assert trials.trials == plan.trials
    assert result.succeeded_count == 2


def test_interruption_keeps_accepted_trial_and_leaves_remaining_unsent(
    tmp_path, monkeypatch
):
    import loom

    sent = []

    def run(request, **kwargs):
        sent.append(request)
        raise KeyboardInterrupt

    monkeypatch.setattr(loom, "run", run)
    with pytest.raises(KeyboardInterrupt):
        run_sweep(
            _plan(),
            request_template=_template(),
            deployment="selection.json",
            sweep_dir=tmp_path,
        )
    records = _records(tmp_path)
    assert set(records) == {"trial-0001"}
    monkeypatch.setattr(
        loom, "run", lambda request, **kw: (sent.append(request), _outcome(request))[1]
    )
    run_sweep(
        _plan(),
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    assert sent[0] == sent[1]
    assert len(sent) == 3


def test_failed_early_stopped_and_cancelled_meanings(tmp_path, monkeypatch):
    import loom

    monkeypatch.setattr(
        loom, "run", lambda request, **kw: _outcome(request, "CANCELLED", True)
    )
    result = run_sweep(
        _plan(),
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    assert result.early_stopped_count == 2
    assert result.failed_count == 0
    assert result.status.value == "succeeded"
    monkeypatch.setattr(loom, "run", lambda request, **kw: _outcome(request, "FAILED"))
    result = run_sweep(
        _plan(),
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    assert result.failed_count == 2
    monkeypatch.setattr(
        loom, "run", lambda request, **kw: _outcome(request, "CANCELLED")
    )
    result = run_sweep(
        _plan(),
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    assert result.status.value == "cancelled"


def test_changed_invocation_rejected_before_send(tmp_path, monkeypatch):
    import loom

    monkeypatch.setattr(loom, "run", lambda request, **kw: _outcome(request))
    run_sweep(
        _plan(),
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    template = _template()
    template = replace(
        template,
        preparation=replace(template.preparation, overrides=("pipeline.name=changed",)),
    )
    monkeypatch.setattr(loom, "run", lambda *a, **k: pytest.fail("changed intent sent"))
    with pytest.raises(SweepProtocolError, match="intent conflicts"):
        run_sweep(
            _plan(),
            request_template=template,
            deployment="selection.json",
            sweep_dir=tmp_path,
        )


def test_explicit_controls_retain_native_references_without_implicit_retry(
    tmp_path, monkeypatch
):
    import loom

    monkeypatch.setattr(loom, "run", lambda request, **kw: _outcome(request, "FAILED"))
    run_sweep(
        _plan(),
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )

    def submit(request, **kwargs):
        records = _records(tmp_path)
        assert records["trial-0001"]["retry_request"] == request.to_dict()
        assert request.retry_failed_revision == 7
        return request

    client: Any = SimpleNamespace(
        submit=submit,
        cancel_run_operation=lambda op, **kwargs: SimpleNamespace(
            operation_id="cancel-" + op
        ),
    )
    request = retry_sweep_trial(
        tmp_path, "trial-0001", client=client, retry_failed_revision=7
    )
    assert request.run_uri == "file:///runs/trial-0001"
    control = cancel_sweep_trial(tmp_path, "trial-0001", client=client)
    records = _records(tmp_path)
    assert records["trial-0001"]["cancellation_operation_id"] == control.operation_id


def test_changed_trial_plan_and_in_process_requests_are_rejected(tmp_path):
    plan = _plan()
    write_sweep_plan(plan, tmp_path)
    changed = plan_sweep(
        ManualSweepSpec(
            sweep_id="native",
            run_uri_root="file:///runs",
            trials=(ManualTrialSpec(overrides={"pipeline.name": "other"}),),
        )
    )
    with pytest.raises(SweepProtocolError, match="incompatible existing sweep plan"):
        run_sweep(
            changed,
            request_template=_template(),
            deployment="selection.json",
            sweep_dir=tmp_path,
        )
    with pytest.raises(SweepProtocolError, match="native RunRequest"):
        run_sweep(
            plan,
            request_template=cast(Any, SimpleNamespace(pipeline=lambda: None)),
            deployment="selection.json",
            sweep_dir=tmp_path,
        )


def test_waiting_detachment_does_not_select_remaining_trials(tmp_path, monkeypatch):
    import loom

    requests = []

    def detached(request, **kwargs):
        requests.append(request)
        return _outcome(request, "WAITING")

    monkeypatch.setattr(loom, "run", detached)
    result = run_sweep(
        _plan(),
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    assert len(requests) == 1
    assert [t.outcome.value for t in result.trials] == ["queued", "pending"]


def test_definite_submission_failure_is_failed_and_later_trials_continue(
    tmp_path, monkeypatch
):
    import loom
    from loom.queue.errors import QueueConfigError

    def run(request, **kwargs):
        if request.preparation.run_name == "trial-0001":
            raise QueueConfigError("selected config is outside source closure")
        return _outcome(request)

    monkeypatch.setattr(loom, "run", run)
    result = run_sweep(
        _plan(),
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    assert result.failed_count == 1
    assert result.succeeded_count == 1
    assert result.status.value == "failed"


def _records(root) -> dict[str, Any]:
    from loom.pipeline.sweep import read_sweep_plan

    manifest = read_sweep_plan(root).sweep_manifest
    assert manifest is not None
    return cast(dict[str, Any], manifest.metadata["native_runs"])
