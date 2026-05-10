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
from loom.pipeline.stores.service_authority import LocalAuthorityService

pytestmark = pytest.mark.integration


def test_create_run_store_uses_transitional_sqlite_authority(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "r1")
    store = create_run_store()

    assert isinstance(store, RunStore)
    revision = store.admit_run(run_uri)
    assert revision.sequence == 1
    assert store.open_run(run_uri).status is RunStatus.CREATED


def test_create_run_store_uses_service_authority_backend(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "service-run")

    with LocalAuthorityService.start() as service:
        store = create_run_store(service.config())
        revision = store.admit_run(run_uri)

        assert isinstance(store, RunStore)
        assert revision.sequence == 1
        assert store.open_run(run_uri).status is RunStatus.CREATED
        assert store.capabilities().backend_name == "local-authority-service"


def test_create_run_store_rejects_service_direct_state_path(tmp_path: Path) -> None:
    with LocalAuthorityService.start() as service:
        config = AuthorityConfig(
            backend_kind=AuthorityBackendKind.CO_LOCATED_SERVICE,
            endpoint=service.endpoint,
            state_path=str(tmp_path / "authority.sqlite"),
            metadata=service.config().metadata,
        )

        with pytest.raises(AuthorityStoreError, match="direct state_path"):
            create_run_store(config)


def test_create_run_store_fails_closed_for_unavailable_service() -> None:
    service = LocalAuthorityService.start()
    config = service.config()
    service.stop()

    with pytest.raises(AuthorityStoreError, match="unavailable"):
        create_run_store(config)
