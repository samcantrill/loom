"""Trusted preparation for managed runs and the embedded-local facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
import fcntl
import hashlib
from tempfile import TemporaryDirectory
from pathlib import Path
import re
from typing import Any, cast

from loom.pipeline import PipelineSpec
from loom.pipeline.orchestration import (
    ExecutionRequirement, ManagedExecutionRequirement, SubmittedContainerRequirement,
)
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
    is_embedded_coordinator_authority,
    AuthenticatedCoordinatorAuthorityError,
    coordinator_authority_identity,
    publish_prepared_run,
)
from loom.serialization import PlainData
from loom.serialization.configuration import configuration_json
from loom.pipeline.stores.authority import AuthorityStoreError
from loom.pipeline.stores.authority_protocol import AuthorityProtocolErrorCategory

from .deployment import CoordinatorServiceConfig, load_coordinator_service_config
from .errors import QueueConflictError, QueueServiceError
from .local_daemon_runtime import (
    _runtime_record_matches_current_intent,
    load_managed_local_runtime_record,
    _runtime_payload,
    _runtime_placements,
    _write_runtime_record_payload,
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


class _PrivateConfigStore(LocalRunStore):
    """Render documents with their final logical URI and private physical paths."""

    def __init__(self, root: Path, target_uri: str) -> None:
        super().__init__(root)
        self.target_uri = target_uri

    def local_run_dir(self, run_uri: str) -> Path:
        if run_uri != self.target_uri:
            raise QueueServiceError(
                "private preparation store received a different run URI"
            )
        return self.root / "run"


_CONFIG_DOCUMENTS = (
    "config/resolved.yaml", "config/resolved.redacted.yaml",
    "config/composition_manifest.json", "config/recipe_manifest.json",
)


@dataclass(frozen=True, slots=True)
class _RenderedConfig:
    directory: TemporaryDirectory[str]
    run_uri: str
    digests: dict[str, str]

    def install(
        self, store: LocalRunStore, run_uri: str, digests: dict[str, str]
    ) -> None:
        from loom.pipeline.stores.atomic import atomic_write_bytes
        import json

        with ExitStack() as snapshots:
            sources = {}
            for name, digest in digests.items():
                stream = snapshots.enter_context(
                    (Path(self.directory.name) / "run" / name).open("rb")
                )
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise _StagingUnavailable("private publication bytes changed")
                stream.seek(0)
                sources[name] = stream

            # Keep verified files open across creation: deletion of disposable
            # staging can never leave a new target with missing inputs.
            store.create_run(run_uri)
            metadata = json.load(sources.pop("run.json"))["metadata"]
            for name, source in sources.items():
                target = store.local_generated_artifact_path(run_uri, name)
                atomic_write_bytes(target, source.read())
                if name == "config/managed_local_runtime.json":
                    target.chmod(0o600)
            store._write_projected_run_metadata(run_uri, metadata)


class _StagingUnavailable(OSError):
    """Transient private evidence loss. The committed report owns retry."""


def _verify_private_config(
    private: _PrivateConfigStore, digests: dict[str, str]
) -> None:
    for name, digest in digests.items():
        try:
            with (private.local_run_dir(private.target_uri) / name).open(
                "rb"
            ) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise _StagingUnavailable("private publication bytes changed")
        except FileNotFoundError as exc:
            raise _StagingUnavailable(
                "private publication bytes are unavailable"
            ) from exc


def _compare_rendered_config(private: _PrivateConfigStore, run_uri: str) -> None:
    # Read the native logical documents, including retained inline provenance
    # and older timestamps. A byte comparison would reject valid replays.
    live = LocalRunStore()
    for key in ("resolved", "resolved_redacted"):
        if live.read_config_snapshot(run_uri, key) != private.read_config_snapshot(
            run_uri, key
        ):
            raise QueueServiceError("managed-local configuration conflicts")
    if (
        live.read_composition_manifest(run_uri)
        != private.read_composition_manifest(run_uri)
        or live.read_recipe_manifest(run_uri) != private.read_recipe_manifest(run_uri)
        or live.read_run_user_metadata(run_uri)
        != private.read_run_user_metadata(run_uri)
    ):
        raise QueueServiceError("managed-local composition evidence conflicts")


def _render_config(
    private_root: Path,
    run_uri: str,
    composed: object,
    authority_identity: dict[str, PlainData],
) -> dict[str, str]:
    store = _PrivateConfigStore(private_root, run_uri)
    store.create_run(run_uri)
    _persist_composed_config(
        store, run_uri, composed, authority_identity=authority_identity
    )
    digests = {}
    for name in (*_CONFIG_DOCUMENTS, "run.json"):
        with (store.local_run_dir(run_uri) / name).open("rb") as stream:
            digests[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return digests


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
    execution_requirements: Mapping[str, ManagedExecutionRequirement],
    _defer_locked: bool = False,
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
    from .preparation import _project_target_uri

    project = getattr(composed, "project_preparation", None)
    if project is not None and project["target_run_uri"] != _project_target_uri(
        service.daemon.run_store_root, run_name_text
    ):
        raise QueueConflictError("project preparation target binding conflicts")
    pipeline = _pipeline_from_resolved(resolved)
    from .preparation import (
        LOCAL_PREPARATION_SCOPE,
        _local_scope,
        _require_local_binding,
    )

    for stage in pipeline.stages:
        scope = _local_scope(stage.fingerprint_fields.get(LOCAL_PREPARATION_SCOPE))
        _require_local_binding(
            scope,
            service.daemon.resident_worker_launch_profile,
            agent_id=service.daemon.machine_id,
        )
        if scope is not None and stage.placement.get("target") != scope["agent_id"]:
            raise QueueConflictError("local preparation hard placement conflicts")
    requirements = _validated_execution_requirements(pipeline, execution_requirements)
    profiles = {
        profile.profile_id: profile for profile in service.daemon.slurm_profiles
    }
    for stage in pipeline.stages:
        route = stage.placement.get("execution_route")
        if isinstance(route, Mapping) and route.get("kind") == "slurm":
            profile = profiles.get(cast(str, route.get("profile")))
            requirement = requirements[stage.name]
            if isinstance(requirement, SubmittedContainerRequirement):
                from ._submitted_container_policy import SubmittedContainerPolicy

                if (profile is None or profile.submitted_container_policy is None
                    or not SubmittedContainerPolicy.from_dict(profile.submitted_container_policy).capability.satisfies(requirement)):
                    raise QueueServiceError("prepared SLURM container policy does not satisfy checked requirements")
                continue
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
        pipeline.stage_names,
        run_name_text,
        effective_options=getattr(composed, "effective_run_options", None),
    )
    store = LocalRunStore(service.daemon.run_store_root)

    # Keep the lock outside the target: creating the lock must not manufacture a
    # partial run. Retain its inode so queued callers always share the same lock.
    lock_path = (
        store.local_run_dir(run_uri).parent
        / ".loom"
        / "preparation-locks"
        / f"{run_name_text}.lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        if _defer_locked:
            from .errors import _PreparationTargetBusy

            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise _PreparationTargetBusy(run_uri) from exc
        else:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing = store.run_uri_exists(run_uri)
        rendered = getattr(composed, "rendered_config", None)
        entry = getattr(composed, "project_contracts_entry", None)
        placements = _runtime_placements(
            pipeline,
            options,
            service.daemon.slurm_profiles,
            service.daemon.scheduling_components,
        )
        if isinstance(rendered, _RenderedConfig):
            from concurrent.futures import ProcessPoolExecutor
            from multiprocessing import get_context

            if rendered.run_uri != run_uri:
                raise QueueConflictError("rendered configuration target conflicts")
            with ProcessPoolExecutor(
                max_workers=1, mp_context=get_context("spawn")
            ) as worker:
                receipt, digests = worker.submit(
                    _render_runtime,
                    Path(rendered.directory.name),
                    run_uri,
                    existing,
                    rendered.digests,
                    dict(resolved),
                    options.to_dict(),
                    {k: v.to_dict() for k, v in requirements.items()},
                    placements,
                    entry,
                ).result()
            if not existing:
                rendered.install(store, run_uri, digests)
        elif existing:
            try:
                _check_composed_config(
                    store,
                    run_uri,
                    composed,
                    coordinator_authority_identity(
                        service.daemon.coordinator_authority_factory
                    ),
                )
                receipt = _replay_runtime(
                    store, run_uri, pipeline, options, requirements, placements
                )
            except Exception as exc:
                raise QueueConflictError(
                    "managed-local preparation conflicts with existing partial, corrupt, or changed state"
                ) from exc
        else:
            store.create_run(run_uri)
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
            receipt = _prepare_runtime(
                store, run_uri, pipeline, options, requirements, placements, entry
            )

        if existing and is_embedded_coordinator_authority(
            service.daemon.coordinator_authority_factory
        ):
            _check_embedded_replay(service, run_uri)
        else:
            _publish_authority(service, run_uri, receipt.runtime_digest)
        return receipt


def _prepare_runtime(
    store: LocalRunStore,
    run_uri: str,
    pipeline: PipelineSpec,
    options: RunOptions,
    requirements: Mapping[str, ManagedExecutionRequirement],
    placements: dict[str, PlainData],
    entry: Mapping[str, PlainData] | None,
) -> ManagedLocalPreparationReceipt:
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        stage_state=store,
        artifact_index=store,
        plans=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        selectors=options.to_plan_selectors(),
        resume=options.to_resume_options(),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        build_runtime_metadata(options, stage_ids=pipeline.stage_names).to_dict(),
    )
    if entry is not None:
        from loom.pipeline.execution.prepared_run import PreparedRunRecord
        from loom.timestamps import utc_timestamp

        store.write_prepared_run(
            run_uri,
            PreparedRunRecord(
                schema_version=1,
                run_uri=run_uri,
                prepared_at=utc_timestamp(),
                executor_name="managed",
                continuation_type="whole_run",
                metadata={"loom.project_contracts": dict(entry)},
            ).to_dict(),
        )
    payload = _runtime_payload(
        store=store,
        run_uri=run_uri,
        plan=plan,
        pipeline=pipeline,
        execution_requirements=requirements,
        options=options,
        placements=placements,
    )
    return _receipt(run_uri, plan, _write_runtime_record_payload(store, run_uri, payload))


def _render_runtime(
    private_root: Path,
    run_uri: str,
    existing: bool,
    config_digests: dict[str, str],
    resolved: dict[str, object],
    options_data: dict[str, PlainData],
    requirement_data: dict[str, dict[str, PlainData]],
    placements: dict[str, PlainData],
    entry: Mapping[str, PlainData] | None,
) -> tuple[ManagedLocalPreparationReceipt, dict[str, str]]:
    pipeline = _pipeline_from_resolved(resolved)
    options = RunOptions.from_dict(options_data)
    requirements = {
        k: ExecutionRequirement.from_dict(v) for k, v in requirement_data.items()
    }
    private = _PrivateConfigStore(private_root, run_uri)
    if existing:
        _verify_private_config(private, config_digests)
        # An exact replay can follow later stage execution. Reuse its retained
        # plan and compare native logical evidence with the checked composition.
        try:
            _compare_rendered_config(private, run_uri)
            return _replay_runtime(
                LocalRunStore(), run_uri, pipeline, options, requirements, placements
            ), {}
        except Exception as exc:
            _verify_private_config(private, config_digests)
            raise QueueConflictError(
                "managed-local preparation conflicts with existing partial, corrupt, or changed state"
            ) from exc
    try:
        receipt = _prepare_runtime(
            private, run_uri, pipeline, options, requirements, placements, entry
        )
    except Exception:
        _verify_private_config(private, config_digests)
        raise
    digests = dict(config_digests)
    files = ("plan.json", "runtime.json", "config/managed_local_runtime.json")
    for name in (*files, *(("prepared_run.json",) if entry is not None else ())):
        with (private.local_run_dir(run_uri) / name).open("rb") as stream:
            digests[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return receipt, digests


def _publish_authority(
    service: CoordinatorServiceConfig, run_uri: str, digest: str
) -> None:
    try:
        publish_prepared_run(
            service.daemon.coordinator_authority_factory,
            run_uri,
            digest,
            observers=service.event_observers,
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
    if not is_embedded_coordinator_authority(daemon.coordinator_authority_factory):
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
    stage_names: Sequence[str],
    run_name: str,
    *,
    effective_options: RunOptions | None = None,
) -> tuple[str, RunOptions]:
    protected_root = service.daemon.run_store_root.resolve()
    run_uri = path_to_run_uri(protected_root / run_name)
    authored = effective_options or merge_config_run_options(
        resolved, known_stage_ids=tuple(stage_names)
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
    requirements: Mapping[str, ManagedExecutionRequirement],
) -> dict[str, ManagedExecutionRequirement]:
    """Snapshot explicit stage requirements before creating durable state."""

    if set(requirements) != set(pipeline.stage_names) or any(
        not isinstance(value, (ExecutionRequirement, SubmittedContainerRequirement)) for value in requirements.values()
    ):
        raise QueueServiceError(
            "managed preparation execution requirements must exactly cover the pipeline"
        )
    return {name: requirements[name] for name in pipeline.stage_names}


def _persist_composed_config(
    store: LocalRunStore,
    run_uri: str,
    composed: object,
    *,
    authority_identity: dict[str, PlainData] | None = None,
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
    store.write_config_snapshot(run_uri, "resolved", configuration_json(resolved))
    store.write_config_snapshot(
        run_uri, "resolved_redacted", configuration_json(redacted)
    )
    store.write_composition_manifest(
        run_uri, _plain_mapping(cast(Any, manifest).to_dict())
    )
    store.write_recipe_manifest(run_uri, recipe_manifest)
    store.write_run_user_metadata(
        run_uri,
        {
            "config_provenance": _plain_mapping(cast(Any, provenance).to_dict()),
            **(
                {"coordinator_authority": authority_identity}
                if authority_identity is not None
                else {}
            ),
        },
    )


def _check_embedded_replay(service: CoordinatorServiceConfig, run_uri: str) -> None:
    factory = service.daemon.coordinator_authority_factory
    assert factory is not None
    try:
        if factory(run_uri).open_run(run_uri).status is RunStatus.CREATED:
            raise QueueServiceError("local authority publication is incomplete")
    except Exception as exc:
        raise QueueConflictError(
            "managed-local preparation conflicts with existing partial, corrupt, or changed state"
        ) from exc


def _replay_runtime(
    store: LocalRunStore,
    run_uri: str,
    pipeline: PipelineSpec,
    options: RunOptions,
    requirements: Mapping[str, ManagedExecutionRequirement],
    placements: dict[str, PlainData],
) -> ManagedLocalPreparationReceipt:
    store.open_run(run_uri)
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
        placements=placements,
    ):
        raise QueueServiceError("managed-local exact runtime intent conflicts")
    return _receipt(run_uri, plan, cast(str, record["digest"]))


def _check_composed_config(
    store: LocalRunStore,
    run_uri: str,
    composed: object,
    authority_identity: dict[str, PlainData],
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
    if store.read_config_snapshot(run_uri, "resolved") != configuration_json(resolved):
        raise QueueServiceError("managed-local resolved config conflicts")
    if store.read_config_snapshot(run_uri, "resolved_redacted") != configuration_json(
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
        "coordinator_authority": authority_identity,
    }:
        raise QueueServiceError("managed-local config provenance conflicts")


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
