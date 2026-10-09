"""
Tests for core.wires (PR D): Wire and WireCollection. Pure Python, no Qt.
"""

import pytest

from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.wires import Wire, WireCollection, describe_crossings


@pytest.fixture
def grid():
    return ConnectionGrid(8, 8)


@pytest.fixture
def wires():
    return WireCollection()


def test_wire_keeps_its_ends():
    wire = Wire("W1", (2, 2), (2, 4))

    assert wire.reference == "W1"
    assert wire.start_point == (2, 2)
    assert wire.end_point == (2, 4)
    assert wire.start_identifier == "NODE_R02_C02"
    assert wire.end_identifier == "NODE_R02_C04"
    assert wire.describe() == "W1 from NODE_R02_C02 to NODE_R02_C04"
    assert wire.get_end_points() == Wire("W2", (2, 4), (2, 2)).get_end_points()


def test_wire_accepts_a_list_point():
    assert Wire("W1", [3, 1], [1, 1]).start_point == (3, 1)


@pytest.mark.parametrize("reference", ["W0", "w1", "R1", "W", 1, None,
                                       "W1234567"])
def test_bad_wire_reference(reference):
    with pytest.raises(ComponentError, match="Wire reference"):
        Wire(reference, (1, 1), (1, 2))


@pytest.mark.parametrize("point", [(0, 1), (1, -2), (1, 2, 3), (1.0, 2),
                                   (True, 2), "NODE_R01_C02", None, (1,)])
def test_bad_wire_point(point):
    with pytest.raises(ComponentError, match="is not a grid point"):
        Wire("W1", point, (2, 2))


def test_zero_length_wire_is_refused():
    with pytest.raises(ComponentError) as error_info:
        Wire("W1", (2, 2), (2, 2))

    assert str(error_info.value) == (
        "A wire needs two different grid points; both ends are NODE_R02_C02."
    )


def test_wire_is_read_only():
    wire = Wire("W1", (1, 1), (1, 2))

    with pytest.raises(AttributeError):
        wire.start_point = (3, 3)


def test_fits_grid():
    wire = Wire("W1", (2, 7), (6, 7))

    assert wire.fits_grid(6, 7)
    assert not wire.fits_grid(5, 7)
    assert not wire.fits_grid(6, 6)


# ----- WireCollection --------------------------------------------------------


def test_add_wire_numbers_from_w1(wires, grid):
    first = wires.add_wire("NODE_R02_C02", "NODE_R02_C04", grid)
    second = wires.add_wire("NODE_R02_C04", "NODE_R05_C04", grid)

    assert (first.reference, second.reference) == ("W1", "W2")
    assert wires.get_wires() == [first, second]
    assert wires.get_wire("W2") is second


def test_diagonal_wire_is_refused(wires, grid):
    with pytest.raises(ComponentError) as error:
        wires.add_wire("NODE_R01_C01", "NODE_R03_C04", grid)

    assert str(error.value) == (
        "A wire from NODE_R01_C01 to NODE_R03_C04 would be diagonal. Wires "
        "run along a row or a column: draw two straight wires that meet at "
        "a corner."
    )
    assert wires.get_wires() == []


def test_next_reference_reuses_the_lowest_free_number(wires, grid):
    wires.add_wire("NODE_R01_C01", "NODE_R01_C02", grid)
    wires.add_wire("NODE_R01_C02", "NODE_R01_C03", grid)
    wires.add_wire("NODE_R01_C03", "NODE_R01_C04", grid)
    wires.remove_wire("W2")

    assert wires.next_reference() == "W2"
    assert wires.add_wire("NODE_R02_C01", "NODE_R02_C02", grid).reference == (
        "W2"
    )


def test_wires_sort_naturally(wires, grid):
    for column in range(1, 8):
        wires.add_wire(f"NODE_R01_C0{column}", f"NODE_R01_C0{column + 1}",
                       grid)
    for column in range(1, 5):
        wires.add_wire(f"NODE_R02_C0{column}", f"NODE_R02_C0{column + 1}",
                       grid)

    assert [wire.reference for wire in wires.get_wires()] == [
        f"W{number}" for number in range(1, 12)
    ]


def test_zero_length_add_stores_nothing(wires, grid):
    with pytest.raises(ComponentError, match="two different grid points"):
        wires.add_wire("NODE_R02_C02", "NODE_R02_C02", grid)

    assert wires.get_wires() == []


@pytest.mark.parametrize("start, end", [
    ("NODE_R02_C02", "NODE_R02_C04"),
    ("NODE_R02_C04", "NODE_R02_C02"),
])
def test_duplicate_wire_either_way_is_refused(wires, grid, start, end):
    wires.add_wire("NODE_R02_C02", "NODE_R02_C04", grid)

    with pytest.raises(ComponentError) as error_info:
        wires.add_wire(start, end, grid)

    assert str(error_info.value) == (
        "W1 already joins NODE_R02_C02 and NODE_R02_C04."
    )
    assert len(wires.get_wires()) == 1


def test_overlapping_but_different_wires_are_allowed(wires, grid):
    # Sharing one end or lying along the same row is fine; only the exact
    # same pair of points is a duplicate.
    wires.add_wire("NODE_R02_C02", "NODE_R02_C04", grid)
    wires.add_wire("NODE_R02_C02", "NODE_R02_C03", grid)
    wires.add_wire("NODE_R02_C04", "NODE_R02_C05", grid)

    assert len(wires.get_wires()) == 3


@pytest.mark.parametrize("identifier", ["NODE_R09_C01", "NODE_R00_C01",
                                        "R1C1", "", None, 5])
def test_off_grid_end_is_refused(wires, grid, identifier):
    with pytest.raises(ComponentError, match="is not a grid point of the "
                                             "8 x 8 grid"):
        wires.add_wire("NODE_R01_C01", identifier, grid)

    with pytest.raises(ComponentError, match="is not a grid point"):
        wires.add_wire(identifier, "NODE_R01_C01", grid)

    assert wires.get_wires() == []


def test_add_wire_needs_a_grid(wires):
    with pytest.raises(ComponentError, match="Expected a ConnectionGrid"):
        wires.add_wire("NODE_R01_C01", "NODE_R01_C02", None)


def test_get_wires_at_a_point(wires, grid):
    wires.add_wire("NODE_R02_C02", "NODE_R02_C04", grid)
    wires.add_wire("NODE_R05_C04", "NODE_R02_C04", grid)
    wires.add_wire("NODE_R07_C07", "NODE_R07_C08", grid)

    assert [wire.reference for wire in wires.get_wires_at("NODE_R02_C04")] == [
        "W1", "W2"
    ]
    assert wires.get_wires_at("NODE_R01_C01") == []


def test_remove_wire(wires, grid):
    wires.add_wire("NODE_R02_C02", "NODE_R02_C04", grid)

    wires.remove_wire("W1")

    assert wires.get_wires() == []
    with pytest.raises(ComponentError, match="no wire called 'W1'"):
        wires.remove_wire("W1")


def test_get_unknown_wire(wires):
    with pytest.raises(ComponentError, match="no wire called 'W3'"):
        wires.get_wire("W3")


def test_remove_wires_outside_grid(wires, grid):
    wires.add_wire("NODE_R02_C02", "NODE_R02_C04", grid)
    wires.add_wire("NODE_R02_C04", "NODE_R08_C04", grid)
    wires.add_wire("NODE_R03_C03", "NODE_R03_C07", grid)
    wires.add_wire("NODE_R06_C06", "NODE_R05_C06", grid)

    grid.configure(6, 6)

    assert wires.remove_wires_outside_grid(grid) == ["W2", "W3"]
    assert [wire.reference for wire in wires.get_wires()] == ["W1", "W4"]
    assert wires.remove_wires_outside_grid(grid) == []


def test_remove_wires_outside_grid_needs_a_grid(wires):
    with pytest.raises(ComponentError, match="Expected a ConnectionGrid"):
        wires.remove_wires_outside_grid("8x8")


def test_wires_module_does_not_import_qt():
    import core.wires

    with open(core.wires.__file__, encoding="utf-8") as source_file:
        source = source_file.read()
    assert "PyQt5" not in source.replace("no PyQt5 imports", "")


def test_joined_identifiers_are_the_one_connection_rule(wires, grid):
    wire = wires.add_wire("NODE_R02_C02", "NODE_R02_C05", grid)

    # Billie's every-dot rule: ends and every point between.
    assert wire.get_joined_identifiers() == (
        "NODE_R02_C02", "NODE_R02_C03", "NODE_R02_C04", "NODE_R02_C05"
    )
    assert wire.get_inner_point_identifiers() == (
        "NODE_R02_C03", "NODE_R02_C04"
    )


def test_get_wires_at_follows_the_connection_rule(wires, grid, monkeypatch):
    wire = wires.add_wire("NODE_R02_C02", "NODE_R02_C05", grid)

    assert wires.get_wires_at("NODE_R02_C03") == [wire]

    # Changing the one rule changes what get_wires_at reports.
    monkeypatch.setattr(
        Wire, "get_joined_identifiers",
        lambda self: (self.start_identifier, self.end_identifier)
    )

    assert wires.get_wires_at("NODE_R02_C03") == []
    assert wires.get_wires_at("NODE_R02_C05") == [wire]


def test_a_bridge_skips_that_point(wires, grid):
    power = wires.add_wire("NODE_R02_C02", "NODE_R06_C02", grid)
    wire = wires.add_wire(
        "NODE_R04_C01", "NODE_R04_C05", grid, ["NODE_R04_C02"]
    )

    assert wire.bridged_identifiers == ("NODE_R04_C02",)
    assert wire.get_joined_identifiers() == (
        "NODE_R04_C01", "NODE_R04_C03", "NODE_R04_C04", "NODE_R04_C05"
    )
    assert wire.get_inner_point_identifiers() == (
        "NODE_R04_C03", "NODE_R04_C04"
    )
    assert wire.describe() == (
        "W2 from NODE_R04_C01 to NODE_R04_C05, bridging NODE_R04_C02"
    )
    assert wires.get_wires_at("NODE_R04_C02") == [power]
    assert wires.get_wires_at("NODE_R04_C03") == [wire]


def test_a_bridge_on_an_end_is_refused_and_stores_nothing(wires, grid):
    with pytest.raises(ComponentError, match="between the wire's ends"):
        wires.add_wire(
            "NODE_R02_C02", "NODE_R02_C05", grid, ["NODE_R02_C02"]
        )

    assert wires.get_wires() == []


def test_find_crossings_lists_another_wire_on_an_interior_point(wires, grid):
    wires.add_wire("NODE_R02_C02", "NODE_R06_C02", grid)

    assert wires.find_crossings(
        "NODE_R04_C01", "NODE_R04_C05", grid
    ) == [("NODE_R04_C02", ["W1"])]
    assert describe_crossings([("NODE_R04_C02", ["W1"])]) == (
        "This wire crosses NODE_R04_C02 (W1)."
    )


def test_ending_on_a_wire_is_not_a_crossing(wires, grid):
    wires.add_wire("NODE_R02_C02", "NODE_R02_C06", grid)

    assert wires.find_crossings("NODE_R02_C04", "NODE_R05_C04", grid) == []


def test_two_crossings_are_named_in_order(wires, grid):
    wires.add_wire("NODE_R02_C02", "NODE_R06_C02", grid)
    wires.add_wire("NODE_R02_C04", "NODE_R06_C04", grid)

    crossings = wires.find_crossings("NODE_R04_C01", "NODE_R04_C06", grid)

    assert crossings == [
        ("NODE_R04_C02", ["W1"]),
        ("NODE_R04_C04", ["W2"]),
    ]
    assert describe_crossings(crossings) == (
        "This wire crosses NODE_R04_C02 (W1) and NODE_R04_C04 (W2)."
    )
