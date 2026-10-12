"""
Read a plotted trace at two cursors.

The value between two samples is the straight line between them. On a
log frequency axis that line is straight in log frequency, which is
how Bode draws it. The difference is B minus A.
"""

import math

from core.exceptions import ComponentError
from core.units import format_spice_number


def value_at(x_values, y_values, x):
    """
    Return the trace value at one cursor.

    Before the first sample the value is the first sample. After the
    last sample it is the last sample. On a sample it is that sample.
    Between two samples it is the straight line.

    :param x_values: Sample positions, in order or not.
    :param y_values: Sample values, one per position.
    :param x: Cursor position, in the same units as ``x_values``.
    :returns: Interpolated value.
    :rtype: float
    :raises ComponentError: If the trace is empty, the two lists differ
        in length, or a number is not finite.
    """
    pairs = _pairs(x_values, y_values)
    _require_finite(x, "A cursor has to sit on a finite position.")

    if x <= pairs[0][0]:
        return pairs[0][1]

    if x >= pairs[-1][0]:
        return pairs[-1][1]

    for index in range(1, len(pairs)):
        left_x, left_y = pairs[index - 1]
        right_x, right_y = pairs[index]

        if x > right_x:
            continue

        if x == right_x or right_x == left_x:
            return right_y if x == right_x else left_y

        portion = (x - left_x) / (right_x - left_x)
        return left_y + portion * (right_y - left_y)

    return pairs[-1][1]


def value_at_log_x(x_values, y_values, x):
    """
    Return the trace value where the plot's x axis is logarithmic.

    Positions at 0 or below are left out. The straight line is drawn
    against log10 of the position, matching a Bode frequency axis.

    :param x_values: Sample positions, such as hertz. Each one used
        must be above 0.
    :param y_values: Sample values, one per position.
    :param x: Cursor position, above 0.
    :returns: Interpolated value.
    :rtype: float
    :raises ComponentError: If the cursor or the trace is not on a
        positive position, or the trace itself is unreadable.
    """
    if len(x_values) != len(y_values):
        raise ComponentError(
            "The cursor trace has a different number of positions and values."
        )

    _require_finite(x, "A cursor on a log axis has to sit above 0.")

    if x <= 0:
        raise ComponentError("A cursor on a log axis has to sit above 0.")

    logged = []
    values = []

    for position, value in zip(x_values, y_values):
        if not math.isfinite(position) or position <= 0:
            continue

        logged.append(math.log10(position))
        values.append(value)

    if not logged:
        raise ComponentError("A cursor on a log axis needs a trace above 0.")

    return value_at(logged, values, math.log10(x))


def format_cursor_text(probe, first_x, second_x, x_unit, columns):
    """
    Describe cursor A, cursor B, and B minus A.

    :param probe: Trace name, such as ``P1``.
    :type probe: str
    :param first_x: Position of cursor A.
    :param second_x: Position of cursor B.
    :param x_unit: Unit for the positions, such as ``s`` or ``Hz``.
    :type x_unit: str
    :param columns: ``(value_at_a, value_at_b, unit)`` for each reading.
        An empty unit prints the number alone.
    :returns: Four lines of plain text.
    :rtype: str
    """
    delta_columns = tuple(
        (second - first, unit) for first, second, unit in columns
    )
    first_columns = tuple((first, unit) for first, _second, unit in columns)
    second_columns = tuple((second, unit) for _first, second, unit in columns)
    lines = (
        f"A is {_side(first_x, x_unit, first_columns)}.",
        f"B is {_side(second_x, x_unit, second_columns)}.",
        f"Difference is {_side(second_x - first_x, x_unit, delta_columns)}.",
        f"Trace {probe}.",
    )
    return "\n".join(lines)


def _side(position, x_unit, columns):
    parts = [_measure(position, x_unit)]
    parts.extend(_measure(value, unit) for value, unit in columns)
    return ", ".join(parts)


def _measure(value, unit):
    if unit in ("s", "Hz"):
        number = format_spice_number(value)
    else:
        number = f"{value:.3f}".rstrip("0").rstrip(".")

        if number in ("-0", ""):
            number = "0"

    if unit:
        return f"{number} {unit}"

    return number


def _pairs(x_values, y_values):
    if len(x_values) != len(y_values):
        raise ComponentError(
            "The cursor trace has a different number of positions and values."
        )

    if len(x_values) == 0:
        raise ComponentError("There is no trace to read at the cursors.")

    pairs = []

    for position, value in zip(x_values, y_values):
        _require_finite(position, "A cursor can only read a trace made of finite numbers.")
        _require_finite(value, "A cursor can only read a trace made of finite numbers.")
        pairs.append((float(position), float(value)))

    pairs.sort(key=lambda pair: pair[0])
    return pairs


def _require_finite(number, message):
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        raise ComponentError(message)

    if not math.isfinite(number):
        raise ComponentError(message)
