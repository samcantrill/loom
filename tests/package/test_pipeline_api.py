"""Package-level API tests for pipeline and pipeline.graph."""

import pytest


pytestmark = pytest.mark.package


def test_pipeline_public_exports() -> None:
    import loom.pipeline as pipeline
    import loom.pipeline.graph as graph

    assert pipeline
    assert graph
    assert set(pipeline.__all__) == {
        "OutputSpec",
        "StageFactorySpec",
        "StageSpec",
        "PipelineSpec",
        "parse_pipeline_config",
        "PipelineValidationResult",
        "PipelineTargetCheckResult",
        "validate_pipeline_config",
        "check_pipeline_stage_targets",
        "Stage",
        "StageContext",
        "RunStatus",
        "StageStatus",
        "RunStatusRecord",
        "StageStatusRecord",
        "parse_run_status",
        "parse_stage_status",
        "ResourceEntry",
        "ResourceRequest",
        "parse_resource_request",
        "ExecutionOptions",
        "RunEnvironmentRequest",
        "RunOptions",
        "RuntimeProfile",
        "RuntimeProfileCollection",
        "RuntimeKind",
        "RuntimeRequest",
        "StageEnvironmentRequest",
        "StageRuntimeOptions",
        "merge_run_options",
        "parse_run_options",
        "parse_runtime_profile",
        "parse_runtime_profiles",
        "parse_runtime_request",
        "select_runtime_profile",
        "validate_stage_runtime_options",
        "PipelineValidationError",
        "PipelineSpecError",
        "RuntimeResourceError",
        "InputBindingError",
        "PipelineGraphError",
        "PipelineCycleError",
        "StageContractError",
        "StatusSerializationError",
        "PipelineRunner",
        "RunRequest",
        "RunResult",
    }

    assert set(graph.__all__) == {
        "ArtifactReference",
        "ResolvedInputBinding",
        "parse_artifact_reference",
        "bind_stage_inputs",
        "resolve_input_bindings",
        "StageEdgeReason",
        "StageNode",
        "StageEdge",
        "StageGraph",
        "build_stage_graph",
        "upstream_of",
        "downstream_of",
        "transitive_upstream",
        "transitive_downstream",
        "detect_cycles",
        "topological_sort",
    }


def test_pipeline_imports_are_explicit() -> None:
    import loom as loom_package
    import loom.pipeline as pipeline
    import loom.pipeline.graph as graph

    assert "pipeline" not in loom_package.__all__
    assert pipeline
    assert graph
