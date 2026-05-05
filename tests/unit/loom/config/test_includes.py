"""Unit tests for include target resolution primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.config.includes import (
    ConfigIncludeResolutionError,
    IncludeResolutionResult,
    resolve_include_target,
)
from loom.config.provenance import ConfigSource


def _config_source(path: Path, *, kind: str = "base") -> ConfigSource:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("name: test\n", encoding="utf-8")
    return ConfigSource(
        kind=kind,
        path=str(path),
        order=0,
        content_digest="sha256:dummy",
        size_bytes=1,
    )


def test_resolve_bare_name_target_with_mapping_parent_segments(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "experiment.yaml")
    include_target = tmp_path / "model" / "resnet50.yaml"
    include_target.parent.mkdir(parents=True)
    include_target.write_text("name: base\n", encoding="utf-8")

    result = resolve_include_target(
        "resnet50",
        source=source_file,
        include_site_path=("model", "_include_"),
    )

    assert isinstance(result, IncludeResolutionResult)
    assert result.target_kind == "bare_name"
    assert result.explicit_escape is False
    assert result.resolved_path == include_target
    assert result.include_site_path == ("model", "_include_")
    assert result.source_path == str(source_file.path)


def test_resolve_nested_bare_name_target_with_dot_segment(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "project" / "config.yaml")
    include_target = tmp_path / "project" / "encoder.v1" / "small.yaml"
    include_target.parent.mkdir(parents=True)
    include_target.write_text("name: small\n", encoding="utf-8")

    result = resolve_include_target(
        "small",
        source=source_file,
        include_site_path=("encoder.v1", "_include_"),
    )

    assert result.resolved_path == include_target
    assert result.target_kind == "bare_name"
    assert result.include_site_path == ("encoder.v1", "_include_")


@pytest.mark.parametrize(
    "target, relative_path",
    [
        ("./local.yaml", "local.yaml"),
        ("../shared/optimizer.yaml", "../shared/optimizer.yaml"),
        ("components/resnet50.yaml", "components/resnet50.yaml"),
        ("resnet50.yaml", "resnet50.yaml"),
    ],
)
def test_resolve_explicit_relative_targets(tmp_path: Path, target: str, relative_path: str) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    explicit_file = tmp_path / relative_path
    explicit_file.parent.mkdir(parents=True, exist_ok=True)
    explicit_file.write_text("name: explicit\n", encoding="utf-8")

    result = resolve_include_target(
        target,
        source=source_file,
        include_site_path=("pipeline", "_include_"),
    )

    assert result.target_kind == "explicit_relative"
    assert result.explicit_escape is True
    assert result.resolved_path == explicit_file


def test_resolve_absolute_path_target(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    absolute_target = tmp_path / "absolute.yaml"
    absolute_target.write_text("name: absolute\n", encoding="utf-8")

    result = resolve_include_target(
        str(absolute_target),
        source=source_file,
        include_site_path=("pipeline", "_include_"),
    )

    assert result.target_kind == "absolute"
    assert result.explicit_escape is True
    assert result.resolved_path == absolute_target


def test_resolve_file_uri_target(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    file_target = tmp_path / "nested" / "from uri.yaml"
    file_target.parent.mkdir(parents=True)
    file_target.write_text("name: uri\n", encoding="utf-8")

    result = resolve_include_target(
        file_target.as_uri(),
        source=source_file,
        include_site_path=("pipeline", "_include_"),
    )

    assert result.target_kind == "file_uri"
    assert result.explicit_escape is True
    assert result.resolved_path == file_target


@pytest.mark.parametrize(
    "include_site_path, code",
    [
        ((), "invalid_include_site"),
        (("model", "not_include"), "invalid_include_site"),
        (("model", 1, "_include_"), "invalid_include_site"),
        (("model", ".", "_include_"), "invalid_include_site"),
        (("model", "..", "_include_"), "invalid_include_site"),
        (("a/b", "_include_"), "invalid_include_site"),
    ],
)
def test_resolve_target_rejects_invalid_include_site(
    tmp_path: Path,
    include_site_path: tuple[object, ...],
    code: str,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target("resnet50", source=source_file, include_site_path=include_site_path)  # type: ignore[arg-type]
    assert exc.value.context is not None
    assert exc.value.context.code == code


@pytest.mark.parametrize(
    "target, expected",
    [
        ("", "invalid_target"),
        ("my config", "unsupported_target_form"),
        ("${oc.env:HOME}", "resolver_dependent"),
        ("s3://bucket/config.yaml", "unsupported_scheme"),
    ],
)
def test_resolve_target_rejects_unsupported_forms(tmp_path: Path, target: str, expected: str) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            target,
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == expected


def test_resolve_bare_name_target_requires_explicit_yaml_extension(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    include_site_path = ("pipeline", "_include_")

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "resnet50.yaml",
            source=source_file,
            include_site_path=include_site_path,
        )
    assert exc.value.context is not None
    assert exc.value.context.code in {"target_not_found", "target_not_file"}


def test_resolve_target_requires_exact_file_for_explicit_relative(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    base_dir = tmp_path
    missing = base_dir / "components" / "missing.yaml"
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "components/missing.yaml",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == "target_not_found"
    assert exc.value.context.details["candidate_path"] == str(missing)


def test_resolve_target_rejects_file_uri_host_query_fragment_and_malformed_escape(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target("file://localhost/tmp/included.yaml", source=source_file, include_site_path=("pipeline", "_include_"))
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target("file:///tmp/target.yaml?download=1", source=source_file, include_site_path=("pipeline", "_include_"))
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target("file:///tmp/target.yaml#latest", source=source_file, include_site_path=("pipeline", "_include_"))
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target("file:///tmp/%zz.yaml", source=source_file, include_site_path=("pipeline", "_include_"))
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target("file:///tmp/a%2Fb.yaml", source=source_file, include_site_path=("pipeline", "_include_"))
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"


def test_resolve_target_rejects_file_uri_path_as_directory(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    target_dir = tmp_path / "directory"
    target_dir.mkdir()

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            target_dir.as_uri() + "/",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == "target_not_file"


def test_resolution_error_context_carries_candidate_and_target_kind(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    include_site_path = ("pipeline", "_include_")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "missing",
            source=source_file,
            include_site_path=include_site_path,
        )
    context = exc.value.context
    assert context is not None
    assert context.code == "target_not_found"
    assert context.config_path == "$.pipeline._include_"
    assert context.details is not None
    assert context.details["candidate_path"] == str(tmp_path / "pipeline" / "missing.yaml")
    assert context.details["target_kind"] == "bare_name"
    assert context.details["explicit_escape"] is False
