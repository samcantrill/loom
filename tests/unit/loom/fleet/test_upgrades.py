"""Upgrade qualification follows the retained native resource inventory."""
from types import SimpleNamespace

import pytest

from loom.fleet import upgrades


@pytest.mark.parametrize("device_source", ["native_inventory", "profile", "cpu_only"])
def test_upgrade_gpu_qualification_includes_native_inventory(
    tmp_path, monkeypatch, device_source
):
    # NVIDIA discovery puts devices in the native offer while the authored
    # resident profile keeps an empty legacy GPU declaration.
    device = {"id": "GPU-qualified", "provider": "exclusive"}
    profile = {"gpu_devices": [device] if device_source == "profile" else []}
    agent = {"offer": {"gpu_devices": [device] if device_source == "native_inventory" else []}}
    authorized = []
    observed = []
    settled = []
    operation = SimpleNamespace(
        directory=tmp_path,
        inventory=object(),
        intent={
            "operation_id": "upgrade-qualified",
            "declarations": {"worker": {"resident_profiles": [profile]}},
            "agents": {"worker": agent},
            "timeout_seconds": 30,
        },
        maintenance=lambda key, action, authorization: authorized.append(authorization),
        settled=lambda: settled.append(True),
    )

    def prepare(operation, name, check, identity):
        return {"operation_id": identity, "authorization": {"check": check}}

    def self_test(inventory, *, operation_id, timeout_seconds):
        observed.append(operation_id)
        return {"outcome": "passed"}

    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", self_test)
    upgrades._run_checks(operation)
    expected = ["cpu", "storage"] + ([] if device_source == "cpu_only" else ["gpu"])
    assert [row["check"] for row in authorized] == expected
    attempts = upgrades.read(tmp_path / "checks.json")
    assert set(attempts) == {"worker:" + check for check in expected}
    assert len(observed) == len(expected)
    assert settled == [True]
    # Continuation retains each check identity instead of preparing replacements.
    monkeypatch.setattr(upgrades, "_prepare_attempt", lambda *a: pytest.fail("duplicate check"))
    upgrades._run_checks(operation)
    assert observed[len(expected):] == observed[:len(expected)]
