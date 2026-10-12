"""
Panels drag, float, and dock. The scope stays under the circuit.
"""

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import QApplication, QDockWidget, QTabWidget

from gui.main_window import MainWindow


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def test_default_layout_keeps_the_scope_under_the_circuit(qt_application):
    window = MainWindow()

    try:
        assert window.corner(Qt.BottomLeftCorner) == Qt.LeftDockWidgetArea
        assert window.corner(Qt.BottomRightCorner) == Qt.RightDockWidgetArea
        assert window.dockWidgetArea(window.component_dock) == (
            Qt.LeftDockWidgetArea
        )
        assert window.dockWidgetArea(window.oscilloscope_dock) == (
            Qt.BottomDockWidgetArea
        )
        assert window.dockWidgetArea(window.bode_dock) == (
            Qt.BottomDockWidgetArea
        )
        assert window.bode_dock in window.tabifiedDockWidgets(
            window.oscilloscope_dock
        )
        assert window.dockWidgetArea(window.fft_dock) == (
            Qt.BottomDockWidgetArea
        )
        assert window.fft_dock in window.tabifiedDockWidgets(
            window.oscilloscope_dock
        )
        assert window.dockWidgetArea(window.selected_node_dock) == (
            Qt.RightDockWidgetArea
        )
        assert window.dockWidgetArea(window.probe_dock) == (
            Qt.RightDockWidgetArea
        )
        assert window.probe_dock in window.tabifiedDockWidgets(
            window.selected_node_dock
        )
        assert window.tabPosition(Qt.RightDockWidgetArea) == QTabWidget.North
    finally:
        close_window(window)


def test_every_panel_can_move_float_and_close(qt_application):
    window = MainWindow()

    try:
        window.show()
        QApplication.processEvents()
        docks = (
            window.component_dock,
            window.selected_node_dock,
            window.probe_dock,
            window.oscilloscope_dock,
            window.fft_dock,
        )

        for dock in docks:
            assert isinstance(dock, QDockWidget)
            features = dock.features()
            assert features & QDockWidget.DockWidgetMovable
            assert features & QDockWidget.DockWidgetFloatable
            assert features & QDockWidget.DockWidgetClosable

        assert window.main_tool_bar.isMovable()
        assert window.main_tool_bar.isFloatable()
        assert window.grid_tool_bar.isMovable()
        assert window.grid_tool_bar.isFloatable()

        window.addDockWidget(Qt.TopDockWidgetArea, window.probe_dock)
        QApplication.processEvents()
        assert window.dockWidgetArea(window.probe_dock) == Qt.TopDockWidgetArea

        window.oscilloscope_dock.setFloating(True)
        QApplication.processEvents()
        assert window.oscilloscope_dock.isFloating()
    finally:
        close_window(window)


def test_a_normal_window_shows_the_circuit_and_the_scope(qt_application):
    window = MainWindow()

    try:
        window.resize(1300, 850)
        window.show()
        QApplication.processEvents()
        grid = window.centralWidget()
        dock = window.oscilloscope_dock
        assert grid.height() >= 200
        assert dock.height() >= 320
        assert window.component_dock.height() > grid.height()

        edit = dock.run_time_edit
        plot = dock.plot
        edit_at = edit.mapTo(dock, edit.rect().topLeft())
        plot_at = plot.mapTo(dock, plot.rect().topLeft())
        assert edit_at.x() + edit.width() <= plot_at.x()
        assert plot_at.y() <= edit_at.y()
        assert plot.height() > edit.height()

        grid_bottom = grid.mapToGlobal(grid.rect().bottomLeft()).y()
        edit_top = edit.mapToGlobal(edit.rect().topLeft()).y()
        plot_top = plot.mapToGlobal(plot.rect().topLeft()).y()
        assert edit_top >= grid_bottom
        assert plot_top >= grid_bottom
    finally:
        close_window(window)


def test_view_menu_lists_every_panel(qt_application):
    window = MainWindow()

    try:
        view_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "&View"
        )
        assert [action.text() for action in view_menu.actions()] == [
            "Zoom In",
            "Zoom Out",
            "Zoom to Fit",
            "",
            "Toolbar",
            "",
            "Components",
            "Selected Connection Point",
            "Probe",
            "Oscilloscope",
            "Bode",
            "FFT",
        ]
    finally:
        close_window(window)


def test_closing_during_tests_does_not_save_the_layout(qt_application):
    settings = QSettings("CircuitWorkbench", "CircuitWorkbench")
    settings.remove("geometry-v2")
    settings.remove("state-v2")
    settings.remove("toolbar-v1")
    window = MainWindow()

    try:
        window.show()
        QApplication.processEvents()
    finally:
        close_window(window)

    assert settings.value("geometry-v2") is None
    assert settings.value("state-v2") is None
    assert settings.value("toolbar-v1") is None


def test_the_arrangement_comes_back_next_time(qt_application, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    settings = QSettings("CircuitWorkbench", "CircuitWorkbench")
    settings.clear()
    window = MainWindow()

    try:
        window.show()
        QApplication.processEvents()
        window.oscilloscope_dock.hide()
        window.save_window_arrangement()
        close_window(window)

        restored = MainWindow()
        restored.show()
        QApplication.processEvents()
        assert restored.oscilloscope_dock.isHidden()
        close_window(restored)
    finally:
        settings.clear()
