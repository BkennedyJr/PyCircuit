"""
DC voltages and currents, without ngspice.

Modified nodal analysis for resistors, capacitors, inductors and
sources. A capacitor is an open. An inductor is a short. An AC source
uses its offset, which is what a DC operating point sees. Simulate >
DC Operating Point uses this for those parts. Anything else still
goes to ngspice when that library is installed. The oscilloscope,
Bode and the FFT still call ngspice.
"""

import numpy as np

from core.components import (
    COMPONENT_DEFINITIONS,
    Component,
    ComponentCollection,
)
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

_NO_GROUND = "Add a ground part before the DC voltages can be found."
_NO_SOLUTION = (
    "This circuit has no single DC solution. A node may be floating, "
    "or voltage sources may form a loop."
)


class DcOperatingPoint:
    """
    Solved DC voltages and the current through each covered part.

    A voltage source's current leaves its positive pin. A positive
    current means the source is supplying the circuit. A current
    source's current leaves its out pin. A resistor's or inductor's
    current enters pin 1 and leaves pin 2. A capacitor's current is 0.

    :param voltages: Volts at each grid point on a solved node.
    :type voltages: dict
    :param currents: Amps through each part, by reference.
    :type currents: dict
    """

    def __init__(self, voltages, currents):
        self.voltages = dict(voltages)
        self.currents = dict(currents)

    def voltage_at(self, identifier):
        """
        Return the DC voltage at one grid point.

        :param identifier: Connection-point identifier.
        :type identifier: str
        :rtype: float
        :raises SimulationError: If that point is not on a solved node.
        """
        if identifier not in self.voltages:
            raise SimulationError(f"{identifier} is not connected.")

        return self.voltages[identifier]

    def current_through(self, reference):
        """
        Return the DC current through one part.

        :param reference: Part reference, such as ``R1``.
        :type reference: str
        :rtype: float
        :raises SimulationError: If that part was not solved.
        """
        if reference not in self.currents:
            raise SimulationError(
                f"{reference} has no DC current in this solution."
            )

        return self.currents[reference]


def dc_circuit_is_covered(components):
    """
    True when every part is one ``solve_dc`` can stamp.

    A ComponentCollection is accepted. This does not solve the circuit.

    :param components: Placed parts, or a ComponentCollection.
    :rtype: bool
    :raises ComponentError: If an item is not a Component.
    """
    if isinstance(components, ComponentCollection):
        components = components.get_components()

    parts = _parts(components)

    return all(part.kind in _COVERED for part in parts)


def solve_dc(components, wire_collection, connection_grid):
    """
    Solve the DC operating point of one circuit.

    :param components: Placed parts.
    :type components: iterable of Component
    :param wire_collection: Wires. A bridged point is not joined.
    :type wire_collection: WireCollection
    :param connection_grid: Grid whose net labels join same-named points.
    :type connection_grid: ConnectionGrid
    :rtype: DcOperatingPoint
    :raises ComponentError: If an argument has the wrong type.
    :raises SimulationError: If the circuit has no ground, a part this
        solver does not cover, or no single DC solution.
    """
    parts = _parts(components)
    _require_wire_collection(wire_collection)
    _require_grid(connection_grid)
    _require_covered(parts)

    if not any(part.kind == "ground" for part in parts):
        raise SimulationError(_NO_GROUND)

    nets = _nets(parts, wire_collection, connection_grid)
    stamps = [
        _stamp(part, nets) for part in parts if part.kind != "ground"
    ]
    node_voltages, currents = _solve(stamps)
    _resistor_currents(stamps, node_voltages, currents)
    voltages = _point_voltages(nets, parts, stamps, node_voltages)

    return DcOperatingPoint(voltages, currents)


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


def _require_covered(parts):
    for part in parts:
        if part.kind in _COVERED:
            continue

        name = COMPONENT_DEFINITIONS[part.kind]["display_name"].lower()
        raise SimulationError(
            f"The DC solver does not cover a {name} yet. It covers "
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


def _stamp(part, nets):
    kind = part.kind

    if kind == "resistor":
        return (
            "R", part.reference, _node(nets, _pin(part, "1")),
            _node(nets, _pin(part, "2")), float(part.value),
        )

    if kind in ("capacitor", "capacitor_polarized"):
        first_name, second_name = _end_names(kind)
        return (
            "C", part.reference, _node(nets, _pin(part, first_name)),
            _node(nets, _pin(part, second_name)),
        )

    if kind == "inductor":
        # The branch current is injected at the first node. Pin 2 is
        # first so a positive current enters pin 1 and leaves pin 2.
        return (
            "L", part.reference, _node(nets, _pin(part, "2")),
            _node(nets, _pin(part, "1")),
        )

    if kind == "dc_source":
        return (
            "V", part.reference, _node(nets, _pin(part, "plus")),
            _node(nets, _pin(part, "minus")), float(part.value),
        )

    if kind == "ac_source":
        return (
            "V", part.reference, _node(nets, _pin(part, "plus")),
            _node(nets, _pin(part, "minus")),
            float(part.parameter_values["offset"]),
        )

    return (
        "I", part.reference, _node(nets, _pin(part, "out")),
        _node(nets, _pin(part, "in")), float(part.value),
    )


def _solve(stamps):
    """
    Return ``(voltage by node id, current by reference)``.

    The branch current of a voltage source or an inductor leaves the
    first stamped pin and enters the second.
    """
    nodes = []
    branches = []

    for stamp in stamps:
        for node in stamp[2:4]:
            if node != "0" and node not in nodes:
                nodes.append(node)

        if stamp[0] in ("V", "L"):
            branches.append(stamp[1])

    order = nodes + branches
    count = len(order)
    matrix = np.zeros((count, count))
    vector = np.zeros(count)
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

        if kind == "R":
            ohms = stamp[4]
            conductance = 1.0 / ohms
            add(left, left, conductance)
            add(right, right, conductance)
            add(left, right, -conductance)
            add(right, left, -conductance)
            continue

        if kind == "C":
            currents[reference] = 0.0
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

        volts = 0.0 if kind == "L" else stamp[4]
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
        return {"0": 0.0}, currents

    try:
        solved = np.linalg.solve(matrix, vector)
    except np.linalg.LinAlgError as error:
        raise SimulationError(_NO_SOLUTION) from error

    if not np.allclose(matrix @ solved, vector, rtol=1e-6, atol=1e-9):
        raise SimulationError(_NO_SOLUTION)

    voltages = {"0": 0.0}

    for node in nodes:
        voltages[node] = float(solved[index[node]])

    for reference in branches:
        currents[reference] = float(solved[index[reference]])

    return voltages, currents


def _resistor_currents(stamps, node_voltages, currents):
    for stamp in stamps:
        if stamp[0] != "R":
            continue

        reference, left, right, ohms = stamp[1], stamp[2], stamp[3], stamp[4]
        currents[reference] = (
            node_voltages[left] - node_voltages[right]
        ) / ohms


def _point_voltages(nets, parts, stamps, node_voltages):
    found = {}

    for part in parts:
        if part.kind != "ground":
            continue

        for identifier in part.get_pin_identifiers():
            for point in nets.get_points(identifier):
                found[point] = 0.0

    for stamp in stamps:
        for node in stamp[2:4]:
            if node == "0":
                continue

            for point in nets.get_points(node):
                found[point] = node_voltages[node]

    return found
