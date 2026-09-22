"""Native remote producer/consumer closure without payload relay or copies."""

import hashlib
import json
from pathlib import Path
from typing import Any, cast
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
from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint
from tests.integration.queue.test_preparation_operations import (
    _service,
    _request,
    _result,
)

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("death", [False, True])
def test_failed_remote_recovery_survives_settlement_and_explicit_retry(
    tmp_path, monkeypatch, death
):
    pure_coordinator = True
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
            "_target_": "tests.support.shared_execution_stages.SharedRecoveryProducer"
        },
        config={"death": death},
        outputs={"manifest": {"artifact_type": "json", "codec_key": "json.v1"}},
        placement={"target": "worker-b"},
    )
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
        for name, path in (("b", alternate),)
    ]
    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
        SHARED_EXECUTION_CAPABILITY,
        "preparation-input-v2",
    )
    config_path = tmp_path / "coordinator.json"
    authored = json.loads(config_path.read_text())
    authored["preparation"]["profiles"]["existing-project"].update(
        configuration_policy="shared", shared_locations=[]
    )
    if pure_coordinator:
        authored["local_agent"] = None
        authored["shared_roots"] = roots(root)
        authored["preparation"]["profiles"]["existing-project"][
            "resident_profile_id"
        ] = profiles[0].descriptor.profile_id
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
        for name, credential in (("worker-b", "agent"),)
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
        for profile, credential in zip(profiles, ("agent",), strict=True):
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
                prepared = clients[0].execute_one(
                    sessions[0].session_id,
                    sessions[0].availability_revision,
                    sequence=1,
                    wait_timeout_ms=5000,
                )
                assert prepared["state"] == "RELEASED", prepared
            operation = client.wait_operation("prepare-1", timeout_seconds=25).operation
            assert operation.state == "applied", operation
            result = _result(operation)
            target_uri = result["prepared_run"]["run_uri"]

            remote = clients[0]
            ordinary = LocalDaemonAdmissionRequest("target", target_uri)
            client.submit(ordinary)
            remote.refresh_resource_offer()
            current = remote.active_session()
            executed = remote.execute_one(
                current.session_id,
                current.availability_revision,
                sequence=remote.next_poll_sequence(current.session_id),
                wait_timeout_ms=5000,
            )
            assert executed["state"] == "RELEASED", executed
            failed = client.wait("target", timeout_seconds=25)
            assert failed.state.value == "FAILED", failed
            assert client.submit(ordinary) == failed
            store = LocalRunStore(service.daemon.run_store_root)
            retained_result = store.read_stage_worker_result(
                target_uri, "produce", attempt=1
            )
            assert retained_result is not None
            assert retained_result["status"] == "FAILED"
            from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore

            authority = SQLitePerRunAuthorityStore(target_uri)
            assert len(authority.open_run(target_uri).stages[0].attempts) == 1
            first_attempt = authority.open_run(target_uri).stages[0].attempts[0]
            if death:
                assert (
                    "without a durable worker result"
                    in cast(Any, retained_result["failure"])["message"]
                )
            retained = list(root.glob("loom-recovery-retained/*"))
            assert len(retained) == 1
            assert (
                retained[0] / "checkpoint" / "weights"
            ).read_bytes() == b"completed-progress"
            # Reopen durable coordinator connections; no process or in-memory
            # result object contributes to predecessor selection.
            with daemon._connection() as conn:
                receipt = conn.execute(
                    "SELECT result_json FROM agent_receipts WHERE principal_id = 'native-shared-recovery'"
                ).fetchone()
                reference = json.loads(receipt[0])
                assert reference["identity"]["attempt"] == 1
            from loom.queue import _shared_recovery

            original_seal = _shared_recovery.seal

            def replayed_seal(*args, **kwargs):
                result = original_seal(*args, **kwargs)
                assert original_seal(*args, **kwargs) == result
                return result

            monkeypatch.setattr(_shared_recovery, "seal", replayed_seal)
            client.submit(
                LocalDaemonAdmissionRequest(
                    "target", target_uri, retry_failed_revision=failed.revision
                )
            )
            remote.refresh_resource_offer()
            current = remote.active_session()
            executed = remote.execute_one(
                current.session_id,
                current.availability_revision,
                sequence=remote.next_poll_sequence(current.session_id),
                wait_timeout_ms=5000,
            )
            assert executed["state"] == "RELEASED", executed
            completed = client.wait("target", timeout_seconds=25)
            assert completed.state.value == "SUCCEEDED", completed
            assert authority.open_run(target_uri).stages[0].attempts[0] == first_attempt
            result = StageWorkerResult.from_dict(
                store.read_stage_worker_result(target_uri, "produce", attempt=2)
            )
            artifacts = LocalArtifactStore(store.local_artifact_root(target_uri))
            payload = artifacts.load(result.outputs["manifest"])
            assert isinstance(payload, dict)
            assert payload["restored"] is True
            binding = payload["binding"]
            assert binding["predecessors"][0]["reference"] == reference
            assert str(alternate) in binding["predecessors"][0]["path"]
            assert binding["current"]["path"] != binding["predecessors"][0]["path"]
            assert len(list(root.glob("loom-recovery-retained/*"))) == 2
            assert not tuple(root.rglob("*.sqlite*"))
    finally:
        for remote in clients:
            remote.close()
        server.stop()
        unix.stop()
        daemon.stop()
