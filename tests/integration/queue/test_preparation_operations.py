"""Durable preparation through native coordinator admission and worker execution."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Mapping
import json
from pathlib import Path
import sqlite3
import sys
import socket
from threading import Event
from concurrent.futures import ThreadPoolExecutor
import io
from time import monotonic, sleep
from typing import Any

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError
from loom.artifacts import ArtifactRef
from loom.serialization import ensure_plain_data, stable_json_bytes
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.io.uris import uri_to_path
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.cleanup import (
    CleanupManagedRoot,
    CleanupSafetyReason,
    CleanupTargetKind,
    CleanupTargetRef,
    assess_local_target_safety,
)
from loom.preparation import CoordinatorPreparation
from loom.queue import (
    CoordinatorSchedulingReload,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonOperation,
    LocalDaemonSocketClient,
    LocalDaemonSocketServer,
)
from loom.queue.deployment import load_coordinator_service_config
from loom.queue.preparation import PreparationSource, PrepareRunRequest
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.managed_local_preparation import prepare_managed_run
from loom.pipeline.orchestration import ExecutionRequirement
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue._preparation_operations import PreparationNotAccepted
from loom.queue._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    ResidentExecutionProfile,
    _ResidentAssignmentWorkspace,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    _resident_provider_descriptors,
)
from loom.queue.agent_sessions import AgentOffer, AgentRegistration
from loom.queue.preparation import PREPARATION_INPUT_CAPABILITY, PREPARATION_STAGED_INPUT_CAPABILITY
from loom.queue.resident_readiness import (
    ResidentReadinessRequirements,
    qualified_resident_profile,
)
from tests.support.mutual_tls import certificate_fingerprint, mutual_tls_credentials
from loom.queue._managed_local import (
    AtomResourceProvider,
    ManagedAssignment,
    SQLiteAgentJournal,
)
from loom.cli.main import main


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _service(tmp_path: Path, *, mode: str = "shared"):
    pytest.importorskip("weave")
    repository = Path(__file__).resolve().parents[3]
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "pipeline.yaml").write_text(
        json.dumps(
            {
                "pipeline": {
                    "name": "example",
                    "stages": [
                        {
                            "name": "produce",
                            "factory": {
                                "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                            },
                            "config": {"value": 41},
                            "resources": {
                                "entries": {
                                    "cpu": {"kind": "cpu", "amount": 1, "unit": "count"}
                                }
                            },
                            "outputs": {
                                "data": {
                                    "artifact_type": "json",
                                    "codec_key": "json.v1",
                                }
                            },
                        }
                    ],
                },
                "runtime": {"executor": "local"},
            }
        )
    )
    agent = tmp_path / "agent.json"
    agent.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.local-agent-service",
                "agent_root": "deployment/agent",
                "resident_profiles": [
                    {
                        "descriptor": {
                            "profile_id": "existing",
                            "revision": "v1",
                            "project_fingerprint": "project",
                            "environment_fingerprint": "environment",
                            "executor_fingerprint": "executor",
                        },
                        "project_root": str(repository),
                        "python_executable": sys.executable,
                        "cpu_capacity": 1,
                        "memory_capacity_bytes": 0,
                        "gpu_devices": [],
                        "environment": {},
                        "preparation_shared_roots": {"projects": "snapshots"},
                        "readiness": {"imports": ["loom", "loom.preparation", "weave"]},
                    }
                ],
            }
        )
    )
    agent.chmod(0o600)
    coordinator = tmp_path / "coordinator.json"
    coordinator.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.coordinator-service",
                "deployment_root": "deployment",
                "run_store_root": "runs",
                "machine_id": "coordinator",
                "poll_interval_seconds": 0.01,
                "max_accepted_time_step_seconds": 60,
                "local_agent": {"config": "agent.json", "env_file": None},
                "remote_profiles": [],
                "agent_server": None,
                "agent_policy": {
                    "revision": "v1",
                    "agents": [],
                    "principals": [],
                    "local_owner": {
                        "actions": ["scheduling_reload"],
                        "agent_ids": [],
                        "pools": [],
                    },
                },
                "authority": {"kind": "embedded"},
                "preparation": {
                    "source_roots": {
                        "projects": {
                            "path": "projects",
                            "shared_snapshot_root": "snapshots",
                        }
                    },
                    "profiles": {
                        "existing-project": {
                            "resident_profile_id": "existing",
                            "allowed_source_roots": ["projects"],
                            "source_modes": ["shared"],
                            "runtime_options": {"executor": "local"},
                        }
                    },
                },
            }
        )
    )
    coordinator.chmod(0o600)
    if mode == "staged":
        authored_agent = json.loads(agent.read_text())
        profile = authored_agent["resident_profiles"][0]
        profile.pop("preparation_shared_roots")
        profile["readiness"]["preparation_staged"] = True
        agent.write_text(json.dumps(authored_agent))
        authored = json.loads(coordinator.read_text())
        authored["preparation"]["source_roots"]["projects"].pop("shared_snapshot_root")
        authored["preparation"]["profiles"]["existing-project"]["source_modes"] = [mode]
        coordinator.write_text(json.dumps(authored))
    return load_coordinator_service_config(coordinator)


def _request(mode: str = "shared") -> PrepareRunRequest:
    return PrepareRunRequest(
        "prepare-1",
        "target-1",
        PreparationSource(mode, "projects", ".", ("pipeline.yaml",)),
        "pipeline.yaml",
        "existing-project",
    )


@pytest.mark.parametrize("restart_after_authority_commit", (False, True))
def test_prepared_native_failed_admission_explicit_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restart_after_authority_commit: bool,
) -> None:
    from weave import compose_config
    from loom.pipeline.status import StageStatus
    from loom.pipeline.stores import AuthorityStoreError, LifecycleReason
    from loom.pipeline.stores.authority import ExecutionFence
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from loom.queue.local_daemon_execution import LocalDaemonExecution

    service = _service(tmp_path)
    pipeline_path = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(pipeline_path.read_text())
    stage = authored["pipeline"]["stages"][0]
    other = {
        **json.loads(json.dumps(stage)),
        "name": "other",
        "depends_on": ["produce"],
    }
    authored["pipeline"]["stages"].append(other)
    stage["factory"]["_target_"] = (
        "tests.support.pipeline_execution_stages.FailOnceThenProduceStage"
    )
    stage["config"] = {"marker_path": str(tmp_path / "failed-once")}
    pipeline_path.write_text(json.dumps(authored))
    assert service.daemon.resident_worker_launch_profile is not None
    profile = ResidentProfileDescriptor.from_dict(
        service.daemon.resident_worker_launch_profile.descriptor
    )
    prepared = prepare_managed_run(
        service,
        compose_config(pipeline_path),
        "retry-target",
        execution_requirements={
            name: ExecutionRequirement(
                profile.project_fingerprint,
                profile.environment_fingerprint,
                profile.executor_fingerprint,
            )
            for name in ("produce", "other")
        },
    )
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon)
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    daemon.start()
    server.start()
    store = LocalRunStore(service.daemon.run_store_root)
    authority = SQLitePerRunAuthorityStore(prepared.run_uri)
    ordinary = LocalDaemonAdmissionRequest("retry-item", prepared.run_uri)
    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            admitted = client.submit(ordinary)
            failed = client.wait("retry-item", timeout_seconds=25)
            assert failed.state.value == "FAILED", failed
            snapshot = authority.open_run(prepared.run_uri)
            first_attempt = next(
                item for item in snapshot.stages if item.stage_name == "produce"
            ).attempts[0]
            assert first_attempt.status is StageStatus.FAILED
            retained_result = store.read_stage_worker_result(
                prepared.run_uri, "produce", attempt=1
            )
            assert retained_result is not None
            assert service.daemon.agent_root is not None
            with sqlite3.connect(
                uri_to_path(prepared.run_uri) / ".loom" / "authority.sqlite3"
            ) as conn:
                first_assignment = conn.execute(
                    "SELECT assignment_id FROM managed_attempt_bindings WHERE attempt_id = 'produce-1'"
                ).fetchone()[0]
            workspace = _ResidentAssignmentWorkspace(
                service.daemon.agent_root, first_assignment
            )
            retained_request = workspace.request()
            retained_workspace_result = (
                workspace.root / "worker-result.json"
            ).read_bytes()
            assert client.submit(ordinary) == failed
            with pytest.raises(CoordinatorClientError):
                client.submit(
                    LocalDaemonAdmissionRequest(
                        "retry-item",
                        prepared.run_uri,
                        retry_failed_revision=failed.revision + 1,
                    )
                )
            request = LocalDaemonAdmissionRequest(
                "retry-item",
                prepared.run_uri,
                retry_failed_revision=failed.revision,
            )
            if restart_after_authority_commit:
                resume = LocalDaemonExecution.resume_failed_admission

                def interrupted_resume(self, *args, **kwargs):
                    resume(self, *args, **kwargs)
                    raise OSError("injected interruption after atomic authority retry")

                monkeypatch.setattr(
                    LocalDaemonExecution, "resume_failed_admission", interrupted_resume
                )
                with pytest.raises(CoordinatorClientError):
                    client.submit(request)
                server.stop()
                daemon.stop()
                monkeypatch.setattr(
                    LocalDaemonExecution, "resume_failed_admission", resume
                )
                daemon = LocalDaemon(service.daemon)
                server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
                daemon.start()
                server.start()

        def submit_retry():
            with CoordinatorClient.from_unix_socket(
                service.daemon.endpoint
            ) as concurrent:
                return concurrent.submit(request)

        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: submit_retry(), range(2)))
        assert {item.admission_id for item in replies} == {admitted.admission_id}
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            try:
                completed = client.wait("retry-item", timeout_seconds=25)
            except TimeoutError:
                daemon.reconcile_once()
                raise
            assert completed.state.value == "SUCCEEDED", (
                completed,
                daemon._service_error,
            )
            assert client.submit(request) == completed
            assert client.submit(ordinary) == completed
        final = authority.open_run(prepared.run_uri)
        final_stages = {item.stage_name: item for item in final.stages}
        assert [attempt.attempt for attempt in final_stages["produce"].attempts] == [
            1,
            2,
        ]
        assert final_stages["produce"].attempts[0] == first_attempt
        assert len(final_stages["other"].attempts) == 1
        assert final_stages["other"].status is StageStatus.SUCCEEDED
        assert workspace.request() == retained_request
        assert (
            workspace.root / "worker-result.json"
        ).read_bytes() == retained_workspace_result
        assert (
            store.read_stage_worker_result(prepared.run_uri, "produce", attempt=2)
            is not None
        )
        with sqlite3.connect(
            uri_to_path(prepared.run_uri) / ".loom" / "authority.sqlite3"
        ) as conn:
            rows = conn.execute(
                "SELECT assignment_id, attempt_id, fence FROM managed_attempt_bindings WHERE attempt_id LIKE 'produce-%' ORDER BY attempt_id"
            ).fetchall()
        assert len(rows) == 2
        assert rows[0][2] != rows[1][2]
        with pytest.raises(AuthorityStoreError, match="terminal result conflicts"):
            authority.record_managed_attempt_terminal(
                prepared.run_uri,
                fence=ExecutionFence(*rows[0]),
                status=StageStatus.CANCELLED,
                reason=LifecycleReason(code="worker.cancelled"),
            )
    finally:
        server.stop()
        daemon.stop()


def _cli_result(*arguments: str, expected_exit: int = 0):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["queue", *arguments, "--format", "json"], stdout=stdout, stderr=stderr)
    assert code == expected_exit, (stdout.getvalue(), stderr.getvalue())
    return json.loads(stdout.getvalue())


def _result(operation: LocalDaemonOperation) -> Mapping[str, Any]:
    assert operation.kind == "prepare_run"
    assert isinstance(operation.result, Mapping)
    return operation.result


@pytest.mark.parametrize("mode", ("shared", "staged"))
def test_native_unix_prepare_publish_submit_and_reconnect(tmp_path: Path, mode: str) -> None:
    service = _service(tmp_path, mode=mode)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    daemon.start()
    server.start()
    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            accepted = client.prepare_run(_request(mode))
            assert accepted.state == "pending"
            completed = client.wait_operation(
                accepted.operation_id, timeout_seconds=25
            ).operation
            assert completed.state == "applied", (
                completed.to_dict(),
                daemon._service_error,
            )
            receipt = _result(completed)["prepared_run"]
            assert _result(completed)["preflight_status"] == "PASS"
            assert _result(completed)["report_ref"] is not None
            assert client.prepare_run(_request(mode)) == completed
            store = LocalRunStore(service.daemon.run_store_root)
            assert (
                store.read_stage_worker_result(receipt["run_uri"], "produce", attempt=1)
                is None
            )
            assert _result(completed)["preparation_admission_id"] != accepted.operation_id
            coordinator_id = _result(completed)["coordinator_id"]
        with CoordinatorClient.from_unix_socket(
            service.daemon.endpoint, expected_coordinator_id=coordinator_id
        ) as client:
            assert client.operation(accepted.operation_id) == completed
            admitted = client.submit(
                LocalDaemonAdmissionRequest("execute-target", receipt["run_uri"])
            )
            outcome = client.wait("execute-target", timeout_seconds=25)
            assert outcome.state.value == "SUCCEEDED", outcome
            detail = client.admission(admitted.admission_id)
            assert detail.admission.run_uri == receipt["run_uri"]
            worker_result = StageWorkerResult.from_dict(
                store.read_stage_worker_result(receipt["run_uri"], "produce", attempt=1)
            )
            assert LocalArtifactStore(
                store.local_artifact_root(receipt["run_uri"])
            ).load(worker_result.outputs["data"]) == {"value": 41}
    finally:
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("missing", ("capability", "selected_profile", "staged_capability"))
def test_unqualified_or_different_profile_cannot_take_preparation_but_runs_ordinary_work(
    tmp_path: Path, missing: str
) -> None:
    mode = "staged" if missing == "staged_capability" else "shared"
    service = _service(tmp_path, mode=mode)
    config_path = tmp_path / "coordinator.json"
    if missing in {"capability", "staged_capability"}:
        agent_path = tmp_path / "agent.json"
        authored = json.loads(agent_path.read_text())
        if missing == "capability":
            authored["resident_profiles"][0].pop("preparation_shared_roots")
        else:
            authored["resident_profiles"][0]["readiness"].pop("preparation_staged")
            authored["resident_profiles"][0]["readiness"]["preparation"] = True
        agent_path.write_text(json.dumps(authored))
    else:
        assert service.daemon.resident_worker_launch_profile is not None
        profile = ResidentProfileDescriptor.from_dict(
            service.daemon.resident_worker_launch_profile.descriptor
        )
        selected = replace(profile, profile_id="selected-remote")
        authored = json.loads(config_path.read_text())
        authored["remote_profiles"] = [selected.to_dict()]
        authored["preparation"]["profiles"]["existing-project"][
            "resident_profile_id"
        ] = selected.profile_id
        config_path.write_text(json.dumps(authored))
    service = load_coordinator_service_config(config_path)
    admitted_child = Event()

    class ObservedDaemon(LocalDaemon):
        def _submit(self, *args, **kwargs):
            admission = super()._submit(*args, **kwargs)
            if kwargs.get("preparation_operation_id") is not None:
                admitted_child.set()
            return admission

    LocalDaemon.initialize_deployment(service.daemon)
    from weave import compose_config

    assert service.daemon.resident_worker_launch_profile is not None
    local_profile = ResidentProfileDescriptor.from_dict(
        service.daemon.resident_worker_launch_profile.descriptor
    )
    ordinary = prepare_managed_run(
        service,
        compose_config(tmp_path / "projects" / "pipeline.yaml"),
        "ordinary",
        execution_requirements={
            "produce": ExecutionRequirement(
                local_profile.project_fingerprint,
                local_profile.environment_fingerprint,
                local_profile.executor_fingerprint,
            ),
        },
    )
    daemon = ObservedDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    server.start()
    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            client.prepare_run(_request(mode))
            assert admitted_child.wait(25)
            daemon.reconcile_once()
            operation = client.operation("prepare-1")
            assert operation.state == "pending"
            child = client.admission(
                _result(operation)["preparation_admission_id"]
            ).admission
            # Admission projection can be ACTIVE between scheduling passes;
            # native assignments establish whether an ineligible worker ran it.
            assert child.state.value in {"ACTIVE", "WAITING"}, child
            with sqlite3.connect(service.daemon.execution_database) as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ?",
                        (child.run_uri,),
                    ).fetchone()[0]
                    == 0
                )
            client.submit(LocalDaemonAdmissionRequest("ordinary", ordinary.run_uri))
            assert (
                client.wait("ordinary", timeout_seconds=25).state.value == "SUCCEEDED"
            )
            assert client.operation("prepare-1").state == "pending"
            with sqlite3.connect(service.daemon.execution_database) as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ?",
                        (child.run_uri,),
                    ).fetchone()[0]
                    == 0
                )
            client.cancel_preparation("prepare-1")
            assert (
                client.wait_operation("prepare-1", timeout_seconds=25).operation.state
                == "cancelled"
            )
    finally:
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("mode", ("shared", "staged"))
def test_https_prepares_on_one_worker_then_executes_on_another(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    import loom.queue.agent_session_transport as transport

    _service(tmp_path, mode=mode)
    prepare_request = _request(mode)
    if mode == "staged":
        (tmp_path / "projects" / "included.txt").write_bytes(b"x" * (96 * 1024))
        prepare_request = replace(prepare_request, source=replace(
            prepare_request.source, include=("pipeline.yaml", "included.txt")
        ))
    credentials = mutual_tls_credentials(tmp_path / "tls")
    repository = Path(__file__).resolve().parents[3]
    base = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "prepare-profile", "v1", "project", "environment", "executor"
        ),
        repository,
        Path(sys.executable),
        readiness_requirements=ResidentReadinessRequirements(
            imports=("loom", "loom.preparation", "weave")
        ),
    )
    preparer = qualified_resident_profile(
        replace(
            base,
            preparation_shared_roots={"projects": tmp_path / "snapshots"} if mode == "shared" else {},
            readiness_requirements=replace(base.readiness_requirements, preparation_staged=mode == "staged"),
        )
    )
    executor = qualified_resident_profile(
        replace(
            base,
            descriptor=replace(base.descriptor, profile_id="execute-profile"),
        )
    )
    assert preparer.readiness_result is not None
    assert executor.readiness_result is not None
    assert preparer.readiness_result.preparation_ready
    assert (
        executor.readiness_result.ok and not executor.readiness_result.preparation_ready
    )
    assert preparer.readiness_identity == executor.readiness_identity
    other_project = tmp_path / "different-project"
    (other_project / "src").mkdir(parents=True)
    (other_project / "src" / "identity.py").write_text("PROJECT = 'different'\n")
    incompatible = qualified_resident_profile(
        replace(
            base,
            descriptor=replace(base.descriptor, profile_id="different-project-profile"),
            project_root=other_project,
            readiness_requirements=replace(
                base.readiness_requirements, source_roots=("src",)
            ),
        )
    )
    assert incompatible.readiness_result is not None
    assert incompatible.readiness_result.ok
    assert (
        incompatible.descriptor.project_fingerprint
        != executor.descriptor.project_fingerprint
    )
    ordinary_capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    preparation_capabilities = (
        *ordinary_capabilities, PREPARATION_INPUT_CAPABILITY,
        *((PREPARATION_STAGED_INPUT_CAPABILITY,) if mode == "staged" else ()),
    )
    config_path = tmp_path / "coordinator.json"
    authored = json.loads(config_path.read_text())
    authored["local_agent"] = None
    authored["remote_profiles"] = [
        preparer.descriptor.to_dict(),
        executor.descriptor.to_dict(),
        incompatible.descriptor.to_dict(),
    ]
    authored["preparation"]["profiles"]["existing-project"]["resident_profile_id"] = (
        preparer.descriptor.profile_id
    )
    authored["agent_policy"]["agents"] = [
        {
            "credential_id": certificate,
            "principal_id": agent,
            "agent_id": agent,
            "pools": ["default"],
            "capabilities": list(capabilities),
            "gpu_devices": [],
        }
        for certificate, agent, capabilities in (
            ("agent", "worker-b", preparation_capabilities),
            ("other", "worker-c", ordinary_capabilities),
        )
    ]
    authored["agent_policy"]["principals"] = [
        {
            "credential_id": "query",
            "principal_id": "client",
            "role": "client",
            "actions": [],
            "agent_ids": [],
            "pools": [],
        },
    ]
    config_path.write_text(json.dumps(authored))
    pipeline_path = tmp_path / "projects" / "pipeline.yaml"
    pipeline = json.loads(pipeline_path.read_text())
    pipeline["pipeline"]["stages"][0]["placement"] = {"target": "worker-c"}
    pipeline_path.write_text(json.dumps(pipeline))
    service = load_coordinator_service_config(config_path)
    assert service.daemon.agent_root is None
    assert service.resident_readiness is None
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
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
                certificate_fingerprint(credentials[name].with_suffix(".crt")): name
                for name in ("agent", "other", "query")
            },
        ),
    )
    server.start()
    url = f"https://localhost:{server.port}"
    connection_path = tmp_path / "client.json"
    connection_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.coordinator-client",
                "transport": {
                    "kind": "https",
                    "url": url,
                    "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
                    "certificate_path": str(credentials["query"].with_suffix(".crt")),
                    "private_key_path": str(credentials["query"].with_suffix(".key")),
                },
            }
        )
    )
    connection_path.chmod(0o600)
    agents = []
    agent_configs = []
    sessions = []
    try:
        for profile, certificate, capabilities in (
            (preparer, "agent", preparation_capabilities),
            (executor, "other", ordinary_capabilities),
        ):
            agent_config = AgentTlsClientConfig(
                url,
                credentials["ca"].with_suffix(".crt"),
                credentials[certificate].with_suffix(".crt"),
                credentials[certificate].with_suffix(".key"),
                tmp_path / f"remote-{certificate}" / "agent",
                (profile,) if certificate == "agent" else (profile, incompatible),
            )
            agent_configs.append(agent_config)
            assert agent_config.agent_root is not None
            LocalDaemonAgentHttpClient.initialize_agent_root(agent_config)
            agent = LocalDaemonAgentHttpClient(agent_config)
            agents.append(agent)
            handshake = agent.handshake()
            registration = AgentRegistration(
                f"register-{certificate}",
                str(handshake["coordinator_id"]),
                str(handshake["coordinator_epoch"]),
                agent.agent_root_id,
                "config-1",
                "inventory-1",
                "availability-1",
                ("default",),
                capabilities,
            )
            if certificate == "other":
                with pytest.raises(
                    QueueServiceError, match="preparation qualification"
                ):
                    agent.register(
                        replace(
                            registration, declared_capabilities=preparation_capabilities
                        )
                    )
                with sqlite3.connect(
                    agent_config.agent_root / "control.sqlite"
                ) as conn:
                    assert (
                        conn.execute(
                            "SELECT COUNT(*) FROM agent_registration_intents"
                        ).fetchone()[0]
                        == 0
                    )
            session = agent.register(registration)
            sessions.append(session)
            agent.publish_offer(
                AgentOffer(
                    session.session_id,
                    session.coordinator_epoch,
                    session.config_revision,
                    session.inventory_revision,
                    session.availability_revision,
                    1,
                    0,
                    30,
                    _resident_provider_descriptors(profile, session.agent_id),
                    resident_profiles=(
                        (
                            profile if certificate == "agent" else incompatible
                        ).descriptor,
                    ),
                ),
                idempotency_key=f"offer-{certificate}",
            )

        dropped = Event()
        reply = transport._Handler._reply

        def drop_accepted_reply(handler, status, value):
            result = value.get("result")
            if (
                isinstance(result, Mapping)
                and result.get("kind") == "prepare_run"
                and result.get("operation_id") == "prepare-1"
                and not dropped.is_set()
            ):
                dropped.set()
                handler.close_connection = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                return
            reply(handler, status, value)

        monkeypatch.setattr(transport._Handler, "_reply", drop_accepted_reply)
        with CoordinatorClient.from_connection_file(connection_path) as client:
            description = client.describe_connection()
            assert description.source_modes == (mode,)
            with pytest.raises(CoordinatorClientError) as wrong:
                client.prepare_run(
                    prepare_request, expected_coordinator_id="wrong-coordinator"
                )
            assert wrong.value.mutation_outcome == "not_applied"
            staged = replace(
                prepare_request, source=replace(prepare_request.source, mode="staged" if mode == "shared" else "shared")
            )
            for native in (False, True):
                with pytest.raises(CoordinatorClientError) as unsupported:
                    if native:
                        client._native_call(
                            "prepare_run",
                            {"request": staged.to_dict()},
                            None,
                            negotiate=False,
                        )
                    else:
                        client.prepare_run(staged)
                assert unsupported.value.code == "unsupported"
                assert unsupported.value.mutation_outcome == "not_applied"
            with sqlite3.connect(service.daemon.control_database) as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM preparation_operations"
                    ).fetchone()[0]
                    == 0
                )
            with pytest.raises(CoordinatorClientError) as lost:
                client.prepare_run(prepare_request)
            assert dropped.is_set() and lost.value.mutation_outcome == "unknown"

        with CoordinatorClient.from_connection_file(connection_path) as client:
            replay = client.prepare_run(
                prepare_request, expected_coordinator_id=description.coordinator_id
            )
            assert replay.operation_id == "prepare-1"
            if mode == "staged":
                import loom.queue.preparation as preparation_inputs

                persisted_chunks = []
                original_chunk = _ResidentAssignmentWorkspace.stage_input_chunk

                def interrupt_after_chunk(workspace, transfer_id, offset, data, *, final):
                    observed = original_chunk(workspace, transfer_id, offset, data, final=final)
                    if not final and not persisted_chunks:
                        persisted_chunks.append(workspace.root)
                        raise RuntimeError("interrupted staged input transfer")
                    return observed

                monkeypatch.setattr(_ResidentAssignmentWorkspace, "stage_input_chunk", interrupt_after_chunk)
                with pytest.raises(RuntimeError, match="interrupted staged input transfer"):
                    agents[0].execute_one(sessions[0].session_id, sessions[0].availability_revision,
                                          sequence=1, wait_timeout_ms=5000)
                assert len(persisted_chunks) == 1
                workspace_root = persisted_chunks[0]
                assert not tuple(workspace_root.glob("preparation-input-*"))
                assert client.operation("prepare-1").state == "pending"
                ready_receipt = _result(client.operation("prepare-1"))["input_receipt"]
                (tmp_path / "projects" / "pipeline.yaml").write_text("edited after ready capture")
                agents[0].close()
                agents[0] = LocalDaemonAgentHttpClient(agent_configs[0])
                monkeypatch.setattr(_ResidentAssignmentWorkspace, "stage_input_chunk", original_chunk)

                original_unpack = preparation_inputs._unpack_staged_archive
                interrupted_extraction = []

                def interrupt_extraction(archive_path, destination, digest):
                    directory = original_unpack(archive_path, destination, digest)
                    if destination.is_relative_to(workspace_root) and not interrupted_extraction:
                        interrupted_extraction.append(destination)
                        raise RuntimeError("interrupted staged input extraction")
                    return directory

                monkeypatch.setattr(preparation_inputs, "_unpack_staged_archive", interrupt_extraction)
                with pytest.raises(QueueConflictError, match="cannot poll"):
                    agents[0].wait_for_work(sessions[0].session_id, sessions[0].availability_revision,
                                            sequence=1, wait_timeout_ms=5000)
                with pytest.raises(RuntimeError, match="interrupted staged input extraction"):
                    agents[0].resume_retained_work()
                assert len(interrupted_extraction) == 1
                assert not interrupted_extraction[0].exists()
                assert not tuple(workspace_root.glob("preparation-input-*"))
                assert _result(client.operation("prepare-1"))["input_receipt"] == ready_receipt
                agents[0].close()
                agents[0] = LocalDaemonAgentHttpClient(agent_configs[0])
                monkeypatch.setattr(preparation_inputs, "_unpack_staged_archive", original_unpack)

            if mode == "staged":
                (result,) = agents[0].resume_retained_work()
                assert agents[0].resume_retained_work() == ()
            else:
                result = agents[0].execute_one(
                    sessions[0].session_id,
                    sessions[0].availability_revision,
                    sequence=1,
                    wait_timeout_ms=5000,
                )
            assert result["state"] == "RELEASED", result
            prepared = client.wait_operation("prepare-1", timeout_seconds=25).operation
            assert prepared.state == "applied", prepared
            assert _result(prepared)["input_receipt"]["mode"] == mode
            if mode == "staged":
                assert not (tmp_path / "snapshots").exists()
                assert not (tmp_path / "remote-agent" / "projects").exists()
            child = client.admission(
                _result(prepared)["preparation_admission_id"]
            ).admission
            assert child.state.value == "SUCCEEDED"
            assert len(client.admissions().admissions) == 1
            target_uri = _result(prepared)["prepared_run"]["run_uri"]
            client.submit(LocalDaemonAdmissionRequest("remote-target", target_uri))
            unavailable = agents[1].wait_for_work(
                sessions[1].session_id,
                sessions[1].availability_revision,
                sequence=1,
                wait_timeout_ms=250,
            )
            assert unavailable["result"] == "wait", unavailable
            with sqlite3.connect(service.daemon.execution_database) as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ?",
                        (target_uri,),
                    ).fetchone()[0]
                    == 0
                )
            agents[1].publish_offer(
                AgentOffer(
                    sessions[1].session_id,
                    sessions[1].coordinator_epoch,
                    sessions[1].config_revision,
                    sessions[1].inventory_revision,
                    sessions[1].availability_revision,
                    1,
                    0,
                    30,
                    _resident_provider_descriptors(executor, sessions[1].agent_id),
                    resident_profiles=(executor.descriptor,),
                ),
                idempotency_key="offer-compatible-c",
            )
            executed = agents[1].execute_one(
                sessions[1].session_id,
                sessions[1].availability_revision,
                sequence=2,
                wait_timeout_ms=5000,
            )
            assert executed["state"] == "RELEASED", executed
            assert (
                client.wait("remote-target", timeout_seconds=25).state.value
                == "SUCCEEDED"
            )
            with sqlite3.connect(service.daemon.execution_database) as conn:
                owners = conn.execute(
                    "SELECT run_uri, agent_id FROM coordinator_assignments"
                ).fetchall()
            assert (child.run_uri, "worker-b") in owners
            assert (target_uri, "worker-c") in owners
            assert len(owners) == 2
            store = LocalRunStore(service.daemon.run_store_root)
            result = store.read_stage_worker_result(target_uri, "produce", attempt=1)
            assert result is not None
            output = StageWorkerResult.from_dict(result).outputs["data"]
            assert LocalArtifactStore(store.local_artifact_root(target_uri)).load(
                output
            ) == {"value": 41}
            if mode == "staged":
                cancel_request = replace(prepare_request, operation_id="cancel-transfer", run_name="cancel-transfer")
                client.prepare_run(cancel_request)
                session_b = agents[0]._require_journal().session(sessions[0].session_id)
                agents[0].publish_offer(AgentOffer(
                    session_b.session_id, session_b.coordinator_epoch,
                    session_b.config_revision, session_b.inventory_revision,
                    session_b.availability_revision, 1, 0, 30,
                    _resident_provider_descriptors(preparer, session_b.agent_id),
                    resident_profiles=(preparer.descriptor,),
                ), idempotency_key="offer-cancel-transfer")
                assert daemon._execution is not None
                cancellation_durable = Event()
                fan_out = daemon._execution._fan_out_remote_cancellation

                def observed_cancellation(run_uri, operation_id):
                    settling = fan_out(run_uri, operation_id)
                    cancellation_durable.set()
                    return settling

                monkeypatch.setattr(daemon._execution, "_fan_out_remote_cancellation", observed_cancellation)
                original_accept = _ResidentAssignmentWorkspace.accept
                cancelled_during_delivery = []

                def cancel_before_inputs_ready(workspace):
                    binding = workspace.request().preparation_input
                    if binding is not None and binding.operation_id == "cancel-transfer":
                        cancelled_during_delivery.append(workspace.assignment_id)
                        assert client.cancel_preparation("cancel-transfer").state == "pending"
                        assert cancellation_durable.wait(25)
                        assert client.operation("cancel-transfer").state == "pending"
                    return original_accept(workspace)

                monkeypatch.setattr(_ResidentAssignmentWorkspace, "accept", cancel_before_inputs_ready)
                cancelled_assignment = agents[0].execute_one(
                    session_b.session_id, session_b.availability_revision,
                    sequence=2, wait_timeout_ms=5000,
                )
                assert cancelled_assignment["state"] == "CANCELLED_BEFORE_GRANT", cancelled_assignment
                assert len(cancelled_during_delivery) == 1
                cancelled = client.wait_operation("cancel-transfer", timeout_seconds=25).operation
                assert cancelled.state == "cancelled", cancelled
                assert not (service.daemon.run_store_root / "cancel-transfer").exists()
                cancelled_child = client.admission(_result(cancelled)["preparation_admission_id"]).admission
                assert cancelled_child.state.value == "CANCELLED"
            for agent in agents:
                agent.shutdown_clean()
    finally:
        for agent in agents:
            agent.close()
        server.stop()
        daemon.stop()


def test_running_preparation_cancellation_waits_for_native_resource_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _service(tmp_path)
    installed = tmp_path / "existing-installation"
    installed.mkdir()
    (installed / "blocking_recipe.py").write_text(
        "import os, socket\n"
        "def recipe():\n"
        "    with socket.create_connection(('127.0.0.1', int(os.environ['LOOM_TEST_RECIPE_PORT'])), timeout=30) as connection:\n"
        "        connection.sendall(b'ready')\n"
        "        connection.recv(1)\n"
        "    return {'value': 41}\n"
    )
    distribution = installed / "blocking_recipe-1.0.dist-info"
    distribution.mkdir()
    (distribution / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: blocking-recipe\nVersion: 1.0\n"
    )
    (distribution / "entry_points.txt").write_text(
        "[loom.recipes]\nblocking-value = blocking_recipe:recipe\n"
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(25)
    agent_path = tmp_path / "agent.json"
    authored = json.loads(agent_path.read_text())
    authored["resident_profiles"][0]["environment"] = {
        "PYTHONPATH": str(installed),
        "LOOM_TEST_RECIPE_PORT": str(listener.getsockname()[1]),
    }
    agent_path.write_text(json.dumps(authored))
    pipeline_path = tmp_path / "projects" / "pipeline.yaml"
    pipeline = json.loads(pipeline_path.read_text())
    pipeline["pipeline"]["stages"][0]["config"] = {"_recipe_": "blocking-value"}
    pipeline_path.write_text(json.dumps(pipeline))
    service = load_coordinator_service_config(tmp_path / "coordinator.json")
    release_entered, allow_release = Event(), Event()
    release = AtomResourceProvider.release

    def delayed_release(provider, command):
        release_entered.set()
        assert allow_release.wait(25)
        return release(provider, command)

    monkeypatch.setattr(AtomResourceProvider, "release", delayed_release)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    server.start()
    connection = None
    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            client.prepare_run(_request())
            connection, _ = listener.accept()
            assert connection.recv(5) == b"ready"
            operation = client.operation("prepare-1")
            child = client.admission(
                _result(operation)["preparation_admission_id"]
            ).admission
            assert child.state.value == "ACTIVE"
            assert client.cancel_preparation("prepare-1").state == "pending"
            assert release_entered.wait(25)
            observation = client.wait_operation("prepare-1", timeout_seconds=0)
            assert observation.operation.state == "pending"
            with sqlite3.connect(service.daemon.execution_database) as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ? AND state != 'released'",
                        (child.run_uri,),
                    ).fetchone()[0]
                    == 1
                )
            assert not (service.daemon.run_store_root / "target-1").exists()
            allow_release.set()
            cancelled = client.wait_operation("prepare-1", timeout_seconds=25).operation
            assert cancelled.state == "cancelled"
            assert client.cancel_preparation("prepare-1") == cancelled
            assert (
                client.admission(child.admission_id).admission.state.value
                == "CANCELLED"
            )
            assert _result(cancelled)["prepared_run"] is None
            assert (
                SQLiteAgentJournal(
                    service.daemon.agent_journal, _allow_initialize=False
                ).retained_claim_commands()
                == ()
            )
            assert len(client.admissions().admissions) == 1
    finally:
        allow_release.set()
        if connection is not None:
            connection.close()
        listener.close()
        server.stop()
        daemon.stop()


def test_upgrade_reopens_real_nonterminal_admission_and_retained_worker_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from weave import compose_config
    from loom.queue.local_daemon_execution import LocalDaemonExecution

    _service(tmp_path)
    config_path = tmp_path / "coordinator.json"
    authored = json.loads(config_path.read_text())
    authored.pop("preparation")
    config_path.write_text(json.dumps(authored))
    agent_path = tmp_path / "agent.json"
    authored = json.loads(agent_path.read_text())
    authored["resident_profiles"][0].pop("preparation_shared_roots")
    agent_path.write_text(json.dumps(authored))
    service = load_coordinator_service_config(config_path)
    LocalDaemon.initialize_deployment(service.daemon)
    assert service.daemon.resident_worker_launch_profile is not None
    assert service.daemon.agent_root is not None
    profile = ResidentProfileDescriptor.from_dict(
        service.daemon.resident_worker_launch_profile.descriptor
    )
    requirements = {
        "produce": ExecutionRequirement(
            profile.project_fingerprint,
            profile.environment_fingerprint,
            profile.executor_fingerprint,
        )
    }
    source = tmp_path / "projects" / "pipeline.yaml"
    complete = prepare_managed_run(
        service, compose_config(source), "complete", execution_requirements=requirements
    )
    barrier = tmp_path / "worker-barrier"
    authored = json.loads(source.read_text())
    authored["pipeline"]["stages"][0]["factory"] = {
        "_target_": "tests.support.pipeline_execution_stages.ReleaseStage"
    }
    authored["pipeline"]["stages"][0]["config"] = {
        "marker_dir": str(barrier),
        "timeout_seconds": 60,
    }
    source.write_text(json.dumps(authored))
    active = prepare_managed_run(
        service, compose_config(source), "active", execution_requirements=requirements
    )
    first = LocalDaemon(service.daemon)
    first.start()
    server = LocalDaemonSocketServer(first, service.daemon.endpoint)
    server.start()
    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            client.submit(LocalDaemonAdmissionRequest("complete", complete.run_uri))
            assert (
                client.wait("complete", timeout_seconds=25).state.value == "SUCCEEDED"
            )
            client.submit(LocalDaemonAdmissionRequest("active", active.run_uri))
            deadline = monotonic() + 25
            while not (barrier / "produce.started").exists():
                assert monotonic() < deadline
                sleep(0.01)
            coordinator_id = client.status().coordinator_id
            admissions = client.admissions().admissions
            assert {row.state.value for row in admissions} == {"SUCCEEDED", "ACTIVE"}
    finally:
        server.stop()
        first.stop()

    journal = SQLiteAgentJournal(service.daemon.agent_journal, _allow_initialize=False)
    retained = journal.retained_claim_commands()
    assert len(retained) == 1
    assert isinstance(retained[0].assignment, ManagedAssignment)
    assert retained[0].assignment.run_uri == active.run_uri
    worker_files = {
        path: path.read_bytes()
        for path in (
            service.daemon.agent_journal,
            service.daemon.agent_root / "control.sqlite",
        )
    }
    # Prior formats are unchanged: create the exact predecessor control shape
    # only after real native admissions, claims and a worker process exist.
    with sqlite3.connect(service.daemon.control_database) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM preparation_operations").fetchone()[0]
            == 0
        )
        conn.execute("DROP TABLE preparation_operations")
        conn.execute("PRAGMA user_version = 12")
        before = {
            row[0]: tuple(conn.execute(f'SELECT * FROM "{row[0]}"'))
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    upgraded = _cli_result("daemon-upgrade", str(config_path))["result"]
    assert upgraded == {"coordinator_id": coordinator_id, "schema_version": 13}
    with sqlite3.connect(service.daemon.control_database) as conn:
        assert {
            name: tuple(conn.execute(f'SELECT * FROM "{name}"')) for name in before
        } == before
    assert {path: path.read_bytes() for path in worker_files} == worker_files
    assert (
        SQLiteAgentJournal(
            service.daemon.agent_journal, _allow_initialize=False
        ).retained_claim_commands()
        == retained
    )
    assert LocalDaemon.upgrade_coordinator_root(service.daemon) == (coordinator_id, 13)
    (backup,) = service.daemon.coordinator_root.glob("*.backup")
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
        assert (
            tuple(conn.execute("SELECT * FROM managed_admissions"))
            == before["managed_admissions"]
        )

    entered = Event()
    resume = LocalDaemonExecution.resume_retained_local_work

    def observe_resume(execution):
        entered.set()
        return resume(execution)

    monkeypatch.setattr(
        LocalDaemonExecution, "resume_retained_local_work", observe_resume
    )
    replacement = LocalDaemon(service.daemon)
    try:
        with ThreadPoolExecutor(max_workers=1) as threads:
            starting = threads.submit(replacement.start)
            assert entered.wait(25)
            assert not starting.done()
            (barrier / "release").touch()
            starting.result(timeout=25)
        assert replacement.status().coordinator_id == coordinator_id
        assert replacement._admission_for_queue_item("complete").admission_id == next(
            row.admission_id for row in admissions if row.queue_item_id == "complete"
        )
        outcome = replacement._wait("active", timeout_seconds=25)
        assert outcome.state.value == "SUCCEEDED"
        assert outcome.admission_id == next(
            row.admission_id for row in admissions if row.queue_item_id == "active"
        )
        assert (
            SQLiteAgentJournal(
                service.daemon.agent_journal, _allow_initialize=False
            ).retained_claim_commands()
            == ()
        )
        with sqlite3.connect(service.daemon.execution_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone()[
                    0
                ]
                == 2
            )
        store = LocalRunStore(service.daemon.run_store_root)
        result = StageWorkerResult.from_dict(
            store.read_stage_worker_result(active.run_uri, "produce", attempt=1)
        )
        assert LocalArtifactStore(store.local_artifact_root(active.run_uri)).load(
            result.outputs["data"]
        ) == {"stage": "produce"}
    finally:
        (barrier / "release").touch()
        replacement.stop()


def test_cancellation_before_capture_is_durable_and_keeps_the_target_absent(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    try:
        accepted = daemon.prepare_run(_request(), principal_id="caller")
        with pytest.raises(QueueConflictError, match="another operation"):
            daemon.prepare_run(
                replace(_request(), operation_id="prepare-other"), principal_id="caller"
            )
        with pytest.raises(QueueConflictError, match="intent conflicts"):
            daemon.prepare_run(_request(), principal_id="another-caller")
        with pytest.raises(PreparationNotAccepted, match="result_too_large"):
            daemon.prepare_run(
                replace(_request(), operation_id="p" * (64 * 1024), run_name="other"),
                principal_id="caller",
            )
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM preparation_operations").fetchone()[
                    0
                ]
                == 1
            )
            assert (
                conn.execute("SELECT COUNT(*) FROM managed_admissions").fetchone()[0]
                == 0
            )
        assert (
            daemon.cancel_preparation(
                accepted.operation_id, principal_id="caller"
            ).state
            == "pending"
        )
        daemon._preparations._reconcile_lock.release()
        completed = daemon.wait_operation(accepted.operation_id, timeout=10).operation
        assert completed.state == "cancelled"
        assert not (tmp_path / "snapshots").exists()
        assert not (tmp_path / "runs" / "target-1").exists()
        assert daemon.prepare_run(_request(), principal_id="caller") == completed
        with pytest.raises(QueueConflictError, match="intent conflicts"):
            daemon.prepare_run(
                replace(_request(), config_path="changed.yaml"), principal_id="caller"
            )
    finally:
        if daemon._preparations._reconcile_lock.locked():
            daemon._preparations._reconcile_lock.release()
        daemon.stop()


@pytest.mark.parametrize(
    "boundary,mode", (("captured", "shared"), ("child_accepted", "shared"),
                      ("published", "shared"), ("report_unavailable", "shared"),
                      ("captured", "staged"))
)
def test_restart_reuses_capture_and_replays_a_claimed_complete_target(
    tmp_path: Path, boundary: str, mode: str
) -> None:
    service = _service(tmp_path, mode=mode)
    reached = Event()
    prior_request = replace(_request(), operation_id="retained-shared", run_name="retained-shared")
    prior_operation = None
    prior_target = service.daemon.run_store_root / "retained-shared"
    prior_files = {}

    class InterruptedPreparation(CoordinatorPreparation):
        def prepare_child(self, *args, **kwargs):
            if boundary == "captured" and args[1].operation_id == "prepare-1":
                reached.set()
                raise RuntimeError("injected interruption after durable capture")
            return super().prepare_child(*args, **kwargs)

        def publish_target(self, *args, **kwargs):
            receipt = super().publish_target(*args, **kwargs)
            if boundary in {"published", "report_unavailable"}:
                reached.set()
                raise RuntimeError(
                    f"injected interruption after publication of {receipt.run_uri}"
                )
            return receipt

    class InterruptedDaemon(LocalDaemon):
        def _submit(self, *args, **kwargs):
            admitted = super()._submit(*args, **kwargs)
            if boundary == "child_accepted":
                reached.set()
                raise RuntimeError("injected loss of the child admission response")
            return admitted

    LocalDaemon.initialize_deployment(service.daemon)
    config_path = tmp_path / "coordinator.json"
    daemon = InterruptedDaemon(
        service.daemon,
        preparation=InterruptedPreparation(service),
        trusted_scheduling_loader=lambda: (
            load_coordinator_service_config(config_path, current=service).daemon
        ),
    )
    daemon.start()
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    server.start()
    try:
        if mode == "shared" and boundary == "captured":
            daemon.prepare_run(prior_request, principal_id="caller")
            prior_operation = daemon.wait_operation(prior_request.operation_id, timeout=25).operation
            assert prior_operation.state == "applied", prior_operation
            prior_files = {path.relative_to(prior_target): (path.read_bytes(), path.stat().st_mtime_ns)
                           for path in prior_target.rglob("*") if path.is_file()}
        daemon.prepare_run(_request(mode), principal_id="caller")
        assert reached.wait(25), daemon.operation("prepare-1")
        # Protected changes use the same atomic reload as the CLI. Accepted
        # preparation retains its snapshot even after new preparation is disabled.
        config_data = json.loads(config_path.read_text())
        config_data.pop("preparation")
        config_path.write_text(json.dumps(config_data))
        reloaded = LocalDaemonSocketClient(service.daemon.endpoint).reload_scheduling(
            CoordinatorSchedulingReload(
                "disable-preparation",
                daemon.status().scheduling_epoch,
                "disable new preparation while retained work reconciles",
            )
        )
        assert reloaded["state"] == "applied", reloaded
    finally:
        server.stop()
        daemon.stop()
    store = LocalRunStore(service.daemon.run_store_root)
    target = service.daemon.run_store_root / "target-1"
    before = {
        path.relative_to(target): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in target.rglob("*")
        if path.is_file()
    }
    (tmp_path / "projects" / "pipeline.yaml").write_text(
        "invalid edited authoring bytes"
    )
    with sqlite3.connect(service.daemon.control_database) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 13
    assert service.daemon.agent_root is not None
    with sqlite3.connect(service.daemon.agent_root / "control.sqlite") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
    service = load_coordinator_service_config(config_path)
    report_unavailable, allow_report = Event(), Event()

    class ReopenedPreparation(CoordinatorPreparation):
        def read_report(self, *args, **kwargs):
            if boundary == "report_unavailable" and not allow_report.is_set():
                report_unavailable.set()
                raise QueueServiceError(
                    "injected temporary report-store unavailability"
                )
            return super().read_report(*args, **kwargs)

    resumed = LocalDaemon(service.daemon, preparation=ReopenedPreparation(service))
    resumed.start()
    try:
        if boundary == "report_unavailable":
            assert report_unavailable.wait(25)
            assert resumed._preparations._reconcile_lock.acquire(timeout=5)
            try:
                pending = resumed.operation("prepare-1")
                assert pending.state == "applying"
                assert pending.code == "preparation_unavailable"
            finally:
                resumed._preparations._reconcile_lock.release()
            allow_report.set()
        completed = resumed.wait_operation("prepare-1", timeout=25).operation
        assert completed.state == "applied", completed
        receipt = _result(completed)["prepared_run"]
        snapshot = store.read_config_snapshot(receipt["run_uri"], "resolved")
        assert snapshot is not None
        assert json.loads(snapshot)["pipeline"]["stages"][0]["config"] == {"value": 41}
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM managed_admissions").fetchone()[0]
                == (2 if prior_operation is not None else 1)
            )
        if boundary in {"published", "report_unavailable"}:
            assert {
                path.relative_to(target): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in target.rglob("*")
                if path.is_file()
            } == before
        managed_root = CleanupManagedRoot(
            "fixture",
            str(tmp_path),
            ownership_key="fixture",
            metadata={"owned_by": "loom"},
        )
        for retained in (
            str(target),
            (
                str(tmp_path / "snapshots" / _result(completed)["input_receipt"]["reference"]["path"])
                if mode == "shared" else _result(completed)["input_receipt"]["reference"]["uri"]
            ),
            _result(completed)["report_ref"]["uri"],
        ):
            decision = assess_local_target_safety(
                CleanupTargetRef(
                    CleanupTargetKind.LOCAL_PATH, retained, ownership_key="fixture"
                ),
                (managed_root,),
            )
            assert (
                decision.reason_code
                is CleanupSafetyReason.RETAINED_PREPARATION_EVIDENCE
            )
        assert resumed.prepare_run(_request(mode), principal_id="caller") == completed
        if prior_operation is not None:
            assert resumed.prepare_run(prior_request, principal_id="caller") == prior_operation
            assert {path.relative_to(prior_target): (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in prior_target.rglob("*") if path.is_file()} == prior_files
    finally:
        resumed.stop()


@pytest.mark.parametrize(
    "fault,code",
    (
        ("checks", "preflight_failed"),
        ("compose", "preparation_child_failed"),
        ("runtime_path", "invalid_preparation_report"),
        ("profile", "installation_mismatch"),
        ("requirements", "installation_mismatch"),
        ("missing_requirement", "invalid_preparation_report"),
        ("malformed_preflight", "invalid_preparation_report"),
        ("malformed_requirements", "invalid_preparation_report"),
        ("malformed_pipeline", "invalid_preparation_report"),
        ("malformed_runtime", "invalid_preparation_report"),
        ("malformed_worker_result", "invalid_preparation_report"),
        ("malformed_json", "invalid_preparation_report"),
        ("worker_result", "invalid_preparation_report"),
        ("checksum", "invalid_preparation_report"),
        ("required_unavailable", "preflight_failed"),
    ),
)
def test_child_failure_or_inconsistent_evidence_never_publishes(
    tmp_path: Path,
    fault: str,
    code: str,
) -> None:
    service = _service(tmp_path)
    source = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(source.read_text())
    stage = authored["pipeline"]["stages"][0]
    if fault == "checks":
        stage["inputs"] = {"missing": "unavailable.data"}
    elif fault == "compose":
        stage["config"] = {"_recipe_": "uninstalled-recipe"}
    elif fault == "runtime_path":
        stage["config"] = {"input_path": str(tmp_path / "worker-private")}
    source.write_text(json.dumps(authored))

    if fault in {
        "profile",
        "requirements",
        "missing_requirement",
        "required_unavailable",
        "malformed_preflight",
        "malformed_requirements",
        "malformed_pipeline",
        "malformed_runtime",
        "malformed_json",
    }:
        # A selected installed Python writes an inconsistent report before its
        # native artifact checksum and authoritative output commit are created.
        installed = tmp_path / "report-producer"
        installed.mkdir()
        (installed / "sitecustomize.py").write_text(
            "import os\n"
            "from dataclasses import replace\n"
            "from loom.pipeline.context import StageContext\n"
            "from loom.diagnostics import PreflightResult, PreflightCheckStatus\n"
            "from loom.io.codecs.json_codec import JSONCodec\n"
            "encode = JSONCodec.encode\n"
            "def encoded(self, obj, **kwargs):\n"
            "    if os.environ['LOOM_TEST_REPORT_FAULT'] == 'malformed_json' and isinstance(obj, dict) and 'input_manifest_digest' in obj:\n"
            "        return b'{invalid json'\n"
            "    return encode(self, obj, **kwargs)\n"
            "JSONCodec.encode = encoded\n"
            "save = StageContext.save_artifact\n"
            "def changed(self, name, value, **kwargs):\n"
            "    if name == 'report' and self.stage_name == 'prepare':\n"
            "        fault = os.environ['LOOM_TEST_REPORT_FAULT']\n"
            "        if fault == 'profile':\n"
            "            value['profile_descriptor']['revision'] = 'another-installation'\n"
            "        elif fault == 'requirements':\n"
            "            value['execution_requirements']['produce']['environment_fingerprint'] = 'another-environment'\n"
            "        elif fault == 'missing_requirement':\n"
            "            value['execution_requirements'] = {}\n"
            "        elif fault == 'malformed_preflight':\n"
            "            value['preflight']['checks'] = None\n"
            "        elif fault == 'malformed_requirements':\n"
            "            value['execution_requirements']['produce']['environment_fingerprint'] = None\n"
            "        elif fault == 'malformed_pipeline':\n"
            "            value['composition']['resolved']['pipeline']['stages'] = None\n"
            "        elif fault == 'malformed_runtime':\n"
            "            value['composition']['resolved']['runtime'] = {'invalid_field': True}\n"
            "        elif fault == 'required_unavailable':\n"
            "            preflight = PreflightResult.from_dict(value['preflight'])\n"
            "            checks = (replace(preflight.checks[0], status=PreflightCheckStatus.SKIP, details={'applicability': 'required'}), *preflight.checks[1:])\n"
            "            value['preflight'] = PreflightResult(checks, preflight.groups).to_dict()\n"
            "    return save(self, name, value, **kwargs)\n"
            "StageContext.save_artifact = changed\n"
        )
        agent_path = tmp_path / "agent.json"
        config = json.loads(agent_path.read_text())
        config["resident_profiles"][0]["environment"] = {
            "PYTHONPATH": str(installed),
            "LOOM_TEST_REPORT_FAULT": fault,
        }
        agent_path.write_text(json.dumps(config))
        service = load_coordinator_service_config(tmp_path / "coordinator.json")

    class ChangedPersistedEvidence(CoordinatorPreparation):
        def read_report(self, config, admission, request, binding):
            # Exercise disagreement at the existing filesystem evidence boundary,
            # using a real committed child rather than a fabricated admission.
            store = LocalRunStore(config.run_store_root)
            stored_result = store.read_stage_worker_result(
                admission.run_uri, "prepare", attempt=1
            )
            assert stored_result is not None
            result: dict[str, Any] = stored_result
            if fault in {"worker_result", "malformed_worker_result"}:
                if fault == "worker_result":
                    result["outputs"]["report"]["artifact_id"] = "different-report"
                else:
                    result["outputs"]["report"]["artifact_id"] = None
                store.write_stage_worker_result(
                    admission.run_uri, "prepare", result, attempt=1
                )
            elif fault == "checksum":
                reference = ArtifactRef.from_dict(result["outputs"]["report"])
                path = uri_to_path(reference.uri)
                path.write_text('{"changed": true}')
            return super().read_report(config, admission, request, binding)

    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=ChangedPersistedEvidence(service))
    daemon.start()
    try:
        daemon.prepare_run(_request(), principal_id="caller")
        failed = daemon.wait_operation("prepare-1", timeout=25).operation
        assert (failed.state, failed.code) == ("failed", code), failed
        assert _result(failed)["prepared_run"] is None
        assert not (service.daemon.run_store_root / "target-1").exists()
        child = daemon._admission(_result(failed)["preparation_admission_id"])
        assert child.state.value == ("FAILED" if fault == "compose" else "SUCCEEDED")
        if fault == "checks":
            assert _result(failed)["preflight_status"] == "FAIL"
            assert _result(failed)["report_ref"] is not None
        if fault == "required_unavailable":
            assert _result(failed)["report_ref"] is not None
            assert any(
                check["status"] == "SKIP"
                and check["details"].get("applicability") == "required"
                for check in _result(failed)["preflight"]["checks"]
            )
        assert len(daemon.admissions().admissions) == 1
    finally:
        daemon.stop()


def test_preparation_rejects_other_operation_ids_and_public_child_submission(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(
        service.daemon,
        preparation=CoordinatorPreparation(service),
        trusted_scheduling_loader=lambda: service.daemon,
    )
    daemon.start()
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    server.start()
    try:
        occupied = LocalDaemonSocketClient(service.daemon.endpoint).reload_scheduling(
            CoordinatorSchedulingReload(
                "occupied-id",
                daemon.status().scheduling_epoch,
                "native operation collision",
            ),
        )
        assert occupied["state"] == "applied", occupied
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            with pytest.raises(CoordinatorClientError) as collision:
                client.prepare_run(replace(_request(), operation_id="occupied-id"))
            assert collision.value.code == "conflict"
            assert collision.value.mutation_outcome == "not_applied"
            assert client.operation("occupied-id").kind == "scheduling_reload"
            assert not (tmp_path / "snapshots").exists()
            client.prepare_run(_request())
            prepared = client.wait_operation("prepare-1", timeout_seconds=25).operation
            assert prepared.state == "applied", prepared
            child = client.admission(
                _result(prepared)["preparation_admission_id"]
            ).admission
            for request in (
                LocalDaemonAdmissionRequest("different-queue", child.run_uri),
                LocalDaemonAdmissionRequest(
                    child.queue_item_id, _result(prepared)["prepared_run"]["run_uri"]
                ),
            ):
                with pytest.raises(CoordinatorClientError) as reserved:
                    client.submit(request)
                assert reserved.value.code == "conflict"
                assert reserved.value.mutation_outcome == "not_applied"
            assert len(client.admissions().admissions) == 1
    finally:
        server.stop()
        daemon.stop()


def test_partial_target_is_preserved_as_a_publication_conflict(tmp_path: Path) -> None:
    service = _service(tmp_path)
    target = service.daemon.run_store_root / "target-1"
    target.mkdir(parents=True)
    sentinel = target / "partial-write.json"
    sentinel.write_text("interrupted native publication")
    before = sentinel.read_bytes(), sentinel.stat().st_mtime_ns
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.prepare_run(_request(), principal_id="caller")
        completed = daemon.wait_operation("prepare-1", timeout=25).operation
        assert (completed.state, completed.code) == ("conflict", "publication_conflict")
        assert _result(completed)["preflight_status"] == "PASS"
        assert _result(completed)["report_ref"] is not None
        assert _result(completed)["prepared_run"] is None
        assert (sentinel.read_bytes(), sentinel.stat().st_mtime_ns) == before
        assert tuple(target.iterdir()) == (sentinel,)
        assert (
            daemon.cancel_preparation("prepare-1", principal_id="caller") == completed
        )
    finally:
        daemon.stop()


@pytest.mark.parametrize("boundary", ("before_claim", "after_claim"))
def test_cancel_and_publication_race_uses_the_durable_claim(
    tmp_path: Path, boundary: str
) -> None:
    service = _service(tmp_path)
    entered, release = Event(), Event()

    class PausedPreparation(CoordinatorPreparation):
        def read_report(self, *args, **kwargs):
            report = super().read_report(*args, **kwargs)
            if boundary == "before_claim":
                entered.set()
                assert release.wait(25)
            return report

        def publish_target(self, *args, **kwargs):
            if boundary == "after_claim":
                entered.set()
                assert release.wait(25)
            return super().publish_target(*args, **kwargs)

    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=PausedPreparation(service))
    daemon.start()
    try:
        daemon.prepare_run(_request(), principal_id="caller")
        assert entered.wait(25), daemon.operation("prepare-1")
        assert daemon._cycle_lock.acquire(timeout=1), (
            "publication I/O held the global cycle lock"
        )
        daemon._cycle_lock.release()
        cancellation = daemon.cancel_preparation("prepare-1", principal_id="caller")
        assert cancellation.state == (
            "pending" if boundary == "before_claim" else "applying"
        )
        release.set()
        completed = daemon.wait_operation("prepare-1", timeout=25).operation
        assert completed.state == (
            "cancelled" if boundary == "before_claim" else "applied"
        ), completed
        assert (service.daemon.run_store_root / "target-1").exists() is (
            boundary == "after_claim"
        )
        assert (
            daemon.cancel_preparation("prepare-1", principal_id="caller") == completed
        )
    finally:
        release.set()
        daemon.stop()


@pytest.mark.parametrize("large", ("preflight", "receipt"))
def test_native_report_projection_omits_large_checks_and_rejects_large_receipts_before_publication(
    tmp_path: Path, large: str
) -> None:
    service = _service(tmp_path)
    config_path = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(config_path.read_text())
    if large == "preflight":
        authored["runtime"]["notes"] = ["large native check context " * 5000]
    else:
        template = authored["pipeline"]["stages"][0]
        authored["pipeline"]["stages"] = [
            {**template, "name": f"stage_{index:04d}_" + "x" * 80}
            for index in range(800)
        ]
    config_path.write_text(json.dumps(authored))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.prepare_run(_request(), principal_id="caller")
        completed = daemon.wait_operation("prepare-1", timeout=25).operation
        assert completed.state == ("applied" if large == "preflight" else "failed"), (
            completed
        )
        assert len(stable_json_bytes(completed.to_dict())) <= 64 * 1024
        assert _result(completed)["preflight_status"] == "PASS"
        reference = ArtifactRef.from_dict(
            ensure_plain_data(_result(completed)["report_ref"])
        )
        report = LocalArtifactStore(service.daemon.run_store_root).load(reference)
        assert isinstance(report, dict)
        assert report["preflight"]["status"] == "PASS"
        if large == "preflight":
            assert _result(completed)["preflight"] is None
            assert len(stable_json_bytes(report["preflight"])) > 64 * 1024
            assert _result(completed)["prepared_run"] is not None
        else:
            assert completed.code == "result_too_large"
            assert not (service.daemon.run_store_root / "target-1").exists()
    finally:
        daemon.stop()
