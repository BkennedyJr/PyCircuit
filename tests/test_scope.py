"""
Oscilloscope dock.

Start with no source says so. A unity-gain buffer puts the 1 V peak
input and the output on the scope, within 1 percent of each other.
Dragging a probe onto a point from the last run keeps the trace.
A point that was not in the run asks for Start again.
"""

import time

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QDockWidget

from gui.main_window import MainWindow
from sim import runner
from tests.test_transient import build_buffer, build_rc_step, place, point

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def wait_for_transient(window):
    deadline = time.time() + 30

    while window._tran_thread is not None and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)

    assert window._tran_thread is None


def test_the_oscilloscope_dock_floats(qt_application):
    window = MainWindow()

    try:
        window.show()
        QApplication.processEvents()
        dock = window.oscilloscope_dock
        assert isinstance(dock, QDockWidget)
        assert dock.windowTitle() == "Oscilloscope"
        assert dock.allowedAreas() & Qt.BottomDockWidgetArea
        dock.setFloating(True)
        QApplication.processEvents()
        assert dock.isFloating()
        titles = [
            action.text()
            for action in window.menuBar().actions()
            if action.text() == "&View"
        ]
        view_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "&View"
        )
        assert "Oscilloscope" in [
            action.text() for action in view_menu.actions()
        ]
        assert titles == ["&View"]
    finally:
        close_window(window)


def test_start_with_no_source_names_the_problem(qt_application):
    window = MainWindow()
    recorded = []
    window.show_error_message = (
        lambda title, reason, resolution: recorded.append((title, reason))
    )

    try:
        place(window.component_collection, window.connection_grid,
              "ground", 6, 2)
        place(window.component_collection, window.connection_grid,
              "resistor", 4, 2, "1k")
        window.run_transient()
        assert recorded == [("Oscilloscope", "Add a source before running.")]
        assert window._tran_thread is None
    finally:
        close_window(window)


@needs_ngspice
def test_the_buffer_draws_input_and_output_within_1_percent(qt_application):
    window = MainWindow()

    try:
        build_buffer(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        window.probe_collection.add_voltage(
            point(5, 3), window.connection_grid
        )
        window.probe_collection.add_voltage(
            point(4, 5), window.connection_grid
        )
        window.refresh_scope_channels()
        window.oscilloscope_dock.refresh_automatic_times(
            window.component_collection.get_components()
        )
        window.run_transient()
        wait_for_transient(window)

        series = {
            name: values
            for name, _time, values in window.oscilloscope_dock.plotted_series()
        }
        assert set(series) == {"P1", "P2"}
        input_peak = max(series["P1"])
        output_peak = max(series["P2"])
        assert input_peak == pytest.approx(1.0, rel=0.01)
        assert output_peak == pytest.approx(input_peak, rel=0.01)
        assert window.probe_collection.get("P1").has_plot
        assert window.probe_collection.get("P2").has_plot
    finally:
        close_window(window)


@needs_ngspice
def test_moving_a_probe_uses_the_last_run(qt_application):
    window = MainWindow()

    try:
        build_buffer(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        window.probe_collection.add_voltage(
            point(5, 3), window.connection_grid
        )
        window.refresh_scope_channels()
        window.run_transient()
        wait_for_transient(window)
        before = window.oscilloscope_dock.plotted_series()

        window.probe_collection.move_point(
            "P1", point(5, 2), window.connection_grid
        )
        window.handle_probe_moved("P1")
        after = window.oscilloscope_dock.plotted_series()

        assert after[0][2] == pytest.approx(before[0][2])

        window.probe_collection.move_point(
            "P1", point(1, 1), window.connection_grid
        )
        window.handle_probe_moved("P1")

        assert window.oscilloscope_dock.plotted_series() == []
        assert "Press Start again" in window.statusBar().currentMessage()
        assert not window.probe_collection.get("P1").has_plot
    finally:
        close_window(window)


@needs_ngspice
def test_an_led_above_1_ma_stays_lit_after_a_rebuild(qt_application):
    window = MainWindow()

    try:
        grid = window.connection_grid
        parts = window.component_collection
        wires = window.wire_collection
        build_rc_step(grid, parts, wires)
        # Swap the capacitor for an LED on the same pins: 5 V through 1k.
        parts.remove_component("C1")
        parts.remove_component("V1")
        place(parts, grid, "dc_source", 4, 2, "5")
        place(parts, grid, "led", 4, 4, "LED_RED")
        window.connection_grid_scene.rebuild_component_items()
        window.connection_grid_scene.rebuild_wire_items()
        window.run_transient()
        wait_for_transient(window)
        led = window.connection_grid_scene.component_items_by_reference["D1"]
        assert led.is_lit
        window.connection_grid_scene.rebuild_component_items()
        led = window.connection_grid_scene.component_items_by_reference["D1"]
        assert led.is_lit
    finally:
        close_window(window)
