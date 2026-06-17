"""Unit tests for internal argv config shorthand parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from weave._argv import parse_config_argv
from weave.api import ConfigArgvWarning
from weave.errors import ConfigValidationError


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("value: true\n", encoding="utf-8")
    return path


def assert_error_code(exc: pytest.ExceptionInfo[ConfigValidationError], code: str) -> None:
    context = exc.value.context
    assert context is not None
    assert context.code == code
    assert context.source_kind == "argv"
    assert context.source_path == "<argv>"


def test_parse_config_argv_classifies_value_overrides_without_rhs_inference(tmp_path: Path) -> None:
    base = tmp_path / "configs" / "base.yaml"
    result = parse_config_argv(
        [
            "train",
            str(base),
            "data.keyC=newValueC",
            "keyD=newValueD",
            "output_dir=results/model_B.yaml",
            "+runtime.enabled=true",
            "count=3",
            "payload={\"items\":[1,2]}",
        ],
        command_choices={"train", "inspect"},
    )

    assert result.command == "train"
    assert result.base_config_path == str(base)
    assert result.scoped_overlays == ()
    assert result.unparsed_args == ()
    assert result.override_strings == (
        "data.keyC=newValueC",
        "keyD=newValueD",
        "output_dir=results/model_B.yaml",
        "+runtime.enabled=true",
        "count=3",
        "payload={\"items\":[1,2]}",
    )
    assert [override.path for override in result.value_overrides] == [
        "data.keyC",
        "keyD",
        "output_dir",
        "runtime.enabled",
        "count",
        "payload",
    ]
    assert [override.operation for override in result.value_overrides] == [
        "update",
        "update",
        "update",
        "add",
        "update",
        "update",
    ]
    assert result.value_overrides[2].value == "results/model_B.yaml"
    assert result.value_overrides[3].value is True
    assert result.value_overrides[4].value == 3
    assert result.value_overrides[5].value == {"items": [1, 2]}
    assert result.value_overrides[0].order == 2
    assert result.to_dict()["value_overrides"][0]["raw"] == "data.keyC=newValueC"


def test_parse_config_argv_resolves_scoped_overlay_scope_directory_before_base_directory(tmp_path: Path) -> None:
    base = tmp_path / "configs" / "base.yaml"
    scope_candidate = touch(tmp_path / "configs" / "data" / "data_A.yaml")
    base_candidate = touch(tmp_path / "configs" / "data_A.yaml")

    result = parse_config_argv(["train", str(base), "data/=data_A"], command_choices={"train"})

    overlay = result.scoped_overlays[0]
    assert overlay.raw == "data/=data_A"
    assert overlay.scope_path == ("data",)
    assert overlay.operation == "update"
    assert overlay.rhs == "data_A"
    assert overlay.resolved_path == str(scope_candidate.resolve())
    assert [candidate.path for candidate in overlay.candidates] == [
        str(scope_candidate.resolve()),
        str((tmp_path / "configs" / "data" / "data_A.yml").resolve()),
        str(base_candidate.resolve()),
        str((tmp_path / "configs" / "data_A.yml").resolve()),
    ]
    assert [candidate.origin for candidate in overlay.candidates] == [
        "scope_directory",
        "scope_directory",
        "base_directory",
        "base_directory",
    ]
    assert [candidate.exists for candidate in overlay.candidates] == [True, False, True, False]
    assert overlay.to_dict()["candidates"][0]["exists"] is True


def test_parse_config_argv_resolves_nested_add_overlay_and_base_fallback(tmp_path: Path) -> None:
    base = tmp_path / "configs" / "base.yaml"
    base_candidate = touch(tmp_path / "configs" / "pipeline_A.yaml")

    result = parse_config_argv(
        ["train", str(base), "+model/pipeline/=pipeline_A"],
        command_choices={"train"},
    )

    overlay = result.scoped_overlays[0]
    assert overlay.scope_path == ("model", "pipeline")
    assert overlay.operation == "add"
    assert overlay.resolved_path == str(base_candidate.resolve())
    assert [candidate.origin for candidate in overlay.candidates] == [
        "scope_directory",
        "scope_directory",
        "base_directory",
        "base_directory",
    ]


def test_parse_config_argv_uses_exact_absolute_paths_without_suffix_probing(tmp_path: Path) -> None:
    base = tmp_path / "configs" / "base.yaml"
    overlay_path = touch(tmp_path / "elsewhere" / "model_B")

    result = parse_config_argv(["train", str(base), f"model/={overlay_path}"])

    overlay = result.scoped_overlays[0]
    assert overlay.resolved_path == str(overlay_path.resolve())
    assert len(overlay.candidates) == 1
    assert overlay.candidates[0].origin == "absolute"
    assert overlay.candidates[0].path == str(overlay_path.resolve())


def test_parse_config_argv_respects_authored_suffix_and_relative_escape(tmp_path: Path) -> None:
    base = tmp_path / "configs" / "base.yaml"
    shared = touch(tmp_path / "shared" / "data_A.yml")

    result = parse_config_argv(["train", str(base), "data/=../shared/data_A.yml"])

    overlay = result.scoped_overlays[0]
    assert overlay.resolved_path == str(shared.resolve())
    assert [candidate.path for candidate in overlay.candidates] == [
        str((tmp_path / "configs" / "shared" / "data_A.yml").resolve()),
        str(shared.resolve()),
    ]


def test_parse_config_argv_does_not_expand_tilde_rhs(tmp_path: Path) -> None:
    base = tmp_path / "configs" / "base.yaml"
    literal_tilde = touch(tmp_path / "configs" / "model" / "~" / "local.yaml")

    result = parse_config_argv(["train", str(base), "model/=~/local"])

    overlay = result.scoped_overlays[0]
    assert overlay.resolved_path == str(literal_tilde.resolve())
    assert str(Path.home()) not in overlay.resolved_path


def test_parse_config_argv_records_allowed_unparsed_args(tmp_path: Path) -> None:
    base = tmp_path / "configs" / "base.yaml"
    result = parse_config_argv(
        ["train", str(base), "--dry-run", "-v"],
        command_choices={"train"},
        allow_unparsed=True,
    )

    assert result.unparsed_arg_strings == ("--dry-run", "-v")
    assert [arg.order for arg in result.unparsed_args] == [2, 3]
    assert result.value_overrides == ()
    assert result.scoped_overlays == ()


def test_parse_config_argv_rejects_disallowed_unparsed_args(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError) as exc:
        parse_config_argv(["train", str(tmp_path / "base.yaml"), "--dry-run"])

    assert_error_code(exc, "disallowed_unparsed_args")
    assert exc.value.context is not None
    assert exc.value.context.details == {
        "command": "train",
        "unparsed_args": ["--dry-run"],
        "unparsed_arg_orders": [2],
    }


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        ([], "missing_argv_command"),
        (["train"], "missing_base_config_path"),
        (["serve", "base.yaml"], "unknown_command"),
        (["train", "base.yaml", "not-a-shorthand"], "malformed_argv_token"),
        (["train", "base.yaml", "/=root"], "unsupported_root_overlay"),
        (["train", "base.yaml", "+/=root"], "unsupported_root_overlay"),
        (["train", "base.yaml", "model/pipeline=value"], "invalid_scoped_overlay_marker"),
        (["train", "base.yaml", "model//pipeline/=pipeline_A"], "invalid_scoped_overlay_scope"),
        (["train", "base.yaml", "model/="], "missing_scoped_overlay_rhs"),
    ],
)
def test_parse_config_argv_structured_parser_errors(argv: list[str], code: str) -> None:
    with pytest.raises(ConfigValidationError) as exc:
        parse_config_argv(argv, command_choices={"train"})

    assert_error_code(exc, code)


def test_parse_config_argv_wraps_invalid_value_override_with_token_context() -> None:
    with pytest.raises(ConfigValidationError) as exc:
        parse_config_argv(["train", "base.yaml", "a..b=1"], command_choices={"train"})

    assert_error_code(exc, "invalid_value_override")
    context = exc.value.context
    assert context is not None
    assert context.details is not None
    assert context.details["command"] == "train"
    assert context.details["token"] == "a..b=1"
    assert "Invalid override path" in str(context.details["error"])


def test_parse_config_argv_missing_overlay_reports_candidates(tmp_path: Path) -> None:
    base = tmp_path / "configs" / "base.yaml"

    with pytest.raises(ConfigValidationError) as exc:
        parse_config_argv(["train", str(base), "model/=model_B"])

    assert_error_code(exc, "missing_scoped_overlay_source")
    context = exc.value.context
    assert context is not None
    assert context.details is not None
    assert context.details["command"] == "train"
    assert context.details["scope_path"] == ["model"]
    assert context.details["rhs"] == "model_B"
    assert context.details["candidate_paths"] == [
        str((tmp_path / "configs" / "model" / "model_B.yaml").resolve()),
        str((tmp_path / "configs" / "model" / "model_B.yml").resolve()),
        str((tmp_path / "configs" / "model_B.yaml").resolve()),
        str((tmp_path / "configs" / "model_B.yml").resolve()),
    ]


def test_parse_config_argv_does_not_validate_base_config_file_existence(tmp_path: Path) -> None:
    base = tmp_path / "missing" / "base.yaml"

    result = parse_config_argv(["train", str(base), "key=value"], command_choices={"train"})

    assert result.base_config_path == str(base)
    assert result.value_overrides[0].path == "key"



def test_config_argv_warning_validates_plain_data() -> None:
    warning = ConfigArgvWarning(
        code="possible_missing_scoped_overlay_slash",
        message="Use scoped overlay syntax.",
        source_order=2,
        token="model=model_B",
        path="model",
        remediation="Use model/=model_B.",
        details={"candidate_paths": ["/tmp/model/model_B.yaml"]},
    )

    payload = warning.to_dict()
    assert payload["code"] == "possible_missing_scoped_overlay_slash"
    assert payload["source_order"] == 2
    assert payload["details"] == {"candidate_paths": ["/tmp/model/model_B.yaml"]}

    with pytest.raises(ConfigValidationError):
        ConfigArgvWarning(
            code="bad",
            message="bad",
            source_order=0,
            token="x=y",
            path="x",
            remediation=None,
            details={"bad": {"not-plain"}},  # type: ignore[dict-item]
        )
