"""
Tests for the LED color setting and the lit-LED drawing hook (Billie's
decision, Oct 9 11:45).

The color is a panel choice stored in parameter_texts; SPICE only sees it
through the default model (LED_RED, LED_GREEN, ...). ComponentItem.set_lit
fills a lit LED with its color plus a glow; the trigger (forward current
above about 1 mA) comes after the ngspice runner. Qt tests use the
qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QComboBox, QGraphicsScene

from core.components import (
    COMPONENT_DEFINITIONS,
    LED_COLORS,
    LED_MODEL_BY_COLOR,
    Component,
    ComponentCollection,
    follow_choice_model,
    get_default_parameter_texts,
)
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from gui.component_item import LED_LIT_COLORS, ComponentItem
from gui.component_panel_widget import ComponentPanelWidget
from gui.main_window import MainWindow

SPACING = 60


# ----- the setting -----

def test_colors_and_models():
    assert LED_COLORS == ("red", "green", "blue", "yellow", "white", "orange")
    assert LED_MODEL_BY_COLOR == {
        "red": "LED_RED",
        "green": "LED_GREEN",
        "blue": "LED_BLUE",
        "yellow": "LED_YELLOW",
        "white": "LED_WHITE",
        "orange": "LED_ORANGE",
    }


def test_color_parameter_definition():
    (parameter,) = [
        parameter
        for parameter in COMPONENT_DEFINITIONS["led"]["parameters"]
        if parameter["name"] == "color"
    ]

    assert parameter["value_kind"] == "choice"
    assert tuple(parameter["choices"]) == LED_COLORS
    assert parameter["default_value_text"] == "red"
    assert parameter["shown_in_panel"] is True
    assert parameter["shown_in_label"] is False


def test_default_is_red():
    led = Component("led", "D1", "LED_RED", 4, 4)

    assert led.parameter_texts == {"color": "red"}
    assert get_default_parameter_texts("led") == {"color": "red"}


@pytest.mark.parametrize("color", LED_COLORS)
def test_every_color_is_accepted(color):
    led = Component("led", "D1", "LED_RED", 4, 4, 0, {"color": color})

    assert led.parameter_texts["color"] == color


@pytest.mark.parametrize("typed, stored", [
    ("Green", "green"), ("BLUE", "blue"), ("  white ", "white"),
])
def test_color_case_and_spaces_are_ignored(typed, stored):
    led = Component("led", "D1", "LED_RED", 4, 4, 0, {"color": typed})

    assert led.parameter_texts["color"] == stored


def test_unknown_color_is_refused():
    with pytest.raises(ComponentError) as error:
        Component("led", "D1", "LED_RED", 4, 4, 0, {"color": "pink"})

    assert str(error.value) == (
        "LED color must be one of red, green, blue, yellow, white, orange, "
        "not 'pink'."
    )


def test_empty_color_on_edit_is_refused_and_nothing_changes():
    led = Component("led", "D1", "LED_RED", 4, 4, 0, {"color": "green"})

    with pytest.raises(ComponentError) as error:
        led.set_values("LED_GREEN", {"color": ""})

    assert str(error.value).startswith("LED color is empty. Pick one of:")
    assert (led.value_text, led.parameter_texts) == (
        "LED_GREEN", {"color": "green"}
    )


def test_label_does_not_show_the_color():
    led = Component("led", "D1", "LED_RED", 4, 4, 0, {"color": "blue"})

    assert led.label_text() == "D1 LED_BLUE"


def test_other_kinds_have_no_color():
    with pytest.raises(ComponentError):
        Component("diode", "D1", "1N4148", 4, 4, 0, {"color": "red"})


# ----- the model follows the color -----

def test_new_led_takes_the_colors_model():
    led = Component("led", "D1", "LED_RED", 4, 4, 0, {"color": "green"})

    assert led.value_text == "LED_GREEN"


def test_editing_the_color_changes_the_default_model():
    led = Component("led", "D1", "LED_RED", 4, 4)
    led.set_values("LED_RED", {"color": "yellow"})

    assert (led.value_text, led.parameter_texts["color"]) == (
        "LED_YELLOW", "yellow"
    )


def test_default_model_match_ignores_case():
    led = Component("led", "D1", "led_red", 4, 4)
    led.set_values("led_red", {"color": "orange"})

    assert led.value_text == "LED_ORANGE"


def test_a_custom_model_is_kept():
    led = Component("led", "D1", "MY_LED", 4, 4)
    led.set_values("MY_LED", {"color": "blue"})

    assert (led.value_text, led.parameter_texts["color"]) == (
        "MY_LED", "blue"
    )


def test_a_new_model_with_the_same_color_is_kept():
    led = Component("led", "D1", "LED_RED", 4, 4, 0, {"color": "green"})
    led.set_values("LED_RED", {"color": "green"})

    assert led.value_text == "LED_RED"


def test_follow_choice_model_ignores_kinds_without_it():
    assert follow_choice_model(
        "resistor", "1k", {}, {}
    ) == "1k"


def test_collection_edit_follows_the_color():
    grid = ConnectionGrid(8, 8)
    collection = ComponentCollection()
    led = collection.add_component("led", 2, 2, "", grid)
    collection.set_component_value("D1", "LED_RED", {"color": "white"})

    assert (led.value_text, led.parameter_texts) == (
        "LED_WHITE", {"color": "white"}
    )


# ----- the panel -----

@pytest.fixture
def panel(qt_application):
    widget = ComponentPanelWidget()
    yield widget
    widget.deleteLater()


def choose_kind(panel, kind):
    panel.kind_combo_box.setCurrentIndex(panel.kind_combo_box.findData(kind))


def test_new_part_color_dropdown(panel):
    choose_kind(panel, "led")
    field = panel.parameter_line_edits["color"]

    assert isinstance(field, QComboBox)
    assert [field.itemText(index) for index in range(field.count())] == [
        "Red", "Green", "Blue", "Yellow", "White", "Orange"
    ]
    assert field.currentData() == "red"
    assert panel.parameter_labels["color"].text() == "Color:"
    assert not field.isHidden()
    assert panel.value_line_edit.text() == "LED_RED"


def test_color_dropdown_is_hidden_for_other_kinds(panel):
    choose_kind(panel, "resistor")

    assert panel.parameter_line_edits["color"].isHidden()
    assert panel.parameter_labels["color"].isHidden()


def test_new_part_model_follows_the_dropdown(panel):
    choose_kind(panel, "led")
    field = panel.parameter_line_edits["color"]
    field.setCurrentIndex(field.findData("blue"))

    assert panel.value_line_edit.text() == "LED_BLUE"

    field.setCurrentIndex(field.findData("green"))

    assert panel.value_line_edit.text() == "LED_GREEN"


def test_new_part_custom_model_is_kept(panel):
    choose_kind(panel, "led")
    panel.value_line_edit.setText("MY_LED")
    field = panel.parameter_line_edits["color"]
    field.setCurrentIndex(field.findData("blue"))

    assert panel.value_line_edit.text() == "MY_LED"


def test_changing_kind_resets_the_color_to_red(panel):
    choose_kind(panel, "led")
    field = panel.parameter_line_edits["color"]
    field.setCurrentIndex(field.findData("white"))
    choose_kind(panel, "diode")
    choose_kind(panel, "led")

    assert field.currentData() == "red"
    assert panel.value_line_edit.text() == "LED_RED"


def test_place_request_carries_the_color(panel):
    choose_kind(panel, "led")
    field = panel.parameter_line_edits["color"]
    field.setCurrentIndex(field.findData("orange"))
    requests = []
    panel.place_requested.connect(
        lambda *arguments: requests.append(arguments)
    )
    panel.place_button.click()

    assert requests == [("led", "LED_ORANGE", {"color": "orange"})]


def test_selected_part_shows_its_color(panel):
    led = Component("led", "D1", "LED_RED", 4, 4, 0, {"color": "yellow"})
    panel.show_component(led)
    field = panel.selected_parameter_line_edits["color"]

    assert field.currentData() == "yellow"
    assert not field.isHidden()


def test_selected_part_color_pick_applies_at_once(panel):
    panel.show_component(Component("led", "D1", "LED_RED", 4, 4))
    requests = []
    panel.value_change_requested.connect(
        lambda *arguments: requests.append(arguments)
    )
    field = panel.selected_parameter_line_edits["color"]
    field.activated.emit(field.findData("green"))

    assert len(requests) == 1


@pytest.fixture
def window(qt_application, monkeypatch):
    main_window = MainWindow()
    main_window.recorded_errors = []
    monkeypatch.setattr(
        main_window, "show_error_message",
        lambda *arguments: main_window.recorded_errors.append(arguments)
    )
    yield main_window
    main_window.is_project_modified = False
    main_window.close()
    main_window.deleteLater()


def place_led(window, parameter_texts=None):
    scene = window.connection_grid_scene
    scene.clearSelection()
    scene.connection_point_items_by_identifier["NODE_R04_C03"].setSelected(
        True
    )
    window.place_component("led", "LED_RED", parameter_texts)

    return scene.component_items_by_reference["D1"]


def test_window_places_a_colored_led(window):
    item = place_led(window, {"color": "green"})

    assert item.component.parameter_texts == {"color": "green"}
    assert item.label_item.text() == "D1 LED_GREEN"


def test_window_color_edit_updates_model_label_and_panel(window):
    item = place_led(window)
    panel_widget = window.component_panel_widget
    field = panel_widget.selected_parameter_line_edits["color"]
    field.setCurrentIndex(field.findData("blue"))
    field.activated.emit(field.currentIndex())

    assert item.component.parameter_texts == {"color": "blue"}
    assert item.label_item.text() == "D1 LED_BLUE"
    assert panel_widget.selected_value_line_edit.text() == "LED_BLUE"
    assert "Color: blue" in item.toolTip()
    assert window.recorded_errors == []


def test_tooltip_shows_the_color(qt_application):
    item = ComponentItem(Component("led", "D1", "LED_RED", 4, 4), SPACING)

    assert "Color: red" in item.toolTip()


# ----- set_lit -----

def make_led(color="red", rotation=0):
    return ComponentItem(
        Component("led", "D1", "LED_RED", 4, 4, rotation, {"color": color}),
        SPACING
    )


def render_item(item, scene_rect):
    scene = QGraphicsScene()
    scene.addItem(item)
    image = QImage(int(scene_rect.width()), int(scene_rect.height()),
                   QImage.Format_ARGB32)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    scene.render(painter, QRectF(image.rect()), scene_rect)
    painter.end()
    scene.removeItem(item)

    return image


def pixel(image, scene_rect, point):
    return QColor(image.pixel(int(point.x() - scene_rect.x()),
                              int(point.y() - scene_rect.y())))


SCENE_RECT = QRectF(-60, -60, 180, 120)
# The body centre is at (0.5, 0) steps: the triangle spans x = 0.34 to
# 0.66 steps, and the glow point sits below the body, clear of the leads
# and the arrows.
TRIANGLE_POINT = QPointF(0.45 * SPACING, 0)
GLOW_POINT = QPointF(0.5 * SPACING, 0.4 * SPACING)


def test_dark_by_default(qt_application):
    assert make_led().is_lit is False


@pytest.mark.parametrize("color", LED_COLORS)
def test_lit_led_fills_the_triangle_with_its_color(qt_application, color):
    item = make_led(color)
    dark = render_item(item, SCENE_RECT)
    item.set_lit(True)
    lit = render_item(item, SCENE_RECT)

    assert item.is_lit is True
    assert pixel(dark, SCENE_RECT, TRIANGLE_POINT).name() == "#d9e2ec"
    assert pixel(lit, SCENE_RECT, TRIANGLE_POINT).name() == (
        LED_LIT_COLORS[color]
    )


def test_lit_led_glows_around_the_body(qt_application):
    item = make_led("green")
    dark = render_item(item, SCENE_RECT)
    item.set_lit(True)
    lit = render_item(item, SCENE_RECT)
    dark_pixel = pixel(dark, SCENE_RECT, GLOW_POINT)
    lit_pixel = pixel(lit, SCENE_RECT, GLOW_POINT)

    # Outside the body the glow tints the black background green.
    assert dark_pixel.name() == "#000000"
    assert lit_pixel.green() > 40
    assert lit_pixel.green() > lit_pixel.red() + 20


def test_glow_fits_in_the_bounding_rect(qt_application):
    for rotation in (0, 90, 180, 270):
        item = make_led(rotation=rotation)

        assert item.boundingRect().contains(item.get_glow_rect())


def test_lit_does_not_change_the_geometry(qt_application):
    item = make_led()
    before = item.boundingRect()
    item.set_lit(True)

    assert item.boundingRect() == before


def test_set_lit_false_turns_it_off(qt_application):
    item = make_led("blue")
    dark = render_item(item, SCENE_RECT)
    item.set_lit(True)
    item.set_lit(False)
    again = render_item(item, SCENE_RECT)

    assert item.is_lit is False
    assert again == dark


def test_color_change_while_lit_shows_the_new_color(qt_application):
    item = make_led("red")
    item.set_lit(True)
    item.component.set_values("LED_RED", {"color": "blue"})
    item.refresh_from_component()
    lit = render_item(item, SCENE_RECT)

    assert pixel(lit, SCENE_RECT, TRIANGLE_POINT).name() == (
        LED_LIT_COLORS["blue"]
    )


@pytest.mark.parametrize("value", [1, 0, None, "yes"])
def test_set_lit_needs_a_bool(qt_application, value):
    item = make_led()

    with pytest.raises(ComponentError) as error:
        item.set_lit(value)

    assert str(error.value) == f"set_lit needs True or False, not {value!r}."
    assert item.is_lit is False


def test_only_leds_light_up(qt_application):
    item = ComponentItem(Component("diode", "D1", "1N4148", 4, 4), SPACING)

    with pytest.raises(ComponentError) as error:
        item.set_lit(True)

    assert str(error.value) == "Only LEDs can light up; D1 is a diode."
    assert item.is_lit is False


def test_non_led_may_be_set_dark(qt_application):
    item = ComponentItem(Component("resistor", "R1", "1k", 4, 4), SPACING)
    item.set_lit(False)

    assert item.is_lit is False
