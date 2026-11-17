"""Whole-cycle result priority, exact history, query budgets and fair progress."""

from dataclasses import replace
from collections.abc import Mapping
import subprocess

import pytest

from loom.pipeline.executors.slurm.commands import SlurmCommandResult
from loom.pipeline.executors.slurm.history import operation_job_name
from loom.pipeline.executors.slurm.ready_stage import ReadyStageState
from loom.queue._agent_slurm import AgentSlurmJobs
from loom.queue._slurm_observation import SlurmObservationPolicy, parse_slurm_observation_policy
from loom.queue.errors import QueueConfigError
from tests.unit.loom.queue.test_agent_slurm import _task
from tests.unit.loom.queue.test_slurm_observation import _owner, _ack, _publish_result, _queries
from tests.unit.loom.queue.test_agent_slurm_storage import drive_until


def _batch_owner(tmp_path, monkeypatch, *, size=8, calls=4, budget=10, submission=None):
    import loom.queue._agent_slurm as module

    _old, _one, clock, runner, profile = _owner(tmp_path, monkeypatch, accounting=[], submission=submission)
    monkeypatch.setattr(module, "utc_timestamp", lambda: "2026-11-02T00:00:00Z")
    policy = SlurmObservationPolicy(300, size, calls, budget)
    owner = AgentSlurmJobs(tmp_path, (profile,), observation_policy=policy)
    return owner, clock, runner, profile


def _line(key, *, uid=1000, submitted="2026-11-02T00:00:00", sluid=None):
    return f"{16 + key}|{operation_job_name(f'operation-{key}')}|{uid}|cluster-a|{submitted}|{40 + key}|{sluid or f's{key}'}|RUNNING\n"


@pytest.mark.parametrize("slow", [False, True])
def test_containment_budget_is_bounded_and_fair(tmp_path, monkeypatch, slow):
    from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentReceipt
    import loom.queue._agent_slurm as module

    owner, clock, runner, profile = _batch_owner(tmp_path, monkeypatch, calls=2, budget=10)
    tasks = [_task(profile, key=str(i)) for i in range(1, 6)]
    owner.step_cycle(tasks, _ack)
    probes = []

    def containment(_profile, proof):
        probes.append(proof["operation"])
        if slow:
            clock[0] += 10
        return SlurmContainmentReceipt("UNKNOWN", diagnostic_code="terminal_controller_record_retained")

    monkeypatch.setattr(module, "resolve_slurm_containment", containment)
    tasks = [{**task, "release_requested": True, "containment_request": {"operation": str(i)}}
             for i, task in enumerate(tasks, start=1)]
    received = []
    for _ in range(5 if slow else 3):
        before = len(probes)
        owner.step_cycle(tasks, lambda value: (received.append(value) or _ack(value)))
        assert len(probes) - before <= (1 if slow else 2)
        clock[0] += 30
    assert probes[:5] == ["1", "2", "3", "4", "5"]
    assert any(value.get("containment_diagnostic") == "terminal_controller_record_retained" for value in received)
    assert owner.has_retained_work()


def _query_responses(monkeypatch, runner, response):
    original = runner.discover_named_operations
    def query(**selection):
        original(**selection)
        return SlurmCommandResult("sacct", ("sacct",), 0, stdout=response(selection))
    monkeypatch.setattr(runner, "discover_named_operations", query)


def test_blocked_accounting_batch_allows_other_assignment_submission_and_cancel(tmp_path, monkeypatch):
    from threading import Event

    owner, clock, runner, profile = _batch_owner(tmp_path, monkeypatch)
    owner._asynchronous_preparation = True
    entered, release = Event(), Event()
    calls = []

    def blocked(**selection):
        calls.append(selection)
        entered.set()
        assert release.wait(10)
        return SlurmCommandResult("sacct", ("sacct",), 0, stdout=_line(1))

    monkeypatch.setattr(runner, "discover_named_operations", blocked)
    monkeypatch.setattr(runner, "discover_named_operation", lambda **_selection: SlurmCommandResult("sacct", ("sacct",), 0, stdout=_line(2)))
    first, peer = _task(profile), _task(profile, key="2")
    def turn(function, *args):
        clock[0] += 0.1
        function(*args)
    try:
        drive_until(lambda: turn(owner.step_cycle, [first], _ack), entered.is_set)
        drive_until(lambda: turn(owner.step, peer, _ack), lambda: (value := owner.journal.find("operation-2")) is not None and value.job_id is not None)
        closing = {**peer, "cancel_requested": True, "containment_request": {}}
        def cancel(value):
            return {"sequence": value["sequence"], "cancel_requested": True}
        drive_until(lambda: turn(owner.step, closing, cancel), lambda: owner.journal.read("operation-2").cancel_requested)
        assert not release.is_set()
        for _ in range(10):
            owner.step_cycle([first], _ack)
        assert len(calls) == 1, "pending accounting must retain its bounded query slot"
        assert sum(call[0] == "sbatch" for call in runner.calls) == 2
        release.set()
        drive_until(lambda: turn(owner.step_cycle, [first], _ack), lambda: not owner._batch_pending)
    finally:
        release.set()
        owner.close()


def test_one_batch_associates_unknown_and_observes_known_without_resubmission(tmp_path, monkeypatch):
    owner, clock, runner, profile = _batch_owner(
        tmp_path, monkeypatch, submission=[subprocess.TimeoutExpired("sbatch", 60)],
    )
    tasks = [_task(profile, key=str(i)) for i in (1, 2)]
    _query_responses(monkeypatch, runner, lambda _selection: _line(1) + _line(2))
    owner.step_cycle(tasks, _ack)
    assert _queries(runner) == 1
    for key in (1, 2):
        current = owner.journal.read(f"operation-{key}")
        assert current.state is ReadyStageState.ACCEPTED
        assert current.job_id == str(16 + key)
        assert current.scheduler_state == "RUNNING"
        assert current.accounting_identity is not None
        assert current.accounting_identity.sluid == f"s{key}"
    reopened = AgentSlurmJobs(tmp_path, (profile,), observation_policy=owner.observation_policy)
    reopened.step_cycle(tasks, _ack, allow_submission=False)
    assert _queries(runner) == 2
    assert sum(command == "sbatch" for command, _argv in runner.calls) == 2


def test_blocked_result_read_allows_peer_submission_observation_and_cancellation(tmp_path, monkeypatch):
    from threading import Event
    from loom.queue._slurm_result_transport import SharedSlurmResult

    owner, clock, runner, profile = _batch_owner(tmp_path, monkeypatch)
    one, two, new = [_task(profile, key=str(i)) for i in (1, 2, 3)]
    owner.step_cycle([one, two], _ack)
    identity, transport = _publish_result(one, profile)
    calls = []
    entered, release = Event(), Event()
    inspect = SharedSlurmResult.inspect_if_available

    def blocked(transport, selected):
        entered.set()
        assert release.wait(5)
        return inspect(transport, selected)

    monkeypatch.setattr(SharedSlurmResult, "inspect_if_available", blocked)
    original = runner.discover_named_operation
    def exact_cancel(**selection):
        original(**selection)
        return SlurmCommandResult("sacct", ("sacct",), 0, stdout=_line(2))
    monkeypatch.setattr(runner, "discover_named_operation", exact_cancel)
    cancel = False
    def acknowledge(value):
        if "result_operation" in value:
            calls.append(value["result_operation"])
            return {"acknowledged": True}
        return {"sequence": value["sequence"], "cancel_requested": cancel and value["assignment"]["assignment_id"] == "assignment-2"}
    try:
        owner.step_cycle([{**one, "result_identity": identity}], acknowledge)
        assert entered.wait(1)
        before = _queries(runner)
        clock[0] = 30
        cancel = True
        owner.step_cycle([new, {**two, "cancel_requested": True, "containment_request": {}},
                          {**one, "result_identity": identity}], acknowledge)
        assert calls == [] and not release.is_set()
        assert owner.journal.read("operation-3").job_id is not None
        assert _queries(runner) > before
        assert any(command == "scancel" for command, _argv in runner.calls)
        release.set()
        drive_until(lambda: owner.step_cycle([{**one, "result_identity": identity}], acknowledge),
                    lambda: not transport.path.exists())
        assert calls == ["report", "commit"]
        assert sum(command == "sbatch" for command, _argv in runner.calls) == 3
    finally:
        release.set()
        owner.close()


def test_full_result_quota_defers_only_new_assignment_and_drains_existing_work(tmp_path, monkeypatch):
    from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentReceipt

    monkeypatch.setattr(
        "loom.queue._agent_slurm.resolve_slurm_containment",
        lambda *_args: SlurmContainmentReceipt("UNKNOWN"),
    )
    owner, clock, runner, original = _batch_owner(tmp_path, monkeypatch)
    assert isinstance(original.result_storage, Mapping)
    profile = replace(original, result_storage={
        **original.result_storage, "retention_bytes": 2 * 65 * 1024**2,
    })
    owner = AgentSlurmJobs(tmp_path, (profile,), observation_policy=owner.observation_policy)
    finished, cancelled, waiting = [_task(profile, key=str(i)) for i in (1, 2, 3)]
    owner.step_cycle([finished, cancelled], _ack)
    observe = runner.discover_named_operation

    def exact_cancel_observation(**selection):
        observe(**selection)
        return SlurmCommandResult("sacct", ("sacct",), 0, stdout=_line(2))

    monkeypatch.setattr(runner, "discover_named_operation", exact_cancel_observation)
    identity, transport = _publish_result(finished, profile)
    calls = []

    def acknowledge(value):
        if "result_operation" in value:
            calls.append(value["result_operation"])
            return {"acknowledged": True}
        return {
            "sequence": value["sequence"],
            "cancel_requested": value["assignment"]["assignment_id"] == "assignment-2",
        }

    owner.step_cycle([
        waiting, {**finished, "result_identity": identity},
        {**cancelled, "cancel_requested": True, "containment_request": {}},
    ], acknowledge)
    assert owner.journal.find("operation-3") is None
    assert any(command == "scancel" for command, _args in runner.calls)
    drive_until(lambda: owner.step_cycle([{**finished, "result_identity": identity}], acknowledge),
                lambda: not transport.path.exists())
    assert calls == ["report", "commit"]
    clock[0] += 5
    owner.step_cycle([waiting], _ack)
    assert owner.journal.read("operation-3").job_id is not None
    assert sum(command == "sbatch" for command, _args in runner.calls) == 3


def test_call_limit_and_rotation_do_not_starve_later_cpu_jobs(tmp_path, monkeypatch):
    owner, clock, runner, profile = _batch_owner(tmp_path, monkeypatch, size=2, calls=4)
    tasks = [_task(profile, key=str(i)) for i in range(1, 13)]
    owner.step_cycle(tasks, _ack)
    assert _queries(runner) == 4
    assert owner.journal.read("operation-9").evidence is None
    clock[0] = 30  # Earlier jobs are due again, but unqueried jobs get priority.
    owner.step_cycle(tasks, _ack, allow_submission=False)
    queries = [argv for command, argv in runner.calls if command == "sacct"]
    assert len(queries) == 8
    assert f"--name={operation_job_name('operation-9')},{operation_job_name('operation-10')}" in queries[4]
    assert f"--name={operation_job_name('operation-11')},{operation_job_name('operation-12')}" in queries[5]
    assert sum(command == "sbatch" for command, _argv in runner.calls) == 12


def test_shared_deadline_passes_remaining_budget_and_leaves_other_jobs_due(tmp_path, monkeypatch):
    owner, clock, runner, profile = _batch_owner(tmp_path, monkeypatch, size=1, calls=4, budget=5)
    original = runner.discover_named_operations
    def query(**selection):
        result = original(**selection)
        clock[0] += min(3, selection["timeout_seconds"])
        return result
    monkeypatch.setattr(runner, "discover_named_operations", query)
    tasks = [_task(profile, key=str(i)) for i in (1, 2, 3)]
    owner.step_cycle(tasks, _ack)
    assert runner.observation_timeouts == [5, 2]
    assert clock[0] == 5
    assert owner.journal.read("operation-3").evidence is None
    owner.step_cycle(tasks, _ack, allow_submission=False)
    assert runner.observation_timeouts == [5, 2, 5]
    assert owner.journal.read("operation-3").evidence == "slurm_history_not_found"


@pytest.mark.parametrize("bad_row", [
    _line(1, uid=1001), _line(1, submitted="2026-11-01T23:00:00"),
    _line(1) + _line(1), _line(1, sluid="different"),
])
def test_each_operation_rechecks_its_own_accounting_identity(tmp_path, monkeypatch, bad_row):
    owner, clock, runner, profile = _batch_owner(tmp_path, monkeypatch)
    tasks = [_task(profile, key=str(i)) for i in (1, 2)]
    _query_responses(monkeypatch, runner, lambda _selection: _line(1) + _line(2))
    owner.step_cycle(tasks, _ack)
    saved = owner.journal.read("operation-1").accounting_identity
    _query_responses(monkeypatch, runner, lambda _selection: bad_row + _line(2))
    clock[0] = 30
    owner.step_cycle(tasks, _ack)
    first, second = [owner.journal.read(f"operation-{i}") for i in (1, 2)]
    assert first.accounting_identity == saved
    assert first.scheduler_source == "unavailable" and first.scheduler_state is None
    assert second.scheduler_source == "sacct" and second.scheduler_state == "RUNNING"


@pytest.mark.parametrize("output", ["malformed", _line(99)])
def test_unattributable_rows_invalidate_complete_batch(tmp_path, monkeypatch, output):
    owner, _clock, runner, profile = _batch_owner(tmp_path, monkeypatch)
    _query_responses(monkeypatch, runner, lambda _selection: _line(1) + output)
    owner.step_cycle([_task(profile, key=str(i)) for i in (1, 2)], _ack)
    assert all(owner.journal.read(f"operation-{i}").scheduler_source == "unavailable" for i in (1, 2))


def test_overflow_splits_later_batches_and_single_oversize_stays_unresolved(tmp_path, monkeypatch):
    owner, clock, runner, profile = _batch_owner(tmp_path, monkeypatch)
    names = {operation_job_name(f"operation-{i}"): i for i in range(1, 5)}
    batches = []
    def output(selection):
        selected = selection["job_names"]
        batches.append(len(selected))
        if len(selected) > 2 or len(selected) == 1 and names[selected[0]] == 1:
            return _line(1) * 50
        return "".join(_line(names[name]) for name in selected)
    _query_responses(monkeypatch, runner, output)
    tasks = [_task(profile, key=str(i)) for i in range(1, 5)]
    owner.step_cycle(tasks, _ack)
    assert batches == [4]
    assert owner.journal.read("operation-1").evidence == "slurm_history_output_limit"
    clock[0] = 30
    owner.step_cycle(tasks, _ack)
    assert batches == [4, 2, 2]
    assert all(owner.journal.read(f"operation-{i}").scheduler_state == "RUNNING" for i in range(1, 5))
    owner.observation_policy = SlurmObservationPolicy(300, 1, 4, 10)
    clock[0] = 60
    owner.step_cycle(tasks, _ack)
    assert owner.journal.read("operation-1").evidence == "slurm_history_output_limit"
    assert owner.journal.read("operation-1").scheduler_source == "unavailable"
    assert owner.has_retained_work()
    assert sum(command == "sbatch" for command, _argv in runner.calls) == 4


def test_lost_batched_evidence_ack_replays_same_receipt_after_restart(tmp_path, monkeypatch):
    owner, _clock, runner, profile = _batch_owner(tmp_path, monkeypatch)
    tasks = [_task(profile, key=str(i)) for i in (1, 2)]
    _query_responses(monkeypatch, runner, lambda _selection: _line(1) + _line(2))
    lost = []
    def acknowledge(value):
        if value["submission"].get("scheduler_state") == "RUNNING":
            lost.append(value)
            raise OSError("lost batched evidence")
        return _ack(value)
    with pytest.raises(OSError, match="lost batched"):
        owner.step_cycle(tasks, acknowledge)
    reopened = AgentSlurmJobs(tmp_path, (profile,), observation_policy=owner.observation_policy)
    seen = []
    reopened.step_cycle(tasks, lambda value: (seen.append(value) or _ack(value)), allow_submission=False)
    assert seen[0] == lost[0]
    assert all(reopened.journal.read(f"operation-{i}").scheduler_state == "RUNNING" for i in (1, 2))
    assert sum(command == "sbatch" for command, _argv in runner.calls) == 2


def test_batching_refuses_unsupported_profile_before_state_open(tmp_path, monkeypatch):
    _owner_value, _clock, _runner, profile = _batch_owner(tmp_path, monkeypatch)
    with pytest.raises(QueueConfigError, match="bounded named-accounting"):
        AgentSlurmJobs(tmp_path / "missing", (replace(profile, accounting_history=None),), observation_policy=SlurmObservationPolicy(300, 8, 4, 10))
    assert not (tmp_path / "missing").exists()


def test_profiles_do_not_share_observation_batches(tmp_path, monkeypatch):
    owner, _clock, runner, profile = _batch_owner(tmp_path, monkeypatch)
    other = replace(profile, profile_id="other-profile")
    owner = AgentSlurmJobs(tmp_path, (profile, other), observation_policy=owner.observation_policy)
    owner.step_cycle([_task(profile), _task(other, key="2")], _ack)
    assert _queries(runner) == 2


def test_union_query_window_does_not_weaken_each_operation_window(tmp_path, monkeypatch):
    import loom.queue._agent_slurm as agent_module
    import loom.pipeline.executors.slurm.ready_stage as ready_module

    owner, _clock, runner, profile = _batch_owner(tmp_path, monkeypatch)
    first, second = _task(profile), _task(profile, key="2")
    owner.step_cycle([first], _ack, allow_submission=False)
    monkeypatch.setattr(ready_module, "utc_timestamp", lambda: "2026-11-02T00:30:00Z")
    monkeypatch.setattr(agent_module, "utc_timestamp", lambda: "2026-11-02T00:30:00Z")
    owner.step_cycle([second], _ack, allow_submission=False)
    _query_responses(monkeypatch, runner, lambda _selection: _line(1) + _line(2))
    owner.step_cycle([first, second], _ack)
    assert _queries(runner) == 1
    assert owner.journal.read("operation-1").scheduler_state == "RUNNING"
    assert owner.journal.read("operation-2").scheduler_source == "unavailable"


@pytest.mark.parametrize("change", [
    {"max_jobs_per_query": None}, {"max_jobs_per_query": True}, {"max_jobs_per_query": 65},
    {"max_queries_per_cycle": 0}, {"max_queries_per_cycle": 129},
    {"cycle_budget_seconds": True}, {"cycle_budget_seconds": float("nan")},
    {"cycle_budget_seconds": float("inf")}, {"cycle_budget_seconds": 10**400},
])
def test_batch_policy_rejects_partial_or_unbounded_values(change):
    declaration = {"failure_backoff_cap_seconds": 300, "max_jobs_per_query": 8, "max_queries_per_cycle": 4, "cycle_budget_seconds": 10}
    with pytest.raises(QueueConfigError):
        parse_slurm_observation_policy({**declaration, **change})
    with pytest.raises(QueueConfigError):
        parse_slurm_observation_policy({"failure_backoff_cap_seconds": 300, **change})
