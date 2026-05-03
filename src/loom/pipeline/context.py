"""Minimal stage execution context for v0 static execution surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from loom.ids import RunID, StageID
from loom.pipeline.errors import PipelineValidationError
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError


@dataclass(frozen=True, slots=True)
class StageContext:
    run_id: RunID
    stage_name: StageID
    run_dir: Path
    stage_dir: Path
    resolved_config: Mapping[str, PlainData]
    stage_config: Mapping[str, PlainData]
    provenance: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise PipelineValidationError("run_id must be a non-empty string")
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise PipelineValidationError("stage_name must be a non-empty string")
        object.__setattr__(self, "run_dir", Path(self.run_dir))
        object.__setattr__(self, "stage_dir", Path(self.stage_dir))
        try:
            object.__setattr__(self, "resolved_config", ensure_plain_data(dict(self.resolved_config), path="resolved_config"))
            object.__setattr__(self, "stage_config", ensure_plain_data(dict(self.stage_config), path="stage_config"))
            object.__setattr__(self, "provenance", ensure_plain_data(dict(self.provenance), path="provenance"))
            object.__setattr__(self, "metadata", ensure_plain_data(dict(self.metadata), path="metadata"))
        except PlainDataError as exc:
            raise PipelineValidationError(f"StageContext mappings must be plain-data-compatible: {exc}") from exc

