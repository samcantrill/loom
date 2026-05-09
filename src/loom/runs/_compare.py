"""Private metadata-only run comparison helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from loom.serialization import PlainData, thaw_plain_data
from loom.timestamps import utc_timestamp

from .models import (
    ArtifactSummary,
    CatalogWarning,
    CatalogWarningCode,
    ComparisonEntry,
    ComparisonSection,
    ComparisonStatus,
    RunComparison,
    RunSummary,
    StageSummary,
    SubmittedOperationSummary,
)


def compare_current_runs(
    summaries: Sequence[RunSummary],
    *,
    left_run_uri: str,
    right_run_uri: str,
    warnings: Sequence[CatalogWarning] = (),
) -> RunComparison:
    """Compare two current summaries using persisted metadata only."""

    left = _find_summary(summaries, left_run_uri)
    right = _find_summary(summaries, right_run_uri)
    comparison_warnings = list(warnings)
    if left is None:
        comparison_warnings.append(
            _warning(
                CatalogWarningCode.DISAPPEARED_RUN,
                "left run was not found in current catalog results",
                run_uri=left_run_uri,
            )
        )
    if right is None:
        comparison_warnings.append(
            _warning(
                CatalogWarningCode.DISAPPEARED_RUN,
                "right run was not found in current catalog results",
                run_uri=right_run_uri,
            )
        )

    sections = _sections(left, right)
    return RunComparison(
        left_run_uri=left_run_uri,
        right_run_uri=right_run_uri,
        sections=sections,
        warnings=tuple(comparison_warnings),
        checked_at=utc_timestamp(),
    )


def compare_summaries(left: RunSummary | None, right: RunSummary | None) -> tuple[ComparisonSection, ...]:
    """Build deterministic metadata comparison sections for two summaries."""

    return _sections(left, right)


def _find_summary(
    summaries: Sequence[RunSummary], run_uri: str
) -> RunSummary | None:
    for summary in summaries:
        if summary.run_uri == run_uri:
            return summary
    return None


def _sections(
    left: RunSummary | None, right: RunSummary | None
) -> tuple[ComparisonSection, ...]:
    return (
        ComparisonSection(name="run", entries=_run_entries(left, right)),
        ComparisonSection(name="fingerprints", entries=_fingerprint_entries(left, right)),
        ComparisonSection(name="stages", entries=_stage_entries(left, right)),
        ComparisonSection(name="artifacts", entries=_artifact_entries(left, right)),
        ComparisonSection(name="execution", entries=_execution_entries(left, right)),
        ComparisonSection(name="provenance", entries=_provenance_entries(left, right)),
    )


def _run_entries(
    left: RunSummary | None, right: RunSummary | None
) -> tuple[ComparisonEntry, ...]:
    return tuple(
        _scalar_entry(left, right, key, field)
        for key, field in (
            ("run.status", "status"),
            ("run.created_at", "created_at"),
            ("run.updated_at", "updated_at"),
            ("run.started_at", "started_at"),
            ("run.finished_at", "finished_at"),
        )
    )


def _fingerprint_entries(
    left: RunSummary | None, right: RunSummary | None
) -> tuple[ComparisonEntry, ...]:
    return tuple(
        _scalar_entry(left, right, key, field)
        for key, field in (
            ("fingerprints.config", "config_fingerprint"),
            ("fingerprints.pipeline", "pipeline_fingerprint"),
        )
    )


def _execution_entries(
    left: RunSummary | None, right: RunSummary | None
) -> tuple[ComparisonEntry, ...]:
    entries = [
        _scalar_entry(left, right, "execution.executor", "executor"),
        _scalar_entry(left, right, "execution.backend", "backend"),
    ]
    entries.extend(
        _keyed_entries(
            _submitted_map(None if left is None else left.submitted_operations),
            _submitted_map(None if right is None else right.submitted_operations),
            prefix="execution.submitted",
            fields=(
                ("backend", "backend"),
                ("mode", "mode"),
                ("state", "state"),
                ("active", "active"),
                ("summary_counts", "summary_counts"),
            ),
        )
    )
    return tuple(entries)


def _provenance_entries(
    left: RunSummary | None, right: RunSummary | None
) -> tuple[ComparisonEntry, ...]:
    return (_scalar_entry(left, right, "provenance.git.commit", "git_commit"),)


def _stage_entries(
    left: RunSummary | None, right: RunSummary | None
) -> tuple[ComparisonEntry, ...]:
    return tuple(
        _keyed_entries(
            _stage_map(None if left is None else left.stages),
            _stage_map(None if right is None else right.stages),
            prefix="stages",
            fields=(
                ("status", "status"),
                ("attempt", "attempt"),
                ("fingerprint", "fingerprint"),
                ("started_at", "started_at"),
                ("finished_at", "finished_at"),
            ),
        )
    )


def _artifact_entries(
    left: RunSummary | None, right: RunSummary | None
) -> tuple[ComparisonEntry, ...]:
    return tuple(
        _keyed_entries(
            _artifact_map(None if left is None else left.artifacts),
            _artifact_map(None if right is None else right.artifacts),
            prefix="artifacts",
            fields=(
                ("artifact_id", "artifact_id"),
                ("logical_name", "logical_name"),
                ("uri", "uri"),
                ("artifact_type", "artifact_type"),
                ("checksum", "checksum"),
                ("fingerprint", "fingerprint"),
                ("producer_stage", "producer_stage"),
            ),
        )
    )


def _scalar_entry(
    left: RunSummary | None, right: RunSummary | None, key: str, field: str
) -> ComparisonEntry:
    left_value = None if left is None else getattr(left, field)
    right_value = None if right is None else getattr(right, field)
    return _entry(key, left_value, right_value)


def _keyed_entries(
    left: Mapping[str, object],
    right: Mapping[str, object],
    *,
    prefix: str,
    fields: Sequence[tuple[str, str]],
) -> Iterable[ComparisonEntry]:
    for item_key in sorted(set(left) | set(right)):
        left_item = left.get(item_key)
        right_item = right.get(item_key)
        if left_item is None or right_item is None:
            status = (
                ComparisonStatus.LEFT_ONLY
                if right_item is None
                else ComparisonStatus.RIGHT_ONLY
            )
            yield ComparisonEntry(
                key=f"{prefix}.{item_key}",
                status=status,
                left=_plain_value(_item_identity(left_item)),
                right=_plain_value(_item_identity(right_item)),
            )
            continue
        for entry_name, attr in fields:
            yield _entry(
                f"{prefix}.{item_key}.{entry_name}",
                getattr(left_item, attr),
                getattr(right_item, attr),
                details={"item": item_key},
            )


def _entry(
    key: str,
    left: object,
    right: object,
    *,
    details: Mapping[str, PlainData] | None = None,
) -> ComparisonEntry:
    plain_left = _plain_value(left)
    plain_right = _plain_value(right)
    if plain_left is None or plain_right is None:
        status = ComparisonStatus.UNKNOWN
    elif plain_left == plain_right:
        status = ComparisonStatus.SAME
    else:
        status = ComparisonStatus.DIFFERENT
    return ComparisonEntry(
        key=key,
        status=status,
        left=plain_left,
        right=plain_right,
        details={} if details is None else details,
    )


def _stage_map(stages: Sequence[StageSummary] | None) -> Mapping[str, StageSummary]:
    if stages is None:
        return {}
    return {stage.stage_name: stage for stage in stages}


def _artifact_map(
    artifacts: Sequence[ArtifactSummary] | None,
) -> Mapping[str, ArtifactSummary]:
    if artifacts is None:
        return {}
    output: dict[str, ArtifactSummary] = {}
    for artifact in artifacts:
        key = artifact.logical_name or artifact.artifact_id
        if key in output:
            key = artifact.artifact_id
        if key in output:
            suffix = 2
            while f"{key}#{suffix}" in output:
                suffix += 1
            key = f"{key}#{suffix}"
        output[key] = artifact
    return output


def _submitted_map(
    operations: Sequence[SubmittedOperationSummary] | None,
) -> Mapping[str, SubmittedOperationSummary]:
    if operations is None:
        return {}
    return {operation.submission_id: operation for operation in operations}


def _item_identity(item: object | None) -> object | None:
    if item is None:
        return None
    if isinstance(item, StageSummary):
        return item.stage_name
    if isinstance(item, ArtifactSummary):
        return item.logical_name or item.artifact_id
    if isinstance(item, SubmittedOperationSummary):
        return item.submission_id
    return None


def _plain_value(value: object | None) -> PlainData:
    if value is None:
        return None
    return thaw_plain_data(value)


def _warning(
    code: CatalogWarningCode,
    message: str,
    *,
    run_uri: str,
) -> CatalogWarning:
    return CatalogWarning(code=code, message=message, run_uri=run_uri)


__all__ = ["compare_current_runs", "compare_summaries"]
