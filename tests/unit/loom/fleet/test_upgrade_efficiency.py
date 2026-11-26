"""Waiting cost, independent progress and immutable activation boundaries."""
import hashlib
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from threading import Event
from contextlib import contextmanager

from typing import Any

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
def test_independent_controls_dispatch_all_agents_but_require_every_ack(kind, tmp_path):
    submitted, verified = [], []
    acknowledged = {"second"}

    def policy(name, key, selected_kind, predecessor):
        assert selected_kind == kind and predecessor == "previous-" + name
        if key not in submitted:
            submitted.append(key)
        if name not in acknowledged:
            raise upgrades._Waiting("pending: " + name)
        return key

    def policy_steps(name, *args):
        return (yield from upgrades.sshops.rpc((name, "policy"), policy, name, *args))

    def verify(name, identity):
        verified.append(identity)
        yield from ()

    operation = SimpleNamespace(directory=tmp_path, deadline=None, policy_steps=policy_steps, verify_policy_steps=verify)
    requests = [(name, name + "-control", kind, "previous-" + name)
                for name in ("first", "second", "third")]
    with pytest.raises(upgrades._Waiting, match="pending"):
        upgrades._independent_policies(operation, requests)
    assert set(submitted) == {"first-control", "second-control", "third-control"}
    assert verified == ["second-control"]
    acknowledged.update(("first", "third"))
    upgrades._independent_policies(operation, requests)
    assert len(submitted) == 3
    assert set(verified[-3:]) == set(submitted)


def test_independent_controls_do_not_hide_predecessor_failure(tmp_path):
    def policy(*args):
        raise upgrades.QueueConflictError("agent control predecessor conflicts")
    operation = SimpleNamespace(directory=tmp_path, deadline=None,
        policy_steps=lambda *args: upgrades.sshops.rpc(("policy",), policy, *args),
        verify_policy_steps=lambda *args: pytest.fail("unaccepted"))
    with pytest.raises(upgrades.QueueConflictError, match="predecessor"):
        upgrades._independent_policies(operation, [("agent", "control", "resume", "old")])


def test_host_batch_starts_peer_and_retains_success_when_first_host_waits(tmp_path, monkeypatch):
    from loom.fleet import ssh_operations
    from loom.fleet._startup import ServiceStarting

    from tests.unit.loom.fleet.test_host_dispatch import operation as fixture_operation
    operation = fixture_operation(tmp_path, monkeypatch)
    second_started = Event()
    launches = []
    def ssh(host, request):
        if request["action"] == "receipt":
            return None
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
    assert read(operation.receipts / "second-upgrade-replace/receipt.json") == {"outcome": "applied"}
    assert not (operation.receipts / "first-upgrade-replace/receipt.json").exists()



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
        intent={"kind": "runtime-upgrade", "hosts": hosts, "agents": {"first": {}, "second": {}},
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
    operation = SimpleNamespace(directory=tmp_path, inventory=object(), intent={"gpu_qualification": "exclusive"}, recheck=lambda: None)
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
    operation: Any = object.__new__(workload_upgrades.WorkloadUpgrade)
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
    operation: Any = object.__new__(upgrades._Upgrade)
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
    operation: Any = object.__new__(workload_upgrades.WorkloadUpgrade)
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
    operation: Any = object.__new__(workload_upgrades.WorkloadUpgrade)
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
    def validate(source, target, profile, **policy_changes):
        assert policy_changes == {"add_container_policies": False, "increase_publication_budgets": False}
        checked.append((source, target, profile))
    monkeypatch.setattr(_profile_promotion, "validate_candidate", validate)
    _workload_host.probe(request)
    assert len(qualified) == 2
    assert checked == [(qualified[0].client, qualified[1].client, "profile")]


def test_upgrade_dispatches_every_slot_before_waiting_or_download(tmp_path, check_gate, monkeypatch):
    from threading import Event

    names = ("first", *(f"agent-{index}" for index in range(2, 9)))
    operation = SimpleNamespace(
        directory=tmp_path, inventory=object(), observation=None,
        intent={"operation_id": "upgrade", "timeout_seconds": 30,
                "agents": {name: {} for name in names},
                "declarations": {name: {"resident_profiles": [{"gpu_devices": ["gpu"]}]}
                                 for name in names}},
        gate=check_gate.observe, maintenance=check_gate.authorize,
        settled=lambda **kw: pytest.fail("pending GPU cannot reopen admission"),
    )
    prepared, dispatched, observed = {}, set(), set()
    storage_published = Event()
    write = upgrades.atomic

    def publish(path, value):
        write(path, value)
        if path.name == upgrades._check_identity(operation, "first", "storage") + "-result.json":
            storage_published.set()

    monkeypatch.setattr(upgrades, "atomic", publish)

    def prepare(op, name, kind, identity, **kw):
        prepared[identity] = (name, kind)
        return {"operation_id": identity, "authorization": {}}

    def check(inventory, *, operation_id, timeout_seconds, _dispatch_only, _wait, _collect):
        assert _wait is False
        if _dispatch_only:
            dispatched.add(operation_id)
            return {"outcome": "waiting"}
        assert len(dispatched) == 24
        observed.add(operation_id)
        if prepared[operation_id] == ("first", "cpu"):
            assert storage_published.wait(timeout=5), "later completed check was never published"
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
    assert observed == dispatched and len(dispatched) == 24
    assert len(read(tmp_path / "checks.json")) == 24
    results = [read(path) for path in tmp_path.glob("check-*-result.json")]
    assert sum(row["outcome"] == "passed" for row in results) == 23
    assert len(operation.check_observations) == 24
    pending = [row for row in operation.check_observations.values() if row["outcome"] == "waiting"]
    assert pending[0]["checks"]["gpu"]["code"] == "waiting_for_capacity"


@pytest.mark.parametrize("stalls", [False, True])
def test_upgrade_spends_remaining_watch_time_on_growing_transfer(tmp_path, check_gate, monkeypatch, stalls):
    operation = SimpleNamespace(
        directory=tmp_path, inventory=object(), observation=None,
        intent={"operation_id": "upgrade", "timeout_seconds": 30, "agents": {"agent": {}},
                "declarations": {"agent": {"resident_profiles": [{}]}}},
        gate=check_gate.observe, maintenance=check_gate.authorize, settled=lambda **kwargs: None,
    )
    kinds = {}
    turns = {"cpu": 0, "storage": 0}

    def prepare(owner, name, kind, identity, **kwargs):
        kinds[identity] = kind
        return {"operation_id": identity, "authorization": {}}

    def check(inventory, *, operation_id, _dispatch_only, timeout_seconds, **kwargs):
        kind = kinds[operation_id]
        if _dispatch_only:
            return {"outcome": "waiting", "checks": {kind: {"disposition": "accepted"}}}
        turns[kind] += 1
        if turns[kind] == 1:
            assert 0 < timeout_seconds <= 10.0
        else:
            assert 10.0 < timeout_seconds <= 30.0
        if kind == "storage" and (stalls or turns[kind] < 3):
            progress = 4096 if stalls else 4096 * turns[kind]
            return {"outcome": "waiting", "checks": {kind: {"outcome": "waiting",
                    "code": "publication_deadline_exceeded", "transfer": {"received_bytes": progress}}}}
        return {"outcome": "passed", "checks": {kind: {"outcome": "passed"}}}

    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", check)
    if stalls:
        with pytest.raises(upgrades._Waiting, match="checks pending"):
            upgrades._run_checks(operation)
        assert turns == {"cpu": 1, "storage": 2}
    else:
        upgrades._run_checks(operation)
        assert turns == {"cpu": 1, "storage": 3}
    assert len(read(tmp_path / "checks.json")) == 2


def test_upgrade_finishes_other_observations_after_one_check_error(tmp_path, check_gate, monkeypatch):
    operation = SimpleNamespace(
        directory=tmp_path, inventory=object(), observation=None,
        intent={"operation_id": "upgrade", "timeout_seconds": 30,
                "agents": {"agent": {}},
                "declarations": {"agent": {"resident_profiles": [{}]}}},
        gate=check_gate.observe, maintenance=check_gate.authorize,
    )
    identities = {}
    def prepare(op, name, kind, identity, **kw):
        identities[kind] = identity
        return {"operation_id": identity, "authorization": {}}
    def check(inventory, *, operation_id, timeout_seconds, _dispatch_only, _wait, _collect):
        if not _dispatch_only and operation_id == identities["cpu"]:
            raise OSError("temporary observation failure")
        return {"outcome": "passed"}
    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", check)
    with pytest.raises(OSError, match="temporary observation"):
        upgrades._run_checks(operation)
    assert read(tmp_path / (identities["storage"] + "-result.json"))["outcome"] == "passed"


def test_check_watcher_detaches_while_storage_owns_worker_and_resumes_same_ids(tmp_path, check_gate, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    operation = SimpleNamespace(
        directory=tmp_path, inventory=object(), observation=None,
        intent={"operation_id": "upgrade", "timeout_seconds": 0.8,
                "agents": {"agent": {}}, "declarations": {"agent": {"resident_profiles": [{}]}}},
        gate=check_gate.observe, maintenance=check_gate.authorize, settled=lambda **kw: None,
    )
    ids, submitted, storage_calls = {}, [], []
    entered, release, finished = Event(), Event(), Event()

    def prepare(op, name, kind, identity, **kw):
        ids[kind] = identity
        return {"operation_id": identity, "authorization": {}}

    def check(inventory, *, operation_id, timeout_seconds, _dispatch_only, _wait, _collect):
        if _dispatch_only:
            submitted.append(operation_id)
            return {"outcome": "waiting", "checks": {"probe": {
                "operation_id": operation_id, "outcome": "waiting", "disposition": "accepted",
            }}}
        if operation_id == ids["storage"]:
            storage_calls.append(operation_id)
            entered.set()
            assert release.wait(8)
            finished.set()
        return {"outcome": "passed"}

    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", check)
    with ThreadPoolExecutor(max_workers=1) as caller:
        try:
            first = caller.submit(upgrades._run_checks, operation)
            assert entered.wait(3)
            with pytest.raises(upgrades._Waiting):
                first.result(timeout=3)
            assert not finished.is_set()
            assert read(tmp_path / (ids["cpu"] + "-result.json"))["outcome"] == "passed"
            assert operation.check_observations[ids["storage"]]["operation_id"] == ids["storage"]
            with pytest.raises(upgrades._Waiting):
                caller.submit(upgrades._run_checks, operation).result(timeout=3)
            assert storage_calls == [ids["storage"]]
            assert set(submitted) == set(ids.values()) and len(submitted) == 2
        finally:
            release.set()
        assert finished.wait(3)
        upgrades._run_checks(operation)
    assert all(row["outcome"] == "passed" for row in operation.check_observations.values())
    assert len(submitted) == 2


def test_check_preparation_uses_fair_slice_and_reports_later_checks(tmp_path, check_gate, monkeypatch):
    from threading import Event
    import time

    op = SimpleNamespace(
        directory=tmp_path, inventory=object(),
        intent={"operation_id": "budget", "agents": {"slow": {}, "fast": {}},
                "declarations": {name: {"resident_profiles": [{}]} for name in ("slow", "fast")},
                "timeout_seconds": 1.6},
        gate=check_gate.observe, maintenance=check_gate.authorize, settled=lambda **kw: None,
    )
    slow = upgrades._check_identity(op, "slow", "cpu")
    ready = False
    def prepare(op, name, check, identity, *, deadline, revision):
        if identity == slow and not ready:
            budget = deadline - time.monotonic()
            assert 0 < budget < 0.3
            Event().wait(budget)
            raise upgrades._Waiting("slow preparation")
        return {"operation_id": identity, "authorization": {"slot": [name, check]}}

    def step(inventory, *, operation_id, _dispatch_only, **opts):
        if _dispatch_only:
            return {"checks": {"check": {"disposition": "accepted"}}}
        return {"outcome": "passed"}

    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", step)
    with pytest.raises(upgrades._Waiting, match="slow preparation"):
        upgrades._run_checks(op)
    assert op.check_observations[slow]["checks"]["cpu"]["disposition"] == "pending"
    assert sum(row["outcome"] == "passed" for row in op.check_observations.values()) == 3
    ready = True
    upgrades._run_checks(op)
    assert len(check_gate.checks) == 4
    assert {row["outcome"] for row in op.check_observations.values()} == {"passed"}


def test_uncertain_grant_fences_next_revision_and_reconciles_live_owner(tmp_path, check_gate, monkeypatch):
    lost = []
    def grant(key, action, authorization, **budget):
        result = check_gate.authorize(key, action, authorization, **budget)
        if not lost:
            lost.append(key.removeprefix("authorize-"))
            raise upgrades.CoordinatorClientError("unavailable", operation="operator_maintenance_control",
                                                  boundary="transport", mutation_outcome="unknown")
        return result

    op = SimpleNamespace(
        directory=tmp_path, inventory=object(),
        intent={"operation_id": "window", "agents": {"worker": {}},
                "declarations": {"worker": {"resident_profiles": [{}]}}, "timeout_seconds": 10},
        gate=check_gate.observe, maintenance=grant, settled=lambda **kw: None,
    )
    monkeypatch.setattr(upgrades, "_prepare_attempt", lambda op, name, check, identity, **kw: {
        "operation_id": identity, "authorization": {"check": check},
    })
    dispatch = []
    def step(inventory, *, operation_id, _dispatch_only, **options):
        if _dispatch_only:
            dispatch.append(operation_id)
            return {"checks": {"probe": {"disposition": "accepted"}}}
        return {"outcome": "passed"}
    monkeypatch.setattr(upgrades, "self_test", step)
    with pytest.raises(upgrades.CoordinatorClientError):
        upgrades._run_checks(op)
    assert list(check_gate.checks) == lost and not dispatch
    assert len(op.check_observations) == 2
    binding = check_gate.checks[lost[0]]
    check_gate.checks[lost[0]] = {"check": "another-binding"}
    with pytest.raises(upgrades.QueueConflictError, match="authorization changed"):
        upgrades._run_checks(op)
    assert not dispatch
    check_gate.checks[lost[0]] = binding
    upgrades._run_checks(op)
    assert set(dispatch) == set(check_gate.checks) and len(dispatch) == 2


def test_gate_grant_can_outlast_one_of_twenty_four_preparation_slices(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(upgrades, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    grants = {}
    def gate(**kwargs):
        return {"revision": len(grants), "checks": dict(grants)}
    def authorize(key, action, authorization, *, deadline, revision):
        clock[0] += 1.6  # Protected inventory and release recheck before the RPC.
        if clock[0] >= deadline:
            raise upgrades._Waiting("grant budget elapsed")
        assert revision == len(grants)
        identity = key.removeprefix("authorize-")
        assert identity not in grants
        grants[identity] = authorization
        return {"gate": gate()}
    def prepare(op, name, check, identity, *, deadline, revision):
        return {"operation_id": identity, "authorization": {"identity": identity}}
    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    op = SimpleNamespace(directory=tmp_path, gate=gate, maintenance=authorize)
    slots = {str(i): (str(i), str(i), "cpu") for i in range(24)}
    attempts = {}
    first, _ = upgrades._authorize_check_slots(op, slots, attempts, 60.0, lambda: None)
    assert 0 < len(first) < 24
    second, errors = upgrades._authorize_check_slots(op, slots, attempts, clock[0] + 60, lambda: None)
    assert not errors and set(second) == set(slots) == set(grants)


def test_outstanding_gpu_probe_gets_budget_before_eleven_retained_profiles(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(upgrades, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    names = [str(n) for n in range(12)]
    op = SimpleNamespace(receipts=tmp_path, check_observations={})
    for name in names:
        key = tmp_path / (name + "-gpu-capability")
        key.mkdir()
        upgrades.atomic(key / "receipt.json", {"outcome": "passed"})
    # A failed predecessor with a selected successor still needs a physical turn.
    upgrades.atomic(tmp_path / "11-gpu-capability" / "successors.json", [{"step_key": "11-retry"}])
    observed = []
    def probe(op, name, declaration, deadline):
        if name == "11":
            clock[0] += 5.0
            assert clock[0] < deadline
        observed.append(name)
    monkeypatch.setattr(upgrades, "_gpu_capability", probe)
    pending, passed = upgrades._gpu_checks_to_observe(op, names)
    assert not upgrades._observe_gpu_checks(op, dict.fromkeys(names), pending, 60)
    assert observed == ["11"]
    assert all(row["outcome"] == "passed" for row in op.check_observations.values())
    assert not upgrades._observe_gpu_checks(op, dict.fromkeys(names), passed, 60, final=True)
    assert observed == ["11", *names[:-1]]


def test_full_transfer_budget_preserves_a_status_slot_with_24_pending_checks(tmp_path):
    from threading import Event
    from time import monotonic
    from loom.fleet._check_workers import completed_steps

    identities = [str(index) for index in range(24)]
    transfers = set(identities[:3])
    records = {key: {} for key in identities}
    entered = {key: Event() for key in identities[:2]}
    peer_finished = Event()
    deadline = monotonic() + 4
    def advance(key, dispatch, step_end):
        if key in entered:
            assert step_end == deadline
            entered[key].set()
            assert peer_finished.wait(2)
        elif key == "3":
            assert all(event.wait(2) for event in entered.values())
            peer_finished.set()
        return "passed"
    jobs = completed_steps(tmp_path, records, identities, transfers=transfers, dispatch=False,
                           deadline=deadline, advance=advance, started=lambda: None)
    assert {key for key, job in jobs if job.result() == "passed"} == set(identities)
    assert peer_finished.is_set()


def test_gpu_receipt_does_not_spend_download_budget_and_changed_final_profile_blocks(tmp_path, check_gate, monkeypatch):
    op = SimpleNamespace(
        directory=tmp_path, receipts=tmp_path / "steps", inventory=object(), observation=None,
        intent={"operation_id": "final-profile", "agents": {"host": {}},
                "declarations": {"host": {"resident_profiles": [{}]}},
                "gpu_qualification": "nonexclusive", "timeout_seconds": 5},
        gate=check_gate.observe, maintenance=check_gate.authorize,
        settled=lambda **kw: pytest.fail("changed profile must withhold settlement"),
    )
    path=op.receipts / "host-gpu-capability"
    path.mkdir(parents=True)
    upgrades.atomic(path / "receipt.json", {"outcome": "passed", "device_uuid": "original"})
    monkeypatch.setattr(upgrades, "_check_kinds", lambda *args: ("cpu", "storage", "gpu"))
    monkeypatch.setattr(upgrades, "_prepare_attempt", lambda op, name, kind, key, **kw:
                        {"operation_id": key, "authorization": {"kind":kind}})
    complete = False
    def observe(inventory, *, operation_id, _dispatch_only, **kw):
        if _dispatch_only:
            return {"checks":{"native":{"disposition":"accepted"}}}
        return {"outcome":"passed" if complete else "waiting"}
    monkeypatch.setattr(upgrades, "self_test", observe)
    confirmations = []
    def confirm(op, name, declaration, deadline):
        confirmations.append(name)
        raise upgrades.QueueConflictError("retained host intent differs")
    monkeypatch.setattr(upgrades, "_gpu_capability", confirm)
    with pytest.raises(upgrades._Waiting, match="checks pending"):
        upgrades._run_checks(op)
    assert not confirmations and op.check_observations["host:gpu-capability"]["device_uuid"] == "original"
    complete = True
    with pytest.raises(upgrades.QueueConflictError, match="retained host intent differs"):
        upgrades._run_checks(op)
    assert confirmations == ["host"]


def test_late_status_starts_while_two_earlier_transfers_remain_attached(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic

    from loom.fleet._check_workers import completed_steps

    entered = {name: Event() for name in ("a", "b", "c")}
    release = Event()
    def advance(name, kind, deadline):
        if kind == "transfer":
            entered[name].set()
            assert release.wait(5)
        return kind

    def run(names, transfers=()):
        return [future.result() for _, future in completed_steps(
            tmp_path, {name: {} for name in names}, names, transfers=transfers,
            dispatch=False, deadline=monotonic() + 5, advance=advance, started=lambda: None,
        )]

    with ThreadPoolExecutor(max_workers=1) as caller:
        initial = caller.submit(run, list(entered), set(entered))
        try:
            assert entered["a"].wait(2) and entered["b"].wait(2)
            assert run(["late-status"]) == ["observe"]
            assert not entered["c"].is_set()
        finally:
            release.set()
        assert initial.result(timeout=2) == ["transfer"] * 3


def test_follow_uses_native_revision_wakes_outside_writer_for_retained_operation(tmp_path, monkeypatch):
    from contextlib import nullcontext
    import fcntl
    from loom.fleet import self_tests

    inventory = SimpleNamespace(path=tmp_path / "fleet.json", name="lab")
    directory = upgrades.sshops._directory(inventory, "old-upgrade")
    directory.mkdir(mode=0o700, parents=True)
    # The preceding release retained no observer targets or milestone fields.
    upgrades.atomic(directory / "intent.json", {"kind": "runtime-upgrade", "operation_id": "old-upgrade"})
    check = tmp_path / "checks" / "old-check"
    check.mkdir(parents=True)
    upgrades.atomic(check / "intent.json", {"connection": "client.json", "coordinator_id": "owner"})
    monkeypatch.setattr(upgrades, "_environment_files", lambda *args: {})
    monkeypatch.setattr(upgrades, "_Upgrade", lambda inventory, path, intent, observation:
                        SimpleNamespace(intent=intent, directory=path, close=lambda: None, observation=observation))
    wakes = []
    turns = []
    def advance(operation):
        turns.append(operation.intent["operation_id"])
        if len(wakes) == 2:
            return {"state": "complete"}
        admission = {"state": "ACTIVE", "revision": 7, "admission_id": "admitted"} if wakes else None
        native = {"operation_id": "old-check", "operation": {"state": "applying"}, "admission": admission}
        operation.check_observations = {"old-check": upgrades._check_observation("old-check", {
            "outcome": "waiting", "checks": {"storage": {"outcome": "waiting", "native": native}},
        })}
        raise upgrades._Waiting("native check pending")

    def wake(*args):
        # A second process may acquire this exact operation writer during a wait.
        with (directory / "writer.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        wakes.append(args[:-1])
        return SimpleNamespace(kind=SimpleNamespace(value="CHANGED"))

    client = SimpleNamespace(wait_operation=wake, wait_admission=wake)
    def connect(path, *, expected_coordinator_id):
        assert (path, expected_coordinator_id) == ("client.json", "owner")
        return nullcontext(client)

    monkeypatch.setattr(self_tests.CoordinatorClient, "from_connection_file", connect)
    monkeypatch.setattr(upgrades, "_continue", advance)
    assert upgrades.upgrade(inventory, operation_id="old-upgrade")["outcome"] == "waiting"
    assert not wakes
    result = upgrades.upgrade(inventory, operation_id="old-upgrade", follow=True, timeout_seconds=5)
    assert result["outcome"] == "complete"
    assert wakes == [("old-check",), ("admitted", 7)]
    assert turns == ["old-upgrade"] * 4


def test_follow_has_one_deadline_and_returns_publication_hold_immediately(tmp_path, monkeypatch):
    from time import monotonic
    inventory = SimpleNamespace(path=tmp_path / "fleet.json")
    turns = []
    def waiting(**opts):
        turns.append(opts["operation_id"])
        return {"outcome": "waiting", "publication_ready": False}
    monkeypatch.setattr(upgrades, "_upgrade", waiting)
    now = monotonic()
    assert upgrades.upgrade(inventory, operation_id="window", follow=True, timeout_seconds=0.05)["outcome"] == "waiting"
    assert 0.04 <= monotonic() - now < 1 and turns == ["window"]
    monkeypatch.setattr(upgrades, "_upgrade", lambda **opts: {"outcome": "waiting", "publication_ready": True})
    monkeypatch.setattr(upgrades, "wait_for_checks", lambda *a: pytest.fail("explicit release required"))
    assert upgrades.upgrade(inventory, operation_id="window", follow=True)["publication_ready"]
    denied = {"outcome": "waiting", "check_observations": {"check": {"checks": {"cpu": {
        "outcome": "waiting", "code": "unauthorized",
    }}}}}
    monkeypatch.setattr(upgrades, "_upgrade", lambda **opts: denied)
    assert upgrades.upgrade(inventory, operation_id="window", follow=True) == denied



def test_follow_rotates_native_watches_across_pending_checks(tmp_path, monkeypatch):
    from loom.fleet._check_workers import WORKERS

    inventory = SimpleNamespace(path=tmp_path / "fleet.json")
    checks = {str(i): {"checks": {"cpu": {"outcome": "waiting", "wait_for": {"operation_id": str(i)}}}}
              for i in range(6)}
    watched = []
    def watch(directory, targets, deadline, native_wait):
        available = targets[:WORKERS]
        watched.append([identity for identity, _ in available])
        return len(available)
    def advance(**options):
        if len(watched) == 2:
            return {"outcome": "complete"}
        return {"outcome": "waiting", "check_observations": checks}

    monkeypatch.setattr(upgrades, "wait_for_checks", watch)
    monkeypatch.setattr(upgrades, "_upgrade", advance)
    result = upgrades.upgrade(inventory, operation_id="window", follow=True, timeout_seconds=5)
    assert result["outcome"] == "complete"
    assert watched == [["0", "1", "2"], ["3", "4", "5"]]
