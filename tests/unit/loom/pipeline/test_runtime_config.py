"""Unit tests for runtime config section adapters."""

from __future__ import annotations

import pytest

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.runtime import (
    RuntimeConfigSections,
    merge_config_run_options,
    parse_runtime_config_sections,
)


pytestmark = pytest.mark.unit


def test_parse_runtime_config_sections_defaults_to_empty_runtime_options() -> None:
    sections = parse_runtime_config_sections({"pipeline": {"stages": []}})

    assert isinstance(sections, RuntimeConfigSections)
    assert sections.to_dict() == {"runtime": {}, "runtime_profiles": {}}
    assert sections.merge().to_dict()["executor"] is None


def test_merge_config_run_options_applies_profile_then_sparse_explicit_source() -> None:
    options = merge_config_run_options(
        {
            "runtime": {
                "profile": "cluster",
                "tags": {"team": "platform"},
                "dry_run": True,
            },
            "runtime_profiles": {
                "cluster": {
                    "executor": "local",
                    "tags": {"queue": "short"},
                    "stage_options": {
                        "train": {
                        "resources": {
                            "entries": {
                                "cpu": {"kind": "cpu", "amount": 8},
                                "memory": {
                                    "kind": "memory",
                                    "amount": 32768,
                                    "unit": "MiB",
                                },
                            }
                        }
                        }
                    },
                }
            },
        },
        explicit={
            "tags": {"owner": "cli"},
            "notes": ["from CLI"],
            "selectors": {"only_stages": ["train"]},
        },
        known_stage_ids=("train",),
    )

    assert options.executor == "local"
    assert options.profile == "cluster"
    assert options.dry_run is True
    assert options.tags == {"owner": "cli", "queue": "short", "team": "platform"}
    assert options.notes == ("from CLI",)
    assert options.to_plan_selectors().only_stages == ("train",)
    assert set(options.stage_options) == {"train"}


def test_merge_config_run_options_allows_explicit_profile_override() -> None:
    options = merge_config_run_options(
        {
            "runtime": {"profile": "local"},
            "runtime_profiles": {
                "local": {"executor": "local", "tags": {"mode": "local"}},
                "debug": {"executor": "local", "tags": {"mode": "debug"}},
            },
        },
        explicit={"profile": "debug"},
    )

    assert options.profile == "debug"
    assert options.tags == {"mode": "debug"}


def test_merge_config_run_options_rejects_unknown_stage_options() -> None:
    with pytest.raises(RuntimeResourceError, match="unknown stage"):
        merge_config_run_options(
            {
                "runtime": {
                    "stage_options": {
                        "missing": {
                            "resources": {
                                "entries": {"cpu": {"kind": "cpu", "amount": 1}}
                            }
                        }
                    }
                }
            },
            known_stage_ids=("known",),
        )


def test_parse_runtime_config_sections_rejects_non_mapping_sections() -> None:
    with pytest.raises(RuntimeResourceError, match=r"\$\.runtime must be a mapping"):
        parse_runtime_config_sections({"runtime": ["bad"]})

    with pytest.raises(RuntimeResourceError, match="RuntimeProfileCollection"):
        parse_runtime_config_sections({"runtime_profiles": ["bad"]})
