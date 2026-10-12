"""
Panels drag, float, and dock. The scope stays under the circuit.
"""

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import QApplication, QDockWidget

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
        assert window.dockWidgetArea(window.selected_node_dock) == (
            Qt.RightDockWidgetArea
        )
        assert window.dockWidgetArea(window.probe_dock) == (
            Qt.RightDockWidgetArea
        )
        assert window.probe_dock in window.tabifiedDockWidgets(
            window.selected_node_dock
        )
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
        window.resize(1100, 720)
        window.show()
        QApplication.processEvents()
        assert window.centralWidget().height() >= 200
        assert window.oscilloscope_dock.height() >= 120
        assert window.component_dock.height() > window.centralWidget().height()
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
            "Components",
            "Selected Connection Point",
            "Probe",
            "Oscilloscope",
        ]
    finally:
        close_window(window)


def test_closing_during_tests_does_not_save_the_layout(qt_application):
    settings = QSettings("CircuitWorkbench", "CircuitWorkbench")
    settings.remove("geometry")
    settings.remove("state")
    window = MainWindow()

    try:
        window.show()
        QApplication.processEvents()
    finally:
        close_window(window)

    assert settings.value("geometry") is None
    assert settings.value("state") is None


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
