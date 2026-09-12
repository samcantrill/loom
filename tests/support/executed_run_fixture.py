"""Build native library execution state for non-run CLI consumer fixtures.

These diagnostics/authority tests exercise their own commands. The retained
PipelineRunner primitive supplies their historical fixture state until those
consumers' mapped cutover; this is not a production ordinary-run entrypoint.
"""

from pathlib import Path
from typing import Any, cast


def execute_fixture(
    config_path: Path,
    run_uri: str,
    *,
    authority_config=None,
    executor: str = "local",
    offline: bool = False,
):
    from weave import compose_config
    from loom.pipeline.execution import (
        PipelineRunner,
        RunRequest,
        RuntimeServices,
        create_authority_backed_serial_run_store,
        create_offline_evidence_run_store,
    )
    from loom.pipeline.executors import LocalExecutor, SubprocessExecutor
    from loom.pipeline.stores import run_uri_to_path

    root = run_uri_to_path(run_uri).parent
    store: Any = (
        create_offline_evidence_run_store(root)
        if offline
        else create_authority_backed_serial_run_store(
            root, authority_config=authority_config
        )
    )
    worker = (
        SubprocessExecutor(worker_results=cast(Any, store))
        if executor == "subprocess"
        else LocalExecutor()
    )
    runner = (
        PipelineRunner(run_store=store, executor=worker)
        if offline
        else PipelineRunner(
            services=RuntimeServices.from_legacy(cast(Any, store)), executor=worker
        )
    )
    result = runner.run(
        RunRequest(
            config=compose_config(config_path),
            options={"run_uri": run_uri, "executor": executor},
        )
    )
    return result, store


def authority_from_args(args: tuple[str, ...]):
    import argparse
    from loom.cli.authority import (
        add_authority_options,
        authority_config_from_namespace,
    )

    parser = argparse.ArgumentParser()
    add_authority_options(parser)
    return authority_config_from_namespace(parser.parse_args(args))
