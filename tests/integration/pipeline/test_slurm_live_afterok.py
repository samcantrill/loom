"""Integration tests for live afterok SLURM submission persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from loom.pipeline.execution import StageJobRunRequest, run_stage_job
from loom.pipeline.execution.continuation import ContinuationStateError
from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
    SlurmLiveSubmissionStatus,
    plan_afterok_slurm_dry_run,
    read_slurm_live_manifest,
    submit_afterok_slurm,
)
from loom.pipeline.runtime import (
    RunOptions,
    StageRuntimeOptions,
    build_runtime_metadata,
    resolve_run_runtime,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationState
from loom.serialization import json_dumps_pretty
from tests.integration.pipeline.test_slurm_dry_run_planning import _prepared_store


def test_live_afterok_submission_updates_manifest_registry_and_stage_statuses(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path,
        {
            "extract": (),
            "features": ("extract",),
            "train": ("extract",),
            "report": ("features", "train"),
        },
        authority_backed=True,
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="planning-live-afterok",
        created_at="2026-05-08T00:00:00Z",
    )
    runner = FakeSlurmCommandRunner(starting_job_id=700)

    result = submit_afterok_slurm(
        run_store=store,
        run_uri=run_uri,
        planning_result=planning,
        command_runner=runner,
        submitted_at="2026-05-08T00:00:03Z",
    )

    manifest = read_slurm_live_manifest(
        json.loads(planning.manifest_artifact.local_path.read_text(encoding="utf-8"))
    )
    registry = store.latest_submitted_operation(run_uri)
    status = store.read_run_status(run_uri)

    assert result.status == "SUBMITTED"
    assert [job["scheduler_job_id"] for job in result.submitted_jobs] == [
        "700",
        "701",
        "702",
        "703",
    ]
    assert result.submitted_jobs[1]["dependency_job_ids"] == ["700"]
    assert result.submitted_jobs[2]["dependency_job_ids"] == ["700"]
    assert result.submitted_jobs[3]["dependency_job_ids"] == ["701", "702"]
    assert "--dependency=afterok:701:702" in runner.calls[3][1]
    assert manifest.submission_status is SlurmLiveSubmissionStatus.SUBMITTED
    assert manifest.summary_counts["active"] == 4
    assert registry is not None
    assert registry.state is SubmittedOperationState.SUBMITTED
    assert registry.manifest_relative_path == planning.manifest_artifact.relative_path
    assert status is not None
    assert status.status is RunStatus.SUBMITTED
    for stage_name in ("extract", "features", "train", "report"):
        stage_status = store.read_stage_status(run_uri, stage_name)
        assert stage_status is not None
        assert stage_status.status is StageStatus.SUBMITTED


def test_live_afterok_partial_failure_persists_accepted_and_failed_facts(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path,
        {
            "extract": (),
            "features": ("extract",),
            "report": ("features",),
        },
        authority_backed=True,
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="planning-partial-afterok",
        created_at="2026-05-08T00:00:00Z",
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": (
                SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "extract.sh"),
                    returncode=0,
                    stdout="810\n",
                ),
                SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "features.sh"),
                    returncode=1,
                    stderr="qos rejected",
                ),
            )
        }
    )

    result = submit_afterok_slurm(
        run_store=store,
        run_uri=run_uri,
        planning_result=planning,
        command_runner=runner,
        submitted_at="2026-05-08T00:00:03Z",
    )

    manifest = read_slurm_live_manifest(
        json.loads(planning.manifest_artifact.local_path.read_text(encoding="utf-8"))
    )
    registry = store.latest_submitted_operation(run_uri)

    assert result.status == "PARTIAL"
    assert result.submitted_jobs[0]["scheduler_job_id"] == "810"
    assert result.failed_submissions[0]["logical_key"] == "stage:features"
    assert result.failed_submissions[0]["reason"] == "qos rejected"
    assert result.failed_submissions[0]["dependency_job_ids"] == ["810"]
    assert manifest.submission_status is SlurmLiveSubmissionStatus.PARTIAL
    assert registry is not None
    assert registry.state is SubmittedOperationState.PARTIAL
    assert store.read_stage_status(run_uri, "extract") is not None
    assert store.read_stage_status(run_uri, "features") is None
    assert store.read_stage_status(run_uri, "report") is None


@pytest.mark.parametrize(
    "resource_case",
    [
        "default",
        "selected",
        "legacy",
        "incompatible",
        "wrong_identity",
        "wrong_selection",
    ],
)
def test_live_afterok_submitted_stage_job_materializes_worker_request_at_start(
    tmp_path: Path,
    resource_case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path,
        {"extract": ()},
        authority_backed=True,
    )
    config = _single_stage_config()
    serialized = json_dumps_pretty(config)
    store.write_config_snapshot(run_uri, "resolved", serialized)
    store.write_config_snapshot(run_uri, "resolved_redacted", serialized)
    runtime_options = RunOptions(
        run_uri=run_uri,
        executor="slurm-afterok",
        stage_options=(
            {
                "extract": StageRuntimeOptions(
                    resources={
                        "entries": {
                            "cpu": {"kind": "cpu", "amount": 2},
                            "memory": {
                                "kind": "memory",
                                "amount": 128,
                                "unit": "MiB",
                            },
                            "gpu": {
                                "kind": "gpu",
                                "amount": 1,
                                "attributes": {"fabric_group": "private-fabric-a"},
                            },
                        }
                    },
                    resource_policy={"account_for": ["cpu"], "enforce": []},
                )
            }
            if resource_case == "selected"
            else {}
        ),
    )
    resolved = resolve_run_runtime(runtime_options, stage_ids=("extract",))
    runtime = build_runtime_metadata(
        runtime_options,
        stage_ids=("extract",),
    ).to_dict()
    if resource_case == "legacy":
        runtime.pop("resource_policy")
        stages = runtime["stages"]
        assert isinstance(stages, dict)
        stage_runtime = stages["extract"]
        assert isinstance(stage_runtime, dict)
        stage_runtime.pop("resource_policy")
    store.write_runtime_metadata(run_uri, runtime)
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="planning-startable-afterok",
        created_at="2026-05-08T00:00:00Z",
        stage_runtime=resolved if resource_case != "legacy" else None,
        stage_resources={
            "extract": ResourceRequest(
                entries={"cpu": ResourceEntry(kind="cpu", amount=8)}
            )
        },
    )
    handoff_path = planning.manifest_artifact.local_path.with_name(
        "execution-resources.json"
    )
    if resource_case in {"incompatible", "wrong_identity", "wrong_selection"}:
        handoff = json.loads(handoff_path.read_text())
        if resource_case == "incompatible":
            handoff["schema_version"] = 99
        elif resource_case == "wrong_identity":
            handoff["run_uri"] = "file:///different/run"
        else:
            handoff["stages"]["extract"]["resource_selection"]["account_for"] = ["cpu"]
        handoff_path.write_text(json_dumps_pretty(handoff))
    retained_bytes = handoff_path.read_bytes() if handoff_path.exists() else None
    submit_afterok_slurm(
        run_store=store,
        run_uri=run_uri,
        planning_result=planning,
        command_runner=FakeSlurmCommandRunner(starting_job_id=910),
        submitted_at="2026-05-08T00:00:03Z",
    )

    assert store.read_stage_worker_request(run_uri, "extract", attempt=1) is None

    if resource_case in {"legacy", "incompatible", "wrong_identity", "wrong_selection"}:
        with pytest.raises(
            ContinuationStateError, match="pinned original runtime"
        ) as caught:
            run_stage_job(
                run_store=store,
                request=StageJobRunRequest(
                    run_uri=run_uri, stage_name="extract", executor="local"
                ),
            )
        assert store.read_stage_worker_request(run_uri, "extract", attempt=1) is None
        assert store.read_stage_worker_result(run_uri, "extract", attempt=1) is None
        assert store.read_runtime_metadata(run_uri) == runtime
        assert caught.value.__cause__ is not None
        assert caught.value.code == "execution.stage_job.invalid_resource_handoff"
        assert (
            handoff_path.read_bytes() if handoff_path.exists() else None
        ) == retained_bytes
        return

    request = StageJobRunRequest(
        run_uri=run_uri, stage_name="extract", executor="local"
    )
    worker_bytes = None
    if resource_case == "selected":
        import loom.pipeline.execution.continuation as continuation

        def interrupted(**_kwargs: object) -> None:
            raise RuntimeError("interrupted after worker preparation")

        with monkeypatch.context() as barrier:
            barrier.setattr(
                continuation, "reconstruct_stage_execution_request", interrupted
            )
            with pytest.raises(
                RuntimeError, match="interrupted after worker preparation"
            ):
                run_stage_job(run_store=store, request=request)
        worker_path = store.local_stage_worker_request_path(run_uri, "extract")
        worker_bytes = worker_path.read_bytes()
        monkeypatch.setattr(
            continuation,
            "read_resource_handoff",
            lambda **_kwargs: pytest.fail(
                "retained worker replay must not read fresh preparation"
            ),
        )
    result = run_stage_job(
        run_store=store,
        request=request,
    )

    worker_request = store.read_stage_worker_request(run_uri, "extract", attempt=1)
    assert result.status is StageStatus.SUCCEEDED
    assert worker_request is not None
    saved_runtime = cast(Mapping[str, object], worker_request["resolved_runtime"])
    assert saved_runtime["resource_selection"] == {
        "account_for": ["cpu"] if resource_case == "selected" else [],
        "enforce": [],
    }
    assert store.read_runtime_metadata(run_uri) == runtime
    assert handoff_path.read_bytes() == retained_bytes
    if worker_bytes is not None:
        assert (
            store.local_stage_worker_request_path(run_uri, "extract").read_bytes()
            == worker_bytes
        )
    assert (
        saved_runtime["resources"]
        == resolved["extract"]._to_worker_metadata()["resources"]
    )
    assert (
        saved_runtime["resource_policy"]
        == resolved["extract"]._to_worker_metadata()["resource_policy"]
    )
    assert "private-fabric-a" not in json.dumps(runtime)
    if resource_case == "selected":
        saved_resources = cast(Mapping[str, object], saved_runtime["resources"])
        assert set(cast(Mapping[str, object], saved_resources["entries"])) == {
            "cpu",
            "memory",
            "gpu",
        }
    metadata = cast(Mapping[str, object], worker_request["metadata"])
    submitted = cast(Mapping[str, object], metadata["submitted_operation"])
    assert submitted["backend"] == "slurm"


def test_afterok_preparation_retains_exact_private_intent_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"extract": ()})
    options = RunOptions(
        executor="slurm-afterok",
        stage_options={
            "extract": StageRuntimeOptions(
                resources={
                    "entries": {
                        "gpu": {
                            "kind": "gpu",
                            "amount": 1,
                            "attributes": {"fabric_group": "private-fabric-a"},
                        }
                    }
                },
                resource_policy={"account_for": [], "enforce": []},
            )
        },
    )
    runtime = resolve_run_runtime(options, stage_ids=("extract",))
    arguments: dict[str, Any] = dict(
        run_store=store,
        run_uri=run_uri,
        planning_id="immutable-resources",
        created_at="2026-05-08T00:00:00Z",
        stage_runtime=runtime,
        stage_resources={
            "extract": ResourceRequest(
                entries={"cpu": ResourceEntry(kind="cpu", amount=8)}
            )
        },
    )
    with pytest.raises(RuntimeResourceError, match="matching resolved runtime"):
        plan_afterok_slurm_dry_run(**{**arguments, "stage_runtime": {}})
    assert not store.local_generated_artifact_path(
        run_uri, "slurm/submissions/immutable-resources/manifest.json"
    ).exists()
    planned = plan_afterok_slurm_dry_run(**arguments)
    path = planned.manifest_artifact.local_path.with_name("execution-resources.json")
    before = path.read_bytes()
    timestamp = path.stat().st_mtime_ns
    public_before = {
        item.local_path: item.local_path.read_bytes()
        for item in planned.generated_artifacts
    }
    plan_afterok_slurm_dry_run(**arguments)
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == timestamp
    assert path.stat().st_mode & 0o777 == 0o600
    assert "private-fabric-a" not in json.dumps(planned.to_dict())
    handoff = json.loads(before)
    assert handoff["stages"]["extract"]["resources"]["entries"]["gpu"][
        "attributes"
    ] == {"fabric_group": "private-fabric-a"}
    conflicting = resolve_run_runtime(RunOptions(), stage_ids=("extract",))
    with pytest.raises(
        RuntimeResourceError, match="conflicts with retained preparation"
    ):
        plan_afterok_slurm_dry_run(**{**arguments, "stage_runtime": conflicting})
    assert path.read_bytes() == before
    assert {item: item.read_bytes() for item in public_before} == public_before


def test_afterok_legacy_preparation_cannot_be_retrofitted(tmp_path: Path) -> None:
    store, run_uri = _prepared_store(tmp_path, {"extract": ()})
    arguments: dict[str, Any] = dict(
        run_store=store, run_uri=run_uri, planning_id="legacy-resources"
    )
    planned = plan_afterok_slurm_dry_run(**arguments)
    before = planned.manifest_artifact.local_path.read_bytes()
    with pytest.raises(RuntimeResourceError, match="cannot be retrofitted"):
        plan_afterok_slurm_dry_run(
            **arguments,
            stage_runtime=resolve_run_runtime(RunOptions(), stage_ids=("extract",)),
        )
    assert planned.manifest_artifact.local_path.read_bytes() == before
    assert not planned.manifest_artifact.local_path.with_name(
        "execution-resources.json"
    ).exists()


def _single_stage_config() -> dict[str, object]:
    return {
        "pipeline": {
            "name": "afterok-startable",
            "stages": [
                {
                    "name": "extract",
                    "factory": {
                        "_target_": (
                            "tests.support.pipeline_execution_stages.JsonProducerStage"
                        )
                    },
                    "outputs": {
                        "data": {
                            "artifact_type": "json",
                            "codec_key": "json.v1",
                        }
                    },
                }
            ],
        }
    }
