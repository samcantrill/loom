from __future__ import annotations

import hashlib
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys

import pytest

import loom.queue._remote_stage_execution as remote_stage_execution
import loom.queue.agent_sessions as agent_sessions
from loom.artifacts import ArtifactRef
from loom.pipeline.execution.models import StageWorkerRequest, StageWorkerResult
from loom.pipeline.planning import StageFingerprintPayload, StageFingerprintRecord
from loom.pipeline.status import StageStatus
from loom.queue import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    ResidentWorkerLaunchProfile,
)
from loom.queue.agent_sessions import (
    AgentOffer,
    AgentProviderDescriptor,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    AgentSessionService,
    AgentTransferAuthorizationStaleError,
    _target_remote_delivery,
)
from loom.queue.agent_session_transport import _RemoteAgentJournal
from loom.queue._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    TRANSFER_CHUNK_BYTES,
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
    _ResidentAssignmentBundle,
    _RemoteArtifact,
    _ResidentAssignmentWorkspace,
    _RemoteExecutionReport,
    _RemoteOutputArtifact,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import thaw_plain_data


def _provider_descriptors(*kinds: str) -> tuple[SchedulingComponentDescriptor, ...]:
    return tuple(
        SchedulingComponentDescriptor(
            kind, 1, "1", f"test-{kind}-provider", f"{kind}-configuration"
        )
        for kind in sorted(kinds)
    )


def _agent_provider_descriptors(*kinds: str) -> tuple[AgentProviderDescriptor, ...]:
    return tuple(
        AgentProviderDescriptor(
            descriptor,
            (
                ResourceClaimContractDescriptor(
                    descriptor.kind, 1, f"builtin-{descriptor.kind}-claim-v1"
                ),
            ),
        )
        for descriptor in _provider_descriptors(*kinds)
    )


def _profile(tmp_path: Path) -> ResidentExecutionProfile:
    project_root = tmp_path / "resident-project"
    project_root.mkdir(exist_ok=True)
    return ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "profile-1", "revision-1", "project-1", "env-1", "executor-1"
        ),
        project_root,
        Path(sys.executable),
    )


def _request(
    profile: ResidentExecutionProfile,
    *,
    stage_config: dict[str, str] | None = None,
) -> _ResidentAssignmentBundle:
    worker = StageWorkerRequest(
        1,
        "run-opaque-1",
        "build",
        1,
        "2020-01-01T00:00:00Z",
        "local",
        {"source": ArtifactRef("source", "file:///coordinator/private", "bytes")},
        StageFingerprintRecord.create(
            algorithm="sha256",
            payload=StageFingerprintPayload(
                schema_version=2,
                policy_name="loom.stage.semantic",
                policy_version=2,
                stage_name="build",
                factory_target="pkg.Stage",
                factory_init={},
                stage_config={} if stage_config is None else stage_config,
                fingerprint_fields={},
                declared_inputs={"source": "seed.data"},
                bound_inputs={},
                declared_outputs={
                    "result": {
                        "artifact_type": "bytes",
                        "codec_key": None,
                        "schema_version": 1,
                        "metadata": {},
                    }
                },
                python_version="3.12",
                loom_version="test",
                git={},
                dependencies={},
                extra={},
            ),
            inputs_summary={"stage_name": "build"},
        ),
        "/coordinator/stdout",
        "/coordinator/stderr",
        "/coordinator/trace",
        "/coordinator/result",
        {"stage_id": "build", "executor": "local"},
    )
    data = b"input"
    atom = CapacityAtom(
        "cpu", "agent-1:cpu", ExactQuantity(1), "count", ExactQuantity(1)
    )
    claim = ResourceClaim(
        "cpu",
        ResourceClaimContractDescriptor("cpu", 1, "loom.cpu.claim.v1"),
        (atom,),
        1,
    )
    return _ResidentAssignmentBundle.from_worker_request(
        assignment_id="assignment-1",
        stage_work_id="stage-work-1",
        attempt_id="attempt-1",
        offer_id="offer-1",
        claim_id="claim-1",
        worker_request=worker,
        profile=profile.descriptor,
        inputs=(
            _RemoteArtifact(
                "input-1",
                "source",
                hashlib.sha256(data).hexdigest(),
                len(data),
                "seed.data",
                "bytes",
            ),
        ),
        declared_outputs=("result",),
        claims=(claim,),
        provider_descriptors=_provider_descriptors("cpu"),
    )


def test_remote_request_excludes_coordinator_paths_and_derives_agent_paths(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    request = _request(profile)
    payload = request.to_dict()
    assert "/coordinator" not in str(payload)
    assert str(profile.project_root) not in str(payload)
    workspace = _ResidentAssignmentWorkspace(tmp_path, request.assignment_id)
    workspace.persist_request(request, profile)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    worker = workspace.worker_request()
    assert worker.run_uri == "loom-agent:assignment-1"
    assert str(tmp_path / "assignments" / "assignment-1") in worker.stdout_path
    assert "/coordinator" not in worker.stdout_path


def test_remote_workspace_rejects_parent_directory_identity(tmp_path: Path) -> None:
    with pytest.raises(QueueServiceError, match="assignment_id is invalid"):
        _ResidentAssignmentWorkspace(tmp_path, "..")


def test_delivered_poll_atomically_retains_an_unresolved_assignment(
    tmp_path: Path,
) -> None:
    agent_root = tmp_path / "agent"
    LocalDaemon.initialize_agent_root(agent_root)
    request = _request(_profile(tmp_path))
    poll_request = {
        "session_id": "session-1",
        "availability_revision": "availability-1",
        "sequence": 1,
        "wait_timeout_ms": 1,
    }
    with sqlite3.connect(agent_root / "control.sqlite") as conn:
        conn.execute(
            "INSERT INTO agent_poll_state_local(session_id, availability_revision, "
            "sequence, request_digest, state, result_json) VALUES "
            "('session-1', 'availability-1', 1, ?, 'PENDING', NULL)",
            (hashlib.sha256(json.dumps(poll_request).encode()).hexdigest(),),
        )
        conn.commit()

    journal = _RemoteAgentJournal(agent_root)
    try:
        journal.complete_poll(
            "session-1",
            1,
            {
                "result": "assignment",
                "sequence": 1,
                "coordinator_epoch": "epoch-1",
                "request": request.to_dict(),
            },
        )
    finally:
        journal.close()

    with sqlite3.connect(agent_root / "control.sqlite") as conn:
        reference = conn.execute(
            "SELECT resolved FROM agent_session_references WHERE session_id = ? "
            "AND reference_kind = 'delivery' AND reference_id = ?",
            ("session-1", request.assignment_id),
        ).fetchone()
        poll_state = conn.execute(
            "SELECT state FROM agent_poll_state_local "
            "WHERE session_id = 'session-1' AND sequence = 1"
        ).fetchone()
    assert reference == (0,)
    assert poll_state == ("DELIVERED",)


def test_remote_semantic_request_rejects_path_bearing_fields(tmp_path: Path) -> None:
    request = _request(
        _profile(tmp_path),
        stage_config={"cache_path": "/coordinator/private"},
    )
    assert _ResidentAssignmentBundle.from_dict(request.to_dict()) == request
    with pytest.raises(QueueServiceError, match="path-bearing"):
        request.validate_remote_transport()
    with pytest.raises(QueueServiceError, match="path-bearing"):
        _ResidentAssignmentBundle.from_remote_dict(request.to_dict())

    portable_request = _request(_profile(tmp_path))
    metadata_request = replace(
        portable_request,
        worker_metadata={"coordinator_path": "/coordinator/private"},
    )
    with pytest.raises(QueueServiceError, match="path-bearing"):
        metadata_request.validate_remote_transport()
    with pytest.raises(QueueServiceError, match="path-bearing"):
        replace(
            portable_request.inputs[0],
            metadata={"source_url": "https://coordinator.invalid/input"},
        )


def test_remote_regular_file_input_rejects_a_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.data"
    source.write_bytes(b"input")
    link = tmp_path / "source-link.data"
    link.symlink_to(source)
    ref = ArtifactRef("source", link.as_uri(), "bytes")

    with pytest.raises(QueueServiceError, match="regular-file inputs only"):
        _RemoteArtifact.from_local_ref(
            transfer_id="input-1",
            logical_name="source",
            ref=ref,
        )


def test_remote_request_rejects_the_old_wire_schema(tmp_path: Path) -> None:
    encoded = _request(_profile(tmp_path)).to_dict()
    encoded["schema_version"] = 2

    with pytest.raises(QueueServiceError, match="schema is unsupported"):
        _ResidentAssignmentBundle.from_dict(encoded)


def test_launch_is_unreachable_until_inputs_and_grant_are_durable(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    request = _request(profile)
    workspace = _ResidentAssignmentWorkspace(tmp_path, request.assignment_id)
    workspace.persist_request(request, profile)
    with pytest.raises(QueueConflictError, match="durable grant"):
        workspace.mark_process_started("execution-1", 101)
    with pytest.raises(QueueConflictError, match="not durable"):
        workspace.accept()
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    with pytest.raises(QueueConflictError, match="durable grant"):
        workspace.mark_process_started("execution-1", 101)
    workspace.grant("fence-1")
    workspace.mark_process_started("execution-1", 101)
    workspace.mark_process_started("execution-1", 101)
    with pytest.raises(QueueConflictError, match="identity conflicts"):
        workspace.mark_process_started("execution-2", 102)


def test_input_replay_and_event_sequence_are_durable_and_exact(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    request = _request(profile)
    workspace = _ResidentAssignmentWorkspace(tmp_path, request.assignment_id)
    workspace.persist_request(request, profile)
    crash_window_part = workspace.root / "input-staging" / "input-1.part"
    crash_window_part.parent.mkdir(parents=True)
    crash_window_part.write_bytes(b"input")
    workspace.stage_input("input-1", b"input")
    workspace.stage_input("input-1", b"input")
    with pytest.raises(QueueConflictError, match="durable bytes"):
        workspace.stage_input("input-1", b"other")
    workspace.record_event(1, "event-1", {"kind": "accepted"})
    workspace.record_event(1, "event-1", {"kind": "accepted"})
    with pytest.raises(QueueConflictError, match="gap"):
        workspace.record_event(3, "event-3", {"kind": "bad"})
    workspace.accept()
    workspace.grant("fence-1")
    workspace.mark_process_started("execution-1", 101)
    output = workspace.root / "outputs" / "result"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"output")
    workspace.persist_worker_result(
        StageWorkerResult(
            schema_version=1,
            run_uri="loom-agent:assignment-1",
            stage_name="build",
            attempt=1,
            status=StageStatus.SUCCEEDED,
            started_at="2020-01-01T00:00:00Z",
            finished_at="2020-01-01T00:00:01Z",
            executor_name="local",
            outputs={
                "result": ArtifactRef(
                    "result.data",
                    output.resolve().as_uri(),
                    "bytes",
                    metadata={"quality": "verified"},
                )
            },
            exit_code=0,
        )
    )
    report = workspace.retain_outputs()
    assert report.outputs[0].logical_name == "result"
    assert report.outputs[0].metadata == {"quality": "verified"}
    replayed = _RemoteExecutionReport.from_dict(report.to_dict())
    assert replayed.outputs[0].metadata == {"quality": "verified"}
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE remote_transfers(assignment_id TEXT, direction TEXT, "
            "logical_name TEXT, private_path TEXT, descriptor_json TEXT, "
            "finalized INTEGER)"
        )
        conn.execute(
            "INSERT INTO remote_transfers VALUES (?, 'output', ?, ?, ?, 1)",
            (
                request.assignment_id,
                "result",
                str(workspace.root / "retained-outputs" / "result"),
                json.dumps(
                    report.outputs[0].to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        coordinator_refs = AgentSessionService._coordinator_output_refs(
            conn, request.assignment_id
        )
    assert coordinator_refs["result"].metadata == {"quality": "verified"}
    assert str(workspace.root) not in str(report.to_dict())


def test_input_publish_before_commit_replay_adopts_only_exact_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _profile(tmp_path)
    data = b"a" * (TRANSFER_CHUNK_BYTES + 7)
    initial = _request(profile)
    request = replace(
        initial,
        inputs=(
            replace(
                initial.inputs[0],
                digest=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
            ),
        ),
    )
    workspace = _ResidentAssignmentWorkspace(tmp_path, request.assignment_id)
    workspace.persist_request(request, profile)
    first = data[:TRANSFER_CHUNK_BYTES]
    final = data[TRANSFER_CHUNK_BYTES:]
    assert workspace.stage_input_chunk("input-1", 0, first, final=False) == len(first)

    original_publish = remote_stage_execution._publish_staged_file

    def crash_after_publish(staging: Path, target: Path) -> None:
        original_publish(staging, target)
        raise RuntimeError("simulated crash after input publication")

    monkeypatch.setattr(
        remote_stage_execution, "_publish_staged_file", crash_after_publish
    )
    with pytest.raises(RuntimeError, match="after input publication"):
        workspace.stage_input_chunk("input-1", len(first), final, final=True)
    monkeypatch.setattr(
        remote_stage_execution, "_publish_staged_file", original_publish
    )

    assert workspace.stage_input_chunk("input-1", len(first), final, final=True) == len(
        data
    )
    with sqlite3.connect(workspace._db) as conn:
        assert conn.execute(
            "SELECT received_bytes, finalized FROM transfers WHERE transfer_id = ?",
            ("input-1",),
        ).fetchone() == (len(data), 1)
        conn.execute(
            "UPDATE transfers SET received_bytes = ?, finalized = 0 "
            "WHERE transfer_id = ?",
            (len(first), "input-1"),
        )
        conn.commit()
    workspace.input_path("source").write_bytes(b"conflict")
    with pytest.raises(QueueConflictError, match="conflicts with durable identity"):
        workspace.stage_input_chunk("input-1", len(first), final, final=True)
    with sqlite3.connect(workspace._db) as conn:
        assert conn.execute(
            "SELECT received_bytes, finalized FROM transfers WHERE transfer_id = ?",
            ("input-1",),
        ).fetchone() == (len(first), 0)


def test_targeted_current_poll_delivers_only_the_exact_durable_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    policy = AgentPolicyConfig(
        agents=(
            AgentPrincipalPolicy(
                "credential-1", "principal-1", "agent-1", ("default",), capabilities
            ),
        )
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        tmp_path / "agent",
        tmp_path / "runs",
        ResidentWorkerLaunchProfile(
            Path.cwd(),
            Path(sys.executable),
            ResidentProfileDescriptor(
                "test-local", "v1", "test-project", "test-environment", "test-executor"
            ).to_dict(),
        ),
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    now = ["2026-01-01T00:00:00Z"]
    daemon = LocalDaemon(config, clock=lambda: now[0])
    daemon.start()
    try:
        view = daemon.agent_view(
            LocalDaemonPrincipal("principal-1", LocalDaemonRole.AGENT, "credential-1")
        )
        handshake = view.handshake()
        session = view.register(
            AgentRegistration(
                "register-1",
                str(handshake["coordinator_id"]),
                str(handshake["coordinator_epoch"]),
                "agent-root-1",
                "config-1",
                "inventory-1",
                "availability-1",
                ("default",),
                capabilities,
                retirement_verifier="01" * 32,
            )
        )
        profile = _profile(tmp_path)
        view.publish_offer(
            AgentOffer(
                session.session_id,
                session.coordinator_epoch,
                "config-1",
                "inventory-1",
                "availability-1",
                1,
                1,
                30,
                _agent_provider_descriptors("cpu", "memory"),
                resident_profiles=(profile.descriptor,),
            ),
            idempotency_key="offer-1",
        )
        request = _request(profile)
        input_path = tmp_path / "input.data"
        input_path.write_bytes(b"input")
        with pytest.raises(QueueServiceError, match="path-bearing"):
            _target_remote_delivery(
                daemon,
                session_id=session.session_id,
                availability_revision="availability-1",
                request=_request(
                    profile,
                    stage_config={"cache_path": "/coordinator/private"},
                ),
                run_uri="file:///coordinator/run",
                input_paths={"input-1": input_path},
            )
        _target_remote_delivery(
            daemon,
            session_id=session.session_id,
            availability_revision="availability-1",
            request=request,
            run_uri="file:///coordinator/run",
            input_paths={"input-1": input_path},
        )
        _target_remote_delivery(
            daemon,
            session_id=session.session_id,
            availability_revision="availability-1",
            request=request,
            run_uri="file:///coordinator/run",
            input_paths={"input-1": input_path},
        )
        with pytest.raises(QueueConflictError, match="owner identity conflicts"):
            _target_remote_delivery(
                daemon,
                session_id=session.session_id,
                availability_revision="availability-1",
                request=request,
                run_uri="file:///coordinator/other-run",
                input_paths={"input-1": input_path},
            )
        delivered = view.wait_for_work(
            session.session_id, "availability-1", sequence=1, wait_timeout_ms=1
        )
        assert delivered["result"] == "assignment"
        assert (
            thaw_plain_data(delivered["request"], path="request") == request.to_dict()
        )
        first_authorization = view.authorize_transfers(
            session.session_id,
            request.assignment_id,
            expected_revision=0,
            operation_id=f"{request.assignment_id}:authorize:1",
        )
        now[0] = "2026-01-01T00:01:01Z"
        with pytest.raises(AgentTransferAuthorizationStaleError):
            view.read_input_chunk(
                session.session_id,
                request.assignment_id,
                "input-1",
                offset=0,
                authorization_id=str(first_authorization["authorization_id"]),
                authorization_revision=1,
            )
        renewed = view.authorize_transfers(
            session.session_id,
            request.assignment_id,
            expected_revision=1,
            operation_id=f"{request.assignment_id}:authorize:2",
        )
        chunk = view.read_input_chunk(
            session.session_id,
            request.assignment_id,
            "input-1",
            offset=0,
            authorization_id=str(renewed["authorization_id"]),
            authorization_revision=2,
        )
        assert chunk["next_offset"] == 5
        assert chunk["final"] is True
        output_data = b"o" * (TRANSFER_CHUNK_BYTES + 11)
        output = _RemoteOutputArtifact(
            "output-1",
            "result",
            hashlib.sha256(output_data).hexdigest(),
            len(output_data),
            "result.data",
            "bytes",
            None,
            1,
            None,
            None,
            None,
        )
        with sqlite3.connect(config.control_database) as conn:
            conn.execute(
                "UPDATE remote_assignments SET state = 'RUNNING', fence = ? "
                "WHERE assignment_id = ?",
                ("fence-1", request.assignment_id),
            )
            conn.commit()
        view.declare_outputs(
            session.session_id,
            request.assignment_id,
            fence="fence-1",
            authorization_id=str(renewed["authorization_id"]),
            authorization_revision=2,
            report=_RemoteExecutionReport(
                request.assignment_id,
                request.stage_name,
                request.attempt,
                StageStatus.SUCCEEDED,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:01Z",
                "local",
                outputs=(output,),
                exit_code=0,
            ),
        )
        first_output = output_data[:TRANSFER_CHUNK_BYTES]
        final_output = output_data[TRANSFER_CHUNK_BYTES:]
        view.upload_output_chunk(
            session.session_id,
            request.assignment_id,
            output.transfer_id,
            offset=0,
            data=first_output,
            final=False,
            authorization_id=str(renewed["authorization_id"]),
            authorization_revision=2,
        )
        original_publish = agent_sessions._publish_staged_file

        def crash_after_publish(staging: Path, target: Path) -> None:
            original_publish(staging, target)
            raise RuntimeError("simulated crash after output publication")

        monkeypatch.setattr(agent_sessions, "_publish_staged_file", crash_after_publish)
        with pytest.raises(RuntimeError, match="after output publication"):
            view.upload_output_chunk(
                session.session_id,
                request.assignment_id,
                output.transfer_id,
                offset=len(first_output),
                data=final_output,
                final=True,
                authorization_id=str(renewed["authorization_id"]),
                authorization_revision=2,
            )
        monkeypatch.setattr(agent_sessions, "_publish_staged_file", original_publish)
        assert view.upload_output_chunk(
            session.session_id,
            request.assignment_id,
            output.transfer_id,
            offset=len(first_output),
            data=final_output,
            final=True,
            authorization_id=str(renewed["authorization_id"]),
            authorization_revision=2,
        ) == {
            "transfer_id": output.transfer_id,
            "received_bytes": len(output_data),
            "final": True,
        }
        output_target = (
            config.coordinator_root
            / "remote-relay"
            / request.assignment_id
            / "outputs"
            / output.logical_name
        )
        assert output_target.read_bytes() == output_data
        with sqlite3.connect(config.control_database) as conn:
            assert conn.execute(
                "SELECT received_bytes, finalized FROM remote_transfers "
                "WHERE assignment_id = ? AND direction = 'output' AND transfer_id = ?",
                (request.assignment_id, output.transfer_id),
            ).fetchone() == (len(output_data), 1)
            conn.execute(
                "UPDATE remote_transfers SET received_bytes = ?, finalized = 0 "
                "WHERE assignment_id = ? AND direction = 'output' AND transfer_id = ?",
                (len(first_output), request.assignment_id, output.transfer_id),
            )
            conn.commit()
        output_target.write_bytes(b"conflict")
        with pytest.raises(QueueConflictError, match="conflicts with durable identity"):
            view.upload_output_chunk(
                session.session_id,
                request.assignment_id,
                output.transfer_id,
                offset=len(first_output),
                data=final_output,
                final=True,
                authorization_id=str(renewed["authorization_id"]),
                authorization_revision=2,
            )
        with sqlite3.connect(config.control_database) as conn:
            assert conn.execute(
                "SELECT received_bytes, finalized FROM remote_transfers "
                "WHERE assignment_id = ? AND direction = 'output' AND transfer_id = ?",
                (request.assignment_id, output.transfer_id),
            ).fetchone() == (len(first_output), 0)
        retained_input = (
            config.coordinator_root
            / "remote-relay"
            / request.assignment_id
            / "inputs"
            / "input-1"
        )
        retained_input.write_bytes(b"other")
        with pytest.raises(QueueConflictError, match="bytes conflict"):
            _target_remote_delivery(
                daemon,
                session_id=session.session_id,
                availability_revision="availability-1",
                request=request,
                run_uri="file:///coordinator/run",
                input_paths={"input-1": input_path},
            )
        with pytest.raises(QueueConflictError, match="current offer"):
            _target_remote_delivery(
                daemon,
                session_id=session.session_id,
                availability_revision="availability-1",
                request=replace(request, assignment_id="assignment-expired"),
                run_uri="file:///coordinator/run",
                input_paths={"input-1": input_path},
            )
    finally:
        daemon.stop()
