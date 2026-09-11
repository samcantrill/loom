"""Managed preparation stage and coordinator publication wiring.

Only the selected worker composes trusted project configuration. Reports carry
plain native evidence; decoding and publishing them never import project recipes
or call the composer on the coordinator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
from typing import Any, cast

from loom.artifacts import ArtifactRef
from loom.diagnostics.models import (
    PreflightCheckStatus,
    PreflightGroup,
    PreflightRequest,
    PreflightResult,
    PreflightStatus,
)
from loom.diagnostics.preflight import run_preflight_composed
from loom.pipeline.context import StageContext
from loom.pipeline.orchestration import ExecutionRequirement
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.runtime.options import RunOptions
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.queue._preparation_operations import PreparationReport
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
    PREPARATION_INPUT_CONTEXT_ENV,
    PREPARATION_STAGE_TARGET,
    PreparationChildInput,
    PrepareRunRequest,
    resolve_shared_input,
)
from loom.serialization import PlainData, ensure_plain_data


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
        if profile.to_dict() != dict(binding.profile_descriptor):
            raise QueueConflictError("preparation installation_mismatch")
        roots = cast(Mapping[str, str], private["shared_roots"])
        captured = resolve_shared_input(
            binding.input_receipt,
            shared_roots={alias: Path(path) for alias, path in roots.items()},
        )
        config_path = captured / binding.config_path
        # The capture manifest is authoritative. A different readable file in the
        # directory must not become an implicit configuration input.
        if not config_path.is_file() or config_path.is_symlink():
            raise QueueServiceError(
                "preparation source_unavailable: selected config is absent"
            )
        composed = _compose_worker_config(config_path)
        preflight = run_preflight_composed(
            composed,
            PreflightRequest(
                config_path=config_path, cwd=captured, groups=_PREPARATION_GROUPS
            ),
        )
        composition = _composition_data(composed)
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
            "schema_version": 1,
            "operation_id": binding.operation_id,
            "input_manifest_digest": binding.input_receipt.manifest_digest,
            "preparation_profile": binding.preparation_profile,
            "profile_descriptor": profile.to_dict(),
            "composition": composition,
            "execution_requirements": requirements,
            "preflight": preflight.to_dict(),
        }
        return {
            "report": context.save_artifact(
                "report", report, artifact_type="json", codec_key="json.v1"
            )
        }


def _compose_worker_config(config_path: Path) -> object:
    from weave import RecipeCatalog, compose_config
    from loom.plugins import list_entry_points, load_recipe_entry_points
    from loom.plugins.entrypoints import LOOM_RECIPES_GROUP

    # This is an explicit composition step inside the qualified worker process.
    # The existing strict plugin loader owns discovery/duplicates/import failures.
    catalog = RecipeCatalog()
    records = list_entry_points(groups=(LOOM_RECIPES_GROUP,))
    load_recipe_entry_points(records, catalog, strict=True)
    return compose_config(config_path, recipe_catalog=catalog)


def _worker_context() -> Mapping[str, PlainData]:
    encoded = os.environ.get(PREPARATION_INPUT_CONTEXT_ENV)
    if encoded is None:
        raise QueueServiceError("preparation requires its managed worker input binding")
    try:
        value = json.loads(encoded)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "profile_descriptor", "shared_roots"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or not isinstance(value["shared_roots"], dict)
            or any(
                not isinstance(alias, str)
                or not isinstance(path, str)
                or not Path(path).is_absolute()
                for alias, path in value["shared_roots"].items()
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


def decode_preparation_report(
    value: object,
    *,
    expected: PreparationChildInput,
) -> tuple[object, dict[str, ExecutionRequirement], PreflightResult]:
    """Decode one committed child's report after its durable artifact join.

    The coordinator operation owner must first establish the committed artifact's
    child/run/assignment identity. This function checks report identity and native
    value contracts, without executing or recomposing the reported configuration.
    """
    report = _plain_mapping(value)
    if (
        set(report) != _REPORT_FIELDS
        or type(report["schema_version"]) is not int
        or report["schema_version"] != 1
    ):
        raise QueueServiceError("preparation report fields are invalid")
    if (
        report["operation_id"] != expected.operation_id
        or report["input_manifest_digest"] != expected.input_receipt.manifest_digest
        or report["preparation_profile"] != expected.preparation_profile
        or ResidentProfileDescriptor.from_dict(report["profile_descriptor"]).to_dict()
        != dict(expected.profile_descriptor)
    ):
        raise QueueConflictError("preparation report identity conflicts")
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
    )
    preflight = PreflightResult.from_dict(report["preflight"])
    if preflight.groups != _PREPARATION_GROUPS:
        raise QueueServiceError(
            "preparation report does not cover the required preflight groups"
        )
    requirements = {
        name: ExecutionRequirement.from_dict(data)
        for name, data in _plain_mapping(report["execution_requirements"]).items()
    }
    if preparation_checks_allow_publication(preflight):
        pipeline = _pipeline_from_resolved(received.resolved)
        requirement = _profile_requirement(
            ResidentProfileDescriptor.from_dict(expected.profile_descriptor)
        )
        if set(requirements) != set(pipeline.stage_names) or any(
            item != requirement for item in requirements.values()
        ):
            raise QueueConflictError(
                "preparation execution requirements do not match the selected installation"
            )
        for stage in pipeline.stages:
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
        result = StageWorkerResult.from_dict(result_data)
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
        value = LocalArtifactStore(store.local_artifact_root(admission.run_uri)).load(
            reference
        )
        composed, requirements, preflight = decode_preparation_report(
            value, expected=binding
        )
        allowed = preparation_checks_allow_publication(preflight)
        prospective = None
        if allowed:
            resolved = cast(_ReceivedComposition, composed).resolved
            pipeline = _pipeline_from_resolved(resolved)
            run_uri, _options = _runtime_for_service(
                self._service(config), resolved, pipeline, request.run_name
            )
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
        )

    def publish_target(
        self,
        config: LocalDaemonConfig,
        request: PrepareRunRequest,
        report: PreparationReport,
    ) -> ManagedLocalPreparationReceipt:
        composed, requirements = cast(
            tuple[object, Mapping[str, ExecutionRequirement]], report.publication_data
        )
        try:
            return prepare_managed_run(
                self._service(config),
                composed,
                request.run_name,
                execution_requirements=requirements,
            )
        except QueueServiceError as exc:
            # Native publisher rejects existing changed/partial targets. Keep
            # that conflict inspectable; do not repair or overwrite its files.
            raise QueueConflictError("preparation publication_conflict") from exc
