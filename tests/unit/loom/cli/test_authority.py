"""Unit coverage for shared CLI authority helpers."""

from __future__ import annotations

import argparse

import pytest

from loom.cli.authority import (
    add_authority_options,
    authority_resolution_mode_from_namespace,
)
from loom.pipeline.stores import AuthorityResolutionMode

pytestmark = pytest.mark.unit


def test_authority_options_can_opt_into_resolution_mode_parsing() -> None:
    parser = argparse.ArgumentParser()
    add_authority_options(parser, include_resolution_mode=True)

    namespace = parser.parse_args(["--authority-mode", "offline_first"])

    assert (
        authority_resolution_mode_from_namespace(namespace)
        is AuthorityResolutionMode.OFFLINE_FIRST
    )


def test_authority_options_default_to_existing_selection_flags_only() -> None:
    parser = argparse.ArgumentParser()
    add_authority_options(parser)

    namespace = parser.parse_args([])

    assert not hasattr(namespace, "authority_mode")
    assert (
        authority_resolution_mode_from_namespace(namespace)
        is AuthorityResolutionMode.ONLINE_MUTATION
    )


def test_offline_first_shortcut_maps_to_explicit_resolution_mode() -> None:
    parser = argparse.ArgumentParser()
    add_authority_options(parser, include_resolution_mode=True)

    namespace = parser.parse_args(["--offline-first"])

    assert (
        authority_resolution_mode_from_namespace(namespace)
        is AuthorityResolutionMode.OFFLINE_FIRST
    )
