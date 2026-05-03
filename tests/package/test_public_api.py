"""Package-level API smoke tests."""

from types import ModuleType

import pytest


pytestmark = pytest.mark.package


def test_phase_one_modules_import_cleanly() -> None:
    from loom import __version__
    import loom.config
    import loom.ids
    import loom.errors
    import loom.io
    import loom.pipeline
    import loom.pipeline.graph
    import loom.pipeline.planning
    import loom.pipeline.execution
    import loom.pipeline.executors
    import loom.pipeline.stores
    import loom.provenance
    import loom.records
    import loom.serialization
    import loom.timestamps

    assert __version__
    assert loom.config.__all__ == [
        "ConfigError",
        "compose_config",
        "instantiate",
        "register_recipe",
    ]


def test_phase_one_modules_are_importable_via_from_import() -> None:
    from loom.ids import ArtifactID, ArtifactType, CodecKey, RecordID, ResourceKey, RunID, StageID
    from loom.errors import ArtifactError, ConfigError, ContractError, ExecutionError
    from loom.timestamps import parse_timestamp, safe_timestamp_for_path, utc_now, utc_timestamp

    assert ArtifactID
    assert ArtifactType
    assert CodecKey
    assert RecordID
    assert ResourceKey
    assert RunID
    assert StageID
    assert ConfigError
    assert ContractError
    assert ArtifactError
    assert ExecutionError
    assert parse_timestamp("2026-05-03T12:34:56Z")
    assert safe_timestamp_for_path(utc_now())
    assert utc_timestamp(utc_now())


def test_empty_skeleton_packages_export_no_public_names() -> None:
    import loom.cli
    import loom.io
    import loom.pipeline
    import loom.pipeline.execution
    import loom.pipeline.executors
    import loom.pipeline.graph
    import loom.pipeline.planning
    import loom.pipeline.stores
    import loom.provenance
    import loom.records
    import loom.serialization

    skeletons: tuple[ModuleType, ...] = (
        loom.cli,
        loom.io,
        loom.pipeline,
        loom.pipeline.execution,
        loom.pipeline.executors,
        loom.pipeline.graph,
        loom.pipeline.planning,
        loom.pipeline.stores,
        loom.provenance,
        loom.records,
        loom.serialization,
    )

    for module in skeletons:
        assert module.__all__ == []
