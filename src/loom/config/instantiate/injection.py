"""Runtime injection helpers for `_inject_` values."""

from __future__ import annotations

from collections.abc import Mapping

from loom.config.errors import RuntimeInjectionError


def apply_injected_kwargs(
    *,
    kwargs: dict[str, object],
    injected: Mapping[str, str],
    runtime: Mapping[str, object] | None,
    path: str,
) -> dict[str, object]:
    """Merge runtime-injected values into kwargs."""

    runtime = runtime or {}
    if not isinstance(runtime, Mapping):
        raise RuntimeInjectionError("runtime must be a mapping")
    duplicate = set(kwargs) & set(injected)
    if duplicate:
        duplicates = ", ".join(sorted(duplicate))
        raise RuntimeInjectionError(f"Duplicate _inject_ keys at {path}: {duplicates}")

    output = dict(kwargs)
    for key, runtime_key in injected.items():
        if runtime_key in runtime:
            output[key] = runtime[runtime_key]
        else:
            raise RuntimeInjectionError(f"Missing runtime injection {runtime_key!r} for key {key!r} at {path}")
    return output
