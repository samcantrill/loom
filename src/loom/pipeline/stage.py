"""Phase 6 structural stage contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from loom.artifacts import ArtifactRef

if TYPE_CHECKING:
    from .context import StageContext


@runtime_checkable
class Stage(Protocol):
    def run(
        self,
        context: "StageContext",
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]: ...


__all__ = ["Stage"]
