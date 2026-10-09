"""
Tests for the current source (back by Billie's decision, Oct 9): kind
current_source, prefix I, value in amps, circle with an arrow toward the
"out" pin. Qt tests use the qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QTransform

from core.components import COMPONENT_DEFINITIONS, Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from gui.component_item import ComponentItem
from gui.component_panel_widget import get_value_field_label
from gui.component_symbols import build_symbol_paths


def test_definition():
    definition = COMPONENT_DEFINITIONS["current_source"]

    assert definition["display_name"] == "Current source"
    assert definition["prefix"] == "I"
    assert definition["pins"] == [("out", 0, 0), ("in", 0, 1)]
    assert definition["default_value_text"] == "1m"
    assert definition["value_kind"] == "any"
    assert (definition["value_label"], definition["value_unit"]) == (
        "Current", "A"
    )


@pytest.mark.parametrize("value_text, value, label", [
    ("1m", 0.001, "I1 1mA"),
    ("-2m", -0.002, "I1 -2mA"),
    ("0", 0.0, "I1 0A"),
    ("1.5", 1.5, "I1 1.5A"),
])
def test_value_is_amps(value_text, value, label):
    source = Component("current_source", "I1", value_text, 4, 4)

    assert source.value == pytest.approx(value)
    assert source.label_text() == label


@pytest.mark.parametrize("value_text", ["abc", "1mA", ""])
def test_bad_values_are_refused(value_text):
    with pytest.raises(ComponentError):
        Component("current_source", "I1", value_text, 4, 4)


def test_numbers_as_i_apart_from_voltage_sources():
    grid = ConnectionGrid(8, 8)
    collection = ComponentCollection()
    collection.add_component("dc_source", 2, 2, "", grid)
    first = collection.add_component("current_source", 2, 4, "", grid)
    second = collection.add_component("current_source", 2, 6, "", grid)

    assert (first.reference, second.reference) == ("I1", "I2")
    assert first.value_text == "1m"


@pytest.mark.parametrize("rotation, out_pin, in_pin", [
    (0, "NODE_R04_C04", "NODE_R05_C04"),
    (90, "NODE_R04_C04", "NODE_R04_C03"),
    (180, "NODE_R04_C04", "NODE_R03_C04"),
    (270, "NODE_R04_C04", "NODE_R04_C05"),
])
def test_pins_at_every_rotation(rotation, out_pin, in_pin):
    source = Component("current_source", "I1", "1m", 4, 4, rotation)

    assert source.get_pin_identifiers() == [out_pin, in_pin]


def test_panel_label(qt_application):
    assert get_value_field_label("current_source") == "Current (A):"


def test_symbol_extents_and_arrow(qt_application):
    stroke_path, fill_path = build_symbol_paths("current_source")
    bounds = stroke_path.boundingRect()

    # Leads from y = 0 to 1, circle radius 0.3 around (0, 0.5).
    assert (bounds.left(), bounds.top(), bounds.width(),
            bounds.height()) == pytest.approx((-0.3, 0.0, 0.6, 1.0), abs=1e-3)
    # The arrowhead tip is at (0, 0.3), pointing up to the out pin.
    head = fill_path.boundingRect()
    assert head.top() == pytest.approx(0.3)
    assert head.bottom() == pytest.approx(0.44)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_arrow_points_at_the_out_pin_at_every_rotation(qt_application,
                                                       rotation):
    # Unlike the AC sine, the arrow turns with the part: it shows which
    # way the current flows.
    source = Component("current_source", "I1", "1m", 4, 4, rotation)
    item = ComponentItem(source, 60)
    head_center = item.fill_path.boundingRect().center()
    body_center = QTransform().rotate(rotation).map(QPointF(0, 30))
    out_pin = QPointF(0, 0)
    in_pin = QTransform().rotate(rotation).map(QPointF(0, 60))

    def distance(a, b):
        return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5

    assert distance(head_center, out_pin) < distance(body_center, out_pin)
    assert distance(head_center, in_pin) > distance(body_center, in_pin)


def test_tooltip_says_current(qt_application):
    item = ComponentItem(Component("current_source", "I1", "2m", 4, 4), 60)

    assert "Current: 2mA" in item.toolTip()


def test_unit_letter_advice_mentions_amps():
    with pytest.raises(ComponentError) as error:
        Component("current_source", "I1", "1mA", 4, 4)

    assert "V, A, or Ohm" in str(error.value)
