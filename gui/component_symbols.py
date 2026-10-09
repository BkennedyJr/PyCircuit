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
BODY_POLYGONS = {
    "opamp_generic": _opamp_triangle,
    "opamp_741": _opamp_triangle,
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
    "opamp_generic": _opamp_paths,
    "opamp_741": _opamp_paths,
}

_OPAMP_GLYPHS = (
    ((OPAMP_SIGN_X, -OPAMP_SIGN_Y), _opamp_minus_glyph_path),
    ((OPAMP_SIGN_X, OPAMP_SIGN_Y), _opamp_plus_glyph_path),
)

# Glyphs drawn inside a body that must read the same at every rotation
# (Billie: the AC sine always stays horizontal; a "-" turned 90 degrees
# would read as "|"). Each is built around its own (0, 0), turned back by
# the part's rotation and moved to its centre (body-centre coordinates),
# so the item's own rotation leaves it upright where it belongs.
_UPRIGHT_GLYPHS = {
    "ac_source": (((0.0, 0.0), _sine_glyph_path),),
    "opamp_generic": _OPAMP_GLYPHS,
    "opamp_741": _OPAMP_GLYPHS,
}

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
