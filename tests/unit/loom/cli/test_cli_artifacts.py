"""Unit tests for ``loom artifacts`` command orchestration."""

from __future__ import annotations

import io
import json

import pytest

import loom.cli.artifacts as artifacts_command
from loom.cli.main import main
from loom.diagnostics.inspection import (
    ArtifactDetailSummary,
    ArtifactSummary,
    RunArtifactsSummary,
)


pytestmark = pytest.mark.unit


def _artifact_summary() -> ArtifactSummary:
    return ArtifactSummary(
        key="build.data",
        artifact_id="build/data",
        stage_name="build",
        output_name="data",
        uri="file:///tmp/run/artifacts/build/data.json",
        artifact_type="json",
        codec_key="json.v1",
        producer_stage="build",
        metadata={"label": "demo"},
        provenance_available=True,
    )


def test_artifacts_list_json_uses_diagnostics_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifacts_command,
        "build_artifacts_list_result",
        lambda run_uri: RunArtifactsSummary(
            run_uri=run_uri,
            artifacts=(_artifact_summary(),),
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["artifacts", "list", "file:///tmp/run", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == artifacts_command.ARTIFACTS_LIST_SCHEMA_VERSION
    assert payload["result"]["artifact_count"] == 1
    assert payload["result"]["artifacts"][0]["artifact_id"] == "build/data"
    assert stderr.getvalue() == ""


def test_artifacts_show_text_passes_artifact_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, str] = {}

    def build_artifact_show_result(
        run_uri: str,
        artifact_id: str,
    ) -> ArtifactDetailSummary:
        calls["run_uri"] = run_uri
        calls["artifact_id"] = artifact_id
        return ArtifactDetailSummary(
            run_uri=run_uri,
            artifact=_artifact_summary(),
            stage_provenance={"tool": "loom"},
        )

    monkeypatch.setattr(
        artifacts_command,
        "build_artifact_show_result",
        build_artifact_show_result,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["artifacts", "show", "file:///tmp/run", "build/data"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert calls == {"run_uri": "file:///tmp/run", "artifact_id": "build/data"}
    assert "artifact build/data (build.data)" in stdout.getvalue()
    assert "stage_provenance: tool" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_artifacts_missing_action_is_usage_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["artifacts"], stdout=stdout, stderr=stderr) == 2

    assert stdout.getvalue() == ""
    assert "usage: loom artifacts" in stderr.getvalue()
