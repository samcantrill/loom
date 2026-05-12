"""Explicit offline-first run-store adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loom.pipeline.offline_evidence import (
    OfflineEvidenceManifest,
    offline_evidence_manifest_path,
    read_offline_evidence_manifest,
)
from loom.pipeline.stores import LocalRunStore
from loom.serialization import PlainData
from loom.state_sources import offline_evidence_source


class OfflineEvidenceRunStore:
    """RunStore-shaped adapter for explicit non-authoritative offline evidence."""

    offline_evidence_enabled = True

    def __init__(
        self,
        root: str | Path,
        *,
        owner_id: str = "offline-controller",
        workspace_id: str | None = None,
    ) -> None:
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("owner_id must be a non-empty string")
        if workspace_id is not None and (
            not isinstance(workspace_id, str) or not workspace_id
        ):
            raise ValueError("workspace_id must be None or a non-empty string")
        self.local_store = LocalRunStore(root)
        self.owner_id = owner_id
        self.workspace_id = workspace_id
        self.state_source = offline_evidence_source()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.local_store, name)

    def offline_evidence_manifest_path(self, run_uri: str) -> Path:
        return offline_evidence_manifest_path(self.local_store, run_uri)

    def read_offline_evidence_manifest(
        self, run_uri: str
    ) -> OfflineEvidenceManifest | None:
        path = self.offline_evidence_manifest_path(run_uri)
        if not path.exists():
            return None
        return read_offline_evidence_manifest(path)

    def offline_evidence_summary(self, run_uri: str) -> dict[str, PlainData] | None:
        manifest = self.read_offline_evidence_manifest(run_uri)
        if manifest is None:
            return None
        path = self.offline_evidence_manifest_path(run_uri)
        return {
            "manifest_path": str(path),
            "manifest_relative_path": "offline-evidence/manifest.json",
            "manifest_status": manifest.manifest_status.value,
            "diagnostic_count": len(manifest.diagnostics),
            "state_source": dict(manifest.state_source),
        }


def create_offline_evidence_run_store(
    root: str | Path,
    *,
    owner_id: str = "offline-controller",
    workspace_id: str | None = None,
) -> OfflineEvidenceRunStore:
    """Create a local run-store adapter for explicit offline-first execution."""

    return OfflineEvidenceRunStore(
        root,
        owner_id=owner_id,
        workspace_id=workspace_id,
    )


def is_offline_evidence_run_store(value: object) -> bool:
    return isinstance(value, OfflineEvidenceRunStore) or bool(
        getattr(value, "offline_evidence_enabled", False)
    )


__all__ = [
    "OfflineEvidenceRunStore",
    "create_offline_evidence_run_store",
    "is_offline_evidence_run_store",
]
