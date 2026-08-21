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
    invocation_id = uuid4().hex[:8]
    journey_root = output_root / f"deterministic-sweep-{invocation_id}"
    sweep_dir = journey_root / "sweep-state"
    spec = require_mapping(json.loads((HERE / "sweep.json").read_text(encoding="utf-8")))
    spec["run_uri_root"] = path_to_run_uri(
        run_root / f"deterministic-sweep-{invocation_id}"
    )
    rendered_spec = journey_root / "sweep.json"
    rendered_spec.parent.mkdir(parents=True, exist_ok=True)
    rendered_spec.write_text(json.dumps(spec), encoding="utf-8")

    plan = _result(
        [
            "sweep",
            "plan",
            str(rendered_spec),
            "--sweep-dir",
            str(sweep_dir),
            "--format",
            "json",
        ]
    )
    run = _result(
        [
            "sweep",
            "run",
            str(rendered_spec),
            "--config",
            str(HERE / "pipeline.yaml"),
            "--sweep-dir",
            str(sweep_dir),
            "--format",
            "json",
        ]
    )
    status = _result(["sweep", "status", str(sweep_dir), "--format", "json"])
    collection = _result(["sweep", "collect", str(sweep_dir), "--format", "json"])
    planned_trials = _required_int(plan, "trial_count")
    run_status = _required_string(require_mapping(run["result"]), "status")
    succeeded_trials = _required_int(require_mapping(status["counts"]), "succeeded")
    collected_trials = len(collection["trials"])
    artifact_count = _required_int(collection, "artifact_count")
    if (planned_trials, run_status, succeeded_trials, collected_trials, artifact_count) != (
        2,
        "succeeded",
        2,
        2,
        2,
    ):
        raise RuntimeError("deterministic sweep did not produce exactly two trials")

    print("deterministic_sweep:")
    print(f"  planned_trials: {planned_trials}")
    print(f"  run_status: {run_status}")
    print(f"  succeeded_trials: {succeeded_trials}")
    print(f"  collected_trials: {collected_trials}")
    print(f"  artifact_count: {artifact_count}")


def _result(argv: list[str]) -> dict[str, object]:
    return require_mapping(run_cli_json(argv)["result"])


def _required_int(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"expected {key} to be an integer")
    return value


def _required_string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"expected {key} to be a non-empty string")
    return value


if __name__ == "__main__":
    main()
