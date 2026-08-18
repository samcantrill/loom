"""Sweep projection helpers for workspace coordination stores."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loom.pipeline.stores.coordination import (
    SweepIdentity,
    TrialReference,
    TrialState,
    WorkspaceCoordinationStore,
    WorkspaceIdentity,
)
from loom.pipeline.stores.read_models import BackendRevision
from loom.serialization import PlainData, ensure_plain_data

from .errors import SweepProtocolError

if TYPE_CHECKING:
    from .runner import SweepPlan
    from .trials import SweepTrialRecord


_RUN_STATUS_TO_TRIAL_STATE = {
    "CREATED": TrialState.PENDING,
    "PLANNED": TrialState.PENDING,
    "SUBMITTED": TrialState.RUNNING,
    "RUNNING": TrialState.RUNNING,
    "SUCCEEDED": TrialState.COMPLETED,
    "FAILED": TrialState.FAILED,
    "CANCELLED": TrialState.CANCELLED,
    "INTERRUPTED": TrialState.CANCELLED,
}
_QUEUE_STATUS_TO_TRIAL_STATE = {
    "QUEUED": TrialState.PENDING,
    "CLAIMED": TrialState.CLAIMED,
    "DISPATCHED": TrialState.RUNNING,
    "SUCCEEDED": TrialState.COMPLETED,
    "FAILED": TrialState.FAILED,
    "CANCELLED": TrialState.CANCELLED,
    "UNKNOWN": TrialState.PENDING,
}


@dataclass(frozen=True, slots=True)
class SweepCoordinationIdentityResult:
    """Result of ensuring workspace and sweep coordination identities."""

    sweep_id: str
    workspace_id: str
    workspace_revision: BackendRevision | None
    sweep_revision: BackendRevision | None


@dataclass(frozen=True, slots=True)
class SweepTrialCoordinationResult:
    """Result of recording one trial reference in a coordination store."""

    trial: TrialReference
    write_revision: BackendRevision


@dataclass(frozen=True, slots=True)
class SweepCoordinationProjection:
    """Projection result for a full sweep plan."""

    identity: SweepCoordinationIdentityResult
    trials: tuple[SweepTrialCoordinationResult, ...]

    @property
    def sweep_id(self) -> str:
        return self.identity.sweep_id

    @property
    def workspace_id(self) -> str:
        return self.identity.workspace_id


def ensure_sweep_coordination_identity(
    plan: "SweepPlan",
    coordination_store: WorkspaceCoordinationStore,
    *,
    workspace_id: str,
    workspace_root_uri: str | None = None,
) -> SweepCoordinationIdentityResult:
    """Ensure workspace and sweep identities exist in a coordination store."""

    if not isinstance(workspace_id, str) or not workspace_id:
        raise SweepProtocolError("workspace_id must be a non-empty string")
    workspace_revision = _create_workspace_if_missing(
        coordination_store,
        WorkspaceIdentity(
            workspace_id=workspace_id,
            root_uri=workspace_root_uri,
            metadata={"source": "sweep_coordination"},
        ),
    )
    sweep_revision = _create_sweep_if_missing(
        coordination_store,
        SweepIdentity(
            sweep_id=plan.sweep_id,
            workspace_id=workspace_id,
            metadata=_sweep_metadata(plan),
        ),
    )
    return SweepCoordinationIdentityResult(
        sweep_id=plan.sweep_id,
        workspace_id=workspace_id,
        workspace_revision=workspace_revision,
        sweep_revision=sweep_revision,
    )


def record_sweep_trial_coordination(
    plan: "SweepPlan",
    trial: "SweepTrialRecord",
    coordination_store: WorkspaceCoordinationStore,
    *,
    state: TrialState | str = TrialState.PENDING,
    source_revision: BackendRevision | None = None,
    metadata: Mapping[str, PlainData] | None = None,
) -> SweepTrialCoordinationResult:
    """Record or update one planned trial reference in a coordination store."""

    if trial.sweep_id != plan.sweep_id:
        raise SweepProtocolError("trial sweep_id does not match plan sweep_id")
    state = TrialState(state)
    reference = TrialReference(
        trial_id=trial.trial_id,
        sweep_id=trial.sweep_id,
        run_uri=trial.run_uri,
        state=state,
        revision=source_revision
        or external_trial_revision(
            source="sweep_coordination",
            sweep_id=trial.sweep_id,
            trial_id=trial.trial_id,
            state=state,
        ),
        metadata={
            **_trial_metadata(trial),
            **_plain_mapping({} if metadata is None else metadata, "metadata"),
        },
    )
    write_revision = coordination_store.record_trial(reference)
    return SweepTrialCoordinationResult(
        trial=reference,
        write_revision=write_revision,
    )


def project_sweep_coordination(
    plan: "SweepPlan",
    coordination_store: WorkspaceCoordinationStore,
    *,
    workspace_id: str,
    workspace_root_uri: str | None = None,
    trial_states: Mapping[str, TrialState | str] | None = None,
    trial_metadata: Mapping[str, Mapping[str, PlainData]] | None = None,
) -> SweepCoordinationProjection:
    """Project a full sweep plan into cross-run coordination records."""

    identity = ensure_sweep_coordination_identity(
        plan,
        coordination_store,
        workspace_id=workspace_id,
        workspace_root_uri=workspace_root_uri,
    )
    states = {} if trial_states is None else dict(trial_states)
    metadata_by_trial = {} if trial_metadata is None else dict(trial_metadata)
    results = tuple(
        record_sweep_trial_coordination(
            plan,
            trial,
            coordination_store,
            state=states.get(trial.trial_id, TrialState.PENDING),
            metadata=metadata_by_trial.get(trial.trial_id, {}),
        )
        for trial in plan.trials
    )
    return SweepCoordinationProjection(identity=identity, trials=results)


def trial_state_from_run_status(value: object) -> TrialState:
    """Map an ordinary run status-like object to a coordination trial state."""

    status = _status_value(value)
    try:
        return _RUN_STATUS_TO_TRIAL_STATE[status]
    except KeyError as exc:
        raise SweepProtocolError(
            f"unsupported run status for trial state: {status}"
        ) from exc


def trial_state_from_queue_status(value: object) -> TrialState:
    """Map a queue item/status-like object to a coordination trial state."""

    status = _status_value(value)
    try:
        return _QUEUE_STATUS_TO_TRIAL_STATE[status]
    except KeyError as exc:
        raise SweepProtocolError(
            f"unsupported queue status for trial state: {status}"
        ) from exc


def external_trial_revision(
    *,
    source: str,
    sweep_id: str,
    trial_id: str,
    state: TrialState | str,
) -> BackendRevision:
    """Build a deterministic external revision for non-authority projections."""

    state_value = TrialState(state).value
    return BackendRevision(
        sequence=1,
        token=f"{source}:{sweep_id}:{trial_id}:{state_value}",
    )


def _create_workspace_if_missing(
    store: WorkspaceCoordinationStore,
    identity: WorkspaceIdentity,
) -> BackendRevision | None:
    try:
        return store.create_workspace(identity)
    except ValueError as exc:
        if "workspace already exists" in str(exc):
            return None
        raise


def _create_sweep_if_missing(
    store: WorkspaceCoordinationStore,
    identity: SweepIdentity,
) -> BackendRevision | None:
    try:
        return store.create_sweep(identity)
    except ValueError as exc:
        if "sweep already exists" in str(exc):
            return None
        raise


def _sweep_metadata(plan: "SweepPlan") -> dict[str, PlainData]:
    return {
        "source": "sweep_plan",
        "sweep_name": plan.sweep_manifest.sweep_name,
        "provider": plan.provider.to_dict(),
        "trial_count": plan.sweep_manifest.trial_count,
        "manifest_metadata": dict(plan.sweep_manifest.metadata),
    }


def _trial_metadata(trial: "SweepTrialRecord") -> dict[str, PlainData]:
    return {
        "source": "sweep_plan",
        "trial_index": trial.trial_index,
        "provider_trial_id": trial.provider_trial_id,
        "proposal_overrides": dict(trial.proposal_overrides),
        "trial_metadata": dict(trial.metadata),
    }


def _plain_mapping(value: Mapping[str, PlainData], field: str) -> dict[str, PlainData]:
    normalized = ensure_plain_data(value, path=field)
    if not isinstance(normalized, dict):
        raise SweepProtocolError(f"{field} must be a plain-data mapping")
    return normalized


def _status_value(value: object) -> str:
    raw: Any = getattr(value, "status", value)
    enum_value = getattr(raw, "value", raw)
    if isinstance(enum_value, str):
        return enum_value
    raise SweepProtocolError("status value must be a string or enum-like object")


__all__ = [
    "SweepCoordinationIdentityResult",
    "SweepCoordinationProjection",
    "SweepTrialCoordinationResult",
    "ensure_sweep_coordination_identity",
    "external_trial_revision",
    "project_sweep_coordination",
    "record_sweep_trial_coordination",
    "trial_state_from_queue_status",
    "trial_state_from_run_status",
]
