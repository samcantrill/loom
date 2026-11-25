"""GPU occupancy exercise shared by transport and observation scenarios."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from time import monotonic, sleep
from typing import Any, cast

import pytest

from loom.queue._managed_local import (
    GpuResourceProvider,
)
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import (
    LocalArtifactStore,
    LocalRunStore,
)
from loom.queue import (
    ConfiguredGpuDevice,
    ExecutionRequirement,
    GpuDeviceDescriptor,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    ResidentExecutionProfile,
    ResidentGpuDevice,
    ResidentProfileDescriptor,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    _RemoteAgentJournal,
)
from loom.queue.agent_sessions import (
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.serialization import freeze_plain_data
from tests.support.mutual_tls import (
    certificate_fingerprint as _fingerprint,
    mutual_tls_credentials as _credentials,
)
from tests.support.agent_sessions import (
    _fresh_remote_agent_root,
    _local_launch_profile,
    _prepare_gpu_environment_run,
)


def exercise_gpu_occupancy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote: bool
) -> None:
    from loom.queue.gpu.occupancy import (
        GpuOccupancyPolicy,
        GpuProcessObservation,
        NvidiaSmiGpuProcessObserver,
    )

    devices = tuple(
        GpuDeviceDescriptor(f"gpu-{i}", f"model-{i}", 1024) for i in range(2)
    )
    bindings = ("GPU-private-0", "GPU-private-1")
    busy: set[str] = set()
    observations: list[tuple[str, ...]] = []
    failed = False

    def observe(observer: NvidiaSmiGpuProcessObserver):
        observations.append(observer.selected_uuids)
        return {
            uuid: GpuProcessObservation(
                uuid,
                not failed,
                uuid in busy if not failed else False,
                "query_failed" if failed else "available",
            )
            for uuid in observer.selected_uuids
        }

    monkeypatch.setattr(NvidiaSmiGpuProcessObserver, "observe", observe)
    occupancy = GpuOccupancyPolicy(0.01, 2, 0.1)
    descriptor = ResidentProfileDescriptor(
        "resident-1", "v1", "project-1", "environment-1", "executor-1"
    )
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    from loom.queue.agent_sessions import LocalOwnerOperatorPolicy
    policy = AgentPolicyConfig(
        local_owner=LocalOwnerOperatorPolicy(("drain",), ("agent-a",), ("default",)),
        agents=(
            AgentPrincipalPolicy(
                "credential-a",
                "principal-a",
                "agent-a",
                ("default",),
                capabilities,
                devices,
            ),
        )
    )
    store = LocalRunStore(tmp_path / "runs")
    run_uri, authority = _prepare_gpu_environment_run(
        store,
        run_name="occupancy-run",
        preferred_models=("model-0", "model-1"),
        target="agent-a" if remote else None,
        capture_requirement=ExecutionRequirement(
            "project-1", "environment-1", "executor-1"
        )
        if remote
        else None,
        delay_seconds=1,
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        None if remote else tmp_path / "coordinator-agent",
        store.root,
        None if remote else _local_launch_profile(),
        machine_id="machine-A",
        cpu_capacity=0 if remote else 1,
        gpu_devices=()
        if remote
        else tuple(
            ConfiguredGpuDevice(d, b) for d, b in zip(devices, bindings, strict=True)
        ),
        gpu_occupancy_policy=None if remote else occupancy,
        agent_policy=policy,
        remote_profiles=(descriptor,),
        poll_interval_seconds=0.02,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = None
    agent = None
    client_config = None
    session = None
    coordinator = daemon.client_view(
        LocalDaemonPrincipal("test-client", LocalDaemonRole.CLIENT)
    )
    try:
        if remote:
            credentials = _credentials(tmp_path / "tls")
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
                            credentials["agent"].with_suffix(".crt")
                        ): "credential-a"
                    },
                ),
            )
            server.start()
            profile = ResidentExecutionProfile(
                descriptor,
                Path.cwd(),
                Path(sys.executable),
                gpu_devices=tuple(
                    ResidentGpuDevice(d, b)
                    for d, b in zip(devices, bindings, strict=True)
                ),
            )
            client_config = AgentTlsClientConfig(
                f"https://localhost:{server.port}",
                credentials["ca"].with_suffix(".crt"),
                credentials["agent"].with_suffix(".crt"),
                credentials["agent"].with_suffix(".key"),
                _fresh_remote_agent_root(tmp_path),
                (profile,),
                gpu_occupancy_policy=occupancy,
            )
            LocalDaemonAgentHttpClient.initialize_agent_root(client_config)
            agent = LocalDaemonAgentHttpClient(client_config)
            hello = agent.handshake()
            session = agent.register(
                AgentRegistration(
                    "register-occupancy",
                    str(hello["coordinator_id"]),
                    str(hello["coordinator_epoch"]),
                    agent.agent_root_id,
                    "config-1",
                    "inventory-1",
                    "availability-1",
                    ("default",),
                    capabilities,
                )
            )
            agent.refresh_resource_offer()
            agent._resource_maintenance_enabled = True

        def statuses():
            return (
                daemon.agent("agent-a").resource_status
                if remote
                else daemon.status().local_resource_status
            )

        def wait_for_reasons(expected: tuple[str, str]) -> None:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                current = statuses()
                if tuple(item.reason_code for item in current) == expected:
                    return
                sleep(0.02)
            raise AssertionError(statuses())

        wait_for_reasons(("available", "available"))
        if agent is not None:
            # Reserve GPU 0 from the idle offer, then publish changed capacity
            # before taking the delivery. The original delivery must survive.
            coordinator.submit(LocalDaemonAdmissionRequest("occupancy-item", run_uri))
            deadline = monotonic() + 10
            targeted = 0
            while monotonic() < deadline:
                with sqlite3.connect(config.control_database) as conn:
                    targeted = conn.execute(
                        "SELECT COUNT(*) FROM agent_deliveries WHERE state = 'TARGETED'"
                    ).fetchone()[0]
                if targeted == 1:
                    break
                sleep(0.02)
            assert targeted == 1
        busy.add(bindings[0])
        if agent is not None:
            # Lose the acknowledgement after the coordinator committed the update.
            original_complete = _RemoteAgentJournal.complete_mutation
            lost = False

            def lose_response(journal, operation, operation_id, result):
                nonlocal lost
                if operation == "offer" and not lost:
                    lost = True
                    raise QueueServiceError("simulated lost occupancy response")
                return original_complete(journal, operation, operation_id, result)

            monkeypatch.setattr(_RemoteAgentJournal, "complete_mutation", lose_response)
            for member in agent._configured_provider_members or ():
                if isinstance(member, GpuResourceProvider):
                    member.refresh_occupancy(force=True)
            with pytest.raises(QueueServiceError, match="lost occupancy"):
                agent.refresh_resource_offer()
            assert session is not None
            old_session = agent.active_session()
            assert (
                old_session is not None
                and old_session.availability_revision == session.availability_revision
            )
            # Reopen the same root and replay the exact pending publication.
            root_id = agent.agent_root_id
            agent.close()
            assert client_config is not None
            agent = LocalDaemonAgentHttpClient(client_config)
            assert agent.agent_root_id == root_id
            agent.refresh_resource_offer()
            agent._resource_maintenance_enabled = True
        wait_for_reasons(("external_process_detected", "available"))
        inspected_count = len(observations)
        statuses()
        statuses()
        if remote:
            assert len(observations) == inspected_count
            with sqlite3.connect(config.control_database) as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM agent_deliveries WHERE state = 'TARGETED'"
                    ).fetchone()[0]
                    == 1
                )
        if agent is not None:
            session = agent.active_session()
            assert session is not None
            declined = agent.execute_one(
                session.session_id,
                session.availability_revision,
                sequence=agent.next_poll_sequence(session.session_id),
                wait_timeout_ms=1000,
            )
            assert declined["state"] == "DECLINED"
            assert declined["reason_code"] == "external_process_detected"
            declined_session = declined["session"]
            assert isinstance(declined_session, Mapping)
            assignment_id = str(declined["assignment_id"])
            # An exact lost-response replay retains the reason and revision.
            replayed = agent.decline_assignment(
                session.session_id,
                assignment_id,
                availability_revision=str(declined_session["availability_revision"]),
                reason_code="external_process_detected",
            )
            assert (
                freeze_plain_data(replayed.value(), path="replayed decline")
                == declined_session
            )
            with pytest.raises(QueueConflictError, match="protocol conflict"):
                agent.decline_assignment(
                    session.session_id,
                    assignment_id,
                    availability_revision=replayed.availability_revision,
                    reason_code="observation_unavailable",
                )
            admission = coordinator.admission_for_queue_item("occupancy-item")
            owners = coordinator.admission(admission.admission_id).owners
            assignment_owner = owners["assignment"]
            assert isinstance(assignment_owner, Mapping)
            records = assignment_owner["assignments"]
            assert isinstance(records, (tuple, list))
            assert any(
                isinstance(item, Mapping)
                and item["assignment_id"] == assignment_id
                and item["decline_reason_code"] == "external_process_detected"
                for item in records
            )
            agent.refresh_resource_offer()
            session = agent.active_session()
            assert session is not None
            with ThreadPoolExecutor(max_workers=1) as workers:
                execution = workers.submit(
                    agent.execute_one,
                    session.session_id,
                    session.availability_revision,
                    sequence=agent.next_poll_sequence(session.session_id),
                    wait_timeout_ms=5000,
                )
                wait_for_reasons(("external_process_detected", "loom_claimed"))
                busy.clear()
                # execute_one keeps reporting while the real subprocess runs.
                wait_for_reasons(("available", "loom_claimed"))
                assert execution.result(timeout=30)["state"] == "RELEASED"
            agent.refresh_resource_offer()
        else:
            coordinator.submit(LocalDaemonAdmissionRequest("occupancy-item", run_uri))
            wait_for_reasons(("external_process_detected", "loom_claimed"))
            busy.clear()
        assert (
            coordinator.wait("occupancy-item", timeout_seconds=30).state
            is LocalDaemonAdmissionState.SUCCEEDED
        )
        snapshot = authority.open_run(run_uri)
        assert snapshot.status is RunStatus.SUCCEEDED
        output = LocalArtifactStore(store.local_artifact_root(run_uri)).load(
            snapshot.stages[0].artifact_facts[0].artifact
        )
        assert isinstance(output, Mapping)
        assert output["value"] == bindings[1]
        # Observe exact native device/settlement evidence, never requested GPUs.
        from loom.queue.operations import inspect_local_assignment
        admission = coordinator.admission_for_queue_item("occupancy-item")
        detail = coordinator.admission(admission.admission_id)
        assignment_records = cast(Sequence[Mapping[str, Any]], cast(Mapping[str, Any], detail.owners["assignment"])["assignments"])
        root = cast(AgentTlsClientConfig, client_config).agent_root if remote else config.agent_root
        assert root is not None
        assignment_observations = [inspect_local_assignment(root, item["assignment_id"]) for item in assignment_records]
        actual = [item for item in assignment_observations if item.availability == "available" and item.value["actual_gpu_uuids"] is not None]
        assert len(actual) == 1
        assert tuple(cast(Sequence[str], actual[0].value["actual_gpu_uuids"])) == (bindings[1],)
        assert actual[0].value["providers_released"] is True
        assert actual[0].value["containment"] == "contained"
        operator = daemon.operator_view(LocalDaemonPrincipal(f"uid:{os.getuid()}", LocalDaemonRole.OPERATOR))
        assignment = operator.observe_assignment(cast(str, actual[0].value["assignment_id"]))
        assert assignment.value["claim_id"] == actual[0].value["claim_id"]
        assert assignment.value["released"] is True
        if remote:
            claim = cast(Mapping[str, Any], assignment.value["actual_claims"])
            assert claim["availability"] == "available"
            assert tuple(claim["actual_gpu_uuids"]) == (bindings[1],)
            assert claim["source"] == "native_supervisor_launch"
            assert claim["gpu_capacity_keys"]
        assert "retirement_secret" not in json.dumps(assignment.to_dict())
        wait_for_reasons(("available", "available"))
        failed = True
        if agent is not None:
            for member in agent._configured_provider_members or ():
                if isinstance(member, GpuResourceProvider):
                    member.refresh_occupancy(force=True)
            agent.refresh_resource_offer()
        wait_for_reasons(("observation_unavailable", "observation_unavailable"))
        safe_projection = json.dumps([item.to_dict() for item in statuses()])
        assert not any(binding in safe_projection for binding in bindings)
    finally:
        if agent is not None:
            if agent._supervisor is not None:
                agent._supervisor.shutdown_for_test()
            agent.close()
        if server is not None:
            server.stop()
        daemon.stop()
