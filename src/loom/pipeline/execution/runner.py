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
    build_stage_fingerprint,
    plan_pipeline,
)
from loom.pipeline.specs import PipelineSpec, StageSpec, parse_pipeline_config
from loom.pipeline.stage_factory import construct_stage
from loom.pipeline.stage import Stage
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStorePaths, RunStore
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.errors import ArtifactStoreError, StoreError
from loom.pipeline.stores.indexes import format_artifact_key, merge_artifact_index
from loom.serialization import PlainData, ensure_plain_data, json_dumps_pretty
from loom.timestamps import utc_timestamp

from .errors import (
    OutputValidationError,
    PipelineExecutionError,
    PlanExecutionError,
    RunRequestError,
)
from .lifecycle import (
    next_stage_attempt,
    write_run_status,
    write_stage_failed,
    write_stage_running,
    write_stage_skipped,
    write_stage_succeeded,
)
from .logs import traceback_log_path
from .models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    ExecutionFailure,
    RunRequest,
    RunResult,
    StageExecutionRequest,
    StageRunResult,
)
from .outputs import validate_stage_outputs

ArtifactStoreFactory = Callable[[Path], ArtifactStore]


class _TargetConstructionError(StageContractError):
    """Private marker for import or no-argument construction failures."""


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

        started_at = self.clock()
        run_id = cast(str, request.run_id)
        local_run_store = self._require_local_run_store()
        self._create_or_open_run(request)
        run_dir = local_run_store.local_run_dir(run_id)
        created_at = self._created_at(run_id, started_at)
        write_run_status(
            self.run_store,
            run_id=run_id,
            status=RunStatus.CREATED,
            created_at=created_at,
            updated_at=started_at,
            started_at=started_at,
            metadata=request.metadata,
        )
        config_mapping, spec = self._resolve_config_and_spec(request)
        self._write_config_and_provenance(run_id, request, config_mapping)
        artifact_store = self.artifact_store_factory(
            local_run_store.local_artifact_root(run_id)
        )

        plan = plan_pipeline(
            spec,
            run_id=run_id,
            run_store=self.run_store,
            artifact_store=artifact_store,
            selectors=request.selectors,
            resume=request.resume,
            fingerprint_context=request.fingerprint_context,
            persist=True,
        )
        write_run_status(
            self.run_store,
            run_id=run_id,
            status=RunStatus.PLANNED,
            created_at=created_at,
            updated_at=self.clock(),
            started_at=started_at,
            metadata={"plan_summary": dict(plan.summary)},
        )
        write_run_status(
            self.run_store,
            run_id=run_id,
            status=RunStatus.RUNNING,
            created_at=created_at,
            updated_at=self.clock(),
            started_at=started_at,
        )

        stage_results: dict[str, StageRunResult] = {}
        outputs_by_stage: dict[str, dict[str, ArtifactRef]] = {}
        failed_stage: str | None = None
        failure: ExecutionFailure | None = None
        for stage_plan in plan.ordered_stage_plans:
            stage = spec.get_stage(stage_plan.stage_name)
            if failed_stage is not None:
                stage_results[stage.name] = _blocked_after_failure(
                    stage, stage_plan.reasons
                )
                continue
            if stage_plan.action == PlanAction.REUSE:
                result = self._reuse_stage(
                    run_id, stage_plan, created_at=created_at, started_at=started_at
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
                    run_id,
                    stage_plan,
                    created_at=created_at,
                    started_at=started_at,
                )
                stage_results[stage.name] = result
                if result.failure is not None:
                    failed_stage = stage.name
                    failure = result.failure
                continue
            if stage_plan.action in {PlanAction.BLOCKED, PlanAction.STALE}:
                failed_stage = stage.name
                failure = self._plan_failure(
                    run_id, stage, stage_plan.action, stage_plan.reasons
                )
                stage_results[stage.name] = StageRunResult(
                    stage_name=stage.name,
                    action=PlanAction.BLOCKED,
                    status=None,
                    attempt=None,
                    outputs={},
                    failure=failure,
                    reasons=stage_plan.reasons,
                    finished_at=failure.failed_at,
                )
                self._write_failed_run(run_id, created_at, started_at, failure)
                continue
            result = self._run_stage(
                request=request,
                run_id=run_id,
                run_dir=run_dir,
                local_output_dir=local_run_store.local_stage_artifact_dir(
                    run_id, stage.name
                ),
                local_workspace_dir=local_run_store.local_stage_workspace_dir(
                    run_id, stage.name
                ),
                config_mapping=config_mapping,
                spec=spec,
                stage=stage,
                stage_plan=stage_plan,
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
        artifact_index = self.run_store.read_artifact_index(run_id)
        if failure is None:
            write_run_status(
                self.run_store,
                run_id=run_id,
                status=RunStatus.SUCCEEDED,
                created_at=created_at,
                updated_at=finished_at,
                started_at=started_at,
                finished_at=finished_at,
            )
            run_status = RunStatus.SUCCEEDED
        else:
            run_status = RunStatus.FAILED
            for stage_plan in plan.ordered_stage_plans:
                if stage_plan.stage_name not in stage_results:
                    stage_results[stage_plan.stage_name] = _blocked_after_failure(
                        stage_plan, ()
                    )
        return RunResult(
            run_id=run_id,
            run_dir=run_dir,
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
        run_id: str,
        run_dir: Path,
        config_mapping: Mapping[str, PlainData],
        spec: PipelineSpec,
        stage: StageSpec,
        stage_plan,
        plan: ExecutionPlan,
        artifact_store: ArtifactStore,
        local_output_dir: Path,
        local_workspace_dir: Path,
        produced_outputs: Mapping[str, Mapping[str, ArtifactRef]],
        created_at: str,
        run_started_at: str,
    ) -> StageRunResult:
        attempt = next_stage_attempt(self.run_store, run_id, stage.name)
        stage_started_at: str | None = None
        local_run_store = self._require_local_run_store()
        try:
            inputs = self._bind_inputs(stage, stage_plan, produced_outputs)
            fingerprint = build_stage_fingerprint(
                stage,
                bound_inputs=inputs,
                fingerprint_context=request.fingerprint_context,
            )
            self.run_store.write_stage_inputs(
                run_id, stage.name, inputs, attempt=attempt
            )
            self.run_store.write_stage_fingerprint(
                run_id, stage.name, fingerprint.to_dict(), attempt=attempt
            )
            self.run_store.prepare_stage_workspace(run_id, stage.name)
            running_at = self.clock()
            write_stage_running(
                self.run_store,
                run_id=run_id,
                stage_name=stage.name,
                attempt=attempt,
                started_at=running_at,
            )
            stage_started_at = running_at
            stage_object = self._construct_stage(spec, stage)
            context = StageContext(
                run_id=run_id,
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
                run_id=run_id,
                stage=stage,
                stage_plan=stage_plan,
                stage_object=stage_object,
                context=context,
                inputs=inputs,
                fingerprint=fingerprint,
                attempt=attempt,
                stdout_path=local_run_store.local_stage_log_path(
                    run_id, stage.name, "stdout"
                ),
                stderr_path=local_run_store.local_stage_log_path(
                    run_id, stage.name, "stderr"
                ),
                traceback_path=traceback_log_path(
                    run_store=local_run_store, run_id=run_id, stage_name=stage.name
                ),
            )
            execution_result = self.executor.execute(exec_request)
            stage_started_at = execution_result.started_at
            if execution_result.status == StageStatus.FAILED:
                failure = execution_result.failure or self._failure(
                    run_id=run_id,
                    stage_name=stage.name,
                    attempt=attempt,
                    failure_type="executor_infrastructure",
                    message="executor failed without failure metadata",
                    executor=str(getattr(self.executor, "name", "unknown")),
                )
                failure = self._record_stage_failure_and_failed_run(
                    run_id=run_id,
                    stage_name=stage.name,
                    attempt=attempt,
                    started_at=execution_result.started_at,
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
                    started_at=execution_result.started_at,
                    finished_at=execution_result.finished_at,
                    executor_metadata=execution_result.executor_metadata,
                )
            outputs = validate_stage_outputs(
                stage=stage,
                outputs=execution_result.outputs,
                artifact_store=artifact_store,
            )
            self.run_store.write_stage_outputs(
                run_id, stage.name, outputs, attempt=attempt
            )
            self._write_artifact_index_for_stage(run_id, stage, outputs, replace=True)
            self._write_stage_provenance(
                run_id,
                stage,
                status=StageStatus.SUCCEEDED,
                attempt=attempt,
                started_at=execution_result.started_at,
                finished_at=execution_result.finished_at,
                fingerprint=fingerprint.to_dict(),
                inputs=inputs,
                outputs=outputs,
                executor_metadata=execution_result.executor_metadata,
            )
            write_stage_succeeded(
                self.run_store,
                run_id=run_id,
                stage_name=stage.name,
                attempt=attempt,
                started_at=execution_result.started_at,
                finished_at=execution_result.finished_at,
                metadata={"action": PlanAction.RUN.value},
            )
            return StageRunResult(
                stage_name=stage.name,
                action=PlanAction.RUN,
                status=StageStatus.SUCCEEDED,
                attempt=attempt,
                outputs=outputs,
                reasons=stage_plan.reasons,
                started_at=execution_result.started_at,
                finished_at=execution_result.finished_at,
                executor_metadata=execution_result.executor_metadata,
            )
        except Exception as exc:
            failure = (
                exc
                if isinstance(exc, ExecutionFailure)
                else self._failure_from_exception(
                    run_id=run_id,
                    stage_name=stage.name,
                    attempt=attempt,
                    failure_type=_failure_type_for_exception(exc),
                    exc=exc,
                )
            )
            failure = self._record_stage_failure_and_failed_run(
                run_id=run_id,
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

    def _require_local_run_store(self) -> LocalRunStorePaths:
        if not isinstance(self.run_store, LocalRunStorePaths):
            raise PipelineExecutionError(
                "PipelineRunner requires a run_store that exposes local_* path helpers"
            )
        return self.run_store

    def _create_or_open_run(self, request: RunRequest) -> None:
        run_id = cast(str, request.run_id)
        if request.open_existing:
            self.run_store.open_run(run_id)
        else:
            self.run_store.create_run(run_id, metadata=request.metadata)

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
        run_id: str,
        request: RunRequest,
        config_mapping: Mapping[str, PlainData],
    ) -> None:
        if _is_composed_config(request.config):
            resolved = cast(
                Mapping[str, PlainData], getattr(request.config, "resolved")
            )
            redacted = cast(
                Mapping[str, PlainData], getattr(request.config, "redacted")
            )
            self.run_store.write_config_snapshot(
                run_id, "resolved", json_dumps_pretty(resolved)
            )
            self.run_store.write_config_snapshot(
                run_id, "resolved_redacted", json_dumps_pretty(redacted)
            )
            self.run_store.write_recipe_manifest(
                run_id,
                cast(
                    Sequence[Mapping[str, PlainData]],
                    getattr(request.config, "recipe_manifest"),
                ),
            )
            self.run_store.write_run_user_metadata(
                run_id,
                {
                    **request.metadata,
                    "config_provenance": getattr(
                        request.config, "provenance"
                    ).to_dict(),
                },
            )
        elif config_mapping:
            self.run_store.write_config_snapshot(
                run_id, "resolved", json_dumps_pretty(config_mapping)
            )
            self.run_store.write_config_snapshot(
                run_id, "resolved_redacted", json_dumps_pretty(config_mapping)
            )
            self.run_store.write_recipe_manifest(run_id, ())
        snapshots = request.config_snapshots
        for name in ("raw", "overlays", "cli_overrides"):
            value = getattr(snapshots, name)
            if value is not None:
                self.run_store.write_config_snapshot(run_id, name, value)
        options = request.provenance_options
        try:
            from loom.provenance import capture_command_provenance

            command = request.command or capture_command_provenance()
            self.run_store.write_provenance_document(
                run_id, "command", _plain(command.to_dict())
            )
        except Exception as exc:  # noqa: BLE001
            self.run_store.write_provenance_document(
                run_id, "command", {"capture_error": str(exc)}
            )
        if options.capture_environment:
            try:
                from loom.provenance import capture_environment_provenance

                env = capture_environment_provenance(
                    env_keys=options.env_keys, include_user=options.include_user
                )
                self.run_store.write_provenance_document(
                    run_id, "environment", _plain(env.to_dict())
                )
            except Exception as exc:  # noqa: BLE001
                self.run_store.write_provenance_document(
                    run_id, "environment", {"capture_error": str(exc)}
                )
        if options.capture_dependencies:
            try:
                from loom.provenance import capture_dependency_provenance

                deps = capture_dependency_provenance(
                    packages=options.packages, strict=options.strict
                )
                self.run_store.write_provenance_document(
                    run_id, "dependencies", _plain(deps.to_dict())
                )
            except Exception as exc:  # noqa: BLE001
                self.run_store.write_provenance_document(
                    run_id, "dependencies", {"capture_error": str(exc)}
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
                    run_id, "git", _plain(git.to_dict())
                )
            except Exception as exc:  # noqa: BLE001
                self.run_store.write_provenance_document(
                    run_id, "git", {"capture_error": str(exc)}
                )

    def _bind_inputs(
        self,
        stage: StageSpec,
        stage_plan,
        produced_outputs: Mapping[str, Mapping[str, ArtifactRef]],
    ) -> dict[str, ArtifactRef]:
        inputs: dict[str, ArtifactRef] = {
            name: bound.artifact_ref for name, bound in stage_plan.bound_inputs.items()
        }
        for pending in stage_plan.pending_inputs:
            upstream = produced_outputs.get(pending.source_stage)
            if upstream is None or pending.source_output not in upstream:
                raise PlanExecutionError(
                    f"Cannot bind input {stage.name}.{pending.input_name} from "
                    f"{pending.source_stage}.{pending.source_output}"
                )
            inputs[pending.input_name] = upstream[pending.source_output]
        expected = set(stage.inputs)
        if set(inputs) != expected:
            missing = expected - set(inputs)
            extra = set(inputs) - expected
            parts: list[str] = []
            if missing:
                parts.append(f"missing {', '.join(sorted(missing))}")
            if extra:
                parts.append(f"extra {', '.join(sorted(extra))}")
            raise PlanExecutionError(
                f"Input binding mismatch for stage {stage.name}: {'; '.join(parts)}"
            )
        return inputs

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

    def _reuse_stage(
        self,
        run_id: str,
        stage_plan,
        *,
        created_at: str,
        started_at: str,
    ) -> StageRunResult:
        outputs = dict(stage_plan.reusable_outputs)
        if not outputs:
            prior_outputs = self.run_store.read_stage_outputs(
                run_id, stage_plan.stage_name
            )
            if prior_outputs is None:
                failure = self._failure(
                    run_id=run_id,
                    stage_name=stage_plan.stage_name,
                    attempt=1,
                    failure_type="plan_execution",
                    message=f"REUSE stage {stage_plan.stage_name!r} has no reusable outputs",
                    executor=str(getattr(self.executor, "name", "unknown")),
                )
                self._write_failed_run(run_id, created_at, started_at, failure)
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
                run_id, stage_plan.stage_name, outputs, replace=False
            )
        except Exception as exc:
            failure = self._failure_from_exception(
                run_id=run_id,
                stage_name=stage_plan.stage_name,
                attempt=1,
                failure_type="store_commit",
                exc=exc,
            )
            self._write_failed_run(run_id, created_at, started_at, failure)
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
        prior_status = self.run_store.read_stage_status(run_id, stage_plan.stage_name)
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
        run_id: str,
        stage_plan,
        *,
        created_at: str,
        started_at: str,
    ) -> StageRunResult:
        attempt = next_stage_attempt(self.run_store, run_id, stage_plan.stage_name)
        finished_at = self.clock()
        try:
            write_stage_skipped(
                self.run_store,
                run_id=run_id,
                stage_name=stage_plan.stage_name,
                attempt=attempt,
                finished_at=finished_at,
                message="stage skipped by selector",
                metadata={
                    "reasons": [reason.to_dict() for reason in stage_plan.reasons]
                },
            )
        except Exception as exc:
            failure = self._failure_from_exception(
                run_id=run_id,
                stage_name=stage_plan.stage_name,
                attempt=attempt,
                failure_type="store_commit",
                exc=exc,
            )
            self._write_failed_run(run_id, created_at, started_at, failure)
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
        run_id: str,
        stage: StageSpec,
        outputs: Mapping[str, ArtifactRef],
        *,
        replace: bool,
    ) -> None:
        updates = {
            format_artifact_key(stage.name, output_name): ref
            for output_name, ref in outputs.items()
        }
        existing = self.run_store.read_artifact_index(run_id)
        self.run_store.write_artifact_index(
            run_id, merge_artifact_index(existing, updates, replace=replace)
        )

    def _write_artifact_index_refs(
        self,
        run_id: str,
        stage_name: str,
        outputs: Mapping[str, ArtifactRef],
        *,
        replace: bool,
    ) -> None:
        updates = {
            format_artifact_key(stage_name, output_name): ref
            for output_name, ref in outputs.items()
        }
        existing = self.run_store.read_artifact_index(run_id)
        self.run_store.write_artifact_index(
            run_id, merge_artifact_index(existing, updates, replace=replace)
        )

    def _write_stage_provenance(
        self,
        run_id: str,
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
        from loom.provenance.models import StageProvenance

        provenance = StageProvenance(
            run_id=run_id,
            stage_name=stage.name,
            status=status.value,
            attempt=attempt,
            target=stage.target_path,
            started_at=started_at,
            finished_at=finished_at,
            fingerprint=fingerprint,
            input_artifacts={
                name: _plain(ref.to_dict()) for name, ref in inputs.items()
            },
            output_artifacts={
                name: _plain(ref.to_dict()) for name, ref in outputs.items()
            },
            executor_metadata=executor_metadata,
        )
        self.run_store.write_stage_provenance(
            run_id, stage.name, _plain(provenance.to_dict()), attempt=attempt
        )

    def _persist_stage_failure(
        self,
        run_id: str,
        stage_name: str,
        attempt: int,
        started_at: str | None,
        failure: ExecutionFailure,
    ) -> None:
        self.run_store.write_stage_failure(
            run_id, stage_name, failure.to_dict(), attempt=attempt
        )
        write_stage_failed(
            self.run_store,
            run_id=run_id,
            stage_name=stage_name,
            attempt=attempt,
            started_at=started_at,
            finished_at=failure.failed_at,
            message=failure.message,
            metadata={"failure_type": failure.failure_type},
        )

    def _record_stage_failure_and_failed_run(
        self,
        *,
        run_id: str,
        stage_name: str,
        attempt: int,
        started_at: str | None,
        created_at: str,
        run_started_at: str,
        failure: ExecutionFailure,
    ) -> ExecutionFailure:
        try:
            self._persist_stage_failure(
                run_id, stage_name, attempt, started_at, failure
            )
        except Exception as exc:
            failure = self._failure_from_exception(
                run_id=run_id,
                stage_name=stage_name,
                attempt=attempt,
                failure_type="store_commit",
                exc=exc,
            )
        self._write_failed_run(run_id, created_at, run_started_at, failure)
        return failure

    def _write_failed_run(
        self,
        run_id: str,
        created_at: str,
        started_at: str,
        failure: ExecutionFailure,
    ) -> None:
        write_run_status(
            self.run_store,
            run_id=run_id,
            status=RunStatus.FAILED,
            created_at=created_at,
            updated_at=failure.failed_at,
            started_at=started_at,
            finished_at=failure.failed_at,
            message=failure.message,
            metadata={
                "failed_stage": failure.stage_name,
                "failure_type": failure.failure_type,
            },
        )

    def _created_at(self, run_id: str, fallback: str) -> str:
        status = self.run_store.read_run_status(run_id)
        if status is not None:
            return status.created_at
        metadata = self.run_store.read_run_document(run_id)
        created = metadata.get("created_at")
        return created if isinstance(created, str) else fallback

    def _plan_failure(
        self,
        run_id: str,
        stage: StageSpec,
        action: PlanAction,
        reasons: tuple[PlanReason, ...],
    ) -> ExecutionFailure:
        return self._failure(
            run_id=run_id,
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
        run_id: str,
        stage_name: str,
        attempt: int,
        failure_type: str,
        exc: Exception,
    ) -> ExecutionFailure:
        return self._failure(
            run_id=run_id,
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
        run_id: str,
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
            run_id=run_id,
            stage_name=stage_name,
            attempt=attempt,
            failed_at=self.clock(),
            executor=executor,
            failure_type=failure_type,
            message=message,
            exception_type=exception_type,
            details=details or {},
        )


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


def _blocked_after_failure(
    stage_or_plan: StageSpec | object, reasons: tuple[PlanReason, ...]
) -> StageRunResult:
    stage_name = getattr(
        stage_or_plan, "name", getattr(stage_or_plan, "stage_name", "unknown")
    )
    return StageRunResult(
        stage_name=str(stage_name),
        action=PlanAction.BLOCKED,
        status=None,
        attempt=None,
        outputs={},
        reasons=reasons,
    )


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
        for name in ("resolved", "redacted", "provenance", "recipe_manifest")
    )


def _plain(value: object) -> dict[str, PlainData]:
    normalized = ensure_plain_data(value, path="provenance")
    if not isinstance(normalized, dict):
        raise PipelineExecutionError("expected mapping plain data")
    return cast(dict[str, PlainData], normalized)


__all__ = ["ArtifactStoreFactory", "PipelineRunner", "run_pipeline"]
