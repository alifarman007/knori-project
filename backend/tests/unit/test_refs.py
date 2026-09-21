"""Short ids are the only names the model gets, and they only work one way.

The property that matters: a ref resolves **only** if it was in the input. A
model that invents ``S99`` gets nothing back, which is what stops a hallucinated
id from ever reaching a row.
"""

from __future__ import annotations

import uuid

import pytest

from ros.engine.refs import RefMap, RefSet, UnknownRef, parse_ref


def test_refs_are_numbered_in_input_order() -> None:
    ids = [str(uuid.uuid4()) for _ in range(3)]
    table = RefMap.build("S", ids)

    assert table.refs() == ("S1", "S2", "S3")
    assert [table.id_for(ref) for ref in table.refs()] == ids
    assert table.ref_for(ids[1]) == "S2"


def test_round_trip_is_exact() -> None:
    ids = [uuid.uuid4() for _ in range(5)]
    table = RefMap.build("I", ids)

    for real in ids:
        assert table.resolve(table.ref_for(real) or "") == str(real)


def test_repeated_ids_get_one_ref() -> None:
    same = uuid.uuid4()
    table = RefMap.build("M", [same, same, uuid.uuid4()])

    assert len(table) == 2
    assert table.refs() == ("M1", "M2")


def test_unknown_ref_is_refused_not_guessed() -> None:
    table = RefMap.build("S", [uuid.uuid4()])

    assert table.id_for("S2") is None
    assert table.id_for("banana") is None
    assert "S2" not in table
    with pytest.raises(UnknownRef):
        table.resolve("S2")


def test_empty_map_resolves_nothing() -> None:
    table = RefMap.empty("S")

    assert len(table) == 0
    with pytest.raises(UnknownRef):
        table.resolve("S1")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("S12", ("S", 12)), (" I3 ", ("I", 3)), ("M0", ("M", 0)), ("s1", None), ("S", None)],
)
def test_parse_ref(value: str, expected: tuple[str, int] | None) -> None:
    assert parse_ref(value) == expected


def test_ref_set_routes_by_prefix() -> None:
    signal, interpretation, message = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    refs = RefSet.build(
        signal_ids=[signal], interpretation_ids=[interpretation], message_ids=[message]
    )

    assert refs.resolve("S1") == str(signal)
    assert refs.resolve("I1") == str(interpretation)
    assert refs.resolve("M1") == str(message)


def test_ref_set_refuses_a_ref_from_another_space() -> None:
    refs = RefSet.build(signal_ids=[uuid.uuid4()])

    with pytest.raises(UnknownRef):
        refs.resolve("I1")
    with pytest.raises(UnknownRef):
        refs.resolve("X1")
