"""Exact committed files, complete receipt trees, and safe client publication."""

from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace

from typing import Any, cast

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
        if operation == "handshake":
            return SimpleNamespace(coordinator_id="test-coordinator")
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


@pytest.mark.parametrize("external_state_root", [False, True])
def test_ranges_read_the_named_original_fact_and_reauthorize_every_offset(tmp_path, monkeypatch, external_state_root):
    from loom.pipeline.stores.coordinator_authority import EmbeddedCoordinatorAuthorityFactory, embedded_coordinator_authority
    from loom.queue import _output_selection

    daemon, authority, uri = fixture(tmp_path)
    if external_state_root:
        state = tmp_path / "authority-state"
        state.mkdir(mode=0o700)
        factory = EmbeddedCoordinatorAuthorityFactory(state, tmp_path)
        authority = factory._store(uri)
        authority.create_run(uri)
        daemon.config.coordinator_authority_factory = factory
    else:
        daemon.config.coordinator_authority_factory = embedded_coordinator_authority
    original, _ = local_ref(uri, b"first-data", name="original.bin")
    current, _ = local_ref(uri, b"successor", name="successor.bin")
    from loom.pipeline.status import StageStatus
    from loom.pipeline.transition_policy import TransitionIntent

    locator = publish(authority, uri, original)
    authority.transition_stage(uri, "produce", from_status=StageStatus.SUCCEEDED,
                               to_status=StageStatus.STALE, intent=TransitionIntent.RESUME)
    publish(authority, uri, current)
    client = LocalClient(daemon)
    monkeypatch.setattr(SQLitePerRunAuthorityStore, "open_run", lambda *_: pytest.fail("full run read for exact artifact"))
    monkeypatch.setattr(SQLitePerRunAuthorityStore, "list_output_commits", lambda *a, **kw: pytest.fail("historical scan"))
    description = client.describe_artifact(locator, scope=SCOPE)
    assert description["outcome"] == "available"
    declaration, member = description["declaration"], description["primary"]
    assert isinstance(declaration, str) and isinstance(member, str)
    assert client.read_artifact_chunk(locator, scope=SCOPE, declaration=declaration, member=member, offset=0, length=4)["data"] == "Zmlycw=="
    for wrong in (replace(locator, stage_name="other"), replace(locator, output_name="other"), replace(locator, commit_id="other")):
        assert client.describe_artifact(wrong, scope=SCOPE)["outcome"] == "unavailable"
    monkeypatch.setattr(_output_selection, "authorized_run", lambda *args: False)
    assert client.read_artifact_chunk(locator, scope=SCOPE, declaration=declaration, member=member, offset=4, length=4)["outcome"] == "unavailable"


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


def test_pages_reuse_exact_declaration_and_recheck_companions_and_access(tmp_path, monkeypatch):
    from loom.queue import _artifact_access, _output_selection

    daemon, authority, uri = fixture(tmp_path)
    ref, tree = shared_ref(daemon, uri)
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    _artifact_access._cached_members.cache_clear()
    counts = {"parse": 0, "inventory": 0}
    parse, inventory = shared._parse_receipt, shared.inventory

    def parsed(*args):
        counts["parse"] += 1
        return parse(*args)
    def audited(*args):
        counts["inventory"] += 1
        return inventory(*args)
    monkeypatch.setattr(shared, "_parse_receipt", parsed)
    monkeypatch.setattr(shared, "inventory", audited)
    page = client.describe_artifact(locator, scope=SCOPE, limit=1)
    declaration, member = page["declaration"], page["primary"]
    assert isinstance(declaration, str) and isinstance(member, str)
    assert client.describe_artifact(locator, cursor=1, limit=1, scope=SCOPE, declaration=declaration)["outcome"] == "available"
    assert client.read_artifact_chunk(locator, member=member, offset=0, length=1, scope=SCOPE, declaration=declaration)["outcome"] == "available"
    assert counts == {"parse": 1, "inventory": 2}
    (tree / "nested/002.bin").write_bytes(b"replacement")
    assert client.describe_artifact(locator, cursor=2, limit=1, scope=SCOPE, declaration=declaration)["outcome"] == "integrity_failed"
    monkeypatch.setattr(_output_selection, "authorized_run", lambda *args: False)
    assert client.describe_artifact(locator, cursor=2, limit=1, scope=SCOPE, declaration=declaration)["outcome"] == "unavailable"
    assert client.read_artifact_chunk(locator, member=member, offset=1, length=1, scope=SCOPE, declaration=declaration)["outcome"] == "unavailable"


def test_kernel_snapshot_verification_across_pages(tmp_path, monkeypatch):
    """LOOM_TEST_IMMUTABLE_PUBLICATION selects a SquashFS mount of shared_ref's root."""
    import os
    from loom.queue import _immutable_tree, _output_selection

    mounted = os.environ.get("LOOM_TEST_IMMUTABLE_PUBLICATION")
    if mounted is None:
        pytest.skip("requires a mounted kernel publication snapshot")
    daemon, authority, uri = fixture(tmp_path)
    ref, _ = shared_ref(daemon, uri)
    mapping = daemon.config.coordinator_shared_roots["shared"]
    mapping["host_path"] = mounted
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    audited = []
    original = _immutable_tree._audit
    def counted(*args):
        audited.append(args[1])
        return original(*args)
    monkeypatch.setattr(_immutable_tree, "_audit", counted)
    first = client.describe_artifact(locator, scope=SCOPE, limit=1)
    second = client.describe_artifact(locator, scope=SCOPE, limit=1, cursor=1, declaration=first["declaration"])
    assert first["verification"] == second["verification"] == "recorded_sha256"
    assert first["members"] != second["members"] and len(audited) == 1
    monkeypatch.setattr(_output_selection, "authorized_run", lambda *args: False)
    assert client.describe_artifact(locator, scope=SCOPE, limit=1, cursor=2, declaration=first["declaration"])["outcome"] == "unavailable"


def test_complete_inventory_mixed_batch_dedup_conflict_and_receipt_changes(tmp_path, download_root):
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
    batch = client.fetch_artifacts(rows, download_root / "fetch", scope=SCOPE)
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
        client.fetch_artifacts([selected], download_root / "fetch", scope=SCOPE)["items"][0][
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


def test_no_overwrite_even_empty_concurrent_target(download_root):
    from loom._artifact_fetch import _publish

    pending, target = download_root / "pending", download_root / "target"
    pending.mkdir()
    (pending / "data").write_text("complete")
    target.mkdir()
    with pytest.raises(FileExistsError):
        _publish(pending, target)
    assert list(target.iterdir()) == [] and (pending / "data").exists()


def test_interrupted_retry_cleanup_corrupt_member_and_unavailable_authority(
    tmp_path, monkeypatch, download_root
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
    result = client.fetch_artifacts([selected], download_root / "retry", scope=SCOPE)
    assert result["success_count"] == 1
    assert calls.count(calls[0]) == 2

    def corrupt_chunk(loc, **options):
        import base64

        result = original(loc, **options)
        result["data"] = base64.b64encode(
            b"a" * len(base64.b64decode(result["data"]))
        ).decode()
        return result

    monkeypatch.setattr(client, "read_artifact_chunk", corrupt_chunk)
    result = client.fetch_artifacts([selected], download_root / "corrupt", scope=SCOPE)
    assert result["items"][0]["outcome"] == "integrity_failed"
    assert list((download_root / "corrupt").iterdir()) == []
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


def test_trusted_tree_fetch_refuses_incomplete_companion_export(tmp_path):
    from loom._artifact_fetch import fetch_artifacts

    daemon, authority, uri = fixture(tmp_path)
    ref, tree = shared_ref(daemon, uri)
    raw = dict(cast(dict[str, Any], ref.metadata[shared.SHARED_PUBLICATION]))
    limits = {**dict(raw["budgets"]), "policy": "trusted_shared_storage"}
    import json
    receipt = json.loads((tree / shared.RECEIPT).read_bytes())
    receipt["schema_version"] = 2
    receipt["members"] = receipt["members"][:1]
    data = shared.encoded(receipt)
    (tree / shared.RECEIPT).write_bytes(data)
    raw.update(schema_version=2, budgets=limits, receipt_digest=hashlib.sha256(data).hexdigest())
    roots = dict(daemon.config.coordinator_shared_roots)
    roots["shared"] = {**roots["shared"], "publication": limits}
    if isinstance(daemon.config, SimpleNamespace):
        daemon.config.coordinator_shared_roots = roots
    else:
        daemon.config = replace(daemon.config, shared_roots=roots)
    ref = replace(ref, metadata={shared.SHARED_PUBLICATION: raw})
    locator = publish(authority, uri, ref)
    result = fetch_artifacts(LocalClient(daemon), [{"locator": locator.to_dict()}],
        tmp_path / "download", scope=SCOPE, expected_coordinator_id=None)
    assert result["items"][0]["outcome"] == "unsupported_backend"
    assert not (tmp_path / "download").exists()


def test_later_ranges_complete_with_first_range_paused(tmp_path, monkeypatch, download_root):
    from threading import Event, Lock
    from loom._artifact_ranges import CHUNK_BYTES, RANGE_WINDOW

    daemon, authority, uri = fixture(tmp_path)
    data = bytes(range(251)) * (CHUNK_BYTES * (RANGE_WINDOW + 2) // 251)
    ref, _ = local_ref(uri, data)
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    original = client.read_artifact_chunk
    first, advanced, lock = Event(), Event(), Lock()
    active = peak = 0
    def read(loc, **options):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            offset = options["offset"]
            if not offset:
                first.set()
                assert advanced.wait(5)
            assert first.wait(5)
            result = original(loc, **options)
            if offset >= CHUNK_BYTES * RANGE_WINDOW:
                advanced.set()
            return result
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(client, "read_artifact_chunk", read)
    result = client.fetch_artifacts([{"locator": locator.to_dict()}], download_root / "window", scope=SCOPE)
    assert result["success_count"] == 1 and 1 < peak <= RANGE_WINDOW
    assert Path(result["items"][0]["primary_path"]).read_bytes() == data


def test_concurrent_fleet_checks_share_range_capacity_and_verify_each_destination(tmp_path, monkeypatch, download_root):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    from loom import _artifact_fetch, _artifact_ranges

    daemon, authority, uri = fixture(tmp_path)
    data = b"v" * (_artifact_ranges.CHUNK_BYTES * 5)
    ref, _ = local_ref(uri, data)
    locator = publish(authority, uri, ref)
    gate, full, submitted, lock = Event(), Event(), Event(), Lock()
    clients, pools = set(), set()
    active = peak = 0
    read = LocalClient.read_artifact_chunk
    submit = ThreadPoolExecutor.submit

    def offer(pool, fn, *args, **kwargs):
        future = submit(pool, fn, *args, **kwargs)
        if args and args[0] is _artifact_ranges._read:
            with lock:
                clients.add(args[1])
                pools.add(pool)
                if len(clients) == 3:
                    submitted.set()
        return future

    def held(client, locator, **kw):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == _artifact_ranges.RANGE_WINDOW:
                full.set()
        try:
            assert gate.wait(10)
            return read(client, locator, **kw)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(ThreadPoolExecutor, "submit", offer)
    monkeypatch.setattr(LocalClient, "read_artifact_chunk", held)
    with ThreadPoolExecutor(max_workers=3) as callers:
        checks = [callers.submit(_artifact_fetch.fetch_artifacts, LocalClient(daemon), [{"locator": locator.to_dict()}],
                                 download_root / str(i), scope=SCOPE, expected_coordinator_id="test-coordinator",
                                 check_scratch=True) for i in range(3)]
        try:
            assert submitted.wait(10) and full.wait(10)
            assert len(pools) == 1
        finally:
            gate.set()
        for check in checks:
            result = check.result()["items"][0]
            assert result["verification"] == "recorded_sha256"
            assert Path(result["primary_path"]).read_bytes() == data
    assert peak == _artifact_ranges.RANGE_WINDOW
    assert "test-coordinator" not in _artifact_ranges._check_pools


@pytest.mark.parametrize(("errors", "outcome"), [
    (["deadline_exceeded"], "available"),
    (["deadline_exceeded", "deadline_exceeded"], "transport_deadline_exceeded"),
    (["capacity_exhausted"], "capacity_exhausted"),
])
def test_range_attempt_deadline_and_capacity_remain_distinct_from_observer_expiry(
    tmp_path, monkeypatch, download_root, errors, outcome,
):
    from time import monotonic
    from loom import _artifact_fetch
    from loom.queue._coordinator_control import CoordinatorClientError

    daemon, authority, uri = fixture(tmp_path)
    ref, _ = local_ref(uri)
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    read = client.read_artifact_chunk
    failures = iter(errors)
    offsets = []
    def limited(loc, **options):
        offsets.append(options["offset"])
        code = next(failures, None)
        if code is not None:
            raise CoordinatorClientError(code, operation="read_artifact_chunk", ids={}, boundary="connection")
        return read(loc, **options)
    monkeypatch.setattr(client, "read_artifact_chunk", limited)
    result = _artifact_fetch.fetch_artifacts(client, [{"locator": locator.to_dict()}], download_root / "check",
        scope=SCOPE, expected_coordinator_id="test-coordinator", check_scratch=True, deadline=monotonic() + 30)
    assert result["items"][0]["outcome"] == outcome
    assert offsets == ([0, 0] if errors[0] == "deadline_exceeded" else [0])


def test_check_scratch_reauthorizes_and_restarts_changed_declaration(tmp_path, monkeypatch, download_root):
    from loom import _artifact_ranges, _artifact_fetch

    daemon, authority, uri = fixture(tmp_path)
    ref, member = local_ref(uri, b"a" * 320000, checksum=False)
    locator = publish(authority, uri, ref)
    client = LocalClient(daemon)
    selected = [{"locator": locator.to_dict()}]
    destination = download_root / "private"
    def fetch():
        return _artifact_fetch.fetch_artifacts(
            client, selected, destination, scope=SCOPE, expected_coordinator_id="test-coordinator",
            check_scratch=True,
        )["items"][0]
    save = _artifact_ranges._save
    def stop(path, data):
        save(path, data)
        raise TimeoutError("observer detached")
    monkeypatch.setattr(_artifact_ranges, "_save", stop)
    first = fetch()
    assert first["outcome"] == "failed" and list((destination / ".ranges").glob("*/*"))
    monkeypatch.setattr(_artifact_ranges, "_save", save)
    resolver = daemon.config.coordinator_authority_factory
    def offline(_):
        raise OSError("owner unavailable")
    monkeypatch.setattr(daemon.config, "coordinator_authority_factory", offline)
    assert fetch()["outcome"] == "unavailable"
    monkeypatch.setattr(daemon.config, "coordinator_authority_factory", resolver)
    member.write_bytes(b"b" * 320000)
    result = fetch()
    assert result["outcome"] == "available" and result["verification"] == "unverified_original"
    assert result["declaration"] != first["declaration"]
    assert result["transfer"]["reused_bytes"] == 0
    assert Path(result["primary_path"]).read_bytes() == member.read_bytes()
