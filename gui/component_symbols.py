"""
Standard schematic symbols drawn with QPainterPath.

Every symbol is built in pitch units: 1.0 is one grid step, the origin is
the part's anchor grid point, and y points down, the same as Qt. Lead ends
land exactly on the pin offsets in core.components.COMPONENT_DEFINITIONS,
so a symbol scaled by the grid spacing and rotated in 90-degree steps keeps
its pins on grid points.

Each builder returns two paths: a stroke path for lines and outlines, and a
fill path for solid shapes such as arrowheads. Keeping them apart means
open shapes like the resistor zigzag are never filled by accident.
"""

import math

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QPainterPath

from core.components import COMPONENT_DEFINITIONS
from core.exceptions import ComponentError

ARROW_HEAD_LENGTH = 0.08
ARROW_HEAD_HALF_WIDTH = 0.04

# Body area of each symbol, excluding the leads, in pitch units. The item
# paints this area in the background color and uses it as the click area.
BODY_RECTS = {
    "resistor": QRectF(-0.65, -0.25, 1.3, 0.5),
    "capacitor": QRectF(-0.15, -0.4, 0.3, 0.8),
    "inductor": QRectF(-0.65, -0.2, 1.3, 0.35),
    "ground": QRectF(-0.35, 0.25, 0.7, 0.35),
}


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

    The shaft goes into stroke_path and a filled triangular head with its
    tip at (x2, y2) goes into fill_path.

    :param stroke_path: Path that receives the shaft.
    :type stroke_path: QPainterPath
    :param fill_path: Path that receives the arrowhead.
    :type fill_path: QPainterPath
    :returns: None
    """
    _add_line(stroke_path, x1, y1, x2, y2)

    # Unit vector along the arrow, and the perpendicular for the head width.
    length = math.hypot(x2 - x1, y2 - y1)
    along_x = (x2 - x1) / length
    along_y = (y2 - y1) / length
    across_x = -along_y
    across_y = along_x

    base_x = x2 - along_x * ARROW_HEAD_LENGTH
    base_y = y2 - along_y * ARROW_HEAD_LENGTH

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


def _resistor_paths():
    """
    ANSI resistor: leads to +/-1 and a six-peak zigzag between them.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    _add_line(stroke_path, -1.0, 0.0, -0.6, 0.0)

    zigzag_points = [
        (-0.6, 0.0), (-0.5, -0.2), (-0.3, 0.2), (-0.1, -0.2),
        (0.1, 0.2), (0.3, -0.2), (0.5, 0.2), (0.6, 0.0),
    ]
    stroke_path.moveTo(QPointF(*zigzag_points[0]))

    for point in zigzag_points[1:]:
        stroke_path.lineTo(QPointF(*point))

    _add_line(stroke_path, 0.6, 0.0, 1.0, 0.0)

    return (stroke_path, QPainterPath())


def _capacitor_paths():
    """
    Non-polarized capacitor: two leads and two parallel plates.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    _add_line(stroke_path, -1.0, 0.0, -0.1, 0.0)
    _add_line(stroke_path, 0.1, 0.0, 1.0, 0.0)
    _add_line(stroke_path, -0.1, -0.35, -0.1, 0.35)
    _add_line(stroke_path, 0.1, -0.35, 0.1, 0.35)

    return (stroke_path, QPainterPath())


def _inductor_paths():
    """
    Inductor: two leads and four semicircular loops bulging upward.

    :returns: (stroke_path, fill_path)
    :rtype: tuple
    """
    stroke_path = QPainterPath()

    _add_line(stroke_path, -1.0, 0.0, -0.6, 0.0)

    # Each arc starts at its left end (180 degrees) and sweeps clockwise on
    # screen over the top to its right end, where the next arc begins.
    for loop_index in range(4):
        stroke_path.arcTo(
            QRectF(-0.6 + 0.3 * loop_index, -0.15, 0.3, 0.3),
            180,
            -180
        )

    _add_line(stroke_path, 0.6, 0.0, 1.0, 0.0)

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


_SYMBOL_BUILDERS = {
    "resistor": _resistor_paths,
    "capacitor": _capacitor_paths,
    "inductor": _inductor_paths,
    "ground": _ground_paths,
}


def build_symbol_paths(kind):
    """
    Build the symbol paths for one component kind, in pitch units.

    A new pair of paths is returned on every call, so callers may change
    or transform them freely.

    :param kind: Component kind, a key of COMPONENT_DEFINITIONS.
    :type kind: str
    :returns: (stroke_path, fill_path)
    :rtype: tuple
    :raises ComponentError: If the kind is unknown.
    :raises NotImplementedError: If the kind has no symbol yet (Step 5).
    """
    if not isinstance(kind, str) or kind not in COMPONENT_DEFINITIONS:
        raise ComponentError(f"Unknown component kind {kind!r}.")

    if kind not in _SYMBOL_BUILDERS:
        raise NotImplementedError(
            f"The {kind} symbol is not drawn yet (planned for Step 5)."
        )

    return _SYMBOL_BUILDERS[kind]()


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

    return QRectF(BODY_RECTS[kind])
