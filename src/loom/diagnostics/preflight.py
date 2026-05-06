"""Local preflight check runner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from loom.serialization import PlainData

from .models import (
    STABLE_CHECK_IDS,
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightRequest,
    PreflightResult,
    PreflightSeverity,
    normalize_groups,
)


@dataclass
class _Context:
    request: PreflightRequest
    _config: object | None = None
    _config_error: BaseException | None = None
    _pipeline: object | None = None
    _pipeline_error: BaseException | None = None
    _run_uri: object | None = None
    _run_uri_error: BaseException | None = None

    def config(self) -> object:
        if self._config is not None:
            return self._config
        if self._config_error is not None:
            raise self._config_error
        try:
            from loom.config.api import compose_config

            self._config = compose_config(
                _resolve_path(self.request.config_path, cwd=self.request.cwd),
                overlays=tuple(_resolve_path(path, cwd=self.request.cwd) for path in self.request.overlays),
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
            self._pipeline = validate_pipeline_config(resolved)
        except Exception as exc:  # noqa: BLE001
            self._pipeline_error = exc
            raise
        return self._pipeline

    def run_uri(self) -> object:
        if self._run_uri is not None:
            return self._run_uri
        if self._run_uri_error is not None:
            raise self._run_uri_error
        try:
            from loom.pipeline.stores import resolve_local_run_uri

            self._run_uri = resolve_local_run_uri(self.request.run_uri, cwd=self.request.cwd)
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
        return (_fail("config.load", PreflightGroup.CONFIG, "config composition failed", exc),)

    source_count = len(cast(Any, config).source_artifacts)
    return (
        _result(
            "config.load",
            PreflightGroup.CONFIG,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "config composed successfully",
            {
                "config_path": str(_resolve_path(context.request.config_path, cwd=context.request.cwd)),
                "source_artifact_count": source_count,
            },
        ),
    )


def _check_pipeline(context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        validation = context.pipeline()
    except Exception as exc:  # noqa: BLE001
        return (_fail("pipeline.graph", PreflightGroup.PIPELINE, "pipeline graph validation failed", exc),)

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
        selectors = _coerce_selectors(context.request.selectors)
        from loom.pipeline.planning.selectors import normalize_selectors

        selection = normalize_selectors(
            cast(Any, selectors),
            spec=validation.spec,
            graph=validation.graph,
        )
    except Exception as exc:  # noqa: BLE001
        return (_fail("selectors.validate", PreflightGroup.SELECTORS, "selector validation failed", exc),)

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


def _check_run_uri(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if context.request.run_uri is None:
        return (_missing_run_uri("run_uri.resolve", PreflightGroup.RUN),)
    try:
        resolved = cast(Any, context.run_uri())
    except Exception as exc:  # noqa: BLE001
        return (_fail("run_uri.resolve", PreflightGroup.RUN, "run URI resolution failed", exc),)

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
                    {"run_uri": resolved.uri, "path": str(path)},
                ),
            )
        return (
            _result(
                "run_uri.resolve",
                PreflightGroup.RUN,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "run URI directory already exists",
                {"run_uri": resolved.uri, "path": str(path)},
            ),
        )

    return (
        _result(
            "run_uri.resolve",
            PreflightGroup.RUN,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "run URI resolves to an available local path",
            {"run_uri": resolved.uri, "path": str(path), "exists": False},
        ),
    )


def _check_artifact_store(context: _Context) -> tuple[PreflightCheckResult, ...]:
    if context.request.run_uri is None:
        return (_missing_run_uri("artifact_store.available", PreflightGroup.ARTIFACTS),)
    try:
        resolved = cast(Any, context.run_uri())
        from loom.pipeline.stores import LocalArtifactStore, LocalRunStore

        run_store = LocalRunStore(resolved.path.parent)
        root = run_store.local_artifact_root(resolved.uri)
        store = LocalArtifactStore(root)
    except Exception as exc:  # noqa: BLE001
        return (_fail("artifact_store.available", PreflightGroup.ARTIFACTS, "artifact store probe failed", exc),)

    if root.exists() and not root.is_dir():
        return (
            _result(
                "artifact_store.available",
                PreflightGroup.ARTIFACTS,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "artifact root exists but is not a directory",
                {"path": str(root)},
            ),
        )

    return (
        _result(
            "artifact_store.available",
            PreflightGroup.ARTIFACTS,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "local artifact store can be constructed",
            {"path": str(store.root), "exists": root.exists()},
        ),
    )


def _check_codecs(_context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        from loom.io.codecs.registry import create_default_codec_registry

        registry = create_default_codec_registry()
        keys = registry.keys()
    except Exception as exc:  # noqa: BLE001
        return (_fail("codec_registry.available", PreflightGroup.CODECS, "codec registry probe failed", exc),)

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


def _check_executor(_context: _Context) -> tuple[PreflightCheckResult, ...]:
    try:
        from loom.pipeline.executors import LocalExecutor

        executor = LocalExecutor()
    except Exception as exc:  # noqa: BLE001
        return (_fail("executor.local", PreflightGroup.EXECUTOR, "local executor probe failed", exc),)

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


def _check_filesystem(context: _Context) -> tuple[PreflightCheckResult, ...]:
    paths = (
        _resolve_path(context.request.config_path, cwd=context.request.cwd),
        *(_resolve_path(path, cwd=context.request.cwd) for path in context.request.overlays),
    )
    missing = [str(path) for path in paths if not path.exists()]
    non_files = [str(path) for path in paths if path.exists() and not path.is_file()]
    if missing or non_files:
        return (
            _result(
                "filesystem.input_exists",
                PreflightGroup.FILESYSTEM,
                PreflightCheckStatus.FAIL,
                PreflightSeverity.ERROR,
                "one or more input files are unavailable",
                cast(Mapping[str, PlainData], {"missing": missing, "non_files": non_files}),
            ),
        )
    return (
        _result(
            "filesystem.input_exists",
            PreflightGroup.FILESYSTEM,
            PreflightCheckStatus.PASS,
            PreflightSeverity.INFO,
            "configured input files exist",
            cast(Mapping[str, PlainData], {"paths": [str(path) for path in paths]}),
        ),
    )


def _coerce_selectors(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        from loom.pipeline.planning import PlanSelectors

        return PlanSelectors.from_dict(value)
    return value


def _missing_run_uri(check_id: str, group: PreflightGroup) -> PreflightCheckResult:
    return _result(
        check_id,
        group,
        PreflightCheckStatus.SKIP,
        PreflightSeverity.INFO,
        "check skipped because RUN_URI was not provided",
        {"reason": "missing_run_uri", "requires": "RUN_URI"},
    )


def _fail(check_id: str, group: PreflightGroup, message: str, exc: BaseException) -> PreflightCheckResult:
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
        raise AssertionError(f"unexpected check ID {check_id!r} for group {group.value!r}")
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
    PreflightGroup.RUN: _check_run_uri,
    PreflightGroup.ARTIFACTS: _check_artifact_store,
    PreflightGroup.CODECS: _check_codecs,
    PreflightGroup.EXECUTOR: _check_executor,
    PreflightGroup.FILESYSTEM: _check_filesystem,
}


__all__ = ["run_preflight"]
