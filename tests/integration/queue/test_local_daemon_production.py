"""Production local-daemon integration coverage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import importlib
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
from threading import Event, Thread
import time
from typing import Any, Never, cast

import pytest

import loom.queue._managed_local as managed_local
from loom.pipeline import PipelineSpec, parse_resource_request
from loom.cli.main import main
from loom.queue._managed_local import (
    AssignmentState,
    AtomResourceProvider,
    ClaimCommand,
    ManagedAssignment,
    ObserveRequest,
    SQLiteAgentJournal,
    _assignment_dict,
    _configured_provider_descriptor,
)
from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorService,
    SupervisorLaunchConfiguration,
    SupervisorLaunchState,
    _launch_from_value,
)
from loom.pipeline.planning import PlanSelectors, plan_pipeline
from loom.pipeline.planning import ExecutionPlan
from loom.pipeline.runtime import CpuResourcePlanner, scheduling_entry_view
from loom.pipeline.runtime.options import ExecutionOptions
from loom.pipeline.status import RunStatus, StageStatus, StageStatusRecord
from loom.pipeline.stores import (
    CancellationEpochRequest,
    CoordinatorAdmissionRequest,
    LocalArtifactStore,
    LocalRunStore,
    path_to_run_uri,
)
from loom.pipeline.execution import ExecutionFailure
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.scheduling import (
    CapacityAtom,
    ClaimSearchBudget,
    ClaimSearchState,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
)
from loom.queue import (
    ConfiguredGpuDevice,
    ExecutionRequirement,
    GpuDeviceDescriptor,
    LocalDaemon,
    LocalDaemonAdmission,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonSchedulingComponents,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketClient,
    LocalDaemonSocketServer,
    ManagedRecoveryTarget,
    QueueConflictError,
    QueueServiceError,
    RecoverUnknownAssignment,
    ResidentWorkerLaunchProfile,
    prepare_managed_local_runtime_record,
)
from loom.queue._remote_stage_execution import (
    ResidentProfileDescriptor,
    _ResidentAssignmentWorkspace,
)
from loom.queue.agent_sessions import (
    AgentPolicyConfig,
    TransportPrincipalPolicy,
)
from loom.serialization import PlainData, json_dumps_pretty, thaw_plain_data
from loom.queue.local_daemon_execution import (
    LocalDaemonExecution,
    LocalDaemonExecutionOutcome,
    _ScopedCoordinatorAuthority,
    _validate_agent_provider_composition,
    build_local_daemon_owner_views,
    initialize_local_daemon_owner_stores,
    load_managed_local_intent,
)
from loom.queue.local_daemon_runtime import load_managed_local_runtime_record


pytestmark = pytest.mark.integration


def _execution_requirements(pipeline: PipelineSpec) -> dict[str, ExecutionRequirement]:
    return {
        stage_name: ExecutionRequirement(
            "test-project", "test-environment", "test-executor"
        )
        for stage_name in pipeline.stage_names
    }


@pytest.fixture(autouse=True)
def _shutdown_test_supervisors(
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """Stop the independent supervisor processes created by each test."""

    clients: list[AgentProcessSupervisorClient] = []
    start = AgentProcessSupervisorService._start

    def tracked_start(
        root: Path, configuration: SupervisorLaunchConfiguration
    ) -> AgentProcessSupervisorClient:
        client = start(root, configuration)
        clients.append(client)
        return client

    monkeypatch.setattr(
        AgentProcessSupervisorService,
        "_start",
        staticmethod(tracked_start),
    )
    yield
    for client in reversed(clients):
        try:
            client.shutdown_for_test()
        except Exception:
            pass


class _ConfiguredCpuPlanner(CpuResourcePlanner):
    descriptor = replace(
        CpuResourcePlanner.descriptor,
        implementation_version="configured-2",
        implementation_fingerprint="test:configured-cpu:v2",
    )


class _RecordingCpuProvider(AtomResourceProvider):
    """A protected site provider used to prove the production composition."""

    def __init__(self, atom: CapacityAtom) -> None:
        planner = CpuResourcePlanner()
        super().__init__(
            _configured_provider_descriptor("cpu", (atom,)),
            planner.claim_contracts,
            (atom,),
        )
        self.operations: list[str] = []

    def prepare(self, command: ClaimCommand):  # type: ignore[no-untyped-def]
        self.operations.append("prepare")
        return super().prepare(command)

    def activate(self, command: ClaimCommand):  # type: ignore[no-untyped-def]
        self.operations.append("activate")
        return super().activate(command)

    def release(self, command: ClaimCommand):  # type: ignore[no-untyped-def]
        self.operations.append("release")
        return super().release(command)

    def worker_environment(self, command: ClaimCommand) -> dict[str, str]:
        self.operations.append("environment")
        return {"LOOM_TEST_PROVIDER": command.assignment.assignment_id}


def test_provider_composition_checks_each_provider_against_its_own_kind() -> None:
    first_atom = CapacityAtom(
        "cpu", "cpu-0", ExactQuantity(1), "count", ExactQuantity(1)
    )
    second_atom = CapacityAtom(
        "cpu", "cpu-1", ExactQuantity(1), "count", ExactQuantity(1)
    )
    first = _RecordingCpuProvider(first_atom)
    second = _RecordingCpuProvider(second_atom)
    planners = {"cpu": CpuResourcePlanner()}

    composition = _validate_agent_provider_composition((first, second), planners)
    assert composition["cpu"].observe(
        ObserveRequest("agent", "session", "observe-composition")
    ).atoms == (first_atom, second_atom)

    unknown = AtomResourceProvider(
        _configured_provider_descriptor("synthetic", ()),
        (ResourceClaimContractDescriptor("synthetic", 1, "synthetic-v1"),),
        (),
    )
    with pytest.raises(QueueServiceError, match="no active planner"):
        _validate_agent_provider_composition((unknown,), planners)

    incompatible = AtomResourceProvider(
        _configured_provider_descriptor("cpu", (first_atom,)),
        (ResourceClaimContractDescriptor("cpu", 1, "other-contract"),),
        (first_atom,),
    )
    with pytest.raises(QueueServiceError, match="no claim-contract intersection"):
        _validate_agent_provider_composition((incompatible,), planners)


@pytest.mark.parametrize(
    ("second_fabric", "expected_claims"),
    [("fabric-a", 1), ("fabric-b", 0)],
)
def test_production_gpu_projection_preserves_multi_device_fabric_groups(
    tmp_path: Path,
    second_fabric: str,
    expected_claims: int,
) -> None:
    devices = (
        ConfiguredGpuDevice(
            GpuDeviceDescriptor(
                "gpu-0", "large", 80 * 1024**3, fabric_group="fabric-a"
            ),
            "private-0",
        ),
        ConfiguredGpuDevice(
            GpuDeviceDescriptor(
                "gpu-1", "large", 80 * 1024**3, fabric_group=second_fabric
            ),
            "private-1",
        ),
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_launch_profile(),
        gpu_devices=devices,
    )
    execution = _execution(config)
    candidate = execution._candidate()
    request = parse_resource_request(
        {
            "entries": {
                "gpu": {
                    "kind": "gpu",
                    "amount": 2,
                    "unit": "count",
                    "attributes": {
                        "allocation_mode": "exclusive",
                        "fabric_group": "fabric-a",
                    },
                }
            }
        }
    ).entries["gpu"]
    resolved = execution.gpu_planner.resolve_request(
        scheduling_entry_view(request), None
    )
    assert resolved.request is not None
    opportunity = execution.gpu_planner.validate_opportunity(
        candidate.inventory["gpu"], candidate.availability["gpu"]
    )
    assert opportunity.opportunity is not None
    result = execution.gpu_planner.propose_claims(
        resolved.request,
        opportunity.opportunity,
        ClaimSearchBudget(4),
    )

    assert result.state is ClaimSearchState.COMPLETE
    assert len(result.claims) == expected_claims
    projected_devices = cast(
        tuple[Mapping[str, object], ...],
        candidate.inventory["gpu"].data["devices"],
    )
    assert [item["fabric_group"] for item in projected_devices] == [
        "fabric-a",
        second_fabric,
    ]


@pytest.mark.parametrize(
    ("account_for", "retained_worker"),
    [
        ("all", None),
        ([], None),
        ("all", "exact"),
        ("all", "conflict"),
        ("all", "predecessor"),
    ],
)
def test_persisted_preprocess_train_run_completes_without_injected_runtime_objects(
    tmp_path: Path,
    account_for: str | list[str],
    retained_worker: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "runs"
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "run-1")
    run_store.create_run(run_uri)
    pipeline_config = {
        "name": "daemon-production",
        "stages": [
            {
                "name": "preprocess",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.JsonProducerStage"
                    )
                },
                "config": {
                    "value": 42,
                    "working_root": str(tmp_path / "same-host-work"),
                    "relative_companion": True,
                },
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "outputs": {
                    "data": {
                        "artifact_type": "json",
                        "codec_key": "json.v1",
                    }
                },
            },
            {
                "name": "train",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.TextConsumerStage"
                    )
                },
                "depends_on": ["preprocess"],
                "inputs": {"data": "preprocess.data"},
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "outputs": {
                    "text": {
                        "artifact_type": "text",
                        "codec_key": "text.v1",
                    }
                },
            },
        ],
    }
    if retained_worker == "predecessor":
        pipeline_config["stages"] = pipeline_config["stages"][:1]
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {name: {"executor": "local"} for name in spec.stage_names},
        },
    )
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=run_store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        options={"resource_policy": {"account_for": account_for}},
        execution_requirements=_execution_requirements(spec),
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    predecessor = None
    if retained_worker == "predecessor":
        from loom.artifacts import ArtifactRef
        from loom.pipeline.transition_policy import TransitionIntent

        # Existing lease execution can leave a committed stale stage in a run
        # that is still running. Native admission must retain that exact head.
        prior = authority.allocate_stage_attempt(
            run_uri, "preprocess", owner_id="prior", lease_ttl_seconds=30
        )
        assert prior.lease is not None
        predecessor = authority.record_output_commit(
            run_uri, "preprocess", attempt_id=prior.attempt.attempt_id,
            fencing_token=prior.lease.fencing_token,
            outputs={"data": ArtifactRef(artifact_id="prior/data", uri=f"{run_uri}/prior", artifact_type="json")},
        )
        authority.transition_stage(
            run_uri, "preprocess", from_status=StageStatus.SUCCEEDED,
            to_status=StageStatus.STALE, intent=TransitionIntent.RESUME,
        )
        run_store.write_stage_status(
            run_uri, "preprocess",
            StageStatusRecord(
                run_uri=run_uri, stage_name="preprocess", status=StageStatus.STALE,
                attempt=1, updated_at="2020-01-01T00:00:00Z",
            ),
        )

    provider = _RecordingCpuProvider(
        CapacityAtom(
            "cpu", "machine-A:cpu", ExactQuantity(1), "count", ExactQuantity(1)
        )
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        agent_resource_providers=(provider,),
    )
    LocalDaemon.initialize(config)
    retained_path = run_store.local_stage_worker_request_path(run_uri, "preprocess")
    retained_bytes: bytes | None = None
    retained_mtime: int | None = None
    rejected = Event()
    if retained_worker in {"exact", "conflict"}:
        from loom.pipeline.execution import prepare_stage_attempt, StageWorkerRequest
        import loom.queue.local_daemon_execution as execution_owner

        intent = load_managed_local_intent(config, run_uri)
        saved = prepare_stage_attempt(
            run_store=run_store,
            run_uri=run_uri,
            stage=spec.get_stage("preprocess"),
            stage_plan=plan.ordered_stage_plans[0],
            fingerprint_context=intent.plan.fingerprint_context,
            resolved_runtime=execution_owner._worker_runtime(intent, "preprocess"),
        ).to_dict()
        if retained_worker == "conflict":
            runtime = cast(dict[str, Any], saved["resolved_runtime"])
            runtime["resource_policy"] = {"account_for": [], "enforce": []}
            runtime["resource_selection"] = {"account_for": [], "enforce": []}
            StageWorkerRequest.from_dict(saved)
            run_store.write_stage_worker_request(
                run_uri, "preprocess", saved, attempt=1
            )
            original_compare = execution_owner._require_retained_resource_handoff_match

            def observe_rejection(*args, **kwargs):
                try:
                    return original_compare(*args, **kwargs)
                except QueueConflictError as error:
                    assert "differs from placement" in str(error)
                    rejected.set()
                    raise

            monkeypatch.setattr(
                execution_owner,
                "_require_retained_resource_handoff_match",
                observe_rejection,
            )
        retained_bytes = retained_path.read_bytes()
        retained_mtime = retained_path.stat().st_mtime_ns
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        submitted = client.submit(LocalDaemonAdmissionRequest("queue-1", run_uri))
        if retained_worker == "conflict":
            assert rejected.wait(5), (
                "actual retained dispatch never rejected the conflict"
            )
            daemon.stop()
            assert retained_path.read_bytes() == retained_bytes
            assert retained_path.stat().st_mtime_ns == retained_mtime
            assert _supervisor_launch_count(config) == 0
            return
        completed = client.wait("queue-1", timeout_seconds=10)
        if predecessor is not None:
            assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
            snapshot = authority.open_run(run_uri)
            request = run_store.read_stage_worker_request(run_uri, "preprocess", attempt=2)
            assert request is not None
            assert cast(Mapping[str, object], request["metadata"])["managed_output_predecessor"] == predecessor.commit.commit_id
            head = snapshot.stages[0].latest_commit
            assert head is not None
            assert head.supersedes_commit_id == predecessor.commit.commit_id
            assert len(authority.list_output_commits(run_uri, stage_name="preprocess")) == 2
            return
        if retained_worker == "exact":
            assert retained_path.read_bytes() == retained_bytes
            assert retained_path.stat().st_mtime_ns == retained_mtime
        owner_view = client.admission(submitted.admission_id).owners
        status = client.status()

        assert submitted.state is LocalDaemonAdmissionState.PENDING_AUTHORITY
        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
        assert cast(Mapping[str, object], owner_view["admission"])["owner"] == (
            "coordinator"
        )
        assert cast(Mapping[str, object], owner_view["authority"])["owner"] == (
            "per-run-authority"
        )
        assert cast(Mapping[str, object], owner_view["scheduling"])["owner"] == (
            "coordinator-stage-work"
        )
        assignment_view = cast(Mapping[str, object], owner_view["assignment"])
        assert assignment_view["owner"] == "coordinator-assignments"
        assert len(cast(list[object], assignment_view["assignments"])) == 2
        execution_view = cast(Mapping[str, object], owner_view["execution"])
        assert execution_view["owner"] == ("local-agent")
        assert (
            len(
                cast(
                    list[object],
                    execution_view["journal"],
                )
            )
            == 2
        )
        for axis_name in ("scheduling", "assignment", "execution"):
            axis = cast(Mapping[str, object], owner_view[axis_name])
            assert axis["availability"] == "available"
            assert axis["state"] == "populated"
            assert isinstance(axis["revision"], int)
            assert axis["revision"] > 0
            assert axis["freshness"] == "current"
            assert str(axis["observed_at"]) <= status.as_of
        server = LocalDaemonSocketServer(daemon, config.endpoint)
        server.start()
        try:
            socket_view = (
                LocalDaemonSocketClient(config.endpoint)
                .admission(submitted.admission_id)
                .owners
            )
        finally:
            server.stop()
        for axis_name in ("scheduling", "assignment", "execution"):
            direct_axis = cast(Mapping[str, object], owner_view[axis_name])
            socket_axis = cast(Mapping[str, object], socket_view[axis_name])
            for field in ("owner", "availability", "state", "freshness"):
                assert socket_axis[field] == direct_axis[field]
            assert cast(int, socket_axis["revision"]) >= cast(
                int, direct_axis["revision"]
            )
        direct_result = cast(Mapping[str, object], owner_view["run_result"])
        socket_result = cast(Mapping[str, object], socket_view["run_result"])
        for field in (
            "owner",
            "availability",
            "state",
            "freshness",
            "diagnostic",
            "diagnostic_failure",
        ):
            assert socket_result[field] == direct_result[field]
        assert list(cast(tuple[object, ...], socket_result["failures"])) == cast(
            list[object], direct_result["failures"]
        )
        assert str(socket_result["observed_at"]) >= str(direct_result["observed_at"])
        assert set(direct_result) == {
            "owner",
            "availability",
            "state",
            "observed_at",
            "freshness",
            "diagnostic",
            "diagnostic_failure",
            "failures",
            "resource_controls",
        }
        assert direct_result["owner"] == "run-store"
        assert direct_result["availability"] == "available"
        assert direct_result["state"] == "populated"
        controls = cast(list[Mapping[str, object]], direct_result["resource_controls"])
        assert [item["stage_name"] for item in controls] == ["preprocess", "train"]
        assert thaw_plain_data(socket_result["resource_controls"]) == controls
        assert status.as_of
        assert status.service_diagnostic is None
        snapshot = authority.open_run(run_uri)
        assert snapshot.status is RunStatus.SUCCEEDED
        assert [stage.stage_name for stage in snapshot.stages] == [
            "preprocess",
            "train",
        ]
        assert all(stage.status is StageStatus.SUCCEEDED for stage in snapshot.stages)
        expected_claims = 2 if account_for == "all" else 0
        assert provider.operations.count("prepare") == expected_claims
        assert provider.operations.count("activate") == expected_claims
        # Default managed policy retains CPU admission but has no outer binding.
        assert provider.operations.count("environment") == 0
        assert provider.operations.count("release") == expected_claims
        if account_for == []:
            with sqlite3.connect(config.agent_journal) as conn:
                rows = tuple(conn.execute("SELECT state, claims_json FROM assignments"))
            assert len(rows) == 2
            assert all(
                state == "released" and json.loads(claims) == {"commands": []}
                for state, claims in rows
            )
        preprocess_artifacts = run_store.local_stage_artifact_dir(run_uri, "preprocess")
        assert (preprocess_artifacts / "payload" / "value.txt").read_text(
            encoding="utf-8"
        ) == "companion-value"
        assert "companion=companion-value" in (
            run_store.local_stage_artifact_dir(run_uri, "train") / "text.txt"
        ).read_text(encoding="utf-8")
        assert run_store.read_stage_outputs(run_uri, "preprocess") is None
        assert run_store.read_stage_outputs(run_uri, "train") is None
    finally:
        daemon.stop()


def test_managed_local_hard_cutover_rejects_old_import_and_existing_roots(
    tmp_path: Path,
) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loom.queue.managed_local")

    coordinator = tmp_path / "legacy-coordinator.sqlite"
    coordinator.write_bytes(b"old-managed-local-state")
    config = LocalDaemonConfig(
        coordinator_root=coordinator,
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_launch_profile(),
    )
    before = coordinator.read_bytes()
    with pytest.raises(Exception, match="fresh roots"):
        LocalDaemon.initialize(config)
    assert coordinator.read_bytes() == before


def test_changed_scheduling_configuration_rejects_before_starting_supervisor(
    tmp_path: Path,
) -> None:
    config = _daemon_config(tmp_path)
    LocalDaemon.initialize(config)

    with pytest.raises(QueueConflictError, match="scheduling configuration changed"):
        LocalDaemon(replace(config, cpu_capacity=2)).start()

    assert config.agent_root is not None
    assert _supervisor_process_ids(config.agent_root) == ()


def test_unavailable_local_owner_store_rejects_before_starting_supervisor(
    tmp_path: Path,
) -> None:
    config = _daemon_config(tmp_path)
    LocalDaemon.initialize(config)
    config.execution_database.unlink()

    with pytest.raises(QueueServiceError, match="retained daemon owner state"):
        LocalDaemon(config).start()

    assert config.agent_root is not None
    assert _supervisor_process_ids(config.agent_root) == ()


def test_failed_local_start_preserves_supervisor_with_retained_owner_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _daemon_config(tmp_path)
    LocalDaemon.initialize(config)
    _retained_claim(config, assignment_id="retained-startup-failure")

    def fail_resume(_execution: LocalDaemonExecution) -> None:
        raise QueueServiceError("post-start local construction failed")

    monkeypatch.setattr(LocalDaemonExecution, "resume_retained_local_work", fail_resume)
    try:
        with pytest.raises(QueueServiceError, match="retained daemon owner state"):
            LocalDaemon(config).start()

        assert config.agent_root is not None
        process_ids = _supervisor_process_ids(config.agent_root)
        assert len(process_ids) == 1
        assert config.agent_root is not None
        with sqlite3.connect(
            config.agent_root / "supervisor" / "supervisor.sqlite"
        ) as conn:
            assert (
                conn.execute(
                    "SELECT value FROM metadata WHERE key = 'clean_shutdown_epoch'"
                ).fetchone()
                is None
            )
    finally:
        _, agent_id = _owner_ids(config)
        assert config.agent_root is not None
        assert config.resident_worker_launch_profile is not None
        supervisor = AgentProcessSupervisorClient(
            config.agent_root,
            SupervisorLaunchConfiguration(
                agent_id, (config.resident_worker_launch_profile,)
            ),
        )
        supervisor.shutdown_for_test()


def test_admission_digest_covers_the_resolved_pipeline_snapshot(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_store, run_uri, pipeline_config = _persist_single_stage_run(run_root)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    load_managed_local_intent(config, run_uri)
    stages = cast(list[dict[str, object]], pipeline_config["stages"])
    stages[0]["config"] = {"value": 99}
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )

    with pytest.raises(Exception, match="conflicts with exact runtime record"):
        load_managed_local_intent(config, run_uri)


def test_safe_runtime_metadata_cannot_activate_a_run_without_exact_record(
    tmp_path: Path,
) -> None:
    run_store, run_uri, _pipeline = _persist_single_stage_run(tmp_path / "runs")
    exact = run_store.local_run_dir(run_uri) / "config" / "managed_local_runtime.json"
    exact.unlink()
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_launch_profile(),
    )

    with pytest.raises(Exception, match="fresh exact runtime record"):
        load_managed_local_intent(config, run_uri)


def test_exact_runtime_record_keeps_attributes_settings_and_run_concurrency(
    tmp_path: Path,
) -> None:
    store, run_uri, pipeline = _persist_single_stage_run(tmp_path / "runs")
    plan = ExecutionPlan.from_dict(store.read_plan(run_uri))
    spec = PipelineSpec.from_config(pipeline)
    prepare_managed_local_runtime_record(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        execution_requirements=_execution_requirements(spec),
        options={
            "run_uri": run_uri,
            "execution": {"settings": {"max_parallel_stages": 2}},
            "stage_options": {
                "build": {
                    "resources": {
                        "entries": {
                            "cpu": {
                                "kind": "cpu",
                                "amount": 1,
                                "unit": "count",
                                "attributes": {},
                            }
                        }
                    },
                    "execution": {"settings": {"worker_mode": "exact"}},
                }
            },
        },
    )
    record = load_managed_local_runtime_record(store, run_uri)

    assert record["max_parallel_stages"] == 2
    runtime = cast(Mapping[str, object], record["runtime_options"])
    stage = cast(Mapping[str, object], runtime["stage_options"])["build"]
    assert cast(Mapping[str, object], stage)["execution"] == {
        "settings": {"worker_mode": "exact"}
    }
    placement = cast(Mapping[str, object], record["placements"])["build"]
    resources = cast(
        Mapping[str, object], cast(Mapping[str, object], placement)["resource_request"]
    )
    cpu = cast(Mapping[str, object], resources["entries"])["cpu"]
    assert cast(Mapping[str, object], cpu)["attributes"] == {}
    intent = load_managed_local_intent(
        _daemon_config(tmp_path, cpu_capacity=1), run_uri
    )
    assert intent.max_parallel_stages == 2
    execution = intent.runtime["build"].execution
    assert isinstance(execution, ExecutionOptions)
    settings = execution.settings
    assert settings["worker_mode"] == "exact"
    assert settings["max_parallel_stages"] == 2


def test_fresh_runtime_placement_uses_the_trusted_active_planner(
    tmp_path: Path,
) -> None:
    store, run_uri, pipeline = _persist_single_stage_run(tmp_path / "runs")
    base = _daemon_config(tmp_path)
    components = LocalDaemonSchedulingComponents(
        planners=tuple(
            _ConfiguredCpuPlanner() if item.resource_kind == "cpu" else item
            for item in base.scheduling_components.planners
        ),
        hard_evaluators=base.scheduling_components.hard_evaluators,
        preference_scorers=base.scheduling_components.preference_scorers,
        policy=base.scheduling_components.policy,
    )
    plan = ExecutionPlan.from_dict(store.read_plan(run_uri))
    spec = PipelineSpec.from_config(pipeline)
    prepare_managed_local_runtime_record(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        execution_requirements=_execution_requirements(spec),
        scheduling_components=components,
    )

    intent = load_managed_local_intent(
        replace(base, scheduling_components=components), run_uri
    )
    assert (
        intent.placements["build"].planner_descriptors["cpu"]
        == _ConfiguredCpuPlanner.descriptor
    )


@pytest.mark.parametrize(
    ("authority_status", "expected"),
    [
        (RunStatus.SUCCEEDED, LocalDaemonAdmissionState.SUCCEEDED),
        (RunStatus.FAILED, LocalDaemonAdmissionState.FAILED),
        (RunStatus.INTERRUPTED, LocalDaemonAdmissionState.FAILED),
        (RunStatus.CANCELLED, LocalDaemonAdmissionState.CANCELLED),
    ],
)
def test_terminal_authority_truth_wins_a_late_cancellation(
    tmp_path: Path, authority_status: RunStatus, expected: LocalDaemonAdmissionState
) -> None:
    _store, run_uri, _pipeline = _persist_single_stage_run(tmp_path / "runs")
    SQLitePerRunAuthorityStore(run_uri).create_run(run_uri, status=authority_status)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("late-cancel", run_uri))
        client.cancel("late-cancel")
        assert client.wait("late-cancel", timeout_seconds=10).state is expected
    finally:
        daemon.stop()


def test_post_bind_scoped_authority_rejects_wrong_run_and_coordinator(
    tmp_path: Path,
) -> None:
    first = path_to_run_uri(tmp_path / "first")
    other = path_to_run_uri(tmp_path / "other")
    authority = SQLitePerRunAuthorityStore(first)
    authority.create_run(first)
    authority.bind_coordinator_admission(
        first,
        CoordinatorAdmissionRequest(
            operation_id="bind",
            coordinator_id="coordinator-a",
            run_uri=first,
            intent_digest="intent",
        ),
    )
    scoped = _ScopedCoordinatorAuthority(
        authority, run_uri=first, coordinator_id="coordinator-a"
    )

    with pytest.raises(Exception, match="scoped authority run conflicts"):
        scoped.open_run(other)
    with pytest.raises(Exception, match="scoped authority coordinator conflicts"):
        scoped.install_cancellation_epoch(
            first,
            CancellationEpochRequest(
                operation_id="cancel",
                coordinator_id="coordinator-b",
                run_uri=first,
                stage_names=("stage-a",),
            ),
        )


def test_cancelling_outcome_remains_reconcilable_until_authority_settles(
    tmp_path: Path,
) -> None:
    config = _daemon_config(tmp_path)
    execution = _execution(config)
    run_uri = path_to_run_uri(tmp_path / "cancelling")
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    authority.bind_coordinator_admission(
        run_uri,
        CoordinatorAdmissionRequest(
            operation_id="bind",
            coordinator_id="coordinator",
            run_uri=run_uri,
            intent_digest="digest",
        ),
    )
    scoped = _ScopedCoordinatorAuthority(
        authority, run_uri=run_uri, coordinator_id="coordinator"
    )
    admission = LocalDaemonAdmission(
        admission_id="admission",
        queue_item_id="item",
        coordinator_id="coordinator",
        run_uri=run_uri,
        intent_digest="digest",
        execution_owner="managed-stage",
        state=LocalDaemonAdmissionState.CANCELLING,
        accepted_at="2020-01-01T00:00:00Z",
        authority_operation_id="bind",
        cancellation_operation_id="cancel",
    )

    class _UnsettledAuthority(_ScopedCoordinatorAuthority):
        def finalize_cancellation(
            self, run_uri: str, request: CancellationEpochRequest
        ) -> Never:
            del request
            self._run(run_uri)
            raise RuntimeError("transient transition outage")

    unsettled = _UnsettledAuthority(
        authority,
        run_uri=run_uri,
        coordinator_id="coordinator",
    )
    assert (
        execution._cancel(admission, unsettled, ("build",)).state
        is LocalDaemonAdmissionState.CANCELLING
    )
    assert (
        execution._cancel(admission, scoped, ("build",)).state
        is LocalDaemonAdmissionState.CANCELLED
    )


def test_mixed_owner_cancellation_waits_for_every_owner_before_final_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _daemon_config(tmp_path)
    execution = _execution(config)
    run_uri = path_to_run_uri(tmp_path / "mixed-cancellation")
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    authority.bind_coordinator_admission(
        run_uri,
        CoordinatorAdmissionRequest(
            operation_id="bind",
            coordinator_id="coordinator",
            run_uri=run_uri,
            intent_digest="digest",
        ),
    )
    scoped = _ScopedCoordinatorAuthority(
        authority, run_uri=run_uri, coordinator_id="coordinator"
    )
    admission = LocalDaemonAdmission(
        admission_id="admission",
        queue_item_id="item",
        coordinator_id="coordinator",
        run_uri=run_uri,
        intent_digest="digest",
        execution_owner="managed-stage",
        state=LocalDaemonAdmissionState.CANCELLING,
        accepted_at="2020-01-01T00:00:00Z",
        authority_operation_id="bind",
        cancellation_operation_id="cancel",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        execution,
        "_fan_out_slurm_cancellation",
        lambda _run_uri: calls.append("slurm") or False,
    )
    monkeypatch.setattr(
        execution,
        "_fan_out_local_cancellation",
        lambda _run_uri, _authority: calls.append("local") or True,
    )
    monkeypatch.setattr(
        execution,
        "_fan_out_remote_cancellation",
        lambda _run_uri, _operation_id: calls.append("remote") or False,
    )

    assert (
        execution._cancel(admission, scoped, ("build",)).state
        is LocalDaemonAdmissionState.CANCELLING
    )
    assert calls == ["slurm", "local", "remote"]
    assert authority.open_run(run_uri).status is RunStatus.RUNNING

    monkeypatch.setattr(
        execution,
        "_fan_out_local_cancellation",
        lambda _run_uri, _authority: calls.append("local-settled") or False,
    )
    assert (
        execution._cancel(admission, scoped, ("build",)).state
        is LocalDaemonAdmissionState.CANCELLED
    )
    assert authority.open_run(run_uri).status is RunStatus.CANCELLED


def test_daemon_reconciles_cancelling_and_wait_does_not_treat_it_as_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, run_uri, _pipeline = _persist_single_stage_run(tmp_path / "runs")
    config = _daemon_config(tmp_path)
    second_reconcile = Event()
    saw_cancelling = Event()

    def reconcile_admission(
        _self: LocalDaemonExecution,
        admission: LocalDaemonAdmission,
    ) -> LocalDaemonExecutionOutcome:
        if admission.state is LocalDaemonAdmissionState.CANCELLING:
            saw_cancelling.set()
            assert second_reconcile.wait(timeout=5)
            return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.CANCELLED)
        if admission.cancellation_operation_id is not None:
            return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.CANCELLING)
        return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.WAITING)

    monkeypatch.setattr(
        LocalDaemonExecution, "reconcile_admission", reconcile_admission
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("settling-cancel", run_uri))
        client.cancel("settling-cancel")
        assert saw_cancelling.wait(timeout=5)
        with pytest.raises(TimeoutError):
            client.wait("settling-cancel", timeout_seconds=0)

        second_reconcile.set()
        assert client.wait("settling-cancel", timeout_seconds=5).state is (
            LocalDaemonAdmissionState.CANCELLED
        )
    finally:
        second_reconcile.set()
        daemon.stop()


def test_status_degrades_per_run_for_corrupt_or_missing_owner_data(
    tmp_path: Path,
) -> None:
    config = _daemon_config(tmp_path)
    config.execution_database.parent.mkdir(parents=True, exist_ok=True)
    config.execution_database.write_bytes(b"not a sqlite database")
    config.agent_journal.parent.mkdir(parents=True, exist_ok=True)
    config.agent_journal.write_bytes(b"not a sqlite database")
    admission = LocalDaemonAdmission(
        admission_id="admission",
        queue_item_id="item",
        coordinator_id="coordinator",
        run_uri=path_to_run_uri(tmp_path / "missing-authority"),
        intent_digest="digest",
        execution_owner="managed-stage",
        state=LocalDaemonAdmissionState.CANCELLATION_REQUESTED,
        accepted_at="2020-01-01T00:00:00Z",
        authority_operation_id="bind",
        cancellation_operation_id="cancel",
    )

    view = build_local_daemon_owner_views(config, (admission,))[0]

    assert (
        cast(Mapping[str, object], view["authority"])["diagnostic"]
        == "authority_unavailable"
    )
    assert (
        cast(Mapping[str, object], view["scheduling"])["diagnostic"]
        == "execution_store_unavailable"
    )
    assert (
        cast(Mapping[str, object], view["execution"])["diagnostic"]
        == "agent_journal_unavailable"
    )
    assert cast(Mapping[str, object], view["service"])["state"] == "degraded"
    assert cast(Mapping[str, object], view["service"])["diagnostic"] == (
        "owner_status_unavailable"
    )
    assert cast(Mapping[str, object], view["cancellation"])["receipt"] is None
    assert (
        cast(Mapping[str, object], view["cancellation"])["state"]
        == "requested_degraded"
    )
    for axis_name in ("scheduling", "assignment", "execution"):
        axis = cast(Mapping[str, object], view[axis_name])
        assert axis["availability"] == "unavailable"
        assert axis["state"] == "unavailable"
        assert axis["revision"] is None
        assert axis["freshness"] == "unavailable"
    assert all("not a sqlite" not in str(axis) for axis in view.values())


def test_status_distinguishes_observed_empty_owners_and_tracks_owner_changes(
    tmp_path: Path,
) -> None:
    config = _daemon_config(tmp_path)
    LocalDaemon.initialize(config)
    admission = LocalDaemonAdmission(
        admission_id="admission",
        queue_item_id="item",
        coordinator_id="coordinator",
        run_uri=path_to_run_uri(tmp_path / "missing-authority"),
        intent_digest="digest",
        execution_owner="managed-stage",
        state=LocalDaemonAdmissionState.WAITING,
        accepted_at="2020-01-01T00:00:00Z",
        authority_operation_id="bind",
    )

    coordinator_id, agent_id = _owner_ids(config)
    initial = build_local_daemon_owner_views(
        config, (admission,), coordinator_id=coordinator_id, agent_id=agent_id
    )[0]
    initial_revisions: dict[str, int] = {}
    for axis_name in ("scheduling", "assignment", "execution"):
        axis = cast(Mapping[str, object], initial[axis_name])
        assert axis["availability"] == "available"
        assert axis["state"] == "empty"
        assert axis["revision"] == 0
        assert axis["freshness"] == "current"
        assert axis["observed_at"]
        initial_revisions[axis_name] = cast(int, axis["revision"])

    with sqlite3.connect(config.execution_database) as conn:
        conn.execute(
            "INSERT INTO preparation_intents "
            "(operation_id, request_digest, admission_id, stage_name, "
            "next_attempt, intent_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("prepare", "digest", "admission", "stage", 1, "{}"),
        )
        conn.execute(
            "INSERT INTO coordinator_offers "
            "(agent_id, session_id, offer_revision, snapshot_revision, "
            "availability_revision, snapshot_json, consumed, is_current) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("agent", "session", "offer", "snapshot", "available", "{}", 0, 1),
        )
    with sqlite3.connect(config.agent_journal) as conn:
        conn.execute(
            "INSERT INTO assignments "
            "(assignment_id, identity_json, request_json, state) "
            "VALUES (?, ?, ?, ?)",
            (
                "assignment",
                json_dumps_pretty({"run_uri": admission.run_uri}),
                "{}",
                AssignmentState.ACCEPTED.value,
            ),
        )

    changed = build_local_daemon_owner_views(
        config, (admission,), coordinator_id=coordinator_id, agent_id=agent_id
    )[0]
    for axis_name in ("scheduling", "assignment", "execution"):
        axis = cast(Mapping[str, object], changed[axis_name])
        assert cast(int, axis["revision"]) > initial_revisions[axis_name]


def test_pending_cancellation_installs_authority_epoch_before_any_stage(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    _run_store, run_uri, _pipeline = _persist_single_stage_run(run_root)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("cancel-before-authority", run_uri))
        requested = client.cancel("cancel-before-authority")
        authority = SQLitePerRunAuthorityStore(run_uri)
        authority.create_run(run_uri, status=RunStatus.RUNNING)
        cancelled = client.wait("cancel-before-authority", timeout_seconds=10)

        assert requested.state is LocalDaemonAdmissionState.CANCELLATION_REQUESTED
        assert cancelled.state is LocalDaemonAdmissionState.CANCELLED
        snapshot = authority.open_run(run_uri)
        assert snapshot.status is RunStatus.CANCELLED
        assert len(snapshot.stages) == 1
        assert snapshot.stages[0].stage_name == "build"
        assert snapshot.stages[0].status is StageStatus.CANCELLED
        assert snapshot.stages[0].attempts == ()
        detail = client.admission(cancelled.admission_id)
        cancellation = cast(Mapping[str, object], detail.owners["cancellation"])
        receipt = cast(Mapping[str, object], cancellation["receipt"])
        request = cast(Mapping[str, object], receipt["request"])
        assert cancellation["state"] == "terminal"
        assert cancellation["principal"] == "integration-client"
        assert cancellation["effective"] is True
        assert cancellation["terminal"] is True
        assert request["operation_id"] == requested.cancellation_operation_id
        assert isinstance(receipt["epoch"], str)
    finally:
        daemon.stop()


def test_connected_active_cancellation_withholds_output_commit(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "active-cancel")
    run_store.create_run(run_uri)
    pipeline_config = {
        "name": "daemon-active-cancel",
        "stages": [
            {
                "name": "slow",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.SleepStage"
                },
                "config": {
                    "seconds": 2.0,
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
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "stages": {"slow": {"executor": "local"}}},
    )
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=run_store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        execution_requirements=_execution_requirements(spec),
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonSocketServer(daemon, config.endpoint)
    server.start()
    try:
        client = LocalDaemonSocketClient(config.endpoint)
        submitted = client.submit(LocalDaemonAdmissionRequest("cancel-active", run_uri))
        _wait_for_supervisor_launch_count(config, expected=1)
        active = client.admission(submitted.admission_id).admission
        assert active.state is LocalDaemonAdmissionState.ACTIVE
        client.cancel("cancel-active")
        cancelled = client.wait("cancel-active", timeout_seconds=10)

        assert cancelled.state is LocalDaemonAdmissionState.CANCELLED
        stage = authority.open_run(run_uri).stages[0]
        assert stage.status is StageStatus.CANCELLED
        assert stage.latest_commit is None
        assert stage.artifact_facts == ()
        result = run_store.read_stage_worker_result(run_uri, "slow", attempt=1)
        assert result is not None
        request = cast(Mapping[str, Any], result["executor_metadata"])["request"]
        assert request["stage_name"] == "slow"
        assert request["executor_name"] == "local"
        assert str(tmp_path) not in json.dumps(request)
    finally:
        server.stop()
        daemon.stop()


def test_daemon_overlaps_independent_runs_with_available_capacity(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    first_uri = _persist_sleep_run(
        run_root,
        run_name="first-run",
        stage_name="first",
    )
    second_uri = _persist_sleep_run(
        run_root,
        run_name="second-run",
        stage_name="second",
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        cpu_capacity=2,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("first-item", first_uri))
        client.submit(LocalDaemonAdmissionRequest("second-item", second_uri))
        _wait_for_supervisor_launch_count(config, expected=2)

        first = client.wait("first-item", timeout_seconds=10)
        second = client.wait("second-item", timeout_seconds=10)

        assert first.state is LocalDaemonAdmissionState.SUCCEEDED
        assert second.state is LocalDaemonAdmissionState.SUCCEEDED
        assert (
            SQLitePerRunAuthorityStore(first_uri).open_run(first_uri).status
            is RunStatus.SUCCEEDED
        )
        assert (
            SQLitePerRunAuthorityStore(second_uri).open_run(second_uri).status
            is RunStatus.SUCCEEDED
        )
    finally:
        daemon.stop()


@pytest.mark.parametrize("account_for", ["all", []])
def test_daemon_finishes_no_start_failure_without_waiting_for_process_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    account_for: str | list[PlainData],
) -> None:
    import loom.queue.local_daemon_execution as execution_owner

    run_root = tmp_path / "runs"
    store, run_uri, _pipeline = _persist_single_stage_run(
        run_root,
        resource_policy={"account_for": account_for, "enforce": ["cpu"]},
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    execution = daemon._execution
    assert execution is not None
    stalled = Event()

    class ObservedStartNotification(Event):
        """Bound the regression without fabricating a process-start event."""

        def __init__(self) -> None:
            super().__init__()
            self.completed_waits = 0

        def wait(self, timeout: float | None = None) -> bool:
            signalled = super().wait(timeout)
            if not signalled and any(
                future.done() and future.exception() is None
                for future in tuple(execution._local_assignment_futures.values())
            ):
                self.completed_waits += 1
                if self.completed_waits == 2:
                    stalled.set()
                    raise AssertionError(
                        "daemon kept waiting after its no-start task completed"
                    )
            return signalled

    monkeypatch.setattr(execution_owner, "Event", ObservedStartNotification)
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        submitted = client.submit(LocalDaemonAdmissionRequest("no-start", run_uri))
        completed = client.wait("no-start", timeout_seconds=10)

        assert not stalled.is_set()
        assert completed.state is LocalDaemonAdmissionState.FAILED
        assert authority.open_run(run_uri).status is RunStatus.FAILED
        assert _supervisor_launch_count(config) == 0
        assert execution.coordinator.list_run_live_states(run_uri) == ()
        assert execution.journal is not None
        assert execution.journal.retained_claim_commands() == ()
        detail = client.admission(submitted.admission_id)
        result = store.read_stage_worker_result(run_uri, "build", attempt=1)
        assert result is not None
        failure = cast(Mapping[str, PlainData], result["failure"])
        assert "cpu" in cast(str, failure["message"])
        assert "enforce: []" in cast(str, failure["message"])
        metadata = cast(Mapping[str, PlainData], result["executor_metadata"])
        assert metadata["process_created"] is False
        request = cast(Mapping[str, Any], metadata["request"])
        assert request["stage_name"] == "build"
        assert request["resolved_runtime"]["resources"]["entries"]["cpu"]["amount"] == 1
        assert str(tmp_path) not in json.dumps(request)
        assert metadata["resource_controls"] == [
            {
                "resource": "cpu",
                "owner": "managed_provider",
                "mechanism": None,
                "disposition": "unavailable",
            }
        ]
        run_result = cast(Mapping[str, object], detail.owners["run_result"])
        assert run_result["availability"] == "available"
        assert run_result["failures"]
    finally:
        daemon.stop()


def test_completed_background_failure_replays_the_same_local_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "runs"
    run_uri = _persist_sleep_run(
        run_root,
        run_name="background-replay",
        stage_name="build",
        seconds=0.1,
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    execution = daemon._execution
    assert execution is not None
    assert execution.supervisor is not None
    original_query = execution.supervisor.query
    third_query_entered = Event()
    allow_recovery = Event()
    failed_replay_wake = Event()
    query_calls = 0
    original_wake = daemon._wake.set

    def observe_replay_wake() -> None:
        if query_calls == 2:
            failed_replay_wake.set()
        original_wake()

    def fail_two_observers_then_recover(launch: object):
        nonlocal query_calls
        query_calls += 1
        if query_calls <= 2:
            raise OSError("simulated post-start observation failure")
        if query_calls == 3:
            third_query_entered.set()
            assert allow_recovery.wait(5)
        return original_query(launch)  # type: ignore[arg-type]

    monkeypatch.setattr(execution.supervisor, "query", fail_two_observers_then_recover)
    monkeypatch.setattr(daemon._wake, "set", observe_replay_wake)
    client = daemon.client_view(
        LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
    )
    try:
        admission = client.submit(
            LocalDaemonAdmissionRequest("background-replay-item", run_uri)
        )
        assert third_query_entered.wait(5)
        assert not failed_replay_wake.is_set(), (
            "a failed replay must await the normal poll, not wake its own retry loop"
        )
        with sqlite3.connect(config.execution_database) as conn:
            assignment_rows = tuple(
                conn.execute(
                    "SELECT assignment_id, identity_json FROM coordinator_assignments"
                )
            )
        assert len(assignment_rows) == 1
        assignment_id = str(assignment_rows[0][0])
        identity_json = str(assignment_rows[0][1])
        with sqlite3.connect(config.control_database) as conn:
            health = conn.execute(
                "SELECT health FROM admission_reconciliation_health "
                "WHERE admission_id = ?",
                (admission.admission_id,),
            ).fetchone()
        assert health is not None and str(health[0]) == "unavailable"

        allow_recovery.set()
        completed = client.wait("background-replay-item", timeout_seconds=10)
        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
        with sqlite3.connect(config.execution_database) as conn:
            final_rows = tuple(
                conn.execute(
                    "SELECT assignment_id, identity_json FROM coordinator_assignments"
                )
            )
        assert final_rows == ((assignment_id, identity_json),)
        assert _supervisor_launch_count(config) == 1
        snapshot = SQLitePerRunAuthorityStore(run_uri).open_run(run_uri)
        assert len(snapshot.stages[0].attempts) == 1
        deadline = time.monotonic() + 5
        final_health = None
        while time.monotonic() < deadline:
            with sqlite3.connect(config.control_database) as conn:
                final_health = conn.execute(
                    "SELECT health FROM admission_reconciliation_health "
                    "WHERE admission_id = ?",
                    (admission.admission_id,),
                ).fetchone()
            if final_health is not None and str(final_health[0]) == "healthy":
                break
            time.sleep(0.02)
        assert final_health is not None and str(final_health[0]) == "healthy"
    finally:
        allow_recovery.set()
        daemon.stop()


def test_daemon_global_priority_preempts_earlier_lower_priority_admission(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    low_uri = _persist_sleep_run(
        run_root,
        run_name="low-run",
        stage_name="low",
        seconds=1.0,
    )
    high_uri = _persist_sleep_run(
        run_root,
        run_name="high-run",
        stage_name="high",
        seconds=1.0,
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        admission_priority_resolver=lambda run_uri: 10 if run_uri == high_uri else 0,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        # Admit both runs before the daemon can project or place either one.
        with daemon._cycle_lock:
            client.submit(LocalDaemonAdmissionRequest("low-item", low_uri))
            client.submit(LocalDaemonAdmissionRequest("high-item", high_uri))
        _wait_for_supervisor_launch_count(config, expected=1)

        with sqlite3.connect(config.execution_database) as conn:
            live_run_uris = tuple(
                str(row[0])
                for row in conn.execute(
                    "SELECT run_uri FROM coordinator_assignments "
                    "WHERE state != 'released' ORDER BY assignment_id"
                )
            )
        assert live_run_uris == (high_uri,)
        assert client.wait("high-item", timeout_seconds=10).state is (
            LocalDaemonAdmissionState.SUCCEEDED
        )
        assert client.wait("low-item", timeout_seconds=10).state is (
            LocalDaemonAdmissionState.SUCCEEDED
        )
    finally:
        daemon.stop()


def test_admission_reconciliation_failure_does_not_stop_other_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "runs"
    unhealthy_uri = _persist_sleep_run(
        run_root,
        run_name="unhealthy-run",
        stage_name="unhealthy",
    )
    healthy_uri = _persist_sleep_run(
        run_root,
        run_name="healthy-run",
        stage_name="healthy",
    )
    original = LocalDaemonExecution.reconcile_admission

    def reconcile_admission(
        execution: LocalDaemonExecution,
        admission: LocalDaemonAdmission,
    ) -> LocalDaemonExecutionOutcome:
        if admission.run_uri == unhealthy_uri:
            raise QueueServiceError("simulated admission-local outage")
        return original(execution, admission)

    monkeypatch.setattr(
        LocalDaemonExecution, "reconcile_admission", reconcile_admission
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        unhealthy = client.submit(
            LocalDaemonAdmissionRequest("unhealthy-item", unhealthy_uri)
        )
        healthy = client.submit(
            LocalDaemonAdmissionRequest("healthy-item", healthy_uri)
        )
        assert client.wait("healthy-item", timeout_seconds=10).state is (
            LocalDaemonAdmissionState.SUCCEEDED
        )
        with sqlite3.connect(config.control_database) as conn:
            health = dict(
                conn.execute(
                    "SELECT admission_id, health FROM admission_reconciliation_health"
                )
            )
        assert health[unhealthy.admission_id] == "unavailable"
        assert health[healthy.admission_id] == "healthy"
        status = daemon.status()
        assert status.service_health == "degraded"
        assert status.service_diagnostic == "admission_reconciliation_degraded"
        assert not status.scheduling_ready
        assert daemon._service_error is None
    finally:
        daemon.stop()


def test_daemon_bypasses_run_limited_older_work_for_another_run(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    limited_uri = _persist_sleep_run(
        run_root,
        run_name="limited-run",
        stage_name="first",
        seconds=20,
        independent_stage_names=("first", "second"),
        max_parallel_stages=1,
    )
    other_uri = _persist_sleep_run(
        run_root,
        run_name="other-run",
        stage_name="other",
        seconds=20,
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        cpu_capacity=2,
        admission_priority_resolver=lambda run_uri: 10 if run_uri == limited_uri else 0,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        with daemon._cycle_lock:
            client.submit(LocalDaemonAdmissionRequest("limited-item", limited_uri))
            client.submit(LocalDaemonAdmissionRequest("other-item", other_uri))
        deadline = time.monotonic() + 30
        live_run_uris: set[str] = set()
        while time.monotonic() < deadline:
            with sqlite3.connect(config.execution_database) as conn:
                live_run_uris = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT run_uri FROM coordinator_assignments "
                        "WHERE state != 'released'"
                    )
                }
            if live_run_uris == {limited_uri, other_uri}:
                break
            time.sleep(0.02)
        assert live_run_uris == {limited_uri, other_uri}
        assert client.wait("other-item", timeout_seconds=60).state is (
            LocalDaemonAdmissionState.SUCCEEDED
        )
        assert client.wait("limited-item", timeout_seconds=60).state is (
            LocalDaemonAdmissionState.SUCCEEDED
        )
    finally:
        daemon.stop()


def test_daemon_overlaps_independent_local_stages_in_one_run(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_uri = _persist_sleep_run(
        run_root,
        run_name="one-run",
        stage_name="first",
        independent_stage_names=("first", "second"),
        seconds=20,
        max_parallel_stages=2,
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        cpu_capacity=2,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("one-run-item", run_uri))
        deadline = time.monotonic() + 30
        active_assignments = 0
        while time.monotonic() < deadline:
            with sqlite3.connect(config.execution_database) as conn:
                active_assignments = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM coordinator_assignments "
                        "WHERE run_uri = ? AND state != 'released'",
                        (run_uri,),
                    ).fetchone()[0]
                )
            if active_assignments == 2:
                break
            time.sleep(0.02)
        assert active_assignments == 2
        assert client.wait("one-run-item", timeout_seconds=60).state is (
            LocalDaemonAdmissionState.SUCCEEDED
        )
    finally:
        daemon.stop()


@pytest.mark.parametrize("retained_change", [None, "resources", "policy"])
def test_daemon_restart_joins_one_supervised_worker_before_reopening_capacity(
    tmp_path: Path,
    retained_change: str | None,
) -> None:
    run_root = tmp_path / "runs"
    run_uri = _persist_sleep_run(
        run_root,
        run_name="restart-run",
        stage_name="slow",
        seconds=3.0,
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    first_daemon = LocalDaemon(config)
    first_daemon.start()
    client = first_daemon.client_view(
        LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
    )
    client.submit(LocalDaemonAdmissionRequest("restart-item", run_uri))
    _wait_for_supervisor_launch_count(config, expected=1)
    supervisor_id, process_id = _running_supervisor_identity(config)

    first_daemon.stop()

    retained = SQLiteAgentJournal(
        config.agent_journal, _allow_initialize=False
    ).retained_claim_commands()
    assert len(retained) == 1
    assert isinstance(retained[0].assignment, ManagedAssignment)
    assert retained[0].assignment.run_uri == run_uri
    assert _running_supervisor_identity(config) == (supervisor_id, process_id)

    store = LocalRunStore(run_root)
    request_path = store.local_stage_worker_request_path(run_uri, "slow")
    original_request_bytes = request_path.read_bytes()
    if retained_change is not None:
        from loom.pipeline.execution import StageWorkerRequest
        from loom.diagnostics import render_diagnostic_failure
        from loom.diagnostics.diagnostic_failure import project_diagnostic_failure

        payload = store.read_stage_worker_request(run_uri, "slow", attempt=1)
        assert payload is not None
        runtime = cast(dict[str, Any], payload["resolved_runtime"])
        if retained_change == "resources":
            runtime["resources"]["entries"]["cpu"]["amount"] = 2
        else:
            runtime["resource_policy"] = {"account_for": [], "enforce": []}
            runtime["resource_selection"] = {"account_for": [], "enforce": []}
        StageWorkerRequest.from_dict(payload)
        store.write_stage_worker_request(run_uri, "slow", payload, attempt=1)
        conflicting_bytes = request_path.read_bytes()
        conflicting_mtime = request_path.stat().st_mtime_ns
        with pytest.raises(
            QueueServiceError, match="retained daemon owner state"
        ) as rejected:
            LocalDaemon(config).start()
        assert (
            "retained worker resource handoff differs from placement"
            in render_diagnostic_failure(project_diagnostic_failure(rejected.value))
        )
        assert request_path.read_bytes() == conflicting_bytes
        assert request_path.stat().st_mtime_ns == conflicting_mtime
        assert _supervisor_launch_count(config) == 1
        # The fixture restores the prior writer bytes; Loom never repairs a
        # conflicting request by overwriting it or allocating replacement work.
        request_path.write_bytes(original_request_bytes)
    replay_mtime = request_path.stat().st_mtime_ns
    replacement = LocalDaemon(config)
    start_finished = Event()
    start_failures: list[BaseException] = []

    def start_replacement() -> None:
        try:
            replacement.start()
        except BaseException as exc:  # pragma: no cover - asserted below.
            start_failures.append(exc)
        finally:
            start_finished.set()

    starter = Thread(target=start_replacement, name="replacement-local-daemon")
    starter.start()
    try:
        assert not start_finished.wait(0.2)
        with pytest.raises(QueueServiceError, match="not started"):
            replacement.client_view(
                LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
            ).status()
        assert _running_supervisor_identity(config) == (supervisor_id, process_id)
        _wait_for_thread(starter, timeout_seconds=10)
        assert start_failures == []

        replacement_client = replacement.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        completed = replacement_client.wait("restart-item", timeout_seconds=10)

        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
        assert _supervisor_launch_count(config) == 1
        assert request_path.read_bytes() == original_request_bytes
        assert request_path.stat().st_mtime_ns == replay_mtime
        assert (
            SQLiteAgentJournal(
                config.agent_journal, _allow_initialize=False
            ).retained_claim_commands()
            == ()
        )
        snapshot = SQLitePerRunAuthorityStore(run_uri).open_run(run_uri)
        assert snapshot.status is RunStatus.SUCCEEDED
        assert snapshot.stages[0].latest_commit is not None
        output = snapshot.stages[0].artifact_facts[0].artifact
        assert LocalArtifactStore(
            LocalRunStore(run_root).local_artifact_root(run_uri)
        ).load(output) == {"slept": 3.0}
        with sqlite3.connect(config.agent_journal) as conn:
            assert (
                int(
                    conn.execute(
                        "SELECT COUNT(*) FROM events "
                        "WHERE acknowledged_sequence IS NULL"
                    ).fetchone()[0]
                )
                == 0
            )
        execution = replacement._execution
        assert execution is not None
        observed = execution.providers["cpu"].observe(
            ObserveRequest(config.machine_id, "post-restart", "fresh")
        )
        assert observed.live_claim_ids == ()
        assert [atom.amount.numerator for atom in observed.atoms] == [1]
    finally:
        if starter.is_alive():
            starter.join(timeout=10)
        replacement.stop()


@pytest.mark.parametrize(
    (
        "requested_outcome",
        "retry_max_attempts",
        "expected_status",
        "retry_allowed",
    ),
    [
        ("cancelled", 2, StageStatus.CANCELLED, False),
        ("failed", 2, StageStatus.FAILED, True),
        ("failed", 1, StageStatus.FAILED, False),
    ],
)
def test_guarded_recovery_closes_exact_supervised_work_and_retains_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested_outcome: str,
    retry_max_attempts: int,
    expected_status: StageStatus,
    retry_allowed: bool,
) -> None:
    run_root = tmp_path / "runs"
    run_uri = _persist_sleep_run(
        run_root,
        run_name="recovery-run",
        stage_name="slow",
        seconds=30.0,
        retry_max_attempts=retry_max_attempts,
    )
    policy = AgentPolicyConfig(
        principals=(
            TransportPrincipalPolicy(
                "operator-credential",
                "operator",
                "operator",
                actions=("recover_unknown",),
            ),
        )
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    client = daemon.client_view(
        LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
    )
    execution = daemon._execution
    assert execution is not None
    assert execution.supervisor is not None
    original_launch = execution.supervisor.launch
    assert execution.supervisor is not None
    original_query = execution.supervisor.query
    launch_response_lost = False

    def launch_then_lose_response(launch: object):
        nonlocal launch_response_lost
        original_launch(launch)  # type: ignore[arg-type]
        launch_response_lost = True
        raise OSError("simulated lost supervisor launch response")

    def query_unknown_launch(launch: object):
        receipt = original_query(launch)  # type: ignore[arg-type]
        if launch_response_lost and receipt.state in {
            SupervisorLaunchState.STARTING,
            SupervisorLaunchState.RUNNING,
        }:
            return replace(
                receipt,
                state=SupervisorLaunchState.UNKNOWN,
                process_id=None,
            )
        return receipt

    monkeypatch.setattr(execution.supervisor, "launch", launch_then_lose_response)
    monkeypatch.setattr(execution.supervisor, "query", query_unknown_launch)
    submitted = client.submit(LocalDaemonAdmissionRequest("recovery-item", run_uri))
    _wait_for_supervisor_launch_count(config, expected=1)
    deadline = time.monotonic() + 5
    snapshot = SQLitePerRunAuthorityStore(run_uri).open_run(run_uri)
    while time.monotonic() < deadline:
        snapshot = SQLitePerRunAuthorityStore(run_uri).open_run(run_uri)
        retained = execution.coordinator.retained_assignments(
            agent_id=config.machine_id
        )
        if retained and execution._is_exact_retained_unknown(  # noqa: SLF001
            retained[0][0].assignment_id
        ):
            break
        time.sleep(0.02)
    retained = execution.coordinator.retained_assignments(agent_id=config.machine_id)
    assert len(retained) == 1
    assignment = retained[0][0]
    assert execution._is_exact_retained_unknown(  # noqa: SLF001
        assignment.assignment_id
    )
    assert config.agent_root is not None
    workspace = _ResidentAssignmentWorkspace(
        config.agent_root, assignment.assignment_id
    )
    launch_json = workspace.supervisor_launch_json()
    assert launch_json is not None
    launch = _launch_from_value(json.loads(launch_json))
    stage = next(item for item in snapshot.stages if item.stage_name == "slow")
    assert stage.status is StageStatus.SUBMITTED
    attempt = next(
        item for item in stage.attempts if item.attempt_id == assignment.attempt_id
    )
    detail = client.admission(submitted.admission_id)
    assignment_view = cast(Mapping[str, object], detail.owners["assignment"])
    assignment_facts = cast(list[Mapping[str, object]], assignment_view["assignments"])
    execution_view = cast(Mapping[str, object], detail.owners["execution"])
    execution_facts = cast(list[Mapping[str, object]], execution_view["journal"])
    authority_attempts = cast(list[Mapping[str, object]], detail.authority["attempts"])
    assert len(assignment_facts) == len(execution_facts) == len(authority_attempts) == 1
    assignment_fact = assignment_facts[0]
    execution_fact = execution_facts[0]
    authority_attempt = authority_attempts[0]
    attempt_revision = cast(Mapping[str, object], authority_attempt["revision"])
    assert assignment_fact["assignment_id"] == execution_fact["assignment_id"]
    assert assignment_fact["stage_name"] == authority_attempt["stage_name"]
    assert assignment_fact["attempt"] == authority_attempt["attempt"]
    assert assignment_fact["assignment_id"] == assignment.assignment_id
    assert execution_fact["process_execution_id"] == launch.process_execution_id
    assert execution_fact["execution_fence"] == launch.execution_fence
    assert attempt_revision["sequence"] == attempt.revision.sequence
    request = RecoverUnknownAssignment(
        recovery_id="recovery-contained-1",
        run_uri=cast(str, assignment_fact["run_uri"]),
        stage_name=cast(str, assignment_fact["stage_name"]),
        attempt=cast(int, assignment_fact["attempt"]),
        stage_work_id=cast(str, assignment_fact["stage_work_id"]),
        assignment_id=cast(str, assignment_fact["assignment_id"]),
        process_execution_id=cast(str, execution_fact["process_execution_id"]),
        execution_fence=cast(str, execution_fact["execution_fence"]),
        target=ManagedRecoveryTarget(
            cast(str, assignment_fact["agent_id"]),
            cast(str, assignment_fact["session_id"]),
        ),
        expected_state_version=cast(int, attempt_revision["sequence"]),
        requested_outcome=requested_outcome,
        consider_retry=True,
        reason="integration containment proof",
    )
    operator = daemon.operator_view(
        LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
    )
    try:
        stale = replace(
            request,
            recovery_id="recovery-stale-identity",
            execution_fence="stale-fence",
        )
        with pytest.raises(
            QueueConflictError, match="managed recovery target identity conflicts"
        ):
            operator.recover_unknown(stale)
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM recovery_operations").fetchone()[0]
                == 0
            )
        assert not daemon._recovery_fences_ordinary_terminal(  # noqa: SLF001
            assignment.assignment_id
        )

        receipt = operator.recover_unknown(request)
        replay = operator.recover_unknown(request)

        assert replay == receipt
        assert receipt["state"] == "closed"
        evidence = cast(Mapping[str, object], receipt["evidence"])
        assert evidence["kind"] == "managed_supervisor"
        assert evidence["state"] == "CONTAINED"
        assert receipt["retry_allowed"] is retry_allowed
        assert receipt["next_attempt"] == (2 if retry_allowed else None)
        assert receipt["physical_ownership"] == "retained"
        closed = SQLitePerRunAuthorityStore(run_uri).open_run(run_uri)
        closed_stage = next(item for item in closed.stages if item.stage_name == "slow")
        closed_attempt = next(
            item for item in closed_stage.attempts if item.attempt == 1
        )
        assert closed_attempt.status is expected_status
        if retry_allowed:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                closed = SQLitePerRunAuthorityStore(run_uri).open_run(run_uri)
                closed_stage = next(
                    item for item in closed.stages if item.stage_name == "slow"
                )
                if closed_stage.status is StageStatus.PENDING and any(
                    item.attempt == 2 for item in closed_stage.attempts
                ):
                    break
                time.sleep(0.02)
            assert closed_stage.status is StageStatus.PENDING, {
                "run_status": closed.status,
                "decisions": [item.to_dict() for item in closed_stage.retry_decisions],
                "admissions": [client.admission_for_queue_item("recovery-item").state],
                "service_diagnostic": client.status().service_diagnostic,
            }
            retry_attempt = next(
                item for item in closed_stage.attempts if item.attempt == 2
            )
            assert retry_attempt.status is StageStatus.PENDING
            assert any(
                item.stage_name == "slow" and item.attempt == 2
                for item in execution.stage_work_store.list_stage_work()
            )
        else:
            assert closed_stage.status is expected_status
            if requested_outcome == "cancelled":
                assert (
                    client.wait("recovery-item", timeout_seconds=10).state
                    is LocalDaemonAdmissionState.CANCELLED
                )
                assert (
                    SQLitePerRunAuthorityStore(run_uri).open_run(run_uri).status
                    is RunStatus.CANCELLED
                )
        assert len(closed_stage.retry_decisions) == 1
        detail = client.admission_for_queue_item("recovery-item")
        assert detail.run_uri == assignment.run_uri
        assert (
            len(
                SQLiteAgentJournal(
                    config.agent_journal, _allow_initialize=False
                ).retained_claim_commands()
            )
            == 1
        )
        assert _supervisor_launch_count(config) == 1
    finally:
        daemon.stop()

    replacement = LocalDaemon(config)
    replacement.start()
    try:
        assert _supervisor_launch_count(config) == 1
        replacement_execution = replacement._execution
        assert replacement_execution is not None
        observed = replacement_execution.providers["cpu"].observe(
            ObserveRequest(config.machine_id, "post-recovery", "retained")
        )
        assert observed.live_claim_ids == (assignment.claim_id,)
        if requested_outcome == "cancelled":
            assert (
                SQLitePerRunAuthorityStore(run_uri).open_run(run_uri).status
                is RunStatus.CANCELLED
            )
    finally:
        replacement.stop()


def test_resident_worker_loss_terminalizes_after_containment_without_output_or_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "runs"
    run_uri = _persist_sleep_run(
        run_root,
        run_name="lost-worker-run",
        stage_name="slow",
        seconds=30.0,
        retry_max_attempts=1,
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    release_entered = Event()
    release_allowed = Event()
    original_release_revision = managed_local._release_revision

    def delay_release_revision(**kwargs: object) -> str:
        release_entered.set()
        assert release_allowed.wait(10)
        return cast(Any, original_release_revision)(**kwargs)

    monkeypatch.setattr(managed_local, "_release_revision", delay_release_revision)
    client = daemon.client_view(
        LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
    )
    try:
        submitted = client.submit(
            LocalDaemonAdmissionRequest("lost-worker-item", run_uri)
        )
        _supervisor_id, worker_pid = _running_supervisor_identity(config)

        os.kill(worker_pid, signal.SIGKILL)
        assert release_entered.wait(10)
        try:
            daemon.reconcile_once()
            settling = client.admission(submitted.admission_id)
            assignment_view = cast(Mapping[str, object], settling.owners["assignment"])
            assignments = cast(
                list[Mapping[str, object]], assignment_view["assignments"]
            )
            assert settling.admission.state is LocalDaemonAdmissionState.ACTIVE
            assert len(assignments) == 1
            assert assignments[0]["state"] == "logical_released"
            assert (
                SQLitePerRunAuthorityStore(run_uri).open_run(run_uri).stages[0].status
                is StageStatus.FAILED
            )
        finally:
            release_allowed.set()
        terminal = client.wait("lost-worker-item", timeout_seconds=10)

        detail = client.admission(submitted.admission_id)
        snapshot = SQLitePerRunAuthorityStore(run_uri).open_run(run_uri)
        stage = next(item for item in snapshot.stages if item.stage_name == "slow")
        assignment_view = cast(Mapping[str, object], detail.owners["assignment"])
        assignments = cast(list[Mapping[str, object]], assignment_view["assignments"])
        assert terminal.state is LocalDaemonAdmissionState.FAILED
        assert detail.authority["state"] == "FAILED"
        assert stage.status is StageStatus.FAILED
        assert len(stage.attempts) == 1
        assert stage.attempts[0].reason is not None
        assert (
            stage.attempts[0].reason.message
            == "resident worker exited without a durable worker result"
        )
        assert len(assignments) == 1
        assert assignments[0]["state"] == "released"
        assert config.agent_root is not None
        worker_result = SQLiteAgentJournal(
            config.agent_root / "journal.sqlite"
        ).read_result(cast(str, assignments[0]["assignment_id"]))
        assert worker_result is not None
        assert worker_result.status is StageStatus.FAILED
        assert worker_result.exit_code is None
        assert worker_result.signal == signal.SIGKILL
        metadata = cast(
            dict[str, Any],
            thaw_plain_data(
                worker_result.executor_metadata, path="lost worker executor metadata"
            ),
        )
        request = metadata.pop("request")
        assert request["stage_name"] == "slow"
        assert request["executor_name"] == "local"
        assert str(tmp_path) not in json.dumps(request)
        assert metadata == {
            "process_created": True,
            "resource_controls": [
                {
                    "resource": "cpu",
                    "owner": "managed_provider",
                    "mechanism": None,
                    "disposition": "not_requested",
                }
            ],
            "worker_result": "missing",
        }
        run_store = LocalRunStore(run_root)
        assert run_store.read_artifact_index(run_uri) == {}
        assert run_store.read_stage_outputs(run_uri, "slow") is None
        assert config.agent_root is not None
        with sqlite3.connect(
            config.agent_root / "supervisor" / "supervisor.sqlite"
        ) as conn:
            supervisor_state = conn.execute(
                "SELECT state, exit_code, result_digest FROM launches"
            ).fetchone()
        assert supervisor_state is not None
        assert supervisor_state[0] == SupervisorLaunchState.CONTAINED.value
        assert supervisor_state[1] == -signal.SIGKILL
        assert supervisor_state[2] is not None
    finally:
        release_allowed.set()
        daemon.stop()


def test_guarded_recovery_rejects_active_managed_work_without_freezing_it(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_uri = _persist_sleep_run(
        run_root,
        run_name="active-recovery-run",
        stage_name="slow",
        seconds=30.0,
        retry_max_attempts=1,
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
        agent_policy=AgentPolicyConfig(
            principals=(
                TransportPrincipalPolicy(
                    "operator-credential",
                    "operator",
                    "operator",
                    actions=("recover_unknown",),
                ),
            )
        ),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        ).submit(LocalDaemonAdmissionRequest("active-recovery-item", run_uri))
        _wait_for_supervisor_launch_count(config, expected=1)
        authority = SQLitePerRunAuthorityStore(run_uri)
        deadline = time.monotonic() + 5
        snapshot = authority.open_run(run_uri)
        while time.monotonic() < deadline:
            snapshot = authority.open_run(run_uri)
            if snapshot.stages[0].status is StageStatus.RUNNING:
                break
            time.sleep(0.02)
        assert snapshot.stages[0].status is StageStatus.RUNNING
        execution = daemon._execution
        assert execution is not None
        ((assignment, _receipt),) = execution.coordinator.retained_assignments(
            agent_id=config.machine_id
        )
        assert config.agent_root is not None
        workspace = _ResidentAssignmentWorkspace(
            config.agent_root, assignment.assignment_id
        )
        launch_json = workspace.supervisor_launch_json()
        assert launch_json is not None
        launch = _launch_from_value(json.loads(launch_json))
        attempt = next(
            item
            for item in snapshot.stages[0].attempts
            if item.attempt_id == assignment.attempt_id
        )
        request = RecoverUnknownAssignment(
            recovery_id="active-managed-recovery",
            run_uri=run_uri,
            stage_name=assignment.stage_name,
            attempt=assignment.attempt,
            stage_work_id=assignment.stage_work_id,
            assignment_id=assignment.assignment_id,
            process_execution_id=launch.process_execution_id,
            execution_fence=launch.execution_fence,
            target=ManagedRecoveryTarget(assignment.agent_id, assignment.session_id),
            expected_state_version=attempt.revision.sequence,
            requested_outcome="cancelled",
            consider_retry=False,
            reason="must not close active work",
        )

        with pytest.raises(QueueConflictError, match="not in an exact unknown state"):
            daemon.operator_view(
                LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
            ).recover_unknown(request)
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM recovery_operations").fetchone()[0]
                == 0
            )
        assert not daemon._recovery_fences_ordinary_terminal(  # noqa: SLF001
            assignment.assignment_id
        )
        assert authority.open_run(run_uri).stages[0].status is StageStatus.RUNNING
    finally:
        daemon.stop()


def test_daemon_reconciles_skip_without_creating_an_assignment(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    _store, run_uri, _pipeline = _persist_single_stage_run(run_root, skip=True)
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        submitted = client.submit(LocalDaemonAdmissionRequest("skip-item", run_uri))
        completed = client.wait("skip-item", timeout_seconds=10)

        snapshot = authority.open_run(run_uri)
        detail = client.admission(submitted.admission_id)
        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
        assert snapshot.status is RunStatus.SUCCEEDED
        assert snapshot.stages[0].status is StageStatus.SKIPPED
        assignment_view = cast(Mapping[str, object], detail.owners["assignment"])
        assert assignment_view["assignments"] == []
    finally:
        daemon.stop()


@pytest.mark.parametrize("reported", [False, True])
def test_daemon_projects_stage_failure_to_authority_run_and_admission(
    tmp_path: Path,
    reported: bool,
) -> None:
    run_root = tmp_path / "runs"
    store, run_uri, _pipeline = _persist_single_stage_run(
        run_root,
        factory_target=(
            "tests.support.pipeline_execution_stages."
            + ("ReportedFailureStage" if reported else "FailingStage")
        ),
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=_launch_profile(),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        submitted = client.submit(LocalDaemonAdmissionRequest("failed-item", run_uri))
        completed = client.wait("failed-item", timeout_seconds=10)

        assert completed.state is LocalDaemonAdmissionState.FAILED
        assert authority.open_run(run_uri).status is RunStatus.FAILED
        server = LocalDaemonSocketServer(daemon, config.endpoint)
        server.start()
        try:
            socket_client = LocalDaemonSocketClient(config.endpoint)
            terminal = socket_client.wait(submitted.queue_item_id, timeout_seconds=10)
            assert terminal.state is LocalDaemonAdmissionState.FAILED
            detail = socket_client.admission(submitted.admission_id)

            def unavailable_authority(_run_uri: str) -> Never:
                raise OSError("socket authority read failure")

            daemon.config = replace(
                config, coordinator_authority_factory=unavailable_authority
            )
            unavailable_detail = socket_client.admission(submitted.admission_id)
            unavailable_view = cast(
                Mapping[str, object], unavailable_detail.owners["run_result"]
            )
            assert unavailable_view["availability"] == "unavailable"
            assert unavailable_view["diagnostic"] == "run_store_unavailable"
            assert unavailable_view["failures"] == ()
            diagnostic_failure = cast(
                Mapping[str, object], unavailable_view["diagnostic_failure"]
            )
            assert diagnostic_failure["type"] == "loom.queue.errors.QueueServiceError"
            links = cast(tuple[Mapping[str, object], ...], diagnostic_failure["links"])
            assert links[0]["relation"] == "cause"
            assert cast(Mapping[str, object], links[0]["record"])["message"] == (
                "socket authority read failure"
            )

            text_stdout = io.StringIO()
            assert (
                main(
                    [
                        "queue",
                        "daemon-admission",
                        "--endpoint",
                        str(config.endpoint),
                        submitted.admission_id,
                    ],
                    stdout=text_stdout,
                    stderr=io.StringIO(),
                )
                == 0
            )
            assert "failed-stage authority is unavailable" in text_stdout.getvalue()
            assert "socket authority read failure" in text_stdout.getvalue()

            json_stdout = io.StringIO()
            assert (
                main(
                    [
                        "queue",
                        "daemon-admission",
                        "--endpoint",
                        str(config.endpoint),
                        submitted.admission_id,
                        "--format",
                        "json",
                    ],
                    stdout=json_stdout,
                    stderr=io.StringIO(),
                )
                == 0
            )
            json_view = json.loads(json_stdout.getvalue())["result"]["owners"][
                "run_result"
            ]
            assert json_view["failures"] == []
            assert json_view["diagnostic_failure"] == thaw_plain_data(
                diagnostic_failure
            )
        finally:
            daemon.config = config
            server.stop()
        view = cast(Mapping[str, object], detail.owners["run_result"])
        assert view["availability"] == "available"
        assert view["state"] == "populated"
        assert view["freshness"] == "current"
        assert view["diagnostic"] is None
        assert view["diagnostic_failure"] is None
        persisted = store.read_stage_failure(run_uri, "build")
        assert persisted is not None
        assert thaw_plain_data(view["failures"]) == [persisted]
        failure = ExecutionFailure.from_dict(persisted)
        assert failure.run_uri == run_uri
        assert failure.stage_name == "build"
        assert failure.attempt == 1
        if reported:
            assert failure.to_dict()["details"] == {
                "domain_failure": {"record": {"items": [1, None, "safe"]}}
            }
            assert failure.traceback_path is None
            assert "private-native-" not in json_dumps_pretty(detail.to_dict())
            assert not list(store.local_run_dir(run_uri).rglob("traceback.txt"))
        else:
            assert "domain_failure" not in failure.details
            assert "stage failed intentionally" in failure.message
    finally:
        daemon.stop()


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "corrupt",
        "read_error",
        "missing_status_and_failure",
        "authority_unavailable",
    ],
)
def test_run_result_owner_projects_complete_failures_or_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run-1")
    store.create_run(run_uri)
    pipeline = {
        "name": "failed-stages",
        "stages": [
            {
                "name": name,
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.FailingStage"
                },
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
            for name in ("zeta", "alpha")
        ],
    }
    plan = plan_pipeline(
        PipelineSpec.from_config(pipeline),
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    assert plan.stage_order == ("zeta", "alpha")
    store.write_config_snapshot(
        run_uri, "resolved", json_dumps_pretty({"pipeline": pipeline})
    )
    config = _daemon_config(tmp_path)
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    admission = LocalDaemonAdmission(
        admission_id="admission",
        queue_item_id="item",
        coordinator_id="coordinator",
        run_uri=run_uri,
        intent_digest="digest",
        execution_owner="managed-stage",
        state=LocalDaemonAdmissionState.FAILED,
        accepted_at="2020-01-01T00:00:00Z",
        authority_operation_id="bind",
    )
    failures = []
    for stage_name in plan.stage_order:
        allocation = authority.allocate_stage_attempt(
            run_uri, stage_name, owner_id="fixture", lease_ttl_seconds=30
        )
        authority.transition_stage(
            run_uri,
            stage_name,
            from_status=StageStatus.RUNNING,
            to_status=StageStatus.FAILED,
        )
        assert allocation.lease is not None
        authority.release_lease(
            allocation.lease.lease_id,
            owner_id="fixture",
            fencing_token=allocation.lease.fencing_token,
        )
        store.write_stage_status(
            run_uri=run_uri,
            stage_name=stage_name,
            status=StageStatusRecord(
                run_uri=run_uri,
                stage_name=stage_name,
                status=StageStatus.FAILED,
                attempt=1,
                updated_at="2020-01-01T00:00:01Z",
            ),
        )
        failure = ExecutionFailure(
            schema_version=1,
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=1,
            failed_at="2020-01-01T00:00:02Z",
            executor="local",
            failure_type="stage_exception",
            message="stage failed",
            details={} if stage_name == "zeta" else {"domain_failure": None},
        )
        failures.append(failure.to_dict())
        store.write_stage_failure(run_uri, stage_name, failure.to_dict(), attempt=1)

    view = cast(
        Mapping[str, object],
        build_local_daemon_owner_views(config, (admission,))[0]["run_result"],
    )

    assert view == {
        "owner": "run-store",
        "availability": "available",
        "state": "populated",
        "observed_at": view["observed_at"],
        "freshness": "current",
        "diagnostic": None,
        "diagnostic_failure": None,
        "failures": failures,
    }

    if damage in {"missing", "missing_status_and_failure"}:
        store.local_stage_dir(run_uri, "alpha").joinpath("failure.json").unlink()
        if damage == "missing_status_and_failure":
            store.local_stage_dir(run_uri, "alpha").joinpath("status.json").unlink()
    elif damage == "corrupt":
        store.write_stage_failure(
            run_uri, "alpha", {**failures[-1], "unknown": True}, attempt=1
        )
    elif damage == "authority_unavailable":

        def unavailable_authority(run_uri: str) -> Never:
            raise OSError("injected authority read failure")

        config = replace(config, coordinator_authority_factory=unavailable_authority)
    else:
        read_failure = LocalRunStore.read_stage_failure

        def fail_later_read(
            self: LocalRunStore,
            run_uri: str,
            stage_name: str,
        ) -> dict[str, PlainData] | None:
            if stage_name == "alpha":
                raise OSError("injected unreadable failure")
            return read_failure(self, run_uri, stage_name)

        monkeypatch.setattr(LocalRunStore, "read_stage_failure", fail_later_read)
    unavailable = cast(
        Mapping[str, object],
        build_local_daemon_owner_views(config, (admission,))[0]["run_result"],
    )
    assert unavailable == {
        "owner": "run-store",
        "availability": "unavailable",
        "state": "unavailable",
        "observed_at": unavailable["observed_at"],
        "freshness": "unavailable",
        "diagnostic": "run_store_unavailable",
        "diagnostic_failure": unavailable["diagnostic_failure"],
        "failures": [],
    }
    diagnostic_failure = cast(Mapping[str, object], unavailable["diagnostic_failure"])
    assert diagnostic_failure["schema"] == "loom.diagnostic.v1"
    expected = {
        "missing": (
            "loom.queue.errors.QueueServiceError",
            "failed stage has no persisted failure",
        ),
        "corrupt": (
            "loom.pipeline.execution.errors.RunRequestError",
            "ExecutionFailure.from_dict: $: unknown field(s): unknown",
        ),
        "read_error": ("builtins.OSError", "injected unreadable failure"),
        "missing_status_and_failure": (
            "loom.queue.errors.QueueServiceError",
            "failed stage has no persisted failure",
        ),
        "authority_unavailable": (
            "loom.queue.errors.QueueServiceError",
            "failed-stage authority is unavailable",
        ),
    }
    assert (diagnostic_failure["type"], diagnostic_failure["message"]) == expected[
        damage
    ]
    from loom.diagnostics import render_diagnostic_failure

    rendered = render_diagnostic_failure(diagnostic_failure)
    if damage == "corrupt":
        assert "loom.serialization.errors.SchemaVersionError" in rendered
    if damage == "authority_unavailable":
        assert "injected authority read failure" in rendered


@pytest.mark.parametrize(
    "state",
    [
        "accepted",
        "granted",
        "running",
        "unknown",
        "terminal",
        "logical_released",
    ],
)
def test_startup_retains_only_the_exact_durable_claim_for_live_coordinator_state(
    tmp_path: Path, state: str
) -> None:
    config = _daemon_config(tmp_path, cpu_capacity=2)
    command = _retained_claim(config, assignment_id=f"retained-{state}")
    _coordinator_assignment(config, command.assignment.assignment_id, state)

    execution = _execution(config)
    observed = execution.providers["cpu"].observe(
        ObserveRequest("agent", "session", "one")
    )

    assert [atom.amount.numerator for atom in observed.atoms] == [1]
    assert observed.live_claim_ids == (command.assignment.claim_id,)


def test_startup_keeps_proven_released_coordinator_capacity_available(
    tmp_path: Path,
) -> None:
    config = _daemon_config(tmp_path, cpu_capacity=2)
    _coordinator_assignment(config, "released-assignment", "released")

    execution = _execution(config)
    observed = execution.providers["cpu"].observe(
        ObserveRequest("agent", "session", "one")
    )

    assert [atom.amount.numerator for atom in observed.atoms] == [2]
    assert observed.live_claim_ids == ()


def test_terminal_settlement_exempts_only_guarded_recovery_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _daemon_config(tmp_path)
    command = _retained_claim(
        config,
        assignment_id="retained-unknown",
        agent_id=config.machine_id,
    )
    assert isinstance(command.assignment, ManagedAssignment)
    _coordinator_assignment(
        config,
        command.assignment.assignment_id,
        "unknown",
        agent_id=config.machine_id,
        assignment=command.assignment,
    )
    execution = _execution(config)
    terminal = LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.FAILED)
    try:
        assert (
            execution._settled_terminal_outcome(  # noqa: SLF001
                command.assignment.run_uri,
                terminal,
                slurm_in_flight=False,
                slurm_diagnostic=None,
            ).state
            is LocalDaemonAdmissionState.ACTIVE
        )

        monkeypatch.setattr(
            execution,
            "_recovery_retains_assignment",
            lambda assignment_id: assignment_id == command.assignment.assignment_id,
        )

        assert (
            execution._settled_terminal_outcome(  # noqa: SLF001
                command.assignment.run_uri,
                terminal,
                slurm_in_flight=False,
                slurm_diagnostic=None,
            )
            is terminal
        )
    finally:
        execution.close()
        assert execution.supervisor is not None
        execution.supervisor.shutdown_for_test()


def test_startup_fails_closed_when_live_coordinator_state_lacks_exact_claim(
    tmp_path: Path,
) -> None:
    config = _daemon_config(tmp_path)
    _coordinator_assignment(config, "unknown-assignment", "unknown")

    with pytest.raises(Exception, match="lacks an exact resident bundle"):
        _execution(config)


def test_socket_diagnostic_redacts_unexpected_exception_text(tmp_path: Path) -> None:
    secret = "credential=do-not-return"

    class _FailingClient:
        def status(self) -> object:
            raise RuntimeError(secret)

    class _FailingDaemon:
        def client_view(self, _principal: object) -> _FailingClient:
            return _FailingClient()

    endpoint = tmp_path / "daemon.sock"
    server = LocalDaemonSocketServer(cast(LocalDaemon, _FailingDaemon()), endpoint)
    server.start()
    try:
        with pytest.raises(QueueServiceError) as raised:
            LocalDaemonSocketClient(endpoint).status()
    finally:
        server.stop()

    assert str(raised.value) == "local_daemon_internal_error"
    assert secret not in str(raised.value)


@pytest.mark.parametrize("legacy_projection", [False, True])
def test_stage_cancellation_finalizes_run_and_repairs_legacy_admissions_on_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy_projection: bool
) -> None:
    _, run_uri, _ = _persist_single_stage_run(
        tmp_path / "runs",
        factory_target="tests.support.pipeline_execution_stages.EarlyStopStage",
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = _daemon_config(tmp_path)
    LocalDaemon.initialize(config)
    original_projection = LocalDaemonExecution._terminal_outcome

    def project_like_previous_version(self, admission, plan, snapshot, scoped):
        if any(stage.status is StageStatus.CANCELLED for stage in snapshot.stages):
            return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.CANCELLED)
        return original_projection(self, admission, plan, snapshot, scoped)

    with monkeypatch.context() as legacy:
        if legacy_projection:
            legacy.setattr(
                LocalDaemonExecution, "_terminal_outcome", project_like_previous_version
            )
        daemon = LocalDaemon(config)
        daemon.start()
        try:
            client = daemon.client_view(
                LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
            )
            client.submit(LocalDaemonAdmissionRequest("stop-early", run_uri))
            assert (
                client.wait("stop-early", timeout_seconds=10).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            assert authority.open_run(run_uri).status is (
                RunStatus.RUNNING if legacy_projection else RunStatus.CANCELLED
            )
        finally:
            daemon.stop()

    replacement = LocalDaemon(config)
    replacement.start()
    try:
        deadline = time.monotonic() + 10
        while authority.open_run(run_uri).status is not RunStatus.CANCELLED:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        client = replacement.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        completed = client.wait("stop-early", timeout_seconds=10)
        assert completed.state is LocalDaemonAdmissionState.CANCELLED
        assert completed.cancellation_operation_id is not None
        assert (
            completed.cancellation_principal_id
            == f"coordinator:{completed.coordinator_id}"
        )
        assert authority.open_run(run_uri).stages[0].status is StageStatus.CANCELLED
        assert replacement._execution is not None
        assert (
            replacement._execution.coordinator.retained_assignments(
                agent_id=config.machine_id
            )
            == ()
        )
    finally:
        replacement.stop()


def test_stage_cancellation_contains_running_sibling_and_closes_downstream(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(store.root / "cancel-siblings")
    store.create_run(run_uri)
    started = tmp_path / "sibling-started"
    pipeline_config = {
        "name": "cancel-siblings",
        "stages": [
            {
                "name": name,
                "factory": {
                    "_target_": f"tests.support.pipeline_execution_stages.{factory}"
                },
                "config": config,
                "depends_on": dependencies,
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
            for name, factory, config, dependencies in (
                (
                    "sibling",
                    "SleepStage",
                    {"seconds": 30, "started_marker": str(started)},
                    [],
                ),
                ("stop", "EarlyStopStage", {"wait_for_marker": str(started)}, []),
                ("downstream", "JsonProducerStage", {}, ["stop"]),
            )
        ],
    }
    pipeline = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {name: {"executor": "local"} for name in pipeline.stage_names},
        },
    )
    store.write_config_snapshot(
        run_uri, "resolved", json_dumps_pretty({"pipeline": pipeline_config})
    )
    prepare_managed_local_runtime_record(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=pipeline,
        execution_requirements=_execution_requirements(pipeline),
        options={
            "run_uri": run_uri,
            "executor": "local",
            "execution": {"settings": {"max_parallel_stages": 2}},
        },
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = _daemon_config(tmp_path, cpu_capacity=2)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("cancel-siblings", run_uri))
        assert (
            client.wait("cancel-siblings", timeout_seconds=15).state
            is LocalDaemonAdmissionState.CANCELLED
        )
        snapshot = authority.open_run(run_uri)
        assert started.exists()
        assert snapshot.status is RunStatus.CANCELLED
        assert {stage.stage_name: stage.status for stage in snapshot.stages} == {
            name: StageStatus.CANCELLED for name in pipeline.stage_names
        }
        assert all(stage.latest_commit is None for stage in snapshot.stages)
        assert daemon._execution is not None
        assert (
            daemon._execution.coordinator.retained_assignments(
                agent_id=config.machine_id
            )
            == ()
        )
    finally:
        daemon.stop()


def test_late_cancellation_waits_for_local_provider_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run_uri, _ = _persist_single_stage_run(tmp_path / "runs")
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    release_entered, allow_release = Event(), Event()
    original_release = AtomResourceProvider.release

    def delayed_release(provider, command):
        release_entered.set()
        assert allow_release.wait(15)
        return original_release(provider, command)

    monkeypatch.setattr(AtomResourceProvider, "release", delayed_release)
    config = _daemon_config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("late-cancel", run_uri))
        assert release_entered.wait(10)
        deadline = time.monotonic() + 10
        while authority.open_run(run_uri).status is not RunStatus.SUCCEEDED:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert (
            client.admission_for_queue_item("late-cancel").state
            is LocalDaemonAdmissionState.ACTIVE
        )
        client.cancel("late-cancel")
        with pytest.raises(TimeoutError):
            client.wait("late-cancel", timeout_seconds=0.2)
        assert not allow_release.is_set()
        allow_release.set()
        assert (
            client.wait("late-cancel", timeout_seconds=10).state
            is LocalDaemonAdmissionState.SUCCEEDED
        )
        assert daemon._execution is not None
        assert (
            daemon._execution.coordinator.retained_assignments(
                agent_id=config.machine_id
            )
            == ()
        )
    finally:
        allow_release.set()
        daemon.stop()


def _daemon_config(tmp_path: Path, *, cpu_capacity: int = 1) -> LocalDaemonConfig:
    return LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=_launch_profile(),
        cpu_capacity=cpu_capacity,
    )


def _launch_profile() -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        Path.cwd(),
        Path(sys.executable),
        ResidentProfileDescriptor(
            "test-local", "v1", "test-project", "test-environment", "test-executor"
        ).to_dict(),
    )


def _owner_ids(config: LocalDaemonConfig) -> tuple[str, str]:
    with sqlite3.connect(config.control_database) as conn:
        coordinator_id = str(
            conn.execute(
                "SELECT value FROM root_metadata WHERE key = 'stable_id'"
            ).fetchone()[0]
        )
    assert config.agent_root is not None
    with sqlite3.connect(config.agent_root / "control.sqlite") as conn:
        agent_id = str(
            conn.execute(
                "SELECT value FROM root_metadata WHERE key = 'stable_id'"
            ).fetchone()[0]
        )
    return coordinator_id, agent_id


def _execution(config: LocalDaemonConfig) -> LocalDaemonExecution:
    initialize_local_daemon_owner_stores(config)
    assert config.agent_root is not None
    assert config.resident_worker_launch_profile is not None
    AgentProcessSupervisorService.initialize(
        config.agent_root,
        configuration=SupervisorLaunchConfiguration(
            "agent", (config.resident_worker_launch_profile,)
        ),
    )
    return LocalDaemonExecution(
        config=config,
        coordinator_id="coordinator",
        agent_id="agent",
        coordinator_epoch="epoch",
        scheduling_epoch="scheduling-epoch",
        cancellation_operation=lambda _admission_id: None,
        admission_activated=lambda _admission_id: None,
    )


def _retained_claim(
    config: LocalDaemonConfig, *, assignment_id: str, agent_id: str = "agent"
) -> ClaimCommand:
    atom = CapacityAtom(
        "cpu", f"{config.machine_id}:cpu", ExactQuantity(1), "count", ExactQuantity(1)
    )
    capacity = CapacityAtom(
        "cpu",
        f"{config.machine_id}:cpu",
        ExactQuantity(config.cpu_capacity),
        "count",
        ExactQuantity(1),
    )
    contract = ResourceClaimContractDescriptor("cpu", 1, "loom.cpu.claim.v1")
    descriptor = _configured_provider_descriptor("cpu", (capacity,))
    assignment = ManagedAssignment(
        assignment_id=assignment_id,
        run_uri="file:///retained-run",
        stage_work_id="work",
        stage_name="stage",
        attempt=1,
        attempt_id="attempt",
        agent_id=agent_id,
        session_id="session",
        offer_id="offer",
        claim_id=f"claim-{assignment_id}",
    )
    command = ClaimCommand(
        assignment,
        "prepare",
        ResourceClaim("cpu", contract, (atom,), 1),
        descriptor,
    )
    journal = SQLiteAgentJournal(config.agent_journal)
    journal.persist_request(assignment, {"request": "durable"})
    provider = AtomResourceProvider(descriptor, (contract,), (capacity,))
    assert (
        journal.prepare_composite(assignment, (command,), {"cpu": provider})
        is AssignmentState.PREPARED
    )
    assert journal.accept(assignment_id) is AssignmentState.ACCEPTED
    return command


def _coordinator_assignment(
    config: LocalDaemonConfig,
    assignment_id: str,
    state: str,
    *,
    agent_id: str = "agent",
    assignment: ManagedAssignment | None = None,
) -> None:
    initialize_local_daemon_owner_stores(config)
    import sqlite3

    with sqlite3.connect(config.execution_database) as conn:
        conn.execute(
            "INSERT INTO coordinator_assignments ("
            "assignment_id, identity_json, run_uri, stage_work_id, state, receipt_json, "
            "agent_id, session_id, offer_id, claim_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                assignment_id,
                (
                    "{}"
                    if assignment is None
                    else json.dumps(
                        _assignment_dict(assignment),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ),
                "file:///retained-run",
                "work",
                state,
                "{}",
                agent_id,
                "session",
                "offer",
                f"claim-{assignment_id}",
            ),
        )


def _persist_single_stage_run(
    run_root: Path,
    *,
    skip: bool = False,
    factory_target: str = ("tests.support.pipeline_execution_stages.JsonProducerStage"),
    resource_policy: Mapping[str, PlainData] | None = None,
) -> tuple[LocalRunStore, str, dict[str, object]]:
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "run-1")
    run_store.create_run(run_uri)
    pipeline_config: dict[str, object] = {
        "name": "daemon-single-stage",
        "stages": [
            {
                "name": "build",
                "factory": {"_target_": factory_target},
                "config": {"value": 1},
                "outputs": {
                    "data": {
                        "artifact_type": "json",
                        "codec_key": "json.v1",
                    }
                },
            }
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        selectors=PlanSelectors(skip_stages=("build",)) if skip else None,
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "stages": {"build": {"executor": "local"}}},
    )
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=run_store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        execution_requirements=_execution_requirements(spec),
        options=(
            None
            if resource_policy is None
            else {"resource_policy": dict(resource_policy)}
        ),
    )
    return run_store, run_uri, pipeline_config


def _persist_sleep_run(
    run_root: Path,
    *,
    run_name: str,
    stage_name: str,
    seconds: float = 0.5,
    retry_max_attempts: int | None = None,
    independent_stage_names: tuple[str, ...] | None = None,
    max_parallel_stages: int | None = None,
) -> str:
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / run_name)
    run_store.create_run(run_uri)
    stage_names = independent_stage_names or (stage_name,)
    pipeline_config = {
        "name": run_name,
        "stages": [
            {
                "name": current_stage_name,
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.SleepStage"
                },
                "config": {
                    "seconds": seconds,
                },
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
            for current_stage_name in stage_names
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    runtime_metadata: dict[str, PlainData] = {
        "executor": "local",
        "stages": {
            current_stage_name: {"executor": "local"}
            for current_stage_name in stage_names
        },
    }
    if retry_max_attempts is not None:
        runtime_metadata["reliability"] = {
            "retry": {"enabled": True, "max_attempts": retry_max_attempts}
        }
    run_store.write_runtime_metadata(run_uri, runtime_metadata)
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    options: dict[str, PlainData] = {"run_uri": run_uri, "executor": "local"}
    if retry_max_attempts is not None:
        options["reliability"] = {
            "retry": {
                "enabled": True,
                "max_attempts": retry_max_attempts,
            }
        }
    if max_parallel_stages is not None:
        options["execution"] = {
            "settings": {"max_parallel_stages": max_parallel_stages}
        }
    prepare_managed_local_runtime_record(
        store=run_store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        execution_requirements=_execution_requirements(spec),
        options=(
            None
            if retry_max_attempts is None and max_parallel_stages is None
            else options
        ),
    )
    SQLitePerRunAuthorityStore(run_uri).create_run(run_uri, status=RunStatus.RUNNING)
    return run_uri


def _wait_for_supervisor_launch_count(
    config: LocalDaemonConfig, *, expected: int
) -> None:
    deadline = time.monotonic() + 5
    assert config.agent_root is not None
    database = config.agent_root / "supervisor" / "supervisor.sqlite"
    observed = 0
    while time.monotonic() < deadline:
        with sqlite3.connect(database) as conn:
            observed = int(conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0])
        if observed >= expected:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"expected {expected} supervisor launches, observed {observed}"
    )


def _supervisor_launch_count(config: LocalDaemonConfig) -> int:
    assert config.agent_root is not None
    with sqlite3.connect(
        config.agent_root / "supervisor" / "supervisor.sqlite"
    ) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0])


def _running_supervisor_identity(config: LocalDaemonConfig) -> tuple[str, int]:
    deadline = time.monotonic() + 5
    assert config.agent_root is not None
    database = config.agent_root / "supervisor" / "supervisor.sqlite"
    while time.monotonic() < deadline:
        with sqlite3.connect(database) as conn:
            metadata = conn.execute(
                "SELECT value FROM metadata WHERE key = 'supervisor_id'"
            ).fetchone()
            launch = conn.execute(
                "SELECT state, pid FROM launches ORDER BY operation_id"
            ).fetchone()
        if (
            metadata is not None
            and launch is not None
            and str(launch[0]) == "running"
            and launch[1] is not None
        ):
            return str(metadata[0]), int(launch[1])
        time.sleep(0.01)
    raise AssertionError("supervisor launch did not remain running")


def _supervisor_process_ids(agent_root: Path) -> tuple[int, ...]:
    expected_root = str(agent_root.resolve() / "supervisor")
    matches: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if (
            len(argv) >= 4
            and argv[-3:-1] == [b"--serve", expected_root.encode()]
            and argv[-4].endswith(b"loom.queue._agent_process_supervisor")
        ):
            matches.append(int(entry.name))
    return tuple(sorted(matches))


def _wait_for_thread(thread: Thread, *, timeout_seconds: float) -> None:
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        raise AssertionError("replacement local daemon did not finish starting")
