"""Attempt-bound shared bytes; the coordinator remains the only finalizer.

The protected site root must qualify atomic replace, fsync and advisory locking
across both mounts. Reservations account for the maximum admitted transfer;
unacknowledged attempts are never evicted to make room for another job.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Iterator, cast

from loom.serialization import PlainData
from ._remote_stage_execution import (
    MAX_TRANSFER_BYTES,
    TRANSFER_CHUNK_BYTES,
    _RemoteExecutionReport,
    _atomic_regular_file,
    _fsync_directory,
    _read_regular_file_bytes,
)
from .errors import QueueConflictError, QueueServiceError

# Report requests already cross the 64 KiB agent application boundary. Reserve
# a MiB for the report, manifest, and fixed identity/reservation records together.
_RESERVATION_BYTES = MAX_TRANSFER_BYTES + 1024 * 1024
_REPORT_BYTES = 60 * 1024
_MANIFEST_BYTES = 64 * 1024


def _json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def validate_identity(value: object, expected: Mapping[str, PlainData]) -> None:
    if value != expected:
        raise QueueConflictError("SLURM retained result identity conflicts")


class SharedSlurmResult:
    """Read/publish only the location bound by this protected profile/assignment."""

    def __init__(
        self,
        storage: Mapping[str, object] | None,
        assignment_id: str,
        *,
        compute: bool = False,
    ) -> None:
        if storage is None:
            raise QueueServiceError("SLURM requires qualified durable result storage")
        if (
            not assignment_id
            or assignment_id in {".", ".."}
            or any(
                c
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
                for c in assignment_id
            )
        ):
            raise QueueServiceError("SLURM result assignment path is invalid")
        self.storage = storage
        self.root = Path(
            cast(str, storage["compute_root" if compute else "agent_root"])
        )
        if self.root.is_symlink() or not self.root.is_dir():
            raise QueueServiceError("SLURM qualified result root is unavailable")
        self.path = self.root / assignment_id
        self.assignment_id = assignment_id

    def _file(self, relative: str, *, bound: int) -> bytes:
        path = Path(relative)
        if (
            path.is_absolute()
            or not path.parts
            or any(p in {".", ".."} for p in path.parts)
        ):
            raise QueueConflictError("SLURM result path is not contained")
        current = self.path
        for part in ("", *path.parts):
            if part:
                current = current / part
            if current.is_symlink():
                raise QueueConflictError("SLURM result path contains a link")
        return _read_regular_file_bytes(current, max_bytes=bound)

    @contextmanager
    def _quota_lock(self) -> Iterator[None]:
        fd = os.open(
            self.root / ".retention.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def reserve(self, assignment: Mapping[str, PlainData]) -> None:
        encoded = _json(assignment)
        with self._quota_lock():
            if self.path.exists():
                if self._file("binding.json", bound=_MANIFEST_BYTES) != encoded:
                    raise QueueConflictError("SLURM result reservation conflicts")
                return
            # Only this transport namespace is counted; there is no output discovery.
            attempts = [p for p in self.root.iterdir() if p.name != ".retention.lock"]
            if (len(attempts) + 1) * _RESERVATION_BYTES > cast(
                int, self.storage["retention_bytes"]
            ):
                raise QueueServiceError(
                    "SLURM result retention quota exhausted; retained attempts were not evicted"
                )
            self.path.mkdir(mode=0o700)
            _atomic_regular_file(self.path / "binding.json", encoded)
            _fsync_directory(self.root)

    def publish(
        self,
        identity: Mapping[str, PlainData],
        report: _RemoteExecutionReport,
        output: Callable[[str, int], tuple[bytes, bool]],
    ) -> None:
        validate_identity(
            json.loads(self._file("binding.json", bound=_MANIFEST_BYTES)),
            cast(Mapping[str, PlainData], identity["assignment"]),
        )
        if not identity.get("fence") or not identity.get("incarnation"):
            raise QueueConflictError("SLURM result requires an execution grant")
        if report.assignment_id != self.assignment_id:
            raise QueueConflictError("SLURM result report assignment conflicts")
        if self.path.is_symlink() or (self.path / "outputs").is_symlink():
            raise QueueConflictError("SLURM result publication path contains a link")
        encoded = _json(report.to_dict())
        if (
            len(encoded) > _REPORT_BYTES
            or sum(p.size_bytes for p in report.outputs) > MAX_TRANSFER_BYTES
        ):
            self.failure("SLURM result exceeds existing report/artifact bounds")
            raise QueueServiceError(
                "SLURM result exceeds existing report/artifact bounds"
            )
        # Use the existing application decoder before publication as well as
        # during delivery, including space for the authenticated session envelope.
        from .agent_session_transport import _decode
        from .agent_sessions import _MAX_IDENTIFIER

        wire = {
            "session_id": "s" * _MAX_IDENTIFIER,
            "coordinator_epoch": "e" * _MAX_IDENTIFIER,
            "cursor": "c" * _MAX_IDENTIFIER,
            "evidence": {
                "assignment_id": self.assignment_id,
                "identity": dict(identity),
                "result_operation": "report",
                "report": report.to_dict(),
            },
        }
        try:
            _decode(_json(wire), failure_report=True)
        except QueueServiceError as exc:
            self.failure(str(exc))
            raise
        if (self.path / "manifest.json").exists():
            previous, _ = self.read(identity)
            if previous != report:
                raise QueueConflictError("SLURM result publication replay conflicts")
            return
        artifacts = []
        for item in report.outputs:
            data = bytearray()
            while True:
                chunk, final = output(item.transfer_id, len(data))
                data.extend(chunk)
                if len(data) > item.size_bytes:
                    raise QueueConflictError("SLURM output exceeds declaration")
                if final:
                    break
                if not chunk:
                    raise QueueConflictError("SLURM output copy made no progress")
            if (
                len(data) != item.size_bytes
                or hashlib.sha256(data).hexdigest() != item.digest
            ):
                raise QueueConflictError("SLURM output bytes conflict")
            relative = "outputs/" + item.transfer_id
            _atomic_regular_file(self.path / relative, bytes(data))
            artifacts.append(
                {
                    "logical_name": item.logical_name,
                    "path": relative,
                    "size_bytes": item.size_bytes,
                    "digest": item.digest,
                }
            )
        _atomic_regular_file(self.path / "report.json", encoded)
        _fsync_directory(self.path)
        manifest = {
            "schema_version": 1,
            "identity": dict(identity),
            "report": {
                "path": "report.json",
                "size_bytes": len(encoded),
                "digest": hashlib.sha256(encoded).hexdigest(),
            },
            "artifacts": artifacts,
        }
        _atomic_regular_file(self.path / "manifest.json", _json(manifest))

    def read(
        self, identity: Mapping[str, PlainData]
    ) -> tuple[_RemoteExecutionReport, dict[str, bytes]]:
        manifest = json.loads(self._file("manifest.json", bound=_MANIFEST_BYTES))
        if (
            set(manifest) != {"schema_version", "identity", "report", "artifacts"}
            or type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != 1
        ):
            raise QueueConflictError("SLURM result manifest schema is invalid")
        validate_identity(manifest["identity"], identity)

        def checked(descriptor: Mapping[str, object], bound: int) -> bytes:
            data = self._file(cast(str, descriptor["path"]), bound=bound)
            if (
                len(data) != descriptor["size_bytes"]
                or hashlib.sha256(data).hexdigest() != descriptor["digest"]
            ):
                raise QueueConflictError("SLURM retained result size/digest conflicts")
            return data

        report = _RemoteExecutionReport.from_dict(
            json.loads(checked(manifest["report"], _REPORT_BYTES))
        )
        if report.assignment_id != self.assignment_id or len(
            manifest["artifacts"]
        ) != len(report.outputs):
            raise QueueConflictError("SLURM retained output declaration conflicts")
        outputs = {}
        for item, descriptor in zip(report.outputs, manifest["artifacts"], strict=True):
            if descriptor != {
                "logical_name": item.logical_name,
                "path": "outputs/" + item.transfer_id,
                "size_bytes": item.size_bytes,
                "digest": item.digest,
            }:
                raise QueueConflictError("SLURM retained output descriptor conflicts")
            outputs[item.transfer_id] = checked(descriptor, item.size_bytes)
        return report, outputs

    def failure(self, reason: str) -> None:
        _atomic_regular_file(
            self.path / "delivery-failure.json", _json({"failure": reason[:1024]})
        )

    def deliver(
        self,
        identity: Mapping[str, PlainData],
        call: Callable[[Mapping[str, PlainData]], Mapping[str, PlainData]],
    ) -> bool:
        if not (self.path / "manifest.json").exists():
            return False
        try:
            report, outputs = self.read(identity)
        except (
            ValueError,
            TypeError,
            KeyError,
            OSError,
            QueueServiceError,
            QueueConflictError,
        ) as exc:
            self.failure(str(exc))
            raise QueueConflictError(
                "SLURM retained result is invalid; evidence retained"
            ) from exc
        binding: dict[str, PlainData] = {
            "assignment_id": self.assignment_id,
            "identity": dict(identity),
        }
        call({**binding, "result_operation": "report", "report": report.to_dict()})
        for item in report.outputs:
            data = outputs[item.transfer_id]
            for offset in range(0, max(1, len(data)), TRANSFER_CHUNK_BYTES):
                chunk = data[offset : offset + TRANSFER_CHUNK_BYTES]
                response = call(
                    {
                        **binding,
                        "result_operation": "output",
                        "transfer_id": item.transfer_id,
                        "offset": offset,
                        "data": base64.b64encode(chunk).decode(),
                        "final": offset + len(chunk) == len(data),
                    }
                )
                if response.get("received") != offset + len(chunk):
                    raise QueueConflictError(
                        "SLURM result output acknowledgement conflicts"
                    )
        response = call({**binding, "result_operation": "commit"})
        if response.get("acknowledged") is not True:
            raise QueueConflictError(
                "SLURM result final acknowledgement is unavailable"
            )
        self.cleanup()
        return True

    def cleanup(self) -> None:
        """Retire transport bytes only after the finalizer acknowledgement."""
        with self._quota_lock():
            if self.path.is_symlink():
                raise QueueConflictError("SLURM result cleanup path contains a link")
            shutil.rmtree(self.path)
            _fsync_directory(self.root)
