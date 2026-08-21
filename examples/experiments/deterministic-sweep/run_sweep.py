"""Run a deterministic two-trial manual sweep through the Loom CLI."""

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

from examples.support import require_mapping, run_cli_json
from loom.pipeline.stores import path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE / "outputs"))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    journey_root = output_root / f"deterministic-sweep-{uuid4().hex[:8]}"
    sweep_dir = journey_root / "sweep-state"
    spec = require_mapping(json.loads((HERE / "sweep.json").read_text(encoding="utf-8")))
    spec["run_uri_root"] = path_to_run_uri(run_root)
    rendered_spec = journey_root / "sweep.json"
    rendered_spec.parent.mkdir(parents=True, exist_ok=True)
    rendered_spec.write_text(json.dumps(spec), encoding="utf-8")

    plan = _result(["sweep", "plan", str(rendered_spec), "--sweep-dir", str(sweep_dir), "--format", "json"])
    run = _result(["sweep", "run", str(rendered_spec), "--config", str(HERE / "pipeline.yaml"), "--sweep-dir", str(sweep_dir), "--format", "json"])
    status = _result(["sweep", "status", str(sweep_dir), "--format", "json"])
    collection = _result(["sweep", "collect", str(sweep_dir), "--format", "json"])

    print("deterministic_sweep:")
    print(f"  planned_trials: {plan['trial_count']}")
    print(f"  run_status: {require_mapping(run['result'])['status']}")
    print(f"  succeeded_trials: {require_mapping(status['counts'])['succeeded']}")
    print(f"  collected_trials: {len(collection['trials'])}")
    print(f"  artifact_count: {collection['artifact_count']}")


def _result(argv: list[str]) -> dict[str, object]:
    return require_mapping(run_cli_json(argv)["result"])


if __name__ == "__main__":
    main()
