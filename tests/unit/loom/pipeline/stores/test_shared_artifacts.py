"""Shared closure validation through the native artifact store."""

from pathlib import Path
from typing import Any, cast

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


def test_trusted_publication_does_not_inventory_sync_or_revalidate_payloads(tmp_path, monkeypatch):
    from loom.queue import _shared_publication as publication
    from loom.pipeline.stores import shared_artifacts as shared
    from loom.queue._remote_stage_execution import _RemoteArtifact

    policy = {"policy": "trusted_shared_storage", "max_members": 1024,
              "max_payload_bytes": 256 * 1024 * 1024, "max_manifest_bytes": 1024 * 1024}
    workspace, profile, _, _ = _shared_publication_workspace(tmp_path, limits=policy)

    def forbidden(*args, **kwargs):
        raise AssertionError("trusted publication traversed or verified payloads")

    monkeypatch.setattr(publication, "inventory", forbidden)
    monkeypatch.setattr(shared, "inventory", forbidden)
    monkeypatch.setattr(shared.os, "walk", forbidden)
    report = workspace.retain_outputs()
    refs = publish(workspace.request(), report, profile.shared_roots,
                   agent_id="agent-1", fence="fence-1")
    ref = refs["result"]
    reference = shared.binding(ref.metadata)
    assert reference is not None
    assert reference["schema_version"] == 2
    primary = Path(ref.uri.removeprefix("file://"))
    # A later change is deliberately not detected by trusted consumers.
    (primary.parent / "values.bin").write_bytes(b"changed companion")
    primary.write_bytes(b'{"trusted":"changed"}')
    store = LocalArtifactStore(tmp_path / "consumer", shared_roots=profile.shared_roots)
    monkeypatch.setattr(store, "_verify_checksum_path", forbidden)
    store.validate(ref)
    _RemoteArtifact.from_local_ref(transfer_id="input-1", logical_name="result", ref=ref)
    assert publish(workspace.request(), report, profile.shared_roots,
                   agent_id="agent-1", fence="fence-1") == refs


def test_trusted_policy_is_explicit_and_cannot_be_consumed_by_verified_root(tmp_path):
    from loom.pipeline.stores.shared_artifacts import admits_budgets, publication_configuration

    limits = {"max_members": 1024, "max_payload_bytes": 1024, "max_manifest_bytes": 1024}
    trusted = {**limits, "policy": "trusted_shared_storage"}
    assert publication_configuration(limits) == limits
    assert publication_configuration(trusted) == trusted
    assert not admits_budgets(limits, trusted)
    assert admits_budgets(trusted, limits)
    with pytest.raises(ArtifactStoreError, match="unsupported"):
        publication_configuration({**limits, "policy": "typo"})


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


def test_inspection_reads_only_committed_inventory_and_audit_still_checks_payloads(
    tmp_path, monkeypatch
):
    import os
    from loom.pipeline.stores.shared_artifacts import RECEIPT

    workspace, profile, _, _ = _shared_publication_workspace(tmp_path)
    refs = publish(workspace.request(), workspace.retain_outputs(), profile.shared_roots,
                   agent_id="agent-1", fence="fence-1")
    store = LocalArtifactStore(tmp_path / "consumer", shared_roots=profile.shared_roots)
    original = os.open
    opened = []

    def receipt_only(path, *args, **kwargs):
        opened.append(Path(path).name)
        assert Path(path).name == RECEIPT, "inspection opened a member payload"
        return original(path, *args, **kwargs)

    with monkeypatch.context() as guard:
        guard.setattr(os, "open", receipt_only)
        inspected = store.inspect(refs["result"])
    assert opened == [RECEIPT]
    assert inspected.receipt is not None
    assert any(row["path"] == "values.bin" for row in inspected.members)
    (inspected.root / "values.bin").write_bytes(b"changed companion")
    assert store.inspect(refs["result"]).members == inspected.members
    with pytest.raises(ArtifactStoreError, match="integrity"):
        store.validate(refs["result"])
    (inspected.root / RECEIPT).write_bytes(b"changed inventory")
    with pytest.raises(ArtifactStoreError, match="integrity"):
        store.inspect(refs["result"])


def test_local_inspection_retains_selected_checksum_without_reading_bytes(tmp_path, monkeypatch):
    store = LocalArtifactStore(tmp_path)
    ref = store.save(b"payload", stage_name="fit", name="weights", artifact_type="bytes",
                     codec_key="bytes.v1")
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("payload was read"))
    inspected = store.inspect(ref)
    assert inspected.root / inspected.primary == Path(ref.uri.removeprefix("file://"))
    assert inspected.members[0]["size_bytes"] == 7
    digest = inspected.members[0]["digest"]
    assert isinstance(digest, str)
    assert "sha256:" + digest == ref.checksum


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


def test_increased_root_ceilings_preserve_historical_reference_and_receipt(tmp_path):
    from loom.serialization import thaw_plain_data
    from loom.pipeline.stores.shared_artifacts import RECEIPT, binding
    from loom.queue.errors import QueueConflictError

    workspace, profile, _, _ = _shared_publication_workspace(tmp_path)
    report = workspace.retain_outputs()
    refs = publish(workspace.request(), report, profile.shared_roots, agent_id="agent-1", fence="fence-1")
    ref = refs["result"]
    recorded = binding(ref.metadata)
    assert recorded is not None
    primary = Path(ref.uri.removeprefix("file://"))
    receipt = (primary.parent / RECEIPT).read_bytes()
    roots = cast(dict[str, Any], thaw_plain_data(profile.shared_roots))
    roots["outputs"]["publication"] = {
        "max_members": 1_000_000, "max_manifest_bytes": 536_870_912,
        "max_payload_bytes": 274_877_906_944,
    }
    store = LocalArtifactStore(tmp_path / "consumer", shared_roots=roots)
    store.validate(ref)
    assert store.local_path(ref) == primary
    assert publish(workspace.request(), report, roots, agent_id="agent-1", fence="fence-1") == refs
    assert binding(ref.metadata) == recorded
    assert (primary.parent / RECEIPT).read_bytes() == receipt
    with pytest.raises(QueueConflictError, match="identity"):
        publish(workspace.request(), report, roots, agent_id="agent-1", fence="another-fence")
    for key, value in budgets(recorded["budgets"]).items():
        prior = roots["outputs"]["publication"][key]
        roots["outputs"]["publication"][key] = value - 1
        with pytest.raises(ArtifactStoreError, match="not admitted"):
            store = LocalArtifactStore(tmp_path / "consumer", shared_roots=roots)
            store.validate(ref)
        roots["outputs"]["publication"][key] = prior


def test_increase_does_not_enlarge_frozen_publication_request(tmp_path):
    from loom.serialization import thaw_plain_data
    from loom.queue.errors import QueueConflictError

    limits = {"max_members": 3, "max_payload_bytes": 4096, "max_manifest_bytes": 4096}
    workspace, profile, _, result = _shared_publication_workspace(tmp_path, limits=limits)
    report = workspace.retain_outputs()
    roots = cast(dict[str, Any], thaw_plain_data(profile.shared_roots))
    roots["outputs"]["publication"]["max_members"] = 1_000_000
    primary = Path(result.outputs["result"].uri.removeprefix("file://"))
    (primary.parent / "late-output").write_bytes(b"unretained output")
    with pytest.raises(QueueConflictError, match="budget=max_members limit=3 observed_at_least=4"):
        publish(workspace.request(), report, roots, agent_id="agent-1", fence="fence-1")
    assert not (tmp_path / "shared" / "loom-artifacts").exists()


@pytest.mark.parametrize("budget,limit,observed", [
    ("max_members", 1, 2), ("max_payload_bytes", 10, 11),
])
def test_inventory_budget_diagnostics_identify_total_bound(tmp_path, budget, limit, observed):
    from loom.pipeline.stores.shared_artifacts import inventory
    (tmp_path / "a").write_bytes(b"1234")
    (tmp_path / "b").write_bytes(b"1234567")
    limits = {"max_members": 2, "max_payload_bytes": 11, "max_manifest_bytes": 4096}
    assert len(inventory(tmp_path, limits)) == 2
    limits[budget] = limit
    with pytest.raises(ArtifactStoreError, match=f"budget={budget} limit={limit} observed_at_least={observed}"):
        inventory(tmp_path, limits)


def test_receipt_budget_diagnostics_identify_inventory_bytes(tmp_path):
    from loom.pipeline.stores.shared_artifacts import receipt_bytes
    path = tmp_path / "receipt"
    path.write_bytes(b"1234")
    assert receipt_bytes(path, 4) == b"1234"
    with pytest.raises(ArtifactStoreError, match="budget=max_manifest_bytes limit=3 observed_at_least=4"):
        receipt_bytes(path, 3)


def test_trusted_registration_uses_producer_digest_without_reading_primary(tmp_path, monkeypatch):
    from loom.fingerprints import hash_bytes

    root = tmp_path / "published"
    path = root / "stage" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"producer manifest")
    limits = {"policy": "trusted_shared_storage", "max_members": 1024,
              "max_payload_bytes": 1024, "max_manifest_bytes": 1024}
    store = LocalArtifactStore(root, shared_roots={"out": {
        "host_path": str(root), "publication": limits}})
    checksum = hash_bytes(b"producer manifest")
    monkeypatch.setattr(Path, "open", lambda *a, **kw: pytest.fail("read producer primary"))
    ref = store.register(path, stage_name="stage", name="manifest", artifact_type="json",
                         checksum=checksum)
    assert ref.checksum == checksum
