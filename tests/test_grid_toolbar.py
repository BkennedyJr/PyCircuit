"""
The rows and columns controls live on a toolbar at the top of the window.

Enter on Apply resizes the grid. Enter in a spin box only accepts the
typed number, so tabbing through the boxes does not resize early.
"""

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QDockWidget,
    QToolBar,
)

from gui.grid_configuration_widget import GridConfigurationWidget
from gui.main_window import MainWindow


def toolbar_ancestor(widget):
    parent = widget
    while parent is not None:
        if isinstance(parent, QToolBar):
            return parent
        parent = parent.parentWidget()
    return None


def press_key(window, widget, key):
    """
    Show the window, focus the widget (or the editor inside it), and
    press a key the way a user would.
    """
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    widget.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    focus = QApplication.focusWidget()
    assert focus is widget or widget.isAncestorOf(focus)
    QTest.keyClick(focus, key)


# ----- the widget itself -----

def test_apply_shows_the_point_count(qt_application):
    widget = GridConfigurationWidget()
    widget.set_grid_configuration(6, 10)
    assert widget.connection_point_count_label.text() == "60 points"
    widget.deleteLater()


def test_return_and_enter_on_apply_each_request_once(qt_application):
    widget = GridConfigurationWidget()
    widget.set_grid_configuration(6, 10)
    requested = []
    widget.configuration_requested.connect(
        lambda rows, columns: requested.append((rows, columns))
    )
    button = widget.apply_configuration_button

    for key in (Qt.Key_Return, Qt.Key_Enter):
        QApplication.sendEvent(
            button, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
        )

    assert requested == [(6, 10), (6, 10)]
    widget.deleteLater()


def test_holding_enter_on_apply_does_not_repeat(qt_application):
    widget = GridConfigurationWidget()
    requested = []
    widget.configuration_requested.connect(
        lambda rows, columns: requested.append((rows, columns))
    )
    repeat = QKeyEvent(
        QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "", True, 1
    )
    QApplication.sendEvent(widget.apply_configuration_button, repeat)
    assert requested == []
    widget.deleteLater()


def test_space_on_apply_still_requests(qt_application):
    widget = GridConfigurationWidget()
    widget.show()
    widget.set_grid_configuration(3, 4)
    requested = []
    widget.configuration_requested.connect(
        lambda rows, columns: requested.append((rows, columns))
    )
    button = widget.apply_configuration_button
    button.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    QTest.keyClick(button, Qt.Key_Space)
    assert requested == [(3, 4)]
    widget.close()
    widget.deleteLater()


# ----- the window toolbar -----

def test_grid_controls_sit_on_a_top_toolbar(qt_application):
    window = MainWindow()
    widget = window.grid_configuration_widget
    bar = window.grid_tool_bar

    assert bar.windowTitle() == "Grid"
    assert window.toolBarArea(bar) == Qt.TopToolBarArea
    assert window.toolBarBreak(bar) is True
    assert toolbar_ancestor(widget) is bar
    assert "Grid Configuration" not in [
        dock.windowTitle() for dock in window.findChildren(QDockWidget)
    ]

    window.is_project_modified = False
    window.close()
    window.deleteLater()


def test_enter_on_apply_resizes_the_grid(qt_application):
    window = MainWindow()
    widget = window.grid_configuration_widget
    widget.row_count_spin_box.setValue(5)
    widget.column_count_spin_box.setValue(7)

    press_key(window, widget.apply_configuration_button, Qt.Key_Return)

    assert window.connection_grid.row_count == 5
    assert window.connection_grid.column_count == 7
    assert widget.connection_point_count_label.text() == "35 points"

    window.is_project_modified = False
    window.close()
    window.deleteLater()


def test_enter_in_a_spin_box_does_not_resize_the_grid(qt_application):
    window = MainWindow()
    widget = window.grid_configuration_widget
    widget.row_count_spin_box.setValue(5)
    widget.column_count_spin_box.setValue(7)

    press_key(window, widget.row_count_spin_box, Qt.Key_Return)
    press_key(window, widget.column_count_spin_box, Qt.Key_Enter)

    assert window.connection_grid.row_count == 8
    assert window.connection_grid.column_count == 8

    window.is_project_modified = False
    window.close()
    window.deleteLater()
