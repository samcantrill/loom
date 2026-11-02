"""Opt-in operation-name accounting identity for ready-stage reconciliation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import timedelta
import hashlib
import re
from typing import cast

from loom.serialization import PlainData
from loom.timestamps import parse_timestamp, utc_timestamp

from .errors import SlurmCommandOutputLimitError, SlurmPlanningError


@dataclass(frozen=True, slots=True)
class SlurmHistoryPolicy:
    """Explicit UID and tolerated client/controller clock skew, in seconds.

    This mode requires JobName, UID, Cluster, Submit, DBIndex and SLUID in Slurm
    accounting. Missing accounting remains unresolved, including for live jobs.
    """

    user_id: int
    clock_skew_seconds: int = 60

    def __post_init__(self) -> None:
        if type(self.user_id) is not int or not 0 <= self.user_id < 2**32:
            raise SlurmPlanningError("accounting history user_id must be a Unix UID")
        if type(self.clock_skew_seconds) is not int or not 0 <= self.clock_skew_seconds <= 300:
            raise SlurmPlanningError("accounting history clock skew must be in 0..300 seconds")

    def to_dict(self) -> dict[str, PlainData]:
        return {"kind": "job-name-accounting-v1", **asdict(self)}

    def window(self, created_at: str, observed_at: str) -> tuple[str, str]:
        created, observed = parse_timestamp(created_at), parse_timestamp(observed_at)
        if observed < created:
            raise SlurmPlanningError("accounting history clock moved before intent")
        skew = timedelta(seconds=self.clock_skew_seconds)
        return utc_timestamp(created - skew), utc_timestamp(observed + skew)


def parse_history_policy(value: object) -> SlurmHistoryPolicy | None:
    if value is None or isinstance(value, SlurmHistoryPolicy):
        return value
    if not isinstance(value, Mapping) or not {"user_id"} <= set(value) or set(value) - {"user_id", "clock_skew_seconds"}:
        raise SlurmPlanningError("accounting_history requires user_id and optional clock_skew_seconds")
    return SlurmHistoryPolicy(
        user_id=cast(int, value["user_id"]),
        clock_skew_seconds=cast(int, value.get("clock_skew_seconds", 60)),
    )


def operation_job_name(operation_id: str) -> str:
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 160:
        raise SlurmPlanningError("accounting history operation ID is invalid")
    return "loom-" + hashlib.sha256(operation_id.encode("utf-8")).hexdigest()


def history_cluster(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value) is None or value.casefold() == "all":
        raise SlurmPlanningError("accounting history requires one explicit cluster")
    return value


@dataclass(frozen=True, slots=True)
class SlurmAccountingIdentity:
    """Immutable scheduler incarnation; a numeric job ID alone is insufficient."""

    job_id: str
    cluster: str
    job_name: str
    user_id: int
    submitted_at: str
    db_index: str
    sluid: str

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, str) or re.fullmatch(r"[0-9]{1,20}", self.job_id) is None or int(self.job_id) == 0:
            raise SlurmPlanningError("accounting job ID is invalid")
        history_cluster(self.cluster)
        if not isinstance(self.job_name, str) or re.fullmatch(r"loom-[0-9a-f]{64}", self.job_name) is None:
            raise SlurmPlanningError("accounting job name is incomplete or invalid")
        SlurmHistoryPolicy(self.user_id)
        try:
            parse_timestamp(self.submitted_at)
        except (ValueError, TypeError, AttributeError) as exc:
            raise SlurmPlanningError("accounting submission timestamp is invalid") from exc
        if not isinstance(self.db_index, str) or re.fullmatch(r"[0-9]{1,30}", self.db_index) is None or int(self.db_index) == 0:
            raise SlurmPlanningError("accounting DBIndex is missing or invalid")
        if not isinstance(self.sluid, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.sluid) is None or self.sluid.casefold() in {"unknown", "none", "0"}:
            raise SlurmPlanningError("accounting SLUID is missing or invalid")

    def to_dict(self) -> dict[str, PlainData]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> SlurmAccountingIdentity:
        fields = {"job_id", "cluster", "job_name", "user_id", "submitted_at", "db_index", "sluid"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise SlurmPlanningError("accounting identity fields are unsupported")
        return cls(
            job_id=cast(str, value["job_id"]), cluster=cast(str, value["cluster"]),
            job_name=cast(str, value["job_name"]), user_id=cast(int, value["user_id"]),
            submitted_at=cast(str, value["submitted_at"]),
            db_index=cast(str, value["db_index"]), sluid=cast(str, value["sluid"]),
        )


def accounting_query_argv(
    *, job_name: str, user_id: int, cluster: str, started_after: str, ended_before: str,
) -> tuple[str, ...]:
    if not isinstance(job_name, str) or re.fullmatch(r"loom-[0-9a-f]{64}", job_name) is None:
        raise SlurmPlanningError("accounting query job name is invalid")
    SlurmHistoryPolicy(user_id)
    history_cluster(cluster)
    start, end = parse_timestamp(started_after), parse_timestamp(ended_before)
    if end < start:
        raise SlurmPlanningError("accounting query time window is invalid")
    # TZ=UTC and SLURM_TIME_FORMAT are imposed by the runner. Slurm's CLI time
    # grammar does not document the Z suffix accepted by Loom's UTC codec.
    return (
        "sacct", "--noheader", "--parsable2", "--allocations", "--duplicates",
        f"--name={job_name}", f"--user={user_id}", f"--clusters={cluster}",
        f"--starttime={utc_timestamp(start)[:-1]}",
        f"--endtime={utc_timestamp(end)[:-1]}",
        "--format=JobIDRaw,JobName%128,UID,Cluster%64,Submit,DBIndex,SLUID%128,State%32",
    )


def accounting_batch_argv(
    *, job_names: Sequence[str], user_id: int, cluster: str,
    started_after: str, ended_before: str,
) -> tuple[str, ...]:
    """Query only a bounded set of full operation names within one window."""
    names = tuple(job_names)
    if not 1 <= len(names) <= 64 or len(set(names)) != len(names):
        raise SlurmPlanningError("accounting batch requires 1..64 distinct names")
    argv = ()
    for name in names:
        argv = accounting_query_argv(
            job_name=name, user_id=user_id, cluster=cluster,
            started_after=started_after, ended_before=ended_before,
        )
    return tuple("--name=" + ",".join(names) if arg.startswith("--name=") else arg for arg in argv)


def partition_accounting_output(output: str, job_names: Sequence[str]) -> dict[str, str]:
    """Partition a complete response; each operation still validates its rows."""
    if "...[truncated]" in output:
        raise SlurmCommandOutputLimitError("accounting batch output is truncated")
    rows: dict[str, list[str]] = {name: [] for name in job_names}
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.strip().removesuffix("|").split("|")
        if len(fields) != 8 or fields[1].strip() not in rows:
            raise SlurmPlanningError("accounting batch row cannot be attributed")
        rows[fields[1].strip()].append(line)
    return {name: "\n".join(values) for name, values in rows.items()}


def parse_accounting_rows(
    output: str, *, job_name: str, user_id: int, cluster: str,
    started_after: str, ended_before: str,
) -> tuple[tuple[SlurmAccountingIdentity, str], ...]:
    """Reject incomplete/contradictory filtered evidence rather than omit it.

    No deduplication: multiple returned records are ambiguous even if their
    numeric job IDs agree. Comments are neither requested nor required.
    """
    start, end = parse_timestamp(started_after), parse_timestamp(ended_before)
    if "...[truncated]" in output:
        raise SlurmPlanningError("accounting history output is truncated")
    rows = []
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = tuple(part.strip() for part in line.strip().removesuffix("|").split("|"))
        if len(fields) != 8:
            raise SlurmPlanningError("accounting history row is incomplete")
        job_id, name, uid, row_cluster, submitted, db_index, sluid, raw_state = fields
        if not uid.isascii() or not uid.isdecimal():
            raise SlurmPlanningError("accounting history UID is invalid")
        # The runner fixes both timezone and format, so a naive Slurm timestamp
        # here represents UTC rather than the local login timezone.
        identity = SlurmAccountingIdentity(
            job_id, row_cluster, name, int(uid), submitted + "Z", db_index, sluid,
        )
        if (name, identity.user_id, row_cluster) != (job_name, user_id, cluster) or not start <= parse_timestamp(identity.submitted_at) <= end:
            raise SlurmPlanningError("accounting history identity is contradictory")
        state = raw_state.split(maxsplit=1)[0] if raw_state else ""
        if re.fullmatch(r"[A-Z_]+", state) is None:
            raise SlurmPlanningError("accounting history state is incomplete")
        rows.append((identity, state))
    return tuple(rows)
