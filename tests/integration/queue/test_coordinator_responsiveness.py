"""Five actual resident owners through TLS, with slow retained context IO.

This opt-in qualification holds synthetic jobs at an observable file barrier.
It uses the host running pytest; it does not qualify remote GPU/boot behavior.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import gc
import json
from pathlib import Path
import sqlite3
import sys
from threading import Event
from time import monotonic, sleep

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.orchestration import ExecutionRequirement
from loom.pipeline.planning import ExecutionPlan
from loom.pipeline.stores import LocalRunStore
from loom.queue import LocalDaemon, LocalDaemonAdmissionRequest, LocalDaemonConfig, LocalDaemonPrincipal, LocalDaemonRole
from loom.queue import agent_session_transport as transport
from loom.queue.agent_sessions import AgentOffer, AgentOfferRenewal, AgentPolicyConfig, AgentPrincipalPolicy, AgentRegistration
from loom.queue.agent_session_transport import AgentTlsClientConfig, AgentTlsServerConfig, LocalDaemonAgentHttpClient, LocalDaemonAgentHttpServer, _resident_provider_descriptors
from loom.queue._remote_stage_execution import REGULAR_FILE_RELAY_CAPABILITY, REMOTE_EXECUTION_CAPABILITY, ResidentExecutionProfile, ResidentProfileDescriptor
from loom.queue.local_daemon_runtime import prepare_managed_local_runtime_record
from tests.integration.queue.test_agent_session_transport import _prepare_remote_producer_run, _fresh_remote_agent_root
from tests.support.mutual_tls import certificate_fingerprint, mutual_tls_credentials


def _until(predicate, seconds=30):
    deadline = monotonic() + seconds
    while not predicate():
        assert monotonic() < deadline, "qualification barrier did not advance"
        sleep(0.05)


def _rss_bytes():
    import os
    return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def _large_composition(store, uri, requirement):
    # A sizeable authored-input projection exercises real JSON validation,
    # hashing, metadata references, and discard of decoded provenance.
    metadata = {"final_value_authorship": [
        {"path": ["parameter", str(i)], "source_path": "source/" + "a" * 3900 + ".yaml"}
        for i in range(8192)
    ]}
    store.write_composition_manifest(uri, {"schema_version": 1, "metadata": metadata})
    store.write_run_user_metadata(uri, {"config_provenance": {"schema_version": 2, "metadata": metadata}})
    pipeline = PipelineSpec.from_config(json.loads(store.read_config_snapshot(uri, "resolved"))["pipeline"])
    prepare_managed_local_runtime_record(
        store=store, run_uri=uri, pipeline=pipeline,
        plan=ExecutionPlan.from_dict(store.read_plan(uri)),
        execution_requirements={name: requirement for name in pipeline.stage_names},
    )
    size = store.local_generated_artifact_path(uri, "config/composition_manifest.json").stat().st_size
    assert 31 * 1024**2 <= size <= 34 * 1024**2
    return size


@pytest.mark.slow
@pytest.mark.integration
def test_five_agents_keep_control_and_exact_ownership_during_slow_io(tmp_path, monkeypatch):
    names = tuple(f"agent-{i}" for i in range(5))
    credentials = mutual_tls_credentials(tmp_path / "tls", client_names=names)
    descriptor = ResidentProfileDescriptor("resident", "v1", "project", "environment", "executor")
    requirement = ExecutionRequirement("project", "environment", "executor")
    capabilities = ("python", REMOTE_EXECUTION_CAPABILITY, REGULAR_FILE_RELAY_CAPABILITY)
    policy = AgentPolicyConfig(agents=tuple(
        AgentPrincipalPolicy(name, name, name, ("default",), capabilities) for name in names
    ))
    store = LocalRunStore(tmp_path / "runs")
    jobs = []
    sizes = []
    markers = [tmp_path / f"marker-{i}" for i in range(5)]
    for i, name in enumerate(names):
        uri, authority = _prepare_remote_producer_run(
            store, run_name=name, machine_id=name, value=i, requirement=requirement,
            stage_factory="tests.support.pipeline_execution_stages.ReleaseStage",
            stage_config={"marker_dir": f"marker-{i}", "marker_dir_environment": "LOOM_QUALIFICATION_ROOT", "timeout_seconds": 180},
        )
        sizes.append(_large_composition(store, uri, requirement))
        jobs.append((uri, authority))
    slow = [_prepare_remote_producer_run(store, run_name=f"slow-{i}", machine_id=names[0], value=0, requirement=requirement)[0] for i in range(2)]
    config = LocalDaemonConfig(tmp_path / "coordinator", None, store.root, None,
                               cpu_capacity=0, agent_policy=policy, remote_profiles=(descriptor,),
                               poll_interval_seconds=0.25)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonAgentHttpServer(daemon, AgentTlsServerConfig(
        "localhost", 0, credentials["server"].with_suffix(".crt"), credentials["server"].with_suffix(".key"),
        credentials["ca"].with_suffix(".crt"),
        {certificate_fingerprint(credentials[name].with_suffix(".crt")): name for name in names},
    ))
    server.start()
    profile = ResidentExecutionProfile(descriptor, Path(__file__).resolve().parents[3], Path(sys.executable), environment={"LOOM_QUALIFICATION_ROOT": str(tmp_path)})
    clients, monitors, sessions, offers, configs = [], [], [], [], []
    stopped, release = Event(), Event()
    entered = [Event(), Event()]
    samples = {"normal": [], "delay": []}
    observation = ["normal"]
    failures = []
    result_lost, renewal_lost = Event(), Event()
    lost_renewal = []
    started_at = monotonic()
    executor = ThreadPoolExecutor(max_workers=10)
    futures, renewal_futures = [], []
    coordinator = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
    try:
        for name in names:
            client_config = AgentTlsClientConfig(
                f"https://localhost:{server.port}", credentials["ca"].with_suffix(".crt"),
                credentials[name].with_suffix(".crt"), credentials[name].with_suffix(".key"),
                _fresh_remote_agent_root(tmp_path, name), (profile,),
            )
            LocalDaemonAgentHttpClient.initialize_agent_root(client_config)
            client = LocalDaemonAgentHttpClient(client_config)
            clients.append(client)
            configs.append(client_config)
            monitors.append(LocalDaemonAgentHttpClient(replace(client_config, agent_root=None, resident_profiles=())))
            handshake = client.handshake()
            session = client.register(AgentRegistration(
                f"register-{name}", str(handshake["coordinator_id"]), str(handshake["coordinator_epoch"]),
                client.agent_root_id, "config-1", "inventory-1", "availability-1", ("default",), capabilities,
            ))
            sessions.append(session)
            offers.append(client.publish_offer(AgentOffer(
                session.session_id, session.coordinator_epoch, session.config_revision,
                session.inventory_revision, session.availability_revision, 1, 0, 30,
                _resident_provider_descriptors(profile, name), resident_profiles=(descriptor,),
            ), idempotency_key=f"offer-{name}"))
        original_exchange = transport._exchange_agent_request

        def lose_response(client_config, operation, *args, **kwargs):
            reply = original_exchange(client_config, operation, *args, **kwargs)
            if client_config.certificate_path == configs[0].certificate_path:
                if operation == "renew" and not renewal_lost.is_set():
                    lost_renewal.append(reply.value)
                    renewal_lost.set()
                    reply.connection.close()
                    raise transport._IndeterminateAgentProtocolError("qualification lost renewal response")
                if operation == "result" and not result_lost.is_set():
                    result_lost.set()
                    reply.connection.close()
                    raise transport._IndeterminateAgentProtocolError("qualification lost commit response")
            return reply

        monkeypatch.setattr(transport, "_exchange_agent_request", lose_response)

        def renew(index):
            sequence = 1
            while not stopped.is_set():
                # The fifth owner deliberately loses offer freshness under load;
                # its running assignment must remain owned until release.
                if observation[0] == "delay" and index == 4:
                    stopped.wait(0.1)
                    continue
                request = AgentOfferRenewal(sessions[index].session_id, str(offers[index]["offer_id"]), "availability-1", sequence)
                begin = monotonic()
                try:
                    try:
                        receipt = monitors[index]._call("renew", {"renewal": request.value()})
                    except transport._IndeterminateAgentProtocolError:
                        receipt = monitors[index]._call("renew", {"renewal": request.value()})
                        if index == 0 and sequence == 1:
                            assert receipt == lost_renewal[0]
                    samples[observation[0]].append(monotonic() - begin)
                    assert receipt["offer_id"] == offers[index]["offer_id"]
                    sequence += 1
                except BaseException as exc:
                    failures.append(exc)
                    return
                stopped.wait(0.15)

        def execute(index):
            client = clients[index]
            try:
                sequence = 1
                deadline = monotonic() + 90
                while True:
                    receipt = client.execute_one(sessions[index].session_id, "availability-1", sequence=sequence, wait_timeout_ms=5000)
                    if receipt.get("state") == "RELEASED":
                        return receipt
                    assert receipt.get("result") == "wait", receipt
                    assert monotonic() < deadline
                    sequence += 1
            except transport._IndeterminateAgentProtocolError:
                # An application restart must resume the exact durable result,
                # including a commit whose acknowledgement was lost.
                if index == 0 and result_lost.is_set():
                    assert client._supervisor is not None
                    supervisor_id = client._supervisor.supervisor_id
                    client.close()
                    client = LocalDaemonAgentHttpClient(configs[index])
                    clients[index] = client
                    assert client._supervisor is not None
                    assert client._supervisor.supervisor_id == supervisor_id
                deadline = monotonic() + 30
                while True:
                    try:
                        (receipt,) = client.resume_retained_work()
                        return receipt
                    except transport._IndeterminateAgentProtocolError:
                        assert monotonic() < deadline
                        sleep(0.05)

        renewal_futures = [executor.submit(renew, i) for i in range(5)]
        # Admit before polling so large first-time decoding does not exhaust one
        # bounded long poll. Renewals already measure this representative load.
        for i, (uri, _) in enumerate(jobs):
            coordinator.submit(LocalDaemonAdmissionRequest(names[i], uri))
        futures = [executor.submit(execute, i) for i in range(5)]
        _until(lambda: all((marker / "build.started").exists() for marker in markers), 60)
        _until(lambda: len(samples["normal"]) >= 150)
        assert not failures, failures
        execution = daemon._execution
        assert execution is not None
        original_load = execution.load_context

        def blocked(admission):
            if admission.run_uri in slow:
                index = slow.index(admission.run_uri)
                entered[index].set()
                assert release.wait(75)
            return original_load(admission)

        monkeypatch.setattr(execution, "load_context", blocked)
        for i, uri in enumerate(slow):
            coordinator.submit(LocalDaemonAdmissionRequest(f"slow-{i}", uri))
        assert all(event.wait(10) for event in entered)
        observation[0] = "delay"
        gc.collect()
        baseline_rss = _rss_bytes()
        peak_rss = baseline_rss
        cancellation_started = monotonic()
        for i in range(2):
            assert coordinator.cancel(f"slow-{i}").cancellation_operation_id
        cancellation_seconds = monotonic() - cancellation_started
        delay_started = monotonic()
        while monotonic() - delay_started < 31.5:
            assert not failures, failures
            assert len(daemon._contexts._pending) == 2
            assert not release.is_set()
            peak_rss = max(peak_rss, _rss_bytes())
            assert daemon.status().coordinator_id
            sleep(0.1)
        with daemon._connection() as conn:
            now = daemon._accepted_time(conn)
            for i, offer in enumerate(offers):
                expiry, current = conn.execute("SELECT expires_at, current FROM agent_offers WHERE offer_id = ?", (offer["offer_id"],)).fetchone()
                assert current == 1
                assert (expiry >= now) is (i != 4)
            assert conn.execute("SELECT COUNT(*) FROM remote_assignments WHERE state = 'RUNNING'").fetchone()[0] == 5
        release.set()
        _until(lambda: all(coordinator.admission_for_queue_item(f"slow-{i}").state.value == "CANCELLED" for i in range(2)))
        with sqlite3.connect(config.execution_database) as conn:
            assert conn.execute("SELECT COUNT(*) FROM coordinator_assignments").fetchone()[0] == 5
            assert conn.execute("SELECT COUNT(*) FROM coordinator_assignments WHERE state = 'released'").fetchone()[0] == 0
        stopped.set()
        for future in renewal_futures:
            future.result(5)
        for marker in markers:
            (marker / "release").touch()
        assert all(future.result(30)["state"] == "RELEASED" for future in futures)
        assert result_lost.is_set() and renewal_lost.is_set()
        for name, (uri, authority) in zip(names, jobs, strict=True):
            assert coordinator.wait(name, timeout_seconds=30).state.value == "SUCCEEDED"
            snapshot = authority.open_run(uri)
            assert len(snapshot.stages) == 1
            assert len(snapshot.stages[0].attempts) == 1
            assert snapshot.stages[0].latest_commit is not None
        for client_config in configs:
            with sqlite3.connect(client_config.agent_root / "supervisor" / "supervisor.sqlite") as conn:
                assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 1
        gc.collect()
        final_rss = _rss_bytes()
        p99 = {name: sorted(values)[int((len(values) - 1) * 0.99)] for name, values in samples.items()}
        assert p99["normal"] < 1 and p99["delay"] < 5, p99
        assert cancellation_seconds < 5
        assert peak_rss - baseline_rss < 512 * 1024**2
        assert final_rss - baseline_rss < 256 * 1024**2
        print(json.dumps({"agents": 5, "manifest_bytes": sizes, "delay_seconds": 31.5,
            "renewal_samples": {key: len(value) for key, value in samples.items()}, "renewal_p99_seconds": p99,
            "cancellation_seconds": cancellation_seconds, "rss_growth_peak_bytes": peak_rss - baseline_rss,
            "rss_growth_final_bytes": final_rss - baseline_rss, "elapsed_seconds": monotonic() - started_at}, sort_keys=True))
    finally:
        stopped.set()
        release.set()
        for marker in markers:
            marker.mkdir(exist_ok=True)
            (marker / "release").touch()
        executor.shutdown(wait=True)
        for client in clients:
            if client._supervisor is not None:
                client._supervisor.shutdown_for_test()
            client.close()
        for monitor in monitors:
            monitor.close()
        server.stop()
        daemon.stop()
