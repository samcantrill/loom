from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from loom.pipeline.executors.slurm.errors import SlurmPlanningError
from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
import loom.pipeline.executors.slurm.trusted_user as trusted


def _provider(tmp_path, **kwargs):
    return SlurmUserPrivateFileProvider(
        root=tmp_path / "credentials", descriptor="trusted-test-v1", **kwargs,
    )


def test_prepare_is_private_replayable_and_never_replaces_a_consumed_token(tmp_path):
    provider = _provider(tmp_path)
    assert not provider.root.exists()
    receipt = provider.prepare(operation_id="operation", request_digest="request")
    path = Path(receipt.path)
    token = path.read_bytes()
    assert len(token) == 32
    assert hashlib.sha256(token).hexdigest() == receipt.verifier
    assert provider.read_capability(operation_id="operation", request_digest="request") == token
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    stored = (path.parent / "receipt.json").read_bytes()
    assert token not in stored
    assert token.hex() not in json.dumps(asdict(receipt))
    reopened = _provider(tmp_path)
    assert reopened.prepare(operation_id="operation", request_digest="request") == receipt
    path.unlink()
    assert reopened.prepare(operation_id="operation", request_digest="request") == receipt
    assert not path.exists()
    with pytest.raises(SlurmPlanningError, match="replay conflicts"):
        reopened.prepare(operation_id="operation", request_digest="changed")
    second = reopened.prepare(operation_id="other", request_digest="request")
    assert second.path != receipt.path
    assert second.verifier != receipt.verifier


def test_concurrent_processes_publish_one_receipt(tmp_path):
    provider = _provider(tmp_path)
    code = (
        "from dataclasses import asdict; import json, sys; "
        "from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider; "
        "p=SlurmUserPrivateFileProvider(root=sys.argv[1],descriptor='trusted-test-v1'); "
        "print(json.dumps(asdict(p.prepare(operation_id='same',request_digest='request'))))"
    )
    children = [
        subprocess.Popen([sys.executable, "-c", code, str(provider.root)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(4)
    ]
    try:
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=30)
            assert child.returncode == 0, stderr
            results.append(json.loads(stdout))
        assert all(value == results[0] for value in results)
        assert len(list(provider.root.glob("[!.]*"))) == 1
        assert len(list((provider.root / ".locks").glob("*.lock"))) == 1
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


@pytest.mark.parametrize("published", [False, True])
def test_sync_failure_retains_only_published_identity(tmp_path, monkeypatch, published):
    provider = _provider(tmp_path)
    final = provider.path_for("operation").parent
    sync = trusted._fsync_path_strict
    failed = False

    def fail_sync(path):
        nonlocal failed
        at_boundary = path == provider.root and final.exists() if published else path.name.startswith("." + final.name + ".")
        if at_boundary and not failed:
            failed = True
            raise OSError("injected sync failure")
        sync(path)

    monkeypatch.setattr(trusted, "_fsync_path_strict", fail_sync)
    with pytest.raises(OSError, match="injected sync"):
        provider.prepare(operation_id="operation", request_digest="request")
    assert failed
    assert final.exists() is published
    assert not list(provider.root.glob(f".{final.name}.*"))
    before = (final / "receipt.json").read_bytes() if published else None
    receipt = provider.prepare(operation_id="operation", request_digest="request")
    if published:
        assert (final / "receipt.json").read_bytes() == before
        assert before is not None
        assert json.loads(before)["prepared"] == asdict(receipt)


def test_revoke_replay_is_exact_and_preserves_lock_inode(tmp_path):
    provider = _provider(tmp_path)
    receipt = provider.prepare(operation_id="operation", request_digest="request")
    path = Path(receipt.path)
    lock = provider.root / ".locks" / (path.parent.name + ".lock")
    inode = lock.stat().st_ino
    with pytest.raises(SlurmPlanningError, match="receipt conflicts"):
        provider.revoke(replace(receipt, verifier="0" * 64))
    assert path.exists()
    provider.revoke(receipt)
    provider.revoke(receipt)
    assert not path.exists()
    assert lock.stat().st_ino == inode
    assert (path.parent / "revoked.json").is_file()
    with pytest.raises(SlurmPlanningError, match="revoked"):
        provider.prepare(operation_id="operation", request_digest="request")
    with pytest.raises(SlurmPlanningError, match="revoked"):
        provider.read_capability(operation_id="operation", request_digest="request")


def test_revoke_crash_after_tombstone_cannot_prepare_again(tmp_path, monkeypatch):
    provider = _provider(tmp_path)
    receipt = provider.prepare(operation_id="operation", request_digest="request")
    path = Path(receipt.path)
    unlink = Path.unlink

    def fail_unlink(target, *args, **kwargs):
        if target == path:
            raise OSError("injected unlink failure")
        return unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(OSError, match="injected unlink"):
        provider.revoke(receipt)
    assert path.exists()
    with pytest.raises(SlurmPlanningError, match="revoked"):
        provider.prepare(operation_id="operation", request_digest="request")
    monkeypatch.setattr(Path, "unlink", unlink)
    provider.revoke(receipt)
    assert not path.exists()


@pytest.mark.parametrize("change", ["permissions", "symlink", "corrupt", "request", "descriptor"])
def test_bootstrap_refuses_invalid_delivery(tmp_path, change):
    provider = _provider(tmp_path)
    receipt = provider.prepare(operation_id="operation", request_digest="request")
    path = Path(receipt.path)
    digest = "request"
    if change == "permissions":
        path.chmod(0o644)
    elif change == "symlink":
        target = tmp_path / "elsewhere"
        path.rename(target)
        path.symlink_to(target)
    elif change == "corrupt":
        path.write_bytes(b"x" * 32)
    elif change == "request":
        digest = "changed"
    else:
        provider = SlurmUserPrivateFileProvider(root=provider.root, descriptor="changed")
    with pytest.raises(SlurmPlanningError):
        provider.read_capability(operation_id="operation", request_digest=digest)


def test_changed_ttl_conflicts_for_provider_but_compute_uses_retained_expiry(tmp_path):
    provider = _provider(tmp_path, ttl_seconds=60)
    receipt = provider.prepare(operation_id="operation", request_digest="request")
    changed = _provider(tmp_path)
    with pytest.raises(SlurmPlanningError, match="TTL conflicts"):
        changed.prepare(operation_id="operation", request_digest="request")
    assert changed.read_capability(operation_id="operation", request_digest="request") == Path(receipt.path).read_bytes()


def test_private_root_is_not_adopted_by_chmod_or_following_symlink(tmp_path):
    root = tmp_path / "credentials"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    with pytest.raises(SlurmPlanningError, match="0700"):
        _provider(tmp_path).prepare(operation_id="operation", request_digest="request")
    assert root.stat().st_mode & 0o777 == 0o755
    target = tmp_path / "target"
    root.rename(target)
    root.symlink_to(target)
    with pytest.raises(SlurmPlanningError, match="symlinks"):
        _provider(tmp_path).prepare(operation_id="operation", request_digest="request")


def test_trusted_user_profile_identity_and_supported_bootstrap_modes(tmp_path):
    from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
    from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import _profile

    provider = _provider(tmp_path)
    profile = _profile(FakeSlurmCommandRunner(), provider=provider)
    same = replace(profile, job_private_file_provider=_provider(tmp_path))
    assert same.configuration_fingerprint == profile.configuration_fingerprint
    changed = replace(profile, job_private_file_provider=_provider(tmp_path, ttl_seconds=60))
    assert changed.configuration_fingerprint != profile.configuration_fingerprint
    with pytest.raises(SlurmPlanningError, match="native bootstrap"):
        replace(profile, container_options={"image": {"reference": "fixture.sif"}})
    assert not provider.root.exists()


def test_legacy_profile_keeps_the_published_configuration_fingerprint():
    from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
    from loom.pipeline.executors.slurm.ready_stage import SlurmJobPrivateFileProvider
    from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import _profile

    profile = _profile(FakeSlurmCommandRunner(), provider=SlurmJobPrivateFileProvider(
        fixed_path="/private/capability", descriptor="fake-prolog-v1", helper_argv=("/bin/true",),
    ))
    # Observed from the installed unmodified 01a0ab48 runtime, without invoking a helper.
    assert profile.configuration_fingerprint == "b281811909d797c011e9d87839468da76a5724ad60d20674d789d4d75899eca3"
