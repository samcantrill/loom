"""Run an offline-first pipeline and import it through authority."""

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

from examples.support import run_cli_json
from examples.support import start_authority_session
from examples.support import require_mapping
from loom.cli.errors import ExitCode
from loom.pipeline.stores import path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"offline-import-{uuid4().hex[:8]}")
    config_path = HERE / "pipeline.yaml"

    authority = start_authority_session(output_root)
    try:
        offline = run_cli_json(
            [
                "run",
                str(config_path),
                "--run-uri",
                run_uri,
                "--offline-first",
                "--format",
                "json",
            ]
        )
        evidence = require_mapping(offline["result"]["offline_evidence"])
        pre_import_status = run_cli_json(
            ["status", run_uri, *authority.authority_args, "--format", "json"],
            expected=int(ExitCode.RUN_STATE),
        )
        imported = run_cli_json(
            [
                "authority",
                "import-offline",
                str(evidence["manifest_path"]),
                *authority.authority_args,
                "--format",
                "json",
            ]
        )
        post_import_status = run_cli_json(
            ["status", run_uri, *authority.authority_args, "--format", "json"]
        )
    finally:
        authority.stop()

    pre_import_error = require_mapping(pre_import_status["error"])
    status_result = require_mapping(post_import_status["result"])
    import_provenance = require_mapping(status_result["import_provenance"])
    import_result = require_mapping(imported["result"])

    print("offline_first_import:")
    print(f"  run_uri: {run_uri}")
    print(f"  offline_manifest_status: {evidence['manifest_status']}")
    print(f"  offline_source: {evidence['state_source']['label']}")
    print(f"  pre_import_status_code: {pre_import_error['code']}")
    print(f"  pre_import_status_message: {pre_import_error['message']}")
    print(f"  imported_status: {import_result['status']}")
    print(f"  imported_stage_count: {import_result['imported_stage_count']}")
    print(f"  post_import_status_source: {status_result['state_source']['label']}")
    print(f"  post_import_import_source: {import_provenance['source']}")


if __name__ == "__main__":
    main()
