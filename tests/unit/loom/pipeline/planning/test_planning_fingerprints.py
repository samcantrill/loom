"""Unit tests for stage fingerprint construction."""

from loom.artifacts import ArtifactRef
from loom.pipeline import OutputSpec, StageFactorySpec, StageSpec
from loom.pipeline.planning import (
    FingerprintContext,
    StageFingerprintError,
    build_stage_fingerprint,
)
from loom.protocols import Fingerprintable
from loom.serialization import PlainData


def _stage(
    *,
    config: dict[str, PlainData] | None = None,
    fingerprint_fields: dict[str, PlainData] | None = None,
    resources: dict[str, PlainData] | None = None,
) -> StageSpec:
    return StageSpec(
        name="report",
        factory=StageFactorySpec(target_path="project.Report", init={}),
        stage_config=config or {"thresholds": [1, 2]},
        fingerprint_fields=fingerprint_fields or {},
        inputs={"data": "build.data"},
        outputs={"summary": OutputSpec(artifact_type="json", codec_key="json.v1")},
        resources=resources or {},
    )


def _input_ref(
    *, checksum: str = "sha256:" + "1" * 64, uri: str = "file:///tmp/a.json"
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id="build/data",
        uri=uri,
        artifact_type="json",
        codec_key="json.v1",
        checksum=checksum,
        created_at="2020-01-01T00:00:00Z",
    )


class _RuntimeParameter:
    def __init__(self, digest: str) -> None:
        self.digest = digest

    def fingerprint(self) -> str:
        return self.digest


def test_fingerprint_changes_for_semantic_inputs_and_excludes_noisy_values() -> None:
    context = FingerprintContext(python_version="3.12.0", loom_version="0.1.0")
    base = build_stage_fingerprint(
        _stage(), bound_inputs={"data": _input_ref()}, fingerprint_context=context
    )
    reordered = build_stage_fingerprint(
        _stage(config={"thresholds": [1, 2]}),
        bound_inputs={"data": _input_ref(uri="file:///tmp/other.json")},
        fingerprint_context=context,
    )
    resource_changed = build_stage_fingerprint(
        _stage(resources={"entries": {"cpu": {"kind": "cpu", "amount": 99}}}),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=context,
    )
    checksum_changed = build_stage_fingerprint(
        _stage(),
        bound_inputs={"data": _input_ref(checksum="sha256:" + "2" * 64)},
        fingerprint_context=context,
    )
    config_changed = build_stage_fingerprint(
        _stage(config={"thresholds": [2, 1]}),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=context,
    )

    assert reordered.fingerprint == base.fingerprint
    assert resource_changed.fingerprint == base.fingerprint
    assert checksum_changed.fingerprint != base.fingerprint
    assert config_changed.fingerprint != base.fingerprint
    assert base.payload.bound_inputs["data"]["source_stage"] == "build"
    assert base.payload.bound_inputs["data"]["source_output"] == "data"
    assert base.payload.factory_init == {}
    assert base.payload.fingerprint_fields == {}
    assert base.payload.factory_target == "project.Report"


def test_fingerprint_tracks_factory_init_and_declared_fingerprint_fields() -> None:
    context = FingerprintContext(python_version="3.12.0", loom_version="0.1.0")
    base = build_stage_fingerprint(
        _stage(
            config={"thresholds": [1, 2]},
        ),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=context,
    )
    with_init = build_stage_fingerprint(
        StageSpec(
            name="report",
            factory=StageFactorySpec(
                target_path="project.Report", init={"worker_count": 4}
            ),
            stage_config={"thresholds": [1, 2]},
            fingerprint_fields={},
            inputs={"data": "build.data"},
            outputs={"summary": OutputSpec(artifact_type="json", codec_key="json.v1")},
        ),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=context,
    )
    with_fingerprint_fields = build_stage_fingerprint(
        StageSpec(
            name="report",
            factory=StageFactorySpec(target_path="project.Report", init={}),
            stage_config={"thresholds": [1, 2]},
            fingerprint_fields={"input_subset": ["foo", "bar"]},
            inputs={"data": "build.data"},
            outputs={"summary": OutputSpec(artifact_type="json", codec_key="json.v1")},
        ),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=context,
    )

    assert base.payload.factory_init == {}
    assert base.fingerprint != with_init.fingerprint
    assert with_init.payload.factory_init == {"worker_count": 4}
    assert base.fingerprint != with_fingerprint_fields.fingerprint
    assert with_fingerprint_fields.payload.fingerprint_fields == {
        "input_subset": ["foo", "bar"]
    }


def test_runtime_fingerprints_are_explicit_stage_or_context_inputs() -> None:
    context = FingerprintContext(python_version="3.12.0", loom_version="0.1.0")
    first_runtime: Fingerprintable = _RuntimeParameter("sha256:" + "a" * 64)
    second_runtime: Fingerprintable = _RuntimeParameter("sha256:" + "b" * 64)
    runtime_free_first = build_stage_fingerprint(
        _stage(),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=context,
    )
    runtime_free_second = build_stage_fingerprint(
        _stage(),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=context,
    )
    stage_explicit_first = build_stage_fingerprint(
        _stage(fingerprint_fields={"runtime_model": first_runtime.fingerprint()}),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=context,
    )
    stage_explicit_second = build_stage_fingerprint(
        _stage(fingerprint_fields={"runtime_model": second_runtime.fingerprint()}),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=context,
    )
    context_explicit_first = build_stage_fingerprint(
        _stage(),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=FingerprintContext(
            python_version="3.12.0",
            loom_version="0.1.0",
            extra={"runtime_model": first_runtime.fingerprint()},
        ),
    )
    context_explicit_second = build_stage_fingerprint(
        _stage(),
        bound_inputs={"data": _input_ref()},
        fingerprint_context=FingerprintContext(
            python_version="3.12.0",
            loom_version="0.1.0",
            extra={"runtime_model": second_runtime.fingerprint()},
        ),
    )

    assert runtime_free_first.fingerprint == runtime_free_second.fingerprint
    assert stage_explicit_first.fingerprint != stage_explicit_second.fingerprint
    assert context_explicit_first.fingerprint != context_explicit_second.fingerprint
    assert stage_explicit_first.payload.fingerprint_fields == {
        "runtime_model": first_runtime.fingerprint()
    }
    assert context_explicit_first.payload.extra == {
        "runtime_model": first_runtime.fingerprint()
    }


def test_fingerprint_requires_all_declared_inputs() -> None:
    try:
        build_stage_fingerprint(_stage(), bound_inputs={})
    except StageFingerprintError as exc:
        assert "pending input" in str(exc)
    else:
        raise AssertionError("missing declared input should fail fingerprinting")


def test_fingerprint_rejects_undeclared_bound_inputs() -> None:
    try:
        build_stage_fingerprint(
            _stage(),
            bound_inputs={"data": _input_ref(), "unused": _input_ref()},
        )
    except StageFingerprintError as exc:
        assert "undeclared bound input" in str(exc)
    else:
        raise AssertionError("undeclared bound input should fail fingerprinting")
