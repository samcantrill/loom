"""Immutable byte checks precede native candidate qualification/publication."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.fleet import _workload_host as host
from loom.queue.errors import QueueConflictError


def test_candidate_digest_mismatch_never_qualifies_or_publishes(tmp_path, monkeypatch):
    image = tmp_path / "candidate.sif"
    image.write_bytes(b"changed-image")
    original = {
        "resident_profiles": [
            {
                "descriptor": {"profile_id": "selected", "revision": "v1"},
                "container": {
                    "kind": "apptainer",
                    "container": {"image": {"reference": "/old.sif"}},
                },
            }
        ]
    }
    monkeypatch.setattr(host, "payload", lambda _: original)
    monkeypatch.setattr(
        host,
        "qualify",
        lambda *a: pytest.fail("must check image before native qualification"),
    )
    with pytest.raises(QueueConflictError, match="digest mismatch"):
        host.probe(
            {
                "name": "agent",
                "workload_profile": "selected",
                "image": str(image),
                "image_sha256": "0" * 64,
            }
        )
    assert original["resident_profiles"][0]["descriptor"]["revision"] == "v1"


@pytest.mark.parametrize("source_path", [None, "/retained/project"])
def test_candidate_keeps_old_source_and_uses_native_target_qualification(
    tmp_path, monkeypatch, source_path
):
    image = tmp_path / "candidate.sif"
    image.write_bytes(b"candidate")
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    original = {
        "resident_profiles": [
            {
                "descriptor": {"profile_id": "selected", "revision": "v1"},
                "container": {
                    "kind": "apptainer",
                    "container": {"image": {"reference": "/old.sif"}},
                },
            }
        ]
    }
    monkeypatch.setattr(host, "payload", lambda _: original)
    monkeypatch.setattr(host, "owner", lambda _: {"owner": "original-root"})
    observed = []
    qualified_source = SimpleNamespace(
        immutable_fingerprint="source", active_fingerprint="source",
        client=SimpleNamespace(resident_profiles=[SimpleNamespace(descriptor=SimpleNamespace(
            to_dict=lambda: original["resident_profiles"][0]["descriptor"],
        ))]),
    )

    def load(path, **kwargs):
        observed.append((json.loads(Path(path).read_text()), False))
        return qualified_source

    def qualify(request, declaration, *, check_promotion=False, original=None):
        assert original is qualified_source
        observed.append((declaration, check_promotion))
        return {"observed": len(observed)}

    monkeypatch.setattr(host, "load_outbound_agent_service_config", load)
    monkeypatch.setattr(host, "qualify", qualify)
    candidate = copy.deepcopy(original)
    candidate["project_root"] = source_path
    result = host.probe(
        {
            "name": "agent",
            "config": str(tmp_path / "agent.json"),
            "workload_profile": "selected",
            "image": str(image),
            "image_sha256": sha,
            **({"candidate_declaration": candidate} if source_path else {}),
        }
    )
    assert result["source"] == {"immutable": "source", "active": "source",
                                "profile": original["resident_profiles"][0]["descriptor"]}
    assert result["target"] == {"observed": 2}
    assert observed[0] == (original, False)
    assert observed[1] == (result["declaration"], True)
    assert result["declaration"].get("project_root") == source_path
    assert (
        result["declaration"]["resident_profiles"][0]["descriptor"]["revision"]
        == "image-" + sha[:24]
    )
    assert (
        Path(
            result["declaration"]["resident_profiles"][0]["container"]["container"][
                "image"
            ]["reference"]
        )
        == image
    )
    assert original["resident_profiles"][0]["descriptor"]["revision"] == "v1"


def test_stopped_host_recovers_native_intent_then_starts_exact_retained_service(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from loom.fleet import _host
    from loom.queue import _profile_promotion

    request = {
        "root": str(tmp_path / "root"),
        "config": str(tmp_path / "agent.json"),
        "release": {"descriptor_sha256": "unchanged"},
        "admin": str(tmp_path),
        "expected_root_id": "root-id",
        "promotion_id": "promotion",
    }
    retained = {**request, "action": "start", "coordinator_id": "original-coordinator"}
    monkeypatch.setattr(
        host, "owner", lambda _: {"owner": "root-id", "value": {"ownership": "stopped"}}
    )
    monkeypatch.setattr(host, "read", lambda _: retained)
    monkeypatch.setattr(
        host,
        "load_outbound_agent_service_config",
        lambda *a, **k: SimpleNamespace(client="native-config"),
    )
    monkeypatch.setattr(host, "payload", lambda _: {"current": "native-published"})
    calls = []
    monkeypatch.setattr(_profile_promotion, "publication_state", lambda *a: "applied")
    monkeypatch.setattr(
        _profile_promotion, "recover", lambda config: calls.append(("recover", config))
    )
    monkeypatch.setattr(_host, "start", lambda value: calls.append(("start", value)))
    result = host.recover_service(request)
    assert calls == [("recover", "native-config"), ("start", {
        **retained, "startup_id": "workload-promotion",
        "expected_declaration": _host.digest({"current": "native-published"}),
    })]
    assert result["declaration"] == {"current": "native-published"}
    retained["release"] = {"descriptor_sha256": "other"}
    with pytest.raises(QueueConflictError, match="retained service binding differs"):
        host.recover_service(request)
    assert len([call for call in calls if call[0] == "start"]) == 1


def test_live_host_without_operator_authorization_never_mutates_services(
    tmp_path, monkeypatch
):
    from loom.fleet import _services
    from loom.queue import _profile_promotion

    request = {
        "root": str(tmp_path),
        "expected_root_id": "root-id",
        "promotion_id": "promotion",
        "service_manager": "systemd-user",
        "admin": str(tmp_path),
    }
    monkeypatch.setattr(
        host, "owner", lambda _: {"owner": "root-id", "value": {"ownership": "live"}}
    )
    monkeypatch.setattr(host, "payload", lambda _: {})
    monkeypatch.setattr(_profile_promotion, "publication_state", lambda *a: "applied")
    monkeypatch.setattr(host, "read", lambda _: request)
    finished = [False]
    monkeypatch.setattr(_profile_promotion, "completed", lambda *a: finished[0])
    calls = []
    monkeypatch.setattr(_services, "systemctl", lambda *a: calls.append(a) or "0")
    host.recover_service(request)
    assert not calls
    finished[0] = True
    host.recover_service(request)
    assert calls == [
        (
            "show",
            _services.unit_name(request, "supervisor"),
            "--property=MainPID",
            "--value",
        )
    ]


def test_fixed_host_cannot_publish_agent_source_ahead_of_native_intent(tmp_path):
    with pytest.raises(QueueConflictError, match="native promotion owns agent source"):
        host.publish({"name": "worker"}, tmp_path)


@pytest.mark.parametrize(
    "case", ["owned", "undelivered", "unacknowledged", "later_control", "wrong_gate"]
)
def test_controller_authorizes_live_stop_only_for_current_acknowledged_promotion(
    monkeypatch, tmp_path, case
):
    from types import SimpleNamespace
    from loom.fleet import workload_upgrades

    operation = object.__new__(workload_upgrades.WorkloadUpgrade)
    operation.intent = {
        "operation_id": "upgrade",
        "release": {"same": "release"},
        "hosts": {"worker": {"host": "selected", "root": str(tmp_path)}},
    }
    promotion = "upgrade-worker-promotion"
    from typing import Any, cast

    operation = cast(Any, operation)

    def observe_control(_):
        if case == "undelivered":
            from loom.coordinator import CoordinatorClientError

            raise CoordinatorClientError(
                "not_found", boundary="coordinator", operation="observe_control"
            )
        return {"state": "applied", "acknowledged": case != "unacknowledged"}

    operation.operator = SimpleNamespace(
        observe_control=observe_control,
        observe_agent=lambda _: SimpleNamespace(
            value={
                "drained": True,
                "control": {
                    "operation_id": "independent-drain"
                    if case == "later_control"
                    else promotion
                },
            }
        ),
    )
    gates = []

    def gate():
        gates.append(True)
        if case == "wrong_gate":
            raise QueueConflictError("maintenance gate owner/intent changed")

    operation.gate = gate
    sent = []
    monkeypatch.setattr(
        workload_upgrades.sshops,
        "ssh",
        lambda host, request: sent.append(request) or {},
    )
    if case == "wrong_gate":
        with pytest.raises(QueueConflictError, match="gate owner"):
            operation.recover_host("worker")
        assert not sent
    else:
        operation.recover_host("worker")
        assert sent[0]["allow_communication_stop"] is (case == "owned")
        assert bool(gates) is (case == "owned")


@pytest.mark.parametrize("case", ["unsettled", "different_process"])
def test_live_stop_refuses_unsettled_or_changed_native_service(
    tmp_path, monkeypatch, case
):
    from types import SimpleNamespace
    from loom.fleet import _services
    from loom.queue import _profile_promotion, service_upgrade

    selection = {
        "root": str(tmp_path),
        "admin": str(tmp_path),
        "service_manager": "systemd-user",
        "expected_root_id": "root",
        "promotion_id": "promotion",
        "allow_communication_stop": True,
    }
    monkeypatch.setattr(host, "read", lambda _: selection)
    fact = {
        "owner": "root",
        "revision": "start",
        "value": {"ownership": "live", "expected_process": 123},
    }
    monkeypatch.setattr(host, "owner", lambda _: fact)
    monkeypatch.setattr(_profile_promotion, "completed", lambda *a: True)
    monkeypatch.setattr(
        service_upgrade,
        "inspect_service_settlement",
        lambda *a, **k: SimpleNamespace(
            availability="available", value={"settled": case != "unsettled"}
        ),
    )
    calls = []

    def systemctl(*args):
        calls.append(args)
        assert args[0] == "show", "must not mutate service after a failed prerequisite"
        return "0" if args[1] == _services.unit_name(selection, "supervisor") else "456"

    monkeypatch.setattr(_services, "systemctl", systemctl)
    with pytest.raises(QueueConflictError, match="settlement|ownership changed"):
        host.recover_service(selection)


@pytest.fixture
def publication(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from loom.fleet import _host
    from loom.coordinator import CoordinatorClientError

    config = tmp_path / "coordinator.json"
    before, after = {"profiles": "before"}, {"profiles": "after"}
    _host.atomic(config, before)
    request = {
        "name": "coordinator", "root": str(tmp_path / "root"),
        "config": str(config), "release": {"descriptor_sha256": "same-release"},
        "admin": str(tmp_path), "request_id": "retained-publication", "declaration": after,
    }
    binding = {**request, "action": "start", "expected_root_id": "original-coordinator"}
    _host.atomic(tmp_path / "service.json", binding)
    directory = tmp_path / "publication"
    directory.mkdir()
    state = SimpleNamespace(owner="original-coordinator", bindings=[], reloads=[], lost=False, statuses=0,
        capabilities=["quiescent-coordinator-retirement-v1"], gate={
            "state": "closed", "settled": True, "checks": {}, "maintenance_id": "retire",
            "intent_digest": "selected", "revision": 1,
        })
    monkeypatch.setattr(host, "owner", lambda _: {"owner": state.owner})
    monkeypatch.setattr(host, "payload", lambda _: _host.read(config))

    class Client:
        def describe_connection(self):
            return SimpleNamespace(capabilities=state.capabilities)

        def observe_maintenance(self):
            return state.gate

        def status(self):
            state.statuses += 1
            return SimpleNamespace(scheduling_epoch="original-epoch")

        def reload_scheduling(self, value):
            state.reloads.append(value.to_dict())
            assert _host.read(config) == after
            if state.lost:
                state.lost = False
                raise CoordinatorClientError("unavailable", boundary="transport",
                                             operation="operator_scheduling_reload", mutation_outcome="unknown")
            return {"state": "applied"}

    def client(value):
        state.bindings.append(copy.deepcopy(value))
        assert value["coordinator_id"] == "original-coordinator"
        return None, Client()

    monkeypatch.setattr(_host, "coordinator_client", client)
    return request, binding, directory, state


def test_publication_binds_existing_service_and_replays_lost_reload_without_rewriting_intents(publication):
    from loom.coordinator import CoordinatorClientError
    from loom.fleet._host import read

    request, binding, directory, state = publication
    original = copy.deepcopy(request)
    state.lost = True
    with pytest.raises(CoordinatorClientError):
        host.publish(request, directory)
    retained = (directory / "reload.json").read_bytes()
    assert read(Path(request["config"])) == request["declaration"]
    result = host.publish(request, directory)
    assert result["reload"] == {"state": "applied"}
    assert state.statuses == 1  # Replay uses the exact retained epoch/request.
    assert len(state.reloads) == 2 and state.reloads[0] == state.reloads[1]
    assert state.reloads[0]["operation_id"] == request["request_id"]
    assert (directory / "reload.json").read_bytes() == retained
    assert request == original and "coordinator_id" not in request
    assert read(Path(request["admin"]) / "service.json") == binding
    assert len(state.bindings) == 3


@pytest.mark.parametrize("changed", ["root", "config", "release", "owner"])
def test_publication_refuses_changed_service_or_native_owner_before_writes(publication, changed):
    from loom.fleet._host import atomic, read

    request, binding, directory, state = publication
    original = Path(request["config"]).read_bytes()
    if changed == "owner":
        state.owner = "replacement-coordinator"
    else:
        binding[changed] = "different-binding"
        atomic(Path(request["admin"]) / "service.json", binding)
    with pytest.raises(QueueConflictError, match="binding differs|identity changed"):
        host.publish(request, directory)
    assert Path(request["config"]).read_bytes() == original
    assert not (directory / "reload.json").exists()
    assert not state.bindings and not state.reloads
    assert read(Path(request["admin"]) / "service.json") == binding


@pytest.fixture
def retirement_candidate(tmp_path, monkeypatch):
    from tests.unit.loom.queue.test_deployment import _agent_config, _write_protected
    from tests.unit.loom.queue.test_submitted_container_policy import _submitted
    from loom.queue.deployment import load_outbound_agent_service_config
    from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
    from loom.queue.retirement import read_agent_declaration_binding

    policy, _, _, _ = _submitted(tmp_path)
    source = _agent_config(tmp_path)
    before = json.loads(source.read_text())
    before["resources"] = {
        "cpu_capacity": 1, "memory_capacity_bytes": 0,
        "gpu": {"provider": "nvidia", "devices": "none"},
    }
    before["container_policies"] = [policy.to_dict()]
    missing = tmp_path / "deleted-qualification-data"
    missing.mkdir()
    (missing / "challenge").write_bytes(b"old-data")
    before["container_policies"][0]["shared_roots"]["obsolete"] = {
        "host_path": str(missing), "container_path": "/loom/obsolete", "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"old-data").hexdigest()},
    }
    # A discarded resident's execution files must not be probed either.
    before["resident_profiles"][0]["project_root"] = str(missing)
    _write_protected(source, before)
    service = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    accepted = read_agent_declaration_binding(service.client.agent_root, service.client.declaration_digest)
    (missing / "challenge").unlink()
    missing.rmdir()
    after = copy.deepcopy(before)
    after["resident_profiles"] = []
    del after["container_policies"][0]["shared_roots"]["obsolete"]
    request = {"name": "worker", "config": str(source),
               "retire_configuration": True, "candidate_declaration": after}
    monkeypatch.setattr(host, "owner", lambda _: {"owner": accepted.root_id})
    return request, missing


def test_retirement_probe_qualifies_container_only_target_with_deleted_predecessor(retirement_candidate):
    from loom.queue.deployment import read_agent_spec

    request, missing = retirement_candidate
    source = Path(request["config"])
    original = source.read_bytes()
    siblings = set(source.parent.iterdir())
    result = host.probe(request)
    assert result["source"]["declaration_digest"] == read_agent_spec(source).declaration_digest
    assert result["target"]["declaration_digest"] != result["source"]["declaration_digest"]
    assert result["target"]["profile"] is None
    assert result["target"]["immutable"] and result["target"]["active"]
    from loom.queue.retirement import read_agent_declaration_binding
    spec = read_agent_spec(source)
    accepted = read_agent_declaration_binding(spec.agent_root, spec.declaration_digest)
    assert result["source"]["immutable"] == accepted.immutable_fingerprint
    assert result["source"]["active"] == accepted.active_fingerprint
    assert result["native_owner"] == {"owner": accepted.root_id}
    assert source.read_bytes() == original
    assert set(source.parent.iterdir()) == siblings
    assert not missing.exists()


@pytest.mark.parametrize("change", ["resources", "transport", "new_policy", "root_identity", "missing_target"])
def test_retirement_probe_refuses_invalid_target_without_publishing(retirement_candidate, change):
    from loom.queue.errors import QueueServiceError

    request, missing = retirement_candidate
    after = request["candidate_declaration"]
    policy = after["container_policies"][0]
    if change == "resources":
        after["resources"]["cpu_capacity"] = 2
    elif change == "transport":
        after["url"] = "https://different.example:8443"
    elif change == "new_policy":
        policy["policy_id"] = "unaccepted-policy"
    elif change == "root_identity":
        policy["shared_roots"]["workloads"]["challenge"]["sha256"] = "b" * 64
    else:
        policy["shared_roots"]["workloads"]["host_path"] = str(missing)
    source = Path(request["config"])
    original = source.read_bytes()
    siblings = set(source.parent.iterdir())
    with pytest.raises((QueueConflictError, QueueServiceError)):
        host.probe(request)
    assert source.read_bytes() == original
    assert set(source.parent.iterdir()) == siblings
    assert not missing.exists()


def _retirement_publication(request):
    return {**request, "retirement": {
        "maintenance_id": "retire", "maintenance_intent_digest": "selected",
        "expected_gate_revision": 1,
    }}


@pytest.mark.parametrize("refusal", ["unsupported", "open", "wrong_owner", "unsettled", "checks"])
def test_retirement_publication_refuses_before_source_or_intent_write(publication, refusal):
    request, _, directory, state = publication
    request = _retirement_publication(request)
    source = Path(request["config"])
    original = source.read_bytes()
    if refusal == "unsupported":
        state.capabilities = []
    elif refusal == "open":
        state.gate["state"] = "open"
    elif refusal == "wrong_owner":
        state.gate["maintenance_id"] = "another-maintenance"
    elif refusal == "unsettled":
        state.gate["settled"] = False
    else:
        state.gate["checks"] = {"active-check": {}}
    with pytest.raises(QueueConflictError, match="unsupported_capability|exact settled maintenance"):
        host.publish(request, directory)
    assert source.read_bytes() == original
    assert not (directory / "reload.json").exists()
    assert not state.reloads


def test_retirement_publication_replays_exact_binding_after_lost_reply(publication):
    from loom.coordinator import CoordinatorClientError

    request, _, directory, state = publication
    request = _retirement_publication(request)
    state.lost = True
    with pytest.raises(CoordinatorClientError):
        host.publish(request, directory)
    before = (directory / "reload.json").read_bytes()
    # Already-written source can replay the native request without reacquiring
    # a gate; the native journal decides whether that exact effect was accepted.
    state.gate["state"] = "open"
    assert host.publish(request, directory)["reload"]["state"] == "applied"
    assert state.reloads[0] == state.reloads[1]
    assert state.reloads[0]["retirement"] == request["retirement"]
    assert (directory / "reload.json").read_bytes() == before
    changed = {**request, "retirement": {**request["retirement"], "expected_gate_revision": 2}}
    with pytest.raises(QueueConflictError, match="retirement binding changed"):
        host.publish(changed, directory)
    assert len(state.reloads) == 2


def test_retirement_publication_rechecks_gate_after_interrupted_source_write(publication, monkeypatch):
    request, _, directory, state = publication
    request = _retirement_publication(request)
    source = Path(request["config"])
    before = source.read_bytes()
    atomic = host.atomic

    def interrupt(path, value):
        if path == source:
            raise RuntimeError("before-source-write")
        return atomic(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(host, "atomic", interrupt)
        with pytest.raises(RuntimeError, match="before-source-write"):
            host.publish(request, directory)
    assert (directory / "reload.json").exists()
    state.gate["revision"] += 1
    with pytest.raises(QueueConflictError, match="exact settled maintenance"):
        host.publish(request, directory)
    assert source.read_bytes() == before
    assert not state.reloads


@pytest.mark.parametrize("change", ["declaration", "native_owner", "uninitialized"])
def test_retirement_probe_requires_accepted_predecessor_before_target_qualification(retirement_candidate, monkeypatch, change):
    from loom.queue.errors import QueueError
    from tests.unit.loom.queue.test_deployment import _write_protected

    request, missing = retirement_candidate
    source = Path(request["config"])
    authored = json.loads(source.read_text())
    if change == "native_owner":
        monkeypatch.setattr(host, "owner", lambda _: {"owner": "different-root"})
    else:
        key, value = ("reconnect_seconds", 0.5) if change == "declaration" else ("agent_root", "uninitialized")
        authored[key] = value
        request["candidate_declaration"][key] = value
        _write_protected(source, authored)
    monkeypatch.setattr(host, "load_outbound_agent_service_config",
                        lambda *args, **kwargs: pytest.fail("unaccepted predecessor qualified a target"))
    with pytest.raises(QueueError):
        host.probe(request)
    assert not missing.exists()
    assert not (source.parent / "uninitialized").exists()


def test_retirement_staging_qualifies_exact_container_target_without_resident_image(retirement_candidate):
    request, missing = retirement_candidate
    target = host.probe(request)["target"]
    declaration = request.pop("candidate_declaration")
    request.update(declaration=declaration, target=target, request_id="retirement-stage")
    result = host.stage(request)
    assert json.loads(Path(result["candidate_source"]).read_text()) == declaration
    assert json.loads(Path(request["config"]).read_text())["resident_profiles"]
    assert not missing.exists()


def test_runtime_probe_qualifies_retirement_target_before_stopping_deleted_predecessor(
    retirement_candidate, monkeypatch, tmp_path,
):
    from loom.fleet import _upgrade_host, releases
    from loom.queue.deployment import read_agent_spec

    request, missing = retirement_candidate
    qualified = host.probe(request)
    spec = read_agent_spec(request["config"])
    release = {"descriptor_sha256": "a" * 64}
    request = {
        **request, "admin": str(tmp_path / "admin"), "root": str(spec.agent_root),
        "release": release, "descriptor_name": "release.yaml",
        "expected_root_id": qualified["native_owner"]["owner"],
        "required_capabilities": [], "images": {},
        "retirement_declaration": request["candidate_declaration"],
        "retirement_target": qualified["target"],
    }
    monkeypatch.setattr(releases, "verify_release", lambda _: release)
    monkeypatch.setattr(_upgrade_host, "owner", host.owner)
    original = Path(request["config"]).read_bytes()
    facts = _upgrade_host.inspect(request)
    assert facts["compatibility"]["value"]["compatible"]
    assert facts["retirement_target"] == qualified["target"]
    assert facts["images"] == {}
    stopped = []
    monkeypatch.setattr(_upgrade_host, "stop_owned", lambda value, **_: stopped.append(value) or {"outcome": "stopped"})
    assert _upgrade_host.stop(request) == {"outcome": "stopped"}
    assert stopped == [request]
    changed = {**request, "retirement_target": {**qualified["target"], "active": "stale"}}
    with pytest.raises(QueueConflictError, match="qualification changed"):
        _upgrade_host.stop(changed)
    assert len(stopped) == 1
    with pytest.raises(QueueConflictError, match="publication first"):
        _upgrade_host.replace(request)
    assert Path(request["config"]).read_bytes() == original
    assert not missing.exists()


@pytest.mark.parametrize("refusal", [None, "capability", "open", "revision"])
def test_policy_addition_publication_guards_and_exact_replay(publication, refusal):
    from loom.fleet._host import read
    from loom.queue._container_policy_addition import CAPABILITY
    from loom.coordinator import CoordinatorClientError

    request, _, directory, state = publication
    binding = _retirement_publication(request)["retirement"]
    request = {**request, "container_policy_addition": binding}
    state.capabilities.append(CAPABILITY)
    if refusal == "capability":
        state.capabilities.remove(CAPABILITY)
    elif refusal == "open":
        state.gate["state"] = "open"
    elif refusal == "revision":
        state.gate["revision"] += 1
    if refusal:
        with pytest.raises(QueueConflictError, match="unsupported_capability|exact settled maintenance"):
            host.publish(request, directory)
        assert not (directory / "reload.json").exists()
        assert read(Path(request["config"])) == {"profiles": "before"}
        return
    state.lost = True
    with pytest.raises(CoordinatorClientError):
        host.publish(request, directory)
    state.gate["state"] = "open"
    assert host.publish(request, directory)["reload"]["state"] == "applied"
    assert state.reloads[0] == state.reloads[1]
    assert state.reloads[0]["container_policy_addition"] == binding
