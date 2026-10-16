"""
DC voltages and currents, without ngspice.

Modified nodal analysis for every part on the schematic. A capacitor
is an open. An inductor is a short. An AC source uses its offset.
Diodes, LEDs and transistors use a Newton companion. Gates and a
limited op-amp hold an output voltage from the previous step. The
741 uses the behavioural stand-in (gain 100k, 1 Mohm, 75 ohm), not
the Logipipe transistor netlist. Simulate > DC Operating Point uses
this for every part. The oscilloscope, Bode and the FFT still call
ngspice.
"""

import numpy as np

from core.components import (
    COMPONENT_DEFINITIONS,
    Component,
    ComponentCollection,
)
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError, SimulationError
from core.spice_models import default_parameter_text
from core.subcircuit_models import (
    GENERIC_OPAMP_GAIN,
    GENERIC_OPAMP_INPUT_RESISTANCE,
    GENERIC_OPAMP_OUTPUT_RESISTANCE,
)
from core.units import parse_value
from core.wires import WireCollection, WireNets
from sim.dc_devices import (
    BjtDevice,
    ClampDevice,
    DiodeDevice,
    JfetDevice,
    LogicDevice,
    MosfetDevice,
)

_COVERED = tuple(COMPONENT_DEFINITIONS)

_NO_GROUND = "Add a ground part before the DC voltages can be found."
_NO_SOLUTION = (
    "This circuit has no single DC solution. A node may be floating, "
    "or voltage sources may form a loop."
)
_SHORT_OHMS = 1e-9
_OPEN_OHMS = 1e9
_SUPPLY_BLEED = 1e12
_ITERATIONS = 80
_BEHAVIOURAL_OPAMPS = (
    "opamp_lm358",
    "opamp_tl072",
    "opamp_ne5532",
    "opamp_tl081",
    "opamp_tl082",
    "opamp_lm324",
)
_LOGIC = {
    "gate_not": "not",
    "gate_buffer": "buf",
    "gate_and": "and",
    "gate_or": "or",
    "gate_nand": "nand",
    "gate_nor": "nor",
    "gate_xor": "xor",
}


class DcOperatingPoint:
    """
    Solved DC voltages and the current through each part.

    A voltage source's current leaves its positive pin. A positive
    current means the source is supplying the circuit. A current
    source's current leaves its out pin. A resistor's or inductor's
    current enters pin 1 and leaves pin 2. A capacitor's current is 0.
    A diode's current enters the anode. A transistor's current enters
    the collector or the drain. An op-amp's or gate's current leaves
    the output pin.

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
    fixed = []
    devices = []

    for part in parts:
        stamps, device = _compile(part, nets)
        fixed.extend(stamps)

        if device is not None:
            devices.append(device)

    node_voltages, currents = _operating_point(fixed, devices)

    for device in devices:
        amps = device.solved_current(node_voltages)

        if amps is not None:
            currents[device.reference] = amps

    currents = {
        reference: amps
        for reference, amps in currents.items()
        if not reference.startswith("@")
    }
    voltages = _point_voltages(nets, parts, node_voltages)

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
        raise SimulationError(f"The DC solver does not cover a {name}.")


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


def _ohms(value):
    if value <= 0.0:
        return _SHORT_OHMS

    return float(value)


def _card(model_name, spice_name, fallback):
    return parse_value(
        default_parameter_text(model_name, spice_name, fallback)
    )


def _compile(part, nets):
    """
    Return ``(fixed stamps, nonlinear device or None)``.
    """
    kind = part.kind
    reference = part.reference

    if kind == "ground":
        return [], None

    if kind in (
            "resistor", "capacitor", "capacitor_polarized",
            "inductor", "dc_source", "ac_source", "current_source",
    ):
        return [_passive(part, nets)], None

    if kind == "switch":
        ohms = (
            _SHORT_OHMS if part.parameter_values["state"] == "closed"
            else _OPEN_OHMS
        )

        return [(
            "R", reference, _node(nets, _pin(part, "1")),
            _node(nets, _pin(part, "2")), ohms,
        )], None

    if kind == "potentiometer":
        return _potentiometer(part, nets), None

    if kind == "transformer":
        return _transformer(part, nets), None

    if kind == "voltage_regulator":
        return _regulator(part, nets), None

    if kind == "timer_555":
        return _timer(part, nets), None

    if kind in ("diode", "led"):
        return _diode(part, nets)

    if kind in ("npn", "pnp"):
        return _bjt(part, nets)

    if kind in ("nmos", "pmos"):
        return _mosfet(part, nets)

    if kind in ("njfet", "pjfet"):
        return _jfet(part, nets)

    if kind in ("opamp_generic", "opamp_741") or kind in _BEHAVIOURAL_OPAMPS:
        return _opamp(part, nets)

    if kind == "follower":
        return _follower(part, nets), None

    if kind == "inverting_amp":
        return _inverting(part, nets), None

    if kind == "noninverting_amp":
        return _noninverting(part, nets), None

    if kind in _LOGIC or kind == "comparator":
        return _logic(part, nets)

    name = COMPONENT_DEFINITIONS[kind]["display_name"].lower()
    raise SimulationError(f"The DC solver does not cover a {name}.")


def _passive(part, nets):
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


def _potentiometer(part, nets):
    resistance = float(part.value)
    position = float(part.parameter_values["position"])
    top = _ohms((1.0 - position) * resistance)
    bottom = _ohms(position * resistance)
    pin_1 = _node(nets, _pin(part, "1"))
    pin_2 = _node(nets, _pin(part, "2"))
    wiper = _node(nets, _pin(part, "wiper"))

    return [
        ("R", part.reference, pin_1, wiper, top),
        ("R", f"@{part.reference}.b", wiper, pin_2, bottom),
    ]


def _transformer(part, nets):
    # V(s1) - V(s2) = n * (V(p1) - V(p2)). The branch current leaves
    # s1. The F source draws n times that current into p1.
    turns = float(part.value)
    p1 = _node(nets, _pin(part, "p1"))
    p2 = _node(nets, _pin(part, "p2"))
    s1 = _node(nets, _pin(part, "s1"))
    s2 = _node(nets, _pin(part, "s2"))
    reference = part.reference

    return [
        ("E", reference, s1, s2, p1, p2, turns),
        ("F", f"@{reference}.f", p2, p1, reference, turns),
    ]


def _regulator(part, nets):
    pin_in = _node(nets, _pin(part, "in"))
    ground = _node(nets, _pin(part, "gnd"))
    pin_out = _node(nets, _pin(part, "out"))

    return [
        ("V", part.reference, pin_out, ground, float(part.value)),
        ("R", f"@{part.reference}.rin", pin_in, ground, _SUPPLY_BLEED),
    ]


def _timer(part, nets):
    vcc = _node(nets, _pin(part, "VCC"))
    cont = _node(nets, _pin(part, "CONT"))
    ground = _node(nets, _pin(part, "GND"))
    third = f"@{part.reference}.third"

    return [
        ("R", part.reference, vcc, cont, 5e3),
        ("R", f"@{part.reference}.b", cont, third, 5e3),
        ("R", f"@{part.reference}.c", third, ground, 5e3),
    ]


def _diode(part, nets):
    anode = _node(nets, _pin(part, "anode"))
    cathode = _node(nets, _pin(part, "cathode"))

    if part.kind == "diode":
        saturation = float(part.parameter_values["is"])
        emission = float(part.parameter_values["n"])
        series = float(part.parameter_values["rs"])
    else:
        saturation = _card(part.value_text, "Is", "10f")
        emission = _card(part.value_text, "N", "1")
        series = _card(part.value_text, "Rs", "0")

    stamps = []
    junction = anode

    if series > 0.0:
        junction = f"@{part.reference}.j"
        stamps.append(("R", f"@{part.reference}.rs", anode, junction, series))

    device = DiodeDevice(
        part.reference, junction, cathode, saturation, emission
    )

    return stamps, device


def _bjt(part, nets):
    base = _node(nets, _pin(part, "base"))
    collector = _node(nets, _pin(part, "collector"))
    emitter = _node(nets, _pin(part, "emitter"))
    stamps = []
    base, collector, emitter = _series_pins(
        part, base, collector, emitter, stamps
    )
    polarity = 1.0 if part.kind == "npn" else -1.0
    device = BjtDevice(
        part.reference, base, collector, emitter,
        _card(part.value_text, "Is", "10f"),
        float(part.parameter_values["bf"]),
        float(part.parameter_values["vaf"]),
        polarity,
    )

    return stamps, device


def _series_pins(part, base, collector, emitter, stamps):
    """
    Move RB, RC and RE inside the transistor when the card has them.

    The resistor is appended to ``stamps``. The returned nodes are the
    ones the junction model should use.
    """
    reference = part.reference
    resistors = (
        ("rb", base, f"@{reference}.b"),
        ("rc", collector, f"@{reference}.c"),
        ("re", emitter, f"@{reference}.e"),
    )
    nodes = {"rb": base, "rc": collector, "re": emitter}

    for name, outer, inner in resistors:
        ohms = float(part.parameter_values[name])

        if ohms <= 0.0:
            continue

        stamps.append(("R", f"@{reference}.{name}", outer, inner, ohms))
        nodes[name] = inner

    return nodes["rb"], nodes["rc"], nodes["re"]


def _mosfet(part, nets):
    gate = _node(nets, _pin(part, "gate"))
    drain = _node(nets, _pin(part, "drain"))
    source = _node(nets, _pin(part, "source"))
    model = part.value_text
    stamps = []
    drain_ohms = _card(model, "Rd", "0")
    source_ohms = _card(model, "Rs", "0")

    if drain_ohms > 0.0:
        inner = f"@{part.reference}.d"
        stamps.append(("R", f"@{part.reference}.rd", drain, inner, drain_ohms))
        drain = inner

    if source_ohms > 0.0:
        inner = f"@{part.reference}.s"
        stamps.append((
            "R", f"@{part.reference}.rs", source, inner, source_ohms
        ))
        source = inner

    polarity = 1.0 if part.kind == "nmos" else -1.0
    device = MosfetDevice(
        part.reference, gate, drain, source,
        float(part.parameter_values["vto"]),
        float(part.parameter_values["kp"]),
        _card(model, "Lambda", "0"),
        polarity,
    )

    return stamps, device


def _jfet(part, nets):
    polarity = 1.0 if part.kind == "njfet" else -1.0
    device = JfetDevice(
        part.reference,
        _node(nets, _pin(part, "gate")),
        _node(nets, _pin(part, "drain")),
        _node(nets, _pin(part, "source")),
        float(part.parameter_values["vt0"]),
        float(part.parameter_values["beta"]),
        float(part.parameter_values["lambda"]),
        float(part.parameter_values["is"]),
        polarity,
    )

    return [], device


def _opamp(part, nets):
    inp = _node(nets, _pin(part, "in+"))
    inn = _node(nets, _pin(part, "in-"))
    out = _node(nets, _pin(part, "out"))
    vp = _node(nets, _pin(part, "V+"))
    vn = _node(nets, _pin(part, "V-"))

    if part.kind in ("opamp_generic", "opamp_741"):
        gain = GENERIC_OPAMP_GAIN
        rin = GENERIC_OPAMP_INPUT_RESISTANCE
        rout = GENERIC_OPAMP_OUTPUT_RESISTANCE
        limited = False
        tie = True
        head_high = 0.0
        head_low = 0.0
    else:
        gain = float(part.parameter_values["gain"])
        rin = float(part.parameter_values["rin"])
        rout = float(part.parameter_values["rout"])
        limited = part.parameter_values.get("limits") == "limited"
        tie = False
        head_high = float(part.parameter_values["head_high"])
        head_low = float(part.parameter_values["head_low"])

    return _amplifier(
        part.reference, inp, inn, out, vp, vn,
        gain, rin, rout, tie, limited, head_high, head_low,
    )


def _follower(part, nets):
    inp = _node(nets, _pin(part, "in"))
    out = _node(nets, _pin(part, "out"))
    stamps, _device = _amplifier(
        part.reference, inp, out, out,
        _node(nets, _pin(part, "V+")),
        _node(nets, _pin(part, "V-")),
        GENERIC_OPAMP_GAIN, GENERIC_OPAMP_INPUT_RESISTANCE,
        GENERIC_OPAMP_OUTPUT_RESISTANCE, True, False, 0.0, 0.0,
    )

    return stamps


def _inverting(part, nets):
    reference = part.reference
    inn = f"@{reference}.inn"
    inp = _node(nets, _pin(part, "in"))
    out = _node(nets, _pin(part, "out"))
    stamps = [
        ("R", f"@{reference}.in", inp, inn, 1e4),
        ("R", f"@{reference}.fb", out, inn, _ohms(1e4 * float(part.value))),
    ]
    inner, _device = _amplifier(
        reference, "0", inn, out,
        _node(nets, _pin(part, "V+")),
        _node(nets, _pin(part, "V-")),
        GENERIC_OPAMP_GAIN, GENERIC_OPAMP_INPUT_RESISTANCE,
        GENERIC_OPAMP_OUTPUT_RESISTANCE, True, False, 0.0, 0.0,
    )

    return stamps + inner


def _noninverting(part, nets):
    reference = part.reference
    inn = f"@{reference}.inn"
    out = _node(nets, _pin(part, "out"))
    stamps = [
        ("R", f"@{reference}.g", inn, "0", 1e4),
        (
            "R", f"@{reference}.fb", out, inn,
            _ohms(1e4 * (float(part.value) - 1.0)),
        ),
    ]
    inner, _device = _amplifier(
        reference, _node(nets, _pin(part, "in")), inn, out,
        _node(nets, _pin(part, "V+")),
        _node(nets, _pin(part, "V-")),
        GENERIC_OPAMP_GAIN, GENERIC_OPAMP_INPUT_RESISTANCE,
        GENERIC_OPAMP_OUTPUT_RESISTANCE, True, False, 0.0, 0.0,
    )

    return stamps + inner


def _amplifier(
        reference, inp, inn, out, vp, vn,
        gain, rin, rout, tie, limited, head_high, head_low):
    stamps = [("R", f"@{reference}.rin", inp, inn, rin)]

    if tie:
        stamps.append(("R", f"@{reference}.vp", vp, "0", _SUPPLY_BLEED))
        stamps.append(("R", f"@{reference}.vn", vn, "0", _SUPPLY_BLEED))

    if not limited:
        gain_node = f"@{reference}.gain"
        stamps.append(("E", reference, gain_node, "0", inp, inn, gain))
        stamps.append(("R", f"@{reference}.rout", gain_node, out, rout))

        return stamps, None

    filt = f"@{reference}.filt"
    pre = f"@{reference}.pre"
    stamps.append(("G", f"@{reference}.g", filt, "0", inp, inn, 1.0))
    stamps.append(("R", f"@{reference}.pole", filt, "0", gain))
    stamps.append(("R", f"@{reference}.rout", pre, out, rout))
    device = ClampDevice(
        reference, pre, filt, vp, vn, head_high, head_low
    )

    return stamps, device


def _logic(part, nets):
    if part.kind == "comparator":
        output = _node(nets, _pin(part, "out"))
        nodes = {
            "inp": _node(nets, _pin(part, "in+")),
            "inn": _node(nets, _pin(part, "in-")),
            "vp": _node(nets, _pin(part, "V+")),
            "vn": _node(nets, _pin(part, "V-")),
        }
        logic = "comp"
    else:
        output = _node(nets, _pin(part, "Y"))
        nodes = {
            "a": _node(nets, _pin(part, "A")),
            "y": output,
            "vcc": _node(nets, _pin(part, "VCC")),
            "gnd": _node(nets, _pin(part, "GND")),
        }
        logic = _LOGIC[part.kind]

        if "B" in {
                name for name, _row, _column in part.get_pin_positions()
        }:
            nodes["b"] = _node(nets, _pin(part, "B"))

    return [], LogicDevice(part.reference, logic, output, nodes)


def _operating_point(fixed, devices):
    if not devices:
        voltages, currents = _solve(fixed)
        _resistor_currents(fixed, voltages, currents)

        return voltages, currents

    for _iteration in range(_ITERATIONS):
        companions = []

        for device in devices:
            companions.extend(device.companions())

        voltages, currents = _solve(fixed + companions)

        if all(device.converged(voltages) for device in devices):
            _resistor_currents(fixed + companions, voltages, currents)

            return voltages, currents

        for device in devices:
            device.update(voltages)

    raise SimulationError(_NO_SOLUTION)


def _stamp_nodes(stamp):
    if stamp[0] in ("G", "E"):
        return stamp[2:6]

    return stamp[2:4]


def _solve(stamps):
    """
    Return ``(voltage by node id, current by reference)``.

    The branch current of a voltage source, a controlled voltage
    source or an inductor leaves the first stamped pin and enters
    the second.
    """
    nodes = []
    branches = []

    for stamp in stamps:
        for node in _stamp_nodes(stamp):
            if node != "0" and node not in nodes:
                nodes.append(node)

        if stamp[0] in ("V", "L", "E") and stamp[1] not in branches:
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

        if kind == "G":
            _cp, _cm, gain = stamp[4], stamp[5], stamp[6]
            add(left, stamp[4], -gain)
            add(left, stamp[5], gain)
            add(right, stamp[4], gain)
            add(right, stamp[5], -gain)
            continue

        if kind == "F":
            control = stamp[4]
            gain = stamp[5]
            column = index[control]
            row_out = at(left)
            row_in = at(right)

            if row_out is not None:
                matrix[row_out, column] -= gain

            if row_in is not None:
                matrix[row_in, column] += gain

            continue

        volts = 0.0 if kind in ("L", "E") else stamp[4]
        branch = at(reference)
        plus_row = at(left)
        minus_row = at(right)

        if plus_row is not None:
            matrix[plus_row, branch] -= 1.0
            matrix[branch, plus_row] += 1.0

        if minus_row is not None:
            matrix[minus_row, branch] += 1.0
            matrix[branch, minus_row] -= 1.0

        if kind == "E":
            gain = stamp[6]
            control_plus = at(stamp[4])
            control_minus = at(stamp[5])

            if control_plus is not None:
                matrix[branch, control_plus] -= gain

            if control_minus is not None:
                matrix[branch, control_minus] += gain

        vector[branch] = volts

    if count == 0:
        return {"0": 0.0}, currents

    try:
        solved = np.linalg.solve(matrix, vector)
    except np.linalg.LinAlgError as error:
        raise SimulationError(_NO_SOLUTION) from error

    if not np.all(np.isfinite(solved)):
        raise SimulationError(_NO_SOLUTION)

    # A closed switch is 1e-9 ohm. That row's residual is a few
    # millionths even when the voltage is right, so the check follows
    # the size of the row.
    residual = np.abs(matrix @ solved - vector)
    row_scale = np.sum(np.abs(matrix), axis=1)
    tolerance = 1e-9 * np.maximum(row_scale, 1.0) + 1e-9

    if np.any(residual > tolerance):
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


def _point_voltages(nets, parts, node_voltages):
    found = {}

    for part in parts:
        if part.kind != "ground":
            continue

        for identifier in part.get_pin_identifiers():
            for point in nets.get_points(identifier):
                found[point] = 0.0

    for node, volts in node_voltages.items():
        if node == "0" or str(node).startswith("@"):
            continue

        for point in nets.get_points(node):
            found[point] = volts

    return found
