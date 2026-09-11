"""Trusted preparation for managed runs and the embedded-local facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import fcntl
from pathlib import Path
import re
from typing import Any, cast

from loom.pipeline import PipelineSpec
from loom.pipeline.orchestration import ExecutionRequirement
from loom.pipeline.planning import ExecutionPlan, plan_pipeline
from loom.pipeline.status import RunStatus
from loom.pipeline.runtime import (
    RunOptions,
    RunStoreOptions,
    StageRuntimeOptions,
    build_runtime_metadata,
    merge_config_run_options,
)
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.pipeline.stores.coordinator_authority import (
    embedded_coordinator_authority,
    AuthenticatedCoordinatorAuthorityError,
    coordinator_authority_identity,
    publish_prepared_run,
)
from loom.serialization import PlainData, json_dumps_pretty
from loom.pipeline.stores.authority import AuthorityStoreError
from loom.pipeline.stores.authority_protocol import AuthorityProtocolErrorCategory

from .deployment import CoordinatorServiceConfig, load_coordinator_service_config
from .errors import QueueConflictError, QueueServiceError
from .local_daemon_runtime import (
    _runtime_record_matches_current_intent,
    load_managed_local_runtime_record,
    prepare_managed_local_runtime_record,
)


_SAFE_RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


@dataclass(frozen=True, slots=True)
class ManagedLocalPreparationReceipt:
    """Immutable identity returned by embedded managed-local preparation."""

    run_uri: str
    plan_digest: str
    runtime_digest: str
    stage_names: tuple[str, ...]

    def to_dict(self) -> dict[str, PlainData]:
        """Serialize the complete native identity without changing its fields."""
        return {
            "run_uri": self.run_uri,
            "plan_digest": self.plan_digest,
            "runtime_digest": self.runtime_digest,
            "stage_names": list(self.stage_names),
        }


def prepare_managed_local_run(
    coordinator_config: str | Path,
    pipeline_config: str | Path,
    run_name: str,
    *,
    env_file: str | Path | None = None,
) -> ManagedLocalPreparationReceipt:
    """Prepare one embedded-local run without starting or submitting work.

    A matching complete run is an immutable replay.  Any other existing path is
    deliberately left untouched so an operator can inspect or remove it. Pass
    the coordinator's explicit protected ``env_file`` when its role YAML uses
    environment interpolation.
    """

    service = load_coordinator_service_config(coordinator_config, env_file=env_file)
    _validate_embedded_service(service)
    composed = _compose_pipeline_config(pipeline_config)
    resolved = _resolved_mapping(composed)
    pipeline = _pipeline_from_resolved(resolved)
    requirements = _execution_requirements(service, pipeline)
    return prepare_managed_run(
        service,
        composed,
        run_name,
        execution_requirements=requirements,
    )


def prepare_managed_run(
    service: CoordinatorServiceConfig,
    composed: object,
    run_name: str,
    *,
    execution_requirements: Mapping[str, ExecutionRequirement],
) -> ManagedLocalPreparationReceipt:
    """Prepare one managed run from trusted resolved inputs.

    ``service`` is a resolved coordinator-role snapshot and ``composed`` is one
    already-composed pipeline configuration. The caller supplies the exact
    requirement for each stage, so coordinator-only preparation neither needs a
    local installation nor discovers a live agent offer. This function never
    reads or recomposes either supplied input.

    Same-URI calls serialize across local processes through completion or failure.
    A matching complete run is an immutable replay. Any other existing path is
    deliberately left untouched so an operator can inspect or remove it.
    """

    _validate_preparation_service(service)
    run_name_text = _validate_run_name(run_name)
    resolved = _resolved_mapping(composed)
    pipeline = _pipeline_from_resolved(resolved)
    requirements = _validated_execution_requirements(pipeline, execution_requirements)
    profiles = {
        profile.profile_id: profile for profile in service.daemon.slurm_profiles
    }
    for stage in pipeline.stages:
        route = stage.placement.get("execution_route")
        if isinstance(route, Mapping) and route.get("kind") == "slurm":
            profile = profiles.get(cast(str, route.get("profile")))
            requirement = requirements[stage.name]
            if profile is None or (
                profile.project_fingerprint != requirement.project_fingerprint
                or profile.environment_fingerprint
                != requirement.environment_fingerprint
                or profile.executor_fingerprint != requirement.executor_fingerprint
            ):
                raise QueueServiceError(
                    "prepared SLURM profile installation does not satisfy checked requirements"
                )
    run_uri, options = _runtime_for_service(
        service,
        resolved,
        pipeline,
        run_name_text,
        effective_options=getattr(composed, "effective_run_options", None),
    )
    store = LocalRunStore(service.daemon.run_store_root)

    # Keep the lock outside the target: creating the lock must not manufacture a
    # partial run. Retain its inode so queued callers always share the same lock.
    lock_path = (
        store.local_run_dir(run_uri).parent / ".loom" / "preparation-locks"
        / f"{run_name_text}.lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if store.run_uri_exists(run_uri):
            return _replay_receipt(
                store=store,
                run_uri=run_uri,
                composed=composed,
                pipeline=pipeline,
                options=options,
                requirements=requirements,
                service=service,
            )

        store.create_run(run_uri)
        try:
            _persist_composed_config(store, run_uri, composed)
            store.write_run_user_metadata(
                run_uri,
                {
                    **store.read_run_user_metadata(run_uri),
                    "coordinator_authority": coordinator_authority_identity(
                        service.daemon.coordinator_authority_factory
                    ),
                },
            )
            plan = plan_pipeline(
                pipeline,
                run_uri=run_uri,
                run_store=store,
                artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
                selectors=options.to_plan_selectors(),
                resume=options.to_resume_options(),
                persist=True,
            )
            store.write_runtime_metadata(
                run_uri,
                build_runtime_metadata(options, stage_ids=pipeline.stage_names).to_dict(),
            )
            runtime_digest = prepare_managed_local_runtime_record(
                store=store,
                run_uri=run_uri,
                plan=plan,
                pipeline=pipeline,
                execution_requirements=requirements,
                options=options,
                scheduling_components=service.daemon.scheduling_components,
                slurm_profiles=service.daemon.slurm_profiles,
            )
            _publish_authority(service, run_uri, runtime_digest)
        except Exception:
            # A partial directory is intentionally a durable conflict, not a repair
            # opportunity for a subsequent preparation call.
            raise
        return _receipt(run_uri, plan, runtime_digest)


def _publish_authority(
    service: CoordinatorServiceConfig, run_uri: str, digest: str
) -> None:
    try:
        publish_prepared_run(
            service.daemon.coordinator_authority_factory, run_uri, digest
        )
    except AuthenticatedCoordinatorAuthorityError as exc:
        if exc.category in {
            AuthorityProtocolErrorCategory.CONFLICT,
            AuthorityProtocolErrorCategory.VALIDATION,
        }:
            raise QueueConflictError(
                "preparation selected authority publication conflicts"
            ) from exc
        raise
    except AuthorityStoreError as exc:
        raise QueueConflictError(
            "preparation embedded authority publication conflicts"
        ) from exc


def _compose_pipeline_config(path: str | Path) -> object:
    from weave import compose_config

    return compose_config(path)


def _validate_embedded_service(service: CoordinatorServiceConfig) -> None:
    daemon = service.daemon
    if service.agent_server is not None:
        raise QueueServiceError(
            "managed-local preparation does not support an agent listener"
        )
    if daemon.remote_profiles:
        raise QueueServiceError(
            "managed-local preparation does not support remote profiles"
        )
    if daemon.agent_policy.agents or daemon.agent_policy.principals:
        raise QueueServiceError(
            "managed-local preparation does not support remote agents or principals"
        )
    if daemon.slurm_profiles:
        raise QueueServiceError(
            "managed-local preparation does not support SLURM profiles"
        )
    if daemon.coordinator_authority_factory is not embedded_coordinator_authority:
        raise QueueServiceError("managed-local preparation requires embedded authority")


def _validate_preparation_service(service: CoordinatorServiceConfig) -> None:
    """Require one supported selected authority without opening another owner."""
    try:
        coordinator_authority_identity(service.daemon.coordinator_authority_factory)
    except Exception as exc:
        raise QueueServiceError("managed preparation authority is unsupported") from exc


def _validate_run_name(value: str) -> str:
    if (
        not isinstance(value, str)
        or value in {".", ".."}
        or not _SAFE_RUN_NAME.fullmatch(value)
    ):
        raise QueueServiceError("managed-local run name must be one safe path segment")
    return value


def _resolved_mapping(composed: object) -> Mapping[str, object]:
    value = getattr(composed, "resolved", None)
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise QueueServiceError(
            "managed-local pipeline config did not compose to a mapping"
        )
    return cast(Mapping[str, object], value)


def _pipeline_from_resolved(resolved: Mapping[str, object]) -> PipelineSpec:
    pipeline_config = resolved.get("pipeline")
    if not isinstance(pipeline_config, Mapping):
        raise QueueServiceError(
            "managed-local pipeline config requires a pipeline mapping"
        )
    return PipelineSpec.from_config(pipeline_config)


def _runtime_for_service(
    service: CoordinatorServiceConfig,
    resolved: Mapping[str, object],
    pipeline: PipelineSpec,
    run_name: str,
    *,
    effective_options: RunOptions | None = None,
) -> tuple[str, RunOptions]:
    protected_root = service.daemon.run_store_root.resolve()
    run_uri = path_to_run_uri(protected_root / run_name)
    authored = effective_options or merge_config_run_options(
        resolved, known_stage_ids=pipeline.stage_names
    )
    if authored.run_uri not in {None, run_uri}:
        raise QueueServiceError("managed-local runtime options belong to another run")
    if authored.executor not in {None, "local"}:
        raise QueueServiceError("managed-local runtime requires the local executor")
    if authored.adapter_options or any(
        option.adapter_options
        for option in cast(
            Mapping[str, StageRuntimeOptions], authored.stage_options
        ).values()
    ):
        raise QueueServiceError(
            "managed preparation executor adapter inputs are obsolete"
        )
    run_store = cast(RunStoreOptions | None, authored.run_store)
    if (
        run_store is not None
        and run_store.root is not None
        and Path(run_store.root).resolve() != protected_root
    ):
        raise QueueServiceError("managed-local runtime run-store root conflicts")
    options = RunOptions.from_dict(
        {**authored.to_dict(), "run_uri": run_uri, "executor": "local"}
    )
    return run_uri, options


def _execution_requirements(
    service: CoordinatorServiceConfig, pipeline: PipelineSpec
) -> dict[str, ExecutionRequirement]:
    profile = service.daemon.resident_worker_launch_profile
    if profile is None:
        raise QueueServiceError(
            "managed-local preparation requires an embedded local agent"
        )
    descriptor = profile.descriptor
    try:
        requirement = ExecutionRequirement(
            cast(str, descriptor["project_fingerprint"]),
            cast(str, descriptor["environment_fingerprint"]),
            cast(str, descriptor["executor_fingerprint"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise QueueServiceError("embedded resident descriptor is invalid") from exc
    return {name: requirement for name in pipeline.stage_names}


def _validated_execution_requirements(
    pipeline: PipelineSpec,
    requirements: Mapping[str, ExecutionRequirement],
) -> dict[str, ExecutionRequirement]:
    """Snapshot explicit stage requirements before creating durable state."""

    if set(requirements) != set(pipeline.stage_names) or any(
        not isinstance(value, ExecutionRequirement) for value in requirements.values()
    ):
        raise QueueServiceError(
            "managed preparation execution requirements must exactly cover the pipeline"
        )
    return {name: requirements[name] for name in pipeline.stage_names}


def _persist_composed_config(
    store: LocalRunStore, run_uri: str, composed: object
) -> None:
    resolved = _resolved_mapping(composed)
    redacted = getattr(composed, "redacted", None)
    manifest = getattr(composed, "manifest", None)
    provenance = getattr(composed, "provenance", None)
    recipe_manifest = _recipe_manifest_data(composed)
    if (
        not isinstance(redacted, Mapping)
        or not hasattr(manifest, "to_dict")
        or not hasattr(provenance, "to_dict")
    ):
        raise QueueServiceError("managed-local composed config evidence is unavailable")
    store.write_config_snapshot(run_uri, "resolved", json_dumps_pretty(resolved))
    store.write_config_snapshot(
        run_uri, "resolved_redacted", json_dumps_pretty(redacted)
    )
    store.write_composition_manifest(
        run_uri, _plain_mapping(cast(Any, manifest).to_dict())
    )
    store.write_recipe_manifest(run_uri, recipe_manifest)
    store.write_run_user_metadata(
        run_uri, {"config_provenance": _plain_mapping(cast(Any, provenance).to_dict())}
    )


def _replay_receipt(
    *,
    store: LocalRunStore,
    run_uri: str,
    composed: object,
    pipeline: PipelineSpec,
    options: RunOptions,
    requirements: Mapping[str, ExecutionRequirement],
    service: CoordinatorServiceConfig,
) -> ManagedLocalPreparationReceipt:
    try:
        _replay_matches(
            store, run_uri, composed, pipeline, options, requirements, service
        )
        if service.daemon.coordinator_authority_factory is embedded_coordinator_authority:
            # Local publication failures leave an inspectable conflict. Only the
            # authenticated owner reconciles uncertain remote publication.
            authority = embedded_coordinator_authority(run_uri)
            if authority.open_run(run_uri).status is RunStatus.CREATED:
                raise QueueServiceError("local authority publication is incomplete")
        record = load_managed_local_runtime_record(store, run_uri)
        plan = ExecutionPlan.from_dict(store.read_plan(run_uri))
        runtime_digest = record["digest"]
        if not isinstance(runtime_digest, str):
            raise QueueServiceError("managed-local runtime record digest is invalid")
    except Exception as exc:
        if isinstance(exc, QueueConflictError):
            raise
        raise QueueConflictError(
            "managed-local preparation conflicts with existing partial, corrupt, or changed state"
        ) from exc

    if service.daemon.coordinator_authority_factory is not embedded_coordinator_authority:
        _publish_authority(service, run_uri, runtime_digest)
    return _receipt(run_uri, plan, runtime_digest)


def _replay_matches(
    store: LocalRunStore,
    run_uri: str,
    composed: object,
    pipeline: PipelineSpec,
    options: RunOptions,
    requirements: Mapping[str, ExecutionRequirement],
    service: CoordinatorServiceConfig,
) -> None:
    store.open_run(run_uri)
    resolved = _resolved_mapping(composed)
    redacted = getattr(composed, "redacted", None)
    manifest = getattr(composed, "manifest", None)
    provenance = getattr(composed, "provenance", None)
    recipe_manifest = _recipe_manifest_data(composed)
    if (
        not isinstance(redacted, Mapping)
        or not hasattr(manifest, "to_dict")
        or not hasattr(provenance, "to_dict")
    ):
        raise QueueServiceError("managed-local composed config evidence is unavailable")
    if store.read_config_snapshot(run_uri, "resolved") != json_dumps_pretty(resolved):
        raise QueueServiceError("managed-local resolved config conflicts")
    if store.read_config_snapshot(run_uri, "resolved_redacted") != json_dumps_pretty(
        redacted
    ):
        raise QueueServiceError("managed-local redacted config conflicts")
    if store.read_composition_manifest(run_uri) != _plain_mapping(
        cast(Any, manifest).to_dict()
    ):
        raise QueueServiceError("managed-local composition manifest conflicts")
    if store.read_recipe_manifest(run_uri) != recipe_manifest:
        raise QueueServiceError("managed-local recipe manifest conflicts")
    if store.read_run_user_metadata(run_uri) != {
        "config_provenance": _plain_mapping(cast(Any, provenance).to_dict()),
        "coordinator_authority": coordinator_authority_identity(
            service.daemon.coordinator_authority_factory
        ),
    }:
        raise QueueServiceError("managed-local config provenance conflicts")
    # Publication owns this plan. Later accepted results may alter reuse facts,
    # but replay must retain the exact original prepared target.
    plan = ExecutionPlan.from_dict(store.read_plan(run_uri))
    if (
        store.read_runtime_metadata(run_uri)
        != build_runtime_metadata(options, stage_ids=pipeline.stage_names).to_dict()
    ):
        raise QueueServiceError("managed-local runtime metadata conflicts")
    record = load_managed_local_runtime_record(store, run_uri)
    if not _runtime_record_matches_current_intent(
        record,
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=pipeline,
        execution_requirements=requirements,
        options=options,
        slurm_profiles=service.daemon.slurm_profiles,
        scheduling_components=service.daemon.scheduling_components,
    ):
        raise QueueServiceError("managed-local exact runtime intent conflicts")


def _receipt(
    run_uri: str, plan: ExecutionPlan, runtime_digest: str
) -> ManagedLocalPreparationReceipt:
    plan_digest = plan.to_dict().get("digest")
    if not isinstance(plan_digest, str):
        # Execution plans intentionally do not own a digest; the managed-local
        # record is the canonical durable digest owner.
        import hashlib
        from loom.serialization import stable_json_dumps

        plan_digest = hashlib.sha256(
            stable_json_dumps(plan.to_dict()).encode("utf-8")
        ).hexdigest()
    return ManagedLocalPreparationReceipt(
        run_uri=run_uri,
        plan_digest=plan_digest,
        runtime_digest=runtime_digest,
        stage_names=plan.stage_order,
    )


def _recipe_manifest_data(composed: object) -> tuple[dict[str, PlainData], ...]:
    """Normalize current mapping and established object recipe evidence once."""
    items = getattr(composed, "recipe_manifest", None)
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise QueueServiceError("managed-local recipe evidence is unavailable")
    result: list[dict[str, PlainData]] = []
    for item in items:
        if not isinstance(item, Mapping):
            serializer = getattr(item, "to_dict", None)
            if not callable(serializer):
                raise QueueServiceError("managed-local recipe evidence is unavailable")
            item = serializer()
        result.append(_plain_mapping(item))
    return tuple(result)


def _plain_mapping(value: object) -> dict[str, PlainData]:
    if not isinstance(value, Mapping):
        raise QueueServiceError("managed-local composed evidence must be a mapping")
    return cast(dict[str, PlainData], dict(value))


__all__ = [
    "ManagedLocalPreparationReceipt",
    "prepare_managed_local_run",
    "prepare_managed_run",
]
