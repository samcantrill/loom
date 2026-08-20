"""Local serial pipeline runner."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Any, cast

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext
from loom.pipeline.errors import StageContractError
from loom.pipeline.executors.base import Executor
from loom.pipeline.planning import (
    ExecutionPlan,
    PlanAction,
    PlanReason,
    PlanReasonCode,
    StageFingerprintRecord,
    StagePlan,
    build_stage_fingerprint,
    plan_pipeline,
)
from loom.pipeline.resources import ResourceRequest
from loom.pipeline.offline_evidence import write_offline_evidence_manifest
from loom.pipeline.reliability import ReliabilityPolicy, RetryPolicy
from loom.pipeline.runtime import (
    ExecutionOptions,
    ParallelExecutionOptions,
    ResolvedStageRuntimeOptions,
    RunOptions,
    build_runtime_metadata,
    merge_config_run_options,
    parallel_execution_options,
    parse_run_options,
    resolve_run_runtime,
)
from loom.pipeline.specs import PipelineSpec, StageSpec, parse_pipeline_config
from loom.pipeline.stage_factory import construct_stage
from loom.pipeline.stage import Stage
from loom.pipeline.status import RunStatus, StageStatus, StageStatusRecord
from loom.pipeline.transition_policy import TransitionIntent
from loom.pipeline.stores import (
    AuthorityStoreError,
    BackendCapability,
    CapabilityScope,
    DiagnosticSeverity,
    LifecycleReason,
    LocalArtifactStore,
    LocalRunStore,
    LocalRunStorePaths,
    LegacyRunStore,
    RequiredAuthorityCapability,
    StoreDiagnostic,
    admit_authority_capabilities,
)
from loom.pipeline.stores.config import authority_config_to_cli_args
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.errors import ArtifactStoreError, StoreError
from loom.serialization import PlainData, ensure_plain_data, json_dumps_pretty
from loom.timestamps import utc_timestamp

from .errors import (
    OutputValidationError,
    ParallelExecutionUnsupportedError,
    PipelineExecutionError,
    PlanExecutionError,
    RunRequestError,
)
from .eventing import EventPersistenceMode, RuntimeEventDispatcher
from .eventing import emit_run_event, emit_stage_event
from .lifecycle import (
    bind_stage_inputs,
    commit_stage_execution_result,
    next_stage_attempt,
    persist_stage_cancellation,
    persist_stage_failure,
    record_stage_failure_and_failed_run,
    write_stage_artifact_index_refs,
    write_cancelled_run,
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
from .offline_adapter import OfflineEvidenceRunStore, is_offline_evidence_run_store
from .services import RuntimeServices, runtime_store_facade
from .reliability import (
    record_resolved_reliability_policy_fact,
    record_retry_decision_for_stage_result,
)
from .resource_admission import (
    DEFAULT_RESOURCE_LEASE_TTL_SECONDS,
    ResourceAdmissionDecision,
    ResourceAdmissionError,
    ResourceAdmissionRequest,
    ResourceAdmissionStatus,
    acquire_resource_admission,
    release_resource_admission,
    resource_requests_from_runtime,
)
from .run_locks import acquire_run_lock, build_lock_owner, release_run_lock
from .stage_attempts import prepare_stage_attempt

ArtifactStoreFactory = Callable[[Path], ArtifactStore]
RunnerRunStore = LegacyRunStore | OfflineEvidenceRunStore
_STAGE_LEASE_RENEWAL_INTERVAL_SECONDS = 60.0
_CONTROLLER_LEASE_RENEWAL_INTERVAL_SECONDS = 60.0
_REQUIRED_PARALLEL_CAPABILITIES = (
    BackendCapability.ATOMIC_TRANSITIONS,
    BackendCapability.ATTEMPT_ALLOCATION,
    BackendCapability.STAGE_LEASES,
    BackendCapability.BACKEND_LEASE_TIME,
    BackendCapability.ATOMIC_OUTPUT_COMMIT,
    BackendCapability.ARTIFACT_FACTS,
    BackendCapability.REVISIONED_SNAPSHOTS,
    BackendCapability.RECOVERY_SCANS,
    BackendCapability.CONSISTENT_READS,
    BackendCapability.PER_RUN_COORDINATION,
)


@dataclass(slots=True)
class _ExecutionOutcome:
    stage_results: dict[str, StageRunResult]
    outputs_by_stage: dict[str, dict[str, ArtifactRef]]
    failed_stage: str | None
    failure: ExecutionFailure | None
    cancelled_stage: str | None = None
    cancellation_reason: LifecycleReason | None = None
    interruption: KeyboardInterrupt | None = None


@dataclass(slots=True)
class _ControllerLeaseRenewal:
    stop_event: Event
    thread: Thread
    errors: list[BaseException]


class _StageInterrupted(Exception):
    """Private handoff for an interrupt after its stage cancellation is durable."""

    def __init__(
        self,
        result: StageRunResult,
        interruption: KeyboardInterrupt,
        *,
        cancelled_stage: str | None,
    ) -> None:
        self.result = result
        self.interruption = interruption
        self.cancelled_stage = cancelled_stage


@dataclass(frozen=True, slots=True)
class _ParallelTask:
    stage_name: str


@dataclass(frozen=True, slots=True)
class _ParallelPlanContext:
    request: RunRequest
    run_uri: str
    run_dir: Path
    local_run_store: LocalRunStorePaths
    config_mapping: Mapping[str, PlainData]
    spec: PipelineSpec
    resolved_runtime: Mapping[str, ResolvedStageRuntimeOptions]
    plan: ExecutionPlan
    artifact_store: ArtifactStore
    created_at: str
    run_started_at: str
    policy: ParallelExecutionOptions


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
        services: RuntimeServices | None = None,
        run_store: RunnerRunStore | None = None,
        executor: Executor | None = None,
        artifact_store_factory: ArtifactStoreFactory | None = None,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None:
        offline_execution = is_offline_evidence_run_store(run_store)
        if services is None:
            if run_store is None:
                raise PipelineExecutionError("PipelineRunner requires services")
            if offline_execution:
                services = RuntimeServices.from_legacy(cast(Any, run_store).local_store)
            else:
                services = RuntimeServices.from_legacy(cast(LegacyRunStore, run_store))
        elif run_store is not None:
            raise PipelineExecutionError(
                "PipelineRunner accepts either services or run_store"
            )
        execution_store = (
            run_store
            if is_offline_evidence_run_store(run_store)
            else runtime_store_facade(services)
        )
        if (
            isinstance(services.local_paths, LocalRunStore)
            and services.authority_store is None
            and not offline_execution
        ):
            raise PipelineExecutionError(
                "PipelineRunner requires an authority-backed runtime store; "
                "LocalRunStore is limited to local artifact/materialization access. "
                "Use create_authority_backed_serial_run_store(...) for serial "
                "Python execution."
            )
        if executor is None:
            from loom.pipeline.executors import LocalExecutor

            executor = LocalExecutor()
        if not isinstance(executor, Executor):
            raise PipelineExecutionError("executor must satisfy Executor")
        self.services = services
        self.run_store = cast(LegacyRunStore, execution_store)
        self.executor = executor
        self.artifact_store_factory = artifact_store_factory or (
            lambda root: LocalArtifactStore(root)
        )
        self.clock = clock
        self._stage_lease_renewal_interval_seconds = (
            _STAGE_LEASE_RENEWAL_INTERVAL_SECONDS
        )
        self._controller_lease_renewal_interval_seconds = (
            _CONTROLLER_LEASE_RENEWAL_INTERVAL_SECONDS
        )
        self._controller_lease_renewal: _ControllerLeaseRenewal | None = None
        self._event_dispatcher: RuntimeEventDispatcher | None = None

    def run(self, request: RunRequest) -> RunResult:
        if not isinstance(request, RunRequest):
            raise RunRequestError("PipelineRunner.run requires RunRequest")
        event_dispatcher = _event_dispatcher_from_request(request)
        previous_event_dispatcher = self._event_dispatcher
        self._event_dispatcher = event_dispatcher
        try:
            config_mapping, spec = self._resolve_config_and_spec(request)
            options = _merged_request_options(
                request,
                config_mapping=config_mapping,
                stage_names=spec.stage_names,
            )
            if options.dry_run:
                raise RunRequestError(
                    "PipelineRunner.run does not execute dry-run requests; use planning APIs instead"
                )
            parallel_policy = _parallel_policy_from_request(request, options)
            self._preflight_authority_admission(parallel_policy)

            started_at = self.clock()
            local_run_store = self._require_local_run_store()
            run_uri = self._resolve_request_run_uri(
                request,
                local_run_store,
                options=options,
            )
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
            renewal = self._start_controller_lease_renewal(run_uri, lock.token)
            try:
                self._raise_controller_lease_renewal_error()
                self._recover_abandoned_run_if_needed(
                    request=request,
                    run_uri=run_uri,
                    prior_status=self._run_status_before_preparation(run_uri),
                )
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
                    config_mapping=config_mapping,
                    spec=spec,
                    options=options,
                    started_at=started_at,
                )
            finally:
                self._stop_controller_lease_renewal(renewal)
                release_run_lock(self.run_store, lock)
        finally:
            self._event_dispatcher = previous_event_dispatcher

    def _preflight_authority_admission(self, policy: ParallelExecutionOptions) -> None:
        if is_offline_evidence_run_store(self.run_store):
            if policy.enabled:
                raise ParallelExecutionUnsupportedError(
                    "offline-first evidence runs do not support bounded parallel execution",
                    code="pipeline.offline_evidence.parallel_unsupported",
                    context={"max_parallel_stages": policy.max_parallel_stages},
                )
            executor_name = str(getattr(self.executor, "name", "unknown"))
            if executor_name != "local":
                raise ParallelExecutionUnsupportedError(
                    "offline-first evidence runs support only the local executor",
                    code="pipeline.offline_evidence.executor_unsupported",
                    context={"executor": executor_name},
                )
            return
        self._admit_authority_capabilities(
            (RequiredAuthorityCapability.SERIAL_RUN,),
            feature="serial pipeline execution",
            error_code="pipeline.authority.unsupported_serial",
            context={},
        )
        if str(getattr(self.executor, "name", "local")) == "subprocess":
            self._admit_authority_capabilities(
                (RequiredAuthorityCapability.SUBPROCESS_WORKER,),
                feature="subprocess worker execution",
                error_code="pipeline.authority.unsupported_subprocess_worker",
                context={},
            )
        if policy.continue_independent and not policy.enabled:
            raise ParallelExecutionUnsupportedError(
                "continue_independent failure policy requires max_parallel_stages greater than 1",
                code="pipeline.parallel.failure_policy_requires_parallelism",
                context={
                    "failure_policy": policy.failure_policy,
                    "max_parallel_stages": policy.max_parallel_stages,
                },
            )
        if not policy.enabled:
            return
        executor_name = str(getattr(self.executor, "name", "unknown"))
        if executor_name != "local":
            raise ParallelExecutionUnsupportedError(
                f"executor {executor_name!r} does not support bounded local parallel execution",
                code="pipeline.parallel.unsupported_executor",
                context={
                    "executor": executor_name,
                    "max_parallel_stages": policy.max_parallel_stages,
                },
            )
        if bool(getattr(self.executor, "capture_stdout_stderr", False)):
            raise ParallelExecutionUnsupportedError(
                "local stdout/stderr capture is not safe with bounded parallel execution",
                code="pipeline.parallel.unsupported_executor_capture",
                context={
                    "executor": executor_name,
                    "max_parallel_stages": policy.max_parallel_stages,
                },
            )
        authority_store = self.services.authority_store
        if authority_store is None:
            diagnostic = StoreDiagnostic(
                code="missing_authority_backend",
                message="explicit parallel execution requires an authoritative backend",
                severity=DiagnosticSeverity.ERROR,
                detail={"required_backend": "PerRunAuthorityStore"},
            )
            raise ParallelExecutionUnsupportedError(
                "explicit parallel execution requires an authoritative backend",
                code="pipeline.parallel.unsupported_backend",
                context={"max_parallel_stages": policy.max_parallel_stages},
                diagnostics=(diagnostic.to_dict(),),
            )
        self._admit_authority_capabilities(
            (RequiredAuthorityCapability.BOUNDED_PARALLEL_STAGES,),
            feature="bounded local parallel execution",
            error_code="pipeline.parallel.unsupported_backend",
            context={"max_parallel_stages": policy.max_parallel_stages},
        )
        capability_set = authority_store.capabilities()
        diagnostics = capability_set.diagnostics_for(
            _REQUIRED_PARALLEL_CAPABILITIES,
            scope=CapabilityScope.PER_RUN,
        )
        if diagnostics:
            raise ParallelExecutionUnsupportedError(
                "backend does not support explicit bounded parallel execution",
                code="pipeline.parallel.unsupported_backend",
                context={
                    "backend_name": capability_set.backend_name,
                    "max_parallel_stages": policy.max_parallel_stages,
                },
                diagnostics=tuple(diagnostic.to_dict() for diagnostic in diagnostics),
            )

    def _admit_authority_capabilities(
        self,
        required: Sequence[RequiredAuthorityCapability],
        *,
        feature: str,
        error_code: str,
        context: Mapping[str, PlainData],
    ) -> None:
        authority_store = self.services.authority_store
        if authority_store is None:
            raise ParallelExecutionUnsupportedError(
                f"{feature} requires an authoritative backend",
                code=error_code,
                context=dict(context or {}),
            )
        config = self.services.authority_config
        from loom.pipeline.stores import AuthorityConfig

        if not isinstance(config, AuthorityConfig):
            config = AuthorityConfig()
        admission = admit_authority_capabilities(
            config=config,
            capabilities=authority_store.capabilities(),
            required=required,
        )
        if admission.supported:
            return
        raise ParallelExecutionUnsupportedError(
            f"authority backend does not support {feature}",
            code=error_code,
            context={
                **dict(context or {}),
                "backend_name": admission.backend_name,
                "required": [item.value for item in required],
            },
            diagnostics=tuple(error.to_dict() for error in admission.errors),
        )

    def _start_controller_lease_renewal(
        self, run_uri: str, token: str
    ) -> _ControllerLeaseRenewal | None:
        renew = getattr(self.run_store, "renew_run_lock", None)
        if not callable(renew):
            return None
        stop_event = Event()
        errors: list[BaseException] = []
        interval_seconds = max(
            0.001, float(self._controller_lease_renewal_interval_seconds)
        )

        def renew_until_released() -> None:
            while not stop_event.wait(interval_seconds):
                try:
                    renew(run_uri, token)
                except BaseException as exc:
                    errors.append(exc)
                    stop_event.set()
                    return

        renewal = _ControllerLeaseRenewal(
            stop_event=stop_event,
            thread=Thread(
                target=renew_until_released,
                name="loom-controller-lease",
                daemon=True,
            ),
            errors=errors,
        )
        self._controller_lease_renewal = renewal
        renewal.thread.start()
        return renewal

    def _stop_controller_lease_renewal(
        self, renewal: _ControllerLeaseRenewal | None
    ) -> None:
        if renewal is None:
            return
        renewal.stop_event.set()
        renewal.thread.join()
        if self._controller_lease_renewal is renewal:
            self._controller_lease_renewal = None

    def _raise_controller_lease_renewal_error(self) -> None:
        renewal = self._controller_lease_renewal
        if renewal is None or not renewal.errors:
            return
        error = renewal.errors[0]
        if isinstance(error, Exception):
            raise error
        raise PipelineExecutionError(
            f"controller lease renewal failed: {type(error).__name__}"
        ) from error

    def _recover_abandoned_run_if_needed(
        self,
        *,
        request: RunRequest,
        run_uri: str,
        prior_status: RunStatus,
    ) -> None:
        if not request.open_existing or prior_status not in {
            RunStatus.RUNNING,
            RunStatus.SUBMITTED,
        }:
            return
        authority_store = self.services.authority_store
        if authority_store is None:
            raise AuthorityStoreError("recovery requires an authoritative backend")
        snapshot = authority_store.snapshot(run_uri)
        recovery = authority_store.scan_recovery(run_uri)
        active_stages = tuple(
            stage
            for stage in snapshot.stages
            if stage.status in {StageStatus.RUNNING, StageStatus.SUBMITTED}
        )
        controller_recovered = any(record.stage_name is None for record in recovery)
        recovered_attempt_ids = {
            record.attempt_id for record in recovery if record.attempt_id is not None
        }
        if not controller_recovered or any(
            not stage.attempts
            or stage.attempts[-1].attempt_id not in recovered_attempt_ids
            for stage in active_stages
        ):
            raise AuthorityStoreError(
                "recovery requires expired controller and incomplete attempt evidence"
            )
        reason = LifecycleReason(code="recovered_after_authority_expiry")
        write_run_status(
            self.run_store,
            run_uri=run_uri,
            status=RunStatus.INTERRUPTED,
            created_at=self._created_at(run_uri, self.clock()),
            updated_at=self.clock(),
            intent=TransitionIntent.RECOVERY,
            metadata={"reason_code": reason.code},
        )
        self._emit_run_event(
            run_uri,
            "run.interrupted",
            timestamp=self.clock(),
            payload={"reason": reason.to_dict()},
        )
        write_stage_status_with_intent = getattr(
            self.run_store, "write_stage_status_with_intent", None
        )
        if not callable(write_stage_status_with_intent):
            raise AuthorityStoreError("recovery requires transition-aware stage state")
        for stage in active_stages:
            attempt = stage.attempts[-1].attempt
            write_stage_status_with_intent(
                run_uri,
                stage.stage_name,
                StageStatusRecord(
                    run_uri=run_uri,
                    stage_name=stage.stage_name,
                    status=StageStatus.STALE,
                    attempt=attempt,
                    updated_at=self.clock(),
                    message="recovered after controller lease expiry",
                    metadata={"reason_code": reason.code},
                ),
                intent=TransitionIntent.RECOVERY,
            )
            self._emit_stage_event(
                run_uri,
                stage.stage_name,
                "stage.stale",
                timestamp=self.clock(),
                payload={"attempt": attempt, "reason": reason.to_dict()},
            )

    def _run_locked(
        self,
        *,
        request: RunRequest,
        run_uri: str,
        run_dir: Path,
        local_run_store: LocalRunStorePaths,
        config_mapping: Mapping[str, PlainData],
        spec: PipelineSpec,
        options: RunOptions,
        started_at: str,
    ) -> RunResult:
        created_at = self._created_at(run_uri, started_at)
        prior_status = self._run_status_before_preparation(run_uri)
        try:
            options = _options_with_resolved_run_uri(options, run_uri)
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
            self._prepare_checksum_repair_branch(run_uri=run_uri, plan=plan)
        except Exception as exc:
            self._record_preparation_failure(
                run_uri=run_uri,
                created_at=created_at,
                prior_status=prior_status,
                exc=exc,
            )
            raise
        write_run_status(
            self.run_store,
            run_uri=run_uri,
            status=RunStatus.PLANNED,
            created_at=created_at,
            updated_at=self.clock(),
            started_at=started_at,
            metadata={"plan_summary": dict(plan.summary)},
            intent=(
                TransitionIntent.RESUME
                if prior_status is not RunStatus.CREATED
                else TransitionIntent.NORMAL
            ),
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

        parallel_policy = _parallel_policy_from_request(request, options)
        if parallel_policy.enabled:
            outcome = self._run_parallel_plan(
                _ParallelPlanContext(
                    request=request,
                    run_uri=run_uri,
                    run_dir=run_dir,
                    local_run_store=local_run_store,
                    config_mapping=config_mapping,
                    spec=spec,
                    resolved_runtime=resolved_runtime,
                    plan=plan,
                    artifact_store=artifact_store,
                    created_at=created_at,
                    run_started_at=started_at,
                    policy=parallel_policy,
                )
            )
        else:
            outcome = self._run_serial_plan(
                request=request,
                run_uri=run_uri,
                run_dir=run_dir,
                local_run_store=local_run_store,
                config_mapping=config_mapping,
                spec=spec,
                resolved_runtime=resolved_runtime,
                plan=plan,
                artifact_store=artifact_store,
                created_at=created_at,
                run_started_at=started_at,
            )

        self._raise_controller_lease_renewal_error()
        finished_at = self.clock()
        if outcome.failure is None and outcome.cancellation_reason is None:
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
        elif outcome.cancellation_reason is not None:
            write_cancelled_run(
                self.run_store,
                run_uri=run_uri,
                created_at=created_at,
                started_at=started_at,
                cancelled_at=finished_at,
                reason=outcome.cancellation_reason,
                stage_name=outcome.cancelled_stage,
            )
            self._emit_run_event(
                run_uri,
                "run.cancelled",
                timestamp=finished_at,
                payload={
                    "status": RunStatus.CANCELLED.value,
                    "cancelled_stage": outcome.cancelled_stage,
                    "reason": outcome.cancellation_reason.to_dict(),
                },
            )
            run_status = RunStatus.CANCELLED
            for stage_plan in plan.ordered_stage_plans:
                if stage_plan.stage_name not in outcome.stage_results:
                    outcome.stage_results[stage_plan.stage_name] = (
                        self._block_stage_after_failure(
                            run_uri=run_uri,
                            stage_plan=stage_plan,
                            blocked_by=outcome.cancelled_stage
                            or outcome.cancellation_reason.code,
                        )
                    )
        else:
            failure = outcome.failure
            if failure is None:
                raise PipelineExecutionError(
                    "execution failed without failure metadata"
                )
            self._write_failed_run(run_uri, created_at, started_at, failure)
            self._emit_run_event(
                run_uri,
                "run.failed",
                timestamp=self.clock(),
                payload={
                    "status": RunStatus.FAILED.value,
                    "failed_stage": outcome.failed_stage,
                    "failure_type": failure.failure_type,
                },
            )
            run_status = RunStatus.FAILED
            for stage_plan in plan.ordered_stage_plans:
                if stage_plan.stage_name not in outcome.stage_results:
                    outcome.stage_results[stage_plan.stage_name] = (
                        self._block_stage_after_failure(
                            run_uri=run_uri,
                            stage_plan=stage_plan,
                            blocked_by=outcome.failed_stage or failure.stage_name,
                        )
                    )
        artifact_index = self.run_store.read_artifact_index(run_uri)
        ordered_stage_results = {
            stage_plan.stage_name: outcome.stage_results[stage_plan.stage_name]
            for stage_plan in plan.ordered_stage_plans
        }
        result_metadata: dict[str, PlainData] = dict(request.metadata)
        if outcome.cancellation_reason is not None:
            result_metadata["reason"] = outcome.cancellation_reason.to_dict()
            result_metadata["reason_code"] = outcome.cancellation_reason.code
        event_dispatcher = self._event_dispatcher
        if event_dispatcher is not None and event_dispatcher.warnings:
            result_metadata["event_sink_warnings"] = [
                warning.to_dict() for warning in event_dispatcher.warnings
            ]
        result = RunResult(
            run_uri=run_uri,
            status=run_status,
            started_at=started_at,
            finished_at=finished_at,
            plan=plan,
            stage_results=ordered_stage_results,
            failed_stage=outcome.failed_stage,
            failure=outcome.failure,
            artifact_index=artifact_index,
            metadata=result_metadata,
        )
        self._write_offline_evidence_manifest_if_needed(run_uri)
        if outcome.interruption is not None:
            raise outcome.interruption
        return result

    def _run_serial_plan(
        self,
        *,
        request: RunRequest,
        run_uri: str,
        run_dir: Path,
        config_mapping: Mapping[str, PlainData],
        spec: PipelineSpec,
        resolved_runtime: Mapping[str, ResolvedStageRuntimeOptions],
        plan: ExecutionPlan,
        artifact_store: ArtifactStore,
        local_run_store: LocalRunStorePaths,
        created_at: str,
        run_started_at: str,
    ) -> _ExecutionOutcome:
        stage_results: dict[str, StageRunResult] = {}
        outputs_by_stage: dict[str, dict[str, ArtifactRef]] = {}
        failed_stage: str | None = None
        failure: ExecutionFailure | None = None
        cancelled_stage: str | None = None
        cancellation_reason: LifecycleReason | None = None
        for stage_plan in plan.ordered_stage_plans:
            stage = spec.get_stage(stage_plan.stage_name)
            if failed_stage is not None or cancelled_stage is not None:
                stage_results[stage.name] = self._block_stage_after_failure(
                    run_uri=run_uri,
                    stage_plan=stage_plan,
                    blocked_by=failed_stage or cancelled_stage or "cancelled",
                )
                continue
            try:
                result = self._run_controller_stage_action(
                    request=request,
                    run_uri=run_uri,
                    run_dir=run_dir,
                    local_run_store=local_run_store,
                    config_mapping=config_mapping,
                    spec=spec,
                    stage=stage,
                    stage_plan=stage_plan,
                    resolved_runtime=resolved_runtime[stage.name],
                    plan=plan,
                    artifact_store=artifact_store,
                    produced_outputs=outputs_by_stage,
                    created_at=created_at,
                    run_started_at=run_started_at,
                )
            except _StageInterrupted as interrupted:
                result = interrupted.result
                stage_results[stage.name] = result
                return _ExecutionOutcome(
                    stage_results=stage_results,
                    outputs_by_stage=outputs_by_stage,
                    failed_stage=failed_stage,
                    failure=failure,
                    cancelled_stage=interrupted.cancelled_stage,
                    cancellation_reason=_keyboard_interrupt_reason(),
                    interruption=interrupted.interruption,
                )
            stage_results[stage.name] = result
            if result.status == StageStatus.SUCCEEDED:
                outputs_by_stage[stage.name] = dict(result.outputs)
            elif result.status == StageStatus.CANCELLED:
                cancelled_stage = stage.name
                cancellation_reason = _stage_cancellation_reason(result)
            elif result.failure is not None:
                failed_stage = stage.name
                failure = result.failure
        return _ExecutionOutcome(
            stage_results=stage_results,
            outputs_by_stage=outputs_by_stage,
            failed_stage=failed_stage,
            failure=failure,
            cancelled_stage=cancelled_stage,
            cancellation_reason=cancellation_reason,
        )

    def _run_parallel_plan(self, context: _ParallelPlanContext) -> _ExecutionOutcome:
        plan_by_stage = {plan.stage_name: plan for plan in context.plan.stage_plans}
        stage_order = tuple(context.plan.stage_order)
        stage_results: dict[str, StageRunResult] = {}
        outputs_by_stage: dict[str, dict[str, ArtifactRef]] = {}
        submitted: set[str] = set()
        stopped = False
        failed_stage: str | None = None
        failure: ExecutionFailure | None = None
        cancelled_stage: str | None = None
        cancellation_reason: LifecycleReason | None = None
        interruption: KeyboardInterrupt | None = None
        active: dict[Future[StageRunResult], _ParallelTask] = {}
        with ThreadPoolExecutor(
            max_workers=context.policy.max_parallel_stages,
            thread_name_prefix="loom-stage",
        ) as pool:
            while len(stage_results) < len(stage_order):
                progressed = False
                if not stopped:
                    progressed = self._submit_parallel_ready_stages(
                        context,
                        pool=pool,
                        plan_by_stage=plan_by_stage,
                        stage_order=stage_order,
                        stage_results=stage_results,
                        outputs_by_stage=outputs_by_stage,
                        submitted=submitted,
                        active=active,
                    )
                    if failure is None:
                        failed_stage, failure = _first_stage_failure(stage_results)
                        if failure is not None and (
                            not context.policy.continue_independent
                            or _failure_requires_global_stop(failure)
                        ):
                            stopped = True
                    if cancellation_reason is None:
                        cancelled_stage, cancellation_reason = (
                            _first_stage_cancellation(stage_results)
                        )
                        if cancellation_reason is not None:
                            stopped = True
                if len(stage_results) >= len(stage_order):
                    break
                if not active:
                    if stopped:
                        break
                    blocked_stage = self._block_first_unresolved_stage(
                        context,
                        plan_by_stage=plan_by_stage,
                        stage_order=stage_order,
                        stage_results=stage_results,
                        submitted=submitted,
                        blocked_by=failed_stage,
                    )
                    if blocked_stage is None and not progressed:
                        raise PlanExecutionError(
                            "parallel scheduler made no progress; static plan is not executable"
                        )
                    continue
                try:
                    done, _pending = wait(active, return_when=FIRST_COMPLETED)
                except KeyboardInterrupt as exc:
                    interruption = exc
                    cancellation_reason = _keyboard_interrupt_reason()
                    stopped = True
                    continue
                for future in done:
                    task = active.pop(future)
                    try:
                        result = future.result()
                    except _StageInterrupted as exc:
                        result = exc.result
                        interruption = exc.interruption
                        cancelled_stage = exc.cancelled_stage
                        cancellation_reason = _keyboard_interrupt_reason()
                        stopped = True
                    stage_results[task.stage_name] = result
                    if result.status == StageStatus.SUCCEEDED:
                        outputs_by_stage[task.stage_name] = dict(result.outputs)
                        continue
                    if (
                        result.status == StageStatus.CANCELLED
                        and cancellation_reason is None
                    ):
                        cancelled_stage = task.stage_name
                        cancellation_reason = _stage_cancellation_reason(result)
                        stopped = True
                        continue
                    if result.failure is not None and failure is None:
                        failed_stage = task.stage_name
                        failure = result.failure
                        if (
                            not context.policy.continue_independent
                            or _failure_requires_global_stop(failure)
                        ):
                            stopped = True
                if (
                    failure is not None
                    and context.policy.continue_independent
                    and not stopped
                ):
                    self._block_failed_downstream_ready_stages(
                        context,
                        plan_by_stage=plan_by_stage,
                        stage_order=stage_order,
                        stage_results=stage_results,
                        submitted=submitted,
                        failed_stage=failed_stage or failure.stage_name,
                    )
            if stopped:
                wait(active)
                for future, task in list(active.items()):
                    try:
                        result = future.result()
                    except _StageInterrupted as exc:
                        result = exc.result
                        interruption = interruption or exc.interruption
                        if cancellation_reason is None:
                            cancelled_stage = exc.cancelled_stage
                            cancellation_reason = _keyboard_interrupt_reason()
                    stage_results[task.stage_name] = result
                    if result.status == StageStatus.SUCCEEDED:
                        outputs_by_stage[task.stage_name] = dict(result.outputs)
                    elif (
                        result.status == StageStatus.CANCELLED
                        and cancellation_reason is None
                    ):
                        cancelled_stage = task.stage_name
                        cancellation_reason = _stage_cancellation_reason(result)
                    elif result.failure is not None and failure is None:
                        failed_stage = task.stage_name
                        failure = result.failure
                    active.pop(future, None)
        if failure is not None or cancellation_reason is not None:
            for stage_name in stage_order:
                if stage_name not in stage_results:
                    stage_results[stage_name] = self._block_stage_after_failure(
                        run_uri=context.run_uri,
                        stage_plan=plan_by_stage[stage_name],
                        blocked_by=failed_stage
                        or cancelled_stage
                        or (failure.stage_name if failure is not None else "cancelled"),
                    )
        return _ExecutionOutcome(
            stage_results=stage_results,
            outputs_by_stage=outputs_by_stage,
            failed_stage=failed_stage,
            failure=failure,
            cancelled_stage=cancelled_stage,
            cancellation_reason=cancellation_reason,
            interruption=interruption,
        )

    def _run_controller_stage_action(
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
        local_run_store: LocalRunStorePaths,
        produced_outputs: Mapping[str, Mapping[str, ArtifactRef]],
        created_at: str,
        run_started_at: str,
    ) -> StageRunResult:
        self._raise_controller_lease_renewal_error()
        if stage_plan.action == PlanAction.REUSE:
            return self._reuse_stage(
                run_uri, stage_plan, created_at=created_at, started_at=run_started_at
            )
        if stage_plan.action == PlanAction.SKIP:
            return self._skip_stage(
                run_uri,
                stage_plan,
                created_at=created_at,
                started_at=run_started_at,
            )
        if stage_plan.action == PlanAction.BLOCKED:
            failure = self._plan_failure(
                run_uri, stage, stage_plan.action, stage_plan.reasons
            )
            return self._block_plan_stage(
                run_uri=run_uri,
                stage_plan=stage_plan,
                failure=failure,
            )
        if stage_plan.action == PlanAction.STALE:
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
                run_started_at=run_started_at,
                failure=failure,
            )
            return StageRunResult(
                stage_name=stage.name,
                action=PlanAction.BLOCKED,
                status=StageStatus.FAILED,
                attempt=attempt,
                outputs={},
                failure=failure,
                reasons=stage_plan.reasons,
                finished_at=failure.failed_at,
            )
        return self._run_stage_with_retries(
            request=request,
            run_uri=run_uri,
            run_dir=run_dir,
            local_run_store=local_run_store,
            config_mapping=config_mapping,
            spec=spec,
            stage=stage,
            stage_plan=stage_plan,
            resolved_runtime=resolved_runtime,
            plan=plan,
            artifact_store=artifact_store,
            produced_outputs=produced_outputs,
            created_at=created_at,
            run_started_at=run_started_at,
        )

    def _run_stage_with_retries(
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
        local_run_store: LocalRunStorePaths,
        produced_outputs: Mapping[str, Mapping[str, ArtifactRef]],
        created_at: str,
        run_started_at: str,
    ) -> StageRunResult:
        retry_policy = _retry_policy_from_runtime(resolved_runtime)
        while True:
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
                resolved_runtime=resolved_runtime,
                plan=plan,
                artifact_store=artifact_store,
                produced_outputs=produced_outputs,
                created_at=created_at,
                run_started_at=run_started_at,
            )
            if result.status not in {StageStatus.FAILED, StageStatus.CANCELLED}:
                return result
            if result.attempt is None:
                return result
            stage_status = cast(StageStatus, result.status)
            decision = record_retry_decision_for_stage_result(
                self.run_store,
                run_uri=run_uri,
                stage_name=stage.name,
                attempt=result.attempt,
                stage_status=stage_status,
                recorded_at=result.finished_at or self.clock(),
                policy=retry_policy,
                failure=result.failure,
            )
            if (
                decision is None
                or not decision.should_retry
                or decision.next_attempt is None
                or decision.next_attempt <= result.attempt
            ):
                return result

    def _submit_parallel_ready_stages(
        self,
        context: _ParallelPlanContext,
        *,
        pool: ThreadPoolExecutor,
        plan_by_stage: Mapping[str, StagePlan],
        stage_order: Sequence[str],
        stage_results: dict[str, StageRunResult],
        outputs_by_stage: dict[str, dict[str, ArtifactRef]],
        submitted: set[str],
        active: dict[Future[StageRunResult], _ParallelTask],
    ) -> bool:
        progressed = False
        while len(active) < context.policy.max_parallel_stages:
            ready = self._next_ready_stage(
                plan_by_stage=plan_by_stage,
                stage_order=stage_order,
                stage_results=stage_results,
                submitted=submitted,
            )
            if ready is None:
                return progressed
            stage_name = ready.stage_name
            submitted.add(stage_name)
            stage = context.spec.get_stage(stage_name)
            produced_outputs = {
                upstream: dict(outputs)
                for upstream, outputs in outputs_by_stage.items()
            }
            if ready.action != PlanAction.RUN:
                result = self._run_controller_stage_action(
                    request=context.request,
                    run_uri=context.run_uri,
                    run_dir=context.run_dir,
                    local_run_store=context.local_run_store,
                    config_mapping=context.config_mapping,
                    spec=context.spec,
                    stage=stage,
                    stage_plan=ready,
                    resolved_runtime=context.resolved_runtime[stage_name],
                    plan=context.plan,
                    artifact_store=context.artifact_store,
                    produced_outputs=produced_outputs,
                    created_at=context.created_at,
                    run_started_at=context.run_started_at,
                )
                stage_results[stage_name] = result
                if result.status == StageStatus.SUCCEEDED:
                    outputs_by_stage[stage_name] = dict(result.outputs)
                progressed = True
                if result.status == StageStatus.CANCELLED:
                    return progressed
                if result.failure is not None and (
                    not context.policy.continue_independent
                    or _failure_requires_global_stop(result.failure)
                ):
                    return progressed
                continue
            upstream_blocker = _first_non_successful_upstream(ready, stage_results)
            if upstream_blocker is not None:
                stage_results[stage_name] = self._block_stage_after_failure(
                    run_uri=context.run_uri,
                    stage_plan=ready,
                    blocked_by=upstream_blocker,
                )
                progressed = True
                continue
            future = pool.submit(
                self._run_controller_stage_action,
                request=context.request,
                run_uri=context.run_uri,
                run_dir=context.run_dir,
                local_run_store=context.local_run_store,
                config_mapping=context.config_mapping,
                spec=context.spec,
                stage=stage,
                stage_plan=ready,
                resolved_runtime=context.resolved_runtime[stage_name],
                plan=context.plan,
                artifact_store=context.artifact_store,
                produced_outputs=produced_outputs,
                created_at=context.created_at,
                run_started_at=context.run_started_at,
            )
            active[future] = _ParallelTask(stage_name=stage_name)
            progressed = True
        return progressed

    def _next_ready_stage(
        self,
        *,
        plan_by_stage: Mapping[str, StagePlan],
        stage_order: Sequence[str],
        stage_results: Mapping[str, StageRunResult],
        submitted: set[str],
    ):
        for stage_name in stage_order:
            if stage_name in submitted or stage_name in stage_results:
                continue
            stage_plan = plan_by_stage[stage_name]
            if all(
                upstream in stage_results for upstream in stage_plan.upstream_stages
            ):
                return stage_plan
        return None

    def _block_first_unresolved_stage(
        self,
        context: _ParallelPlanContext,
        *,
        plan_by_stage: Mapping[str, StagePlan],
        stage_order: Sequence[str],
        stage_results: dict[str, StageRunResult],
        submitted: set[str],
        blocked_by: str | None,
    ) -> str | None:
        for stage_name in stage_order:
            if stage_name in stage_results or stage_name in submitted:
                continue
            stage_plan = plan_by_stage[stage_name]
            if blocked_by is None:
                blocker = _first_completed_upstream(stage_plan, stage_results)
                if blocker is None:
                    continue
            else:
                blocker = blocked_by
            stage_results[stage_name] = self._block_stage_after_failure(
                run_uri=context.run_uri,
                stage_plan=stage_plan,
                blocked_by=blocker,
            )
            submitted.add(stage_name)
            return stage_name
        return None

    def _block_failed_downstream_ready_stages(
        self,
        context: _ParallelPlanContext,
        *,
        plan_by_stage: Mapping[str, StagePlan],
        stage_order: Sequence[str],
        stage_results: dict[str, StageRunResult],
        submitted: set[str],
        failed_stage: str,
    ) -> None:
        changed = True
        while changed:
            changed = False
            for stage_name in stage_order:
                if stage_name in stage_results or stage_name in submitted:
                    continue
                stage_plan = plan_by_stage[stage_name]
                if not all(
                    upstream in stage_results for upstream in stage_plan.upstream_stages
                ):
                    continue
                blocker = _first_non_successful_upstream(stage_plan, stage_results)
                if blocker is None:
                    continue
                stage_results[stage_name] = self._block_stage_after_failure(
                    run_uri=context.run_uri,
                    stage_plan=stage_plan,
                    blocked_by=blocker or failed_stage,
                )
                submitted.add(stage_name)
                changed = True

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
        self._authorize_checksum_repair_attempt(
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            plan=plan,
        )
        record_resolved_reliability_policy_fact(
            self.run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            resolved_runtime=resolved_runtime,
            recorded_at=self.clock(),
        )
        stage_started_at: str | None = None
        local_run_store = self._require_local_run_store()
        resource_admission: ResourceAdmissionDecision | None = None
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
            resource_admission = self._acquire_stage_resource_admission(
                run_uri=run_uri,
                stage_name=stage.name,
                resolved_runtime=resolved_runtime,
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
            execution_result = self._execute_stage_request_with_lease_renewal(
                run_uri=run_uri,
                stage_name=stage.name,
                attempt=attempt,
                request=exec_request,
            )
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
        except KeyboardInterrupt as exc:
            raise self._interrupted_stage_result(
                run_uri=run_uri,
                stage=stage,
                stage_plan=stage_plan,
                attempt=attempt,
                started_at=stage_started_at,
                interruption=exc,
            ) from exc
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
        finally:
            if resource_admission is not None:
                self._release_stage_resource_admission(resource_admission)

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
        resource_admission: ResourceAdmissionDecision | None = None
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
            self._authorize_checksum_repair_attempt(
                run_uri=run_uri,
                stage_name=stage.name,
                attempt=attempt,
                plan=plan,
            )
            record_resolved_reliability_policy_fact(
                self.run_store,
                run_uri=run_uri,
                stage_name=stage.name,
                attempt=attempt,
                resolved_runtime=resolved_runtime,
                recorded_at=self.clock(),
            )
            inputs = prepared.inputs
            fingerprint = cast(StageFingerprintRecord, prepared.fingerprint)
            resource_admission = self._acquire_stage_resource_admission(
                run_uri=run_uri,
                stage_name=stage.name,
                resolved_runtime=resolved_runtime,
            )
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
                worker_authority_cli_args=_worker_authority_cli_args(self.services),
            )
            execution_result = self._execute_stage_request_with_lease_renewal(
                run_uri=run_uri,
                stage_name=stage.name,
                attempt=attempt,
                request=exec_request,
            )
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
        except KeyboardInterrupt as exc:
            raise self._interrupted_stage_result(
                run_uri=run_uri,
                stage=stage,
                stage_plan=stage_plan,
                attempt=attempt,
                started_at=stage_started_at,
                interruption=exc,
            ) from exc
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
        finally:
            if resource_admission is not None:
                self._release_stage_resource_admission(resource_admission)

    def _prepare_checksum_repair_branch(
        self, *, run_uri: str, plan: ExecutionPlan
    ) -> None:
        prepare = getattr(self.run_store, "prepare_checksum_repair", None)
        if not callable(prepare):
            return
        repair_stages = _checksum_repair_stage_names(plan)
        for stage_plan in plan.ordered_stage_plans:
            stage_name = stage_plan.stage_name
            if (
                stage_name not in repair_stages
                or stage_plan.action is not PlanAction.RUN
            ):
                continue
            if self.run_store.read_stage_outputs(run_uri, stage_name) is None:
                continue
            prepare(run_uri, stage_name)

    def _authorize_checksum_repair_attempt(
        self,
        *,
        run_uri: str,
        stage_name: str,
        attempt: int,
        plan: ExecutionPlan,
    ) -> None:
        if stage_name not in _checksum_repair_stage_names(plan):
            return
        if self.run_store.read_stage_outputs(run_uri, stage_name) is None:
            return
        authorize = getattr(self.run_store, "authorize_checksum_repair_output", None)
        if callable(authorize):
            authorize(run_uri, stage_name, attempt=attempt)

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
        self._raise_controller_lease_renewal_error()
        result = commit_stage_execution_result(
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
            event_dispatcher=self._event_dispatcher,
            finalize_run_on_failure=False,
        )
        self._raise_controller_lease_renewal_error()
        return result

    def _execute_stage_request_with_lease_renewal(
        self,
        *,
        run_uri: str,
        stage_name: str,
        attempt: int,
        request: StageExecutionRequest,
    ) -> StageExecutionResult:
        renew_stage_attempt_lease = getattr(
            self.services.stage_state,
            "renew_stage_attempt_lease",
            None,
        )
        if not callable(renew_stage_attempt_lease):
            return self.executor.execute(request)
        renew = cast(
            Callable[[str, str, int], None],
            renew_stage_attempt_lease,
        )
        stop_event = Event()
        renewal_errors: list[BaseException] = []
        interval_seconds = max(
            0.001,
            float(self._stage_lease_renewal_interval_seconds),
        )

        def renew_until_finished() -> None:
            while not stop_event.wait(interval_seconds):
                try:
                    renew(run_uri, stage_name, attempt)
                except BaseException as exc:
                    renewal_errors.append(exc)
                    stop_event.set()
                    return

        renewal_thread = Thread(
            target=renew_until_finished,
            name=f"loom-stage-lease-{stage_name}",
            daemon=True,
        )
        renewal_thread.start()
        try:
            execution_result = self.executor.execute(request)
        finally:
            stop_event.set()
            renewal_thread.join()
        if renewal_errors:
            error = renewal_errors[0]
            if isinstance(error, Exception):
                raise error
            raise PipelineExecutionError(
                f"stage lease renewal failed: {type(error).__name__}"
            ) from error
        return execution_result

    def _acquire_stage_resource_admission(
        self,
        *,
        run_uri: str,
        stage_name: str,
        resolved_runtime: ResolvedStageRuntimeOptions,
    ) -> ResourceAdmissionDecision | None:
        resources = resource_requests_from_runtime(
            cast("ResourceRequest", resolved_runtime.resources)
        )
        if not resources:
            return None
        coordination_store = self.services.coordination_store
        if coordination_store is None:
            return None
        workspace_id = self.services.workspace_id
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ResourceAdmissionError(
                "resource admission requires an authority workspace_id",
                code="resource_admission.missing_workspace",
                context={"run_uri": run_uri, "stage_name": stage_name},
            )
        owner_id = self.services.owner_id or "serial-controller"
        execution = cast(ExecutionOptions, resolved_runtime.execution)
        settings = execution.settings
        request = ResourceAdmissionRequest(
            run_uri=run_uri,
            stage_name=stage_name,
            workspace_id=workspace_id,
            owner_id=f"{owner_id}:{stage_name}",
            resources=resources,
            lease_ttl_seconds=_resource_lease_ttl_seconds(settings),
            wait_timeout_seconds=_resource_wait_timeout_seconds(settings),
            poll_interval_seconds=_resource_poll_interval_seconds(settings),
        )
        decision = acquire_resource_admission(coordination_store, request)
        if decision.admitted:
            return decision
        raise ResourceAdmissionError(
            decision.message or "resource capacity is unavailable",
            code="resource_admission.blocked"
            if decision.status is ResourceAdmissionStatus.BLOCKED
            else "resource_admission.rejected",
            context=decision.to_dict(),
        )

    def _release_stage_resource_admission(
        self, decision: ResourceAdmissionDecision
    ) -> None:
        coordination_store = self.services.coordination_store
        if coordination_store is None:
            return
        try:
            release_resource_admission(
                coordination_store,
                decision,
                reason=LifecycleReason(
                    code="resource_admission_released",
                    message=(
                        "released resource admission leases for stage "
                        f"{decision.request.stage_name}"
                    ),
                ),
            )
        except Exception:
            # The stage terminal state is already recorded; stale release failures
            # fall back to the coordination store's lease expiry recovery.
            return

    def _require_local_run_store(self) -> LocalRunStorePaths:
        if isinstance(self.run_store, OfflineEvidenceRunStore):
            return self.run_store.local_store
        return self.services.local_paths

    def _write_offline_evidence_manifest_if_needed(self, run_uri: str) -> None:
        if not is_offline_evidence_run_store(self.run_store):
            return
        local_store = self._require_local_run_store()
        if not isinstance(local_store, LocalRunStore):
            raise PipelineExecutionError(
                "offline evidence writing requires a LocalRunStore-backed adapter"
            )
        write_offline_evidence_manifest(
            local_store,
            run_uri,
            generated_at=self.clock(),
        )

    def _resolve_request_run_uri(
        self,
        request: RunRequest,
        local_run_store: LocalRunStorePaths,
        *,
        options: RunOptions,
    ) -> str:
        run_uri = options.run_uri
        if run_uri is None:
            if request.open_existing:
                raise RunRequestError("RunRequest.open_existing requires run_uri")
            return local_run_store.allocate_run_uri()
        return local_run_store.resolve_run_uri(run_uri)

    def _create_or_open_run(self, run_uri: str, request: RunRequest) -> None:
        if request.open_existing:
            self.run_store.open_run(run_uri)
        else:
            self.run_store.create_run(
                run_uri,
                metadata=request.metadata,
                idempotency_key=request.idempotency_key,
            )

    def _run_status_before_preparation(self, run_uri: str) -> RunStatus:
        snapshot = self.run_store.open_run(run_uri)
        status = getattr(snapshot, "status", None)
        if isinstance(status, RunStatus):
            return status
        local_status = self.run_store.read_run_status(run_uri)
        return RunStatus.CREATED if local_status is None else local_status.status

    def _record_preparation_failure(
        self,
        *,
        run_uri: str,
        created_at: str,
        prior_status: RunStatus,
        exc: Exception,
    ) -> None:
        failed_at = self.clock()
        try:
            self._emit_run_event(
                run_uri,
                "run.preparation_failed",
                timestamp=failed_at,
                payload={
                    "prior_status": prior_status.value,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
        except Exception:
            # Failure recording must never hide the preparation error.
            pass
        if prior_status is RunStatus.CREATED:
            write_run_status(
                self.run_store,
                run_uri=run_uri,
                status=RunStatus.FAILED,
                created_at=created_at,
                updated_at=failed_at,
                finished_at=failed_at,
                metadata={
                    "failure_phase": "preparation",
                    "error_type": type(exc).__name__,
                },
            )

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
            event_dispatcher=self._event_dispatcher,
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
            event_dispatcher=self._event_dispatcher,
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
            event_dispatcher=self._event_dispatcher,
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
            event_dispatcher=self._event_dispatcher,
            finalize_run=False,
        )

    def _interrupted_stage_result(
        self,
        *,
        run_uri: str,
        stage: StageSpec,
        stage_plan: StagePlan,
        attempt: int,
        started_at: str | None,
        interruption: KeyboardInterrupt,
    ) -> _StageInterrupted:
        committed = self.run_store.read_stage_status(run_uri, stage.name)
        if committed is not None and committed.status is StageStatus.SUCCEEDED:
            outputs = self.run_store.read_stage_outputs(run_uri, stage.name)
            if outputs is None:
                raise PipelineExecutionError(
                    "committed successful stage is missing durable outputs"
                ) from interruption
            return _StageInterrupted(
                StageRunResult(
                    stage_name=stage.name,
                    action=PlanAction.RUN,
                    status=StageStatus.SUCCEEDED,
                    attempt=attempt,
                    outputs=outputs,
                    reasons=stage_plan.reasons,
                    started_at=committed.started_at,
                    finished_at=committed.finished_at,
                ),
                interruption,
                cancelled_stage=None,
            )
        cancelled_at = self.clock()
        reason = _keyboard_interrupt_reason()
        persist_stage_cancellation(
            self.run_store,
            run_uri=run_uri,
            stage_name=stage.name,
            attempt=attempt,
            started_at=started_at,
            cancelled_at=cancelled_at,
            reason=reason,
            clock=self.clock,
            event_dispatcher=self._event_dispatcher,
        )
        return _StageInterrupted(
            StageRunResult(
                stage_name=stage.name,
                action=PlanAction.RUN,
                status=StageStatus.CANCELLED,
                attempt=attempt,
                outputs={},
                reasons=stage_plan.reasons,
                started_at=started_at,
                finished_at=cancelled_at,
                executor_metadata={"lifecycle_reason": reason.to_dict()},
            ),
            interruption,
            cancelled_stage=stage.name,
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
        exc: BaseException,
    ) -> ExecutionFailure:
        return self._failure(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            failure_type=failure_type,
            message=str(exc) or type(exc).__name__,
            executor=str(getattr(self.executor, "name", "unknown")),
            exception_type=f"{type(exc).__module__}.{type(exc).__name__}",
            details=exc.to_dict() if isinstance(exc, ResourceAdmissionError) else None,
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


def _merged_request_options(
    request: RunRequest,
    *,
    config_mapping: Mapping[str, PlainData],
    stage_names: Sequence[str],
) -> RunOptions:
    return merge_config_run_options(
        config_mapping,
        explicit=_sparse_request_options(parse_run_options(request.options)),
        known_stage_ids=stage_names,
    )


def _sparse_request_options(options: RunOptions) -> Mapping[str, object]:
    default_options = RunOptions()
    default_data = default_options.to_dict()
    return {
        key: value
        for key, value in options.to_dict().items()
        if key != "schema_version" and value != default_data.get(key)
    }


def _parallel_policy_from_request(
    request: RunRequest,
    options: RunOptions,
) -> ParallelExecutionOptions:
    policy = parallel_execution_options(options)
    if (
        policy.failure_policy == "stop_on_first_failure"
        and not request.failure_policy.stop_on_first_failure
    ):
        return ParallelExecutionOptions(
            max_parallel_stages=policy.max_parallel_stages,
            failure_policy="continue_independent",
        )
    return policy


def _event_dispatcher_from_request(
    request: RunRequest,
) -> RuntimeEventDispatcher | None:
    registry = request.event_sink_registry
    if registry is None and request.event_persistence == "durable":
        return None
    return RuntimeEventDispatcher(
        registry=registry,
        persistence=cast("EventPersistenceMode", request.event_persistence),
    )


def run_pipeline(
    request: RunRequest,
    *,
    run_store: RunnerRunStore,
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


def _first_non_successful_upstream(
    stage_plan: StagePlan,
    stage_results: Mapping[str, StageRunResult],
) -> str | None:
    for upstream in stage_plan.upstream_stages:
        result = stage_results.get(upstream)
        if result is not None and result.status is not StageStatus.SUCCEEDED:
            return upstream
    return None


def _first_completed_upstream(
    stage_plan: StagePlan,
    stage_results: Mapping[str, StageRunResult],
) -> str | None:
    for upstream in stage_plan.upstream_stages:
        if upstream in stage_results:
            return upstream
    return None


def _first_stage_failure(
    stage_results: Mapping[str, StageRunResult],
) -> tuple[str | None, ExecutionFailure | None]:
    for stage_name, result in stage_results.items():
        if result.failure is not None:
            return stage_name, result.failure
    return None, None


def _first_stage_cancellation(
    stage_results: Mapping[str, StageRunResult],
) -> tuple[str | None, LifecycleReason | None]:
    for stage_name, result in stage_results.items():
        if result.status == StageStatus.CANCELLED:
            return stage_name, _stage_cancellation_reason(result)
    return None, None


def _stage_cancellation_reason(result: StageRunResult) -> LifecycleReason:
    raw = result.executor_metadata.get("lifecycle_reason")
    if isinstance(raw, Mapping):
        try:
            return LifecycleReason.from_dict(raw)
        except Exception:
            pass
    return LifecycleReason(
        code="early_stop",
        message="stage requested early stop",
    )


def _keyboard_interrupt_reason() -> LifecycleReason:
    return LifecycleReason(
        code="keyboard_interrupt",
        message="execution interrupted by keyboard interrupt",
    )


def _retry_policy_from_runtime(
    resolved_runtime: ResolvedStageRuntimeOptions,
) -> RetryPolicy | None:
    policy = resolved_runtime.reliability
    if not isinstance(policy, ReliabilityPolicy):
        return None
    retry = policy.retry
    if not isinstance(retry, RetryPolicy):
        return None
    return retry


def _resource_lease_ttl_seconds(settings: Mapping[str, PlainData]) -> int:
    value = settings.get(
        "resource_lease_ttl_seconds", DEFAULT_RESOURCE_LEASE_TTL_SECONDS
    )
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResourceAdmissionError(
            "resource_lease_ttl_seconds must be a positive integer",
            code="resource_admission.invalid_settings",
        )
    return value


def _resource_wait_timeout_seconds(settings: Mapping[str, PlainData]) -> float:
    value = settings.get("resource_admission_timeout_seconds", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ResourceAdmissionError(
            "resource_admission_timeout_seconds must be non-negative",
            code="resource_admission.invalid_settings",
        )
    return float(value)


def _resource_poll_interval_seconds(settings: Mapping[str, PlainData]) -> float:
    value = settings.get("resource_admission_poll_seconds", 1.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ResourceAdmissionError(
            "resource_admission_poll_seconds must be positive",
            code="resource_admission.invalid_settings",
        )
    return float(value)


def _failure_type_for_exception(exc: BaseException) -> str:
    if isinstance(exc, ResourceAdmissionError):
        return "resource_admission"
    if isinstance(exc, OutputValidationError):
        return "output_validation"
    if isinstance(exc, _TargetConstructionError):
        return "target_construction"
    if isinstance(exc, StageContractError):
        return "stage_contract"
    if isinstance(exc, PlanExecutionError):
        return "plan_execution"
    if isinstance(exc, (StoreError, ArtifactStoreError, AuthorityStoreError)):
        return "store_commit"
    return "executor_infrastructure"


def _failure_requires_global_stop(failure: ExecutionFailure) -> bool:
    if failure.failure_type != "store_commit":
        return False
    exception_type = failure.exception_type or ""
    return exception_type.rsplit(".", 1)[-1].startswith("Authority")


def _checksum_repair_stage_names(plan: ExecutionPlan) -> frozenset[str]:
    repair_stages: set[str] = set()
    for stage_plan in plan.ordered_stage_plans:
        if not any(
            reason.code is PlanReasonCode.ARTIFACT_CHECKSUM_MISMATCH
            for reason in stage_plan.reasons
        ):
            continue
        repair_stages.add(stage_plan.stage_name)
        repair_stages.update(stage_plan.downstream_stages)
    return frozenset(repair_stages)


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


def _worker_authority_cli_args(services: RuntimeServices) -> tuple[str, ...]:
    """Return launch-only authority facts without changing worker payloads."""

    if services.authority_config is None:
        return ()
    return tuple(authority_config_to_cli_args(services.authority_config))


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
