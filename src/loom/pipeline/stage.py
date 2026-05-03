"""Phase 6 structural stage contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from loom.artifacts import ArtifactRef


@runtime_checkable
class Stage(Protocol):
    def run(
        self,
        context: "StageContext",
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]: ...


from .context import StageContext


__all__ = ["Stage"]
