"""Native grant handlers finish storage handoff before exposing a writable mount.

Use real delivery decoding, SQLite control records, session authorization and
storage operations. Provider release and run-authority replies are controlled
facts; these tests do not launch a container or claim physical provider fencing.
"""

from collections.abc import Callable, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import fields, replace
import hashlib
import json
import sqlite3
from threading import RLock
from types import SimpleNamespace
from typing import cast

import pytest

from loom.pipeline.planning import StageFingerprintRecord
from loom.pipeline.stores.shared_artifacts import encoded
from loom.queue import LocalDaemon, LocalDaemonConfig, LocalDaemonPrincipal, LocalDaemonRole
from loom.queue import _shared_publication as publication
from loom.queue import _shared_recovery as recovery
from loom.queue import _shared_staging_continuation as continuation
from loom.queue._action_results import initialize_action_results
from loom.queue._publication_guards import PublicationGuards
from loom.queue._remote_stage_execution import REGULAR_FILE_RELAY_CAPABILITY, REMOTE_EXECUTION_CAPABILITY
from loom.queue.agent_sessions import AgentSessionService, initialize_agent_session_schema
from loom.queue.errors import QueueConflictError
from loom.queue.local_daemon_execution import LocalDaemonExecution, _ScopedCoordinatorAuthority
from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE, STAGING_CONTINUATION_CAPABILITY
from loom.queue.slurm_ready_stage import SQLiteSlurmStageAssignments, SlurmStageDelivery, SlurmStageRecord
from loom.serialization import PlainData, thaw_plain_data
from tests.unit.loom.queue.test_agent_sessions import _policy
from tests.unit.loom.queue.test_shared_recovery import _retention_database, _workspace
from tests.unit.loom.queue.test_shared_staging_continuation import _first


def _select(request, predecessor=None):
    fingerprint = StageFingerprintRecord.from_dict(request.fingerprint)
    scopes = cast(dict[str, PlainData], thaw_plain_data(fingerprint.payload.fingerprint_fields))
    cast(dict[str, PlainData], scopes[SHARED_EXECUTION_SCOPE])["staging_continuation"] = {
        "capability": STAGING_CONTINUATION_CAPABILITY,
    }
    return replace(
        request,
        fingerprint=StageFingerprintRecord.create(
            algorithm=fingerprint.algorithm,
            payload=replace(fingerprint.payload, fingerprint_fields=scopes),
            inputs_summary=fingerprint.inputs_summary,
        ).to_dict(),
        worker_metadata={
            **request.worker_metadata,
            continuation.WIRE: {"schema_version": 1, "predecessor": predecessor},
        },
    )


def _selected_delivery(tmp_path):
    _, profile, source, reference, inode = _first(tmp_path)
    second, profile, _ = _workspace(tmp_path, attempt=2)
    with _retention_database(tmp_path / "retention.sqlite") as conn:
        request = recovery._bind_delivery(
            _select(second.request()), conn, "file:///fixture", profile.shared_roots,
            agent_id="agent-1", slurm_assignments=None,
        )
    assert thaw_plain_data(request.worker_metadata[continuation.WIRE]["predecessor"]) == reference
    return request, profile, source, inode


def _slurm_delivery(request, profile):
    return SlurmStageDelivery(**{
        field.name: getattr(request, field.name)
        for field in fields(SlurmStageDelivery)
        if field.name != "schema_version" and hasattr(request, field.name)
    }, profile_id=profile.descriptor.profile_id,
        project_fingerprint=profile.descriptor.project_fingerprint,
        environment_fingerprint=profile.descriptor.environment_fingerprint,
        executor_fingerprint=profile.descriptor.executor_fingerprint,
    )


class _Control:
    def __init__(self, tmp_path):
        self.path = tmp_path / "grant-control.sqlite"
        self.fault = None
        self.authority_live = True
        control = self

        class Connection(sqlite3.Connection):
            receipt_write = False

            def execute(self, sql, parameters=()):
                if sql.startswith("INSERT OR IGNORE INTO agent_receipts"):
                    self.receipt_write = True
                return super().execute(sql, parameters)

            def commit(self):
                if self.receipt_write and control.fault == "before_control_commit":
                    raise RuntimeError("cut before control receipt commit")
                super().commit()
                if self.receipt_write and control.fault == "after_control_commit":
                    raise RuntimeError("cut after control receipt commit")

        self.factory = Connection
        with self.connection() as conn:
            initialize_agent_session_schema(conn, coordinator=True)
            initialize_action_results(conn)
            conn.execute("CREATE TABLE managed_admissions(run_uri TEXT, cancellation_operation_id TEXT)")

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, factory=self.factory)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    def cancel(self):
        with self.connection() as conn:
            conn.execute("INSERT INTO managed_admissions VALUES ('file:///fixture', 'cancel')")
        self.authority_live = False

    def authority(self, *args, **kwargs):
        if not self.authority_live:
            raise QueueConflictError("run authority is cancelled")
        return SimpleNamespace(fencing_token="fence-1")


def _client(tmp_path, request, profile, provider):
    control = _Control(tmp_path)
    guards = PublicationGuards()
    state_lock = RLock()
    grant: Callable[[], PlainData]
    if provider == "resident":
        policy = _policy()
        capabilities = ("python", REMOTE_EXECUTION_CAPABILITY, REGULAR_FILE_RELAY_CAPABILITY)
        policy = replace(policy, agents=(replace(policy.agents[0], capabilities=capabilities),))
        with control.connection() as conn:
            conn.execute("INSERT INTO agent_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "session-1", "agent-a", "agent-1", "principal-a", policy.revision,
                "config-1", "inventory-1", "availability-1", json.dumps(capabilities),
                '["default"]', "0" * 64, "epoch", "ACTIVE", "2020-01-01T00:00:00Z",
            ))
            conn.execute(
                "INSERT INTO remote_assignments(assignment_id,session_id,availability_revision,issuer_epoch,"
                "run_uri,stage_work_id,stage_name,attempt,attempt_id,profile_json,state) "
                "VALUES (?, 'session-1', 'availability-1', 'epoch', 'file:///fixture', ?, ?, ?, ?, '{}', 'BOUND')",
                (request.assignment_id, request.stage_work_id, request.stage_name, request.attempt, request.attempt_id),
            )
            data = encoded(request.to_dict()).decode()
            conn.execute(
                "INSERT INTO agent_deliveries(assignment_id,session_id,availability_revision,coordinator_epoch,request_json,state) "
                "VALUES (?, 'session-1', 'availability-1', 'epoch', ?, 'DELIVERED')",
                (request.assignment_id, data),
            )
        daemon = SimpleNamespace(
            config=SimpleNamespace(coordinator_shared_roots=profile.shared_roots),
            _agent_policy=policy, _epoch="epoch", _scheduling_epoch=1, _connection=control.connection,
            _publication_guards=guards, _state_guard=lambda: state_lock,
            _require_started=lambda: "coordinator",
            _execution=SimpleNamespace(
                remote_accept=lambda assignment_id: control.authority().fencing_token,
                remote_start_permit=lambda *args, **kwargs: bool(control.authority()),
            ),
        )
        service = AgentSessionService(cast(LocalDaemon, daemon), LocalDaemonPrincipal("principal-a", LocalDaemonRole.AGENT, "agent-a"))

        def resident_grant():
            return service.accept_assignment(
                "session-1", request.assignment_id,
                request_digest=hashlib.sha256(data.encode()).hexdigest(),
            )["fence"]

        grant = resident_grant

        def start():
            return service.start_permit("session-1", request.assignment_id, fence="fence-1")

        def running():
            with control.connection() as conn:
                conn.execute("UPDATE remote_assignments SET state='RUNNING' WHERE assignment_id=?", (request.assignment_id,))

    else:
        delivery = _slurm_delivery(request, profile)
        record = SimpleNamespace(
            input_ready=True, fence=None, state="accepted", start_consumed=False, delivery=delivery,
            assignment=SimpleNamespace(run_uri="file:///fixture", attempt_id=request.attempt_id, agent_id="agent-1"),
        )
        execution = object.__new__(LocalDaemonExecution)
        execution.config = cast(LocalDaemonConfig, SimpleNamespace(
            control_database=control.path, connect_database=lambda path: control.connection(),
            coordinator_shared_roots=profile.shared_roots,
        ))
        execution.daemon = cast(LocalDaemon, SimpleNamespace(_publication_guards=guards))

        def authorized_record(
            principal_id: str, credential_id: str | None, assignment_id: str, incarnation: str,
        ) -> SlurmStageRecord:
            return cast(SlurmStageRecord, record)

        execution._slurm_authorized_record = authorized_record
        execution._remote_authority = lambda run_uri: cast(
            _ScopedCoordinatorAuthority, SimpleNamespace(grant_prepared_attempt=control.authority),
        )

        def mark_granted(assignment_id, incarnation, fence):
            record.fence, record.state = fence, "granted"

        def consume_start(assignment_id, **kwargs):
            record.start_consumed = True
            return True

        execution.slurm_assignments = cast(
            SQLiteSlurmStageAssignments, SimpleNamespace(mark_granted=mark_granted, consume_start=consume_start),
        )
        arguments = dict(principal_id="slurm-agent", credential_id="credential",
                         assignment_id=request.assignment_id, incarnation="incarnation")

        def slurm_grant():
            return execution.slurm_grant(**arguments)

        grant = slurm_grant

        def start():
            return execution.slurm_start_permit(**arguments, fence="fence-1")

        def running():
            record.state = "running"

    return SimpleNamespace(control=control, grant=grant, start=start, running=running)


@pytest.mark.parametrize("provider", ["resident", "slurm"])
def test_grant_finishes_before_start_and_replays_without_touching_live_output(tmp_path, monkeypatch, provider):
    request, profile, source, inode = _selected_delivery(tmp_path)
    client = _client(tmp_path, request, profile, provider)
    assert client.grant() == "fence-1"
    destination = publication.staging_tree(request, profile.shared_roots, "agent-1")
    assert not source.exists()
    assert (destination / "assembled/values.npy").stat().st_ino == inode
    assert client.start()
    client.running()
    (destination / "worker-output").write_bytes(b"written by current worker")

    def no_handoff(*args, **kwargs):
        raise AssertionError("grant replay touched live staging")

    monkeypatch.setattr(continuation, "continue_staging", no_handoff)
    assert client.grant() == "fence-1"
    client.control.cancel()
    assert client.grant() == "fence-1"
    assert client.start() is False
    assert (destination / "worker-output").read_bytes() == b"written by current worker"


@pytest.mark.parametrize("provider", ["resident", "slurm"])
@pytest.mark.parametrize("fault", ["rename", "before_control_commit", "after_control_commit"])
def test_interrupted_native_grant_repairs_storage_or_replays_receipt(tmp_path, monkeypatch, provider, fault):
    request, profile, _, inode = _selected_delivery(tmp_path)
    client = _client(tmp_path, request, profile, provider)
    client.control.fault = fault
    rename = continuation.os.rename

    def cut(old, new):
        rename(old, new)
        raise OSError("cut after staging rename")

    with monkeypatch.context() as patch:
        if fault == "rename":
            patch.setattr(continuation.os, "rename", cut)
        with pytest.raises((QueueConflictError, RuntimeError), match="cut"):
            client.grant()
    if fault != "after_control_commit":
        with pytest.raises(QueueConflictError, match="not acknowledged"):
            client.start()
    client.control.fault = None
    if fault == "after_control_commit":
        monkeypatch.setattr(continuation, "continue_staging", lambda *args, **kwargs: pytest.fail("durable receipt must skip storage"))
    assert client.grant() == "fence-1"
    assert client.start()
    destination = publication.staging_tree(request, profile.shared_roots, "agent-1")
    assert (destination / "assembled/values.npy").stat().st_ino == inode


@pytest.mark.parametrize("provider", ["resident", "slurm"])
def test_cancelled_unacknowledged_handoff_cannot_restart_or_start(tmp_path, monkeypatch, provider):
    request, profile, _, inode = _selected_delivery(tmp_path)
    client = _client(tmp_path, request, profile, provider)
    client.control.fault = "before_control_commit"
    with pytest.raises(RuntimeError, match="cut"):
        client.grant()
    client.control.fault = None
    client.control.cancel()
    with pytest.raises(QueueConflictError, match="cancelled|no longer live"):
        client.grant()
    assert client.start() is False
    destination = publication.staging_tree(request, profile.shared_roots, "agent-1")
    assert (destination / "assembled/values.npy").stat().st_ino == inode


@pytest.mark.parametrize("boundary", ["before_rename", "after_rename", "completed"])
def test_released_unstarted_attempt_delivers_the_actual_surviving_staging(tmp_path, monkeypatch, boundary):
    request, profile, original, inode = _selected_delivery(tmp_path)
    client = _client(tmp_path, request, profile, "resident")
    rename = continuation.os.rename

    def interrupted(old, new):
        if boundary == "after_rename":
            rename(old, new)
        raise OSError("cut during handoff")

    if boundary == "completed":
        client.grant()
    else:
        with monkeypatch.context() as patch:
            patch.setattr(continuation.os, "rename", interrupted)
            with pytest.raises(QueueConflictError, match="cut"):
                client.grant()
    destination = publication.staging_tree(request, profile.shared_roots, "agent-1")
    if boundary == "before_rename":
        # Mount setup may leave an empty path in the attempt with no payload.
        destination.mkdir(parents=True, exist_ok=True)
    with client.control.connection() as conn:
        assert conn.execute("SELECT start_permitted FROM remote_assignments").fetchone()[0] == 0
    # Controlled positive provider release; seal the empty recovery tree even
    # though the attempt never ran. Its output staging is a separate namespace.
    with _retention_database(tmp_path / "retention.sqlite") as conn:
        proof = {"provider_release_proof_json": "positive-provider-release", "fence": "fence-1"}
        recovery.retain_released(conn, proof, request, profile.shared_roots, agent_id="agent-1")
        conn.execute("INSERT INTO remote_assignments VALUES (?,?,?,?,?,?,?,?,?,?)", (
            request.assignment_id, "file:///fixture", request.stage_name, request.attempt,
            request.attempt_id, "RELEASED", proof["provider_release_proof_json"],
            json.dumps({"status": "FAILED"}), "fence-1", 0,
        ))
        conn.execute("INSERT INTO agent_deliveries VALUES (?,?)", (request.assignment_id, encoded(request.to_dict()).decode()))
    third, profile, _ = _workspace(tmp_path, attempt=3)
    with _retention_database(tmp_path / "retention.sqlite") as conn:
        delivered = recovery._bind_delivery(
            _select(third.request()), conn, "file:///fixture", profile.shared_roots,
            agent_id="agent-1", slurm_assignments=None,
        )
    references = delivered.worker_metadata[recovery.WIRE]["predecessors"]
    assert len(references) == 2
    selected = delivered.worker_metadata[continuation.WIRE]["predecessor"]
    assert selected["identity"]["attempt"] == (1 if boundary == "before_rename" else 2)
    third_control = tmp_path / "third-control"
    third_control.mkdir()
    successor = _client(third_control, delivered, profile, "resident")
    assert successor.grant() == "fence-1"
    assert successor.start()
    final = publication.staging_tree(delivered, profile.shared_roots, "agent-1")
    assert (final / "assembled/values.npy").stat().st_ino == inode
    assert not original.exists()


@pytest.mark.parametrize("damage", ["missing_selection", "missing_recovery", "unauthorized_source", "escaping_source"])
def test_remote_decoder_admits_only_exact_native_continuation_references(tmp_path, damage):
    from loom.pipeline.stores.errors import ArtifactStoreError
    from loom.queue._remote_stage_execution import _ResidentAssignmentBundle
    from loom.queue.errors import QueueServiceError

    request, _, source, inode = _selected_delivery(tmp_path)
    assert _ResidentAssignmentBundle.from_remote_dict(request.to_dict()) == request
    value = request.to_dict()
    metadata = value["worker_metadata"]
    if damage == "missing_selection":
        del metadata[continuation.WIRE]
    elif damage == "missing_recovery":
        del metadata[recovery.WIRE]
    elif damage == "unauthorized_source":
        metadata[continuation.WIRE]["predecessor"]["receipt_digest"] = "0" * 64
    else:
        metadata[continuation.WIRE]["predecessor"]["tree"] = "../../unowned"
    with pytest.raises((QueueConflictError, QueueServiceError, ArtifactStoreError)):
        _ResidentAssignmentBundle.from_remote_dict(value)
    assert (source / "assembled/values.npy").stat().st_ino == inode


def test_continuation_scope_is_explicit_and_requires_shared_publication(tmp_path):
    from loom.queue.errors import QueueServiceError
    from loom.queue.shared_execution import qualifications, scope, stage_scope

    _, profile, _ = _workspace(tmp_path)
    permitted = {"roots": qualifications(profile.shared_roots)}
    ordinary = stage_scope({}, {}, permitted)
    assert set(ordinary) == {"capability", "roots", "locations"}
    assert stage_scope({}, {}, permitted, continue_staging=False) == ordinary
    selected = stage_scope({}, {}, permitted, continue_staging=True)
    assert scope(json.loads(encoded(selected))) == selected
    assert {k: v for k, v in selected.items() if k != "staging_continuation"} == ordinary
    with pytest.raises(QueueServiceError, match="shared publication policy"):
        stage_scope({}, {}, {"roots": {}}, continue_staging=True)
    with pytest.raises(QueueServiceError, match="boolean"):
        stage_scope({}, {}, permitted, continue_staging=cast(bool, 1))


@pytest.mark.parametrize("provider", ["resident", "slurm"])
def test_selected_fresh_grant_needs_no_handoff_receipt(tmp_path, monkeypatch, provider):
    workspace, profile, _ = _workspace(tmp_path)
    client = _client(tmp_path, _select(workspace.request()), profile, provider)
    monkeypatch.setattr(continuation, "continue_staging", lambda *args, **kwargs: pytest.fail("fresh grant cannot hand off"))
    assert client.grant() == "fence-1"
    assert client.start()
    with client.control.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_receipts WHERE operation='continue_staging'").fetchone()[0] == 0


def test_resident_start_rechecks_cancellation_after_authority_observation(tmp_path):
    request, profile, _, _ = _selected_delivery(tmp_path)
    client = _client(tmp_path, request, profile, "resident")
    client.grant()

    def cancelled_during_observation():
        client.control.cancel()
        return SimpleNamespace(fencing_token="fence-1")

    client.control.authority = cancelled_during_observation
    assert client.start() is False
    with client.control.connection() as conn:
        assert conn.execute("SELECT start_permitted FROM remote_assignments").fetchone()[0] == 0


@pytest.mark.parametrize("provider", ["resident", "slurm"])
def test_worker_receives_recovery_roots_without_native_handoff_metadata(tmp_path, provider):
    from loom.queue._agent_process_supervisor import ResidentWorkerLaunch, _launch_value
    from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
    from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace

    request, profile, _, _ = _selected_delivery(tmp_path)
    client = _client(tmp_path, request, profile, provider)
    client.grant()
    assert client.start()
    if provider == "resident":
        workspace = _ResidentAssignmentWorkspace(tmp_path / "received", request.assignment_id)
        workspace.persist_request(request, profile)
        workspace.stage_input("input-1", b"input")
        workspace.accept()
        workspace.grant("fence-1")
        launch = ResidentWorkerLaunch(
            supervisor_id="supervisor-1", continuity_epoch="epoch-1", agent_id="agent-1",
            session_id="session-1", assignment_id=request.assignment_id,
            process_execution_id="execution-1", execution_fence="fence-1", launch_operation_id="launch-1",
            bundle_digest=hashlib.sha256(encoded(request.to_dict())).hexdigest(),
            workspace_root=workspace.root, profile=profile.launch_profile, environment={},
        )
        workspace.persist_supervisor_launch(json.dumps(_launch_value(launch)))
        workspace.mark_process_started("execution-1", 101)
        worker = workspace.worker_request(resolve_shared=True)
    else:
        workspace = SlurmBootstrapWorkspace(tmp_path / "received", request.assignment_id)
        workspace.persist_delivery(_slurm_delivery(request, profile))
        workspace.stage_input_chunk("input-1", 0, b"input", final=True)
        workspace.persist_execution_binding(agent_id="agent-1", fence="fence-1", profile=profile.launch_profile)
        worker = workspace.worker_request(shared_roots=profile.shared_roots)
    assert continuation.WIRE not in worker.metadata
    assert recovery.WIRE not in worker.metadata
    binding = cast(Mapping[str, PlainData], worker.metadata[recovery.BINDING])
    assert len(cast(Sequence[PlainData], binding["predecessors"])) == 1
