"""
Tests for gui.component_symbols: all 11 kinds (Step 4: resistor, capacitor,
inductor, ground; Step 5: polarized capacitor, both sources, diode, LED,
NPN, PNP). Runs headless through the qt_application fixture in
tests/conftest.py.
"""

import math

import pytest
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath

from core.components import COMPONENT_DEFINITIONS
from core.exceptions import ComponentError
from gui.component_symbols import (
    ARROW_HEAD_HALF_WIDTH,
    ARROW_HEAD_LENGTH,
    BODY_RECTS,
    _add_arrow,
    build_symbol_paths,
    get_body_rect,
)

ALL_KINDS = list(COMPONENT_DEFINITIONS)
KINDS_WITH_FILL = ["current_source", "diode", "led", "npn", "pnp"]
KINDS_WITHOUT_FILL = sorted(set(ALL_KINDS) - set(KINDS_WITH_FILL))

# The grid dot is 16 px across at 60 px spacing: radius 8/60 of a pitch.
GRID_DOT_RADIUS_IN_PITCH = 8.0 / 60.0


@pytest.fixture(autouse=True)
def use_qt(qt_application):
    return qt_application


def rect_tuple(rectangle):
    return (
        rectangle.x(), rectangle.y(), rectangle.width(), rectangle.height()
    )


def rounded_point(point):
    return (round(point.x(), 9) + 0.0, round(point.y(), 9) + 0.0)


def subpath_end_points(path):
    """Every subpath's first and last point, rounded to 1e-9."""
    end_points = set()

    for polygon in path.toSubpathPolygons():
        end_points.add(rounded_point(polygon[0]))
        end_points.add(rounded_point(polygon[polygon.count() - 1]))

    return end_points


def straight_segments(path):
    """Subpaths that are a single straight line, as (start, end) pairs."""
    return {
        (rounded_point(polygon[0]), rounded_point(polygon[1]))
        for polygon in path.toSubpathPolygons()
        if polygon.count() == 2
    }


def test_every_kind_has_a_symbol_and_a_body():
    assert set(BODY_RECTS) == set(COMPONENT_DEFINITIONS)

    for kind in ALL_KINDS:
        build_symbol_paths(kind)
        get_body_rect(kind)


@pytest.mark.parametrize("kind", KINDS_WITHOUT_FILL)
def test_kinds_without_filled_parts(kind):
    stroke_path, fill_path = build_symbol_paths(kind)

    assert not stroke_path.isEmpty()
    assert fill_path.isEmpty()


@pytest.mark.parametrize("kind", KINDS_WITH_FILL)
def test_kinds_with_filled_parts(kind):
    stroke_path, fill_path = build_symbol_paths(kind)

    assert not stroke_path.isEmpty()
    assert not fill_path.isEmpty()


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_every_pin_lies_on_the_drawing(kind):
    stroke_path = build_symbol_paths(kind)[0]
    drawing_rect = stroke_path.boundingRect().adjusted(-0.01, -0.01, 0.01, 0.01)

    for unused_name, dx, dy in COMPONENT_DEFINITIONS[kind]["pins"]:
        assert drawing_rect.contains(QPointF(dx, dy))


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_every_pin_is_the_exact_end_of_a_lead(kind):
    # Stronger than the bounding-rect check: a lead that stopped short of
    # its pin would fail here even if another line reached as far.
    end_points = subpath_end_points(build_symbol_paths(kind)[0])

    for unused_name, dx, dy in COMPONENT_DEFINITIONS[kind]["pins"]:
        assert (float(dx), float(dy)) in end_points


# Two-pin parts span one step: anchor (first pin) at x = 0 or y = 0 and the
# second pin at 1; builders draw around the body centre, shifted by 0.5.
TWO_PIN_KINDS = [
    kind for kind in ALL_KINDS
    if len(COMPONENT_DEFINITIONS[kind]["pins"]) == 2
]


def led_shaft_top():
    # The first LED arrow runs (0.44, -0.2) -> (0.6, -0.38) in anchor
    # coordinates; its shaft stops ARROW_HEAD_LENGTH back from the tip.
    along_x, along_y = 0.16, -0.18
    length = math.hypot(along_x, along_y)
    return -0.38 - along_y / length * ARROW_HEAD_LENGTH


@pytest.mark.parametrize(
    "kind, expected_rect",
    [
        # Leads reach x = 0 and 1; zigzag peaks at y = +/-0.13.
        ("resistor", (0.0, -0.13, 1.0, 0.26)),
        # Leads reach x = 0 and 1; plates run from y = -0.26 to 0.26.
        ("capacitor", (0.0, -0.26, 1.0, 0.52)),
        # Leads reach x = 0 and 1; loops of radius 0.1 rise to y = -0.1.
        ("inductor", (0.0, -0.1, 1.0, 0.1)),
        # Unchanged: lead from the pin at y = 0; widest bar 0.6; last bar
        # at y = 0.54.
        ("ground", (-0.3, 0.0, 0.6, 0.54)),
        # Leads from y = 0 to 1; circle radius 0.3 around (0, 0.5).
        ("voltage_source", (-0.3, 0.0, 0.6, 1.0)),
        ("current_source", (-0.3, 0.0, 0.6, 1.0)),
        # Leads reach x = 0 and 1; triangle and bar from y = -0.17 to 0.17.
        ("diode", (0.0, -0.17, 1.0, 0.34)),
        # Unchanged: base lead from x = -1; circle centered x = -0.05,
        # radius 0.5, so its right edge is x = 0.45; collector/emitter
        # leads to y = +/-1.
        ("npn", (-1.0, -1.0, 1.45, 2.0)),
        ("pnp", (-1.0, -1.0, 1.45, 2.0)),
    ]
)
def test_drawing_extents_match_hand_calculation(kind, expected_rect):
    stroke_path = build_symbol_paths(kind)[0]

    assert rect_tuple(stroke_path.boundingRect()) == pytest.approx(
        expected_rect, abs=1e-9
    )


def test_led_extents():
    stroke_path = build_symbol_paths("led")[0]
    top = led_shaft_top()

    # Diode, plus arrow shafts rising to the first head's base.
    assert rect_tuple(stroke_path.boundingRect()) == pytest.approx(
        (0.0, top, 1.0, 0.17 - top), abs=1e-9
    )


def test_polarized_capacitor_extents():
    stroke_path = build_symbol_paths("capacitor_polarized")[0]

    # Leads reach x = 0 and 1; plates and "+" run from y = -0.26 to 0.26.
    # Qt draws arcs as Bezier curves, so allow 1e-3.
    assert rect_tuple(stroke_path.boundingRect()) == pytest.approx(
        (0.0, -0.26, 1.0, 0.52), abs=1e-3
    )


def test_polarized_capacitor_curved_plate_bulges_toward_plus():
    stroke_path = build_symbol_paths("capacitor_polarized")[0]
    segments = straight_segments(stroke_path)

    # Straight plate on the plus (anchor) side, plus sign above-left of it.
    assert ((0.43, -0.26), (0.43, 0.26)) in segments
    assert ((0.23, -0.2), (0.35, -0.2)) in segments
    assert ((0.29, -0.26), (0.29, -0.14)) in segments

    # The curved plate is the one subpath with many points. Its ends are at
    # x = 0.92 - 0.35 * cos(30 deg), and its middle touches x = 0.57,
    # closer to the plus plate than the ends are.
    curve = [
        polygon for polygon in stroke_path.toSubpathPolygons()
        if polygon.count() > 2
    ]
    assert len(curve) == 1

    points = [curve[0][index] for index in range(curve[0].count())]
    end_x = 0.92 - 0.35 * math.cos(math.radians(30))

    assert points[0].x() == pytest.approx(end_x, abs=1e-3)
    assert points[0].y() == pytest.approx(-0.26, abs=1e-3)
    assert points[-1].x() == pytest.approx(end_x, abs=1e-3)
    assert points[-1].y() == pytest.approx(0.26, abs=1e-3)
    assert min(point.x() for point in points) == pytest.approx(0.57, abs=1e-3)


def test_voltage_source_plus_is_on_the_plus_pin_side():
    segments = straight_segments(build_symbol_paths("voltage_source")[0])

    # "+" near the plus pin (0, 0), "-" near the minus pin (0, 1).
    assert ((-0.07, 0.36), (0.07, 0.36)) in segments
    assert ((0.0, 0.29), (0.0, 0.43)) in segments
    assert ((-0.07, 0.64), (0.07, 0.64)) in segments
    assert ((0.0, 0.57), (0.0, 0.71)) not in segments


def test_current_source_arrow_points_at_the_out_pin():
    stroke_path, fill_path = build_symbol_paths("current_source")

    # The out pin is (0, 1): the head's tip is at the bottom, (0, 0.68).
    assert rect_tuple(fill_path.boundingRect()) == pytest.approx(
        (
            -ARROW_HEAD_HALF_WIDTH, 0.68 - ARROW_HEAD_LENGTH,
            2 * ARROW_HEAD_HALF_WIDTH, ARROW_HEAD_LENGTH,
        ),
        abs=1e-9
    )
    shaft_end = round(0.68 - ARROW_HEAD_LENGTH, 9)
    assert ((0.0, 0.32), (0.0, shaft_end)) in straight_segments(stroke_path)


@pytest.mark.parametrize("kind", ["diode", "led"])
def test_diode_triangle_points_at_the_cathode_bar(kind):
    stroke_path, fill_path = build_symbol_paths(kind)

    assert ((0.66, -0.17), (0.66, 0.17)) in straight_segments(stroke_path)

    # The first filled subpath is the closed triangle; its tip touches the
    # bar at (0.66, 0).
    triangle = fill_path.toSubpathPolygons()[0]
    assert [rounded_point(triangle[index]) for index in range(4)] == [
        (0.34, -0.17), (0.34, 0.17), (0.66, 0.0), (0.34, -0.17),
    ]


def test_led_arrows_point_up_and_away():
    stroke_path, fill_path = build_symbol_paths("led")
    shaft_starts = {start for start, end in straight_segments(stroke_path)}

    assert (0.44, -0.2) in shaft_starts
    assert (0.58, -0.2) in shaft_starts

    # Both tips are at y = -0.38; the right tip is at x = 0.74.
    fill_rect = fill_path.boundingRect()
    assert fill_rect.top() == pytest.approx(-0.38, abs=1e-9)
    assert fill_rect.right() == pytest.approx(0.74, abs=1e-9)


def test_npn_emitter_arrow_points_out():
    fill_path = build_symbol_paths("npn")[1]
    fill_rect = fill_path.boundingRect()

    # Tip at (0, 0.35), on the emitter lead, away from the base bar: it is
    # the head's right-most and lowest point.
    assert fill_rect.right() == pytest.approx(0.0, abs=1e-9)
    assert fill_rect.bottom() == pytest.approx(0.35, abs=1e-9)
    assert fill_rect.left() > -0.25


def test_pnp_emitter_arrow_points_in():
    fill_path = build_symbol_paths("pnp")[1]
    fill_rect = fill_path.boundingRect()

    # Tip at (-0.25, -0.12), on the base bar: it is the head's left-most
    # and lowest point.
    assert fill_rect.left() == pytest.approx(-0.25, abs=1e-9)
    assert fill_rect.bottom() == pytest.approx(-0.12, abs=1e-9)
    assert fill_rect.right() < 0.0


@pytest.mark.parametrize("kind", ["npn", "pnp"])
def test_transistor_pins_match_core(kind):
    pins = {
        name: (dx, dy)
        for name, dx, dy in COMPONENT_DEFINITIONS[kind]["pins"]
    }
    stroke_path = build_symbol_paths(kind)[0]
    end_points = subpath_end_points(stroke_path)

    # NPN: collector on top. PNP: emitter on top (the arrow end).
    top_pin = "collector" if kind == "npn" else "emitter"
    assert pins[top_pin] == (0, -1)
    assert (0.0, -1.0) in end_points


def test_inductor_loops_touch_the_axis_between_humps():
    stroke_path = build_symbol_paths("inductor")[0]

    # The tops of the three humps are at x = 0.3, 0.5 and 0.7, y = -0.1.
    for hump_x in (0.3, 0.5, 0.7):
        hump_top = QRectF(hump_x - 0.01, -0.11, 0.02, 0.02)
        assert stroke_path.intersects(hump_top)


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_body_rect_excludes_pins(kind):
    body_rect = get_body_rect(kind)
    half_dx, half_dy = COMPONENT_DEFINITIONS[kind]["body_center_half_steps"]

    # BODY_RECTS is around the body centre; get_body_rect shifts it to the
    # anchor like the paths.
    assert rect_tuple(body_rect) == pytest.approx(
        rect_tuple(BODY_RECTS[kind].translated(half_dx / 2, half_dy / 2)),
        abs=1e-12
    )

    for unused_name, dx, dy in COMPONENT_DEFINITIONS[kind]["pins"]:
        assert not body_rect.contains(QPointF(dx, dy))


@pytest.mark.parametrize("kind", ["npn", "pnp"])
def test_transistor_body_hides_the_grid_dot_under_it(kind):
    # Transistors are centred on a grid point that is not a pin; the body
    # must cover that dot so it does not show through.
    radius = GRID_DOT_RADIUS_IN_PITCH
    dot_rect = QRectF(-radius, -radius, 2 * radius, 2 * radius)

    assert get_body_rect(kind).contains(dot_rect)


@pytest.mark.parametrize("kind", TWO_PIN_KINDS)
def test_two_pin_body_sits_between_the_pins_clear_of_their_dots(kind):
    # The body is between the two neighbouring grid points and does not
    # touch either pin's dot, so a short stretch of each lead stays visible.
    body_rect = get_body_rect(kind)
    radius = GRID_DOT_RADIUS_IN_PITCH

    for unused_name, dx, dy in COMPONENT_DEFINITIONS[kind]["pins"]:
        dot_rect = QRectF(dx - radius, dy - radius, 2 * radius, 2 * radius)
        assert not body_rect.intersects(dot_rect)

    (_name_a, x1, y1), (_name_b, x2, y2) = (
        COMPONENT_DEFINITIONS[kind]["pins"]
    )
    assert body_rect.contains(QPointF((x1 + x2) / 2, (y1 + y2) / 2))


@pytest.mark.parametrize("kind", TWO_PIN_KINDS)
def test_two_pin_symbol_fits_one_step(kind):
    # Nothing is drawn past the two pins along the part's axis.
    stroke_rect = build_symbol_paths(kind)[0].boundingRect()
    (_name_a, _x1, y1), (_name_b, _x2, y2) = (
        COMPONENT_DEFINITIONS[kind]["pins"]
    )

    if y1 == y2:
        assert (stroke_rect.left(), stroke_rect.right()) == pytest.approx(
            (0.0, 1.0), abs=1e-9
        )
        assert stroke_rect.height() < 0.7
    else:
        assert (stroke_rect.top(), stroke_rect.bottom()) == pytest.approx(
            (0.0, 1.0), abs=1e-9
        )
        assert stroke_rect.width() < 0.7


@pytest.mark.parametrize("kind", KINDS_WITH_FILL)
def test_filled_parts_lie_inside_the_body(kind):
    fill_rect = build_symbol_paths(kind)[1].boundingRect()

    assert get_body_rect(kind).contains(fill_rect)


def test_get_body_rect_returns_a_copy():
    body_rect = get_body_rect("resistor")
    body_rect.setWidth(99.0)

    assert BODY_RECTS["resistor"].width() == 0.64


def test_each_call_returns_new_paths():
    first_stroke = build_symbol_paths("resistor")[0]
    first_stroke.lineTo(5.0, 5.0)

    second_stroke = build_symbol_paths("resistor")[0]

    assert rect_tuple(second_stroke.boundingRect()) == pytest.approx(
        (0.0, -0.13, 1.0, 0.26), abs=1e-9
    )


@pytest.mark.parametrize("kind", ["transistor", "", None, 5, "NPN"])
def test_unknown_kind_raises_component_error(kind):
    with pytest.raises(ComponentError):
        build_symbol_paths(kind)

    with pytest.raises(ComponentError):
        get_body_rect(kind)


def test_kind_added_to_core_without_a_symbol_is_not_implemented(monkeypatch):
    # A future kind in core that has no drawing yet must fail loudly.
    monkeypatch.setitem(COMPONENT_DEFINITIONS, "op_amp", {"pins": []})

    with pytest.raises(NotImplementedError):
        build_symbol_paths("op_amp")

    with pytest.raises(NotImplementedError):
        get_body_rect("op_amp")


def test_add_arrow_head_geometry():
    stroke_path = QPainterPath()
    fill_path = QPainterPath()

    _add_arrow(stroke_path, fill_path, 0.0, 0.0, 1.0, 0.0)

    # Tip at (1,0), base 0.14 back at x = 0.86, 0.07 to each side. The
    # shaft stops at the base so the round pen cap stays behind the tip.
    assert rect_tuple(stroke_path.boundingRect()) == pytest.approx(
        (0.0, 0.0, 0.86, 0.0), abs=1e-9
    )
    assert rect_tuple(fill_path.boundingRect()) == pytest.approx(
        (0.86, -0.07, 0.14, 0.14), abs=1e-9
    )


@pytest.mark.parametrize(
    "end_point",
    [
        (0.5, 0.5),                       # zero length: no direction
        (0.5, 0.5 + ARROW_HEAD_LENGTH),   # exactly the head: no shaft
    ]
)
def test_add_arrow_too_short_raises_and_draws_nothing(end_point):
    stroke_path = QPainterPath()
    fill_path = QPainterPath()

    with pytest.raises(ComponentError):
        _add_arrow(stroke_path, fill_path, 0.5, 0.5, *end_point)

    assert stroke_path.isEmpty()
    assert fill_path.isEmpty()
