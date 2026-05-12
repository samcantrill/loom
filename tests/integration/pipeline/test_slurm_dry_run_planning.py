"""Integration tests for SLURM dry-run planning artifact writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from loom.pipeline.execution import (
    PREPARED_RUN_CONTINUATION_WHOLE_RUN,
    PREPARED_RUN_SCHEMA_VERSION,
    PreparedRunRecord,
    create_authority_backed_serial_run_store,
)
from loom.pipeline.executors.slurm import (
    SlurmOptions,
    SlurmPlannedDependency,
    SlurmPlannedJob,
    SlurmPlannedSubmission,
)
from loom.pipeline.executors.slurm.planning import (
    plan_afterok_slurm_dry_run,
    plan_single_job_slurm_dry_run,
)
from loom.pipeline.planning import (
    ExecutionPlan,
    FingerprintContext,
    FingerprintStatus,
    PlanAction,
    PlanSelectors,
    ResumeOptions,
    StagePlan,
)
from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    LocalRunStore,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


def test_single_job_dry_run_writes_manifest_plan_and_script_under_run_dir(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"build": ()})

    result = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        options=SlurmOptions(prelude=("module load python",)),
        planning_id="planning-single",
        created_at="2026-05-08T00:00:00Z",
    )

    run_dir = store.local_run_dir(run_uri)
    script = result.script_artifacts["pipeline"].local_path
    manifest_payload = cast(dict[str, object], _read_json(result.manifest_artifact.local_path))
    plan_payload = cast(dict[str, object], _read_json(result.plan_artifact.local_path))

    assert result.manifest_artifact.relative_path == (
        "slurm/submissions/planning-single/manifest.json"
    )
    assert script.is_relative_to(run_dir)
    assert result.manifest_artifact.local_path.is_relative_to(run_dir)
    assert result.plan_artifact.local_path.is_relative_to(run_dir)
    assert script.read_text() == "\n".join(
        (
            "#!/usr/bin/env bash",
            "#SBATCH --job-name=loom-planning-single-pipeline",
            "#SBATCH --output=slurm/submissions/planning-single/logs/pipeline.stdout.log",
            "#SBATCH --error=slurm/submissions/planning-single/logs/pipeline.stderr.log",
            "",
            "set -euo pipefail",
            "",
            "module load python",
            "",
            f"loom prepared-run continue --run-uri {run_uri} --executor local",
            "",
        )
    )
    assert SlurmPlannedSubmission.from_dict(manifest_payload) == result.submission
    assert plan_payload["kind"] == "loom.slurm_dry_run_plan"
    assert "SECRET" not in json.dumps(plan_payload)


def test_afterok_dry_run_writes_manifest_round_trip_and_stage_scripts(
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
    )

    result = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="planning-afterok",
        created_at="2026-05-08T00:00:00Z",
    )

    jobs = cast(tuple[SlurmPlannedJob, ...], result.submission.jobs)
    dependencies = cast(
        tuple[SlurmPlannedDependency, ...],
        result.submission.dependencies,
    )
    assert [job.logical_key for job in jobs] == [
        "stage:extract",
        "stage:features",
        "stage:train",
        "stage:report",
    ]
    assert {
        dependency.job_key: tuple(dependency.upstream_job_keys)
        for dependency in dependencies
    } == {
        "stage:features": ("stage:extract",),
        "stage:train": ("stage:extract",),
        "stage:report": ("stage:features", "stage:train"),
    }
    report_script = result.script_artifacts["stage:report"].local_path.read_text()
    assert "#SBATCH --dependency=afterok:stage:features:stage:train" in report_script
    assert f"loom stage-job run --run-uri {run_uri} --stage report --executor local" in report_script
    assert "loom stage run" not in report_script
    assert SlurmPlannedSubmission.from_dict(
        _read_json(result.manifest_artifact.local_path)
    ) == result.submission


def test_default_planning_ids_are_distinct_for_repeated_dry_runs(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"build": ()})

    first = plan_single_job_slurm_dry_run(run_store=store, run_uri=run_uri)
    second = plan_single_job_slurm_dry_run(run_store=store, run_uri=run_uri)

    assert first.submission.planning_id != second.submission.planning_id
    assert first.manifest_artifact.local_path != second.manifest_artifact.local_path
    assert first.manifest_artifact.local_path.exists()
    assert second.manifest_artifact.local_path.exists()


def _prepared_store(
    tmp_path: Path,
    stage_upstreams: dict[str, tuple[str, ...]],
    *,
    authority_backed: bool = False,
) -> tuple[Any, str]:
    root = tmp_path / "runs"
    if authority_backed:
        store = create_authority_backed_serial_run_store(
            root,
            authority_store=SQLitePerRunAuthorityStore(),
            authority_config=AuthorityConfig(
                backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
                deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
                endpoint="http://authority.test",
                workspace_id="workspace-a",
                reference_id="slurm-live-test",
            ),
        )
    else:
        store = LocalRunStore(root=root)
    run_uri = path_to_run_uri(root / "run-1")
    store.create_run(run_uri, metadata={"token": "SECRET_SHOULD_NOT_BE_COPIED"})
    plan = _execution_plan(run_uri, stage_upstreams)
    store.write_plan(run_uri, plan.to_dict())
    store.write_prepared_run(
        run_uri,
        PreparedRunRecord(
            schema_version=PREPARED_RUN_SCHEMA_VERSION,
            run_uri=run_uri,
            prepared_at="2026-05-08T00:00:00Z",
            executor_name="slurm-single-job",
            continuation_type=PREPARED_RUN_CONTINUATION_WHOLE_RUN,
            plan={"plan_summary": {"stage_count": len(stage_upstreams)}},
            config={"composition_manifest_ref": "config/composition_manifest.json"},
            runtime={"executor": "slurm-single-job", "stage_count": len(stage_upstreams)},
        ).to_dict(),
    )
    return store, run_uri


def _execution_plan(
    run_uri: str,
    stage_upstreams: dict[str, tuple[str, ...]],
) -> ExecutionPlan:
    stage_plans = tuple(
        StagePlan(
            stage_name=stage_name,
            action=PlanAction.RUN,
            base_action=PlanAction.RUN,
            fingerprint_status=FingerprintStatus.PENDING_INPUTS,
            fingerprint=None,
            resume_check=None,
            reasons=(),
            bound_inputs={},
            pending_inputs=(),
            reusable_outputs={},
            declared_outputs={},
            upstream_stages=upstream,
            downstream_stages=(),
            selected_by=(),
            invalidated_by=(),
        )
        for stage_name, upstream in stage_upstreams.items()
    )
    return ExecutionPlan(
        schema_version=1,
        run_uri=run_uri,
        pipeline_name="demo",
        selectors=PlanSelectors(),
        resume=ResumeOptions(),
        fingerprint_context=FingerprintContext(
            python_version="3.12.0",
            loom_version="0.1.0",
        ),
        stage_order=tuple(stage_upstreams),
        stage_plans=stage_plans,
        reasons=(),
        summary={"RUN": len(stage_plans), "REUSE": 0, "SKIP": 0, "STALE": 0, "BLOCKED": 0},
    )


def _read_json(path: Path) -> object:
    return json.loads(path.read_text())
