"""Waiting cost, independent progress and immutable activation boundaries."""
import hashlib
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from threading import Event
from contextlib import contextmanager

import pytest

from loom.fleet import upgrades, workload_upgrades, _workload_host
from loom.fleet._host import atomic, read, digest


@pytest.mark.parametrize("failure", [None, "qualification", "image"])
def test_replacement_uses_one_qualified_service_and_its_image_observation(tmp_path, monkeypatch, failure):
    from loom.fleet import _upgrade_host, _host, releases
    from loom.queue import deployment, preflight
    from loom.diagnostics.models import PreflightStatus

    admin = tmp_path / "admin"
    admin.mkdir()
    old, new = {"descriptor_sha256": "old"}, {"descriptor_sha256": "new"}
    request = {"admin": str(admin), "release": new, "source_release": old,
               "name": "agent", "config": str(tmp_path / "agent.json"),
               "root": str(tmp_path / "root"), "descriptor_name": "release.json",
               "expected_root_id": "root", "required_capabilities": [],
               "images": {"/image.sif": "expected"}}
    atomic(admin / "active.json", old)
    profile = SimpleNamespace(container={"container": {"image": {"reference": "/image.sif"}}},
                              readiness_result=SimpleNamespace(image_sha256="changed" if failure == "image" else "expected"))
    service = SimpleNamespace(client=SimpleNamespace(resident_profiles=(profile,)))
    loaded, checked, guarded = [], [], []
    def load(*args, **kwargs):
        loaded.append(kwargs)
        return service
    def check(selected):
        checked.append(selected)
        return SimpleNamespace(status=PreflightStatus.FAIL if failure == "qualification" else PreflightStatus.PASS,
                               to_dict=lambda: {"checks": [{"status": "FAIL" if failure == "qualification" else "PASS"}]})
    @contextmanager
    def guard(selected, root, **kwargs):
        guarded.append(selected)
        yield
    monkeypatch.setattr(deployment, "load_outbound_agent_service_config", load)
    monkeypatch.setattr(preflight, "check_loaded_agent", check)
    monkeypatch.setattr(deployment, "service_replacement_guard", guard)
    monkeypatch.setattr(releases, "verify_release", lambda *args: new)
    monkeypatch.setattr(_upgrade_host, "owner", lambda *args: {"owner": "root", "value": {"ownership": "stopped"}})
    monkeypatch.setattr(_upgrade_host, "probe_upgrade_compatibility", lambda *args, **kwargs: SimpleNamespace(
        availability="available", value={"compatible": True}, to_dict=lambda: {}))
    monkeypatch.setattr(_upgrade_host, "_settled", lambda *args: None)
    monkeypatch.setattr(_upgrade_host.hashlib, "file_digest", lambda *args: pytest.fail("qualified image hashed twice"))
    monkeypatch.setattr(_host, "start", lambda *args: {"ready": True})
    if failure:
        with pytest.raises(upgrades.QueueConflictError):
            _upgrade_host.replace(request)
        assert read(admin / "active.json") == old and not guarded
    else:
        result = _upgrade_host.replace(request)
        assert result["ready"] and read(admin / "active.json") == new
        assert guarded == [service]
    assert len(loaded) == 1 and loaded[0]["_deadline"] > 0
    assert checked == [service]
    assert read(admin / "last-native.json")["returncode"] == int(failure == "qualification")


@pytest.mark.parametrize("kind", ["drain", "resume"])
def test_independent_controls_dispatch_all_agents_but_require_every_ack(kind):
    submitted, verified = [], []
    acknowledged = {"second"}

    def policy(name, key, selected_kind, predecessor):
        assert selected_kind == kind and predecessor == "previous-" + name
        if key not in submitted:
            submitted.append(key)
        if name not in acknowledged:
            raise upgrades._Waiting("pending: " + name)
        return key

    operation = SimpleNamespace(policy=policy,
                                verify_policy=lambda name, identity: verified.append(identity))
    requests = [(name, name + "-control", kind, "previous-" + name)
                for name in ("first", "second", "third")]
    with pytest.raises(upgrades._Waiting, match="first"):
        upgrades._independent_policies(operation, requests)
    assert submitted == ["first-control", "second-control", "third-control"]
    assert verified == ["second-control"]
    acknowledged.update(("first", "third"))
    upgrades._independent_policies(operation, requests)
    assert len(submitted) == 3
    assert verified[-3:] == submitted


def test_independent_controls_do_not_hide_predecessor_failure():
    def policy(*args):
        raise upgrades.QueueConflictError("agent control predecessor conflicts")
    operation = SimpleNamespace(policy=policy, verify_policy=lambda *args: pytest.fail("unaccepted"))
    with pytest.raises(upgrades.QueueConflictError, match="predecessor"):
        upgrades._independent_policies(operation, [("agent", "control", "resume", "old")])


def test_host_batch_starts_peer_and_retains_success_when_first_host_waits(tmp_path, monkeypatch):
    from loom.fleet import ssh_operations
    from loom.fleet._startup import ServiceStarting

    operation = object.__new__(ssh_operations._Operation)
    operation.intent = {"hosts": {name: {"host": name} for name in ("first", "second")}}
    operation.accept_update = lambda *args: None
    ids = []
    def prepare(name, action, **values):
        directory = tmp_path / name
        directory.mkdir(exist_ok=True)
        request = {"request_id": name + "-original", "action": action}
        ids.append(request["request_id"])
        receipt = directory / "receipt.json"
        return directory, request, read(receipt) if receipt.exists() else None
    operation._prepare_call = prepare
    second_started = Event()
    launches = []
    def ssh(host, request):
        launches.append(host)
        if host == "first":
            assert second_started.wait(5), "peer was not dispatched independently"
            raise ServiceStarting("still starting")
        second_started.set()
        return {"outcome": "applied"}
    monkeypatch.setattr(ssh_operations, "ssh", ssh)
    calls = [(name, "upgrade-replace", {}) for name in ("first", "second")]
    for _ in range(2):
        with pytest.raises(ServiceStarting):
            operation.call_many(calls)
    assert launches.count("second") == 1
    assert ids == ["first-original", "second-original"] * 2
    assert read(tmp_path / "second" / "receipt.json") == {"outcome": "applied"}
    assert not (tmp_path / "first" / "receipt.json").exists()


@pytest.mark.parametrize("waiting", ["agent-stop", "coordinator", "agent-start", None])
def test_runtime_transition_keeps_coordinator_and_all_agent_readiness_barriers(tmp_path, monkeypatch, waiting):
    atomic(tmp_path / "irreversible.json", {})
    hosts = {name: {"expected_root_id": name, "source_release": {"id": "old"}}
             for name in ("coordinator", "first", "second")}
    for name in hosts:
        atomic(tmp_path / (name + "-candidate.json"), {"images": {}})
    calls = []
    operation = SimpleNamespace(
        directory=tmp_path, receipts=tmp_path / "receipts", operator=object(),
        intent={"hosts": hosts, "agents": {"first": {}, "second": {}},
                "target_path": "/release.json", "operation_id": "upgrade",
                "check_selection": {"coordinator_id": "coordinator"}},
        recheck=lambda: None, gate=lambda: None, probes=lambda: None,
    )
    def call(name, action, **values):
        calls.append((name, action))
        if waiting == "coordinator" and action == "upgrade-replace":
            raise upgrades._Waiting("coordinator starting")
    def call_many(batch):
        calls.append(tuple((name, action) for name, action, _ in batch))
        action = batch[0][1]
        if ((waiting == "agent-stop" and action == "upgrade-stop")
                or (waiting == "agent-start" and action == "upgrade-replace")):
            raise upgrades._Waiting("agent transition pending")
    operation.call, operation.call_many = call, call_many
    monkeypatch.setattr(upgrades, "phase", lambda *args: None)
    monkeypatch.setattr(upgrades, "_capable", lambda *args: None)
    def capacity(*args):
        calls.append("capacity")
        raise upgrades._Waiting("capacity pending")
    monkeypatch.setattr(upgrades, "_independent_policies", capacity)
    with pytest.raises(upgrades._Waiting):
        upgrades._continue(operation)
    expected = [(("first", "upgrade-stop"), ("second", "upgrade-stop")),
                ("coordinator", "upgrade-stop"), ("coordinator", "upgrade-replace"),
                (("first", "upgrade-replace"), ("second", "upgrade-replace")), "capacity"]
    limit = {"agent-stop": 1, "coordinator": 3, "agent-start": 4, None: 5}[waiting]
    assert calls == expected[:limit]


def test_completed_check_retry_replays_after_admission_reopens(tmp_path, monkeypatch):
    operation = SimpleNamespace(directory=tmp_path, inventory=object(), recheck=lambda: None)
    atomic(tmp_path / "checks.json", {"worker:cpu": [
        {"operation_id": "failed", "previous_check_id": None},
        {"operation_id": "successor", "previous_check_id": "failed"},
    ]})
    monkeypatch.setattr(upgrades.sshops, "_directory", lambda *args: tmp_path)
    completed = {"state": "complete"}
    monkeypatch.setattr(upgrades, "_continue", lambda op: completed)
    # There is no maintenance gate to acquire after this operation completed.
    assert upgrades._retry_check(operation, "failed", "successor") == completed
    with pytest.raises(upgrades.QueueConflictError, match="another successor"):
        upgrades._retry_check(operation, "failed", "different-successor")
    assert len(read(tmp_path / "checks.json")["worker:cpu"]) == 2


def test_workload_waiting_observations_do_not_requalify(tmp_path, monkeypatch):
    operation = object.__new__(workload_upgrades.WorkloadUpgrade)
    operation.directory = tmp_path
    release = {"release_id": "current"}
    operation.intent = {
        "release": release, "candidates": {"agent": {"target": {}}},
        "hosts": {"agent": {"host": "host", "source_release": release,
                             "expected_root_id": "root"}},
    }
    atomic(tmp_path / "agent-candidate.json", {"intent_digest": digest(operation.intent)})
    calls = []
    observed = {"installed": release, "native_owner": {
        "owner": "root", "value": {"ownership": "live",
                                    "capabilities": [workload_upgrades.CAPABILITY]}}}

    def ssh(host, request):
        calls.append(request["action"])
        return observed

    monkeypatch.setattr(upgrades.sshops, "ssh", ssh)
    for _ in range(50):
        operation.probes()
    assert calls == ["inspect"] * 50
    observed["native_owner"]["owner"] = "replacement-root"
    with pytest.raises(upgrades.QueueConflictError, match="root identity changed"):
        operation.probes()


def test_runtime_retained_qualification_still_observes_live_owner(tmp_path, monkeypatch):
    operation = object.__new__(upgrades._Upgrade)
    release = {"release_id": "candidate"}
    source = {"release_id": "previous"}
    operation.directory = tmp_path
    operation.intent = {"release": release, "target_path": "/candidate/release.json",
                        "hosts": {"agent": {"host": "host", "source_release": source,
                                             "expected_root_id": "root"}}}
    atomic(tmp_path / "agent-candidate.json", {"images": {"/image": "sha"}})
    observed = {"installed": source, "native_owner": {
        "owner": "root", "value": {"ownership": "live"}}}
    calls = []

    def ssh(host, request):
        calls.append(request["action"])
        return observed

    monkeypatch.setattr(upgrades.sshops, "ssh", ssh)
    for _ in range(50):
        operation.probes()
    assert calls == ["inspect"] * 50
    observed["native_owner"]["value"]["ownership"] = "stopped"
    with pytest.raises(upgrades._Waiting, match="readiness"):
        operation.probes()
    observed["installed"] = {"release_id": "unrelated"}
    with pytest.raises(upgrades.QueueConflictError, match="release changed"):
        operation.probes()


def test_changed_image_refuses_at_staging_before_qualification(tmp_path, monkeypatch):
    image = tmp_path / "candidate.sif"
    image.write_bytes(b"qualified candidate")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    image.write_bytes(b"replaced after qualification")
    monkeypatch.setattr(_workload_host, "qualify", lambda *args: pytest.fail("changed image qualified"))
    with pytest.raises(upgrades.QueueConflictError, match="image digest mismatch"):
        _workload_host.stage({"image": str(image), "image_sha256": digest})


def test_workload_preparation_is_retained_only_after_success(tmp_path, monkeypatch):
    operation = object.__new__(workload_upgrades.WorkloadUpgrade)
    operation.directory = tmp_path
    release = {"release_id": "current"}
    target = {"profile": "qualified"}
    operation.intent = {
        "release": release, "candidates": {"agent": {"target": target}},
        "workload_profile": "profile", "image": "/candidate", "image_sha256": "sha",
        "hosts": {"agent": {"host": "host", "source_release": release,
                             "expected_root_id": "root"}},
    }
    observed = {"installed": release, "native_owner": {
        "owner": "root", "value": {"ownership": "live",
                                    "capabilities": [workload_upgrades.CAPABILITY]}}}
    monkeypatch.setattr(upgrades.sshops, "ssh", lambda *args: observed)
    calls = []
    def qualify(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise upgrades.QueueConflictError("candidate mount disappeared")
        return {"target": target}
    operation.host_observe = qualify
    with pytest.raises(upgrades.QueueConflictError, match="mount disappeared"):
        operation.probes()
    assert not (tmp_path / "agent-candidate.json").exists()
    for _ in range(50):
        operation.probes()
    assert len(calls) == 2


@pytest.mark.parametrize("changed", [None, "image", "root", "declaration", "binding"])
def test_apply_reuses_only_exact_current_preview_qualification(tmp_path, monkeypatch, changed):
    operation = object.__new__(workload_upgrades.WorkloadUpgrade)
    operation.directory = tmp_path
    image = tmp_path / "image.sif"
    image.write_bytes(b"qualified")
    release = {"release_id": "current"}
    operation.intent = {
        "release": release, "candidates": {"agent": {"target": {}}},
        "workload_profile": "profile", "image": str(image),
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "hosts": {"agent": {"host": "host", "source_release": release,
                             "expected_root_id": "root"}},
    }
    operation._preview_qualification = deepcopy(operation.intent)
    observed = {"installed": release, "native_owner": {
        "owner": "root", "value": {"ownership": "live", "capabilities": [workload_upgrades.CAPABILITY]}}}
    def recheck():
        if changed == "declaration":
            raise upgrades.QueueConflictError("composed role changed")
    operation.recheck = recheck
    qualifications = []
    operation.host_observe = lambda *a, **k: qualifications.append(a) or {"target": {}}
    monkeypatch.setattr(upgrades.sshops, "ssh", lambda *a: observed)
    if changed == "image":
        image.write_bytes(b"replaced")
    elif changed == "root":
        observed["native_owner"]["owner"] = "other-root"
    elif changed == "binding":
        operation._preview_qualification["workload_profile"] = "another-profile"
    if changed in {"image", "root", "declaration"}:
        with pytest.raises(upgrades.QueueConflictError):
            operation.probes()
        assert not (tmp_path / "agent-candidate.json").exists()
    else:
        operation.probes()
        assert read(tmp_path / "agent-candidate.json") == {"intent_digest": digest(operation.intent)}
        assert len(qualifications) == (1 if changed == "binding" else 0)


def test_probe_qualifies_source_once_and_reuses_it_for_promotion(tmp_path, monkeypatch):
    from loom.queue import _profile_promotion

    image = tmp_path / "candidate.sif"
    image.write_bytes(b"image stand-in")
    declaration = {"resident_profiles": [{"descriptor": {"profile_id": "profile"},
                                           "container": {"kind": "apptainer", "container": {}}}]}
    request = {"name": "agent", "config": str(tmp_path / "role.json"),
               "image": str(image), "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
               "workload_profile": "profile"}
    monkeypatch.setattr(_workload_host, "payload", lambda request: declaration)
    monkeypatch.setattr(_workload_host, "environment", lambda request: None)
    monkeypatch.setattr(_workload_host, "owner", lambda request: {"owner": "root"})
    qualified = []
    def load(path, **kwargs):
        value = json.loads(Path(path).read_text())
        descriptor = value["resident_profiles"][0]["descriptor"]
        service = SimpleNamespace(immutable_fingerprint="immutable", active_fingerprint="active",
                                  client=SimpleNamespace(resident_profiles=[SimpleNamespace(
                                      descriptor=SimpleNamespace(to_dict=lambda: descriptor))]))
        qualified.append(service)
        return service
    monkeypatch.setattr(_workload_host, "load_outbound_agent_service_config", load)
    checked = []
    monkeypatch.setattr(_profile_promotion, "validate_candidate",
                        lambda source, target, profile: checked.append((source, target, profile)))
    _workload_host.probe(request)
    assert len(qualified) == 2
    assert checked == [(qualified[0].client, qualified[1].client, "profile")]


def test_upgrade_dispatches_every_slot_before_waiting_or_download(tmp_path, monkeypatch):
    names = ("first", "second", "third")
    operation = SimpleNamespace(
        directory=tmp_path, inventory=object(), observation=None,
        intent={"operation_id": "upgrade", "timeout_seconds": 30,
                "agents": {name: {} for name in names},
                "declarations": {name: {"resident_profiles": [{"gpu_devices": ["gpu"]}]}
                                 for name in names}},
        maintenance=lambda *args: None,
        settled=lambda: pytest.fail("pending GPU cannot reopen admission"),
    )
    prepared, dispatched, observed = {}, set(), set()

    def prepare(op, name, kind, identity):
        prepared[identity] = (name, kind)
        return {"operation_id": identity, "authorization": {}}

    def check(inventory, *, operation_id, timeout_seconds, _dispatch_only, _wait):
        assert _wait is False
        if _dispatch_only:
            dispatched.add(operation_id)
            return {"outcome": "waiting"}
        assert len(dispatched) == 9
        observed.add(operation_id)
        pending = prepared[operation_id] == ("first", "gpu")
        return {
            "outcome": "waiting" if pending else "passed",
            "checks": {prepared[operation_id][1]: {
                "operation_id": operation_id + "-native",
                "outcome": "waiting" if pending else "passed",
                "code": "waiting_for_capacity" if pending else None,
            }},
        }

    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", check)
    with pytest.raises(upgrades._Waiting, match="checks pending"):
        upgrades._run_checks(operation)
    assert observed == dispatched and len(dispatched) == 9
    assert len(read(tmp_path / "checks.json")) == 9
    results = [read(path) for path in tmp_path.glob("check-*-result.json")]
    assert sum(row["outcome"] == "passed" for row in results) == 8
    assert len(operation.check_observations) == 9
    pending = [row for row in operation.check_observations.values() if row["outcome"] == "waiting"]
    assert pending[0]["checks"]["gpu"]["code"] == "waiting_for_capacity"


def test_upgrade_finishes_other_observations_after_one_check_error(tmp_path, monkeypatch):
    operation = SimpleNamespace(
        directory=tmp_path, inventory=object(), observation=None,
        intent={"operation_id": "upgrade", "timeout_seconds": 30,
                "agents": {"agent": {}},
                "declarations": {"agent": {"resident_profiles": [{}]}}},
        maintenance=lambda *args: None,
    )
    identities = {}
    def prepare(op, name, kind, identity):
        identities[kind] = identity
        return {"operation_id": identity, "authorization": {}}
    def check(inventory, *, operation_id, timeout_seconds, _dispatch_only, _wait):
        if not _dispatch_only and operation_id == identities["cpu"]:
            raise OSError("temporary observation failure")
        return {"outcome": "passed"}
    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", check)
    with pytest.raises(OSError, match="temporary observation"):
        upgrades._run_checks(operation)
    assert read(tmp_path / (identities["storage"] + "-result.json"))["outcome"] == "passed"
