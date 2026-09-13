"""Frozen synthetic old-version evidence for read-only import contracts.

The fixture was produced by the retired engine before cutover. Tests vary its
identity without executing that engine or inventing a production offline mode.
"""

import json
from pathlib import Path

from loom.pipeline.offline_evidence import OfflineEvidenceManifest


def complete_manifest(
    tmp_path: Path, *, name: str = "offline-run"
) -> OfflineEvidenceManifest:
    fixture = Path(__file__).parents[1] / "fixtures/offline_evidence/complete.json"
    serialized = fixture.read_text().replace(
        "/historical/loom-fixture/offline-runs/offline-run",
        str(tmp_path / "offline-runs" / name),
    )
    return OfflineEvidenceManifest.from_dict(json.loads(serialized))
