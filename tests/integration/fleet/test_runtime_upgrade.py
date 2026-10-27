"""Public maintenance orchestration over actual disposable SSH/native services."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, cast

import pytest

from loom.fleet import upgrades
from loom.fleet.ssh_operations import apply
from loom.fleet._host import read
from loom.coordinator import (
    CoordinatorOperatorClient,
    CoordinatorClient,
    CoordinatorClientError,
)
from tests.integration.fleet.test_ssh_operations import bundle, endpoint, site, write, bind_environments  # noqa: F401

from tests.integration.queue.test_operator_observations import owner as native_owner  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def target_bundle(inventory, tmp_path):
    import yaml

    destination = tmp_path / "candidate"
    shutil.copytree(inventory.runtime_release.parent, destination)
    path = destination / inventory.runtime_release.name
    data = yaml.safe_load(path.read_text())
    data["release_id"] = "candidate-runtime"
    path.write_text(json.dumps(data))
    return path


def finish(inventory, identity, **kwargs):
    deadline = time.monotonic() + 240
    result = upgrades.upgrade(inventory, operation_id=identity, **kwargs)
    while result["outcome"] == "waiting" and time.monotonic() < deadline:
        time.sleep(0.25)
        # A retry awaiting settlement has not yet bound its successor. Replay
        # that exact request until accepted; ordinary resume cannot invent it.
        replay = kwargs if kwargs.get("action") == "retry-check" else {}
        result = upgrades.upgrade(inventory, operation_id=identity, **replay)
    assert result["outcome"] == "complete", json.dumps(result)
    return result


def retry_other_failed_checks(inventory, operation_id, *, keep):
    """A malformed recipe now fails every dispatched slot, not only the first."""
    from tests.integration.fleet.test_self_tests import finish as finish_check

    root = inventory.path.parent
    attempts = read(root / "operations" / operation_id / "checks.json")
    for slot, history in attempts.items():
        failed = history[-1]["operation_id"]
        if failed == keep:
            continue
        # Nonblocking upgrade observation may report one failed slot while
        # another admitted preparation is still running.
        result = finish_check(inventory, failed)
        if result["outcome"] != "failed":
            continue
        successor = failed + "-explicit-retry"
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            upgrades.upgrade(inventory, operation_id=operation_id, action="retry-check",
                             failed_check=failed, new_check=successor)
            current = read(root / "operations" / operation_id / "checks.json")
            if current[slot][-1]["operation_id"] == successor:
                break
            time.sleep(0.05)
        assert current[slot][-1]["operation_id"] == successor
        assert finish_check(inventory, successor)["outcome"] == "passed"


def settle_failed_checks(inventory, operation_id):
    from tests.integration.fleet.test_self_tests import finish as finish_check

    directory = inventory.path.parent / "operations" / operation_id
    for rows in read(directory / "checks.json").values():
        assert finish_check(inventory, rows[-1]["operation_id"])["outcome"] == "failed"
    connection = read(directory / "intent.json")["check_selection"]["operator_connection"]
    with CoordinatorOperatorClient.from_connection_file(connection) as operator:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if operator.observe_maintenance()["settled"]:
                return
            time.sleep(0.05)
    pytest.fail("failed native checks did not release their claims")



def held_progress_cli(inventory, identity, options, monkeypatch):
    """Observe the real CLI/native call while a selected SSH boundary is held."""
    import io
    import threading
    from loom.cli.main import main

    held, release, heartbeat = threading.Event(), threading.Event(), threading.Event()
    host_call = upgrades.sshops.ssh
    records = []
    class Stream(io.StringIO):
        def write(self, value):
            record = json.loads(value)
            records.append(record)
            if record["event"] == "heartbeat" and held.is_set():
                heartbeat.set()
            return super().write(value)
    def hold(host, request):
        if not held.is_set() and request["action"] == "inspect":
            held.set()
            assert release.wait(20)
        return host_call(host, request)
    output, error = io.StringIO(), Stream()
    args = ["fleet", "upgrade", "--fleet", str(inventory.path), "--apply",
            "--operation-id", identity, "--progress", "json", "--format", "json"]
    for key, value in options.items():
        args.extend(["--" + key.replace("_", "-"), str(value)])
    codes = []
    with monkeypatch.context() as patch:
        patch.setattr(upgrades.sshops, "ssh", hold)
        worker = threading.Thread(target=lambda: codes.append(main(args, stdout=output, stderr=error)))
        worker.start()
        try:
            assert held.wait(30)
            assert heartbeat.wait(7)
            assert not codes
            assert output.getvalue() == ""
            observed = records[-1]
            assert observed["phase"] == "preparing"
            assert observed["elapsed_seconds"] >= 4.9
            assert observed["preparation_seconds"] >= 4.9
            assert observed["admission_closed_seconds"] is None
            assert any(row["event"] == "phase" for row in records)
        finally:
            release.set()
            worker.join(240)
        assert not worker.is_alive()
    result = json.loads(output.getvalue())
    assert codes == [0 if result["outcome"] == "complete" else 2 if result["outcome"] == "waiting" else 1]
    assert records[-1]["event"] == "result"
    assert str(inventory.path) not in error.getvalue()
    return result


def test_runtime_upgrade_abort_interruption_resume_and_native_checks(
    site,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    inventory, base, selection = site
    inventory = bind_environments(inventory)
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    write(inventory.hosts[0].config, authored)
    setup = apply(
        inventory,
        operation_id="setup-upgrade",
        issuer=base / "issuer",
        check_selection=selection,
    )
    assert setup["outcome"] == "complete", setup
    target = target_bundle(inventory, tmp_path)
    original_source = tmp_path / "projects" / "pipeline.yaml"
    source_bytes = original_source.read_bytes()
    options = {
        "runtime_release": target,
        "deployment": Path(setup["deployment"]),
        "connection": Path(setup["operator_connection"]),
        "config": selection["config"],
    }
    preview = upgrades.preview(inventory, **options)
    assert preview["outcome"] == "preview"
    assert preview["gate"]["state"] == "open"
    assert preview["source"]["owner"] == setup["identities"]["coordinator"]
    # Invalid preparation refuses while the old services and admission remain usable.
    original_source.write_text("pipeline: [invalid")
    incompatible = upgrades.upgrade(
        inventory, operation_id="incompatible-preflight", apply=True, **options
    )
    assert incompatible["outcome"] == "blocked", incompatible
    assert "candidate preparation is incompatible" in incompatible["reason"]
    directory = upgrades.sshops._directory(inventory, "incompatible-preflight")
    assert not (directory / "steps/close/intent.json").exists()
    assert not (directory / "irreversible.json").exists()
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        assert operator.observe_maintenance()["state"] == "open"
    original_source.write_bytes(source_bytes)
    assert upgrades.upgrade(inventory, operation_id="incompatible-preflight", action="abort")["outcome"] == "aborted"
    # A lost controller before closure retains candidate evidence but no native gate.
    probes = upgrades._Upgrade.probes

    def before_closure(operation):
        probes(operation)
        raise upgrades._Waiting("interrupted before gate closure")

    monkeypatch.setattr(upgrades._Upgrade, "probes", before_closure)
    interrupted = held_progress_cli(inventory, "before-window", options, monkeypatch)
    assert interrupted["outcome"] == "waiting"
    assert (
        upgrades.upgrade(inventory, operation_id="before-window", action="abort")[
            "outcome"
        ]
        == "aborted"
    )
    monkeypatch.setattr(upgrades._Upgrade, "probes", probes)
    native = upgrades._Upgrade.native
    dropped = []

    def interrupt(self, key, request, invoke):
        result = native(self, key, request, invoke)
        if key == "close" and not dropped:
            if self.intent["operation_id"] == "upgrade-window":
                original_source.write_text("pipeline: [invalid")
            dropped.append(request["operation_id"])
            raise upgrades.sshops.SshUnavailable("lost accepted close reply")
        return result

    monkeypatch.setattr(upgrades._Upgrade, "native", interrupt)
    observations = []
    result = upgrades.upgrade(
        inventory, operation_id="abort-window", apply=True, progress=observations.append, **options
    )
    assert observations[-1]["phase"] == "closing_admission"
    assert observations[-1]["reason_code"] == "host_unavailable"
    assert observations[-1]["admission_closed_seconds"] is None
    assert result["outcome"] == "waiting", result
    result = upgrades.upgrade(inventory, operation_id="abort-window", action="abort")
    assert result["outcome"] == "aborted", result
    with CoordinatorOperatorClient.from_connection_file(
        setup["operator_connection"]
    ) as operator:
        assert operator.observe_maintenance()["state"] == "open"
    dropped.clear()
    host_calls = upgrades.sshops.ssh
    migrations = []

    def lost_migration(host, request):
        result = host_calls(host, request)
        if request["action"] == "upgrade-replace" and request["name"] == "coordinator":
            migrations.append(request["request_id"])
            if len(migrations) == 1:
                raise upgrades.sshops.SshUnavailable(
                    "lost native migration/replacement receipt"
                )
        return result

    monkeypatch.setattr(upgrades.sshops, "ssh", lost_migration)
    call = upgrades._Upgrade.call
    first_stop = []

    def lost_stop_intent(operation, name, action, **kwargs):
        if action == "upgrade-stop" and not first_stop:
            first_stop.append(True)
            raise upgrades._Waiting("interrupted after irreversible intent")
        return call(operation, name, action, **kwargs)

    monkeypatch.setattr(upgrades._Upgrade, "call", lost_stop_intent)
    result = upgrades.upgrade(
        inventory, operation_id="upgrade-window", apply=True, **options
    )
    assert result["outcome"] == "waiting"
    deadline = time.monotonic() + 240
    checked_irreversible = False
    while result["outcome"] == "waiting" and time.monotonic() < deadline:
        if first_stop and not checked_irreversible:
            refused = upgrades.upgrade(
                inventory, operation_id="upgrade-window", action="abort"
            )
            assert (
                refused["outcome"] == "blocked" and "irreversible" in refused["reason"]
            )
            checked_irreversible = True
        result = upgrades.upgrade(inventory, operation_id="upgrade-window")
    assert (
        result["outcome"] == "blocked"
        and "explicit operation retry-check" in result["reason"]
    ), result
    settle_failed_checks(inventory, "upgrade-window")
    attempts = read(inventory.path.parent / "operations/upgrade-window/checks.json")
    failed = attempts["worker:cpu"][-1]["operation_id"]
    retained_failure = read(inventory.path.parent / "checks" / failed / "result.json")
    assert retained_failure["outcome"] == "failed"
    wrong_owner = upgrades.upgrade(
        inventory,
        operation_id="upgrade-window",
        action="retry-check",
        failed_check="another-maintenance-check",
        new_check="wrong-owner-successor",
    )
    assert (
        wrong_owner["outcome"] == "blocked"
        and "maintenance owner" in wrong_owner["reason"]
    )
    target_bytes = target.read_bytes()
    target.write_bytes(target_bytes + b"\n")
    changed_target = upgrades.upgrade(
        inventory,
        operation_id="upgrade-window",
        action="retry-check",
        failed_check=failed,
        new_check="changed-target-successor",
    )
    assert changed_target["outcome"] == "blocked"
    assert not (inventory.path.parent / "checks/changed-target-successor").exists()
    target.write_bytes(target_bytes)
    original_source.write_bytes(source_bytes)
    repeated_failure = upgrades.upgrade(inventory, operation_id="upgrade-window")
    assert repeated_failure["outcome"] == "blocked"
    retry_other_failed_checks(inventory, "upgrade-window", keep=failed)
    submit = CoordinatorClient.start_run
    submitted = []

    def lost_check(client, request, **kwargs):
        result = submit(client, request, **kwargs)
        if request.preparation.operation_id == "replacement-check":
            submitted.append(request.preparation.operation_id)
            if len(submitted) == 1:
                raise CoordinatorClientError(
                    "unavailable",
                    boundary="transport",
                    operation="start_run",
                    mutation_outcome="unknown",
                )
        return result

    monkeypatch.setattr(CoordinatorClient, "start_run", lost_check)
    replacement = upgrades.upgrade(
        inventory,
        operation_id="upgrade-window",
        action="retry-check",
        failed_check=failed,
        new_check="replacement-check",
    )
    deadline = time.monotonic() + 120
    while (
        read(inventory.path.parent / "operations/upgrade-window/checks.json")[
            "worker:cpu"
        ][-1]["operation_id"]
        != "replacement-check"
        and replacement["outcome"] == "waiting"
        and time.monotonic() < deadline
    ):
        replacement = upgrades.upgrade(
            inventory,
            operation_id="upgrade-window",
            action="retry-check",
            failed_check=failed,
            new_check="replacement-check",
        )
    # Dispatch and observation are separate passes. The lost submission reply
    # can already be reconciled by observation in this same continuation.
    assert replacement["outcome"] in {"waiting", "complete"}, replacement
    assert (
        read(inventory.path.parent / "operations/upgrade-window/checks.json")[
            "worker:cpu"
        ][-1]["operation_id"]
        == "replacement-check"
    )
    duplicate = upgrades.upgrade(
        inventory,
        operation_id="upgrade-window",
        action="retry-check",
        failed_check=failed,
        new_check="different-successor",
    )
    assert duplicate["outcome"] == "blocked" and "successor" in duplicate["reason"]
    result = finish(inventory, "upgrade-window")
    replayed_retry = upgrades.upgrade(
        inventory,
        operation_id="upgrade-window",
        action="retry-check",
        failed_check=failed,
        new_check="replacement-check",
    )
    assert replayed_retry["outcome"] == "complete"
    assert replayed_retry["checks"] == result["checks"]
    assert checked_irreversible
    assert len(migrations) == 1 and submitted == ["replacement-check"]
    assert (
        read(inventory.path.parent / "checks" / failed / "result.json")
        == retained_failure
    )
    assert [row["operation_id"] for row in result["checks"]["worker:cpu"]] == [
        failed,
        "replacement-check",
    ]
    assert result["release"]["release_id"] == "candidate-runtime"
    repeat = upgrades.upgrade(inventory, operation_id="upgrade-window")
    assert repeat["checks"] == result["checks"]
    from loom.cli.main import main

    capsys.readouterr()
    assert (
        main(
            [
                "fleet",
                "operation",
                "status",
                "upgrade-window",
                "--fleet",
                str(inventory.path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["outcome"] == "complete"

    with CoordinatorOperatorClient.from_connection_file(
        setup["operator_connection"]
    ) as operator:
        assert operator.observe_maintenance()["state"] == "open"
        assert operator.observe_maintenance()["checks"] == {}
        current = operator.observe_agent("worker")
        assert (
            current.value["agent_root_id"]
            == preview["agents"]["worker"]["agent_root_id"]
        )
        assert current.value["session_id"] == preview["agents"]["worker"]["session_id"]
        assert current.value["drained"] is False
    for rows in result["checks"].values():
        identity = rows[-1]["operation_id"]
        check = read(inventory.path.parent / "checks" / identity / "result.json")
        assert check["outcome"] == "passed"
        assert all(
            fact["assignment"]["value"]["released"]
            for fact in check["checks"].values()
            if fact["outcome"] != "not_requested"
        )


@pytest.mark.parametrize(
    "missing", ["maintenance-admission-v1", "conditional-agent-control-v1"]
)
def test_source_capability_refuses_even_with_capable_operator(
    native_owner,  # noqa: F811
    monkeypatch,
    missing,
):
    from dataclasses import replace
    from loom.queue import LocalDaemonSocketServer
    from loom.queue import operations
    from loom.queue.errors import QueueConflictError

    daemon, _, _, _ = native_owner
    observed = operations._coordinator_observation

    def incapable(source):
        fact = observed(source)
        return replace(
            fact,
            value={
                **fact.value,
                "capabilities": [
                    cap
                    for cap in cast(list[str], fact.value["capabilities"])
                    if cap != missing
                ],
            },
        )

    monkeypatch.setattr(operations, "_coordinator_observation", incapable)
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    server.start()
    try:
        with CoordinatorOperatorClient.from_unix_socket(
            daemon.config.endpoint,
            expected_coordinator_id=daemon.status().coordinator_id,
        ) as operator:
            with pytest.raises(QueueConflictError, match="unsupported_capability"):
                upgrades._capable(operator)
            assert operator.observe_maintenance()["state"] == "open"
    finally:
        server.stop()


def independent_policy(operator, name, identity, kind):
    from loom.queue.agent_sessions import AgentControl, AgentControlKind

    current = operator.observe_agent(name).value
    operator.control_agent(
        AgentControl(
            identity,
            AgentControlKind(kind),
            name,
            current["session_id"],
            current["config_revision"],
            None,
            False,
            "independent administrator",
        )
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = operator.observe_control(identity)
        if result["state"] == "applied" and result["acknowledged"]:
            return
        assert result["state"] != "failed", result
        time.sleep(0.1)
    pytest.fail("independent native policy did not settle")


@pytest.mark.parametrize("boundary", ["abort", "restore"])
def test_upgrade_restoration_preserves_intervening_applied_drain(
    site,  # noqa: F811
    tmp_path,
    monkeypatch,
    boundary,
):
    inventory, base, selection = site
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    write(inventory.hosts[0].config, authored)
    setup = apply(
        inventory,
        operation_id="setup-race",
        issuer=base / "issuer",
        check_selection=selection,
    )
    assert setup["outcome"] == "complete", setup
    options = {
        "runtime_release": target_bundle(inventory, tmp_path),
        "deployment": Path(setup["deployment"]),
        "connection": Path(setup["operator_connection"]),
        "config": selection["config"],
    }
    original = upgrades._Upgrade.policy
    injected = []
    with CoordinatorOperatorClient.from_connection_file(
        setup["operator_connection"]
    ) as operator:
        if boundary == "restore":
            independent_policy(operator, "worker", "original-admin-drain", "drain")

        def intervene(operation, name, key, kind, predecessor):
            if boundary == "restore" and key == "worker-restore" and not injected:
                independent_policy(operator, name, "independent-admin-drain", "drain")
                injected.append(True)
            result = original(operation, name, key, kind, predecessor)
            if boundary == "abort" and key == "worker-drain" and not injected:
                independent_policy(operator, name, "independent-admin-drain", "drain")
                injected.append(True)
                raise upgrades._Waiting("controller interruption after owned drain")
            return result

        monkeypatch.setattr(upgrades._Upgrade, "policy", intervene)
        result = upgrades.upgrade(
            inventory, operation_id="policy-race", apply=True, **options
        )
        deadline = time.monotonic() + 300
        while (
            result["outcome"] == "waiting"
            and not injected
            and time.monotonic() < deadline
        ):
            result = upgrades.upgrade(inventory, operation_id="policy-race")
        assert injected, result
        if boundary == "abort":
            assert not (
                inventory.path.parent / "operations/policy-race/irreversible.json"
            ).exists()
            result = upgrades.upgrade(
                inventory, operation_id="policy-race", action="abort"
            )
        assert result["outcome"] == "blocked", result
        assert operator.observe_maintenance()["state"] == "closed"
        current = cast(dict[str, Any], operator.observe_agent("worker").value)
        assert current["control"]["operation_id"] == "independent-admin-drain"
        assert current["drained"] is True
        with pytest.raises(CoordinatorClientError) as refused:
            operator.observe_control(
                "policy-race-worker-"
                + ("abort-restore" if boundary == "abort" else "restore")
            )
        assert refused.value.code == "not_found"


def test_finished_worker_with_retained_publication_prevents_settlement(monkeypatch):
    from threading import Event
    from loom.queue import _shared_publication
    from loom.queue.service_upgrade import inspect_service_settlement
    from tests.integration.queue.test_concurrent_outbound_agent import (
        _service,
        _submit,
        _eventually,
    )

    entered, release = Event(), Event()
    retain = _shared_publication.retain

    def hold(workspace, result):
        entered.set()
        assert release.wait(30)
        return retain(workspace, result)

    monkeypatch.setattr(_shared_publication, "retain", hold)
    with _service(monkeypatch, shared=True) as case:
        try:
            _submit(case, "publication-check")
            assert entered.wait(20), case.failures
            # The worker result exists, but publication and its claim still have
            # a native owner. Neither a CPU reading nor terminal work is release.
            gate = case.operator.observe_maintenance()
            assert gate["settled"] is False
            assert "accepted_work_or_preparation" in gate["wait_reasons"]
            fact = inspect_service_settlement(
                case.daemon.config.coordinator_root,
                expected_root_id=case.daemon.status().coordinator_id,
            )
            assert fact.availability == "available" and fact.value["settled"] is False
            release.set()
            assert (
                case.client.wait("publication-check", timeout_seconds=30).state.value
                == "SUCCEEDED"
            )
            _eventually(lambda: case.operator.observe_maintenance()["settled"])
        finally:
            release.set()


@pytest.mark.parametrize("case", ["older", "capability", "wheel"])
def test_candidate_probe_refuses_before_native_mutation(tmp_path, case):
    from loom.fleet._upgrade_host import inspect
    from loom.fleet.releases import verify_release
    from loom.queue.errors import QueueConfigError, QueueConflictError
    from loom.queue.operations import inspect_native_service
    from tests.unit.loom.queue.test_current_storage import current_config
    from tests.integration.fleet.test_releases import bundle as release_bundle

    config = current_config(tmp_path)
    if case == "older":
        with sqlite3.connect(config.control_database) as conn:
            conn.execute("PRAGMA user_version = 18")
    descriptor = release_bundle(tmp_path / "candidate")
    release = verify_release(descriptor)
    installed = tmp_path / "admin/releases" / release["descriptor_sha256"] / "bundle"
    shutil.copytree(descriptor.parent, installed)
    before = config.control_database.read_bytes()
    if case == "wheel":
        next((installed / "wheels").iterdir()).write_bytes(b"changed wheel")
    required: list[str] = list(upgrades.REQUIRED_CAPABILITIES)
    if case == "capability":
        required.append("unavailable-required-capability")
    request = {
        "admin": str(tmp_path / "admin"),
        "root": str(config.deployment_root),
        "name": "coordinator",
        "release": release,
        "descriptor_name": descriptor.name,
        "required_capabilities": required,
        "expected_root_id": inspect_native_service(config.coordinator_root).owner,
    }
    expected = {
        "older": "unsupported_storage_version",
        "capability": "unsupported_capability",
        "wheel": "changed",
    }[case]
    with pytest.raises((QueueConfigError, QueueConflictError), match=expected):
        inspect(request)
    assert config.control_database.read_bytes() == before
    assert not list(config.coordinator_root.glob("*.backup"))


def test_abort_reopens_while_admitted_pipeline_remains_active(
    site,  # noqa: F811
    tmp_path,
    capsys,
):
    from loom.cli.main import main
    from loom.coordinator import RunRequest
    from loom.deployment import load_deployment
    from loom.queue.preparation import PrepareRunRequest

    inventory, base, selection = site
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    barrier = tmp_path / "outputs/active-work"
    barrier.mkdir()
    location = {
        "kind": "loom.shared-location",
        "schema_version": 1,
        "root_id": "outputs",
        "path": "active-work",
    }
    for profile in authored["preparation"]["profiles"].values():
        profile["shared_locations"] = [location]
    write(inventory.hosts[0].config, authored)
    setup = apply(
        inventory,
        operation_id="setup-active-abort",
        issuer=base / "issuer",
        check_selection=selection,
    )
    assert setup["outcome"] == "complete", setup
    source = tmp_path / "projects/pipeline.yaml"
    pipeline = json.loads(source.read_text())
    stage = pipeline["pipeline"]["stages"][0]
    stage["factory"] = {
        "_target_": "tests.support.pipeline_execution_stages.ReleaseStage"
    }
    stage["config"] = {"marker_dir": location, "timeout_seconds": 180}
    write(source, pipeline)
    deployment = load_deployment(setup["deployment"])
    assert deployment.connection is not None
    request = RunRequest(
        PrepareRunRequest(
            "admitted-work",
            "admitted-work",
            deployment.source,
            selection["config"],
            deployment.preparation_profile,
        ),
        "admitted-work",
    )
    with (
        CoordinatorClient.from_connection_file(deployment.connection) as client,
        CoordinatorOperatorClient.from_connection_file(
            setup["operator_connection"]
        ) as operator,
    ):
        client.start_run(request)
        try:
            deadline = time.monotonic() + 30
            while not (barrier / "produce.started").exists():
                assert time.monotonic() < deadline, client.observe_run(
                    "admitted-work", wait=False
                )
                time.sleep(0.05)
            active = client.observe_run("admitted-work", wait=False).admission
            assert active is not None and active.state.value == "ACTIVE"
            original_control = operator.observe_agent("worker").value["control"]
            result = upgrades.upgrade(
                inventory,
                operation_id="abort-active-work",
                apply=True,
                runtime_release=target_bundle(inventory, tmp_path),
                deployment=Path(setup["deployment"]),
                connection=Path(setup["operator_connection"]),
                config=selection["config"],
            )
            assert (
                result["outcome"] == "waiting"
                and "accepted_work_or_preparation" in result["reason"]
            )
            assert operator.observe_maintenance()["state"] == "closed"
            directory = inventory.path.parent / "operations/abort-active-work"
            assert not (directory / "irreversible.json").exists()
            assert not (directory / "steps/worker-drain/intent.json").exists()
            capsys.readouterr()
            assert (
                main(
                    [
                        "fleet",
                        "operation",
                        "abort",
                        "abort-active-work",
                        "--fleet",
                        str(inventory.path),
                        "--format",
                        "json",
                    ]
                )
                == 0
            )
            assert json.loads(capsys.readouterr().out)["outcome"] == "aborted"
            gate = operator.observe_maintenance()
            assert (
                gate["state"] == "open"
                and gate["checks"] == {}
                and gate["settled"] is False
            )
            assert operator.observe_agent("worker").value["control"] == original_control
            continuing = client.observe_run("admitted-work", wait=False).admission
            assert continuing is not None and continuing.state.value == "ACTIVE"
            assert continuing.admission_id == active.admission_id
            assert not (barrier / "release").exists()
        finally:
            (barrier / "release").touch()
            completed = client.observe_run(
                "admitted-work", timeout_seconds=30
            ).admission
            assert completed is not None and completed.state.value == "SUCCEEDED"


def test_runtime_recovery_mode_preserves_empty_cohort_and_native_checks(
    site, tmp_path,  # noqa: F811
):
    inventory, base, selection = site
    inventory = bind_environments(inventory)
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    write(inventory.hosts[0].config, authored)
    setup = apply(
        inventory, operation_id="setup-recovery", issuer=base / "issuer",
        check_selection=selection,
    )
    assert setup["outcome"] == "complete", setup
    target = target_bundle(inventory, tmp_path)
    options = {
        "runtime_release": target, "recover_retained_results": True,
        "deployment": Path(setup["deployment"]),
        "connection": Path(setup["operator_connection"]),
        "config": selection["config"],
    }
    preview = upgrades.preview(inventory, **options)
    assert preview["recover_retained_results"] is True
    result = finish(inventory, "recover-empty", apply=True, **options)
    assert result["outcome"] == "complete", result
    directory = upgrades.sshops._directory(inventory, "recover-empty")
    assert read(directory / "retained-results.json") == {"results": []}
    assert read(directory / "intent.json")["recover_retained_results"] is True
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        assert operator.observe_maintenance()["state"] == "open"
        assert not operator.observe_agent("worker").value["drained"]


def broken_metadata_release(inventory, tmp_path, *, preparation_barrier=None):
    """Build a disposable source runtime reproducing the pre-fix wire defect."""
    import base64
    import csv
    import hashlib
    import io
    import zipfile
    from tests.integration.fleet.test_ssh_operations import sha
    from loom.fleet.configuration import load_inventory

    root = tmp_path / "broken-runtime"
    shutil.copytree(inventory.runtime_release.parent, root)
    wheel = next((root / "wheels").glob("loom-*.whl"))
    before = sha(wheel)
    with zipfile.ZipFile(wheel) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    if preparation_barrier is None:
        codec = "loom/queue/_agent_session_codec.py"
        old = b'max_collection=_MAX_BODY_BYTES)'
        assert files[codec].count(old) == 1
        files[codec] = files[codec].replace(old, b"max_collection=_MAX_JSON_COLLECTION)")
    else:
        codec = "loom/queue/agent_sessions.py"
        old = b'        if report.assignment_id != assignment_id:\n'
        assert files[codec].count(old) == 1
        fault = (
            f'        if report.stage_name == "prepare" and Path({str(preparation_barrier)!r}).exists():\n'
            '            raise QueueConflictError("injected preparation result communication defect")\n'
        ).encode()
        files[codec] = files[codec].replace(old, fault + old)
        recovery = "loom/queue/service_upgrade.py"
        old = b'preparations, children = _recoverable_preparations(conn, results)'
        assert files[recovery].count(old) == 1
        files[recovery] = files[recovery].replace(old, b'preparations, children = frozenset(), frozenset()')
    record = next(name for name in files if name.endswith(".dist-info/RECORD"))
    stream = io.StringIO()
    writer = csv.writer(stream)
    for name, content in sorted(files.items()):
        if name != record:
            writer.writerow((name, "sha256=" + base64.urlsafe_b64encode(
                hashlib.sha256(content).digest()).decode().rstrip("="), len(content)))
    writer.writerow((record, "", ""))
    files[record] = stream.getvalue().encode()
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    descriptor = root / inventory.runtime_release.name
    value = read(descriptor)
    for entry in (value["requirements"], value["wheelhouse"]):
        path = root / entry.get("manifest", entry["path"])
        path.write_text(path.read_text().replace(before, sha(wheel)))
        entry["sha256"] = sha(path)
    value["release_id"] = "broken-output-metadata"
    write(descriptor, value)
    authored = read(inventory.path)
    authored["runtime_release"] = str(descriptor)
    write(inventory.path, authored)
    return load_inventory(inventory.path)


def test_runtime_candidate_repair_recovers_cancelled_preparation(
    site, tmp_path, monkeypatch, capsys,  # noqa: F811
):
    from loom.cli.main import main
    from loom.coordinator import RunRequest
    from loom.deployment import load_deployment
    from loom.queue.preparation import PrepareRunRequest
    from loom.queue.service_upgrade import inspect_coordinator_result_recovery

    inventory, base, selection = site
    target = target_bundle(inventory, tmp_path)
    barrier = tmp_path / "refuse-preparation-result"
    inventory = bind_environments(broken_metadata_release(inventory, tmp_path, preparation_barrier=barrier))
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    write(inventory.hosts[0].config, authored)
    setup = apply(inventory, operation_id="setup-preparation-recovery", issuer=base / "issuer", check_selection=selection)
    assert setup["outcome"] == "complete", setup
    # A second descriptor of the deficient source is an unactivated candidate.
    candidate = tmp_path / "unactivated-candidate"
    shutil.copytree(inventory.runtime_release.parent, candidate)
    old_target = candidate / inventory.runtime_release.name
    value = read(old_target)
    value["release_id"] = "unactivated-deficient-candidate"
    write(old_target, value)
    deployment = load_deployment(setup["deployment"])
    request = RunRequest(PrepareRunRequest(
        "retained-preparation", "retained-preparation", deployment.source,
        selection["config"], deployment.preparation_profile,
    ), "retained-preparation")
    barrier.touch()
    with CoordinatorClient.from_connection_file(deployment.connection) as client:
        client.start_run(request)
        deadline = time.monotonic() + 60
        while True:
            with sqlite3.connect(base / "worker/journal.sqlite") as conn:
                retained = conn.execute("SELECT assignment_id, grant_fence, result_json FROM assignments WHERE state = 'result_durable'").fetchall()
            if retained:
                break
            assert time.monotonic() < deadline, client.observe_run("retained-preparation", wait=False)
            time.sleep(0.1)
        assert len(retained) == 1
        assignment, fence, result_json = retained[0]
        worker_result = base / "worker/assignments" / assignment / "worker-result.json"
        original_bytes = worker_result.read_bytes()
        cancel = client.cancel_run_operation("retained-preparation")
        options = dict(
            runtime_release=old_target, recover_retained_results=True, hold_admission=True,
            deployment=Path(setup["deployment"]), connection=Path(setup["operator_connection"]),
            config=selection["config"],
        )
        blocked = upgrades.upgrade(inventory, operation_id="recover-preparation", apply=True, **options)
        deadline = time.monotonic() + 60
        while "coordinator mutation remains active" not in blocked.get("reason", ""):
            assert blocked["outcome"] == "waiting" and time.monotonic() < deadline, blocked
            time.sleep(0.25)
            blocked = upgrades.upgrade(inventory, operation_id="recover-preparation")
        assert blocked["outcome"] == "waiting", blocked
        assert "coordinator mutation remains active" in blocked["reason"]
        directory = upgrades.sshops._directory(inventory, "recover-preparation")
        original_intent = (directory / "intent.json").read_bytes()
        assert not (directory / "irreversible.json").exists()
        # The current checker admits only the exact successful child cohort.
        intent = read(directory / "intent.json")
        operation = upgrades._Upgrade(inventory, directory, intent)
        try:
            results = operation.host_observe("worker", "upgrade-result-recovery")["value"]["results"]
            current = inspect_coordinator_result_recovery(
                Path(intent["hosts"]["coordinator"]["root"]) / "coordinator", expected_root_id=intent["hosts"]["coordinator"]["expected_root_id"],
                agent_results=results,
            )
            assert current.availability == "available", current.reason
            missing = inspect_coordinator_result_recovery(
                Path(intent["hosts"]["coordinator"]["root"]) / "coordinator", expected_root_id=current.owner, agent_results=[],
            )
            assert missing.availability == "unavailable"
        finally:
            operation.close()
        # Lose the successor's applied replacement reply and recover by parent ID.
        call, dropped = upgrades.sshops.ssh, []

        def lose_reply(host, request):
            reply = call(host, request)
            if request["action"] == "upgrade-replace" and request["name"] == "worker" and not dropped:
                dropped.append(request["request_id"])
                raise upgrades.sshops.SshUnavailable("lost candidate repair reply")
            return reply

        monkeypatch.setattr(upgrades.sshops, "ssh", lose_reply)
        code = main([
            "fleet", "operation", "repair-runtime-candidate", "recover-preparation",
            "--fleet", str(inventory.path), "--runtime-release", str(target), "--format", "json",
        ])
        repaired = json.loads(capsys.readouterr().out)
        assert code in (0, 2), repaired
        held = upgrades.upgrade(inventory, operation_id="recover-preparation")
        deadline = time.monotonic() + 120
        while held.get("reason_code") != "publication_pending":
            assert held["outcome"] == "waiting" and time.monotonic() < deadline, held
            time.sleep(0.25)
            held = upgrades.upgrade(inventory, operation_id="recover-preparation")
        assert held["outcome"] == "waiting" and held["reason_code"] == "publication_pending", held
        assert len(dropped) == 1
        assert (directory / "intent.json").read_bytes() == original_intent
        assert client.wait_operation(cancel.operation_id, timeout_seconds=25).operation.state == "applied"
        assert client.operation("retained-preparation").state == "cancelled"
        assert worker_result.read_bytes() == original_bytes
        with sqlite3.connect(base / "worker/journal.sqlite") as conn:
            assert conn.execute("SELECT grant_fence, result_json, state FROM assignments WHERE assignment_id = ?", (assignment,)).fetchone() == (fence, result_json, "released")
        conflict = upgrades.upgrade(inventory, operation_id="recover-preparation", action="repair-runtime-candidate", runtime_release=old_target)
        assert conflict["outcome"] == "blocked" and "repair target changed" in conflict["reason"], conflict
        completed = finish(inventory, "recover-preparation", action="release-admission")
        assert completed["outcome"] == "complete", completed
        assert completed["runtime_candidate_repair"]
        with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
            assert operator.observe_maintenance()["state"] == "open"
            assert not operator.observe_agent("worker").value["drained"]


def test_runtime_recovery_publishes_original_result_and_finishes_downstream(
    site, tmp_path, monkeypatch,  # noqa: F811
):
    from loom.coordinator import RunRequest
    from loom.deployment import load_deployment
    from loom.queue.preparation import PrepareRunRequest

    inventory, base, selection = site
    target = target_bundle(inventory, tmp_path)
    inventory = bind_environments(broken_metadata_release(inventory, tmp_path))
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    write(inventory.hosts[0].config, authored)
    setup = apply(inventory, operation_id="setup-retained", issuer=base / "issuer", check_selection=selection)
    assert setup["outcome"] == "complete", setup
    source = tmp_path / "projects/pipeline.yaml"
    pipeline = json.loads(source.read_text())
    producer = pipeline["pipeline"]["stages"][0]
    producer["factory"] = {"_target_": "tests.support.pipeline_execution_stages.MeasurementProducerStage"}
    consumer = json.loads(json.dumps(producer))
    consumer.update(
        name="consume",
        factory={"_target_": "tests.support.pipeline_execution_stages.MeasurementConsumerStage"},
        inputs={"data": "produce.data"},
    )
    pipeline["pipeline"]["stages"].append(consumer)
    write(source, pipeline)
    deployment = load_deployment(setup["deployment"])
    request = RunRequest(PrepareRunRequest(
        "retained-measurement", "retained-measurement", deployment.source,
        selection["config"], deployment.preparation_profile,
    ), "retained-measurement")
    with CoordinatorClient.from_connection_file(deployment.connection) as client:
        client.start_run(request)
        deadline = time.monotonic() + 60
        while True:
            with sqlite3.connect(base / "worker/journal.sqlite") as conn:
                retained = conn.execute(
                    "SELECT assignment_id, grant_fence, result_json FROM assignments WHERE state = 'result_durable'"
                ).fetchall()
            if retained:
                break
            assert time.monotonic() < deadline, client.observe_run("retained-measurement", wait=False)
            time.sleep(0.1)
        assert len(retained) == 1
        assignment, fence, result_json = retained[0]
        worker_result = base / "worker/assignments" / assignment / "worker-result.json"
        original_bytes = worker_result.read_bytes()
        source.write_text(json.dumps({"pipeline": {"name": "checks", "stages": [
            {**producer, "factory": {"_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"}}
        ]}, "runtime": {"executor": "local"}}))
        # Lose an applied replacement reply; resuming must reuse the same owner.
        call = upgrades.sshops.ssh
        dropped = []

        def lose_reply(host, request):
            reply = call(host, request)
            if request["action"] == "upgrade-replace" and request["name"] == "worker" and not dropped:
                dropped.append(request["request_id"])
                raise upgrades.sshops.SshUnavailable("lost applied replacement reply")
            return reply

        monkeypatch.setattr(upgrades.sshops, "ssh", lose_reply)
        result = finish(
            inventory, "recover-retained", apply=True, runtime_release=target,
            recover_retained_results=True, deployment=Path(setup["deployment"]),
            connection=Path(setup["operator_connection"]), config=selection["config"],
        )
        assert result["outcome"] == "complete", result
        assert len(dropped) == 1
        observation = client.observe_run("retained-measurement", wait=False)
        assert observation.admission.state.value == "SUCCEEDED", observation
        assert worker_result.read_bytes() == original_bytes
        with sqlite3.connect(base / "worker/journal.sqlite") as conn:
            assert conn.execute(
                "SELECT grant_fence, result_json, state FROM assignments WHERE assignment_id = ?", (assignment,)
            ).fetchone() == (fence, result_json, "released")
        with sqlite3.connect(base / "worker/supervisor/supervisor.sqlite") as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM launches WHERE json_extract(launch_json, '$.assignment_id') = ?", (assignment,)
            ).fetchone() == (1,)


def test_stale_check_profile_refuses_before_maintenance_without_changing_intent(
    site, tmp_path,  # noqa: F811
):
    from copy import deepcopy
    from dataclasses import replace
    from loom.deployment import load_deployment, export_connection_deployment

    inventory, base, selection = site
    inventory = bind_environments(inventory)
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    profiles = authored["preparation"]["profiles"]
    profiles["other-project"] = deepcopy(profiles["existing-project"])
    write(inventory.hosts[0].config, authored)
    setup = apply(inventory, operation_id="setup-profile-repair", issuer=base / "issuer",
                  check_selection=selection)
    assert setup["outcome"] == "complete", setup
    current = load_deployment(setup["deployment"])
    stale = tmp_path / "stale-checks.json"
    export_connection_deployment(replace(current, preparation_profile="old-project"), stale)
    identity = "repair-profile"
    result = upgrades.upgrade(
        inventory, operation_id=identity, apply=True,
        runtime_release=target_bundle(inventory, tmp_path), deployment=stale,
        connection=Path(setup["operator_connection"]), config=selection["config"],
    )
    deadline = time.monotonic() + 240
    while result["outcome"] == "waiting" and time.monotonic() < deadline:
        time.sleep(.25)
        result = upgrades.upgrade(inventory, operation_id=identity)
    assert result["outcome"] == "blocked" and "ambiguous" in result["reason"], result
    directory = upgrades.sshops._directory(inventory, identity)
    original_intent = (directory / "intent.json").read_bytes()
    stale_bytes = stale.read_bytes()
    assert not (directory / "checks.json").exists()
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        assert operator.observe_maintenance()["state"] == "open"
    assert not (directory / "irreversible.json").exists()
    assert not (directory / "steps/close/intent.json").exists()
    assert (directory / "intent.json").read_bytes() == original_intent
    assert stale.read_bytes() == stale_bytes
    assert upgrades.upgrade(inventory, operation_id=identity, action="abort")["outcome"] == "aborted"


def test_runtime_upgrade_repairs_profile_after_settled_failed_check(site, tmp_path, monkeypatch):  # noqa: F811
    from copy import deepcopy
    from dataclasses import replace
    from loom.deployment import load_deployment, export_connection_deployment

    inventory, base, selection = site
    inventory = bind_environments(inventory)
    authored = read(inventory.hosts[0].config)
    for principal in authored['agent_policy']['principals']:
        if principal['role'] == 'operator':
            principal['actions'].append('resume')
    profiles = authored['preparation']['profiles']
    profiles['infrastructure'] = deepcopy(profiles['existing-project'])
    write(inventory.hosts[0].config, authored)
    setup = apply(inventory, operation_id='setup-failed-profile', issuer=base/'issuer', check_selection=selection)
    assert setup['outcome'] == 'complete', setup
    source = tmp_path/'projects/pipeline.yaml'
    original_source = source.read_bytes()
    native = upgrades._Upgrade.native

    def corrupt_after_preflight(operation, key, request, invoke):
        result = native(operation, key, request, invoke)
        if key == "close":
            source.write_text("pipeline: [invalid")
        return result

    monkeypatch.setattr(upgrades._Upgrade, "native", corrupt_after_preflight)
    identity = 'repair-failed-profile'
    result = upgrades.upgrade(inventory, operation_id=identity, apply=True,
        runtime_release=target_bundle(inventory, tmp_path), deployment=Path(setup['deployment']),
        connection=Path(setup['operator_connection']), config=selection['config'])
    deadline = time.monotonic()+240
    while result['outcome']=='waiting' and time.monotonic()<deadline:
        time.sleep(.25)
        result=upgrades.upgrade(inventory, operation_id=identity)
    assert result['outcome']=='blocked' and 'retry-check' in result['reason'], result
    settle_failed_checks(inventory, identity)
    directory=upgrades.sshops._directory(inventory, identity)
    intent=(directory/'intent.json').read_bytes()
    failed=read(directory/'checks.json')['worker:cpu'][-1]['operation_id']
    failed_intent=inventory.path.parent/'checks'/failed/'intent.json'
    failed_bytes=failed_intent.read_bytes()
    selected=directory/'worker-check-selection.json'
    selected_bytes=selected.read_bytes()
    source.write_bytes(original_source)
    deployment=load_deployment(setup['deployment'])
    for name, invalid in (
        ("source", replace(deployment, source=replace(deployment.source, path="different"))),
        ("profile", replace(deployment, preparation_profile="missing")),
    ):
        path = tmp_path / (name + ".json")
        export_connection_deployment(invalid, path)
        refused = upgrades.upgrade(inventory, operation_id=identity,
                                   action="repair-check-selection", deployment=path)
        assert refused["outcome"] == "blocked", refused
        assert not (directory / "check-selection-repair.json").exists()
    candidate=tmp_path/'infrastructure-checks.json'
    export_connection_deployment(replace(deployment, preparation_profile='infrastructure'), candidate)
    result=upgrades.upgrade(inventory, operation_id=identity, action='repair-check-selection', deployment=candidate)
    assert result['outcome']=='blocked' and 'retry-check' in result['reason'], result
    assert (directory/'check-selection-repair.json').exists()
    assert failed_intent.read_bytes()==failed_bytes
    assert selected.read_bytes()==selected_bytes
    assert (directory/'intent.json').read_bytes()==intent
    # Repair alone does not turn the failed check into a pass or authorize a new one.
    assert len(read(directory/'checks.json')['worker:cpu'])==1
    storage_failed = read(directory / 'checks.json')['worker:storage'][-1]['operation_id']
    result = upgrades.upgrade(inventory, operation_id=identity, action='retry-check',
                              failed_check=failed, new_check='correct-profile-check')
    assert result['outcome'] == 'blocked' and storage_failed in result['reason'], result
    result=finish(inventory, identity, action='retry-check',
                  failed_check=storage_failed, new_check='correct-storage-check')
    assert result['outcome']=='complete', result
    rows=read(directory/'checks.json')['worker:cpu']
    assert [row['operation_id'] for row in rows]==[failed,'correct-profile-check']
    assert rows[0]['authorization']['request']['preparation']['preparation_profile']=='existing-project'
    assert rows[1]['authorization']['request']['preparation']['preparation_profile']=='infrastructure'
    assert failed_intent.read_bytes()==failed_bytes
    assert selected.read_bytes()==selected_bytes
    assert load_deployment(directory/'worker-repaired-check-selection.json').preparation_profile=='infrastructure'
    with CoordinatorOperatorClient.from_connection_file(setup['operator_connection']) as operator:
        assert operator.observe_maintenance()['state']=='open'


def test_qualified_upgrade_holds_admission_until_explicit_publication_release(site, tmp_path, monkeypatch):  # noqa: F811
    inventory, base, selection = site
    inventory = bind_environments(inventory)
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    write(inventory.hosts[0].config, authored)
    setup = apply(inventory, operation_id="setup-publication", issuer=base / "issuer", check_selection=selection)
    assert setup["outcome"] == "complete", setup
    target = target_bundle(inventory, tmp_path)
    original_inventory = inventory.path.read_bytes()
    options = dict(runtime_release=target, deployment=Path(setup["deployment"]),
                   connection=Path(setup["operator_connection"]), config=selection["config"],
                   hold_admission=True)
    result = upgrades.upgrade(inventory, operation_id="publication", apply=True, **options)
    deadline = time.monotonic() + 240
    while not result.get("publication_ready") and result["outcome"] == "waiting" and time.monotonic() < deadline:
        time.sleep(0.25)
        result = upgrades.upgrade(inventory, operation_id="publication")
    assert result.get("publication_ready") and result["outcome"] == "waiting", result
    directory = upgrades.sshops._directory(inventory, "publication")
    assert read(directory / "intent.json")["kind"] == "runtime-upgrade-publication"
    assert not (directory / "complete.json").exists()
    assert inventory.path.read_bytes() == original_inventory
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        gate = operator.observe_maintenance()
        assert gate["state"] == "closed"
        assert upgrades.upgrade(inventory, operation_id="publication")["publication_ready"]
        assert operator.observe_maintenance()["state"] == "closed"
    # Publication is an external caller responsibility. Its success authorizes
    # this explicit continuation; normal resume cannot infer success from time.
    intent = read(directory / "intent.json")
    environments = {row["env_file"] for row in intent["hosts"].values() if row["env_file"]}
    assert environments
    for environment in environments:
        path = Path(environment)
        path.write_text(path.read_text() + "\nCLIENT_SELECTION=published\n")
    from loom.fleet import _inventory_publication

    replace_file = _inventory_publication.os.replace
    interrupted = []

    def lose_inventory_reply(source, destination):
        replace_file(source, destination)
        if Path(destination) == inventory.path and not interrupted:
            interrupted.append(True)
            raise OSError("lost inventory publication reply")

    with monkeypatch.context() as patch:
        patch.setattr(_inventory_publication.os, "replace", lose_inventory_reply)
        result = upgrades.upgrade(inventory, operation_id="publication", action="release-admission")
    assert interrupted and result["outcome"] != "complete", result
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        assert operator.observe_maintenance()["state"] == "closed"
    from loom.fleet.configuration import load_inventory

    # A new CLI invocation reloads the now-published inventory from disk.
    inventory = load_inventory(inventory.path)
    result = finish(inventory, "publication", action="release-admission")
    assert result["outcome"] == "complete"
    assert read(directory / "restoring.json")["publication_released"] is True
    assert read(inventory.path)["runtime_release"] == str(target.resolve())
    assert read(directory / "steps/publish-inventory/receipt.json")["state"] == "published"
    assert upgrades.upgrade(inventory, operation_id="publication", action="release-admission")["outcome"] == "complete"
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        assert operator.observe_maintenance()["state"] == "open"


def test_preview_compares_accepted_coordinator_identity_after_input_disappears(site, tmp_path):  # noqa: F811
    import hashlib
    from loom.queue.errors import QueueConflictError

    inventory, base, selection = site
    inventory = bind_environments(inventory)
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    obsolete = base / "obsolete-dataset"
    obsolete.mkdir()
    (obsolete / "challenge").write_bytes(b"obsolete")
    authored.setdefault("shared_roots", {})["obsolete"] = {
        "host_path": str(obsolete), "container_path": "/loom/obsolete", "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"obsolete").hexdigest()},
    }
    write(inventory.hosts[0].config, authored)
    setup = apply(inventory, operation_id="setup-preview", issuer=base / "issuer", check_selection=selection)
    assert setup["outcome"] == "complete", setup
    (obsolete / "challenge").unlink()
    obsolete.rmdir()
    options = dict(runtime_release=target_bundle(inventory, tmp_path),
                   deployment=Path(setup["deployment"]), connection=Path(setup["operator_connection"]),
                   config=selection["config"])
    result = upgrades.preview(inventory, **options)
    assert result["outcome"] == "preview"
    assert result["declarations"]["coordinator"]["shared_roots"]["obsolete"]["host_path"] == str(obsolete)
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        assert operator.observe_maintenance()["state"] == "open"
    assert not obsolete.exists()
    authored["shared_roots"]["obsolete"]["host_path"] = str(base / "unaccepted-path")
    write(inventory.hosts[0].config, authored)
    with pytest.raises(QueueConflictError, match="authored policy differs"):
        upgrades.preview(inventory, **options)
