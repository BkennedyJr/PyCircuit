"""
Snapshot keeps one reading. Continuous runs it again.

Hand calculation for the divider: 10 V across 10k + 10k is 5 V.
The bottom resistor at 30k is 10 * 30/40 = 7.5 V and 250 uA. The
source at 8 V with that 30k is 6 V and 200 uA. Snapshot clears the
drawn numbers when the value changes. The next DC run shows the
new reading.
"""

import pytest

from gui.main_window import MainWindow
from tests.test_bode import point
from tests.test_refresh_on_edit import (
    build_divider,
    close_window,
    current_text,
    select,
    show_on_scene,
    volts_at,
    wait_until_idle,
)


def _simulate_entries(window):
    simulate = next(
        action.menu()
        for action in window.menuBar().actions()
        if action.text() == "&Simulate"
    )
    return [
        action.text()
        for action in simulate.actions()
        if not action.isSeparator()
    ]


def test_continuous_is_the_usual_choice_and_the_plots_follow_it(
        qt_application):
    window = MainWindow()

    try:
        assert _simulate_entries(window) == [
            "DC Operating Point",
            "Snapshot",
            "Continuous",
        ]
        assert window.continuous_action.isChecked()
        assert not window.snapshot_action.isChecked()
        assert window._continuous
        assert window.oscilloscope_dock.update_mode_combo.currentText() == (
            "Continuous"
        )

        window.snapshot_action.trigger()
        assert not window._continuous
        assert window.snapshot_action.isChecked()
        assert window.oscilloscope_dock.update_mode_combo.currentText() == (
            "Snapshot"
        )
        assert window.bode_dock.update_mode_combo.currentText() == "Snapshot"
        assert window.fft_dock.update_mode_combo.currentText() == "Snapshot"
        assert "Snapshot" in window.statusBar().currentMessage()

        window._on_update_mode_combo(1)
        assert window._continuous
        assert window.continuous_action.isChecked()
        assert window.bode_dock.update_mode_combo.currentIndex() == 1
        assert window.fft_dock.update_mode_combo.currentIndex() == 1
        assert "Continuous" in window.statusBar().currentMessage()
    finally:
        close_window(window)


def test_snapshot_keeps_one_reading_until_the_next_run(qt_application):
    window = MainWindow()

    try:
        build_divider(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        show_on_scene(window)
        window.run_dc_operating_point()
        wait_until_idle(window)
        assert volts_at(window, point(4, 4)) == pytest.approx(5.0)

        window.set_continuous(False)
        assert volts_at(window, point(4, 4)) == pytest.approx(5.0)

        select(window, "R2")
        window.apply_component_value("30k")
        assert window._dc_volts_by_node == {}
        assert current_text(window, "R1") == ""
        assert window._dc_thread is None

        window.run_dc_operating_point()
        wait_until_idle(window)
        assert volts_at(window, point(4, 4)) == pytest.approx(7.5)
        assert current_text(window, "R1") == "250 uA"

        select(window, "V1")
        window.apply_component_value("8")
        assert window._dc_volts_by_node == {}

        window.set_continuous(True)
        assert window._dc_volts_by_node == {}
        assert window._dc_thread is None

        window.run_dc_operating_point()
        wait_until_idle(window)
        assert volts_at(window, point(4, 4)) == pytest.approx(6.0)
        assert current_text(window, "R1") == "200 uA"
    finally:
        close_window(window)
