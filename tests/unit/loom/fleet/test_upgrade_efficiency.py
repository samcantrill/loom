"""Waiting cost, independent progress and immutable activation boundaries."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.fleet import upgrades, workload_upgrades, _workload_host
from loom.fleet._host import atomic, read, digest


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

    def check(inventory, *, operation_id, timeout_seconds, _dispatch_only):
        if _dispatch_only:
            dispatched.add(operation_id)
            return {"outcome": "waiting"}
        assert len(dispatched) == 9
        observed.add(operation_id)
        return {"outcome": "waiting" if prepared[operation_id] == ("first", "gpu") else "passed"}

    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", check)
    with pytest.raises(upgrades._Waiting, match="checks pending"):
        upgrades._run_checks(operation)
    assert observed == dispatched and len(dispatched) == 9
    assert len(read(tmp_path / "checks.json")) == 9
    results = [read(path) for path in tmp_path.glob("check-*-result.json")]
    assert sum(row["outcome"] == "passed" for row in results) == 8


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
    def check(inventory, *, operation_id, timeout_seconds, _dispatch_only):
        if not _dispatch_only and operation_id == identities["cpu"]:
            raise OSError("temporary observation failure")
        return {"outcome": "passed"}
    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", check)
    with pytest.raises(OSError, match="temporary observation"):
        upgrades._run_checks(operation)
    assert read(tmp_path / (identities["storage"] + "-result.json"))["outcome"] == "passed"
