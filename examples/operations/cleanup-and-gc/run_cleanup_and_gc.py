"""Prove preview-first, candidate-only cleanup through public CLI commands."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path
from typing import cast

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import require_mapping, run_cli_json
from loom.artifacts import ArtifactRef
from loom.authority._repository import initialize_authority_repository
from loom.cli import clean as clean_command
from loom.cli import gc as gc_command
from loom.io.uris import path_to_file_uri
from loom.pipeline.status import RunStatus
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.stores import (
    CleanupCandidateKind,
    LifecycleReason,
    PerRunAuthorityStore,
    path_to_run_uri,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


HERE = Path(__file__).resolve().parent


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    fixture = _seed_cleanup_candidates_for_example(output_root, run_root)
    store = fixture.authority_store
    _install_setup_only_cleanup_store(store)

    clean_preview = _result(["clean", fixture.first.run_uri, "--format", "json"])
    if not fixture.first.candidate_path.exists():
        raise RuntimeError("clean preview changed the candidate path")
    clean_delete = _result(
        ["clean", fixture.first.run_uri, "--delete", "--yes", "--format", "json"]
    )
    if fixture.first.candidate_path.exists():
        raise RuntimeError("clean delete did not remove the selected candidate")

    gc_preview = _result(["gc", str(run_root), "--format", "json"])
    if not fixture.second.candidate_path.exists():
        raise RuntimeError("gc preview changed the candidate path")
    gc_delete = _result(
        ["gc", str(run_root), "--delete", "--yes", "--format", "json"]
    )
    if fixture.second.candidate_path.exists():
        raise RuntimeError("gc delete did not remove the selected candidate")

    preserved = all(
        path.exists()
        for path in (
            fixture.first.run_path,
            fixture.second.run_path,
            fixture.first.committed_path,
            fixture.second.committed_path,
            fixture.first.non_candidate_path,
            fixture.second.non_candidate_path,
        )
    )
    if not preserved:
        raise RuntimeError("cleanup changed a run, committed output, or non-candidate")

    print("cleanup_and_gc:")
    print(f"  clean_preview_selected: {clean_preview['summary']['selected']}")
    print(f"  clean_deleted: {clean_delete['summary']['deleted']}")
    print(f"  gc_preview_selected: {gc_preview['summary']['selected']}")
    print(f"  gc_deleted: {gc_delete['summary']['deleted']}")
    print("  candidate_paths_removed: True")
    print("  preserved_paths: True")
    print(f"  first_run_uri: {fixture.first.run_uri}")
    print(f"  second_run_uri: {fixture.second.run_uri}")


def _install_setup_only_cleanup_store(store: PerRunAuthorityStore) -> None:
    """Connect the CLI to this fixture's isolated authority repository.

    This is deliberately private setup, not a supported candidate-authoring API.
    The example actions themselves still enter through ``loom clean`` and
    ``loom gc`` via ``run_cli_json``.
    """

    clean_command.create_cleanup_authority_store = lambda _config, *, owner_id: store
    gc_command.create_cleanup_authority_store = lambda _config, *, owner_id: store


class _CleanupRunFixture:
    def __init__(
        self,
        *,
        run_uri: str,
        run_path: Path,
        candidate_path: Path,
        committed_path: Path,
        non_candidate_path: Path,
    ) -> None:
        self.run_uri = run_uri
        self.run_path = run_path
        self.candidate_path = candidate_path
        self.committed_path = committed_path
        self.non_candidate_path = non_candidate_path


class _CleanupFixture:
    def __init__(
        self,
        *,
        authority_store: PerRunAuthorityStore,
        first: _CleanupRunFixture,
        second: _CleanupRunFixture,
    ) -> None:
        self.authority_store = authority_store
        self.first = first
        self.second = second


def _seed_cleanup_candidates_for_example(
    output_root: Path,
    run_root: Path,
) -> _CleanupFixture:
    """Build an isolated, setup-only authority fixture for public cleanup commands."""

    output_root.mkdir(parents=True, exist_ok=True)
    repository = initialize_authority_repository(
        output_root / "setup-only-authority",
        service_generation="cleanup-example",
    )
    first = _seed_cleanup_run(repository, run_root, "first", "candidate-first")
    second = _seed_cleanup_run(repository, run_root, "second", "candidate-second")
    return _CleanupFixture(
        authority_store=cast(PerRunAuthorityStore, repository),
        first=first,
        second=second,
    )


def _seed_cleanup_run(
    repository: PerRunAuthorityStore,
    run_root: Path,
    name: str,
    candidate_id: str,
) -> _CleanupRunFixture:
    """Create local completed-run facts plus one registered temporary payload."""

    run_path = run_root / name
    run_uri = path_to_run_uri(run_path)
    run_store = SQLitePerRunAuthorityStore(run_uri)
    catalog_store = create_authority_backed_serial_run_store(
        run_root,
        authority_store=run_store,
    )
    catalog_store.create_run(run_uri)
    committed_path = run_path / "artifacts" / "build" / "result.txt"
    candidate_path = run_path / "temporary" / "candidate.txt"
    non_candidate_path = run_path / "temporary" / "keep.txt"
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    committed_path.write_text("committed result\n", encoding="utf-8")
    candidate_path.write_text("registered temporary payload\n", encoding="utf-8")
    non_candidate_path.write_text("not a cleanup candidate\n", encoding="utf-8")

    allocation = run_store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="cleanup-example",
        lease_ttl_seconds=30,
    )
    if allocation.lease is None:
        raise RuntimeError("expected a cleanup fixture stage lease")
    run_store.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={
            "result": ArtifactRef(
                artifact_id="build/result",
                uri=path_to_file_uri(committed_path),
                artifact_type="text",
                codec_key="text.v1",
            )
        },
    )
    run_store.transition_run(run_uri, from_status=RunStatus.CREATED, to_status=RunStatus.RUNNING)
    run_store.transition_run(run_uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED)

    repository.admit_run(run_uri)
    repository.record_cleanup_candidate(
        run_uri,
        candidate_id=candidate_id,
        kind=CleanupCandidateKind.STAGED_PAYLOAD,
        uri=path_to_file_uri(candidate_path),
        reason=LifecycleReason(
            code="temporary_payload",
            detail={"stage_name": "build", "fixture": "setup-only"},
        ),
    )
    return _CleanupRunFixture(
        run_uri=run_uri,
        run_path=run_path,
        candidate_path=candidate_path,
        committed_path=committed_path,
        non_candidate_path=non_candidate_path,
    )


def _result(argv: list[str]) -> dict[str, object]:
    return require_mapping(run_cli_json(argv)["result"])


if __name__ == "__main__":
    main()
