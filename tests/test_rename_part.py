"""
A part's schematic name can change. V1 can become BATT.

The label shows BATT. ngspice still needs a V, so the netlist line is
VBATT. A bad name or a bad value leaves the part as it was.
"""

import pytest
import sympy
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

from core.components import Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.netlist import build_netlist
from core.node_formula import build_node_formulas
from core.probes import ProbeCollection
from core.project_io import load_project_file, save_project_file
from core.wires import WireCollection
from gui.main_window import MainWindow


@pytest.fixture
def grid():
    return ConnectionGrid(8, 8)


@pytest.fixture
def collection():
    return ComponentCollection()


@pytest.fixture
def window(qt_application, monkeypatch):
    main_window = MainWindow()
    main_window.recorded_errors = []

    def record_error(title, reason, resolution):
        main_window.recorded_errors.append((title, reason, resolution))

    monkeypatch.setattr(main_window, "show_error_message", record_error)
    yield main_window
    main_window.is_project_modified = False
    main_window.close()
    main_window.deleteLater()


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def connect(wires, grid, start, end):
    wires.add_wire(point(*start), point(*end), grid)


def build_divider(grid, parts, wires):
    parts.add_component("ground", 6, 2, "", grid)
    parts.add_component("dc_source", 4, 2, "10", grid)
    parts.add_component("resistor", 4, 3, "10k", grid)
    parts.add_component("resistor", 4, 4, "10k", grid)
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))


RENAMED_DIVIDER = """\
* PyCircuit SPICE netlist
VBATT N001 0 DC 10
RLOAD N001 N002 10k
R2 N002 0 10k
.end
"""


def test_the_reference_property_stays_read_only():
    source = Component("dc_source", "V1", "9", 4, 4)

    with pytest.raises(ComponentError, match="cannot be changed"):
        source.reference = "BATT"

    assert source.reference == "V1"


def test_a_divider_renamed_to_batt_and_load_is_the_hand_checked_netlist(
        collection, grid):
    wires = WireCollection()
    build_divider(grid, collection, wires)
    collection.rename_component("V1", "BATT")
    collection.rename_component("R1", "LOAD")

    text = build_netlist(collection, wires, grid)

    # 10 V across two 10k resistors. The source name BATT is VBATT because
    # ngspice uses the first letter, and LOAD is the resistor RLOAD.
    assert text == RENAMED_DIVIDER
    assert "\nV1 " not in text
    assert "\nBATT " not in text
    assert "\nLOAD " not in text


def test_a_name_that_already_starts_with_v_is_not_doubled(collection, grid):
    wires = WireCollection()
    build_divider(grid, collection, wires)
    collection.rename_component("V1", "VBATT")

    text = build_netlist(collection, wires, grid)

    assert "VBATT N001 0 DC 10" in text
    assert "VVBATT" not in text


def test_batt_on_a_source_clashes_with_a_part_already_named_vbatt(
        collection, grid):
    collection.add_component("dc_source", 2, 2, "9", grid)
    collection.add_component("dc_source", 2, 5, "5", grid)
    collection.rename_component("V2", "VBATT")

    with pytest.raises(ComponentError, match="VBATT"):
        collection.rename_component("V1", "BATT")

    assert collection.get_component("V1").value_text == "9"
    assert "BATT" not in collection.components_by_reference


def test_a_bad_name_keeps_the_old_name_and_value(collection, grid):
    source = collection.add_component("dc_source", 2, 2, "9", grid)

    for bad_name in ("", "1V", "BATT 1", "s", "v_0"):
        with pytest.raises(ComponentError):
            collection.rename_component("V1", bad_name)

        assert source.reference == "V1"
        assert source.value_text == "9"
        assert source.label_text() == "V1 9V"


def test_names_are_unique_ignoring_case(collection, grid):
    collection.add_component("dc_source", 2, 2, "9", grid)
    collection.add_component("dc_source", 2, 5, "5", grid)
    collection.rename_component("V1", "BATT")

    with pytest.raises(ComponentError, match="already used"):
        collection.rename_component("V2", "batt")

    assert collection.get_component("V2").reference == "V2"


def test_the_next_number_skips_a_name_that_differs_only_by_case(
        collection, grid):
    collection.add_component("dc_source", 2, 2, "9", grid)
    collection.rename_component("V1", "BATT")

    assert collection.next_reference("dc_source") == "V1"

    collection.rename_component("BATT", "v1")

    assert collection.next_reference("dc_source") == "V2"


def test_a_name_without_a_number_sorts_with_the_numbered_ones(
        collection, grid):
    collection.place_saved("dc_source", "BATT", "9", 2, 2, grid)
    collection.place_saved("resistor", "R10", "1k", 4, 4, grid)
    collection.place_saved("resistor", "R2", "1k", 6, 4, grid)

    references = [
        component.reference for component in collection.get_components()
    ]

    assert references == ["BATT", "R2", "R10"]


def test_an_ac_divider_keeps_the_new_name_in_the_formula(collection, grid):
    collection.place_saved("ac_source", "V1", "1", 2, 2, grid)
    collection.rename_component("V1", "BATT")
    source = collection.get_component("BATT")
    wires = WireCollection()
    wires.add_wire(point(3, 2), point(4, 2), grid)
    wires.add_wire(point(3, 3), point(3, 2), grid)
    book = build_node_formulas(
        [
            Component("ground", "GND1", "", 4, 2),
            source,
            Component("resistor", "R1", "10k", 2, 2),
            Component("resistor", "R2", "10k", 2, 3, 90),
        ],
        wires,
        grid,
    )

    # Two equal resistors. The midpoint is half the source, and the
    # source symbol is the schematic name.
    assert sympy.simplify(
        book.expression_at(point(2, 3)) - sympy.Symbol("BATT") / 2
    ) == 0


def test_a_current_probe_follows_the_new_name(collection, grid, tmp_path):
    source = collection.add_component("dc_source", 2, 2, "9", grid)
    probes = ProbeCollection()
    probes.add_current(source)
    collection.rename_component("V1", "BATT")
    probes.rename_part("V1", "BATT")

    assert probes.get("P1").component_reference == "BATT"
    assert source.label_text() == "BATT 9V"

    path = tmp_path / "batt.json"
    save_project_file(path, grid, collection, WireCollection(), probes)
    loaded = load_project_file(path)

    assert loaded.component_collection.get_component("BATT").value_text == "9"
    assert loaded.probe_collection.get("P1").component_reference == "BATT"


def test_the_panel_renames_v1_to_batt(window):
    scene = window.connection_grid_scene
    scene.connection_point_items_by_identifier["NODE_R04_C03"].setSelected(
        True
    )
    window.place_component("dc_source", "9")
    source = window.component_collection.get_component("V1")
    window.probe_collection.add_current(source)
    panel = window.component_panel_widget
    panel.selected_name_line_edit.setText("BATT")
    panel.apply_value_button.click()

    assert source.reference == "BATT"
    assert source.label_text() == "BATT 9V"
    assert window.selected_component_reference == "BATT"
    assert "V1" not in scene.component_items_by_reference
    assert scene.component_items_by_reference["BATT"].label_item.text() == (
        "BATT 9V"
    )
    assert window.probe_collection.get("P1").component_reference == "BATT"
    assert panel.selected_name_line_edit.text() == "BATT"
    assert window.statusBar().currentMessage() == "Renamed V1 to BATT."
    assert window.recorded_errors == []


def test_enter_in_the_name_box_renames_the_part(window):
    scene = window.connection_grid_scene
    scene.connection_point_items_by_identifier["NODE_R04_C03"].setSelected(
        True
    )
    window.place_component("dc_source", "9")
    panel = window.component_panel_widget
    panel.selected_name_line_edit.setText("BATT")
    QTest.keyClick(panel.selected_name_line_edit, Qt.Key_Return)

    assert window.component_collection.get_component("BATT").value_text == "9"


def test_a_bad_name_and_a_bad_value_change_nothing(window):
    scene = window.connection_grid_scene
    scene.connection_point_items_by_identifier["NODE_R04_C03"].setSelected(
        True
    )
    window.place_component("dc_source", "9")
    window.is_project_modified = False
    panel = window.component_panel_widget
    panel.selected_name_line_edit.setText("BATT")
    panel.selected_value_line_edit.setText("abc")
    panel.apply_value_button.click()

    source = window.component_collection.get_component("V1")
    assert source.value_text == "9"
    assert source.reference == "V1"
    assert "BATT" not in scene.component_items_by_reference
    assert window.recorded_errors[0][0] == "Part Value Not Changed"
    assert panel.selected_name_line_edit.text() == "V1"
    assert panel.selected_value_line_edit.text() == "9"
    assert window.is_project_modified is False


def test_a_bad_name_is_refused_before_the_value_changes(window):
    scene = window.connection_grid_scene
    scene.connection_point_items_by_identifier["NODE_R04_C03"].setSelected(
        True
    )
    window.place_component("dc_source", "9")
    panel = window.component_panel_widget
    panel.selected_name_line_edit.setText("1V")
    panel.selected_value_line_edit.setText("12")
    panel.apply_value_button.click()

    source = window.component_collection.get_component("V1")
    assert source.value_text == "9"
    assert window.recorded_errors[0][0] == "Part Not Changed"
    assert panel.selected_name_line_edit.text() == "V1"
    assert panel.selected_value_line_edit.text() == "9"
