from __future__ import annotations

from pathlib import Path

from loom.pipeline.orchestration import ReadyStageOrchestrator, SQLiteStageWorkStore
from loom.pipeline.planning import FingerprintStatus, PlanAction, StagePlan
from loom.pipeline.planning.readiness import AttemptReadiness
from loom.pipeline.stores.authority import PreparedAttemptReceipt
from loom.pipeline.stores.read_models import BackendRevision, StageAttempt
from loom.pipeline.status import StageStatus


def _readiness() -> AttemptReadiness:
    plan = StagePlan(stage_name="train", action=PlanAction.RUN, base_action=PlanAction.RUN,
        fingerprint_status=FingerprintStatus.PENDING_INPUTS, fingerprint=None, resume_check=None,
        reasons=(), bound_inputs={}, pending_inputs=(), reusable_outputs={}, declared_outputs={},
        upstream_stages=(), downstream_stages=(), selected_by=(), invalidated_by=())
    return AttemptReadiness(plan, PlanAction.RUN, "generation-1", {})


class _Authority:
    def ensure_prepared_attempt(self, run_uri: str, stage_name: str, **kwargs: object) -> PreparedAttemptReceipt:
        attempt = StageAttempt(run_uri, stage_name, 1, "train-1", StageStatus.PENDING,
            BackendRevision(1, "one", "2020-01-01T00:00:00Z"), "2020-01-01T00:00:00Z", "coordinator")
        return PreparedAttemptReceipt(str(kwargs["operation_id"]), str(kwargs["request_digest"]), str(kwargs["readiness_generation"]), attempt)


def test_reconcile_replays_exact_authority_attempt_and_stage_work_id(tmp_path: Path) -> None:
    store = SQLiteStageWorkStore(tmp_path / "stage-work.sqlite")
    orchestrator = ReadyStageOrchestrator(authority=_Authority(), store=store, owner_id="coordinator")
    first = orchestrator.reconcile(run_uri="file:///run", readiness=_readiness(), placement={})
    second = orchestrator.reconcile(run_uri="file:///run", readiness=_readiness(), placement={})
    assert first is not None and second is not None
    assert first.stage_work_id == second.stage_work_id
    assert SQLiteStageWorkStore(tmp_path / "stage-work.sqlite").list() == (first,)
