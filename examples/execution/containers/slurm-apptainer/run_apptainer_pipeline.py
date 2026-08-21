"""Run the Apptainer executor with a fake command that executes workers locally."""

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

from examples.support import run_cli_json, started_authority_session
from fake_apptainer import activate_fake_apptainer, read_fake_apptainer_log
from loom.pipeline.stores import LocalRunArtifactStore, path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    existing = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(HERE) if not existing else str(HERE) + os.pathsep + existing
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE / "outputs"))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_root.mkdir(parents=True, exist_ok=True)
    fake = activate_fake_apptainer(output_root)
    run_uri = path_to_run_uri(run_root / f"apptainer-pipeline-{uuid4().hex[:8]}")

    with started_authority_session(output_root) as authority:
        run = run_cli_json(
            ["run", str(HERE / "pipeline.yaml"), "--run-uri", run_uri, "--executor", "apptainer", *authority.authority_args, "--format", "json"]
        )

    provenance = LocalRunArtifactStore(run_root).stage_artifacts(run_uri, "analyze").read_stage_provenance()
    if provenance is None:
        raise RuntimeError("expected Apptainer stage provenance")
    metadata = provenance.get("executor_metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError("expected executor metadata")
    calls = [record for record in read_fake_apptainer_log(fake.log_path) if record.get("operation") == "exec"]
    if not calls:
        raise RuntimeError("expected fake Apptainer exec call")

    print(f"  run_uri: {run_uri}")
    print(f"  run_status: {run['result']['status']}")
    print(f"  artifact_count: {run['result']['artifact_count']}")
    print(f"  executor: {metadata.get('executor')}")
    print(f"  image: {calls[0].get('image')}")
    print(f"  flags: {','.join(calls[0].get('flags', []))}")
    print(f"  fake_call_count: {len(calls)}")


if __name__ == "__main__":
    main()
