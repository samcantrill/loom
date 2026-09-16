from __future__ import annotations

from collections.abc import Mapping
import hashlib
from dataclasses import replace
import json
from pathlib import Path
import pickle
import sqlite3
import sys

import pytest

import loom.queue._remote_stage_execution as remote_stage_execution
import loom.queue.agent_sessions as agent_sessions
from loom.artifacts import ArtifactRef
from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    ExecutionFailure,
    STAGE_WORKER_REQUEST_SCHEMA_VERSION,
    StageWorkerRequest,
    StageWorkerResult,
)
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
from loom.queue._agent_process_supervisor import ResidentWorkerLaunch, _launch_value
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
from loom.queue.preparation import (
    PREPARATION_STAGE_TARGET,
    PreparationChildInput,
    SharedInputReceipt,
)
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


def test_preparation_profile_preserves_its_binding_across_process_serialization(
    tmp_path: Path,
) -> None:
    roots = {"projects": tmp_path / "snapshots"}
    profile = replace(_profile(tmp_path), preparation_shared_roots=roots)
    retained_launch = profile.launch_profile
    roots["projects"] = tmp_path / "different-snapshots"

    received = pickle.loads(pickle.dumps(profile))
    assert received == profile
    assert received.launch_profile == retained_launch
    assert received.preparation_shared_roots == {"projects": tmp_path / "snapshots"}


def _request(
    profile: ResidentExecutionProfile,
    *,
    stage_config: dict[str, str] | None = None,
) -> _ResidentAssignmentBundle:
    worker = StageWorkerRequest(
        STAGE_WORKER_REQUEST_SCHEMA_VERSION,
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
        {
            "stage_id": "build",
            "executor": "local",
            "resources": {"entries": {}},
            "resource_policy": {"account_for": "all", "enforce": []},
            "resource_selection": {"account_for": [], "enforce": []},
        },
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


def test_only_fixed_preparation_input_can_cross_the_semantic_path_guard(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    request = _request(profile)
    binding = PreparationChildInput(
        "prepare-1",
        "existing",
        "configs/pipeline.yaml",
        SharedInputReceipt("sha256:" + "a" * 64, "projects", "capture-1"),
        profile.descriptor.to_dict(),
    )
    fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
    prepared_fingerprint = StageFingerprintRecord.create(
        algorithm=fingerprint.algorithm,
        payload=replace(
            fingerprint.payload,
            factory_target=PREPARATION_STAGE_TARGET,
            stage_config=binding.to_dict(),
        ),
        inputs_summary=fingerprint.inputs_summary,
    )
    preparation = replace(request, fingerprint=prepared_fingerprint.to_dict())
    assert (
        _ResidentAssignmentBundle.from_remote_dict(preparation.to_dict()) == preparation
    )
    assert preparation.preparation_input == binding
    with pytest.raises(QueueServiceError, match="path-bearing"):
        replace(
            preparation,
            resolved_runtime={
                **preparation.resolved_runtime,
                "scratch_path": "/worker/private",
            },
        ).validate_remote_transport()
    ordinary_fingerprint = StageFingerprintRecord.create(
        algorithm=fingerprint.algorithm,
        payload=replace(prepared_fingerprint.payload, factory_target="pkg.Stage"),
        inputs_summary=fingerprint.inputs_summary,
    )
    with pytest.raises(QueueServiceError, match="path-bearing"):
        replace(
            request, fingerprint=ordinary_fingerprint.to_dict()
        ).validate_remote_transport()


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


@pytest.mark.parametrize("status", [StageStatus.SUCCEEDED, StageStatus.FAILED])
@pytest.mark.parametrize("legacy", [False, True])
def test_workspace_joins_actual_launch_controls_without_rewriting_worker_bytes(
    tmp_path: Path,
    status: StageStatus,
    legacy: bool,
) -> None:
    profile = _profile(tmp_path)
    request = _request(profile)
    workspace = _ResidentAssignmentWorkspace(tmp_path, request.assignment_id)
    workspace.persist_request(request, profile)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    workspace.grant("fence-1")
    controls = (
        {
            "resource": "gpu",
            "owner": "managed_provider",
            "mechanism": "provider_environment_binding",
            "disposition": "requested",
        },
    )
    launch = ResidentWorkerLaunch(
        supervisor_id="supervisor-1",
        continuity_epoch="epoch-1",
        agent_id="agent-1",
        session_id="session-1",
        assignment_id=request.assignment_id,
        process_execution_id="execution-1",
        execution_fence="fence-1",
        launch_operation_id="launch-1",
        bundle_digest="a" * 64,
        workspace_root=workspace.root,
        profile=profile.launch_profile,
        environment={},
        schema_version=None if legacy else 2,
        resource_controls=None if legacy else controls,
    )
    workspace.persist_supervisor_launch(json.dumps(_launch_value(launch)))
    workspace.mark_process_started("execution-1", 101)
    output = workspace.root / "result.data"
    output.write_bytes(b"output")
    failure = (
        None
        if status is StageStatus.SUCCEEDED
        else ExecutionFailure(
            schema_version=1,
            run_uri=f"loom-agent:{request.assignment_id}",
            stage_name=request.stage_name,
            attempt=request.attempt,
            failed_at="2020-01-01T00:00:01Z",
            executor="local",
            failure_type="stage_exception",
            message="application failed after launch",
        )
    )
    result = StageWorkerResult(
        schema_version=1,
        run_uri=f"loom-agent:{request.assignment_id}",
        stage_name=request.stage_name,
        attempt=request.attempt,
        status=status,
        started_at="2020-01-01T00:00:00Z",
        finished_at="2020-01-01T00:00:01Z",
        executor_name="local",
        failure=failure,
        outputs={"result": ArtifactRef("result", output.as_uri(), "bytes")}
        if status is StageStatus.SUCCEEDED
        else {},
        executor_metadata={"process_created": False, "application_detail": "retained"},
    )
    result_path = workspace.root / "worker-result.json"
    result_path.write_text(json.dumps(result.to_dict()))
    original_bytes = result_path.read_bytes()
    workspace.persist_worker_result(result)
    report = workspace.retain_outputs()
    assert report.process_created is True
    if legacy:
        assert report.resource_controls is None
    else:
        assert report.resource_controls == ({**controls[0], "disposition": "applied"},)
        if report.failure is not None:
            failure_controls = report.failure.executor_metadata["resource_controls"]
            assert isinstance(failure_controls, (list, tuple))
            assert isinstance(failure_controls[0], Mapping)
            assert failure_controls[0]["disposition"] == "applied"
    saved = workspace.worker_result()
    assert saved is not None
    assert saved.executor_metadata["application_detail"] == "retained"
    workspace.persist_worker_result(result)
    assert workspace.retain_outputs().to_dict() == report.to_dict()
    assert result_path.read_bytes() == original_bytes


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
            executor_metadata={
                "request": {"executor": "local", "stage_name": "build"},
                "command": ["python", "--workspace", str(workspace.root)],
                "stdout": "private worker output",
            },
        )
    )
    report = workspace.retain_outputs()
    assert report.outputs[0].logical_name == "result"
    assert report.outputs[0].metadata == {"quality": "verified"}
    replayed = _RemoteExecutionReport.from_dict(report.to_dict())
    assert replayed.outputs[0].metadata == {"quality": "verified"}
    assert replayed.schema_version == 3
    assert replayed.process_created is True
    assert replayed.executor_metadata is not None
    assert replayed.executor_metadata["request"] == {
        "executor": "local",
        "stage_name": "build",
    }
    assert (
        replayed.to_dict()["executor_metadata"] == report.to_dict()["executor_metadata"]
    )
    assert "private worker output" not in json.dumps(report.to_dict())
    assert str(workspace.root) not in json.dumps(report.to_dict())
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


def test_resident_no_start_failure_is_durable_without_process_identity(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    request = _request(profile)
    workspace = _ResidentAssignmentWorkspace(tmp_path, request.assignment_id)
    workspace.persist_request(request, profile)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    workspace.grant("fence-1")
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=f"loom-agent:{request.assignment_id}",
        stage_name=request.stage_name,
        attempt=request.attempt,
        failed_at="2020-01-01T00:00:00Z",
        executor="local",
        failure_type="executor_infrastructure",
        message="selected 'cpu' control has no active claim",
        details={"process_created": False},
    )
    result = StageWorkerResult(
        schema_version=1,
        run_uri=f"loom-agent:{request.assignment_id}",
        stage_name=request.stage_name,
        attempt=request.attempt,
        status=StageStatus.FAILED,
        started_at="2020-01-01T00:00:00Z",
        finished_at="2020-01-01T00:00:00Z",
        executor_name="local",
        failure=failure,
        exit_code=1,
    )
    with pytest.raises(QueueConflictError, match="grant or supervisor"):
        workspace.persist_failed_before_start(result, fence="wrong-fence")
    workspace.persist_failed_before_start(result, fence="fence-1")
    report = workspace.retain_outputs()
    assert report.process_created is False
    assert report.failure == failure
    assert (
        _RemoteExecutionReport.from_dict(report.to_dict()).to_dict() == report.to_dict()
    )


def test_legacy_report_writer_shape_and_digest_do_not_acquire_current_fields() -> None:
    legacy = {
        "schema_version": 1,
        "assignment_id": "assignment-1",
        "stage_name": "build",
        "attempt": 1,
        "status": "FAILED",
        "started_at": "2020-01-01T00:00:00Z",
        "finished_at": "2020-01-01T00:00:01Z",
        "executor_name": "local",
        "outputs": [],
        "failure_type": "stage_exception",
        "message": "resident stage execution failed",
        "exception_type": "builtins.RuntimeError",
        "exit_code": 1,
    }
    encoded = json.dumps(legacy, sort_keys=True, separators=(",", ":"))
    report = _RemoteExecutionReport.from_dict(json.loads(encoded))
    replay = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
    assert replay == encoded
    assert (
        hashlib.sha256(replay.encode()).digest()
        == hashlib.sha256(encoded.encode()).digest()
    )
    assert report.failure is None
    assert report.resource_controls is None
    assert report.process_created is None
    with pytest.raises(QueueServiceError):
        _RemoteExecutionReport.from_dict({**legacy, "resource_controls": None})
    for invalid_version in (True, 1.0, "1"):
        with pytest.raises(QueueServiceError, match="schema is unsupported"):
            _RemoteExecutionReport.from_dict(
                {**legacy, "schema_version": invalid_version}
            )


def test_current_remote_report_preserves_full_failure_and_owner_start_proof(
    tmp_path: Path,
) -> None:
    message = "nested worker failure " + "x" * 2048
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri="loom-agent:assignment-1",
        stage_name="build",
        attempt=1,
        failed_at="2020-01-01T00:00:00Z",
        executor="local",
        failure_type="executor_infrastructure",
        message=message,
        details={"diagnostic_failure": {"message": "nested cause"}},
    )
    report = _RemoteExecutionReport(
        assignment_id="assignment-1",
        stage_name="build",
        attempt=1,
        status=StageStatus.FAILED,
        started_at="2020-01-01T00:00:00Z",
        finished_at="2020-01-01T00:00:01Z",
        executor_name="local",
        failure_type=failure.failure_type,
        message=message,
        exception_type=failure.exception_type,
        failure=failure,
        process_created=None,
        schema_version=2,
    )
    retained = report.to_dict()
    assert "executor_metadata" not in retained
    replayed = _RemoteExecutionReport.from_dict(retained)
    assert replayed.failure == failure
    assert json.dumps(replayed.to_dict(), sort_keys=True) == json.dumps(
        retained, sort_keys=True
    )
    assert replayed.executor_metadata is None
    with pytest.raises(QueueServiceError, match="shape is invalid"):
        _RemoteExecutionReport.from_dict({**retained, "executor_metadata": {}})
    with pytest.raises(QueueConflictError, match="summary conflicts"):
        _RemoteExecutionReport(
            assignment_id="assignment-1",
            stage_name="wrong-stage",
            attempt=1,
            status=StageStatus.FAILED,
            started_at="2020-01-01T00:00:00Z",
            finished_at="2020-01-01T00:00:01Z",
            executor_name="local",
            failure_type=failure.failure_type,
            message=message,
            exception_type=failure.exception_type,
            failure=failure,
            schema_version=2,
        )
    profile = _profile(tmp_path)
    request = _request(profile)
    workspace = _ResidentAssignmentWorkspace(tmp_path, request.assignment_id)
    workspace.persist_request(request, profile)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    workspace.grant("fence-1")
    cancelled = StageWorkerResult(
        schema_version=1,
        run_uri=f"loom-agent:{request.assignment_id}",
        stage_name=request.stage_name,
        attempt=request.attempt,
        status=StageStatus.CANCELLED,
        started_at="2020-01-01T00:00:00Z",
        finished_at="2020-01-01T00:00:00Z",
        executor_name="local",
        exit_code=1,
    )
    workspace.persist_cancelled_before_start(cancelled)
    assert workspace.retain_outputs().process_created is False


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
        binding = PreparationChildInput(
            "prepare-1",
            "existing",
            "configs/pipeline.yaml",
            SharedInputReceipt("sha256:" + "a" * 64, "projects", "capture-1"),
            profile.descriptor.to_dict(),
        )
        fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
        preparation = replace(
            request,
            fingerprint=StageFingerprintRecord.create(
                algorithm=fingerprint.algorithm,
                payload=replace(
                    fingerprint.payload,
                    factory_target=PREPARATION_STAGE_TARGET,
                    stage_config=binding.to_dict(),
                ),
                inputs_summary=fingerprint.inputs_summary,
            ).to_dict(),
        )
        from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE
        shared = replace(request, fingerprint=StageFingerprintRecord.create(
            algorithm=fingerprint.algorithm,
            payload=replace(fingerprint.payload, fingerprint_fields={SHARED_EXECUTION_SCOPE: {
                "capability": "shared-execution-v1", "roots": {}, "locations": []}}),
            inputs_summary=fingerprint.inputs_summary,
        ).to_dict())
        with pytest.raises(QueueServiceError, match="lacks shared-execution-v1"):
            _target_remote_delivery(daemon, session_id=session.session_id, availability_revision="availability-1",
                request=shared, run_uri="file:///coordinator/run", input_paths={"input-1": input_path})
        with pytest.raises(QueueServiceError, match="lacks preparation-input-v2"):
            _target_remote_delivery(
                daemon,
                session_id=session.session_id,
                availability_revision="availability-1",
                request=preparation,
                run_uri="file:///coordinator/run",
                input_paths={"input-1": input_path},
            )
        with sqlite3.connect(config.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM agent_deliveries").fetchone()[0] == 0
            )
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


def test_local_assignment_rejects_changed_binding_and_remote_export(tmp_path: Path) -> None:
    from loom.queue.preparation import LOCAL_PREPARATION_SCOPE

    profile = _profile(tmp_path)
    request = _request(profile)
    fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
    local = StageFingerprintRecord.create(
        algorithm=fingerprint.algorithm,
        payload=replace(fingerprint.payload, fingerprint_fields={LOCAL_PREPARATION_SCOPE: {
            "agent_id": "agent-1", "binding_fingerprint": profile.launch_profile.fingerprint,
        }}),
        inputs_summary=fingerprint.inputs_summary,
    )
    request = replace(request, fingerprint=local.to_dict())
    workspace = _ResidentAssignmentWorkspace(tmp_path / "agent", request.assignment_id)
    workspace.persist_request(request, profile)
    # A reopening process receives the durable scope even when config changes.
    reopened = _ResidentAssignmentWorkspace(tmp_path / "agent", request.assignment_id)
    assert reopened.request() == request
    changed = replace(profile, preparation_shared_roots={"data": tmp_path / "different"})
    with pytest.raises(QueueConflictError, match="binding identity"):
        reopened.persist_request(request, changed)
    with pytest.raises(QueueServiceError, match="unresolved local"):
        request.validate_remote_transport()
    with pytest.raises(QueueServiceError, match="unresolved local"):
        _ResidentAssignmentBundle.from_remote_dict(request.to_dict())


@pytest.mark.parametrize("backend", ["apptainer", "docker"])
def test_local_container_launch_reopens_without_recursive_worker_materialization(
    tmp_path: Path, backend: str,
) -> None:
    from loom.queue._agent_process_supervisor import _launch_from_value
    from loom.queue.preparation import LOCAL_PREPARATION_SCOPE

    image = tmp_path / "installed.sif"
    image.write_bytes(b"command construction fixture")
    binding = {
        "kind": backend,
        "container": {"image": {"reference": (
            str(image) if backend == "apptainer" else "sha256:" + "a" * 64
        )}},
        "options": {"command": sys.executable},
        "python_executable": "/opt/installed/bin/python",
        "daemon_endpoint": None if backend == "apptainer" else "unix:///var/run/docker.sock",
    }
    profile = replace(_profile(tmp_path), container=binding)
    request = _request(profile)
    fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
    scoped = StageFingerprintRecord.create(
        algorithm=fingerprint.algorithm,
        payload=replace(fingerprint.payload, fingerprint_fields={LOCAL_PREPARATION_SCOPE: {
            "agent_id": "agent-1", "binding_fingerprint": profile.launch_profile.fingerprint,
        }}),
        inputs_summary=fingerprint.inputs_summary,
    )
    request = replace(request, fingerprint=scoped.to_dict(), resolved_runtime={
        **request.resolved_runtime, "resources": {"schema_version": 2, "entries": {}},
    })
    workspace = _ResidentAssignmentWorkspace(tmp_path / "agent", request.assignment_id)
    workspace.persist_request(request, profile)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    workspace.grant("fence-1")
    launch = ResidentWorkerLaunch(
        supervisor_id="supervisor-1", continuity_epoch="epoch-1", agent_id="agent-1",
        session_id="session-1", assignment_id=request.assignment_id,
        process_execution_id="execution-1", execution_fence="fence-1",
        launch_operation_id="launch-1", bundle_digest="a" * 64,
        workspace_root=workspace.root, profile=profile.launch_profile, environment={},
    )
    argv, digest, controls = launch.command_argv, launch.spec_digest, launch.resource_controls
    workspace.persist_supervisor_launch(json.dumps(_launch_value(launch)))

    reopened = _ResidentAssignmentWorkspace(tmp_path / "agent", request.assignment_id)
    retained = reopened.supervisor_launch_json()
    assert retained is not None
    decoded = _launch_from_value(json.loads(retained))
    assert decoded.command_argv == argv
    assert decoded.spec_digest == digest and decoded.resource_controls == controls
    worker = reopened.worker_request()
    assert worker.resolved_runtime == request.resolved_runtime
    assert worker.fingerprint == scoped
    assert worker.inputs["source"].uri == reopened.input_path("source").as_uri()
    # A reachable profile reload cannot replace the retained local binding.
    changed = replace(profile, preparation_shared_roots={"data": tmp_path / "different"})
    with pytest.raises(QueueConflictError, match="binding identity"):
        reopened.persist_request(request, changed)


def test_shared_assignment_requires_versioned_scope_and_live_root_binding(tmp_path):
    from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE, qualifications, stage_scope
    from loom.queue.agent_session_transport import _decode
    root = tmp_path / "data"
    root.mkdir()
    (root / "challenge").write_bytes(b"shared")
    (root / "selected").write_bytes(b"content")
    roots = {"data": {"host_path": str(root), "container_path": "/loom/data", "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"shared").hexdigest()}}}
    profile = replace(_profile(tmp_path), shared_roots=roots)
    base = _request(profile)
    config = {"input": {"kind": "loom.shared-location", "schema_version": 1, "root_id": "data", "path": "selected"}}
    scope = stage_scope(config, {}, {"roots": qualifications(roots)})
    payload = replace(StageFingerprintRecord.from_dict(base.fingerprint).payload,
                      stage_config=config, fingerprint_fields={SHARED_EXECUTION_SCOPE: scope})
    fingerprint = StageFingerprintRecord.create(algorithm="sha256", payload=payload, inputs_summary={"stage_name": "build"})
    request = replace(base, fingerprint=fingerprint.to_dict())
    assert request.schema_version == 5
    assert _ResidentAssignmentBundle.from_remote_dict(request.to_dict()) == request
    with pytest.raises(QueueServiceError, match="schema capability"):
        _ResidentAssignmentBundle.from_remote_dict({**request.to_dict(), "schema_version": 4})
    with pytest.raises(QueueServiceError, match="schema is unsupported"):
        _ResidentAssignmentBundle.from_remote_dict({**request.to_dict(), "schema_version": 99})
    response = {"ok": True, "result": {"result": "assignment", "request": request.to_dict()}}
    assert _decode(json.dumps(response).encode()) == response
    workspace = _ResidentAssignmentWorkspace(tmp_path / "agent", request.assignment_id)
    workspace.persist_request(request, profile)
    (root / "challenge").write_bytes(b"wrong")
    with pytest.raises(QueueServiceError, match="bytes mismatch"):
        workspace.persist_request(request, profile)


def _shared_publication_workspace(tmp_path, *, limits=None, assignment_id="assignment-1", container=False):
    from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE, qualifications, stage_scope
    from loom.queue._shared_publication import worker_artifact_root
    root = tmp_path / "shared"
    root.mkdir(exist_ok=True)
    (root / "challenge").write_bytes(b"shared")
    roots = {"outputs": {"host_path": str(root), "container_path": "/loom/outputs", "access": "rw",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"shared").hexdigest()},
        "publication": limits or {"max_members": 1024, "max_payload_bytes": 256 * 1024 * 1024, "max_manifest_bytes": 1024 * 1024}}}
    profile = replace(_profile(tmp_path), shared_roots=roots)
    if container:
        image = tmp_path / "worker.sif"
        image.write_bytes(b"command-only fixture")
        profile = replace(profile, container={"kind": "apptainer", "container": {"image": {"reference": str(image)}},
            "options": {"command": sys.executable}, "python_executable": "/opt/python", "daemon_endpoint": None})
    request = _request(profile)
    scoped = stage_scope({}, {}, {"roots": qualifications(roots)})
    fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
    request = replace(request, assignment_id=assignment_id, fingerprint=StageFingerprintRecord.create(
        algorithm=fingerprint.algorithm, payload=replace(fingerprint.payload, fingerprint_fields={SHARED_EXECUTION_SCOPE: scoped}),
        inputs_summary=fingerprint.inputs_summary).to_dict())
    request = replace(request, resolved_runtime={**request.resolved_runtime,
        "resources": {"schema_version": 2, "entries": {}}})
    workspace = _ResidentAssignmentWorkspace(tmp_path / "agent", request.assignment_id)
    workspace.persist_request(request, profile)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    workspace.grant("fence-1")
    launch = ResidentWorkerLaunch(supervisor_id="supervisor-1", continuity_epoch="epoch-1", agent_id="agent-1",
        session_id="session-1", assignment_id=request.assignment_id, process_execution_id="execution-1",
        execution_fence="fence-1", launch_operation_id="launch-1",
        bundle_digest=hashlib.sha256(remote_stage_execution._canonical_json(request.to_dict()).encode()).hexdigest(),
        workspace_root=workspace.root, profile=profile.launch_profile, environment={})
    workspace.persist_supervisor_launch(json.dumps(_launch_value(launch)))
    workspace.mark_process_started("execution-1", 101)
    artifacts = worker_artifact_root(workspace)
    assert artifacts is not None
    output = artifacts / request.stage_name / "primary.json"
    output.write_bytes(b'{"companion":"values.bin"}')
    (output.parent / "values.bin").write_bytes(b"companion-bytes")
    (output.parent / "catalog").mkdir()
    (output.parent / "catalog" / "checkpoint").write_bytes(b"checkpoint")
    result = StageWorkerResult(schema_version=1, run_uri=f"loom-agent:{request.assignment_id}", stage_name=request.stage_name,
        attempt=request.attempt, status=StageStatus.SUCCEEDED, started_at="2020-01-01T00:00:00Z",
        finished_at="2020-01-01T00:00:01Z", executor_name="local",
        outputs={"result": ArtifactRef("build/result", output.as_uri(), "bytes", checksum="sha256:" + hashlib.sha256(output.read_bytes()).hexdigest())},
        executor_metadata={})
    workspace.persist_worker_result(result)
    return workspace, profile, launch, result


def test_shared_publication_replay_keeps_complete_closure_and_native_identity(tmp_path):
    from loom.queue._shared_publication import publish
    from loom.pipeline.stores.shared_artifacts import binding
    workspace, profile, _, _ = _shared_publication_workspace(tmp_path)
    report = workspace.retain_outputs()
    assert report.schema_version == 4
    assert _RemoteExecutionReport.from_dict(report.to_dict()) == report
    refs = publish(workspace.request(), report, profile.shared_roots, agent_id="agent-1", fence="fence-1")
    assert workspace.retain_outputs() == report
    assert publish(workspace.request(), report, profile.shared_roots, agent_id="agent-1", fence="fence-1") == refs
    tree = Path(refs["result"].uri.removeprefix("file://")).parent
    assert (tree / "values.bin").read_bytes() == b"companion-bytes"
    assert (tree / "catalog" / "checkpoint").read_bytes() == b"checkpoint"
    publication = binding(refs["result"].metadata)
    assert publication is not None
    assert publication["primary"] == "primary.json"
    assert not (workspace.root / "retained-outputs").exists()
    with pytest.raises(QueueConflictError, match="identity"):
        publish(workspace.request(), report, profile.shared_roots, agent_id="agent-1", fence="obsolete-fence")
    assert (tree / "values.bin").is_file()


@pytest.mark.parametrize("limit,value,error", [
    ("max_members", 2, "member or payload budget"),
    ("max_payload_bytes", 1, "member or payload budget"),
    ("max_manifest_bytes", 64, "manifest budget"),
])
def test_shared_publication_budget_excess_never_publishes(tmp_path, limit, value, error):
    limits = {"max_members": 1024, "max_payload_bytes": 256 * 1024 * 1024, "max_manifest_bytes": 1024 * 1024}
    limits[limit] = value
    workspace, _, _, _ = _shared_publication_workspace(tmp_path, limits=limits)
    with pytest.raises((QueueConflictError, QueueServiceError), match=error):
        workspace.retain_outputs()
    assert not (tmp_path / "shared" / "loom-artifacts").exists()


@pytest.mark.parametrize("change", ["missing", "changed", "unlisted", "symlink", "fifo"])
def test_shared_publication_rejects_interrupted_or_changed_closure(tmp_path, change):
    from loom.queue._shared_publication import publish
    import os
    workspace, profile, _, result = _shared_publication_workspace(tmp_path)
    report = workspace.retain_outputs()
    tree = Path(result.outputs["result"].uri.removeprefix("file://")).parent
    companion = tree / "values.bin"
    if change == "changed":
        companion.write_bytes(b"different")
    elif change == "unlisted":
        (tree / "late-member").write_bytes(b"late writer")
    else:
        companion.unlink()
        if change == "symlink":
            companion.symlink_to(tree / "primary.json")
        elif change == "fifo":
            os.mkfifo(companion)
    with pytest.raises(QueueConflictError):
        publish(workspace.request(), report, profile.shared_roots, agent_id="agent-1", fence="fence-1")
    assert not (tmp_path / "shared" / "loom-artifacts").exists()


def test_shared_attempts_and_container_mounts_are_disjoint_and_narrow(tmp_path):
    from loom.queue._shared_publication import staging_tree
    first, profile, launch, _ = _shared_publication_workspace(tmp_path, container=True)
    second, _, _, _ = _shared_publication_workspace(tmp_path, assignment_id="assignment-2", container=True)
    first_tree = staging_tree(first.request(), profile.shared_roots, "agent-1")
    second_tree = staging_tree(second.request(), profile.shared_roots, "agent-1")
    assert first_tree != second_tree and first_tree.is_dir() and second_tree.is_dir()
    argv = launch.container_command.argv
    assert any(str(first_tree) in arg and ":rw" in arg for arg in argv)
    assert not any(str(second_tree) in arg for arg in argv)
    assert not any(arg.startswith(str(tmp_path / "shared") + ":") for arg in argv)


def test_shared_input_descriptor_preserves_primary_checksum_contract(tmp_path):
    from loom.queue._shared_publication import publish
    workspace, profile, _, _ = _shared_publication_workspace(tmp_path)
    ref = publish(workspace.request(), workspace.retain_outputs(), profile.shared_roots,
                  agent_id="agent-1", fence="fence-1")["result"]
    retained = ArtifactRef.from_dict({**ref.to_dict(), "checksum": "sha256:" + "0" * 64})
    with pytest.raises(QueueServiceError, match="integrity"):
        _RemoteArtifact.from_local_ref(transfer_id="candidate-input", logical_name="result", ref=retained)
