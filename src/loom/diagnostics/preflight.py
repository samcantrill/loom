"""Local preflight check runner."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loom.state_sources import (
    authoritative_service_source,
    deferred_finalization_source,
    local_materialization_source,
    offline_evidence_source,
    redacted_authority_summary,
    unavailable_authority_source,
)
from loom.serialization import PlainData, ensure_plain_data

from .models import (
    ArtifactBackendPreflightTarget,
    CleanupPreflightTarget,
    STABLE_CHECK_IDS,
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightRequest,
    PreflightResult,
    PreflightSeverity,
    normalize_groups,
)

if TYPE_CHECKING:
    from loom.pipeline.executors.slurm import SlurmOptions
    from loom.plugins.entrypoints import EntryPointProvider, PluginRecord


_SLURM_EXECUTORS = frozenset({"slurm-single-job", "slurm-afterok"})
_APPTAINER_EXECUTORS = frozenset({"apptainer", "singularity"})
_CONTAINER_BUILD_RUNTIMES = frozenset({"docker", "apptainer"})
_plugin_entry_point_provider: "EntryPointProvider | None" = None


@dataclass(frozen=True)
class _ContainerBuildPreflightOptions:
    owner_id: str
    adapter_options: Mapping[str, object]


@dataclass(frozen=True)
class _ContainerBuildPreflightTarget:
    owner_id: str
    name: str
    target: object


@dataclass(frozen=True)
class _DockerPreflightRawTarget:
    stage_id: str | None
    adapter_options: Mapping[str, object]
    resources: object | None


@dataclass(frozen=True)
class _DockerPreflightTarget:
    stage_id: str | None
    container: object
    docker_options: object
    resources: object | None


@dataclass(frozen=True)
class _ApptainerPreflightRawTarget:
    stage_id: str | None
    adapter_options: Mapping[str, object]
    resources: object | None
    executor_name: str
    selected_executor: str


@dataclass(frozen=True)
class _ApptainerPreflightTarget:
    stage_id: str | None
    container: object
    apptainer_options: object
    resources: object | None
    executor_name: str
    selected_executor: str


@dataclass
class _Context:
    request: PreflightRequest
    _config: object | None = None
    _config_error: BaseException | None = None
    _pipeline: object | None = None
    _pipeline_error: BaseException | None = None
    _runtime_options: object | None = None
    _runtime_options_error: BaseException | None = None
    _capability_validation: object | None = None
    _capability_validation_error: BaseException | None = None
    _run_uri: object | None = None
    _run_uri_error: BaseException | None = None

    def authority_config(self) -> object | None:
        return self.request.authority_config

    def authority_mode(self) -> object | None:
        return self.request.authority_mode

    def config(self) -> object:
        if self._config is not None:
            return self._config
        if self._config_error is not None:
            raise self._config_error
        try:
            from weave.api import compose_config

            self._config = compose_config(
                _resolve_path(self.request.config_path, cwd=self.request.cwd),
                overlays=tuple(
                    _resolve_path(path, cwd=self.request.cwd)
                    for path in self.request.overlays
                ),
                overrides=self.request.overrides,
            )
        except Exception as exc:  # noqa: BLE001
            self._config_error = exc
            raise
        return self._config

    def pipeline(self) -> object:
        if self._pipeline is not None:
            return self._pipeline
        if self._pipeline_error is not None:
            raise self._pipeline_error
        try:
            from loom.pipeline import validate_pipeline_config

            composed = self.config()
            resolved = cast(Any, composed).resolved
            self._pipeline = (
                validate_pipeline_config(
                    resolved,
                    registry=cast(Any, self.request.resource_validator_registry),
                )
                if self.request.resource_validator_registry is not None
                else validate_pipeline_config(resolved)
            )
        except Exception as exc:  # noqa: BLE001
            self._pipeline_error = exc
            raise
        return self._pipeline

    def runtime_options(self) -> object:
        if self._runtime_options is not None:
            return self._runtime_options
        if self._runtime_options_error is not None:
            raise self._runtime_options_error
        try:
            from loom.pipeline.runtime import merge_config_run_options

            composed = self.config()
            self._runtime_options = merge_config_run_options(
                cast(Any, composed).resolved,
                explicit=cast(Any, _request_runtime_source(self.request)),
                registry=cast(Any, self.request.resource_validator_registry),
            )
        except Exception as exc:  # noqa: BLE001
            self._runtime_options_error = exc
            raise
        return self._runtime_options

    def capability_validation(self) -> object:
        if self._capability_validation is not None:
            return self._capability_validation
        if self._capability_validation_error is not None:
            raise self._capability_validation_error
        try:
            from loom.pipeline.runtime import validate_executor_capabilities

            self._capability_validation = validate_executor_capabilities(
                cast(Any, self.runtime_options()),
                registry=cast(Any, self.request.executor_descriptor_registry),
                resource_validator_registry=cast(
                    Any,
                    self.request.resource_validator_registry,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._capability_validation_error = exc
            raise
        return self._capability_validation

    def run_uri(self) -> object:
        if self._run_uri is not None:
            return self._run_uri
        if self._run_uri_error is not None:
            raise self._run_uri_error
        try:
            from loom.pipeline.stores import resolve_local_run_uri

            self._run_uri = resolve_local_run_uri(
                _selected_run_uri(self), cwd=self.request.cwd
            )
        except Exception as exc:  # noqa: BLE001
            self._run_uri_error = exc
            raise
        return self._run_uri


def run_preflight(request: PreflightRequest) -> PreflightResult:
    """Run the selected local preflight checks without writing store documents."""

    if not isinstance(request, PreflightRequest):
        raise TypeError("request must be a PreflightRequest")
    selected_groups = normalize_groups(request.groups)
    context = _Context(request=request)
    checks: list[PreflightCheckResult] = []
    for group in selected_groups:
        checks.extend(_CHECKS[group](context))
    return PreflightResult(checks=tuple(checks), groups=selected_groups)


def _check_config(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        config = context.config()
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "config.load", PreflightGroup.CONFIG, "config composition failed", exc
            ),
        )

    source_count = len(cast(Any, config).source_artifacts)
    return (
        _result(
            "config.load",
            PreflightGroup.CONFIG,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "config composed successfully",
            {
                "config_path": str(
                    _resolve_path(context.request.config_path, cwd=context.request.cwd)
                ),
                "source_artifact_count": source_count,
            },
        ),
    )


def _check_pipeline(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        validation = context.pipeline()
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "pipeline.graph",
                PreflightGroup.PIPELINE,
                "pipeline graph validation failed",
                exc,
            ),
        )

    return (
        _result(
            "pipeline.graph",
            PreflightGroup.PIPELINE,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "pipeline graph is valid",
            {
                "pipeline_name": cast(Any, validation).pipeline_name,
                "stage_count": cast(Any, validation).stage_count,
            },
        ),
    )


def _check_selectors(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        validation = cast(Any, context.pipeline())
        selectors = _coerce_selectors(cast(Any, context.runtime_options()).selectors)
        from loom.pipeline.planning.selectors import normalize_selectors

        selection = normalize_selectors(
            cast(Any, selectors),
            spec=validation.spec,
            graph=validation.graph,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "selectors.validate",
                PreflightGroup.SELECTORS,
                "selector validation failed",
                exc,
            ),
        )

    return (
        _result(
            "selectors.validate",
            PreflightGroup.SELECTORS,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "selectors are valid",
            {
                "eligible_stage_count": len(selection.eligible_stages),
                "skipped_stage_count": len(selection.skipped_stages),
            },
        ),
    )


def _check_runtime(context: _Context) -> tuple[PreflightCheckResult, ...]:
    return (
        *_check_runtime_options(context),
        *_check_runtime_profile(context),
        *_check_runtime_container_build_options(context),
        *_check_runtime_slurm_options(context),
        *_check_runtime_stage_options(context),
    )


def _check_runtime_options(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "runtime.options",
                PreflightGroup.RUNTIME,
                "runtime options could not be normalized",
                exc,
            ),
        )

    return (
        _result(
            "runtime.options",
            PreflightGroup.RUNTIME,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "runtime options are normalized",
            cast(Mapping[str, PlainData], options.to_safe_metadata()),
        ),
    )


def _check_runtime_profile(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "runtime.profile",
                PreflightGroup.RUNTIME,
                "runtime profile selection failed",
                exc,
            ),
        )

    profile = options.profile
    return (
        _result(
            "runtime.profile",
            PreflightGroup.RUNTIME,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "runtime profile selection is valid",
            {"profile": profile, "selected": profile is not None},
        ),
    )


def _check_runtime_container_build_options(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    try:
        sources = _container_build_option_sources(context)
    except Exception:  # noqa: BLE001 - runtime.options reports normalization failures.
        return ()
    if not sources:
        return ()

    targets: list[PlainData] = []
    diagnostics: list[PlainData] = []
    for source in sources:
        try:
            parsed = _container_build_options_from_adapter(source.adapter_options)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _container_build_diagnostic(
                    source.owner_id,
                    code="container_build_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        for name, target in cast(
            Mapping[str, object], cast(Any, parsed).targets
        ).items():
            targets.append(
                {
                    "owner_id": source.owner_id,
                    "name": name,
                    "target": cast(Any, target).to_redacted_metadata(),
                }
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return (
        _result(
            "runtime.container_build.options",
            PreflightGroup.RUNTIME,
            status,
            _severity_for_status(status),
            (
                "container build adapter options are valid"
                if status is PreflightCheckStatus.PASS
                else "container build adapter options are invalid"
            ),
            {
                "namespace_count": len(sources),
                "target_count": len(targets),
                "targets": targets,
                "diagnostics": diagnostics,
            },
        ),
    )


def _check_runtime_slurm_options(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - runtime.options reports normalization failures.
        return ()

    if not _is_slurm_executor(options):
        return ()

    try:
        run_options = _slurm_options_from_adapter(
            options.adapter_options,
            path="RunOptions.adapter_options['slurm']",
        )
        stage_options = {
            stage_id: _slurm_options_from_adapter(
                stage_runtime.adapter_options,
                path=f"RunOptions.stage_options[{stage_id!r}].adapter_options['slurm']",
            )
            for stage_id, stage_runtime in cast(
                Mapping[str, Any], options.stage_options
            ).items()
            if "slurm" in stage_runtime.adapter_options
        }
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "runtime.slurm.options",
                PreflightGroup.RUNTIME,
                "SLURM adapter options are invalid",
                exc,
            ),
        )

    return (
        _result(
            "runtime.slurm.options",
            PreflightGroup.RUNTIME,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM adapter options are valid",
            cast(
                Mapping[str, PlainData],
                {
                    "executor": options.executor,
                    "run_option_keys": _slurm_option_keys(run_options),
                    "stage_option_count": len(stage_options),
                    "stage_options": sorted(stage_options),
                },
            ),
        ),
    )


def _check_runtime_stage_options(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        options = context.runtime_options()
        validation = cast(Any, context.pipeline())
        from loom.pipeline.runtime import validate_stage_runtime_options

        validate_stage_runtime_options(
            cast(Any, options),
            known_stage_ids=validation.spec.stage_names,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "runtime.stage_options",
                PreflightGroup.RUNTIME,
                "runtime stage options are invalid",
                exc,
            ),
        )

    stage_ids = tuple(cast(Any, options).stage_options)
    return (
        _result(
            "runtime.stage_options",
            PreflightGroup.RUNTIME,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "runtime stage options target known exact stages",
            {"stage_option_count": len(stage_ids), "stage_options": list(stage_ids)},
        ),
    )


def _check_run_uri(context: _Context) -> tuple[PreflightCheckResult, ...]:
    return (
        *_check_run_uri_resolve(context),
        *_check_slurm_run_uri_local(context),
        *_check_slurm_active_submission(context),
    )


def _check_run_uri_resolve(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.resolve", PreflightGroup.RUN, "run URI resolution failed", exc
            ),
        )
    if run_uri is None:
        return (_missing_run_uri("run_uri.resolve", PreflightGroup.RUN),)
    try:
        resolved = cast(Any, context.run_uri())
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.resolve", PreflightGroup.RUN, "run URI resolution failed", exc
            ),
        )

    path = resolved.path
    if path.exists():
        if not path.is_dir():
            return (
                _result(
                    "run_uri.resolve",
                    PreflightGroup.RUN,
                    PreflightCheckStatus.FAIL,
                    PreflightSeverity.ERROR,
                    "run URI resolves to a non-directory path",
                    {
                        "run_uri": resolved.uri,
                        "path": str(path),
                        "state_source": local_materialization_source(path=str(path)),
                    },
                ),
            )
        if _request_resume_enabled(context):
            return (
                _result(
                    "run_uri.resolve",
                    PreflightGroup.RUN,
                    PreflightCheckStatus.PASS,
                    PreflightSeverity.INFO,
                    "run URI resolves to an existing local run directory for resume",
                    {
                        "run_uri": resolved.uri,
                        "path": str(path),
                        "exists": True,
                        "resume": True,
                        "state_source": local_materialization_source(path=str(path)),
                        **_authority_policy_details(context),
                    },
                ),
            )
        return (
            _result(
                "run_uri.resolve",
                PreflightGroup.RUN,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "run URI directory already exists",
                {
                    "run_uri": resolved.uri,
                    "path": str(path),
                    "state_source": local_materialization_source(path=str(path)),
                    "guidance": (
                        "resume the run with the selected authority or choose "
                        "a new run URI"
                    ),
                    **_authority_policy_details(context),
                },
            ),
        )

    return (
        _result(
            "run_uri.resolve",
            PreflightGroup.RUN,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "run URI resolves to an available local path",
            {
                "run_uri": resolved.uri,
                "path": str(path),
                "exists": False,
                "state_source": local_materialization_source(path=str(path)),
                **_authority_policy_details(context),
            },
        ),
    )


def _check_slurm_active_submission(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_slurm(context):
        return ()
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.slurm.active_submission",
                PreflightGroup.RUN,
                "SLURM submitted-operation probe failed",
                exc,
            ),
        )
    if run_uri is None:
        return (
            _missing_run_uri("run_uri.slurm.active_submission", PreflightGroup.RUN),
        )
    try:
        from loom.pipeline.execution import create_authority_backed_serial_run_store

        resolved = cast(Any, context.run_uri())
        if not resolved.path.exists():
            return (
                _result(
                    "run_uri.slurm.active_submission",
                    PreflightGroup.RUN,
                    PreflightCheckStatus.PASS,
                    PreflightSeverity.INFO,
                    "no existing run directory has active submitted SLURM work",
                    {
                        "run_uri": resolved.uri,
                        "run_exists": False,
                        "state_source": local_materialization_source(
                            path=str(resolved.path)
                        ),
                        **_authority_policy_details(context),
                    },
                ),
            )
        store = create_authority_backed_serial_run_store(
            resolved.path.parent,
            authority_config=cast(Any, context.authority_config()),
            owner_id="preflight",
        )
        store.open_run(resolved.uri)
        active = store.latest_active_submitted_operation(resolved.uri)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.slurm.active_submission",
                PreflightGroup.RUN,
                "SLURM submitted-operation probe failed",
                exc,
            ),
        )
    if active is None:
        return (
            _result(
                "run_uri.slurm.active_submission",
                PreflightGroup.RUN,
                PreflightCheckStatus.PASS,
                PreflightSeverity.INFO,
                "existing run has no active submitted SLURM work",
                {
                    "run_uri": resolved.uri,
                    "active": False,
                    "state_source": _active_submission_source(context),
                    **_authority_policy_details(context),
                },
            ),
        )
    return (
        _result(
            "run_uri.slurm.active_submission",
            PreflightGroup.RUN,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "run already has active submitted scheduler work",
            {
                "run_uri": resolved.uri,
                "active": True,
                "submission_id": active.submission_id,
                "backend": active.backend,
                "mode": active.mode,
                "state": active.state.value,
                "state_source": _active_submission_source(context),
                "guidance": "cancel or inspect active scheduler work before resubmitting",
                **_authority_policy_details(context),
            },
        ),
    )


def _check_slurm_run_uri_local(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_slurm(context):
        return ()
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.slurm.local",
                PreflightGroup.RUN,
                "SLURM run URI probe failed",
                exc,
            ),
        )
    if run_uri is None:
        return (_missing_run_uri("run_uri.slurm.local", PreflightGroup.RUN),)
    try:
        resolved = cast(Any, context.run_uri())
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "run_uri.slurm.local",
                PreflightGroup.RUN,
                "SLURM dry-run requires a local run URI",
                exc,
            ),
        )
    return (
        _result(
            "run_uri.slurm.local",
            PreflightGroup.RUN,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM dry-run run URI resolves locally",
            {
                "run_uri": resolved.uri,
                "path": str(resolved.path),
                "state_source": local_materialization_source(path=str(resolved.path)),
            },
        ),
    )


def _check_artifacts(context: _Context) -> tuple[PreflightCheckResult, ...]:
    return (
        *_check_artifact_store(context),
        *_check_artifact_backends(context),
    )


def _check_artifact_store(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "artifact_store.available",
                PreflightGroup.ARTIFACTS,
                "artifact store probe failed",
                exc,
            ),
        )
    if run_uri is None:
        return (_missing_run_uri("artifact_store.available", PreflightGroup.ARTIFACTS),)
    try:
        resolved = cast(Any, context.run_uri())
        from loom.pipeline.stores import LocalArtifactStore, LocalRunStore

        run_store = LocalRunStore(resolved.path.parent)
        root = run_store.local_artifact_root(resolved.uri)
        store = LocalArtifactStore(root)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "artifact_store.available",
                PreflightGroup.ARTIFACTS,
                "artifact store probe failed",
                exc,
            ),
        )

    if root.exists() and not root.is_dir():
        return (
            _result(
                "artifact_store.available",
                PreflightGroup.ARTIFACTS,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "artifact root exists but is not a directory",
                {
                    "path": str(root),
                    "state_source": local_materialization_source(path=str(root)),
                },
            ),
        )

    return (
        _result(
            "artifact_store.available",
            PreflightGroup.ARTIFACTS,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "local artifact store can be constructed",
            {
                "path": str(store.root),
                "exists": root.exists(),
                "state_source": local_materialization_source(path=str(root)),
            },
        ),
    )


@dataclass(frozen=True)
class _ResolvedArtifactBackendTarget:
    target: ArtifactBackendPreflightTarget
    backend_kind: str | None
    handler: object | None
    handler_source: str
    registry_diagnostics: tuple[object, ...] = ()
    handler_diagnostics: tuple[object, ...] = ()


def _check_artifact_backends(context: _Context) -> tuple[PreflightCheckResult, ...]:
    targets = context.request.artifact_backend_targets
    if not targets:
        details = {"reason": "no_artifact_backend_targets"}
        return (
            _skip(
                "artifact_backends.registry",
                PreflightGroup.ARTIFACTS,
                "no artifact backend targets configured",
                details,
            ),
            _skip(
                "artifact_backends.handlers",
                PreflightGroup.ARTIFACTS,
                "no artifact backend targets configured",
                details,
            ),
            _skip(
                "artifact_backends.capabilities",
                PreflightGroup.ARTIFACTS,
                "no artifact backend targets configured",
                details,
            ),
            _skip(
                "artifact_backends.materialization",
                PreflightGroup.ARTIFACTS,
                "no artifact backend targets configured",
                details,
            ),
        )

    resolved = _resolve_artifact_backend_targets(context)
    return (
        _artifact_backend_registry_check(resolved),
        _artifact_backend_handler_check(resolved),
        _artifact_backend_capability_check(resolved),
        _artifact_backend_materialization_check(resolved),
    )


def _resolve_artifact_backend_targets(
    context: _Context,
) -> tuple[_ResolvedArtifactBackendTarget, ...]:
    from loom.artifacts import ArtifactStoreRef
    from loom.pipeline.stores import (
        ArtifactStoreBackendDiagnostic,
        ArtifactStoreBackendDiagnosticSeverity,
        ArtifactStoreBackendHandler,
        ArtifactStoreBackendRegistry,
        ArtifactStoreBackendRegistryError,
        normalize_artifact_store_backend_kind,
    )

    registry = context.request.artifact_backend_registry
    if registry is not None and not isinstance(registry, ArtifactStoreBackendRegistry):
        diagnostic = ArtifactStoreBackendDiagnostic(
            code="invalid_artifact_store_backend_registry",
            message="artifact backend registry must be ArtifactStoreBackendRegistry",
            severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
        )
        return tuple(
            _ResolvedArtifactBackendTarget(
                target=target,
                backend_kind=None,
                handler=None,
                handler_source="missing",
                registry_diagnostics=(diagnostic,),
                handler_diagnostics=(diagnostic,),
            )
            for target in context.request.artifact_backend_targets
        )

    supplied_handlers: dict[str, object] = {}
    for key, handler in context.request.artifact_backend_handlers.items():
        try:
            supplied_handlers[normalize_artifact_store_backend_kind(key)] = handler
        except Exception:  # noqa: BLE001
            supplied_handlers[key] = handler
    resolved: list[_ResolvedArtifactBackendTarget] = []
    for target in context.request.artifact_backend_targets:
        registry_diagnostics: list[object] = []
        handler_diagnostics: list[object] = []
        handler: object | None = None
        handler_source = "missing"

        if not isinstance(target.store, ArtifactStoreRef):
            diagnostic = ArtifactStoreBackendDiagnostic(
                code="invalid_artifact_backend_preflight_store",
                message="artifact backend preflight target store must be ArtifactStoreRef",
                severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                detail={"target_id": target.target_id},
            )
            resolved.append(
                _ResolvedArtifactBackendTarget(
                    target=target,
                    backend_kind=None,
                    handler=None,
                    handler_source=handler_source,
                    registry_diagnostics=(diagnostic,),
                    handler_diagnostics=(diagnostic,),
                )
            )
            continue

        try:
            backend_kind = normalize_artifact_store_backend_kind(target.store.kind)
        except Exception as exc:  # noqa: BLE001
            diagnostic = ArtifactStoreBackendDiagnostic(
                code="invalid_artifact_store_backend_kind",
                message=str(exc),
                severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                detail={"target_id": target.target_id},
            )
            resolved.append(
                _ResolvedArtifactBackendTarget(
                    target=target,
                    backend_kind=None,
                    handler=None,
                    handler_source=handler_source,
                    registry_diagnostics=(diagnostic,),
                    handler_diagnostics=(diagnostic,),
                )
            )
            continue

        supplied = supplied_handlers.get(backend_kind)
        if supplied is not None:
            if isinstance(supplied, ArtifactStoreBackendHandler):
                handler = supplied
                handler_source = "supplied_handler"
            else:
                handler_diagnostics.append(
                    ArtifactStoreBackendDiagnostic(
                        code="invalid_artifact_store_backend_handler",
                        message=(
                            "artifact backend handler must implement "
                            "ArtifactStoreBackendHandler"
                        ),
                        severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                        detail={
                            "target_id": target.target_id,
                            "backend_kind": backend_kind,
                        },
                    )
                )
        elif registry is not None:
            try:
                handler = registry.create_handler(
                    backend_kind,
                    target.store,
                    config=target.config,
                    run_context=target.run_context,
                )
                handler_source = "registry"
            except ArtifactStoreBackendRegistryError as exc:
                registry_diagnostics.append(exc.diagnostic)
            except Exception as exc:  # noqa: BLE001
                registry_diagnostics.append(
                    ArtifactStoreBackendDiagnostic(
                        code="artifact_store_backend_handler_create_failed",
                        message=str(exc),
                        severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                        detail={
                            "target_id": target.target_id,
                            "backend_kind": backend_kind,
                        },
                    )
                )
        else:
            registry_diagnostics.append(
                ArtifactStoreBackendDiagnostic(
                    code="missing_artifact_store_backend_registry",
                    message="artifact backend target has no supplied registry or handler",
                    severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                    detail={
                        "target_id": target.target_id,
                        "backend_kind": backend_kind,
                    },
                )
            )

        if handler is None and not handler_diagnostics:
            handler_diagnostics.append(
                ArtifactStoreBackendDiagnostic(
                    code="missing_artifact_store_backend_handler",
                    message="artifact backend target has no configured handler",
                    severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                    detail={
                        "target_id": target.target_id,
                        "backend_kind": backend_kind,
                    },
                )
            )
        if isinstance(handler, ArtifactStoreBackendHandler):
            try:
                handler_diagnostics.extend(handler.validate_store_ref(target.store))
            except Exception as exc:  # noqa: BLE001
                handler_diagnostics.append(
                    ArtifactStoreBackendDiagnostic(
                        code="artifact_store_backend_ref_validation_failed",
                        message=str(exc),
                        severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                        detail={
                            "target_id": target.target_id,
                            "backend_kind": backend_kind,
                        },
                    )
                )

        resolved.append(
            _ResolvedArtifactBackendTarget(
                target=target,
                backend_kind=backend_kind,
                handler=handler,
                handler_source=handler_source,
                registry_diagnostics=tuple(registry_diagnostics),
                handler_diagnostics=tuple(handler_diagnostics),
            )
        )
    return tuple(resolved)


def _artifact_backend_registry_check(
    resolved: tuple[_ResolvedArtifactBackendTarget, ...],
) -> PreflightCheckResult:
    diagnostics = tuple(
        diagnostic for item in resolved for diagnostic in item.registry_diagnostics
    )
    status, severity = _artifact_backend_preflight_status(diagnostics)
    return _result(
        "artifact_backends.registry",
        PreflightGroup.ARTIFACTS,
        status,
        severity,
        _artifact_backend_message(
            "artifact backend registry",
            status=status,
            diagnostic_count=len(diagnostics),
        ),
        _artifact_backend_details(resolved, diagnostics=diagnostics),
    )


def _artifact_backend_handler_check(
    resolved: tuple[_ResolvedArtifactBackendTarget, ...],
) -> PreflightCheckResult:
    diagnostics = tuple(
        diagnostic for item in resolved for diagnostic in item.handler_diagnostics
    )
    status, severity = _artifact_backend_preflight_status(diagnostics)
    return _result(
        "artifact_backends.handlers",
        PreflightGroup.ARTIFACTS,
        status,
        severity,
        _artifact_backend_message(
            "artifact backend handlers",
            status=status,
            diagnostic_count=len(diagnostics),
        ),
        _artifact_backend_details(resolved, diagnostics=diagnostics),
    )


def _artifact_backend_capability_check(
    resolved: tuple[_ResolvedArtifactBackendTarget, ...],
) -> PreflightCheckResult:
    from loom.pipeline.stores import (
        ArtifactStoreBackendDiagnostic,
        ArtifactStoreBackendDiagnosticSeverity,
        ArtifactStoreBackendHandler,
        admit_artifact_store_operations,
    )

    diagnostics: list[object] = []
    operation_results: list[PlainData] = []
    for item in resolved:
        source = (
            item.handler
            if isinstance(item.handler, ArtifactStoreBackendHandler)
            else None
        )
        results = admit_artifact_store_operations(
            source,
            item.target.required_operations,
        )
        for result in results:
            operation_results.append(result.to_dict())
            diagnostics.extend(result.diagnostics)
        if source is None and item.target.required_operations:
            diagnostics.append(
                ArtifactStoreBackendDiagnostic(
                    code="artifact_store_backend_capability_handler_missing",
                    message="required artifact backend operations have no handler",
                    severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                    detail={
                        "target_id": item.target.target_id,
                        "backend_kind": item.backend_kind,
                        "required_operations": list(item.target.required_operations),
                    },
                )
            )

    status, severity = _artifact_backend_preflight_status(tuple(diagnostics))
    details = dict(
        _artifact_backend_details(tuple(resolved), diagnostics=tuple(diagnostics))
    )
    details["operation_results"] = operation_results
    return _result(
        "artifact_backends.capabilities",
        PreflightGroup.ARTIFACTS,
        status,
        severity,
        _artifact_backend_message(
            "artifact backend capabilities",
            status=status,
            diagnostic_count=len(diagnostics),
        ),
        details,
    )


def _artifact_backend_materialization_check(
    resolved: tuple[_ResolvedArtifactBackendTarget, ...],
) -> PreflightCheckResult:
    from loom.pipeline.stores import (
        ArtifactStoreBackendDiagnostic,
        ArtifactStoreBackendDiagnosticSeverity,
        ArtifactStoreBackendOperation,
        ArtifactStoreBackendPayloadHandler,
    )

    payload_operations = {
        ArtifactStoreBackendOperation.PUBLISH.value,
        ArtifactStoreBackendOperation.MATERIALIZE.value,
        ArtifactStoreBackendOperation.UPLOAD.value,
        ArtifactStoreBackendOperation.DOWNLOAD.value,
        ArtifactStoreBackendOperation.VERIFY_CHECKSUM.value,
    }
    materialization_targets = tuple(
        item
        for item in resolved
        if any(
            operation in payload_operations
            for operation in item.target.required_operations
        )
    )
    if not materialization_targets:
        return _skip(
            "artifact_backends.materialization",
            PreflightGroup.ARTIFACTS,
            "no artifact backend materialization targets configured",
            {"reason": "no_materialization_targets"},
        )

    diagnostics: list[object] = []
    readiness: list[PlainData] = []
    for item in materialization_targets:
        payload_handler_configured = isinstance(
            item.handler,
            ArtifactStoreBackendPayloadHandler,
        )
        readiness.append(
            {
                "target_id": item.target.target_id,
                "backend_kind": item.backend_kind,
                "payload_handler_configured": payload_handler_configured,
                "required_operations": list(item.target.required_operations),
                "expensive_probe": False,
            }
        )
        if item.handler is None:
            diagnostics.append(
                ArtifactStoreBackendDiagnostic(
                    code="artifact_store_backend_materialization_handler_missing",
                    message="payload materialization target has no configured handler",
                    severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                    detail={
                        "target_id": item.target.target_id,
                        "backend_kind": item.backend_kind,
                    },
                )
            )
            continue
        if not payload_handler_configured:
            diagnostics.append(
                ArtifactStoreBackendDiagnostic(
                    code="artifact_store_backend_payload_handler_missing",
                    message=(
                        "payload materialization target requires "
                        "ArtifactStoreBackendPayloadHandler"
                    ),
                    severity=ArtifactStoreBackendDiagnosticSeverity.ERROR,
                    detail={
                        "target_id": item.target.target_id,
                        "backend_kind": item.backend_kind,
                        "required_operations": list(item.target.required_operations),
                    },
                )
            )

    status, severity = _artifact_backend_preflight_status(tuple(diagnostics))
    details = dict(
        _artifact_backend_details(tuple(resolved), diagnostics=tuple(diagnostics))
    )
    details["materialization_targets"] = readiness
    details["expensive_probe"] = False
    return _result(
        "artifact_backends.materialization",
        PreflightGroup.ARTIFACTS,
        status,
        severity,
        _artifact_backend_message(
            "artifact backend materialization readiness",
            status=status,
            diagnostic_count=len(diagnostics),
        ),
        details,
    )


def _artifact_backend_preflight_status(
    diagnostics: tuple[object, ...],
) -> tuple[PreflightCheckStatus, PreflightSeverity]:
    from loom.pipeline.stores import ArtifactStoreBackendDiagnosticSeverity

    severities = {
        getattr(getattr(diagnostic, "severity", None), "value", None)
        for diagnostic in diagnostics
    }
    if ArtifactStoreBackendDiagnosticSeverity.ERROR.value in severities:
        return PreflightCheckStatus.FAIL, PreflightSeverity.ERROR
    if ArtifactStoreBackendDiagnosticSeverity.WARNING.value in severities:
        return PreflightCheckStatus.WARN, PreflightSeverity.WARNING
    return PreflightCheckStatus.PASS, PreflightSeverity.INFO


def _artifact_backend_message(
    label: str,
    *,
    status: PreflightCheckStatus,
    diagnostic_count: int,
) -> str:
    if status is PreflightCheckStatus.PASS:
        return f"{label} checks passed"
    if status is PreflightCheckStatus.WARN:
        return f"{label} checks reported {diagnostic_count} warning(s)"
    return f"{label} checks failed"


def _artifact_backend_details(
    resolved: tuple[_ResolvedArtifactBackendTarget, ...],
    *,
    diagnostics: tuple[object, ...],
) -> Mapping[str, PlainData]:
    payload = {
        "target_count": len(resolved),
        "targets": [_artifact_backend_target_detail(item) for item in resolved],
        "diagnostic_count": len(diagnostics),
        "diagnostics": [
            cast(Mapping[str, PlainData], cast(Any, diagnostic).to_dict())
            for diagnostic in diagnostics
            if hasattr(diagnostic, "to_dict")
        ],
    }
    return cast(
        Mapping[str, PlainData],
        ensure_plain_data(payload, path="artifact_backend_details"),
    )


def _artifact_backend_target_detail(
    item: _ResolvedArtifactBackendTarget,
) -> Mapping[str, PlainData]:
    target = item.target
    return {
        "target_id": target.target_id,
        "backend_kind": item.backend_kind,
        "handler_source": item.handler_source,
        "handler_configured": item.handler is not None,
        "required_operations": list(target.required_operations),
        "store": _redacted_artifact_backend_store(item),
        "details": dict(target.details),
    }


def _redacted_artifact_backend_store(
    item: _ResolvedArtifactBackendTarget,
) -> PlainData:
    from loom.artifacts import ArtifactStoreRef
    from loom.pipeline.stores import ArtifactStoreBackendHandler

    store = item.target.store
    if isinstance(store, ArtifactStoreRef) and isinstance(
        item.handler, ArtifactStoreBackendHandler
    ):
        try:
            store = item.handler.redact_store_ref(store)
        except Exception:  # noqa: BLE001 - diagnostics fall back to display summary.
            pass
    summary = (
        cast(Any, store).to_summary()
        if hasattr(store, "to_summary")
        else {"type": type(store).__name__}
    )
    if isinstance(summary, Mapping) and summary.get("display_uri") is not None:
        summary = {**summary, "uri": None}
    return cast(PlainData, ensure_plain_data(summary, path="artifact_backend_store"))


@dataclass(frozen=True)
class _CleanupPreflightPlan:
    target: CleanupPreflightTarget
    report: object


def _check_cleanup(context: _Context) -> tuple[PreflightCheckResult, ...]:
    targets = context.request.cleanup_targets
    if not targets:
        details = {"reason": "no_cleanup_targets"}
        return (
            _skip(
                "cleanup.candidates.safety",
                PreflightGroup.CLEANUP,
                "no cleanup preflight targets configured",
                details,
            ),
            _skip(
                "cleanup.targets.support",
                PreflightGroup.CLEANUP,
                "no cleanup preflight targets configured",
                details,
            ),
            _skip(
                "cleanup.retention.policy",
                PreflightGroup.CLEANUP,
                "no cleanup preflight targets configured",
                details,
            ),
        )
    try:
        plans = _cleanup_preflight_plans(targets)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "cleanup.candidates.safety",
                PreflightGroup.CLEANUP,
                "cleanup candidate preflight failed",
                exc,
            ),
            _skip(
                "cleanup.targets.support",
                PreflightGroup.CLEANUP,
                "cleanup target support check skipped after planning failure",
                {"reason": "cleanup_plan_failed"},
            ),
            _skip(
                "cleanup.retention.policy",
                PreflightGroup.CLEANUP,
                "cleanup retention check skipped after planning failure",
                {"reason": "cleanup_plan_failed"},
            ),
        )
    return (
        _cleanup_candidate_safety_check(plans),
        _cleanup_target_support_check(plans),
        _cleanup_retention_policy_check(plans),
    )


def _cleanup_preflight_plans(
    targets: tuple[CleanupPreflightTarget, ...],
) -> tuple[_CleanupPreflightPlan, ...]:
    from loom.pipeline.cleanup import CleanupManagedRoot, plan_cleanup

    plans: list[_CleanupPreflightPlan] = []
    for target in targets:
        roots: list[CleanupManagedRoot] = []
        for index, root in enumerate(target.managed_roots):
            if not isinstance(root, CleanupManagedRoot):
                raise TypeError(
                    "cleanup preflight target "
                    f"{target.target_id!r} managed_roots[{index}] "
                    "must be CleanupManagedRoot"
                )
            roots.append(root)
        report = plan_cleanup(
            cast(Any, target.store),
            target.run_uri,
            selector=target.selector,
            managed_roots=tuple(roots),
            require_ownership=target.require_ownership,
            metadata=target.details,
        )
        plans.append(_CleanupPreflightPlan(target=target, report=report))
    return tuple(plans)


def _cleanup_candidate_safety_check(
    plans: tuple[_CleanupPreflightPlan, ...],
) -> PreflightCheckResult:
    unsafe = _unsafe_cleanup_entries(plans)
    status = PreflightCheckStatus.WARN if unsafe else PreflightCheckStatus.PASS
    return _result(
        "cleanup.candidates.safety",
        PreflightGroup.CLEANUP,
        status,
        _severity_for_status(status),
        (
            "cleanup candidates have safety warnings"
            if unsafe
            else "cleanup candidate safety checks passed"
        ),
        {
            "target_count": len(plans),
            "run_count": len({plan.target.run_uri for plan in plans}),
            "unsafe_count": len(unsafe),
            "unsafe": unsafe,
            "expensive_probe": False,
        },
    )


def _cleanup_target_support_check(
    plans: tuple[_CleanupPreflightPlan, ...],
) -> PreflightCheckResult:
    unsupported = _unsupported_cleanup_targets(plans)
    status = PreflightCheckStatus.WARN if unsupported else PreflightCheckStatus.PASS
    return _result(
        "cleanup.targets.support",
        PreflightGroup.CLEANUP,
        status,
        _severity_for_status(status),
        (
            "cleanup targets include unsupported local-deletion references"
            if unsupported
            else "cleanup target support checks passed"
        ),
        {
            "target_count": len(plans),
            "unsupported_target_count": len(unsupported),
            "unsupported_targets": unsupported,
            "expensive_probe": False,
        },
    )


def _cleanup_retention_policy_check(
    plans: tuple[_CleanupPreflightPlan, ...],
) -> PreflightCheckResult:
    unsupported = _unsupported_retention_policies(plans)
    status = PreflightCheckStatus.WARN if unsupported else PreflightCheckStatus.PASS
    return _result(
        "cleanup.retention.policy",
        PreflightGroup.CLEANUP,
        status,
        _severity_for_status(status),
        (
            "cleanup candidates include unsupported retention policies"
            if unsupported
            else "cleanup retention policy checks passed"
        ),
        {
            "target_count": len(plans),
            "unsupported_policy_count": len(unsupported),
            "unsupported_policies": unsupported,
            "expensive_probe": False,
        },
    )


def _unsafe_cleanup_entries(
    plans: tuple[_CleanupPreflightPlan, ...],
) -> list[PlainData]:
    from loom.pipeline.cleanup import CleanupReportEntryStatus

    unsafe: list[PlainData] = []
    for plan in plans:
        report = cast(Any, plan.report)
        for entry in report.entries:
            if entry.status is not CleanupReportEntryStatus.REJECTED:
                continue
            unsafe.append(_cleanup_entry_detail(plan, entry))
    return unsafe


def _unsupported_cleanup_targets(
    plans: tuple[_CleanupPreflightPlan, ...],
) -> list[PlainData]:
    unsupported: list[PlainData] = []
    for plan in plans:
        report = cast(Any, plan.report)
        for entry in report.entries:
            if getattr(
                entry.target.kind, "value", entry.target.kind
            ) != "local_path" or entry.reason_code in {
                "unsupported_target_kind",
                "unsupported_uri_scheme",
            }:
                unsupported.append(_cleanup_entry_detail(plan, entry))
    return unsupported


def _unsupported_retention_policies(
    plans: tuple[_CleanupPreflightPlan, ...],
) -> list[PlainData]:
    from loom.artifacts import normalize_retention_policy

    unsupported: list[PlainData] = []
    for plan in plans:
        report = cast(Any, plan.report)
        for entry in report.entries:
            retention = _cleanup_entry_retention_value(entry)
            if retention is None:
                continue
            try:
                normalize_retention_policy(retention)
            except Exception as exc:  # noqa: BLE001
                detail = cast(dict[str, PlainData], _cleanup_entry_detail(plan, entry))
                detail["retention"] = _retention_detail_value(retention)
                detail["error_type"] = type(exc).__name__
                detail["error"] = str(exc)
                unsupported.append(detail)
    return unsupported


def _cleanup_entry_detail(plan: _CleanupPreflightPlan, entry: object) -> PlainData:
    target = cast(Any, entry).target
    safety = cast(Any, entry).safety_decision
    detail: dict[str, PlainData] = {
        "target_id": plan.target.target_id,
        "run_uri": plan.target.run_uri,
        "candidate_id": cast(str, cast(Any, entry).candidate_id),
        "target_kind": str(getattr(target.kind, "value", target.kind)),
        "target_uri": str(target.uri),
        "status": str(
            getattr(cast(Any, entry).status, "value", cast(Any, entry).status)
        ),
        "reason_code": str(cast(Any, entry).reason_code),
    }
    if isinstance(safety, Mapping):
        managed_root_id = safety.get("managed_root_id")
        message = safety.get("message")
        if isinstance(managed_root_id, str):
            detail["managed_root_id"] = managed_root_id
        if isinstance(message, str):
            detail["message"] = message
    return detail


def _cleanup_entry_retention_value(entry: object) -> PlainData:
    metadata = getattr(getattr(entry, "target"), "metadata")
    if not isinstance(metadata, Mapping):
        return None
    if "retention" in metadata:
        return cast(PlainData, metadata["retention"])
    mode = metadata.get("retention_mode")
    if mode is None:
        return None
    return {"mode": mode}


def _retention_detail_value(value: PlainData) -> PlainData:
    return cast(PlainData, ensure_plain_data(value, path="retention"))


def _authority_policy_details(context: _Context) -> dict[str, PlainData]:
    config = context.authority_config()
    authority = redacted_authority_summary(config)
    backend_kind = _enum_value(getattr(config, "backend_kind", None))
    deployment_profile = _enum_value(getattr(config, "deployment_profile", None))
    authority_mode = _enum_value(context.authority_mode())
    policy: dict[str, PlainData] = {
        "backend_kind": backend_kind,
        "deployment_profile": deployment_profile,
    }
    if authority_mode is not None:
        policy["authority_mode"] = authority_mode
    details: dict[str, PlainData] = {"authority_policy": policy}
    if authority is not None:
        details["authority"] = authority
    if authority_mode == "offline_first":
        policy["source"] = offline_evidence_source()
        details["guidance"] = (
            "offline-first mode records local evidence and does not create "
            "authority truth until import"
        )
    elif (
        backend_kind == "deferred_finalization"
        or deployment_profile == "deferred_finalization"
    ):
        policy["source"] = deferred_finalization_source()
        details["guidance"] = (
            "deferred finalization is non-authoritative until a service imports it"
        )
    elif backend_kind in {"direct_database", "transitional_sqlite"}:
        policy["source"] = unavailable_authority_source(
            reason=f"unsupported_{backend_kind}",
            authority=authority,
        )
        details["guidance"] = (
            "select a service authority endpoint or explicit offline mode"
        )
    else:
        policy["source"] = authoritative_service_source(
            authority=authority,
        )
    return details


def _active_submission_source(context: _Context) -> dict[str, PlainData]:
    return authoritative_service_source(
        authority=redacted_authority_summary(context.authority_config())
    )


def _enum_value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    if raw is None:
        return None
    return str(raw)


def _check_codecs(_context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        from loom.io.codecs.registry import create_default_codec_registry

        registry = create_default_codec_registry()
        keys = registry.keys()
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "codec_registry.available",
                PreflightGroup.CODECS,
                "codec registry probe failed",
                exc,
            ),
        )

    required = {"json.v1", "text.v1", "bytes.v1"}
    missing = sorted(required - set(keys))
    if missing:
        return (
            _result(
                "codec_registry.available",
                PreflightGroup.CODECS,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "default codec registry is missing required codecs",
                cast(
                    Mapping[str, PlainData],
                    {"missing": missing, "registered": list(keys)},
                ),
            ),
        )
    return (
        _result(
            "codec_registry.available",
            PreflightGroup.CODECS,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "default codec registry is available",
            cast(Mapping[str, PlainData], {"registered": list(keys)}),
        ),
    )


def _check_executor(context: _Context) -> tuple[PreflightCheckResult, ...]:
    return (
        *_check_local_executor(),
        *_check_executor_resolve(context),
        *_check_executor_capabilities(context),
        *_check_container_build_target_selection(context),
        *_check_apptainer_executor(context),
        *_check_docker_executor(context),
        *_check_subprocess_executor(context),
        *_check_slurm_executor(context),
    )


def _check_local_executor() -> tuple[PreflightCheckResult, ...]:
    try:
        from loom.pipeline.executors import LocalExecutor

        executor = LocalExecutor()
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "executor.local",
                PreflightGroup.EXECUTOR,
                "local executor probe failed",
                exc,
            ),
        )

    return (
        _result(
            "executor.local",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "local executor is available",
            {"executor": type(executor).__name__},
        ),
    )


def _check_executor_resolve(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        result = context.capability_validation()
        options = cast(Any, context.runtime_options())
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "executor.resolve",
                PreflightGroup.EXECUTOR,
                "executor resolution failed",
                exc,
            ),
        )

    unknown = _unknown_executor_diagnostic(result)
    if unknown is not None:
        return (
            _result(
                "executor.resolve",
                PreflightGroup.EXECUTOR,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                cast(Any, unknown).message,
                {"diagnostic": cast(Any, unknown).to_dict()},
            ),
        )

    return (
        _result(
            "executor.resolve",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "selected executor descriptor is registered",
            {"executor": options.executor or "local"},
        ),
    )


def _check_executor_capabilities(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        result = context.capability_validation()
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "executor.capabilities",
                PreflightGroup.EXECUTOR,
                "executor capability validation failed",
                exc,
            ),
        )

    if _unknown_executor_diagnostic(result) is not None:
        return (
            _skip(
                "executor.capabilities",
                PreflightGroup.EXECUTOR,
                "check skipped because the selected executor is unresolved",
                {"reason": "executor_unresolved"},
            ),
        )

    diagnostics = [
        diagnostic
        for diagnostic in cast(Any, result).diagnostics
        if not str(diagnostic.code).startswith("resource.")
    ]
    status = _status_from_capability_diagnostics(diagnostics)
    return (
        _result(
            "executor.capabilities",
            PreflightGroup.EXECUTOR,
            status,
            _severity_for_status(status),
            _capability_message(
                "executor capability diagnostics",
                diagnostics=diagnostics,
                status=status,
            ),
            _capability_details(diagnostics),
        ),
    )


def _check_container_build_target_selection(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    try:
        selections = _selected_container_build_targets(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "executor.container_build.targets",
                PreflightGroup.EXECUTOR,
                "container build target selection probe failed",
                exc,
            ),
        )
    if not selections:
        return ()

    targets: list[PlainData] = []
    diagnostics: list[PlainData] = []
    for raw_target in selections:
        container = raw_target.adapter_options.get("container")
        if not isinstance(container, Mapping):
            diagnostics.append(
                _container_build_diagnostic(
                    _target_owner_id(raw_target.stage_id),
                    code="container_options_invalid",
                    message="adapter_options.container must be a mapping",
                )
            )
            continue
        target_name = container.get("target")
        if not isinstance(target_name, str) or not target_name:
            continue
        try:
            build_options = _container_build_options_from_adapter(
                raw_target.adapter_options
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _container_build_diagnostic(
                    _target_owner_id(raw_target.stage_id),
                    code="container_build_options_invalid",
                    message=str(exc) or type(exc).__name__,
                    detail={"target_name": target_name},
                )
            )
            continue
        target = cast(Mapping[str, object], cast(Any, build_options).targets).get(
            target_name
        )
        if target is None:
            diagnostics.append(
                _container_build_diagnostic(
                    _target_owner_id(raw_target.stage_id),
                    code="container_build_target_missing",
                    message=f"container build target {target_name!r} is not defined",
                    detail={"target_name": target_name},
                )
            )
            continue
        runtime = _enum_value(getattr(target, "runtime", None))
        output = getattr(target, "output", None)
        output_kind = _enum_value(getattr(output, "kind", None))
        output_identity = _container_build_output_identity(output)
        selected_executor = _selected_container_executor_name(raw_target)
        targets.append(
            {
                "stage_id": raw_target.stage_id,
                "target_name": target_name,
                "selected_executor": selected_executor,
                "target_runtime": runtime,
                "output_kind": output_kind,
                "output_identity": output_identity,
            }
        )
        if _is_slurm_executor_name(selected_executor):
            if runtime != "apptainer" or output_kind != "apptainer_sif":
                diagnostics.append(
                    _container_build_diagnostic(
                        _target_owner_id(raw_target.stage_id),
                        code="container_build_target_incompatible",
                        message=(
                            "selected Apptainer execution requires an "
                            "apptainer target with an apptainer_sif output"
                        ),
                        detail={
                            "target_name": target_name,
                            "target_runtime": runtime,
                            "output_kind": output_kind,
                        },
                    )
                )
        elif selected_executor in _APPTAINER_EXECUTORS:
            diagnostics.append(
                _container_build_diagnostic(
                    _target_owner_id(raw_target.stage_id),
                    code="container_build_target_not_resolved",
                    message=(
                        "direct Apptainer/Singularity preflight does not resolve "
                        "container.target in Stage 18; use "
                        "adapter_options.container.image with the built SIF path"
                    ),
                    detail={"target_name": target_name},
                )
            )
        elif selected_executor == "docker":
            diagnostics.append(
                _container_build_diagnostic(
                    _target_owner_id(raw_target.stage_id),
                    code="container_build_target_not_resolved",
                    message=(
                        "Docker preflight does not resolve container.target in "
                        "Stage 18; use adapter_options.container.image"
                    ),
                    detail={"target_name": target_name},
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return (
        _result(
            "executor.container_build.targets",
            PreflightGroup.EXECUTOR,
            status,
            _severity_for_status(status),
            (
                "selected container build targets are compatible"
                if status is PreflightCheckStatus.PASS
                else "selected container build target checks failed"
            ),
            {
                "target_count": len(targets),
                "targets": targets,
                "diagnostics": diagnostics,
                "expensive_probe": False,
            },
        ),
    )


def _check_apptainer_executor(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_apptainer(context):
        return ()
    return (
        _check_apptainer_command(context),
        _check_apptainer_container_options(context),
        _check_apptainer_image(context),
        _check_apptainer_environment(context),
    )


def _check_apptainer_command(context: _Context) -> PreflightCheckResult:
    try:
        targets = _apptainer_raw_targets(context)
        options = cast(Any, context.runtime_options())
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.apptainer.command",
            PreflightGroup.EXECUTOR,
            "Apptainer command availability probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    commands: list[PlainData] = []
    command_required = _apptainer_command_required(options)
    for target in targets:
        try:
            apptainer_options = _apptainer_options_from_adapter(
                target.adapter_options,
                executor_name=target.executor_name,
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        command = cast(Any, apptainer_options).command
        resolved = shutil.which(command)
        commands.append(
            {
                "stage_id": target.stage_id,
                "command": command,
                "available": resolved is not None,
                "path": resolved,
                "required": command_required,
            }
        )
        if resolved is None:
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_command_unavailable",
                    message=(
                        "Apptainer/Singularity command is not available on PATH: "
                        f"{command}"
                    ),
                    detail={"command": command, "required": command_required},
                )
            )

    if diagnostics:
        status = (
            PreflightCheckStatus.FAIL if command_required else PreflightCheckStatus.WARN
        )
    else:
        status = PreflightCheckStatus.PASS
    return _result(
        "executor.apptainer.command",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Apptainer/Singularity command is available"
            if status is PreflightCheckStatus.PASS
            else "Apptainer/Singularity command availability checks reported issues"
        ),
        {
            "target_count": len(targets),
            "commands": commands,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_apptainer_container_options(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _apptainer_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.apptainer.container_options",
            PreflightGroup.EXECUTOR,
            "Apptainer container adapter option parsing failed",
            exc,
        )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.apptainer.container_options",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Apptainer container adapter options are valid"
            if status is PreflightCheckStatus.PASS
            else "Apptainer container adapter options are invalid"
        ),
        {
            "target_count": len(parsed) + len(diagnostics),
            "targets": [_apptainer_target_summary(target) for target in parsed],
            "diagnostics": list(diagnostics),
        },
    )


def _check_apptainer_image(context: _Context) -> PreflightCheckResult:
    try:
        targets = _apptainer_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.apptainer.image",
            PreflightGroup.EXECUTOR,
            "Apptainer image/SIF reference probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    images: list[PlainData] = []
    for target in targets:
        try:
            image = _apptainer_image_from_adapter(
                target.adapter_options,
                allow_target_resolution=_is_slurm_executor_name(
                    target.selected_executor
                ),
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_image_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        reference = cast(Any, image).reference
        local_path = _local_reference_path(reference, cwd=context.request.cwd)
        images.append(
            {
                "stage_id": target.stage_id,
                "image": reference,
                "local_path": None if local_path is None else str(local_path),
                "local_path_probe": local_path is not None,
                "exists": None if local_path is None else local_path.exists(),
            }
        )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.apptainer.image",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Apptainer image/SIF references are present"
            if status is PreflightCheckStatus.PASS
            else "Apptainer image/SIF reference checks failed"
        ),
        {
            "target_count": len(targets),
            "images": images,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_apptainer_environment(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _apptainer_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.apptainer.environment",
            PreflightGroup.EXECUTOR,
            "Apptainer environment readiness probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "executor.apptainer.environment",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Apptainer environment checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    missing: list[PlainData] = []
    required: list[PlainData] = []
    explicit_names: list[PlainData] = []
    cleanenv: list[PlainData] = []
    for target in parsed:
        environment = cast(Any, target.container).environment
        target_required = list(cast(Any, environment).required_host_variables)
        target_explicit = list(cast(Any, environment).variables)
        required.append({"stage_id": target.stage_id, "names": target_required})
        explicit_names.append({"stage_id": target.stage_id, "names": target_explicit})
        cleanenv.append(
            {
                "stage_id": target.stage_id,
                "cleanenv": bool(getattr(target.apptainer_options, "cleanenv")),
                "command": str(getattr(target.apptainer_options, "command")),
            }
        )
        for name in target_required:
            if name not in os.environ:
                missing.append({"stage_id": target.stage_id, "name": name})

    status = PreflightCheckStatus.FAIL if missing else PreflightCheckStatus.PASS
    return _result(
        "executor.apptainer.environment",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Apptainer required host environment variables are available"
            if status is PreflightCheckStatus.PASS
            else "Apptainer required host environment variables are missing"
        ),
        {
            "required_host_variables": required,
            "explicit_variable_names": explicit_names,
            "clean_environment": cleanenv,
            "missing_required_host_variables": missing,
            "value_redaction": "values_not_reported",
        },
    )


def _check_docker_executor(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_docker(context):
        return ()
    return (
        _check_docker_command(context),
        _check_docker_container_options(context),
        _check_docker_image(context),
        _check_docker_environment(context),
    )


def _check_docker_command(context: _Context) -> PreflightCheckResult:
    try:
        targets = _docker_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.docker.command",
            PreflightGroup.EXECUTOR,
            "Docker command availability probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    commands: list[PlainData] = []
    for target in targets:
        try:
            docker_options = _docker_options_from_adapter(target.adapter_options)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        command = cast(Any, docker_options).command
        resolved = shutil.which(command)
        commands.append(
            {
                "stage_id": target.stage_id,
                "command": command,
                "available": resolved is not None,
                "path": resolved,
            }
        )
        if resolved is None:
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_command_unavailable",
                    message=f"Docker command is not available on PATH: {command}",
                    detail={"command": command},
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.docker.command",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Docker command is available"
            if status is PreflightCheckStatus.PASS
            else "Docker command availability checks failed"
        ),
        {
            "target_count": len(targets),
            "commands": commands,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_docker_container_options(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _docker_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.docker.container_options",
            PreflightGroup.EXECUTOR,
            "Docker adapter option parsing failed",
            exc,
        )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.docker.container_options",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Docker container adapter options are valid"
            if status is PreflightCheckStatus.PASS
            else "Docker container adapter options are invalid"
        ),
        {
            "target_count": len(parsed) + len(diagnostics),
            "targets": [_docker_target_summary(target) for target in parsed],
            "diagnostics": list(diagnostics),
        },
    )


def _check_docker_image(context: _Context) -> PreflightCheckResult:
    try:
        targets = _docker_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.docker.image",
            PreflightGroup.EXECUTOR,
            "Docker image reference probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    images: list[PlainData] = []
    for target in targets:
        try:
            image = _docker_image_from_adapter(target.adapter_options)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_image_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        reference = cast(Any, image).reference
        images.append({"stage_id": target.stage_id, "image": reference})

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "executor.docker.image",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Docker image references are present"
            if status is PreflightCheckStatus.PASS
            else "Docker image reference checks failed"
        ),
        {
            "target_count": len(targets),
            "images": images,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_docker_environment(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _docker_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.docker.environment",
            PreflightGroup.EXECUTOR,
            "Docker environment readiness probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "executor.docker.environment",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Docker environment checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    missing: list[PlainData] = []
    required: list[PlainData] = []
    explicit_names: list[PlainData] = []
    for target in parsed:
        environment = cast(Any, target.container).environment
        target_required = list(cast(Any, environment).required_host_variables)
        target_explicit = list(cast(Any, environment).variables)
        required.append({"stage_id": target.stage_id, "names": target_required})
        explicit_names.append({"stage_id": target.stage_id, "names": target_explicit})
        for name in target_required:
            if name not in os.environ:
                missing.append({"stage_id": target.stage_id, "name": name})

    status = PreflightCheckStatus.FAIL if missing else PreflightCheckStatus.PASS
    return _result(
        "executor.docker.environment",
        PreflightGroup.EXECUTOR,
        status,
        _severity_for_status(status),
        (
            "Docker required host environment variables are available"
            if status is PreflightCheckStatus.PASS
            else "Docker required host environment variables are missing"
        ),
        {
            "required_host_variables": required,
            "explicit_variable_names": explicit_names,
            "missing_required_host_variables": missing,
            "value_redaction": "values_not_reported",
        },
    )


def _check_subprocess_executor(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
        result = context.capability_validation()
    except Exception:  # noqa: BLE001 - runtime/resolve checks already report this.
        return ()

    if (options.executor or "local") != "subprocess":
        return ()

    if _unknown_executor_diagnostic(result) is not None:
        return (
            _skip(
                "executor.subprocess.python",
                PreflightGroup.EXECUTOR,
                "check skipped because the selected executor is unresolved",
                {"reason": "executor_unresolved"},
            ),
            _skip(
                "executor.subprocess.worker",
                PreflightGroup.EXECUTOR,
                "check skipped because the selected executor is unresolved",
                {"reason": "executor_unresolved"},
            ),
        )

    return (_check_subprocess_python(), _check_subprocess_worker())


def _check_subprocess_python() -> PreflightCheckResult:
    executable = sys.executable
    if not executable:
        return _result(
            "executor.subprocess.python",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "subprocess Python executable is unavailable",
            {"python_executable": "", "reason": "missing_sys_executable"},
        )

    resolved = shutil.which(executable)
    if resolved is None:
        return _result(
            "executor.subprocess.python",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "subprocess Python executable is unavailable",
            {"python_executable": executable, "reason": "not_found_or_not_executable"},
        )

    return _result(
        "executor.subprocess.python",
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "subprocess Python executable is available",
        {"python_executable": executable, "resolved_python_executable": resolved},
    )


def _check_subprocess_worker() -> PreflightCheckResult:
    module_name = "loom.cli.main"
    command = "loom stage run"
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception as exc:  # noqa: BLE001 - import resolution failure is a structured diagnostic.
        return _result(
            "executor.subprocess.worker",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "subprocess worker command is unavailable",
            {
                "module": module_name,
                "command": command,
                "reason": "module_resolution_error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )

    if spec is None:
        return _result(
            "executor.subprocess.worker",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "subprocess worker command is unavailable",
            {"module": module_name, "command": command, "reason": "module_not_found"},
        )

    return _result(
        "executor.subprocess.worker",
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "subprocess worker command is available",
        {"module": module_name, "command": command, "origin": spec.origin},
    )


def _check_slurm_executor(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - runtime checks already report this.
        return ()
    if not _is_slurm_executor(options):
        return ()
    dry_run = bool(getattr(options, "dry_run", False))
    checks = [
        _check_slurm_mode(options),
        _check_slurm_launcher(options),
        _check_slurm_sbatch(live_submission=not dry_run),
    ]
    if not dry_run:
        checks.extend(
            (
                _check_optional_slurm_command(
                    check_id="executor.slurm.squeue",
                    command="squeue",
                    purpose="scheduler-aware status for active jobs",
                ),
                _check_optional_slurm_command(
                    check_id="executor.slurm.sacct",
                    command="sacct",
                    purpose="scheduler accounting status for completed jobs",
                ),
                _check_optional_slurm_command(
                    check_id="executor.slurm.scancel",
                    command="scancel",
                    purpose="submitted-job cancellation",
                ),
            )
        )
    return tuple(checks)


def _check_slurm_mode(options: object) -> PreflightCheckResult:
    executor = str(getattr(options, "executor", ""))
    dry_run = bool(getattr(options, "dry_run", False))
    if executor not in _SLURM_EXECUTORS:
        return _result(
            "executor.slurm.mode",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "selected SLURM executor mode is unsupported",
            cast(
                Mapping[str, PlainData],
                {"executor": executor, "supported": sorted(_SLURM_EXECUTORS)},
            ),
        )
    if not dry_run:
        return _result(
            "executor.slurm.mode",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM live executor mode is supported",
            {"executor": executor, "dry_run": False, "live_submission": True},
        )
    return _result(
        "executor.slurm.mode",
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "SLURM dry-run executor mode is supported",
        {
            "executor": executor,
            "dry_run": True,
            "live_submission": True,
        },
    )


def _check_slurm_launcher(options: object) -> PreflightCheckResult:
    try:
        slurm_options = _slurm_options_from_adapter(
            cast(Any, options).adapter_options,
            path="RunOptions.adapter_options['slurm']",
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "executor.slurm.launcher",
            PreflightGroup.EXECUTOR,
            "SLURM launcher argv is invalid",
            exc,
        )
    return _result(
        "executor.slurm.launcher",
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "SLURM launcher argv is valid",
        {
            "launcher_argv": list(slurm_options.launcher_argv),
            "argc": len(slurm_options.launcher_argv),
        },
    )


def _check_slurm_sbatch(*, live_submission: bool) -> PreflightCheckResult:
    resolved = shutil.which("sbatch")
    if resolved is None:
        if live_submission:
            return _result(
                "executor.slurm.sbatch",
                PreflightGroup.EXECUTOR,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "sbatch is required for SLURM live submission",
                {"command": "sbatch", "available": False, "required": True},
            )
        return _result(
            "executor.slurm.sbatch",
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.WARN,
            PreflightSeverity.WARNING,
            "sbatch is not available; SLURM dry-run artifact generation can continue",
            {"command": "sbatch", "available": False},
        )
    return _result(
        "executor.slurm.sbatch",
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "sbatch is available",
        {"command": "sbatch", "available": True, "path": resolved},
    )


def _check_optional_slurm_command(
    *,
    check_id: str,
    command: str,
    purpose: str,
) -> PreflightCheckResult:
    resolved = shutil.which(command)
    if resolved is None:
        return _result(
            check_id,
            PreflightGroup.EXECUTOR,
            PreflightCheckStatus.WARN,
            PreflightSeverity.WARNING,
            f"{command} is not available; {purpose} may be unavailable",
            {
                "command": command,
                "available": False,
                "required": False,
                "purpose": purpose,
            },
        )
    return _result(
        check_id,
        PreflightGroup.EXECUTOR,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        f"{command} is available",
        {"command": command, "available": True, "path": resolved, "purpose": purpose},
    )


def _check_resources(context: _Context) -> tuple[PreflightCheckResult, ...]:
    checks: list[PreflightCheckResult] = []
    try:
        result = context.capability_validation()
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "resources.capabilities",
                PreflightGroup.RESOURCES,
                "resource capability validation failed",
                exc,
            ),
        )

    if _unknown_executor_diagnostic(result) is not None:
        checks.append(
            _skip(
                "resources.capabilities",
                PreflightGroup.RESOURCES,
                "check skipped because the selected executor is unresolved",
                {"reason": "executor_unresolved"},
            )
        )
        return tuple(checks)

    diagnostics = [
        diagnostic
        for diagnostic in cast(Any, result).diagnostics
        if str(diagnostic.code).startswith("resource.")
    ]
    status = _status_from_capability_diagnostics(diagnostics)
    checks.append(
        _result(
            "resources.capabilities",
            PreflightGroup.RESOURCES,
            status,
            _severity_for_status(status),
            _capability_message(
                "resource capability diagnostics",
                diagnostics=diagnostics,
                status=status,
            ),
            _capability_details(diagnostics),
        )
    )
    checks.extend(_check_slurm_resource_mapping(context))
    checks.extend(_check_slurm_container_compatibility(context))
    checks.extend(_check_apptainer_resource_mapping(context))
    checks.extend(_check_docker_resource_mapping(context))
    return tuple(checks)


def _check_slurm_resource_mapping(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - runtime checks already report this.
        return ()
    if not _is_slurm_executor(options):
        return ()
    try:
        from loom.pipeline.executors.slurm.resources import build_sbatch_directives

        run_slurm_options = _slurm_options_from_adapter(
            options.adapter_options,
            path="RunOptions.adapter_options['slurm']",
        )
        mapped: dict[str, int] = {}
        for stage_id, stage_runtime in cast(
            Mapping[str, Any], options.stage_options
        ).items():
            directives = build_sbatch_directives(
                options=_slurm_stage_options(options, stage_id, run_slurm_options),
                resources=stage_runtime.resources,
            )
            mapped[stage_id] = len(directives)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "resources.slurm.mapping",
                PreflightGroup.RESOURCES,
                "SLURM resource mapping failed",
                exc,
            ),
        )

    return (
        _result(
            "resources.slurm.mapping",
            PreflightGroup.RESOURCES,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM resource mapping is valid",
            cast(
                Mapping[str, PlainData],
                {
                    "stage_count": len(mapped),
                    "directive_counts_by_stage": mapped,
                    "supported_resources": ["cpu", "gpu", "memory"],
                },
            ),
        ),
    )


def _check_slurm_container_compatibility(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - runtime checks already report this.
        return ()
    if not _is_slurm_executor(options) or not _request_selects_slurm_container(context):
        return ()

    diagnostics: list[PlainData] = []
    compatibility: list[PlainData] = []
    try:
        targets = _apptainer_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "resources.slurm.container_compatibility",
                PreflightGroup.RESOURCES,
                "SLURM container compatibility probe failed",
                exc,
            ),
        )
    for target in targets:
        resources = _resource_entries(target.resources)
        try:
            apptainer_options = _apptainer_options_from_adapter(
                target.adapter_options,
                executor_name=target.executor_name,
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        gpu_requested = _resource_amount(resources.get("gpu")) > 0
        try:
            gpu_flag = _projected_apptainer_gpu_flag(apptainer_options, resources)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_gpu_projection_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        detail: dict[str, PlainData] = {
            "stage_id": target.stage_id,
            "scheduler_authority": "slurm",
            "container_runtime": target.executor_name,
            "selected_executor": target.selected_executor,
            "resource_kinds": cast(list[PlainData], sorted(resources)),
            "gpu_requested": gpu_requested,
            "gpu_flag": gpu_flag,
            "cpu_memory_owner": "slurm",
            "runtime_device_owner": "apptainer",
        }
        compatibility.append(detail)
        if gpu_requested and gpu_flag is None:
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="slurm_container_gpu_flag_missing",
                    message=(
                        "SLURM GPU allocation is selected but GPU passthrough "
                        "could not be projected"
                    ),
                    detail={"resource_kind": "gpu"},
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return (
        _result(
            "resources.slurm.container_compatibility",
            PreflightGroup.RESOURCES,
            status,
            _severity_for_status(status),
            (
                "SLURM and Apptainer resource ownership is compatible"
                if status is PreflightCheckStatus.PASS
                else "SLURM and Apptainer resource compatibility checks failed"
            ),
            {
                "target_count": len(targets),
                "compatibility": compatibility,
                "diagnostics": diagnostics,
                "expensive_probe": False,
            },
        ),
    )


def _check_apptainer_resource_mapping(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_apptainer(context):
        return ()
    return (
        _check_apptainer_cpu_memory_mapping(context),
        _check_apptainer_gpu_resource(context),
    )


def _check_apptainer_cpu_memory_mapping(context: _Context) -> PreflightCheckResult:
    try:
        targets = _apptainer_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "resources.apptainer.mapping",
            PreflightGroup.RESOURCES,
            "Apptainer resource mapping probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    mapped: list[PlainData] = []
    for target in targets:
        resources = _resource_entries(target.resources)
        for kind, entry in sorted(resources.items()):
            if kind in {"cpu", "memory"}:
                mapped.append(
                    {
                        "stage_id": target.stage_id,
                        "resource_kind": kind,
                        "amount": cast(Any, entry).amount,
                        "unit": cast(Any, entry).unit,
                        "support_level": (
                            "supported"
                            if _is_slurm_executor_name(target.selected_executor)
                            else "advisory"
                        ),
                        "enforcement": (
                            "slurm_enforced"
                            if _is_slurm_executor_name(target.selected_executor)
                            else "external_or_best_effort"
                        ),
                    }
                )
                continue
            if kind == "gpu":
                continue
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_resource_unsupported",
                    message=f"Apptainer resource kind {kind!r} is unsupported",
                    detail={"resource_kind": kind},
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "resources.apptainer.mapping",
        PreflightGroup.RESOURCES,
        status,
        _severity_for_status(status),
        (
            "Apptainer CPU and memory resource mapping is valid"
            if status is PreflightCheckStatus.PASS
            else "Apptainer resource mapping checks failed"
        ),
        {
            "target_count": len(targets),
            "mapped_resources": mapped,
            "diagnostics": diagnostics,
            "supported_resources": ["cpu", "memory", "gpu"],
            "expensive_probe": False,
        },
    )


def _check_apptainer_gpu_resource(context: _Context) -> PreflightCheckResult:
    try:
        targets = _apptainer_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "resources.apptainer.gpu",
            PreflightGroup.RESOURCES,
            "Apptainer GPU resource probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    gpu_targets: list[PlainData] = []
    for target in targets:
        resources = _resource_entries(target.resources)
        gpu = resources.get("gpu")
        if _resource_amount(gpu) <= 0:
            continue
        try:
            apptainer_options = _apptainer_options_from_adapter(
                target.adapter_options,
                executor_name=target.executor_name,
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        try:
            gpu_flag = _projected_apptainer_gpu_flag(apptainer_options, resources)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_gpu_projection_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        gpu_targets.append(
            {
                "stage_id": target.stage_id,
                "amount": _resource_amount(gpu),
                "unit": getattr(gpu, "unit", None),
                "gpu_flag": gpu_flag,
            }
        )
        if gpu_flag is None:
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_gpu_flag_missing",
                    message=(
                        "GPU resources are requested but Apptainer NVIDIA "
                        "passthrough could not be projected"
                    ),
                    detail={"resource_kind": "gpu"},
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "resources.apptainer.gpu",
        PreflightGroup.RESOURCES,
        status,
        _severity_for_status(status),
        (
            "Apptainer GPU resources are either not requested or project runtime flags"
            if status is PreflightCheckStatus.PASS
            else "Apptainer GPU resource mapping checks failed"
        ),
        {
            "target_count": len(targets),
            "gpu_targets": gpu_targets,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_docker_resource_mapping(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_docker(context):
        return ()
    return (
        _check_docker_cpu_memory_mapping(context),
        _check_docker_gpu_resource(context),
    )


def _check_docker_cpu_memory_mapping(context: _Context) -> PreflightCheckResult:
    try:
        targets = _docker_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "resources.docker.mapping",
            PreflightGroup.RESOURCES,
            "Docker resource mapping probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    mapped: list[PlainData] = []
    for target in targets:
        resources = _resource_entries(target.resources)
        for kind, entry in sorted(resources.items()):
            capability = _docker_resource_capability(kind)
            support_level = cast(Any, capability).support_level.value
            enforcement = cast(Any, capability).enforcement.value
            if kind in {"cpu", "memory"}:
                mapped.append(
                    {
                        "stage_id": target.stage_id,
                        "resource_kind": kind,
                        "amount": cast(Any, entry).amount,
                        "unit": cast(Any, entry).unit,
                        "support_level": support_level,
                        "enforcement": enforcement,
                    }
                )
                continue
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_resource_unsupported",
                    message=f"Docker resource kind {kind!r} is unsupported",
                    detail={
                        "resource_kind": kind,
                        "support_level": support_level,
                        "enforcement": enforcement,
                    },
                )
            )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "resources.docker.mapping",
        PreflightGroup.RESOURCES,
        status,
        _severity_for_status(status),
        (
            "Docker CPU and memory resource mapping is valid"
            if status is PreflightCheckStatus.PASS
            else "Docker resource mapping checks failed"
        ),
        {
            "target_count": len(targets),
            "mapped_resources": mapped,
            "diagnostics": diagnostics,
            "supported_resources": ["cpu", "memory"],
            "expensive_probe": False,
        },
    )


def _check_docker_gpu_resource(context: _Context) -> PreflightCheckResult:
    try:
        targets = _docker_raw_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "resources.docker.gpu",
            PreflightGroup.RESOURCES,
            "Docker GPU resource probe failed",
            exc,
        )

    diagnostics: list[PlainData] = []
    for target in targets:
        resources = _resource_entries(target.resources)
        if "gpu" not in resources:
            continue
        capability = _docker_resource_capability("gpu")
        diagnostics.append(
            _docker_diagnostic(
                target.stage_id,
                code="docker_gpu_unsupported",
                message="Docker GPU resource mapping is unsupported in Stage 17",
                detail={
                    "resource_kind": "gpu",
                    "amount": cast(Any, resources["gpu"]).amount,
                    "unit": cast(Any, resources["gpu"]).unit,
                    "support_level": cast(Any, capability).support_level.value,
                    "enforcement": cast(Any, capability).enforcement.value,
                },
            )
        )

    status = PreflightCheckStatus.FAIL if diagnostics else PreflightCheckStatus.PASS
    return _result(
        "resources.docker.gpu",
        PreflightGroup.RESOURCES,
        status,
        _severity_for_status(status),
        (
            "Docker GPU resources are not requested"
            if status is PreflightCheckStatus.PASS
            else "Docker GPU resource mapping is unsupported"
        ),
        {
            "target_count": len(targets),
            "diagnostics": diagnostics,
            "supported": False,
            "expensive_probe": False,
        },
    )


def _check_filesystem(context: _Context) -> tuple[PreflightCheckResult, ...]:
    paths = (
        _resolve_path(context.request.config_path, cwd=context.request.cwd),
        *(
            _resolve_path(path, cwd=context.request.cwd)
            for path in context.request.overlays
        ),
    )
    missing = [str(path) for path in paths if not path.exists()]
    non_files = [str(path) for path in paths if path.exists() and not path.is_file()]
    results: list[PreflightCheckResult] = []
    if missing or non_files:
        results.append(
            _result(
                "filesystem.input_exists",
                PreflightGroup.FILESYSTEM,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "one or more input files are unavailable",
                cast(
                    Mapping[str, PlainData],
                    {"missing": missing, "non_files": non_files},
                ),
            )
        )
    else:
        results.append(
            _result(
                "filesystem.input_exists",
                PreflightGroup.FILESYSTEM,
                PreflightCheckStatus.PASS,
                PreflightSeverity.INFO,
                "configured input files exist",
                cast(Mapping[str, PlainData], {"paths": [str(path) for path in paths]}),
            )
        )
    results.extend(_check_container_build_filesystem(context))
    results.extend(_check_slurm_generated_paths(context))
    results.extend(_check_slurm_generated_paths_writable(context))
    results.extend(_check_apptainer_filesystem(context))
    results.extend(_check_docker_filesystem(context))
    return tuple(results)


def _check_container_build_filesystem(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    try:
        targets, diagnostics = _container_build_targets(context)
    except Exception:  # noqa: BLE001 - runtime checks report normalization failures.
        return ()
    if not targets and not diagnostics:
        return ()
    return (
        _check_container_build_sources(context, targets, diagnostics),
        _check_container_build_outputs(context, targets, diagnostics),
    )


def _check_container_build_sources(
    context: _Context,
    targets: tuple[_ContainerBuildPreflightTarget, ...],
    option_diagnostics: tuple[PlainData, ...],
) -> PreflightCheckResult:
    source_checks: list[PlainData] = []
    missing: list[PlainData] = []
    diagnostics: list[PlainData] = list(option_diagnostics)
    for item in targets:
        source = getattr(item.target, "source", None)
        for label, raw_path in _container_build_local_source_paths(source):
            path = _resolve_path(raw_path, cwd=context.request.cwd)
            detail = {
                "owner_id": item.owner_id,
                "target_name": item.name,
                "source_field": label,
                "path": str(path),
                "exists": path.exists(),
                "expensive_probe": False,
            }
            source_checks.append(detail)
            if not path.exists():
                missing.append(detail)
        if not _container_build_local_source_paths(source):
            source_checks.append(
                {
                    "owner_id": item.owner_id,
                    "target_name": item.name,
                    "source_kind": _enum_value(getattr(source, "kind", None)),
                    "local_path_probe": False,
                    "expensive_probe": False,
                }
            )

    status = (
        PreflightCheckStatus.FAIL
        if diagnostics or missing
        else PreflightCheckStatus.PASS
    )
    return _result(
        "filesystem.container_build.sources",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "container build local sources are available"
            if status is PreflightCheckStatus.PASS
            else "container build source checks failed"
        ),
        {
            "target_count": len(targets),
            "sources": source_checks,
            "missing": missing,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_container_build_outputs(
    context: _Context,
    targets: tuple[_ContainerBuildPreflightTarget, ...],
    option_diagnostics: tuple[PlainData, ...],
) -> PreflightCheckResult:
    output_checks: list[PlainData] = []
    missing_required: list[PlainData] = []
    diagnostics: list[PlainData] = list(option_diagnostics)
    for item in targets:
        target = item.target
        output = getattr(target, "output", None)
        policy = getattr(getattr(target, "policy", None), "mode", None)
        policy_mode = _enum_value(policy)
        path_text = getattr(output, "path", None)
        reference = getattr(output, "reference", None)
        if isinstance(path_text, str):
            path = _resolve_path(path_text, cwd=context.request.cwd)
            exists = path.exists()
            detail = {
                "owner_id": item.owner_id,
                "target_name": item.name,
                "kind": _enum_value(getattr(output, "kind", None)),
                "path": str(path),
                "exists": exists,
                "policy": policy_mode,
                "local_path_probe": True,
                "expensive_probe": False,
            }
            output_checks.append(detail)
            if policy_mode == "never" and not exists:
                missing_required.append(detail)
        else:
            output_checks.append(
                {
                    "owner_id": item.owner_id,
                    "target_name": item.name,
                    "kind": _enum_value(getattr(output, "kind", None)),
                    "reference": reference,
                    "policy": policy_mode,
                    "local_path_probe": False,
                    "expensive_probe": False,
                }
            )

    status = (
        PreflightCheckStatus.FAIL
        if diagnostics or missing_required
        else PreflightCheckStatus.PASS
    )
    return _result(
        "filesystem.container_build.outputs",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "container build output references are ready for the selected policies"
            if status is PreflightCheckStatus.PASS
            else "container build output checks failed"
        ),
        {
            "target_count": len(targets),
            "outputs": output_checks,
            "missing_required_outputs": missing_required,
            "diagnostics": diagnostics,
            "expensive_probe": False,
        },
    )


def _check_apptainer_filesystem(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_apptainer(context):
        return ()
    return (
        _check_apptainer_bind_sources(context),
        _check_apptainer_bind_targets(context),
        _check_apptainer_run_dir_writable(context),
        _check_apptainer_artifact_root_visible(context),
    )


def _check_apptainer_bind_sources(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _apptainer_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.bind_sources",
            PreflightGroup.FILESYSTEM,
            "Apptainer bind source probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "filesystem.apptainer.bind_sources",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Apptainer bind source checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    bind_sources: list[PlainData] = []
    missing: list[PlainData] = []
    for target in parsed:
        for mount in cast(tuple[Any, ...], cast(Any, target.container).mounts):
            source = Path(mount.source)
            exists = source.exists()
            detail = {
                "stage_id": target.stage_id,
                "source": mount.source,
                "target": mount.target,
                "exists": exists,
                "is_dir": source.is_dir() if exists else False,
                "is_file": source.is_file() if exists else False,
            }
            bind_sources.append(detail)
            if not exists:
                missing.append(detail)

    status = PreflightCheckStatus.FAIL if missing else PreflightCheckStatus.PASS
    return _result(
        "filesystem.apptainer.bind_sources",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Apptainer bind sources exist"
            if status is PreflightCheckStatus.PASS
            else "Apptainer bind source checks failed"
        ),
        {"target_count": len(parsed), "bind_sources": bind_sources, "missing": missing},
    )


def _check_apptainer_bind_targets(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _apptainer_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.bind_targets",
            PreflightGroup.FILESYSTEM,
            "Apptainer bind target probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "filesystem.apptainer.bind_targets",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Apptainer bind target checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    summaries: list[PlainData] = []
    invalid: list[PlainData] = []
    for target in parsed:
        for summary in cast(Any, target.container).path_parity_summaries():
            detail = {"stage_id": target.stage_id, **summary.to_dict()}
            summaries.append(detail)
            if not summary.ok:
                invalid.append(detail)

    status = PreflightCheckStatus.FAIL if invalid else PreflightCheckStatus.PASS
    return _result(
        "filesystem.apptainer.bind_targets",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Apptainer bind targets satisfy path parity"
            if status is PreflightCheckStatus.PASS
            else "Apptainer bind target path-parity checks failed"
        ),
        {"target_count": len(parsed), "path_parity": summaries, "invalid": invalid},
    )


def _check_apptainer_run_dir_writable(context: _Context) -> PreflightCheckResult:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.run_dir_writable",
            PreflightGroup.FILESYSTEM,
            "Apptainer run-directory writability probe failed",
            exc,
        )
    if run_uri is None:
        return _missing_run_uri(
            "filesystem.apptainer.run_dir_writable", PreflightGroup.FILESYSTEM
        )
    try:
        resolved = cast(Any, context.run_uri())
        probe_parent = _nearest_existing_directory(resolved.path)
        with tempfile.TemporaryDirectory(
            prefix=".loom-preflight-apptainer-",
            dir=probe_parent,
        ) as probe_dir:
            probe_path = Path(probe_dir) / "run-dir-write-probe"
            probe_path.write_text("ok\n", encoding="utf-8")
            probe_path.unlink()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.run_dir_writable",
            PreflightGroup.FILESYSTEM,
            "Apptainer run-directory parent is not writable",
            exc,
        )

    return _result(
        "filesystem.apptainer.run_dir_writable",
        PreflightGroup.FILESYSTEM,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "Apptainer run-directory parent is writable",
        {
            "run_uri": resolved.uri,
            "run_path": str(resolved.path),
            "probe_parent": str(probe_parent),
        },
    )


def _check_apptainer_artifact_root_visible(context: _Context) -> PreflightCheckResult:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.artifact_root_visible",
            PreflightGroup.FILESYSTEM,
            "Apptainer artifact-root visibility probe failed",
            exc,
        )
    if run_uri is None:
        return _missing_run_uri(
            "filesystem.apptainer.artifact_root_visible", PreflightGroup.FILESYSTEM
        )
    try:
        from loom.pipeline.executors.containers import ContainerMountMode
        from loom.pipeline.stores import LocalRunStore

        parsed, diagnostics = _apptainer_parsed_targets(context)
        if diagnostics:
            return _result(
                "filesystem.apptainer.artifact_root_visible",
                PreflightGroup.FILESYSTEM,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "Apptainer artifact-root checks require valid container options",
                {"diagnostics": list(diagnostics)},
            )
        resolved = cast(Any, context.run_uri())
        store = LocalRunStore(resolved.path.parent)
        run_dir = str(store.local_run_dir(resolved.uri))
        artifact_root = store.local_artifact_root(resolved.uri)
        required_paths = (run_dir, str(artifact_root))
        conflicts: list[PlainData] = []
        for target in parsed:
            mounts = cast(tuple[Any, ...], cast(Any, target.container).mounts)
            for required_path in required_paths:
                existing = next(
                    (mount for mount in mounts if mount.target == required_path),
                    None,
                )
                if existing is None:
                    continue
                mode = cast(Any, existing).mode
                if (
                    existing.source != required_path
                    or mode is not ContainerMountMode.READ_WRITE
                ):
                    conflicts.append(
                        {
                            "stage_id": target.stage_id,
                            "path": required_path,
                            "source": existing.source,
                            "target": existing.target,
                            "mode": mode.value,
                        }
                    )
        if artifact_root.exists() and not artifact_root.is_dir():
            conflicts.append(
                {
                    "stage_id": None,
                    "path": str(artifact_root),
                    "reason": "artifact_root_not_directory",
                }
            )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.apptainer.artifact_root_visible",
            PreflightGroup.FILESYSTEM,
            "Apptainer artifact-root visibility probe failed",
            exc,
        )

    status = PreflightCheckStatus.FAIL if conflicts else PreflightCheckStatus.PASS
    return _result(
        "filesystem.apptainer.artifact_root_visible",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Apptainer artifact root is path-parity bindable"
            if status is PreflightCheckStatus.PASS
            else "Apptainer artifact-root path-parity checks failed"
        ),
        {
            "run_uri": resolved.uri,
            "artifact_root": str(artifact_root),
            "artifact_root_exists": artifact_root.exists(),
            "required_binds": [
                {"path": path, "mode": "rw", "source_equals_target": True}
                for path in required_paths
            ],
            "conflicts": conflicts,
        },
    )


def _check_docker_filesystem(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_docker(context):
        return ()
    return (
        _check_docker_mount_sources(context),
        _check_docker_mount_targets(context),
        _check_docker_run_dir_writable(context),
        _check_docker_artifact_root_visible(context),
    )


def _check_docker_mount_sources(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _docker_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.mount_sources",
            PreflightGroup.FILESYSTEM,
            "Docker mount source probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "filesystem.docker.mount_sources",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Docker mount source checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    mount_sources: list[PlainData] = []
    missing: list[PlainData] = []
    for target in parsed:
        for mount in cast(tuple[Any, ...], cast(Any, target.container).mounts):
            source = Path(mount.source)
            exists = source.exists()
            is_dir = source.is_dir() if exists else False
            is_file = source.is_file() if exists else False
            detail = {
                "stage_id": target.stage_id,
                "source": mount.source,
                "target": mount.target,
                "exists": exists,
                "is_dir": is_dir,
                "is_file": is_file,
            }
            mount_sources.append(detail)
            if not exists:
                missing.append(detail)

    status = PreflightCheckStatus.FAIL if missing else PreflightCheckStatus.PASS
    return _result(
        "filesystem.docker.mount_sources",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Docker mount sources exist"
            if status is PreflightCheckStatus.PASS
            else "Docker mount source checks failed"
        ),
        {
            "target_count": len(parsed),
            "mount_sources": mount_sources,
            "missing": missing,
        },
    )


def _check_docker_mount_targets(context: _Context) -> PreflightCheckResult:
    try:
        parsed, diagnostics = _docker_parsed_targets(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.mount_targets",
            PreflightGroup.FILESYSTEM,
            "Docker mount target probe failed",
            exc,
        )
    if diagnostics:
        return _result(
            "filesystem.docker.mount_targets",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.FAIL,
            PreflightSeverity.ERROR,
            "Docker mount target checks require valid container options",
            {"diagnostics": list(diagnostics)},
        )

    summaries: list[PlainData] = []
    invalid: list[PlainData] = []
    for target in parsed:
        for summary in cast(Any, target.container).path_parity_summaries():
            detail = {"stage_id": target.stage_id, **summary.to_dict()}
            summaries.append(detail)
            if not summary.ok:
                invalid.append(detail)

    status = PreflightCheckStatus.FAIL if invalid else PreflightCheckStatus.PASS
    return _result(
        "filesystem.docker.mount_targets",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Docker mount targets satisfy Stage 17 path parity"
            if status is PreflightCheckStatus.PASS
            else "Docker mount target path-parity checks failed"
        ),
        {
            "target_count": len(parsed),
            "path_parity": summaries,
            "invalid": invalid,
        },
    )


def _check_docker_run_dir_writable(context: _Context) -> PreflightCheckResult:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.run_dir_writable",
            PreflightGroup.FILESYSTEM,
            "Docker run-directory writability probe failed",
            exc,
        )
    if run_uri is None:
        return _missing_run_uri(
            "filesystem.docker.run_dir_writable", PreflightGroup.FILESYSTEM
        )
    try:
        resolved = cast(Any, context.run_uri())
        probe_parent = _nearest_existing_directory(resolved.path)
        with tempfile.TemporaryDirectory(
            prefix=".loom-preflight-docker-",
            dir=probe_parent,
        ) as probe_dir:
            probe_path = Path(probe_dir) / "run-dir-write-probe"
            probe_path.write_text("ok\n", encoding="utf-8")
            probe_path.unlink()
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.run_dir_writable",
            PreflightGroup.FILESYSTEM,
            "Docker run-directory parent is not writable",
            exc,
        )

    return _result(
        "filesystem.docker.run_dir_writable",
        PreflightGroup.FILESYSTEM,
        PreflightCheckStatus.PASS,
        PreflightSeverity.INFO,
        "Docker run-directory parent is writable",
        {
            "run_uri": resolved.uri,
            "run_path": str(resolved.path),
            "probe_parent": str(probe_parent),
        },
    )


def _check_docker_artifact_root_visible(context: _Context) -> PreflightCheckResult:
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.artifact_root_visible",
            PreflightGroup.FILESYSTEM,
            "Docker artifact-root visibility probe failed",
            exc,
        )
    if run_uri is None:
        return _missing_run_uri(
            "filesystem.docker.artifact_root_visible", PreflightGroup.FILESYSTEM
        )
    try:
        from loom.pipeline.executors.containers import ContainerMountMode
        from loom.pipeline.stores import LocalRunStore

        parsed, diagnostics = _docker_parsed_targets(context)
        if diagnostics:
            return _result(
                "filesystem.docker.artifact_root_visible",
                PreflightGroup.FILESYSTEM,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "Docker artifact-root checks require valid container options",
                {"diagnostics": list(diagnostics)},
            )
        resolved = cast(Any, context.run_uri())
        store = LocalRunStore(resolved.path.parent)
        run_dir = str(store.local_run_dir(resolved.uri))
        artifact_root = store.local_artifact_root(resolved.uri)
        required_paths = (run_dir, str(artifact_root))
        conflicts: list[PlainData] = []
        for target in parsed:
            mounts = cast(tuple[Any, ...], cast(Any, target.container).mounts)
            for required_path in required_paths:
                existing = next(
                    (mount for mount in mounts if mount.target == required_path),
                    None,
                )
                if existing is None:
                    continue
                mode = cast(Any, existing).mode
                if (
                    existing.source != required_path
                    or mode is not ContainerMountMode.READ_WRITE
                ):
                    conflicts.append(
                        {
                            "stage_id": target.stage_id,
                            "path": required_path,
                            "source": existing.source,
                            "target": existing.target,
                            "mode": mode.value,
                        }
                    )
        if artifact_root.exists() and not artifact_root.is_dir():
            conflicts.append(
                {
                    "stage_id": None,
                    "path": str(artifact_root),
                    "reason": "artifact_root_not_directory",
                }
            )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "filesystem.docker.artifact_root_visible",
            PreflightGroup.FILESYSTEM,
            "Docker artifact-root visibility probe failed",
            exc,
        )

    status = PreflightCheckStatus.FAIL if conflicts else PreflightCheckStatus.PASS
    return _result(
        "filesystem.docker.artifact_root_visible",
        PreflightGroup.FILESYSTEM,
        status,
        _severity_for_status(status),
        (
            "Docker artifact root is path-parity mountable"
            if status is PreflightCheckStatus.PASS
            else "Docker artifact-root path-parity checks failed"
        ),
        {
            "run_uri": resolved.uri,
            "artifact_root": str(artifact_root),
            "artifact_root_exists": artifact_root.exists(),
            "required_mounts": [
                {"path": path, "mode": "rw", "source_equals_target": True}
                for path in required_paths
            ],
            "conflicts": conflicts,
        },
    )


def _check_slurm_generated_paths(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_slurm(context):
        return ()
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "filesystem.slurm.generated_paths",
                PreflightGroup.FILESYSTEM,
                "SLURM generated path probe failed",
                exc,
            ),
        )
    if run_uri is None:
        return (
            _missing_run_uri(
                "filesystem.slurm.generated_paths", PreflightGroup.FILESYSTEM
            ),
        )
    try:
        from loom.pipeline.executors.slurm.paths import (
            resolve_slurm_generated_artifact_path,
            slurm_job_log_relative_path,
            slurm_job_script_relative_path,
            slurm_manifest_relative_path,
            slurm_plan_relative_path,
        )
        from loom.pipeline.stores import LocalRunStore

        resolved = cast(Any, context.run_uri())
        store = LocalRunStore(resolved.path.parent)
        relative_paths = (
            slurm_plan_relative_path("preflight"),
            slurm_manifest_relative_path("preflight"),
            slurm_job_script_relative_path("preflight", "pipeline"),
            slurm_job_log_relative_path("preflight", "pipeline", "stdout"),
            slurm_job_log_relative_path("preflight", "pipeline", "stderr"),
        )
        artifacts = [
            resolve_slurm_generated_artifact_path(store, resolved.uri, relative)
            for relative in relative_paths
        ]
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "filesystem.slurm.generated_paths",
                PreflightGroup.FILESYSTEM,
                "SLURM generated paths are unsafe",
                exc,
            ),
        )
    return (
        _result(
            "filesystem.slurm.generated_paths",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM generated paths resolve under the local run directory",
            cast(
                Mapping[str, PlainData],
                {
                    "run_uri": cast(Any, context.run_uri()).uri,
                    "path_count": len(artifacts),
                    "relative_paths": [
                        artifact.relative_path for artifact in artifacts
                    ],
                },
            ),
        ),
    )


def _check_slurm_generated_paths_writable(
    context: _Context,
) -> tuple[PreflightCheckResult, ...]:
    if not _request_selects_slurm(context):
        return ()
    try:
        run_uri = _selected_run_uri(context)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "filesystem.slurm.generated_writable",
                PreflightGroup.FILESYSTEM,
                "SLURM generated path writability probe failed",
                exc,
            ),
        )
    if run_uri is None:
        return (
            _missing_run_uri(
                "filesystem.slurm.generated_writable", PreflightGroup.FILESYSTEM
            ),
        )
    try:
        resolved = cast(Any, context.run_uri())
        probe_parent = _nearest_existing_directory(resolved.path)
        with tempfile.TemporaryDirectory(
            prefix=".loom-preflight-slurm-",
            dir=probe_parent,
        ) as probe_dir:
            probe_path = Path(probe_dir) / "generated-path-write-probe"
            probe_path.write_text("ok\n", encoding="utf-8")
            probe_path.unlink()
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "filesystem.slurm.generated_writable",
                PreflightGroup.FILESYSTEM,
                "SLURM generated paths are not writable",
                exc,
            ),
        )
    return (
        _result(
            "filesystem.slurm.generated_writable",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "SLURM generated path parent is writable",
            {
                "run_uri": resolved.uri,
                "run_path": str(resolved.path),
                "probe_parent": str(probe_parent),
            },
        ),
    )


def _check_plugins(context: _Context) -> tuple[PreflightCheckResult, ...]:
    from loom.plugins import (
        LOADABLE_PLUGIN_GROUPS,
        PluginSelection,
        check_plugin_records,
        summarize_plugin_records,
    )

    selection = PluginSelection(
        groups=context.request.plugin_groups,
        names=context.request.plugin_names,
        packages=context.request.plugin_packages,
    )
    if selection.is_empty:
        details = {
            "guidance": (
                "Use --plugin-group, --plugin-name, or --plugin-package with "
                "--check plugins to select trusted installed plugins."
            ),
            "reason": "missing_plugin_selector",
        }
        return (
            _result(
                "plugins.metadata",
                PreflightGroup.PLUGINS,
                PreflightCheckStatus.SKIP,
                PreflightSeverity.INFO,
                "plugin diagnostics require an explicit selector",
                details,
            ),
            _result(
                "plugins.load",
                PreflightGroup.PLUGINS,
                PreflightCheckStatus.SKIP,
                PreflightSeverity.INFO,
                "plugin loading skipped because no plugin selector was provided",
                details,
            ),
        )

    try:
        records = _list_plugin_records(groups=selection.groups or None)
    except Exception as exc:  # noqa: BLE001
        return (
            _fail(
                "plugins.metadata",
                PreflightGroup.PLUGINS,
                "plugin metadata discovery failed",
                exc,
            ),
        )

    metadata = summarize_plugin_records(records, selection=selection)
    checked = check_plugin_records(records, selection=selection, load=True)
    metadata_failed = bool(checked.missing or checked.duplicates)
    metadata_check = _result(
        "plugins.metadata",
        PreflightGroup.PLUGINS,
        PreflightCheckStatus.FAIL if metadata_failed else PreflightCheckStatus.PASS,
        PreflightSeverity.ERROR if metadata_failed else PreflightSeverity.INFO,
        (
            "selected plugin metadata has missing or duplicate records"
            if metadata_failed
            else "selected plugin metadata discovered"
        ),
        cast(
            Mapping[str, PlainData],
            {
                **metadata.to_summary(),
                "missing": [missing.to_summary() for missing in checked.missing],
                "duplicates": [
                    duplicate.to_summary() for duplicate in checked.duplicates
                ],
            },
        ),
    )

    selected_loadable = tuple(
        record for record in checked.records if record.group in LOADABLE_PLUGIN_GROUPS
    )
    if not selected_loadable:
        load_check = _result(
            "plugins.load",
            PreflightGroup.PLUGINS,
            PreflightCheckStatus.SKIP,
            PreflightSeverity.INFO,
            "selected plugin groups are listing-only in Stage 14",
            cast(Mapping[str, PlainData], checked.to_summary()),
        )
    else:
        load_failed = bool(checked.duplicates or checked.failures)
        load_check = _result(
            "plugins.load",
            PreflightGroup.PLUGINS,
            PreflightCheckStatus.FAIL if load_failed else PreflightCheckStatus.PASS,
            PreflightSeverity.ERROR if load_failed else PreflightSeverity.INFO,
            (
                "selected plugin loading failed"
                if load_failed
                else "selected registry-ready plugins loaded in scratch registries"
            ),
            cast(Mapping[str, PlainData], checked.to_summary()),
        )

    return (metadata_check, load_check)


def _list_plugin_records(*, groups: Iterable[str] | None) -> tuple["PluginRecord", ...]:
    from loom.plugins import list_entry_points

    if _plugin_entry_point_provider is None:
        return list_entry_points(groups=groups)
    return list_entry_points(groups=groups, provider=_plugin_entry_point_provider)


def _nearest_existing_directory(path: Path) -> Path:
    current = path if path.exists() else path.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    if not current.is_dir():
        raise NotADirectoryError(str(current))
    return current


def _coerce_selectors(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        from loom.pipeline.planning import PlanSelectors

        return PlanSelectors.from_dict(value)
    return value


def _request_selects_apptainer(context: _Context) -> bool:
    try:
        options = cast(Any, context.runtime_options())
        return _is_apptainer_executor(options) or _request_selects_slurm_container(
            context
        )
    except Exception:  # noqa: BLE001 - caller-specific checks report request failures.
        runtime_options = context.request.runtime_options
        executor = None
        adapter_options: object = None
        stage_options: object = None
        if isinstance(runtime_options, Mapping):
            executor = runtime_options.get("executor")
            adapter_options = runtime_options.get("adapter_options")
            stage_options = runtime_options.get("stage_options")
        else:
            executor = getattr(runtime_options, "executor", None)
            adapter_options = getattr(runtime_options, "adapter_options", None)
            stage_options = getattr(runtime_options, "stage_options", None)
        return executor in _APPTAINER_EXECUTORS or (
            executor in _SLURM_EXECUTORS
            and _adapter_options_include_container(adapter_options, stage_options)
        )


def _request_selects_slurm_container(context: _Context) -> bool:
    try:
        options = cast(Any, context.runtime_options())
    except Exception:  # noqa: BLE001 - caller-specific checks report request failures.
        return False
    return _is_slurm_executor(options) and _runtime_options_include_container(options)


def _request_selects_slurm(context: _Context) -> bool:
    try:
        return _is_slurm_executor(cast(Any, context.runtime_options()))
    except Exception:  # noqa: BLE001 - caller-specific checks report request failures.
        runtime_options = context.request.runtime_options
        executor = None
        if isinstance(runtime_options, Mapping):
            executor = runtime_options.get("executor")
        else:
            executor = getattr(runtime_options, "executor", None)
        return executor in _SLURM_EXECUTORS


def _request_selects_docker(context: _Context) -> bool:
    try:
        return _is_docker_executor(cast(Any, context.runtime_options()))
    except Exception:  # noqa: BLE001 - caller-specific checks report request failures.
        runtime_options = context.request.runtime_options
        executor = None
        if isinstance(runtime_options, Mapping):
            executor = runtime_options.get("executor")
        else:
            executor = getattr(runtime_options, "executor", None)
        return executor == "docker"


def _is_apptainer_executor(options: object) -> bool:
    return (getattr(options, "executor", None) or "local") in _APPTAINER_EXECUTORS


def _is_slurm_executor(options: object) -> bool:
    return getattr(options, "executor", None) in _SLURM_EXECUTORS


def _is_slurm_executor_name(executor: object) -> bool:
    return executor in _SLURM_EXECUTORS


def _is_docker_executor(options: object) -> bool:
    return (getattr(options, "executor", None) or "local") == "docker"


def _runtime_options_include_container(options: object) -> bool:
    return _adapter_options_include_container(
        getattr(options, "adapter_options", None),
        getattr(options, "stage_options", None),
    )


def _adapter_options_include_container(
    adapter_options: object,
    stage_options: object,
) -> bool:
    if isinstance(adapter_options, Mapping) and "container" in adapter_options:
        return True
    if isinstance(stage_options, Mapping):
        for value in stage_options.values():
            raw_adapter_options = (
                value.get("adapter_options")
                if isinstance(value, Mapping)
                else getattr(value, "adapter_options", None)
            )
            if (
                isinstance(raw_adapter_options, Mapping)
                and "container" in raw_adapter_options
            ):
                return True
    return False


def _container_build_option_sources(
    context: _Context,
) -> tuple[_ContainerBuildPreflightOptions, ...]:
    options = cast(Any, context.runtime_options())
    sources: list[_ContainerBuildPreflightOptions] = []
    adapter_options = cast(Mapping[str, object], options.adapter_options)
    if "container_build" in adapter_options:
        sources.append(
            _ContainerBuildPreflightOptions(
                owner_id="run",
                adapter_options=adapter_options,
            )
        )
    for stage_id, stage_runtime in cast(
        Mapping[str, Any],
        options.stage_options,
    ).items():
        stage_adapter_options = cast(
            Mapping[str, object], stage_runtime.adapter_options
        )
        if "container_build" in stage_adapter_options:
            sources.append(
                _ContainerBuildPreflightOptions(
                    owner_id=f"stage:{stage_id}",
                    adapter_options=stage_adapter_options,
                )
            )
    return tuple(sources)


def _container_build_targets(
    context: _Context,
) -> tuple[tuple[_ContainerBuildPreflightTarget, ...], tuple[PlainData, ...]]:
    targets: list[_ContainerBuildPreflightTarget] = []
    diagnostics: list[PlainData] = []
    for source in _container_build_option_sources(context):
        try:
            parsed = _container_build_options_from_adapter(source.adapter_options)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _container_build_diagnostic(
                    source.owner_id,
                    code="container_build_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        targets.extend(
            _ContainerBuildPreflightTarget(
                owner_id=source.owner_id,
                name=name,
                target=target,
            )
            for name, target in cast(
                Mapping[str, object],
                cast(Any, parsed).targets,
            ).items()
        )
    return tuple(targets), tuple(diagnostics)


def _container_build_options_from_adapter(
    adapter_options: Mapping[str, object],
) -> object:
    from loom.pipeline.executors.containers import parse_container_build_options

    return parse_container_build_options(adapter_options.get("container_build"))


def _container_build_output_identity(output: object) -> str | None:
    if output is None:
        return None
    try:
        from loom.pipeline.executors.containers import container_build_output_identity

        return container_build_output_identity(cast(Any, output))
    except Exception:  # noqa: BLE001 - identity is best-effort diagnostic metadata.
        return None


def _container_build_local_source_paths(source: object) -> tuple[tuple[str, str], ...]:
    paths: list[tuple[str, str]] = []
    for field_name in ("path", "context_path", "recipe_path"):
        value = getattr(source, field_name, None)
        if isinstance(value, str):
            paths.append((field_name, value))
    return tuple(paths)


def _selected_container_build_targets(
    context: _Context,
) -> tuple[_ApptainerPreflightRawTarget | _DockerPreflightRawTarget, ...]:
    targets: list[_ApptainerPreflightRawTarget | _DockerPreflightRawTarget] = []
    if _request_selects_apptainer(context):
        targets.extend(_apptainer_raw_targets(context))
    if _request_selects_docker(context):
        targets.extend(_docker_raw_targets(context))
    return tuple(
        target
        for target in targets
        if _container_target_name(target.adapter_options) is not None
    )


def _container_target_name(adapter_options: Mapping[str, object]) -> str | None:
    container = adapter_options.get("container")
    if not isinstance(container, Mapping):
        return None
    target = container.get("target")
    return target if isinstance(target, str) and target else None


def _selected_container_executor_name(
    target: _ApptainerPreflightRawTarget | _DockerPreflightRawTarget,
) -> str:
    return (
        target.selected_executor
        if isinstance(target, _ApptainerPreflightRawTarget)
        else "docker"
    )


def _target_owner_id(stage_id: str | None) -> str:
    return "run" if stage_id is None else f"stage:{stage_id}"


def _docker_raw_targets(context: _Context) -> tuple[_DockerPreflightRawTarget, ...]:
    options = cast(Any, context.runtime_options())
    if not _is_docker_executor(options):
        return ()
    stage_ids = _docker_stage_ids(context, options)
    if not stage_ids:
        return (
            _DockerPreflightRawTarget(
                stage_id=None,
                adapter_options=cast(Mapping[str, object], options.adapter_options),
                resources=None,
            ),
        )
    from loom.pipeline.runtime import resolve_run_runtime

    resolved = resolve_run_runtime(options, stage_ids=stage_ids)
    return tuple(
        _DockerPreflightRawTarget(
            stage_id=stage_id,
            adapter_options=cast(
                Mapping[str, object],
                cast(Any, resolved[stage_id]).adapter_options,
            ),
            resources=cast(Any, resolved[stage_id]).resources,
        )
        for stage_id in stage_ids
    )


def _docker_stage_ids(context: _Context, options: object) -> tuple[str, ...]:
    try:
        validation = cast(Any, context.pipeline())
        stage_names = tuple(str(stage_id) for stage_id in validation.spec.stage_names)
        if stage_names:
            return stage_names
    except Exception:  # noqa: BLE001 - Docker option checks can still inspect explicit runtime input.
        pass
    return tuple(str(stage_id) for stage_id in cast(Any, options).stage_options)


def _docker_parsed_targets(
    context: _Context,
) -> tuple[tuple[_DockerPreflightTarget, ...], tuple[PlainData, ...]]:
    parsed: list[_DockerPreflightTarget] = []
    diagnostics: list[PlainData] = []
    for target in _docker_raw_targets(context):
        try:
            container = _docker_container_from_adapter(target.adapter_options)
            docker_options = _docker_options_from_adapter(target.adapter_options)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _docker_diagnostic(
                    target.stage_id,
                    code="docker_container_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        parsed.append(
            _DockerPreflightTarget(
                stage_id=target.stage_id,
                container=container,
                docker_options=docker_options,
                resources=target.resources,
            )
        )
    return tuple(parsed), tuple(diagnostics)


def _apptainer_raw_targets(
    context: _Context,
) -> tuple[_ApptainerPreflightRawTarget, ...]:
    options = cast(Any, context.runtime_options())
    if not (
        _is_apptainer_executor(options) or _request_selects_slurm_container(context)
    ):
        return ()
    stage_ids = _apptainer_stage_ids(context, options)
    executor_name = _apptainer_executor_name_for_options(options)
    selected_executor = str(getattr(options, "executor", None) or "apptainer")
    if not stage_ids:
        adapter_options = cast(Mapping[str, object], options.adapter_options)
        return (
            _ApptainerPreflightRawTarget(
                stage_id=None,
                adapter_options=adapter_options,
                resources=None,
                executor_name=_apptainer_executor_name_for_adapter(
                    adapter_options,
                    fallback=executor_name,
                ),
                selected_executor=selected_executor,
            ),
        )
    from loom.pipeline.runtime import resolve_run_runtime

    resolved = resolve_run_runtime(options, stage_ids=stage_ids)
    return tuple(
        _ApptainerPreflightRawTarget(
            stage_id=stage_id,
            adapter_options=cast(
                Mapping[str, object],
                cast(Any, resolved[stage_id]).adapter_options,
            ),
            resources=cast(Any, resolved[stage_id]).resources,
            executor_name=_apptainer_executor_name_for_adapter(
                cast(
                    Mapping[str, object], cast(Any, resolved[stage_id]).adapter_options
                ),
                fallback=executor_name,
            ),
            selected_executor=selected_executor,
        )
        for stage_id in stage_ids
        if _is_apptainer_executor(options)
        or "container" in cast(Any, resolved[stage_id]).adapter_options
    )


def _apptainer_stage_ids(context: _Context, options: object) -> tuple[str, ...]:
    try:
        validation = cast(Any, context.pipeline())
        stage_names = tuple(str(stage_id) for stage_id in validation.spec.stage_names)
        if stage_names:
            return stage_names
    except Exception:  # noqa: BLE001 - checks can still inspect explicit runtime input.
        pass
    return tuple(str(stage_id) for stage_id in cast(Any, options).stage_options)


def _apptainer_parsed_targets(
    context: _Context,
) -> tuple[tuple[_ApptainerPreflightTarget, ...], tuple[PlainData, ...]]:
    parsed: list[_ApptainerPreflightTarget] = []
    diagnostics: list[PlainData] = []
    for target in _apptainer_raw_targets(context):
        try:
            container = _apptainer_container_from_adapter(
                target.adapter_options,
                allow_target_resolution=_is_slurm_executor_name(
                    target.selected_executor
                ),
            )
            apptainer_options = _apptainer_options_from_adapter(
                target.adapter_options,
                executor_name=target.executor_name,
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                _apptainer_diagnostic(
                    target.stage_id,
                    code="apptainer_container_options_invalid",
                    message=str(exc) or type(exc).__name__,
                )
            )
            continue
        parsed.append(
            _ApptainerPreflightTarget(
                stage_id=target.stage_id,
                container=container,
                apptainer_options=apptainer_options,
                resources=target.resources,
                executor_name=target.executor_name,
                selected_executor=target.selected_executor,
            )
        )
    return tuple(parsed), tuple(diagnostics)


def _apptainer_container_from_adapter(
    adapter_options: Mapping[str, object],
    *,
    allow_target_resolution: bool,
) -> object:
    from loom.pipeline.executors.containers import parse_container_options

    if "container" not in adapter_options:
        raise ValueError(
            "adapter_options.container is required for Apptainer preflight"
        )
    raw = adapter_options["container"]
    if (
        allow_target_resolution
        and isinstance(raw, Mapping)
        and "target" in raw
        and "image" not in raw
    ):
        raw = _resolve_apptainer_preflight_target(adapter_options, raw)
    return parse_container_options(raw)


def _resolve_apptainer_preflight_target(
    adapter_options: Mapping[str, object],
    container: Mapping[str, object],
) -> Mapping[str, object]:
    from loom.pipeline.executors.containers import (
        ContainerBuildOutputKind,
        ContainerBuildRuntime,
    )

    target_name = container.get("target")
    if not isinstance(target_name, str) or not target_name:
        raise ValueError("adapter_options.container.target must be non-empty")
    build_options = _container_build_options_from_adapter(adapter_options)
    target = cast(Mapping[str, object], cast(Any, build_options).targets).get(
        target_name
    )
    if target is None:
        raise ValueError(f"container build target {target_name!r} is not defined")
    runtime = getattr(target, "runtime", None)
    output = getattr(target, "output", None)
    output_kind = getattr(output, "kind", None)
    if runtime is not ContainerBuildRuntime.APPTAINER:
        raise ValueError("Apptainer execution requires an apptainer build target")
    if output_kind is not ContainerBuildOutputKind.APPTAINER_SIF:
        raise ValueError("Apptainer execution requires an apptainer_sif output")
    identity = _container_build_output_identity(output)
    if identity is None:
        raise ValueError("Apptainer build target output has no image identity")
    resolved = dict(container)
    resolved.pop("target", None)
    resolved["image"] = {"reference": identity}
    return cast(Mapping[str, object], resolved)


def _apptainer_options_from_adapter(
    adapter_options: Mapping[str, object],
    *,
    executor_name: str,
) -> object:
    from loom.pipeline.executors.apptainer import ApptainerExecOptions

    raw_options: object | None
    if executor_name == "singularity":
        raw_options = adapter_options.get(
            "singularity",
            adapter_options.get("apptainer"),
        )
    else:
        raw_options = adapter_options.get("apptainer")
    options = ApptainerExecOptions.from_dict(raw_options)
    if executor_name == "singularity" and not _adapter_options_set_command(raw_options):
        return replace(options, command="singularity")
    return options


def _adapter_options_set_command(raw_options: object | None) -> bool:
    return isinstance(raw_options, Mapping) and "command" in raw_options


def _apptainer_executor_name_for_options(options: object) -> str:
    executor = getattr(options, "executor", None)
    if executor in _APPTAINER_EXECUTORS:
        return cast(str, executor)
    return "apptainer"


def _apptainer_executor_name_for_adapter(
    adapter_options: Mapping[str, object],
    *,
    fallback: str,
) -> str:
    if "singularity" in adapter_options:
        return "singularity"
    return fallback if fallback in _APPTAINER_EXECUTORS else "apptainer"


def _apptainer_image_from_adapter(
    adapter_options: Mapping[str, object],
    *,
    allow_target_resolution: bool,
) -> object:
    from loom.pipeline.executors.containers import ContainerImageReference

    if "container" not in adapter_options:
        raise ValueError(
            "adapter_options.container is required for Apptainer preflight"
        )
    raw = adapter_options["container"]
    if (
        allow_target_resolution
        and isinstance(raw, Mapping)
        and "target" in raw
        and "image" not in raw
    ):
        raw = _resolve_apptainer_preflight_target(adapter_options, raw)
    if not isinstance(raw, Mapping):
        raise TypeError("adapter_options.container must be a mapping")
    if "image" not in raw:
        raise ValueError("adapter_options.container.image is required")
    image = raw["image"]
    return (
        ContainerImageReference(reference=image)
        if isinstance(image, str)
        else ContainerImageReference.from_dict(image)
    )


def _apptainer_target_summary(target: _ApptainerPreflightTarget) -> PlainData:
    apptainer_options = cast(Any, target.apptainer_options).to_dict()
    return {
        "stage_id": target.stage_id,
        "executor_name": target.executor_name,
        "selected_executor": target.selected_executor,
        "container": cast(Any, target.container).to_redacted_metadata(),
        "apptainer_option_keys": [
            key for key, value in sorted(apptainer_options.items()) if value is not None
        ],
    }


def _apptainer_diagnostic(
    stage_id: str | None,
    *,
    code: str,
    message: str,
    detail: Mapping[str, PlainData] | None = None,
) -> PlainData:
    payload: dict[str, PlainData] = {
        "stage_id": stage_id,
        "code": code,
        "message": message,
    }
    if detail:
        payload["detail"] = dict(detail)
    return payload


def _container_build_diagnostic(
    owner_id: str,
    *,
    code: str,
    message: str,
    detail: Mapping[str, PlainData] | None = None,
) -> PlainData:
    payload: dict[str, PlainData] = {
        "owner_id": owner_id,
        "code": code,
        "message": message,
    }
    if detail:
        payload["detail"] = dict(detail)
    return payload


def _apptainer_command_required(options: object) -> bool:
    if _is_apptainer_executor(options):
        return True
    if _is_slurm_executor(options):
        return not bool(getattr(options, "dry_run", False))
    return False


def _apptainer_gpu_flag(apptainer_options: object) -> str | None:
    if bool(getattr(apptainer_options, "nv", False)):
        return "nv"
    if bool(getattr(apptainer_options, "rocm", False)):
        return "rocm"
    return None


def _projected_apptainer_gpu_flag(
    apptainer_options: object,
    resources: object | None,
) -> str | None:
    """Report the same resource-derived GPU option used at execution time."""

    from loom.pipeline.executors.apptainer import ApptainerExecOptions
    from loom.pipeline.executors.gpu_visibility import project_apptainer_gpu_options

    if not isinstance(apptainer_options, ApptainerExecOptions):
        raise TypeError("Apptainer options are not normalized")
    return _apptainer_gpu_flag(
        project_apptainer_gpu_options(apptainer_options, cast(Any, resources))
    )


def _resource_amount(resource: object | None) -> float:
    if resource is None:
        return 0.0
    amount = getattr(resource, "amount", 0)
    if isinstance(amount, int | float) and not isinstance(amount, bool):
        return float(amount)
    return 0.0


def _local_reference_path(reference: str, *, cwd: str | Path | None) -> Path | None:
    if "://" in reference or reference.startswith(("docker:", "oras:", "library:")):
        return None
    if not (
        reference.startswith(("/", "."))
        or "/" in reference
        or reference.endswith((".sif", ".simg"))
    ):
        return None
    return _resolve_path(reference, cwd=cwd)


def _docker_container_from_adapter(adapter_options: Mapping[str, object]) -> object:
    from loom.pipeline.executors.containers import parse_container_options

    if "container" not in adapter_options:
        raise ValueError("adapter_options.container is required for Docker preflight")
    return parse_container_options(adapter_options["container"])


def _docker_options_from_adapter(adapter_options: Mapping[str, object]) -> object:
    from loom.pipeline.executors.docker.commands import DockerOptions

    return DockerOptions.from_dict(adapter_options.get("docker"))


def _docker_image_from_adapter(adapter_options: Mapping[str, object]) -> object:
    from loom.pipeline.executors.containers import ContainerImageReference

    if "container" not in adapter_options:
        raise ValueError("adapter_options.container is required for Docker preflight")
    raw = adapter_options["container"]
    if not isinstance(raw, Mapping):
        raise TypeError("adapter_options.container must be a mapping")
    if "image" not in raw:
        raise ValueError("adapter_options.container.image is required")
    image = raw["image"]
    return (
        ContainerImageReference(reference=image)
        if isinstance(image, str)
        else ContainerImageReference.from_dict(image)
    )


def _docker_target_summary(target: _DockerPreflightTarget) -> PlainData:
    docker_options = cast(Any, target.docker_options).to_dict()
    return {
        "stage_id": target.stage_id,
        "container": cast(Any, target.container).to_redacted_metadata(),
        "docker_option_keys": [
            key for key, value in sorted(docker_options.items()) if value is not None
        ],
    }


def _docker_diagnostic(
    stage_id: str | None,
    *,
    code: str,
    message: str,
    detail: Mapping[str, PlainData] | None = None,
) -> PlainData:
    payload: dict[str, PlainData] = {
        "stage_id": stage_id,
        "code": code,
        "message": message,
    }
    if detail:
        payload["detail"] = dict(detail)
    return payload


def _resource_entries(resources: object | None) -> Mapping[str, object]:
    if resources is None:
        return {}
    entries = getattr(resources, "entries", None)
    if isinstance(entries, Mapping):
        return cast(Mapping[str, object], entries)
    return {}


def _docker_resource_capability(kind: str) -> object:
    from loom.pipeline.runtime.capabilities import DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY

    descriptor = DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY.resolve("docker")
    return descriptor.capability_for(kind)


def _slurm_options_from_adapter(
    adapter_options: Mapping[str, object],
    *,
    path: str,
) -> "SlurmOptions":
    from loom.pipeline.executors.slurm.options import SlurmOptions

    raw = adapter_options.get("slurm", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise TypeError(f"{path} must be a mapping")
    if not raw:
        return SlurmOptions()
    try:
        return SlurmOptions.from_dict(raw)
    except Exception as exc:  # noqa: BLE001
        raise type(exc)(f"{path}: {exc}") from exc


def _slurm_stage_options(
    options: object,
    stage_id: str,
    fallback: "SlurmOptions",
) -> "SlurmOptions":
    stage_runtime = cast(Mapping[str, Any], getattr(options, "stage_options"))[stage_id]
    if "slurm" not in stage_runtime.adapter_options:
        return fallback
    raw = stage_runtime.adapter_options.get("slurm", {})
    if not isinstance(raw, Mapping):
        raise TypeError(
            f"RunOptions.stage_options[{stage_id!r}].adapter_options['slurm'] "
            "must be a mapping"
        )
    merged = dict(fallback.to_dict())
    merged.update(raw)
    try:
        from loom.pipeline.executors.slurm.options import SlurmOptions

        return SlurmOptions.from_dict(merged)
    except Exception as exc:  # noqa: BLE001
        raise type(exc)(
            f"RunOptions.stage_options[{stage_id!r}].adapter_options['slurm']: {exc}"
        ) from exc


def _slurm_option_keys(options: object) -> list[str]:
    data = cast(Any, options).to_dict()
    return [
        key
        for key, value in sorted(data.items())
        if key != "schema_version" and value not in (None, [], {})
    ]


def _selected_run_uri(context: _Context) -> str | None:
    explicit_run_uri = _explicit_runtime_run_uri(context.request.runtime_options)
    if explicit_run_uri is not None:
        return explicit_run_uri
    if context.request.run_uri is not None:
        return context.request.run_uri
    if context._runtime_options is not None:
        options = cast(Any, context.runtime_options())
        if options.run_uri is not None:
            return cast(str, options.run_uri)
    return None


def _explicit_runtime_run_uri(runtime_options: object | None) -> str | None:
    if isinstance(runtime_options, Mapping):
        value = runtime_options.get("run_uri")
        if value is None:
            return None
        return cast(str, value)
    value = getattr(runtime_options, "run_uri", None)
    if value is None:
        return None
    return cast(str, value)


def _request_resume_enabled(context: _Context) -> bool:
    runtime_options = context.request.runtime_options
    if isinstance(runtime_options, Mapping):
        resume = runtime_options.get("resume")
        if isinstance(resume, Mapping):
            return bool(resume.get("enabled", False))
        return bool(resume)
    resume = getattr(runtime_options, "resume", None)
    if resume is None:
        return False
    return bool(getattr(resume, "enabled", resume))


def _request_runtime_source(request: PreflightRequest) -> object | None:
    if request.runtime_options is not None and not isinstance(
        request.runtime_options, Mapping
    ):
        return request.runtime_options
    source = dict(cast(Mapping[str, object], request.runtime_options or {}))
    if request.run_uri is not None and "run_uri" not in source:
        source["run_uri"] = request.run_uri
    if request.selectors is not None and "selectors" not in source:
        source["selectors"] = request.selectors
    return source or None


def _unknown_executor_diagnostic(result: object) -> object | None:
    for diagnostic in cast(Any, result).diagnostics:
        if diagnostic.code == "executor.unknown":
            return diagnostic
    return None


def _status_from_capability_diagnostics(
    diagnostics: list[object],
) -> PreflightCheckStatus:
    severities = {
        str(getattr(diagnostic, "severity").value) for diagnostic in diagnostics
    }
    if "error" in severities:
        return PreflightCheckStatus.FAIL
    if "warning" in severities:
        return PreflightCheckStatus.WARN
    return PreflightCheckStatus.PASS


def _severity_for_status(status: PreflightCheckStatus) -> PreflightSeverity:
    if status is PreflightCheckStatus.FAIL:
        return PreflightSeverity.ERROR
    if status is PreflightCheckStatus.WARN:
        return PreflightSeverity.WARNING
    return PreflightSeverity.INFO


def _capability_message(
    label: str,
    *,
    diagnostics: list[object],
    status: PreflightCheckStatus,
) -> str:
    if not diagnostics:
        return f"{label} passed"
    if status is PreflightCheckStatus.FAIL:
        return f"{label} failed"
    if status is PreflightCheckStatus.WARN:
        return f"{label} reported warnings"
    return f"{label} passed with informational diagnostics"


def _capability_details(diagnostics: list[object]) -> Mapping[str, PlainData]:
    return cast(
        Mapping[str, PlainData],
        {
            "diagnostic_count": len(diagnostics),
            "diagnostics": [
                cast(Any, diagnostic).to_dict()
                for diagnostic in sorted(
                    diagnostics,
                    key=lambda item: (
                        str(getattr(item, "path")),
                        str(getattr(item, "code")),
                        str(getattr(item, "message")),
                    ),
                )
            ],
        },
    )


def _missing_run_uri(check_id: str, group: PreflightGroup) -> PreflightCheckResult:
    return _skip(
        check_id,
        group,
        "check skipped because RUN_URI was not provided",
        {"reason": "missing_run_uri", "requires": "RUN_URI"},
    )


def _skip(
    check_id: str,
    group: PreflightGroup,
    message: str,
    details: Mapping[str, PlainData],
) -> PreflightCheckResult:
    return _result(
        check_id,
        group,
        PreflightCheckStatus.SKIP,
        PreflightSeverity.INFO,
        message,
        details,
    )


def _fail(
    check_id: str, group: PreflightGroup, message: str, exc: BaseException
) -> PreflightCheckResult:
    return _result(
        check_id,
        group,
        PreflightCheckStatus.FAIL,
        PreflightSeverity.ERROR,
        message,
        {"error_type": type(exc).__name__, "error": str(exc)},
    )


def _result(
    check_id: str,
    group: PreflightGroup,
    status: PreflightCheckStatus,
    severity: PreflightSeverity,
    message: str,
    details: Mapping[str, PlainData],
) -> PreflightCheckResult:
    expected_ids = STABLE_CHECK_IDS[group]
    if check_id not in expected_ids:
        raise AssertionError(
            f"unexpected check ID {check_id!r} for group {group.value!r}"
        )
    return PreflightCheckResult(
        check_id=check_id,
        group=group,
        status=status,
        severity=severity,
        message=message,
        details=details,
    )


def _resolve_path(value: str | Path, *, cwd: str | Path | None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve(strict=False)
    root = Path.cwd() if cwd is None else Path(cwd)
    return (root / path).resolve(strict=False)


_CHECKS = {
    PreflightGroup.CONFIG: _check_config,
    PreflightGroup.PIPELINE: _check_pipeline,
    PreflightGroup.SELECTORS: _check_selectors,
    PreflightGroup.RUNTIME: _check_runtime,
    PreflightGroup.RUN: _check_run_uri,
    PreflightGroup.ARTIFACTS: _check_artifacts,
    PreflightGroup.CODECS: _check_codecs,
    PreflightGroup.EXECUTOR: _check_executor,
    PreflightGroup.RESOURCES: _check_resources,
    PreflightGroup.FILESYSTEM: _check_filesystem,
    PreflightGroup.CLEANUP: _check_cleanup,
    PreflightGroup.PLUGINS: _check_plugins,
}


__all__ = ["run_preflight"]
