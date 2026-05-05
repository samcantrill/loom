"""Unit tests for nested target instantiation inside positional args."""

import pytest

from loom.config.errors import TargetImportError
from loom.config.instantiate import instantiate
from tests.support.config_samples import EchoService, RuntimePlaceholder


def test_nested_target_inside_args_can_use_runtime_injection() -> None:
    runtime_value = object()

    result = instantiate(
        {
            "_target_": "tests.support.config_samples:EchoService",
            "_args_": [
                {
                    "_target_": "tests.support.config_samples:RuntimePlaceholder",
                    "_inject_": {"value": "injected_value"},
                }
            ],
        },
        runtime={"injected_value": runtime_value},
    )

    assert isinstance(result, EchoService)
    assert isinstance(result.value, RuntimePlaceholder)
    assert result.value.value is runtime_value


def test_invalid_nested_target_inside_args_reports_child_path() -> None:
    with pytest.raises(TargetImportError) as exc:
        instantiate(
            {
                "_target_": "tests.support.config_samples:EchoService",
                "_args_": [
                    {"_target_": "tests.support.config_samples:MissingTarget"},
                ],
            }
        )

    message = str(exc.value)
    assert "MissingTarget" in message
    assert "$[_args_][0]._target_" in message
