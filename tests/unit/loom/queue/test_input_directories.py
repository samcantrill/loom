"""External inputs authorize read-only paths without asserting storage identity."""

from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.shared_execution import (
    attributes, materialize, qualifications, qualified_roots, require_bindings,
    root_bindings, scope, stage_scope,
)
from loom.queue.submitted_execution import (
    INPUT_DIRECTORY_WORKER_CONTRACT, submitted_worker_command,
)
from tests.unit.loom.queue.test_submitted_container_policy import _submitted

pytestmark = pytest.mark.unit


def _root(path):
    return {"host_path": str(path), "container_path": "/loom/inputs/data", "access": "ro",
            "qualification": {"kind": "input_directory"}}


def test_input_directory_round_trip_and_cross_host_projection_without_markers(tmp_path):
    local, remote = tmp_path / "machine-a", tmp_path / "machine-b"
    for path in (local, remote):
        path.mkdir()
        (path / "selected.txt").write_text("input")
    first, second = (root_bindings({"data": _root(path)}) for path in (local, remote))
    portable = qualifications(first)
    assert qualifications(second) == portable == qualified_roots(portable)
    assert portable == {"data": {"container_path": "/loom/inputs/data", "access": "ro",
                                "qualification": {"kind": "input_directory"}}}
    location = {"kind": "loom.shared-location", "schema_version": 1,
                "root_id": "data", "path": "selected.txt"}
    selected = stage_scope({"input": location}, {}, {"roots": portable})
    assert scope(selected) == selected
    require_bindings(selected, first)
    require_bindings(selected, second)
    assert materialize(location, second, container=True) == "/loom/inputs/data/selected.txt"
    assert materialize(location, second, container=False) == str(remote / "selected.txt")
    assert attributes(selected)["shared_root_data"]
    assert sorted(path.name for path in local.iterdir()) == ["selected.txt"]
    (local / ".loom-challenge").write_text("irrelevant to explicit input mode")
    assert qualifications(first) == portable


@pytest.mark.parametrize("change", [
    {"access": "rw"}, {"publication": {}},
    {"challenge": {"path": ".loom-challenge", "sha256": "a" * 64}},
    {"qualification": {"kind": "unknown"}},
])
def test_input_directory_refuses_other_storage_permissions(tmp_path, change):
    with pytest.raises(QueueServiceError):
        root_bindings({"data": {**_root(tmp_path), **change}})


@pytest.mark.parametrize("failure", ["missing", "symlink", "unreadable", "escape"])
def test_live_input_failures_do_not_provision_or_redirect(tmp_path, monkeypatch, failure):
    path = tmp_path / "input"
    if failure != "missing":
        path.mkdir()
    if failure == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(path, target_is_directory=True)
        path = alias
    elif failure == "unreadable":
        monkeypatch.setattr("loom.queue.shared_execution.os.access", lambda *args: False)
    roots = root_bindings({"data": _root(path)})
    with pytest.raises(QueueServiceError):
        if failure == "escape":
            outside = tmp_path / "outside"
            outside.write_text("not authorized")
            (path / "selected").symlink_to(outside)
            selected = stage_scope({"input": {"kind": "loom.shared-location", "schema_version": 1,
                                               "root_id": "data", "path": "selected"}}, {},
                                   {"roots": qualifications(roots)})
            require_bindings(selected, roots)
        else:
            qualifications(roots)
    if failure == "missing":
        assert not path.exists()


def test_legacy_challenge_encoding_and_failure_remain_unchanged(tmp_path):
    root = {"host_path": str(tmp_path), "container_path": "/loom/data", "access": "ro",
            "challenge": {"path": ".loom-challenge", "sha256": hashlib.sha256(b"original").hexdigest()}}
    assert root_bindings({"data": root}) == {"data": root}
    with pytest.raises(QueueServiceError):
        qualifications({"data": root})
    (tmp_path / ".loom-challenge").write_bytes(b"original")
    expected = {"data": {key: value for key, value in root.items() if key != "host_path"}}
    assert qualifications({"data": root}) == qualified_roots(expected) == expected
    (tmp_path / ".loom-challenge").write_bytes(b"different")
    with pytest.raises(QueueServiceError, match="bytes mismatch"):
        qualifications({"data": root})


def test_submitted_input_policy_requires_new_worker_and_challenged_image_storage(tmp_path):
    from tests.integration.queue.test_submitted_container_agents import _bound
    from tests.unit.loom.queue.test_submitted_container_policy import _retained_launch

    policy, legacy, request, _ = _submitted(tmp_path)
    data = tmp_path / "input"
    data.mkdir()
    roots = {**policy.shared_roots, "input": _root(data)}
    with pytest.raises(QueueServiceError, match="v2"):
        replace(policy, shared_roots=roots)
    new = replace(policy, shared_roots=roots, worker_contracts=(INPUT_DIRECTORY_WORKER_CONTRACT,))
    assert new.capability.required_worker_contract == INPUT_DIRECTORY_WORKER_CONTRACT
    assert new.qualify() == new.capability
    assert new.capability.fingerprint != policy.capability.fingerprint
    with pytest.raises(QueueServiceError, match="not allowed"):
        new.capability.require_execution(legacy)
    execution = replace(legacy, worker_contract=INPUT_DIRECTORY_WORKER_CONTRACT)
    new.capability.require_execution(execution)
    _, _, launch = _retained_launch(tmp_path, new, execution, _bound(request, execution, new))
    assert INPUT_DIRECTORY_WORKER_CONTRACT in launch.container_command.argv
    with pytest.raises(QueueServiceError, match="challenged storage"):
        replace(new, allowed_image_roots=("input",))


def test_older_image_refuses_new_contract_before_request_decoding(tmp_path):
    _, legacy, _, _ = _submitted(tmp_path)
    old_installation = tmp_path / "old-installation"
    package = old_installation / "loom" / "queue"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").touch()
    (package / "__init__.py").touch()
    (package / "submitted_execution.py").write_text(
        'SUBMITTED_CONTAINER_WORKER_CONTRACT = "resident-submitted-container-v1"\n'
    )
    (package / "_resident_stage_worker.py").write_text('raise AssertionError("request was decoded")\n')
    execution = replace(legacy, python_executable=sys.executable, worker_contract=INPUT_DIRECTORY_WORKER_CONTRACT)
    workspace = tmp_path / "unread-request"
    workspace.mkdir()
    command = submitted_worker_command(execution, workspace)
    result = subprocess.run(command, cwd=old_installation, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "does not support required worker contract" in result.stderr
    assert "request was decoded" not in result.stderr
    assert (workspace / "logs/stderr.log").read_text() == result.stderr
    assert submitted_worker_command(legacy, Path("/workspace")) == (
        legacy.python_executable, "-m", "loom.queue._resident_stage_worker", "--workspace", "/workspace",
    )


def test_preparation_scope_keeps_only_explicitly_selected_input_directories(tmp_path):
    from loom.queue._preparation_policy import load_preparation_policy
    from loom.queue._remote_stage_execution import ResidentProfileDescriptor

    roots = {name: {"container_path": f"/loom/inputs/{name}", "access": "ro",
                    "qualification": {"kind": "input_directory"}} for name in ("selected", "other")}
    descriptor = ResidentProfileDescriptor("inputs", "v1", "project", "environment", "executor", roots)
    location = {"kind": "loom.shared-location", "schema_version": 1, "root_id": "selected", "path": "."}
    declaration = {
        "source_roots": {"project": {"path": str(tmp_path), "shared_snapshot_root": str(tmp_path / "snapshots")}},
        "profiles": {"inputs": {"resident_profile_id": "inputs", "allowed_source_roots": ["project"],
            "source_modes": ["shared"], "runtime_options": {"executor": "local"},
            "configuration_policy": "shared", "shared_locations": [location]}},
    }
    policy = load_preparation_policy(declaration, base=tmp_path, descriptors=(descriptor,))
    assert policy is not None
    assert policy.profiles["inputs"].shared_scope == {
        "capability": "shared-execution-v1", "roots": {"selected": roots["selected"]}, "locations": [location],
    }


def test_input_directory_cannot_back_captured_configuration(tmp_path):
    from loom.queue.shared_execution import project_snapshot_mount
    from tests.unit.loom.queue.test_preparation_probe import fixture

    profile, binding = fixture(tmp_path)
    assert binding.input_receipt is not None
    roots = {"input": _root(tmp_path / "snapshots")}
    profile = replace(profile, shared_roots=roots)
    with pytest.raises(QueueServiceError, match="captured configuration requires challenged storage"):
        project_snapshot_mount(profile, binding.input_receipt)



def test_overlapping_inputs_scan_once_and_revalidate_next_boundary(tmp_path, monkeypatch):
    from loom.queue import shared_execution
    from loom.queue._phase_timing import observe_phases

    child = tmp_path / "nested"
    child.mkdir()
    payload = child / "values"
    payload.write_text("input")
    roots = root_bindings({"data": _root(tmp_path)})
    locations = [{"kind": "loom.shared-location", "schema_version": 1,
                  "root_id": "data", "path": path} for path in ("nested/values", ".", "nested")]
    selected = stage_scope({"inputs": locations}, {}, {"roots": qualifications(roots)})
    walked = []
    original = shared_execution.os.walk

    def walk(path, **kwargs):
        walked.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(shared_execution.os, "walk", walk)
    timings = []
    with observe_phases(timings.append):
        require_bindings(selected, roots)
    assert walked == [tmp_path]
    assert timings[0]["spans"][0]["action"] == "input_root_validation"
    assert timings[0]["spans"][0]["outcome"] == "complete"
    (child / "link").symlink_to(payload)
    with pytest.raises(QueueServiceError, match="regular"):
        require_bindings(selected, roots)
    assert walked == [tmp_path, tmp_path]
    payload.unlink()
    with pytest.raises(QueueServiceError):
        require_bindings(selected, roots)
