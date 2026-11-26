"""Verification evidence owned by one immutable fleet check under its receipt lock."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from tempfile import gettempdir
from typing import Any, cast

from loom._artifact_fetch import fetch_artifacts
from loom.queue.deployment import (
    _protected_input_path,
    load_coordinator_connection_file,
)
from loom.queue.errors import QueueConfigError
from loom.serialization import thaw_plain_data

from ._host import atomic, digest
from ._timing import measure
from .probes import verify_storage


def _private_scratch(path: Path) -> None:
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise QueueConfigError("Fleet check scratch requires an owner-only directory")


def _principal(intent):
    certificate = load_coordinator_connection_file(
        intent["connection"]
    ).certificate_path
    return hashlib.sha256(certificate.read_bytes()).hexdigest()


def verify_publication(
    client, directory, check, intent, selected, deadline, *, collect=True, native_result_observed_at=None
) -> dict[str, Any]:
    """Return verified report facts, or a pending/failed transfer disposition.

    The caller selects the current output through the authenticated coordinator
    on every visit. This checks both consuming and originating run access.
    Staging belongs to the same local check owner as its exclusive receipt lock.
    """
    row = cast(dict[str, Any], thaw_plain_data(selected))
    artifact = row["artifact"]
    identity = intent["requests"][check]["preparation"]["operation_id"]
    principal = _principal(intent)
    binding = digest(
        [identity, intent["coordinator_id"], principal, row["locator"], artifact]
    )
    receipt = directory / (check + ".verified.json")
    scratch_id = digest([str(directory.resolve()), identity])
    scratch = Path(gettempdir()) / ("loom-fleet-check-" + scratch_id)
    if receipt.exists():
        previous = json.loads(
            _protected_input_path(
                receipt, label="verified check publication"
            ).read_text()
        )
        if previous["binding"] == binding:
            if scratch.exists():
                _private_scratch(scratch)
                shutil.rmtree(scratch)
            with measure("artifact_verification") as timing:
                timing["outcome"] = "reused"
            facts = previous["facts"]
            if "artifact_verified_at" not in facts:
                # Earlier releases retained the binding and proof in this same
                # atomic owner-only receipt, without an explicit time field.
                facts["artifact_verified_at"] = datetime.fromtimestamp(receipt.stat().st_mtime, timezone.utc).isoformat()
            return facts

    if not collect:
        return {"outcome": "waiting", "code": "publication_available"}
    _private_scratch(scratch)
    marker = scratch / "binding.json"
    if not marker.is_file() or marker.read_text() != binding:
        shutil.rmtree(scratch)
        _private_scratch(scratch)
        marker.write_text(binding)
    started = datetime.fromtimestamp(marker.stat().st_mtime, timezone.utc).isoformat()
    with measure("artifact_download"):
        batch = fetch_artifacts(
            client,
            [row],
            scratch,
            scope=None,
            expected_coordinator_id=intent["coordinator_id"],
            deadline=deadline,
            check_scratch=True,
        )
    fetched = batch["items"][0]
    if fetched["outcome"] != "available":
        if fetched["outcome"] == "integrity_failed":
            shutil.rmtree(scratch)
        return {
            "outcome": "failed"
            if fetched["outcome"] == "integrity_failed"
            else "waiting",
            "code": "publication_" + fetched["outcome"],
            "transfer": fetched.get("transfer", {}),
            "collection_started_at": started,
        }

    path = Path(fetched["primary_path"])
    facts = {
        "report": json.loads(path.read_text()),
        "verified_artifact": artifact,
        "declaration": fetched["declaration"],
        "verification": fetched["verification"],
    }
    if check == "storage":
        try:
            with measure("artifact_verification"):
                facts["storage"] = verify_storage(path.parent / "values.bin")
        except (OSError, ValueError):
            shutil.rmtree(scratch)
            return {"outcome": "failed", "code": "storage_result_mismatch"}
    if _principal(intent) != principal:
        return {"outcome": "waiting", "code": "check_credential_changed"}
    facts.update(collection_started_at=started, artifact_verified_at=datetime.now(timezone.utc).isoformat())
    if native_result_observed_at is not None:
        facts["native_result_observed_at"] = native_result_observed_at
    atomic(receipt, {"binding": binding, "facts": facts})
    shutil.rmtree(scratch)
    return facts
