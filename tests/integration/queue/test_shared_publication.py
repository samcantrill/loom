"""Native remote producer/consumer closure without payload relay or copies."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import threading

import pytest

from loom.coordinator import CoordinatorClient
from loom.preparation import CoordinatorPreparation
from loom.queue import (
    LocalDaemon, LocalDaemonAdmissionRequest, LocalDaemonSocketServer,
    LocalDaemonPrincipal, LocalDaemonRole,
)
from loom.queue.agent_sessions import AgentRegistration, AgentOffer
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    _resident_provider_descriptors,
)
from loom.queue.deployment import load_coordinator_service_config
from loom.queue._remote_stage_execution import (
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
    _ResidentAssignmentWorkspace,
    REMOTE_EXECUTION_CAPABILITY,
    REGULAR_FILE_RELAY_CAPABILITY,
)
from loom.queue.resident_readiness import (
    qualified_resident_profile,
    ResidentReadinessRequirements,
)
from loom.queue.shared_execution import SHARED_EXECUTION_CAPABILITY
from loom.pipeline.stores import LocalRunStore, LocalArtifactStore
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.stores.shared_artifacts import SHARED_PUBLICATION
from loom.pipeline.stores.errors import ArtifactStoreError
from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint
from tests.integration.queue.test_preparation_operations import (
    _service,
    _request,
    _result,
)

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("pure_coordinator,project_context,slow_preparation", [
    (False, False, False), (True, False, False), (True, True, False),
    (True, True, True),
])
def test_two_agents_publish_and_consume_complete_large_shared_closure(
    tmp_path, monkeypatch, pure_coordinator, project_context, slow_preparation
):
    _service(tmp_path)
    root = tmp_path / "nas" / "outputs"
    root.mkdir(parents=True)
    (root / "challenge").write_bytes(b"shared-output-root")
    # The kernel's root alias supplies an independent prefix to the same mount;
    # no payload links, copies, relay directories, or worker authority mounts.
    alternate = Path("/proc/self/root") / root.relative_to("/")
    assert alternate.is_dir()
    limits = {
        "max_members": 1024,
        "max_payload_bytes": 256 * 1024 * 1024,
        "max_manifest_bytes": 1024 * 1024,
    }

    def roots(path):
        return {
            "outputs": {
                "host_path": str(path),
                "container_path": "/loom/outputs",
                "access": "rw",
                "challenge": {
                    "path": "challenge",
                    "sha256": hashlib.sha256(b"shared-output-root").hexdigest(),
                },
                "publication": limits,
            }
        }

    agent_path = tmp_path / "agent.json"
    agent = json.loads(agent_path.read_text())
    agent["resident_profiles"][0]["shared_roots"] = roots(root)
    agent_path.write_text(json.dumps(agent))
    pipeline_path = tmp_path / "projects" / "pipeline.yaml"
    pipeline = json.loads(pipeline_path.read_text())
    producer = pipeline["pipeline"]["stages"][0]
    producer.update(
        factory={
            "_target_": "tests.support.shared_execution_stages.SharedClosureProducer"
        },
        config={"project_context": project_context},
        outputs={"manifest": {"artifact_type": "json", "codec_key": "json.v1"}},
        placement={"target": "worker-b"},
    )
    consumer = deepcopy(producer)
    consumer.update(
        name="consume",
        factory={
            "_target_": "tests.support.shared_execution_stages.SharedClosureConsumer"
        },
        inputs={"manifest": "produce.manifest"},
        outputs={"receipt": {"artifact_type": "json", "codec_key": "json.v1"}},
        placement={"target": "worker-c"},
    )
    pipeline["pipeline"]["stages"].append(consumer)
    pipeline_path.write_text(json.dumps(pipeline))
    profiles = [
        qualified_resident_profile(
            ResidentExecutionProfile(
                ResidentProfileDescriptor(
                    "execute-" + name, "v1", "project", "environment", "executor"
                ),
                Path(__file__).resolve().parents[3],
                Path(sys.executable),
                readiness_requirements=ResidentReadinessRequirements(
                    imports=("loom", "loom.preparation", "weave")
                ),
                shared_roots=roots(path),
                preparation_shared_roots={"projects": tmp_path / "snapshots"},
            )
        )
        for name, path in (("b", root), ("c", alternate))
    ]
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
        SHARED_EXECUTION_CAPABILITY,
        "shared-assignment-reference-v1",
        "preparation-input-v2",
    )
    config_path = tmp_path / "coordinator.json"
    authored = json.loads(config_path.read_text())
    authored["assignment_payload_root_id"] = "outputs"
    authored["preparation"]["profiles"]["existing-project"].update(
        configuration_policy="shared", shared_locations=[]
    )
    if project_context:
        authored["preparation"]["profiles"]["existing-project"]["project_processor"] = {
            "schema_version": 3,
            "callable": "tests.support.shared_execution_stages:inspect_shared_context",
            "evidence_namespace": "shared-context",
            "target_prefix": "context-",
        }
    if pure_coordinator:
        authored["local_agent"] = None
        authored["shared_roots"] = roots(root)
        authored["preparation"]["profiles"]["existing-project"]["resident_profile_id"] = profiles[0].descriptor.profile_id
    authored["remote_profiles"] = [profile.descriptor.to_dict() for profile in profiles]
    authored["agent_policy"]["agents"] = [
        {
            "credential_id": credential,
            "principal_id": name,
            "agent_id": name,
            "pools": ["default"],
            "capabilities": list(capabilities),
            "gpu_devices": [],
        }
        for name, credential in (("worker-b", "agent"), ("worker-c", "other"))
    ]
    config_path.write_text(json.dumps(authored))
    service = load_coordinator_service_config(config_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    credentials = mutual_tls_credentials(tmp_path / "tls")
    daemon.start()
    unix = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    unix.start()
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
                for name in ("agent", "other")
            },
        ),
    )
    server.start()
    clients = []
    import loom.queue._shared_publication as publication
    import loom.queue.agent_session_transport as transport
    import loom.preparation as preparation
    from loom.queue.agent_sessions import AgentSessionService

    publications = []
    original_publish = publication.prepare_publication
    publication_context = threading.local()

    def counted_publish(request, *args, **kwargs):
        publications.append(request.assignment_id)
        publication_context.active = True
        try:
            return original_publish(request, *args, **kwargs)
        finally:
            publication_context.active = False

    monkeypatch.setattr(publication, "prepare_publication", counted_publish)
    decoding = threading.Event()
    deadline_expired = threading.Event()
    retained = threading.Event()
    timed_out_requests = []
    if slow_preparation:
        original_decode = preparation.load_preparation_report
        original_declare = AgentSessionService.declare_outputs
        original_exchange = transport._exchange_agent_request

        def slow_decode(*args, **kwargs):
            if getattr(publication_context, "active", False) and not decoding.is_set():
                decoding.set()
                assert deadline_expired.wait(5), "client did not exceed its deadline"
            return original_decode(*args, **kwargs)

        def observe_retention(*args, **kwargs):
            result = original_declare(*args, **kwargs)
            if decoding.is_set():
                retained.set()
            return result

        def deadline_exchange(config, operation, body, role, connection, keep_alive):
            if operation != "output_manifest" or deadline_expired.is_set():
                return original_exchange(config, operation, body, role, connection, keep_alive)
            # Use real TLS and a real socket deadline. The server remains inside
            # native semantic validation until this request actually times out.
            if connection is not None:
                connection.close()
            connection = transport.https_connection(
                config.url, config.server_ca_path, config.certificate_path,
                config.private_key_path, timeout=0.2,
            )
            try:
                return original_exchange(config, operation, body, role, connection, keep_alive)
            except transport._IndeterminateAgentProtocolError:
                assert decoding.is_set(), "deadline expired before validation started"
                timed_out_requests.append(json.loads(body)["assignment_id"])
                deadline_expired.set()
                assert retained.wait(5), "server did not retain the successful result"
                raise

        monkeypatch.setattr(preparation, "load_preparation_report", slow_decode)
        monkeypatch.setattr(AgentSessionService, "declare_outputs", observe_retention)
        monkeypatch.setattr(transport, "_exchange_agent_request", deadline_exchange)
    try:
        sessions = []
        for profile, credential in zip(profiles, ("agent", "other"), strict=True):
            config = AgentTlsClientConfig(
                f"https://localhost:{server.port}",
                credentials["ca"].with_suffix(".crt"),
                credentials[credential].with_suffix(".crt"),
                credentials[credential].with_suffix(".key"),
                tmp_path / "remote" / credential,
                (profile,),
            )
            LocalDaemonAgentHttpClient.initialize_agent_root(config)
            remote = LocalDaemonAgentHttpClient(config)
            clients.append(remote)
            handshake = remote.handshake()
            session = remote.register(
                AgentRegistration(
                    "register-" + credential,
                    str(handshake["coordinator_id"]),
                    str(handshake["coordinator_epoch"]),
                    remote.agent_root_id,
                    "config-1",
                    "inventory-1",
                    "availability-1",
                    ("default",),
                    capabilities,
                )
            )
            sessions.append(session)
            remote.publish_offer(
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
                    resident_profiles=(profile.descriptor,),
                ),
                idempotency_key="offer-" + credential,
            )
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            client.prepare_run(_request())
            if pure_coordinator:
                assert daemon.config.resident_worker_launch_profile is None
                prepared = clients[0].execute_one(sessions[0].session_id,
                    sessions[0].availability_revision, sequence=1, wait_timeout_ms=5000)
                assert prepared["state"] == "RELEASED", prepared
                if slow_preparation:
                    assert len(timed_out_requests) == 1
                    assert publications.count(timed_out_requests[0]) == 1
            operation = client.wait_operation("prepare-1", timeout_seconds=25).operation
            assert operation.state == "applied", operation
            result = _result(operation)
            target_uri = result["prepared_run"]["run_uri"]

            def forbidden(*args, **kwargs):
                raise AssertionError("shared payload must not be relayed or copied")

            import loom.queue._managed_local as managed

            monkeypatch.setattr(_ResidentAssignmentWorkspace, "output_chunk", forbidden)
            monkeypatch.setattr(
                _ResidentAssignmentWorkspace, "stage_input_chunk", forbidden
            )
            monkeypatch.setattr(managed, "_publish_regular_file_tree", forbidden)
            from loom.queue.agent_session_transport import (
                _IndeterminateAgentProtocolError,
            )
            from loom.queue.errors import QueueConflictError

            baseline_publications = len(tuple(root.glob("loom-artifacts/*")))
            assert baseline_publications == 1  # The preparation report uses the same native publication path.
            original = clients[0].declare_outputs
            attempts = []

            def lost_publication_ack(*args, **kwargs):
                if not attempts:
                    with pytest.raises(QueueConflictError):
                        original(*args, **{**kwargs, "fence": "stale-fence"})
                    assert len(tuple(root.glob("loom-artifacts/*"))) == baseline_publications
                response = original(*args, **kwargs)
                attempts.append(kwargs["report"].to_dict())
                if len(attempts) == 1:
                    assert len(tuple(root.glob("loom-artifacts/*"))) == baseline_publications + 1
                    raise _IndeterminateAgentProtocolError(
                        "injected lost shared publication acknowledgement"
                    )
                with pytest.raises(QueueConflictError):
                    original(*args, **{**kwargs, "report": replace(
                        kwargs["report"], finished_at="2099-01-01T00:00:00Z"
                    )})
                with pytest.raises(QueueConflictError):
                    original(*args, **{**kwargs, "fence": "stale-fence"})
                from loom.queue.agent_sessions import AgentTransferAuthorizationStaleError
                with pytest.raises(AgentTransferAuthorizationStaleError):
                    original(*args, **{**kwargs, "authorization_revision": kwargs["authorization_revision"] + 1})
                return response

            monkeypatch.setattr(clients[0], "declare_outputs", lost_publication_ack)
            original_commit = clients[0].commit_result
            original_verify = AgentSessionService._coordinator_output_refs
            verifications = []
            commits = []
            retained_commit = {}

            def counted_verify(transfers):
                verifications.append(transfers[0]["assignment_id"])
                return original_verify(transfers)

            def lost_commit_ack(*args, **kwargs):
                retained_commit.update(kwargs)
                if not commits and not pure_coordinator:
                    # Retention is an acknowledgement, not permission to skip
                    # integrity at the first execution commit.
                    with sqlite3.connect(daemon.config.control_database) as conn:
                        primary = Path(conn.execute(
                            "SELECT private_path FROM remote_transfers WHERE assignment_id=? AND direction='output'",
                            (args[1],),
                        ).fetchone()[0])
                    companion = primary.parent / "sample_ids.json"
                    original_bytes = companion.read_bytes()
                    companion.write_bytes(b'["damaged before first commit"]')
                    view = daemon.agent_view(LocalDaemonPrincipal("worker-b", LocalDaemonRole.AGENT, "agent"))
                    try:
                        with pytest.raises(ArtifactStoreError, match="closure integrity"):
                            view.commit_result(*args, **kwargs)
                        with sqlite3.connect(daemon.config.control_database) as conn:
                            assert conn.execute("SELECT state FROM remote_assignments WHERE assignment_id=?", (args[1],)).fetchone()[0] == "RESULT_RETAINED"
                    finally:
                        companion.write_bytes(original_bytes)
                response = original_commit(*args, **kwargs)
                commits.append(args[1])
                if len(commits) == 1:
                    raise _IndeterminateAgentProtocolError("injected lost commit acknowledgement")
                with pytest.raises(QueueConflictError):
                    original_commit(*args, **{**kwargs, "fence": "stale-fence"})
                return response

            monkeypatch.setattr(AgentSessionService, "_coordinator_output_refs", staticmethod(counted_verify))
            monkeypatch.setattr(clients[0], "commit_result", lost_commit_ack)
            client.submit(LocalDaemonAdmissionRequest("target", target_uri))
            for remote in clients:
                remote.refresh_resource_offer()
                current = remote.active_session()
                assert current is not None
                executed = remote.execute_one(
                    current.session_id,
                    current.availability_revision,
                    sequence=remote.next_poll_sequence(current.session_id),
                    wait_timeout_ms=5000,
                )
                if daemon._service_error:
                    daemon.reconcile_once()
                assert executed.get("state") == "RELEASED", (executed, daemon._service_error)
            assert client.wait("target", timeout_seconds=25).state.value == "SUCCEEDED"
            assert len(attempts) == 2 and attempts[0] == attempts[1]
            producer_assignment = attempts[0]["assignment_id"]
            assert publications.count(producer_assignment) == 1
            assert commits == [producer_assignment, producer_assignment]
            assert verifications.count(producer_assignment) == (1 if pure_coordinator else 2)
            # Release also retains the terminal acknowledgement without IO.
            assert clients[0].commit_result(
                sessions[0].session_id, producer_assignment,
                **retained_commit,
            )["state"] == "RELEASED"
            assert verifications.count(producer_assignment) == (1 if pure_coordinator else 2)
            store = LocalRunStore(service.daemon.run_store_root)
            producer_result = StageWorkerResult.from_dict(
                store.read_stage_worker_result(target_uri, "produce", attempt=1)
            )
            consumer_result = StageWorkerResult.from_dict(
                store.read_stage_worker_result(target_uri, "consume", attempt=1)
            )
            artifacts = LocalArtifactStore(store.local_artifact_root(target_uri))
            receipt = artifacts.load(consumer_result.outputs["receipt"])
            assert isinstance(receipt, dict)
            assert receipt["size"] > 64 * 1024 * 1024
            assert receipt["producer_pid"] != receipt["consumer_pid"]
            reference = producer_result.outputs["manifest"]
            assert reference.metadata["measurement"] == 0.1803790032863617
            assert SHARED_PUBLICATION in reference.metadata
            primary = artifacts.local_path(reference)
            assert (
                primary.parent / "checkpoints" / "checkpoint.bin"
            ).read_bytes() == b"checkpoint-bytes"
            assert not tuple(
                service.daemon.coordinator_root.glob("remote-relay/*/outputs/*")
            )
            assert not tuple((tmp_path / "remote").glob("*/assignments/*/inputs/*/*"))
            assert not tuple(root.rglob("*.sqlite*"))
            for credential in ("agent", "other"):
                agent_root = tmp_path / "remote" / credential
                for directory in (agent_root / "assignments").iterdir():
                    request = _ResidentAssignmentWorkspace(agent_root, directory.name).request()
                    if project_context and "loom.project_report" in request.worker_metadata:
                        with pytest.raises(QueueConflictError, match="project report input"):
                            replace(request, inputs=tuple(item for item in request.inputs if item.logical_name != "loom_project_report"))
                    encoded_request = json.dumps(request.to_dict())
                    assert str(service.daemon.coordinator_root) not in encoded_request
                    assert str(root) not in encoded_request

            with sqlite3.connect(service.daemon.execution_database) as conn:
                owners = conn.execute(
                    "SELECT agent_id FROM coordinator_assignments WHERE run_uri = ?",
                    (target_uri,),
                ).fetchall()
            assert set(owners) == {("worker-b",), ("worker-c",)}
            # Native consumer/candidate integrity includes companions, not only JSON.
            (primary.parent / "sample_ids.json").write_text('["damaged"]')
            with pytest.raises(ArtifactStoreError, match="closure integrity"):
                artifacts.validate(reference)
    finally:
        for remote in clients:
            remote.close()
        server.stop()
        unix.stop()
        daemon.stop()
