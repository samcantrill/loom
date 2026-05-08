"""Show stable context fields from structured config errors."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from loom.config import compose_config
from loom.config.errors import (
    ConfigErrorContext,
    ConfigIncludeExpansionError,
    ConfigIncludeResolutionError,
    ConfigLoadError,
    ConfigUnsupportedResolverError,
)


HERE = Path(__file__).resolve().parent


Scenario = tuple[str, type[Exception], str, Callable[[], None]]


def _missing_include() -> None:
    compose_config(HERE / "missing-include.yaml")


def _invalid_override() -> None:
    compose_config(
        HERE / "override-base.yaml",
        overrides=("+pipeline.component._include_=true",),
    )


def _unsupported_resolver() -> None:
    compose_config(HERE / "unsupported-resolver.yaml")


def _unsupported_copy() -> None:
    compose_config(HERE / "unsupported-copy.yaml")


def _summarize_context(context: ConfigErrorContext) -> dict[str, Any]:
    details = context.details or {}
    summary: dict[str, Any] = {
        "code": context.code,
        "source_kind": context.source_kind,
        "source_order": context.source_order,
        "config_path": context.config_path,
    }
    if context.directive is not None:
        summary["directive"] = context.directive
    if context.expected is not None:
        summary["expected"] = context.expected
    if context.actual is not None:
        summary["actual"] = context.actual
    if "reason" in details:
        summary["reason"] = details["reason"]
    if "target_kind" in details:
        summary["target_kind"] = details["target_kind"]
    if "override_path" in details:
        summary["override_path"] = details["override_path"]
    if "unsupported_resolver" in details:
        summary["unsupported_resolver"] = details["unsupported_resolver"]
    return summary


def _run_scenario(
    label: str,
    expected_type: type[Exception],
    expected_code: str,
    trigger: Callable[[], None],
) -> None:
    try:
        trigger()
    except expected_type as exc:
        context = getattr(exc, "context", None)
        if not isinstance(context, ConfigErrorContext):
            raise RuntimeError(f"{label} did not provide structured context") from exc
        if context.code != expected_code:
            raise RuntimeError(
                f"{label} produced context code {context.code!r}, expected {expected_code!r}"
            ) from exc
        print(f"{label}:")
        for key, value in _summarize_context(context).items():
            print(f"  {key}: {value}")
    else:
        raise RuntimeError(f"{label} unexpectedly succeeded")


def main() -> None:
    scenarios: tuple[Scenario, ...] = (
        (
            "missing include",
            ConfigIncludeResolutionError,
            "target_not_found",
            _missing_include,
        ),
        (
            "invalid override",
            ConfigIncludeExpansionError,
            "invalid_include_value",
            _invalid_override,
        ),
        (
            "unsupported resolver",
            ConfigUnsupportedResolverError,
            "unsupported_resolver",
            _unsupported_resolver,
        ),
        (
            "unsupported _copy_",
            ConfigLoadError,
            "unsupported_directive",
            _unsupported_copy,
        ),
    )
    for label, expected_type, expected_code, trigger in scenarios:
        _run_scenario(label, expected_type, expected_code, trigger)


if __name__ == "__main__":
    main()
