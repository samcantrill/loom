"""Config-owned helpers for opt-in target construction checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re

from .instantiate import instantiate


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class TargetCheckResult:
    """Summary of constructed generic config target blocks."""

    target_count: int
    checked_paths: tuple[str, ...]


def check_config_targets(
    value: object,
    *,
    skip_paths: Sequence[str] = (),
) -> TargetCheckResult:
    """Construct generic ``_target_`` blocks and discard the objects."""

    skipped = frozenset(skip_paths)
    target_paths: list[str] = []
    construction_roots: list[tuple[str, Mapping[str, object]]] = []
    _collect_target_roots(
        value,
        path="$",
        skip_paths=skipped,
        target_paths=target_paths,
        construction_roots=construction_roots,
        covered_by_parent_target=False,
    )

    for _path, mapping in construction_roots:
        instantiate(mapping)

    return TargetCheckResult(
        target_count=len(target_paths),
        checked_paths=tuple(target_paths),
    )


def _collect_target_roots(
    value: object,
    *,
    path: str,
    skip_paths: frozenset[str],
    target_paths: list[str],
    construction_roots: list[tuple[str, Mapping[str, object]]],
    covered_by_parent_target: bool,
) -> None:
    if isinstance(value, Mapping):
        mapping = dict(value)
        is_target = "_target_" in mapping
        skip_current = path in skip_paths
        child_covered = covered_by_parent_target
        if is_target and not skip_current:
            target_paths.append(path)
            if not covered_by_parent_target:
                construction_roots.append((path, mapping))
            child_covered = True

        for key, child in mapping.items():
            _collect_target_roots(
                child,
                path=_child_path(path, str(key)),
                skip_paths=skip_paths,
                target_paths=target_paths,
                construction_roots=construction_roots,
                covered_by_parent_target=child_covered,
            )
        return

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _collect_target_roots(
                child,
                path=f"{path}[{index}]",
                skip_paths=skip_paths,
                target_paths=target_paths,
                construction_roots=construction_roots,
                covered_by_parent_target=covered_by_parent_target,
            )


def _child_path(path: str, key: str) -> str:
    if _IDENTIFIER_RE.fullmatch(key):
        return f"{path}.{key}"
    return f"{path}[{key!r}]"


__all__ = ["TargetCheckResult", "check_config_targets"]
