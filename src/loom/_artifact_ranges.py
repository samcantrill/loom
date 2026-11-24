"""Bounded authenticated range reads and private restartable check scratch."""

from __future__ import annotations

import base64
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
import hashlib
import os
from pathlib import Path
from typing import Any

from loom.queue._coordinator_control import CoordinatorClientError

CHUNK_BYTES = 256 * 1024
RANGE_WINDOW = 4


class TransferFailure(Exception):
    def __init__(self, outcome: str):
        self.outcome = outcome
        super().__init__(outcome)


def _read(client, locator, options, declaration, member, offset, length, check_time):
    chunk: dict[str, Any] = {}
    for attempt in range(2):
        check_time()
        try:
            chunk = client.read_artifact_chunk(
                locator,
                declaration=declaration,
                member=member,
                offset=offset,
                length=length,
                **options,
            )
            break
        except CoordinatorClientError as exc:
            if attempt or exc.code not in {"unavailable", "timeout", "transport_error"}:
                raise
    if chunk["outcome"] != "available":
        raise TransferFailure(chunk["outcome"])
    data = base64.b64decode(chunk["data"], validate=True)
    if (
        len(data) != length
        or chunk["member"] != member
        or chunk["offset"] != offset
        or chunk["declaration"] != declaration
        or chunk["locator"] != locator.to_dict()
    ):
        raise TransferFailure("integrity_failed")
    return data


def _cached(path: Path, length: int) -> bytes | None:
    try:
        with path.open("rb") as stream:
            expected = stream.read(32)
            data = stream.read(length + 1)
    except FileNotFoundError:
        return None
    if len(data) == length and hashlib.sha256(data).digest() == expected:
        return data
    path.unlink(missing_ok=True)
    return None


def _save(path: Path, data: bytes) -> None:
    # The check lock excludes other writers. After a crash a missing or torn
    # scratch range can be fetched again under the original declaration.
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        stream.write(hashlib.sha256(data).digest())
        stream.write(data)
    os.replace(temporary, path)


def copy_member(
    client,
    locator,
    options,
    declaration: str,
    member: dict[str, Any],
    path: Path,
    cache: Path | None,
    workers: ThreadPoolExecutor,
    check_time,
    progress,
) -> None:
    """Only network reads run in workers. The check owner writes each exact offset."""
    name, size = member["path"], member["size_bytes"]
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
    offsets = iter(range(0, size, CHUNK_BYTES))
    inflight = {}
    try:
        with path.open("xb") as sink:

            def store(offset, data, from_cache=False):
                sink.seek(offset)
                sink.write(data)
                if cache is not None:
                    if not from_cache:
                        _save(cache / str(offset), data)
                    progress["reused_bytes" if from_cache else "received_bytes"] += len(
                        data
                    )

            while True:
                while len(inflight) < RANGE_WINDOW:
                    check_time()
                    offset = next(offsets, None)
                    if offset is None:
                        break
                    length = min(CHUNK_BYTES, size - offset)
                    data = (
                        _cached(cache / str(offset), length)
                        if cache is not None
                        else None
                    )
                    if data is not None:
                        store(offset, data, from_cache=True)
                    elif size <= CHUNK_BYTES:
                        store(
                            offset,
                            _read(
                                client,
                                locator,
                                options,
                                declaration,
                                name,
                                offset,
                                length,
                                check_time,
                            ),
                        )
                    else:
                        future = workers.submit(
                            copy_context().run,
                            _read,
                            client,
                            locator,
                            options,
                            declaration,
                            name,
                            offset,
                            length,
                            check_time,
                        )
                        inflight[future] = offset
                if not inflight:
                    break
                ready, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for future in ready:
                    store(inflight.pop(future), future.result())
    finally:
        for future in inflight:
            future.cancel()
