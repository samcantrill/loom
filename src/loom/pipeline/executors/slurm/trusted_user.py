"""Durable bootstrap credentials for deployments that trust every same-UID process.

This provider does not claim allocation-private isolation. The protected root
must be visible at the same absolute path to the submit agent and bootstrap.
Secrets are file-only; returned receipts contain a SHA-256 verifier, not a token.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from datetime import timedelta
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import tempfile

from loom.pipeline.stores.atomic import (
    _ensure_durable_parent,
    _fsync_path_strict,
    atomic_write_json,
)
from loom.timestamps import parse_timestamp, utc_now, utc_timestamp

from .errors import SlurmPlanningError
from .ready_stage import JobPrivateFilePrepared


_KIND = "user_private_file_v1"
_RECEIPT_FIELDS = {
    "version", "kind", "operation_id", "request_digest", "ttl_seconds", "prepared",
}


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024 or any(ord(c) < 32 or c.isspace() for c in value):
        raise SlurmPlanningError(f"trusted-user {name} is invalid")
    return value


def operation_key(operation_id: str) -> str:
    """One operation has one path, including conflicting request replays."""
    return hashlib.sha256(_text(operation_id, "operation_id").encode()).hexdigest()


def _private_directory(path: Path, *, create: bool = False) -> None:
    if path.resolve() != path:
        raise SlurmPlanningError("trusted-user directory must not traverse symlinks")
    if create:
        _ensure_durable_parent(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise SlurmPlanningError("trusted-user directory is unavailable") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise SlurmPlanningError("trusted-user directory must be owned and mode 0700")


def _read_private(path: Path, *, maximum: int) -> bytes:
    """Read a bounded, owned regular file without following its final symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or not 0 < info.st_size <= maximum
            ):
                raise SlurmPlanningError("trusted-user file must be bounded, owned and mode 0600")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(maximum + 1)
            if len(data) != info.st_size:
                raise SlurmPlanningError("trusted-user file changed during read")
            return data
        finally:
            os.close(fd)
    except OSError as exc:
        raise SlurmPlanningError("trusted-user file is unavailable") from exc


def _read_json(path: Path) -> object:
    try:
        return json.loads(_read_private(path, maximum=16 * 1024))
    except (ValueError, UnicodeError) as exc:
        raise SlurmPlanningError("trusted-user receipt is invalid") from exc


class SlurmUserPrivateFileProvider:
    """Replayable file delivery with an explicit same-user trust boundary.

    Construction validates declarations without creating files. Preparation and
    revocation use stable per-operation flock files, which must never be unlinked
    while an operation can be replayed. Filesystem locking/fsync support must be
    qualified by the deployment; this class cannot certify network storage.
    """

    delivery_kind = _KIND

    def __init__(
        self, *, root: str | Path, descriptor: str, ttl_seconds: int = 604800,
    ) -> None:
        self.root = Path(root)
        if not self.root.is_absolute() or ".." in self.root.parts:
            raise SlurmPlanningError("trusted-user root must be absolute without '..'")
        self.descriptor = _text(descriptor, "descriptor")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 31_536_000:
            raise SlurmPlanningError("trusted-user TTL must be an integer in 1..31536000")
        self.ttl_seconds = ttl_seconds

    def binding_identity(self) -> Mapping[str, object]:
        return {
            "kind": self.delivery_kind,
            "root": str(self.root),
            "descriptor": self.descriptor,
            "ttl_seconds": self.ttl_seconds,
        }

    def path_for(self, operation_id: str) -> Path:
        return self.root / operation_key(operation_id) / "capability"

    @contextmanager
    def _locked(self, key: str, *, create: bool = False) -> Iterator[None]:
        _private_directory(self.root, create=create)
        locks = self.root / ".locks"
        _private_directory(locks, create=create)
        flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
        fd = os.open(locks / f"{key}.lock", flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise SlurmPlanningError("trusted-user lock must be owned and mode 0600")
            fcntl.flock(fd, fcntl.LOCK_EX)
            _fsync_path_strict(locks)
            yield
        finally:
            os.close(fd)

    def _retained(
        self, directory: Path, *, require_ttl: bool = True,
    ) -> tuple[Mapping[str, object], JobPrivateFilePrepared]:
        _private_directory(directory)
        value = _read_json(directory / "receipt.json")
        if not isinstance(value, dict) or set(value) != _RECEIPT_FIELDS or type(value["version"]) is not int or value["version"] != 1 or value["kind"] != self.delivery_kind:
            raise SlurmPlanningError("trusted-user receipt fields are invalid")
        if operation_key(value["operation_id"]) != directory.name:
            raise SlurmPlanningError("trusted-user receipt operation conflicts")
        _text(value["request_digest"], "request_digest")
        ttl = value["ttl_seconds"]
        if type(ttl) is not int or not 1 <= ttl <= 31_536_000 or require_ttl and ttl != self.ttl_seconds:
            raise SlurmPlanningError("trusted-user receipt TTL conflicts")
        fields = value["prepared"]
        if not isinstance(fields, dict) or set(fields) != {"receipt", "verifier", "expires_at", "path", "descriptor"}:
            raise SlurmPlanningError("trusted-user prepared receipt is invalid")
        prepared = JobPrivateFilePrepared(**fields)
        if prepared.path != str(directory / "capability") or prepared.descriptor != self.descriptor:
            raise SlurmPlanningError("trusted-user receipt binding conflicts")
        if len(prepared.verifier) != 64 or any(c not in "0123456789abcdef" for c in prepared.verifier):
            raise SlurmPlanningError("trusted-user verifier is invalid")
        try:
            parse_timestamp(prepared.expires_at)
        except ValueError as exc:
            raise SlurmPlanningError("trusted-user expiry is invalid") from exc
        return value, prepared

    def prepare(self, *, operation_id: str, request_digest: str) -> JobPrivateFilePrepared:
        key = operation_key(operation_id)
        _text(request_digest, "request_digest")
        directory = self.root / key
        with self._locked(key, create=True):
            # Tombstones take precedence over any replay, including absent tokens.
            if os.path.lexists(directory / "revoked.json"):
                raise SlurmPlanningError("trusted-user operation is revoked")
            if os.path.lexists(directory):
                value, prepared = self._retained(directory)
                if value["operation_id"] != operation_id or value["request_digest"] != request_digest:
                    raise SlurmPlanningError("trusted-user preparation replay conflicts")
                # The file may have been consumed. Never mint a replacement token.
                if os.path.lexists(prepared.path):
                    token = _read_private(Path(prepared.path), maximum=32)
                    if len(token) != 32 or not hmac.compare_digest(hashlib.sha256(token).hexdigest(), prepared.verifier):
                        raise SlurmPlanningError("trusted-user capability conflicts")
                _fsync_path_strict(directory)
                _fsync_path_strict(self.root)
                return prepared

            token = secrets.token_bytes(32)
            prepared = JobPrivateFilePrepared(
                receipt="user-private-" + secrets.token_hex(16),
                verifier=hashlib.sha256(token).hexdigest(),
                expires_at=utc_timestamp(utc_now() + timedelta(seconds=self.ttl_seconds), timespec="microseconds"),
                path=str(directory / "capability"),
                descriptor=self.descriptor,
            )
            staging = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=self.root))
            try:
                fd = os.open(staging / "capability", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(token)
                    stream.flush()
                    os.fsync(stream.fileno())
                atomic_write_json(staging / "receipt.json", {
                    "version": 1, "kind": self.delivery_kind,
                    "operation_id": operation_id, "request_digest": request_digest,
                    "ttl_seconds": self.ttl_seconds, "prepared": asdict(prepared),
                }, durability="strict")
                _fsync_path_strict(staging)
                # All supported publishers hold the same persistent lock. Refuse
                # a conflicting target; never replace an acknowledged directory.
                if os.path.lexists(directory):
                    raise SlurmPlanningError("trusted-user publication target exists")
                staging.rename(directory)
                _fsync_path_strict(self.root)
            finally:
                # A published directory is deliberately retained after sync failure.
                if staging.exists():
                    shutil.rmtree(staging)
                    _fsync_path_strict(self.root)
            return prepared

    def revoke(self, prepared: JobPrivateFilePrepared) -> None:
        if not isinstance(prepared, JobPrivateFilePrepared):
            raise SlurmPlanningError("trusted-user revocation receipt is invalid")
        path = Path(prepared.path)
        key = path.parent.name
        if path != self.root / key / "capability" or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise SlurmPlanningError("trusted-user revocation path conflicts")
        with self._locked(key):
            _, retained = self._retained(path.parent)
            if prepared != retained:
                raise SlurmPlanningError("trusted-user revocation receipt conflicts")
            tombstone = {"version": 1, "receipt": prepared.receipt, "verifier": prepared.verifier}
            revoked = path.parent / "revoked.json"
            if os.path.lexists(revoked) and _read_json(revoked) != tombstone:
                raise SlurmPlanningError("trusted-user revocation conflicts")
            atomic_write_json(revoked, tombstone, durability="strict")
            path.unlink(missing_ok=True)
            _fsync_path_strict(path.parent)

    def read_capability(self, *, operation_id: str, request_digest: str) -> bytes:
        """Validate the protected receipt before compute-side registration.

        Coordinator accepted time owns first-use expiry; the worker clock must
        not reject an exact consumed registration replay.
        """
        key = operation_key(operation_id)
        with self._locked(key):
            directory = self.root / key
            if os.path.lexists(directory / "revoked.json"):
                raise SlurmPlanningError("trusted-user operation is revoked")
            value, prepared = self._retained(directory, require_ttl=False)
            if value["operation_id"] != operation_id or value["request_digest"] != request_digest:
                raise SlurmPlanningError("trusted-user bootstrap request conflicts")
            token = _read_private(Path(prepared.path), maximum=32)
            if len(token) != 32 or not hmac.compare_digest(hashlib.sha256(token).hexdigest(), prepared.verifier):
                raise SlurmPlanningError("trusted-user bootstrap capability conflicts")
            return token
