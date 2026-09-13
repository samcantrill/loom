"""Execute a file-using graph through the protected native local policy."""

# ruff: noqa: E402

import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from examples.execution.agent_workers import run_example, print_outcome, worker_records
from loom.io.uris import uri_to_path
from loom.pipeline.stores import LocalArtifactStore


HERE = Path(__file__).resolve().parent


def main():
    output = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE / "output")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = output / "input.txt"
    source.write_text("local file content\n", encoding="utf-8")
    outcome = run_example(
        HERE / "pipeline.yaml", output, configuration_policy="local",
        overrides=("input_file=" + json.dumps(str(source)),),
    )
    print_outcome(outcome)
    result = worker_records(outcome)["read"]
    run = uri_to_path(outcome.observation.admission.run_uri)
    artifact = LocalArtifactStore(run / "artifacts").load(result.outputs["text"])
    assert artifact == {"text": "local file content\n"}, artifact
    print("local_file_verified: true")


if __name__ == "__main__":
    main()
