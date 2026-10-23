"""Staged runtime retirement preserves native identity and startup recovery."""

from dataclasses import replace
import hashlib
import json

import pytest

from loom.queue import LocalDaemon
from loom.queue._coordinator_retirement import stage_retirement
from loom.queue.deployment import load_coordinator_service_config
from loom.queue.errors import QueueError
from loom.queue.local_daemon import CoordinatorSchedulingReload
from tests.integration.queue.test_maintenance_admission import change, operator
from tests.unit.loom.queue.test_deployment import _coordinator_config, _write_protected

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("change", [None, "policy", "scope", "source-mode"])
def test_submitted_preparation_retirement_preserves_execution_permissions(tmp_path, change):
    from loom.queue._preparation_policy import SubmittedPreparationProfile
    from loom.queue.local_daemon import _validate_retired_coordinator_execution
    from tests.integration.queue.test_maintenance_admission import service
    from tests.unit.loom.queue.test_submitted_container_policy import _submitted

    selected = service(tmp_path)
    policy, _, _, _ = _submitted(tmp_path)
    preparation = selected.daemon.preparation_policy
    installed = preparation.profiles["existing-project"]
    old = SubmittedPreparationProfile(
        policy.capability, installed.allowed_source_roots, ("shared",),
        installed.runtime_options,
        {"capability": "shared-execution-v1", "roots": policy.capability.workload_roots, "locations": []},
        policy.shared_roots,
    )
    capability = replace(old.capability,
        shared_roots={"workloads": old.capability.shared_roots["workloads"]},
        environment_fingerprint="sha256:" + "b" * 64)
    narrowed = replace(old, capability=capability,
        shared_scope={**old.shared_scope, "roots": capability.workload_roots},
        image_roots={"workloads": old.image_roots["workloads"]})
    if change == "policy":
        narrowed = replace(narrowed, capability=replace(capability, policy_id="different"))
    elif change == "scope":
        narrowed = replace(narrowed, shared_scope={**narrowed.shared_scope,
            "roots": {"new-data": old.shared_scope["roots"]["data"]}})
    elif change == "source-mode":
        narrowed = replace(narrowed, source_modes=("shared", "staged"))
    before = replace(selected.daemon,
        container_capabilities=(old.capability,),
        preparation_policy=replace(preparation, profiles={"submitted": old}))
    after = replace(before,
        container_capabilities=(capability,),
        preparation_policy=replace(preparation, profiles={"submitted": narrowed}))
    if change is None:
        _validate_retired_coordinator_execution(before, after)
    else:
        with pytest.raises(QueueError, match="coordinator retirement cannot"):
            _validate_retired_coordinator_execution(before, after)


def test_stopped_retirement_records_target_and_recovers_deleted_predecessor(tmp_path):
    source = _coordinator_config(tmp_path)
    before = json.loads(source.read_text())
    before["local_agent"] = None
    before["agent_policy"]["local_owner"] = {
        "actions": ["scheduling_reload", "maintenance"], "agent_ids": [], "pools": [],
    }
    obsolete = tmp_path / "obsolete"
    obsolete.mkdir()
    (obsolete / "challenge").write_bytes(b"old")
    before["shared_roots"] = {"obsolete": {
        "host_path": str(obsolete), "container_path": "/loom/obsolete", "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"old").hexdigest()},
    }}
    _write_protected(source, before)
    service = load_coordinator_service_config(source)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon)
    started = daemon.start()
    after = {**before, "shared_roots": {}}
    candidate = source.with_name("candidate.json")
    _write_protected(candidate, after)
    change(daemon, "close")
    gate = operator(daemon).observe_maintenance()
    request = CoordinatorSchedulingReload("bootstrap", started.scheduling_epoch, "retire obsolete input",
        retirement={"maintenance_id": gate["maintenance_id"],
            "maintenance_intent_digest": gate["intent_digest"], "expected_gate_revision": gate["revision"]})
    try:
        with pytest.raises(QueueError, match="locked"):
            stage_retirement(source, candidate, request, expected_root_id=started.coordinator_id)
    finally:
        daemon.stop()
    (obsolete / "challenge").unlink()
    obsolete.rmdir()
    with pytest.raises(QueueError):
        load_coordinator_service_config(source)
    wrong = replace(request, retirement={**dict(request.retirement), "maintenance_id": "another-owner"})
    with pytest.raises(QueueError, match="exact closed maintenance"):
        stage_retirement(source, candidate, wrong, expected_root_id=started.coordinator_id)
    with pytest.raises(QueueError, match="native root identity changed"):
        stage_retirement(source, candidate, request, expected_root_id="different-root")
    _write_protected(candidate, {**after, "run_store_root": str(tmp_path / "different-runs")})
    with pytest.raises(QueueError, match="unrelated coordinator declaration"):
        stage_retirement(source, candidate, request, expected_root_id=started.coordinator_id)
    _write_protected(candidate, after)
    _write_protected(source, after)
    with pytest.raises(QueueError, match="scheduling predecessor conflicts"):
        stage_retirement(source, candidate, request, expected_root_id=started.coordinator_id)
    _write_protected(source, before)
    retained = stage_retirement(source, candidate, request, expected_root_id=started.coordinator_id)
    assert retained["state"] == "applying"
    assert json.loads(source.read_text()) == before and not obsolete.exists()
    assert stage_retirement(source, candidate, request, expected_root_id=started.coordinator_id) == retained
    with pytest.raises(QueueError, match="replay conflicts"):
        stage_retirement(source, candidate, replace(request, reason="different"), expected_root_id=started.coordinator_id)
    # Simulate interruption after native intent, then the existing publisher's
    # source replacement. Normal startup must finish the exact retained target.
    _write_protected(source, after)
    target = load_coordinator_service_config(source)
    restarted = LocalDaemon(target.daemon)
    status = restarted.start()
    try:
        assert status.coordinator_id == started.coordinator_id
        assert status.scheduling_epoch != started.scheduling_epoch
        assert operator(restarted).observe_maintenance()["state"] == "closed"
        assert not restarted.config.coordinator_shared_roots
        assert not obsolete.exists()
    finally:
        restarted.stop()
    completed = stage_retirement(source, candidate, request, expected_root_id=started.coordinator_id)
    assert completed["state"] == "applied"
