"""
Tests for PR D in the GUI: gui.wire_item, Wire mode in the scene, and the
main window's Wire Mode action, Delete and grid-resize cleanup. Headless
through the qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QKeySequence, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QGraphicsItem, QToolBar

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.wires import Wire, WireCollection
from gui.component_item import COMPONENT_Z_VALUE, LABEL_Z_VALUE
from gui.component_panel_widget import NO_PART_SELECTED_TEXT
from gui.grid_editor import (
    CONNECTION_POINT_Z_VALUE,
    WIRE_SNAP_DISTANCE,
    ConnectionGridScene,
    ConnectionGridView,
    grid_point_to_scene_position,
)
from gui.main_window import MainWindow
from gui.wire_item import (
    SELECTED_WIRE_COLOR,
    WIRE_COLOR,
    WIRE_PICK_WIDTH,
    WIRE_Z_VALUE,
    WireItem,
)
from tests.view_mouse import click, drag, send_mouse


def point(row, column):
    return grid_point_to_scene_position(row, column)


# ----- WireItem ---------------------------------------------------------------


def test_wire_item_draws_between_the_two_points(qt_application):
    wire = Wire("W1", (2, 2), (2, 4))
    item = WireItem(wire, point(2, 2), point(2, 4))

    assert item.line().p1() == point(2, 2)
    assert item.line().p2() == point(2, 4)
    assert item.toolTip() == "W1 from NODE_R02_C02 to NODE_R02_C04"
    assert item.flags() & QGraphicsItem.ItemIsSelectable
    assert not item.flags() & QGraphicsItem.ItemIsMovable


def test_wire_stacks_below_parts_and_dots_above_label_patches():
    assert LABEL_Z_VALUE < WIRE_Z_VALUE < CONNECTION_POINT_Z_VALUE
    assert WIRE_Z_VALUE < COMPONENT_Z_VALUE


def test_wire_item_needs_a_wire(qt_application):
    with pytest.raises(ComponentError, match="WireItem needs a Wire"):
        WireItem("W1", point(1, 1), point(1, 2))


def test_wire_click_area_is_wider_than_the_line(qt_application):
    item = WireItem(Wire("W1", (2, 2), (2, 4)), point(2, 2), point(2, 4))
    middle = (point(2, 2) + point(2, 4)) / 2

    assert item.shape().contains(middle + QPointF(0, WIRE_PICK_WIDTH / 2 - 1))
    assert not item.shape().contains(
        middle + QPointF(0, WIRE_PICK_WIDTH / 2 + 1)
    )
    assert item.boundingRect().contains(item.shape().boundingRect())


def test_wire_turns_yellow_when_selected(qt_application):
    scene = ConnectionGridScene(ConnectionGrid(4, 4))
    item = WireItem(Wire("W1", (2, 2), (2, 4)), point(2, 2), point(2, 4))
    scene.addItem(item)

    assert item.pen().color() == QColor(WIRE_COLOR)
    item.setSelected(True)
    assert item.pen().color() == QColor(SELECTED_WIRE_COLOR)
    item.setSelected(False)
    assert item.pen().color() == QColor(WIRE_COLOR)


# ----- scene ------------------------------------------------------------------


class Editor:
    pass


@pytest.fixture
def editor(qt_application):
    grid = ConnectionGrid(8, 8)
    scene = ConnectionGridScene(grid)
    components = ComponentCollection()
    wires = WireCollection()
    scene.set_component_collection(components)
    scene.set_wire_collection(wires)
    view = ConnectionGridView(scene)
    view.resize(900, 800)
    view.show()
    view.resetTransform()
    view.centerOn(point(4, 4))
    QApplication.processEvents()

    result = Editor()
    result.grid = grid
    result.scene = scene
    result.view = view
    result.components = components
    result.wires = wires
    result.added = []
    result.refused = []
    result.selected = []
    scene.wire_added.connect(result.added.append)
    scene.wire_refused.connect(result.refused.append)
    scene.wires_selected.connect(result.selected.append)
    yield result
    view.close()
    view.deleteLater()


def wire_ends(editor):
    return [(wire.start_identifier, wire.end_identifier)
            for wire in editor.wires.get_wires()]


def test_wire_mode_drag_adds_a_wire(editor):
    editor.scene.set_wire_mode(True)

    # Start and end a few pixels off the centres: within the snap distance.
    drag(editor.view, point(2, 2) + QPointF(5, -4),
         point(2, 5) + QPointF(-6, 7))

    assert wire_ends(editor) == [("NODE_R02_C02", "NODE_R02_C05")]
    assert editor.added == ["W1"]
    item = editor.scene.wire_items_by_reference["W1"]
    assert item.scene() is editor.scene
    assert (item.line().p1(), item.line().p2()) == (point(2, 2), point(2, 5))
    assert editor.scene.wire_preview_item is None


def test_rubber_band_line_follows_the_mouse(editor):
    editor.scene.set_wire_mode(True)
    send_mouse(editor.view, QEvent.MouseButtonPress, point(3, 3))
    send_mouse(editor.view, QEvent.MouseMove, point(3, 3) + QPointF(47, 81),
               Qt.NoButton)

    preview = editor.scene.wire_preview_item
    assert preview is not None and preview.scene() is editor.scene
    assert preview.line().p1() == point(3, 3)
    assert preview.line().p2() == point(3, 3) + QPointF(47, 81)
    assert preview.pen().style() == Qt.DashLine
    assert editor.wires.get_wires() == []

    send_mouse(editor.view, QEvent.MouseButtonRelease, point(5, 3),
               Qt.LeftButton, Qt.NoButton)

    assert wire_ends(editor) == [("NODE_R03_C03", "NODE_R05_C03")]
    assert preview.scene() is None


def test_diagonal_drag_is_refused_with_a_message(editor):
    editor.scene.set_wire_mode(True)

    drag(editor.view, point(1, 1), point(4, 3))

    assert editor.wires.get_wires() == []
    assert editor.refused == [(
        "A wire from NODE_R01_C01 to NODE_R04_C03 would be diagonal. Wires "
        "run along a row or a column: draw two straight wires that meet at "
        "a corner."
    )]
    assert editor.scene.wire_preview_item is None


def test_release_away_from_a_point_adds_nothing(editor):
    editor.scene.set_wire_mode(True)

    drag(editor.view, point(2, 2), point(2, 4) + QPointF(30, 0))

    assert editor.wires.get_wires() == []
    assert editor.refused == [
        "release on a grid point to finish the wire from NODE_R02_C02."
    ]
    assert editor.scene.wire_preview_item is None


def test_release_on_the_start_point_cancels_quietly(editor):
    editor.scene.set_wire_mode(True)

    click(editor.view, point(2, 2))
    drag(editor.view, point(2, 2), point(2, 2) + QPointF(8, 8))

    assert editor.wires.get_wires() == []
    assert editor.refused == [] and editor.added == []


def test_duplicate_drag_is_refused(editor):
    editor.scene.set_wire_mode(True)
    drag(editor.view, point(2, 2), point(2, 4))

    drag(editor.view, point(2, 4), point(2, 2))

    assert len(editor.wires.get_wires()) == 1
    assert editor.refused == [
        "W1 already joins NODE_R02_C02 and NODE_R02_C04."
    ]


def test_snap_distance_limits(editor):
    scene = editor.scene
    inside = WIRE_SNAP_DISTANCE - 0.5
    outside = WIRE_SNAP_DISTANCE + 0.5

    assert scene.find_grid_point_near(point(3, 3) + QPointF(inside, 0)) == (
        "NODE_R03_C03"
    )
    assert scene.find_grid_point_near(point(3, 3) + QPointF(outside, 0)) is None
    # Beyond the last row and column there are no points.
    assert scene.find_grid_point_near(point(9, 3)) is None
    assert scene.find_grid_point_near(point(3, 0)) is None


def test_press_off_a_point_in_wire_mode_still_selects(editor):
    editor.components.add_component("resistor", 5, 5, "1k", editor.grid)
    editor.scene.rebuild_component_items()
    editor.scene.set_wire_mode(True)

    # The resistor body is half a step from both pins: not a grid point.
    click(editor.view, (point(5, 5) + point(5, 6)) / 2)

    assert editor.scene.component_items_by_reference["R1"].isSelected()
    assert editor.wires.get_wires() == []


def test_without_wire_mode_a_press_drag_on_a_point_selects(editor):
    dot = editor.scene.connection_point_items_by_identifier["NODE_R02_C02"]

    click(editor.view, point(2, 2))
    assert dot.isSelected()

    # A drag from empty space rubber-band selects; no wire, no preview.
    drag(editor.view, point(2, 2) + QPointF(-25, -25),
         point(3, 3) + QPointF(25, 25))

    assert editor.wires.get_wires() == []
    assert editor.scene.wire_preview_item is None
    assert editor.scene.connection_point_items_by_identifier[
        "NODE_R03_C03"
    ].isSelected()


def test_without_wire_mode_a_drag_starting_on_a_point_draws_nothing(editor):
    drag(editor.view, point(2, 2), point(2, 4))

    assert editor.wires.get_wires() == []
    assert editor.scene.wire_preview_item is None
    assert editor.scene.connection_point_items_by_identifier[
        "NODE_R02_C02"
    ].isSelected()


def test_escape_cancels_a_wire_in_progress(editor):
    editor.scene.set_wire_mode(True)
    send_mouse(editor.view, QEvent.MouseButtonPress, point(2, 2))
    send_mouse(editor.view, QEvent.MouseMove, point(2, 4), Qt.NoButton)
    editor.view.setFocus()

    QTest.keyClick(editor.view.viewport(), Qt.Key_Escape)

    assert editor.scene.wire_preview_item is None
    assert editor.scene.wire_start_identifier is None
    send_mouse(editor.view, QEvent.MouseButtonRelease, point(2, 4),
               Qt.LeftButton, Qt.NoButton)
    assert editor.wires.get_wires() == []


def test_leaving_wire_mode_cancels_a_wire_in_progress(editor):
    editor.scene.set_wire_mode(True)
    send_mouse(editor.view, QEvent.MouseButtonPress, point(2, 2))

    editor.scene.set_wire_mode(False)

    assert editor.scene.wire_preview_item is None
    send_mouse(editor.view, QEvent.MouseButtonRelease, point(2, 4),
               Qt.LeftButton, Qt.NoButton)
    assert editor.wires.get_wires() == []


def test_wire_can_be_selected_by_clicking_it(editor):
    editor.wires.add_wire("NODE_R02_C02", "NODE_R02_C05", editor.grid)
    editor.scene.rebuild_wire_items()

    click(editor.view, (point(2, 3) + point(2, 4)) / 2 + QPointF(0, 3))

    assert editor.scene.wire_items_by_reference["W1"].isSelected()
    assert editor.selected[-1] == ["W1"]


def test_wires_survive_a_grid_rebuild(editor):
    editor.wires.add_wire("NODE_R02_C02", "NODE_R02_C05", editor.grid)
    editor.scene.rebuild_wire_items()

    editor.scene.set_connection_grid(editor.grid)

    item = editor.scene.wire_items_by_reference["W1"]
    assert item.scene() is editor.scene


def render(scene, rect):
    image = QImage(int(rect.width()), int(rect.height()),
                   QImage.Format_ARGB32)
    image.fill(QColor("black"))
    painter = QPainter(image)
    scene.render(painter, QRectF(image.rect()), rect)
    painter.end()
    return image


def test_wire_draws_above_grid_lines_below_dots_and_parts(editor):
    editor.wires.add_wire("NODE_R02_C02", "NODE_R02_C05", editor.grid)
    editor.components.add_component("resistor", 2, 3, "1k", editor.grid)
    editor.scene.rebuild_wire_items()
    editor.scene.rebuild_component_items()
    rect = editor.scene.sceneRect()
    image = render(editor.scene, rect)

    def color_at(position):
        return QColor(image.pixel(int(position.x() - rect.x()),
                                  int(position.y() - rect.y())))

    # Between C2 and C3, the wire covers the grid line.
    assert color_at((point(2, 2) + point(2, 3)) / 2) == QColor(WIRE_COLOR)
    # On the C2 dot centre, the dot is on top.
    assert color_at(point(2, 2)) != QColor(WIRE_COLOR)
    # In the middle of R1's body, the part is on top.
    assert color_at((point(2, 3) + point(2, 4)) / 2 + QPointF(0, 4)) != (
        QColor(WIRE_COLOR)
    )


# ----- main window -------------------------------------------------------------


@pytest.fixture
def window(qt_application, monkeypatch):
    main_window = MainWindow()
    main_window.recorded_errors = []
    monkeypatch.setattr(
        main_window, "show_error_message",
        lambda *details: main_window.recorded_errors.append(details)
    )
    main_window.resize(1200, 800)
    main_window.show()
    QApplication.processEvents()
    yield main_window
    main_window.is_project_modified = False
    main_window.close()
    main_window.deleteLater()


def test_wire_mode_action_in_menu_and_toolbar(window):
    action = window.wire_mode_action

    assert action.isCheckable() and not action.isChecked()
    assert action.shortcut() == QKeySequence("W")
    assert action.shortcutContext() == Qt.WidgetWithChildrenShortcut
    assert action in window.connection_grid_view.actions()
    component_menu = next(
        menu_action.menu() for menu_action in window.menuBar().actions()
        if menu_action.text() == "&Component"
    )
    assert action in component_menu.actions()
    tool_bar_actions = [
        tool_action for tool_bar in window.findChildren(QToolBar)
        for tool_action in tool_bar.actions()
    ]
    assert action in tool_bar_actions


def test_toggling_wire_mode(window):
    window.wire_mode_action.trigger()

    assert window.connection_grid_scene.is_wire_mode is True
    assert window.connection_grid_view.viewport().cursor().shape() == (
        Qt.CrossCursor
    )
    assert window.statusBar().currentMessage().startswith("Wire mode:")

    window.wire_mode_action.trigger()

    assert window.connection_grid_scene.is_wire_mode is False
    assert window.connection_grid_view.viewport().cursor().shape() == (
        Qt.ArrowCursor
    )


def test_w_key_on_the_view_toggles_wire_mode(window):
    window.connection_grid_view.setFocus()
    QApplication.processEvents()

    QTest.keyClick(window.connection_grid_view, Qt.Key_W)

    assert window.wire_mode_action.isChecked()


def test_set_wire_mode_keeps_the_action_in_step(window):
    window.set_wire_mode(True)

    assert window.wire_mode_action.isChecked()
    assert window.connection_grid_scene.is_wire_mode


def test_drawing_a_wire_reports_and_marks_modified(window):
    window.set_wire_mode(True)

    drag(window.connection_grid_view, point(2, 2), point(2, 4))

    assert window.statusBar().currentMessage() == (
        "Added W1 from NODE_R02_C02 to NODE_R02_C04."
    )
    assert window.is_project_modified is True


def test_refused_wire_is_a_status_message(window):
    window.set_wire_mode(True)
    drag(window.connection_grid_view, point(2, 2), point(2, 4))
    window.is_project_modified = False

    drag(window.connection_grid_view, point(2, 4), point(2, 2))

    assert window.statusBar().currentMessage() == (
        "Wire not added: W1 already joins NODE_R02_C02 and NODE_R02_C04."
    )
    assert window.is_project_modified is False
    assert window.recorded_errors == []


def test_delete_removes_a_selected_wire(window):
    window.set_wire_mode(True)
    drag(window.connection_grid_view, point(2, 2), point(2, 4))
    window.set_wire_mode(False)
    window.connection_grid_scene.wire_items_by_reference["W1"].setSelected(
        True
    )
    assert window.delete_component_action.isEnabled()

    window.delete_component_action.trigger()

    assert window.wire_collection.get_wires() == []
    assert window.connection_grid_scene.wire_items_by_reference == {}
    assert window.statusBar().currentMessage() == "Deleted W1."
    assert window.delete_component_action.isEnabled() is False


def test_delete_key_on_the_view_removes_a_wire(window):
    window.wire_collection.add_wire("NODE_R02_C02", "NODE_R02_C04",
                                    window.connection_grid)
    window.connection_grid_scene.rebuild_wire_items()
    # Between the C2 and C3 dots (a dot draws above the wire).
    click(window.connection_grid_view,
          (point(2, 2) + point(2, 3)) / 2 + QPointF(0, 3))
    assert window.selected_wire_references == ["W1"]
    window.connection_grid_view.setFocus()
    QApplication.processEvents()

    QTest.keyClick(window.connection_grid_view, Qt.Key_Delete)

    assert window.wire_collection.get_wires() == []


def test_delete_removes_a_part_and_selected_wires_together(window):
    scene = window.connection_grid_scene
    scene.connection_point_items_by_identifier["NODE_R05_C05"].setSelected(
        True
    )
    window.place_component("resistor", "1k")
    window.wire_collection.add_wire("NODE_R02_C02", "NODE_R02_C04",
                                    window.connection_grid)
    window.wire_collection.add_wire("NODE_R03_C02", "NODE_R03_C04",
                                    window.connection_grid)
    scene.rebuild_wire_items()
    scene.wire_items_by_reference["W2"].setSelected(True)

    window.delete_selection()

    assert window.component_collection.get_components() == []
    assert [wire.reference for wire in window.wire_collection.get_wires()] == [
        "W1"
    ]
    assert window.statusBar().currentMessage() == "Deleted R1, W2."


def test_panel_delete_part_button_leaves_wires(window):
    scene = window.connection_grid_scene
    scene.connection_point_items_by_identifier["NODE_R05_C05"].setSelected(
        True
    )
    window.place_component("resistor", "1k")
    window.wire_collection.add_wire("NODE_R05_C05", "NODE_R07_C05",
                                    window.connection_grid)
    scene.rebuild_wire_items()

    window.component_panel_widget.delete_button.click()

    assert window.component_collection.get_components() == []
    assert len(window.wire_collection.get_wires()) == 1


def test_shrinking_the_grid_removes_off_grid_wires(window):
    for start, end in [("NODE_R02_C02", "NODE_R02_C04"),
                       ("NODE_R02_C04", "NODE_R08_C04"),
                       ("NODE_R06_C06", "NODE_R06_C07")]:
        window.wire_collection.add_wire(start, end, window.connection_grid)
    window.connection_grid_scene.rebuild_wire_items()

    window.apply_grid_configuration(6, 6)

    assert [wire.reference for wire in window.wire_collection.get_wires()] == [
        "W1"
    ]
    assert list(window.connection_grid_scene.wire_items_by_reference) == [
        "W1"
    ]
    assert window.statusBar().currentMessage() == (
        "Grid updated. Removed 2 wire(s) (W2, W3) outside the new grid "
        "boundary."
    )


def test_new_project_starts_with_no_wires(window, monkeypatch):
    window.wire_collection.add_wire("NODE_R02_C02", "NODE_R02_C04",
                                    window.connection_grid)
    window.connection_grid_scene.rebuild_wire_items()
    monkeypatch.setattr(window, "confirm_project_replacement", lambda: True)

    window.create_new_project()

    assert window.wire_collection.get_wires() == []
    assert window.connection_grid_scene.wire_collection is (
        window.wire_collection
    )
    assert window.connection_grid_scene.wire_items_by_reference == {}


def test_delete_removes_every_selected_part_and_wire(window):
    scene = window.connection_grid_scene

    for identifier, kind, value in [
        ("NODE_R05_C05", "resistor", "1k"),
        ("NODE_R07_C02", "capacitor", "100n"),
        ("NODE_R07_C06", "resistor", "2k"),
    ]:
        scene.clearSelection()
        scene.connection_point_items_by_identifier[identifier].setSelected(
            True
        )
        window.place_component(kind, value)

    for start, end in [("NODE_R02_C02", "NODE_R02_C04"),
                       ("NODE_R03_C02", "NODE_R03_C04"),
                       ("NODE_R04_C02", "NODE_R04_C04")]:
        window.wire_collection.add_wire(start, end, window.connection_grid)
    scene.rebuild_wire_items()
    scene.clearSelection()

    for reference in ("R1", "C1"):
        scene.component_items_by_reference[reference].setSelected(True)
    for reference in ("W1", "W2"):
        scene.wire_items_by_reference[reference].setSelected(True)
    window.connection_grid_view.setFocus()
    QApplication.processEvents()

    QTest.keyClick(window.connection_grid_view, Qt.Key_Delete)

    assert [component.reference for component in
            window.component_collection.get_components()] == ["R2"]
    assert [wire.reference for wire in window.wire_collection.get_wires()] == [
        "W3"
    ]
    assert window.statusBar().currentMessage() == "Deleted C1, R1, W1, W2."
    assert window.component_panel_widget.selected_component_label.text() == (
        NO_PART_SELECTED_TEXT
    )
