"""Compose the bootstrap owner around a single registered assignment for unit tests."""
from contextlib import nullcontext
from types import SimpleNamespace
from typing import cast

from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile
from loom.queue._agent_slurm import SlurmSubmissionProjection
from loom.queue.slurm_ready_stage import SQLiteSlurmStageAssignments

from loom.queue._slurm_bootstrap import SlurmBootstrapLifecycle
from loom.queue._slurm_bootstrap_settlement import SlurmBootstrapSettlement


def registered_bootstrap(record, *, assignment_id, incarnation, connect, authority_for,
                         mark_granted, consume_start, shared_roots=None, hold_publication=None,
                         principal="slurm-agent", credential="credential"):
    profile = SimpleNamespace(
        profile_id="slurm", descriptor="retained", bootstrap_principal_id=principal,
        credential_reference=credential,
    )
    record.assignment.assignment_id = assignment_id
    record.assignment.profile_id = profile.profile_id
    record.assignment.profile_descriptor = profile.descriptor
    record.assignment.profile_configuration_fingerprint = "profile-revision"
    record.job_id, record.cluster = "734", "test"
    record.bootstrap_incarnation = incarnation
    record.terminal_observation = None

    def read(identity):
        assert identity == assignment_id
        return record

    assignments = SimpleNamespace(
        read=read, mark_granted=mark_granted, consume_start=consume_start,
        unresolved_bootstrap_grants=lambda: (assignment_id,) if record.fence is None else (),
    )
    settlement = SlurmBootstrapSettlement(
        cast(SQLiteSlurmStageAssignments, assignments), cast(SlurmSubmissionProjection, SimpleNamespace()),
        connect, lambda _: False,
    )
    return SlurmBootstrapLifecycle(
        settlement, lambda *_: cast(SlurmReadyStageProfile, profile), authority_for, lambda: "2026-01-01T00:00:00Z",
        lambda: shared_roots or {}, hold_publication or (lambda _: nullcontext()), lambda *_: None,
    )
