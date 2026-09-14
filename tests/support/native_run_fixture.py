"""Execute synthetic consumer fixtures through the native coordinator owner."""

from pathlib import Path

from loom.coordinator import RunRequest
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from loom.pipeline.stores import LocalRunStore
from tests.integration.queue.test_preparation_operations import _service, _request


def run_native_fixture(config_path: Path):
    root = config_path.parent / "native-deployment"
    root.mkdir()
    service = _service(root)
    (root / "projects" / "pipeline.yaml").write_text(config_path.read_text())
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(RunRequest(_request(), "consumer-run"), principal_id="caller")
        operation = daemon.wait_operation("prepare-1", timeout=60).operation
        assert operation.state == "applied", operation
        admission = daemon._wait("consumer-run", timeout_seconds=60)
        return admission, LocalRunStore(service.daemon.run_store_root)
    finally:
        daemon.stop()
