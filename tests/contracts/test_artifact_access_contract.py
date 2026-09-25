"""Exact committed files, complete receipt trees, and safe client publication."""

from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.artifacts import ArtifactRef
from loom.coordinator import CoordinatorClient
from loom.fingerprints import hash_bytes
from loom.pipeline.stores import shared_artifacts as shared
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue._artifact_access import artifact_operation, validate_artifact_request
from loom.runs import OutputLocator
from tests.contracts.test_output_selection_contract import fixture

pytestmark = pytest.mark.contract
SCOPE = {"kind": "collection", "name": "run_store"}


def publish(authority, uri, ref, stage="produce"):
    previous = authority.list_output_commits(uri, stage_name=stage)
    attempt = authority.allocate_stage_attempt(
        uri, stage, owner_id="worker", lease_ttl_seconds=300
    )
    version = authority.record_output_commit(
        uri,
        stage,
        attempt_id=attempt.attempt.attempt_id,
        **(
            {"owner_id": "worker"}
            if not isinstance(authority, SQLitePerRunAuthorityStore)
            else {}
        ),
        fencing_token=attempt.lease.fencing_token,
        outputs={"out": ref},
        supersedes_commit_id=previous[-1].commit.commit_id if previous else None,
    )
    return OutputLocator(uri, stage, version.commit.commit_id, "out")


def local_ref(uri, content=b'{"value": 1}', checksum=True, name="result.json"):
    from loom.io.uris import uri_to_path

    path = uri_to_path(uri) / "artifacts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return ArtifactRef(
        "result",
        path.as_uri(),
        "summary",
        checksum=hash_bytes(content) if checksum else None,
        codec_key="never.execute",
        metadata={"_target_": "never.execute"},
    ), path


def shared_ref(daemon, uri, count=3):
    root = daemon.config.run_store_root.parent / "publications"
    tree = root / "tree"
    tree.mkdir(parents=True)
    limits = {
        "max_members": 1000,
        "max_payload_bytes": 8 * 1024 * 1024,
        "max_manifest_bytes": 1024 * 1024,
    }
    for n in range(count):
        path = tree / "nested" / f"{n:03}.bin"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes((f"payload {n}".encode() + b"\x00") * (35000 if n == 0 else 1))
    members = shared.inventory(tree, limits)
    receipt = {
        "schema_version": 1,
        "publication_id": "publication",
        "identity": {},
        "members": members,
        "outputs": {"out": "nested/000.bin"},
    }
    raw = shared.encoded(receipt)
    (tree / shared.RECEIPT).write_bytes(raw)
    binding = {
        "schema_version": 1,
        "root_id": "shared",
        "tree": "tree",
        "publication_id": "publication",
        "receipt_digest": hashlib.sha256(raw).hexdigest(),
        "primary": "nested/000.bin",
        "budgets": limits,
    }
    (root / "challenge").write_bytes(b"qualified")
    roots = {
        "shared": {
            "host_path": str(root),
            "publication": limits,
            "container_path": None,
            "access": "rw",
            "challenge": {
                "path": "challenge",
                "sha256": hashlib.sha256(b"qualified").hexdigest(),
            },
        }
    }
    if isinstance(daemon.config, SimpleNamespace):
        daemon.config.coordinator_shared_roots = roots
    else:
        daemon.config = replace(daemon.config, shared_roots=roots)
    return ArtifactRef(
        "tree",
        (tree / "nested/000.bin").as_uri(),
        "summary",
        metadata={shared.SHARED_PUBLICATION: binding},
    ), tree


class LocalClient(CoordinatorClient):
    def __init__(self, daemon):
        self.daemon = daemon

    def _native_call(self, operation, payload, expected=None, **kwargs):
        return artifact_operation(
            self.daemon, operation, validate_artifact_request(operation, payload)
        )


def test_fetch_expiry_during_verification_prevents_publication(tmp_path, monkeypatch):
    from loom import _artifact_fetch

    daemon, authority, uri = fixture(tmp_path)
    ref, _ = local_ref(uri)
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    now = [100.0]
    monkeypatch.setattr(_artifact_fetch, "time", SimpleNamespace(monotonic=lambda: now[0]))

    class ExpiringDigest:
        def __init__(self):
            self.digest = hashlib.sha256()

        def update(self, data):
            self.digest.update(data)

        def hexdigest(self):
            now[0] = 130.0
            return self.digest.hexdigest()

    monkeypatch.setattr(_artifact_fetch, "hashlib", SimpleNamespace(sha256=ExpiringDigest))
    destination = tmp_path / "fetch"
    result = client.fetch_artifacts(
        [{"locator": locator.to_dict()}], destination, scope=SCOPE, deadline=130.0
    )
    assert result["items"][0]["outcome"] == "failed"
    assert result["success_count"] == 0
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_local_exact_preview_corruption_legacy_and_authorization(tmp_path, backend):
    daemon, authority, uri = fixture(tmp_path, backend)
    ref, path = local_ref(uri, "a€z".encode())
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    description = client.describe_artifact(locator, scope=SCOPE)
    assert description["outcome"] == "available"
    assert client.read_artifact(locator, scope=SCOPE, limit=2)["content"] == "a"
    assert client.read_artifact(locator, scope=SCOPE, limit=2)["truncated"]
    assert (
        client.read_artifact(locator, scope=SCOPE, format="json", limit=2)["outcome"]
        == "too_large"
    )
    assert (
        client.read_artifact(locator, scope=SCOPE, format="json")["outcome"]
        == "invalid_content"
    )
    assert (
        client.describe_artifact(
            replace(locator, run_uri="file:///unapproved"), scope=SCOPE
        )["outcome"]
        == "unavailable"
    )
    path.write_bytes(b"corrupt")
    assert (
        client.describe_artifact(locator, scope=SCOPE)["outcome"] == "integrity_failed"
    )
    assert (
        client.read_artifact_chunk(
            locator,
            scope=SCOPE,
            declaration=description["declaration"],
            member=description["primary"],
            offset=0,
        )["outcome"]
        == "integrity_failed"
    )
    path.unlink()
    assert client.describe_artifact(locator, scope=SCOPE)["outcome"] == "unavailable"
    ref, path = local_ref(uri, b"\xff", False, "legacy")
    legacy = publish(authority, uri, ref, "legacy")
    assert (
        client.describe_artifact(legacy, scope=SCOPE)["verification"]
        == "unverified_original"
    )
    assert client.read_artifact(legacy, scope=SCOPE)["outcome"] == "invalid_content"
    assert (
        client.read_artifact(legacy, scope=SCOPE, format="bytes")["content"] == "/w=="
    )
    path.unlink()
    path.symlink_to(tmp_path / "private")
    (tmp_path / "private").write_text("secret")
    assert client.describe_artifact(legacy, scope=SCOPE)["outcome"] == "unavailable"


def test_complete_inventory_mixed_batch_dedup_conflict_and_receipt_changes(tmp_path):
    daemon, authority, uri = fixture(tmp_path)
    ref, tree = shared_ref(daemon, uri, count=205)
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    description = client.describe_artifact(locator, scope=SCOPE)
    assert len(description["members"]) == 100 and description["next_cursor"] == 100
    selected = {
        "locator": locator.to_dict(),
        "matched_run_uri": uri,
        "outcome": "selected",
    }
    from loom.pipeline.stores.read_models import ActionResultBinding
    from loom.runs import CollectionScope, OutputSelection
    from tests.contracts.test_output_selection_contract import select

    reused_uri = (daemon.config.run_store_root / "reused").as_uri()
    reused = SQLitePerRunAuthorityStore(reused_uri)
    reused.create_run(reused_uri)
    version = authority.list_output_commits(uri, stage_name="produce")[0]
    reused.bind_action_result(
        reused_uri,
        "adopted",
        ActionResultBinding(
            claim_id="reuse",
            execution_key="sha256:" + "a" * 64,
            commit=version.commit,
            artifact_facts=version.artifact_facts,
            verification={
                "schema_version": 1,
                "candidate_digest": "sha256:" + "b" * 64,
                "verdict": "verified",
            },
        ),
    )
    duplicate = select(
        daemon, OutputSelection(run_uris=(reused_uri,), scope=CollectionScope())
    ).items[0]
    unsupported = publish(
        authority, uri, ArtifactRef("cloud", "s3://bucket/file", "summary"), "cloud"
    )
    rows = [
        selected,
        {"locator": unsupported.to_dict()},
        duplicate,
        {"outcome": "no_matching_output", "matched_run_uri": "empty"},
    ]
    batch = client.fetch_artifacts(rows, tmp_path / "fetch", scope=SCOPE)
    assert (
        batch["complete"]
        and batch["success_count"] == 2
        and batch["failure_count"] == 2
    )
    assert [r["outcome"] for r in batch["items"]] == [
        "available",
        "unsupported_backend",
        "available",
        "no_matching_output",
    ]
    assert batch["items"][2]["matched_run_uri"] == reused_uri
    assert batch["items"][0]["local_path"] == batch["items"][2]["local_path"]
    target = Path(batch["items"][0]["local_path"])
    assert len(list(target.rglob("*.bin"))) == 205
    for source in tree.rglob("*.bin"):
        assert (target / source.relative_to(tree)).read_bytes() == source.read_bytes()
    assert (
        client.fetch_artifacts([selected], tmp_path / "fetch", scope=SCOPE)["items"][0][
            "outcome"
        ]
        == "destination_exists"
    )
    with pytest.raises(ValueError):
        client.read_artifact_chunk(
            locator,
            scope=SCOPE,
            declaration=description["declaration"],
            member="../private",
            offset=0,
        )
    assert (
        client.read_artifact_chunk(
            locator,
            scope=SCOPE,
            declaration=description["declaration"],
            member="undeclared",
            offset=0,
        )["outcome"]
        == "unavailable"
    )
    (tree / shared.RECEIPT).write_text("{}")
    assert (
        client.read_artifact_chunk(
            locator,
            scope=SCOPE,
            declaration=description["declaration"],
            member=description["primary"],
            offset=0,
        )["outcome"]
        == "integrity_failed"
    )


def test_no_overwrite_even_empty_concurrent_target(tmp_path):
    from loom._artifact_fetch import _publish

    pending, target = tmp_path / "pending", tmp_path / "target"
    pending.mkdir()
    (pending / "data").write_text("complete")
    target.mkdir()
    with pytest.raises(FileExistsError):
        _publish(pending, target)
    assert list(target.iterdir()) == [] and (pending / "data").exists()


def test_interrupted_retry_cleanup_corrupt_member_and_unavailable_authority(
    tmp_path, monkeypatch
):
    from loom.coordinator import CoordinatorClientError

    daemon, authority, uri = fixture(tmp_path)
    ref, tree = shared_ref(daemon, uri)
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    selected = {"locator": locator.to_dict()}
    original = client.read_artifact_chunk
    calls = []

    def lost_reply(loc, **options):
        result = original(loc, **options)
        calls.append(options)
        if len(calls) == 1:
            raise CoordinatorClientError(
                "unavailable", boundary="transport", operation="read_artifact_chunk"
            )
        return result

    monkeypatch.setattr(client, "read_artifact_chunk", lost_reply)
    result = client.fetch_artifacts([selected], tmp_path / "retry", scope=SCOPE)
    assert result["success_count"] == 1
    assert calls[0] == calls[1]

    def corrupt_chunk(loc, **options):
        import base64

        result = original(loc, **options)
        result["data"] = base64.b64encode(
            b"a" * len(base64.b64decode(result["data"]))
        ).decode()
        return result

    monkeypatch.setattr(client, "read_artifact_chunk", corrupt_chunk)
    result = client.fetch_artifacts([selected], tmp_path / "corrupt", scope=SCOPE)
    assert result["items"][0]["outcome"] == "integrity_failed"
    assert list((tmp_path / "corrupt").iterdir()) == []
    monkeypatch.setattr(client, "read_artifact_chunk", original)
    (tree / "nested/001.bin").write_bytes(b"corrupted")
    assert (
        client.describe_artifact(locator, scope=SCOPE)["outcome"] == "integrity_failed"
    )
    (tree / "nested/001.bin").unlink()
    assert client.describe_artifact(locator, scope=SCOPE)["outcome"] == "unavailable"

    def unavailable(_):
        raise OSError("offline")

    daemon.config.coordinator_authority_factory = unavailable
    assert client.describe_artifact(locator, scope=SCOPE)["outcome"] == "unavailable"


def test_directory_closure_successor_and_response_budget(tmp_path):
    from loom.pipeline.status import RunStatus, StageStatus
    from loom.pipeline.transition_policy import TransitionIntent
    from loom.queue._coordinator_control import encode_wire, MAX_RESPONSE_BYTES

    daemon, authority, uri = fixture(tmp_path)
    ref, path = local_ref(uri, b"\x00" * (256 * 1024))
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    preview = client.read_artifact(locator, scope=SCOPE)
    assert preview["outcome"] == "available" and preview["truncated"]
    assert len(encode_wire(preview)) < MAX_RESPONSE_BYTES
    authority.transition_stage(
        uri,
        "produce",
        from_status=StageStatus.SUCCEEDED,
        to_status=StageStatus.STALE,
        intent=TransitionIntent.RESUME,
    )
    newer, _ = local_ref(uri, b"new", name="new")
    publish(authority, uri, newer)
    authority.transition_run(
        uri, from_status=authority.open_run(uri).status, to_status=RunStatus.FAILED
    )
    assert client.read_artifact(locator, scope=SCOPE, limit=1)["content"] == "\x00"
    path.unlink()
    path.mkdir()
    assert (
        client.describe_artifact(locator, scope=SCOPE)["outcome"]
        == "unsupported_closure"
    )
