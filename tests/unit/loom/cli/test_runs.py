"""Unit tests for ``loom runs`` command orchestration."""

from __future__ import annotations

import io
import json

import pytest

import loom.cli.runs as runs_command
from loom.cli.main import main
from loom.runs import (
    CatalogIndexResult,
    CatalogWarning,
    ComparisonEntry,
    ComparisonSection,
    ComparisonStatus,
    ListRunsResult,
    MigrationReadinessBlocker,
    MigrationReadinessBlockerCode,
    MigrationResumeReadiness,
    PortableRunSourceIdentity,
    PortableRunTargetIdentityPolicy,
    RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
    RunAdapterIdentity,
    RunBundleExportOptions,
    RunBundleExportResult,
    RunBundleImportPolicy,
    RunBundleImportResult,
    RunBundleInspection,
    RunBundleManifest,
    RunComparison,
    RunExchangeDiagnostic,
    RunExchangeOperationStatus,
    RunFilter,
    RunFilterKind,
    RunImportResumeMode,
    RunSummary,
    RunTargetIdentityPolicyMode,
    TransferRecordKind,
)


pytestmark = pytest.mark.unit


def test_runs_index_json_preserves_warning_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runs_command,
        "build_runs_index_result",
        lambda collection: CatalogIndexResult(
            indexed_count=1,
            skipped_count=1,
            warnings=[
                CatalogWarning(
                    "partial_run",
                    "missing status",
                    run_uri="file:///tmp/runs/partial",
                    path="/tmp/runs/partial/run.json",
                    details={"field": "status"},
                )
            ],
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["runs", "index", "/tmp/runs", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == runs_command.RUNS_INDEX_SCHEMA_VERSION
    assert payload["warnings"] == [
        {
            "code": "partial_run",
            "message": "missing status",
            "details": {
                "field": "status",
                "path": "/tmp/runs/partial/run.json",
                "run_uri": "file:///tmp/runs/partial",
            },
        }
    ]
    assert payload["result"]["indexed_count"] == 1
    assert stderr.getvalue() == ""


def test_runs_list_builds_filters_and_formats_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def build_runs_list_result(
        collection: object,
        filters: tuple[RunFilter, ...],
    ) -> ListRunsResult:
        calls["collection"] = collection
        calls["filters"] = filters
        return ListRunsResult(
            summaries=[
                RunSummary(
                    run_uri="file:///tmp/runs/a",
                    status="SUCCEEDED",
                    config_fingerprint="config-a",
                    pipeline_fingerprint="pipeline-a",
                    git_commit="abc123",
                )
            ]
        )

    monkeypatch.setattr(runs_command, "build_runs_list_result", build_runs_list_result)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "runs",
                "list",
                "/tmp/runs",
                "--status",
                "SUCCEEDED",
                "--tag",
                "project=demo",
                "--config-fingerprint",
                "config-a",
                "--pipeline-fingerprint",
                "pipeline-a",
                "--commit",
                "abc123",
                "--stage-status",
                "build=SUCCEEDED",
                "--artifact",
                "build.out=build/out",
                "--artifact-checksum",
                "build.out=sha256:abc",
                "--executor",
                "local",
                "--backend",
                "local",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    filters = calls["filters"]
    assert isinstance(filters, tuple)
    assert [(item.kind, item.key, item.value) for item in filters] == [
        (RunFilterKind.RUN_STATUS, None, "SUCCEEDED"),
        (RunFilterKind.TAG, "project", "demo"),
        (RunFilterKind.CONFIG_FINGERPRINT, None, "config-a"),
        (RunFilterKind.PIPELINE_FINGERPRINT, None, "pipeline-a"),
        (RunFilterKind.GIT_COMMIT, None, "abc123"),
        (RunFilterKind.STAGE_STATUS, "build", "SUCCEEDED"),
        (RunFilterKind.ARTIFACT_IDENTITY, "build.out", "build/out"),
        (RunFilterKind.ARTIFACT_CHECKSUM, "build.out", "sha256:abc"),
        (RunFilterKind.EXECUTOR, None, "local"),
        (RunFilterKind.BACKEND, None, "local"),
    ]
    assert "runs list /tmp/runs: 1 run" in stdout.getvalue()
    assert "SUCCEEDED file:///tmp/runs/a" in stdout.getvalue()
    assert "source=unknown" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_runs_list_rejects_malformed_tag_filter() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["runs", "list", "/tmp/runs", "--tag", "project"],
            stdout=stdout,
            stderr=stderr,
        )
        == 2
    )

    assert stdout.getvalue() == ""
    assert "expected KEY=VALUE" in stderr.getvalue()


def test_runs_diff_text_shows_non_same_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runs_command,
        "build_runs_diff_result",
        lambda collection, left, right: RunComparison(
            left_run_uri=left,
            right_run_uri=right,
            sections=[
                ComparisonSection(
                    name="run",
                    entries=[
                        ComparisonEntry(
                            key="run.status",
                            status=ComparisonStatus.DIFFERENT,
                            left="SUCCEEDED",
                            right="FAILED",
                        ),
                        ComparisonEntry(
                            key="fingerprints.config",
                            status=ComparisonStatus.SAME,
                            left="config",
                            right="config",
                        ),
                    ],
                )
            ],
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "runs",
                "diff",
                "/tmp/runs",
                "file:///tmp/runs/a",
                "file:///tmp/runs/b",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    output = stdout.getvalue()
    assert "different=1" in output
    assert "same=1" in output
    assert "run.status: different left=SUCCEEDED right=FAILED" in output
    assert "fingerprints.config" not in output
    assert stderr.getvalue() == ""


def test_runs_export_json_builds_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def build_runs_export_result(
        run_uri: str,
        destination: object,
        options: RunBundleExportOptions,
    ) -> RunBundleExportResult:
        calls["run_uri"] = run_uri
        calls["destination"] = destination
        calls["options"] = options
        return RunBundleExportResult(
            status=RunExchangeOperationStatus.SUCCEEDED,
            adapter=_adapter(),
            manifest=_manifest(run_uri=run_uri),
            exported_payload_count=2,
        )

    monkeypatch.setattr(
        runs_command,
        "build_runs_export_result",
        build_runs_export_result,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "runs",
                "export",
                "file:///tmp/runs/a",
                "/tmp/bundle.tar",
                "--include-payloads",
                "--include-logs",
                "--include-workspace",
                "--verify-checksums",
                "--max-payload-count",
                "3",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    options = calls["options"]
    assert isinstance(options, RunBundleExportOptions)
    assert calls["run_uri"] == "file:///tmp/runs/a"
    assert str(calls["destination"]) == "/tmp/bundle.tar"
    assert options.include_payloads is True
    assert options.include_logs is True
    assert options.include_workspace is True
    assert options.verify_checksums is True
    assert options.max_payload_count == 3
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == runs_command.RUNS_EXPORT_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["result"]["exported_payload_count"] == 2
    assert stderr.getvalue() == ""


def test_runs_inspect_text_uses_public_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def build_runs_inspect_result(
        bundle: object,
        *,
        verify_checksums: bool = False,
    ) -> RunBundleInspection:
        calls["bundle"] = bundle
        calls["verify_checksums"] = verify_checksums
        return RunBundleInspection(
            status=RunExchangeOperationStatus.SUCCEEDED,
            manifest=_manifest(),
            included_payload_count=0,
        )

    monkeypatch.setattr(
        runs_command,
        "build_runs_inspect_result",
        build_runs_inspect_result,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["runs", "inspect", "/tmp/bundle.tar", "--verify-checksums"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert str(calls["bundle"]) == "/tmp/bundle.tar"
    assert calls["verify_checksums"] is True
    output = stdout.getvalue()
    assert "runs inspect /tmp/bundle.tar: succeeded" in output
    assert "source: kind=local_bundle run_uri=file:///tmp/runs/a" in output
    assert stderr.getvalue() == ""


def test_runs_import_failed_result_returns_run_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def build_runs_import_result(
        bundle: object,
        target_collection: object,
        policy: RunBundleImportPolicy,
    ) -> RunBundleImportResult:
        calls["bundle"] = bundle
        calls["target_collection"] = target_collection
        calls["policy"] = policy
        return RunBundleImportResult(
            status=RunExchangeOperationStatus.FAILED,
            source_identity=_source_identity(),
            adapter=_adapter(),
            target_run_uri=None,
            imported_entry_count=0,
            imported_payload_count=0,
            readiness=_readiness(),
            diagnostics=(
                RunExchangeDiagnostic(
                    code="run_bundle_import.run_uri_collision",
                    message="target run already exists",
                ),
            ),
        )

    monkeypatch.setattr(
        runs_command,
        "build_runs_import_result",
        build_runs_import_result,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "runs",
                "import",
                "/tmp/bundle.tar",
                "/tmp/target-runs",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 6
    )

    assert str(calls["bundle"]) == "/tmp/bundle.tar"
    assert str(calls["target_collection"]) == "/tmp/target-runs"
    assert isinstance(calls["policy"], RunBundleImportPolicy)
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == runs_command.RUNS_IMPORT_SCHEMA_VERSION
    assert payload["ok"] is False
    assert payload["result"]["diagnostics"][0]["code"] == (
        "run_bundle_import.run_uri_collision"
    )
    assert stderr.getvalue() == ""


def test_runs_missing_action_is_usage_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["runs"], stdout=stdout, stderr=stderr) == 2

    assert stdout.getvalue() == ""
    assert "usage: loom runs" in stderr.getvalue()


def _adapter() -> RunAdapterIdentity:
    return RunAdapterIdentity(
        name="local-bundle",
        version="1",
        kind=TransferRecordKind.BUNDLE,
    )


def _source_identity(run_uri: str = "file:///tmp/runs/a") -> PortableRunSourceIdentity:
    return PortableRunSourceIdentity(
        source_kind=TransferRecordKind.BUNDLE,
        run_uri=run_uri,
    )


def _manifest(run_uri: str = "file:///tmp/runs/a") -> RunBundleManifest:
    return RunBundleManifest(
        schema_version=RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
        run_uri=run_uri,
        source_identity=_source_identity(run_uri),
        target_identity=PortableRunTargetIdentityPolicy(
            mode=RunTargetIdentityPolicyMode.TARGET_LOCAL,
        ),
    )


def _readiness() -> MigrationResumeReadiness:
    return MigrationResumeReadiness(
        mode=RunImportResumeMode.HISTORICAL_ONLY,
        blockers=(
            MigrationReadinessBlocker(
                code=MigrationReadinessBlockerCode.HISTORICAL_ONLY_POLICY,
                message="historical-only import",
            ),
        ),
    )
