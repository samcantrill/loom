"""Run a small authority-backed pipeline and inspect backend diagnostics."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import run_cli_json
from examples.support import require_mapping


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    from examples.execution.agent_workers import run_example

    run = run_example(HERE / "pipeline.yaml", output_root, run_root=run_root)
    run_uri = run.observation.admission.run_uri
    inspect = run_cli_json(["backend", "inspect", run_uri, "--format", "json"])
    capabilities = run_cli_json(
        ["backend", "capabilities", run_uri, "--format", "json"]
    )

    inspect_result = require_mapping(inspect["result"])
    capabilities_result = require_mapping(capabilities["result"])
    capability_records = capabilities_result["capabilities"]
    if not isinstance(capability_records, list):
        raise RuntimeError("expected a list of backend capabilities")
    supported_count = sum(
        1
        for capability in capability_records
        if isinstance(capability, dict) and capability.get("support") == "supported"
    )

    print("authority_backend_diagnostics:")
    print(f"  run_uri: {run_uri}")
    print(f"  run_status: {run.observation.admission.state.value}")
    print(f"  inspect_source: {inspect_result['state_source']['label']}")
    print(f"  backend_name: {capabilities_result['backend_name']}")
    print(f"  capabilities_total: {len(capability_records)}")
    print(f"  capabilities_supported: {supported_count}")


if __name__ == "__main__":
    main()
