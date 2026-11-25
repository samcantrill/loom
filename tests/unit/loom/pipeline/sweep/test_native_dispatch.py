"""Request-before-send persistence, exact replay and observer-only controls."""

from dataclasses import replace
import json
from typing import Any, cast
from types import SimpleNamespace

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError, RunRequest
from loom.queue.errors import QueueConfigError
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
    observe_sweep,
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
    assert len(sent) == 1  # Uncertain submission occupies the default window.
    write_sweep_plan(
        plan, tmp_path
    )  # A plan refresh must not erase accepted identities.
    result = run_sweep(
        plan,
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    assert len(sent) == 3 and sent[0] == sent[1]
    assert [r.preparation.overrides for r in sent[1:]] == [
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


def test_refused_resend_cannot_resolve_prior_unknown_acceptance(tmp_path, monkeypatch):
    import loom

    sent = []
    outcomes = iter((ConnectionError("original reply lost"),
                     QueueConfigError("local configuration refused resend")))

    def send(request, **kwargs):
        sent.append(request)
        error = next(outcomes, None)
        if error:
            raise error
        return _outcome(request)

    monkeypatch.setattr(loom, "run", send)
    def submit():
        return run_sweep(
            _plan(), request_template=_template(), deployment="selection.json", sweep_dir=tmp_path,
        )
    for _ in range(2):
        status = submit()
        assert [row.metadata["submission_state"] for row in status.trials] == [
            "uncertain", "unselected"
        ]
    assert sent[0] == sent[1]
    assert submit().succeeded_count == 2
    assert sent[2] == sent[0]


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


def test_reconciled_template_is_rejected_before_persistence_or_submission(
    tmp_path, monkeypatch
):
    import loom

    sent = []
    monkeypatch.setattr(loom, "run", lambda request, **kwargs: sent.append(request))
    request = RunRequest(
        replace(_template().preparation, run_name=None),
        mode="reconcile",
        retry_policy="one_observed_failure",
    )
    root = tmp_path / "sweep"
    with pytest.raises(SweepProtocolError, match="exact run intent"):
        run_sweep(
            _plan(),
            request_template=request,
            deployment="selection.json",
            sweep_dir=root,
        )
    assert not sent
    assert not root.exists()


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


@pytest.mark.parametrize(
    "failure,expected",
    [
        (ConnectionError("connection lost before acceptance"), "unknown"),
        (QueueConfigError("selected config is outside source closure"), "failed"),
    ],
)
def test_observe_unaccepted_trial_preserves_failure_and_refreshes_later_trial(
    tmp_path, monkeypatch, failure, expected
):
    import loom

    sent = []

    def run(request, **kwargs):
        sent.append(request)
        if len(sent) == 1:
            raise failure
        return _outcome(request, "WAITING")

    monkeypatch.setattr(loom, "run", run)
    plan = _plan()
    run_sweep(
        plan,
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
        wait=False,
    )
    before = _records(tmp_path)["trial-0001"]
    observed = []

    def observe(operation_id, **kwargs):
        observed.append(operation_id)
        if operation_id == sent[0].preparation.operation_id:
            raise CoordinatorClientError(
                "not_found",
                boundary="coordinator",
                operation="operation",
                ids={"operation_id": operation_id},
            )
        return _outcome(sent[1]).observation

    monkeypatch.setattr(loom, "run", lambda *a, **kw: pytest.fail("observer sent work"))
    summary = observe_sweep(
        plan, client=cast(Any, SimpleNamespace(observe_run=observe)), sweep_dir=tmp_path
    )
    assert observed == [r.preparation.operation_id for r in sent]
    assert [t.outcome.value for t in summary.trials] == [expected, "succeeded"]
    assert _records(tmp_path)["trial-0001"] == before


def test_observe_interruption_before_send_leaves_saved_intent_untouched(
    tmp_path, monkeypatch
):
    import loom
    from loom.queue._coordinator_control import (
        control_error,
        encode_wire,
        error_envelope,
    )
    from tests.unit.loom.test_coordinator import _peer

    def interrupt(request, **kwargs):
        saved = json.loads((tmp_path / "sweep.json").read_text())
        assert (
            saved["metadata"]["native_runs"]["trial-0001"]["request"]
            == request.to_dict()
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(loom, "run", interrupt)
    plan = _plan()
    with pytest.raises(KeyboardInterrupt):
        run_sweep(
            plan,
            request_template=_template(),
            deployment="selection.json",
            sweep_dir=tmp_path,
        )
    before = (tmp_path / "sweep.json").read_bytes()

    def respond(connection, request):
        assert request["operation"] == "operation"
        error = control_error("not_found", "operation", request, boundary="coordinator")
        connection.sendall(encode_wire(error_envelope(error)) + b"\n")

    monkeypatch.setattr(loom, "run", lambda *a, **kw: pytest.fail("observer sent work"))
    endpoint = tmp_path / "service.sock"
    with _peer(endpoint, respond) as requests:
        with CoordinatorClient.from_unix_socket(endpoint) as client:
            summary = observe_sweep(plan, client=client, sweep_dir=tmp_path)
    assert {r["operation"] for r in requests} == {"handshake", "operation"}
    assert (tmp_path / "sweep.json").read_bytes() == before
    assert [t.outcome.value for t in summary.trials] == ["queued", "pending"]
    assert all(t.metadata["admission_id"] is None for t in summary.trials)


@pytest.mark.parametrize("accepted_by", ["observation", "cancellation"])
def test_missing_previously_accepted_operation_still_raises(
    tmp_path, monkeypatch, accepted_by
):
    import loom

    def run(request, **kwargs):
        if accepted_by == "cancellation":
            raise ConnectionError("acceptance response lost")
        return _outcome(request)

    monkeypatch.setattr(loom, "run", run)
    plan = _plan()
    run_sweep(
        plan,
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    if accepted_by == "cancellation":
        cancel_sweep_trial(
            tmp_path,
            "trial-0001",
            client=cast(
                Any,
                SimpleNamespace(
                    cancel_run_operation=lambda op, **kw: SimpleNamespace(
                        operation_id="cancel-" + op
                    )
                ),
            ),
        )
    operation_id = _records(tmp_path)["trial-0001"]["request"]["preparation"][
        "operation_id"
    ]
    error = CoordinatorClientError(
        "not_found",
        boundary="coordinator",
        operation="operation",
        ids={"operation_id": operation_id},
    )

    def observe(*args, **kwargs):
        raise error

    before = (tmp_path / "sweep.json").read_bytes()
    with pytest.raises(CoordinatorClientError) as caught:
        observe_sweep(
            plan,
            client=cast(Any, SimpleNamespace(observe_run=observe)),
            sweep_dir=tmp_path,
        )
    assert caught.value is error
    assert (tmp_path / "sweep.json").read_bytes() == before


@pytest.mark.parametrize(
    "failure_at,code", [("admission", "not_found"), ("operation", "conflict")]
)
def test_native_observation_errors_beyond_missing_requested_operation_propagate(
    tmp_path, monkeypatch, failure_at, code
):
    import loom
    from loom.queue._coordinator_control import (
        control_error,
        encode_wire,
        error_envelope,
    )
    from tests.unit.loom.test_coordinator import _peer

    def lose_response(request, **kwargs):
        raise ConnectionError("response lost")

    monkeypatch.setattr(loom, "run", lose_response)
    plan = _plan()
    run_sweep(
        plan,
        request_template=_template(),
        deployment="selection.json",
        sweep_dir=tmp_path,
    )
    operation_id = _records(tmp_path)["trial-0001"]["request"]["preparation"][
        "operation_id"
    ]

    def respond(connection, request):
        if request["operation"] == failure_at:
            response = error_envelope(
                control_error(code, failure_at, request, boundary="coordinator")
            )
        else:
            assert request["operation"] == "operation"
            response = {
                "ok": True,
                "result": {
                    "operation_id": operation_id,
                    "kind": "run",
                    "state": "applied",
                    "code": None,
                    "result": {"admission": {"admission_id": "accepted"}},
                },
            }
        connection.sendall(encode_wire(response) + b"\n")

    before = (tmp_path / "sweep.json").read_bytes()
    endpoint = tmp_path / "service.sock"
    with _peer(endpoint, respond) as requests:
        with CoordinatorClient.from_unix_socket(endpoint) as client:
            with pytest.raises(CoordinatorClientError) as caught:
                observe_sweep(plan, client=client, sweep_dir=tmp_path)
    assert caught.value.code == code
    assert caught.value.operation == failure_at
    assert {r["operation"] for r in requests} == {"handshake", "operation", failure_at}
    assert (tmp_path / "sweep.json").read_bytes() == before


def _records(root) -> dict[str, Any]:
    from loom.pipeline.sweep import read_sweep_plan

    manifest = read_sweep_plan(root).sweep_manifest
    assert manifest is not None
    return cast(dict[str, Any], manifest.metadata["native_runs"])


def test_two_waiting_callers_count_the_same_uncertain_slot(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event
    from loom import _run, deployment

    template = _template()
    plan = plan_sweep(ManualSweepSpec(sweep_id="shared-window", run_uri_root="file:///runs", trials=tuple(
        ManualTrialSpec(overrides={"pipeline.name": name}) for name in ("one", "two", "three")
    )))
    selection = SimpleNamespace(source=template.preparation.source, preparation_profile="local",
                                startup_seconds=5, wait_seconds=None)
    monkeypatch.setattr(deployment, "load_deployment", lambda _: selection)
    ids = {}
    reached_b, pending_b, deliver_a = Barrier(3), Event(), Event()

    def observation(request, state):
        result = _outcome(request, state).observation.to_dict()
        result["connection"] = {"coordinator_id": "owner"}
        return SimpleNamespace(to_dict=lambda: result, operation=SimpleNamespace(state="applied"),
                               admission=SimpleNamespace(state=state))

    def start(available, request, **kwargs):
        trial_id = request.preparation.run_name
        prior = ids.setdefault(trial_id, request)
        assert prior == request
        if trial_id == "trial-0001" and not deliver_a.is_set():
            raise ConnectionError("lost acceptance response")
        return observation(request, "ACTIVE")

    def read(op, connection, **kwargs):
        request = next(item for item in ids.values() if item.preparation.operation_id == op)
        if request.preparation.run_name == "trial-0002" and not pending_b.is_set():
            reached_b.wait(timeout=5)
            assert pending_b.wait(5)
        yield observation(request, "SUCCEEDED")

    def available(*args, **kwargs):
        return SimpleNamespace(connection_id="owner", roles={}, description=SimpleNamespace(coordinator_id="owner"),
                               selection=selection, release=lambda deadline: None,
                               client=SimpleNamespace(_run_observation_steps=read, close=lambda: None))

    monkeypatch.setattr(deployment, "ensure_available", available)
    monkeypatch.setattr(_run, "_start_exact", start)
    monkeypatch.setattr(_run, "_cleanup_step", lambda *args: {"coordinator": {"state": "persistent/borrowed"}})
    def invoke():
        return run_sweep(plan, request_template=template, deployment="selection.json",
                         sweep_dir=tmp_path, max_in_flight=2)

    # Prewrite the plan as a normal 'sweep plan' invocation would.
    write_sweep_plan(plan, tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        try:
            reached_b.wait(timeout=5)
            rows = _records(tmp_path)
            assert set(rows) == {"trial-0001", "trial-0002"}
            assert rows["trial-0001"]["error"] and not rows["trial-0001"]["dispatch_failed"]
            assert rows["trial-0002"]["observation"]["admission"]["state"] == "ACTIVE"
        finally:
            pending_b.set()
        for future in futures:
            assert future.result(timeout=5).succeeded_count == 2
    deliver_a.set()
    assert invoke().succeeded_count == 3
    assert len(ids) == 3


def test_wider_window_detaches_with_an_active_read_and_resumes_same_trials(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from loom import _run, deployment

    template = _template()
    plan = plan_sweep(ManualSweepSpec(
        sweep_id="detach-window", run_uri_root="file:///runs", trials=tuple(
            ManualTrialSpec(overrides={"pipeline.name": name}) for name in ("a", "b", "c")
        ),
    ))
    selection = SimpleNamespace(source=template.preparation.source, preparation_profile="local",
                                startup_seconds=4, wait_seconds=0.8)
    monkeypatch.setattr(deployment, "load_deployment", lambda _: selection)
    entered, allow, closed = Event(), Event(), Event()
    requests = {}

    def observation(request, state):
        row = _outcome(request, state).observation.to_dict()
        row["connection"] = {"coordinator_id": "owner"}
        return SimpleNamespace(to_dict=lambda: row, operation=SimpleNamespace(state="applied"),
                               admission=SimpleNamespace(state=state))

    def start(available, request, **kwargs):
        op = request.preparation.operation_id
        assert op not in requests
        requests[op] = request
        return observation(request, "ACTIVE")

    def open_trial(*args, attachment_id, **kwargs):
        original_read = False

        def read(op, connection, **kwargs):
            nonlocal original_read
            request = requests[op]
            if request.preparation.run_name == "trial-0001" and attachment_id == op:
                original_read = True
                entered.set()
                assert allow.wait(6)
            yield observation(request, "SUCCEEDED" if allow.is_set() else "ACTIVE")

        def close():
            if original_read:
                assert allow.is_set()
                closed.set()

        return SimpleNamespace(connection_id="owner", roles={}, description=SimpleNamespace(coordinator_id="owner"),
                               selection=selection, release=lambda end: None,
                               client=SimpleNamespace(_run_observation_steps=read, close=close))

    monkeypatch.setattr(deployment, "ensure_available", open_trial)
    monkeypatch.setattr(_run, "_start_exact", start)
    monkeypatch.setattr(_run, "_cleanup_step", lambda *args: {"coordinator": {"state": "persistent/borrowed"}})

    def invoke():
        return run_sweep(plan, request_template=template, deployment="selection.json",
                         sweep_dir=tmp_path, max_in_flight=2)

    with ThreadPoolExecutor(max_workers=1) as pool:
        watcher = pool.submit(invoke)
        try:
            assert entered.wait(3)
            watcher.result(timeout=3)
            assert not closed.is_set()
            saved = _records(tmp_path)
            assert set(saved) == {"trial-0001", "trial-0002"}
            assert all(r["observation"]["admission"]["state"] == "ACTIVE" for r in saved.values())
        finally:
            allow.set()
        assert closed.wait(3)
    assert _records(tmp_path) == saved
    selection.wait_seconds = None
    assert invoke().succeeded_count == 3
    assert len(requests) == 3


@pytest.mark.parametrize("window", [0, -1, 1.5, True])
def test_invalid_window_precedes_sweep_persistence(tmp_path, window):
    with pytest.raises(SweepProtocolError, match="positive integer"):
        run_sweep(_plan(), request_template=_template(), deployment="selection.json",
                  sweep_dir=tmp_path / "sweep", max_in_flight=window)
    assert not (tmp_path / "sweep").exists()
