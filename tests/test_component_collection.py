"""
Tests for core.components.ComponentCollection and the validating
Component.row_number, column_number and set_value_text.
"""

import pytest

from core.components import Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError


@pytest.fixture
def grid():
    return ConnectionGrid(8, 8)


@pytest.fixture
def collection():
    return ComponentCollection()


# References ---------------------------------------------------------------


def test_two_resistors_become_r1_and_r2(collection, grid):
    first = collection.add_component("resistor", 4, 4, "1k", grid)
    second = collection.add_component("resistor", 6, 4, "2k2", grid)

    assert (first.reference, second.reference) == ("R1", "R2")


def test_removed_reference_is_reused(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)
    collection.add_component("resistor", 6, 4, "1k", grid)
    collection.remove_component("R1")

    assert collection.next_reference("resistor") == "R1"
    assert collection.add_component("resistor", 2, 4, "1k", grid).reference \
        == "R1"


def test_diode_and_led_share_the_d_prefix(collection, grid):
    diode = collection.add_component("diode", 4, 4, "1N4148", grid)
    led = collection.add_component("led", 6, 4, "LED_RED", grid)

    assert (diode.reference, led.reference) == ("D1", "D2")


def test_each_prefix_counts_separately(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)

    assert collection.next_reference("capacitor") == "C1"
    assert collection.next_reference("capacitor_polarized") == "C1"
    assert collection.next_reference("ground") == "GND1"


def test_next_reference_rejects_unknown_kind(collection):
    with pytest.raises(ComponentError):
        collection.next_reference("transistor")


# Adding --------------------------------------------------------------------


def test_resistor_at_corner_raises(collection, grid):
    with pytest.raises(ComponentError) as error_info:
        collection.add_component("resistor", 1, 1, "1k", grid)

    assert "further inside the grid" in str(error_info.value)
    assert collection.get_components() == []


def test_resistor_at_left_edge(collection, grid):
    # Pins of a resistor at (4,1) would be at columns 0 and 2.
    with pytest.raises(ComponentError):
        collection.add_component("resistor", 4, 1, "1k", grid)

    resistor = collection.add_component("resistor", 4, 2, "1k", grid)
    assert resistor.get_pin_positions() == [("1", 4, 1), ("2", 4, 3)]


def test_failed_add_does_not_use_up_a_reference(collection, grid):
    with pytest.raises(ComponentError):
        collection.add_component("resistor", 1, 1, "1k", grid)

    assert collection.add_component("resistor", 4, 4, "1k", grid).reference \
        == "R1"


@pytest.mark.parametrize(
    "kind, expected_text",
    [("resistor", "1k"), ("capacitor", "100n"), ("diode", "1N4148")]
)
def test_empty_value_uses_default(collection, grid, kind, expected_text):
    component = collection.add_component(kind, 4, 4, "  ", grid)

    assert component.value_text == expected_text


def test_ground_can_sit_in_a_corner(collection, grid):
    ground = collection.add_component("ground", 8, 8, "", grid)

    assert ground.reference == "GND1"
    assert ground.get_pin_identifiers() == ["NODE_R08_C08"]


def test_add_with_rotation(collection, grid):
    resistor = collection.add_component("resistor", 4, 4, "4k7", grid, 90)

    assert resistor.get_pin_positions() == [("1", 3, 4), ("2", 5, 4)]


def test_add_rejects_bad_value_and_stores_nothing(collection, grid):
    with pytest.raises(ComponentError):
        collection.add_component("resistor", 4, 4, "abc", grid)

    assert collection.components_by_reference == {}


@pytest.mark.parametrize("bad_grid", [None, (8, 8), "grid"])
def test_add_requires_a_connection_grid(collection, bad_grid):
    with pytest.raises(ComponentError):
        collection.add_component("resistor", 4, 4, "1k", bad_grid)


# Lookup and ordering -------------------------------------------------------


@pytest.mark.parametrize("reference", ["R9", "r1", None, ["R1"]])
def test_get_component_unknown_raises(collection, grid, reference):
    collection.add_component("resistor", 4, 4, "1k", grid)

    with pytest.raises(ComponentError):
        collection.get_component(reference)


def test_get_components_orders_naturally(collection):
    big_grid = ConnectionGrid(30, 30)

    for row_number in range(2, 13):
        collection.add_component("resistor", row_number, 4, "1k", big_grid)

    collection.add_component("capacitor", 4, 10, "1n", big_grid)

    references = [
        component.reference for component in collection.get_components()
    ]

    assert references == [
        "C1", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10",
        "R11",
    ]


# Rotating ------------------------------------------------------------------


def test_rotate_cycles_through_all_angles(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)

    angles = [collection.rotate_component("R1", grid) for unused in range(4)]

    assert angles == [90, 180, 270, 0]


def test_rotation_off_grid_raises_and_keeps_old_rotation(collection, grid):
    collection.add_component("resistor", 1, 4, "1k", grid)

    with pytest.raises(ComponentError) as error_info:
        collection.rotate_component("R1", grid)

    assert "cannot be rotated" in str(error_info.value)
    assert collection.get_component("R1").rotation == 0
    assert collection.get_component("R1").get_pin_positions() == [
        ("1", 1, 3), ("2", 1, 5)
    ]


def test_rotate_unknown_raises(collection, grid):
    with pytest.raises(ComponentError):
        collection.rotate_component("R1", grid)


# Values --------------------------------------------------------------------


def test_set_component_value(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)

    resistor = collection.set_component_value("R1", "10k")
    assert (resistor.value_text, resistor.value) == ("10k", 10000.0)

    with pytest.raises(ComponentError):
        collection.set_component_value("R1", "abc")

    assert (resistor.value_text, resistor.value) == ("10k", 10000.0)
    assert resistor.label_text() == "R1 10k"


def test_set_component_value_rejects_zero_resistor(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)

    with pytest.raises(ComponentError):
        collection.set_component_value("R1", "0")

    assert collection.get_component("R1").value == 1000.0


def test_set_component_value_on_model_part(collection, grid):
    collection.add_component("npn", 4, 4, "", grid)

    transistor = collection.set_component_value("Q1", "2N2222")

    assert (transistor.value_text, transistor.value) == ("2N2222", None)


# Removing ------------------------------------------------------------------


def test_remove_unknown_raises(collection):
    with pytest.raises(ComponentError):
        collection.remove_component("R1")


def test_remove_components_outside_grid(collection, grid):
    collection.add_component("resistor", 4, 7, "1k", grid)
    collection.add_component("resistor", 4, 3, "1k", grid)
    collection.add_component("ground", 8, 8, "", grid)

    grid.configure(8, 6)

    assert collection.remove_components_outside_grid(grid) == ["GND1", "R1"]
    assert [c.reference for c in collection.get_components()] == ["R2"]


def test_nothing_removed_when_grid_grows(collection, grid):
    collection.add_component("resistor", 4, 7, "1k", grid)
    grid.configure(10, 10)

    assert collection.remove_components_outside_grid(grid) == []


# Validating row, column and value on Component ----------------------------


@pytest.mark.parametrize("bad_number", [0, 51, 4.0, True, "4", None])
def test_row_and_column_assignment_is_validated(bad_number):
    resistor = Component("resistor", "R1", "1k", 4, 4)

    with pytest.raises(ComponentError):
        resistor.row_number = bad_number

    with pytest.raises(ComponentError):
        resistor.column_number = bad_number

    assert (resistor.row_number, resistor.column_number) == (4, 4)


def test_valid_row_assignment_moves_pins():
    resistor = Component("resistor", "R1", "1k", 4, 4)
    resistor.row_number = 6

    assert resistor.get_pin_positions() == [("1", 6, 3), ("2", 6, 5)]


def test_set_value_text_keeps_pair_on_error():
    capacitor = Component("capacitor", "C1", "100n", 4, 4)

    with pytest.raises(ComponentError):
        capacitor.set_value_text("abc")

    assert (capacitor.value_text, capacitor.value) == ("100n", 1e-07)

    capacitor.set_value_text(" 2.2u ")
    assert (capacitor.value_text, capacitor.value) == ("2.2u", 2.2e-06)


# Argument checks and read-only fields -------------------------------------


@pytest.mark.parametrize("bad_component", [None, "R1", 5])
def test_ensure_pins_fit_grid_rejects_non_component(grid, bad_component):
    with pytest.raises(ComponentError):
        ComponentCollection.ensure_pins_fit_grid(bad_component, grid)


@pytest.mark.parametrize("bad_grid", [None, (8, 8), "grid"])
def test_ensure_pins_fit_grid_rejects_non_grid(bad_grid):
    resistor = Component("resistor", "R1", "1k", 4, 4)

    with pytest.raises(ComponentError):
        ComponentCollection.ensure_pins_fit_grid(resistor, bad_grid)


def test_ensure_pins_fit_grid_accepts_fitting_part(grid):
    resistor = Component("resistor", "R1", "1k", 4, 4)

    assert ComponentCollection.ensure_pins_fit_grid(resistor, grid) is None


def test_kind_and_reference_are_read_only(collection, grid):
    resistor = collection.add_component("resistor", 4, 4, "1k", grid)

    with pytest.raises(ComponentError):
        resistor.reference = "R99"

    with pytest.raises(ComponentError):
        resistor.kind = "capacitor"

    assert (resistor.kind, resistor.reference) == ("resistor", "R1")
    assert collection.get_component("R1") is resistor
