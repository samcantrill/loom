"""Create comparable runs and move one payload through the public runs CLI."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path
from uuid import uuid4

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import require_mapping, run_cli_json
from weave import compose_config
from loom.io.uris import uri_to_path
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    configured_run_root = Path(
        os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs")
    )
    token = uuid4().hex[:8]
    journey_root = output_root / f"run-catalog-and-bundles-{token}"
    run_root = configured_run_root / f"run-catalog-and-bundles-{token}"
    run_root.mkdir(parents=True, exist_ok=True)
    baseline_uri = path_to_run_uri(run_root / f"baseline-{token}")
    challenger_uri = path_to_run_uri(run_root / f"challenger-{token}")
    baseline = _runner(run_root).run(
        RunRequest(
            config=compose_config(HERE / "pipeline.yaml"),
            run_uri=baseline_uri,
        )
    )
    challenger = _runner(run_root).run(
        RunRequest(
            config=compose_config(
                HERE / "pipeline.yaml",
                overrides=("variant=challenger",),
            ),
            run_uri=challenger_uri,
        )
    )
    if baseline.status.name != "SUCCEEDED" or challenger.status.name != "SUCCEEDED":
        raise RuntimeError("expected both example runs to succeed")

    index = _result(["runs", "index", str(run_root), "--format", "json"])
    listed = _result(["runs", "list", str(run_root), "--format", "json"])
    comparison = _result(
        [
            "runs",
            "diff",
            str(run_root),
            baseline_uri,
            challenger_uri,
            "--format",
            "json",
        ]
    )
    bundle_path = journey_root / "baseline.bundle.tar"
    exported = _result(
        [
            "runs",
            "export",
            baseline_uri,
            str(bundle_path),
            "--include-payloads",
            "--format",
            "json",
        ]
    )
    inspected = _result(
        ["runs", "inspect", str(bundle_path), "--verify-checksums", "--format", "json"]
    )
    imported = _result(
        [
            "runs",
            "import",
            str(bundle_path),
            str(journey_root / "imported-runs"),
            "--format",
            "json",
        ]
    )

    source_payload = uri_to_path(baseline.artifact_index["produce.payload"].uri)
    imported_uri = _required_string(imported, "target_run_uri")
    imported_refs = LocalRunStore(journey_root / "imported-runs").read_artifact_index(
        imported_uri
    )
    imported_payload = uri_to_path(imported_refs["produce.payload"].uri)
    if source_payload.read_bytes() != imported_payload.read_bytes():
        raise RuntimeError("imported payload bytes did not match the exported payload")

    different_entries = sum(
        1
        for section in comparison["sections"]
        for entry in require_mapping(section)["entries"]
        if require_mapping(entry)["status"] == "different"
    )
    if index["indexed_count"] != 2 or len(listed["summaries"]) != 2:
        raise RuntimeError("run catalog did not contain exactly the two example runs")
    if different_entries == 0:
        raise RuntimeError("run comparison did not report the configured difference")
    if exported["exported_payload_count"] != 1:
        raise RuntimeError("bundle export did not include the example payload")

    manifest = require_mapping(inspected["manifest"])
    print("run_catalog_and_bundles:")
    print(f"  indexed_run_count: {index['indexed_count']}")
    print(f"  listed_run_count: {len(listed['summaries'])}")
    print(f"  different_entries: {different_entries}")
    print(f"  exported_payload_count: {exported['exported_payload_count']}")
    print(f"  inspected_payload_count: {len(manifest['payload_refs'])}")
    print(f"  imported_payload_count: {imported['imported_payload_count']}")
    print("  payload_bytes_equal: True")
    print(f"  imported_run_uri: {imported_uri}")


def _result(argv: list[str]) -> dict[str, object]:
    return require_mapping(run_cli_json(argv)["result"])


def _runner(run_root: Path) -> PipelineRunner:
    """Create an independent per-run authority store for one local run."""

    return PipelineRunner(
        run_store=create_authority_backed_serial_run_store(
            run_root,
            authority_store=SQLitePerRunAuthorityStore(),
        )
    )


def _required_string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"expected a non-empty string for {key}")
    return value


if __name__ == "__main__":
    main()
