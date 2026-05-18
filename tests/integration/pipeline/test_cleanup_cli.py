"""Integration coverage for cleanup CLI command builders."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

import loom.cli.clean as clean_command
import loom.cli.gc as gc_command
from loom.authority._repository import initialize_authority_repository
from loom.pipeline.cleanup import CollectionCleanupTarget
from loom.pipeline.stores import (
    CleanupCandidateKind,
    LifecycleReason,
    PerRunAuthorityStore,
    path_to_run_uri,
)


pytestmark = pytest.mark.integration


def test_clean_builder_deletes_selected_candidate_and_records_result(
    tmp_path: Path,
) -> None:
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )
    run_uri, target = _cleanup_run(
        repository,
        tmp_path,
        run_name="run-1",
        candidate_id="candidate-1",
    )

    preview = clean_command.build_clean_result(
        run_uri,
        authority_store=cast(PerRunAuthorityStore, repository),
    )
    delete = clean_command.build_clean_result(
        run_uri,
        delete=True,
        yes=True,
        authority_store=cast(PerRunAuthorityStore, repository),
    )

    assert preview.report.summary["selected"] == 1
    assert delete.result is not None
    assert delete.result.result.summary["deleted"] == 1
    assert not target.exists()
    assert repository.list_cleanup_results(run_uri) == (delete.result,)


def test_gc_builder_uses_collection_targets_without_deleting_run_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = initialize_authority_repository(
        tmp_path / "authority",
        service_generation="generation-1",
    )
    first_uri, first_target = _cleanup_run(
        repository,
        tmp_path,
        run_name="run-1",
        candidate_id="candidate-1",
    )
    second_uri, second_target = _cleanup_run(
        repository,
        tmp_path,
        run_name="run-2",
        candidate_id="candidate-2",
    )
    store = cast(PerRunAuthorityStore, repository)

    def collection_targets(collection: Path, authority_store: PerRunAuthorityStore):
        assert collection == tmp_path / "runs"
        assert authority_store is store
        return (
            CollectionCleanupTarget(
                run_uri=first_uri,
                store=authority_store,
                managed_roots=clean_command.managed_roots_for_run(first_uri),
            ),
            CollectionCleanupTarget(
                run_uri=second_uri,
                store=authority_store,
                managed_roots=clean_command.managed_roots_for_run(second_uri),
            ),
        ), ()

    monkeypatch.setattr(gc_command, "_collection_cleanup_targets", collection_targets)

    result = gc_command.build_gc_result(
        tmp_path / "runs",
        delete=True,
        yes=True,
        authority_store=store,
    )

    assert result.result is not None
    assert result.result.summary["deleted"] == 2
    assert not first_target.exists()
    assert not second_target.exists()
    assert (tmp_path / "runs" / "run-1").is_dir()
    assert (tmp_path / "runs" / "run-2").is_dir()


def _cleanup_run(
    repository,
    tmp_path: Path,
    *,
    run_name: str,
    candidate_id: str,
) -> tuple[str, Path]:
    run_path = tmp_path / "runs" / run_name
    target = run_path / "tmp" / "payload.txt"
    target.parent.mkdir(parents=True)
    target.write_text("payload", encoding="utf-8")
    run_uri = path_to_run_uri(run_path)
    repository.admit_run(run_uri)
    repository.record_cleanup_candidate(
        run_uri,
        candidate_id=candidate_id,
        kind=CleanupCandidateKind.STAGED_PAYLOAD,
        uri=path_to_run_uri(target),
        reason=LifecycleReason(
            code="temporary_payload",
            detail={"stage_name": "build"},
        ),
    )
    return run_uri, target
