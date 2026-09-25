"""Typed predicates preserve caller types, presence and same-stage meaning."""

import pytest

from loom.runs.query import (
    AllOf,
    AnyOf,
    AnyStage,
    Compare,
    ContainsText,
    Field,
    IsNull,
    Missing,
    Not,
    QueryError,
    QueryRecord,
    RunQuery,
    Truth,
    UNAVAILABLE,
    compare_semver,
    evaluate,
)


def check(predicate, sources, stages=None):
    query = RunQuery(where=predicate).checked()
    return evaluate(query.where, QueryRecord(sources, stages))


@pytest.mark.parametrize(
    "value,operand,expected",
    [(3, 3.0, True), (True, 1, False), ("3", 3, False), (None, None, True)],
)
def test_equality_preserves_json_types(value, operand, expected):
    assert check(
        Compare(Field("metadata", ("revision",)), "eq", operand),
        {"metadata": {"revision": value}},
    ) is (Truth.TRUE if expected else Truth.FALSE)


def test_presence_null_unknown_and_boolean_truth():
    key = Field("metadata", ("n",))
    assert check(Missing(key), {"metadata": {}}) is Truth.TRUE
    assert check(IsNull(key), {"metadata": {"n": None}}) is Truth.TRUE
    assert check(Not(Missing(key)), {}) is Truth.UNKNOWN
    assert check(AllOf((AnyOf(), Missing(key))), {}) is Truth.FALSE
    assert check(AnyOf((AllOf(), Missing(key))), {}) is Truth.TRUE
    assert check(Not(Compare(key, "gte", 3)), {"metadata": {"n": "3"}}) is Truth.UNKNOWN


def test_numeric_membership_literal_paths_and_text():
    record = {
        "tags": {"dataset.version": "V3"},
        "metadata": {"dataset": {"version": 3}},
        "description": "Straße",
    }
    assert (
        check(
            AllOf(
                (
                    Compare(Field("tags", ("dataset.version",)), "eq", "V3"),
                    Compare(
                        Field("metadata", ("dataset", "version")), "in", [False, 3]
                    ),
                    ContainsText(Field("description"), "STRASSE"),
                )
            ),
            record,
        )
        is Truth.TRUE
    )
    assert (
        check(Compare(Field("tags", ("dataset.version",)), "eq", "v3"), record)
        is Truth.FALSE
    )


@pytest.mark.parametrize(
    "a,b",
    [
        ("1.0.0-alpha", "1.0.0-alpha.1"),
        ("1.0.0-alpha.2", "1.0.0-alpha.10"),
        ("1.0.0-1", "1.0.0-a"),
        ("1.0.0-rc.1", "1.0.0"),
        ("1.9.0", "1.10.0"),
    ],
)
def test_strict_semver_order(a, b):
    assert compare_semver(a, b) == -1
    assert compare_semver(b, a) == 1
    assert compare_semver(a + "+build", a) == 0


@pytest.mark.parametrize("version", ["01.0.0", "1.0", "1.0.0-01", "v1.0.0", "1.0.0+"])
def test_invalid_version_operand_is_rejected(version):
    with pytest.raises(QueryError):
        RunQuery(
            where=Compare(Field("tags", ("version",)), "semver_gte", version)
        ).checked()


def test_invalid_stored_version_stays_unknown():
    assert (
        check(
            Not(Compare(Field("tags", ("version",)), "semver_gte", "1.0.0")),
            {"tags": {"version": "next"}},
        )
        is Truth.UNKNOWN
    )


def test_time_ranges_use_instants_and_require_timezone():
    key = Field("native", ("submitted_at",))
    assert (
        check(
            Compare(key, "lt", "2026-09-23T00:00:00.0000001Z"),
            {"native": {"submitted_at": "2026-09-23T00:00:00Z"}},
        )
        is Truth.TRUE
    )
    assert (
        check(
            AllOf(
                (
                    Compare(key, "gte", "2026-09-23T00:00:00Z"),
                    Compare(key, "lt", "2026-09-24T00:00:00Z"),
                )
            ),
            {"native": {"submitted_at": "2026-09-23T10:00:00+10:00"}},
        )
        is Truth.TRUE
    )
    with pytest.raises(QueryError):
        RunQuery(where=Compare(key, "gte", "2026-09-23")).checked()
    assert (
        check(Not(Missing(key)), {"native": {"submitted_at": UNAVAILABLE}})
        is Truth.UNKNOWN
    )


def test_stage_conjunction_is_correlated():
    stages = (
        QueryRecord({"native": {"name": "first", "status": "FAILED"}}),
        QueryRecord({"native": {"name": "second", "status": "SUCCEEDED"}}),
    )
    predicate = AnyStage(
        AllOf(
            (
                Compare(Field("native", ("name",)), "eq", "first"),
                Compare(Field("native", ("status",)), "eq", "SUCCEEDED"),
            )
        )
    )
    assert check(predicate, {}, stages) is Truth.FALSE
    assert check(predicate, {}) is Truth.UNKNOWN


def test_finite_tree_and_unsupported_operands():
    with pytest.raises(QueryError):
        RunQuery(where=AllOf(tuple(AllOf() for _ in range(64)))).checked()
    for operand in (True, "3", None, float("inf")):
        with pytest.raises(QueryError):
            RunQuery(where=Compare(Field("metadata", ("n",)), "gte", operand)).checked()
