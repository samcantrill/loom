"""Trigger stable offline import rejection codes through the public CLI."""

from __future__ import annotations

# ruff: noqa: E402

import json
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
from loom.cli.errors import ExitCode
from loom.pipeline.stores import path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"offline-rejection-{uuid4().hex[:8]}")
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
        manifest_path = Path(offline["result"]["offline_evidence"]["manifest_path"])
        incomplete_path = output_root / "incomplete-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["manifest_status"] = "incomplete"
        incomplete_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        incomplete = run_cli_json(
            [
                "authority",
                "import-offline",
                str(incomplete_path),
                *authority.authority_args,
                "--format",
                "json",
            ],
            expected=int(ExitCode.RUN_STATE),
        )
        accepted = run_cli_json(
            [
                "authority",
                "import-offline",
                str(manifest_path),
                *authority.authority_args,
                "--format",
                "json",
            ]
        )
        conflict = run_cli_json(
            [
                "authority",
                "import-offline",
                str(manifest_path),
                *authority.authority_args,
                "--format",
                "json",
            ],
            expected=int(ExitCode.RUN_STATE),
        )
    finally:
        authority.stop()

    print("offline_import_rejections:")
    print(f"  run_uri: {run_uri}")
    print(f"  incomplete_code: {incomplete['error']['code']}")
    print(f"  accepted_status: {accepted['result']['status']}")
    print(f"  conflict_code: {conflict['error']['code']}")


if __name__ == "__main__":
    main()
