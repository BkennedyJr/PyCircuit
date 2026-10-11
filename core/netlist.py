"""
SPICE netlist for the circuit on the grid.

``build_netlist`` walks the parts and wires already on the bench. Ground
is node 0. Every other net is N001, N002, ... in row-column order, or the
net's name when it has one (Vcc stays Vcc). The same text is what File >
Export Netlist writes, so there is one exporter.

A closed switch is a 1 nOhm resistor and an open switch is a 1 GOhm
resistor. A potentiometer is two resistors. An ideal transformer is an E
source and an F source. A regulator and a 555 are the subcircuits in
core.subcircuit_models. This module does not import Qt.
"""

import os
import re
import tempfile
from pathlib import Path

from core.components import COMPONENT_DEFINITIONS, Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError, SimulationError
from core.spice_models import DEVICE_KIND_BY_PART, device_model_line, get_device_model
from core.subcircuit_models import (
    DEFAULT_SUBCIRCUIT_BY_KIND,
    SUBCIRCUIT_MODELS,
    get_subcircuit_model_name,
    get_subcircuit_text,
)
from core.units import format_spice_number
from core.wires import WireCollection, WireNets

_SOURCE_KINDS = ("dc_source", "ac_source", "current_source")
_AMPLIFIER_MODELS = ("FOLLOW", "INVAMP", "NONINV")
# A closed switch is a 1 nOhm short. An open switch is 1 GOhm.
_SWITCH_CLOSED_OHMS = 1e-9
_SWITCH_OPEN_OHMS = 1e9


def build_netlist(components, wire_collection, connection_grid=None):
    """
    Return the SPICE netlist for one circuit.

    :param components: Placed parts, or a ComponentCollection.
    :type components: iterable of Component
    :param wire_collection: Wires of the same circuit.
    :type wire_collection: WireCollection
    :param connection_grid: Grid whose net labels name nodes. None means
        no labels.
    :type connection_grid: ConnectionGrid or None
    :returns: Netlist text ending in a newline.
    :rtype: str
    :raises SimulationError: If the circuit has no ground, no source, an
        unknown model, a shorted part, or a floating node.
    """
    parts = _component_list(components)
    _validate_wires_and_grid(wire_collection, connection_grid)
    nets = _build_nets(parts, wire_collection, connection_grid)
    node_of = _name_nodes(parts, nets)
    _require_ground_and_source(parts)
    model_names = _require_known_models(parts)
    _require_no_shorts(parts, node_of)
    _require_no_floating_nodes(parts, nets, node_of)

    lines = ["* PyCircuit SPICE netlist"]

    for component in parts:
        lines.extend(_element_lines(component, node_of))

    model_text = _model_text(model_names, parts)

    if model_text:
        lines.append("")
        lines.append(model_text.rstrip("\n"))

    lines.append(".end")

    return "\n".join(lines) + "\n"


def write_netlist_file(netlist_file_path, netlist_text):
    """
    Write a netlist atomically. The destination is replaced only after
    the temporary file is flushed.

    :param netlist_file_path: Destination, for example ``divider.cir``.
    :type netlist_file_path: pathlib.Path or str
    :param netlist_text: Text from build_netlist.
    :type netlist_text: str
    :returns: None
    :raises SimulationError: If the text or the path cannot be written.
    """
    if not isinstance(netlist_text, str) or not netlist_text.endswith("\n"):
        raise SimulationError(
            "The netlist text is empty or unfinished, so it was not written."
        )

    if not isinstance(netlist_file_path, Path):
        netlist_file_path = Path(netlist_file_path)

    destination_directory = netlist_file_path.parent

    if not destination_directory.exists() or not destination_directory.is_dir():
        raise SimulationError(
            f"The netlist folder does not exist: {destination_directory}."
        )

    temporary_file_path = None

    try:
        with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".temporary",
                prefix="circuit_workbench_",
                dir=str(destination_directory),
                delete=False) as temporary_file_handle:
            temporary_file_path = Path(temporary_file_handle.name)
            temporary_file_handle.write(netlist_text)
            temporary_file_handle.flush()
            os.fsync(temporary_file_handle.fileno())

        os.replace(str(temporary_file_path), str(netlist_file_path))
        temporary_file_path = None

    except OSError as error:
        raise SimulationError(
            f"Unable to write the netlist '{netlist_file_path}'. "
            f"Reason: {error}."
        ) from None

    finally:
        if temporary_file_path is not None:
            try:
                temporary_file_path.unlink()
            except OSError:
                pass


def _component_list(components):
    if isinstance(components, ComponentCollection):
        return components.get_components()

    if isinstance(components, Component):
        raise SimulationError(
            "Pass the list of parts, not one part."
        )

    try:
        parts = list(components)
    except TypeError:
        raise SimulationError(
            f"Parts must be a list, not {components!r}."
        ) from None

    for component in parts:
        if not isinstance(component, Component):
            raise SimulationError(
                f"Expected a placed part, not {component!r}."
            )

    return sorted(parts, key=_reference_key)


def _reference_key(component):
    reference = component.reference
    prefix = reference.rstrip("0123456789")

    return (prefix, int(reference[len(prefix):]))


def _validate_wires_and_grid(wire_collection, connection_grid):
    if not isinstance(wire_collection, WireCollection):
        raise SimulationError(
            "The netlist needs the circuit's wires."
        )

    if (connection_grid is not None and
            not isinstance(connection_grid, ConnectionGrid)):
        raise SimulationError(
            "The netlist needs the circuit's grid."
        )


def _build_nets(parts, wire_collection, connection_grid):
    ground_identifiers = []
    pin_labels = []

    for component in parts:
        for pin_name, row_number, column_number in (
                component.get_pin_positions()):
            identifier = ConnectionGrid.build_connection_point_identifier(
                row_number, column_number
            )
            pin_labels.append((identifier, f"{component.reference}.{pin_name}"))

            if component.kind == "ground":
                ground_identifiers.append(identifier)

    net_labels = ()

    if connection_grid is not None:
        net_labels = tuple(connection_grid.get_net_labels().items())

    return WireNets(
        wire_collection, ground_identifiers, pin_labels, net_labels
    )


def _name_nodes(parts, nets):
    """
    Map each pin's grid point to a SPICE node name.

    Ground is ``0``. A net with one name keeps that name. The rest are
    N001, N002, ... by the top-left point of the net.
    """
    groups = {}

    for component in parts:
        for _pin_name, row_number, column_number in (
                component.get_pin_positions()):
            identifier = ConnectionGrid.build_connection_point_identifier(
                row_number, column_number
            )
            points = nets.get_points(identifier)
            groups[points] = identifier

    numbered = []
    named = {}

    for points, identifier in groups.items():
        if nets.is_ground(identifier):
            named[points] = "0"
            continue

        names = nets.get_net_names(identifier)

        if len(names) == 1 and names[0] != "0":
            named[points] = names[0]
            continue

        numbered.append(points)

    numbered.sort(key=lambda points: points[0])
    width = max(3, len(str(len(numbered))))

    for index, points in enumerate(numbered, start=1):
        named[points] = f"N{index:0{width}d}"

    node_of = {}

    for component in parts:
        for _pin_name, row_number, column_number in (
                component.get_pin_positions()):
            identifier = ConnectionGrid.build_connection_point_identifier(
                row_number, column_number
            )
            node_of[(component.reference, _pin_name)] = named[
                nets.get_points(identifier)
            ]

    return node_of


def _require_ground_and_source(parts):
    if not any(component.kind == "ground" for component in parts):
        raise SimulationError("Add a ground part.")

    if not any(component.kind in _SOURCE_KINDS for component in parts):
        raise SimulationError("Add a source before running.")


def _require_known_models(parts):
    """
    Check diode, LED and transistor models. Return the names to emit.

    :rtype: list
    """
    model_names = []

    for component in parts:
        if component.kind not in DEVICE_KIND_BY_PART:
            continue

        model_name, device_kind, _parameters = get_device_model(
            component.value_text
        )
        expected = DEVICE_KIND_BY_PART[component.kind]

        if device_kind != expected:
            raise SimulationError(
                f"{component.reference} uses model {model_name}, which is "
                f"a {device_kind} model. This part needs a {expected} model."
            )

        if model_name not in model_names:
            model_names.append(model_name)

    return model_names


def _pin_node(node_of, component, pin_name):
    return node_of[(component.reference, pin_name)]


def _require_no_shorts(parts, node_of):
    for component in parts:
        pin_names = [
            pin_name
            for pin_name, _dx, _dy in COMPONENT_DEFINITIONS[component.kind][
                "pins"
            ]
        ]

        if len(pin_names) == 2:
            first = _pin_node(node_of, component, pin_names[0])
            second = _pin_node(node_of, component, pin_names[1])

            if first == second:
                raise SimulationError(
                    f"{component.reference} is shorted: both pins are on "
                    "the same net."
                )

        if (component.kind == "potentiometer" and
                _pin_node(node_of, component, "1") ==
                _pin_node(node_of, component, "2")):
            raise SimulationError(
                f"{component.reference} is shorted: both ends are on "
                "the same net."
            )

        if component.kind == "transformer":
            primary_short = (
                _pin_node(node_of, component, "p1") ==
                _pin_node(node_of, component, "p2")
            )
            secondary_short = (
                _pin_node(node_of, component, "s1") ==
                _pin_node(node_of, component, "s2")
            )

            if primary_short or secondary_short:
                raise SimulationError(
                    f"{component.reference} is shorted: a winding has both "
                    "pins on the same net."
                )


def _require_no_floating_nodes(parts, nets, node_of):
    counted = set()

    for component in parts:
        for pin_name, row_number, column_number in (
                component.get_pin_positions()):
            identifier = ConnectionGrid.build_connection_point_identifier(
                row_number, column_number
            )
            points = nets.get_points(identifier)

            if points in counted or nets.is_ground(identifier):
                continue

            counted.add(points)
            labels = nets.get_pin_labels(identifier)

            if len(labels) < 2:
                node = node_of[(component.reference, pin_name)]
                raise SimulationError(
                    f"Node {node} has only one connection. Each node "
                    "needs two."
                )


def _element_lines(component, node_of):
    kind = component.kind
    reference = component.reference

    if kind == "ground":
        return []

    if kind in ("resistor", "capacitor", "inductor"):
        letter = {"resistor": "R", "capacitor": "C", "inductor": "L"}[kind]

        return [_two_pin_line(component, node_of, reference, letter)]

    if kind == "capacitor_polarized":
        plus = _pin_node(node_of, component, "plus")
        minus = _pin_node(node_of, component, "minus")

        return [
            (f"{reference} {plus} {minus} "
            f"{format_spice_number(component.value)}")
        ]

    if kind in ("diode", "led"):
        anode = _pin_node(node_of, component, "anode")
        cathode = _pin_node(node_of, component, "cathode")
        model_name = get_device_model(component.value_text)[0]

        return [f"{reference} {anode} {cathode} {model_name}"]

    if kind == "npn":
        return [_bjt_line(component, node_of, "collector", "base", "emitter")]

    if kind == "pnp":
        return [_bjt_line(component, node_of, "collector", "base", "emitter")]

    if kind in ("nmos", "pmos"):
        drain = _pin_node(node_of, component, "drain")
        gate = _pin_node(node_of, component, "gate")
        source = _pin_node(node_of, component, "source")
        model_name = get_device_model(component.value_text)[0]

        return [
            f"{reference} {drain} {gate} {source} {source} {model_name}"
        ]

    if kind == "dc_source":
        plus = _pin_node(node_of, component, "plus")
        minus = _pin_node(node_of, component, "minus")

        return [
            (f"{reference} {plus} {minus} DC "
            f"{format_spice_number(component.value)}")
        ]

    if kind == "ac_source":
        plus = _pin_node(node_of, component, "plus")
        minus = _pin_node(node_of, component, "minus")
        offset = format_spice_number(component.parameter_values["offset"])
        peak = format_spice_number(component.value)
        frequency = format_spice_number(
            component.parameter_values["frequency"]
        )
        phase = format_spice_number(component.parameter_values["phase"])

        return [
            (f"{reference} {plus} {minus} DC {offset} AC {peak} "
            f"SIN({offset} {peak} {frequency} 0 0 {phase})")
        ]

    if kind == "current_source":
        # Current flows from "in" through the source and out of "out".
        incoming = _pin_node(node_of, component, "in")
        outgoing = _pin_node(node_of, component, "out")

        return [
            (f"{reference} {incoming} {outgoing} DC "
            f"{format_spice_number(component.value)}")
        ]

    if kind == "switch":
        first = _pin_node(node_of, component, "1")
        second = _pin_node(node_of, component, "2")
        state = component.parameter_values["state"]
        ohms = (
            _SWITCH_CLOSED_OHMS if state == "closed" else _SWITCH_OPEN_OHMS
        )

        return [
            f"* {reference} {state}",
            f"R{reference} {first} {second} {format_spice_number(ohms)}",
        ]

    if kind == "potentiometer":
        return _potentiometer_lines(component, node_of)

    if kind == "transformer":
        return _transformer_lines(component, node_of)

    if kind == "voltage_regulator":
        return _regulator_lines(component, node_of)

    if COMPONENT_DEFINITIONS[kind]["prefix"] in ("X", "A"):
        return _subcircuit_lines(component, node_of)

    raise SimulationError(
        f"{reference} is a {COMPONENT_DEFINITIONS[kind]['display_name']}, "
        "which has no SPICE line yet."
    )


def _two_pin_line(component, node_of, reference, letter):
    first = _pin_node(node_of, component, "1")
    second = _pin_node(node_of, component, "2")

    # The reference already starts with the SPICE letter (R, C, L).
    if not reference.startswith(letter):
        reference = letter + reference

    return (
        f"{reference} {first} {second} "
        f"{format_spice_number(component.value)}"
    )


def _bjt_line(component, node_of, collector, base, emitter):
    model_name = get_device_model(component.value_text)[0]

    return (
        f"{component.reference} "
        f"{_pin_node(node_of, component, collector)} "
        f"{_pin_node(node_of, component, base)} "
        f"{_pin_node(node_of, component, emitter)} {model_name}"
    )


def _potentiometer_lines(component, node_of):
    resistance = component.value
    position = component.parameter_values["position"]
    top = (1.0 - position) * resistance
    bottom = position * resistance
    pin_1 = _pin_node(node_of, component, "1")
    pin_2 = _pin_node(node_of, component, "2")
    wiper = _pin_node(node_of, component, "wiper")
    reference = component.reference

    return [
        (f"* {reference} {format_spice_number(resistance)} "
        f"position={_plain_number(position)}"),
        f"R{reference}A {pin_1} {wiper} {_half_resistance(top)}",
        f"R{reference}B {wiper} {pin_2} {_half_resistance(bottom)}",
    ]


def _plain_number(number):
    """
    A short decimal for a comment. 0.5 stays ``0.5``, not ``500m``.
    """
    return f"{float(number):.6g}"


def _half_resistance(ohms):
    if ohms == 0:
        return format_spice_number(_SWITCH_CLOSED_OHMS)

    return format_spice_number(ohms)


def _transformer_lines(component, node_of):
    # V(s1,s2) = n*V(p1,p2). The F source draws n times the secondary
    # current into the dotted primary, so power in equals power out.
    turns = format_spice_number(component.value)
    p1 = _pin_node(node_of, component, "p1")
    p2 = _pin_node(node_of, component, "p2")
    s1 = _pin_node(node_of, component, "s1")
    s2 = _pin_node(node_of, component, "s2")
    reference = component.reference
    voltage_source = f"E{reference}"

    return [
        f"* {reference} turns={turns} dots on p1 and s1",
        f"{voltage_source} {s1} {s2} {p1} {p2} {turns}",
        f"F{reference} {p2} {p1} {voltage_source} {turns}",
    ]


def _regulator_lines(component, node_of):
    pin_in = _pin_node(node_of, component, "in")
    ground = _pin_node(node_of, component, "gnd")
    pin_out = _pin_node(node_of, component, "out")
    voltage = format_spice_number(component.value)

    return [
        f"* {component.reference} {voltage}V",
        (f"X{component.reference} {pin_in} {ground} {pin_out} REG "
        f"voltage={voltage}"),
    ]


def _subcircuit_lines(component, node_of):
    definition = COMPONENT_DEFINITIONS[component.kind]
    model_name = component.value_text

    if definition["prefix"] != "X":
        model_name = DEFAULT_SUBCIRCUIT_BY_KIND[component.kind]

    try:
        model_name = get_subcircuit_model_name(model_name)
    except ComponentError as error:
        raise SimulationError(str(error)) from None

    ports = SUBCIRCUIT_MODELS[model_name]["ports"]
    nodes = [
        _pin_node(node_of, component, pin_name) for pin_name in ports
    ]
    spice_reference = component.reference

    if not spice_reference.startswith("X"):
        spice_reference = "X" + spice_reference

    line = f"{spice_reference} {' '.join(nodes)} {model_name}"

    if model_name in ("INVAMP", "NONINV"):
        line += f" gain={format_spice_number(component.value)}"

    return [line]


def _model_text(device_model_names, parts):
    chunks = []

    for model_name in device_model_names:
        chunks.append(device_model_line(model_name))

    subcircuit_names = []

    for component in parts:
        kind = component.kind

        if kind == "voltage_regulator":
            if "REG" not in subcircuit_names:
                subcircuit_names.append("REG")
            continue

        if kind not in DEVICE_KIND_BY_PART and kind != "ground":
            definition = COMPONENT_DEFINITIONS[kind]

            if definition["prefix"] not in ("X", "A"):
                continue

            if definition["prefix"] == "X":
                model_name = get_subcircuit_model_name(component.value_text)
            else:
                model_name = DEFAULT_SUBCIRCUIT_BY_KIND[kind]

            if model_name not in subcircuit_names:
                subcircuit_names.append(model_name)

    emitted = set()

    for model_name in subcircuit_names:
        text = get_subcircuit_text(model_name)

        if model_name in _AMPLIFIER_MODELS and "OPAMP" in emitted:
            ends = text.find(".ends OPAMP")

            if ends != -1:
                text = text[ends + len(".ends OPAMP"):].lstrip("\n")

        if model_name in emitted:
            continue

        if re.search(r"(?m)^\.subckt OPAMP\b", text):
            emitted.add("OPAMP")

        emitted.add(model_name)
        chunks.append(text.rstrip("\n"))

    return "\n".join(chunks)
