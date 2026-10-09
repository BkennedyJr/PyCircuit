"""
Tests for core.placement: a part waiting to be placed (Billie, Oct 9
12:07). Pure Python, no Qt.
"""

import pytest

from core.components import COMPONENT_DEFINITIONS, VALID_ROTATIONS, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.placement import (
    DIRECTIONS,
    PendingPlacement,
    get_direction_at_rotation_zero,
    get_direction_for_rotation,
    get_rotation_for_direction,
)


def test_two_pin_parts_point_toward_their_second_pin():
    for kind in ("resistor", "capacitor", "capacitor_polarized", "inductor",
                 "diode", "led"):
        assert {
            direction: get_rotation_for_direction(kind, direction)
            for direction in DIRECTIONS
        } == {"right": 0, "down": 90, "left": 180, "up": 270}


def test_upright_sources_and_ground_point_down_at_rotation_zero():
    for kind in ("dc_source", "ac_source", "current_source", "ground"):
        assert get_direction_at_rotation_zero(kind) == "down"
        assert {
            direction: get_rotation_for_direction(kind, direction)
            for direction in DIRECTIONS
        } == {"down": 0, "left": 90, "up": 180, "right": 270}


def test_transistors_and_opamps_point_right_at_rotation_zero():
    for kind in ("npn", "pnp", "opamp_generic", "opamp_741"):
        assert get_direction_at_rotation_zero(kind) == "right"
        assert get_rotation_for_direction(kind, "up") == 270


def test_direction_and_rotation_are_inverse_for_every_kind():
    for kind in COMPONENT_DEFINITIONS:
        for rotation in VALID_ROTATIONS:
            direction = get_direction_for_rotation(kind, rotation)

            assert get_rotation_for_direction(kind, direction) == rotation


def test_direction_matches_the_second_pin_on_the_grid():
    collection = ComponentCollection()
    grid = ConnectionGrid(8, 8)
    expected_pins = {
        "right": ["NODE_R04_C04", "NODE_R04_C05"],
        "down": ["NODE_R04_C04", "NODE_R05_C04"],
        "left": ["NODE_R04_C04", "NODE_R04_C03"],
        "up": ["NODE_R04_C04", "NODE_R03_C04"],
    }

    for kind in ("capacitor_polarized", "dc_source"):
        for direction, pins in expected_pins.items():
            pending = PendingPlacement(
                collection, grid, kind, "", 4, 4, direction=direction
            )

            assert pending.build_component().get_pin_identifiers() == pins


def test_unknown_direction_is_refused():
    with pytest.raises(ComponentError) as error:
        get_rotation_for_direction("resistor", "north")

    assert str(error.value) == (
        "Direction must be one of right, down, left, up, not 'north'."
    )


def billie_grid():
    """R1 on R7 C3-C4, as in Billie's report."""
    collection = ComponentCollection()
    grid = ConnectionGrid(8, 8)
    collection.add_component("resistor", 7, 3, "1k", grid)

    return collection, grid


def test_billies_cap_on_r1s_pins_is_refused_with_the_free_directions():
    collection, grid = billie_grid()
    pending = PendingPlacement(
        collection, grid, "capacitor_polarized", "", 7, 3
    )

    assert pending.direction == "right"
    assert pending.get_free_directions() == ["down", "left", "up"]

    with pytest.raises(ComponentError) as error:
        pending.commit()

    assert str(error.value) == (
        "R1 (Resistor) already connects exactly these grid points: "
        "NODE_R07_C03, NODE_R07_C04. Pick other grid points or another "
        "rotation, or select R1 to edit it. Free directions at "
        "NODE_R07_C03: Down, Left, Up."
    )
    assert [c.reference for c in collection.get_components()] == ["R1"]


def test_billies_cap_down_from_r7_c4_is_placed():
    collection, grid = billie_grid()
    pending = PendingPlacement(
        collection, grid, "capacitor_polarized", "", 7, 3
    )
    pending.move_to(7, 4)
    pending.set_direction("down")

    assert pending.check() is None
    capacitor = pending.commit()

    assert capacitor.reference == "C1"
    assert capacitor.rotation == 90
    assert capacitor.get_pin_identifiers() == ["NODE_R07_C04", "NODE_R08_C04"]
    assert collection.get_component("C1") is capacitor


def test_nothing_is_stored_until_commit():
    collection, grid = billie_grid()
    pending = PendingPlacement(collection, grid, "resistor", "4k7", 2, 2)
    pending.set_direction("down")
    pending.move_to(3, 3)
    pending.check()
    pending.get_free_directions()

    assert [c.reference for c in collection.get_components()] == ["R1"]
    assert pending.build_component().reference == "R2"


def test_off_grid_directions_are_not_free():
    collection = ComponentCollection()
    pending = PendingPlacement(
        collection, ConnectionGrid(8, 8), "resistor", "", 8, 8
    )

    assert pending.check() == (
        "R1 does not fit at row 8, column 8: a pin would fall outside the "
        "8 x 8 grid. Choose a point further inside the grid."
    )
    assert pending.get_free_directions() == ["left", "up"]


def test_no_free_direction_says_pick_another_point():
    collection = ComponentCollection()
    grid = ConnectionGrid(4, 4)
    collection.add_component("resistor", 1, 1, "1k", grid)
    collection.add_component("resistor", 1, 1, "1k", grid, 90)
    pending = PendingPlacement(collection, grid, "capacitor", "", 1, 1)

    assert pending.get_free_directions() == []
    assert pending.describe_free_directions() == (
        "No direction is free at NODE_R01_C01; pick another grid point."
    )


def test_bad_value_is_refused_before_any_ghost():
    collection = ComponentCollection()
    grid = ConnectionGrid(8, 8)

    with pytest.raises(ComponentError) as pending_error:
        PendingPlacement(collection, grid, "resistor", "abc", 2, 2)

    with pytest.raises(ComponentError) as add_error:
        collection.add_component("resistor", 2, 2, "abc", grid)

    assert str(pending_error.value) == str(add_error.value)


def test_empty_value_takes_the_kinds_default():
    pending = PendingPlacement(
        ComponentCollection(), ConnectionGrid(8, 8), "capacitor", "  ", 2, 2
    )

    assert pending.value_text == (
        COMPONENT_DEFINITIONS["capacitor"]["default_value_text"]
    )


def test_settings_are_kept_for_the_commit():
    collection = ComponentCollection()
    pending = PendingPlacement(
        collection, ConnectionGrid(8, 8), "ac_source", "2", 2, 2,
        {"frequency": "50"}
    )
    source = pending.commit()

    assert source.parameter_texts["frequency"] == "50"
    assert source.label_text() == "V1 2V 50Hz"


@pytest.mark.parametrize("row_number, column_number", [
    (0, 1), (9, 1), (1, 0), (1, 9), (True, 1), ("1", 1),
])
def test_point_must_be_on_the_grid(row_number, column_number):
    with pytest.raises(ComponentError) as error:
        PendingPlacement(
            ComponentCollection(), ConnectionGrid(8, 8), "resistor", "",
            row_number, column_number
        )

    assert str(error.value) == (
        f"Row {row_number!r}, column {column_number!r} is not a point on "
        "the 8 x 8 grid."
    )


def test_collection_and_grid_types_are_checked():
    with pytest.raises(ComponentError) as error:
        PendingPlacement([], ConnectionGrid(8, 8), "resistor", "", 1, 1)

    assert str(error.value) == "Expected a ComponentCollection, not list."

    with pytest.raises(ComponentError) as error:
        PendingPlacement(ComponentCollection(), None, "resistor", "", 1, 1)

    assert str(error.value) == "Expected a ConnectionGrid, not NoneType."


def test_unknown_kind_is_refused():
    with pytest.raises(ComponentError) as error:
        PendingPlacement(
            ComponentCollection(), ConnectionGrid(8, 8), "valve", "", 1, 1
        )

    assert str(error.value) == "Unknown component kind 'valve'."
