"""End-to-end smoke tests for cleanup CLI commands."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import cast

import pytest

import loom.cli.clean as clean_command
import loom.cli.gc as gc_command
from loom.authority._repository import initialize_authority_repository
from loom.cli.main import main
from loom.pipeline.cleanup import CollectionCleanupTarget
from loom.pipeline.stores import (
    CleanupCandidateKind,
    LifecycleReason,
    PerRunAuthorityStore,
    path_to_run_uri,
)


pytestmark = pytest.mark.e2e


def test_clean_cli_previews_then_deletes_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    store = cast(PerRunAuthorityStore, repository)
    monkeypatch.setattr(
        clean_command,
        "create_cleanup_authority_store",
        lambda _config, *, owner_id: store,
    )

    preview_stdout = io.StringIO()
    assert (
        main(
            ["clean", run_uri, "--format", "json"],
            stdout=preview_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    preview = json.loads(preview_stdout.getvalue())
    assert preview["result"]["summary"]["selected"] == 1
    assert target.exists()

    delete_stdout = io.StringIO()
    assert (
        main(
            ["clean", run_uri, "--delete", "--yes", "--format", "json"],
            stdout=delete_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    deleted = json.loads(delete_stdout.getvalue())
    assert deleted["result"]["summary"]["deleted"] == 1
    assert not target.exists()


def test_gc_cli_deletes_candidates_without_deleting_run_directories(
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
    monkeypatch.setattr(
        gc_command,
        "create_cleanup_authority_store",
        lambda _config, *, owner_id: store,
    )

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

    stdout = io.StringIO()
    assert (
        main(
            ["gc", str(tmp_path / "runs"), "--delete", "--yes", "--format", "json"],
            stdout=stdout,
            stderr=io.StringIO(),
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["result"]["summary"]["deleted"] == 2
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
