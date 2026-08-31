"""Exact, private preparation record for the managed-local daemon.

``runtime.json`` is deliberately safe display metadata.  It cannot be used to
start managed work: this module owns the distinct, exact record written by the
trusted preparation path and read before daemon admission.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from loom.pipeline.planning import ExecutionPlan
from loom.pipeline.orchestration import ExecutionRequirement
from loom.pipeline.runtime import (
    ExecutionRoute,
    ExecutionRouteKind,
    RunOptions,
    StagePlacementPolicy,
    parallel_execution_options,
    resolve_stage_placement,
    resolve_run_runtime,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile
from loom.pipeline.specs import PipelineSpec, StageSpec
from loom.scheduling import (
    PreferenceScorer,
    PreferenceSpec,
    SchedulingComponentDescriptor,
)
from loom.serialization import (
    PlainData,
    ensure_plain_data,
    json_loads,
    stable_json_dumps,
)
from loom.pipeline.stores.local_runs import LocalRunStore, atomic_write_json

from .errors import QueueServiceError
from .local_daemon import (
    LocalDaemonSchedulingComponents,
    _default_scheduling_components,
)


_SCHEMA_VERSION = 2
_RECORD_NAME = "managed_local_runtime.json"


def prepare_managed_local_runtime_record(
    *,
    store: LocalRunStore,
    run_uri: str,
    plan: ExecutionPlan,
    pipeline: PipelineSpec,
    execution_requirements: Mapping[str, ExecutionRequirement],
    options: RunOptions | Mapping[str, object] | None = None,
    slurm_profiles: Sequence[SlurmReadyStageProfile] = (),
    scheduling_components: LocalDaemonSchedulingComponents | None = None,
) -> str:
    """Write the current exact managed-local execution intent once prepared.

    The record is deliberately not inferred by the daemon.  Preparation is the
    only writer, so a safe summary, an old record, or changed plan cannot become
    executable merely by being present in a run directory.
    """

    payload = _runtime_payload(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=pipeline,
        execution_requirements=execution_requirements,
        options=options,
        slurm_profiles=slurm_profiles,
        scheduling_components=scheduling_components,
    )
    payload["digest"] = _digest(payload)
    path = _record_path(store, run_uri)
    atomic_write_json(path, payload)
    path.chmod(0o600)
    return str(payload["digest"])


def _runtime_record_matches_current_intent(
    record: Mapping[str, PlainData],
    *,
    store: LocalRunStore,
    run_uri: str,
    plan: ExecutionPlan,
    pipeline: PipelineSpec,
    execution_requirements: Mapping[str, ExecutionRequirement],
    options: RunOptions | Mapping[str, object] | None = None,
    slurm_profiles: Sequence[SlurmReadyStageProfile] = (),
    scheduling_components: LocalDaemonSchedulingComponents | None = None,
) -> bool:
    """Return whether a verified record is the current executable intent.

    This is intentionally private: the runtime-record module remains the sole
    owner of both the durable payload and its digest, while preparation can
    safely compare a replay against the current trusted composition.
    """

    expected = _runtime_payload(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=pipeline,
        execution_requirements=execution_requirements,
        options=options,
        slurm_profiles=slurm_profiles,
        scheduling_components=scheduling_components,
    )
    expected["digest"] = _digest(expected)
    return dict(record) == expected


def _runtime_payload(
    *,
    store: LocalRunStore,
    run_uri: str,
    plan: ExecutionPlan,
    pipeline: PipelineSpec,
    execution_requirements: Mapping[str, ExecutionRequirement],
    options: RunOptions | Mapping[str, object] | None = None,
    slurm_profiles: Sequence[SlurmReadyStageProfile] = (),
    scheduling_components: LocalDaemonSchedulingComponents | None = None,
) -> dict[str, PlainData]:
    """Build the exact payload shared by preparation and replay comparison."""

    if plan.run_uri != run_uri or set(plan.stage_order) != set(pipeline.stage_names):
        raise QueueServiceError("managed-local runtime preparation identity conflicts")
    if set(execution_requirements) != set(plan.stage_order) or any(
        not isinstance(value, ExecutionRequirement)
        for value in execution_requirements.values()
    ):
        raise QueueServiceError(
            "managed-local execution requirements must exactly cover the plan"
        )
    normalized = (
        options
        if isinstance(options, RunOptions)
        else RunOptions.from_dict(options or {"run_uri": run_uri})
    )
    if normalized.run_uri not in {None, run_uri}:
        raise QueueServiceError("managed-local runtime options belong to another run")
    if normalized.executor not in {None, "local"}:
        raise QueueServiceError("managed-local runtime requires the local executor")
    runtime_options = normalized.to_dict()
    _reject_forbidden(runtime_options, path="runtime_options")
    composition = scheduling_components or _default_scheduling_components()
    if not isinstance(composition, LocalDaemonSchedulingComponents):
        raise QueueServiceError("managed-local scheduling composition is invalid")
    planners = {item.resource_kind: item for item in composition.planners}
    preference_scorers = {
        item.descriptor.kind: item for item in composition.preference_scorers
    }
    resolved_snapshot = store.read_config_snapshot(run_uri, "resolved")
    if resolved_snapshot is None:
        raise QueueServiceError(
            "managed-local preparation requires a resolved config snapshot"
        )
    runtime = resolve_run_runtime(normalized, stage_ids=pipeline.stage_names)
    profiles = _slurm_profile_registry(slurm_profiles)
    placements: dict[str, PlainData] = {}
    for stage in pipeline.stages:
        exact = runtime[stage.name]
        if exact.executor != "local":
            raise QueueServiceError(
                "managed-local stage runtime requires local executor"
            )
        resources = cast(ResourceRequest, exact.resources)
        unsupported = set(resources.entries) - set(planners)
        if unsupported:
            raise QueueServiceError(
                "managed-local runtime has no planner for: "
                + ", ".join(sorted(unsupported))
            )
        placements[stage.name] = resolve_stage_placement(
            authored=stage.resource_request,
            runtime=resources,
            policy=_stage_placement_policy(
                stage,
                resources,
                profiles,
                preference_scorers=preference_scorers,
            ),
            planners=planners,
        ).to_dict()
    return {
        "schema_version": _SCHEMA_VERSION,
        "run_uri": run_uri,
        "plan": plan.to_dict(),
        "plan_digest": _digest(plan.to_dict()),
        "pipeline_digest": hashlib.sha256(
            resolved_snapshot.encode("utf-8")
        ).hexdigest(),
        "runtime_options": runtime_options,
        "placements": placements,
        "execution_requirements": {
            name: execution_requirements[name].to_dict() for name in plan.stage_order
        },
        "max_parallel_stages": parallel_execution_options(
            normalized
        ).max_parallel_stages,
    }


def _stage_placement_policy(
    stage: StageSpec,
    resources: ResourceRequest,
    slurm_profiles: Mapping[str, SlurmReadyStageProfile],
    *,
    preference_scorers: Mapping[str, PreferenceScorer],
) -> StagePlacementPolicy:
    raw = dict(stage.placement)
    unknown = set(raw) - {"pool", "target", "preferences", "execution_route"}
    if unknown:
        raise QueueServiceError(
            "stage placement contains unsupported field(s): "
            + ", ".join(sorted(unknown))
        )
    pool = raw.get("pool", "default")
    target = raw.get("target")
    if not isinstance(pool, str) or not pool:
        raise QueueServiceError("stage placement pool must be non-empty")
    if target is not None and (not isinstance(target, str) or not target):
        raise QueueServiceError("stage placement target must be non-empty or null")
    return StagePlacementPolicy(
        pool_name=pool,
        target=cast(str | None, target),
        default_resources=ResourceRequest(
            entries={"cpu": ResourceEntry("cpu", 1, "count")}
        ),
        preferences=_resolved_preferences(
            stage,
            resources,
            raw.get("preferences"),
            preference_scorers=preference_scorers,
        ),
        route=_execution_route(raw.get("execution_route"), slurm_profiles),
    )


def _slurm_profile_registry(
    profiles: Sequence[SlurmReadyStageProfile],
) -> dict[str, SlurmReadyStageProfile]:
    result: dict[str, SlurmReadyStageProfile] = {}
    for profile in profiles:
        if not isinstance(profile, SlurmReadyStageProfile):
            raise QueueServiceError("protected SLURM profiles are invalid")
        if profile.profile_id in result:
            raise QueueServiceError("protected SLURM profile IDs must be unique")
        result[profile.profile_id] = profile
    return result


def _execution_route(
    value: object,
    profiles: Mapping[str, SlurmReadyStageProfile],
) -> ExecutionRoute:
    if value is None:
        return ExecutionRoute()
    if not isinstance(value, Mapping) or set(value) != {"kind", "profile"}:
        raise QueueServiceError("stage execution_route fields are invalid")
    if value.get("kind") != ExecutionRouteKind.SLURM.value:
        raise QueueServiceError("stage execution_route kind is unsupported")
    profile_id = value.get("profile")
    if not isinstance(profile_id, str) or not profile_id:
        raise QueueServiceError("stage SLURM profile must be a non-empty alias")
    profile = profiles.get(profile_id)
    if profile is None:
        raise QueueServiceError("stage names an unknown protected SLURM profile")
    return ExecutionRoute(
        kind=ExecutionRouteKind.SLURM,
        profile_id=profile.profile_id,
        profile_descriptor=profile.descriptor,
        profile_configuration_fingerprint=profile.configuration_fingerprint,
    )


def _resolved_preferences(
    stage: StageSpec,
    resources: ResourceRequest,
    value: object,
    *,
    preference_scorers: Mapping[str, PreferenceScorer],
) -> tuple[PreferenceSpec, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise QueueServiceError("stage placement preferences must be a sequence")
    if len(value) > 8:
        raise QueueServiceError("stage placement preferences exceed the bound")
    result: list[PreferenceSpec] = []
    seen: set[str] = set()
    requested_kinds = set(stage.resource_request.entries) | set(resources.entries)
    scorer_kinds = {
        "agent_order": "preferred_agent",
        "gpu_model_order": "gpu_model",
        "resource_attribute_order": "resource_attribute",
        "packing": "packing",
    }
    tiers = {
        "agent_order": 0,
        "gpu_model_order": 0,
        "resource_attribute_order": 1,
        "packing": 2,
    }
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise QueueServiceError("stage placement preference is invalid")
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in scorer_kinds or kind in seen:
            raise QueueServiceError("stage placement preference kind is invalid")
        seen.add(kind)
        scorer = preference_scorers.get(scorer_kinds[kind])
        descriptor = getattr(scorer, "descriptor", None)
        if scorer is None or not isinstance(descriptor, SchedulingComponentDescriptor):
            raise QueueServiceError(
                "stage placement preference scorer is not configured"
            )
        fallback_after = item.get("fallback_after_seconds")
        if fallback_after is not None and (
            isinstance(fallback_after, bool)
            or not isinstance(fallback_after, int)
            or not 0 <= fallback_after <= 86_400
        ):
            raise QueueServiceError(
                "stage placement fallback duration is outside the site bound"
            )
        data: dict[str, PlainData]
        utility_min = 0
        utility_max = 0
        if kind == "packing":
            _exact_preference_fields(item, {"kind", "fallback_after_seconds"})
            data = {}
            utility_min = -(2**63) + 1
        elif kind == "agent_order":
            _exact_preference_fields(item, {"kind", "agents", "fallback_after_seconds"})
            agents = _ordered_strings(item.get("agents"), "agents")
            data = {"agents": list(agents)}
            utility_max = len(agents)
        elif kind == "gpu_model_order":
            _exact_preference_fields(item, {"kind", "models", "fallback_after_seconds"})
            if "gpu" not in requested_kinds:
                raise QueueServiceError(
                    "GPU model preference requires a GPU stage request"
                )
            models = _ordered_strings(item.get("models"), "models")
            data = {"models": list(models)}
            utility_max = len(models)
        else:
            _exact_preference_fields(
                item,
                {
                    "kind",
                    "resource",
                    "attribute",
                    "values",
                    "fallback_after_seconds",
                },
            )
            resource = item.get("resource")
            attribute = item.get("attribute")
            if (
                not isinstance(resource, str)
                or resource not in requested_kinds
                or not isinstance(attribute, str)
                or not attribute
            ):
                raise QueueServiceError(
                    "resource attribute preference requires a requested resource"
                )
            values = _ordered_strings(item.get("values"), "values")
            data = {
                "resource": resource,
                "attribute": attribute,
                "values": list(values),
            }
            utility_max = len(values)
        result.append(
            PreferenceSpec(
                identifier=f"{stage.name}:preference:{index}:{kind}",
                scorer=descriptor.kind,
                tier=tiers[kind],
                weight=1,
                fallback_after_seconds=cast(int | None, fallback_after),
                data=data,
                utility_min=utility_min,
                utility_max=utility_max,
                quality_bands=("preferred", "fallback"),
                fallback_band=("fallback" if fallback_after is not None else None),
                descriptor=descriptor,
            )
        )
    return tuple(result)


def _exact_preference_fields(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected - {"fallback_after_seconds"} and set(value) != expected:
        raise QueueServiceError("stage placement preference fields are invalid")


def _ordered_strings(value: object, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or len(value) > 32
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise QueueServiceError(
            f"stage placement preference {field} must be bounded unique strings"
        )
    return tuple(cast(Sequence[str], value))


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
        "schema_version",
        "run_uri",
        "plan",
        "plan_digest",
        "runtime_options",
        "pipeline_digest",
        "placements",
        "execution_requirements",
        "max_parallel_stages",
        "digest",
    }:
        raise QueueServiceError("managed-local runtime record is unsupported")
    try:
        payload = ensure_plain_data(dict(data), path="managed_local_runtime")
    except Exception as exc:
        raise QueueServiceError("managed-local runtime record is invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _SCHEMA_VERSION
    ):
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
    requirements = payload.get("execution_requirements")
    if not isinstance(requirements, Mapping) or set(requirements) != set(
        ExecutionPlan.from_dict(cast(object, payload["plan"])).stage_order
    ):
        raise QueueServiceError(
            "managed-local runtime record execution requirements are invalid"
        )
    try:
        for value in requirements.values():
            ExecutionRequirement.from_dict(value)
    except Exception as exc:
        raise QueueServiceError(
            "managed-local runtime record execution requirements are invalid"
        ) from exc
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
            if (
                "provider" in lowered
                or "authority" in lowered
                or any(
                    part in lowered
                    for part in ("token", "credential", "secret", "password")
                )
            ):
                raise QueueServiceError(
                    "managed-local runtime record forbids provider or authority credentials"
                )
            _reject_forbidden(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_forbidden(item, path=path)


__all__ = ["prepare_managed_local_runtime_record"]
