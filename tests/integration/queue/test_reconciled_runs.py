"""Installed reconciliation through native publication, verification and replay."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError, RunRequest
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from loom.queue.deployment import load_coordinator_service_config
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue.agent_session_transport import (
    AgentTlsServerConfig,
    LocalDaemonAgentHttpServer,
)
from loom.queue.agent_sessions import TransportPrincipalPolicy
from tests.support.mutual_tls import certificate_fingerprint, mutual_tls_credentials
from tests.integration.queue.test_preparation_operations import (
    _service,
    _request,
    _result,
)

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]

_PROCESSOR = r"""
from copy import deepcopy
from loom.fingerprints import hash_mapping
from loom.queue.preparation import project_target_from_key
from loom.pipeline.stores import LocalArtifactStore
from loom.artifacts import ArtifactRef

def inspect(request):
    assert request['schema_version'] == 2
    if request['operation'] == 'verify_candidate':
        candidate = request['candidate']
        assert candidate['configuration']['scientific_evidence'] == request['project_result']['evidence']['payload']
        assert candidate['native_intent']['pipeline_digest']
        assert candidate['authority']['run_uri'] == candidate['run_uri']
        if candidate['authority']['status'] == 'SUCCEEDED':
            store = LocalArtifactStore(__import__('pathlib').Path(candidate['artifact_binding']['root']))
            for stage in candidate['authority']['stages']:
                assert stage['status'] == 'SUCCEEDED'
                for fact in stage['artifact_facts']:
                    payload = store.load(ArtifactRef.from_dict(fact['artifact']))
                    if isinstance(payload, dict) and payload.get('format') == 'fixture-resource-v1':
                        assert store.load(ArtifactRef.from_dict(payload['member'])) == {'value': 41}
        return {'schema_version': 1, 'candidate_digest': hash_mapping(candidate), 'verdict': 'verified'}
    composition = deepcopy(request['composition'])
    key = {'namespace': 'example', 'version': 1, 'digest': 'a' * 64}
    evidence = {'value': composition['resolved']['pipeline']['stages'][0]['config']['value']}
    uri = project_target_from_key(request['project_preparation'], key)
    for view in ('resolved', 'redacted'):
        composition[view]['scientific_evidence'] = evidence
        composition[view]['pipeline']['stages'][0]['config']['recovery'] = {
            'run_uri': uri if view == 'resolved' else '<redacted>',
            'resume_fingerprint': 'resume',
            'environment_fingerprint': request['profile_descriptor']['environment_fingerprint']}
    return {'schema_version': 2, 'composition': composition,
            'evidence': {'namespace': 'example', 'payload': evidence}, 'reconciliation_key': key}
"""


def _reconciled_service(tmp_path: Path):
    _service(tmp_path, local=True)
    installation = tmp_path / "installed-project"
    installation.mkdir()
    (installation / "reconcile_project.py").write_text(_PROCESSOR)
    path = tmp_path / "agent.json"
    agent = json.loads(path.read_text())
    agent["resident_profiles"][0]["environment"]["PYTHONPATH"] = str(installation)
    agent["resident_profiles"][0]["cpu_capacity"] = 2
    path.write_text(json.dumps(agent))
    path = tmp_path / "coordinator.json"
    config = json.loads(path.read_text())
    config["preparation"]["profiles"]["existing-project"]["project_processor"] = {
        "schema_version": 2,
        "callable": "reconcile_project:inspect",
        "evidence_namespace": "example",
        "recovery_stage": "produce",
        "target_prefix": "science-",
    }
    path.write_text(json.dumps(config))
    return load_coordinator_service_config(path)


def _reconciled_request(operation_id: str, *, retry: bool = False):
    return RunRequest(
        replace(_request("shared"), operation_id=operation_id, run_name=None),
        mode="reconcile",
        retry_policy="one_observed_failure" if retry else "never",
    )


@pytest.mark.parametrize("preparation_available", [False, True])
def test_https_negotiates_reconciliation_before_submission(
    tmp_path: Path, preparation_available: bool
) -> None:
    service = _reconciled_service(tmp_path)
    service = replace(service, daemon=replace(
        service.daemon,
        agent_policy=replace(service.daemon.agent_policy, principals=(
            TransportPrincipalPolicy("client", "caller", "client"),
        )),
    ))
    credentials = mutual_tls_credentials(tmp_path / "tls")
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(
        service.daemon,
        preparation=CoordinatorPreparation(service) if preparation_available else None,
    )
    daemon.start()
    server = LocalDaemonAgentHttpServer(daemon, AgentTlsServerConfig(
        "localhost", 0,
        credentials["server"].with_suffix(".crt"),
        credentials["server"].with_suffix(".key"),
        credentials["ca"].with_suffix(".crt"),
        {certificate_fingerprint(credentials["query"].with_suffix(".crt")): "client"},
    ))
    server.start()
    connection = tmp_path / "client.json"
    connection.write_text(json.dumps({
        "schema_version": 1,
        "kind": "loom.coordinator-client",
        "transport": {
            "kind": "https",
            "url": f"https://localhost:{server.port}",
            "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
            "certificate_path": str(credentials["query"].with_suffix(".crt")),
            "private_key_path": str(credentials["query"].with_suffix(".key")),
        },
    }))
    connection.chmod(0o600)
    try:
        with CoordinatorClient.from_connection_file(connection) as client:
            description = client.describe_connection()
            assert "authenticated-application-v1" in description.capabilities
            assert "daemon-control-v1" in description.capabilities
            for capability in ("agent-preparation-v1", "reconciled-run-v1"):
                assert (capability in description.capabilities) == preparation_available
            request = _reconciled_request("https-reconcile")
            if not preparation_available:
                with pytest.raises(CoordinatorClientError) as rejected:
                    client.start_run(request)
                assert rejected.value.code == "unsupported"
                assert rejected.value.mutation_outcome == "not_applied"
                assert not daemon._preparations.contains("https-reconcile")
            else:
                client.start_run(request)
                applied = daemon.wait_operation("https-reconcile", timeout=60).operation
                assert applied.state == "applied", applied.to_dict()
                assert client.start_run(request) == applied
                assert _result(applied)["decision"] == "new_attempt"
    finally:
        server.stop()
        daemon.stop()


def test_concurrent_reconciled_publication_and_verified_reuse(tmp_path):
    service = _reconciled_service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first, second = (
            _reconciled_request("submission-a"),
            _reconciled_request("submission-b"),
        )
        second = replace(
            second,
            preparation=replace(
                second.preparation, run_options={"tags": {"presentation": "second"}}
            ),
        )
        with ThreadPoolExecutor(2) as pool:
            accepted = list(
                pool.map(
                    lambda request: daemon.start_run(request, principal_id="caller"),
                    (first, second),
                )
            )
        assert all(_result(operation)["binding"] is None for operation in accepted)
        one = daemon.wait_operation(
            first.preparation.operation_id, timeout=40
        ).operation
        two = daemon.wait_operation(
            second.preparation.operation_id, timeout=40
        ).operation
        assert one.state == two.state == "applied", (
            one.to_dict(),
            two.to_dict(),
            daemon._service_error,
        )
        assert _result(one)["prepared_run"] == _result(two)["prepared_run"]
        assert (
            _result(one)["admission"]["admission_id"]
            == _result(two)["admission"]["admission_id"]
        )
        assert any(
            _result(item)["verification_report_ref"] is not None for item in (one, two)
        )
        with pytest.raises(QueueConflictError):
            daemon.start_run(
                replace(first, retry_policy="one_observed_failure"),
                principal_id="caller",
            )
        from copy import deepcopy
        from loom.preparation import decode_preparation_report
        from loom.queue.preparation import PreparationChildInput
        from loom.queue.local_daemon_execution import load_managed_local_intent
        from loom.pipeline.stores import LocalRunStore, LocalArtifactStore
        from loom.artifacts import ArtifactRef

        verified = next(
            item
            for item in (one, two)
            if _result(item)["verification_report_ref"] is not None
        )
        child = daemon.admission(
            _result(verified)["preparation_admission_id"]
        ).admission
        binding = PreparationChildInput.from_dict(
            load_managed_local_intent(service.daemon, child.run_uri)
            .pipeline.get_stage("prepare")
            .stage_config
        )
        report = LocalArtifactStore(
            LocalRunStore(service.daemon.run_store_root).local_artifact_root(
                child.run_uri
            )
        ).load(
            ArtifactRef.from_dict(dict(_result(verified)["verification_report_ref"]))
        )
        assert isinstance(report, dict)
        assert report["schema_version"] == 5 and report["candidate"] is not None
        for field in ("candidate", "verification", "profile_descriptor", "invocation"):
            changed = deepcopy(report)
            if field == "candidate":
                changed[field]["intent_digest"] = "changed"
            elif field == "verification":
                changed[field]["candidate_digest"] = "changed"
            elif field == "profile_descriptor":
                changed[field]["revision"] = "changed"
            else:
                changed[field]["overrides"] = ["value=999"]
            with pytest.raises(QueueConflictError):
                decode_preparation_report(changed, expected=binding)
        assert "reconcile_project" not in sys.modules
    finally:
        daemon.stop()


def test_unresolved_roundtrip_and_exact_legacy_shape():
    request = _reconciled_request("submission")
    assert request.preparation.run_name is None and request.queue_item_id is None
    assert RunRequest.from_dict(request.to_dict()) == request
    exact = RunRequest(_request(), "exact-queue")
    assert set(exact.to_dict()) == {"preparation", "queue_item_id"}
    assert RunRequest.from_dict(exact.to_dict()) == exact
    with pytest.raises(QueueServiceError, match="unresolved"):
        replace(request, queue_item_id="placeholder")


def test_lost_publication_reply_restart_keeps_single_owner(tmp_path):
    from threading import Event
    import sqlite3

    service = _reconciled_service(tmp_path)
    reached = Event()

    class Interrupted(CoordinatorPreparation):
        def publish_target(self, *args, **kwargs):
            super().publish_target(*args, **kwargs)
            reached.set()
            raise RuntimeError("lost publication reply")

    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=Interrupted(service))
    daemon.start()
    first, second = _reconciled_request("first"), _reconciled_request("second")
    try:
        daemon.start_run(first, principal_id="caller")
        daemon.start_run(second, principal_id="caller")
        assert reached.wait(30)
    finally:
        daemon.stop()
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        for request in (first, second):
            operation = daemon.wait_operation(
                request.preparation.operation_id, timeout=45
            ).operation
            assert operation.state == "applied", operation.to_dict()
            assert daemon.start_run(request, principal_id="caller") == operation
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM managed_admissions WHERE queue_item_id = ?",
                    ("science-" + "a" * 64,),
                ).fetchone()[0]
                == 1
            )
    finally:
        daemon.stop()


@pytest.mark.parametrize(
    "fault", ["corrupt", "missing_authority", "foreign_principal", "changed_science"]
)
def test_existing_candidate_conflicts_never_create_duplicate(
    tmp_path, fault, monkeypatch
):
    from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
    from loom.artifacts import ArtifactRef

    service = _reconciled_service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _reconciled_request("first")
        daemon.start_run(first, principal_id="caller")
        operation = daemon.wait_operation("first", timeout=40).operation
        assert operation.state == "applied", operation.to_dict()
        queue = _result(operation)["queue_item_id"]
        assert daemon._wait(queue, timeout_seconds=30).state.value == "SUCCEEDED"
        if fault == "corrupt":
            uri = _result(operation)["prepared_run"]["run_uri"]
            factory = service.daemon.coordinator_authority_factory
            assert factory is not None
            snapshot = factory(uri).open_run(uri)
            reference = snapshot.stages[0].artifact_facts[0].artifact
            store = LocalArtifactStore(
                LocalRunStore(service.daemon.run_store_root).local_artifact_root(uri)
            )
            assert isinstance(reference, ArtifactRef)
            # A real declared output byte changes after native success.
            artifact_path = store.local_path(reference)
            artifact_path.write_bytes(b"corrupt")
        elif fault == "missing_authority":

            def unavailable(*args, **kwargs):
                raise QueueConflictError("authority unavailable")

            assert daemon._preparations.callbacks is not None
            monkeypatch.setattr(
                daemon._preparations.callbacks, "capture_candidate", unavailable
            )
        second = _reconciled_request("second")
        if fault == "changed_science":
            second = replace(
                second,
                preparation=replace(
                    second.preparation, overrides=("pipeline.stages.0.config.value=42",)
                ),
            )
        daemon.start_run(
            second, principal_id="other" if fault == "foreign_principal" else "caller"
        )
        failed = daemon.wait_operation("second", timeout=45).operation
        assert failed.state in {"failed", "conflict"}, failed.to_dict()
        assert _result(failed)["admission"] is None
        assert len(tuple(service.daemon.run_store_root.glob("science-*"))) == 1
    finally:
        daemon.stop()


@pytest.mark.parametrize("bound", [False, True])
def test_cancellation_scope_with_second_contender(tmp_path, bound):
    from threading import Event

    service = _reconciled_service(tmp_path)
    entered, release = Event(), Event()

    class Paused(CoordinatorPreparation):
        def publish_target(self, *args, **kwargs):
            entered.set()
            assert release.wait(30)
            return super().publish_target(*args, **kwargs)

    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(
        service.daemon,
        preparation=Paused(service) if bound else CoordinatorPreparation(service),
    )
    if not bound:
        daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    try:
        first, second = _reconciled_request("first"), _reconciled_request("second")
        daemon.start_run(first, principal_id="caller")
        daemon.start_run(second, principal_id="caller")
        if bound:
            assert entered.wait(30)
        control = daemon.cancel_run_operation("first", principal_id="caller")
        if not bound:
            daemon._preparations._reconcile_lock.release()
        release.set()
        settled = daemon.wait_operation(control.operation_id, timeout=40).operation
        assert settled.state == "applied", settled.to_dict()
        first_result = daemon.wait_operation("first", timeout=40).operation
        second_result = daemon.wait_operation("second", timeout=45).operation
        assert first_result.state == "cancelled", first_result.to_dict()
        assert second_result.state == ("conflict" if bound else "applied"), (
            second_result.to_dict()
        )
        assert (
            _result(first_result)["binding"] is not None
            if bound
            else _result(first_result)["binding"] is None
        )
    finally:
        release.set()
        if daemon._preparations._reconcile_lock.locked():
            daemon._preparations._reconcile_lock.release()
        daemon.stop()


def test_schema_upgrade_preserves_accepted_exact_intent_and_cancel_receipt(tmp_path):
    import sqlite3
    from loom.queue.local_daemon import _initialize_preparation_schema

    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    request = RunRequest(_request(), "exact-queue")
    try:
        accepted = daemon.start_run(request, principal_id="caller")
        cancellation = daemon.cancel_run_operation(
            request.preparation.operation_id, principal_id="caller"
        )
    finally:
        daemon.stop()
        daemon._preparations._reconcile_lock.release()
    with sqlite3.connect(service.daemon.control_database) as conn:
        operations = conn.execute("SELECT * FROM preparation_operations").fetchall()
        cancellations = conn.execute(
            "SELECT * FROM preparation_cancellations"
        ).fetchall()
        conn.execute("DROP TABLE action_demands")
        conn.execute("DROP TABLE action_claims")
        conn.execute("DROP TABLE action_graph_cancellations")
        conn.execute("DROP TABLE preparation_cancellations")
        conn.execute("DROP TABLE preparation_operations")
        _initialize_preparation_schema(conn, legacy=True)
        conn.executemany(
            "INSERT INTO preparation_operations VALUES ("
            + ",".join("?" for _ in operations[0])
            + ")",
            operations,
        )
        conn.executemany(
            "INSERT INTO preparation_cancellations VALUES (?, ?, ?, ?, ?)",
            cancellations,
        )
        conn.execute("PRAGMA user_version = 15")
    assert LocalDaemon.upgrade_coordinator_root(service.daemon)[1] == 17
    with sqlite3.connect(service.daemon.control_database) as conn:
        assert (
            conn.execute("SELECT * FROM preparation_operations").fetchall()
            == operations
        )
        assert (
            conn.execute("SELECT * FROM preparation_cancellations").fetchall()
            == cancellations
        )
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        settled = daemon.wait_operation(cancellation.operation_id, timeout=20).operation
        assert settled.state == "applied"
        replay = daemon.start_run(request, principal_id="caller")
        assert (
            replay.operation_id == accepted.operation_id and replay.state == "cancelled"
        )
    finally:
        daemon.stop()


def test_frozen_retry_lost_reply_and_later_failure_never_chases(tmp_path):
    import sqlite3
    from threading import Event

    service = _reconciled_service(tmp_path)
    path = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(path.read_text())
    authored["pipeline"]["stages"].append(
        {
            **json.loads(json.dumps(authored["pipeline"]["stages"][0])),
            "name": "other",
            "depends_on": ["produce"],
        }
    )
    authored["pipeline"]["stages"][0]["factory"]["_target_"] = (
        "tests.support.pipeline_execution_stages.FailingStage"
    )
    path.write_text(json.dumps(authored))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(_reconciled_request("initial"), principal_id="caller")
        initial = daemon.wait_operation("initial", timeout=40).operation
        assert initial.state == "applied", initial.to_dict()
        queue = _result(initial)["queue_item_id"]
        failed = daemon._wait(queue, timeout_seconds=30)
        assert failed.state.value == "FAILED"
        factory = service.daemon.coordinator_authority_factory
        assert factory is not None
        uri = _result(initial)["prepared_run"]["run_uri"]
        assert {
            stage.stage_name for stage in factory(uri).open_run(uri).stages
        } == {"produce"}
    finally:
        daemon.stop()
    lost = Event()

    class LostReplyDaemon(LocalDaemon):
        def _submit(self, request, **kwargs):
            if request.retry_failed_revision is not None:
                # Both independently prepared contenders must freeze this failure
                # before either is allowed to apply its shared native journal.
                with self._connection() as conn:
                    rows = conn.execute(
                        "SELECT selected_json FROM preparation_operations WHERE operation_id IN ('retry-a', 'retry-b')"
                    ).fetchall()
                if len(rows) != 2 or any(
                    json.loads(row[0])["reconciliation"]["failed_revision"] is None
                    for row in rows
                ):
                    raise RuntimeError("awaiting second observed failure")
            result = super()._submit(request, **kwargs)
            if request.retry_failed_revision is not None:
                lost.set()
                raise RuntimeError("lost native retry reply")
            return result

    daemon = LostReplyDaemon(
        service.daemon, preparation=CoordinatorPreparation(service)
    )
    daemon.start()
    requests = [
        _reconciled_request(name, retry=True) for name in ("retry-a", "retry-b")
    ]
    try:
        for request in requests:
            daemon.start_run(request, principal_id="caller")
        assert lost.wait(60), [
            daemon.operation(name).to_dict() for name in ("retry-a", "retry-b")
        ]
        later = daemon._wait(queue, timeout_seconds=30)
        assert later.state.value == "FAILED" and later.revision > failed.revision
    finally:
        daemon.stop()
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        for request in requests:
            applied = daemon.wait_operation(
                request.preparation.operation_id, timeout=50
            ).operation
            assert applied.state == "applied", applied.to_dict()
            assert daemon.start_run(request, principal_id="caller") == applied
        with sqlite3.connect(service.daemon.control_database) as conn:
            journals = conn.execute(
                "SELECT value FROM daemon_metadata WHERE key LIKE 'admission-retry:%'"
            ).fetchall()
            assert len(journals) == 1
            assert json.loads(journals[0][0])["failed_revision"] == failed.revision
        assert daemon.admission_for_queue_item(queue).revision == later.revision
    finally:
        daemon.stop()


def _wait_path(path: Path, timeout: float = 40):
    import time
    from threading import Event

    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, str(path)
        Event().wait(0.02)


def test_prepared_without_admission_verifies_then_submits_once(tmp_path):
    service = _reconciled_service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        preparation = replace(_request(), run_name="science-" + "a" * 64)
        daemon.prepare_run(preparation, principal_id="caller")
        prepared = daemon.wait_operation(preparation.operation_id, timeout=40).operation
        assert prepared.state == "applied", prepared.to_dict()
        daemon.start_run(_reconciled_request("attach"), principal_id="caller")
        attached = daemon.wait_operation("attach", timeout=45).operation
        assert attached.state == "applied", attached.to_dict()
        assert _result(attached)["decision"] == "admit_prepared"
        assert _result(attached)["verification_report_ref"] is not None
        assert _result(attached)["prepared_run"] == _result(prepared)["prepared_run"]
    finally:
        daemon.stop()


@pytest.mark.parametrize("finish_during_verification", [False, True])
def test_active_candidate_observation_revision_change_and_shared_child_cancellation(
    tmp_path, finish_during_verification
):
    import os
    from loom.coordinator import CoordinatorClient
    from loom.queue import LocalDaemonSocketServer

    service = _reconciled_service(tmp_path)
    marker = tmp_path / "markers"
    marker.mkdir()
    path = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(path.read_text())
    authored["pipeline"]["stages"].append(
        {
            **json.loads(json.dumps(authored["pipeline"]["stages"][0])),
            "name": "other",
            "depends_on": ["produce"],
        }
    )
    authored["pipeline"]["stages"][0]["factory"]["_target_"] = (
        "tests.support.pipeline_execution_stages.ReleaseStage"
    )
    authored["pipeline"]["stages"][0]["config"].update(
        marker_dir=str(marker), timeout_seconds=120
    )
    path.write_text(json.dumps(authored))
    # Record the real target worker process while retaining the fixture's release owner.
    module = tmp_path / "installed-project" / "reconcile_project.py"
    module.write_text(
        module.read_text()
        + """
from tests.support.pipeline_execution_stages import ReleaseStage
class OwnedStage(ReleaseStage):
    def run(self, context, inputs):
        import os
        from pathlib import Path
        Path(context.stage_config['marker_dir'], 'pid').write_text(str(os.getpid()))
        return super().run(context, inputs)
"""
    )
    authored["pipeline"]["stages"][0]["factory"]["_target_"] = (
        "reconcile_project.OwnedStage"
    )
    path.write_text(json.dumps(authored))
    captures = []

    class Changing(CoordinatorPreparation):
        def capture_candidate(self, *args, **kwargs):
            candidate = super().capture_candidate(*args, **kwargs)
            captures.append(candidate)
            if finish_during_verification:
                (marker / "release").touch()
            return candidate

    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=Changing(service))
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    daemon.start()
    server.start()
    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            assert "reconciled-run-v1" in client.describe_connection().capabilities
            client.start_run(_reconciled_request("first"))
            first = daemon.wait_operation("first", timeout=40).operation
            assert first.state == "applied", first.to_dict()
            _wait_path(marker / "produce.started")
            pid = int((marker / "pid").read_text())
            client.start_run(_reconciled_request("observer"))
            attached = daemon.wait_operation("observer", timeout=50).operation
            assert attached.state == "applied", attached.to_dict()
            assert {
                stage["stage_name"] for stage in captures[0]["authority"]["stages"]
            } == {"produce"}
            assert set(captures[0]["prepared_run"]["stage_names"]) == {
                "produce", "other"
            }
            assert (
                _result(attached)["admission"]["admission_id"]
                == _result(first)["admission"]["admission_id"]
            )
            assert _result(attached)["decision"] == (
                "reuse" if finish_during_verification else "observe"
            )
            if finish_during_verification:
                assert (
                    len(
                        {
                            json.dumps(item["authority"]["revision"], sort_keys=True)
                            for item in captures
                        }
                    )
                    >= 2
                )
            else:
                # Closing an observer leaves the actual owned target worker alive.
                client.close()
                os.kill(pid, 0)
                with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as cancellation_client:
                    control = cancellation_client.cancel_run_operation("observer")
                assert control.state == "pending"
                settled = daemon.wait_operation(
                    control.operation_id, timeout=45
                ).operation
                assert settled.state == "applied", settled.to_dict()
                assert (
                    daemon.admission_for_queue_item(
                        _result(first)["queue_item_id"]
                    ).state.value
                    == "CANCELLED"
                )
                with pytest.raises(ProcessLookupError):
                    os.kill(pid, 0)
    finally:
        (marker / "release").touch()
        server.stop()
        daemon.stop()


def test_public_run_facade_and_cli_reconciled_replay(tmp_path):
    import io
    import loom
    from loom.cli.main import main

    _reconciled_service(tmp_path)
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.deployment",
                "coordinator": {
                    "service_config": "coordinator.json",
                    "lifetime": "run",
                },
                "binding_path": "binding.json",
                "preparation": {
                    "source": _request().source.to_dict(),
                    "profile": _request().preparation_profile,
                },
                "startup_seconds": 30,
            }
        )
    )
    selection.chmod(0o600)
    request = _reconciled_request("facade-submission")
    outcome = loom.run(request, deployment=selection, timeout_seconds=90)
    admission = outcome.observation.admission
    assert admission is not None and admission.state.value == "SUCCEEDED", (
        outcome.to_dict()
    )
    output, errors = io.StringIO(), io.StringIO()
    code = main(
        [
            "run",
            "pipeline.yaml",
            "--deployment",
            str(selection),
            "--reconcile",
            "--operation-id",
            "cli-submission",
            "--format",
            "json",
        ],
        stdout=output,
        stderr=errors,
    )
    assert code == 0, (output.getvalue(), errors.getvalue())
    value = json.loads(output.getvalue())["result"]
    assert value["operation"]["result"]["decision"] == "reuse"
    assert value["admission"]["admission_id"] == admission.admission_id


def test_corrupt_formatted_resource_member_rejected_despite_success(tmp_path):
    from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
    from loom.artifacts import ArtifactRef

    service = _reconciled_service(tmp_path)
    module = tmp_path / "installed-project" / "reconcile_project.py"
    module.write_text(
        module.read_text()
        + """
class ManifestProducer:
    def run(self, context, inputs):
        path = context.local_output_path('data', suffix='.member.json')
        path.write_text('{"value":41}')
        member = context.register_local_artifact('data', path, artifact_type='json', codec_key='json.v1')
        manifest = {'format': 'fixture-resource-v1', 'member': member.to_dict()}
        return {'data': context.save_artifact('data', manifest, artifact_type='json', codec_key='json.v1')}
"""
    )
    path = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(path.read_text())
    authored["pipeline"]["stages"][0]["factory"]["_target_"] = (
        "reconcile_project.ManifestProducer"
    )
    path.write_text(json.dumps(authored))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(_reconciled_request("first"), principal_id="caller")
        first = daemon.wait_operation("first", timeout=40).operation
        assert first.state == "applied", first.to_dict()
        assert (
            daemon._wait(
                _result(first)["queue_item_id"], timeout_seconds=30
            ).state.value
            == "SUCCEEDED"
        )
        uri = _result(first)["prepared_run"]["run_uri"]
        factory = service.daemon.coordinator_authority_factory
        assert factory is not None
        snapshot = factory(uri).open_run(uri)
        manifest = snapshot.stages[0].artifact_facts[0].artifact
        store = LocalArtifactStore(
            LocalRunStore(service.daemon.run_store_root).local_artifact_root(uri)
        )
        manifest_payload = store.load(manifest)
        assert isinstance(manifest_payload, dict)
        member = ArtifactRef.from_dict(manifest_payload["member"])
        store.local_path(member).write_text('{"value":99}')
        assert store.verify_checksum(
            manifest
        )  # The top-level success artifact is unchanged.
        daemon.start_run(_reconciled_request("second"), principal_id="caller")
        rejected = daemon.wait_operation("second", timeout=45).operation
        assert rejected.state == "failed", rejected.to_dict()
        assert _result(rejected)["admission"] is None
        assert (
            daemon.admission_for_queue_item(_result(first)["queue_item_id"]).state.value
            == "SUCCEEDED"
        )
    finally:
        daemon.stop()


def test_before_binding_cancel_reaps_installed_child_and_contender_continues(tmp_path):
    import os

    service = _reconciled_service(tmp_path)
    marker = tmp_path / "preparation-pid"
    module = tmp_path / "installed-project" / "reconcile_project.py"
    module.write_text(
        module.read_text().replace(
            "    assert request['schema_version'] == 2",
            f"""    assert request['schema_version'] == 2
    if request['operation_id'] == 'cancel-unbound':
        import os, time
        from pathlib import Path
        Path({str(marker)!r}).write_text(str(os.getpid()))
        time.sleep(120)
""",
        )
    )
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(_reconciled_request("cancel-unbound"), principal_id="caller")
        _wait_path(marker)
        pid = int(marker.read_text())
        assert _result(daemon.operation("cancel-unbound"))["binding"] is None
        daemon.start_run(_reconciled_request("contender"), principal_id="caller")
        control = daemon.cancel_run_operation("cancel-unbound", principal_id="caller")
        settled = daemon.wait_operation(control.operation_id, timeout=45).operation
        assert settled.state == "applied", settled.to_dict()
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        contender = daemon.wait_operation("contender", timeout=45).operation
        assert contender.state == "applied", contender.to_dict()
        assert _result(contender)["decision"] == "new_attempt"
    finally:
        daemon.stop()
