"""
Four small circuits for File > Examples.

Each one is a normal circuit the user can edit. The numbers below are
the hand calculation.

Divider: 10 V across 10k + 10k is 5 V in the middle, and
10 V / 20k = 0.5 mA.

RC low-pass: 1 V peak at 1 kHz into 1k and 159 nF.
``2*pi*1e3*1e3*159e-9`` is 0.999, so the capacitor is
``1/sqrt(1 + 0.998**2)`` V peak (about 0.707 V) at about -45 degrees.

Unity-gain buffer: the follower copies a 1 V peak, 1 kHz sine, so the
output is that same sine. Supplies are +12 V and -12 V. The 10k load
does not change an ideal follower.

AND gate: both inputs and VCC are 5 V, GND is ground, and a 10k load
is on the output. The output is 5 V. A logic gate has no V(s), so this
sheet has no probe box.
"""

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.probes import ProbeCollection
from core.project_io import Workbook
from core.wires import WireCollection


def _point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


class _Sheet:
    """One example while it is being placed."""

    def __init__(self, rows, columns):
        self.grid = ConnectionGrid(rows, columns)
        self.parts = ComponentCollection()
        self.wires = WireCollection()
        self.probes = ProbeCollection()

    def place(self, kind, row, column, value="", parameters=None, rotation=0):
        """
        Place one part.

        :rtype: core.components.Component
        """
        return self.parts.add_component(
            kind,
            row,
            column,
            value,
            self.grid,
            rotation=rotation,
            parameter_texts=parameters,
        )

    def link(self, start, end):
        """
        Draw one straight wire.

        :param start: ``(row, column)``.
        :param end: ``(row, column)``.
        :rtype: core.wires.Wire
        """
        return self.wires.add_wire(
            _point(*start), _point(*end), self.grid
        )

    def probe(self, row, column):
        """
        Put a Direct probe on one point.

        :rtype: core.probes.Probe
        """
        return self.probes.add_voltage(_point(row, column), self.grid)

    def workbook(self):
        """
        Return the finished sheet.

        :rtype: core.project_io.Workbook
        """
        return Workbook(self.grid, self.parts, self.wires, self.probes)


def _divider():
    """
    10 V, two 10k resistors, probe on the 5 V middle.

    :rtype: core.project_io.Workbook
    """
    sheet = _Sheet(8, 8)
    sheet.place("ground", 6, 2)
    sheet.place("dc_source", 4, 2, "10")
    sheet.place("resistor", 4, 3, "10k")
    sheet.place("resistor", 4, 4, "10k")
    sheet.link((5, 2), (6, 2))
    sheet.link((4, 2), (4, 3))
    sheet.link((4, 5), (6, 5))
    sheet.link((6, 2), (6, 5))
    sheet.probe(4, 4)
    return sheet.workbook()


def _rc():
    """
    1 V peak at 1 kHz, 1k, 159 nF to ground. Probe on the capacitor.

    :rtype: core.project_io.Workbook
    """
    sheet = _Sheet(8, 8)
    sheet.place("ground", 6, 2)
    sheet.place(
        "ac_source", 4, 2, "1", {"frequency": "1k"}
    )
    sheet.place("resistor", 4, 3, "1k")
    sheet.place("capacitor", 4, 4, "159n")
    sheet.link((4, 2), (4, 3))
    sheet.link((5, 2), (6, 2))
    sheet.link((4, 5), (6, 5))
    sheet.link((6, 2), (6, 5))
    sheet.probe(4, 4)
    return sheet.workbook()


def _buffer():
    """
    Unity-gain follower of a 1 V, 1 kHz sine, with probes on both ends.

    The follower sits at (6, 6): input (6, 5), output (6, 7),
    V+ (5, 6), V- (7, 6). Each supply is turned so its negative pin
    points right, off the supply wire.

    :rtype: core.project_io.Workbook
    """
    sheet = _Sheet(12, 12)
    sheet.place("follower", 6, 6)
    sheet.place("ac_source", 6, 2, "1", {"frequency": "1k"})
    sheet.place("dc_source", 5, 8, "12", rotation=270)
    sheet.place("dc_source", 7, 8, "-12", rotation=270)
    sheet.place("resistor", 6, 8, "10k")
    sheet.place("ground", 11, 11)
    sheet.link((6, 2), (6, 5))
    sheet.link((7, 2), (11, 2))
    sheet.link((11, 2), (11, 11))
    sheet.link((5, 6), (5, 8))
    sheet.link((7, 6), (7, 8))
    sheet.link((5, 9), (11, 9))
    sheet.link((7, 9), (11, 9))
    sheet.link((11, 9), (11, 11))
    sheet.link((6, 7), (6, 8))
    sheet.link((6, 9), (11, 9))
    sheet.probe(6, 2)
    sheet.probe(6, 7)
    return sheet.workbook()


def _and_gate():
    """
    AND gate with both inputs at 5 V. The output is 5 V into 10k.

    The gate sits at (6, 6): A (5, 5), B (7, 5), Y (6, 7),
    VCC (5, 6), GND (7, 6).

    :rtype: core.project_io.Workbook
    """
    sheet = _Sheet(12, 12)
    sheet.place("gate_and", 6, 6)
    sheet.place("dc_source", 5, 8, "5", rotation=270)
    sheet.place("resistor", 6, 8, "10k")
    sheet.place("ground", 11, 11)
    sheet.link((5, 6), (5, 8))
    sheet.link((5, 5), (5, 6))
    sheet.link((7, 5), (7, 2))
    sheet.link((7, 2), (3, 2))
    sheet.link((3, 2), (3, 8))
    sheet.link((3, 8), (5, 8))
    sheet.link((6, 7), (6, 8))
    sheet.link((6, 9), (11, 9))
    sheet.link((5, 9), (11, 9))
    sheet.link((7, 6), (7, 10))
    sheet.link((7, 10), (11, 10))
    sheet.link((11, 10), (11, 11))
    sheet.link((11, 9), (11, 11))
    return sheet.workbook()


# id, menu label, what the tooltip says, builder.
EXAMPLES = (
    (
        "divider",
        "Voltage divider",
        "10 V across two 10k resistors. The middle is 5 V.",
        _divider,
    ),
    (
        "rc",
        "RC low-pass",
        "1 V at 1 kHz into 1k and 159 nF.",
        _rc,
    ),
    (
        "buffer",
        "Unity-gain buffer",
        "A follower copies a 1 V, 1 kHz sine.",
        _buffer,
    ),
    (
        "and",
        "AND gate",
        "Both inputs are 5 V, so the output is 5 V.",
        _and_gate,
    ),
)


def example_ids():
    """
    Return the example ids in menu order.

    :rtype: tuple
    """
    return tuple(example_id for example_id, *_rest in EXAMPLES)


def build_example(example_id):
    """
    Build one example circuit.

    :param example_id: ``divider``, ``rc``, ``buffer`` or ``and``.
    :type example_id: str
    :rtype: core.project_io.Workbook
    :raises ComponentError: If the id is not one of the four.
    """
    for stored_id, _label, _tip, builder in EXAMPLES:
        if stored_id == example_id:
            return builder()

    names = ", ".join(example_ids())
    raise ComponentError(
        f"Unknown example {example_id!r}. Examples: {names}."
    )
