"""Retained per-port assignment evidence, independent of worker-local paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from loom.artifacts import ArtifactRef
from loom._output_identity import OutputLocator
from loom.serialization import thaw_plain_data


@dataclass(frozen=True, slots=True)
class AttemptInputBinding:
    """Original input and producer selected before an attempt was handed off.

    This records assignment, not application file access. Consumption additionally
    requires an authority-owned start witness. External refs confer no authority.
    """

    input_name: str
    source_stage_name: str | None
    source_output_name: str | None
    artifact: ArtifactRef
    producer: OutputLocator | None
    source_kind: str

    def __post_init__(self) -> None:
        for name in ("input_name", "source_stage_name", "source_output_name"):
            value = getattr(self, name)
            if (name == "input_name" or value is not None) and (
                not isinstance(value, str) or not value
            ):
                raise ValueError(f"{name} must be a nonempty string")
        if not isinstance(self.artifact, ArtifactRef):
            raise ValueError("binding artifact must be an ArtifactRef")
        if self.source_kind not in {"produced", "external", "legacy_unresolved"}:
            raise ValueError("invalid input source kind")
        if (self.source_kind == "produced") != isinstance(self.producer, OutputLocator):
            raise ValueError("only produced inputs have an exact producer")
        if (
            self.producer is not None
            and self.source_output_name != self.producer.output_name
        ):
            raise ValueError("binding source output differs from its producer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_name": self.input_name,
            "source_stage_name": self.source_stage_name,
            "source_output_name": self.source_output_name,
            "artifact": self.artifact.to_dict(),
            "producer": None if self.producer is None else self.producer.to_dict(),
            "source_kind": self.source_kind,
        }

    @classmethod
    def from_dict(cls, value: Any) -> AttemptInputBinding:
        if not isinstance(value, Mapping) or set(value) != {
            "input_name",
            "source_stage_name",
            "source_output_name",
            "artifact",
            "producer",
            "source_kind",
        }:
            raise ValueError("invalid input binding fields")
        return cls(
            value["input_name"],
            value["source_stage_name"],
            value["source_output_name"],
            ArtifactRef.from_dict(thaw_plain_data(value["artifact"])),
            None
            if value["producer"] is None
            else OutputLocator.from_dict(value["producer"]),
            value["source_kind"],
        )


def decode_bindings(value: Any) -> tuple[AttemptInputBinding, ...] | None:
    """Keep absent legacy evidence distinct from a known zero-input attempt."""
    if value is None:
        return None
    if not isinstance(value, (tuple, list)):
        raise ValueError("input_bindings must be a sequence or null")
    result = tuple(
        v if isinstance(v, AttemptInputBinding) else AttemptInputBinding.from_dict(v)
        for v in value
    )
    if len({v.input_name for v in result}) != len(result):
        raise ValueError("duplicate input binding")
    return result


def capture_bindings(
    stage_plan: Any, stages: Mapping[str, Any]
) -> tuple[AttemptInputBinding, ...]:
    """Resolve declared ports against the same snapshot used by readiness.

    A bound external reference stays external unless its declared source's
    authoritative fact equals the supplied ref. No URI/checksum lookup is used.
    """
    result = []
    for port in (*stage_plan.bound_inputs.values(), *stage_plan.pending_inputs):
        source = stages.get(port.source_stage)
        commit = None if source is None else source.latest_commit
        fact = next(
            (
                f
                for f in (() if source is None else source.artifact_facts)
                if f.artifact_name == port.source_output
            ),
            None,
        )
        artifact = getattr(port, "artifact_ref", None)
        if artifact is None:
            if fact is None or commit is None:
                raise ValueError("pending input has no committed source")
            artifact = fact.artifact
        elif fact is not None and commit is not None and fact.artifact != artifact:
            raise ValueError(
                "planned input differs from the selected upstream commit; replan required"
            )
        producer = None
        if fact is not None and commit is not None and fact.artifact == artifact:
            producer = OutputLocator(
                commit.run_uri, commit.stage_name, commit.commit_id, port.source_output
            )
        result.append(
            AttemptInputBinding(
                port.input_name,
                port.source_stage,
                port.source_output,
                artifact,
                producer,
                "external" if producer is None else "produced",
            )
        )
    return tuple(sorted(result, key=lambda binding: binding.input_name))


def validate_bindings(
    bindings: Sequence[AttemptInputBinding] | None, stages: Mapping[str, Any]
) -> None:
    """Verify native selectors against authoritative declared-source facts."""
    for binding in bindings or ():
        if binding.producer is None:
            continue
        source = stages.get(binding.source_stage_name or "")
        commit = None if source is None else source.latest_commit
        if (
            commit is None
            or binding.producer
            != OutputLocator(
                commit.run_uri,
                commit.stage_name,
                commit.commit_id,
                binding.source_output_name or "",
            )
            or source is None
            or not any(
                f.artifact_name == binding.source_output_name
                and f.artifact == binding.artifact
                for f in source.artifact_facts
            )
        ):
            raise ValueError("input binding no longer matches its authoritative source")


def validate_worker_inputs(
    request: Any, bindings: Sequence[AttemptInputBinding] | None
) -> None:
    """Check the common handoff before any worker-local materialization."""
    if bindings is None:
        return
    if (
        request.inputs != {b.input_name: b.artifact for b in bindings}
        or decode_bindings(request.metadata.get("attempt_input_bindings"))
        != tuple(bindings)
        or request.metadata.get("attempt_input_evidence") != binding_evidence(bindings)
    ):
        raise ValueError("worker handoff differs from retained input bindings")


def binding_evidence(bindings: Sequence[AttemptInputBinding]) -> dict[str, Any]:
    """Path-free handoff reference; the scoped authority attempt owns the refs."""
    payload = [binding.to_dict() for binding in bindings]
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"schema_version": 1, "bindings_digest": digest}
