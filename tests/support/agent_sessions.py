"""Shared resident agent, TLS endpoint, and run builders."""

from __future__ import annotations

from contextlib import suppress
import json
import os
from pathlib import Path
import sqlite3
import sys
from collections.abc import Mapping
from time import monotonic
from typing import Any, cast

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.execution.models import ExecutionFailure
from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.ready_stage import (
    SlurmJobPrivateFileProvider,
    SlurmReadyStageProfile,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    LocalArtifactStore,
    LocalRunStore,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import (
    ExecutionRequirement,
    LocalDaemon,
    LocalDaemonConfig,
    ResidentWorkerLaunchProfile,
    prepare_managed_local_runtime_record,
)
from loom.queue._remote_stage_execution import (
    ResidentProfileDescriptor,
    _RemoteExecutionReport,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    _resident_provider_descriptors,
)
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentProviderDescriptor,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    TransportPrincipalPolicy,
)
from loom.queue.errors import QueueConflictError, QueueError
from loom.scheduling import (
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData, json_dumps_pretty
from tests.support.mutual_tls import (
    certificate_fingerprint as _fingerprint,
    mutual_tls_credentials as _credentials,
)


def _local_launch_profile() -> ResidentWorkerLaunchProfile:
    return ResidentWorkerLaunchProfile(
        Path.cwd(),
        Path(sys.executable),
        ResidentProfileDescriptor(
            "test-local", "v1", "test-project", "test-environment", "test-executor"
        ).to_dict(),
    )


def _execution_requirements(pipeline: PipelineSpec) -> dict[str, ExecutionRequirement]:
    return {
        stage_name: ExecutionRequirement(
            "test-project", "test-environment", "test-executor"
        )
        for stage_name in pipeline.stage_names
    }


def _provider_descriptors(*kinds: str) -> tuple[AgentProviderDescriptor, ...]:
    return tuple(
        AgentProviderDescriptor(
            SchedulingComponentDescriptor(
                kind, 1, "1", f"test-{kind}-provider", f"{kind}-configuration"
            ),
            (ResourceClaimContractDescriptor(kind, 1, f"builtin-{kind}-claim-v1"),),
        )
        for kind in sorted(kinds)
    )


def _policy() -> AgentPolicyConfig:
    return AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "agent-credential",
                "agent-principal",
                "agent-a",
                ("default",),
                ("python",),
            ),
        )
    )


def _request(handshake: Mapping[str, object], agent_root_id: str) -> AgentRegistration:
    return AgentRegistration(
        idempotency_key="register-1",
        coordinator_id=str(handshake["coordinator_id"]),
        coordinator_epoch=str(handshake["coordinator_epoch"]),
        agent_root_id=agent_root_id,
        config_revision="config-1",
        inventory_revision="inventory-1",
        availability_revision="availability-1",
        declared_pools=("default",),
        declared_capabilities=("python",),
    )


def _remote_agent_root(tmp_path: Path, name: str = "remote-owner") -> Path:
    root = tmp_path / name / "agent"
    LocalDaemon.initialize_agent_root(root)
    return root


def _fresh_remote_agent_root(tmp_path: Path, name: str = "remote-owner") -> Path:
    """Return a path for the explicit profile-set remote initializer."""
    root = tmp_path / name / "agent"
    root.parent.mkdir(parents=True, exist_ok=True)
    return root


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


def _execute_available_assignment(
    agent: LocalDaemonAgentHttpClient,
    session_id: str,
    availability_revision: str,
) -> Mapping[str, PlainData]:
    """Wait for fixture preparation without mistaking an empty poll for work."""
    deadline = monotonic() + 20
    while True:
        result = agent.execute_one(
            session_id,
            availability_revision,
            sequence=agent.next_poll_sequence(session_id),
            wait_timeout_ms=5_000,
        )
        if result.get("result") != "wait":
            return result
        assert monotonic() < deadline, "fixture did not deliver an assignment"


def _reconcile_remote_agent_application(
    config: AgentTlsClientConfig,
    session_id: str,
    events: object,
) -> None:
    """Run application B in another interpreter and replay the retained work."""

    queue = cast(Any, events)
    agent = LocalDaemonAgentHttpClient(config)
    try:
        session = agent._require_journal().session(session_id)  # noqa: SLF001
        profile = config.resident_profiles[0]
        offer = AgentOffer(
            session.session_id,
            session.coordinator_epoch,
            session.config_revision,
            session.inventory_revision,
            session.availability_revision,
            1,
            0,
            30,
            _resident_provider_descriptors(profile, session.agent_id),
            resident_profiles=(profile.descriptor,),
        )
        blocked_offer = blocked_poll = False
        try:
            agent.publish_offer(offer, idempotency_key="offer-before-fresh-replay")
        except QueueConflictError:
            blocked_offer = True
        try:
            agent.wait_for_work(
                session.session_id,
                session.availability_revision,
                sequence=1,
                wait_timeout_ms=1,
            )
        except QueueConflictError:
            blocked_poll = True
        replayed = agent.resume_retained_work()
        released = agent._require_journal().session(session_id)  # noqa: SLF001
        agent.publish_offer(
            AgentOffer(
                released.session_id,
                released.coordinator_epoch,
                released.config_revision,
                released.inventory_revision,
                released.availability_revision,
                1,
                0,
                30,
                _resident_provider_descriptors(profile, released.agent_id),
                resident_profiles=(profile.descriptor,),
            ),
            idempotency_key="offer-after-fresh-replay",
        )
        supervisor = agent._supervisor  # noqa: SLF001 - continuity assertion
        assert supervisor is not None
        queue.put(
            (
                "replayed",
                os.getpid(),
                blocked_offer,
                blocked_poll,
                tuple(item["state"] for item in replayed),
                supervisor.supervisor_id,
            )
        )
    except Exception as exc:  # pragma: no cover - surfaced by the parent assertion
        queue.put(("error", os.getpid(), repr(exc)))
    finally:
        agent.close()


@pytest.fixture(autouse=True)
def _shutdown_detached_remote_supervisors(
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """Every integration test that initializes a detached owner also stops it."""

    initialized: list[AgentTlsClientConfig] = []
    original = LocalDaemonAgentHttpClient.initialize_agent_root.__func__

    def initialize(
        cls: type[LocalDaemonAgentHttpClient], config: AgentTlsClientConfig
    ) -> None:
        original(cls, config)
        initialized.append(config)

    monkeypatch.setattr(
        LocalDaemonAgentHttpClient, "initialize_agent_root", classmethod(initialize)
    )
    yield
    for config in initialized:
        with suppress(QueueError):
            client = LocalDaemonAgentHttpClient(config)
            try:
                assert client._supervisor is not None  # noqa: SLF001
                client._supervisor.shutdown_for_test()  # noqa: SLF001
            finally:
                client.close()


def _prepare_remote_producer_run(
    store: LocalRunStore,
    *,
    run_name: str,
    machine_id: str,
    value: int,
    requirement: ExecutionRequirement | None = None,
    resource_entries: Mapping[str, object] | None = None,
    account_for: str | list[str] = "all",
    sequential: bool = False,
    enforce: tuple[str, ...] = (),
    native_failure: bool = False,
    reported_failure: bool = False,
    shared_scope: Mapping[str, PlainData] | None = None,
    stage_factory: str | None = None,
    stage_config: Mapping[str, object] | None = None,
    independent_stages: int = 1,
) -> tuple[str, SQLitePerRunAuthorityStore]:
    run_uri = path_to_run_uri(store.root / run_name)
    store.create_run(run_uri)
    pipeline_config = {
        "name": run_name,
        "stages": [
            {
                "name": "build",
                "factory": {
                    "_target_": stage_factory or (
                        "tests.support.pipeline_execution_stages.NestedFailureStage"
                        if native_failure
                        else "tests.support.pipeline_execution_stages.ReportedFailureStage"
                        if reported_failure
                        else "tests.support.pipeline_execution_stages.JsonProducerStage"
                    )
                },
                "config": {
                    "value": value,
                    **({"structured_float": True} if reported_failure else {}),
                    **(stage_config or {}),
                },
                "resources": {
                    "entries": (
                        resource_entries
                        if resource_entries is not None
                        else {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                    )
                },
                "placement": {"target": machine_id},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
        ],
    }
    if independent_stages > 1:
        pipeline_config["stages"] = [
            {**pipeline_config["stages"][0], "name": f"build-{index}"}
            for index in range(independent_stages)
        ]
    if sequential:
        pipeline_config["stages"].append(
            {
                "name": "consume",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage"
                },
                "depends_on": ["build"],
                "inputs": {"data": "build.data"},
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "placement": {"target": machine_id},
                "outputs": {"text": {"artifact_type": "text", "codec_key": "text.v1"}},
            }
        )
    if shared_scope is not None:
        from loom.queue.shared_execution import bind_snapshot
        bind_snapshot({"pipeline": pipeline_config}, shared_scope)
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        stage_state=store,
        artifact_index=store,
        plans=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "stages": {"build": {"executor": "local"}}},
    )
    store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        options={
            "resource_policy": {"account_for": account_for, "enforce": list(enforce)},
            **({"execution": {"settings": {"max_parallel_stages": independent_stages}}} if independent_stages > 1 else {}),
        },
        execution_requirements={
            stage_name: (
                requirement
                or ExecutionRequirement(
                    "test-project", "test-environment", "test-executor"
                )
            )
            for stage_name in spec.stage_names
        },
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    return run_uri, authority


def _prepare_remote_sleep_run(
    store: LocalRunStore, *, run_name: str, machine_id: str, seconds: float = 30
) -> tuple[str, SQLitePerRunAuthorityStore]:
    run_uri = path_to_run_uri(store.root / run_name)
    store.create_run(run_uri)
    pipeline_config = {
        "name": run_name,
        "stages": [
            {
                "name": "slow",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.SleepStage"
                },
                "config": {"seconds": seconds},
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "placement": {"target": machine_id},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        stage_state=store,
        artifact_index=store,
        plans=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "stages": {"slow": {"executor": "local"}}},
    )
    store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        execution_requirements={
            stage_name: ExecutionRequirement("project-1", "environment-1", "executor-1")
            for stage_name in spec.stage_names
        },
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    return run_uri, authority


def _prepare_gpu_environment_run(
    store: LocalRunStore,
    *,
    run_name: str,
    preferred_models: tuple[str, ...],
    include_cpu_preprocess: bool = False,
    fallback_after_seconds: int | None = None,
    target: str | None = None,
    capture_requirement: ExecutionRequirement | None = None,
    delay_seconds: float = 0,
    enforce_gpu: bool = True,
) -> tuple[str, SQLitePerRunAuthorityStore]:
    run_uri = path_to_run_uri(store.root / run_name)
    store.create_run(run_uri)
    stages: list[dict[str, object]] = []
    if include_cpu_preprocess:
        stages.append(
            {
                "name": "preprocess",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages."
                        "EnvironmentProducerStage"
                    )
                },
                "resources": {
                    "entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}
                },
                "placement": {"target": "machine-A"},
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            }
        )
    preference: dict[str, object] = {
        "kind": "resource_attribute_order",
        "resource": "gpu",
        "attribute": "model",
        "values": list(preferred_models),
    }
    if fallback_after_seconds is not None:
        preference["fallback_after_seconds"] = fallback_after_seconds
    placement: dict[str, object] = {"preferences": [preference]}
    if target is not None:
        placement["target"] = target
    capture: dict[str, object] = {
        "name": "capture",
        "factory": {
            "_target_": (
                "tests.support.pipeline_execution_stages.EnvironmentProducerStage"
            )
        },
        "config": {"delay_seconds": delay_seconds},
        "resources": {
            "entries": {
                "gpu": {
                    "kind": "gpu",
                    "amount": 1,
                    "unit": "count",
                    "attributes": {"allocation_mode": "exclusive"},
                }
            }
        },
        "placement": placement,
        "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
    }
    if include_cpu_preprocess:
        capture["depends_on"] = ["preprocess"]
    stages.append(capture)
    pipeline_config = {
        "name": run_name,
        "stages": stages,
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        stage_state=store,
        artifact_index=store,
        plans=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {stage.name: {"executor": "local"} for stage in spec.stages},
        },
    )
    store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=spec,
        options={
            "stage_options": {
                "capture": {
                    "resource_policy": {
                        "enforce": ["gpu"] if enforce_gpu else [],
                    }
                }
            }
        },
        execution_requirements={
            **_execution_requirements(spec),
            "capture": capture_requirement
            or ExecutionRequirement(
                "test-project", "test-environment", "test-executor"
            ),
        },
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    return run_uri, authority


def _sqlite_dump(path: Path) -> tuple[str, ...]:
    with sqlite3.connect(path) as conn:
        return tuple(conn.iterdump())


def _nested_report_detail(depth: int) -> Any:
    value: Any = 0.5
    for _ in range(depth):
        value = {"nested": value}
    return value


def _failure_report(details: Mapping[str, PlainData]) -> _RemoteExecutionReport:
    failure = ExecutionFailure(
        1,
        "loom-agent:assignment-1",
        "build",
        1,
        "2020-01-01T00:00:01Z",
        "local",
        "stage_exception",
        "stage failed",
        details=details,
    )
    return _RemoteExecutionReport(
        assignment_id="assignment-1",
        stage_name="build",
        attempt=1,
        status=StageStatus.FAILED,
        started_at="2020-01-01T00:00:00Z",
        finished_at=failure.failed_at,
        executor_name="local",
        failure_type=failure.failure_type,
        message=failure.message,
        failure=failure,
        schema_version=6,
        executor_metadata={},
    )


@pytest.fixture
def native_control_endpoint(tmp_path: Path):  # type: ignore[no-untyped-def]
    """A coordinator-only TLS service; the native client has no agent root."""
    credentials = _credentials(tmp_path / "tls")
    policy = AgentPolicyConfig(
        agents=_policy().agents,
        principals=(
            TransportPrincipalPolicy("client-credential", "client-principal", "client"),
        ),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        None,
        tmp_path / "runs",
        None,
        cpu_capacity=0,
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                _fingerprint(
                    credentials["other"].with_suffix(".crt")
                ): "client-credential",
                _fingerprint(
                    credentials["agent"].with_suffix(".crt")
                ): "agent-credential",
            },
        ),
    )
    server.start()
    connection_path = tmp_path / "client.yaml"
    connection_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.coordinator-client",
                "transport": {
                    "kind": "https",
                    "url": f"https://localhost:{server.port}",
                    "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
                    "certificate_path": str(credentials["other"].with_suffix(".crt")),
                    "private_key_path": str(credentials["other"].with_suffix(".key")),
                },
            }
        )
    )
    connection_path.chmod(0o600)
    try:
        yield daemon, server, connection_path, credentials
    finally:
        server.stop()
        daemon.stop()


def _slurm_bootstrap_profile(tmp_path: Path) -> SlurmReadyStageProfile:
    result_root = tmp_path / "shared-results"
    result_root.mkdir(exist_ok=True)
    return SlurmReadyStageProfile(
        result_storage={
            "agent_root": str(result_root),
            "compute_root": str(result_root),
            "retention_bytes": 1024 * 1024 * 1024,
        },
        profile_id="training",
        partition="gpu",
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
            fixed_path=str(tmp_path / "capability"),
            descriptor="fake-prolog-v1",
            helper_argv=(
                sys.executable,
                str(
                    Path(__file__).parent
                    / "slurm_job_private_helper.py"
                ),
            ),
        ),
    )
