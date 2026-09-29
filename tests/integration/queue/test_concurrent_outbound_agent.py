"""Serial outbound service progress across actual TLS and supervisor boundaries."""

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
def _service(monkeypatch, *, ceiling=1, threaded_supervisor=False, shared=False):
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
            cpu_capacity=2,
            shared_roots=roots,
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
            agent_resource_provider_factory=ResidentProviderFactory(capacity=2),
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
        finally:
            stop.set()
            case.thread.join(80)
            assert not case.thread.is_alive(), failures
            # Only this fixture's exact supervisor is allowed to contain its
            # retained groups, including assertion-failure and stopped-app paths.
            if _supervisor_process_ids(agent_root) or (
                supervisor_thread is not None and supervisor_thread.is_alive()
            ):
                owner = LocalDaemonAgentHttpClient(client_config)
                try:
                    assert owner._supervisor is not None
                    for (encoded,) in _rows(
                        agent_root / "supervisor/supervisor.sqlite",
                        "SELECT launch_json FROM launches",
                    ):
                        launch = supervisor_module._launch_from_value(
                            json.loads(encoded)
                        )
                        assert (
                            owner._supervisor.contain(launch).state
                            is SupervisorLaunchState.CONTAINED
                        )
                    owner._supervisor.shutdown_for_test()
                finally:
                    owner.close()
            server.stop()
            daemon.stop()
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
    )
    case.client.submit(LocalDaemonAdmissionRequest(name, uri))
    return uri, authority


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
            # The held assignment keeps its slot/claims until ordered settlement;
            # the second run cannot start under either advertised ceiling.
            assert not _rows(
                case.database,
                "SELECT assignment_id FROM remote_assignments WHERE state = 'RELEASED' AND assignment_id = ?",
                (held["assignment_id"],),
            )
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
