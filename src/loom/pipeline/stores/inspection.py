"""Read-only run inspection models owned by run stores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from loom.pipeline.submitted import SubmittedOperationRecord
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.serialization import PlainData, ensure_plain_data


@dataclass(frozen=True, slots=True)
class RunStageInspection:
    """Read-only persisted state for one discovered stage."""

    stage_name: str
    status: StageStatusRecord | None = None
    failure: Mapping[str, PlainData] | None = None
    input_count: int = 0
    output_count: int = 0
    provenance_available: bool = False
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    stdout_available: bool = False
    stderr_available: bool = False

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "status": None if self.status is None else self.status.to_dict(),
            "failure": None if self.failure is None else dict(self.failure),
            "input_count": self.input_count,
            "output_count": self.output_count,
            "provenance_available": self.provenance_available,
            "stdout_path": None if self.stdout_path is None else str(self.stdout_path),
            "stderr_path": None if self.stderr_path is None else str(self.stderr_path),
            "stdout_available": self.stdout_available,
            "stderr_available": self.stderr_available,
        }


@dataclass(frozen=True, slots=True)
class RunStateInspection:
    """Read-only persisted state for a local run."""

    run_uri: str
    run_status: RunStatusRecord | None = None
    stage_inspections: tuple[RunStageInspection, ...] = ()
    artifact_count: int = 0
    submitted_operations: tuple[SubmittedOperationRecord, ...] = ()

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "run_status": None
            if self.run_status is None
            else self.run_status.to_dict(),
            "stage_inspections": [stage.to_dict() for stage in self.stage_inspections],
            "artifact_count": self.artifact_count,
            "submitted_operations": [
                record.to_summary_dict() for record in self.submitted_operations
            ],
        }


def ensure_failure_payload(
    value: Mapping[str, PlainData] | None,
) -> Mapping[str, PlainData] | None:
    """Normalize an optional stage failure payload to plain data."""

    if value is None:
        return None
    normalized = ensure_plain_data(dict(value), path="failure")
    if not isinstance(normalized, dict):
        return {"value": normalized}
    return normalized


__all__ = [
    "RunStageInspection",
    "RunStateInspection",
    "ensure_failure_payload",
]
