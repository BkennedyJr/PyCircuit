"""
Tests for placing a part through a "ghost" (Billie, Oct 9 12:07-12:08).

Place shows the part semi-transparent at the selected point, not yet in
the collection. Arrow keys and W/A/S/D turn it, with green or red for
allowed or refused; Enter or a right-click places it (a refusal keeps it
waiting); Esc cancels; clicking another grid point moves it. Typing in
the panel's boxes never turns it, and W does not toggle Wire Mode while
a part waits.

Error dialogs are replaced with a recorder, so no modal box opens.
"""

import pytest
from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from gui.component_item import (
    BACKGROUND_COLOR,
    PENDING_ALLOWED_COLOR,
    PENDING_OPACITY,
    PENDING_Z_VALUE,
)
from gui.main_window import MainWindow
from gui.wire_item import WIRE_COLOR
from tests.view_mouse import send_mouse


@pytest.fixture
def window(qt_application, monkeypatch):
    main_window = MainWindow()
    main_window.recorded_errors = []

    def record_error(title, reason, resolution):
        main_window.recorded_errors.append((title, reason, resolution))

    monkeypatch.setattr(main_window, "show_error_message", record_error)
    yield main_window
    main_window.is_project_modified = False
    main_window.close()
    main_window.deleteLater()


def scene(window):
    return window.connection_grid_scene


def view(window):
    return window.connection_grid_view


def panel(window):
    return window.component_panel_widget


def select_point(window, identifier):
    scene(window).clearSelection()
    scene(window).connection_point_items_by_identifier[identifier].setSelected(
        True
    )


def references(window):
    return [c.reference for c in window.component_collection.get_components()]


def press(window, key):
    QTest.keyClick(view(window), key)


def show_with_grid_focus(window):
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    view(window).setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()


def start_ghost(window, identifier, kind, value_text=""):
    select_point(window, identifier)
    combo = panel(window).kind_combo_box
    combo.setCurrentIndex(combo.findData(kind))
    panel(window).value_line_edit.setText(value_text)
    panel(window).place_button.click()


def ghost(window):
    return scene(window).pending_item


def billie_layout(window):
    """R1 on R7 C3-C4, R7 C3 selected, a polarized cap waiting there."""
    select_point(window, "NODE_R07_C03")
    window.place_component("resistor", "1k")
    start_ghost(window, "NODE_R07_C03", "capacitor_polarized")


# ----- Place shows a ghost -----

def test_place_shows_a_ghost_and_stores_nothing(window):
    start_ghost(window, "NODE_R04_C04", "resistor", "4k7")
    item = ghost(window)

    assert references(window) == []
    assert item is not None and item.scene() is scene(window)
    assert item not in scene(window).component_items_by_reference.values()
    assert item.component.reference == "R1"
    assert item.component.value_text == "4k7"
    assert item.pos() == scene(window).connection_point_items_by_identifier[
        "NODE_R04_C04"
    ].pos()
    assert item.opacity() == PENDING_OPACITY
    assert item.zValue() == PENDING_Z_VALUE
    assert item.pending_allowed is True
    assert item.label_item.isVisible() is False
    assert window.is_project_modified is False
    assert window.statusBar().currentMessage() == (
        "Placing R1 (Resistor) at NODE_R04_C04, pointing Right: Enter or "
        "right-click places it. Arrows or W/A/S/D turn it; Esc cancels."
    )


def test_ghost_takes_no_clicks_or_selection(window):
    start_ghost(window, "NODE_R04_C04", "resistor")
    item = ghost(window)

    assert item.acceptedMouseButtons() == Qt.NoButton
    assert not item.flags() & item.ItemIsSelectable


def test_place_moves_focus_to_the_grid(window):
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    panel(window).place_button.setFocus(Qt.OtherFocusReason)
    start_ghost(window, "NODE_R04_C04", "resistor")
    QApplication.processEvents()

    assert QApplication.focusWidget() is view(window)


def test_place_with_a_bad_value_shows_no_ghost(window):
    start_ghost(window, "NODE_R04_C04", "resistor", "abc")

    assert ghost(window) is None
    assert scene(window).pending_placement is None
    assert [title for title, _reason, _fix in window.recorded_errors] == [
        "Part Not Placed"
    ]


def test_place_without_a_point_shows_the_error(window):
    scene(window).clearSelection()
    panel(window).place_button.click()

    assert ghost(window) is None
    assert window.recorded_errors[0][0] == "No Connection Point Selected"


# ----- turning it -----

@pytest.mark.parametrize("key, direction, rotation", [
    (Qt.Key_Right, "right", 0), (Qt.Key_Down, "down", 90),
    (Qt.Key_Left, "left", 180), (Qt.Key_Up, "up", 270),
    (Qt.Key_D, "right", 0), (Qt.Key_S, "down", 90),
    (Qt.Key_A, "left", 180), (Qt.Key_W, "up", 270),
])
def test_arrows_and_wasd_turn_the_ghost(window, key, direction, rotation):
    start_ghost(window, "NODE_R04_C04", "capacitor_polarized")
    press(window, Qt.Key_Up if key != Qt.Key_Up else Qt.Key_Down)
    press(window, key)

    assert scene(window).pending_placement.direction == direction
    assert ghost(window).component.rotation == rotation
    assert references(window) == []


def test_down_on_a_source_keeps_it_upright(window):
    start_ghost(window, "NODE_R04_C04", "dc_source", "9")

    assert scene(window).pending_placement.direction == "down"
    assert ghost(window).component.rotation == 0
    press(window, Qt.Key_Right)

    assert ghost(window).component.rotation == 270
    assert ghost(window).component.get_pin_identifiers() == [
        "NODE_R04_C04", "NODE_R04_C05"
    ]


def test_transistor_turns_with_the_arrows(window):
    start_ghost(window, "NODE_R04_C04", "npn")
    press(window, Qt.Key_Down)

    assert ghost(window).component.rotation == 90


def test_w_turns_the_ghost_and_does_not_toggle_wire_mode(window):
    show_with_grid_focus(window)
    start_ghost(window, "NODE_R04_C04", "resistor")
    QApplication.processEvents()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_W)

    assert window.wire_mode_action.isChecked() is False
    assert scene(window).pending_placement.direction == "up"


def test_w_toggles_wire_mode_again_once_placed(window):
    show_with_grid_focus(window)
    start_ghost(window, "NODE_R04_C04", "resistor")
    QApplication.processEvents()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_Return)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_W)

    assert references(window) == ["R1"]
    assert window.wire_mode_action.isChecked() is True


def test_shift_w_is_not_a_placing_key(window):
    start_ghost(window, "NODE_R04_C04", "resistor")
    QTest.keyClick(view(window), Qt.Key_W, Qt.ShiftModifier)

    assert scene(window).pending_placement.direction == "right"


def test_typing_in_the_panel_boxes_does_not_turn_the_ghost(window):
    show_with_grid_focus(window)
    start_ghost(window, "NODE_R04_C04", "ac_source", "1")
    line_edit = panel(window).value_line_edit
    line_edit.clear()
    line_edit.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    QTest.keyClicks(line_edit, "wasd")
    QTest.keyClick(line_edit, Qt.Key_Left)
    QTest.keyClick(line_edit, Qt.Key_Up)
    frequency_edit = panel(window).parameter_line_edits["frequency"]
    frequency_edit.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    QTest.keyClicks(frequency_edit, "dw")

    assert line_edit.text() == "wasd"
    assert frequency_edit.text().endswith("dw")
    assert scene(window).pending_placement.direction == "down"
    assert window.wire_mode_action.isChecked() is False


# ----- live feedback and committing -----

def test_billies_cap_shows_red_and_names_the_free_directions(window):
    billie_layout(window)

    assert ghost(window).pending_allowed is False
    assert window.statusBar().currentMessage() == (
        "Placing C1 (Capacitor (polarized)) at NODE_R07_C03, pointing "
        "Right: it can't go here. Free directions at NODE_R07_C03: Down, "
        "Left, Up. Arrows or W/A/S/D turn it; Esc cancels."
    )


def test_enter_on_a_clash_is_refused_and_the_ghost_stays(window):
    billie_layout(window)
    press(window, Qt.Key_Return)

    assert references(window) == ["R1"]
    assert scene(window).pending_placement is not None
    assert ghost(window).pending_allowed is False
    assert window.recorded_errors == [(
        "Part Not Placed",
        (
            "R1 (Resistor) already connects exactly these grid points: "
            "NODE_R07_C03, NODE_R07_C04. Pick other grid points or another "
            "rotation, or select R1 to edit it. Free directions at "
            "NODE_R07_C03: Down, Left, Up."
        ),
        (
            "Turn it with the arrow keys or W/A/S/D, click another grid "
            "point, or press Esc to cancel."
        ),
    )]


def test_billies_cap_clicked_to_r7_c4_and_turned_down_is_placed(window):
    billie_layout(window)
    select_point(window, "NODE_R07_C04")

    assert scene(window).pending_placement.identifier == "NODE_R07_C04"
    assert ghost(window).pos() == scene(
        window
    ).connection_point_items_by_identifier["NODE_R07_C04"].pos()
    press(window, Qt.Key_S)

    assert ghost(window).pending_allowed is True
    press(window, Qt.Key_Enter)

    capacitor = window.component_collection.get_component("C1")
    assert capacitor.get_pin_identifiers() == [
        "NODE_R07_C04", "NODE_R08_C04"
    ]
    assert scene(window).pending_placement is None
    assert ghost(window) is None
    assert window.selected_component_reference == "C1"
    assert window.is_project_modified is True
    assert window.statusBar().currentMessage() == (
        f"Placed {capacitor.label_text()} at NODE_R07_C04."
    )
    assert capacitor.label_text().startswith("C1 ")


def test_turning_onto_a_free_direction_marks_it_allowed(window):
    billie_layout(window)
    press(window, Qt.Key_Left)

    assert ghost(window).pending_allowed is True
    press(window, Qt.Key_Right)

    assert ghost(window).pending_allowed is False


def test_right_click_places_it(window):
    start_ghost(window, "NODE_R04_C04", "resistor", "1k")
    press(window, Qt.Key_Down)
    window.resize(1000, 800)
    window.show()
    QTest.qWaitForWindowExposed(window)
    position = view(window).mapFromScene(
        scene(window).connection_point_items_by_identifier[
            "NODE_R02_C02"
        ].pos()
    )
    QTest.mouseClick(view(window).viewport(), Qt.RightButton, Qt.NoModifier,
                     position)

    component = window.component_collection.get_component("R1")
    assert (component.row_number, component.column_number) == (4, 4)
    assert component.rotation == 90
    assert ghost(window) is None


def test_esc_cancels(window):
    start_ghost(window, "NODE_R04_C04", "resistor")
    press(window, Qt.Key_Escape)

    assert scene(window).pending_placement is None
    assert ghost(window) is None
    assert references(window) == []
    assert window.statusBar().currentMessage() == "Placing cancelled."
    press(window, Qt.Key_Return)

    assert references(window) == []


def test_place_again_replaces_the_ghost_and_keeps_its_direction(window):
    start_ghost(window, "NODE_R04_C04", "resistor", "1k")
    press(window, Qt.Key_Down)
    first_item = ghost(window)
    panel(window).value_line_edit.setText("2k2")
    panel(window).place_button.click()

    assert first_item.scene() is None
    assert ghost(window).component.value_text == "2k2"
    assert scene(window).pending_placement.direction == "down"


def test_deleting_the_blocking_part_marks_the_ghost_allowed(window):
    billie_layout(window)
    window.component_collection.remove_component("R1")
    scene(window).rebuild_component_items()

    assert ghost(window).pending_allowed is True


def test_wire_mode_cancels_the_ghost_and_place_leaves_wire_mode(window):
    start_ghost(window, "NODE_R04_C04", "resistor")
    window.set_wire_mode(True)

    assert scene(window).pending_placement is None
    assert ghost(window) is None
    start_ghost(window, "NODE_R04_C04", "resistor")

    assert window.wire_mode_action.isChecked() is False
    assert scene(window).pending_placement is not None


def test_a_new_grid_drops_the_ghost(window):
    start_ghost(window, "NODE_R04_C04", "resistor")
    window.apply_grid_configuration(6, 6)

    assert scene(window).pending_placement is None
    assert ghost(window) is None


def test_ghost_is_drawn_cyan_or_red(qt_application, window):
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QColor, QImage, QPainter

    billie_layout(window)
    item = ghost(window)

    def body_colors():
        rect = item.sceneBoundingRect()
        image = QImage(int(rect.width()), int(rect.height()),
                       QImage.Format_ARGB32)
        image.fill(QColor("#000000"))
        painter = QPainter(image)
        scene(window).render(painter, QRectF(image.rect()), rect)
        painter.end()

        return {
            QColor(image.pixel(x, y)).name()
            for x in range(image.width())
            for y in range(image.height())
        }

    def has_reddish(colors):
        return any(
            QColor(name).red() > QColor(name).green() + 60 and
            QColor(name).red() > QColor(name).blue() + 60
            for name in colors
        )

    def has_cyanish(colors):
        return any(
            # Cyan: green and blue both well above red and close to each
            # other (the blue grid dots have blue far above green).
            QColor(name).green() > QColor(name).red() + 60 and
            abs(QColor(name).green() - QColor(name).blue()) < 30
            for name in colors
        )

    colors = body_colors()

    assert has_reddish(colors) and not has_cyanish(colors)
    press(window, Qt.Key_Down)
    item = ghost(window)
    colors = body_colors()

    assert has_cyanish(colors) and not has_reddish(colors)


# ----- QC #20 fixes -----

def point_position(window, identifier):
    return scene(window).connection_point_items_by_identifier[identifier].pos()


def start_ghost_and_hold_a_part(window):
    """R1 on R2 C2-C3, a resistor ghost at R6 C2, R1 held mid-drag."""
    window.resize(1000, 800)
    window.show()
    QTest.qWaitForWindowExposed(window)
    select_point(window, "NODE_R02_C02")
    window.place_component("resistor", "1k")
    start_ghost(window, "NODE_R06_C02", "resistor", "2k2")
    body = QPointF(point_position(window, "NODE_R02_C02")) + QPointF(30, 0)
    drop = QPointF(point_position(window, "NODE_R04_C02")) + QPointF(30, 0)
    send_mouse(view(window), QEvent.MouseButtonPress, body)

    for step in range(1, 6):
        send_mouse(view(window), QEvent.MouseMove,
                   body + (drop - body) * (step / 5), Qt.NoButton)

    assert item_for(window, "R1").is_dragging is True

    return drop


def item_for(window, reference):
    return scene(window).component_items_by_reference[reference]


def release_at(window, drop):
    send_mouse(view(window), QEvent.MouseButtonRelease, drop, Qt.LeftButton,
               Qt.NoButton)


def test_enter_during_a_part_drag_does_not_place_or_cancel_the_drag(window):
    drop = start_ghost_and_hold_a_part(window)
    press(window, Qt.Key_Return)

    assert references(window) == ["R1"]
    assert scene(window).pending_placement is not None
    assert item_for(window, "R1").is_dragging is True
    release_at(window, drop)

    resistor = window.component_collection.get_component("R1")
    assert (resistor.row_number, resistor.column_number) == (4, 2)
    assert scene(window).pending_placement is not None
    assert references(window) == ["R1"]


def test_right_click_during_a_part_drag_does_not_place_or_cancel_the_drag(
        window):
    drop = start_ghost_and_hold_a_part(window)
    send_mouse(view(window), QEvent.MouseButtonPress, drop, Qt.RightButton,
               Qt.LeftButton | Qt.RightButton)
    send_mouse(view(window), QEvent.MouseButtonRelease, drop, Qt.RightButton,
               Qt.LeftButton)

    assert references(window) == ["R1"]
    assert item_for(window, "R1").is_dragging is True
    release_at(window, drop)

    resistor = window.component_collection.get_component("R1")
    assert (resistor.row_number, resistor.column_number) == (4, 2)
    assert scene(window).pending_placement is not None
    assert references(window) == ["R1"]


def test_direction_keys_still_turn_the_ghost_during_a_drag(window):
    drop = start_ghost_and_hold_a_part(window)
    press(window, Qt.Key_Down)

    assert scene(window).pending_placement.direction == "down"
    release_at(window, drop)


def test_status_shows_the_placing_text_after_deleting_the_blocker(window):
    billie_layout(window)
    blocker = item_for(window, "R1")
    scene(window).clearSelection()
    blocker.setSelected(True)
    window.delete_selection()

    message = window.statusBar().currentMessage()
    assert message.startswith("Deleted R1.")
    assert "Placing C1 (Capacitor (polarized)) at NODE_R07_C03" in message
    assert "Enter or right-click places it" in message


def test_status_after_an_edit_without_a_ghost_is_unchanged(window):
    select_point(window, "NODE_R04_C04")
    window.place_component("resistor", "1k")

    assert window.statusBar().currentMessage() == (
        "Placed R1 1k at NODE_R04_C04."
    )


def test_fits_color_is_distinct_from_the_wire_color():
    fits = QColor(PENDING_ALLOWED_COLOR)
    wire = QColor(WIRE_COLOR)

    assert PENDING_ALLOWED_COLOR == "#4dd0e1"
    assert abs(fits.hue() - wire.hue()) >= 40


def test_led_ghost_is_fully_tinted(window):
    start_ghost(window, "NODE_R04_C04", "led")
    ghost_item = ghost(window)
    assert ghost_item.pending_allowed is True

    # The LED body centre is (0.5, 0) steps from the anchor; this point is
    # inside the triangle, just below the grid line through the anchor.
    point = ghost_item.pos() + QPointF(0.42 * 60, 6)
    rect = QRectF(point.x() - 1, point.y() - 1, 3, 3)
    image = QImage(3, 3, QImage.Format_ARGB32)
    image.fill(QColor(BACKGROUND_COLOR))
    painter = QPainter(image)
    scene(window).render(painter, QRectF(image.rect()), rect)
    painter.end()
    pixel = QColor(image.pixel(1, 1))

    # Tinted cyan (green and blue well above red, close to each other),
    # not the grey-white SYMBOL_COLOR fill of a dark LED.
    assert pixel.green() > pixel.red() + 50, pixel.name()
    assert pixel.blue() > pixel.red() + 50, pixel.name()
    assert abs(pixel.green() - pixel.blue()) < 30, pixel.name()
