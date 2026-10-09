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
    # From the top-right corner the second pin would be at column 9.
    with pytest.raises(ComponentError) as error_info:
        collection.add_component("resistor", 1, 8, "1k", grid)

    assert "further inside the grid" in str(error_info.value)
    assert collection.get_components() == []


def test_resistor_at_left_edge(collection, grid):
    # Turned 180 deg at (4,1), the second pin would be at column 0.
    with pytest.raises(ComponentError):
        collection.add_component("resistor", 4, 1, "1k", grid, 180)

    resistor = collection.add_component("resistor", 4, 1, "1k", grid)
    assert resistor.get_pin_positions() == [("1", 4, 1), ("2", 4, 2)]


def test_failed_add_does_not_use_up_a_reference(collection, grid):
    with pytest.raises(ComponentError):
        collection.add_component("resistor", 1, 8, "1k", grid)

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

    assert resistor.get_pin_positions() == [("1", 4, 4), ("2", 5, 4)]


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
    # On the bottom row, a quarter turn would put pin 2 on row 9.
    collection.add_component("resistor", 8, 4, "1k", grid)

    with pytest.raises(ComponentError) as error_info:
        collection.rotate_component("R1", grid)

    assert "cannot be rotated" in str(error_info.value)
    assert collection.get_component("R1").rotation == 0
    assert collection.get_component("R1").get_pin_positions() == [
        ("1", 8, 4), ("2", 8, 5)
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

    assert resistor.get_pin_positions() == [("1", 6, 4), ("2", 6, 5)]


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


# Overlaps: the same pin points (any kind, either order) or the same body
# centre are refused; sharing single pins is how parts connect. -------------


def add_stacked(collection, kind, reference, value_text, row, column,
                rotation):
    """
    Store a part directly, bypassing add_component's checks, so the
    rotate guards can still be tested on an overlapping pair.
    """
    component = Component(kind, reference, value_text, row, column, rotation)
    collection.components_by_reference[reference] = component
    return component


def test_same_pins_are_refused_with_a_clear_message(collection, grid):
    collection.add_component("resistor", 2, 2, "1k", grid)

    with pytest.raises(ComponentError) as error_info:
        collection.add_component("resistor", 2, 2, "2k2", grid)

    assert str(error_info.value) == (
        "R1 (Resistor) already connects exactly these grid points: "
        "NODE_R02_C02, NODE_R02_C03. Pick other grid points or another "
        "rotation, or select R1 to edit it."
    )


def test_refused_overlap_stores_nothing_and_keeps_numbering(
        collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)

    with pytest.raises(ComponentError):
        collection.add_component("resistor", 4, 4, "1k", grid)

    assert [c.reference for c in collection.get_components()] == ["R1"]
    assert collection.get_component("R1").value_text == "1k"
    assert collection.add_component("resistor", 5, 5, "1k", grid).reference \
        == "R2"


@pytest.mark.parametrize("kind, value", [
    ("capacitor", "100n"), ("capacitor_polarized", "10u"),
    ("inductor", "10u"), ("diode", "1N4148"), ("led", "LED_RED"),
])
def test_another_kind_on_the_same_pins_is_refused(collection, grid, kind,
                                                  value):
    collection.add_component("resistor", 4, 4, "1k", grid)

    with pytest.raises(ComponentError, match=r"^R1 \(Resistor\) already "
                       r"connects exactly these grid points: NODE_R04_C04, "
                       r"NODE_R04_C05\."):
        collection.add_component(kind, 4, 4, value, grid)

    assert len(collection.get_components()) == 1


def test_same_pins_in_the_other_order_are_refused(collection, grid):
    # R1 runs C4 -> C5; a capacitor anchored on C5 turned 180 deg runs
    # C5 -> C4: the same two points.
    collection.add_component("resistor", 4, 4, "1k", grid)

    with pytest.raises(ComponentError, match=r"^R1 \(Resistor\) already "):
        collection.add_component("capacitor", 4, 5, "100n", grid, 180)


def test_vertical_parts_on_the_same_pins_are_refused(collection, grid):
    # V1 runs R4 -> R5 down; a resistor at 90 deg runs the same way, and a
    # diode anchored on R5 at 270 deg runs R5 -> R4.
    collection.add_component("dc_source", 4, 4, "9", grid)

    with pytest.raises(ComponentError, match=r"^V1 \(DC voltage source\)"):
        collection.add_component("resistor", 4, 4, "1k", grid, 90)

    with pytest.raises(ComponentError, match=r"^V1 \(DC voltage source\)"):
        collection.add_component("diode", 5, 4, "1N4148", grid, 270)


def test_ac_source_on_a_dc_source_is_refused(grid):
    collection = ComponentCollection()
    collection.add_component("dc_source", 5, 5, "9", grid)

    with pytest.raises(ComponentError, match=r"^V1 \(DC voltage source\)"):
        collection.add_component("ac_source", 5, 5, "1", grid)


def test_identical_ground_is_refused(collection, grid):
    collection.add_component("ground", 6, 2, "", grid)

    with pytest.raises(ComponentError, match=r"^GND1 \(Ground\) already "
                       r"connects exactly these grid points: NODE_R06_C02\."):
        collection.add_component("ground", 6, 2, "", grid)


def test_transistor_on_another_transistors_centre_is_refused(
        collection, grid):
    # A quarter turn gives different pins but the same body centre.
    collection.add_component("npn", 4, 4, "2N3904", grid)

    with pytest.raises(ComponentError) as error_info:
        collection.add_component("pnp", 4, 4, "2N3906", grid, 90)

    assert str(error_info.value) == (
        "Q1 (NPN transistor) already has its centre at row 4, column 4. "
        "Pick another grid point, or select Q1 to edit it."
    )


def test_ground_on_a_transistor_centre_is_refused(collection, grid):
    collection.add_component("npn", 4, 4, "2N3904", grid)

    with pytest.raises(ComponentError, match=r"^Q1 \(NPN transistor\) "
                       r"already has its centre"):
        collection.add_component("ground", 4, 4, "", grid)


def test_parts_sharing_one_pin_are_allowed(collection, grid):
    # R1 runs C2 -> C3 and R2 runs C3 -> C4: they connect at C3.
    first = collection.add_component("resistor", 2, 2, "1k", grid)
    second = collection.add_component("resistor", 2, 3, "1k", grid)

    assert set(first.get_pin_identifiers()) & set(
        second.get_pin_identifiers()
    ) == {"NODE_R02_C03"}


def test_parts_sharing_an_anchor_are_allowed(collection, grid):
    # Anchors are pins now: three parts can start on one point.
    collection.add_component("resistor", 4, 4, "1k", grid)
    collection.add_component("capacitor", 4, 4, "1n", grid, 90)
    collection.add_component("diode", 4, 4, "1N4148", grid, 180)

    assert [c.reference for c in collection.get_components()] == [
        "C1", "D1", "R1"
    ]


def test_ground_on_a_resistor_pin_is_allowed(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)
    collection.add_component("ground", 4, 5, "", grid)
    ground = collection.add_component("ground", 4, 4, "", grid)

    assert ground.reference == "GND2"


def test_transistor_pin_on_a_resistor_pin_is_allowed(collection, grid):
    # Q1's base is at (4, 3), R1's second pin.
    collection.add_component("resistor", 4, 2, "1k", grid)
    transistor = collection.add_component("npn", 4, 4, "2N3904", grid)

    assert "NODE_R04_C03" in transistor.get_pin_identifiers()


def test_spot_is_free_again_after_removal(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)
    collection.remove_component("R1")

    assert collection.add_component("capacitor", 4, 4, "1n", grid).reference \
        == "C1"


def test_find_component_with_same_pins(collection, grid):
    resistor = collection.add_component("resistor", 4, 4, "1k", grid)
    twin = Component("capacitor", "C1", "1n", 4, 5, 180)
    neighbour = Component("capacitor", "C1", "1n", 4, 5, 0)

    assert collection.find_component_with_same_pins(twin) is resistor
    assert collection.find_component_with_same_pins(neighbour) is None
    assert collection.find_component_with_same_pins(resistor) is None


def test_find_component_with_body_center(collection, grid):
    transistor = collection.add_component("npn", 4, 4, "2N3904", grid)

    assert collection.find_component_with_body_center(
        Component("pnp", "Q2", "2N3906", 4, 4, 180)
    ) is transistor
    assert collection.find_component_with_body_center(transistor) is None
    assert collection.find_component_with_body_center(
        Component("npn", "Q2", "2N3904", 4, 6)
    ) is None


def test_rotation_onto_the_same_pins_is_refused(collection, grid):
    # R1 runs C4 -> C5. R2 starts on C5 pointing down; one quarter turn
    # would point it left, back onto C4.
    collection.add_component("resistor", 4, 4, "1k", grid)
    collection.add_component("resistor", 4, 5, "2k2", grid, 90)

    with pytest.raises(ComponentError) as error_info:
        collection.rotate_component("R2", grid)

    assert str(error_info.value) == (
        "R2 cannot be rotated to 180 deg: R1 (Resistor) already connects "
        "exactly these grid points: NODE_R04_C04, NODE_R04_C05. Pick other "
        "grid points or another rotation, or select R1 to edit it."
    )
    assert collection.get_component("R2").rotation == 90


def test_rotation_onto_a_transistor_centre_is_refused(collection, grid):
    # Only an overlapping pair stored outside add_component (e.g. a later
    # file load) can share a centre; rotating it is refused.
    collection.add_component("npn", 4, 4, "2N3904", grid)
    add_stacked(collection, "npn", "Q2", "2N3904", 4, 4, 90)

    with pytest.raises(ComponentError, match=r"^Q2 cannot be rotated to 180 "
                       r"deg: Q1 \(NPN transistor\) already has its "
                       r"centre at row 4, column 4\."):
        collection.rotate_component("Q2", grid)

    assert collection.get_component("Q2").rotation == 90


def test_rotation_with_free_pins_is_allowed(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)
    collection.add_component("resistor", 4, 4, "1k", grid, 90)

    # R2 turns to 180 (C4 -> C3): free, it only shares the anchor.
    assert collection.rotate_component("R2", grid) == 180


# PR B: sources ------------------------------------------------------------


def test_dc_and_ac_sources_share_v_numbering(collection, grid):
    first = collection.add_component("dc_source", 2, 2, "9", grid)
    second = collection.add_component("ac_source", 2, 4, "", grid)

    assert (first.reference, second.reference) == ("V1", "V2")
    assert first.label_text() == "V1 9V"
    assert second.label_text() == "V2 1V 1kHz"


def test_add_ac_source_with_a_frequency(collection, grid):
    source = collection.add_component(
        "ac_source", 2, 2, "2", grid, 90, parameter_texts={"frequency": "50"}
    )

    assert source.rotation == 90
    assert source.parameter_values["frequency"] == 50.0
    assert source.label_text() == "V1 2V 50Hz"


def test_bad_frequency_places_nothing(collection, grid):
    with pytest.raises(ComponentError, match="frequency"):
        collection.add_component(
            "ac_source", 2, 2, "1", grid, parameter_texts={"frequency": "0"}
        )

    assert collection.get_components() == []


def test_set_component_value_with_settings(collection, grid):
    collection.add_component("ac_source", 2, 2, "1", grid)

    source = collection.set_component_value("V1", "5", {"frequency": "60"})

    assert source.label_text() == "V1 5V 60Hz"


def test_set_component_value_keeps_the_frequency(collection, grid):
    collection.add_component(
        "ac_source", 2, 2, "1", grid, parameter_texts={"frequency": "60"}
    )

    source = collection.set_component_value("V1", "5")

    assert source.label_text() == "V1 5V 60Hz"


# --- QC #11 issue 1: a symbol drawn over another part's body or pin ----------


def assert_drawn_over_refused(collection, grid, other_reference, kind, row,
                              column, rotation=0, value=""):
    stored_before = [part.reference for part in collection.get_components()]

    with pytest.raises(ComponentError) as error_info:
        collection.add_component(kind, row, column, value, grid, rotation)

    message = str(error_info.value)
    assert message.startswith(other_reference)
    assert "is already drawn there" in message
    assert [part.reference for part in collection.get_components()] == (
        stored_before
    )


def test_resistor_pin_on_a_transistor_centre_is_refused(collection, grid):
    collection.add_component("npn", 4, 4, "2N3904", grid)

    assert_drawn_over_refused(collection, grid, "Q1", "resistor", 4, 4)


def test_resistor_turned_180_onto_a_transistor_centre_is_refused(
        collection, grid):
    collection.add_component("npn", 4, 4, "2N3904", grid)

    # Pins (4,5) and (4,4): the second pin is on Q1's centre.
    assert_drawn_over_refused(collection, grid, "Q1", "resistor", 4, 5, 180)


def test_resistor_from_the_collector_into_the_centre_is_refused(
        collection, grid):
    collection.add_component("npn", 4, 4, "2N3904", grid)

    # Pins (3,4) and (4,4), body at half point (3.5, 4): over Q1's body.
    assert_drawn_over_refused(collection, grid, "Q1", "resistor", 3, 4, 90)


def test_transistor_over_a_resistor_pin_is_refused(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)

    assert_drawn_over_refused(collection, grid, "R1", "npn", 4, 4,
                              value="2N3904")


def test_ground_bars_over_a_vertical_resistor_body_are_refused(
        collection, grid):
    # R1 runs (4,4) -> (5,4) with its body at (4.5, 4); ground at (4,4)
    # draws its bars at (4.5, 4).
    collection.add_component("resistor", 4, 4, "1k", grid, 90)

    assert_drawn_over_refused(collection, grid, "R1", "ground", 4, 4)


def test_transistor_over_ground_bars_is_refused(collection, grid):
    # Ground at (4,4) covers (4.5, 4); an npn at (5,4) covers (4.5, 4)
    # toward its collector.
    collection.add_component("ground", 4, 4, "", grid)

    assert_drawn_over_refused(collection, grid, "GND1", "npn", 5, 4,
                              value="2N3904")


def test_rotation_onto_ground_bars_is_refused(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid)
    collection.add_component("ground", 4, 4, "", grid)

    with pytest.raises(ComponentError) as error_info:
        collection.rotate_component("R1", grid)

    assert str(error_info.value).startswith(
        "R1 cannot be rotated to 90 deg: GND1 (Ground) is already drawn there"
    )
    assert collection.get_component("R1").rotation == 0


@pytest.mark.parametrize("first, second", [
    (("resistor", 4, 4, "1k", 90), ("ground", 5, 4, "", 0)),
    (("resistor", 4, 4, "1k", 0), ("ground", 4, 4, "", 0)),
    (("resistor", 4, 4, "1k", 0), ("ground", 4, 5, "", 0)),
    (("resistor", 4, 2, "1k", 0), ("npn", 4, 4, "2N3904", 0)),
    (("dc_source", 4, 4, "5", 0), ("npn", 4, 6, "2N3904", 0)),
])
def test_neighbours_that_only_share_pins_are_allowed(collection, grid, first,
                                                     second):
    for kind, row, column, value, rotation in (first, second):
        collection.add_component(kind, row, column, value, grid, rotation)

    assert len(collection.get_components()) == 2


def test_three_parts_fanning_out_of_one_anchor_are_allowed(collection, grid):
    collection.add_component("resistor", 4, 4, "1k", grid, 0)
    collection.add_component("capacitor", 4, 4, "100n", grid, 90)
    collection.add_component("diode", 4, 4, "1N4148", grid, 180)

    assert len(collection.get_components()) == 3
