"""Managed preparation stage and coordinator publication wiring.

Only the selected worker composes trusted project configuration. Reports carry
plain native evidence; decoding and publishing them never import project recipes
or call the composer on the coordinator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
from typing import Any, cast

from loom.artifacts import ArtifactRef
from loom.diagnostics.models import (
    PreflightCheckStatus,
    PreflightCheckResult,
    PreflightSeverity,
    PreflightGroup,
    PreflightRequest,
    PreflightResult,
    PreflightStatus,
)
from loom.diagnostics.preflight import run_preflight_composed
from loom.errors import SerializationError, ValidationError
from loom.io.codecs.errors import CodecDecodeError
from loom.pipeline.context import StageContext
from loom.pipeline.orchestration import ExecutionRequirement
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.runtime.options import RunOptions
from loom.pipeline.runtime import merge_config_run_options
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.pipeline.stores.errors import ArtifactChecksumMismatchError, ArtifactStoreError
from loom.queue._preparation_operations import (
    PreparationInstallationMismatch,
    PreparationReport,
)
from loom.queue._remote_stage_execution import (
    ResidentProfileDescriptor,
    _reject_path_bearing_data,
)
from loom.queue.deployment import CoordinatorServiceConfig
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue.local_daemon import LocalDaemonAdmission, LocalDaemonConfig
from loom.queue.local_daemon_execution import load_managed_local_intent
from loom.queue.managed_local_preparation import (
    ManagedLocalPreparationReceipt,
    _pipeline_from_resolved,
    _recipe_manifest_data,
    _runtime_for_service,
    _validate_preparation_service,
    prepare_managed_run,
)
from loom.queue.preparation import (
    LOCAL_PREPARATION_SCOPE,
    _local_scope,
    _project_binding,
    _require_local_binding,
    PREPARATION_INPUT_CONTEXT_ENV,
    PREPARATION_STAGE_TARGET,
    PreparationChildInput,
    PrepareRunRequest,
    SharedInputReceipt,
    resolve_shared_input,
    _invocation_data,
)
from loom.serialization import PlainData, ensure_plain_data, stable_json_bytes
from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE, bind_snapshot, scope as shared_scope, stage_scope, validate_workload


_PREPARATION_GROUPS = (
    PreflightGroup.CONFIG,
    PreflightGroup.PIPELINE,
    PreflightGroup.SELECTORS,
    PreflightGroup.RUNTIME,
)
_REPORT_FIELDS = {
    "schema_version",
    "operation_id",
    "input_manifest_digest",
    "preparation_profile",
    "profile_descriptor",
    "composition",
    "execution_requirements",
    "preflight",
    "invocation",
    "effective_run_options",
}


class PreparationStage:
    """Compose captured inputs once in the selected existing managed installation."""

    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        binding = PreparationChildInput.from_dict(context.stage_config)
        private = _worker_context()
        profile = ResidentProfileDescriptor.from_dict(private["profile_descriptor"])
        if shared_scope(private.get("shared_scope")) != binding.shared_scope:
            raise QueueConflictError("preparation shared policy identity conflicts")
        if _local_scope(private.get("local_scope")) != binding.local_scope:
            raise QueueConflictError("preparation local policy identity conflicts")
        if _project_binding(private.get("project_preparation")) != binding.project_preparation:
            raise QueueConflictError("preparation project processor identity conflicts")
        if profile.to_dict() != dict(binding.profile_descriptor):
            raise QueueConflictError("preparation installation_mismatch")
        if isinstance(binding.input_receipt, SharedInputReceipt):
            roots = cast(Mapping[str, str], private["shared_roots"])
            captured = resolve_shared_input(
                binding.input_receipt,
                shared_roots={alias: Path(path) for alias, path in roots.items()},
            )
        else:
            # The native workspace verifies extraction before acceptance and
            # again while binding this child to its retained supervisor launch.
            captured = Path(cast(str, private["staged_directory"]))
        config_path = captured / binding.config_path
        # The capture manifest is authoritative. A different readable file in the
        # directory must not become an implicit configuration input.
        if not config_path.is_file() or config_path.is_symlink():
            raise QueueServiceError(
                "preparation source_unavailable: selected config is absent"
            )
        composed = _compose_worker_config(
            config_path,
            overlays=tuple(captured / path for path in binding.overlays),
            overrides=binding.overrides,
        )
        # Includes and overlays are trusted config, but cannot escape the captured closure.
        for source in cast(Any, composed).source_artifacts:
            if source.kind == "recipe":
                continue  # Installed recipe identity is qualified by the worker profile.
            path = Path(source.path).resolve()
            if not path.is_relative_to(captured.resolve()) or not path.is_file():
                raise QueueServiceError(
                    "preparation composition dependency is outside captured inputs"
                )
        preflight = run_preflight_composed(
            composed,
            PreflightRequest(
                config_path=config_path,
                cwd=captured,
                groups=_PREPARATION_GROUPS,
                runtime_options=binding.run_options,
            ),
        )
        composition = _composition_data(composed)
        if preflight.status != PreflightStatus.FAIL:
            _bind_local_snapshot(
                cast(dict[str, PlainData], composition["resolved"]),
                binding.local_scope,
                redacted=cast(dict[str, PlainData], composition["redacted"]),
            )
        if binding.shared_scope is not None and preflight.status != PreflightStatus.FAIL:
            bind_snapshot(cast(dict[str, PlainData], composition["resolved"]), binding.shared_scope,
                          redacted=cast(dict[str, PlainData], composition["redacted"]))
        provenance = cast(dict[str, PlainData], composition["provenance"])
        metadata = cast(dict[str, PlainData], provenance["metadata"])
        metadata["loom_invocation"] = _invocation_data(binding)
        effective_options = None
        if preparation_checks_allow_publication(preflight):
            effective_options = merge_config_run_options(
                cast(Any, composed).resolved, explicit=binding.run_options
            )

        requested_composition = deepcopy(composition)
        project_result = None
        if binding.project_preparation is not None and preparation_checks_allow_publication(preflight):
            composition, project_result, preflight = _inspect_project(
                composition, effective_options, binding, preflight
            )

        verification = None
        if binding.candidate is not None and preparation_checks_allow_publication(preflight):
            verification = _verify_project_candidate(binding, composition, effective_options, project_result)

        requirements: dict[str, PlainData] = {}
        if preflight.status != PreflightStatus.FAIL:
            pipeline = _pipeline_from_resolved(
                cast(Mapping[str, object], composition["resolved"])
            )
            requirement = _profile_requirement(profile)
            requirements = {
                name: requirement.to_dict() for name in pipeline.stage_names
            }
        report: dict[str, PlainData] = {
            "schema_version": binding.to_dict()["schema_version"],
            **({"candidate": dict(binding.candidate) if binding.candidate is not None else None,
                "verification": verification} if "candidate" in binding.to_dict() else {}),
            **({"project_preparation": dict(binding.project_preparation),
                "requested_composition": requested_composition,
                "project_result": project_result} if binding.project_preparation is not None else {}),
            **({"shared_scope": dict(binding.shared_scope)} if binding.shared_scope is not None else {}),
            **({"local_scope": dict(binding.local_scope)} if binding.local_scope is not None else {}),
            "operation_id": binding.operation_id,
            "input_manifest_digest": binding.input_receipt.manifest_digest,
            "preparation_profile": binding.preparation_profile,
            "profile_descriptor": profile.to_dict(),
            "composition": composition,
            "execution_requirements": requirements,
            "preflight": preflight.to_dict(),
            "invocation": _invocation_data(binding),
            "effective_run_options": None
            if effective_options is None
            else effective_options.to_dict(),
        }
        return {
            "report": context.save_artifact(
                "report", report, artifact_type="json", codec_key="json.v1"
            )
        }


def _inspect_project(
    composition: dict[str, PlainData], options: RunOptions | None,
    binding: PreparationChildInput, preflight: PreflightResult,
) -> tuple[dict[str, PlainData], dict[str, PlainData] | None, PreflightResult]:
    assert binding.project_preparation is not None and options is not None
    selected = _plain_mapping(binding.project_preparation["processor"])
    try:
        module, attribute = cast(str, selected["callable"]).split(":")
        processor = importlib.import_module(module)
        for part in attribute.split("."):
            processor = getattr(processor, part)
        request: dict[str, PlainData] = {
            "schema_version": selected["schema_version"],
            **({"operation": "prepare"} if selected["schema_version"] == 2 else {}),
            "composition": deepcopy(composition),
            "effective_run_options": options.to_dict(),
            "invocation": _invocation_data(binding),
            "operation_id": binding.operation_id,
            "input_manifest_digest": binding.input_receipt.manifest_digest,
            "preparation_profile": binding.preparation_profile,
            "profile_descriptor": dict(binding.profile_descriptor),
            **({"shared_scope": dict(binding.shared_scope)} if binding.shared_scope is not None else {"local_scope": dict(binding.local_scope or {})}),
            "project_preparation": dict(binding.project_preparation),
        }
        result = _plain_mapping(cast(Any, processor)(request))
        if set(result) != {"schema_version", "composition", "evidence", "reconciliation_key"}:
            raise QueueConflictError("project preparation result fields are invalid")
        checked = _plain_mapping(result.pop("composition"))
        _validate_project_result(composition, checked, result, binding)
    except Exception as exc:
        # Project exceptions may contain paths or secrets. Retain the failure class,
        # never unchecked exception text, in the existing native diagnostic owner.
        check = PreflightCheckResult(
            "config.project_preparation", PreflightGroup.CONFIG,
            PreflightCheckStatus.FAIL, PreflightSeverity.ERROR,
            "Installed project preparation failed",
            {"applicability": "required", "error_type": type(exc).__name__},
        )
        return composition, None, PreflightResult((*preflight.checks, check), preflight.groups)
    check = PreflightCheckResult(
        "config.project_preparation", PreflightGroup.CONFIG,
        PreflightCheckStatus.PASS, PreflightSeverity.INFO,
        "Installed project checked the final invocation", {"applicability": "required"},
    )
    return checked, result, PreflightResult((*preflight.checks, check), preflight.groups)


def _checked_project_uri(binding: PreparationChildInput, result: Mapping[str, PlainData]) -> str:
    from loom.queue.preparation import project_target_from_key

    assert binding.project_preparation is not None
    if binding.project_preparation["target_run_uri"] is not None:
        return cast(str, binding.project_preparation["target_run_uri"])
    return project_target_from_key(binding.project_preparation, _plain_mapping(result["reconciliation_key"]))


def _verify_project_candidate(binding: PreparationChildInput, composition: Mapping[str, PlainData],
                              options: RunOptions | None, project_result: Mapping[str, PlainData] | None) -> dict[str, PlainData]:
    from loom.fingerprints import hash_mapping
    from loom.serialization import thaw_plain_data

    assert binding.project_preparation is not None and binding.candidate is not None
    selected = _plain_mapping(binding.project_preparation["processor"])
    module, attribute = cast(str, selected["callable"]).split(":")
    processor = importlib.import_module(module)
    for part in attribute.split("."):
        processor = getattr(processor, part)
    candidate = _plain_mapping(thaw_plain_data(binding.candidate))
    expected = {"schema_version": 1, "candidate_digest": hash_mapping(candidate), "verdict": "verified"}
    try:
        response = _plain_mapping(cast(Any, processor)({
            "schema_version": 2, "operation": "verify_candidate", "candidate": candidate,
            "composition": deepcopy(composition), "project_result": project_result,
            "effective_run_options": None if options is None else options.to_dict(),
            "operation_id": binding.operation_id, "invocation": _invocation_data(binding),
            "input_manifest_digest": binding.input_receipt.manifest_digest,
            "profile_descriptor": dict(binding.profile_descriptor),
            "project_preparation": dict(binding.project_preparation),
            **({"shared_scope": dict(binding.shared_scope)} if binding.shared_scope is not None else {"local_scope": dict(binding.local_scope or {})}),
        }))
        if response != expected:
            raise QueueConflictError("candidate verification result conflicts")
    except Exception as exc:
        return {**expected, "verdict": "rejected", "error_type": type(exc).__name__}
    return expected


def _recovery_config(snapshot: dict[str, PlainData], name: str) -> dict[str, PlainData]:
    pipeline = snapshot.get("pipeline")
    if not isinstance(pipeline, dict):
        raise QueueConflictError("project recovery requires an existing pipeline")
    stages = pipeline.get("stages")
    if not isinstance(stages, list):
        raise QueueConflictError("project recovery requires an existing stage declaration")
    matches = [stage for stage in stages if isinstance(stage, dict) and stage.get("name") == name]
    if len(matches) != 1 or not isinstance(matches[0].get("config"), dict):
        raise QueueConflictError("project recovery requires an existing stage config")
    # Return the original dictionary: comparison strips only these finite fields.
    return cast(dict[str, PlainData], matches[0]["config"])


def _validate_project_result(
    original: dict[str, PlainData], checked: dict[str, PlainData],
    result: dict[str, PlainData], binding: PreparationChildInput,
) -> None:
    assert binding.project_preparation is not None
    selected = _plain_mapping(binding.project_preparation["processor"])
    if (set(result) != {"schema_version", "evidence", "reconciliation_key"}
        or type(result["schema_version"]) is not int or result["schema_version"] != selected["schema_version"]):
        raise QueueConflictError("unsupported project preparation result capability")
    evidence = _plain_mapping(result["evidence"])
    if set(evidence) != {"namespace", "payload"} or evidence["namespace"] != selected["evidence_namespace"]:
        raise QueueConflictError("project preparation evidence namespace conflicts")
    _plain_mapping(evidence["payload"])
    key = result["reconciliation_key"]
    if key is not None:
        key = _plain_mapping(key)
        digest = key.get("digest")
        if (set(key) != {"namespace", "version", "digest"}
            or key["namespace"] != selected["evidence_namespace"]
            or type(key["version"]) is not int or key["version"] != 1
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)):
            raise QueueConflictError("project preparation reconciliation key is invalid")
    if binding.project_preparation["target_run_uri"] is None and key is None:
        raise QueueConflictError("reconciled preparation requires a complete key")
    before, after = deepcopy(original), deepcopy(checked)
    for view in ("resolved", "redacted"):
        requested = cast(dict[str, PlainData], before.get(view))
        augmented = cast(dict[str, PlainData], after.get(view))
        if not isinstance(requested, dict) or not isinstance(augmented, dict):
            raise QueueConflictError("project preparation snapshot is invalid")
        if "scientific_evidence" not in augmented:
            raise QueueConflictError("project preparation evidence is missing from snapshot")
        if view == "resolved" and augmented["scientific_evidence"] != evidence["payload"]:
            raise QueueConflictError("project preparation snapshot evidence conflicts")
        requested.pop("scientific_evidence", None)
        augmented.pop("scientific_evidence")
        stage = selected["recovery_stage"]
        if stage is not None:
            old_config = _recovery_config(requested, cast(str, stage))
            new_config = _recovery_config(augmented, cast(str, stage))
            recovery = _plain_mapping(new_config.get("recovery"))
            if set(recovery) != {"run_uri", "resume_fingerprint", "environment_fingerprint"}:
                raise QueueConflictError("project recovery fields are invalid")
            if view == "resolved":
                if (recovery["run_uri"] != _checked_project_uri(binding, result)
                    or recovery["environment_fingerprint"] != binding.profile_descriptor["environment_fingerprint"]
                    or not isinstance(recovery["resume_fingerprint"], str)
                    or not recovery["resume_fingerprint"]):
                    raise QueueConflictError("project recovery target or installation conflicts")
            elif recovery["run_uri"] != "<redacted>":
                raise QueueConflictError("project recovery locator must be redacted")
            old_config.pop("recovery", None)
            new_config.pop("recovery")
    if stable_json_bytes(before) != stable_json_bytes(after):
        raise QueueConflictError("project preparation changed requested data outside derived destinations")
    _pipeline_from_resolved(cast(Mapping[str, object], checked["resolved"]))


def _bind_local_snapshot(
    snapshot: dict[str, PlainData],
    scope: Mapping[str, PlainData] | None,
    *,
    redacted: dict[str, PlainData] | None = None,
) -> None:
    """Validate resolved locality and annotate executable and diagnostic views."""
    pipeline = _pipeline_from_resolved(snapshot)
    for stage in pipeline.stages:
        if LOCAL_PREPARATION_SCOPE in stage.fingerprint_fields or SHARED_EXECUTION_SCOPE in stage.fingerprint_fields:
            raise QueueConflictError("captured configuration cannot select protected preparation scope")
        if scope is not None:
            target = stage.placement.get("target")
            if target is not None and target != scope["agent_id"]:
                raise QueueConflictError("local preparation conflicts with requested hard target")
            route = stage.placement.get("execution_route")
            if route is not None and route != {"kind": "managed_agent"}:
                raise QueueConflictError("local preparation requires the managed agent route")
    if scope is None:
        return
    # Redaction may mask valid declarations (for example an output named tokens).
    # Annotate that diagnostic view without parsing it or restoring authored data.
    for view in (snapshot,) if redacted is None else (snapshot, redacted):
        definition = cast(dict[str, PlainData], view["pipeline"])
        for stage in cast(list[dict[str, PlainData]], definition["stages"]):
            stage["placement"] = {
                **cast(dict[str, PlainData], stage.get("placement", {})),
                "target": scope["agent_id"],
            }
            stage["fingerprint"] = {
                **cast(dict[str, PlainData], stage.get("fingerprint", {})),
                LOCAL_PREPARATION_SCOPE: dict(scope),
            }


def _compose_worker_config(
    config_path: Path,
    *,
    overlays: tuple[Path, ...] = (),
    overrides: tuple[str, ...] = (),
) -> object:
    from weave import RecipeCatalog, compose_config
    from loom.plugins import list_entry_points, load_recipe_entry_points
    from loom.plugins.entrypoints import LOOM_RECIPES_GROUP

    # This is an explicit composition step inside the qualified worker process.
    # The existing strict plugin loader owns discovery/duplicates/import failures.
    catalog = RecipeCatalog()
    records = list_entry_points(groups=(LOOM_RECIPES_GROUP,))
    load_recipe_entry_points(records, catalog, strict=True)
    return compose_config(
        config_path, recipe_catalog=catalog, overlays=overlays, overrides=overrides
    )


def _worker_context() -> Mapping[str, PlainData]:
    encoded = os.environ.get(PREPARATION_INPUT_CONTEXT_ENV)
    if encoded is None:
        raise QueueServiceError("preparation requires its managed worker input binding")
    try:
        value = json.loads(encoded)
        if (
            not isinstance(value, dict)
            or (set(value) - {"local_scope", "project_preparation", "shared_scope"}) not in (
                {"schema_version", "profile_descriptor", "shared_roots"},
                {"schema_version", "profile_descriptor", "staged_directory"},
            )
            or type(value["schema_version"]) is not int
            or value["schema_version"] not in (1, 2, 3, 4)
            or (value["schema_version"] in (2, 3)) != ("local_scope" in value)
            or (value["schema_version"] != 4 and (value["schema_version"] == 3) != ("project_preparation" in value))
            or (value["schema_version"] == 4) != ("shared_scope" in value)
            or not isinstance(value.get("shared_roots", {}), dict)
            or any(
                not isinstance(alias, str)
                or not isinstance(path, str)
                or not Path(path).is_absolute()
                for alias, path in value.get("shared_roots", {}).items()
            )
            or (
                "staged_directory" in value
                and (not isinstance(value["staged_directory"], str)
                     or not Path(value["staged_directory"]).is_absolute())
            )
        ):
            raise ValueError
        return cast(Mapping[str, PlainData], value)
    except (ValueError, TypeError) as exc:
        raise QueueServiceError("preparation managed input context is invalid") from exc


def _composition_data(composed: object) -> dict[str, PlainData]:
    return {
        "resolved": _plain_mapping(getattr(composed, "resolved", None)),
        "redacted": _plain_mapping(getattr(composed, "redacted", None)),
        "manifest": _plain_mapping(cast(Any, composed).manifest.to_dict()),
        "recipe_manifest": list(
            cast(tuple[PlainData, ...], _recipe_manifest_data(composed))
        ),
        "provenance": _plain_mapping(cast(Any, composed).provenance.to_dict()),
    }


@dataclass(frozen=True, slots=True)
class _PlainEvidence:
    value: Mapping[str, PlainData]

    def to_dict(self) -> dict[str, PlainData]:
        return _plain_mapping(self.value)


@dataclass(frozen=True, slots=True)
class _ReceivedComposition:
    resolved: Mapping[str, PlainData]
    redacted: Mapping[str, PlainData]
    manifest: _PlainEvidence
    recipe_manifest: tuple[dict[str, PlainData], ...]
    provenance: _PlainEvidence
    effective_run_options: RunOptions | None = None
    project_preparation: Mapping[str, PlainData] | None = None
    project_result: Mapping[str, PlainData] | None = None


def decode_preparation_report(
    value: object,
    *,
    expected: PreparationChildInput,
) -> tuple[object, dict[str, ExecutionRequirement], PreflightResult]:
    """Decode one committed child's report after its durable artifact join.

    The coordinator operation owner must first establish the committed artifact's
    child/run/assignment identity. This function checks report identity and native
    value contracts, without executing or recomposing the reported configuration.
    Malformed native values raise QueueConflictError for terminal report rejection.
    """
    try:
        return _decode_preparation_report(value, expected=expected)
    except (ValueError, ValidationError, SerializationError) as exc:
        raise QueueConflictError("preparation report native evidence is invalid") from exc


def _decode_preparation_report(
    value: object,
    *,
    expected: PreparationChildInput,
) -> tuple[object, dict[str, ExecutionRequirement], PreflightResult]:
    report = _plain_mapping(value)
    if (
        set(report) != (_REPORT_FIELDS | ({"shared_scope"} if expected.shared_scope is not None else set()) | ({"local_scope"} if expected.local_scope is not None else set())
                        | ({"project_preparation", "requested_composition", "project_result"} if expected.project_preparation is not None else set())
                        | ({"candidate", "verification"} if "candidate" in expected.to_dict() else set()))
        or type(report["schema_version"]) is not int
        or report["schema_version"] != expected.to_dict()["schema_version"]
    ):
        raise QueueServiceError("preparation report fields or capability are unsupported")
    if "candidate" in expected.to_dict():
        from loom.fingerprints import hash_mapping
        from loom.serialization import thaw_plain_data

        candidate = thaw_plain_data(expected.candidate)
        if report["candidate"] != candidate:
            raise QueueConflictError("preparation candidate binding conflicts")
        if candidate is not None and report["verification"] != {"schema_version": 1, "candidate_digest": hash_mapping(candidate), "verdict": "verified"}:
            raise QueueConflictError("installed candidate verification failed")
        if candidate is None and report["verification"] is not None:
            raise QueueConflictError("unexpected candidate verification")
    if _project_binding(report.get("project_preparation")) != expected.project_preparation:
        raise QueueConflictError("preparation report project processor identity conflicts")
    if shared_scope(report.get("shared_scope")) != expected.shared_scope:
        raise QueueConflictError("preparation report shared policy conflicts")
    if _local_scope(report.get("local_scope")) != expected.local_scope:
        raise QueueConflictError("preparation report local policy identity conflicts")
    if (
        report["invocation"] != _invocation_data(expected)
        or report["operation_id"] != expected.operation_id
        or report["input_manifest_digest"] != expected.input_receipt.manifest_digest
        or report["preparation_profile"] != expected.preparation_profile
    ):
        raise QueueConflictError("preparation report identity conflicts")
    if ResidentProfileDescriptor.from_dict(
        report["profile_descriptor"]
    ).to_dict() != dict(expected.profile_descriptor):
        raise PreparationInstallationMismatch(
            "preparation report installation identity conflicts"
        )
    composition = _plain_mapping(report["composition"])
    if set(composition) != {
        "resolved",
        "redacted",
        "manifest",
        "recipe_manifest",
        "provenance",
    }:
        raise QueueServiceError("preparation composition fields are invalid")
    recipes = composition["recipe_manifest"]
    if not isinstance(recipes, list):
        raise QueueServiceError("preparation recipe evidence is invalid")
    received = _ReceivedComposition(
        _plain_mapping(composition["resolved"]),
        _plain_mapping(composition["redacted"]),
        _PlainEvidence(_plain_mapping(composition["manifest"])),
        tuple(_plain_mapping(recipe) for recipe in recipes),
        _PlainEvidence(_plain_mapping(composition["provenance"])),
        None
        if report["effective_run_options"] is None
        else RunOptions.from_dict(report["effective_run_options"]),
        expected.project_preparation,
        None if report.get("project_result") is None else _plain_mapping(report["project_result"]),
    )
    preflight = PreflightResult.from_dict(report["preflight"])
    if preflight.groups != _PREPARATION_GROUPS:
        raise QueueServiceError(
            "preparation report does not cover the required preflight groups"
        )
    if expected.project_preparation is not None:
        if preparation_checks_allow_publication(preflight):
            checks = [check for check in preflight.checks if check.check_id == "config.project_preparation"]
            if len(checks) != 1 or checks[0].status != PreflightCheckStatus.PASS:
                raise QueueConflictError("required project preparation evidence is missing")
            _validate_project_result(
                _plain_mapping(report["requested_composition"]), composition,
                _plain_mapping(report["project_result"]), expected,
            )
        elif report["project_result"] is not None:
            raise QueueConflictError("failed project preparation cannot return checked evidence")
    requirements = {
        name: ExecutionRequirement.from_dict(data)
        for name, data in _plain_mapping(report["execution_requirements"]).items()
    }
    if preparation_checks_allow_publication(preflight):
        if received.effective_run_options is None:
            raise QueueConflictError("preparation checked runtime options are missing")
        pipeline = _pipeline_from_resolved(received.resolved)
        # Validate the serialized report against accepted invocation intent;
        # publication still uses the worker's checked options unchanged.
        expected_options = merge_config_run_options(
            received.resolved,
            explicit=expected.run_options,
            known_stage_ids=pipeline.stage_names,
        )
        if expected_options != received.effective_run_options:
            raise QueueConflictError(
                "preparation report effective invocation conflicts"
            )
        provenance_metadata = _plain_mapping(received.provenance.value.get("metadata"))
        if provenance_metadata.get("loom_invocation") != _invocation_data(expected):
            raise QueueConflictError(
                "preparation report invocation provenance conflicts"
            )
        requirement = _profile_requirement(
            ResidentProfileDescriptor.from_dict(expected.profile_descriptor)
        )
        if set(requirements) != set(pipeline.stage_names):
            raise QueueConflictError(
                "preparation execution requirements must exactly cover stages"
            )
        if any(item != requirement for item in requirements.values()):
            raise PreparationInstallationMismatch(
                "preparation execution requirements do not match the selected installation"
            )
        for stage in pipeline.stages:
            scope = _local_scope(stage.fingerprint_fields.get(LOCAL_PREPARATION_SCOPE))
            if scope != expected.local_scope or (scope is not None and stage.placement.get("target") != scope["agent_id"]):
                raise QueueConflictError("preparation report local placement conflicts")
            if expected.shared_scope is not None:
                selected = stage_scope(stage.stage_config, stage.factory.init, expected.shared_scope)
                if shared_scope(stage.fingerprint_fields.get(SHARED_EXECUTION_SCOPE)) != selected:
                    raise QueueConflictError("prepared stage shared selection conflicts")
                validate_workload(stage.stage_config, selected)
                validate_workload(stage.factory.init, selected)
            elif shared_scope(stage.fingerprint_fields.get(SHARED_EXECUTION_SCOPE)) is not None:
                raise QueueConflictError("preparation report shared scope conflicts with policy")
            elif scope is None:
                _reject_path_bearing_data(stage.stage_config, "prepared stage config")
                _reject_path_bearing_data(stage.factory.init, "prepared factory arguments")
    return received, requirements, preflight


def preparation_checks_allow_publication(result: PreflightResult) -> bool:
    """Preserve failed/required-unavailable findings and allow inapplicable skips."""
    return result.status in {PreflightStatus.PASS, PreflightStatus.WARN} and not any(
        check.status == PreflightCheckStatus.SKIP
        and check.details.get("applicability") == "required"
        for check in result.checks
    )


def prepare_child_run(
    service: CoordinatorServiceConfig,
    binding: PreparationChildInput,
    run_name: str,
    *,
    runtime_options: RunOptions,
) -> ManagedLocalPreparationReceipt:
    """Publish the fixed internal child without composing any project configuration."""
    resolved: dict[str, PlainData] = {
        "pipeline": {
            "name": "loom-preparation",
            "stages": [
                {
                    "name": "prepare",
                    "factory": {"_target_": PREPARATION_STAGE_TARGET},
                    "config": binding.to_dict(),
                    "resources": {
                        "entries": {
                            "cpu": {"kind": "cpu", "amount": 1, "unit": "count"}
                        }
                    },
                    "outputs": {
                        "report": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                }
            ],
        },
        "runtime": runtime_options.to_dict(),
    }
    _require_local_binding(binding.local_scope, service.daemon.resident_worker_launch_profile, agent_id=service.daemon.machine_id)
    _bind_local_snapshot(resolved, binding.local_scope)
    if binding.shared_scope is not None:
        stage = cast(list[dict[str, PlainData]], cast(Mapping[str, PlainData], resolved["pipeline"])["stages"])[0]
        stage["fingerprint"] = {SHARED_EXECUTION_SCOPE: dict(binding.shared_scope)}
    # The fixed child has no authored composition/recipe provenance. Its native
    # plan fingerprint includes the complete validated input and profile binding.
    composed = _ReceivedComposition(
        resolved, resolved, _PlainEvidence({}), (), _PlainEvidence({})
    )
    return prepare_managed_run(
        service,
        composed,
        run_name,
        execution_requirements={
            "prepare": _profile_requirement(
                ResidentProfileDescriptor.from_dict(binding.profile_descriptor)
            ),
        },
    )


def _profile_requirement(profile: ResidentProfileDescriptor) -> ExecutionRequirement:
    return ExecutionRequirement(
        profile.project_fingerprint,
        profile.environment_fingerprint,
        profile.executor_fingerprint,
    )


def _plain_mapping(value: object) -> dict[str, PlainData]:
    plain = ensure_plain_data(value, path="preparation report")
    if not isinstance(plain, dict):
        raise QueueServiceError("preparation report value must be a mapping")
    return plain


def _prospective_run_name(request: PrepareRunRequest, binding: PreparationChildInput, composed: _ReceivedComposition) -> str:
    from loom.pipeline.stores import run_uri_to_path

    if request.run_name is not None:
        return request.run_name
    if composed.project_result is None:
        raise QueueConflictError("reconciled preparation has no checked project result")
    return run_uri_to_path(_checked_project_uri(binding, composed.project_result)).name


class CoordinatorPreparation:
    """Application callbacks installed alongside the native coordinator daemon.

    The daemon owns intent, cancellation and claims. These callbacks publish the
    fixed child, join its authoritative report, and publish the checked target
    using the daemon's retained service settings. They never compose project code.
    """

    def __init__(self, service: CoordinatorServiceConfig) -> None:
        self.service = service

    def _service(self, config: LocalDaemonConfig) -> CoordinatorServiceConfig:
        return replace(self.service, daemon=config)

    def validate_config(self, config: LocalDaemonConfig) -> None:
        _validate_preparation_service(self._service(config))

    def prepare_child(
        self,
        config: LocalDaemonConfig,
        binding: PreparationChildInput,
        run_name: str,
        options: RunOptions,
    ) -> ManagedLocalPreparationReceipt:
        return prepare_child_run(
            self._service(config), binding, run_name, runtime_options=options
        )

    def read_report(
        self,
        config: LocalDaemonConfig,
        admission: LocalDaemonAdmission,
        request: PrepareRunRequest,
        binding: PreparationChildInput,
    ) -> PreparationReport:
        intent = load_managed_local_intent(config, admission.run_uri)
        if intent.digest != admission.intent_digest or intent.pipeline.stage_names != (
            "prepare",
        ):
            raise QueueConflictError("preparation child admission intent conflicts")
        stage = intent.pipeline.get_stage("prepare")
        if (
            stage.factory.target_path != PREPARATION_STAGE_TARGET
            or PreparationChildInput.from_dict(stage.stage_config) != binding
        ):
            raise QueueConflictError("preparation child input binding conflicts")
        factory = config.coordinator_authority_factory
        if factory is None:
            raise QueueServiceError("preparation authority is unavailable")
        snapshot = factory(admission.run_uri).open_run(admission.run_uri)
        if snapshot.run_uri != admission.run_uri or len(snapshot.stages) != 1:
            raise QueueConflictError("preparation child authority identity conflicts")
        observed = snapshot.stages[0]
        commit = observed.latest_commit
        if (
            observed.stage_name != "prepare"
            or observed.status is not StageStatus.SUCCEEDED
            or commit is None
            or commit.run_uri != admission.run_uri
            or commit.stage_name != "prepare"
            or not observed.attempts
            or observed.attempts[-1].attempt_id != commit.attempt_id
        ):
            raise QueueServiceError(
                "preparation report has no matching committed child attempt"
            )
        facts = [
            fact
            for fact in observed.artifact_facts
            if fact.artifact_name == "report" and fact.commit_id == commit.commit_id
        ]
        if len(facts) != 1 or commit.output_names != ("report",):
            raise QueueConflictError("preparation report commit identity conflicts")
        reference = facts[0].artifact
        store = LocalRunStore(config.run_store_root)
        result_data = store.read_stage_worker_result(
            admission.run_uri, "prepare", attempt=observed.attempts[-1].attempt
        )
        if result_data is None:
            raise QueueServiceError("preparation child result is unavailable")
        try:
            result = StageWorkerResult.from_dict(result_data)
        except (ValueError, ValidationError, SerializationError) as exc:
            raise QueueConflictError(
                "preparation committed worker result is invalid"
            ) from exc
        if (
            result.run_uri != admission.run_uri
            or result.stage_name != "prepare"
            or result.attempt != observed.attempts[-1].attempt
            or result.status is not StageStatus.SUCCEEDED
            or result.outputs.get("report") != reference
        ):
            raise QueueConflictError(
                "preparation report does not match the committed worker result"
            )
        try:
            value = LocalArtifactStore(
                store.local_artifact_root(admission.run_uri)
            ).load(reference)
        except ArtifactChecksumMismatchError as exc:
            raise QueueConflictError(
                "preparation committed report checksum conflicts"
            ) from exc
        except ArtifactStoreError as exc:
            if isinstance(exc.__cause__, CodecDecodeError):
                raise QueueConflictError(
                    "preparation committed report cannot be decoded"
                ) from exc
            raise
        composed, requirements, preflight = decode_preparation_report(
            value, expected=binding
        )
        allowed = preparation_checks_allow_publication(preflight)
        prospective = None
        if allowed:
            resolved = cast(_ReceivedComposition, composed).resolved
            pipeline = _pipeline_from_resolved(resolved)
            try:
                run_uri, _options = _runtime_for_service(
                    self._service(config),
                    resolved,
                    pipeline,
                    _prospective_run_name(request, binding, cast(_ReceivedComposition, composed)),
                    effective_options=cast(
                        _ReceivedComposition, composed
                    ).effective_run_options,
                )
            except (ValueError, ValidationError, SerializationError) as exc:
                raise QueueConflictError(
                    "preparation report runtime evidence is invalid"
                ) from exc
            prospective = ManagedLocalPreparationReceipt(
                run_uri, "f" * 64, "f" * 64, pipeline.stage_names
            )
        return PreparationReport(
            reference,
            preflight.to_dict(),
            preflight.status.value,
            allowed,
            prospective,
            (composed, requirements),
            None if cast(_ReceivedComposition, composed).project_result is None else cast(Mapping[str, PlainData], cast(_ReceivedComposition, composed).project_result)["reconciliation_key"],
        )

    def capture_candidate(self, config: LocalDaemonConfig, run_uri: str,
                          admission: LocalDaemonAdmission | None) -> dict[str, PlainData]:
        """Capture plain native evidence without exporting an authority factory."""
        from loom.queue.local_daemon_runtime import load_managed_local_runtime_record

        intent = load_managed_local_intent(config, run_uri)
        factory = config.coordinator_authority_factory
        if factory is None:
            raise QueueConflictError("candidate authority is unavailable")
        snapshot = factory(run_uri).open_run(run_uri)
        planned_stages = set(intent.pipeline.stage_names)
        observed_stages = {stage.stage_name for stage in snapshot.stages}
        # Managed execution materializes stages when they start. A running or
        # failed prefix may be observed or retried; success requires the full plan.
        if (snapshot.run_uri != run_uri
            or not observed_stages.issubset(planned_stages)
            or (snapshot.status.value == "SUCCEEDED" and observed_stages != planned_stages)
            or (not snapshot.stages and snapshot.status.value != "PLANNED")
            or snapshot.status.value in {"CANCELLED", "CANCELLING"}
            or (admission is not None and admission.state.value == "SUCCEEDED" and snapshot.status.value != "SUCCEEDED")):
            raise QueueConflictError("candidate authority identity conflicts")
        store = LocalRunStore(config.run_store_root)
        resolved = store.read_config_snapshot(run_uri, "resolved")
        if resolved is None:
            raise QueueConflictError("candidate configuration is unavailable")
        record = load_managed_local_runtime_record(store, run_uri)
        return {
            "schema_version": 1, "run_uri": run_uri,
            "admission": None if admission is None else admission.to_dict(),
            "authority": snapshot.to_dict(), "configuration": json.loads(resolved),
            "native_intent": record, "intent_digest": intent.digest,
            "artifact_binding": {"access": "read_only", "root": str(store.local_artifact_root(run_uri))},
            "prepared_run": {"run_uri": run_uri, "plan_digest": record["plan_digest"],
                             "runtime_digest": record["digest"], "stage_names": list(intent.pipeline.stage_names)},
        }

    def publish_target(
        self,
        config: LocalDaemonConfig,
        request: PrepareRunRequest,
        report: PreparationReport,
    ) -> ManagedLocalPreparationReceipt:
        composed, requirements = cast(
            tuple[object, Mapping[str, ExecutionRequirement]], report.publication_data
        )
        received = cast(_ReceivedComposition, composed)
        if received.project_preparation is not None and received.project_preparation["target_run_uri"] is None:
            from loom.queue.preparation import project_target_from_key
            received = replace(received, project_preparation={"processor": received.project_preparation["processor"],
                "target_run_uri": project_target_from_key(received.project_preparation, _plain_mapping(cast(Mapping[str, PlainData], received.project_result)["reconciliation_key"]))})
        try:
            return prepare_managed_run(
                self._service(config),
                received,
                cast(str, request.run_name),
                execution_requirements=requirements,
            )
        except QueueServiceError as exc:
            # Native publisher rejects existing changed/partial targets. Keep
            # that conflict inspectable; do not repair or overwrite its files.
            raise QueueConflictError("preparation publication_conflict") from exc
