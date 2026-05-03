"""Interpolation wrapper around OmegaConf."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from loom.serialization import PlainData, ensure_plain_data

from .errors import ConfigInterpolationError

_INTERPOLATION_PATTERN = re.compile(r"\$\{([^{}]+)\}")


def resolve_interpolation(mapping: Mapping[str, Any], *, path: str = "$") -> dict[str, PlainData]:
    _validate_interpolation_syntax(mapping, path=path)
    try:
        config = OmegaConf.create(dict(mapping))
    except OmegaConfBaseException as exc:
        raise ConfigInterpolationError(f"Failed to prepare interpolation context at {path}") from exc

    try:
        resolved = OmegaConf.to_container(config, resolve=True)
    except OmegaConfBaseException as exc:
        raise ConfigInterpolationError(f"Failed to resolve interpolation at {path}") from exc

    try:
        plain = ensure_plain_data(resolved, path=path)
    except Exception as exc:  # noqa: BLE001
        raise ConfigInterpolationError(f"Interpolation produced non-plain values at {path}") from exc
    if not isinstance(plain, dict):
        raise ConfigInterpolationError(f"Interpolation produced non-mapping root at {path}")
    return plain


def _validate_interpolation_syntax(value: Any, *, path: str) -> None:
    if isinstance(value, str):
        for match in _INTERPOLATION_PATTERN.finditer(value):
            token = match.group(1)
            if ":" in token:
                raise ConfigInterpolationError(
                    f"Resolver-style interpolation is not supported in Phase 4 at {path}: {match.group(0)!r}"
                )
        return

    if isinstance(value, Mapping):
        for key, child in value.items():
            _validate_interpolation_syntax(child, path=f"{path}[{key!r}]")
        return

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_interpolation_syntax(child, path=f"{path}[{index}]")
        return
