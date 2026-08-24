"""Exact, private preparation record for the managed-local daemon.

``runtime.json`` is deliberately safe display metadata.  It cannot be used to
start managed work: this module owns the distinct, exact record written by the
trusted preparation path and read before daemon admission.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from loom.pipeline.planning import ExecutionPlan
from loom.pipeline.runtime import (
    CpuResourcePlanner,
    MemoryResourcePlanner,
    RunOptions,
    StagePlacementPolicy,
    parallel_execution_options,
    resolve_stage_placement,
    resolve_run_runtime,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.specs import PipelineSpec
from loom.serialization import PlainData, ensure_plain_data, json_loads, stable_json_dumps
from loom.pipeline.stores.local_runs import LocalRunStore, atomic_write_json

from .errors import QueueServiceError


_SCHEMA_VERSION = 1
_RECORD_NAME = "managed_local_runtime.json"


def prepare_managed_local_runtime_record(
    *,
    store: LocalRunStore,
    run_uri: str,
    plan: ExecutionPlan,
    pipeline: PipelineSpec,
    options: RunOptions | Mapping[str, object] | None = None,
    machine_id: str = "machine-A",
) -> str:
    """Write the current exact managed-local execution intent once prepared.

    The record is deliberately not inferred by the daemon.  Preparation is the
    only writer, so a safe summary, an old record, or changed plan cannot become
    executable merely by being present in a run directory.
    """

    if plan.run_uri != run_uri or set(plan.stage_order) != set(pipeline.stage_names):
        raise QueueServiceError("managed-local runtime preparation identity conflicts")
    normalized = options if isinstance(options, RunOptions) else RunOptions.from_dict(
        options or {"run_uri": run_uri}
    )
    if normalized.run_uri not in {None, run_uri}:
        raise QueueServiceError("managed-local runtime options belong to another run")
    if normalized.executor not in {None, "local"}:
        raise QueueServiceError("managed-local runtime requires the local executor")
    runtime_options = normalized.to_dict()
    _reject_forbidden(runtime_options, path="runtime_options")
    planners = {
        "cpu": CpuResourcePlanner(),
        "memory": MemoryResourcePlanner(),
    }
    resolved_snapshot = store.read_config_snapshot(run_uri, "resolved")
    if resolved_snapshot is None:
        raise QueueServiceError("managed-local preparation requires a resolved config snapshot")
    runtime = resolve_run_runtime(normalized, stage_ids=pipeline.stage_names)
    placements: dict[str, PlainData] = {}
    for stage in pipeline.stages:
        exact = runtime[stage.name]
        if exact.executor != "local":
            raise QueueServiceError("managed-local stage runtime requires local executor")
        resources = cast(ResourceRequest, exact.resources)
        unsupported = set(resources.entries) - set(planners)
        if unsupported:
            raise QueueServiceError(
                "managed-local runtime has no planner for: " + ", ".join(sorted(unsupported))
            )
        placements[stage.name] = resolve_stage_placement(
            authored=stage.resource_request,
            runtime=resources,
            policy=StagePlacementPolicy(
                pool_name="default",
                target=machine_id,
                default_resources=ResourceRequest(
                    entries={"cpu": ResourceEntry("cpu", 1, "count")}
                ),
            ),
            planners=planners,
        ).to_dict()
    payload: dict[str, PlainData] = {
        "schema_version": _SCHEMA_VERSION,
        "run_uri": run_uri,
        "plan": plan.to_dict(),
        "plan_digest": _digest(plan.to_dict()),
        "pipeline_digest": hashlib.sha256(resolved_snapshot.encode("utf-8")).hexdigest(),
        "runtime_options": runtime_options,
        "placements": placements,
        "max_parallel_stages": parallel_execution_options(normalized).max_parallel_stages,
    }
    payload["digest"] = _digest(payload)
    path = _record_path(store, run_uri)
    atomic_write_json(path, payload)
    path.chmod(0o600)
    return str(payload["digest"])


def load_managed_local_runtime_record(
    store: LocalRunStore, run_uri: str
) -> dict[str, PlainData]:
    """Load one exact current record, rejecting missing and summary-only state."""

    path = _record_path(store, run_uri)
    if not path.is_file():
        raise QueueServiceError(
            "managed-local admission requires a fresh exact runtime record"
        )
    try:
        data = json_loads(path.read_text(encoding="utf-8"), path=str(path))
    except Exception as exc:
        raise QueueServiceError("managed-local runtime record is corrupt") from exc
    if not isinstance(data, Mapping) or set(data) != {
        "schema_version", "run_uri", "plan", "plan_digest", "runtime_options",
        "pipeline_digest", "placements", "max_parallel_stages", "digest",
    }:
        raise QueueServiceError("managed-local runtime record is unsupported")
    try:
        payload = ensure_plain_data(dict(data), path="managed_local_runtime")
    except Exception as exc:
        raise QueueServiceError("managed-local runtime record is invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
        raise QueueServiceError("managed-local runtime record schema is unsupported")
    if payload.get("run_uri") != run_uri:
        raise QueueServiceError("managed-local runtime record belongs to another run")
    digest = payload.pop("digest", None)
    if not isinstance(digest, str) or digest != _digest(payload):
        raise QueueServiceError("managed-local runtime record digest conflicts")
    plan = payload.get("plan")
    if not isinstance(plan, Mapping) or payload.get("plan_digest") != _digest(plan):
        raise QueueServiceError("managed-local runtime record plan identity conflicts")
    runtime_options = payload.get("runtime_options")
    if not isinstance(runtime_options, Mapping):
        raise QueueServiceError("managed-local runtime record lacks exact options")
    _reject_forbidden(runtime_options, path="runtime_options")
    max_parallel_stages = payload.get("max_parallel_stages")
    if (
        isinstance(max_parallel_stages, bool)
        or not isinstance(max_parallel_stages, int)
        or max_parallel_stages < 1
    ):
        raise QueueServiceError("managed-local runtime record concurrency is invalid")
    payload["digest"] = digest
    return payload


def _record_path(store: LocalRunStore, run_uri: str) -> Path:
    store.open_run(run_uri)
    return store.local_run_dir(run_uri) / "config" / _RECORD_NAME


def _digest(payload: Mapping[str, PlainData]) -> str:
    return hashlib.sha256(stable_json_dumps(payload).encode("utf-8")).hexdigest()


def _reject_forbidden(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise QueueServiceError(f"{path} has an invalid field")
            lowered = key.lower()
            if "provider" in lowered or "authority" in lowered or any(
                part in lowered for part in ("token", "credential", "secret", "password")
            ):
                raise QueueServiceError(
                    "managed-local runtime record forbids provider or authority credentials"
                )
            _reject_forbidden(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_forbidden(item, path=path)


__all__ = ["prepare_managed_local_runtime_record"]
