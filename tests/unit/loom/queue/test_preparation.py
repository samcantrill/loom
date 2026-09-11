"""Focused contracts for shared preparation request and capture boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil

import pytest

from loom.fingerprints import hash_mapping
from loom.errors import SerializationError
from loom.queue import preparation as inputs
from loom.queue.errors import QueueServiceError
from loom.queue.local_daemon import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)
from loom.queue.preparation import (
    PrepareRunRequest,
    PreparationSource,
    capture_shared_input,
    resolve_shared_input,
    SharedInputReceipt,
)
from loom.queue._agent_process_supervisor import ResidentWorkerLaunchProfile
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue._preparation_policy import load_preparation_policy
import sys


def _request(*, mode: str = "shared") -> PrepareRunRequest:
    return PrepareRunRequest(
        "prepare-demo-001",
        "demo-001",
        PreparationSource(mode, "projects", "example-project", ("configs",)),
        "configs/experiment.yaml",
        "example-cpu",
    )


def test_shared_capture_is_finite_and_immutable(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    config = root / "example-project" / "configs" / "experiment.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("pipeline: {}\n", encoding="utf-8")

    request = _request()
    first = capture_shared_input(
        request, source_root=root, snapshot_root=tmp_path / "snapshots"
    )
    snapshot = tmp_path / "snapshots" / first.path
    assert (snapshot / "files" / "configs" / "experiment.yaml").read_text(
        encoding="utf-8"
    ) == "pipeline: {}\n"
    assert first.to_dict()["reference"] == {
        "schema_version": 1,
        "kind": "loom.shared-preparation-input",
        "root": "projects",
        "path": first.path,
    }


def test_staged_request_does_not_use_shared_capture() -> None:
    with pytest.raises(QueueServiceError, match="unsupported"):
        capture_shared_input(
            _request(mode="staged"),
            source_root=Path("."),
            snapshot_root=Path("snapshots"),
        )


def test_capture_recovery_preserves_ready_inputs_and_another_coordinators_temporary(
    tmp_path: Path,
) -> None:
    root = tmp_path / "projects"
    source = root / "example-project" / "configs" / "experiment.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("original")
    snapshots = tmp_path / "snapshots"
    first = capture_shared_input(
        _request(), source_root=root, snapshot_root=snapshots, owner_id="coordinator-a"
    )
    second = capture_shared_input(
        _request(), source_root=root, snapshot_root=snapshots, owner_id="coordinator-b"
    )
    assert first.path != second.path
    assert first.manifest_digest == second.manifest_digest
    temporaries = []
    for receipt in (first, second):
        key = receipt.path.rsplit("-", 1)[0]
        temporary = snapshots / f".{key}.tmp-{'1' * 32}"
        shutil.copytree(snapshots / receipt.path, temporary)
        temporaries.append(temporary)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for receipt in (first, second)
        for path in (snapshots / receipt.path).rglob("*")
        if path.is_file()
    }
    inputs.discard_shared_input_temporaries(
        _request(), snapshot_root=snapshots, owner_id="coordinator-a"
    )
    assert not temporaries[0].exists()
    assert temporaries[1].is_dir()
    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == data
        for path, data in before.items()
    )


def test_capture_rejects_symlinked_project_components_and_tampered_reuse(
    tmp_path: Path,
) -> None:
    root = tmp_path / "projects"
    actual = tmp_path / "actual"
    (actual / "configs").mkdir(parents=True)
    (actual / "configs" / "experiment.yaml").write_text(
        "pipeline: {}\n", encoding="utf-8"
    )
    root.mkdir()
    (root / "example-project").symlink_to(actual, target_is_directory=True)
    with pytest.raises(QueueServiceError, match="symbolic link"):
        capture_shared_input(
            _request(), source_root=root, snapshot_root=tmp_path / "snapshots"
        )

    project = root / "example-project"
    (root / "example-project").unlink()
    (project / "configs").mkdir(parents=True)
    (project / "configs" / "experiment.yaml").write_text(
        "pipeline: {}\n", encoding="utf-8"
    )
    receipt = capture_shared_input(
        _request(), source_root=root, snapshot_root=tmp_path / "snapshots"
    )
    snapshot = tmp_path / "snapshots" / receipt.path
    (snapshot / "files" / "configs" / "experiment.yaml").write_text(
        "changed", encoding="utf-8"
    )
    with pytest.raises(QueueServiceError, match="capture"):
        capture_shared_input(
            _request(), source_root=root, snapshot_root=tmp_path / "snapshots"
        )


@pytest.mark.parametrize("path", ("/absolute", "../escape", "configs/../../escape"))
def test_request_rejects_escape_paths_before_capture(path: str) -> None:
    with pytest.raises(QueueServiceError, match="relative path"):
        PrepareRunRequest(
            "prepare-demo-001",
            "demo-001",
            PreparationSource("shared", "projects", ".", ("configs",)),
            path,
            "example-cpu",
        )


def test_preparation_operation_is_principal_bound_idempotent_and_cancellable(
    tmp_path: Path,
) -> None:
    from loom.coordinator import CoordinatorClient
    from loom.preparation import CoordinatorPreparation
    from loom.queue.deployment import CoordinatorServiceConfig
    from loom.queue.local_daemon_transport import LocalDaemonSocketServer

    profile = ResidentWorkerLaunchProfile(
        project_root=Path.cwd(),
        python_executable=Path(sys.executable),
        descriptor=ResidentProfileDescriptor(
            "local", "v1", "project", "environment", "executor"
        ).to_dict(),
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=profile,
        preparation_policy=load_preparation_policy(
            {
                "source_roots": {
                    "projects": {
                        "path": "projects",
                        "shared_snapshot_root": "snapshots",
                    }
                },
                "profiles": {
                    "example-cpu": {
                        "resident_profile_id": "local",
                        "allowed_source_roots": ["projects"],
                        "source_modes": ["shared"],
                        "runtime_options": {"executor": "local"},
                    }
                },
            },
            base=tmp_path,
            descriptors=(ResidentProfileDescriptor.from_dict(profile.descriptor),),
        ),
    )
    LocalDaemon.initialize(config)
    service = CoordinatorServiceConfig(
        config, None, tmp_path / "coordinator.json", "immutable", "active"
    )
    daemon = LocalDaemon(config, preparation=CoordinatorPreparation(service))
    daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    server = LocalDaemonSocketServer(daemon, config.endpoint)
    try:
        server.start()
        with CoordinatorClient.from_unix_socket(config.endpoint) as client:
            description = client.describe_connection()
            assert description.source_modes == ("shared",)
            assert description.preparation_profiles == ("example-cpu",)
            assert description.source_roots == ("projects",)
            assert "agent-preparation-v1" in description.capabilities
            assert str(tmp_path) not in json.dumps(description.to_dict())
        view = daemon.client_view(
            LocalDaemonPrincipal("client-a", LocalDaemonRole.CLIENT)
        )
        accepted = view.prepare_run(_request())
        replay = view.prepare_run(_request())
        assert accepted == replay
        assert accepted.state == "pending"
        assert isinstance(accepted.result, Mapping)
        assert accepted.result["coordinator_id"] == daemon.status().coordinator_id
        assert view.cancel_preparation("prepare-demo-001").state == "pending"
        daemon._preparations._reconcile_lock.release()
        assert (
            daemon.wait_operation("prepare-demo-001", timeout=10).operation.state
            == "cancelled"
        )
        with pytest.raises(Exception, match="conflicts"):
            daemon.client_view(
                LocalDaemonPrincipal("client-b", LocalDaemonRole.CLIENT)
            ).prepare_run(_request())
    finally:
        server.stop()
        if daemon._preparations._reconcile_lock.locked():
            daemon._preparations._reconcile_lock.release()
        daemon.stop()


def test_capture_preserves_authored_manifests_and_uses_native_digest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    (root / "nested").mkdir(parents=True)
    for name in (
        "pipeline.yaml",
        "manifest.json",
        "nested/manifest.json",
        "nested/unicodé.yaml",
    ):
        (root / name).write_text(name, encoding="utf-8")
    request = replace(
        _request(),
        source=PreparationSource("shared", "projects", ".", (".",)),
        config_path="pipeline.yaml",
    )
    receipt = capture_shared_input(
        request, source_root=root, snapshot_root=tmp_path / "snapshots"
    )
    assert SharedInputReceipt.from_dict(receipt.to_dict()) == receipt
    directory = tmp_path / "snapshots" / receipt.path
    manifest = json.loads((directory / "manifest.json").read_text())
    assert receipt.manifest_digest == hash_mapping(manifest)
    assert [item["path"] for item in manifest["files"]] == [
        "manifest.json",
        "nested/manifest.json",
        "nested/unicodé.yaml",
        "pipeline.yaml",
    ]
    assert (directory / "files" / "manifest.json").read_text() == "manifest.json"
    assert (
        directory / "files" / "nested" / "manifest.json"
    ).read_text() == "nested/manifest.json"
    before = {
        p.relative_to(directory): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in directory.rglob("*")
        if p.is_file()
    }
    assert (
        capture_shared_input(
            request, source_root=root, snapshot_root=tmp_path / "snapshots"
        )
        == receipt
    )
    assert before == {
        p.relative_to(directory): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in directory.rglob("*")
        if p.is_file()
    }


def test_worker_resolves_captured_bytes_with_its_own_mapping_after_source_edit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "projects"
    source = root / "example-project" / "configs" / "experiment.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("original")
    snapshots = tmp_path / "coordinator-mount"
    receipt = capture_shared_input(
        _request(), source_root=root, snapshot_root=snapshots
    )
    worker_mount = tmp_path / "worker-mount"
    # Two directory views of the same file inodes model differing mount prefixes;
    # this does not claim a physical NAS deployment test.
    shutil.copytree(snapshots, worker_mount, copy_function=os.link)
    source.write_text("new authored value")
    resolved = resolve_shared_input(receipt, shared_roots={"projects": worker_mount})
    assert resolved == worker_mount / receipt.path / "files"
    assert (resolved / "configs" / "experiment.yaml").read_text() == "original"
    with pytest.raises(QueueServiceError, match="not mapped"):
        resolve_shared_input(receipt, shared_roots={})
    with pytest.raises(QueueServiceError, match="capture"):
        resolve_shared_input(
            replace(receipt, manifest_digest=hash_mapping({})),
            shared_roots={"projects": worker_mount},
        )
    (resolved / "configs" / "extra.txt").write_text("unexpected")
    with pytest.raises(QueueServiceError, match="capture"):
        resolve_shared_input(receipt, shared_roots={"projects": worker_mount})


@pytest.mark.parametrize("kind", ("directory_link", "file_link", "fifo"))
def test_selected_links_and_special_files_are_refused(
    tmp_path: Path, kind: str
) -> None:
    root = tmp_path / "projects"
    configs = root / "example-project" / "configs"
    configs.mkdir(parents=True)
    (configs / "experiment.yaml").write_text("config")
    unexpected = configs / "unexpected"
    if kind == "directory_link":
        unexpected.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "file_link":
        unexpected.symlink_to(configs / "experiment.yaml")
    else:
        os.mkfifo(unexpected)
    with pytest.raises(QueueServiceError, match="symbolic link|unsupported file"):
        capture_shared_input(
            _request(), source_root=root, snapshot_root=tmp_path / "snapshots"
        )
    assert not (tmp_path / "snapshots").exists()


@pytest.mark.parametrize("change", ("edit", "add", "delete"))
def test_source_changes_fail_without_publishing_a_partial_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root = tmp_path / "projects"
    config = root / "example-project" / "configs" / "experiment.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("original")
    write = inputs._write_durable
    changed = False

    def change_after_copy(path: Path, data: bytes) -> None:
        nonlocal changed
        write(path, data)
        if not changed:
            changed = True
            if change == "edit":
                config.write_text("modified")
            elif change == "add":
                (config.parent / "another.yaml").write_text("added")
            else:
                config.unlink()

    monkeypatch.setattr(inputs, "_write_durable", change_after_copy)
    with pytest.raises(QueueServiceError, match="source_changed"):
        capture_shared_input(
            _request(), source_root=root, snapshot_root=tmp_path / "snapshots"
        )
    assert not tuple((tmp_path / "snapshots").iterdir())


@pytest.mark.parametrize("limit", ("files", "bytes"))
def test_capture_limits_are_enforced_before_publishing_or_reading_oversized_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    root = tmp_path / "projects"
    config = root / "example-project" / "configs" / "experiment.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("config")
    if limit == "files":
        for number in range(4096):
            (config.parent / f"file-{number}").touch()
    else:
        with config.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)

    def unexpected_read(*args: object, **kwargs: object) -> bytes:
        raise AssertionError(
            "size and count violations must be refused before file reads"
        )

    monkeypatch.setattr(inputs, "_read_regular_file", unexpected_read)
    with pytest.raises(QueueServiceError, match="input_limit_exceeded"):
        capture_shared_input(
            _request(), source_root=root, snapshot_root=tmp_path / "snapshots"
        )
    assert not (tmp_path / "snapshots").exists()


def test_request_normalizes_equivalent_explicit_selections_and_native_intent() -> None:
    request = _request()
    equivalent = replace(
        request,
        source=PreparationSource(
            "shared",
            "projects",
            "./example-project",
            ("configs/.", "configs", "configs/experiment.yaml"),
        ),
    )
    assert equivalent == request
    assert request.intent_digest("client-a") == hash_mapping(
        {"principal_id": "client-a", "request": request.to_dict()}
    )
    with pytest.raises(QueueServiceError, match="glob"):
        replace(
            request,
            source=PreparationSource("shared", "projects", ".", ("configs/*.yaml",)),
        )
    with pytest.raises(QueueServiceError, match="1..100"):
        replace(
            request,
            source=PreparationSource(
                "shared", "projects", ".", tuple(f"file-{i}" for i in range(101))
            ),
        )


def test_source_removed_between_selection_and_open_is_a_detected_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "projects"
    config = root / "example-project" / "configs" / "experiment.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("original")
    read = inputs._read_regular_file

    def remove_before_open(
        directory: Path,
        relative: str,
        limit: int,
        *,
        expected: os.stat_result | None = None,
    ) -> bytes:
        config.unlink()
        return read(directory, relative, limit, expected=expected)

    monkeypatch.setattr(inputs, "_read_regular_file", remove_before_open)
    with pytest.raises(QueueServiceError, match="source_changed"):
        capture_shared_input(
            _request(), source_root=root, snapshot_root=tmp_path / "snapshots"
        )
    assert not (tmp_path / "snapshots").exists()


@pytest.mark.parametrize("mode", ("shared", "staged"))
def test_invocation_is_sparse_immutable_and_ordered(mode: str) -> None:
    options = {"tags": {"trial": "first"}, "selectors": {"force_stages": ["train"]}}
    request = replace(
        _request(mode=mode),
        overlays=("configs/a.yaml", "configs/b.yaml"),
        overrides=("x=1", "x=2"),
        run_options=options,
    )
    encoded = request.to_dict()
    options["tags"]["trial"] = "mutated"
    assert request.to_dict() == encoded
    assert PrepareRunRequest.from_dict(encoded) == request
    assert encoded["run_options"] == {
        "tags": {"trial": "first"},
        "selectors": {"force_stages": ["train"]},
    }
    assert replace(request, overlays=tuple(reversed(request.overlays))).intent_digest(
        "owner"
    ) != request.intent_digest("owner")
    assert replace(request, overrides=tuple(reversed(request.overrides))).intent_digest(
        "owner"
    ) != request.intent_digest("owner")
    assert replace(request, run_options={"dry_run": False}).intent_digest(
        "owner"
    ) != replace(request, run_options={}).intent_digest("owner")


@pytest.mark.parametrize(
    "options",
    (
        {"executor": "local"},
        {"adapter_options": {}},
        {"stage_options": {"train": {"adapter_options": {}}}},
        {"validator_registry": object()},
    ),
)
def test_preparation_rejects_obsolete_or_live_invocation_options(options) -> None:
    with pytest.raises((QueueServiceError, ValueError, SerializationError)):
        replace(_request(), run_options=options)


def test_overlay_must_belong_to_explicit_capture(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    config = root / "example-project" / "configs" / "experiment.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("pipeline: {}")
    (config.parents[1] / "outside.yaml").write_text("runtime: {}")
    request = replace(_request(), overlays=("outside.yaml",))
    with pytest.raises(QueueServiceError, match="overlay is not included"):
        capture_shared_input(
            request, source_root=root, snapshot_root=tmp_path / "snapshots"
        )
