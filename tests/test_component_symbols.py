"""
Tests for gui.component_symbols (Step 4: resistor, capacitor, inductor,
ground). Runs headless: tests/conftest.py selects the "offscreen" platform.
"""

import pytest
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath

from core.components import COMPONENT_DEFINITIONS
from core.exceptions import ComponentError
from gui.component_symbols import (
    BODY_RECTS,
    _add_arrow,
    build_symbol_paths,
    get_body_rect,
)

STEP4_KINDS = ["resistor", "capacitor", "inductor", "ground"]


@pytest.fixture(autouse=True)
def use_qt(qt_application):
    return qt_application


def rect_tuple(rectangle):
    return (
        rectangle.x(), rectangle.y(), rectangle.width(), rectangle.height()
    )


@pytest.mark.parametrize("kind", STEP4_KINDS)
def test_stroke_path_is_not_empty_and_fill_is_empty(kind):
    stroke_path, fill_path = build_symbol_paths(kind)

    assert not stroke_path.isEmpty()
    assert fill_path.isEmpty()


@pytest.mark.parametrize("kind", STEP4_KINDS)
def test_every_pin_lies_on_the_drawing(kind):
    stroke_path = build_symbol_paths(kind)[0]
    drawing_rect = stroke_path.boundingRect().adjusted(-0.01, -0.01, 0.01, 0.01)

    for unused_name, dx, dy in COMPONENT_DEFINITIONS[kind]["pins"]:
        assert drawing_rect.contains(QPointF(dx, dy))


@pytest.mark.parametrize(
    "kind, expected_rect",
    [
        # Leads reach x = -1 and +1; zigzag peaks at y = +/-0.2.
        ("resistor", (-1.0, -0.2, 2.0, 0.4)),
        # Leads reach x = +/-1; plates run from y = -0.35 to 0.35.
        ("capacitor", (-1.0, -0.35, 2.0, 0.7)),
        # Leads reach x = +/-1; loops of radius 0.15 rise to y = -0.15.
        ("inductor", (-1.0, -0.15, 2.0, 0.15)),
        # Lead from the pin at y = 0; widest bar 0.6; last bar at y = 0.54.
        ("ground", (-0.3, 0.0, 0.6, 0.54)),
    ]
)
def test_drawing_extents_match_hand_calculation(kind, expected_rect):
    stroke_path = build_symbol_paths(kind)[0]

    assert rect_tuple(stroke_path.boundingRect()) == pytest.approx(
        expected_rect, abs=1e-9
    )


def test_inductor_loops_touch_the_axis_between_humps():
    stroke_path = build_symbol_paths("inductor")[0]

    # The tops of the four humps are at x = -0.45, -0.15, 0.15, 0.45.
    for hump_x in (-0.45, -0.15, 0.15, 0.45):
        hump_top = QRectF(hump_x - 0.01, -0.16, 0.02, 0.02)
        assert stroke_path.intersects(hump_top)


@pytest.mark.parametrize("kind", STEP4_KINDS)
def test_body_rect_excludes_pins(kind):
    body_rect = get_body_rect(kind)

    assert rect_tuple(body_rect) == rect_tuple(BODY_RECTS[kind])

    for unused_name, dx, dy in COMPONENT_DEFINITIONS[kind]["pins"]:
        assert not body_rect.contains(QPointF(dx, dy))


# The grid dot is 16 px across at 60 px spacing: radius 8/60 of a pitch.
GRID_DOT_RADIUS_IN_PITCH = 8.0 / 60.0


@pytest.mark.parametrize("kind", ["resistor", "capacitor", "inductor"])
def test_body_hides_the_grid_dot_under_the_part(kind):
    # Two-pin parts sit centered on a grid point that is not a pin; the
    # body must cover that dot so it does not show through the symbol.
    radius = GRID_DOT_RADIUS_IN_PITCH
    dot_rect = QRectF(-radius, -radius, 2 * radius, 2 * radius)

    assert get_body_rect(kind).contains(dot_rect)


def test_get_body_rect_returns_a_copy():
    body_rect = get_body_rect("resistor")
    body_rect.setWidth(99.0)

    assert BODY_RECTS["resistor"].width() == 1.3


def test_each_call_returns_new_paths():
    first_stroke = build_symbol_paths("resistor")[0]
    first_stroke.lineTo(5.0, 5.0)

    second_stroke = build_symbol_paths("resistor")[0]

    assert rect_tuple(second_stroke.boundingRect()) == pytest.approx(
        (-1.0, -0.2, 2.0, 0.4), abs=1e-9
    )


@pytest.mark.parametrize("kind", ["transistor", "", None, 5])
def test_unknown_kind_raises_component_error(kind):
    with pytest.raises(ComponentError):
        build_symbol_paths(kind)

    with pytest.raises(ComponentError):
        get_body_rect(kind)


@pytest.mark.parametrize(
    "kind", sorted(set(COMPONENT_DEFINITIONS) - set(STEP4_KINDS))
)
def test_step5_kinds_are_not_implemented_yet(kind):
    with pytest.raises(NotImplementedError):
        build_symbol_paths(kind)


def test_add_arrow_head_geometry():
    stroke_path = QPainterPath()
    fill_path = QPainterPath()

    _add_arrow(stroke_path, fill_path, 0.0, 0.0, 1.0, 0.0)

    # Shaft from (0,0) to (1,0); head tip at (1,0), base 0.08 back, 0.04 wide.
    assert rect_tuple(stroke_path.boundingRect()) == pytest.approx(
        (0.0, 0.0, 1.0, 0.0), abs=1e-9
    )
    assert rect_tuple(fill_path.boundingRect()) == pytest.approx(
        (0.92, -0.04, 0.08, 0.08), abs=1e-9
    )
