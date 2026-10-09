"""
Tests for PR E: zoom and pan in gui.grid_editor.ConnectionGridView and the
main window's Zoom In / Zoom Out / Zoom to Fit actions. Headless through
the qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QKeySequence, QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QToolBar

from core.connection_grid import ConnectionGrid
from gui.grid_editor import (
    MAXIMUM_ZOOM,
    MINIMUM_ZOOM,
    ZOOM_STEP,
    ConnectionGridScene,
    ConnectionGridView,
    grid_point_to_scene_position,
)
from gui.main_window import MainWindow
from tests.view_mouse import drag, send_mouse


def point(row, column):
    return grid_point_to_scene_position(row, column)


def send_wheel(view, viewport_position, delta_y, modifiers=Qt.NoModifier):
    """Send one wheel event to the viewport at a viewport pixel."""
    position = QPointF(viewport_position)
    event = QWheelEvent(
        position,
        QPointF(view.viewport().mapToGlobal(viewport_position)),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.NoButton,
        modifiers,
        Qt.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view.viewport(), event)
    return event


class ZoomEditor:
    def __init__(self, rows=20, columns=20):
        self.scene = ConnectionGridScene(ConnectionGrid(rows, columns))
        self.view = ConnectionGridView(self.scene)
        self.view.resize(600, 500)
        self.view.show()
        QApplication.processEvents()
        self.zooms = []
        self.view.zoom_changed.connect(self.zooms.append)


@pytest.fixture
def editor(qt_application):
    zoom_editor = ZoomEditor()
    yield zoom_editor
    zoom_editor.view.close()
    zoom_editor.view.deleteLater()


def scene_at(view, viewport_position):
    return view.mapToScene(viewport_position)


# ----- Wheel zoom --------------------------------------------------------------


@pytest.mark.parametrize("modifiers", [Qt.NoModifier, Qt.ControlModifier])
def test_wheel_up_zooms_in_one_step(editor, modifiers):
    send_wheel(editor.view, QPoint(300, 250), 120, modifiers)

    assert editor.view.get_zoom() == pytest.approx(ZOOM_STEP)
    assert editor.zooms == [pytest.approx(ZOOM_STEP)]


@pytest.mark.parametrize("modifiers", [Qt.NoModifier, Qt.ControlModifier])
def test_wheel_down_zooms_out_one_step(editor, modifiers):
    send_wheel(editor.view, QPoint(300, 250), -120, modifiers)

    assert editor.view.get_zoom() == pytest.approx(1 / ZOOM_STEP)


def test_half_a_notch_zooms_half_a_step(editor):
    # Touchpads send smaller deltas; two halves make one step.
    send_wheel(editor.view, QPoint(300, 250), 60)
    assert editor.view.get_zoom() == pytest.approx(ZOOM_STEP ** 0.5)
    send_wheel(editor.view, QPoint(300, 250), 60)
    assert editor.view.get_zoom() == pytest.approx(ZOOM_STEP)


def test_wheel_event_is_accepted(editor):
    event = send_wheel(editor.view, QPoint(300, 250), 120)

    assert event.isAccepted()


@pytest.mark.parametrize("delta", [120, -120, 360, -240])
@pytest.mark.parametrize("cursor", [QPoint(150, 120), QPoint(420, 330)])
def test_wheel_zoom_keeps_the_point_under_the_cursor(editor, delta, cursor):
    editor.view.centerOn(point(10, 10))
    before = scene_at(editor.view, cursor)

    send_wheel(editor.view, cursor, delta)

    after = scene_at(editor.view, cursor)
    # Within a pixel at the new zoom (scrollbars move in whole pixels).
    tolerance = 1.5 / editor.view.get_zoom()
    assert after.x() == pytest.approx(before.x(), abs=tolerance)
    assert after.y() == pytest.approx(before.y(), abs=tolerance)


@pytest.mark.parametrize("cursor", [QPoint(80, 60), QPoint(520, 430)])
def test_wheel_zoom_from_the_fitted_view_keeps_the_cursor_point(
        qt_application, cursor):
    # A fitted 8 x 8 grid is smaller than the view; the scroll margin still
    # lets every notch keep the point under the cursor.
    small = ZoomEditor(8, 8)
    small.view.fit_grid_in_view()

    for delta in (120, 120, 120, -120, -120, -120, -120):
        before = scene_at(small.view, cursor)
        send_wheel(small.view, cursor, delta)
        after = scene_at(small.view, cursor)
        tolerance = 1.5 / small.view.get_zoom()
        assert after.x() == pytest.approx(before.x(), abs=tolerance)
        assert after.y() == pytest.approx(before.y(), abs=tolerance)

    small.view.close()
    small.view.deleteLater()


def test_view_can_scroll_a_viewport_past_the_scene(editor):
    for zoom in (0.5, 1.0, 3.0):
        editor.view.set_zoom(zoom)
        scene_rect = editor.scene.sceneRect()
        view_rect = editor.view.sceneRect()
        margin_x = editor.view.viewport().width() / zoom
        margin_y = editor.view.viewport().height() / zoom

        assert view_rect.left() == pytest.approx(scene_rect.left() - margin_x)
        assert view_rect.bottom() == pytest.approx(
            scene_rect.bottom() + margin_y
        )


def test_scroll_margin_follows_scene_growth(editor):
    editor.scene.setSceneRect(editor.scene.sceneRect().adjusted(0, 0, 500, 0))
    margin_x = editor.view.viewport().width() / editor.view.get_zoom()

    assert editor.view.sceneRect().right() == pytest.approx(
        editor.scene.sceneRect().right() + margin_x
    )


def test_shift_wheel_scrolls_instead_of_zooming(editor):
    editor.view.centerOn(point(10, 10))
    send_wheel(editor.view, QPoint(300, 250), -120, Qt.ShiftModifier)

    assert editor.view.get_zoom() == 1.0
    assert editor.zooms == []


def test_wheel_zoom_stops_at_the_maximum(editor):
    for _notch in range(30):
        send_wheel(editor.view, QPoint(300, 250), 120)

    assert editor.view.get_zoom() == pytest.approx(MAXIMUM_ZOOM)
    count = len(editor.zooms)
    send_wheel(editor.view, QPoint(300, 250), 120)
    assert len(editor.zooms) == count


def test_wheel_zoom_stops_at_the_minimum(editor):
    for _notch in range(30):
        send_wheel(editor.view, QPoint(300, 250), -120)

    assert editor.view.get_zoom() == pytest.approx(MINIMUM_ZOOM)


def test_zoom_limits():
    assert MINIMUM_ZOOM == 0.1
    assert MAXIMUM_ZOOM == 8.0
    assert ZOOM_STEP == 1.25
    assert ConnectionGridView.clamp_zoom(0.01) == MINIMUM_ZOOM
    assert ConnectionGridView.clamp_zoom(100) == MAXIMUM_ZOOM
    assert ConnectionGridView.clamp_zoom(2.5) == 2.5


# ----- Buttons and fit ---------------------------------------------------------


def test_zoom_in_and_out_keep_the_middle_of_the_view(editor):
    editor.view.centerOn(point(10, 10))
    middle = editor.view.viewport().rect().center()
    before = scene_at(editor.view, middle)

    assert editor.view.zoom_in() is True
    assert editor.view.get_zoom() == pytest.approx(ZOOM_STEP)
    assert editor.view.zoom_out() is True
    assert editor.view.get_zoom() == pytest.approx(1.0)

    after = scene_at(editor.view, middle)
    assert after.x() == pytest.approx(before.x(), abs=2)
    assert after.y() == pytest.approx(before.y(), abs=2)


def test_zoom_by_at_a_limit_changes_nothing(editor):
    editor.view.set_zoom(MAXIMUM_ZOOM)
    editor.zooms.clear()

    assert editor.view.zoom_in() is False
    assert editor.zooms == []
    assert not editor.view.can_zoom_in()
    assert editor.view.can_zoom_out()


def test_set_zoom_is_clamped(editor):
    editor.view.set_zoom(50)
    assert editor.view.get_zoom() == MAXIMUM_ZOOM
    editor.view.set_zoom(0)
    assert editor.view.get_zoom() == MINIMUM_ZOOM


def test_fit_shows_the_whole_grid(editor):
    editor.view.set_zoom(4.0)
    editor.view.fit_grid_in_view()

    visible = editor.view.mapToScene(
        editor.view.viewport().rect()
    ).boundingRect()
    assert visible.contains(editor.scene.get_grid_rect())
    assert MINIMUM_ZOOM <= editor.view.get_zoom() < 1.0


def test_fit_of_a_huge_grid_stops_at_the_minimum(qt_application):
    big = ZoomEditor(50, 50)
    big.view.resize(200, 150)
    QApplication.processEvents()

    big.view.fit_grid_in_view()

    assert big.view.get_zoom() == pytest.approx(MINIMUM_ZOOM)
    big.view.close()
    big.view.deleteLater()


def test_fit_of_a_tiny_grid_stops_at_the_maximum(qt_application):
    tiny = ZoomEditor(1, 1)
    tiny.view.resize(1600, 1200)
    QApplication.processEvents()

    tiny.view.fit_grid_in_view()

    assert tiny.view.get_zoom() <= MAXIMUM_ZOOM
    tiny.view.close()
    tiny.view.deleteLater()


# ----- Middle-button pan -------------------------------------------------------


def drag_pixels(view, start_pixel, offset, button, steps=4):
    """
    Drag by viewport pixels. Scene positions are worked out at send time,
    because the view scrolls under the mouse while it pans.
    """
    send_mouse(view, QEvent.MouseButtonPress, view.mapToScene(start_pixel),
               button, button)

    for step in range(1, steps + 1):
        pixel = start_pixel + offset * step / steps
        send_mouse(view, QEvent.MouseMove, view.mapToScene(pixel),
                   Qt.NoButton, button)

    send_mouse(view, QEvent.MouseButtonRelease,
               view.mapToScene(start_pixel + offset), button, Qt.NoButton)


def middle_drag_pixels(view, start_pixel, offset, steps=4):
    """Middle-drag by viewport pixels."""
    drag_pixels(view, start_pixel, offset, Qt.MiddleButton, steps)


def test_middle_drag_pans_the_view(editor):
    editor.view.centerOn(point(10, 10))
    horizontal = editor.view.horizontalScrollBar().value()
    vertical = editor.view.verticalScrollBar().value()
    start_pixel = QPoint(300, 250)
    grabbed = editor.view.mapToScene(start_pixel)

    middle_drag_pixels(editor.view, start_pixel, QPoint(40, 32))

    assert editor.view.horizontalScrollBar().value() == horizontal - 40
    assert editor.view.verticalScrollBar().value() == vertical - 32
    # The grabbed scene point followed the mouse.
    assert editor.view.mapToScene(start_pixel + QPoint(40, 32)) == grabbed
    assert editor.view.get_zoom() == 1.0


def test_middle_drag_restores_the_cursor(editor):
    editor.view.viewport().setCursor(Qt.CrossCursor)
    start = point(10, 10)
    send_mouse(editor.view, QEvent.MouseButtonPress, start,
               Qt.MiddleButton, Qt.MiddleButton)

    assert editor.view.viewport().cursor().shape() == Qt.ClosedHandCursor

    send_mouse(editor.view, QEvent.MouseButtonRelease, start,
               Qt.MiddleButton, Qt.NoButton)

    assert editor.view.viewport().cursor().shape() == Qt.CrossCursor
    assert editor.view.pan_start_position is None


def test_middle_drag_selects_nothing_and_draws_no_wire(editor):
    from core.wires import WireCollection

    wires = WireCollection()
    editor.scene.set_wire_collection(wires)
    editor.scene.set_wire_mode(True)
    editor.view.centerOn(point(10, 10))

    middle_drag_pixels(editor.view, editor.view.mapFromScene(point(10, 10)),
                       QPoint(60, 0))

    assert wires.get_wires() == []
    assert editor.scene.selectedItems() == []
    assert editor.scene.wire_preview_item is None


def test_left_drag_pans_the_board(editor):
    editor.view.centerOn(point(10, 10))
    editor.view.set_zoom(ZOOM_STEP * ZOOM_STEP)
    editor.view.viewport().setCursor(Qt.ArrowCursor)
    horizontal = editor.view.horizontalScrollBar().value()
    vertical = editor.view.verticalScrollBar().value()
    start_pixel = QPoint(300, 250)
    grabbed = editor.view.mapToScene(start_pixel)

    send_mouse(editor.view, QEvent.MouseButtonPress,
               editor.view.mapToScene(start_pixel))
    assert editor.view.viewport().cursor().shape() == Qt.ArrowCursor

    send_mouse(editor.view, QEvent.MouseMove,
               editor.view.mapToScene(start_pixel + QPoint(40, 32)),
               Qt.NoButton, Qt.LeftButton)

    assert editor.view.viewport().cursor().shape() == Qt.ClosedHandCursor
    assert editor.view.mapToScene(start_pixel + QPoint(40, 32)) == grabbed

    send_mouse(editor.view, QEvent.MouseButtonRelease,
               editor.view.mapToScene(start_pixel + QPoint(40, 32)),
               Qt.LeftButton, Qt.NoButton)

    assert editor.view.horizontalScrollBar().value() == horizontal - 40
    assert editor.view.verticalScrollBar().value() == vertical - 32
    assert editor.view.get_zoom() == pytest.approx(ZOOM_STEP * ZOOM_STEP)
    assert editor.scene.selectedItems() == []
    assert editor.view.pan_start_position is None
    assert editor.view.viewport().cursor().shape() == Qt.ArrowCursor


def test_a_short_left_drag_is_a_click(editor):
    editor.view.centerOn(point(10, 10))
    horizontal = editor.view.horizontalScrollBar().value()
    start_pixel = editor.view.mapFromScene(point(10, 10))

    drag_pixels(editor.view, start_pixel, QPoint(3, 2), Qt.LeftButton)

    assert editor.view.horizontalScrollBar().value() == horizontal
    assert editor.scene.connection_point_items_by_identifier[
        "NODE_R10_C10"
    ].isSelected()


def test_shift_drag_still_rubber_band_selects(editor):
    editor.view.centerOn(point(10, 10))
    horizontal = editor.view.horizontalScrollBar().value()

    drag(editor.view, point(10, 10) + QPointF(-10, -10),
         point(10, 10) + QPointF(10, 10), modifiers=Qt.ShiftModifier)

    assert editor.view.horizontalScrollBar().value() == horizontal
    assert editor.scene.connection_point_items_by_identifier[
        "NODE_R10_C10"
    ].isSelected()


# ----- Main window -------------------------------------------------------------


@pytest.fixture
def window(qt_application, monkeypatch):
    main_window = MainWindow()
    monkeypatch.setattr(main_window, "show_error_message",
                        lambda *details: None)
    main_window.resize(1200, 800)
    main_window.show()
    QApplication.processEvents()
    yield main_window
    main_window.is_project_modified = False
    main_window.close()
    main_window.deleteLater()


def test_view_menu_has_the_zoom_actions(window):
    view_menu = next(
        menu_action.menu() for menu_action in window.menuBar().actions()
        if menu_action.text() == "&View"
    )

    assert [action.text() for action in view_menu.actions()] == [
        "Zoom In", "Zoom Out", "Zoom to Fit"
    ]


def test_toolbar_has_the_zoom_actions(window):
    toolbar_actions = window.findChild(QToolBar).actions()

    for action in (window.zoom_in_action, window.zoom_out_action,
                   window.fit_grid_action):
        assert action in toolbar_actions


def test_zoom_shortcuts(window):
    assert window.zoom_in_action.shortcuts() == [
        QKeySequence(QKeySequence.ZoomIn), QKeySequence("Ctrl+=")
    ]
    assert QKeySequence("Ctrl++") in window.zoom_in_action.shortcuts()
    assert window.zoom_out_action.shortcut() == QKeySequence("Ctrl+-")
    assert window.fit_grid_action.shortcut() == QKeySequence("Ctrl+0")


def test_zoom_actions_change_the_view(window):
    view = window.connection_grid_view
    view.set_zoom(1.0)

    window.zoom_in_action.trigger()
    assert view.get_zoom() == pytest.approx(ZOOM_STEP)
    window.zoom_out_action.trigger()
    window.zoom_out_action.trigger()
    assert view.get_zoom() == pytest.approx(1 / ZOOM_STEP)

    window.fit_grid_action.trigger()
    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    assert visible.contains(window.connection_grid_scene.get_grid_rect())


def test_ctrl_plus_and_ctrl_minus_keys_zoom(window):
    view = window.connection_grid_view
    view.set_zoom(1.0)
    window.activateWindow()
    view.setFocus()
    QApplication.processEvents()

    QTest.keyClick(view, Qt.Key_Equal, Qt.ControlModifier)
    assert view.get_zoom() == pytest.approx(ZOOM_STEP)
    QTest.keyClick(view, Qt.Key_Minus, Qt.ControlModifier)
    assert view.get_zoom() == pytest.approx(1.0)
    QTest.keyClick(view, Qt.Key_0, Qt.ControlModifier)
    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    assert visible.contains(window.connection_grid_scene.get_grid_rect())


def test_zoom_label_and_limits_in_the_window(window):
    view = window.connection_grid_view

    view.set_zoom(1.0)
    assert window.zoom_label.text() == "Zoom 100%"
    assert window.zoom_in_action.isEnabled()

    view.set_zoom(MAXIMUM_ZOOM)
    assert window.zoom_label.text() == "Zoom 800%"
    assert not window.zoom_in_action.isEnabled()
    assert window.zoom_out_action.isEnabled()

    view.set_zoom(MINIMUM_ZOOM)
    assert window.zoom_label.text() == "Zoom 10%"
    assert window.zoom_in_action.isEnabled()
    assert not window.zoom_out_action.isEnabled()


def test_window_wheel_zoom_updates_the_label(window):
    view = window.connection_grid_view
    view.set_zoom(1.0)

    send_wheel(view, view.viewport().rect().center(), 120)

    assert window.zoom_label.text() == "Zoom 125%"


def test_wheel_keeps_the_point_near_the_scene_edge(qt_application):
    # QC #15: with only half a viewport of margin, zooming out over the
    # grid's top-left while it sits at the bottom-right of the view hit
    # the scroll limit and the point jumped (R2 C2 18 px off by notch 4).
    scene = ConnectionGridScene(ConnectionGrid(8, 8))
    view = ConnectionGridView(scene)
    view.resize(1000, 800)
    view.show()
    QApplication.processEvents()
    viewport = view.viewport()
    view.resize(1000 - (viewport.width() - 900),
                800 - (viewport.height() - 700))
    QApplication.processEvents()
    assert (viewport.width(), viewport.height()) == (900, 700)
    view.fit_grid_in_view()
    QApplication.processEvents()

    cursor = QPoint(540, 440)
    view.keep_scene_point_at(point(2, 2), QPointF(cursor))
    assert view.mapFromScene(point(2, 2)) == cursor

    for _notch in range(4):
        send_wheel(view, cursor, -120)
        where = view.mapFromScene(point(2, 2))

        assert abs(where.x() - cursor.x()) <= 1
        assert abs(where.y() - cursor.y()) <= 1

    view.close()
    view.deleteLater()
