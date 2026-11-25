"""Read-only Slurm evidence for the selected fleet role, also sent to older installations."""
from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any, cast

from loom._bounded_process import run_bounded_process
from loom._sqlite_inspection import inspect_sqlite_database
from loom.pipeline.executors.slurm.commands import ready_stage_client_environment
from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile
from loom.queue.deployment import _load_protected_config, _slurm_profile_composition
from loom.queue.operations import inspect_native_service


def _strings(value):
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _targets(value):
    if isinstance(value, Mapping):
        if "_target_" in value:
            yield value["_target_"]
        for item in value.values():
            yield from _targets(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _targets(item)


def _profile_paths(raw, profile):
    paths = {path for path in _strings(raw) if Path(path).is_absolute()}
    if len(profile.bootstrap_argv) == 4:
        # The fixed worker retains its own project/runtime and workspace.
        bootstrap = json.loads(Path(profile.bootstrap_argv[3]).read_bytes())
        paths.update(path for path in _strings(bootstrap) if Path(path).is_absolute())
    executables = [profile.bootstrap_argv[0]]
    if profile.containment_helper is not None:
        executables.extend(profile.containment_helper.argv[:1])
    for executable in executables:
        path = Path(executable)
        if path.is_absolute():
            paths.add(str(path.resolve()))
            if path.is_file():
                with path.open("rb") as stream:
                    prefix = stream.readline(4096)
                if prefix.startswith(b"#!"):
                    interpreter = os.fsdecode(prefix[2:].strip().split()[0])
                    if Path(interpreter).is_absolute():
                        paths.add(interpreter)
    return sorted(paths)


def _live(profile):
    # Scope by the effective scheduler user and cluster. Unmatched jobs may
    # still invoke an installation via their batch scripts.
    argv = ["squeue", "--noheader", "--user=" + str(os.getuid()), "--format=%i|%T|%k"]
    if profile.cluster:
        argv.append("--clusters=" + profile.cluster)
    result = run_bounded_process(argv, environment=ready_stage_client_environment(profile.runner),
                                 timeout=10, output_limit=2**20, text=True)
    if result.returncode:
        raise ValueError("scheduler query failed")
    jobs = []
    for line in result.stdout.splitlines():
        job_id, state, marker = line.strip().split("|", 2)
        if not job_id or not state:
            raise ValueError("incomplete scheduler identity")
        jobs.append({"job_id": job_id, "cluster": profile.cluster, "state": state,
                     "operation_id": marker.removeprefix("loom-op-v1:") if marker.startswith("loom-op-v1:") else None})
    return jobs


def _assignments(root, coordinator, jobs):
    operations = json.dumps([job["operation_id"] for job in jobs if job["operation_id"]])
    handles = json.dumps([job["job_id"] for job in jobs])
    with inspect_sqlite_database(root / ("execution.sqlite" if coordinator else "slurm.sqlite")) as conn:
        if coordinator:
            rows = conn.execute(
                "SELECT identity_json, state, job_id, cluster FROM slurm_stage_assignments "
                "WHERE state != 'released' OR operation_id IN (SELECT value FROM json_each(?)) "
                "OR job_id IN (SELECT value FROM json_each(?))", (operations, handles))
        else:
            rows = conn.execute(
                "SELECT a.assignment_json, CASE WHEN a.released=1 AND a.acknowledged=1 THEN 'released' "
                "ELSE 'unresolved' END, json_extract(s.value_json,'$.job_id'), json_extract(s.value_json,'$.cluster') "
                "FROM agent_slurm_operations a LEFT JOIN ready_stage_submissions s USING(operation_id) "
                "WHERE a.released!=1 OR a.acknowledged!=1 OR a.operation_id IN (SELECT value FROM json_each(?)) "
                "OR json_extract(s.value_json,'$.job_id') IN (SELECT value FROM json_each(?))", (operations, handles))
        result = []
        for raw, state, job, cluster in rows:
            identity = json.loads(raw)
            result.append({key: identity[key] for key in (
                "operation_id", "assignment_id", "agent_id", "agent_root_id", "profile_id",
                "profile_configuration_fingerprint", "run_uri", "stage_name",
            )} | {"state": state, "job_id": job, "cluster": cluster})
        owner_table = "slurm_stage_assignments" if coordinator else "agent_slurm_operations"
        if conn.execute(f"SELECT 1 FROM ready_stage_submissions s LEFT JOIN {owner_table} a USING(operation_id) "
                        "WHERE a.operation_id IS NULL LIMIT 1").fetchone():
            raise ValueError("submission has no assignment owner")
        return result


# These native constructors decode protected declarations without external
# effects. A custom factory cannot establish a read-only preview.
_NATIVE_TARGETS = {
    "loom.pipeline.executors.slurm." + module + name
    for module, name in (
        ("", "SubprocessSlurmCommandRunner"), ("commands.", "SubprocessSlurmCommandRunner"),
        ("", "SlurmContainmentHelper"), ("ready_stage.", "SlurmContainmentHelper"),
        ("", "SlurmJobPrivateFileProvider"), ("ready_stage.", "SlurmJobPrivateFileProvider"),
        ("", "SlurmUserPrivateFileProvider"), ("trusted_user.", "SlurmUserPrivateFileProvider"),
    )
}


def observe(request):
    coordinator = request["name"] == "coordinator"
    root = Path(request["root"]) / "coordinator" if coordinator else Path(request["root"])
    owner = inspect_native_service(root, expected_root_id=request.get("expected_root_id"))
    result = {"status": "unavailable", "profiles": [], "assignments": [], "jobs": [], "other_jobs": []}
    if owner.availability != "available":
        return {**result, "reason": "role_unavailable"}
    try:
        declaration = _load_protected_config(request["config"], env_file=request.get("env_file"))[2]
        raw_profiles = cast(list[dict[str, Any]], declaration["slurm_profiles"])
        if set(_targets(raw_profiles)) - _NATIVE_TARGETS:
            return {**result, "reason": "opaque_profile_factory"}
        profiles = cast(tuple[SlurmReadyStageProfile, ...], _slurm_profile_composition(raw_profiles))
        observations = {}
        for raw, profile in zip(raw_profiles, profiles, strict=True):
            paths = _profile_paths(raw, profile)
            result["profiles"].append({"profile_id": profile.profile_id, "fingerprint": profile.configuration_fingerprint,
                                       "cluster": profile.cluster, "paths": paths})
            selection = (profile.cluster, tuple(sorted((ready_stage_client_environment(profile.runner) or {}).items())))
            if selection not in observations:
                try:
                    observations[selection] = _live(profile)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    observations[selection] = None
        jobs = {(job["cluster"], job["job_id"]): job for observed in observations.values()
                if observed is not None for job in observed}
        assignments = _assignments(root, coordinator, jobs.values())
        result["assignments"] = assignments
        unresolved = False
        for item in assignments:
            match = next((p for p in result["profiles"] if p["profile_id"] == item["profile_id"]
                          and p["fingerprint"] == item["profile_configuration_fingerprint"]), None)
            item["paths"] = None if match is None else match["paths"]
            unresolved |= item["state"] != "released"
        for job in jobs.values():
            matches = [item for item in assignments if job["operation_id"] == item["operation_id"] or (
                item["job_id"] == job["job_id"] and item["cluster"] == job["cluster"])]
            if matches:
                result["jobs"].append({**job, "assignment_ids": [item["assignment_id"] for item in matches],
                                       "paths": sorted({path for item in matches for path in item["paths"] or []})
                                       if all(item["paths"] is not None for item in matches) else None})
            else:
                result["other_jobs"].append(job)
        if None in observations.values():
            return {**result, "reason": "scheduler_unavailable"}
        result["status"] = "active" if result["jobs"] else "unresolved" if unresolved else "settled"
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error, RuntimeError):
        return {**result, "status": "unavailable", "reason": "profile_or_journal_unavailable"}
    return result


if __name__ == "__main__":
    print(json.dumps(observe(json.load(sys.stdin))))
