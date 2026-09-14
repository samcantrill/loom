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
from loom.io.uris import uri_to_path
from examples.execution.agent_workers import run_example, worker_records
from loom.pipeline.stores import LocalRunStore


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
    baseline = run_example(HERE / "pipeline.yaml", output_root, run_root=run_root)
    challenger = run_example(
        HERE / "pipeline.yaml",
        output_root,
        run_root=run_root,
        overrides=("variant=challenger",),
    )
    baseline_uri = baseline.observation.admission.run_uri
    challenger_uri = challenger.observation.admission.run_uri
    if any(
        result.observation.admission.state.name != "SUCCEEDED"
        for result in (baseline, challenger)
    ):
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

    source_payload = uri_to_path(
        worker_records(baseline)["produce"].outputs["payload"].uri
    )
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
    indexed_uris = {item["run_uri"] for item in listed["summaries"]}
    if not {baseline_uri, challenger_uri} <= indexed_uris:
        raise RuntimeError("run catalog did not include both target runs")
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


def _required_string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"expected a non-empty string for {key}")
    return value


if __name__ == "__main__":
    main()
