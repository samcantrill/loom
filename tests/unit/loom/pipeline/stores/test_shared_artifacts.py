"""Shared closure validation through the native artifact store."""

from pathlib import Path

import pytest

from loom.pipeline.stores import LocalArtifactStore
from loom.pipeline.stores.shared_artifacts import budgets
from loom.pipeline.stores.errors import ArtifactStoreError
from loom.queue.errors import QueueServiceError
from loom.queue._shared_publication import publish
from loom.queue.shared_execution import root_bindings
from tests.unit.loom.queue.test_remote_stage_execution import (
    _shared_publication_workspace,
)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1024", None])
@pytest.mark.parametrize(
    "key", ["max_members", "max_payload_bytes", "max_manifest_bytes"]
)
def test_publication_budgets_are_positive_finite_integers(key, value):
    limits = {
        "max_members": 1024,
        "max_payload_bytes": 256 * 1024 * 1024,
        "max_manifest_bytes": 1024 * 1024,
    }
    limits[key] = value
    with pytest.raises(ArtifactStoreError, match="positive integer"):
        budgets(limits)


def test_publication_root_selection_requires_one_writable_binding(tmp_path):
    _, profile, _, _ = _shared_publication_workspace(tmp_path)
    binding = profile.shared_roots["outputs"]
    assert isinstance(binding, dict)
    root = dict(binding)
    with pytest.raises(QueueServiceError, match="writable"):
        root_bindings({"outputs": {**root, "access": "ro"}})
    with pytest.raises(QueueServiceError, match="exactly one"):
        root_bindings(
            {"outputs": root, "another": {**root, "container_path": "/loom/another"}}
        )


@pytest.mark.parametrize(
    "member", ["values.bin", "catalog/checkpoint", ".loom-publication.json"]
)
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_native_artifact_validation_checks_all_retained_members(
    tmp_path, member, damage
):
    workspace, profile, _, _ = _shared_publication_workspace(tmp_path)
    refs = publish(
        workspace.request(),
        workspace.retain_outputs(),
        profile.shared_roots,
        agent_id="agent-1",
        fence="fence-1",
    )
    ref = refs["result"]
    store = LocalArtifactStore(tmp_path / "consumer")
    store.validate(ref)
    path = Path(ref.uri.removeprefix("file://")).parent / member
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corrupt")
    with pytest.raises(ArtifactStoreError, match="missing|integrity"):
        store.validate(ref)
    assert not store.root.exists()


def test_retained_candidate_reference_resolves_before_opening_foreign_uri(tmp_path):
    from dataclasses import replace

    workspace, profile, _, _ = _shared_publication_workspace(tmp_path)
    refs = publish(
        workspace.request(),
        workspace.retain_outputs(),
        profile.shared_roots,
        agent_id="agent-1",
        fence="fence-1",
    )
    candidate = replace(
        refs["result"], uri="file:///unmounted-producer-prefix/native/primary.json"
    )
    store = LocalArtifactStore(tmp_path / "consumer", shared_roots=profile.shared_roots)
    assert store.exists(candidate)
    store.validate(candidate)
    assert store.local_path(candidate).read_bytes() == b'{"companion":"values.bin"}'
    assert not store.root.exists()


def test_publication_payload_budget_is_checked_before_reading_file_bytes(tmp_path, monkeypatch):
    import os
    from loom.pipeline.stores.shared_artifacts import inventory
    (tmp_path / "too-large.bin").write_bytes(b"too large")
    def forbidden(*args, **kwargs):
        raise AssertionError("over-budget payload must not be read")
    monkeypatch.setattr(os, "fdopen", forbidden)
    with pytest.raises(ArtifactStoreError, match="payload budget"):
        inventory(tmp_path, {"max_members": 2, "max_payload_bytes": 1, "max_manifest_bytes": 1024})


def test_unreadable_member_tree_is_not_a_complete_empty_closure(tmp_path, monkeypatch):
    import os
    from loom.pipeline.stores.shared_artifacts import inventory, publication_path_is_retained
    def unreadable(*args, onerror, **kwargs):
        onerror(PermissionError("producer left an unreadable directory"))
        return iter(())
    monkeypatch.setattr(os, "walk", unreadable)
    with pytest.raises(ArtifactStoreError, match="unreadable"):
        inventory(tmp_path, {"max_members": 2, "max_payload_bytes": 1024, "max_manifest_bytes": 1024})
    assert publication_path_is_retained(tmp_path)
