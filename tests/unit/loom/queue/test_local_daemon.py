"""Unit coverage for local-daemon control ownership."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from shutil import copyfile
import sqlite3
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest

import loom.queue.local_daemon_execution as local_daemon_execution
from loom.queue import (
    AgentControl,
    CoordinatorSchedulingReload,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonSchedulingComponents,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketClient,
    LocalDaemonSocketServer,
    ManagedRecoveryTarget,
    RecoverUnknownAssignment,
    QueueConflictError,
    QueueServiceError,
    QueueStorageError,
    ResidentWorkerLaunchProfile,
)
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.agent_sessions import (
    AgentControlKind,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    TransportPrincipalPolicy,
)
from loom.pipeline.orchestration import (
    SchedulingProjectionState,
    StageWorkRecord,
    stage_work_identity,
)
from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.ready_stage import (
    SlurmJobPrivateFileProvider,
    SlurmReadyStageProfile,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import CpuResourcePlanner, ExecutionRouteKind
from loom.pipeline.runtime.placement import (
    StagePlacementPolicy,
    resolve_stage_placement,
)
from loom.pipeline.runtime.scheduling_preferences import OrderedAgentPreferenceScorer
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import PreparedAttemptRequest, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.scheduling import (
    FifoSchedulingPolicy,
    ResourceClaimContractDescriptor,
    TargetConstraintEvaluator,
)


class _CpuPlannerV2(CpuResourcePlanner):
    descriptor = replace(
        CpuResourcePlanner.descriptor,
        implementation_version="2",
        implementation_fingerprint="test:cpu:v2",
    )


class _IncompatibleCpuPlanner(CpuResourcePlanner):
    descriptor = replace(
        CpuResourcePlanner.descriptor,
        implementation_version="incompatible",
        implementation_fingerprint="test:cpu:incompatible",
    )
    claim_contracts = (ResourceClaimContractDescriptor("cpu", 2, "test-cpu-claim-v2"),)


def test_recovery_request_round_trips_complete_immutable_identity() -> None:
    request = RecoverUnknownAssignment(
        recovery_id="recovery-1",
        run_uri="file:///run",
        stage_name="train",
        attempt=2,
        stage_work_id="work-1",
        assignment_id="assignment-1",
        process_execution_id="process-1",
        execution_fence="fence-1",
        target=ManagedRecoveryTarget("agent-1", "session-1"),
        expected_state_version=7,
        requested_outcome="failed",
        consider_retry=True,
        reason="contained",
    )
    assert RecoverUnknownAssignment.from_dict(request.to_dict()) == request
    payload = request.to_dict()
    payload["run_uri"] = "file:///other"
    assert RecoverUnknownAssignment.from_dict(payload).run_uri == "file:///other"


def test_recovery_persists_exact_evidence_before_close_and_replays_it(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config = replace(
        config,
        agent_policy=AgentPolicyConfig(
            principals=(
                TransportPrincipalPolicy(
                    "operator-credential",
                    f"uid:{os.getuid()}",
                    "operator",
                    actions=("recover_unknown",),
                ),
            )
        ),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    request = RecoverUnknownAssignment(
        recovery_id="recovery-crash-1",
        run_uri="file:///run",
        stage_name="train",
        attempt=1,
        stage_work_id="work-1",
        assignment_id="assignment-1",
        process_execution_id="process-1",
        execution_fence="fence-1",
        target=ManagedRecoveryTarget("agent-1", "session-1"),
        expected_state_version=7,
        requested_outcome="failed",
        consider_retry=True,
        reason="target owner contained the process",
    )
    evidence: dict[str, object] = {
        "kind": "test-contained",
        "state": "CONTAINED",
        "receipt": "receipt-1",
    }

    class _CrashOnceExecution:
        def __init__(self) -> None:
            self.resolve_calls = 0
            self.close_calls = 0

        def recovery_has_ordinary_winner(self, _request: object) -> bool:
            return False

        def validate_recovery_admission(self, _request: object) -> None:
            return None

        def recovery_target_is_still_unknown(self, _request: object) -> bool:
            return True

        def resolve_recovery_evidence(
            self, _request: object
        ) -> tuple[str, dict[str, object]]:
            self.resolve_calls += 1
            return "contained", evidence

        def close_recovered_assignment(
            self, _request: object, persisted: object, *, recorded_at: str
        ) -> dict[str, object]:
            assert persisted == evidence
            assert recorded_at
            self.close_calls += 1
            if self.close_calls == 1:
                raise QueueServiceError("injected crash after evidence commit")
            return {
                "recovery_id": request.recovery_id,
                "state": "closed",
                "evidence": evidence,
                "revision": 8,
            }

    execution = _CrashOnceExecution()
    daemon._execution = cast(Any, execution)
    with pytest.raises(QueueServiceError, match="not authorized"):
        daemon.operator_view(
            LocalDaemonPrincipal("intruder", LocalDaemonRole.OPERATOR)
        ).recover_unknown(request)
    with sqlite3.connect(config.control_database) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM recovery_operations").fetchone()[0] == 0
        )
    operator = daemon.operator_view(
        LocalDaemonPrincipal(f"uid:{os.getuid()}", LocalDaemonRole.OPERATOR)
    )

    with pytest.raises(QueueServiceError, match="injected crash"):
        operator.recover_unknown(request)
    with sqlite3.connect(config.control_database) as conn:
        state, persisted = conn.execute(
            "SELECT state, evidence_json FROM recovery_operations "
            "WHERE recovery_id = ?",
            (request.recovery_id,),
        ).fetchone()
    assert state == "evidence_confirmed"
    assert persisted is not None

    replacement = LocalDaemon(config)
    replacement._execution = cast(Any, execution)
    replacement._resume_pending_recoveries(cast(Any, execution))
    replacement_operator = replacement.operator_view(
        LocalDaemonPrincipal(f"uid:{os.getuid()}", LocalDaemonRole.OPERATOR)
    )
    server = LocalDaemonSocketServer(replacement, config.endpoint)
    server.start()
    try:
        result = LocalDaemonSocketClient(config.endpoint).recover_unknown(request)
    finally:
        server.stop()

    assert result["state"] == "closed"
    assert execution.resolve_calls == 1
    assert execution.close_calls == 2
    with pytest.raises(QueueConflictError, match="operation conflicts"):
        replacement_operator.recover_unknown(replace(request, reason="changed replay"))


class _TargetEvaluatorV2(TargetConstraintEvaluator):
    descriptor = replace(
        TargetConstraintEvaluator.descriptor,
        implementation_version="2",
        implementation_fingerprint="test:target:v2",
    )


class _AgentPreferenceV2(OrderedAgentPreferenceScorer):
    descriptor = replace(
        OrderedAgentPreferenceScorer.descriptor,
        implementation_version="2",
        implementation_fingerprint="test:preferred-agent:v2",
    )


class _PolicyV2(FifoSchedulingPolicy):
    descriptor = replace(
        FifoSchedulingPolicy.descriptor,
        implementation_version="2",
        implementation_fingerprint="test:fifo:v2",
    )


def _replacement_components(
    current: LocalDaemonSchedulingComponents,
) -> LocalDaemonSchedulingComponents:
    return LocalDaemonSchedulingComponents(
        planners=tuple(
            _CpuPlannerV2() if item.resource_kind == "cpu" else item
            for item in current.planners
        ),
        hard_evaluators=tuple(
            _TargetEvaluatorV2() if item.descriptor.kind == "target" else item
            for item in current.hard_evaluators
        ),
        preference_scorers=tuple(
            _AgentPreferenceV2() if item.descriptor.kind == "preferred_agent" else item
            for item in current.preference_scorers
        ),
        policy=_PolicyV2(),
    )


def _config(tmp_path: Path) -> LocalDaemonConfig:
    return LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_launch_profile(),
        agent_policy=AgentPolicyConfig(
            principals=(
                TransportPrincipalPolicy(
                    "operator-credential",
                    "operator",
                    "operator",
                    actions=("scheduling_reload",),
                ),
            )
        ),
    )


def _launch_profile() -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=Path(sys.executable),
        descriptor=ResidentProfileDescriptor(
            "test-local", "v1", "test-project", "test-environment", "test-executor"
        ).to_dict(),
    )


def test_initialize_start_restart_preserves_owner_and_rotates_epoch(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    first = LocalDaemon(config)
    first_status = first.start()
    first.stop()

    second = LocalDaemon(config)
    second_status = second.start()
    second.stop()

    assert second_status.coordinator_id == first_status.coordinator_id
    assert second_status.coordinator_epoch != first_status.coordinator_epoch


def test_scheduling_reload_is_local_atomic_and_durable(tmp_path: Path) -> None:
    config = _config(tmp_path)
    replacement = replace(
        config,
        agent_policy=AgentPolicyConfig(
            revision="policy-2",
            principals=config.agent_policy.principals,
        ),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
    before = daemon.start()
    request = CoordinatorSchedulingReload(
        operation_id="reload-scheduling-1",
        expected_scheduling_epoch=before.scheduling_epoch,
        reason="site policy changed",
    )
    operator = daemon.operator_view(
        LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
    )
    try:
        receipt = operator.reload_scheduling(request)
        assert receipt["state"] == "applied"
        assert receipt["scheduling_epoch"] != before.scheduling_epoch
        assert operator.reload_scheduling(request) == receipt
        status = operator.status()
        assert status.scheduling_epoch == receipt["scheduling_epoch"]
        assert any(
            item.get("owner") == "coordinator-scheduling"
            and item.get("state") == "applied"
            for item in status.controls
        )
    finally:
        daemon.stop()

    with pytest.raises(QueueConflictError, match="changed without reload"):
        LocalDaemon(config).start()
    restarted = LocalDaemon(replacement)
    restarted.start()
    restarted.stop()


def test_complete_component_epoch_retains_old_bindings_and_activates_new_ones(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    old = config.scheduling_components
    replacement = _replacement_components(old)
    initial = local_daemon_execution._build_scheduling_epoch(
        epoch_id="epoch-1",
        composition=old,
        active_slurm_profiles={},
    )
    old_cpu = next(item for item in old.planners if item.resource_kind == "cpu")
    old_target = next(
        item for item in old.hard_evaluators if item.descriptor.kind == "target"
    )
    old_preference = next(
        item
        for item in old.preference_scorers
        if item.descriptor.kind == "preferred_agent"
    )
    replacement_epoch = local_daemon_execution._build_scheduling_epoch(
        epoch_id="epoch-2",
        composition=replacement,
        active_slurm_profiles={},
        current=initial,
        referenced_descriptors=(
            old_cpu.descriptor,
            old_target.descriptor,
            old_preference.descriptor,
            old.policy.descriptor,
        ),
    )

    old_record = cast(
        Any,
        SimpleNamespace(
            stage_work_id="old-work",
            placement=SimpleNamespace(
                planner_descriptors={"cpu": old_cpu.descriptor},
                hard_constraints=(
                    SimpleNamespace(
                        evaluator="target", descriptor=old_target.descriptor
                    ),
                ),
                preferences=(
                    SimpleNamespace(
                        scorer="preferred_agent",
                        descriptor=old_preference.descriptor,
                    ),
                ),
            ),
        ),
    )
    new_cpu = next(item for item in replacement.planners if item.resource_kind == "cpu")
    new_target = next(
        item for item in replacement.hard_evaluators if item.descriptor.kind == "target"
    )
    new_preference = next(
        item
        for item in replacement.preference_scorers
        if item.descriptor.kind == "preferred_agent"
    )
    fresh_record = cast(
        Any,
        SimpleNamespace(
            stage_work_id="fresh-work",
            placement=SimpleNamespace(
                planner_descriptors={"cpu": new_cpu.descriptor},
                hard_constraints=(
                    SimpleNamespace(
                        evaluator="target", descriptor=new_target.descriptor
                    ),
                ),
                preferences=(
                    SimpleNamespace(
                        scorer="preferred_agent",
                        descriptor=new_preference.descriptor,
                    ),
                ),
            ),
        ),
    )

    mixed_kernel = cast(Any, replacement_epoch.kernel((old_record, fresh_record)))
    assert mixed_kernel._work_planners["old-work"]["cpu"] is old_cpu
    assert mixed_kernel._work_hard["old-work"]["target"] is old_target
    assert (
        mixed_kernel._work_preference["old-work"]["preferred_agent"] is old_preference
    )
    assert mixed_kernel._work_planners["fresh-work"]["cpu"] is new_cpu
    assert mixed_kernel._work_hard["fresh-work"]["target"] is new_target
    assert (
        mixed_kernel._work_preference["fresh-work"]["preferred_agent"] is new_preference
    )
    assert mixed_kernel._policy is replacement.policy
    assert replacement_epoch.registry.retained(old.policy.descriptor) is old.policy


def test_component_reload_collision_rejects_before_epoch_or_config_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    replacement = replace(
        config,
        scheduling_components=LocalDaemonConfig(
            tmp_path / "unused-coordinator",
            tmp_path / "unused-agent",
            tmp_path / "unused-runs",
            _launch_profile(),
        ).scheduling_components,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
    before = daemon.start()
    execution = cast(Any, daemon._execution)
    old_epoch = execution._scheduling
    monkeypatch.setattr(
        execution,
        "_referenced_component_descriptors",
        lambda _placements=(): config.scheduling_components.descriptors,
    )
    try:
        receipt = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        ).reload_scheduling(
            CoordinatorSchedulingReload(
                operation_id="reload-collision",
                expected_scheduling_epoch=before.scheduling_epoch,
                reason="same descriptor with different objects",
            )
        )
        assert receipt["state"] == "failed"
        assert execution._scheduling is old_epoch
        assert daemon.config is config
        assert daemon.status().scheduling_epoch == before.scheduling_epoch
    finally:
        daemon.stop()


def test_reload_rejects_a_planner_the_local_provider_cannot_honor(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    replacement = replace(
        config,
        scheduling_components=replace(
            config.scheduling_components,
            planners=tuple(
                _IncompatibleCpuPlanner() if item.resource_kind == "cpu" else item
                for item in config.scheduling_components.planners
            ),
        ),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
    before = daemon.start()
    execution = cast(Any, daemon._execution)
    try:
        receipt = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        ).reload_scheduling(
            CoordinatorSchedulingReload(
                operation_id="reload-incompatible-claim-contract",
                expected_scheduling_epoch=before.scheduling_epoch,
                reason="install incompatible planner",
            )
        )
        assert receipt["state"] == "failed"
        assert execution.scheduling_epoch == before.scheduling_epoch
        assert daemon.config is config
    finally:
        daemon.stop()


def test_reload_collects_nonterminal_stage_work_and_retains_its_exact_planner(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    replacement = replace(
        config,
        scheduling_components=_replacement_components(config.scheduling_components),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
    before = daemon.start()
    execution = cast(Any, daemon._execution)
    old_cpu = next(
        item
        for item in config.scheduling_components.planners
        if item.resource_kind == "cpu"
    )
    run_uri = path_to_run_uri(tmp_path / "referenced-run")
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    prepared = authority.ensure_prepared_attempt(
        run_uri,
        PreparedAttemptRequest(
            operation_id="prepare-1",
            request_digest="digest-1",
            admission_id="admission-1",
            stage_name="build",
            readiness_generation="ready-1",
            expected_revision=authority.open_run(run_uri).revision,
            expected_stage_status=None,
            expected_attempt_id=None,
            next_attempt=1,
            owner_id="coordinator",
            plan_fingerprint="plan-1",
            bound_inputs={},
            upstream_commits={},
        ),
    )
    resources = ResourceRequest(entries={"cpu": ResourceEntry("cpu", 1, "count")})
    stage_work_id = stage_work_identity(
        "admission-1", "build", prepared.attempt.attempt_id, "ready-1"
    )
    execution.stage_work_store.create_or_refresh(
        StageWorkRecord(
            stage_work_id=stage_work_id,
            admission_id="admission-1",
            run_uri=run_uri,
            stage_name="build",
            attempt=1,
            attempt_id=prepared.attempt.attempt_id,
            readiness_generation="ready-1",
            ready_at=1,
            ready_order=1,
            plan_fingerprint="plan-1",
            authority_revision=prepared.attempt.revision,
            bound_inputs={},
            upstream_commits={},
            placement=resolve_stage_placement(
                authored=resources,
                runtime=None,
                policy=StagePlacementPolicy(),
                planners={"cpu": old_cpu},
            ),
        )
    )
    try:
        result = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        ).reload_scheduling(
            CoordinatorSchedulingReload(
                operation_id="reload-retain-stage-work",
                expected_scheduling_epoch=before.scheduling_epoch,
                reason="install new components",
            )
        )
        assert result["state"] == "applied"
        assert execution._scheduling.registry.retained(old_cpu.descriptor) is old_cpu
        assert execution._scheduling.registry.active("cpu") is next(
            item
            for item in replacement.scheduling_components.planners
            if item.resource_kind == "cpu"
        )
    finally:
        daemon.stop()


def test_reload_retains_exact_components_from_an_accepted_runtime_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    replacement = replace(
        config,
        scheduling_components=_replacement_components(config.scheduling_components),
    )
    old_cpu = next(
        item
        for item in config.scheduling_components.planners
        if item.resource_kind == "cpu"
    )
    resources = ResourceRequest(entries={"cpu": ResourceEntry("cpu", 1, "count")})
    placement = resolve_stage_placement(
        authored=resources,
        runtime=None,
        policy=StagePlacementPolicy(),
        planners={"cpu": old_cpu},
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
    monkeypatch.setattr(daemon, "_serve", lambda: daemon._stop.wait())
    before = daemon.start()
    execution = cast(Any, daemon._execution)
    run_uri = path_to_run_uri(tmp_path / "accepted-runtime")
    monkeypatch.setattr(
        local_daemon_execution,
        "load_managed_local_runtime_record",
        lambda _store, _run_uri: {
            "digest": "intent-digest",
            "placements": {"build": placement.to_dict()},
        },
    )
    with sqlite3.connect(config.control_database) as conn:
        conn.execute(
            "INSERT INTO managed_admissions("
            "admission_id, queue_item_id, coordinator_id, run_uri, intent_digest, "
            "execution_owner, state, accepted_at, authority_operation_id, "
            "cancellation_operation_id, blocked_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
            (
                "admission-accepted",
                "queue-accepted",
                before.coordinator_id,
                run_uri,
                "intent-digest",
                "managed-stage",
                LocalDaemonAdmissionState.PENDING_AUTHORITY.value,
                "2020-01-01T00:00:00Z",
                "authority-bind-accepted",
            ),
        )
        conn.commit()
    try:
        result = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        ).reload_scheduling(
            CoordinatorSchedulingReload(
                operation_id="reload-retain-accepted-runtime",
                expected_scheduling_epoch=before.scheduling_epoch,
                reason="install new components",
            )
        )
        assert result["state"] == "applied"
        assert execution._scheduling.registry.retained(old_cpu.descriptor) is old_cpu
    finally:
        daemon.stop()


def test_fresh_admission_rejects_a_pre_reload_runtime_before_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _config(tmp_path)
    config = replace(
        base,
        scheduling_components=_replacement_components(base.scheduling_components),
    )
    old_cpu = next(
        item
        for item in base.scheduling_components.planners
        if item.resource_kind == "cpu"
    )
    resources = ResourceRequest(entries={"cpu": ResourceEntry("cpu", 1, "count")})
    placement = resolve_stage_placement(
        authored=resources,
        runtime=None,
        policy=StagePlacementPolicy(),
        planners={"cpu": old_cpu},
    )
    stale_intent = SimpleNamespace(
        digest="stale-intent",
        placements={"build": placement},
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    monkeypatch.setattr(daemon, "_serve", lambda: daemon._stop.wait())
    daemon.start()
    monkeypatch.setattr(
        local_daemon_execution,
        "load_managed_local_intent",
        lambda _config, _run_uri, **_kwargs: stale_intent,
    )
    client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
    try:
        with pytest.raises(QueueConflictError, match="another epoch"):
            client.submit(
                LocalDaemonAdmissionRequest(
                    queue_item_id="stale-item",
                    run_uri=path_to_run_uri(tmp_path / "stale-run"),
                )
            )
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM managed_admissions").fetchone()[0]
                == 0
            )
    finally:
        daemon.stop()


@pytest.mark.parametrize(
    "reference_owner",
    ["accepted-runtime", "submission", "same-identity-collision"],
)
def test_reload_retains_the_exact_profile_for_nonterminal_slurm_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference_owner: str,
) -> None:
    profile = SlurmReadyStageProfile(
        profile_id="training",
        partition="cpu",
        max_outstanding=1,
        bootstrap_argv=("loom", "slurm-bootstrap"),
        runner=FakeSlurmCommandRunner(),
        command_adapter_fingerprint="fake-slurm-v1",
        bootstrap_principal_id="slurm-principal",
        credential_reference="slurm-credential",
        coordinator_endpoint="https://coordinator.example",
        project_fingerprint="project-v1",
        environment_fingerprint="environment-v1",
        executor_fingerprint="executor-v1",
        job_private_file_provider=SlurmJobPrivateFileProvider(
            fixed_path="/tmp/loom-phase-8a-capability",
            descriptor="fake-prolog-v1",
            helper_argv=("/bin/true",),
        ),
        cluster="cluster-a",
    )
    config = replace(_config(tmp_path), slurm_profiles=(profile,))
    replacement = replace(
        config,
        slurm_profiles=(
            (replace(profile),) if reference_owner == "same-identity-collision" else ()
        ),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: replacement)
    before = daemon.start()
    execution = cast(Any, daemon._execution)
    if reference_owner in {"accepted-runtime", "same-identity-collision"}:
        monkeypatch.setattr(
            execution,
            "_referenced_runtime_placements",
            lambda: (
                SimpleNamespace(
                    planner_descriptors={},
                    hard_constraints=(),
                    preferences=(),
                    route=SimpleNamespace(
                        kind=ExecutionRouteKind.SLURM,
                        profile_id=profile.profile_id,
                        profile_configuration_fingerprint=(
                            profile.configuration_fingerprint
                        ),
                    ),
                ),
            ),
        )
    else:
        monkeypatch.setattr(
            execution.slurm_submissions,
            "list_nonterminal",
            lambda: (
                SimpleNamespace(
                    request=SimpleNamespace(
                        profile_id=profile.profile_id,
                        profile_descriptor=profile.descriptor,
                    )
                ),
            ),
        )
    try:
        result = daemon.operator_view(
            LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
        ).reload_scheduling(
            CoordinatorSchedulingReload(
                operation_id="reload-retain-slurm-profile",
                expected_scheduling_epoch=before.scheduling_epoch,
                reason="remove profile from fresh admission",
            )
        )
        if reference_owner == "same-identity-collision":
            assert result["state"] == "failed"
            assert execution.scheduling_epoch == before.scheduling_epoch
        else:
            assert result["state"] == "applied"
            assert execution._scheduling.active_slurm_profiles == {}
            assert (
                execution._slurm_profile(
                    profile.profile_id, profile.configuration_fingerprint
                )
                is profile
            )
            if reference_owner == "accepted-runtime":
                monkeypatch.setattr(
                    execution, "_referenced_runtime_placements", lambda: ()
                )
                second = daemon.operator_view(
                    LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
                ).reload_scheduling(
                    CoordinatorSchedulingReload(
                        operation_id="reload-drop-settled-profile",
                        expected_scheduling_epoch=cast(str, result["scheduling_epoch"]),
                        reason="all old profile references settled",
                    )
                )
                assert second["state"] == "applied"
                assert execution._scheduling.retained_slurm_profiles == {}
    finally:
        daemon.stop()


def test_slurm_dispatch_resolves_the_exact_retained_profile() -> None:
    route = SimpleNamespace(
        kind=ExecutionRouteKind.SLURM,
        profile_id="training",
        profile_configuration_fingerprint="profile-fingerprint-v1",
    )
    record = SimpleNamespace(
        admission_id="admission-1",
        scheduling_state=SchedulingProjectionState.READY,
        placement=SimpleNamespace(route=route),
        ready_at=1,
        ready_order=1,
        stage_work_id="stage-work-1",
    )
    resolved: list[tuple[str, str | None]] = []

    def resolve_profile(
        profile_id: str, configuration_fingerprint: str | None = None
    ) -> None:
        resolved.append((profile_id, configuration_fingerprint))
        raise QueueConflictError("stop after exact profile lookup")

    subject = cast(
        Any,
        SimpleNamespace(
            stage_work_store=SimpleNamespace(list_stage_work=lambda: (record,)),
            _slurm_profile=resolve_profile,
        ),
    )
    with pytest.raises(QueueConflictError, match="exact profile lookup"):
        local_daemon_execution.LocalDaemonExecution._dispatch_slurm_ready(
            subject,
            admission=cast(Any, SimpleNamespace(admission_id="admission-1")),
            intent=cast(Any, SimpleNamespace()),
            authority=cast(Any, SimpleNamespace()),
            snapshot=cast(Any, SimpleNamespace()),
        )

    assert resolved == [("training", "profile-fingerprint-v1")]


def test_owner_socket_operator_scope_denial_happens_before_persistence(
    tmp_path: Path,
) -> None:
    policy = AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "agent-credential",
                "agent-principal",
                "agent-a",
                ("default",),
                ("python",),
            ),
        ),
        principals=(
            TransportPrincipalPolicy(
                "owner-local",
                f"uid:{os.getuid()}",
                "operator",
                actions=("drain",),
                agent_ids=("another-agent",),
                pools=("default",),
            ),
        ),
    )
    config = replace(_config(tmp_path), agent_policy=policy)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    agent = daemon.agent_view(
        LocalDaemonPrincipal(
            "agent-principal", LocalDaemonRole.AGENT, "agent-credential"
        )
    )
    handshake = agent.handshake()
    session = agent.register(
        AgentRegistration(
            "register-1",
            str(handshake["coordinator_id"]),
            str(handshake["coordinator_epoch"]),
            "agent-root-a",
            "config-1",
            "inventory-1",
            "availability-1",
            ("default",),
            ("python",),
            retirement_verifier="01" * 32,
        )
    )
    server = LocalDaemonSocketServer(daemon, config.endpoint)
    server.start()
    try:
        with pytest.raises(QueueServiceError, match="local_daemon_request_rejected"):
            LocalDaemonSocketClient(config.endpoint).control_agent(
                AgentControl(
                    operation_id="socket-denied-control",
                    kind=AgentControlKind.DRAIN,
                    agent_id=session.agent_id,
                    expected_session_id=session.session_id,
                    expected_config_revision=session.config_revision,
                    pool="default",
                    cancel_active=False,
                    reason="outside owner socket scope",
                )
            )
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM agent_controls").fetchone()[0] == 0
            )
    finally:
        server.stop()
        daemon.stop()


def test_scheduling_reload_without_trusted_loader_fails_without_swap(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    before = daemon.start()
    operator = daemon.operator_view(
        LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
    )
    request = CoordinatorSchedulingReload(
        operation_id="reload-scheduling-1",
        expected_scheduling_epoch=before.scheduling_epoch,
        reason="no protected loader",
    )
    try:
        receipt = operator.reload_scheduling(request)
        assert receipt == {
            "operation_id": "reload-scheduling-1",
            "state": "failed",
            "code": "reload_rejected",
            "scheduling_epoch": before.scheduling_epoch,
        }
        assert operator.reload_scheduling(request) == receipt
        assert daemon.config is config
    finally:
        daemon.stop()


def test_start_is_open_only_and_second_owner_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(QueueServiceError, match="missing"):
        LocalDaemon(config).start()

    LocalDaemon.initialize(config)
    first = LocalDaemon(config)
    first.start()
    try:
        with pytest.raises(QueueServiceError, match="already locked"):
            LocalDaemon(config).start()
    finally:
        first.stop()


@pytest.mark.parametrize("owner_store", ("execution_database", "agent_journal"))
def test_start_rejects_missing_expected_owner_store_without_retaining_locks(
    tmp_path: Path, owner_store: str
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    store_path = getattr(config, owner_store)
    store_path.unlink()

    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()
    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()
    assert not store_path.exists()


@pytest.mark.parametrize(
    "store_path",
    ("control_database", "execution_database", "agent_journal"),
)
def test_start_rejects_current_schema_owner_substitution(
    tmp_path: Path, store_path: str
) -> None:
    config = _config(tmp_path / "original")
    donor = _config(tmp_path / "donor")
    LocalDaemon.initialize(config)
    LocalDaemon.initialize(donor)
    target = getattr(config, store_path)
    target.unlink()
    copyfile(getattr(donor, store_path), target)
    target.chmod(0o600)

    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()


def test_live_control_loss_never_recreates_control_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        config.control_database.unlink()
        with pytest.raises(QueueStorageError, match="control state is unavailable"):
            daemon.status()
        assert not config.control_database.exists()
    finally:
        daemon.stop()


def test_live_control_substitution_rejects_cached_coordinator_identity(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path / "original")
    donor = _config(tmp_path / "donor")
    LocalDaemon.initialize(config)
    LocalDaemon.initialize(donor)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        config.control_database.unlink()
        copyfile(donor.control_database, config.control_database)
        with pytest.raises(QueueStorageError, match="control identity is invalid"):
            daemon.status()
    finally:
        daemon.stop()


@pytest.mark.parametrize("owner_store", ("execution_database", "agent_journal"))
def test_live_owner_substitution_degrades_status_and_blocks_scheduling(
    tmp_path: Path, owner_store: str
) -> None:
    config = _config(tmp_path / "original")
    donor = _config(tmp_path / "donor")
    LocalDaemon.initialize(config)
    LocalDaemon.initialize(donor)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        target = getattr(config, owner_store)
        target.unlink()
        copyfile(getattr(donor, owner_store), target)
        target.chmod(0o600)

        status = daemon.status()
        assert status.service_health == "degraded"
        assert status.service_diagnostic == "owner_status_unavailable"
        with pytest.raises(QueueServiceError, match="owner state is unavailable"):
            daemon.reconcile_once()
    finally:
        daemon.stop()


def test_failed_execution_construction_releases_daemon_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)

    class _Failure:
        def __init__(self, **_kwargs: object) -> None:
            raise RuntimeError("construction failed")

    monkeypatch.setattr(local_daemon_execution, "LocalDaemonExecution", _Failure)
    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()

    monkeypatch.undo()
    restarted = LocalDaemon(config)
    restarted.start()
    restarted.stop()


def test_slurm_cancellation_fanout_uses_only_exact_known_handles() -> None:
    """An epoch request is not mistaken for scheduler containment."""

    known = SimpleNamespace(
        state="accepted",
        assignment=SimpleNamespace(
            operation_id="known",
            profile_id="profile-a",
            profile_configuration_fingerprint="config-a",
        ),
    )
    unknown = SimpleNamespace(
        state="submitting",
        assignment=SimpleNamespace(
            operation_id="unknown",
            profile_id="profile-a",
            profile_configuration_fingerprint="config-a",
        ),
    )

    class _Assignments:
        def list_run_unreleased(self, run_uri: str) -> tuple[object, ...]:
            assert run_uri == "run://example"
            return (known, unknown)

    calls: list[tuple[str, object]] = []

    class _Submissions:
        def find(self, operation_id: str) -> object:
            return (
                SimpleNamespace(job_id="1234")
                if operation_id == "known"
                else SimpleNamespace(job_id=None)
            )

        def request_cancel(self, operation_id: str, profile: object) -> object:
            calls.append((operation_id, profile))
            return SimpleNamespace(cancel_requested=True)

    execution = object.__new__(local_daemon_execution.LocalDaemonExecution)
    subject = cast(Any, execution)
    subject.slurm_assignments = _Assignments()
    subject.slurm_submissions = _Submissions()
    subject._slurm_profile = lambda profile_id, fingerprint: (
        f"resolved:{profile_id}:{fingerprint}"
    )

    assert execution._fan_out_slurm_cancellation("run://example") is True
    assert calls == [("known", "resolved:profile-a:config-a")]


def test_slurm_cancellation_waits_for_exact_provider_release() -> None:
    record = SimpleNamespace(
        state="logical_released",
        assignment=SimpleNamespace(
            assignment_id="assignment-1",
            operation_id="operation-1",
            attempt_id="attempt-1",
        ),
    )
    execution = object.__new__(local_daemon_execution.LocalDaemonExecution)
    subject = cast(Any, execution)
    subject.slurm_assignments = SimpleNamespace(
        list_run_unreleased=lambda _run_uri: (record,)
    )
    subject.slurm_submissions = SimpleNamespace(
        find=lambda _operation_id: SimpleNamespace()
    )

    def unavailable(_assignment_id: str) -> None:
        raise QueueConflictError("provider release is unavailable")

    subject._release_slurm_assignment = unavailable
    assert execution._fan_out_slurm_cancellation("run://example") is True

    released: list[str] = []
    subject._release_slurm_assignment = released.append
    assert execution._fan_out_slurm_cancellation("run://example") is False
    assert released == ["assignment-1"]


def test_slurm_grant_and_start_are_blocked_by_the_durable_cancel_request(
    tmp_path: Path,
) -> None:
    control_database = tmp_path / "control.sqlite"
    with sqlite3.connect(control_database) as conn:
        conn.execute(
            "CREATE TABLE managed_admissions ("
            "run_uri TEXT PRIMARY KEY, cancellation_operation_id TEXT)"
        )
        conn.execute(
            "INSERT INTO managed_admissions VALUES ('run://cancelled', 'cancel-1')"
        )
        conn.commit()

    record = SimpleNamespace(
        input_ready=True,
        fence=None,
        state="accepted",
        assignment=SimpleNamespace(
            run_uri="run://cancelled",
            operation_id="slurm-operation-1",
            attempt_id="attempt-1",
        ),
    )
    execution = object.__new__(local_daemon_execution.LocalDaemonExecution)
    subject = cast(Any, execution)
    subject.config = SimpleNamespace(control_database=control_database)
    subject._slurm_authorized_record = lambda *args, **kwargs: record
    subject._remote_authority = lambda run_uri: pytest.fail(
        "cancellation must block authority grant"
    )
    subject.slurm_submissions = SimpleNamespace(
        consume_start=lambda operation_id: pytest.fail(
            "cancellation must block authored-root start"
        )
    )

    with pytest.raises(QueueConflictError, match="run is cancelling"):
        execution.slurm_grant(
            principal_id="slurm-principal",
            credential_id="slurm-credential",
            assignment_id="assignment-1",
            incarnation="bootstrap-1",
        )

    record.fence = "fence-1"
    record.state = "granted"
    assert (
        execution.slurm_start_permit(
            principal_id="slurm-principal",
            credential_id="slurm-credential",
            assignment_id="assignment-1",
            incarnation="bootstrap-1",
            fence="fence-1",
        )
        is False
    )


@pytest.mark.parametrize("owner_store", ("execution_database", "agent_journal"))
def test_live_owner_loss_degrades_service_and_blocks_scheduling(
    tmp_path: Path, owner_store: str
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        store_path = getattr(config, owner_store)
        store_path.unlink()

        status = daemon.status()
        assert status.service_health == "degraded"
        assert status.service_diagnostic == "owner_status_unavailable"
        assert not status.scheduling_ready
        with pytest.raises(QueueServiceError, match="owner state is unavailable"):
            daemon.reconcile_once()
        assert not store_path.exists()
    finally:
        daemon.stop()


def test_schema_mismatch_requires_fresh_root_without_migration(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    with sqlite3.connect(config.control_database) as conn:
        conn.execute("PRAGMA user_version = 0")

    with pytest.raises(QueueStorageError, match="fresh roots"):
        LocalDaemon(config).start()


def test_scoped_view_rejects_client_principal_for_operator_action(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        operator = daemon.operator_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        with pytest.raises(QueueServiceError, match="not authorized"):
            operator.status()
    finally:
        daemon.stop()
