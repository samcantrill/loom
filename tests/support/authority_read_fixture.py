"""Seed committed synthetic facts for read-only consumer tests, without execution."""

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, StageStatus, StageStatusRecord
from loom.pipeline.reliability import ReliabilityPolicy
from loom.pipeline.stores.read_models import (
    ReliabilityPolicyFact,
    ReliabilityPolicyScope,
)


def seed_completed_authority_run(store, run_uri):
    store.create_run(run_uri)
    authority = store.authority_store
    authority.transition_run(
        run_uri, from_status=RunStatus.CREATED, to_status=RunStatus.RUNNING
    )
    for name, output_name, extension in (
        ("build", "data", "json"),
        ("report", "text", "txt"),
    ):
        allocation = authority.allocate_stage_attempt(
            run_uri, name, owner_id="read-fixture", lease_ttl_seconds=30
        )
        path = (
            store.local_store.local_run_dir(run_uri)
            / "artifacts"
            / name
            / f"{output_name}.{extension}"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"value": 7}' if extension == "json" else "value=7")
        ref = ArtifactRef(
            artifact_id=f"{name}/{output_name}",
            uri=path.as_uri(),
            artifact_type="json" if extension == "json" else "text",
        )
        authority.write_reliability_policy_fact(
            run_uri,
            ReliabilityPolicyFact(
                run_uri=run_uri,
                recorded_at=allocation.attempt.revision.created_at,
                scope=ReliabilityPolicyScope.STAGE,
                stage_name=name,
                policy=ReliabilityPolicy().to_dict(),
            ),
        )
        authority.record_output_commit(
            run_uri,
            name,
            attempt_id=allocation.attempt.attempt_id,
            fencing_token=allocation.lease.fencing_token,
            outputs={output_name: ref},
        )
        store.local_store.write_stage_status(
            run_uri,
            name,
            StageStatusRecord(
                run_uri=run_uri,
                stage_name=name,
                status=StageStatus.SUCCEEDED,
                attempt=1,
                updated_at=allocation.attempt.revision.created_at,
            ),
        )
    authority.transition_run(
        run_uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED
    )
