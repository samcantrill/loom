"""Generate and inspect a SLURM afterok dry run for a diamond DAG."""

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

from weave import compose_config
from loom.pipeline.validation import validate_pipeline_config
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.stores import LocalRunStore, LocalArtifactStore

HERE = Path(__file__).resolve().parent


def main():
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    # Pure graph planning does not generate scheduler continuation commands.
    os.environ.setdefault("LOOM_EXAMPLE_SLURM_SECRET", "synthetic-reference")
    composed = compose_config(HERE / "pipeline.yaml")
    spec = validate_pipeline_config(composed.unresolved).spec
    store = LocalRunStore(output_root / "plans")
    uri = (output_root / "plans" / "graph").resolve().as_uri()
    plan = plan_pipeline(
        spec,
        run_uri=uri,
        run_store=store,
        artifact_store=LocalArtifactStore(output_root / "artifacts"),
    )
    print("graph_plan:")
    print(f"  stages: {','.join(plan.stage_order)}")
    print(f"  edges: {sum(len(stage.dependencies) for stage in spec.stages)}")
    print("  scheduler_submission: not_requested")
    print("  generated_commands: 0")


if __name__ == "__main__":
    main()
