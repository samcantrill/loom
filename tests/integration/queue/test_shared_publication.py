"""Native remote producer/consumer closure without payload relay or copies."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest

from loom.coordinator import CoordinatorClient
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonAdmissionRequest, LocalDaemonSocketServer
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


def test_two_agents_publish_and_consume_complete_large_shared_closure(
    tmp_path, monkeypatch
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
        config={},
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
            )
        )
        for name, path in (("b", root), ("c", alternate))
    ]
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
        SHARED_EXECUTION_CAPABILITY,
    )
    config_path = tmp_path / "coordinator.json"
    authored = json.loads(config_path.read_text())
    authored["preparation"]["profiles"]["existing-project"].update(
        configuration_policy="shared", shared_locations=[]
    )
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
                return response

            monkeypatch.setattr(clients[0], "declare_outputs", lost_publication_ack)
            client.submit(LocalDaemonAdmissionRequest("target", target_uri))
            for remote, session in zip(clients, sessions, strict=True):
                executed = remote.execute_one(
                    session.session_id,
                    session.availability_revision,
                    sequence=1,
                    wait_timeout_ms=5000,
                )
                assert executed["state"] == "RELEASED", executed
            assert client.wait("target", timeout_seconds=25).state.value == "SUCCEEDED"
            assert len(attempts) == 2 and attempts[0] == attempts[1]
            store = LocalRunStore(service.daemon.run_store_root)
            producer_result = StageWorkerResult.from_dict(
                store.read_stage_worker_result(target_uri, "produce", attempt=1)
            )
            consumer_result = StageWorkerResult.from_dict(
                store.read_stage_worker_result(target_uri, "consume", attempt=1)
            )
            artifacts = LocalArtifactStore(store.local_artifact_root(target_uri))
            receipt = artifacts.load(consumer_result.outputs["receipt"])
            assert receipt["size"] > 64 * 1024 * 1024
            assert receipt["producer_pid"] != receipt["consumer_pid"]
            reference = producer_result.outputs["manifest"]
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
