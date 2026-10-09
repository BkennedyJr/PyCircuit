"""
Tests for the part hover tooltips (Billie, Oct 9 11:46): every setting,
the rotation, the node under each pin and, once wires exist, the net each
pin belongs to. Qt tests use the qt_application fixture in
tests/conftest.py.
"""

import pytest

from core.components import Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.wires import WireCollection, WireNets
from gui.component_item import ComponentItem
from gui.grid_editor import ConnectionGridScene
from gui.main_window import MainWindow

SPACING = 60


def make_wires(*pairs, grid=None):
    grid = grid or ConnectionGrid(12, 12)
    wires = WireCollection()

    for start, end in pairs:
        wires.add_wire(start, end, grid)

    return wires


# ----- core.wires.WireNets ----------------------------------------------------

def test_no_wires():
    nets = WireNets(WireCollection())

    assert nets.get_points("NODE_R02_C02") == ("NODE_R02_C02",)
    assert nets.get_wire_references("NODE_R02_C02") == ()
    assert nets.is_ground("NODE_R02_C02") is False
    assert nets.describe("NODE_R02_C02") == "no wires"


def test_wires_sharing_an_end_are_one_net():
    nets = WireNets(make_wires(
        ("NODE_R02_C05", "NODE_R06_C05"),
        ("NODE_R02_C02", "NODE_R02_C05"),
        ("NODE_R08_C01", "NODE_R08_C02"),
    ))
    expected = "NODE_R02_C02, NODE_R02_C05, NODE_R06_C05 via W1, W2"

    for identifier in ("NODE_R02_C02", "NODE_R02_C05", "NODE_R06_C05"):
        assert nets.describe(identifier) == expected

    assert nets.describe("NODE_R08_C02") == (
        "NODE_R08_C01, NODE_R08_C02 via W3"
    )


def test_points_are_in_row_then_column_order():
    nets = WireNets(make_wires(
        ("NODE_R10_C01", "NODE_R09_C12"),
        ("NODE_R09_C12", "NODE_R09_C02"),
    ))

    assert nets.get_points("NODE_R09_C02") == (
        "NODE_R09_C02", "NODE_R09_C12", "NODE_R10_C01"
    )


def test_wire_references_sort_naturally():
    pairs = [
        (f"NODE_R01_C{column:02d}", f"NODE_R01_C{column + 1:02d}")
        for column in range(1, 11)
    ]
    nets = WireNets(make_wires(*pairs))

    assert nets.get_wire_references("NODE_R01_C01") == tuple(
        f"W{number}" for number in range(1, 11)
    )


def test_a_wire_joins_only_its_ends():
    # PR D semantics: the dot a straight wire passes over is not joined.
    nets = WireNets(make_wires(("NODE_R02_C02", "NODE_R02_C05")))

    assert nets.describe("NODE_R02_C03") == "no wires"


def test_a_ground_pin_makes_the_net_node_0():
    nets = WireNets(
        make_wires(("NODE_R02_C02", "NODE_R06_C02")),
        ["NODE_R06_C02", "NODE_R09_C09"]
    )

    assert nets.describe("NODE_R02_C02") == (
        "0 (ground): NODE_R02_C02, NODE_R06_C02 via W1"
    )
    # A ground pin on a point with no wire.
    assert nets.describe("NODE_R09_C09") == "0 (ground)"
    assert nets.is_ground("NODE_R08_C08") is False


def test_needs_a_wire_collection():
    with pytest.raises(ComponentError) as error:
        WireNets([])

    assert str(error.value) == "Expected a WireCollection, not list."


@pytest.mark.parametrize("identifier", [None, 5, "R2C2", "NODE_R2_C2", ""])
def test_bad_points_are_refused(identifier):
    nets = WireNets(WireCollection())

    with pytest.raises(ComponentError) as error:
        nets.describe(identifier)

    assert str(error.value) == (
        f"Expected a grid point such as NODE_R02_C03, not {identifier!r}."
    )


def test_bad_ground_points_are_refused():
    with pytest.raises(ComponentError):
        WireNets(WireCollection(), ["NODE_R02_C02", 7])


# ----- ComponentItem tooltip ----------------------------------------------------

def tool_tip_lines(kind, value_text, rotation=0, reference=None,
                   parameter_texts=None):
    reference = reference or {"ground": "GND1"}.get(kind, "X1")
    component = Component(kind, reference, value_text, 4, 4, rotation,
                          parameter_texts)

    return ComponentItem(component, SPACING).toolTip().splitlines()


def test_resistor_tool_tip(qt_application):
    assert tool_tip_lines("resistor", "4k7", 0, "R1") == [
        "Kind: Resistor",
        "Reference: R1",
        "Value: 4k7",
        "Rotation: 0 deg",
        "pin 1: NODE_R04_C04",
        "pin 2: NODE_R04_C05",
    ]


def test_rotation_moves_the_pin_nodes(qt_application):
    assert tool_tip_lines("resistor", "4k7", 270, "R1")[3:] == [
        "Rotation: 270 deg",
        "pin 1: NODE_R04_C04",
        "pin 2: NODE_R03_C04",
    ]


def test_ac_source_shows_every_setting(qt_application):
    assert tool_tip_lines(
        "ac_source", "2", 0, "V1",
        {"frequency": "50", "offset": "1.5", "phase": "90"}
    ) == [
        "Kind: AC voltage source",
        "Reference: V1",
        "Peak amplitude: 2V",
        "Frequency: 50Hz",
        "Offset: 1.5V",
        "Phase: 90deg",
        "Rotation: 0 deg",
        "pin plus: NODE_R04_C04",
        "pin minus: NODE_R05_C04",
    ]


def test_model_parts_show_the_model(qt_application):
    assert tool_tip_lines("diode", "1N4148", 180, "D1") == [
        "Kind: Diode",
        "Reference: D1",
        "Model: 1N4148",
        "Rotation: 180 deg",
        "pin anode: NODE_R04_C04",
        "pin cathode: NODE_R04_C03",
    ]


def test_transistor_lists_three_pins(qt_application):
    assert tool_tip_lines("npn", "2N3904", 0, "Q1")[-3:] == [
        "pin base: NODE_R04_C03",
        "pin collector: NODE_R03_C04",
        "pin emitter: NODE_R05_C04",
    ]


def test_ground_has_no_value_line(qt_application):
    assert tool_tip_lines("ground", "") == [
        "Kind: Ground",
        "Reference: GND1",
        "Rotation: 0 deg",
        "pin gnd: NODE_R04_C04",
    ]


def test_tool_tip_follows_a_value_change(qt_application):
    component = Component("resistor", "R1", "1k", 4, 4)
    item = ComponentItem(component, SPACING)
    component.set_values("2k2")
    item.refresh_from_component()

    assert "Value: 2k2" in item.toolTip().splitlines()


def test_wire_nets_add_a_net_line_per_pin(qt_application):
    item = ComponentItem(Component("resistor", "R1", "1k", 4, 4), SPACING)
    item.set_wire_nets(WireNets(
        make_wires(("NODE_R04_C04", "NODE_R08_C04")), ["NODE_R08_C04"]
    ))

    assert item.toolTip().splitlines()[4:] == [
        "pin 1: NODE_R04_C04",
        "  net: 0 (ground): NODE_R04_C04, NODE_R08_C04 via W1",
        "pin 2: NODE_R04_C05",
        "  net: no wires",
    ]


def test_wire_nets_none_removes_the_net_lines(qt_application):
    item = ComponentItem(Component("resistor", "R1", "1k", 4, 4), SPACING)
    item.set_wire_nets(WireNets(WireCollection()))
    item.set_wire_nets(None)

    assert not any("net:" in line for line in item.toolTip().splitlines())


@pytest.mark.parametrize("value", [WireCollection(), "nets", 0])
def test_set_wire_nets_needs_wire_nets(qt_application, value):
    item = ComponentItem(Component("resistor", "R1", "1k", 4, 4), SPACING)

    with pytest.raises(ComponentError) as error:
        item.set_wire_nets(value)

    assert str(error.value) == (
        f"set_wire_nets needs WireNets or None, not {value!r}."
    )


# ----- the scene keeps the nets current -----------------------------------------

@pytest.fixture
def scene(qt_application):
    grid = ConnectionGrid(8, 8)
    result = ConnectionGridScene(grid)
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


def net_lines(scene, reference):
    return [
        line for line in
        scene.component_items_by_reference[reference].toolTip().splitlines()
        if line.startswith("  net: ")
    ]


def test_scene_tool_tips_show_no_wires_at_first(scene):
    add_part(scene, "resistor", 2, 2)

    assert net_lines(scene, "R1") == ["  net: no wires", "  net: no wires"]


def test_scene_without_wires_has_no_net_lines(qt_application):
    scene = ConnectionGridScene(ConnectionGrid(8, 8))
    scene.set_component_collection(ComponentCollection())
    add_part(scene, "resistor", 2, 2)

    assert net_lines(scene, "R1") == []


def test_drawing_and_deleting_a_wire_updates_the_tool_tips(scene):
    add_part(scene, "resistor", 2, 2)
    add_part(scene, "capacitor", 5, 2)
    wire = add_wire(scene, "NODE_R02_C03", "NODE_R05_C03")

    assert net_lines(scene, "R1") == [
        "  net: no wires",
        "  net: NODE_R02_C03, NODE_R05_C03 via W1",
    ]
    assert net_lines(scene, "C1")[1] == (
        "  net: NODE_R02_C03, NODE_R05_C03 via W1"
    )

    scene.wire_collection.remove_wire(wire)
    scene.rebuild_wire_items()

    assert net_lines(scene, "R1")[1] == "  net: no wires"


def test_placing_ground_on_a_net_makes_it_node_0(scene):
    add_part(scene, "resistor", 2, 2)
    add_wire(scene, "NODE_R02_C03", "NODE_R06_C03")
    add_part(scene, "ground", 6, 3)

    assert net_lines(scene, "R1")[1] == (
        "  net: 0 (ground): NODE_R02_C03, NODE_R06_C03 via W1"
    )
    assert net_lines(scene, "GND1") == [
        "  net: 0 (ground): NODE_R02_C03, NODE_R06_C03 via W1"
    ]


def test_moving_ground_off_the_net_updates_the_tool_tips(scene):
    add_part(scene, "resistor", 2, 2)
    add_wire(scene, "NODE_R02_C03", "NODE_R06_C03")
    add_part(scene, "ground", 6, 3)
    scene.component_collection.move_component(
        "GND1", 7, 6, scene.connection_grid
    )
    scene.refresh_component("GND1")

    assert net_lines(scene, "R1")[1] == (
        "  net: NODE_R02_C03, NODE_R06_C03 via W1"
    )
    assert net_lines(scene, "GND1") == ["  net: 0 (ground)"]


def test_window_delete_of_a_wire_updates_the_tool_tip(qt_application):
    window = MainWindow()
    scene = window.connection_grid_scene
    scene.clearSelection()
    scene.connection_point_items_by_identifier["NODE_R02_C02"].setSelected(
        True
    )
    window.place_component("resistor", "1k")
    window.wire_collection.add_wire(
        "NODE_R02_C03", "NODE_R04_C03", window.connection_grid
    )
    scene.rebuild_wire_items()

    assert net_lines(scene, "R1")[1] == (
        "  net: NODE_R02_C03, NODE_R04_C03 via W1"
    )

    scene.clearSelection()
    scene.wire_items_by_reference["W1"].setSelected(True)
    window.delete_selection()

    assert net_lines(scene, "R1")[1] == "  net: no wires"
    window.is_project_modified = False
    window.close()
    window.deleteLater()
