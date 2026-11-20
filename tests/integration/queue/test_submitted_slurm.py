"""Submitted Slurm dispatch, worker, and shared commit across coordinator restart."""

import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
from time import monotonic, sleep

import pytest
import loom

from examples.execution.containers.apptainer_fixture import fake_apptainer
from loom.pipeline.runtime.options import RunOptions
from loom.pipeline.status import StageStatus
from loom.preparation import decode_preparation_report, prepare_child_run
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue._slurm_submitted_worker import run_submitted_stage
from loom.queue._submitted_container_policy import SubmittedContainerPolicy
from loom.queue.managed_local_preparation import prepare_managed_run
from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace, SlurmStageDelivery
from tests.integration.queue import test_submitted_preparation as preparation_fixture
from tests.integration.queue.test_slurm_ready_stage import (
    _launch_profile,
    _positive_containment_helper,
)

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("preparation,recovery,cancel_inspection,peer_inspection", [
    (False, False, False, False), (True, False, False, False),
    (False, True, False, False), (False, False, True, False),
    (False, False, True, True),
])
@pytest.mark.parametrize("outbound,cancel_publication", [(False, False), (True, False), (True, True)])
def test_submitted_slurm_dispatch_worker_and_shared_commit_restart(
    tmp_path, monkeypatch, preparation, recovery, cancel_inspection, peer_inspection, outbound, cancel_publication
):
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((
        str(Path(loom.__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[3]),
    )))
    original_fixture = preparation_fixture._fixture
    with fake_apptainer() as runtime:
        # The fake runtime has no mount namespace. Translate only the fixed
        # preparation snapshot lookup; shared paths use the existing fake namespace seam.
        executable = Path(runtime["options"]["command"])
        shim = (
            "import loom.queue.shared_execution as shared; "
            "shared.execution_roots = lambda roots, container: roots; "
            "original = shared.materialize; "
            "shared.materialize = lambda value, roots, container: original(value, roots, container=False); "
            "shared._preparation_input_roots = lambda profile, preparation: {key: str(value) for key, value in profile.preparation_shared_roots.items()}; "
            "import runpy; runpy.run_module('loom.queue._slurm_submitted_worker', run_name='__main__')"
        )
        executable.write_text(
            executable.read_text().replace(
                "elif option == '--pwd':",
                "elif option == '--bind':\n"
                "        for mount in value.split(','):\n"
                "            assert os.path.exists(mount.split(':', 1)[0]), 'missing bind source: ' + mount\n"
                "    elif option == '--pwd':",
            ).replace(
                "os.execvpe(args[0], args, os.environ)",
                "if args[1:3] == ['-m', 'loom.queue._slurm_submitted_worker']:\n"
                f"    args = [args[0], '-c', {shim!r}, *args[3:]]\n"
                "os.execvpe(args[0], args, os.environ)",
            )
        )

        def fixture(path):
            policy, execution, request = original_fixture(path)
            output = path / "published"
            output.mkdir()
            (output / "challenge").write_bytes(b"published")
            roots = dict(policy.shared_roots)
            captures = path / "captures"
            captures.mkdir()
            (captures / "challenge").write_bytes(b"captures")
            roots["captures"] = {
                "host_path": str(captures),
                "container_path": "/loom/captures",
                "access": "ro",
                "challenge": {
                    "path": "challenge",
                    "sha256": hashlib.sha256(b"captures").hexdigest(),
                },
            }
            roots["outputs"] = {
                "host_path": str(output),
                "container_path": "/loom/outputs",
                "access": "rw",
                "challenge": {
                    "path": "challenge",
                    "sha256": hashlib.sha256(b"published").hexdigest(),
                },
                "publication": {
                    "max_members": 128,
                    "max_payload_bytes": 1024**3,
                    "max_manifest_bytes": 1024**2,
                },
            }
            return (
                replace(
                    policy,
                    shared_roots=roots,
                    runtime_options=runtime["options"],
                    preparation_shared_roots={"projects": path / "captures"},
                ),
                replace(execution, python_executable=sys.executable),
                request,
            )

        monkeypatch.setattr(preparation_fixture, "_fixture", fixture)
        service, binding, report = preparation_fixture._run(
            tmp_path,
            monkeypatch,
            slurm=True,
            staging_continuation_stages=("produce",) if recovery else (),
            stage_update={
                "placement": {"execution_route": {"kind": "slurm", "profile": "batch"}},
                **({
                    "factory": {"_target_": "tests.support.shared_execution_stages.SharedRecoveryProducer"},
                    "config": {"death": False, "complete_diagnostics": True, "staged_sample": True},
                    "outputs": {"manifest": {"artifact_type": "json", "codec_key": "json.v1"}},
                } if recovery else {}),
            },
        )
        service = replace(
            service,
            daemon=replace(
                service.daemon,
                slurm_profiles=(
                    replace(
                        service.daemon.slurm_profiles[0],
                        containment_helper=_positive_containment_helper(),
                        max_outstanding=None if outbound else service.daemon.slurm_profiles[0].max_outstanding,
                    ),
                ),
            ),
        )
        if preparation:
            prepared = prepare_child_run(
                service, binding, "child", runtime_options=RunOptions(executor="local")
            )
        else:
            composed, requirements, _ = decode_preparation_report(
                report, expected=binding
            )
            prepared = prepare_managed_run(
                service, composed, "workload", execution_requirements=requirements
            )
        peer = None
        if peer_inspection or (outbound and recovery):
            peer = prepare_managed_run(
                service, composed, "independent-workload", execution_requirements=requirements
            )
        profile = service.daemon.slurm_profiles[0]
        config = LocalDaemonConfig(
            coordinator_root=tmp_path / "daemon/coordinator",
            agent_root=tmp_path / "daemon/agent",
            run_store_root=service.daemon.run_store_root,
            resident_worker_launch_profile=_launch_profile(),
            slurm_profiles=(profile,),
            shared_roots=service.daemon.shared_roots,
            container_capabilities=service.daemon.container_capabilities,
        )
        # Hold the first coordinator inspection only. Worker launch checks
        # remain real, and the restarted coordinator must inspect afresh.
        validation_started, validation_release = Event(), Event()
        retention_started, retention_release = Event(), Event()
        publication_started, publication_release = Event(), Event()
        peer_submitted = False
        if not preparation and not recovery:
            from loom.queue import _input_validation
            inspect_inputs = _input_validation.require_bindings

            def slow_inputs(*args, **kwargs):
                if not validation_started.is_set():
                    validation_started.set()
                    assert validation_release.wait(30)
                return inspect_inputs(*args, **kwargs)

            monkeypatch.setattr(_input_validation, "require_bindings", slow_inputs)
        from tests.support.outbound_slurm import OutboundSlurmCoordinator
        if outbound:
            config = OutboundSlurmCoordinator.configure(config)
        def make_daemon(config):
            return OutboundSlurmCoordinator(config, tmp_path / 'outbound') if outbound else LocalDaemon(config)
        LocalDaemon.initialize(config)
        daemon = make_daemon(config)
        daemon.start()
        try:
            client = daemon.client_view(
                LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
            )
            client.submit(LocalDaemonAdmissionRequest("submitted", prepared.run_uri))
            if not preparation and not recovery:
                try:
                    assert validation_started.wait(10)
                    assert not daemon._execution.slurm_assignments.list_run_unreleased(prepared.run_uri)
                    assert not [call for call in profile.runner.calls if call[0] == "sbatch"]
                    with ThreadPoolExecutor(max_workers=1) as readers:
                        detail = readers.submit(
                            lambda: client.admission(client.admission_for_queue_item("submitted").admission_id)
                        ).result(timeout=5)
                        assert detail.admission.run_uri == prepared.run_uri
                        inspections = detail.owners["input_validation"]["inspections"]
                        assert len(inspections) == 1
                        assert inspections[0]["reason"] == "input_validation_pending"
                        if peer is not None:
                            client.submit(LocalDaemonAdmissionRequest("independent", peer.run_uri))
                            deadline = monotonic() + 10
                            peer_records = ()
                            while monotonic() < deadline:
                                peer_records = daemon._execution.slurm_assignments.list_run_unreleased(peer.run_uri)
                                if peer_records and peer_records[0].state == "accepted":
                                    break
                                sleep(0.02)
                            assert peer_records and peer_records[0].state == "accepted"
                            assert not validation_release.is_set()
                            assert not daemon._execution.slurm_assignments.list_run_unreleased(prepared.run_uri)
                            assert len([call for call in profile.runner.calls if call[0] == "sbatch"]) == 1
                        if cancel_inspection:
                            cancelled = readers.submit(client.cancel, "submitted").result(timeout=5)
                            assert cancelled.cancellation_operation_id is not None
                            validation_release.set()
                            settled = readers.submit(client.wait, "submitted", timeout_seconds=10).result(timeout=12)
                            assert settled.state.value == "CANCELLED"
                            assert not daemon._execution.slurm_assignments.list_run_unreleased(prepared.run_uri)
                            assert len([call for call in profile.runner.calls if call[0] == "sbatch"]) == int(peer is not None)
                            return
                    # Stop cannot wait on the blocked inspection. Its eventual
                    # result cannot authorize work in the new coordinator.
                    daemon.stop()
                    daemon = make_daemon(config)
                    daemon.start()
                finally:
                    validation_release.set()
            for attempt in range(1, 3 if recovery else 2):
                deadline = monotonic() + 10
                records = ()
                while monotonic() < deadline:
                    records = daemon._execution.slurm_assignments.list_run_unreleased(
                        prepared.run_uri
                    )
                    if records and records[0].state == "accepted":
                        break
                    sleep(0.02)
                assert records and records[0].state == "accepted"
                record = records[0]
                operation = daemon.operation(record.assignment.operation_id)
                assert operation.result["job_id"] == record.job_id
                assert (
                    len([call for call in profile.runner.calls if call[0] == "sbatch"]) == attempt + int(peer_submitted)
                )
                daemon.stop()
                daemon = make_daemon(config)
                daemon.start()
                principal = LocalDaemonPrincipal(
                    profile.bootstrap_principal_id,
                    LocalDaemonRole.SLURM_BOOTSTRAP,
                    profile.credential_reference,
                )
                view = daemon.slurm_bootstrap_view(principal)
                registration = view.register(
                    operation_id=record.assignment.operation_id,
                    request_digest=record.assignment.request_digest,
                    job_id=record.job_id,
                    cluster=record.cluster,
                    incarnation="compute-1",
                    capability=base64.b64encode(
                        Path(profile.job_private_file_provider.fixed_path).read_bytes()
                    ).decode(),
                )
                delivery = SlurmStageDelivery.from_dict(registration["delivery"])
                assert delivery.submitted_execution == binding.execution
                policy = SubmittedContainerPolicy.from_dict(
                    registration["submitted_container_policy"]
                )
                assert policy.capability == binding.container_capability
                workspace = SlurmBootstrapWorkspace(
                    tmp_path / "compute", delivery.assignment_id
                )
                workspace.persist_delivery(delivery)
                for item in delivery.inputs:
                    offset = 0
                    while True:
                        data, final = view.input_chunk(
                            delivery.assignment_id,
                            "compute-1",
                            item.transfer_id,
                            offset=offset,
                        )
                        offset = workspace.stage_input_chunk(
                            item.transfer_id, offset, data, final=final
                        )
                        if final:
                            break
                workspace.accept_inputs(shared_roots=policy.shared_roots)
                assert view.inputs_ready(delivery.assignment_id, "compute-1")
                fence = view.grant(delivery.assignment_id, "compute-1")
                assert view.start_permit(delivery.assignment_id, "compute-1", fence)
                view.started(delivery.assignment_id, "compute-1", fence, "process-1")
                result = run_submitted_stage(
                    workspace, policy, agent_id=record.assignment.agent_id, fence=fence
                )
                failed = recovery and attempt == 1
                assert result.status is (StageStatus.FAILED if failed else StageStatus.SUCCEEDED), result.failure
                if failed:
                    assert "synthetic failure after complete progress" in result.failure.message
                    assert not tuple((tmp_path / "published").glob("loom-recovery-retained/*"))
                    from loom.queue import _shared_recovery

                    original_seal = _shared_recovery.seal
                    interrupted = False

                    def interrupted_seal(*args, **kwargs):
                        nonlocal interrupted
                        if outbound and not interrupted:
                            retention_started.set()
                            assert retention_release.wait(30)
                        reference = original_seal(*args, **kwargs)
                        if not interrupted:
                            interrupted = True
                            raise OSError("lost seal acknowledgement before reference commit")
                        return reference

                    monkeypatch.setattr(_shared_recovery, "seal", interrupted_seal)
                retained = workspace.retain_result(result)
                if not failed:
                    assert retained.output_kind == "shared"
                if outbound and (recovery or cancel_publication) and not failed:
                    from loom.queue import _shared_publication
                    from loom.queue._slurm_result_transport import SharedSlurmResult
                    prepare_publication = _shared_publication.prepare_publication
                    def held_publication(*args, **kwargs):
                        publication_started.set()
                        assert publication_release.wait(30)
                        return prepare_publication(*args, **kwargs)
                    monkeypatch.setattr(_shared_publication, "prepare_publication", held_publication)
                    identity = daemon._execution.slurm_result_identity(
                        daemon._execution.slurm_assignments.read(delivery.assignment_id),
                    )
                    transport = SharedSlurmResult(profile.result_storage, delivery.assignment_id, compute=True)
                    from loom.queue import local_daemon_execution as execution_module
                    # Force durable acceptance without an in-memory worker. A
                    # new coordinator must rediscover this publication intent.
                    with monkeypatch.context() as capacity:
                        capacity.setattr(execution_module, "_SLURM_STORAGE_LIMIT", 0)
                        transport.publish(identity, retained, lambda *args: pytest.fail("shared payload relay"))
                        deadline = monotonic() + 10
                        while monotonic() < deadline:
                            queued = daemon._execution.slurm_assignments.read(delivery.assignment_id)
                            if queued.publication_requested_at is not None:
                                break
                            sleep(0.02)
                        assert queued.publication_requested_at is not None
                        assert queued.publication_completed_at is None
                        assert not daemon._execution._slurm_storage_futures
                        assert not publication_started.is_set()
                        daemon.stop()
                    daemon = make_daemon(config)
                    daemon.start()
                    assert publication_started.wait(10)
                    deadline = monotonic() + 15
                    while monotonic() < deadline:
                        pending_record = daemon._execution.slurm_assignments.read(delivery.assignment_id)
                        if pending_record.compute_released_at is not None:
                            break
                        sleep(0.02)
                    assert pending_record.compute_released_at is not None
                    assert pending_record.publication_completed_at is None
                    assert pending_record.state != "released"
                    assert transport.path.exists()
                    if cancel_publication:
                        cancel_client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
                        cancel_client.cancel("submitted")
                        deadline = monotonic() + 15
                        while monotonic() < deadline:
                            cancelled = daemon._execution.slurm_assignments.read(delivery.assignment_id)
                            if cancelled.publication_cancelled_at is not None:
                                break
                            sleep(0.02)
                        assert cancelled.publication_cancelled_at is not None
                        assert cancelled.publication_completed_at is None
                        assert cancelled.state != "released"
                        assert transport.path.exists()
                        assert delivery.assignment_id in daemon._execution._slurm_storage_futures
                        publication_release.set()
                        daemon.stop()
                        daemon = make_daemon(config)
                        daemon.start()
                        cancel_client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
                        assert cancel_client.wait("submitted", timeout_seconds=15).state.value == "CANCELLED"
                        deadline = monotonic() + 10
                        while monotonic() < deadline and transport.path.exists():
                            sleep(0.02)
                        assert not transport.path.exists()
                        assert daemon._execution.slurm_assignments.read(delivery.assignment_id).publication_completed_at is None
                        assert not daemon._execution._slurm_storage_futures
                        return
                    publication_release.set()
                    deadline = monotonic() + 15
                    while monotonic() < deadline:
                        if daemon._execution.slurm_assignments.read(delivery.assignment_id).publication_completed_at is not None:
                            break
                        sleep(0.02)
                    assert daemon._execution.slurm_assignments.read(delivery.assignment_id).publication_completed_at is not None
                elif failed:
                    from loom.queue import _shared_publication
                    from loom.queue._slurm_result_transport import SharedSlurmResult

                    execution = daemon._execution
                    agent = execution._slurm_agent
                    assert agent is not None
                    prepare_publication = _shared_publication.prepare_publication

                    def prepare_during_observation_backoff(*args, **kwargs):
                        publication = prepare_publication(*args, **kwargs)
                        agent._next_poll[record.assignment.operation_id] = monotonic() + 60
                        return publication

                    identity = execution.slurm_result_identity(execution.slurm_assignments.read(delivery.assignment_id))
                    transport = SharedSlurmResult(profile.result_storage, delivery.assignment_id, compute=True)
                    with monkeypatch.context() as polling:
                        polling.setattr(_shared_publication, "prepare_publication", prepare_during_observation_backoff)
                        transport.publish(identity, retained, workspace.output_chunk)
                        deadline = monotonic() + 10
                        while monotonic() < deadline:
                            current = execution.slurm_assignments.read(delivery.assignment_id)
                            if current.state in {"terminal", "logical_released", "released"}:
                                break
                            sleep(0.02)
                        assert current.state in {"terminal", "logical_released", "released"}
                else:
                    view.declare_report(delivery.assignment_id, "compute-1", fence, retained)
                    view.commit_result(delivery.assignment_id, "compute-1", fence)
                # Hold retention on the live outbound owner for peer progress;
                # the subsequent successful attempt still exercises commit restart.
                if not (outbound and failed):
                    daemon.stop()
                    daemon = make_daemon(config)
                    daemon.start()
                view = daemon.slurm_bootstrap_view(principal)
                assert not view.start_permit(delivery.assignment_id, "compute-1", fence)
                view.commit_result(delivery.assignment_id, "compute-1", fence)
                view.release(delivery.assignment_id, "compute-1")
                client = daemon.client_view(
                    LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
                )
                if outbound and failed:
                    assert retention_started.wait(10), "outbound retention did not start"
                    assert peer is not None
                    original_squeue = profile.runner.squeue
                    def running_peer(*, job_ids=()):
                        response = original_squeue(job_ids=job_ids)
                        return replace(response, stdout="".join(f"{job}|RUNNING|None\n" for job in job_ids))
                    monkeypatch.setattr(profile.runner, "squeue", running_peer)
                    client.submit(LocalDaemonAdmissionRequest("retention-peer", peer.run_uri))
                    peer_submitted = True
                    deadline = monotonic() + 15
                    peer_record = None
                    while monotonic() < deadline:
                        candidates = daemon._execution.slurm_assignments.list_run_unreleased(peer.run_uri)
                        if candidates and candidates[0].job_id:
                            peer_record = candidates[0]
                            observed = daemon._execution.slurm_submissions.read(peer_record.assignment.operation_id)
                            if observed.scheduler_source == "squeue":
                                break
                        sleep(0.02)
                    assert peer_record is not None and observed.scheduler_source == "squeue"
                    client.cancel("retention-peer")
                    deadline = monotonic() + 10
                    while monotonic() < deadline:
                        if any(call[0] == "scancel" and peer_record.job_id in call[1] for call in profile.runner.calls):
                            break
                        sleep(0.02)
                    assert any(call[0] == "scancel" and peer_record.job_id in call[1] for call in profile.runner.calls)
                    assert not retention_release.is_set()
                    assert daemon._execution.slurm_assignments.read(delivery.assignment_id).state != "released"
                    assert len(daemon._execution._slurm_storage_futures) <= 2
                    retention_release.set()
                settled = client.wait("submitted", timeout_seconds=15)
                assert settled.state.value == ("FAILED" if failed else "SUCCEEDED")
                if recovery:
                    deadline = monotonic() + 10
                    while monotonic() < deadline:
                        released = daemon._execution.slurm_assignments.read(delivery.assignment_id)
                        if released.state == "released":
                            break
                        sleep(0.02)
                    assert released.state == "released"
                    from loom.queue import _shared_recovery
                    from loom.queue._recovery_cleanup import preview_recovery_cleanup, release_recovery
                    with daemon._connection() as conn:
                        row = conn.execute(
                            "SELECT result_json FROM agent_receipts WHERE principal_id=? "
                            "AND operation='seal' AND idempotency_key=?",
                            (_shared_recovery._PRINCIPAL, delivery.assignment_id),
                        ).fetchone()
                    reference = json.loads(row[0])
                    tree = _shared_recovery.resolve(reference, config.coordinator_shared_roots)
                    assert reference["identity"]["agent_id"] == record.assignment.agent_id
                    entries = preview_recovery_cleanup(daemon, prepared.run_uri)["entries"]
                    entry = next(item for item in entries if item["assignment_id"] == delivery.assignment_id)
                    assert entry["eligible"] is (not failed), entry
                    assert "recovery_not_sealed" not in entry["reasons"]
                    if failed:
                        assert interrupted
                        assert "recovery_still_required" in entry["reasons"]
                        assert (tree / "checkpoint/weights").read_bytes() == b"completed-progress"
                        assert (tree / "partial").read_bytes() == b"incomplete-progress"
                        first_reference = reference
                        # Retry must acquire the retained seal after reopening the same owners.
                        daemon.stop()
                        daemon = make_daemon(config)
                        daemon.start()
                        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
                        client.submit(LocalDaemonAdmissionRequest(
                            "submitted", prepared.run_uri, retry_failed_revision=settled.revision,
                        ))
                    else:
                        from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
                        from loom.pipeline.execution.models import StageWorkerResult

                        store = LocalRunStore(config.run_store_root)
                        committed = StageWorkerResult.from_dict(store.read_stage_worker_result(
                            prepared.run_uri, delivery.stage_name, attempt=attempt,
                        ))
                        artifacts = LocalArtifactStore(store.local_artifact_root(prepared.run_uri))
                        payload = artifacts.load(committed.outputs["manifest"])
                        assert payload["restored"] is True
                        assert payload["binding"]["predecessors"][0]["reference"] == first_reference
                        assert payload["binding"]["current"]["path"] != payload["binding"]["predecessors"][0]["path"]
                        # Cleanup authorizes the recorded Slurm agent, preserves
                        # failed recovery and replays without rewriting science.
                        operator = LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
                        arguments = dict(run_uri=prepared.run_uri, assignment_id=delivery.assignment_id,
                                         operation_id="release-success", reason="qualified complete diagnostics")
                        from loom.queue.agent_sessions import AgentPolicyConfig, TransportPrincipalPolicy

                        # Scope the test's operator to the dynamically allocated
                        # native agent. Protected-config reload has separate coverage.
                        with monkeypatch.context() as patch:
                            patch.setattr(daemon.daemon if outbound else daemon, "_agent_policy", AgentPolicyConfig(principals=(
                                TransportPrincipalPolicy(
                                    "operator-credential", "operator", "operator", actions=("cleanup_recovery",),
                                    agent_ids=(record.assignment.agent_id,),
                                ),
                            )))
                            released = release_recovery(daemon, operator, **arguments)
                            assert release_recovery(daemon, operator, **arguments) == released
                        assert not tree.exists()
                        assert _shared_recovery.resolve(first_reference, config.coordinator_shared_roots).is_dir()
                assert (
                    len([call for call in profile.runner.calls if call[0] == "sbatch"]) == attempt + int(peer_submitted)
                )
        finally:
            retention_release.set()
            publication_release.set()
            daemon.stop()
