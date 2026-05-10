"""Contract tests for public authority RunStore and StageStore surfaces."""

from datetime import UTC, datetime, timedelta
from collections.abc import Iterator
from pathlib import Path

import pytest

from loom.pipeline.stores import (
    LocalRunStore,
    RunStore,
    StageStore,
    create_run_store,
    path_to_run_uri,
)
from loom.pipeline.stores.service_authority import LocalAuthorityService
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.support.authority_conformance import (
    PublicAuthorityCase,
    assert_public_authority_lifecycle,
    assert_public_authority_rejects_stale_and_foreign_writes,
)
from tests.support.authority_stores import InMemoryPerRunAuthorityStore

pytestmark = pytest.mark.contract


@pytest.fixture(params=["in-memory", "sqlite", "service"])
def authority_case(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[PublicAuthorityCase]:
    if request.param == "in-memory":
        authority_store = InMemoryPerRunAuthorityStore()
        yield PublicAuthorityCase(
            store=create_run_store(authority_store=authority_store),
            run_uri="file:///runs/r1",
            advance_time=authority_store.advance_time,
        )
        return

    tick = {"seconds": 0}

    def now() -> datetime:
        return datetime(2020, 1, 1, tzinfo=UTC) + timedelta(seconds=tick["seconds"])

    def advance_time(seconds: int) -> None:
        tick["seconds"] += seconds

    run_uri = path_to_run_uri(tmp_path / "r1")
    if request.param == "service":
        with LocalAuthorityService.start() as service:
            yield PublicAuthorityCase(
                store=create_run_store(service.config()),
                run_uri=run_uri,
                advance_time=service.advance_time,
            )
        return

    yield PublicAuthorityCase(
        store=create_run_store(
            authority_store=SQLitePerRunAuthorityStore(clock=now),
        ),
        run_uri=run_uri,
        advance_time=advance_time,
    )


def test_public_factory_returns_authority_run_store() -> None:
    store = create_run_store(authority_store=InMemoryPerRunAuthorityStore())

    assert isinstance(store, RunStore)
    assert isinstance(store.stage_store("file:///runs/r1", "build"), StageStore)


def test_local_run_store_does_not_satisfy_public_authority_run_store(
    tmp_path: Path,
) -> None:
    assert not isinstance(LocalRunStore(root=tmp_path / "runs"), RunStore)


def test_public_authority_contract_records_lifecycle_facts(
    authority_case: PublicAuthorityCase,
) -> None:
    assert_public_authority_lifecycle(authority_case)


def test_public_authority_contract_rejects_stale_and_foreign_writes(
    authority_case: PublicAuthorityCase,
) -> None:
    assert_public_authority_rejects_stale_and_foreign_writes(authority_case)
