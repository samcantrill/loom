"""Retire an exact fleet-owned unpacked environment after its consumers release it."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import shutil

from loom.fleet._host import owner, read
from loom.fleet.releases import verify_release
from loom.queue.errors import QueueConflictError
from ._slurm_upgrade import _strings


def recovery_consumers(operation):
    """An unfinished administrative operation can replay its bound release."""
    releases = {row["source_release"]["descriptor_sha256"] for row in operation.intent["hosts"].values()}
    consumers = []
    for path in operation.directory.parent.glob("*/intent.json"):
        if path.parent == operation.directory:
            continue
        result = path.parent / "result.json"
        if result.exists() and read(result).get("state") in {"complete", "aborted"}:
            continue
        if releases.intersection(_strings(read(path))):
            consumers.append(path.parent.name)
    return sorted(consumers)


def _process_consumers(environment):
    # Capture native executables, venv interpreter argv, loaded libraries and
    # process-local reference paths. Inaccessible same-user owners are unknown.
    prefix = os.fsencode(environment)
    consumers = []
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            contents = [os.fsencode(os.readlink(process / name)) for name in ("cwd", "exe")]
            contents.extend((process / name).read_bytes() for name in ("cmdline", "environ", "maps"))
            for fd in (process / "fd").iterdir():
                try:
                    contents.append(os.fsencode(os.readlink(fd)))
                except FileNotFoundError:
                    continue
            if any(prefix in item for item in contents):
                consumers.append(process.name)
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            consumers.append(process.name + ":unknown")
    return consumers


def retire(request):
    from ._upgrade_host import _settlement

    admin = Path(request["admin"])
    source = request["source_release"]
    digest = source["descriptor_sha256"]
    if digest == request["release"]["descriptor_sha256"]:
        return {"outcome": "unchanged"}
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise QueueConflictError("invalid predecessor release identity")
    release = admin / "releases" / digest
    environment = release / "environment"
    if release.resolve() != release or environment.is_symlink():
        raise QueueConflictError("predecessor installation is not a fleet-owned directory")
    proof = _settlement(request, include_pending_poll=False)
    observed = owner(request)
    if (read(admin / "active.json") != request["release"] or observed["owner"] != request["expected_root_id"]
            or observed["value"]["ownership"] != "live"):
        raise QueueConflictError("replacement service ownership changed")
    reasons = []
    if proof["availability"] != "available" or not proof["value"].get("settled"):
        reasons.append("native_or_scheduler_evidence_pending")
    slurm = proof["value"].get("slurm") or {}
    if slurm.get("other_jobs") or request.get("unattributed_jobs"):
        reasons.append("unattributed_scheduler_jobs")
    profile_paths = []
    for path in set(request["role_paths"]) | set(_strings(slurm.get("profiles", ()))):
        candidate = Path(path)
        if candidate.is_absolute() and (
            candidate.is_relative_to(environment) or candidate.resolve().is_relative_to(environment)
        ):
            profile_paths.append(path)
    if profile_paths:
        reasons.append("installed_profile_reference")
    if request.get("deferred_agents"):
        reasons.append("qualification_deferred")
    if request["recovery_consumers"]:
        reasons.append("retained_recovery_operations")
    with (admin / "installation.lock").open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = release / "installed.json"
        if marker.exists() and read(marker) != source:
            raise QueueConflictError("superseded installation identity changed")
        if environment.exists() and not marker.exists():
            raise QueueConflictError("superseded installation has no ownership marker")
        bundle = release / "bundle" / request["source_descriptor_name"]
        if verify_release(bundle) != source:
            raise QueueConflictError("predecessor restore bundle changed")
        processes = _process_consumers(environment)
        if processes:
            reasons.append("process_reference_or_unavailable")
        facts = {"environment": str(environment), "restore_descriptor": str(bundle),
                 "processes": processes, "recovery_operations": request["recovery_consumers"],
                 "profile_paths": sorted(profile_paths), "deferred_agents": request.get("deferred_agents", []), "slurm": slurm}
        if reasons:
            return {**facts, "outcome": "retained", "reasons": reasons,
                    "removal_condition": "repeat consumer inspection after every listed owner releases this environment"}
        if environment.is_dir():
            shutil.rmtree(environment)
        marker.unlink(missing_ok=True)
        return {**facts, "outcome": "retired"}
