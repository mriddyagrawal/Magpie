"""Slot markers: the contract between the flattener and the transport."""

from __future__ import annotations

from src.inference.image_slots import slot, split_slots, strip_slots


def test_round_trip_preserves_order() -> None:
    text = f"intro{slot(0)}middle{slot(1)}tail"
    assert split_slots(text) == ["intro", 0, "middle", 1, "tail"]


def test_adjacent_and_edge_slots_produce_no_empty_runs() -> None:
    assert split_slots(f"{slot(0)}{slot(1)}") == [0, 1]
    assert split_slots(f"{slot(3)}x") == [3, "x"]
    assert split_slots("plain") == ["plain"]
    assert split_slots("") == []


def test_strip_removes_every_marker() -> None:
    assert strip_slots(f"a{slot(0)}b{slot(12)}") == "ab"
    assert "\x00" not in strip_slots(slot(0))
