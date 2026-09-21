"""Causal installed-action identity, separate from authored audit fingerprints."""

from __future__ import annotations

from collections.abc import Mapping

from loom.fingerprints import hash_mapping
from loom.pipeline._project_contracts import validate_envelope
from loom.pipeline.specs import StageSpec
from loom.serialization import PlainData, ensure_plain_data

from .fingerprints import _output_spec_identity


DEFAULT_GENERATION = "default"


def action_execution_identity(
    stage: StageSpec,
    contract: Mapping[str, PlainData] | None,
    *,
    implementation: Mapping[str, PlainData] | None,
    inputs: Mapping[str, PlainData],
    generation: str = DEFAULT_GENERATION,
) -> dict[str, PlainData] | None:
    """Identify work from checked semantics and original committed inputs.

    ``implementation`` is native qualified installation/processor evidence, never
    the captured configuration manifest. An unavailable qualification or null
    project key opts out. ``inputs`` is resolved by native authority per consumer
    port and contains original producer commit, output and verified closure
    identity; a current graph alias or an intermediate reuse binding is not an
    input realization. Control prerequisites are checked by the scheduler first.
    """
    if contract is None or implementation is None:
        return None
    checked = validate_envelope(contract)
    if checked["semantic_key"] is None:
        return None
    if set(inputs) != set(stage.inputs):
        raise ValueError("action identity requires every declared input realization")
    if not isinstance(generation, str) or not generation:
        raise ValueError("action generation is invalid")
    payload = ensure_plain_data(
        {
            "schema_version": 1,
            "integration": {"namespace": checked["namespace"], "version": 3},
            "semantic_key": checked["semantic_key"],
            "implementation": {
                "installation": dict(implementation),
                "factory_target": stage.target_path,
                "factory_init": dict(stage.factory.init),
            },
            "inputs": dict(inputs),
            "outputs": {
                port: _output_spec_identity(spec)
                for port, spec in stage.outputs.items()
            },
            "generation": generation,
        },
        path="action execution identity",
    )
    assert isinstance(payload, dict)
    return {"schema_version": 1, "digest": hash_mapping(payload), "payload": payload}
