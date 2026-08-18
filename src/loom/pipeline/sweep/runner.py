"""Plan-only sweep orchestration helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from loom.serialization import (
    PlainData,
    PlainDataError,
    ensure_plain_data,
    freeze_plain_data,
    json_dumps_pretty,
    json_loads,
    stable_json_dumps,
)

from .errors import (
    SweepManifestCompatibilityDiagnostic,
    SweepManifestError,
    SweepProtocolError,
)
from .grid import GridSweepProposalProvider
from .manifest import (
    SWEEP_MANIFEST_FILE_NAME,
    TRIALS_MANIFEST_FILE_NAME,
    SweepManifest,
    TrialsManifest,
    check_sweep_manifest_payload,
    check_trials_manifest_payload,
    write_sweep_manifest,
    write_trials_manifest,
)
from .manual import ManualSweepProposalProvider
from .providers import (
    SweepProviderContext,
    SweepProviderIdentity,
    SweepProposalProvider,
    TrialProposal,
    provider_trial_count,
)
from .spec import (
    GridSweepSpec,
    ManualSweepSpec,
    SweepSpec,
    parse_sweep_spec,
    sweep_spec_to_dict,
)
from .trials import SweepTrialRecord

AUTHORED_SWEEP_SPEC_FILE_NAME = "sweep-spec.json"


@dataclass(frozen=True, slots=True)
class SweepPlan:
    """Generated plan artifacts for a finite deterministic sweep."""

    sweep_manifest: SweepManifest
    trials_manifest: TrialsManifest
    authored_spec: Mapping[str, PlainData]
    provider: SweepProviderIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.sweep_manifest, SweepManifest):
            raise SweepProtocolError("sweep_manifest must be a SweepManifest")
        if not isinstance(self.trials_manifest, TrialsManifest):
            raise SweepProtocolError("trials_manifest must be a TrialsManifest")
        if not isinstance(self.provider, SweepProviderIdentity):
            raise SweepProtocolError("provider must be a SweepProviderIdentity")
        try:
            authored_spec = freeze_plain_data(self.authored_spec, path="authored_spec")
        except PlainDataError as exc:
            raise SweepProtocolError("authored_spec must contain plain data") from exc
        if not isinstance(authored_spec, Mapping):
            raise SweepProtocolError("authored_spec must be a mapping")
        object.__setattr__(self, "authored_spec", authored_spec)

    @property
    def sweep_id(self) -> str:
        return self.sweep_manifest.sweep_id

    @property
    def trials(self) -> tuple[SweepTrialRecord, ...]:
        return self.trials_manifest.trials


@dataclass(frozen=True, slots=True)
class SweepPlanPaths:
    """Paths written by ``write_sweep_plan``."""

    sweep_manifest_path: Path
    trials_manifest_path: Path
    authored_spec_path: Path


@dataclass(frozen=True, slots=True)
class SweepPlanCompatibilityResult:
    """Readback result for an existing sweep plan directory."""

    sweep_manifest: SweepManifest | None
    trials_manifest: TrialsManifest | None
    diagnostics: tuple[SweepManifestCompatibilityDiagnostic, ...]

    @property
    def compatible(self) -> bool:
        return (
            not self.diagnostics
            and self.sweep_manifest is not None
            and self.trials_manifest is not None
        )


def provider_for_spec(spec: SweepSpec) -> SweepProposalProvider:
    """Return the first-party provider for a trusted sweep spec."""

    if isinstance(spec, GridSweepSpec):
        return GridSweepProposalProvider(spec)
    if isinstance(spec, ManualSweepSpec):
        return ManualSweepProposalProvider(spec)
    raise SweepProtocolError(f"unsupported sweep spec type {type(spec).__name__}")


def plan_sweep(
    spec: SweepSpec | Mapping[str, object],
    *,
    created_at: str | None = None,
    run_uri_root: str | None = None,
) -> SweepPlan:
    """Expand a trusted first-party sweep spec into manifests."""

    parsed_spec = parse_sweep_spec(spec)
    provider = provider_for_spec(parsed_spec)
    context = SweepProviderContext(
        sweep_id=parsed_spec.sweep_id,
        sweep_name=parsed_spec.sweep_name,
        metadata={"mode": parsed_spec.mode.value},
    )
    expected_count = provider_trial_count(provider)
    if expected_count is None:
        raise SweepProtocolError("built-in sweep planning requires a finite provider")
    _enforce_trial_guard(expected_count, parsed_spec.max_generated_trials)

    proposals = tuple(provider.proposals(context))
    if len(proposals) != expected_count:
        raise SweepProtocolError(
            "finite provider proposal count does not match its declared length"
        )

    timestamp = created_at or _utc_now()
    root = (
        run_uri_root or parsed_spec.run_uri_root or _default_run_uri_root(parsed_spec)
    )
    trials = _canonical_trial_records(
        sweep_id=parsed_spec.sweep_id,
        proposals=proposals,
        run_uri_root=root,
        provider=provider.identity,
    )
    manifest_metadata: dict[str, PlainData] = {
        "mode": parsed_spec.mode.value,
        "run_uri_root": root,
        "plan_fingerprint": _plan_fingerprint(trials),
    }
    if parsed_spec.metadata:
        manifest_metadata["spec_metadata"] = dict(parsed_spec.metadata)
    sweep_manifest = SweepManifest(
        sweep_id=parsed_spec.sweep_id,
        sweep_name=parsed_spec.sweep_name,
        provider=provider.identity,
        created_at=timestamp,
        trial_count=len(trials),
        metadata=manifest_metadata,
    )
    trials_manifest = TrialsManifest(
        sweep_id=parsed_spec.sweep_id,
        trials=trials,
        generated_at=timestamp,
        metadata={"mode": parsed_spec.mode.value},
    )
    return SweepPlan(
        sweep_manifest=sweep_manifest,
        trials_manifest=trials_manifest,
        authored_spec=sweep_spec_to_dict(parsed_spec),
        provider=provider.identity,
    )


def plan_sweep_from_file(
    spec_path: str | Path,
    *,
    created_at: str | None = None,
    run_uri_root: str | None = None,
) -> SweepPlan:
    """Read a trusted JSON sweep spec file and return an in-memory plan."""

    path = Path(spec_path)
    payload = json_loads(path.read_text(encoding="utf-8"), path=str(path))
    if not isinstance(payload, Mapping):
        raise SweepProtocolError("sweep spec file must contain a JSON object")
    return plan_sweep(
        cast(Mapping[str, object], payload),
        created_at=created_at,
        run_uri_root=run_uri_root,
    )


def write_sweep_plan(
    plan: SweepPlan,
    sweep_dir: str | Path,
    *,
    authored_spec_payload: Mapping[str, object] | None = None,
    authored_spec_name: str = AUTHORED_SWEEP_SPEC_FILE_NAME,
) -> SweepPlanPaths:
    """Write generated manifests and a copied/normalized authored spec payload."""

    root = Path(sweep_dir)
    compatibility = check_existing_sweep_plan(root, expected_plan=plan)
    if compatibility.diagnostics:
        codes = ", ".join(diagnostic.code for diagnostic in compatibility.diagnostics)
        raise SweepManifestError(f"incompatible existing sweep plan: {codes}")

    sweep_manifest_path = root / SWEEP_MANIFEST_FILE_NAME
    trials_manifest_path = root / TRIALS_MANIFEST_FILE_NAME
    authored_spec_path = root / authored_spec_name

    write_sweep_manifest(plan.sweep_manifest, sweep_manifest_path)
    write_trials_manifest(plan.trials_manifest, trials_manifest_path)
    payload = (
        authored_spec_payload
        if authored_spec_payload is not None
        else plan.authored_spec
    )
    _write_plain_json(authored_spec_path, payload)

    return SweepPlanPaths(
        sweep_manifest_path=sweep_manifest_path,
        trials_manifest_path=trials_manifest_path,
        authored_spec_path=authored_spec_path,
    )


def read_sweep_plan(sweep_dir: str | Path) -> SweepPlanCompatibilityResult:
    """Read existing generated manifests from a sweep plan directory."""

    return check_existing_sweep_plan(sweep_dir)


def check_existing_sweep_plan(
    sweep_dir: str | Path,
    *,
    expected_plan: SweepPlan | None = None,
) -> SweepPlanCompatibilityResult:
    """Check existing generated manifests for plan-only compatibility."""

    root = Path(sweep_dir)
    sweep_path = root / SWEEP_MANIFEST_FILE_NAME
    trials_path = root / TRIALS_MANIFEST_FILE_NAME
    if not sweep_path.exists() and not trials_path.exists():
        return SweepPlanCompatibilityResult(None, None, ())

    diagnostics: list[SweepManifestCompatibilityDiagnostic] = []
    sweep_manifest: SweepManifest | None = None
    trials_manifest: TrialsManifest | None = None

    if not sweep_path.exists():
        diagnostics.append(
            _diagnostic(
                root,
                SWEEP_MANIFEST_FILE_NAME,
                "missing_sweep_manifest",
                "sweep manifest is missing",
            )
        )
    else:
        try:
            sweep_payload = _read_json_object(sweep_path)
            sweep_manifest, sweep_diagnostics = check_sweep_manifest_payload(
                sweep_payload, sweep_dir=str(root)
            )
        except (OSError, json.JSONDecodeError, SweepManifestError) as exc:
            sweep_diagnostics = (
                _diagnostic(
                    root, SWEEP_MANIFEST_FILE_NAME, "malformed_sweep_manifest", str(exc)
                ),
            )
        diagnostics.extend(sweep_diagnostics)

    expected_sweep_id = (
        expected_plan.sweep_id
        if expected_plan is not None
        else (sweep_manifest.sweep_id if sweep_manifest is not None else None)
    )
    if not trials_path.exists():
        diagnostics.append(
            _diagnostic(
                root,
                TRIALS_MANIFEST_FILE_NAME,
                "missing_trials_manifest",
                "trials manifest is missing",
            )
        )
    else:
        try:
            trials_payload = _read_json_object(trials_path)
            trials_manifest, trials_diagnostics = check_trials_manifest_payload(
                trials_payload,
                sweep_dir=str(root),
                sweep_id=expected_sweep_id,
            )
        except (OSError, json.JSONDecodeError, SweepManifestError) as exc:
            trials_diagnostics = (
                _diagnostic(
                    root,
                    TRIALS_MANIFEST_FILE_NAME,
                    "malformed_trials_manifest",
                    str(exc),
                ),
            )
        diagnostics.extend(trials_diagnostics)

    if expected_plan is not None and not diagnostics:
        diagnostics.extend(
            _plan_match_diagnostics(
                root, expected_plan, sweep_manifest, trials_manifest
            )
        )

    return SweepPlanCompatibilityResult(
        sweep_manifest=sweep_manifest if not diagnostics else None,
        trials_manifest=trials_manifest if not diagnostics else None,
        diagnostics=tuple(diagnostics),
    )


def build_trial_id(index: int) -> str:
    """Return the canonical sweep-local trial ID for a zero-based index."""

    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise SweepProtocolError("trial index must be a non-negative integer")
    return f"trial-{index + 1:04d}"


def build_trial_run_uri(run_uri_root: str, trial_id: str) -> str:
    """Map a sweep-local trial ID under an explicit run URI root."""

    if not isinstance(run_uri_root, str) or not run_uri_root:
        raise SweepProtocolError("run_uri_root must be a non-empty string")
    if not isinstance(trial_id, str) or not trial_id:
        raise SweepProtocolError("trial_id must be a non-empty string")
    root = run_uri_root[:-1] if run_uri_root.endswith("/") else run_uri_root
    return f"{root}/{trial_id}"


def trial_override_expressions(overrides: Mapping[str, PlainData]) -> tuple[str, ...]:
    """Render override facts with the existing Loom override syntax."""

    return tuple(
        f"{path}={stable_json_dumps(value)}" for path, value in overrides.items()
    )


def _canonical_trial_records(
    *,
    sweep_id: str,
    proposals: tuple[TrialProposal, ...],
    run_uri_root: str,
    provider: SweepProviderIdentity,
) -> tuple[SweepTrialRecord, ...]:
    records: list[SweepTrialRecord] = []
    for index, proposal in enumerate(proposals):
        if proposal.trial_index is not None and proposal.trial_index != index:
            raise SweepProtocolError(
                "provider proposal trial_index must match proposal order"
            )
        trial_id = build_trial_id(index)
        metadata: dict[str, PlainData] = {
            "provider": provider.to_dict(),
            "override_expressions": list(
                trial_override_expressions(proposal.overrides)
            ),
        }
        metadata.update(dict(proposal.metadata))
        records.append(
            SweepTrialRecord(
                trial_id=trial_id,
                trial_index=index,
                sweep_id=sweep_id,
                run_uri=build_trial_run_uri(run_uri_root, trial_id),
                provider_trial_id=proposal.provider_trial_id,
                proposal_overrides=dict(proposal.overrides),
                metadata=metadata,
            )
        )
    return tuple(records)


def _plan_match_diagnostics(
    root: Path,
    expected_plan: SweepPlan,
    sweep_manifest: SweepManifest | None,
    trials_manifest: TrialsManifest | None,
) -> tuple[SweepManifestCompatibilityDiagnostic, ...]:
    diagnostics: list[SweepManifestCompatibilityDiagnostic] = []
    if sweep_manifest is None or trials_manifest is None:
        return ()
    if sweep_manifest.sweep_id != expected_plan.sweep_id:
        diagnostics.append(
            _diagnostic(
                root,
                SWEEP_MANIFEST_FILE_NAME,
                "sweep_id_mismatch",
                "existing sweep_id does not match generated plan",
            )
        )
    if sweep_manifest.provider != expected_plan.provider:
        diagnostics.append(
            _diagnostic(
                root,
                SWEEP_MANIFEST_FILE_NAME,
                "provider_mismatch",
                "existing provider does not match generated plan",
            )
        )
    if sweep_manifest.trial_count != expected_plan.sweep_manifest.trial_count:
        diagnostics.append(
            _diagnostic(
                root,
                SWEEP_MANIFEST_FILE_NAME,
                "trial_count_mismatch",
                "existing trial count does not match generated plan",
            )
        )
    if _plan_fingerprint(trials_manifest.trials) != _plan_fingerprint(
        expected_plan.trials
    ):
        diagnostics.append(
            _diagnostic(
                root,
                TRIALS_MANIFEST_FILE_NAME,
                "trial_plan_mismatch",
                "existing trial plan does not match generated plan",
            )
        )
    return tuple(diagnostics)


def _plan_fingerprint(trials: tuple[SweepTrialRecord, ...]) -> str:
    return stable_json_dumps([trial.to_dict() for trial in trials])


def _enforce_trial_guard(count: int, limit: int | None) -> None:
    if limit is not None and count > limit:
        raise SweepProtocolError(
            f"generated trial count {count} exceeds max_generated_trials {limit}"
        )


def _default_run_uri_root(spec: SweepSpec) -> str:
    return f"file://./runs/{spec.sweep_id}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json_object(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SweepManifestError(f"manifest at {path} must be a JSON object")
    return payload


def _write_plain_json(path: Path, payload: Mapping[str, object]) -> None:
    try:
        plain = ensure_plain_data(payload, path=str(path))
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError(
            "authored sweep spec payload must contain plain data"
        ) from exc
    if not isinstance(plain, dict):
        raise SweepProtocolError("authored sweep spec payload must be a mapping")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps_pretty(cast(dict[str, object], plain)), encoding="utf-8")


def _diagnostic(
    root: Path, manifest_name: str, code: str, message: str
) -> SweepManifestCompatibilityDiagnostic:
    return SweepManifestCompatibilityDiagnostic(
        code=code,
        sweep_dir=str(root),
        manifest_name=manifest_name,
        message=message,
        detail={"manifest_name": manifest_name},
    )


__all__ = [
    "AUTHORED_SWEEP_SPEC_FILE_NAME",
    "SweepPlan",
    "SweepPlanPaths",
    "SweepPlanCompatibilityResult",
    "provider_for_spec",
    "plan_sweep",
    "plan_sweep_from_file",
    "write_sweep_plan",
    "read_sweep_plan",
    "check_existing_sweep_plan",
    "build_trial_id",
    "build_trial_run_uri",
    "trial_override_expressions",
]
