"""Runtime injection helpers for `_inject_` values."""

from __future__ import annotations

from collections.abc import Mapping

from ..errors import RuntimeInjectionError


def apply_injected_kwargs(
    *,
    kwargs: dict[str, object],
    injected: Mapping[str, str],
    runtime: Mapping[str, object] | None,
    path: str,
) -> dict[str, object]:
    """Merge runtime-injected values into kwargs."""

    runtime = {} if runtime is None else runtime
    if not isinstance(injected, Mapping):
        raise RuntimeInjectionError(f"_inject_ must be a mapping at {path}")
    if not isinstance(runtime, Mapping):
        raise RuntimeInjectionError("runtime must be a mapping")

    for name, runtime_key in injected.items():
        if not isinstance(name, str) or not name:
            raise RuntimeInjectionError(f"Injected key {name!r} must be a non-empty string at {path}")
        if not isinstance(runtime_key, str) or not runtime_key:
            raise RuntimeInjectionError(f"Runtime key {runtime_key!r} for {name!r} at {path} must be a non-empty string")

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
