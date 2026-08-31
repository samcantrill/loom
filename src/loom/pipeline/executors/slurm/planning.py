"""Python APIs for SLURM dry-run script planning."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import cast

from loom.pipeline.execution import PreparedRunRecord
from loom.pipeline.executors.apptainer import ApptainerExecOptions
from loom.pipeline.executors.containers import ContainerBuildResult, ContainerOptions
from loom.pipeline.planning import ExecutionPlan, PlanAction
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.stores import AuthorityConfig
from loom.pipeline.stores.run_store import (
    LegacyRunStore as RunStore,
    LocalRunStorePaths,
)
from loom.serialization import PlainData
from loom.timestamps import safe_timestamp_for_path, utc_timestamp

from .artifacts import SlurmDryRunPlanningResult, write_slurm_dry_run_artifacts
from .container import (
    container_build_results_metadata,
    prepare_slurm_container_options,
    wrap_slurm_command_with_apptainer,
)
from .errors import SlurmPlanningError
from .manifest import (
    SlurmDependencyType,
    SlurmMode,
    SlurmPlannedDependency,
    SlurmPlannedJob,
    SlurmPlannedSubmission,
    pipeline_job_key,
    stage_job_key,
)
from .options import (
    SlurmCommandArgv,
    SlurmOptions,
    build_single_job_command_argv,
    build_stage_job_command_argv,
)
from .paths import (
    slurm_job_log_relative_path,
    slurm_job_script_relative_path,
    slurm_manifest_relative_path,
    slurm_plan_relative_path,
)
from .rendering import render_dependency_value, render_slurm_script
from .resources import SlurmSbatchDirective, build_sbatch_directives

type SlurmResourceInput = ResourceRequest | Mapping[str, ResourceEntry]
type SlurmStageResourceInputs = Mapping[str, SlurmResourceInput]
type SlurmStageOptionInputs = Mapping[str, SlurmOptions]
type SlurmContainerInput = ContainerOptions | Mapping[str, object]
type SlurmStageContainerInputs = Mapping[str, SlurmContainerInput]
type SlurmApptainerOptionInput = ApptainerExecOptions | Mapping[str, object]
type SlurmStageApptainerOptionInputs = Mapping[str, SlurmApptainerOptionInput]

SLURM_DRY_RUN_PLAN_METADATA_SCHEMA_VERSION = 1


def plan_single_job_slurm_dry_run(
    *,
    run_store: RunStore,
    run_uri: str,
    options: SlurmOptions | None = None,
    resources: SlurmResourceInput | None = None,
    container_options: SlurmContainerInput | None = None,
    apptainer_options: SlurmApptainerOptionInput | None = None,
    container_build_results: Sequence[ContainerBuildResult] = (),
    planning_id: str | None = None,
    created_at: str | None = None,
) -> SlurmDryRunPlanningResult:
    """Read persisted state and write single-job SLURM dry-run artifacts."""

    plan, prepared_run = _read_persisted_state(run_store=run_store, run_uri=run_uri)
    _validate_local_store_paths(run_store)
    prepared_container = _prepare_container_options(
        container_options,
        run_store=run_store,
        run_uri=run_uri,
    )
    planned_submission = build_single_job_planned_submission(
        run_uri=run_uri,
        planning_id=_planning_id(planning_id, mode=SlurmMode.SINGLE_JOB),
        created_at=created_at or utc_timestamp(),
        options=options or SlurmOptions(),
        resources=resources,
        authority_config=_authority_config_from_run_store(run_store),
        container_options=prepared_container,
        apptainer_options=apptainer_options,
    )
    jobs = cast(tuple[SlurmPlannedJob, ...], planned_submission.jobs)
    scripts = {
        job.logical_key: render_slurm_script(
            job,
            options=cast(SlurmOptions, planned_submission.options),
        )
        for job in jobs
    }
    metadata = build_slurm_plan_metadata(
        submission=planned_submission,
        plan=plan,
        prepared_run=prepared_run,
        container_build_results=container_build_results,
    )
    return write_slurm_dry_run_artifacts(
        store_paths=cast(LocalRunStorePaths, run_store),
        run_uri=run_uri,
        submission=planned_submission,
        scripts=scripts,
        plan_metadata=metadata,
    )


def plan_afterok_slurm_dry_run(
    *,
    run_store: RunStore,
    run_uri: str,
    options: SlurmOptions | None = None,
    stage_options: SlurmStageOptionInputs | None = None,
    stage_resources: SlurmStageResourceInputs | None = None,
    container_options: SlurmContainerInput | None = None,
    stage_container_options: SlurmStageContainerInputs | None = None,
    apptainer_options: SlurmApptainerOptionInput | None = None,
    stage_apptainer_options: SlurmStageApptainerOptionInputs | None = None,
    container_build_results: Sequence[ContainerBuildResult] = (),
    planning_id: str | None = None,
    created_at: str | None = None,
    plugin_selectors: Sequence[str] = (),
) -> SlurmDryRunPlanningResult:
    """Read persisted state and write afterok SLURM dry-run artifacts."""

    plan, prepared_run = _read_persisted_state(run_store=run_store, run_uri=run_uri)
    _validate_local_store_paths(run_store)
    prepared_container = _prepare_container_options(
        container_options,
        run_store=run_store,
        run_uri=run_uri,
    )
    prepared_stage_containers = _prepare_stage_container_options(
        stage_container_options,
        run_store=run_store,
        run_uri=run_uri,
    )
    planned_submission = build_afterok_planned_submission(
        run_uri=run_uri,
        execution_plan=plan,
        planning_id=_planning_id(planning_id, mode=SlurmMode.AFTEROK),
        created_at=created_at or utc_timestamp(),
        options=options or SlurmOptions(),
        stage_options=stage_options,
        stage_resources=stage_resources,
        authority_config=_authority_config_from_run_store(run_store),
        container_options=prepared_container,
        stage_container_options=prepared_stage_containers,
        apptainer_options=apptainer_options,
        stage_apptainer_options=stage_apptainer_options,
        plugin_selectors=plugin_selectors,
    )
    jobs = cast(tuple[SlurmPlannedJob, ...], planned_submission.jobs)
    scripts = {
        job.logical_key: render_slurm_script(
            job,
            options=_job_options(
                job.logical_key,
                run_options=cast(SlurmOptions, planned_submission.options),
                stage_options=stage_options,
            ),
        )
        for job in jobs
    }
    metadata = build_slurm_plan_metadata(
        submission=planned_submission,
        plan=plan,
        prepared_run=prepared_run,
        container_build_results=container_build_results,
    )
    return write_slurm_dry_run_artifacts(
        store_paths=cast(LocalRunStorePaths, run_store),
        run_uri=run_uri,
        submission=planned_submission,
        scripts=scripts,
        plan_metadata=metadata,
    )


def build_single_job_planned_submission(
    *,
    run_uri: str,
    planning_id: str,
    created_at: str,
    options: SlurmOptions,
    resources: SlurmResourceInput | None = None,
    authority_config: AuthorityConfig | None = None,
    container_options: SlurmContainerInput | None = None,
    apptainer_options: SlurmApptainerOptionInput | None = None,
) -> SlurmPlannedSubmission:
    """Build a deterministic single-job dry-run manifest in memory."""

    logical_key = pipeline_job_key()
    command = build_single_job_command_argv(
        run_uri,
        launcher_argv=options.launcher_argv,
        authority_config=authority_config,
    )
    command = _maybe_wrap_command(
        command,
        container_options=container_options,
        apptainer_options=apptainer_options,
        resources=None,
    )
    manifest_relative_path = slurm_manifest_relative_path(planning_id)
    job = _build_job(
        run_uri=run_uri,
        planning_id=planning_id,
        mode=SlurmMode.SINGLE_JOB,
        logical_key=logical_key,
        command=command,
        options=options,
        resources=resources,
        dependency_job_keys=(),
        manifest_relative_path=manifest_relative_path,
    )
    return SlurmPlannedSubmission(
        run_uri=run_uri,
        mode=SlurmMode.SINGLE_JOB,
        planning_id=planning_id,
        created_at=created_at,
        plan_relative_path=slurm_plan_relative_path(planning_id),
        manifest_relative_path=manifest_relative_path,
        options=options,
        jobs=(job,),
        dependencies=(),
        generated_command_argv=(command,),
        resources={logical_key: _resources_to_manifest_data(resources)},
    )


def build_afterok_planned_submission(
    *,
    run_uri: str,
    execution_plan: ExecutionPlan,
    planning_id: str,
    created_at: str,
    options: SlurmOptions,
    stage_options: SlurmStageOptionInputs | None = None,
    stage_resources: SlurmStageResourceInputs | None = None,
    authority_config: AuthorityConfig | None = None,
    container_options: SlurmContainerInput | None = None,
    stage_container_options: SlurmStageContainerInputs | None = None,
    apptainer_options: SlurmApptainerOptionInput | None = None,
    stage_apptainer_options: SlurmStageApptainerOptionInputs | None = None,
    plugin_selectors: Sequence[str] = (),
) -> SlurmPlannedSubmission:
    """Build a deterministic afterok dry-run manifest in memory."""

    run_stage_plans = tuple(
        stage_plan
        for stage_plan in execution_plan.ordered_stage_plans
        if stage_plan.action == PlanAction.RUN
    )
    if not run_stage_plans:
        raise SlurmPlanningError("afterok planning requires at least one RUN stage")

    manifest_relative_path = slurm_manifest_relative_path(planning_id)
    run_stage_names = {stage_plan.stage_name for stage_plan in run_stage_plans}
    jobs: list[SlurmPlannedJob] = []
    dependencies: list[SlurmPlannedDependency] = []
    commands: list[SlurmCommandArgv] = []
    resource_data: dict[str, PlainData] = {}

    for stage_plan in run_stage_plans:
        logical_key = stage_job_key(stage_plan.stage_name)
        job_options = _stage_options(
            stage_plan.stage_name,
            stage_options,
            fallback=options,
        )
        upstream_job_keys = tuple(
            stage_job_key(stage_name)
            for stage_name in stage_plan.upstream_stages
            if stage_name in run_stage_names
        )
        resources = _stage_resources(stage_plan.stage_name, stage_resources)
        command = build_stage_job_command_argv(
            run_uri,
            stage_plan.stage_name,
            launcher_argv=job_options.launcher_argv,
            authority_config=authority_config,
            plugin_selectors=plugin_selectors,
        )
        command = _maybe_wrap_command(
            command,
            container_options=_stage_container_options(
                stage_plan.stage_name,
                stage_container_options,
                fallback=container_options,
            ),
            apptainer_options=_stage_apptainer_options(
                stage_plan.stage_name,
                stage_apptainer_options,
                fallback=apptainer_options,
            ),
            resources=resources,
        )
        jobs.append(
            _build_job(
                run_uri=run_uri,
                planning_id=planning_id,
                mode=SlurmMode.AFTEROK,
                logical_key=logical_key,
                command=command,
                options=job_options,
                resources=resources,
                dependency_job_keys=upstream_job_keys,
                manifest_relative_path=manifest_relative_path,
            )
        )
        if upstream_job_keys:
            dependencies.append(
                SlurmPlannedDependency(
                    job_key=logical_key,
                    upstream_job_keys=upstream_job_keys,
                )
            )
        commands.append(command)
        resource_data[logical_key] = _resources_to_manifest_data(resources)

    return SlurmPlannedSubmission(
        run_uri=run_uri,
        mode=SlurmMode.AFTEROK,
        planning_id=planning_id,
        created_at=created_at,
        plan_relative_path=slurm_plan_relative_path(planning_id),
        manifest_relative_path=manifest_relative_path,
        options=options,
        jobs=tuple(jobs),
        dependencies=tuple(dependencies),
        generated_command_argv=tuple(commands),
        resources=resource_data,
    )


def build_slurm_plan_metadata(
    *,
    submission: SlurmPlannedSubmission,
    plan: ExecutionPlan,
    prepared_run: PreparedRunRecord,
    container_build_results: Sequence[ContainerBuildResult] = (),
) -> dict[str, PlainData]:
    """Build secret-safe dry-run planning metadata from public state."""

    metadata: dict[str, PlainData] = {
        "schema_version": SLURM_DRY_RUN_PLAN_METADATA_SCHEMA_VERSION,
        "kind": "loom.slurm_dry_run_plan",
        "run_uri": submission.run_uri,
        "mode": cast(SlurmMode, submission.mode).value,
        "dry_run": True,
        "planning_id": submission.planning_id,
        "created_at": submission.created_at,
        "source_plan": {
            "run_uri": plan.run_uri,
            "pipeline_name": plan.pipeline_name,
            "stage_order": list(plan.stage_order),
            "stage_actions": {
                stage_plan.stage_name: stage_plan.action.value
                for stage_plan in plan.ordered_stage_plans
            },
            "summary": dict(plan.summary),
        },
        "prepared_run": {
            "run_uri": prepared_run.run_uri,
            "prepared_at": prepared_run.prepared_at,
            "executor_name": prepared_run.executor_name,
            "continuation_type": prepared_run.continuation_type,
        },
        "jobs": [
            {
                "logical_key": job.logical_key,
                "script_relative_path": job.script_relative_path,
                "stdout_relative_path": job.stdout_relative_path,
                "stderr_relative_path": job.stderr_relative_path,
                "dependency_job_keys": list(job.dependency_job_keys),
            }
            for job in cast(tuple[SlurmPlannedJob, ...], submission.jobs)
        ],
        "dependencies": [
            dependency.to_dict()
            for dependency in cast(
                tuple[SlurmPlannedDependency, ...],
                submission.dependencies,
            )
        ],
        "manifest_relative_path": submission.manifest_relative_path,
    }
    if container_build_results:
        metadata["container_build_results"] = [
            dict(item)
            for item in container_build_results_metadata(container_build_results)
        ]
    return metadata


def _build_job(
    *,
    run_uri: str,
    planning_id: str,
    mode: SlurmMode,
    logical_key: str,
    command: SlurmCommandArgv,
    options: SlurmOptions,
    resources: SlurmResourceInput | None,
    dependency_job_keys: tuple[str, ...],
    manifest_relative_path: str,
) -> SlurmPlannedJob:
    script_relative_path = slurm_job_script_relative_path(planning_id, logical_key)
    stdout_relative_path = slurm_job_log_relative_path(
        planning_id,
        logical_key,
        "stdout",
    )
    stderr_relative_path = slurm_job_log_relative_path(
        planning_id,
        logical_key,
        "stderr",
    )
    return SlurmPlannedJob(
        logical_key=logical_key,
        mode=mode,
        command=command,
        dependency_job_keys=dependency_job_keys,
        resources=_resources_to_manifest_data(resources),
        sbatch_directives=_job_sbatch_directives(
            planning_id=planning_id,
            logical_key=logical_key,
            stdout_relative_path=stdout_relative_path,
            stderr_relative_path=stderr_relative_path,
            dependency_job_keys=dependency_job_keys,
            options=options,
            resources=resources,
        ),
        script_relative_path=script_relative_path,
        stdout_relative_path=stdout_relative_path,
        stderr_relative_path=stderr_relative_path,
        manifest_relative_path=manifest_relative_path,
    )


def _job_sbatch_directives(
    *,
    planning_id: str,
    logical_key: str,
    stdout_relative_path: str,
    stderr_relative_path: str,
    dependency_job_keys: tuple[str, ...],
    options: SlurmOptions,
    resources: SlurmResourceInput | None,
) -> tuple[SlurmSbatchDirective, ...]:
    generated = [
        SlurmSbatchDirective(
            name="job-name",
            value=_job_name(planning_id, logical_key),
            source="generated",
        ),
        SlurmSbatchDirective(
            name="output",
            value=stdout_relative_path,
            source="generated",
        ),
        SlurmSbatchDirective(
            name="error",
            value=stderr_relative_path,
            source="generated",
        ),
    ]
    if dependency_job_keys:
        generated.append(
            SlurmSbatchDirective(
                name="dependency",
                value=render_dependency_value(
                    dependency_job_keys,
                    dependency_type=SlurmDependencyType.AFTEROK,
                ),
                source="generated",
            )
        )
    return (
        *generated,
        *build_sbatch_directives(options=options, resources=resources),
    )


def _job_name(planning_id: str, logical_key: str) -> str:
    if logical_key == pipeline_job_key():
        stem = "pipeline"
    else:
        stem = "stage-" + logical_key.removeprefix("stage:")
    return f"loom-{planning_id}-{stem}"


def _resources_to_manifest_data(
    resources: SlurmResourceInput | None,
) -> dict[str, PlainData]:
    if resources is None:
        return {}
    entries = resources.entries if isinstance(resources, ResourceRequest) else resources
    return {kind: entry.to_dict() for kind, entry in sorted(entries.items())}


def _stage_resources(
    stage_name: str,
    stage_resources: SlurmStageResourceInputs | None,
) -> SlurmResourceInput | None:
    if stage_resources is None:
        return None
    logical_key = stage_job_key(stage_name)
    return stage_resources.get(stage_name) or stage_resources.get(logical_key)


def _prepare_container_options(
    container_options: SlurmContainerInput | None,
    *,
    run_store: RunStore,
    run_uri: str,
) -> ContainerOptions | None:
    if container_options is None:
        return None
    return prepare_slurm_container_options(
        container_options,
        run_store=run_store,
        run_uri=run_uri,
    )


def _prepare_stage_container_options(
    stage_container_options: SlurmStageContainerInputs | None,
    *,
    run_store: RunStore,
    run_uri: str,
) -> Mapping[str, ContainerOptions]:
    if stage_container_options is None:
        return {}
    return {
        stage_name: prepare_slurm_container_options(
            container,
            run_store=run_store,
            run_uri=run_uri,
        )
        for stage_name, container in stage_container_options.items()
    }


def _stage_container_options(
    stage_name: str,
    stage_container_options: SlurmStageContainerInputs
    | Mapping[str, ContainerOptions]
    | None,
    *,
    fallback: SlurmContainerInput | None,
) -> SlurmContainerInput | None:
    if stage_container_options is None:
        return fallback
    logical_key = stage_job_key(stage_name)
    return (
        stage_container_options.get(stage_name)
        or stage_container_options.get(logical_key)
        or fallback
    )


def _stage_apptainer_options(
    stage_name: str,
    stage_apptainer_options: SlurmStageApptainerOptionInputs | None,
    *,
    fallback: SlurmApptainerOptionInput | None,
) -> SlurmApptainerOptionInput | None:
    if stage_apptainer_options is None:
        return fallback
    logical_key = stage_job_key(stage_name)
    return (
        stage_apptainer_options.get(stage_name)
        or stage_apptainer_options.get(logical_key)
        or fallback
    )


def _maybe_wrap_command(
    command: SlurmCommandArgv,
    *,
    container_options: SlurmContainerInput | None,
    apptainer_options: SlurmApptainerOptionInput | None,
    resources: SlurmResourceInput | None,
) -> SlurmCommandArgv:
    if container_options is None:
        return command
    return wrap_slurm_command_with_apptainer(
        command,
        container_options=container_options,
        apptainer_options=apptainer_options,
        resources=resources,
    )


def _stage_options(
    stage_name: str,
    stage_options: SlurmStageOptionInputs | None,
    *,
    fallback: SlurmOptions,
) -> SlurmOptions:
    if stage_options is None:
        return fallback
    logical_key = stage_job_key(stage_name)
    return stage_options.get(stage_name) or stage_options.get(logical_key) or fallback


def _job_options(
    logical_key: str,
    *,
    run_options: SlurmOptions,
    stage_options: SlurmStageOptionInputs | None,
) -> SlurmOptions:
    if not logical_key.startswith("stage:"):
        return run_options
    stage_name = logical_key.removeprefix("stage:")
    return _stage_options(stage_name, stage_options, fallback=run_options)


def _read_persisted_state(
    *,
    run_store: RunStore,
    run_uri: str,
) -> tuple[ExecutionPlan, PreparedRunRecord]:
    plan_payload = run_store.read_plan(run_uri)
    if plan_payload is None:
        raise SlurmPlanningError(f"run has no persisted execution plan: {run_uri}")
    prepared_payload = run_store.read_prepared_run(run_uri)
    if prepared_payload is None:
        raise SlurmPlanningError(f"run has no prepared-run metadata: {run_uri}")

    plan = ExecutionPlan.from_dict(plan_payload)
    prepared_run = PreparedRunRecord.from_dict(prepared_payload)
    if plan.run_uri != run_uri:
        raise SlurmPlanningError("persisted execution plan run_uri does not match")
    if prepared_run.run_uri != run_uri:
        raise SlurmPlanningError("prepared-run metadata run_uri does not match")
    return plan, prepared_run


def _validate_local_store_paths(run_store: RunStore) -> None:
    if not isinstance(run_store, LocalRunStorePaths):
        raise SlurmPlanningError(
            "SLURM dry-run artifact writing requires local store path support"
        )


def _authority_config_from_run_store(run_store: RunStore) -> AuthorityConfig | None:
    raw_config = getattr(run_store, "authority_config", None)
    if isinstance(raw_config, AuthorityConfig):
        return raw_config
    if callable(raw_config):
        value = raw_config()
        if isinstance(value, AuthorityConfig):
            return value
    return None


def _planning_id(value: str | None, *, mode: SlurmMode) -> str:
    if value is not None:
        return value
    return (
        f"{mode.value}-"
        f"{safe_timestamp_for_path(timespec='microseconds')}-"
        f"{uuid.uuid4().hex[:8]}"
    )


__all__ = [
    "SLURM_DRY_RUN_PLAN_METADATA_SCHEMA_VERSION",
    "SlurmDryRunPlanningResult",
    "build_afterok_planned_submission",
    "build_single_job_planned_submission",
    "build_slurm_plan_metadata",
    "plan_afterok_slurm_dry_run",
    "plan_single_job_slurm_dry_run",
]
