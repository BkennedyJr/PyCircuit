"""
Standard schematic symbols drawn with QPainterPath.

Every symbol is built in pitch units: 1.0 is one grid step and y points
down, the same as Qt. Builders draw each symbol around its body centre;
build_symbol_paths() then shifts it by the kind's body_center_half_steps
(core.components) so the origin is the part's anchor grid point and the
lead ends land exactly on the pin offsets. A symbol scaled by the grid
spacing and rotated in 90-degree steps about the anchor therefore keeps
its pins on grid points.

Two-pin parts span ONE grid step: leads run from -0.5 to +0.5 around the
body centre, so at 60 px per step the body is about 36 px long. Grid dots
(16 px) sit under the lead ends; bodies stay about 0.2 of a step (12 px)
from each pin, so a few pixels of lead show past each dot.

Transistors and ground are drawn around their anchor (no shift) and keep
their earlier size: transistors span two steps with three pins. Op-amps are
a triangle around their anchor, two steps tall, with five pins.

Most bodies are rectangles (BODY_RECTS). An op-amp's body is its triangle
(BODY_POLYGONS); get_body_path() returns the exact body for every kind.
Small glyphs that must read the same at every rotation (the AC sine, the
op-amp's + and - input marks) are turned back around their own centres.

Each builder returns two paths: a stroke path for lines and outlines, and a
fill path for solid shapes such as arrowheads. Keeping them apart means
open shapes like the resistor zigzag are never filled by accident.
"""

import math

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath, QPolygonF, QTransform

from core.components import COMPONENT_DEFINITIONS
from core.exceptions import ComponentError

# 0.14 x 0.14 of a step is about 8 px at the 60 px grid spacing, large
# enough to read the transistor emitter arrows (0.08 was barely visible).
ARROW_HEAD_LENGTH = 0.14
ARROW_HEAD_HALF_WIDTH = 0.07

# Half the span of a two-pin part: its leads end at +/-0.5 around the body.
HALF_SPAN = 0.5

# Body area of each symbol, excluding the leads, in pitch units and around
# the body centre (build_symbol_paths shifts them with the paths). The item
# paints this area in the background color and uses it as the click area.
BODY_RECTS = {
    "resistor": QRectF(-0.32, -0.16, 0.64, 0.32),
    "capacitor": QRectF(-0.12, -0.3, 0.24, 0.6),
    "inductor": QRectF(-0.32, -0.16, 0.64, 0.24),
    "ground": QRectF(-0.35, 0.25, 0.7, 0.35),
    "capacitor_polarized": QRectF(-0.3, -0.3, 0.44, 0.6),
    "dc_source": QRectF(-0.3, -0.3, 0.6, 0.42),
    "ac_source": QRectF(-0.32, -0.32, 0.64, 0.64),
    "current_source": QRectF(-0.32, -0.32, 0.64, 0.64),
    "diode": QRectF(-0.2, -0.2, 0.4, 0.4),
    "led": QRectF(-0.2, -0.4, 0.5, 0.6),
    "npn": QRectF(-0.55, -0.5, 1.0, 1.0),
    "pnp": QRectF(-0.55, -0.5, 1.0, 1.0),
    # Op-amps: the largest rectangle inside the triangle band that keeps
    # clear of the five pins; the real body is the triangle below.
    "opamp_generic": QRectF(-0.6, -0.6, 1.35, 1.2),
    "opamp_741": QRectF(-0.6, -0.6, 1.35, 1.2),
    "opamp_lm358": QRectF(-0.6, -0.6, 1.35, 1.2),
    "opamp_tl072": QRectF(-0.6, -0.6, 1.35, 1.2),
    "opamp_ne5532": QRectF(-0.6, -0.6, 1.35, 1.2),
    "comparator": QRectF(-0.6, -0.6, 1.35, 1.2),
    "gate_and": QRectF(-0.55, -0.75, 1.45, 1.5),
    "gate_or": QRectF(-0.72, -0.75, 1.57, 1.5),
    "gate_xor": QRectF(-0.92, -0.75, 1.77, 1.5),
    "gate_nand": QRectF(-0.55, -0.75, 1.41, 1.5),
    "gate_nor": QRectF(-0.72, -0.75, 1.55, 1.5),
    "gate_not": QRectF(-0.45, -0.40, 1.05, 0.80),
    "gate_buffer": QRectF(-0.45, -0.40, 0.95, 0.80),
    "follower": QRectF(-0.45, -0.40, 0.95, 0.80),
    "inverting_amp": QRectF(-0.45, -0.40, 0.95, 0.80),
    "noninverting_amp": QRectF(-0.45, -0.40, 0.95, 0.80),
}

# Op-amp triangle, pointing right at rotation 0: left side at x = -0.6 from
# y = -1.2 to 1.2, apex at (0.75, 0). At 60 px per step the inputs' leads
# show 16 px past their dots, the supply leads 11 px and the output 7 px.
OPAMP_LEFT_X = -0.6
OPAMP_APEX_X = 0.75
OPAMP_HALF_HEIGHT = 1.2
# The - and + input marks sit inside the triangle, beside their inputs.
OPAMP_SIGN_X = -0.38
OPAMP_SIGN_Y = 0.55
OPAMP_SIGN_HALF_SIZE = 0.1


def _opamp_triangle():
    """
    Return the op-amp triangle as a polygon around the anchor.

    :rtype: QPolygonF
    """
    return QPolygonF([
        QPointF(OPAMP_LEFT_X, -OPAMP_HALF_HEIGHT),
        QPointF(OPAMP_APEX_X, 0.0),
        QPointF(OPAMP_LEFT_X, OPAMP_HALF_HEIGHT),
    ])


def opamp_edge_y(x):
    """
    Return how far the op-amp triangle reaches above and below y = 0 at x.

    :param x: Position across the triangle, OPAMP_LEFT_X..OPAMP_APEX_X.
    :type x: float
    :returns: Half height of the triangle at x.
    :rtype: float
    """
    return OPAMP_HALF_HEIGHT * (OPAMP_APEX_X - x) / (
        OPAMP_APEX_X - OPAMP_LEFT_X
    )


# Non-rectangular bodies, around the body centre like BODY_RECTS.
# One-input triangle (buffer, follower, amplifiers). Short enough that the
# label fits in the gap above the body, between the grid rows.
BLOCK_LEFT = -0.45
BLOCK_APEX = 0.50
BLOCK_HALF = 0.40
# NOT gate triangle stops short so the bubble fits before the output pin.
NOT_LEFT = -0.45
NOT_APEX = 0.40
NOT_HALF = 0.40
BUBBLE_RADIUS = 0.08
# AND/OR body. A bubbled gate is shorter so the bubble stays off the pin.
GATE_LEFT = -0.55
GATE_TOP = -0.75
GATE_BOTTOM = 0.75
AND_MID = 0.15
AND_RADIUS = 0.75
NAND_MID = 0.05
NAND_RADIUS = 0.62


def _buffer_triangle():
    """
    Triangle for a one-input gate or amplifier block, pointing right.

    :rtype: QPolygonF
    """
    return QPolygonF([
        QPointF(BLOCK_LEFT, -BLOCK_HALF),
        QPointF(BLOCK_APEX, 0.0),
        QPointF(BLOCK_LEFT, BLOCK_HALF),
    ])


def _not_triangle():
    """
    Smaller triangle, leaving room for the output bubble.

    :rtype: QPolygonF
    """
    return QPolygonF([
        QPointF(NOT_LEFT, -NOT_HALF),
        QPointF(NOT_APEX, 0.0),
        QPointF(NOT_LEFT, NOT_HALF),
    ])


BODY_POLYGONS = {
    "opamp_generic": _opamp_triangle,
    "opamp_741": _opamp_triangle,
    "opamp_lm358": _opamp_triangle,
    "opamp_tl072": _opamp_triangle,
    "opamp_ne5532": _opamp_triangle,
    "comparator": _opamp_triangle,
    "gate_buffer": _buffer_triangle,
    "gate_not": _not_triangle,
    "follower": _buffer_triangle,
    "inverting_amp": _buffer_triangle,
    "noninverting_amp": _buffer_triangle,
}

# AC source: a 36 px circle with 12 px leads at the 60 px spacing.
SOURCE_RADIUS = 0.3
# Current source arrow: from y = 0.2 up to y = -0.2, inside the circle.
CURRENT_ARROW_HALF_LENGTH = 0.2

# DC source (battery cell): the long plate is the plus side, nearest the
# plus pin; plates are 0.12 of a step (7 px) apart.
BATTERY_LONG_PLATE_Y = -0.06
BATTERY_SHORT_PLATE_Y = 0.06
BATTERY_LONG_PLATE_HALF_WIDTH = 0.26
BATTERY_SHORT_PLATE_HALF_WIDTH = 0.13

# AC source sine: one full period across the circle.
SINE_HALF_WIDTH = 0.18
SINE_AMPLITUDE = 0.1
SINE_POINT_COUNT = 25
TRANSISTOR_CIRCLE_CENTER_X = -0.05
TRANSISTOR_CIRCLE_RADIUS = 0.5


def _add_line(path, x1, y1, x2, y2):
    """
    Add one straight line segment to a path.

    :param path: Path to extend.
    :type path: QPainterPath
    :returns: None
    """
    path.moveTo(x1, y1)
    path.lineTo(x2, y2)


def _add_arrow(stroke_path, fill_path, x1, y1, x2, y2):
    """
    Add an arrow from (x1, y1) to (x2, y2).

    A filled triangular head with its tip at (x2, y2) goes into fill_path.
    The shaft goes into stroke_path and stops at the base of the head, so
    the pen's round cap does not poke out past the tip.

    :param stroke_path: Path that receives the shaft.
    :type stroke_path: QPainterPath
    :param fill_path: Path that receives the arrowhead.
    :type fill_path: QPainterPath
    :returns: None
    :raises ComponentError: If the arrow is not longer than its head
        (this includes a zero-length arrow, which has no direction and
        would divide by zero). Neither path is changed in that case.
    """
    length = math.hypot(x2 - x1, y2 - y1)

    if length <= ARROW_HEAD_LENGTH:
        raise ComponentError(
            f"An arrow must be longer than its head ({ARROW_HEAD_LENGTH} "
            f"of a grid step); this one is {length:g}."
        )

    # Unit vector along the arrow, and the perpendicular for the head width.
    along_x = (x2 - x1) / length
    along_y = (y2 - y1) / length
    across_x = -along_y
    across_y = along_x

    base_x = x2 - along_x * ARROW_HEAD_LENGTH
    base_y = y2 - along_y * ARROW_HEAD_LENGTH

    _add_line(stroke_path, x1, y1, base_x, base_y)

    fill_path.moveTo(x2, y2)
    fill_path.lineTo(
        base_x + across_x * ARROW_HEAD_HALF_WIDTH,
        base_y + across_y * ARROW_HEAD_HALF_WIDTH
    )
    fill_path.lineTo(
        base_x - across_x * ARROW_HEAD_HALF_WIDTH,
        base_y - across_y * ARROW_HEAD_HALF_WIDTH
    )
    fill_path.closeSubpath()


def _add_horizontal_leads(stroke_path, body_half_width):
    """
    Add the two leads of a horizontal two-pin part (pins at +/-HALF_SPAN).

    :param stroke_path: Path to extend.
    :type stroke_path: QPainterPath
    :param body_half_width: Where each lead meets the body.
    :type body_half_width: float
    :returns: None
    """
    _add_line(stroke_path, -HALF_SPAN, 0.0, -body_half_width, 0.0)
    _add_line(stroke_path, body_half_width, 0.0, HALF_SPAN, 0.0)


def _resistor_paths():
    """
    ANSI resistor: short leads and a six-peak zigzag 0.6 of a step long.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    _add_horizontal_leads(stroke_path, 0.3)

    zigzag_points = [
        (-0.3, 0.0), (-0.25, -0.13), (-0.15, 0.13), (-0.05, -0.13),
        (0.05, 0.13), (0.15, -0.13), (0.25, 0.13), (0.3, 0.0),
    ]
    stroke_path.moveTo(QPointF(*zigzag_points[0]))

    for point in zigzag_points[1:]:
        stroke_path.lineTo(QPointF(*point))

    return (stroke_path, QPainterPath())


def _capacitor_paths():
    """
    Non-polarized capacitor: two leads and two parallel plates.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    _add_horizontal_leads(stroke_path, 0.07)
    _add_line(stroke_path, -0.07, -0.26, -0.07, 0.26)
    _add_line(stroke_path, 0.07, -0.26, 0.07, 0.26)

    return (stroke_path, QPainterPath())


def _inductor_paths():
    """
    Inductor: two leads and three semicircular loops bulging upward.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    _add_line(stroke_path, -HALF_SPAN, 0.0, -0.3, 0.0)

    # Each arc starts at its left end (180 degrees) and sweeps clockwise on
    # screen over the top to its right end, where the next arc begins.
    for loop_index in range(3):
        stroke_path.arcTo(
            QRectF(-0.3 + 0.2 * loop_index, -0.1, 0.2, 0.2),
            180,
            -180
        )

    _add_line(stroke_path, 0.3, 0.0, HALF_SPAN, 0.0)

    return (stroke_path, QPainterPath())


def _ground_paths():
    """
    Ground: a lead down from the pin and three shrinking bars.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    _add_line(stroke_path, 0.0, 0.0, 0.0, 0.3)
    _add_line(stroke_path, -0.3, 0.3, 0.3, 0.3)
    _add_line(stroke_path, -0.2, 0.42, 0.2, 0.42)
    _add_line(stroke_path, -0.1, 0.54, 0.1, 0.54)

    return (stroke_path, QPainterPath())


def _polarized_capacitor_paths():
    """
    Polarized capacitor: a straight plate on the plus (left) pin side, a
    curved plate on the minus side that bulges toward the plus plate, and
    a small plus sign.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    _add_horizontal_leads(stroke_path, 0.07)
    _add_line(stroke_path, -0.07, -0.26, -0.07, 0.26)

    # Arc of an ellipse centered at (0.42, 0) with radii 0.35 and 0.52, from
    # 150 to 210 degrees: about (0.117, -0.26) through (0.07, 0) to
    # (0.117, 0.26).
    curved_plate_rect = QRectF(0.07, -0.52, 0.7, 1.04)
    stroke_path.arcMoveTo(curved_plate_rect, 150)
    stroke_path.arcTo(curved_plate_rect, 150, 60)

    _add_line(stroke_path, -0.27, -0.2, -0.15, -0.2)
    _add_line(stroke_path, -0.21, -0.26, -0.21, -0.14)

    return (stroke_path, QPainterPath())


def _dc_source_paths():
    """
    DC voltage source drawn as a battery cell: the long plate toward the
    plus pin (top), the short plate toward the minus pin (bottom), and a
    "+" beside the long plate.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    _add_line(stroke_path, 0.0, -HALF_SPAN, 0.0, BATTERY_LONG_PLATE_Y)
    _add_line(stroke_path, 0.0, BATTERY_SHORT_PLATE_Y, 0.0, HALF_SPAN)
    _add_line(
        stroke_path,
        -BATTERY_LONG_PLATE_HALF_WIDTH, BATTERY_LONG_PLATE_Y,
        BATTERY_LONG_PLATE_HALF_WIDTH, BATTERY_LONG_PLATE_Y
    )
    _add_line(
        stroke_path,
        -BATTERY_SHORT_PLATE_HALF_WIDTH, BATTERY_SHORT_PLATE_Y,
        BATTERY_SHORT_PLATE_HALF_WIDTH, BATTERY_SHORT_PLATE_Y
    )

    # "+" above the right half of the long plate, beside the plus lead.
    _add_line(stroke_path, 0.11, -0.2, 0.23, -0.2)
    _add_line(stroke_path, 0.17, -0.26, 0.17, -0.14)

    return (stroke_path, QPainterPath())


def _ac_source_paths():
    """
    AC voltage source: circle with leads to the plus pin (top) and the
    minus pin (bottom). The sine inside is a separate glyph
    (_sine_glyph_path) that build_symbol_paths keeps upright.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    stroke_path.addEllipse(QPointF(0.0, 0.0), SOURCE_RADIUS, SOURCE_RADIUS)
    _add_line(stroke_path, 0.0, -HALF_SPAN, 0.0, -SOURCE_RADIUS)
    _add_line(stroke_path, 0.0, SOURCE_RADIUS, 0.0, HALF_SPAN)

    return (stroke_path, QPainterPath())


def _sine_glyph_path():
    """
    One full period of a sine, horizontal and centred on the body centre,
    first half-wave up. Drawn upright at every rotation.

    :returns: Stroke path of the sine.
    :rtype: QPainterPath
    """
    stroke_path = QPainterPath()

    # y points down, so the minus sign makes the first half-wave go up.
    for point_index in range(SINE_POINT_COUNT):
        fraction = point_index / (SINE_POINT_COUNT - 1)
        x = -SINE_HALF_WIDTH + 2 * SINE_HALF_WIDTH * fraction
        y = -SINE_AMPLITUDE * math.sin(2 * math.pi * fraction)

        if point_index == 0:
            stroke_path.moveTo(x, y)
        else:
            stroke_path.lineTo(x, y)

    return stroke_path


def _current_source_paths():
    """
    Current source: circle with leads to the out pin (top) and the in pin
    (bottom), and an arrow inside pointing to out, the way the current
    leaves the source. The arrow turns with the part (it shows direction).

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()
    fill_path = QPainterPath()

    stroke_path.addEllipse(QPointF(0.0, 0.0), SOURCE_RADIUS, SOURCE_RADIUS)
    _add_line(stroke_path, 0.0, -HALF_SPAN, 0.0, -SOURCE_RADIUS)
    _add_line(stroke_path, 0.0, SOURCE_RADIUS, 0.0, HALF_SPAN)
    _add_arrow(
        stroke_path, fill_path, 0.0, CURRENT_ARROW_HALF_LENGTH,
        0.0, -CURRENT_ARROW_HALF_LENGTH
    )

    return (stroke_path, fill_path)


def _diode_paths():
    """
    Diode: anode on the left, a filled triangle pointing right, and the
    cathode bar on the right.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()
    fill_path = QPainterPath()

    _add_horizontal_leads(stroke_path, 0.16)

    # The triangle is outlined (so it has the same edge as the other lines)
    # and also filled.
    for path in (stroke_path, fill_path):
        path.moveTo(-0.16, -0.17)
        path.lineTo(-0.16, 0.17)
        path.lineTo(0.16, 0.0)
        path.closeSubpath()

    _add_line(stroke_path, 0.16, -0.17, 0.16, 0.17)

    return (stroke_path, fill_path)


def _led_paths():
    """
    LED: the diode plus two parallel arrows pointing up and away (emitted
    light).

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path, fill_path = _diode_paths()

    _add_arrow(stroke_path, fill_path, -0.06, -0.2, 0.1, -0.38)
    _add_arrow(stroke_path, fill_path, 0.08, -0.2, 0.24, -0.38)

    return (stroke_path, fill_path)


def _transistor_base_paths():
    """
    Circle, base lead and base bar shared by NPN and PNP (base pin at
    (-1, 0)).

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    stroke_path.addEllipse(
        QPointF(TRANSISTOR_CIRCLE_CENTER_X, 0.0),
        TRANSISTOR_CIRCLE_RADIUS,
        TRANSISTOR_CIRCLE_RADIUS
    )
    _add_line(stroke_path, -1.0, 0.0, -0.25, 0.0)
    _add_line(stroke_path, -0.25, -0.3, -0.25, 0.3)

    return (stroke_path, QPainterPath())


def _npn_paths():
    """
    NPN BJT: collector at the top (0, -1), emitter at the bottom (0, 1),
    emitter arrow pointing out, away from the base bar.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path, fill_path = _transistor_base_paths()

    stroke_path.moveTo(-0.25, -0.12)
    stroke_path.lineTo(0.0, -0.35)
    stroke_path.lineTo(0.0, -1.0)

    _add_arrow(stroke_path, fill_path, -0.25, 0.12, 0.0, 0.35)
    _add_line(stroke_path, 0.0, 0.35, 0.0, 1.0)

    return (stroke_path, fill_path)


def _pnp_paths():
    """
    PNP BJT: emitter at the top (0, -1), collector at the bottom (0, 1),
    emitter arrow pointing in, toward the base bar.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path, fill_path = _transistor_base_paths()

    stroke_path.moveTo(-0.25, 0.12)
    stroke_path.lineTo(0.0, 0.35)
    stroke_path.lineTo(0.0, 1.0)

    _add_line(stroke_path, 0.0, -1.0, 0.0, -0.35)
    _add_arrow(stroke_path, fill_path, 0.0, -0.35, -0.25, -0.12)

    return (stroke_path, fill_path)


def _opamp_paths():
    """
    Op-amp: triangle pointing right, in- (top) and in+ (bottom) on the
    left, out at the apex, V+ above and V- below. The - and + marks are
    upright glyphs (_opamp_minus_glyph_path, _opamp_plus_glyph_path).

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()
    stroke_path.addPolygon(_opamp_triangle())
    stroke_path.closeSubpath()

    supply_lead_end = opamp_edge_y(0.0)

    _add_line(stroke_path, -1.0, -1.0, OPAMP_LEFT_X, -1.0)
    _add_line(stroke_path, -1.0, 1.0, OPAMP_LEFT_X, 1.0)
    _add_line(stroke_path, OPAMP_APEX_X, 0.0, 1.0, 0.0)
    _add_line(stroke_path, 0.0, -1.0, 0.0, -supply_lead_end)
    _add_line(stroke_path, 0.0, 1.0, 0.0, supply_lead_end)

    return (stroke_path, QPainterPath())


def _opamp_minus_glyph_path():
    """
    The "-" mark of the inverting input, around (0, 0).

    :rtype: QPainterPath
    """
    path = QPainterPath()
    _add_line(path, -OPAMP_SIGN_HALF_SIZE, 0.0, OPAMP_SIGN_HALF_SIZE, 0.0)
    return path


def _opamp_plus_glyph_path():
    """
    The "+" mark of the non-inverting input, around (0, 0).

    :rtype: QPainterPath
    """
    path = _opamp_minus_glyph_path()
    _add_line(path, 0.0, -OPAMP_SIGN_HALF_SIZE, 0.0, OPAMP_SIGN_HALF_SIZE)
    return path


def _and_shape(stroke_path, mid, radius):
    """
    D-shaped AND body. The flat side is on the left; the arc bulges right.

    :returns: The x of the right-most point of the arc.
    :rtype: float
    """
    stroke_path.moveTo(GATE_LEFT, GATE_TOP)
    stroke_path.lineTo(mid, GATE_TOP)
    stroke_path.arcTo(
        mid - radius, GATE_TOP, 2 * radius, GATE_BOTTOM - GATE_TOP,
        90, -180
    )
    stroke_path.lineTo(GATE_LEFT, GATE_BOTTOM)
    stroke_path.closeSubpath()

    return mid + radius


def _or_shape(stroke_path, tip):
    """
    OR body: curved back, pointed front.

    :returns: None
    """
    stroke_path.moveTo(-0.55, GATE_TOP)
    stroke_path.quadTo(-0.20, 0.0, -0.55, GATE_BOTTOM)
    stroke_path.quadTo(0.15, GATE_BOTTOM, tip, 0.0)
    stroke_path.quadTo(0.15, GATE_TOP, -0.55, GATE_TOP)


def _supply_leads(stroke_path, top_y, bottom_y):
    """
    Leads from the VCC/V+ pin above and the GND/V- pin below.

    :returns: None
    """
    _add_line(stroke_path, 0.0, -1.0, 0.0, top_y)
    _add_line(stroke_path, 0.0, 1.0, 0.0, bottom_y)


def _output_bubble(fill_path, left_x):
    """
    Filled bubble just to the right of ``left_x``.

    :returns: The x where the output lead should start.
    :rtype: float
    """
    center = left_x + BUBBLE_RADIUS
    fill_path.addEllipse(
        QPointF(center, 0.0), BUBBLE_RADIUS, BUBBLE_RADIUS
    )

    return center + BUBBLE_RADIUS


def _and_paths():
    """
    2-input AND gate.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()
    tip = _and_shape(stroke_path, AND_MID, AND_RADIUS)
    _add_line(stroke_path, -1.0, -1.0, GATE_LEFT, -0.40)
    _add_line(stroke_path, -1.0, 1.0, GATE_LEFT, 0.40)
    _add_line(stroke_path, tip, 0.0, 1.0, 0.0)
    _supply_leads(stroke_path, GATE_TOP, GATE_BOTTOM)

    return (stroke_path, QPainterPath())


def _nand_paths():
    """
    2-input NAND gate: AND with an output bubble.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()
    fill_path = QPainterPath()
    tip = _and_shape(stroke_path, NAND_MID, NAND_RADIUS)
    lead = _output_bubble(fill_path, tip)
    _add_line(stroke_path, -1.0, -1.0, GATE_LEFT, -0.40)
    _add_line(stroke_path, -1.0, 1.0, GATE_LEFT, 0.40)
    _add_line(stroke_path, lead, 0.0, 1.0, 0.0)
    _supply_leads(stroke_path, GATE_TOP, GATE_BOTTOM)

    return (stroke_path, fill_path)


def _or_paths():
    """
    2-input OR gate.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()
    _or_shape(stroke_path, 0.85)
    _add_line(stroke_path, -1.0, -1.0, -0.48, -0.42)
    _add_line(stroke_path, -1.0, 1.0, -0.48, 0.42)
    _add_line(stroke_path, 0.85, 0.0, 1.0, 0.0)
    _supply_leads(stroke_path, -0.55, 0.55)

    return (stroke_path, QPainterPath())


def _nor_paths():
    """
    2-input NOR gate: OR with an output bubble.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()
    fill_path = QPainterPath()
    _or_shape(stroke_path, 0.62)
    lead = _output_bubble(fill_path, 0.62)
    _add_line(stroke_path, -1.0, -1.0, -0.48, -0.42)
    _add_line(stroke_path, -1.0, 1.0, -0.48, 0.42)
    _add_line(stroke_path, lead, 0.0, 1.0, 0.0)
    _supply_leads(stroke_path, -0.55, 0.55)

    return (stroke_path, fill_path)


def _xor_paths():
    """
    2-input XOR gate: OR plus a second curve on the input side.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()
    _or_shape(stroke_path, 0.85)
    stroke_path.moveTo(-0.75, GATE_TOP)
    stroke_path.quadTo(-0.40, 0.0, -0.75, GATE_BOTTOM)
    _add_line(stroke_path, -1.0, -1.0, -0.70, -0.42)
    _add_line(stroke_path, -1.0, 1.0, -0.70, 0.42)
    _add_line(stroke_path, 0.85, 0.0, 1.0, 0.0)
    _supply_leads(stroke_path, -0.55, 0.55)

    return (stroke_path, QPainterPath())


def _one_input_paths(left, apex, half, bubble):
    """
    Triangle with one input on the left, supplies above and below.

    :param bubble: Draw a filled output bubble when True.
    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()
    fill_path = QPainterPath()
    stroke_path.moveTo(left, -half)
    stroke_path.lineTo(apex, 0.0)
    stroke_path.lineTo(left, half)
    stroke_path.closeSubpath()
    _add_line(stroke_path, -1.0, 0.0, left, 0.0)
    edge = half * (apex - 0.0) / (apex - left)
    _supply_leads(stroke_path, -edge, edge)

    if bubble:
        lead = _output_bubble(fill_path, apex)
        _add_line(stroke_path, lead, 0.0, 1.0, 0.0)
    else:
        _add_line(stroke_path, apex, 0.0, 1.0, 0.0)

    return (stroke_path, fill_path)


def _not_paths():
    """
    NOT gate.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    return _one_input_paths(NOT_LEFT, NOT_APEX, NOT_HALF, True)


def _buffer_gate_paths():
    """
    Non-inverting logic buffer.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    return _one_input_paths(BLOCK_LEFT, BLOCK_APEX, BLOCK_HALF, False)


def _amp_block_paths(feedback):
    """
    Amplifier-block triangle. ``feedback`` draws the follower's loop.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path, fill_path = _one_input_paths(
        BLOCK_LEFT, BLOCK_APEX, BLOCK_HALF, False
    )

    if feedback:
        _add_line(stroke_path, 0.15, 0.06, 0.15, -0.08)
        _add_line(stroke_path, 0.15, -0.08, -0.10, -0.08)

    return (stroke_path, fill_path)


def _follower_paths():
    """
    Voltage follower: one input and an internal feedback loop.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    return _amp_block_paths(True)


def _plain_amp_paths():
    """
    Inverting or non-inverting amplifier block. The sign is a glyph.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    return _amp_block_paths(False)


_OPAMP_KINDS = (
    "opamp_generic", "opamp_741", "opamp_lm358", "opamp_tl072",
    "opamp_ne5532", "comparator",
)

_SYMBOL_BUILDERS = {
    "resistor": _resistor_paths,
    "capacitor": _capacitor_paths,
    "capacitor_polarized": _polarized_capacitor_paths,
    "inductor": _inductor_paths,
    "dc_source": _dc_source_paths,
    "ac_source": _ac_source_paths,
    "current_source": _current_source_paths,
    "diode": _diode_paths,
    "led": _led_paths,
    "npn": _npn_paths,
    "pnp": _pnp_paths,
    "ground": _ground_paths,
    "gate_and": _and_paths,
    "gate_nand": _nand_paths,
    "gate_or": _or_paths,
    "gate_nor": _nor_paths,
    "gate_xor": _xor_paths,
    "gate_not": _not_paths,
    "gate_buffer": _buffer_gate_paths,
    "follower": _follower_paths,
    "inverting_amp": _plain_amp_paths,
    "noninverting_amp": _plain_amp_paths,
}
_SYMBOL_BUILDERS.update({kind: _opamp_paths for kind in _OPAMP_KINDS})

_OPAMP_GLYPHS = (
    ((OPAMP_SIGN_X, -OPAMP_SIGN_Y), _opamp_minus_glyph_path),
    ((OPAMP_SIGN_X, OPAMP_SIGN_Y), _opamp_plus_glyph_path),
)

# Glyphs drawn inside a body that must read the same at every rotation
# (Billie: the AC sine always stays horizontal; a "-" turned 90 degrees
# would read as "|"). Each is built around its own (0, 0), turned back by
# the part's rotation and moved to its centre (body-centre coordinates),
# so the item's own rotation leaves it upright where it belongs.
_AMP_MINUS = (((-0.28, 0.0), _opamp_minus_glyph_path),)
_AMP_PLUS = (((-0.28, 0.0), _opamp_plus_glyph_path),)

_UPRIGHT_GLYPHS = {
    "ac_source": (((0.0, 0.0), _sine_glyph_path),),
    "inverting_amp": _AMP_MINUS,
    "noninverting_amp": _AMP_PLUS,
    "follower": _AMP_PLUS,
}
_UPRIGHT_GLYPHS.update({kind: _OPAMP_GLYPHS for kind in _OPAMP_KINDS})

ALLOWED_SYMBOL_ROTATIONS = (0, 90, 180, 270)


def build_symbol_paths(kind, rotation=0):
    """
    Build the symbol paths for one component kind, in pitch units.

    A new pair of paths is returned on every call, so callers may change
    or transform them freely. The paths are unrotated; the caller rotates
    them by the part's rotation. Pass that same rotation here so glyphs
    that must stay upright (the AC sine) are pre-turned the other way.

    :param kind: Component kind, a key of COMPONENT_DEFINITIONS.
    :type kind: str
    :param rotation: The part's rotation in degrees: 0, 90, 180 or 270.
    :type rotation: int
    :returns: (stroke_path, fill_path)
    :rtype: tuple
    :raises ComponentError: If the kind or the rotation is not valid.
    :raises NotImplementedError: If the kind has no symbol yet (Step 5).
    """
    if not isinstance(kind, str) or kind not in COMPONENT_DEFINITIONS:
        raise ComponentError(f"Unknown component kind {kind!r}.")

    if kind not in _SYMBOL_BUILDERS:
        raise NotImplementedError(
            f"The {kind} symbol is not drawn yet (planned for Step 5)."
        )

    if (isinstance(rotation, bool) or not isinstance(rotation, int) or
            rotation not in ALLOWED_SYMBOL_ROTATIONS):
        raise ComponentError(
            f"Symbol rotation must be 0, 90, 180 or 270, not {rotation!r}."
        )

    stroke_path, fill_path = _SYMBOL_BUILDERS[kind]()

    for (center_x, center_y), glyph_builder in _UPRIGHT_GLYPHS.get(kind, ()):
        to_place = QTransform().translate(center_x, center_y).rotate(-rotation)
        stroke_path.addPath(to_place.map(glyph_builder()))

    to_anchor = _get_anchor_transform(kind)

    return (to_anchor.map(stroke_path), to_anchor.map(fill_path))


def get_body_rect(kind):
    """
    Return a copy of the body rectangle for one kind, in pitch units.

    :param kind: Component kind.
    :type kind: str
    :returns: Body rectangle (a copy, safe to change).
    :rtype: QRectF
    :raises ComponentError: If the kind is unknown.
    :raises NotImplementedError: If the kind has no symbol yet (Step 5).
    """
    if not isinstance(kind, str) or kind not in COMPONENT_DEFINITIONS:
        raise ComponentError(f"Unknown component kind {kind!r}.")

    if kind not in BODY_RECTS:
        raise NotImplementedError(
            f"The {kind} symbol is not drawn yet (planned for Step 5)."
        )

    return _get_anchor_transform(kind).mapRect(BODY_RECTS[kind])


def get_body_path(kind):
    """
    Return the exact body area of one kind as a path, in pitch units.

    This is the triangle for op-amps and the body rectangle for every other
    kind. The item fills it to hide the grid and uses it as the click area.

    :param kind: Component kind.
    :type kind: str
    :returns: New path, shifted to the anchor like the symbol.
    :rtype: QPainterPath
    :raises ComponentError: If the kind is unknown.
    """
    body_rect = get_body_rect(kind)
    body_path = QPainterPath()

    if kind in BODY_POLYGONS:
        body_path.addPolygon(
            _get_anchor_transform(kind).map(BODY_POLYGONS[kind]())
        )
        body_path.closeSubpath()
    else:
        body_path.addRect(body_rect)

    return body_path


def _get_anchor_transform(kind):
    """
    Return the shift from body-centre coordinates to anchor coordinates.

    :param kind: Known component kind.
    :type kind: str
    :returns: Translation by the unrotated body centre offset.
    :rtype: QTransform
    """
    half_dx, half_dy = COMPONENT_DEFINITIONS[kind]["body_center_half_steps"]

    return QTransform().translate(half_dx / 2, half_dy / 2)
