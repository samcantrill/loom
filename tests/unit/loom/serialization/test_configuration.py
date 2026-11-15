"""Persisted configuration wire version and authored-order preservation."""

import json

import pytest

from loom.serialization.configuration import configuration_json, read_configuration_json
from loom.serialization.errors import DeserializationError


def test_nested_order_and_duplicates_survive_snapshot_wire():
    original = {"z": {"reconstruction": {}, "detrending": {}}, "a": [3, 1, 3]}
    wire = configuration_json(original)
    assert json.loads(wire)["schema"] == "weave.ordered-config.v1"
    decoded = read_configuration_json(wire)
    assert list(decoded) == ["z", "a"]
    assert list(decoded["z"]) == ["reconstruction", "detrending"]
    assert decoded["a"] == [3, 1, 3]
    assert configuration_json(decoded) == wire


def test_legacy_snapshot_is_read_without_inventing_authored_order():
    wire = '{"a": 1, "z": 2}'
    assert list(read_configuration_json(wire)) == ["a", "z"]


@pytest.mark.parametrize("value", [
    {"schema": "weave.ordered-config.v0", "value": {}},
    {"schema": "weave.ordered-config.v1", "value": {"kind": "sequence", "items": []}},
    {"schema": "weave.ordered-config.v1", "value": {}},
])
def test_unknown_or_malformed_ordered_snapshot_is_not_treated_as_legacy(value):
    with pytest.raises(DeserializationError):
        read_configuration_json(json.dumps(value))
