"""
DC voltages on the nodes and currents on the parts.

Hand calculation for the divider: 10 V across 10k + 10k is 5 V in the
middle, and 10 V / 20k = 0.5 mA. The source current is -0.5 mA because
ngspice measures it into the positive pin.
"""

import pytest
from PyQt5.QtCore import QThread
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.netlist import spice_node_map
from core.wires import WireCollection
from gui.main_window import MainWindow
from sim import runner
from sim.runner import OperatingPoint, run_operating_point

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def place(parts, grid, kind, row, column, value=""):
    return parts.add_component(kind, row, column, value, grid)


def connect(wires, grid, start, end):
    wires.add_wire(point(*start), point(*end), grid)


def build_divider(grid, parts, wires):
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "10")
    place(parts, grid, "resistor", 4, 3, "10k")
    place(parts, grid, "resistor", 4, 4, "10k")
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))


def build_diode(grid, parts, wires):
    place(parts, grid, "ground", 6, 5)
    place(parts, grid, "dc_source", 4, 1, "5")
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "diode", 4, 4, "1N4148")
    connect(wires, grid, (4, 1), (4, 3))
    connect(wires, grid, (5, 1), (6, 1))
    connect(wires, grid, (6, 1), (6, 5))
    connect(wires, grid, (4, 5), (6, 5))


def show_on_scene(window):
    scene = window.connection_grid_scene
    scene.rebuild_component_items()
    scene.rebuild_wire_items()


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def select_point(window, identifier):
    item = window.connection_grid_scene.connection_point_items_by_identifier[
        identifier
    ]
    window.handle_connection_point_selection(item.connection_point)


def voltage_text(window, identifier):
    item = window.connection_grid_scene.connection_point_items_by_identifier[
        identifier
    ]
    return item.dc_voltage_item.text()


def current_text(window, reference):
    item = window.connection_grid_scene.component_items_by_reference[reference]
    return item.dc_current_item.text()


def test_the_divider_node_names_match_the_netlist():
    grid = ConnectionGrid(8, 8)
    parts = ComponentCollection()
    wires = WireCollection()
    build_divider(grid, parts, wires)

    name_by_point, draw_at = spice_node_map(parts, wires, grid)

    assert name_by_point[point(4, 2)] == "N001"
    assert name_by_point[point(4, 4)] == "N002"
    assert name_by_point[point(6, 2)] == "0"
    assert draw_at["N001"] == point(4, 2)
    assert draw_at["N002"] == point(4, 4)
    assert draw_at["0"] == point(6, 2)

    grid.set_net_label(point(4, 2), "Vcc")
    name_by_point, draw_at = spice_node_map(parts, wires, grid)

    assert name_by_point[point(4, 2)] == "Vcc"
    assert name_by_point[point(4, 3)] == "Vcc"
    assert name_by_point[point(4, 4)] == "N001"
    assert draw_at["Vcc"] == point(4, 2)
    assert "N002" not in draw_at


def test_simulate_menu_is_before_help(qt_application):
    window = MainWindow()

    try:
        titles = [action.text() for action in window.menuBar().actions()]
        assert titles[-1] == "&Help"
        assert titles.index("&Simulate") < titles.index("&View")
        simulate = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "&Simulate"
        )
        assert [
            action.text()
            for action in simulate.actions()
            if not action.isSeparator()
        ] == [
            "DC Operating Point",
            "Snapshot",
            "Continuous",
        ]
    finally:
        close_window(window)


def test_an_empty_circuit_reports_the_missing_ground(qt_application):
    window = MainWindow()
    recorded = []
    window.show_error_message = (
        lambda title, reason, resolution: recorded.append((title, reason))
    )

    try:
        window.run_dc_operating_point()
        assert recorded == [("DC Operating Point", "Add a ground part.")]
        assert window._dc_thread is None
    finally:
        close_window(window)


@needs_ngspice
def test_the_divider_draws_10_v_5_v_and_half_a_milliamp(qt_application):
    window = MainWindow()

    try:
        build_divider(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        show_on_scene(window)
        result = run_operating_point(
            window.component_collection,
            window.wire_collection,
            window.connection_grid,
        )
        window.show_dc_operating_point(result)
        select_point(window, point(4, 4))

        assert result.voltages["N002"] == pytest.approx(5)
        assert result.currents["R1"] == pytest.approx(0.0005)
        assert result.currents["V1"] == pytest.approx(-0.0005)
        assert voltage_text(window, point(4, 2)) == "10 V"
        assert voltage_text(window, point(4, 4)) == "5 V"
        assert voltage_text(window, point(6, 2)) == "0 V"
        assert voltage_text(window, point(4, 3)) == ""
        assert current_text(window, "R1") == "500 uA"
        assert current_text(window, "R2") == "500 uA"
        assert current_text(window, "V1") == "-500 uA"
        assert window.selected_node_dc_label.text() == "5 V"
        assert window.selected_node_formula_label.text().startswith("V(s)")
        scene = window.connection_grid_scene
        midpoint = scene.connection_point_items_by_identifier[point(4, 4)]
        resistor = scene.component_items_by_reference["R1"]
        assert "DC: 5 V" in midpoint.toolTip()
        assert "DC current: 500 uA" in resistor.toolTip()
    finally:
        close_window(window)


def test_a_node_with_no_formula_still_shows_the_dc_number(qt_application):
    window = MainWindow()

    try:
        build_diode(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        show_on_scene(window)
        window.show_dc_operating_point(OperatingPoint(
            {"N001": 5.0, "N002": 1.8, "0": 0.0},
            {"R1": 0.0032, "D1": 0.0032, "V1": -0.0032},
        ))
        select_point(window, point(4, 4))

        assert "no s-domain formula" in window.selected_node_formula_label.text()
        assert window.selected_node_dc_label.text() == "1.8 V"
        assert voltage_text(window, point(4, 4)) == "1.8 V"
    finally:
        close_window(window)


def test_editing_the_circuit_clears_the_dc_numbers(qt_application):
    window = MainWindow()

    try:
        build_divider(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        show_on_scene(window)
        window.show_dc_operating_point(OperatingPoint(
            {"N001": 10.0, "N002": 5.0, "0": 0.0},
            {"R1": 0.0005, "R2": 0.0005, "V1": -0.0005},
        ))
        select_point(window, point(4, 4))
        assert window.selected_node_dc_label.text() == "5 V"

        window.mark_project_modified("Changed a part.")

        assert window.selected_node_dc_label.text() == "-"
        assert voltage_text(window, point(4, 4)) == ""
        assert current_text(window, "R1") == ""
    finally:
        close_window(window)


def test_the_run_happens_off_the_gui_thread(qt_application, monkeypatch):
    window = MainWindow()
    seen = {}

    def fake_run(netlist):
        seen["qthread"] = QThread.currentThread()
        seen["netlist"] = netlist
        return OperatingPoint(
            {"N001": 10.0, "N002": 5.0, "0": 0.0},
            {"R1": 0.0005, "R2": 0.0005, "V1": -0.0005},
        )

    monkeypatch.setattr(runner, "run_op", fake_run)

    try:
        build_divider(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        show_on_scene(window)
        window.run_dc_operating_point()

        for _ in range(50):
            QApplication.processEvents()
            if (window.dc_operating_point_action.isEnabled() and
                    voltage_text(window, point(4, 4)) == "5 V"):
                break
            QTest.qWait(20)

        assert seen["qthread"] is not window.thread()
        assert "R1 N001 N002 10k" in seen["netlist"]
        assert voltage_text(window, point(4, 4)) == "5 V"
        assert window.dc_operating_point_action.isEnabled()
    finally:
        close_window(window)
