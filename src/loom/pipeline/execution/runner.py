"""Local serial pipeline runner."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext
from loom.pipeline.errors import StageContractError
from loom.pipeline.executors.base import Executor
from loom.pipeline.planning import (
    ExecutionPlan,
    PlanAction,
    PlanReason,
    StageFingerprintRecord,
    build_stage_fingerprint,
    plan_pipeline,
)
from loom.pipeline.runtime import (
    ResolvedStageRuntimeOptions,
    RunOptions,
    build_runtime_metadata,
    parse_run_options,
    resolve_run_runtime,
)
from loom.pipeline.specs import PipelineSpec, StageSpec, parse_pipeline_config
from loom.pipeline.stage_factory import construct_stage
from loom.pipeline.stage import Stage
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStorePaths, RunStore
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.errors import ArtifactStoreError, StoreError
from loom.serialization import PlainData, ensure_plain_data, json_dumps_pretty
from loom.timestamps import utc_timestamp

from .errors import (
    OutputValidationError,
    PipelineExecutionError,
    PlanExecutionError,
    RunRequestError,
)
from .eventing import emit_run_event, emit_stage_event
from .lifecycle import (
    bind_stage_inputs,
    commit_stage_execution_result,
    next_stage_attempt,
    persist_stage_failure,
    record_stage_failure_and_failed_run,
    write_stage_artifact_index_refs,
    write_failed_run,
    write_run_status,
    write_stage_blocked,
    write_stage_running,
    write_stage_skipped,
)
from .logs import traceback_log_path
from .models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    ExecutionFailure,
    RunRequest,
    RunResult,
    StageExecutionRequest,
    StageExecutionResult,
    StageRunResult,
)
from .run_locks import acquire_run_lock, build_lock_owner, release_run_lock
from .stage_attempts import prepare_stage_attempt

ArtifactStoreFactory = Callable[[Path], ArtifactStore]


class _TargetConstructionError(StageContractError):
    """Private marker for import or no-argument construction failures."""


class _PreparedWorkerStage:
    """Placeholder stage object for executors that launch the real worker."""

    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        raise PipelineExecutionError("prepared worker placeholder must not run")


class PipelineRunner:
    def __init__(
        self,
        *,
        run_store: RunStore,
        executor: Executor | None = None,
        artifact_store_factory: ArtifactStoreFactory | None = None,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None:
        if not isinstance(run_store, RunStore):
            raise PipelineExecutionError("run_store must satisfy RunStore")
        if executor is None:
            from loom.pipeline.executors import LocalExecutor

            executor = LocalExecutor()
        if not isinstance(executor, Executor):
            raise PipelineExecutionError("executor must satisfy Executor")
        self.run_store = run_store
        self.executor = executor
        self.artifact_store_factory = artifact_store_factory or (
            lambda root: LocalArtifactStore(root)
        )
        self.clock = clock

    def run(self, request: RunRequest) -> RunResult:
        if not isinstance(request, RunRequest):
            raise RunRequestError("PipelineRunner.run requires RunRequest")
        options = parse_run_options(request.options)
        if options.dry_run:
            raise RunRequestError(
                "PipelineRunner.run does not execute dry-run requests; use planning APIs instead"
            )

        started_at = self.clock()
        local_run_store = self._require_local_run_store()
        run_uri = self._resolve_request_run_uri(request, local_run_store)
        self._create_or_open_run(run_uri, request)
        run_dir = local_run_store.local_run_dir(run_uri)
        lock = acquire_run_lock(
            self.run_store,
            run_uri,
            owner=build_lock_owner(
                component="PipelineRunner",
                run_uri=run_uri,
                executor=str(getattr(self.executor, "name", "unknown")),
            ),
        )
        try:
            self._emit_run_event(
                run_uri,
                "run.opened" if request.open_existing else "run.created",
                timestamp=self.clock(),
                payload={"open_existing": request.open_existing},
            )
            return self._run_locked(
                request=request,
                run_uri=run_uri,
                run_dir=run_dir,
                local_run_store=local_run_store,
                started_at=started_at,
            )
        finally:
            release_run_lock(self.run_store, lock)

    def _run_locked(
        self,
        *,
        request: RunRequest,
        run_uri: str,
        run_dir: Path,
        local_run_store: LocalRunStorePaths,
        started_at: str,
    ) -> RunResult:
        created_at = self._created_at(run_uri, started_at)
        write_run_status(
            self.run_store,
            run_uri=run_uri,
            status=RunStatus.CREATED,
            created_at=created_at,
            updated_at=started_at,
            started_at=started_at,
            metadata=request.metadata,
        )
        config_mapping, spec = self._resolve_config_and_spec(request)
        options = _options_with_resolved_run_uri(
            parse_run_options(request.options),
            run_uri,
        )
        resolved_runtime = resolve_run_runtime(
            options,
            stage_ids=spec.stage_names,
        )
        self.run_store.write_runtime_metadata(
            run_uri,
            build_runtime_metadata(
                options,
                stage_ids=spec.stage_names,
            ).to_dict(),
        )
        self._write_config_and_provenance(run_uri, request, config_mapping)
        artifact_store = self.artifact_store_factory(
            local_run_store.local_artifact_root(run_uri)
        )

        plan = plan_pipeline(
            spec,
            run_uri=run_uri,
            run_store=self.run_store,
            artifact_store=artifact_store,
            selectors=request.selectors,
            resume=request.resume,
            fingerprint_context=request.fingerprint_context,
            persist=True,
        )
        write_run_status(
            self.run_store,
            run_uri=run_uri,
            status=RunStatus.PLANNED,
            created_at=created_at,
            updated_at=self.clock(),
            started_at=started_at,
            metadata={"plan_summary": dict(plan.summary)},
        )
        self._emit_run_event(
            run_uri,
            "run.planned",
            timestamp=self.clock(),
            payload={"summary": dict(plan.summary)},
        )
        for stage_plan in plan.ordered_stage_plans:
            self._emit_stage_event(
                run_uri,
                stage_plan.stage_name,
                "stage.planned",
                timestamp=self.clock(),
                payload={
                    "action": stage_plan.action.value,
                    "reason_codes": _reason_codes(stage_plan.reasons),
                },
            )
        write_run_status(
            self.run_store,
            run_uri=run_uri,
            status=RunStatus.RUNNING,
            created_at=created_at,
            updated_at=self.clock(),
            started_at=started_at,
        )
        self._emit_run_event(
            run_uri,
            "run.started",
            timestamp=self.clock(),
            payload={"stage_count": len(plan.ordered_stage_plans)},
        )

        stage_results: dict[str, StageRunResult] = {}
        outputs_by_stage: dict[str, dict[str, ArtifactRef]] = {}
        failed_stage: str | None = None
        failure: ExecutionFailure | None = None
        for stage_plan in plan.ordered_stage_plans:
            stage = spec.get_stage(stage_plan.stage_name)
            if failed_stage is not None:
                stage_results[stage.name] = self._block_stage_after_failure(
                    run_uri=run_uri,
                    stage_plan=stage_plan,
                    blocked_by=failed_stage,
                )
                continue
            if stage_plan.action == PlanAction.REUSE:
                result = self._reuse_stage(
                    run_uri, stage_plan, created_at=created_at, started_at=started_at
                )
                stage_results[stage.name] = result
                if result.failure is not None:
                    failed_stage = stage.name
                    failure = result.failure
                else:
                    outputs_by_stage[stage.name] = dict(result.outputs)
                continue
            if stage_plan.action == PlanAction.SKIP:
                result = self._skip_stage(
                    run_uri,
                    stage_plan,
                    created_at=created_at,
                    started_at=started_at,
                )
                stage_results[stage.name] = result
                if result.failure is not None:
                    failed_stage = stage.name
                    failure = result.failure
                continue
            if stage_plan.action == PlanAction.BLOCKED:
                failed_stage = stage.name
                failure = self._plan_failure(
                    run_uri, stage, stage_plan.action, stage_plan.reasons
                )
                stage_results[stage.name] = self._block_plan_stage(
                    run_uri=run_uri,
                    stage_plan=stage_plan,
                    failure=failure,
                )
                self._write_failed_run(run_uri, created_at, started_at, failure)
                continue
            if stage_plan.action == PlanAction.STALE:
                failed_stage = stage.name
                failure = self._plan_failure(
                    run_uri, stage, stage_plan.action, stage_plan.reasons
                )
                attempt = next_stage_attempt(self.run_store, run_uri, stage.name)
                failure = self._record_stage_failure_and_failed_run(
                    run_uri=run_uri,
                    stage_name=stage.name,
                    attempt=attempt,
                    started_at=None,
                    created_at=created_at,
                    run_started_at=started_at,
                    failure=failure,
                )
                stage_results[stage.name] = StageRunResult(
                    stage_name=stage.name,
                    action=PlanAction.BLOCKED,
                    status=StageStatus.FAILED,
                    attempt=attempt,
                    outputs={},
                    failure=failure,
                    reasons=stage_plan.reasons,
                    finished_at=failure.failed_at,
                )
                continue
            result = self._run_stage(
                request=request,
                run_uri=run_uri,
                run_dir=run_dir,
                local_output_dir=local_run_store.local_stage_artifact_dir(
                    run_uri, stage.name
                ),
                local_workspace_dir=local_run_store.local_stage_workspace_dir(
                    run_uri, stage.name
                ),
                config_mapping=config_mapping,
                spec=spec,
                stage=stage,
                stage_plan=stage_plan,
                resolved_runtime=resolved_runtime[stage.name],
                plan=plan,
                artifact_store=artifact_store,
                produced_outputs=outputs_by_stage,
                created_at=created_at,
                run_started_at=started_at,
            )
            stage_results[stage.name] = result
            if result.status == StageStatus.SUCCEEDED:
                outputs_by_stage[stage.name] = dict(result.outputs)
            else:
                failed_stage = stage.name
                failure = result.failure

        finished_at = self.clock()
        if failure is None:
            write_run_status(
                self.run_store,
                run_uri=run_uri,
                status=RunStatus.SUCCEEDED,
                created_at=created_at,
                updated_at=finished_at,
                started_at=started_at,
                finished_at=finished_at,
            )
            self._emit_run_event(
                run_uri,
                "run.completed",
                timestamp=finished_at,
                payload={"status": RunStatus.SUCCEEDED.value},
            )
            run_status = RunStatus.SUCCEEDED
        else:
            self._write_failed_run(run_uri, created_at, started_at, failure)
            self._emit_run_event(
                run_uri,
                "run.failed",
                timestamp=self.clock(),
                payload={
                    "status": RunStatus.FAILED.value,
                    "failed_stage": failed_stage,
                    "failure_type": failure.failure_type,
                },
            )
            run_status = RunStatus.FAILED
            for stage_plan in plan.ordered_stage_plans:
                if stage_plan.stage_name not in stage_results:
                    stage_results[stage_plan.stage_name] = (
                        self._block_stage_after_failure(
                            run_uri=run_uri,
                            stage_plan=stage_plan,
                            blocked_by=failed_stage or failure.stage_name,
                        )
                    )
        artifact_index = self.run_store.read_artifact_index(run_uri)
        return RunResult(
            run_uri=run_uri,
            status=run_status,
            started_at=started_at,
            finished_at=finished_at,
            plan=plan,
            stage_results=stage_results,
            failed_stage=failed_stage,
            failure=failure,
            artifact_index=artifact_index,
            metadata=request.metadata,
        )

    def _run_stage(
        self,
        *,
        request: RunRequest,
        run_uri: str,
        run_dir: Path,
        config_mapping: Mapping[str, PlainData],
        spec: PipelineSpec,
        stage: StageSpec,
        stage_plan,
        resolved_runtime: ResolvedStageRuntimeOptions,
        plan: ExecutionPlan,
        artifact_store: ArtifactStore,
        local_output_dir: Path,
        local_workspace_dir: Path,
        produced_outputs: Mapping[str, Mapping[str, ArtifactRef]],
        created_at: str,
        run_started_at: str,
    ) -> StageRunResult:
        if bool(getattr(self.executor, "requires_prepared_worker_request", False)):
            return self._run_prepared_worker_stage(
                request=request,
                run_uri=run_uri,
                config_mapping=config_mapping,
                stage=stage,
                stage_plan=stage_plan,
                resolved_runtime=resolved_runtime,
                plan=plan,
                artifact_store=artifact_store,
                local_output_dir=local_output_dir,
                local_workspace_dir=local_workspace_dir,
                produced_outputs=produced_outputs,
                created_at=created_at,
                run_started_at=run_started_at,
            )

        attempt = next_stage_attempt(self.run_store, run_uri, stage.name)
        stage_started_at: str | None = None
        local_run_store = self._require_local_run_store()
        try:
            inputs = bind_stage_inputs(
                stage=stage,
                stage_plan=stage_plan,
                produced_outputs=produced_outputs,
            )
            fingerprint = build_stage_fingerprint(
                stage,
                bound_inputs=inputs,
                fingerprint_context=request.fingerprint_context,
            )
            self.run_store.write_stage_inputs(
                run_uri, stage.name, inputs, attempt=attempt
            )
            self.run_store.write_stage_fingerprint(
                run_uri, stage.name, fingerprint.to_dict(), attempt=attempt
            )
            self.run_store.prepare_stage_workspace(run_uri, stage.name)
            running_at = self.clock()
            write_stage_running(
                self.run_store,
                run_uri=run_uri,
                stage_name=stage.name,
                attempt=attempt,
                started_at=running_at,
            )
            self._emit_stage_event(
                run_uri,
                stage.name,
                "stage.started",
                timestamp=running_at,
                payload={"attempt": attempt, "action": PlanAction.RUN.value},
            )
            stage_started_at = running_at
            stage_object = self._construct_stage(spec, stage)
            context = StageContext(
                run_uri=run_uri,
                stage_name=stage.name,
                resolved_config=config_mapping,
                stage_config=stage.stage_config,
                inputs=inputs,
                local_output_dir=local_output_dir,
                local_workspace_dir=local_workspace_dir,
                provenance={},
                metadata={"factory_target": stage.factory.target_path},
                artifact_store=artifact_store,
                output_specs=stage.outputs,
            )
            exec_request = StageExecutionRequest(
                run_uri=run_uri,
                stage=stage,
                stage_plan=stage_plan,
                stage_object=stage_object,
                context=context,
                inputs=inputs,
                fingerprint=fingerprint,
                attempt=attempt,
                stdout_path=local_run_store.local_stage_log_path(
                    run_uri, stage.name, "stdout"
                ),
                stderr_path=local_run_store.local_stage_log_path(
                    run_uri, stage.name, "stderr"
                ),
                traceback_path=traceback_log_path(
                    run_store=local_run_store, run_uri=run_uri, stage_name=stage.name
                ),
                resolved_runtime=resolved_runtime,
            )
            execution_result = self.executor.execute(exec_request)
            stage_started_at = execution_result.started_at
            return self._commit_stage_execution_result(
                run_uri=run_uri,
                stage=stage,
                stage_plan=stage_plan,
                attempt=attempt,
                inputs=inputs,
                fingerprint=fingerprint,
                artifact_store=artifact_store,
                created_at=created_at,
                run_started_at=run_started_at,
                execution_result=execution_result,
            )
        except Exception as exc:
            failure = (
                exc
                if isinstance(exc, ExecutionFailure)
                else self._failure_from_exception(
                    run_uri=run_uri,
                    stage_name=stage.name,
                    attempt=attempt,
                    failure_type=_failure_type_for_exception(exc),
                    exc=exc,
                )
            )
            failure = self._record_stage_failure_and_failed_run(
                run_uri=run_uri,
                stage_name=stage.name,
                attempt=attempt,
                started_at=stage_started_at,
                created_at=created_at,
                run_started_at=run_started_at,
                failure=failure,
            )
            return StageRunResult(
                stage_name=stage.name,
                action=PlanAction.RUN,
                status=StageStatus.FAILED,
                attempt=attempt,
                outputs={},
                failure=failure,
                reasons=stage_plan.reasons,
                started_at=stage_started_at,
                finished_at=failure.failed_at,
            )

    def _run_prepared_worker_stage(
        self,
        *,
        request: RunRequest,
        run_uri: str,
        config_mapping: Mapping[str, PlainData],
        stage: StageSpec,
        stage_plan,
        resolved_runtime: ResolvedStageRuntimeOptions,
        plan: ExecutionPlan,
        artifact_store: ArtifactStore,
        local_output_dir: Path,
        local_workspace_dir: Path,
        produced_outputs: Mapping[str, Mapping[str, ArtifactRef]],
        created_at: str,
        run_started_at: str,
    ) -> StageRunResult:
        attempt = next_stage_attempt(self.run_store, run_uri, stage.name)
        stage_started_at: str | None = None
        local_run_store = self._require_local_run_store()
        try:
            prepared = prepare_stage_attempt(
                run_store=self.run_store,
                run_uri=run_uri,
                stage=stage,
                stage_plan=stage_plan,
                produced_outputs=produced_outputs,
                fingerprint_context=request.fingerprint_context,
                resolved_runtime=resolved_runtime,
                executor_name=str(getattr(self.executor, "name", "unknown")),
                executor_metadata={"worker_command": "loom stage run"},
                metadata={"subprocess": True},
                clock=self.clock,
            )
            attempt = prepared.attempt
            inputs = prepared.inputs
            fingerprint = cast(StageFingerprintRecord, prepared.fingerprint)
            running_at = self.clock()
            write_stage_running(
                self.run_store,
                run_uri=run_uri,
                stage_name=stage.name,
                attempt=attempt,
                started_at=running_at,
                metadata={
                    "action": PlanAction.RUN.value,
                    "prepared": True,
                    "worker_request": str(
                        local_run_store.local_stage_worker_request_path(
                            run_uri, stage.name
                        )
                    ),
                },
            )
            self._emit_stage_event(
                run_uri,
                stage.name,
                "stage.started",
                timestamp=running_at,
                payload={"attempt": attempt, "action": PlanAction.RUN.value},
            )
            stage_started_at = running_at
            context = StageContext(
                run_uri=run_uri,
                stage_name=stage.name,
                resolved_config=config_mapping,
                stage_config=stage.stage_config,
                inputs=inputs,
                local_output_dir=local_output_dir,
                local_workspace_dir=local_workspace_dir,
                provenance={},
                metadata={
                    "factory_target": stage.factory.target_path,
                    "worker_request": True,
                },
                run_store=self.run_store,
                artifact_store=artifact_store,
                output_specs=stage.outputs,
            )
            exec_request = StageExecutionRequest(
                run_uri=run_uri,
                stage=stage,
                stage_plan=stage_plan,
                stage_object=_PreparedWorkerStage(),
                context=context,
                inputs=inputs,
                fingerprint=fingerprint,
                attempt=attempt,
                stdout_path=Path(prepared.stdout_path),
                stderr_path=Path(prepared.stderr_path),
                traceback_path=Path(prepared.traceback_path),
                metadata={"worker_request": True},
                resolved_runtime=resolved_runtime,
            )
            execution_result = self.executor.execute(exec_request)
            stage_started_at = execution_result.started_at
            return self._commit_stage_execution_result(
                run_uri=run_uri,
                stage=stage,
                stage_plan=stage_plan,
                attempt=attempt,
                inputs=inputs,
                fingerprint=fingerprint,
                artifact_store=artifact_store,
                created_at=created_at,
                run_started_at=run_started_at,
                execution_result=execution_result,
            )
        except Exception as exc:
            failure = (
                exc
                if isinstance(exc, ExecutionFailure)
                else self._failure_from_exception(
                    run_uri=run_uri,
                    stage_name=stage.name,
                    attempt=attempt,
                    failure_type=_failure_type_for_exception(exc),
                    exc=exc,
                )
            )
            failure = self._record_stage_failure_and_failed_run(
                run_uri=run_uri,
                stage_name=stage.name,
                attempt=attempt,
                started_at=stage_started_at,
                created_at=created_at,
                run_started_at=run_started_at,
                failure=failure,
            )
            return StageRunResult(
                stage_name=stage.name,
                action=PlanAction.RUN,
                status=StageStatus.FAILED,
                attempt=attempt,
                outputs={},
                failure=failure,
                reasons=stage_plan.reasons,
                started_at=stage_started_at,
                finished_at=failure.failed_at,
            )

    def _commit_stage_execution_result(
        self,
        *,
        run_uri: str,
        stage: StageSpec,
        stage_plan,
        attempt: int,
        inputs: Mapping[str, ArtifactRef],
        fingerprint: StageFingerprintRecord,
        artifact_store: ArtifactStore,
        created_at: str,
        run_started_at: str,
        execution_result: StageExecutionResult,
    ) -> StageRunResult:
        return commit_stage_execution_result(
            self.run_store,
            run_uri=run_uri,
            stage=stage,
            stage_plan=stage_plan,
            attempt=attempt,
            inputs=inputs,
            fingerprint=fingerprint.to_dict(),
            artifact_store=artifact_store,
            created_at=created_at,
            run_started_at=run_started_at,
            execution_result=execution_result,
            executor_name=str(getattr(self.executor, "name", "unknown")),
            clock=self.clock,
        )

    def _require_local_run_store(self) -> LocalRunStorePaths:
        if not isinstance(self.run_store, LocalRunStorePaths):
            raise PipelineExecutionError(
                "PipelineRunner requires a run_store that exposes local_* path helpers"
            )
        return self.run_store

    def _resolve_request_run_uri(
        self, request: RunRequest, local_run_store: LocalRunStorePaths
    ) -> str:
        run_uri = parse_run_options(request.options).run_uri
        if run_uri is None:
            if request.open_existing:
                raise RunRequestError("RunRequest.open_existing requires run_uri")
            return local_run_store.allocate_run_uri()
        return local_run_store.resolve_run_uri(run_uri)

    def _create_or_open_run(self, run_uri: str, request: RunRequest) -> None:
        if request.open_existing:
            self.run_store.open_run(run_uri)
        else:
            self.run_store.create_run(run_uri, metadata=request.metadata)

    def _resolve_config_and_spec(
        self, request: RunRequest
    ) -> tuple[Mapping[str, PlainData], PipelineSpec]:
        if _is_composed_config(request.config):
            config_mapping = cast(
                Mapping[str, PlainData], getattr(request.config, "resolved")
            )
        elif isinstance(request.config, Mapping):
            config_mapping = dict(request.config)
        else:
            config_mapping = {}
        if request.pipeline is not None:
            return config_mapping, request.pipeline
        if "pipeline" not in config_mapping:
            raise RunRequestError(
                "config mapping must contain a top-level 'pipeline' key"
            )
        return config_mapping, parse_pipeline_config(config_mapping["pipeline"])

    def _write_config_and_provenance(
        self,
        run_uri: str,
        request: RunRequest,
        config_mapping: Mapping[str, PlainData],
    ) -> None:
        if _is_composed_config(request.config):
            self.run_store.write_composition_manifest(
                run_uri,
                _plain_mapping_from_maybe_to_dict(
                    getattr(request.config, "manifest"),
                    path="composition_manifest",
                ),
            )
            self.run_store.write_recipe_manifest(
                run_uri,
                cast(
                    Sequence[Mapping[str, PlainData]],
                    getattr(request.config, "recipe_manifest"),
                ),
            )
            self.run_store.write_run_user_metadata(
                run_uri,
                {
                    **request.metadata,
                    "config_provenance": _plain_mapping_from_maybe_to_dict(
                        getattr(request.config, "provenance"),
                        path="config_provenance",
                    ),
                },
            )
        elif config_mapping:
            self.run_store.write_config_snapshot(
                run_uri, "resolved", json_dumps_pretty(config_mapping)
            )
            self.run_store.write_config_snapshot(
                run_uri, "resolved_redacted", json_dumps_pretty(config_mapping)
            )
            self.run_store.write_recipe_manifest(run_uri, ())
        snapshots = request.config_snapshots
        for name in ("raw", "overlays", "cli_overrides"):
            value = getattr(snapshots, name)
            if value is not None:
                self.run_store.write_config_snapshot(run_uri, name, value)
        options = request.provenance_options
        try:
            from loom.provenance import capture_command_provenance

            command = request.command or capture_command_provenance()
            self.run_store.write_provenance_document(
                run_uri, "command", _plain(command.to_dict())
            )
        except Exception as exc:  # noqa: BLE001
            self.run_store.write_provenance_document(
                run_uri, "command", {"capture_error": str(exc)}
            )
        if options.capture_environment:
            try:
                from loom.provenance import capture_environment_provenance

                env = capture_environment_provenance(
                    env_keys=options.env_keys, include_user=options.include_user
                )
                self.run_store.write_provenance_document(
                    run_uri, "environment", _plain(env.to_dict())
                )
            except Exception as exc:  # noqa: BLE001
                self.run_store.write_provenance_document(
                    run_uri, "environment", {"capture_error": str(exc)}
                )
        if options.capture_dependencies:
            try:
                from loom.provenance import capture_dependency_provenance

                deps = capture_dependency_provenance(
                    packages=options.packages, strict=options.strict
                )
                self.run_store.write_provenance_document(
                    run_uri, "dependencies", _plain(deps.to_dict())
                )
            except Exception as exc:  # noqa: BLE001
                self.run_store.write_provenance_document(
                    run_uri, "dependencies", {"capture_error": str(exc)}
                )
        git_root = (
            str(request.project_root)
            if request.project_root is not None
            else options.git_root
        )
        if options.capture_git and git_root is not None:
            try:
                from loom.provenance import capture_git_provenance

                git = capture_git_provenance(
                    git_root,
                    include_remote=options.include_git_remote,
                    strict=options.strict,
                )
                self.run_store.write_provenance_document(
                    run_uri, "git", _plain(git.to_dict())
                )
            except Exception as exc:  # noqa: BLE001
                self.run_store.write_provenance_document(
                    run_uri, "git", {"capture_error": str(exc)}
                )

    def _construct_stage(self, spec: PipelineSpec, stage: StageSpec) -> Stage:
        try:
            stage_path = f"pipeline.stages[{spec.stage_names.index(stage.name)}]"
            return construct_stage(factory=stage.factory, stage_path=stage_path)
        except StageContractError:
            raise
        except Exception as exc:
            raise _TargetConstructionError(
                f"could not construct stage {stage.name!r} at {stage.factory.target_path!r}: {exc}"
            ) from exc

    def _emit_run_event(
        self,
        run_uri: str,
        event_type: str,
        *,
        timestamp: str,
        payload: Mapping[str, PlainData] | None = None,
    ) -> None:
        emit_run_event(
            self.run_store,
            run_uri=run_uri,
            event_type=event_type,
            timestamp=timestamp,
            payload=payload,
        )

    def _emit_stage_event(
        self,
        run_uri: str,
        stage_name: str,
        event_type: str,
        *,
        timestamp: str,
        payload: Mapping[str, PlainData] | None = None,
    ) -> None:
        emit_stage_event(
            self.run_store,
            run_uri=run_uri,
            stage_name=stage_name,
            event_type=event_type,
            timestamp=timestamp,
            payload=payload,
        )

    def _block_plan_stage(
        self,
        *,
        run_uri: str,
        stage_plan,
        failure: ExecutionFailure,
    ) -> StageRunResult:
        attempt = next_stage_attempt(self.run_store, run_uri, stage_plan.stage_name)
        blocked_at = failure.failed_at
        write_stage_blocked(
            self.run_store,
            run_uri=run_uri,
            stage_name=stage_plan.stage_name,
            attempt=attempt,
            blocked_at=blocked_at,
            message=f"stage {stage_plan.stage_name!r} blocked by execution plan",
            blocked_by=[],
            reason_code="plan_blocked",
            metadata={"reasons": [reason.to_dict() for reason in stage_plan.reasons]},
        )
        self._emit_stage_event(
            run_uri,
            stage_plan.stage_name,
            "stage.blocked",
            timestamp=blocked_at,
            payload={
                "attempt": attempt,
                "blocked_by": [],
                "reason_codes": _reason_codes(stage_plan.reasons),
            },
        )
        return StageRunResult(
            stage_name=stage_plan.stage_name,
            action=PlanAction.BLOCKED,
            status=StageStatus.BLOCKED,
            attempt=attempt,
            outputs={},
            failure=failure,
            reasons=stage_plan.reasons,
            finished_at=blocked_at,
        )

    def _block_stage_after_failure(
        self,
        *,
        run_uri: str,
        stage_plan,
        blocked_by: str,
    ) -> StageRunResult:
        attempt = next_stage_attempt(self.run_store, run_uri, stage_plan.stage_name)
        blocked_at = self.clock()
        blocked_by_list: list[PlainData] = [blocked_by]
        write_stage_blocked(
            self.run_store,
            run_uri=run_uri,
            stage_name=stage_plan.stage_name,
            attempt=attempt,
            blocked_at=blocked_at,
            message=f"stage blocked because upstream stage {blocked_by!r} failed",
            blocked_by=blocked_by_list,
            reason_code="upstream_failed",
            metadata={"reasons": [reason.to_dict() for reason in stage_plan.reasons]},
        )
        self._emit_stage_event(
            run_uri,
            stage_plan.stage_name,
            "stage.blocked",
            timestamp=blocked_at,
            payload={
                "attempt": attempt,
                "blocked_by": blocked_by_list,
                "reason_codes": _reason_codes(stage_plan.reasons),
            },
        )
        return StageRunResult(
            stage_name=stage_plan.stage_name,
            action=PlanAction.BLOCKED,
            status=StageStatus.BLOCKED,
            attempt=attempt,
            outputs={},
            reasons=stage_plan.reasons,
            finished_at=blocked_at,
        )

    def _reuse_stage(
        self,
        run_uri: str,
        stage_plan,
        *,
        created_at: str,
        started_at: str,
    ) -> StageRunResult:
        outputs = dict(stage_plan.reusable_outputs)
        if not outputs:
            prior_outputs = self.run_store.read_stage_outputs(
                run_uri, stage_plan.stage_name
            )
            if prior_outputs is None:
                failure = self._failure(
                    run_uri=run_uri,
                    stage_name=stage_plan.stage_name,
                    attempt=1,
                    failure_type="plan_execution",
                    message=f"REUSE stage {stage_plan.stage_name!r} has no reusable outputs",
                    executor=str(getattr(self.executor, "name", "unknown")),
                )
                self._write_failed_run(run_uri, created_at, started_at, failure)
                return StageRunResult(
                    stage_name=stage_plan.stage_name,
                    action=PlanAction.BLOCKED,
                    status=None,
                    attempt=None,
                    outputs={},
                    failure=failure,
                    reasons=stage_plan.reasons,
                    finished_at=failure.failed_at,
                )
            outputs = prior_outputs
        try:
            self._write_artifact_index_refs(
                run_uri, stage_plan.stage_name, outputs, replace=False
            )
        except Exception as exc:
            failure = self._failure_from_exception(
                run_uri=run_uri,
                stage_name=stage_plan.stage_name,
                attempt=1,
                failure_type="store_commit",
                exc=exc,
            )
            self._write_failed_run(run_uri, created_at, started_at, failure)
            return StageRunResult(
                stage_name=stage_plan.stage_name,
                action=PlanAction.BLOCKED,
                status=None,
                attempt=None,
                outputs={},
                failure=failure,
                reasons=stage_plan.reasons,
                finished_at=failure.failed_at,
            )
        prior_status = self.run_store.read_stage_status(run_uri, stage_plan.stage_name)
        self._emit_stage_event(
            run_uri,
            stage_plan.stage_name,
            "stage.reused",
            timestamp=self.clock(),
            payload={
                "action": PlanAction.REUSE.value,
                "reason_codes": _reason_codes(stage_plan.reasons),
                **({"attempt": prior_status.attempt} if prior_status else {}),
            },
        )
        return StageRunResult(
            stage_name=stage_plan.stage_name,
            action=PlanAction.REUSE,
            status=prior_status.status if prior_status else StageStatus.SUCCEEDED,
            attempt=prior_status.attempt if prior_status else None,
            outputs=outputs,
            reasons=stage_plan.reasons,
        )

    def _skip_stage(
        self,
        run_uri: str,
        stage_plan,
        *,
        created_at: str,
        started_at: str,
    ) -> StageRunResult:
        attempt = next_stage_attempt(self.run_store, run_uri, stage_plan.stage_name)
        finished_at = self.clock()
        try:
            write_stage_skipped(
                self.run_store,
                run_uri=run_uri,
                stage_name=stage_plan.stage_name,
                attempt=attempt,
                finished_at=finished_at,
                message="stage skipped by selector",
                metadata={
                    "reasons": [reason.to_dict() for reason in stage_plan.reasons]
                },
            )
            self._emit_stage_event(
                run_uri,
                stage_plan.stage_name,
                "stage.skipped",
                timestamp=finished_at,
                payload={
                    "attempt": attempt,
                    "action": PlanAction.SKIP.value,
                    "reason_codes": _reason_codes(stage_plan.reasons),
                },
            )
        except Exception as exc:
            failure = self._failure_from_exception(
                run_uri=run_uri,
                stage_name=stage_plan.stage_name,
                attempt=attempt,
                failure_type="store_commit",
                exc=exc,
            )
            self._write_failed_run(run_uri, created_at, started_at, failure)
            return StageRunResult(
                stage_name=stage_plan.stage_name,
                action=PlanAction.BLOCKED,
                status=None,
                attempt=attempt,
                outputs={},
                failure=failure,
                reasons=stage_plan.reasons,
                finished_at=failure.failed_at,
            )
        return StageRunResult(
            stage_name=stage_plan.stage_name,
            action=PlanAction.SKIP,
            status=StageStatus.SKIPPED,
            attempt=attempt,
            outputs={},
            reasons=stage_plan.reasons,
            finished_at=finished_at,
        )

    def _write_artifact_index_for_stage(
        self,
        run_uri: str,
        stage: StageSpec,
        outputs: Mapping[str, ArtifactRef],
        *,
        replace: bool,
    ) -> None:
        write_stage_artifact_index_refs(
            self.run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            outputs=outputs,
            replace=replace,
        )

    def _write_artifact_index_refs(
        self,
        run_uri: str,
        stage_name: str,
        outputs: Mapping[str, ArtifactRef],
        *,
        replace: bool,
    ) -> None:
        write_stage_artifact_index_refs(
            self.run_store,
            run_uri=run_uri,
            stage_name=stage_name,
            outputs=outputs,
            replace=replace,
        )

    def _write_stage_provenance(
        self,
        run_uri: str,
        stage: StageSpec,
        *,
        status: StageStatus,
        attempt: int,
        started_at: str,
        finished_at: str,
        fingerprint: Mapping[str, PlainData],
        inputs: Mapping[str, ArtifactRef],
        outputs: Mapping[str, ArtifactRef],
        executor_metadata: Mapping[str, PlainData],
    ) -> None:
        from .lifecycle import write_stage_provenance

        write_stage_provenance(
            self.run_store,
            run_uri=run_uri,
            stage=stage,
            status=status,
            attempt=attempt,
            started_at=started_at,
            finished_at=finished_at,
            fingerprint=fingerprint,
            inputs=inputs,
            outputs=outputs,
            executor_metadata=executor_metadata,
        )

    def _persist_stage_failure(
        self,
        run_uri: str,
        stage_name: str,
        attempt: int,
        started_at: str | None,
        failure: ExecutionFailure,
    ) -> None:
        persist_stage_failure(
            self.run_store,
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            started_at=started_at,
            failure=failure,
            clock=self.clock,
        )

    def _record_stage_failure_and_failed_run(
        self,
        *,
        run_uri: str,
        stage_name: str,
        attempt: int,
        started_at: str | None,
        created_at: str,
        run_started_at: str,
        failure: ExecutionFailure,
    ) -> ExecutionFailure:
        return record_stage_failure_and_failed_run(
            self.run_store,
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            started_at=started_at,
            created_at=created_at,
            run_started_at=run_started_at,
            failure=failure,
            executor_name=str(getattr(self.executor, "name", "unknown")),
            clock=self.clock,
        )

    def _write_failed_run(
        self,
        run_uri: str,
        created_at: str,
        started_at: str,
        failure: ExecutionFailure,
    ) -> None:
        write_failed_run(
            self.run_store,
            run_uri=run_uri,
            created_at=created_at,
            started_at=started_at,
            failure=failure,
        )

    def _created_at(self, run_uri: str, fallback: str) -> str:
        status = self.run_store.read_run_status(run_uri)
        if status is not None:
            return status.created_at
        metadata = self.run_store.read_run_document(run_uri)
        created = metadata.get("created_at")
        return created if isinstance(created, str) else fallback

    def _plan_failure(
        self,
        run_uri: str,
        stage: StageSpec,
        action: PlanAction,
        reasons: tuple[PlanReason, ...],
    ) -> ExecutionFailure:
        return self._failure(
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=1,
            failure_type="plan_execution",
            message=f"stage plan action {action.value} is not executable",
            executor=str(getattr(self.executor, "name", "unknown")),
            details={"reasons": [reason.to_dict() for reason in reasons]},
        )

    def _failure_from_exception(
        self,
        *,
        run_uri: str,
        stage_name: str,
        attempt: int,
        failure_type: str,
        exc: Exception,
    ) -> ExecutionFailure:
        return self._failure(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            failure_type=failure_type,
            message=str(exc) or type(exc).__name__,
            executor=str(getattr(self.executor, "name", "unknown")),
            exception_type=f"{type(exc).__module__}.{type(exc).__name__}",
        )

    def _failure(
        self,
        *,
        run_uri: str,
        stage_name: str,
        attempt: int,
        failure_type: str,
        message: str,
        executor: str,
        exception_type: str | None = None,
        details: Mapping[str, PlainData] | None = None,
    ) -> ExecutionFailure:
        return ExecutionFailure(
            schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            failed_at=self.clock(),
            executor=executor,
            failure_type=failure_type,
            message=message,
            exception_type=exception_type,
            details=details or {},
        )


def _options_with_resolved_run_uri(options: RunOptions, run_uri: str) -> RunOptions:
    if options.run_uri == run_uri:
        return options
    data = options.to_dict()
    data["run_uri"] = run_uri
    return RunOptions.from_dict(data)


def run_pipeline(
    request: RunRequest,
    *,
    run_store: RunStore,
    executor: Executor | None = None,
    artifact_store_factory: ArtifactStoreFactory | None = None,
) -> RunResult:
    return PipelineRunner(
        run_store=run_store,
        executor=executor,
        artifact_store_factory=artifact_store_factory,
    ).run(request)


def _reason_codes(reasons: tuple[PlanReason, ...]) -> list[PlainData]:
    return [reason.code.value for reason in reasons]


def _failure_type_for_exception(exc: Exception) -> str:
    if isinstance(exc, OutputValidationError):
        return "output_validation"
    if isinstance(exc, _TargetConstructionError):
        return "target_construction"
    if isinstance(exc, StageContractError):
        return "stage_contract"
    if isinstance(exc, PlanExecutionError):
        return "plan_execution"
    if isinstance(exc, (StoreError, ArtifactStoreError)):
        return "store_commit"
    return "executor_infrastructure"


def _is_composed_config(value: object) -> bool:
    return all(
        hasattr(value, name)
        for name in (
            "resolved",
            "redacted",
            "manifest",
            "provenance",
            "recipe_manifest",
        )
    )


def _plain(value: object) -> dict[str, PlainData]:
    normalized = ensure_plain_data(value, path="provenance")
    if not isinstance(normalized, dict):
        raise PipelineExecutionError("expected mapping plain data")
    return cast(dict[str, PlainData], normalized)


def _plain_mapping_from_maybe_to_dict(
    value: object, *, path: str
) -> dict[str, PlainData]:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
    normalized = ensure_plain_data(value, path=path)
    if not isinstance(normalized, dict):
        raise PipelineExecutionError(f"{path} must be mapping plain data")
    return cast(dict[str, PlainData], normalized)


__all__ = ["ArtifactStoreFactory", "PipelineRunner", "run_pipeline"]
