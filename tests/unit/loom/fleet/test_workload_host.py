"""Immutable byte checks precede native candidate qualification/publication."""

import copy
import hashlib
from pathlib import Path

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

    def qualify(request, declaration, *, check_promotion=False):
        observed.append((declaration, check_promotion))
        return {"observed": len(observed)}

    monkeypatch.setattr(host, "qualify", qualify)
    candidate = copy.deepcopy(original)
    candidate["project_root"] = source_path
    result = host.probe(
        {
            "name": "agent",
            "workload_profile": "selected",
            "image": str(image),
            "image_sha256": sha,
            **({"candidate_declaration": candidate} if source_path else {}),
        }
    )
    assert result["source"] == {"observed": 1}
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
    assert calls == [("recover", "native-config"), ("start", retained)]
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
    state = SimpleNamespace(owner="original-coordinator", bindings=[], reloads=[], lost=False, statuses=0)
    monkeypatch.setattr(host, "owner", lambda _: {"owner": state.owner})
    monkeypatch.setattr(host, "payload", lambda _: _host.read(config))

    class Client:
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
