"""
Tests for Billie's Oct 9 wire rule: a wire connects every grid point it
covers (breadboard strip), wires are horizontal or vertical only, and
junction dots mark where three or more connections meet. Qt tests use the
qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.wires import Wire, WireCollection, find_junction_identifiers
from gui.component_item import COMPONENT_Z_VALUE
from gui.grid_editor import (
    CONNECTION_POINT_Z_VALUE,
    JUNCTION_DIAMETER,
    JUNCTION_Z_VALUE,
    ConnectionGridScene,
    ConnectionGridView,
    grid_point_to_scene_position,
)
from gui.wire_item import WIRE_COLOR
from tests.view_mouse import click

DIAGONAL_MESSAGE = (
    "A wire from {} to {} would be diagonal. Wires run along a row or a "
    "column: draw two straight wires that meet at a corner."
)


# ----- core: strips -----------------------------------------------------------

@pytest.mark.parametrize("start, end, points", [
    ((2, 2), (2, 5), ((2, 2), (2, 3), (2, 4), (2, 5))),
    ((2, 5), (2, 3), ((2, 5), (2, 4), (2, 3))),
    ((1, 4), (4, 4), ((1, 4), (2, 4), (3, 4), (4, 4))),
    ((4, 4), (3, 4), ((4, 4), (3, 4))),
])
def test_a_wire_covers_every_point_between_its_ends(start, end, points):
    wire = Wire("W1", start, end)

    assert wire.get_points() == points


def test_point_identifiers_and_inner_points():
    wire = Wire("W1", (2, 2), (2, 5))

    assert wire.get_point_identifiers() == (
        "NODE_R02_C02", "NODE_R02_C03", "NODE_R02_C04", "NODE_R02_C05"
    )
    assert wire.get_inner_point_identifiers() == (
        "NODE_R02_C03", "NODE_R02_C04"
    )
    assert Wire("W1", (2, 2), (3, 2)).get_inner_point_identifiers() == ()


@pytest.mark.parametrize("start, end", [
    ((1, 1), (2, 2)), ((3, 3), (1, 4)), ((5, 2), (4, 1)), ((1, 1), (8, 2)),
])
def test_diagonal_wires_are_refused(start, end):
    with pytest.raises(ComponentError) as error:
        Wire("W1", start, end)

    assert str(error.value) == DIAGONAL_MESSAGE.format(
        "NODE_R{:02d}_C{:02d}".format(*start),
        "NODE_R{:02d}_C{:02d}".format(*end)
    )


def test_get_wires_at_includes_mid_span():
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire("NODE_R02_C02", "NODE_R02_C06", grid)
    wires.add_wire("NODE_R01_C04", "NODE_R05_C04", grid)

    assert [wire.reference for wire in wires.get_wires_at(
        "NODE_R02_C04")] == ["W1", "W2"]
    assert [wire.reference for wire in wires.get_wires_at(
        "NODE_R02_C03")] == ["W1"]
    assert wires.get_wires_at("NODE_R03_C03") == []


# ----- core: junctions --------------------------------------------------------

def make_wires(*pairs):
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()

    for start, end in pairs:
        wires.add_wire(start, end, grid)

    return wires


def test_wire_ending_on_a_pin_has_no_dot():
    wires = make_wires(("NODE_R02_C02", "NODE_R02_C05"))

    assert find_junction_identifiers(wires, ["NODE_R02_C05"]) == []


def test_wire_passing_a_pin_mid_span_has_a_dot():
    wires = make_wires(("NODE_R02_C02", "NODE_R02_C05"))

    assert find_junction_identifiers(
        wires, ["NODE_R02_C03", "NODE_R07_C07"]
    ) == ["NODE_R02_C03"]


def test_t_and_crossing_have_dots():
    wires = make_wires(
        ("NODE_R02_C02", "NODE_R02_C06"),
        ("NODE_R02_C04", "NODE_R05_C04"),
        ("NODE_R04_C02", "NODE_R04_C06"),
    )

    # W2 ends on W1 mid-span (T) and crosses W3 mid-span.
    assert find_junction_identifiers(wires) == [
        "NODE_R02_C04", "NODE_R04_C04"
    ]


def test_a_bridged_crossing_has_no_dot():
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire("NODE_R02_C02", "NODE_R06_C02", grid)
    wires.add_wire(
        "NODE_R04_C01", "NODE_R04_C06", grid, ["NODE_R04_C02"]
    )

    assert find_junction_identifiers(wires) == []


def test_a_plain_corner_has_no_dot_but_three_ends_do():
    corner = make_wires(
        ("NODE_R02_C02", "NODE_R02_C05"), ("NODE_R02_C05", "NODE_R06_C05")
    )

    assert find_junction_identifiers(corner) == []
    assert find_junction_identifiers(corner, ["NODE_R02_C05"]) == [
        "NODE_R02_C05"
    ]

    corner.add_wire("NODE_R02_C05", "NODE_R02_C08", ConnectionGrid(8, 8))

    assert find_junction_identifiers(corner) == ["NODE_R02_C05"]


def test_pins_sharing_a_point_without_a_wire_have_no_dot():
    assert find_junction_identifiers(
        WireCollection(), ["NODE_R03_C03"] * 3
    ) == []


def test_junction_errors():
    with pytest.raises(ComponentError) as error:
        find_junction_identifiers([], [])

    assert str(error.value) == "Expected a WireCollection, not list."

    with pytest.raises(ComponentError) as error:
        find_junction_identifiers(WireCollection(), [(2, 2)])

    assert str(error.value) == (
        "Pin points must be identifiers such as NODE_R02_C03, not (2, 2)."
    )


# ----- scene: junction dots ---------------------------------------------------

@pytest.fixture
def scene(qt_application):
    result = ConnectionGridScene(ConnectionGrid(8, 8))
    result.set_component_collection(ComponentCollection())
    result.set_wire_collection(WireCollection())

    return result


def add_part(scene, kind, row, column, rotation=0):
    component = scene.component_collection.add_component(
        kind, row, column, "", scene.connection_grid, rotation
    )
    scene.rebuild_component_items()

    return component.reference


def add_wire(scene, start, end):
    wire = scene.wire_collection.add_wire(start, end, scene.connection_grid)
    scene.rebuild_wire_items()

    return wire.reference


def junctions(scene):
    return sorted(scene.junction_items_by_identifier)


def test_dot_where_a_wire_passes_a_pin(scene):
    add_part(scene, "resistor", 4, 3, 90)
    add_wire(scene, "NODE_R04_C02", "NODE_R04_C06")

    assert junctions(scene) == ["NODE_R04_C03"]
    item = scene.junction_items_by_identifier["NODE_R04_C03"]
    assert item.scene() is scene
    assert item.rect().center() == grid_point_to_scene_position(4, 3)
    assert item.rect().width() == JUNCTION_DIAMETER
    assert item.brush().color() == QColor(WIRE_COLOR)
    assert item.acceptedMouseButtons() == Qt.NoButton


def test_dots_stack_above_grid_points_and_below_parts():
    assert CONNECTION_POINT_Z_VALUE < JUNCTION_Z_VALUE < COMPONENT_Z_VALUE


def test_dot_follows_part_placement_move_and_delete(scene):
    add_wire(scene, "NODE_R04_C02", "NODE_R04_C06")

    assert junctions(scene) == []

    reference = add_part(scene, "resistor", 4, 4, 90)

    assert junctions(scene) == ["NODE_R04_C04"]

    scene.component_collection.move_component(
        reference, 6, 4, scene.connection_grid
    )
    scene.refresh_component(reference)

    assert junctions(scene) == []

    scene.component_collection.move_component(
        reference, 3, 5, scene.connection_grid
    )
    scene.refresh_component(reference)

    # Pin 2 of the turned resistor is at R4 C5, mid-span.
    assert junctions(scene) == ["NODE_R04_C05"]

    scene.component_collection.remove_component(reference)
    scene.rebuild_component_items()

    assert junctions(scene) == []


def test_dot_follows_wire_add_and_delete(scene):
    add_wire(scene, "NODE_R02_C02", "NODE_R02_C06")
    second = add_wire(scene, "NODE_R02_C04", "NODE_R06_C04")

    assert junctions(scene) == ["NODE_R02_C04"]
    old_item = scene.junction_items_by_identifier["NODE_R02_C04"]

    scene.wire_collection.remove_wire(second)
    scene.rebuild_wire_items()

    assert junctions(scene) == []
    assert old_item.scene() is None


def test_grid_rebuild_keeps_dots(scene):
    add_wire(scene, "NODE_R02_C02", "NODE_R02_C06")
    add_wire(scene, "NODE_R02_C04", "NODE_R06_C04")
    scene.set_connection_grid(scene.connection_grid)

    assert junctions(scene) == ["NODE_R02_C04"]
    assert scene.junction_items_by_identifier[
        "NODE_R02_C04"
    ].scene() is scene


def test_click_on_a_dot_selects_the_grid_point(scene):
    add_wire(scene, "NODE_R02_C02", "NODE_R02_C06")
    add_wire(scene, "NODE_R02_C04", "NODE_R06_C04")
    view = ConnectionGridView(scene)
    view.resize(900, 800)
    view.show()
    view.resetTransform()
    view.centerOn(grid_point_to_scene_position(4, 4))
    QApplication.processEvents()

    click(view, grid_point_to_scene_position(2, 4) + QPointF(2, 2))

    assert scene.connection_point_items_by_identifier[
        "NODE_R02_C04"
    ].isSelected()
    view.close()
    view.deleteLater()
