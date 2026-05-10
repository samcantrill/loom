"""Integration smoke tests for the public authority factory."""

from pathlib import Path

import pytest

from loom.pipeline.status import RunStatus
from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityStoreError,
    RunStore,
    create_run_store,
    path_to_run_uri,
)

pytestmark = pytest.mark.integration


def test_create_run_store_uses_transitional_sqlite_authority(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "r1")
    store = create_run_store()

    assert isinstance(store, RunStore)
    revision = store.admit_run(run_uri)
    assert revision.sequence == 1
    assert store.open_run(run_uri).status is RunStatus.CREATED


def test_create_run_store_fails_closed_for_unimplemented_service_backend() -> None:
    config = AuthorityConfig(backend_kind=AuthorityBackendKind.MANAGED_SERVICE)

    with pytest.raises(AuthorityStoreError, match="not implemented"):
        create_run_store(config)
