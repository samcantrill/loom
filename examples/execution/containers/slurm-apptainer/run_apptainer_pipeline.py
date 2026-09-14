"""Run the Apptainer executor with a fake command that executes workers locally."""

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

from examples.execution.agent_workers import run_example, print_outcome

HERE = Path(__file__).resolve().parent


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    image = os.environ.get("LOOM_APPTAINER_RESOURCE_IMAGE")
    if image is None:
        from examples.execution.containers.apptainer_fixture import fake_apptainer

        with fake_apptainer() as binding:
            binding["container"]["environment"] = {
                "variables": {"LOOM_CONTAINER_EXAMPLE": "apptainer-pipeline"}
            }
            outcome = run_example(
                HERE / "pipeline.yaml",
                output_root,
                container=binding,
                overrides=("runtime.profile=null",),
            )
        print("runtime_qualification: fake namespace fixture")
    else:
        binding = {
            "kind": "apptainer",
            "container": {
                "image": {"reference": image},
                "environment": {
                    "variables": {"LOOM_CONTAINER_EXAMPLE": "apptainer-pipeline"}
                },
            },
            "options": {
                "command": os.environ["LOOM_APPTAINER_COMMAND"],
                "cleanenv": True,
            },
            "python_executable": os.environ.get("LOOM_CONTAINER_PYTHON", "python3"),
            "daemon_endpoint": None,
        }
        outcome = run_example(
            HERE / "pipeline.yaml",
            output_root,
            container=binding,
            overrides=("runtime.profile=null",),
        )
        print("runtime_qualification: selected installed foreground runtime only")
    print_outcome(outcome)


if __name__ == "__main__":
    main()
