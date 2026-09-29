"""Concurrent outbound progress across actual TLS and supervisor boundaries."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Mapping
from pathlib import Path
import sqlite3
import json
import os
import subprocess
import hashlib
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread, get_ident
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from loom.pipeline.stores import LocalRunStore
from loom.queue import (
    ExecutionRequirement,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    SupervisorLaunchState,
)
import loom.queue._agent_process_supervisor as supervisor_module
from loom.queue.agent_sessions import (
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentControl,
    AgentControlKind,
    GpuDeviceDescriptor,
    TransportPrincipalPolicy,
)
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer,
    _RemoteAgentJournal,
)
from loom.queue._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
    ResidentGpuDevice,
)
from loom.queue.gpu.occupancy import (
    GpuOccupancyMonitor,
    GpuOccupancyPolicy,
    GpuProcessObservation,
    NvidiaSmiGpuProcessObserver,
)
import loom.queue.agent_session_transport as transport
import loom.queue.deployment as deployment
from loom.queue.shared_execution import SHARED_EXECUTION_CAPABILITY
from loom.queue.deployment import (
    OutboundAgentRegistrationConfig,
    OutboundAgentServiceConfig,
)
from tests.support.mutual_tls import certificate_fingerprint, mutual_tls_credentials
from tests.support.stage29_composition import ResidentProviderFactory
from .test_agent_session_transport import (
    _prepare_remote_producer_run,
    _prepare_remote_sleep_run,
    _prepare_gpu_environment_run,
    _supervisor_process_ids,
)

pytestmark = pytest.mark.integration


def _eventually(check, *, seconds=20):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        result = check()
        if result:
            return result
        sleep(0.02)
    pytest.fail("service boundary did not progress before the fixture watchdog")


def _rows(path, sql, parameters=()):
    with sqlite3.connect(path) as conn:
        return conn.execute(sql, parameters).fetchall()


@contextmanager
def _service(
    monkeypatch,
    *,
    ceiling=1,
    threaded_supervisor=False,
    shared=False,
    gpu: bool | int = False,
    cpu=2,
    memory=0,
):
    # Supervisor IPC has a platform path limit; all fixture-owned roots are short.
    with TemporaryDirectory(prefix="la-", dir="/tmp") as temporary:
        root = Path(temporary)
        credentials = mutual_tls_credentials(root / "tls")
        descriptor = ResidentProfileDescriptor(
            "resident-1", "revision-1", "project-1", "environment-1", "executor-1"
        )
        capabilities = (
            "python",
            REMOTE_EXECUTION_CAPABILITY,
            REGULAR_FILE_RELAY_CAPABILITY,
        )
        roots = {}
        devices = tuple(
            GpuDeviceDescriptor(f"gpu-{index}", "model-0", 1024)
            for index in range(int(gpu))
        )
        if shared:
            shared_root = root / "shared"
            shared_root.mkdir()
            (shared_root / "challenge").write_bytes(b"publication")
            roots = {
                "outputs": {
                    "host_path": str(shared_root),
                    "container_path": "/loom/outputs",
                    "access": "rw",
                    "challenge": {
                        "path": "challenge",
                        "sha256": hashlib.sha256(b"publication").hexdigest(),
                    },
                    "publication": {
                        "max_members": 1024,
                        "max_payload_bytes": 1024 * 1024,
                        "max_manifest_bytes": 1024 * 1024,
                    },
                }
            }
            capabilities += (
                SHARED_EXECUTION_CAPABILITY,
                "shared-assignment-reference-v1",
            )
        profile = ResidentExecutionProfile(
            descriptor,
            Path(__file__).resolve().parents[3],
            Path(sys.executable),
            cpu_capacity=cpu,
            memory_capacity_bytes=memory,
            environment={"LOOM_TEST_GATE_ROOT": str(root)},
            shared_roots=roots,
            gpu_devices=tuple(
                ResidentGpuDevice(
                    device,
                    "GPU-private" if len(devices) == 1 else f"GPU-private-{index}",
                )
                for index, device in enumerate(devices)
            ),
        )
        if shared:
            from loom.queue.resident_readiness import qualified_resident_profile

            profile = qualified_resident_profile(profile)
            assert profile.readiness_result is not None
            assert profile.readiness_result.ok
            descriptor = profile.descriptor
        policy = AgentPolicyConfig(
            agents=(
                AgentPrincipalPolicy(
                    "credential",
                    "principal",
                    "agent-a",
                    ("default",),
                    capabilities,
                    devices,
                ),
            ),
            principals=(
                TransportPrincipalPolicy(
                    "operator",
                    "operator",
                    "operator",
                    ("drain", "resume", "reload", "cancel_active"),
                    ("agent-a",),
                ),
            ),
        )
        store = LocalRunStore(root / "runs")
        daemon_config = LocalDaemonConfig(
            root / "coordinator",
            None,
            store.root,
            None,
            cpu_capacity=0,
            agent_policy=policy,
            remote_profiles=(descriptor,),
            shared_roots=roots,
            assignment_payload_root_id="outputs" if shared else None,
        )
        LocalDaemon.initialize(daemon_config)
        daemon = LocalDaemon(daemon_config)
        daemon.start()
        server = LocalDaemonAgentHttpServer(
            daemon,
            AgentTlsServerConfig(
                "localhost",
                0,
                credentials["server"].with_suffix(".crt"),
                credentials["server"].with_suffix(".key"),
                credentials["ca"].with_suffix(".crt"),
                {
                    certificate_fingerprint(
                        credentials["agent"].with_suffix(".crt")
                    ): "credential"
                },
            ),
        )
        server.start()
        agent_root = root / "agent"
        client_config = AgentTlsClientConfig(
            f"https://localhost:{server.port}",
            credentials["ca"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".crt"),
            credentials["agent"].with_suffix(".key"),
            agent_root,
            (profile,),
            agent_resource_provider_factory=(
                transport._default_remote_providers
                if gpu or memory
                else ResidentProviderFactory(capacity=cpu)
            ),
            gpu_occupancy_policy=GpuOccupancyPolicy(3600, 7200, 0.1) if gpu else None,
            max_concurrent_assignments=ceiling,
        )
        LocalDaemonAgentHttpClient.initialize_agent_root(client_config)
        supervisor_thread = None
        dispatches = []
        if threaded_supervisor:
            dispatch_type = supervisor_module._SupervisorDispatch

            def capture_dispatch(owner):
                dispatch = dispatch_type(owner)
                dispatches.append(dispatch)
                return dispatch

            monkeypatch.setattr(
                supervisor_module, "_SupervisorDispatch", capture_dispatch
            )
            supervisor_thread = Thread(
                target=supervisor_module._serve,
                args=(agent_root / "supervisor",),
                daemon=True,
            )
            supervisor_thread.start()
            _eventually(lambda: dispatches)
            original_wait = AgentProcessSupervisorClient._wait_for_shutdown

            def join_thread(client):
                if client.service_process_id == os.getpid():
                    supervisor_thread.join(10)
                    assert not supervisor_thread.is_alive()
                else:
                    original_wait(client)

            monkeypatch.setattr(
                AgentProcessSupervisorClient, "_wait_for_shutdown", join_thread
            )
        config = OutboundAgentServiceConfig(
            client_config,
            OutboundAgentRegistrationConfig(
                "config-1",
                "inventory-1",
                "availability-1",
                ("default",),
                capabilities,
            ),
            0.01,
            root / "agent.yaml",
            "0" * 64,
            "1" * 64,
        )
        monkeypatch.setattr(deployment, "_OUTBOUND_POLL_WAIT_MS", 100)
        stop = Event()
        failures = []
        retries = []
        original_steps = deployment._steps

        def observed_steps(function, *args, **kwargs):
            from loom.queue.errors import QueueError

            try:
                return (yield from original_steps(function, *args, **kwargs))
            except QueueError as error:
                retries.append((function.__name__, str(error)))
                raise

        monkeypatch.setattr(deployment, "_steps", observed_steps)

        def serve():
            try:
                deployment.run_outbound_agent_service(config, stop=stop)
            except BaseException as error:
                failures.append(error)

        thread = Thread(target=serve)
        thread.start()
        case = SimpleNamespace(
            root=root,
            agent_root=agent_root,
            store=store,
            config=config,
            daemon=daemon,
            database=daemon_config.control_database,
            client=daemon.client_view(
                LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
            ),
            operator=daemon.operator_view(
                LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR, "operator")
            ),
            stop=stop,
            thread=thread,
            failures=failures,
            retries=retries,
            serve=serve,
            expected_failures=[],
            requirement=ExecutionRequirement(
                descriptor.project_fingerprint,
                descriptor.environment_fingerprint,
                descriptor.executor_fingerprint,
            ),
            shared_scope=None
            if not shared
            else {
                "capability": SHARED_EXECUTION_CAPABILITY,
                "roots": descriptor.shared_roots,
                "locations": [],
            },
            supervisor_owner=None if not dispatches else dispatches[0].supervisor,
        )
        try:
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT offer_json FROM agent_offers WHERE current = 1",
                )
            )
            yield case
        except BaseException:
            print("service failures", failures, "retries", retries[-10:])
            print(
                "assignments",
                _rows(
                    case.database, "SELECT assignment_id, state FROM remote_assignments"
                ),
            )
            print(
                "local",
                _rows(
                    agent_root / "journal.sqlite",
                    "SELECT assignment_id, state FROM assignments",
                ),
            )
            print(
                "admissions",
                _rows(
                    case.database,
                    "SELECT queue_item_id, state, blocked_reason FROM managed_admissions",
                ),
            )
            raise
        finally:
            stop.set()
            case.thread.join(80)
            # Only this fixture's exact supervisor is allowed to contain its
            # retained groups, including assertion-failure and stopped-app paths.
            cleanup_errors = []
            try:
                if _supervisor_process_ids(agent_root) or (
                    supervisor_thread is not None and supervisor_thread.is_alive()
                ):
                    owner = AgentProcessSupervisorClient(
                        agent_root,
                        supervisor_module.SupervisorLaunchConfiguration(
                            transport._read_remote_agent_root_id(agent_root),
                            tuple(
                                item.launch_profile
                                for item in client_config.resident_profiles
                            ),
                        ),
                    )
                    for (encoded,) in _rows(
                        agent_root / "supervisor/supervisor.sqlite",
                        "SELECT launch_json FROM launches",
                    ):
                        launch = supervisor_module._launch_from_value(
                            json.loads(encoded)
                        )
                        try:
                            assert (
                                owner.contain(launch).state
                                is SupervisorLaunchState.CONTAINED
                            )
                        except BaseException as error:
                            cleanup_errors.append(error)
                    owner.shutdown_for_test()
            finally:
                case.thread.join(10)
                server.stop()
                daemon.stop()
            assert not cleanup_errors
            assert not case.thread.is_alive(), failures
            assert _supervisor_process_ids(agent_root) == ()
            if case.supervisor_owner is not None:
                for child in case.supervisor_owner._children.values():
                    assert child.settled()
                    assert child._process.returncode is not None
            assert [type(error) for error in failures] == case.expected_failures


def _submit(case, name, *, sequential=False):
    uri, authority = _prepare_remote_producer_run(
        case.store,
        run_name=name,
        machine_id="agent-a",
        value=7,
        requirement=case.requirement,
        sequential=sequential,
        shared_scope=case.shared_scope,
        resource_entries=(
            None
            if not case.config.client.capacity_profile.memory_capacity_bytes
            else {
                "cpu": {"kind": "cpu", "amount": 1, "unit": "count"},
                "memory": {"kind": "memory", "amount": 1024**3, "unit": "B"},
            }
        ),
    )
    case.client.submit(LocalDaemonAdmissionRequest(name, uri))
    return uri, authority


def _submit_gated(case, name, *, memory=1024**3, gpu=False, workers=1):
    gate = case.root / name
    uri, authority = _prepare_remote_producer_run(
        case.store,
        run_name=name,
        machine_id="agent-a",
        value=7,
        requirement=case.requirement,
        stage_factory="tests.support.pipeline_execution_stages.ReleaseStage",
        enforce=("gpu",) if gpu else (),
        shared_scope=case.shared_scope,
        independent_stages=workers,
        stage_config={
            "marker_dir": name,
            "marker_dir_environment": "LOOM_TEST_GATE_ROOT",
            "timeout_seconds": 900,
        },
        resource_entries={
            "cpu": {"kind": "cpu", "amount": 1, "unit": "count"},
            "memory": {"kind": "memory", "amount": memory, "unit": "B"},
            **(
                {
                    "gpu": {
                        "kind": "gpu",
                        "amount": 1,
                        "unit": "count",
                        "attributes": {"allocation_mode": "exclusive"},
                    }
                }
                if gpu
                else {}
            ),
        },
    )
    case.client.submit(LocalDaemonAdmissionRequest(name, uri))
    return gate, uri, authority


def _release_gate(gate):
    gate.mkdir(exist_ok=True)
    (gate / "release").touch()


def _running(case):
    return _rows(
        case.agent_root / "supervisor/supervisor.sqlite",
        "SELECT json_extract(launch_json, '$.assignment_id'), operation_id, pid FROM launches WHERE state = 'running' ORDER BY operation_id",
    )


@pytest.mark.parametrize("ceiling", [1, 2])
def test_held_worker_and_short_assignment_obey_resident_ceiling(monkeypatch, ceiling):
    with _service(monkeypatch, ceiling=ceiling, memory=2 * 1024**3) as case:
        gate, _, _ = _submit_gated(case, "long")
        try:
            _eventually(lambda: (gate / "build.started").exists())
            held = _running(case)
            assert len(held) == 1
            short_uri, authority = _submit(case, "short")
            if ceiling == 1:
                assert not _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ?",
                    (short_uri,),
                )
                _release_gate(gate)
            assert (
                case.client.wait("short", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                    (short_uri,),
                )
            )
            from loom.pipeline.stores import LocalArtifactStore

            artifact = (
                authority.list_output_commits(short_uri)[0].artifact_facts[0].artifact
            )
            assert LocalArtifactStore(case.store.local_artifact_root(short_uri)).load(
                artifact
            ) == {"value": 7}
            if ceiling == 2:
                assert _running(case) == held
                offer = json.loads(
                    _eventually(
                        lambda: _rows(
                            case.database,
                            "SELECT offer_json FROM agent_offers WHERE current = 1",
                        )
                    )[0][0]
                )
                assert len(offer["reflected_claim_ids"]) == 1
            _release_gate(gate)
            assert (
                case.client.wait("long", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
        finally:
            _release_gate(gate)


@pytest.mark.parametrize("restart_epoch", [False, True])
def test_restart_admits_short_work_before_known_worker_exits(
    monkeypatch, restart_epoch
):
    from dataclasses import replace
    from loom.pipeline.stores import LocalArtifactStore

    uncertain, queried = Event(), Event()
    original_query = AgentProcessSupervisorClient.query

    def query(owner, launch):
        receipt = original_query(owner, launch)
        if uncertain.is_set():
            queried.set()
            return replace(receipt, state=SupervisorLaunchState.UNKNOWN)
        return receipt

    monkeypatch.setattr(AgentProcessSupervisorClient, "query", query)
    with _service(monkeypatch, ceiling=2, memory=2 * 1024**3) as case:
        gate, _, _ = _submit_gated(case, "long")
        try:
            _eventually(lambda: (gate / "build.started").exists())
            held = _running(case)
            assert len(held) == 1
            original_launch = _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT launch_json FROM launches",
            )
            case.stop.set()
            case.thread.join(20)
            assert not case.thread.is_alive()
            if restart_epoch:
                case.daemon.stop()
                case.daemon.start()
            uncertain.set()
            uri, authority = _submit(case, "short")
            offers = _rows(case.database, "SELECT COUNT(*) FROM agent_offers")
            case.stop.clear()
            case.thread = Thread(target=case.serve)
            case.thread.start()
            assert queried.wait(10)
            assert _rows(case.database, "SELECT COUNT(*) FROM agent_offers") == offers
            assert not _rows(
                case.database,
                "SELECT assignment_id FROM remote_assignments WHERE run_uri = ?",
                (uri,),
            )
            uncertain.clear()
            assert (
                case.client.wait("short", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                    (uri,),
                )
            )
            artifact = authority.list_output_commits(uri)[0].artifact_facts[0].artifact
            assert LocalArtifactStore(case.store.local_artifact_root(uri)).load(
                artifact
            ) == {"value": 7}
            assert _running(case) == held
            owner = AgentProcessSupervisorClient(
                case.agent_root,
                supervisor_module.SupervisorLaunchConfiguration(
                    transport._read_remote_agent_root_id(case.agent_root),
                    tuple(
                        profile.launch_profile
                        for profile in case.config.client.resident_profiles
                    ),
                ),
            )
            launch = supervisor_module._launch_from_value(
                json.loads(original_launch[0][0])
            )
            receipt = owner.query(launch)
            assert receipt.state is SupervisorLaunchState.RUNNING
            assert receipt.launch == launch and receipt.process_id == held[0][2]
            assert original_launch[0] in _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT launch_json FROM launches",
            )
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT COUNT(*) FROM launches WHERE json_extract(launch_json, '$.assignment_id') = ?",
                (held[0][0],),
            ) == [(1,)]

            def remaining():
                offers = _rows(
                    case.database,
                    "SELECT offer_json FROM agent_offers WHERE current = 1",
                )
                if not offers:
                    return None
                offer = json.loads(offers[0][0])
                capacity = transport.AgentOffer.from_value(offer)
                return (
                    offer
                    if capacity.cpu == 1 and capacity.memory_bytes == 1024**3
                    else None
                )

            offer = _eventually(remaining)
            assert len(offer["reflected_claim_ids"]) == 1
            _release_gate(gate)
            assert (
                case.client.wait("long", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
        finally:
            uncertain.clear()
            _release_gate(gate)


def test_restart_accepts_live_starting_operation_before_process_exists(monkeypatch):
    entered, unblock, crashed = Event(), Event(), Event()
    original_spawn = subprocess.Popen
    original_launch = AgentProcessSupervisorClient.launch
    owned = []

    def spawn(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            assert unblock.wait(40)
        process = original_spawn(*args, **kwargs)
        owned.append(process)
        return process

    def launch(client, request):
        if not crashed.is_set():
            client._call("launch", supervisor_module._launch_value(request))
            assert entered.wait(10)
            crashed.set()
            raise RuntimeError("lost accepted launch response")
        return original_launch(client, request)

    with _service(
        monkeypatch, ceiling=2, memory=2 * 1024**3, threaded_supervisor=True
    ) as case:
        monkeypatch.setattr(supervisor_module.subprocess, "Popen", spawn)
        monkeypatch.setattr(AgentProcessSupervisorClient, "launch", launch)
        try:
            _submit(case, "starting")
            assert crashed.wait(20)
            case.thread.join(20)
            assert not case.thread.is_alive(), case.failures
            case.expected_failures.append(RuntimeError)
            launch_row = _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT operation_id, launch_json, state, pid FROM launches",
            )
            assert len(launch_row) == 1 and launch_row[0][2:] == ("starting", None)
            uri, _ = _submit(case, "fresh")
            case.thread = Thread(target=case.serve)
            case.thread.start()
            assert (
                case.client.wait("fresh", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                    (uri,),
                )
            )
            assert launch_row[0] in _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT operation_id, launch_json, state, pid FROM launches",
            )
            unblock.set()
            assert (
                case.client.wait("starting", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT COUNT(*) FROM launches WHERE operation_id = ?",
                (launch_row[0][0],),
            ) == [(1,)]
        finally:
            unblock.set()
    assert owned and all(process.poll() is not None for process in owned)


@pytest.mark.parametrize("gap", ["missing_request", "changed_config"])
def test_restart_does_not_admit_with_unavailable_request_or_changed_config(
    monkeypatch, gap
):
    from dataclasses import replace
    from loom.queue._agent_progress import _cooperative, _steps

    armed, rejected = Event(), Event()
    opening = deployment._open_outbound_agent
    qualify = LocalDaemonAgentHttpClient._qualify_service_admission
    exchange = transport._exchange_agent_request
    attempted = []

    def tracked(config, operation, *args, **kwargs):
        if armed.is_set() and operation in {"offer", "renew", "poll"}:
            attempted.append(operation)
        return exchange(config, operation, *args, **kwargs)

    def changed(config, **kwargs):
        if armed.is_set() and gap == "changed_config":
            try:
                return opening(replace(config, max_concurrent_assignments=1), **kwargs)
            except transport.QueueError:
                rejected.set()
                raise
        return opening(config, **kwargs)

    @_cooperative
    def assessment(client):
        result = yield from _steps(qualify, client)
        if armed.is_set() and not result:
            rejected.set()
        return result

    monkeypatch.setattr(deployment, "_open_outbound_agent", changed)
    monkeypatch.setattr(
        LocalDaemonAgentHttpClient, "_qualify_service_admission", assessment
    )
    monkeypatch.setattr(transport, "_exchange_agent_request", tracked)
    with _service(
        monkeypatch, ceiling=2, memory=2 * 1024**3, shared=gap == "missing_request"
    ) as case:
        gate, _, _ = _submit_gated(case, "long")
        saved = []
        try:
            _eventually(lambda: (gate / "build.started").exists())
            held = _running(case)
            case.stop.set()
            case.thread.join(20)
            assert not case.thread.is_alive()
            if gap == "missing_request":
                raw = json.loads(
                    _rows(
                        case.agent_root / "control.sqlite",
                        "SELECT reference_json FROM agent_session_references WHERE reference_kind = 'delivery' AND resolved = 0",
                    )[0][0]
                )
                for path in (
                    case.agent_root / "assignments" / held[0][0] / "resident.sqlite",
                    case.root / "shared" / raw["location"]["path"],
                ):
                    backup = path.with_name(path.name + ".unavailable")
                    path.rename(backup)
                    saved.append((path, backup))
            armed.set()
            uri, _ = _submit(case, "fresh")
            offers = _rows(case.database, "SELECT COUNT(*) FROM agent_offers")
            case.stop.clear()
            case.thread = Thread(target=case.serve)
            case.thread.start()
            assert rejected.wait(15), (case.failures, case.retries)
            assert _rows(case.database, "SELECT COUNT(*) FROM agent_offers") == offers
            assert not attempted
            assert not _rows(
                case.database,
                "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state != 'BOUND'",
                (uri,),
            )
            assert _running(case) == held
            case.stop.set()
            case.thread.join(20)
            assert not case.thread.is_alive()
            if gap == "changed_config":
                assert len(case.failures) == 1
                assert isinstance(case.failures[0], transport.QueueServiceError)
                assert "configuration" in str(case.failures[0])
                case.expected_failures.append(transport.QueueServiceError)
            for path, backup in saved:
                backup.replace(path)
            saved.clear()
            armed.clear()
            case.stop.clear()
            case.thread = Thread(target=case.serve)
            case.thread.start()
            assert (
                case.client.wait("fresh", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            assert _running(case) == held
            _release_gate(gate)
            assert (
                case.client.wait("long", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
        finally:
            armed.clear()
            _release_gate(gate)
            if saved:
                case.stop.set()
                case.thread.join(20)
                for path, backup in saved:
                    backup.replace(path)


def test_restart_observes_known_b_while_unknown_a_blocks_fresh_admission(monkeypatch):
    from dataclasses import replace

    unknown = Event()
    original_query = AgentProcessSupervisorClient.query
    blocked_id = []

    def query(owner, launch):
        receipt = original_query(owner, launch)
        if unknown.is_set() and launch.assignment_id in blocked_id:
            return replace(receipt, state=SupervisorLaunchState.UNKNOWN)
        return receipt

    monkeypatch.setattr(AgentProcessSupervisorClient, "query", query)
    with _service(monkeypatch, ceiling=2, memory=2 * 1024**3) as case:
        a, _, _ = _submit_gated(case, "a")
        b, b_uri, _ = _submit_gated(case, "b")
        try:
            _eventually(
                lambda: (
                    (a / "build.started").exists() and (b / "build.started").exists()
                )
            )
            original = _running(case)
            assert len(original) == 2
            blocked_id.append(original[0][0])
            # Pick A by its authoritative coordinator run mapping.
            blocked_id[:] = [
                row[0]
                for row in _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri != ?",
                    (b_uri,),
                )
            ]
            case.stop.set()
            case.thread.join(20)
            assert not case.thread.is_alive()
            assert _running(case) == original
            unknown.set()
            fresh_uri, _ = _submit(case, "fresh")
            case.stop.clear()
            case.thread = Thread(target=case.serve)
            case.thread.start()
            _release_gate(b)
            assert (
                case.client.wait("b", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                    (b_uri,),
                )
            )
            assert not _rows(
                case.database,
                "SELECT assignment_id FROM remote_assignments WHERE run_uri = ?",
                (fresh_uri,),
            )
            assert [row for row in _running(case) if row[0] in blocked_id] == [
                row for row in original if row[0] in blocked_id
            ]
            unknown.clear()
            _release_gate(a)
            assert (
                case.client.wait("a", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            assert (
                case.client.wait("fresh", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT COUNT(*) FROM launches",
            ) == [(3,)]
        finally:
            unknown.clear()
            _release_gate(a)
            _release_gate(b)


def test_recovery_rejects_newer_unknown_observation_during_other_owner_query(
    monkeypatch,
):
    from dataclasses import replace
    from loom.queue._agent_progress import _cooperative, _steps, _delay

    armed, driver_waiting, querying_second, applied_unknown, assessed, allow_fresh = (
        Event() for _ in range(6)
    )
    targets, outcomes, attempted = [], [], []
    qualify = LocalDaemonAgentHttpClient._qualify_service_admission
    observe = LocalDaemonAgentHttpClient._observe_supervisor_ownership
    external = transport._external
    exchange = transport._exchange_agent_request

    def observation(client, receipt):
        observe(client, receipt)
        if armed.is_set() and receipt.state is SupervisorLaunchState.UNKNOWN:
            applied_unknown.set()

    def interleave(lane, function, *args, **kwargs):
        if function.__name__ == "query" and targets and not allow_fresh.is_set():
            assignment_id = args[0].assignment_id
            driver = transport._owns_assignment(assignment_id)
            if not driver and assignment_id == targets[1]:

                def held_query():
                    result = function(*args, **kwargs)
                    querying_second.set()
                    assert applied_unknown.wait(15)
                    return result

                return (yield from external(lane, held_query))
            if driver and assignment_id == targets[0]:

                def unknown_query():
                    result = function(*args, **kwargs)
                    driver_waiting.set()
                    assert querying_second.wait(15)
                    return replace(result, state=SupervisorLaunchState.UNKNOWN)

                return (yield from external(lane, unknown_query))
        return (yield from external(lane, function, *args, **kwargs))

    @_cooperative
    def assessment(client):
        if armed.is_set() and not allow_fresh.is_set():
            while len(client._joined_starts) < 2 or assessed.is_set():
                if client._suspend_requested() or allow_fresh.is_set():
                    break
                yield from _delay(0.01)
            if not targets:
                targets.extend(
                    assignment_id
                    for _, assignment_id in client._require_journal().unresolved_assignment_references()
                )
            while not driver_waiting.is_set() and not client._suspend_requested():
                yield from _delay(0.01)
            before = client._admission_inventory()
            result = yield from _steps(qualify, client)
            if applied_unknown.is_set() and not assessed.is_set():
                outcomes.append((result, before == client._admission_inventory()))
                assessed.set()
            return result
        return (yield from _steps(qualify, client))

    def tracked(config, operation, *args, **kwargs):
        if applied_unknown.is_set() and not allow_fresh.is_set():
            if operation in {"offer", "renew", "poll"}:
                attempted.append(operation)
        return exchange(config, operation, *args, **kwargs)

    with _service(monkeypatch, ceiling=3, cpu=3, memory=3 * 1024**3) as case:
        a, _, _ = _submit_gated(case, "a")
        b, _, _ = _submit_gated(case, "b")
        try:
            _eventually(
                lambda: (
                    (a / "build.started").exists() and (b / "build.started").exists()
                )
            )
            original = _running(case)
            case.stop.set()
            case.thread.join(20)
            assert not case.thread.is_alive()
            monkeypatch.setattr(
                LocalDaemonAgentHttpClient, "_qualify_service_admission", assessment
            )
            monkeypatch.setattr(
                LocalDaemonAgentHttpClient, "_observe_supervisor_ownership", observation
            )
            monkeypatch.setattr(transport, "_external", interleave)
            monkeypatch.setattr(transport, "_exchange_agent_request", tracked)
            armed.set()
            case.stop.clear()
            case.thread = Thread(target=case.serve)
            case.thread.start()
            assert assessed.wait(25), (case.failures, case.retries)
            assert outcomes == [(False, True)]
            assert not attempted
            assert _running(case) == original
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT COUNT(*) FROM launches",
            ) == [(2,)]
            # The invalidation is not a permanent ban: a wholly fresh proof can
            # admit spare capacity while both exact original workers remain live.
            allow_fresh.set()
            uri, _ = _submit(case, "fresh")
            assert (
                case.client.wait("fresh", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                    (uri,),
                )
            )
            assert _running(case) == original
        finally:
            allow_fresh.set()
            applied_unknown.set()
            querying_second.set()
            _release_gate(a)
            _release_gate(b)


def test_recovery_rechecks_inventory_after_preparation_completes_during_proof(
    monkeypatch,
):
    from loom.queue._agent_progress import _cooperative, _steps, _delay
    from loom.queue._managed_local import SQLiteAgentJournal

    armed, crashed, collecting, prepared, release, rejected = (
        Event() for _ in range(6)
    )
    changed_snapshots = []
    target = []
    persist = SQLiteAgentJournal.persist_request
    recovery = LocalDaemonAgentHttpClient._resume_retained_assignments
    inventory = LocalDaemonAgentHttpClient._admission_inventory
    qualify = LocalDaemonAgentHttpClient._qualify_service_admission
    prepare = SQLiteAgentJournal.prepare_composite
    external = transport._external

    def interrupt(journal, assignment, request):
        result = persist(journal, assignment, request)
        if armed.is_set() and not crashed.is_set():
            target.append(assignment.assignment_id)
            crashed.set()
            raise RuntimeError("interrupted durable request")
        return result

    @_cooperative
    def recover(client, references, **kwargs):
        if references[0][1] in target:
            while not collecting.is_set() and not kwargs["suspend_requested"]():
                yield from _delay(0.01)
        return (yield from _steps(recovery, client, references, **kwargs))

    def snapshot(client):
        result = inventory(client)
        if target and client._joined_starts:
            changed_snapshots.append(tuple((row[0], row[4]) for row in result[1]))
            collecting.set()
        return result

    def observe(lane, function, *args, **kwargs):
        if (
            function.__name__ == "query"
            and collecting.is_set()
            and not transport._owns_assignment(args[0].assignment_id)
        ):

            def complete():
                result = function(*args, **kwargs)
                assert prepared.wait(15)
                return result

            return (yield from external(lane, complete))
        return (yield from external(lane, function, *args, **kwargs))

    @_cooperative
    def preparing(journal, assignment, *args):
        result = yield from _steps(prepare, journal, assignment, *args)
        if assignment.assignment_id in target:
            prepared.set()
            while not release.is_set():
                yield from _delay(0.01)
        return result

    @_cooperative
    def assessment(client):
        if crashed.is_set():
            while not client._joined_starts and not client._suspend_requested():
                yield from _delay(0.01)
        result = yield from _steps(qualify, client)
        if prepared.is_set() and not release.is_set() and len(changed_snapshots) >= 2:
            assert changed_snapshots[0] != changed_snapshots[-1]
            assert not result
            rejected.set()
        return result

    with _service(monkeypatch, ceiling=3, cpu=3, memory=3 * 1024**3) as case:
        a, _, _ = _submit_gated(case, "a")
        b = None
        try:
            _eventually(lambda: (a / "build.started").exists())
            held = _running(case)
            monkeypatch.setattr(SQLiteAgentJournal, "persist_request", interrupt)
            armed.set()
            b, _, _ = _submit_gated(case, "b")
            assert crashed.wait(20)
            case.thread.join(20)
            assert not case.thread.is_alive()
            case.expected_failures.append(RuntimeError)
            monkeypatch.setattr(
                LocalDaemonAgentHttpClient, "_resume_retained_assignments", recover
            )
            monkeypatch.setattr(
                LocalDaemonAgentHttpClient, "_admission_inventory", snapshot
            )
            monkeypatch.setattr(
                LocalDaemonAgentHttpClient, "_qualify_service_admission", assessment
            )
            monkeypatch.setattr(SQLiteAgentJournal, "prepare_composite", preparing)
            monkeypatch.setattr(transport, "_external", observe)
            case.thread = Thread(target=case.serve)
            case.thread.start()
            assert rejected.wait(20), (case.failures, case.retries, changed_snapshots)
            release.set()
            _eventually(lambda: (b / "build.started").exists())
            uri, _ = _submit(case, "fresh")
            assert (
                case.client.wait("fresh", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                    (uri,),
                )
            )
            assert held[0] in _running(case) and len(_running(case)) == 2
        finally:
            release.set()
            prepared.set()
            collecting.set()
            _release_gate(a)
            if b is not None:
                _release_gate(b)


def test_thirty_two_live_workers_fair_observation_and_five_renewal_cycles(monkeypatch):
    from collections import Counter
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor
    import loom.queue._agent_progress as progress

    pools = []

    class CountedPool(ThreadPoolExecutor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.submissions = []
            self.maximum = 0
            pools.append(self)

        def submit(self, *args, **kwargs):
            self.submissions = [
                future for future in self.submissions if not future.done()
            ]
            future = super().submit(*args, **kwargs)
            self.submissions.append(future)
            self.maximum = max(self.maximum, len(self.submissions))
            assert self.maximum <= self._max_workers
            return future

    monkeypatch.setattr(progress, "ThreadPoolExecutor", CountedPool)
    observed = []
    ever_observed = set()
    collecting = Event()
    query = AgentProcessSupervisorClient.query

    def record(owner, launch):
        receipt = query(owner, launch)
        if receipt.state is SupervisorLaunchState.RUNNING:
            ever_observed.add(launch.assignment_id)
        if collecting.is_set() and receipt.state is SupervisorLaunchState.RUNNING:
            observed.append(launch.assignment_id)
        return receipt

    monkeypatch.setattr(AgentProcessSupervisorClient, "query", record)
    offset = [0.0]
    monkeypatch.setattr(deployment, "monotonic", lambda: monotonic() + offset[0])
    with _service(monkeypatch, ceiling=32, cpu=32, memory=32 * 1024**2) as case:
        gates = []
        try:
            gate, _, _ = _submit_gated(case, "worker-0", memory=1024**2)
            gates.append(gate)
            population, _, _ = _submit_gated(
                case, "population", memory=1024**2, workers=31
            )
            gates.append(population)
            _eventually(
                lambda: (
                    (gate / "build.started").exists()
                    and all(
                        (population / f"build-{index}.started").exists()
                        for index in range(31)
                    )
                ),
                seconds=480,
            )
            held = _running(case)
            assert len(held) == 32
            ids = {row[0] for row in held}
            _eventually(lambda: ever_observed == ids, seconds=30)
            collecting.set()
            _eventually(lambda: set(observed) == ids, seconds=30)
            first_round = observed[
                : next(
                    index + 1
                    for index in range(len(observed))
                    if set(observed[: index + 1]) == ids
                )
            ]
            assert max(Counter(first_round).values()) <= 2
            collecting.clear()
            clock = case.daemon._clock
            baseline = datetime.fromisoformat(clock().replace("Z", "+00:00"))
            monkeypatch.setattr(
                case.daemon,
                "_clock",
                lambda: (
                    (baseline + timedelta(seconds=offset[0]))
                    .isoformat()
                    .replace("+00:00", "Z")
                ),
            )
            for _ in range(10):
                old = _rows(case.database, "SELECT sequence FROM agent_offer_renewals")
                offset[0] += deployment._OUTBOUND_OFFER_TTL_SECONDS / 2
                _eventually(
                    lambda: (
                        _rows(
                            case.database, "SELECT sequence FROM agent_offer_renewals"
                        )
                        != old
                    )
                )
                assert _running(case) == held
            case.client.cancel("worker-0")
            assert (
                case.client.wait("worker-0", timeout_seconds=30).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            _eventually(lambda: len(_running(case)) == 31)
            survivors = _running(case)
            assert all(row in held for row in survivors)
            assert len(survivors) == 31
            for gate in gates:
                _release_gate(gate)
            assert (
                case.client.wait("population", timeout_seconds=180).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: (
                    _rows(
                        case.database,
                        "SELECT COUNT(*) FROM remote_assignments WHERE state = 'RELEASED'",
                    )
                    == [(32,)]
                ),
                seconds=60,
            )
            assert {pool._thread_name_prefix: pool._max_workers for pool in pools} == {
                "loom-agent-bulk": 2,
                "loom-agent-control": 2,
                "loom-agent-poll": 1,
            }
            assert all(pool.maximum <= pool._max_workers for pool in pools)
        finally:
            for gate in gates:
                _release_gate(gate)


def test_gpu_admission_probe_keeps_control_receipt_responsive(monkeypatch):
    entered, unblock, retained = Event(), Event(), Event()
    samples, applied, prepared = [], [], []
    original_apply = GpuOccupancyMonitor._apply_snapshot
    original_control = _RemoteAgentJournal.prepare_assignment_control
    from loom.queue._managed_local import GpuResourceProvider

    original_prepare = GpuResourceProvider._prepare

    def observe(observer):
        samples.append(get_ident())
        if len(samples) == 2:
            entered.set()
            assert unblock.wait(20)
        return {
            "GPU-private": GpuProcessObservation(
                "GPU-private", True, False, "available"
            )
        }

    def apply(monitor, snapshot):
        applied.append(get_ident())
        return original_apply(monitor, snapshot)

    def prepare(provider, command):
        prepared.append(get_ident())
        return original_prepare(provider, command)

    def control(journal, request):
        result = original_control(journal, request)
        if entered.is_set():
            retained.set()
        return result

    monkeypatch.setattr(NvidiaSmiGpuProcessObserver, "observe", observe)
    monkeypatch.setattr(GpuOccupancyMonitor, "_apply_snapshot", apply)
    monkeypatch.setattr(GpuResourceProvider, "_prepare", prepare)
    monkeypatch.setattr(_RemoteAgentJournal, "prepare_assignment_control", control)
    with _service(monkeypatch, gpu=True) as case:
        try:
            uri, _ = _prepare_gpu_environment_run(
                case.store,
                run_name="gpu-admission",
                preferred_models=("model-0",),
                target="agent-a",
                capture_requirement=case.requirement,
            )
            case.client.submit(LocalDaemonAdmissionRequest("gpu-admission", uri))
            assert entered.wait(20), case.failures
            # An offer sample already exists. This second sample is the forced
            # prepare boundary after the journal retained the exact claim intent.
            assert len(samples) == 2
            assert _rows(
                case.agent_root / "journal.sqlite",
                "SELECT state, claims_json IS NOT NULL FROM assignments",
            ) == [("request_durable", 1)]
            case.client.cancel("gpu-admission")
            assert retained.wait(5), case.failures
            assert not prepared
            assert all(thread != case.thread.ident for thread in samples)
            unblock.set()
            assert (
                case.client.wait("gpu-admission", timeout_seconds=30).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE state = 'RELEASED'",
                )
            )
            assert len(samples) == 2  # Applying the fresh facts never probes again.
            assert applied == [case.thread.ident, case.thread.ident]
            assert prepared == [case.thread.ident]
            assert not _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT operation_id FROM launches",
            )
        finally:
            unblock.set()


@pytest.mark.parametrize("ceiling", [1, 2])
@pytest.mark.parametrize("boundary", ["input", "output", "shared_publication"])
def test_serial_service_retains_cancel_while_real_transfer_is_held(
    monkeypatch, ceiling, boundary
):
    entered, unblock, retained = Event(), Event(), Event()
    held = {}
    dispatch = transport._dispatch
    prepare_control = _RemoteAgentJournal.prepare_assignment_control
    exchange = transport._exchange_agent_request
    live_connections = set()
    exchanged = []
    owner_threads = set()

    def held_dispatch(view, operation, value):
        result = dispatch(view, operation, value)
        if operation == boundary and not entered.is_set():
            held.update(value)
            entered.set()
            assert unblock.wait(30)
        return result

    def retain(journal, control):
        owner_threads.add(get_ident())
        result = prepare_control(journal, control)
        if entered.is_set() and control.assignment_id == held["assignment_id"]:
            retained.set()
        return result

    def isolated(config, operation, body, role, connection, keep_alive):
        # Service exchanges create a fresh exclusive connection, even when the
        # bulk peer is still holding an earlier authenticated request.
        assert connection is None
        live_connections.add((get_ident(), operation))
        try:
            if entered.is_set() and not unblock.is_set():
                exchanged.append(operation)
            return exchange(config, operation, body, role, connection, keep_alive)
        finally:
            live_connections.discard((get_ident(), operation))

    monkeypatch.setattr(transport, "_dispatch", held_dispatch)
    monkeypatch.setattr(_RemoteAgentJournal, "prepare_assignment_control", retain)
    monkeypatch.setattr(transport, "_exchange_agent_request", isolated)
    if boundary == "shared_publication":
        from loom.queue import _shared_publication

        original_retain = _shared_publication.retain

        def hold_publication(workspace, result):
            if not entered.is_set():
                held["assignment_id"] = workspace.assignment_id
                entered.set()
                assert unblock.wait(30)
            return original_retain(workspace, result)

        monkeypatch.setattr(_shared_publication, "retain", hold_publication)
    with _service(
        monkeypatch, ceiling=ceiling, shared=boundary == "shared_publication"
    ) as case:
        try:
            _submit(case, "held", sequential=boundary == "input")
            assert entered.wait(20), (
                case.failures,
                case.retries[-4:],
                _rows(
                    case.database, "SELECT state, report_json FROM remote_assignments"
                ),
            )
            later_uri, later_authority = _submit(case, "later")
            case.client.cancel("held")
            assert retained.wait(5), case.failures
            assert "assignment_control" in exchanged
            assert owner_threads == {case.thread.ident}
            offers = _rows(case.database, "SELECT offer_json FROM agent_offers")
            assert all(
                json.loads(row[0]).get("max_concurrent_assignments", 1) == ceiling
                for row in offers
            )
            # A held assignment retains its own slot and claims until release.
            assert not _rows(
                case.database,
                "SELECT assignment_id FROM remote_assignments WHERE state = 'RELEASED' AND assignment_id = ?",
                (held["assignment_id"],),
            )
            if ceiling == 1:
                assert not _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND start_permitted = 1",
                    (later_uri,),
                )
            unblock.set()
            assert (
                case.client.wait("held", timeout_seconds=30).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            assert (
                case.client.wait("later", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            from loom.pipeline.stores import LocalArtifactStore

            artifact = (
                later_authority.list_output_commits(later_uri)[0]
                .artifact_facts[0]
                .artifact
            )
            assert LocalArtifactStore(case.store.local_artifact_root(later_uri)).load(
                artifact
            ) == {"value": 7}
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE assignment_id = ? AND state = 'RELEASED'",
                    (held["assignment_id"],),
                )
            )
            assert not live_connections or case.thread.is_alive()
        finally:
            unblock.set()


@pytest.mark.parametrize("after_permit", [False, True])
def test_cancel_at_permit_boundary_proves_no_start(monkeypatch, after_permit):
    entered, unblock, retained = Event(), Event(), Event()
    original = transport._dispatch
    prepare = _RemoteAgentJournal.prepare_assignment_control

    def dispatch(view, operation, value):
        if operation == "start_permit" and not entered.is_set():
            result = original(view, operation, value) if after_permit else None
            entered.set()
            assert unblock.wait(20)
            return result if after_permit else original(view, operation, value)
        return original(view, operation, value)

    def capture(journal, control):
        result = prepare(journal, control)
        retained.set()
        return result

    monkeypatch.setattr(transport, "_dispatch", dispatch)
    monkeypatch.setattr(_RemoteAgentJournal, "prepare_assignment_control", capture)
    with _service(monkeypatch) as case:
        try:
            _submit(case, "cancelled")
            assert entered.wait(20), case.failures
            case.client.cancel("cancelled")
            assert retained.wait(5), case.failures
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT COUNT(*) FROM launches",
            ) == [(0,)]
            unblock.set()
            assert (
                case.client.wait("cancelled", timeout_seconds=30).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE state = 'RELEASED'",
                )
            )
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT COUNT(*) FROM launches",
            ) == [(0,)]
            if after_permit:
                assert _rows(
                    case.agent_root / "supervisor/supervisor.sqlite",
                    "SELECT COUNT(*) FROM rejected_assignments",
                ) == [(1,)]
        finally:
            unblock.set()


def test_cancel_accepted_starting_keeps_truthful_receipt_until_exact_containment(
    monkeypatch,
):
    entered, unblock, stop_received = Event(), Event(), Event()
    original_spawn = subprocess.Popen
    original_stop = AgentProcessSupervisorClient.request_stop
    spawned = []

    def spawn(*args, **kwargs):
        entered.set()
        assert unblock.wait(20)
        process = original_spawn(*args, **kwargs)
        spawned.append(process)
        return process

    def request_stop(client, launch):
        receipt = original_stop(client, launch)
        if receipt.state is SupervisorLaunchState.STARTING:
            stop_received.set()
        return receipt

    with _service(monkeypatch, threaded_supervisor=True) as case:
        monkeypatch.setattr(supervisor_module.subprocess, "Popen", spawn)
        monkeypatch.setattr(AgentProcessSupervisorClient, "request_stop", request_stop)
        try:
            _submit(case, "starting")
            assert entered.wait(20), case.failures
            case.client.cancel("starting")
            assert stop_received.wait(5), case.failures
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT state, pid FROM launches",
            ) == [("starting", None)]
            assert _rows(
                case.agent_root / "control.sqlite",
                "SELECT result_code FROM remote_assignment_controls_local",
            ) == [(None,)]
            unblock.set()
            terminal = case.client.wait("starting", timeout_seconds=30)
            assert terminal.state is LocalDaemonAdmissionState.CANCELLED
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE state = 'RELEASED'",
                )
            )
            assert len(spawned) == 1
            assert spawned[0].poll() is not None
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT state FROM launches",
            ) == [("contained",)]
        finally:
            unblock.set()


def test_stop_resume_preserves_running_owner_and_conservative_startup(monkeypatch):
    with _service(monkeypatch, ceiling=2) as case:
        uri, _ = _prepare_remote_sleep_run(
            case.store, run_name="running", machine_id="agent-a"
        )
        case.client.submit(LocalDaemonAdmissionRequest("running", uri))
        database = case.agent_root / "supervisor/supervisor.sqlite"
        original = _eventually(
            lambda: _rows(
                database,
                "SELECT operation_id, pid FROM launches WHERE state = 'running'",
            )
        )
        supervisor_pids = _supervisor_process_ids(case.agent_root)
        case.stop.set()
        case.thread.join(10)
        assert not case.thread.is_alive(), case.failures
        assert _supervisor_process_ids(case.agent_root) == supervisor_pids
        assert (
            _rows(
                database,
                "SELECT operation_id, pid FROM launches WHERE state = 'running'",
            )
            == original
        )
        later_uri, _ = _submit(case, "later")
        case.stop.clear()
        case.thread = Thread(target=case.serve)
        case.thread.start()
        case.client.cancel("running")
        assert (
            case.client.wait("running", timeout_seconds=30).state
            is LocalDaemonAdmissionState.CANCELLED
        )
        assert (
            case.client.wait("later", timeout_seconds=30).state
            is LocalDaemonAdmissionState.SUCCEEDED
        )
        _eventually(
            lambda: (
                len(
                    _rows(
                        case.database,
                        "SELECT assignment_id FROM remote_assignments WHERE state = 'RELEASED'",
                    )
                )
                == 2
            )
        )
        assert _rows(
            database,
            "SELECT COUNT(*) FROM launches WHERE operation_id = ?",
            (original[0][0],),
        ) == [(1,)]
        assert _rows(
            case.database,
            "SELECT COUNT(*) FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
            (later_uri,),
        ) == [(1,)]


def test_indeterminate_poll_replays_exact_bytes_before_due_offer_and_next_poll(
    monkeypatch,
):
    entered, unblock, control_progress, replayed = Event(), Event(), Event(), Event()
    original = transport._dispatch
    exchange = transport._exchange_agent_request
    requests = []
    held_request = []
    active_polls = []
    clock_offset = [0.0]
    monkeypatch.setattr(deployment, "monotonic", lambda: monotonic() + clock_offset[0])

    def record(config, operation, body, role, connection, keep_alive):
        requests.append((operation, body))
        return exchange(config, operation, body, role, connection, keep_alive)

    def dispatch(view, operation, value):
        if operation != "poll":
            if operation == "assignment_control" and entered.is_set():
                control_progress.set()
            return original(view, operation, value)
        active_polls.append(value)
        assert len(active_polls) == 1
        try:
            result = original(view, operation, value)
            if not entered.is_set():
                held_request.append(dict(value))
                entered.set()
                assert unblock.wait(20)
                raise ConnectionError("lost response after exact poll committed")
            if dict(value) == held_request[0]:
                replayed.set()
            return result
        finally:
            active_polls.remove(value)

    monkeypatch.setattr(transport, "_exchange_agent_request", record)
    monkeypatch.setattr(transport, "_dispatch", dispatch)
    with _service(monkeypatch) as case:
        try:
            assert entered.wait(10)
            assert control_progress.wait(5)
            first = next(
                index
                for index, (operation, _) in enumerate(requests)
                if operation == "poll"
            )
            assert not any(
                operation in {"offer", "renew"}
                for operation, _ in requests[first + 1 :]
            )
            clock_offset[0] = deployment._OUTBOUND_OFFER_TTL_SECONDS
            unblock.set()
            assert replayed.wait(10), case.failures
            _eventually(
                lambda: len([item for item in requests if item[0] == "poll"]) >= 3
            )
            polls = [
                (index, body)
                for index, (operation, body) in enumerate(requests)
                if operation == "poll"
            ]
            assert polls[0][1] == polls[1][1]
            assert polls[2][1] != polls[1][1]
            assert any(
                operation in {"offer", "renew"}
                for operation, _ in requests[polls[1][0] + 1 : polls[2][0]]
            )
            assert not any(
                operation in {"offer", "renew"}
                for operation, _ in requests[polls[0][0] + 1 : polls[1][0]]
            )
        finally:
            unblock.set()


def test_drain_retains_late_poll_delivery_and_settles_it_without_fresh_admission(
    monkeypatch,
):
    entered, unblock = Event(), Event()
    original = transport._dispatch
    assignment = []

    def dispatch(view, operation, value):
        result = original(view, operation, value)
        if (
            operation == "poll"
            and result.get("result") == "assignment"
            and not entered.is_set()
        ):
            request = result["request"]
            assert isinstance(request, Mapping)
            assignment.append(request["assignment_id"])
            entered.set()
            assert unblock.wait(20)
        return result

    monkeypatch.setattr(transport, "_dispatch", dispatch)
    with _service(monkeypatch, ceiling=2) as case:
        try:
            _submit(case, "late")
            assert entered.wait(20), case.failures
            later_uri, _ = _submit(case, "after-drain")
            session = json.loads(
                _rows(
                    case.agent_root / "control.sqlite",
                    "SELECT value_json FROM agent_sessions_local",
                )[0][0]
            )
            case.operator.control_agent(
                AgentControl(
                    "drain-late",
                    AgentControlKind.DRAIN,
                    "agent-a",
                    session["session_id"],
                    session["config_revision"],
                    None,
                    False,
                    "settle already delivered work",
                )
            )
            unblock.set()
            assert (
                case.client.wait("late", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE assignment_id = ? AND state = 'RELEASED'",
                    (assignment[0],),
                )
            )
            assert not _rows(
                case.database,
                "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND start_permitted = 1",
                (later_uri,),
            )
            assert _rows(
                case.agent_root / "control.sqlite",
                "SELECT value FROM root_metadata WHERE key = 'availability_state'",
            ) == [("drained",)]
        finally:
            unblock.set()


@pytest.mark.parametrize("after_close", [False, True])
def test_control_receipts_survive_lost_reply_from_reconnecting_client(
    monkeypatch, after_close
):
    armed, held, release, reconnecting, closed = (Event() for _ in range(5))
    publishing, release_publication, control_suspended = (Event() for _ in range(3))
    owners = []
    dispatch = transport._dispatch
    complete = _RemoteAgentJournal.complete_offer_renewal
    close = LocalDaemonAgentHttpClient.close
    initialize = LocalDaemonAgentHttpClient.__init__
    receive = LocalDaemonAgentHttpClient._receive_service_controls
    retain = transport._ResidentAssignmentWorkspace.retain_outputs

    def capture_owner(owner, *args, **kwargs):
        initialize(owner, *args, **kwargs)
        owners.append(owner)

    def observe_receive(owner):
        try:
            yield from receive(owner)
        except deployment._ManagedApplicationSuspended:
            control_suspended.set()
            raise

    def hold_publication(workspace):
        if not publishing.is_set():
            publishing.set()
            assert release_publication.wait(60)
        return retain(workspace)

    def lost_control_reply(view, operation, value):
        result = dispatch(view, operation, value)
        if operation == "assignment_control" and armed.is_set() and not held.is_set():
            held.set()
            assert release.wait(30)
            raise ConnectionError("lost control reply from the closing client")
        return result

    def reconnect_after_renewal(journal, renewal, result):
        if held.is_set() and not reconnecting.is_set():
            reconnecting.set()
            raise transport.QueueServiceError("lost renewal application")
        return complete(journal, renewal, result)

    def observe_close(owner):
        close(owner)
        if reconnecting.is_set():
            closed.set()

    monkeypatch.setattr(transport, "_dispatch", lost_control_reply)
    monkeypatch.setattr(
        _RemoteAgentJournal, "complete_offer_renewal", reconnect_after_renewal
    )
    monkeypatch.setattr(LocalDaemonAgentHttpClient, "close", observe_close)
    monkeypatch.setattr(LocalDaemonAgentHttpClient, "__init__", capture_owner)
    monkeypatch.setattr(
        LocalDaemonAgentHttpClient, "_receive_service_controls", observe_receive
    )
    monkeypatch.setattr(
        transport._ResidentAssignmentWorkspace, "retain_outputs", hold_publication
    )
    with _service(monkeypatch, ceiling=2, memory=2 * 1024**3) as case:
        gate, _, _ = _submit_gated(case, "retained")
        try:
            _eventually(lambda: (gate / "build.started").exists())
            original = _running(case)
            _submit(case, "publishing")
            assert publishing.wait(20)
            armed.set()
            assert held.wait(10)
            _eventually(lambda: owners[0]._suspend_requested(), seconds=20)
            if after_close:
                release_publication.set()
                assert closed.wait(10)
            release.set()
            assert control_suspended.wait(10)
            release_publication.set()
            assert closed.wait(10)
            assert _running(case) == original
            case.client.cancel("retained")
            assert (
                case.client.wait("retained", timeout_seconds=15).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            assert (
                case.client.wait("publishing", timeout_seconds=15).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: (
                    _rows(
                        case.database,
                        "SELECT COUNT(*) FROM remote_assignments WHERE state = 'RELEASED'",
                    )
                    == [(2,)]
                )
            )
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT COUNT(*) FROM launches",
            ) == [(2,)]
        finally:
            release.set()
            release_publication.set()
            _release_gate(gate)


def test_lost_release_blocks_new_availability_but_not_control_receipts(monkeypatch):
    entered, unblock, observed = Event(), Event(), Event()
    dispatch = transport._dispatch
    exchange = transport._exchange_agent_request
    requests = []

    def record(config, operation, body, role, connection, keep_alive):
        requests.append((operation, body))
        return exchange(config, operation, body, role, connection, keep_alive)

    def lose_release(view, operation, value):
        result = dispatch(view, operation, value)
        if operation == "release" and not entered.is_set():
            entered.set()
            assert unblock.wait(20)
            raise ConnectionError("release committed but reply was lost")
        if operation == "assignment_control" and entered.is_set():
            observed.set()
        return result

    monkeypatch.setattr(transport, "_exchange_agent_request", record)
    monkeypatch.setattr(transport, "_dispatch", lose_release)
    with _service(monkeypatch, ceiling=2) as case:
        try:
            _submit(case, "first")
            assert entered.wait(20), case.failures
            assert observed.wait(5), case.failures
            _submit(case, "later")
            first = next(
                index
                for index, (operation, _) in enumerate(requests)
                if operation == "release"
            )
            assert not any(
                operation in {"offer", "renew", "poll"}
                for operation, _ in requests[first + 1 :]
            )
            unblock.set()
            assert (
                case.client.wait("later", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: (
                    len(
                        _rows(
                            case.database,
                            "SELECT assignment_id FROM remote_assignments WHERE state = 'RELEASED'",
                        )
                    )
                    == 2
                )
            )
            releases = [
                (index, body)
                for index, (operation, body) in enumerate(requests)
                if operation == "release"
            ]
            assert releases[0][1] == releases[1][1]
            assert not any(
                operation in {"offer", "renew", "poll"}
                for operation, _ in requests[releases[0][0] + 1 : releases[1][0]]
            )
            assert _rows(
                case.agent_root / "journal.sqlite",
                "SELECT COUNT(*) FROM assignments WHERE state != 'released'",
            ) == [(0,)]
        finally:
            unblock.set()


def test_drain_running_publishing_and_late_delivery_settles_entire_population(
    monkeypatch,
):
    publishing, late, release_publication, release_poll = (
        Event(),
        Event(),
        Event(),
        Event(),
    )
    arm_publication, arm_poll = Event(), Event()
    retain = transport._ResidentAssignmentWorkspace.retain_outputs
    dispatch = transport._dispatch

    def publication(workspace):
        if arm_publication.is_set() and not publishing.is_set():
            publishing.set()
            assert release_publication.wait(40)
        return retain(workspace)

    def exchange(view, operation, value):
        result = dispatch(view, operation, value)
        if (
            arm_poll.is_set()
            and operation == "poll"
            and result.get("result") == "assignment"
            and not late.is_set()
        ):
            late.set()
            assert release_poll.wait(30)
        return result

    monkeypatch.setattr(
        transport._ResidentAssignmentWorkspace, "retain_outputs", publication
    )
    monkeypatch.setattr(transport, "_dispatch", exchange)
    with _service(monkeypatch, ceiling=3, cpu=3, memory=3 * 1024**3) as case:
        gate, _, _ = _submit_gated(case, "running")
        try:
            _eventually(lambda: (gate / "build.started").exists())
            arm_publication.set()
            _submit(case, "publishing")
            assert publishing.wait(20)
            arm_poll.set()
            _submit(case, "late")
            assert late.wait(20)
            session = json.loads(
                _rows(
                    case.agent_root / "control.sqlite",
                    "SELECT value_json FROM agent_sessions_local",
                )[0][0]
            )
            case.operator.control_agent(
                AgentControl(
                    "drain-all",
                    AgentControlKind.DRAIN,
                    "agent-a",
                    session["session_id"],
                    session["config_revision"],
                    None,
                    False,
                    "settle every retained assignment",
                )
            )
            fresh_uri, _ = _submit(case, "after-drain")
            release_poll.set()
            _eventually(
                lambda: (
                    _rows(
                        case.agent_root / "control.sqlite",
                        "SELECT value FROM root_metadata WHERE key = 'availability_state'",
                    )
                    == [("drained",)]
                )
            )
            assert (
                len(
                    _rows(case.database, "SELECT assignment_id FROM remote_assignments")
                )
                == 3
            )
            release_publication.set()
            _release_gate(gate)
            for name in ("running", "publishing", "late"):
                assert (
                    case.client.wait(name, timeout_seconds=30).state
                    is LocalDaemonAdmissionState.SUCCEEDED
                )
            _eventually(
                lambda: (
                    _rows(
                        case.database,
                        "SELECT COUNT(*) FROM remote_assignments WHERE state = 'RELEASED'",
                    )
                    == [(3,)]
                )
            )
            assert not _rows(
                case.database,
                "SELECT assignment_id FROM remote_assignments WHERE run_uri = ?",
                (fresh_uri,),
            )
        finally:
            release_poll.set()
            release_publication.set()
            _release_gate(gate)


@pytest.mark.parametrize("restart_epoch", [False, True])
def test_lost_release_orders_other_completion_and_preserves_local_stop(
    monkeypatch, restart_epoch
):
    held, release, committed_b, stopped_c = Event(), Event(), Event(), Event()
    dispatch = transport._dispatch
    stop_request = AgentProcessSupervisorClient.request_stop
    requests = []
    ids = {}

    def exchange(view, operation, value):
        requests.append((operation, dict(value)))
        result = dispatch(view, operation, value)
        if (
            operation == "release"
            and value["assignment_id"] == ids.get("a")
            and not held.is_set()
        ):
            held.set()
            assert release.wait(40)
            raise ConnectionError("lost accepted release")
        if operation == "result" and value["assignment_id"] == ids.get("b"):
            committed_b.set()
        return result

    def request_stop(owner, launch):
        receipt = stop_request(owner, launch)
        if held.is_set() and launch.assignment_id == ids.get("c"):
            stopped_c.set()
        return receipt

    monkeypatch.setattr(transport, "_dispatch", exchange)
    monkeypatch.setattr(AgentProcessSupervisorClient, "request_stop", request_stop)
    offset = [0.0]
    monkeypatch.setattr(deployment, "monotonic", lambda: monotonic() + offset[0])
    with _service(monkeypatch, ceiling=3, cpu=3, memory=3 * 1024**3) as case:
        gates = []
        try:
            for name in ("a", "b", "c"):
                gate, uri, _ = _submit_gated(case, name)
                gates.append(gate)
                _eventually(lambda: (gate / "build.started").exists())
                ids[name] = _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ?",
                    (uri,),
                )[0][0]
            _release_gate(gates[0])
            assert held.wait(20)
            first_release = next(
                index
                for index, (operation, _) in enumerate(requests)
                if operation == "release"
            )
            offset[0] += deployment._OUTBOUND_OFFER_TTL_SECONDS
            _release_gate(gates[1])
            assert committed_b.wait(20)
            case.client.cancel("c")
            assert stopped_c.wait(5)
            assert not any(
                operation in {"release", "offer", "renew", "poll"}
                for operation, _ in requests[first_release + 1 :]
            )
            if restart_epoch:
                case.daemon.stop()
                case.daemon.start()
            release.set()
            for name in ("a", "b"):
                assert (
                    case.client.wait(name, timeout_seconds=30).state
                    is LocalDaemonAdmissionState.SUCCEEDED
                )
            assert (
                case.client.wait("c", timeout_seconds=30).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            _eventually(
                lambda: (
                    _rows(
                        case.database,
                        "SELECT COUNT(*) FROM remote_assignments WHERE state = 'RELEASED'",
                    )
                    == [(3,)]
                )
            )
            releases = [
                value for operation, value in requests if operation == "release"
            ]
            a_releases = [
                value for value in releases if value["assignment_id"] == ids["a"]
            ]
            assert len(a_releases) >= 2 and all(
                value == a_releases[0] for value in a_releases
            )
            local = json.loads(
                _rows(
                    case.agent_root / "control.sqlite",
                    "SELECT value_json FROM agent_sessions_local",
                )[0][0]
            )
            assert _rows(
                case.database,
                "SELECT coordinator_epoch, availability_revision FROM agent_sessions",
            ) == [(local["coordinator_epoch"], local["availability_revision"])]
            if restart_epoch:
                assert (
                    len(
                        {
                            value["idempotency_key"]
                            for operation, value in requests
                            if operation == "reconcile"
                        }
                    )
                    == 1
                )
        finally:
            release.set()
            for gate in gates:
                _release_gate(gate)


def test_workspace_failure_closes_application_and_resumes_exact_delivery(monkeypatch):
    from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace

    original = _ResidentAssignmentWorkspace.stage_input_chunk
    failed = Event()

    def fail_once(workspace, *args, **kwargs):
        if not failed.is_set():
            failed.set()
            raise OSError("fixture input storage unavailable")
        return original(workspace, *args, **kwargs)

    monkeypatch.setattr(_ResidentAssignmentWorkspace, "stage_input_chunk", fail_once)
    with _service(monkeypatch) as case:
        case.expected_failures.append(OSError)
        _submit(case, "recover", sequential=True)
        assert failed.wait(20)
        case.thread.join(10)
        assert not case.thread.is_alive()
        assert (
            len(case.failures) == 1
            and str(case.failures[0]) == "fixture input storage unavailable"
        )
        original_supervisor = _supervisor_process_ids(case.agent_root)
        assert len(original_supervisor) == 1
        case.thread = Thread(target=case.serve)
        case.thread.start()
        assert (
            case.client.wait("recover", timeout_seconds=30).state
            is LocalDaemonAdmissionState.SUCCEEDED
        )
        _eventually(
            lambda: (
                len(
                    _rows(
                        case.database,
                        "SELECT assignment_id FROM remote_assignments WHERE state = 'RELEASED'",
                    )
                )
                == 2
            )
        )
        assert _supervisor_process_ids(case.agent_root) == original_supervisor
        assert _rows(
            case.agent_root / "supervisor/supervisor.sqlite",
            "SELECT COUNT(*) FROM launches",
        ) == [(2,)]


@pytest.mark.parametrize(
    "window", ["before_permit", "after_permit", "starting", "running", "publication"]
)
def test_exact_cancel_windows_preserve_unrelated_running_worker(monkeypatch, window):
    armed, held, release, received = Event(), Event(), Event(), Event()
    dispatch = transport._dispatch
    spawn = subprocess.Popen
    retain = transport._ResidentAssignmentWorkspace.retain_outputs
    prepare = _RemoteAgentJournal.prepare_assignment_control

    def pause():
        held.set()
        assert release.wait(30)

    def exchange(view, operation, value):
        if armed.is_set() and operation == "start_permit" and window == "before_permit":
            pause()
        result = dispatch(view, operation, value)
        if armed.is_set() and operation == "start_permit" and window == "after_permit":
            pause()
        return result

    def launch(*args, **kwargs):
        if armed.is_set() and window == "starting":
            pause()
        return spawn(*args, **kwargs)

    def publication(workspace):
        if armed.is_set() and window == "publication":
            pause()
        return retain(workspace)

    def control(journal, request):
        result = prepare(journal, request)
        if armed.is_set():
            received.set()
        return result

    monkeypatch.setattr(transport, "_dispatch", exchange)
    monkeypatch.setattr(supervisor_module.subprocess, "Popen", launch)
    monkeypatch.setattr(
        transport._ResidentAssignmentWorkspace, "retain_outputs", publication
    )
    monkeypatch.setattr(_RemoteAgentJournal, "prepare_assignment_control", control)
    with _service(
        monkeypatch, ceiling=2, memory=2 * 1024**3, threaded_supervisor=True
    ) as case:
        b, _, _ = _submit_gated(case, "survivor")
        a = None
        try:
            _eventually(lambda: (b / "build.started").exists())
            survivor = _running(case)
            armed.set()
            if window == "running":
                a, _, _ = _submit_gated(case, "cancel")
                _eventually(lambda: (a / "build.started").exists())
            else:
                _submit(case, "cancel")
                assert held.wait(20)
            case.client.cancel("cancel")
            assert received.wait(5)
            release.set()
            assert (
                case.client.wait("cancel", timeout_seconds=30).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            _eventually(lambda: _running(case) == survivor)
            if window in {"before_permit", "after_permit"}:
                assert _rows(
                    case.agent_root / "supervisor/supervisor.sqlite",
                    "SELECT COUNT(*) FROM launches",
                ) == [(1,)]
            armed.clear()
            _release_gate(b)
            assert (
                case.client.wait("survivor", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
        finally:
            armed.clear()
            release.set()
            _release_gate(b)
            if a is not None:
                _release_gate(a)


def test_four_exclusive_devices_mixed_cpu_and_excess_gpu_through_service(monkeypatch):
    monkeypatch.setattr(
        NvidiaSmiGpuProcessObserver,
        "observe",
        lambda owner: {
            f"GPU-private-{index}": GpuProcessObservation(
                f"GPU-private-{index}", True, False, "available"
            )
            for index in range(4)
        },
    )
    with _service(monkeypatch, ceiling=6, cpu=8, memory=8 * 1024**3, gpu=4) as case:
        gates = []
        try:
            for index in range(5):
                gate, _, _ = _submit_gated(case, f"gpu-{index}", gpu=True)
                gates.append(gate)
            cpu_gate, _, _ = _submit_gated(case, "cpu")
            gates.append(cpu_gate)
            _eventually(
                lambda: (
                    all((gate / "build.started").exists() for gate in gates[:4])
                    and (cpu_gate / "build.started").exists()
                ),
                seconds=45,
            )
            assert not (gates[4] / "build.started").exists()
            assert len(_running(case)) == 5
            launches = [
                json.loads(row[0])
                for row in _rows(
                    case.agent_root / "supervisor/supervisor.sqlite",
                    "SELECT launch_json FROM launches WHERE state = 'running'",
                )
            ]
            bindings = [
                launch["environment"]["CUDA_VISIBLE_DEVICES"]
                for launch in launches
                if "CUDA_VISIBLE_DEVICES" in launch["environment"]
            ]
            assert set(bindings) == {f"GPU-private-{index}" for index in range(4)}
            assert len(bindings) == 4
            _release_gate(gates[0])
            _eventually(lambda: (gates[4] / "build.started").exists(), seconds=30)
            assert all((gate / "build.started").exists() for gate in gates)
            for gate in gates:
                _release_gate(gate)
            for name in [*(f"gpu-{index}" for index in range(5)), "cpu"]:
                assert (
                    case.client.wait(name, timeout_seconds=45).state
                    is LocalDaemonAdmissionState.SUCCEEDED
                )
        finally:
            for gate in gates:
                _release_gate(gate)


@pytest.mark.parametrize("shared", [False, True])
def test_two_bulk_holds_preserve_exact_stop_and_unrelated_observation(
    monkeypatch, shared
):
    published, input_held, release = Event(), Event(), Event()
    stopped, observed = Event(), Event()
    from loom.queue import _shared_publication

    publication_owner, publication_name = (
        (_shared_publication, "retain")
        if shared
        else (transport._ResidentAssignmentWorkspace, "retain_outputs")
    )
    retain = getattr(publication_owner, publication_name)
    dispatch = transport._dispatch
    query = AgentProcessSupervisorClient.query
    stop_request = AgentProcessSupervisorClient.request_stop
    armed = Event()
    survivor_ids = []
    from concurrent.futures import ThreadPoolExecutor

    submit = ThreadPoolExecutor.submit
    extra_bulk = []

    def submitted(pool, *args, **kwargs):
        if (
            pool._thread_name_prefix == "loom-agent-bulk"
            and input_held.is_set()
            and not release.is_set()
        ):
            extra_bulk.append(args)
        return submit(pool, *args, **kwargs)

    monkeypatch.setattr(ThreadPoolExecutor, "submit", submitted)

    def hold_publication(workspace, *args):
        if armed.is_set() and not published.is_set():
            published.set()
            assert release.wait(60)
        elif armed.is_set() and shared and not input_held.is_set():
            input_held.set()
            assert release.wait(60)
        return retain(workspace, *args)

    def hold_input(view, operation, value):
        result = dispatch(view, operation, value)
        if operation == "input" and published.is_set() and not input_held.is_set():
            input_held.set()
            assert release.wait(60)
        return result

    def observe(owner, launch):
        receipt = query(owner, launch)
        if (
            input_held.is_set()
            and survivor_ids
            and launch.assignment_id == survivor_ids[-1]
        ):
            observed.set()
        return receipt

    def request_stop(owner, launch):
        receipt = stop_request(owner, launch)
        if input_held.is_set() and launch.assignment_id == survivor_ids[0]:
            stopped.set()
        return receipt

    monkeypatch.setattr(publication_owner, publication_name, hold_publication)
    monkeypatch.setattr(transport, "_dispatch", hold_input)
    monkeypatch.setattr(AgentProcessSupervisorClient, "query", observe)
    monkeypatch.setattr(AgentProcessSupervisorClient, "request_stop", request_stop)
    with _service(
        monkeypatch, ceiling=4, cpu=4, memory=4 * 1024**3, shared=shared
    ) as case:
        c, c_uri, _ = _submit_gated(case, "cancel")
        d, d_uri, _ = _submit_gated(case, "observe")
        try:
            _eventually(
                lambda: (
                    (c / "build.started").exists() and (d / "build.started").exists()
                )
            )
            survivor_ids.extend(
                _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ?",
                    (uri,),
                )[0][0]
                for uri in (c_uri, d_uri)
            )
            armed.set()
            _submit(case, "publishing")
            assert published.wait(20)
            _submit(case, "input", sequential=not shared)
            assert input_held.wait(25)
            case.client.cancel("cancel")
            assert stopped.wait(5)
            assert observed.wait(5)
            assert not extra_bulk
            assert not _rows(
                case.database,
                "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                (c_uri,),
            )
            assert any(row[0] == survivor_ids[1] for row in _running(case))
            release.set()
            assert (
                case.client.wait("cancel", timeout_seconds=30).state
                is LocalDaemonAdmissionState.CANCELLED
            )
            assert (
                case.client.wait("publishing", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            assert (
                case.client.wait("input", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            assert any(row[0] == survivor_ids[1] for row in _running(case))
            _release_gate(d)
            assert (
                case.client.wait("observe", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
        finally:
            release.set()
            _release_gate(c)
            _release_gate(d)


@pytest.mark.parametrize(
    "boundary",
    ["delivery", "prepare", "launch", "publication", "commit", "provider_release"],
)
def test_restart_recovers_every_retained_assignment_at_crash_boundaries(
    monkeypatch, boundary
):
    from loom.queue._agent_progress import _steps, _cooperative
    from loom.queue._managed_local import SQLiteAgentJournal

    armed, crashed = Event(), Event()
    owners = {
        "delivery": (_RemoteAgentJournal, "complete_poll"),
        "prepare": (SQLiteAgentJournal, "prepare_composite"),
        "launch": (AgentProcessSupervisorClient, "launch"),
        "publication": (transport._ResidentAssignmentWorkspace, "retain_outputs"),
        "commit": (LocalDaemonAgentHttpClient, "commit_result"),
        "provider_release": (LocalDaemonAgentHttpClient, "_release_provider_claims"),
    }
    owner, name = owners[boundary]
    original = getattr(owner, name)

    def fail():
        if armed.is_set() and not crashed.is_set():
            crashed.set()
            raise RuntimeError("injected application crash")

    if hasattr(original, "_progress"):

        @_cooperative
        def interrupted(*args, **kwargs):
            result = yield from _steps(original, *args, **kwargs)
            fail()
            return result
    else:

        def interrupted(*args, **kwargs):
            result = original(*args, **kwargs)
            if boundary != "delivery" or args[-1].get("result") == "assignment":
                fail()
            return result

    monkeypatch.setattr(owner, name, interrupted)
    with _service(monkeypatch, ceiling=2, memory=2 * 1024**3) as case:
        gate, _, _ = _submit_gated(case, "survivor")
        try:
            _eventually(lambda: (gate / "build.started").exists())
            held = _running(case)
            armed.set()
            second_uri, _ = _submit(case, "interrupted")
            assert crashed.wait(30)
            case.thread.join(30)
            assert not case.thread.is_alive(), case.failures
            case.expected_failures.append(RuntimeError)
            assert _running(case)[0] in held or any(
                row in held for row in _running(case)
            )
            case.thread = Thread(target=case.serve)
            case.thread.start()
            assert (
                case.client.wait("interrupted", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                    (second_uri,),
                )
            )
            assert any(row in held for row in _running(case))
            fresh_uri, _ = _submit(case, "fresh")
            assert (
                case.client.wait("fresh", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            _eventually(
                lambda: _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                    (fresh_uri,),
                )
            )
            assert any(row in held for row in _running(case))
            _release_gate(gate)
            assert (
                case.client.wait("survivor", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite",
                "SELECT COUNT(*) FROM launches",
            ) == [(3,)]
        finally:
            _release_gate(gate)


@pytest.mark.parametrize(
    "boundary",
    [
        "request",
        "partial_prepare",
        "prepared",
        "activation_unknown",
        "activated",
        "publishing",
        "no_start",
        "committed",
        "partial_release",
        "released",
        "closure",
    ],
)
def test_recovery_population_proof_while_its_driver_is_paused(monkeypatch, boundary):
    from loom.queue._agent_progress import _cooperative, _steps, _delay
    from loom.queue._managed_local import SQLiteAgentJournal, AtomResourceProvider

    crashed, held, resume, assessed = Event(), Event(), Event(), Event()
    outcomes = []
    admission_calls, completed_kinds = [], []
    exchange = transport._exchange_agent_request

    def tracked(config, operation, *args, **kwargs):
        if (
            held.is_set()
            and not resume.is_set()
            and operation in {"offer", "renew", "poll"}
        ):
            admission_calls.append(operation)
        return exchange(config, operation, *args, **kwargs)

    owners = {
        "request": (SQLiteAgentJournal, "persist_request"),
        "partial_prepare": (AtomResourceProvider, "prepare"),
        "prepared": (SQLiteAgentJournal, "prepare_composite"),
        "activation_unknown": (SQLiteAgentJournal, "activate_composite"),
        "activated": (SQLiteAgentJournal, "activate_composite"),
        "publishing": (transport._ResidentAssignmentWorkspace, "retain_outputs"),
        "no_start": (
            transport._ResidentAssignmentWorkspace,
            "persist_failed_before_start",
        ),
        "committed": (LocalDaemonAgentHttpClient, "commit_result"),
        "partial_release": (AtomResourceProvider, "release"),
        "released": (LocalDaemonAgentHttpClient, "_release_provider_claims"),
        "closure": (_RemoteAgentJournal, "complete_assignment_release"),
    }
    owner, name = owners[boundary]
    original = getattr(owner, name)
    recovery = LocalDaemonAgentHttpClient._resume_retained_assignments
    qualify = LocalDaemonAgentHttpClient._qualify_service_admission

    def fail():
        if not crashed.is_set():
            crashed.set()
            if boundary == "partial_prepare":
                raise KeyboardInterrupt("interrupted composite preparation")
            if boundary == "closure":
                case.stop.set()
                raise transport._ManagedApplicationSuspended()
            raise RuntimeError("interrupted retained population")

    if hasattr(original, "_progress"):

        @_cooperative
        def interrupt(*args, **kwargs):
            result = yield from _steps(original, *args, **kwargs)
            fail()
            return result
    else:

        def interrupt(*args, **kwargs):
            if (
                boundary in {"partial_prepare", "partial_release"}
                and args[0].descriptor.kind != "memory"
            ):
                result = original(*args, **kwargs)
                completed_kinds.append(args[0].descriptor.kind)
                return result
            if boundary in {"closure", "partial_prepare", "partial_release"}:
                fail()
            result = original(*args, **kwargs)
            fail()
            return result

    @_cooperative
    def paused(client, references, **kwargs):
        held.set()
        while not resume.is_set() and not kwargs["suspend_requested"]():
            yield from _delay(0.01)
        return (yield from _steps(recovery, client, references, **kwargs))

    @_cooperative
    def observed(client):
        result = yield from _steps(qualify, client)
        if held.is_set() and not resume.is_set():
            outcomes.append(result)
            assessed.set()
        return result

    with _service(monkeypatch, ceiling=2, memory=2 * 1024**3) as case:
        monkeypatch.setattr(owner, name, interrupt)
        if boundary == "activation_unknown":
            from loom.queue._managed_local import ClaimResult, ClaimOutcome

            activate = AtomResourceProvider.activate

            def uncertain(provider, command):
                if provider.descriptor.kind == "memory":
                    return ClaimResult(
                        ClaimOutcome.INDETERMINATE,
                        command.operation_id,
                        command.claim.fingerprint,
                    )
                return activate(provider, command)

            monkeypatch.setattr(AtomResourceProvider, "activate", uncertain)
        if boundary == "no_start":
            environment = transport._worker_environment

            def unavailable(*args, **kwargs):
                if not crashed.is_set():
                    raise OSError("worker environment unavailable before launch")
                return environment(*args, **kwargs)

            monkeypatch.setattr(transport, "_worker_environment", unavailable)
        _submit(case, "retained")
        assert crashed.wait(20), case.failures
        case.thread.join(20)
        assert not case.thread.is_alive()
        if boundary in {"partial_prepare", "partial_release"}:
            assert completed_kinds == ["cpu"]
        if boundary != "closure":
            case.expected_failures.append(
                KeyboardInterrupt if boundary == "partial_prepare" else RuntimeError
            )
        monkeypatch.setattr(
            LocalDaemonAgentHttpClient, "_resume_retained_assignments", paused
        )
        monkeypatch.setattr(
            LocalDaemonAgentHttpClient, "_qualify_service_admission", observed
        )
        monkeypatch.setattr(transport, "_exchange_agent_request", tracked)
        uri, _ = _submit(case, "fresh")
        case.stop.clear()
        case.thread = Thread(target=case.serve)
        case.thread.start()
        try:
            assert held.wait(10)
            assert assessed.wait(10), case.retries
            if boundary in {
                "partial_prepare",
                "activation_unknown",
                "partial_release",
                "released",
                "closure",
            }:
                assert not any(outcomes)
                assert not admission_calls
            else:
                assert any(outcomes)
            if boundary in {
                "request",
                "partial_prepare",
                "prepared",
                "activation_unknown",
                "partial_release",
                "released",
                "closure",
            }:
                # A known pregrant request has no claim to reflect yet. Its
                # existing coordinator target guard still forbids a new target.
                assert not _rows(
                    case.database,
                    "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state != 'BOUND'",
                    (uri,),
                )
            else:
                assert (
                    case.client.wait("fresh", timeout_seconds=30).state
                    is LocalDaemonAdmissionState.SUCCEEDED
                )
                _eventually(
                    lambda: _rows(
                        case.database,
                        "SELECT assignment_id FROM remote_assignments WHERE run_uri = ? AND state = 'RELEASED'",
                        (uri,),
                    )
                )
                assert not resume.is_set()
            if boundary == "activation_unknown":
                assert _rows(
                    case.agent_root / "journal.sqlite", "SELECT state FROM assignments"
                ) == [("activation_unknown",)]
                assert not _rows(
                    case.agent_root / "supervisor/supervisor.sqlite",
                    "SELECT operation_id FROM launches",
                )
                case.stop.set()
                return
            resume.set()
            assert case.client.wait("retained", timeout_seconds=30).state is (
                LocalDaemonAdmissionState.FAILED
                if boundary == "no_start"
                else LocalDaemonAdmissionState.SUCCEEDED
            )
            assert (
                case.client.wait("fresh", timeout_seconds=30).state
                is LocalDaemonAdmissionState.SUCCEEDED
            )
        finally:
            resume.set()
