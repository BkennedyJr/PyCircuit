"""
Tests for PR C, drag to move: ComponentCollection.move_component (core),
the item drag and the scene snap (gui.component_item, gui.grid_editor),
and the main window's status messages. Qt tests run headless through the
qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import QEvent, QPointF, QRectF, QSizeF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from gui.component_item import (
    COMPONENT_Z_VALUE,
    DRAGGED_COMPONENT_Z_VALUE,
    REFUSED_DROP_COLOR,
)
from gui.grid_editor import (
    GRID_POINT_SPACING,
    ConnectionGridScene,
    ConnectionGridView,
    grid_point_to_scene_position,
    scene_position_to_grid_point,
)
from gui.main_window import MainWindow
from tests.view_mouse import click, drag, send_mouse


def point(row, column):
    return grid_point_to_scene_position(row, column)


def between(first, second):
    return (first + second) / 2


# ----- core: move_component ------------------------------------------------


@pytest.fixture
def grid():
    return ConnectionGrid(8, 8)


@pytest.fixture
def collection():
    return ComponentCollection()


def position(component):
    return (component.row_number, component.column_number, component.rotation)


def test_move_changes_the_anchor_and_pins(collection, grid):
    collection.add_component("resistor", 2, 2, "1k", grid)

    moved = collection.move_component("R1", 5, 4, grid)

    assert moved is collection.get_component("R1")
    assert position(moved) == (5, 4, 0)
    assert moved.get_pin_identifiers() == ["NODE_R05_C04", "NODE_R05_C05"]


def test_move_keeps_rotation_and_value(collection, grid):
    collection.add_component("capacitor", 2, 2, "47n", grid, 90)

    moved = collection.move_component("C1", 6, 7, grid)

    assert position(moved) == (6, 7, 90)
    assert moved.value_text == "47n"
    assert moved.get_pin_identifiers() == ["NODE_R06_C07", "NODE_R07_C07"]


def test_move_onto_its_own_spot_is_allowed(collection, grid):
    collection.add_component("resistor", 2, 2, "1k", grid)

    assert position(collection.move_component("R1", 2, 2, grid)) == (2, 2, 0)


def test_move_sharing_a_pin_is_allowed(collection, grid):
    collection.add_component("resistor", 2, 2, "1k", grid)
    collection.add_component("resistor", 5, 5, "1k", grid)

    # R2 now starts where R1 ends: they connect at R2 C3.
    collection.move_component("R2", 2, 3, grid)

    assert collection.get_component("R2").get_pin_identifiers()[0] == (
        "NODE_R02_C03"
    )


@pytest.mark.parametrize("row, column", [(9, 2), (2, 9), (0, 3), (3, 0),
                                         (-1, -1)])
def test_move_outside_the_grid_is_refused(collection, grid, row, column):
    collection.add_component("resistor", 2, 2, "1k", grid)

    with pytest.raises(ComponentError) as error_info:
        collection.move_component("R1", row, column, grid)

    assert str(error_info.value) == (
        f"R1 cannot be moved to row {row}, column {column}: that is outside "
        "the 8 x 8 grid."
    )
    assert position(collection.get_component("R1")) == (2, 2, 0)


def test_move_with_a_pin_off_the_grid_is_refused(collection, grid):
    collection.add_component("resistor", 2, 2, "1k", grid)

    # The anchor is on the grid, but pin 2 would be column 9.
    with pytest.raises(ComponentError) as error_info:
        collection.move_component("R1", 4, 8, grid)

    assert str(error_info.value) == (
        "R1 cannot be moved to row 4, column 8: a pin would fall outside "
        "the 8 x 8 grid."
    )
    assert position(collection.get_component("R1")) == (2, 2, 0)


def test_move_onto_the_same_pins_is_refused(collection, grid):
    collection.add_component("resistor", 2, 2, "1k", grid)
    collection.add_component("capacitor", 5, 5, "100n", grid, 180)

    # C1 at R2 C3 turned 180 deg would run C3 -> C2: R1's two points.
    with pytest.raises(ComponentError) as error_info:
        collection.move_component("C1", 2, 3, grid)

    assert str(error_info.value).startswith(
        "C1 cannot be moved to row 2, column 3: R1 (Resistor) already "
        "connects exactly these grid points: NODE_R02_C02, NODE_R02_C03."
    )
    assert position(collection.get_component("C1")) == (5, 5, 180)


def test_move_onto_another_transistor_centre_is_refused(collection, grid):
    collection.add_component("npn", 4, 4, "2N3904", grid)
    collection.add_component("pnp", 4, 7, "2N3906", grid, 180)

    with pytest.raises(ComponentError, match="already has its centre"):
        collection.move_component("Q2", 4, 4, grid)

    assert position(collection.get_component("Q2")) == (4, 7, 180)


@pytest.mark.parametrize("row, column", [("4", 4), (4, 4.0), (True, 4),
                                         (4, None)])
def test_move_with_bad_numbers_is_refused(collection, grid, row, column):
    collection.add_component("resistor", 2, 2, "1k", grid)

    with pytest.raises(ComponentError, match="^R1 cannot be moved there: "):
        collection.move_component("R1", row, column, grid)

    assert position(collection.get_component("R1")) == (2, 2, 0)


def test_move_unknown_part_or_bad_grid(collection, grid):
    with pytest.raises(ComponentError, match="no part called 'R7'"):
        collection.move_component("R7", 2, 2, grid)

    collection.add_component("resistor", 2, 2, "1k", grid)

    with pytest.raises(ComponentError, match="Expected a ConnectionGrid"):
        collection.move_component("R1", 3, 3, (8, 8))


# ----- scene: snapping a drop -----------------------------------------------


@pytest.mark.parametrize("offset, expected", [
    (QPointF(0, 0), (1, 1)),
    (QPointF(29.9, -29.9), (1, 1)),
    (QPointF(30, 30), (2, 2)),
    (QPointF(-30.1, 0), (1, 0)),
    (QPointF(125, 61), (2, 3)),
])
def test_scene_position_snaps_to_the_nearest_point(offset, expected):
    assert scene_position_to_grid_point(point(1, 1) + offset) == expected


@pytest.fixture
def editor(qt_application):
    """
    A scene on an 8 x 8 grid shown in a real view, with signal recorders.
    """
    grid = ConnectionGrid(8, 8)
    collection = ComponentCollection()
    scene = ConnectionGridScene(grid)
    scene.set_component_collection(collection)
    view = ConnectionGridView(scene)
    view.resize(900, 800)
    view.show()
    view.resetTransform()
    view.centerOn(point(4, 4))
    QApplication.processEvents()

    moves = []
    refusals = []
    scene.component_moved.connect(moves.append)
    scene.component_move_refused.connect(
        lambda reference, reason: refusals.append((reference, reason))
    )

    class Editor:
        pass

    editor = Editor()
    editor.grid = grid
    editor.collection = collection
    editor.scene = scene
    editor.view = view
    editor.moves = moves
    editor.refusals = refusals

    def add(kind, row, column, value="", rotation=0):
        collection.add_component(kind, row, column, value, grid, rotation)
        scene.rebuild_component_items()

    editor.add = add
    yield editor
    view.close()
    view.deleteLater()


def item(editor, reference):
    return editor.scene.component_items_by_reference[reference]


def test_dragging_a_part_moves_it_to_the_nearest_point(editor):
    editor.add("resistor", 2, 2, "1k")
    body = between(point(2, 2), point(2, 3))

    # Dropped a little off R5 C4: snaps there.
    drag(editor.view, body, body + QPointF(2 * 60 + 10, 3 * 60 - 12))

    component = editor.collection.get_component("R1")
    assert (component.row_number, component.column_number) == (5, 4)
    assert item(editor, "R1").pos() == point(5, 4)
    assert editor.moves == ["R1"]
    assert editor.refusals == []


def test_the_part_follows_the_cursor_before_release(editor):
    editor.add("resistor", 2, 2, "1k")
    body = between(point(2, 2), point(2, 3))
    view = editor.view

    send_mouse(view, QEvent.MouseButtonPress, body)
    send_mouse(view, QEvent.MouseMove, body + QPointF(20, 5), Qt.NoButton)
    send_mouse(view, QEvent.MouseMove, body + QPointF(37, 23), Qt.NoButton)

    r1 = item(editor, "R1")
    # Not snapped yet: exactly the mouse offset, drawn above other parts.
    assert r1.pos() == point(2, 2) + QPointF(37, 23)
    assert r1.zValue() == DRAGGED_COMPONENT_Z_VALUE
    # The label travels with it.
    assert r1.label_item.pos() == r1.pos() + r1.label_offset
    # The model has not changed until the drop.
    assert editor.collection.get_component("R1").column_number == 2

    send_mouse(view, QEvent.MouseButtonRelease, body + QPointF(37, 23),
               Qt.LeftButton, Qt.NoButton)

    # 37 px right (over half a step) and 23 px down (under half): R2 C3.
    assert r1.pos() == point(2, 3)
    assert r1.zValue() == COMPONENT_Z_VALUE


def test_a_refused_drop_puts_the_part_back(editor):
    editor.add("resistor", 2, 2, "1k")
    editor.add("capacitor", 5, 5, "100n")
    body = between(point(5, 5), point(5, 6))

    # Onto R1's exact two points.
    drag(editor.view, body, body + (point(2, 2) - point(5, 5)))

    component = editor.collection.get_component("C1")
    assert (component.row_number, component.column_number) == (5, 5)
    assert item(editor, "C1").pos() == point(5, 5)
    assert item(editor, "C1").zValue() == COMPONENT_Z_VALUE
    assert editor.moves == []
    assert editor.refusals[0][0] == "C1"
    assert "R1 (Resistor) already connects exactly" in editor.refusals[0][1]


def test_dropping_off_the_grid_puts_the_part_back(editor):
    editor.add("resistor", 2, 2, "1k")
    body = between(point(2, 2), point(2, 3))

    drag(editor.view, body, body + QPointF(-3 * 60, 0))

    assert item(editor, "R1").pos() == point(2, 2)
    assert editor.refusals == [(
        "R1",
        (
            "R1 cannot be moved to row 2, column -1: that is outside the "
            "8 x 8 grid."
        ),
    )]


def test_a_short_wobble_is_a_click_not_a_drag(editor):
    editor.add("resistor", 2, 2, "1k")
    body = between(point(2, 2), point(2, 3))
    # Less than the drag distance in screen pixels (view scale is 1).
    wobble = QPointF(QApplication.startDragDistance() / 2 - 1, 0)

    drag(editor.view, body, body + wobble, steps=2)

    assert item(editor, "R1").pos() == point(2, 2)
    assert item(editor, "R1").isSelected()
    assert editor.moves == editor.refusals == []


def test_a_click_still_selects_the_part(editor):
    editor.add("resistor", 2, 2, "1k")

    click(editor.view, between(point(2, 2), point(2, 3)))

    assert item(editor, "R1").isSelected()


def test_dropping_on_its_own_point_changes_nothing(editor):
    editor.add("resistor", 2, 2, "1k")
    body = between(point(2, 2), point(2, 3))

    drag(editor.view, body, body + QPointF(20, 20))

    assert item(editor, "R1").pos() == point(2, 2)
    assert editor.moves == editor.refusals == []


def test_a_right_button_drag_does_not_move(editor):
    editor.add("resistor", 2, 2, "1k")
    body = between(point(2, 2), point(2, 3))

    drag(editor.view, body, body + QPointF(120, 120), button=Qt.RightButton)

    assert item(editor, "R1").pos() == point(2, 2)
    assert editor.moves == []


def test_moving_relayouts_the_labels(editor):
    editor.add("resistor", 2, 2, "1k")
    editor.add("resistor", 6, 6, "1k")
    r1 = item(editor, "R1")
    body = between(point(6, 6), point(6, 7))

    # R2 to just below R1: R1's label must stay clear of R2's body.
    drag(editor.view, body, body + (point(3, 2) - point(6, 6)))

    r2 = item(editor, "R2")
    assert r2.pos() == point(3, 2)
    label_rect = r1.label_item.mapRectToScene(r1.label_item.text_rect())
    assert not r2.mapToScene(r2.obstacle_path).boundingRect().intersects(
        label_rect
    )


def test_dragging_a_transistor_snaps_its_centre(editor):
    editor.add("npn", 4, 4, "2N3904")

    drag(editor.view, point(4, 4), point(4, 4) + QPointF(GRID_POINT_SPACING
                                                         * 2 + 25, -10))

    component = editor.collection.get_component("Q1")
    assert (component.row_number, component.column_number) == (4, 6)
    assert component.get_pin_identifiers() == [
        "NODE_R04_C05", "NODE_R03_C06", "NODE_R05_C06"
    ]


# ----- main window ----------------------------------------------------------


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


def place(window, row, column, kind, value):
    scene = window.connection_grid_scene
    scene.clearSelection()
    identifier = ConnectionGrid.build_connection_point_identifier(row, column)
    scene.connection_point_items_by_identifier[identifier].setSelected(True)
    window.place_component(kind, value)


def test_window_reports_a_move_and_updates_the_panel(window):
    place(window, 2, 2, "resistor", "1k")
    window.is_project_modified = False
    body = between(point(2, 2), point(2, 3))

    drag(window.connection_grid_view, body,
         body + (point(5, 4) - point(2, 2)))

    assert window.statusBar().currentMessage() == "Moved R1 to NODE_R05_C04."
    assert window.is_project_modified is True
    assert window.component_panel_widget.selected_component_label.text() == (
        "R1 (Resistor) at R5 C4, 0 deg"
    )
    assert window.recorded_errors == []


def test_window_reports_a_refused_move_without_a_dialog(window):
    place(window, 2, 2, "resistor", "1k")
    place(window, 5, 5, "capacitor", "100n")
    window.is_project_modified = False
    body = between(point(5, 5), point(5, 6))

    drag(window.connection_grid_view, body,
         body + (point(2, 2) - point(5, 5)))

    assert window.statusBar().currentMessage().startswith(
        "Part not moved: C1 cannot be moved to row 2, column 2: R1 "
        "(Resistor) already connects exactly"
    )
    assert window.is_project_modified is False
    assert window.recorded_errors == []
    component = window.component_collection.get_component("C1")
    assert (component.row_number, component.column_number) == (5, 5)


def test_rubber_band_selection_on_empty_space_still_works(window):
    place(window, 2, 2, "resistor", "1k")
    view = window.connection_grid_view
    window.connection_grid_scene.clearSelection()

    # From an empty spot above-left of R1 to below-right of its body.
    drag(view, point(1, 1) + QPointF(25, 25), point(3, 4) - QPointF(25, 25))

    assert window.connection_grid_scene.component_items_by_reference[
        "R1"
    ].isSelected()


def test_move_is_checked_against_the_grid_size_after_a_shrink(collection,
                                                              grid):
    collection.add_component("resistor", 2, 2, "1k", grid)
    collection.move_component("R1", 7, 7, grid)
    collection.move_component("R1", 2, 2, grid)

    grid.configure(6, 6)

    with pytest.raises(ComponentError, match="outside the 6 x 6 grid"):
        collection.move_component("R1", 7, 2, grid)

    with pytest.raises(ComponentError, match="pin would fall outside"):
        collection.move_component("R1", 2, 6, grid)

    assert position(collection.get_component("R1")) == (2, 2, 0)


def test_move_drawing_over_another_part_is_refused(collection, grid):
    # QC #11 rule through a move: R1 dragged so its pin lands on Q1's
    # centre (covered by Q1's body, not a pin).
    collection.add_component("npn", 4, 4, "2N3904", grid)
    collection.add_component("resistor", 7, 2, "1k", grid)

    with pytest.raises(ComponentError) as error_info:
        collection.move_component("R1", 4, 4, grid)

    assert str(error_info.value).startswith(
        "R1 cannot be moved to row 4, column 4: Q1 (NPN transistor) is "
        "already drawn there"
    )
    assert position(collection.get_component("R1")) == (7, 2, 0)


# ----- QC fixes: Esc, lost grab, drop hint, panel ---------------------------


def start_drag(editor, start, offset):
    send_mouse(editor.view, QEvent.MouseButtonPress, start)
    send_mouse(editor.view, QEvent.MouseMove, start + offset * 0.5,
               Qt.NoButton)
    send_mouse(editor.view, QEvent.MouseMove, start + offset, Qt.NoButton)


def test_escape_cancels_a_drag_and_the_release_does_nothing(editor):
    editor.add("resistor", 2, 2, "1k")
    body = between(point(2, 2), point(2, 3))
    r1 = item(editor, "R1")
    start_drag(editor, body, QPointF(130, 70))
    assert r1.is_dragging is True

    editor.view.setFocus()
    QTest.keyClick(editor.view.viewport(), Qt.Key_Escape)

    assert r1.pos() == point(2, 2)
    assert r1.zValue() == COMPONENT_Z_VALUE
    assert r1.is_dragging is False
    assert r1.is_drop_refused is False

    send_mouse(editor.view, QEvent.MouseButtonRelease,
               body + QPointF(130, 70), Qt.LeftButton, Qt.NoButton)

    component = editor.collection.get_component("R1")
    assert (component.row_number, component.column_number) == (2, 2)
    assert r1.pos() == point(2, 2)
    assert editor.moves == []
    assert editor.refusals == []


def test_escape_without_a_drag_does_nothing(editor):
    editor.add("resistor", 2, 2, "1k")
    click(editor.view, between(point(2, 2), point(2, 3)))
    selected = editor.scene.selectedItems()

    editor.view.setFocus()
    QTest.keyClick(editor.view.viewport(), Qt.Key_Escape)

    assert editor.scene.selectedItems() == selected
    assert item(editor, "R1").pos() == point(2, 2)


def test_losing_the_mouse_grab_puts_the_part_back(editor):
    editor.add("resistor", 2, 2, "1k")
    r1 = item(editor, "R1")
    start_drag(editor, between(point(2, 2), point(2, 3)), QPointF(130, 70))

    r1.ungrabMouse()

    assert r1.pos() == point(2, 2)
    assert r1.zValue() == COMPONENT_Z_VALUE
    assert r1.is_dragging is False
    component = editor.collection.get_component("R1")
    assert (component.row_number, component.column_number) == (2, 2)
    assert editor.moves == [] and editor.refusals == []


def test_the_part_turns_red_over_a_refused_spot(editor):
    editor.add("resistor", 2, 2, "1k")
    editor.add("capacitor", 5, 5, "100n")
    body = between(point(5, 5), point(5, 6))
    c1 = item(editor, "C1")

    # Over R1's exact two points: refused.
    start_drag(editor, body, point(2, 2) - point(5, 5))

    assert c1.is_drop_refused is True

    # On to a free spot: fine again.
    send_mouse(editor.view, QEvent.MouseMove,
               body + (point(7, 2) - point(5, 5)), Qt.NoButton)

    assert c1.is_drop_refused is False

    send_mouse(editor.view, QEvent.MouseMove,
               body + (point(2, 2) - point(5, 5)), Qt.NoButton)
    send_mouse(editor.view, QEvent.MouseButtonRelease,
               body + (point(2, 2) - point(5, 5)), Qt.LeftButton, Qt.NoButton)

    assert c1.is_drop_refused is False
    assert editor.refusals[0][0] == "C1"


def test_refused_colour_is_drawn(editor):
    editor.add("resistor", 2, 2, "1k")
    r1 = item(editor, "R1")
    r1.set_drop_refused(True)
    image = QImage(200, 120, QImage.Format_ARGB32)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    editor.scene.render(painter, QRectF(image.rect()),
                        QRectF(point(2, 2) - QPointF(40, 60),
                               QSizeF(200, 120)))
    painter.end()
    colours = {
        QColor(image.pixel(x, y)).name()
        for x in range(200) for y in range(120)
    }

    assert REFUSED_DROP_COLOR in colours


def test_check_move_does_not_move(collection, grid):
    collection.add_component("resistor", 2, 2, "1k", grid)
    collection.add_component("capacitor", 5, 5, "100n", grid)

    assert collection.check_move("C1", 7, 2, grid) is None
    assert collection.check_move("C1", 2, 2, grid).startswith(
        "C1 cannot be moved to row 2, column 2: R1 (Resistor) already "
        "connects exactly"
    )
    assert collection.check_move("C1", 2, 9, grid) == (
        "C1 cannot be moved to row 2, column 9: that is outside the 8 x 8 "
        "grid."
    )
    assert position(collection.get_component("C1")) == (5, 5, 0)

    with pytest.raises(ComponentError):
        collection.check_move("X9", 1, 1, grid)


def test_the_panel_follows_the_moved_part(window):
    place(window, 2, 2, "resistor", "1k")
    place(window, 5, 5, "capacitor", "100n")
    scene = window.connection_grid_scene
    # Both selected, the panel showing C1.
    scene.component_items_by_reference["R1"].setSelected(True)
    scene.component_items_by_reference["C1"].setSelected(True)
    window.handle_component_selection(
        window.component_collection.get_component("C1")
    )
    body = between(point(2, 2), point(2, 3))

    drag(window.connection_grid_view, body,
         body + (point(7, 2) - point(2, 2)))

    assert window.component_panel_widget.selected_component_label.text() == (
        "R1 (Resistor) at R7 C2, 0 deg"
    )
    assert window.selected_component_reference == "R1"
