"""
AC voltages and currents at one frequency, without ngspice.

Modified nodal analysis for the same parts as the DC solver. A
resistor stays 1/R. A capacitor's admittance is j*omega*C. An
inductor's is 1/(j*omega*L). A DC voltage source is a short (0 V).
A DC current source is an open (0 A). An AC voltage source is its
peak and phase; the offset is left out, because that is the DC
part. Bode still calls ngspice.
"""

import cmath
import math

import numpy as np

from core.components import COMPONENT_DEFINITIONS, Component
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError, SimulationError
from core.wires import WireCollection, WireNets

_COVERED = (
    "resistor",
    "capacitor",
    "capacitor_polarized",
    "inductor",
    "dc_source",
    "ac_source",
    "current_source",
    "ground",
)

_NO_GROUND = "Add a ground part before the AC voltages can be found."
_NO_SOLUTION = (
    "This circuit has no single AC solution. A node may be floating, "
    "or voltage sources may form a loop."
)


class AcSolution:
    """
    Solved AC voltages and the current through each covered part.

    Voltages and currents are complex peak phasors. Angle is in
    radians, from the positive real axis. A voltage source's current
    leaves its positive pin. A current source's current leaves its
    out pin. A resistor's, capacitor's or inductor's current enters
    pin 1 and leaves pin 2.

    :param frequency_hz: Frequency this solution was run at.
    :type frequency_hz: float
    :param voltages: Volts at each grid point on a solved node.
    :type voltages: dict
    :param currents: Amps through each part, by reference.
    :type currents: dict
    """

    def __init__(self, frequency_hz, voltages, currents):
        self.frequency_hz = float(frequency_hz)
        self.voltages = dict(voltages)
        self.currents = dict(currents)

    def voltage_at(self, identifier):
        """
        Return the AC voltage at one grid point.

        :param identifier: Connection-point identifier.
        :type identifier: str
        :rtype: complex
        :raises SimulationError: If that point is not on a solved node.
        """
        if identifier not in self.voltages:
            raise SimulationError(f"{identifier} is not connected.")

        return self.voltages[identifier]

    def current_through(self, reference):
        """
        Return the AC current through one part.

        :param reference: Part reference, such as ``R1``.
        :type reference: str
        :rtype: complex
        :raises SimulationError: If that part was not solved.
        """
        if reference not in self.currents:
            raise SimulationError(
                f"{reference} has no AC current in this solution."
            )

        return self.currents[reference]


def solve_ac(components, wire_collection, connection_grid, frequency_hz):
    """
    Solve the AC phasors of one circuit at one frequency.

    :param components: Placed parts.
    :type components: iterable of Component
    :param wire_collection: Wires. A bridged point is not joined.
    :type wire_collection: WireCollection
    :param connection_grid: Grid whose net labels join same-named points.
    :type connection_grid: ConnectionGrid
    :param frequency_hz: Frequency in hertz, greater than 0.
    :type frequency_hz: float
    :rtype: AcSolution
    :raises ComponentError: If an argument has the wrong type, or the
        frequency is not a number of hertz greater than 0.
    :raises SimulationError: If the circuit has no ground, a part this
        solver does not cover, or no single AC solution.
    """
    parts = _parts(components)
    _require_wire_collection(wire_collection)
    _require_grid(connection_grid)
    frequency = _require_frequency(frequency_hz)
    _require_covered(parts)

    if not any(part.kind == "ground" for part in parts):
        raise SimulationError(_NO_GROUND)

    omega = 2.0 * math.pi * frequency
    nets = _nets(parts, wire_collection, connection_grid)
    stamps = [
        _stamp(part, nets, omega)
        for part in parts
        if part.kind != "ground"
    ]
    node_voltages, currents = _solve(stamps)
    _admittance_currents(stamps, node_voltages, currents)
    voltages = _point_voltages(nets, parts, stamps, node_voltages)

    return AcSolution(frequency, voltages, currents)


def _parts(components):
    parts = []

    for component in components:
        if not isinstance(component, Component):
            raise ComponentError(
                f"Expected a Component, not {component!r}."
            )

        parts.append(component)

    return parts


def _require_wire_collection(wire_collection):
    if not isinstance(wire_collection, WireCollection):
        raise ComponentError(
            "Expected a WireCollection, not "
            f"{type(wire_collection).__name__}."
        )


def _require_grid(connection_grid):
    if not isinstance(connection_grid, ConnectionGrid):
        raise ComponentError(
            "Expected a ConnectionGrid, not "
            f"{type(connection_grid).__name__}."
        )


def _require_frequency(frequency_hz):
    if (isinstance(frequency_hz, bool) or
            not isinstance(frequency_hz, (int, float))):
        raise ComponentError(
            f"Frequency {frequency_hz!r} is not a number of hertz. "
            "Use a number greater than 0, for example 1000."
        )

    if frequency_hz <= 0:
        raise ComponentError(
            f"Frequency {frequency_hz} Hz is not valid. Use a frequency "
            "greater than 0."
        )

    return float(frequency_hz)


def _require_covered(parts):
    for part in parts:
        if part.kind in _COVERED:
            continue

        name = COMPONENT_DEFINITIONS[part.kind]["display_name"].lower()
        raise SimulationError(
            f"The AC solver does not cover a {name} yet. It covers "
            "resistors, capacitors, inductors, DC voltage sources, "
            "AC voltage sources and current sources."
        )


def _nets(parts, wire_collection, connection_grid):
    grounds = []
    labels = []

    for part in parts:
        if part.kind == "ground":
            grounds.extend(part.get_pin_identifiers())

    for identifier, name in connection_grid.get_net_labels().items():
        labels.append((identifier, name))

    return WireNets(wire_collection, grounds, net_labels=labels)


def _node(nets, identifier):
    if nets.is_ground(identifier):
        return "0"

    return nets.get_points(identifier)[0]


def _pin(part, name):
    for pin_name, row_number, column_number in part.get_pin_positions():
        if pin_name == name:
            return ConnectionGrid.build_connection_point_identifier(
                row_number, column_number
            )

    raise ComponentError(f"{part.reference} has no pin {name!r}.")


def _end_names(kind):
    if kind == "capacitor_polarized":
        return ("plus", "minus")

    return ("1", "2")


def _stamp(part, nets, omega):
    kind = part.kind

    if kind == "resistor":
        return (
            "Y", part.reference, _node(nets, _pin(part, "1")),
            _node(nets, _pin(part, "2")), 1.0 / float(part.value),
        )

    if kind in ("capacitor", "capacitor_polarized"):
        first_name, second_name = _end_names(kind)
        return (
            "Y", part.reference, _node(nets, _pin(part, first_name)),
            _node(nets, _pin(part, second_name)),
            1j * omega * float(part.value),
        )

    if kind == "inductor":
        return (
            "Y", part.reference, _node(nets, _pin(part, "1")),
            _node(nets, _pin(part, "2")),
            1.0 / (1j * omega * float(part.value)),
        )

    if kind == "dc_source":
        # A DC source is a short for AC: 0 V between its pins.
        return (
            "V", part.reference, _node(nets, _pin(part, "plus")),
            _node(nets, _pin(part, "minus")), 0j,
        )

    if kind == "ac_source":
        phase = math.radians(float(part.parameter_values["phase"]))
        phasor = complex(part.value) * cmath.exp(1j * phase)
        return (
            "V", part.reference, _node(nets, _pin(part, "plus")),
            _node(nets, _pin(part, "minus")), phasor,
        )

    return (
        "I", part.reference, _node(nets, _pin(part, "out")),
        _node(nets, _pin(part, "in")), 0j,
    )


def _solve(stamps):
    """
    Return ``(voltage by node id, current by reference)``.

    The branch current of a voltage source leaves the first stamped
    pin and enters the second.
    """
    nodes = []
    branches = []

    for stamp in stamps:
        for node in stamp[2:4]:
            if node != "0" and node not in nodes:
                nodes.append(node)

        if stamp[0] == "V":
            branches.append(stamp[1])

    order = nodes + branches
    count = len(order)
    matrix = np.zeros((count, count), dtype=complex)
    vector = np.zeros(count, dtype=complex)
    index = {name: position for position, name in enumerate(order)}
    currents = {}

    def at(name):
        if name == "0":
            return None

        return index[name]

    def add(row_name, column_name, value):
        row = at(row_name)
        column = at(column_name)

        if row is None or column is None:
            return

        matrix[row, column] += value

    for stamp in stamps:
        kind = stamp[0]
        reference = stamp[1]
        left = stamp[2]
        right = stamp[3]

        if kind == "Y":
            admittance = stamp[4]
            add(left, left, admittance)
            add(right, right, admittance)
            add(left, right, -admittance)
            add(right, left, -admittance)
            continue

        if kind == "I":
            amps = stamp[4]
            outgoing = at(left)

            if outgoing is not None:
                vector[outgoing] += amps

            incoming = at(right)

            if incoming is not None:
                vector[incoming] -= amps

            currents[reference] = amps
            continue

        volts = stamp[4]
        branch = at(reference)
        plus_row = at(left)
        minus_row = at(right)

        if plus_row is not None:
            matrix[plus_row, branch] -= 1.0
            matrix[branch, plus_row] += 1.0

        if minus_row is not None:
            matrix[minus_row, branch] += 1.0
            matrix[branch, minus_row] -= 1.0

        vector[branch] = volts

    if count == 0:
        return {"0": 0j}, currents

    try:
        solved = np.linalg.solve(matrix, vector)
    except np.linalg.LinAlgError as error:
        raise SimulationError(_NO_SOLUTION) from error

    if not np.allclose(matrix @ solved, vector, rtol=1e-6, atol=1e-9):
        raise SimulationError(_NO_SOLUTION)

    voltages = {"0": 0j}

    for node in nodes:
        voltages[node] = complex(solved[index[node]])

    for reference in branches:
        currents[reference] = complex(solved[index[reference]])

    return voltages, currents


def _admittance_currents(stamps, node_voltages, currents):
    for stamp in stamps:
        if stamp[0] != "Y":
            continue

        reference, left, right, admittance = (
            stamp[1], stamp[2], stamp[3], stamp[4]
        )
        currents[reference] = (
            node_voltages[left] - node_voltages[right]
        ) * admittance


def _point_voltages(nets, parts, stamps, node_voltages):
    found = {}

    for part in parts:
        if part.kind != "ground":
            continue

        for identifier in part.get_pin_identifiers():
            for point in nets.get_points(identifier):
                found[point] = 0j

    for stamp in stamps:
        for node in stamp[2:4]:
            if node == "0":
                continue

            for point in nets.get_points(node):
                found[point] = node_voltages[node]

    return found
