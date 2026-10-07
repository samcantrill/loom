"""Public maintenance orchestration over actual disposable SSH/native services."""

from __future__ import annotations

import json
import shutil
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
from tests.integration.fleet.test_ssh_operations import bundle, endpoint, site, write  # noqa: F401

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
        result = upgrades.upgrade(inventory, operation_id=identity)
    assert result["outcome"] == "complete", json.dumps(result)
    return result


def test_runtime_upgrade_abort_interruption_resume_and_native_checks(
    site,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    inventory, base, selection = site
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
    # A lost controller before closure retains candidate evidence but no native gate.
    probes = upgrades._Upgrade.probes

    def before_closure(operation):
        probes(operation)
        raise upgrades._Waiting("interrupted before gate closure")

    monkeypatch.setattr(upgrades._Upgrade, "probes", before_closure)
    interrupted = upgrades.upgrade(
        inventory, operation_id="before-window", apply=True, **options
    )
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
            dropped.append(request["operation_id"])
            raise upgrades.sshops.SshUnavailable("lost accepted close reply")
        return result

    monkeypatch.setattr(upgrades._Upgrade, "native", interrupt)
    result = upgrades.upgrade(
        inventory, operation_id="abort-window", apply=True, **options
    )
    assert result["outcome"] == "waiting", result
    result = upgrades.upgrade(inventory, operation_id="abort-window", action="abort")
    assert result["outcome"] == "aborted", result
    with CoordinatorOperatorClient.from_connection_file(
        setup["operator_connection"]
    ) as operator:
        assert operator.observe_maintenance()["state"] == "open"
    dropped.clear()
    original_source.write_text("pipeline: [invalid")
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
    assert replacement["outcome"] == "waiting", replacement
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
    from tests.unit.loom.queue.test_coordinator_upgrade import _predecessor
    from tests.integration.fleet.test_releases import bundle as release_bundle

    # The native migration fixture represents the retained schema-12 producer.
    config = _predecessor(tmp_path)
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
        "older": "unsupported direct Fleet migration",
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
