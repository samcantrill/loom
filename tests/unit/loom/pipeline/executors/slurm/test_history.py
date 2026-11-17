"""Exact operation-name history, retained incarnation, and conservative replay."""

from dataclasses import replace
import subprocess

from typing import Any

import pytest

from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner, SlurmCommandPolicy, SlurmCommandResult, SubprocessSlurmCommandRunner,
)
from loom.pipeline.executors.slurm.errors import SlurmPlanningError
from loom.pipeline.executors.slurm.history import SlurmHistoryPolicy, operation_job_name
from loom.pipeline.executors.slurm.ready_stage import (
    ReadyStageState, SQLiteReadyStageSubmissions, SlurmContainmentHelper,
    SlurmReadyStageSubmission, resolve_slurm_containment,
)
from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import _profile, _request, _script


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(
        "loom.pipeline.executors.slurm.ready_stage.utc_timestamp",
        lambda: "2026-11-02T00:00:00Z",
    )


def _selected(tmp_path, runner):
    return replace(
        _profile(runner, provider=SlurmUserPrivateFileProvider(
            root=tmp_path / "credentials", descriptor="history-test-v1",
        )),
        accounting_history=SlurmHistoryPolicy(user_id=1000),
    )


def _row(**changes):
    values = dict(
        job="17", name=operation_job_name("operation-1"), uid="1000", cluster="cluster-a",
        submitted="2026-11-02T00:00:00", db_index="42", sluid="s5YDM6CNYGSP00", state="RUNNING",
    )
    values.update(changes)
    return "|".join(values.values()) + "\n"


def _runner(*rows):
    return FakeSlurmCommandRunner(
        command_policy=SlurmCommandPolicy(10, 60, 10),
        scripted_results={
            "sbatch": [subprocess.TimeoutExpired("sbatch", 60)],
            "sacct": [
                row if isinstance(row, (BaseException, SlurmCommandResult)) else
                SlurmCommandResult("sacct", ("sacct",), 0, stdout=row)
                for row in rows
            ],
        },
    )


def _uncertain(tmp_path, runner):
    profile = _selected(tmp_path, runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    script = _script(tmp_path, request)
    uncertain = store.submit(request, profile, script)
    assert uncertain.state is ReadyStageState.UNKNOWN
    return profile, request, store, script


def test_history_changes_only_selected_profile_and_script(tmp_path):
    runner = _runner()
    profile = _selected(tmp_path, runner)
    legacy = replace(profile, accounting_history=None)
    request = _request(profile)
    assert request.profile_descriptor != _request(legacy).profile_descriptor
    assert len(operation_job_name(request.operation_id)) == 69
    directives = {item.name: item.value for item in request.directives}
    assert directives["job-name"] == operation_job_name(request.operation_id)
    assert directives["clusters"] == "cluster-a"
    assert "job-name" not in {item.name for item in _request(legacy).directives}
    assert request.script != _request(legacy).script
    for changes in ({"cluster": None}, {"cluster": "all"}, {"cluster": "cluster-a,cluster-b"},
                    {"runner": FakeSlurmCommandRunner()}):
        with pytest.raises(SlurmPlanningError):
            replace(profile, **changes)
    assert not (tmp_path / "credentials").exists()


@pytest.mark.parametrize("fields", [
    {"user_id": True}, {"user_id": -1}, {"user_id": "1000"},
    {"user_id": 1000, "clock_skew_seconds": -1},
    {"user_id": 1000, "clock_skew_seconds": 301},
    {"user_id": 1000, "clock_skew_seconds": True},
])
def test_history_rejects_invalid_uid_or_skew(fields):
    with pytest.raises(SlurmPlanningError):
        SlurmHistoryPolicy(**fields)


def test_lost_reply_reconciles_from_name_without_comments_and_retains_identity(tmp_path):
    runner = _runner(_row())
    profile, request, store, script = _uncertain(tmp_path, runner)
    reopened = SQLiteReadyStageSubmissions(store.path, _allow_initialize=False)
    accepted = reopened.reconcile(request.operation_id, profile)
    assert accepted.state is ReadyStageState.ACCEPTED
    assert accepted.job_id == "17"
    assert accepted.accounting_identity is not None
    assert accepted.accounting_identity.db_index == "42"
    assert accepted.accounting_identity.sluid == "s5YDM6CNYGSP00"
    assert accepted.schema_version == 4
    assert SlurmReadyStageSubmission.from_dict(accepted.to_dict()) == accepted
    assert reopened.submit(request, profile, script) == accepted
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1
    query = [argv for command, argv in runner.calls if command == "sacct"][0]
    assert "--duplicates" in query
    assert "--starttime=2026-11-01T23:59:00" in query
    assert "--endtime=2026-11-02T00:01:00" in query
    assert f"--name={operation_job_name(request.operation_id)}" in query
    assert "Comment" not in " ".join(query)
    assert "--user=1000" in query and "--clusters=cluster-a" in query

    from loom.queue._agent_slurm import SlurmSubmissionProjection
    projection = SlurmSubmissionProjection(tmp_path / "projection.sqlite", _allow_initialize=True)
    projection.acknowledge(accepted)
    assert projection.read(request.operation_id) == accepted

    missing = accepted.to_dict()
    missing.pop("accounting_identity")
    with pytest.raises(SlurmPlanningError, match="fields"):
        SlurmReadyStageSubmission.from_dict(missing)
    downgraded = accepted.to_dict()
    downgraded["schema_version"] = 3
    with pytest.raises(SlurmPlanningError, match="fields"):
        SlurmReadyStageSubmission.from_dict(downgraded)


def test_unselected_history_preserves_receipt_version_and_shape(tmp_path):
    profile = replace(_selected(tmp_path, _runner()), accounting_history=None)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "legacy.sqlite")
    receipt = store.prepare(request, profile, _script(tmp_path, request))
    assert receipt.schema_version == 3
    assert "accounting_identity" not in receipt.to_dict()
    assert SlurmReadyStageSubmission.from_dict(receipt.to_dict()) == receipt


def test_known_handle_gains_accounting_identity_without_inferring_completion(tmp_path):
    runner = FakeSlurmCommandRunner(
        command_policy=SlurmCommandPolicy(10, 60, 10),
        scripted_results={"sacct": [SlurmCommandResult(
            "sacct", ("sacct",), 0, stdout=_row(job="1000", state="COMPLETED"),
        )]},
    )
    profile = _selected(tmp_path, runner)
    request = _request(profile)
    store = SQLiteReadyStageSubmissions(tmp_path / "submissions.sqlite")
    accepted = store.submit(request, profile, _script(tmp_path, request))
    assert accepted.accounting_identity is None
    observed = store.observe(request.operation_id, profile)
    assert observed.accounting_identity is not None
    assert observed.accounting_identity.job_id == "1000"
    assert observed.scheduler_state == "COMPLETED"
    assert observed.state is ReadyStageState.ACCEPTED
    assert not observed.start_consumed


@pytest.mark.parametrize(("row", "diagnostic"), [
    ("", "slurm_history_not_found"),
    (_row() + _row(job="18"), "slurm_history_ambiguous"),
    (_row() + _row(db_index="43", sluid="sOther"), "slurm_history_ambiguous"),
    (_row(name=operation_job_name("operation-1")[:20] + "+"), "slurm_history_unavailable"),
    (_row(uid="1001"), "slurm_history_unavailable"),
    (_row(cluster="cluster-b"), "slurm_history_unavailable"),
    (_row(submitted="2026-11-01T00:00:00"), "slurm_history_unavailable"),
    (_row(db_index=""), "slurm_history_unavailable"),
    (_row(sluid=""), "slurm_history_unavailable"),
    (_row(sluid="unknown"), "slurm_history_unavailable"),
    (_row(job="0"), "slurm_history_unavailable"),
    (_row() + "...[truncated]", "slurm_history_unavailable"),
    (subprocess.TimeoutExpired("sacct", 10), "slurm_history_timeout"),
    (SlurmCommandResult("sacct", ("sacct",), 1), "slurm_history_command_failed"),
])
def test_incomplete_ambiguous_or_unavailable_history_never_resubmits(tmp_path, row, diagnostic):
    runner = _runner(row)
    profile, request, store, script = _uncertain(tmp_path, runner)
    result = store.reconcile(request.operation_id, profile)
    assert result.state is ReadyStageState.UNKNOWN
    assert result.accounting_identity is None
    assert result.evidence == diagnostic
    assert store.submit(request, profile, script) == result
    assert len([call for call in runner.calls if call[0] == "sbatch"]) == 1


def test_reused_numeric_id_cannot_replace_identity_or_trigger_unfiltered_cancel(tmp_path):
    replacement = _row(db_index="43", sluid="sReplacement")
    runner = _runner(_row(), replacement, replacement, _row())
    profile, request, store, _script_path = _uncertain(tmp_path, runner)
    accepted = store.reconcile(request.operation_id, profile)
    unavailable = store.observe(request.operation_id, profile)
    assert unavailable.scheduler_source == "unavailable"
    assert unavailable.evidence == "slurm_history_identity_conflict"
    assert unavailable.accounting_identity == accepted.accounting_identity
    assert not store.request_cancel(request.operation_id, profile).cancel_requested
    assert not [call for call in runner.calls if call[0] == "scancel"]
    cancelled = store.request_cancel(request.operation_id, profile)
    assert cancelled.cancel_requested
    assert cancelled.accounting_identity == accepted.accounting_identity
    assert [argv for command, argv in runner.calls if command == "scancel"] == [(
        "scancel", "--clusters=cluster-a", "--user=1000",
        f"--name={operation_job_name(request.operation_id)}", "17",
    )]


def test_real_runner_uses_explicit_utc_format_for_history(monkeypatch):
    calls = []
    def capture(self, command, argv, *, environment=None):
        calls.append((command, argv, environment))
        return SlurmCommandResult(command, argv, 0)
    monkeypatch.setattr(SubprocessSlurmCommandRunner, "_run", capture)
    SubprocessSlurmCommandRunner(command_policy=SlurmCommandPolicy(10, 60, 10)).discover_named_operation(
        job_name=operation_job_name("operation-1"), user_id=1000, cluster="cluster-a",
        started_after="2026-11-01T23:59:00Z", ended_before="2026-11-02T00:01:00Z",
    )
    assert calls[0][2]["TZ"] == "UTC"
    assert calls[0][2]["SLURM_TIME_FORMAT"] == "%Y-%m-%dT%H:%M:%S"


def test_selected_containment_requires_retained_exact_accounting_identity(tmp_path, monkeypatch):
    runner = _runner(_row())
    profile, request, store, _script_path = _uncertain(tmp_path, runner)
    accepted = store.reconcile(request.operation_id, profile)
    profile = replace(profile, containment_helper=SlurmContainmentHelper("history-test", ("/unused/helper",)))
    calls = []
    def resolve(self, request):
        calls.append(request)
        return {"state": "CONTAINED", "evidence_id": "fixture", "evidence_revision": "v1", "echo": dict(request)}
    monkeypatch.setattr(SlurmContainmentHelper, "resolve", resolve)
    proof: dict[str, Any] = {"job_id": "17", "cluster_id": "cluster-a", "submission_operation_id": request.operation_id}
    assert not resolve_slurm_containment(profile, proof).contained
    assert accepted.accounting_identity is not None
    proof["accounting_identity"] = {**accepted.accounting_identity.to_dict(), "user_id": 1001}
    assert not resolve_slurm_containment(profile, proof).contained
    assert not calls
    proof["accounting_identity"] = accepted.accounting_identity.to_dict()
    assert resolve_slurm_containment(profile, proof).contained
    assert len(calls) == 1
