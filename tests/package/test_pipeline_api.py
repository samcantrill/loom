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
        "SubmittedOperationError",
        "SubmittedOperationRecord",
        "SubmittedOperationState",
        "is_active_submitted_operation",
        "is_terminal_submitted_operation",
        "ResourceEntry",
        "ResourceRequest",
        "parse_resource_request",
        "CONTINUE_INDEPENDENT_FAILURE_POLICY",
        "DEFAULT_EXECUTOR_DESCRIPTOR_REGISTRY",
        "DEFAULT_FAILURE_POLICY",
        "DEFAULT_MAX_PARALLEL_STAGES",
        "RUNTIME_CONFIG_SECTION",
        "RUNTIME_METADATA_SCHEMA_VERSION",
        "RUNTIME_PROFILES_CONFIG_SECTION",
        "CapabilityDiagnostic",
        "CapabilitySeverity",
        "CapabilityValidationResult",
        "ExecutionOptions",
        "ExecutorDescriptor",
        "ExecutorDescriptorRegistry",
        "ParallelExecutionOptions",
        "RunEnvironmentRequest",
        "RunOptions",
        "ResolvedStageRuntimeOptions",
        "ResourceCapability",
        "ResourceEnforcementExpectation",
        "ResourceSupportLevel",
        "RuntimeConfigSections",
        "RuntimeMetadata",
        "RuntimeProfile",
        "RuntimeProfileCollection",
        "RuntimeKind",
        "RuntimeRequest",
        "StageEnvironmentRequest",
        "StageRuntimeOptions",
        "build_runtime_metadata",
        "merge_config_run_options",
        "merge_run_options",
        "parallel_execution_options",
        "parse_run_options",
        "parse_runtime_config_sections",
        "parse_runtime_profile",
        "parse_runtime_profiles",
        "parse_runtime_request",
        "resolve_executor_descriptor",
        "resolve_run_runtime",
        "select_runtime_profile",
        "validate_executor_capabilities",
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
