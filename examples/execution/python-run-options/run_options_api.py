"""Demonstrate v4 runtime options through the public Python API."""

from __future__ import annotations

from loom.pipeline import (
    ResourceEntry,
    ResourceRequest,
    RunOptions,
    StageRuntimeOptions,
    merge_run_options,
    validate_executor_capabilities,
    validate_stage_runtime_options,
)


def main() -> None:
    options = RunOptions(
        run_uri="file:///tmp/loom-python-options-demo",
        executor="local",
        tags={"api": "python"},
        stage_options={
            "extract": StageRuntimeOptions(
                resources=ResourceRequest(
                    entries={
                        "cpu": ResourceEntry(kind="cpu", amount=1),
                        "memory": ResourceEntry(kind="memory", amount=256, unit="MiB"),
                    }
                )
            )
        },
    )
    validate_stage_runtime_options(options, known_stage_ids={"extract", "train"})

    merged = merge_run_options(
        base={"profile": "local-debug"},
        profiles={
            "local-debug": {
                "executor": "local",
                "tags": {"profile": "local-debug"},
                "stage_options": {
                    "train": {
                        "resources": {
                            "entries": {
                                "gpu": {"kind": "gpu", "amount": 1},
                            }
                        }
                    }
                },
            }
        },
        explicit=options,
        known_stage_ids={"extract", "train"},
    )
    diagnostics = validate_executor_capabilities(merged).to_dict()["diagnostics"]

    print(f"executor: {merged.executor}")
    print(f"stage_options: {','.join(sorted(merged.stage_options))}")
    print(f"diagnostic_count: {len(diagnostics)}")
    print(f"first_diagnostic: {diagnostics[0]['code'] if diagnostics else 'none'}")


if __name__ == "__main__":
    main()
