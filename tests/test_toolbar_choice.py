"""
The main toolbar shows the menu commands the user has turned on.

It starts with Delete, Wire Mode, Probe Mode, and DC Operating Point,
on the same row as the grid size. Save stays in the File menu.
View > Toolbar turns the others on or off. Zoom stays in the View menu.
"""

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication

from gui.main_window import MainWindow


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def command_texts(window):
    return [
        action.text()
        for action in window.main_tool_bar.actions()
        if action.text() and not action.isSeparator()
    ]


def toolbar_menu(window):
    view_menu = next(
        action.menu()
        for action in window.menuBar().actions()
        if action.text() == "&View"
    )
    return next(
        action.menu()
        for action in view_menu.actions()
        if action.text() == "Toolbar"
    )


def test_the_toolbar_starts_short_and_zoom_stays_in_the_menu(qt_application):
    window = MainWindow()

    try:
        assert command_texts(window) == [
            "Delete",
            "Wire Mode",
            "Probe Mode",
            "DC Operating Point",
        ]
        assert window.grid_tool_bar is window.main_tool_bar
        assert window.toolBarBreak(window.main_tool_bar) is False
        assert window.grid_configuration_widget.parent() is (
            window.main_tool_bar
        )
        entries = [action.text() for action in toolbar_menu(window).actions()]
        assert "Zoom In" not in entries
        assert "Zoom Out" not in entries
        assert "Zoom to Fit" not in entries
        assert entries[:4] == [
            "New Grid Project",
            "Open Project...",
            "Save Project",
            "Print...",
        ]
        assert not toolbar_menu(window).actions()[2].isChecked()
        assert not toolbar_menu(window).actions()[0].isChecked()
        file_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "&File"
        )
        assert window.save_project_action in file_menu.actions()
        assert window.zoom_in_action not in window.main_tool_bar.actions()
    finally:
        close_window(window)


def test_a_toolbar_command_can_be_turned_off_and_another_on(qt_application):
    window = MainWindow()

    try:
        menu = toolbar_menu(window)
        by_text = {action.text(): action for action in menu.actions()}
        by_text["Delete"].trigger()
        by_text["New Grid Project"].trigger()

        assert "Delete" not in command_texts(window)
        assert "Save Project" not in command_texts(window)
        assert command_texts(window)[0] == "New Grid Project"
        file_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "&File"
        )
        assert window.save_project_action in file_menu.actions()
        assert window.new_project_action in window.main_tool_bar.actions()
    finally:
        close_window(window)


def test_the_old_default_drops_save(qt_application, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    settings = QSettings("CircuitWorkbench", "CircuitWorkbench")
    settings.clear()
    settings.setValue(
        "toolbar-v1",
        "save_project_action|delete_component_action|wire_mode_action|"
        "probe_mode_action|dc_operating_point_action",
    )
    window = MainWindow()

    try:
        window.show()
        QApplication.processEvents()
        assert "Save Project" not in command_texts(window)
        assert command_texts(window) == [
            "Delete",
            "Wire Mode",
            "Probe Mode",
            "DC Operating Point",
        ]
        close_window(window)
    finally:
        settings.clear()


def test_the_toolbar_choice_comes_back_next_time(qt_application, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    settings = QSettings("CircuitWorkbench", "CircuitWorkbench")
    settings.clear()
    window = MainWindow()

    try:
        window.show()
        QApplication.processEvents()
        menu = toolbar_menu(window)
        by_text = {action.text(): action for action in menu.actions()}
        by_text["Print..."].trigger()
        by_text["Wire Mode"].trigger()
        close_window(window)

        restored = MainWindow()
        restored.show()
        QApplication.processEvents()
        texts = command_texts(restored)
        assert "Print..." in texts
        assert "Wire Mode" not in texts
        assert "Delete" in texts
        assert "Save Project" not in texts
        assert restored.zoom_in_action not in restored.main_tool_bar.actions()
        close_window(restored)
    finally:
        settings.clear()
