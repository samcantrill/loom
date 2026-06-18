"""Shared test fixtures for submitted SLURM status inspection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from loom.pipeline.executors.slurm import (
    SlurmCommandResult,
    SlurmLiveSubmissionStatus,
    SlurmOptions,
    SlurmPlannedJob,
    SlurmSubmittedJob,
    build_afterok_planned_submission,
    live_manifest_from_planned_submission,
    write_slurm_live_manifest,
)
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.planning import (
    ExecutionPlan,
    FingerprintContext,
    FingerprintStatus,
    PlanAction,
    PlanSelectors,
    ResumeOptions,
    StagePlan,
)
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState


def write_submitted_slurm_fixture(
    tmp_path: Path,
    stage_upstreams: Mapping[str, tuple[str, ...]],
    *,
    starting_job_id: int = 700,
    run_status: RunStatus = RunStatus.SUBMITTED,
    stage_status: StageStatus = StageStatus.SUBMITTED,
    authority_config: AuthorityConfig | None = None,
    authority_store: SQLitePerRunAuthorityStore | None = None,
) -> tuple[Any, str, Path]:
    """Persist a submitted afterok manifest and registry for status tests."""

    if authority_config is None:
        authority_config = _slurm_live_authority_config()
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_store=authority_store or SQLitePerRunAuthorityStore(),
            authority_config=authority_config,
        )
    else:
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=authority_config,
        )
    run_uri = path_to_run_uri(tmp_path / "runs" / "submitted-slurm")
    store.create_run(run_uri)
    submission = build_afterok_planned_submission(
        run_uri=run_uri,
        execution_plan=_execution_plan(run_uri, stage_upstreams),
        planning_id="planning-status",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(),
    )
    scheduler_ids: dict[str, str] = {}
    submitted_jobs: list[SlurmSubmittedJob] = []
    for index, job in enumerate(cast(tuple[SlurmPlannedJob, ...], submission.jobs)):
        scheduler_job_id = str(starting_job_id + index)
        scheduler_ids[job.logical_key] = scheduler_job_id
        dependency_job_ids = tuple(
            scheduler_ids[key] for key in job.dependency_job_keys if key in scheduler_ids
        )
        submitted_jobs.append(
            SlurmSubmittedJob(
                logical_key=job.logical_key,
                scheduler_job_id=scheduler_job_id,
                raw_job_id_output=f"{scheduler_job_id}\n",
                submitted_at="2026-05-08T00:00:03Z",
                dependency_job_ids=dependency_job_ids,
                command_record=SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", job.script_relative_path or "job.sh"),
                    returncode=0,
                    stdout=f"{scheduler_job_id}\n",
                ),
                script_relative_path=job.script_relative_path,
                stdout_relative_path=job.stdout_relative_path,
                stderr_relative_path=job.stderr_relative_path,
            )
        )

    manifest = replace(
        live_manifest_from_planned_submission(
            submission,
            status=SlurmLiveSubmissionStatus.SUBMITTED,
            updated_at="2026-05-08T00:00:03Z",
        ),
        submitted_jobs=tuple(submitted_jobs),
    )
    manifest_path = store.local_generated_artifact_path(
        run_uri, "slurm/submissions/planning-status/manifest.json"
    )
    write_slurm_live_manifest(manifest_path, manifest)
    store.write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id="planning-status",
            backend="slurm",
            mode="slurm-afterok",
            created_at="2026-05-08T00:00:00Z",
            updated_at="2026-05-08T00:00:03Z",
            state=SubmittedOperationState.SUBMITTED,
            manifest_relative_path="slurm/submissions/planning-status/manifest.json",
            summary_counts={"submitted": len(submitted_jobs), "active": len(submitted_jobs)},
        ),
    )
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=run_status,
            created_at="2026-05-08T00:00:00Z",
            updated_at="2026-05-08T00:00:03Z",
        ),
    )
    for stage_name in stage_upstreams:
        store.write_stage_status(
            run_uri,
            stage_name,
            StageStatusRecord(
                run_uri=run_uri,
                stage_name=stage_name,
                status=stage_status,
                attempt=1,
                updated_at="2026-05-08T00:00:03Z",
            ),
        )
    return store, run_uri, manifest_path


def _slurm_live_authority_config() -> AuthorityConfig:
    return AuthorityConfig(
        backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
        deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
        endpoint="http://authority.test",
        workspace_id="workspace-a",
        reference_id="slurm-live-test",
    )


def _execution_plan(
    run_uri: str,
    stage_upstreams: Mapping[str, tuple[str, ...]],
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
        pipeline_name="status-fixture",
        selectors=PlanSelectors(),
        resume=ResumeOptions(),
        fingerprint_context=FingerprintContext(
            python_version="3.12.0",
            loom_version="0.1.0",
        ),
        stage_order=tuple(stage_upstreams),
        stage_plans=stage_plans,
        reasons=(),
        summary={
            "RUN": len(stage_plans),
            "REUSE": 0,
            "SKIP": 0,
            "STALE": 0,
            "BLOCKED": 0,
        },
    )
