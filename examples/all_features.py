"""
One circuit that uses every part, for File > Open.

Supplies are +12 V (Vcc) and -12 V (Vee). Ground is Vss. The one AC
source is 1 V peak at 1 kHz, so the oscilloscope and the Bode plot
both have a sine to show. The 10 V source only feeds the dividers.
"""

from pathlib import Path

from core.components import COMPONENT_DEFINITIONS, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.probes import ProbeCollection
from core.project_io import Workbook, save_project_file
from core.wires import WireCollection

EXAMPLE_PATH = Path(__file__).with_name("all-features.json")

# Room for the tallest symbol (the 555) and the op-amp feedback wires.
_ROWS = 48
_COLUMNS = 42


def build_all_features():
    """
    Build the all-features workbook.

    :returns: The workbook, and identifiers used by the checks.
    :rtype: tuple
    """
    grid = ConnectionGrid(_ROWS, _COLUMNS)
    parts = ComponentCollection()
    wires = WireCollection()
    probes = ProbeCollection()
    marks = {}

    def point(row, column):
        return ConnectionGrid.build_connection_point_identifier(row, column)

    def pin(component, name):
        for pin_name, row, column in component.get_pin_positions():
            if pin_name == name:
                return point(row, column)

        raise KeyError(name)

    def tag(component, name, label):
        grid.set_net_label(pin(component, name), label)

    def place(kind, row, column, value="", parameters=None):
        return parts.add_component(
            kind, row, column, value, grid, parameter_texts=parameters
        )

    def link(start, end, bridges=()):
        wires.add_wire(start, end, grid, bridged_identifiers=bridges)

    def supply(component):
        names = {name for name, _row, _column in component.get_pin_positions()}

        if "V+" in names:
            tag(component, "V+", "Vcc")
            tag(component, "V-", "Vee")

        if "VCC" in names:
            tag(component, "VCC", "Vcc")
            tag(component, "GND", "Vss")

    def follower_feedback(component):
        out = pin(component, "out")
        minus = pin(component, "in-")
        row = component.row_number
        column = component.column_number
        above = point(row - 2, column + 1)
        corner = point(row - 2, column - 1)
        link(out, above)
        link(above, corner)
        link(corner, minus)

    def load_to_ground(row, column, value):
        resistor = place("resistor", row, column, value)
        tag(resistor, "2", "Vss")
        return resistor

    ground = place("ground", 2, 2)
    tag(ground, "gnd", "Vss")

    batt = place("dc_source", 2, 4, "12")
    batt = parts.rename_component(batt.reference, "BATT")
    tag(batt, "plus", "Vcc")
    tag(batt, "minus", "Vss")

    vee = place("dc_source", 2, 6, "12")
    # The rail is named Vee. The part cannot be VEE too: ngspice
    # treats those as the same name.
    vee = parts.rename_component(vee.reference, "NEG")
    tag(vee, "plus", "Vss")
    tag(vee, "minus", "Vee")

    ten = place("dc_source", 4, 2, "10")
    tag(ten, "plus", "V10")
    tag(ten, "minus", "Vss")

    def divider(row):
        top = place("resistor", row, 4, "10k")
        tag(top, "1", "V10")
        bottom = place("resistor", row, 5, "10k")
        tag(bottom, "2", "Vss")
        return top

    direct_top = divider(4)
    megohm_top = divider(6)
    scope_top = divider(8)
    marks["divider"] = pin(direct_top, "2")
    marks["megohm"] = pin(megohm_top, "2")
    marks["scope_10x"] = pin(scope_top, "2")
    marks["divider_top"] = pin(direct_top, "1")
    marks["divider_resistor"] = direct_top.reference

    source = place(
        "ac_source", 10, 2, "1", {"frequency": "1k", "offset": "0"}
    )
    tag(source, "plus", "IN")
    tag(source, "minus", "Vss")
    marks["input"] = pin(source, "plus")

    series = place("resistor", 10, 4, "1k")
    tag(series, "1", "IN")
    capacitor = place("capacitor", 10, 5, "159n")
    tag(capacitor, "2", "Vss")
    marks["lowpass"] = pin(capacitor, "1")
    grid.toggle_signal_pickoff(marks["lowpass"])

    # A ground wire, and a signal that hops it. Two 10k resistors from
    # 12 V would be shorted to ground without the bridge, and 6 V with it.
    link(point(14, 6), point(18, 6))
    grid.set_net_label(point(14, 6), "Vss")
    bridge_top = place("resistor", 16, 3, "10k")
    tag(bridge_top, "1", "Vcc")
    link(
        pin(bridge_top, "2"),
        point(16, 8),
        bridges=(point(16, 6),),
    )
    bridge_bottom = place("resistor", 16, 8, "10k")
    tag(bridge_bottom, "2", "Vss")
    marks["bridge"] = pin(bridge_top, "2")

    pot = place("potentiometer", 16, 12, "10k", {"position": "0.5"})
    tag(pot, "1", "Vcc")
    tag(pot, "2", "Vss")
    # A light load gives the wiper its second connection. 10 megohm
    # across 2.5 kilohm barely moves the 6 V reading.
    wiper = pin(pot, "wiper")
    row, column = _row_column(wiper)
    wiper_load = place("resistor", row, column, "10meg")
    tag(wiper_load, "2", "Vss")
    marks["pot"] = wiper

    transformer = place("transformer", 16, 18, "2")
    tag(transformer, "p1", "Vcc")
    tag(transformer, "p2", "Vss")
    tag(transformer, "s2", "Vss")
    secondary = place("resistor", 16, 20, "10k")
    link(pin(transformer, "s1"), pin(secondary, "1"))
    tag(secondary, "2", "Vss")
    marks["secondary"] = pin(transformer, "s1")

    current = place("current_source", 20, 2, "1m")
    tag(current, "in", "Vss")
    current_load = load_to_ground(20, 2, "1k")
    marks["current"] = pin(current, "out")
    marks["current_load"] = current_load.reference

    closed = place("switch", 20, 6, "", {"state": "closed"})
    tag(closed, "1", "Vcc")
    load_to_ground(20, 7, "1k")
    marks["closed"] = pin(closed, "2")

    opened = place("switch", 20, 12, "", {"state": "open"})
    tag(opened, "1", "Vcc")
    load_to_ground(20, 13, "1k")
    marks["open"] = pin(opened, "2")

    regulator = place("voltage_regulator", 20, 18, "5")
    tag(regulator, "in", "Vcc")
    tag(regulator, "gnd", "Vss")
    load_to_ground(20, 19, "1k")
    marks["regulator"] = pin(regulator, "out")

    inductor = place("inductor", 24, 2, "10m")
    tag(inductor, "1", "Vcc")
    load_to_ground(24, 3, "1k")

    polarized = place("capacitor_polarized", 24, 8, "10u")
    tag(polarized, "minus", "Vss")
    charger = place("resistor", 24, 6, "10k")
    tag(charger, "1", "Vcc")
    link(pin(charger, "2"), pin(polarized, "plus"))

    diode_feed = place("resistor", 24, 12, "10k")
    tag(diode_feed, "1", "Vcc")
    diode = place("diode", 24, 13, "1N4148")
    tag(diode, "cathode", "Vss")

    led_feed = place("resistor", 24, 16, "1k")
    tag(led_feed, "1", "Vcc")
    led = place("led", 24, 17, "LED_RED", {"color": "red"})
    tag(led, "cathode", "Vss")
    marks["led"] = led.reference
    marks["led_resistor"] = led_feed.reference

    npn = place("npn", 28, 4, "2N3904")
    tag(npn, "emitter", "Vss")
    base_feed = place("resistor", 28, 2, "100k")
    tag(base_feed, "1", "Vcc")
    collector_feed = place("resistor", 27, 4, "1k")
    tag(collector_feed, "2", "Vcc")

    pnp = place("pnp", 28, 10, "2N3906")
    tag(pnp, "emitter", "Vcc")
    pnp_base = place("resistor", 28, 8, "100k")
    tag(pnp_base, "1", "Vss")
    link(pin(pnp, "collector"), point(29, 11))
    pnp_load = place("resistor", 29, 11, "1k")
    tag(pnp_load, "2", "Vss")

    nmos = place("nmos", 28, 16, "2N7000")
    tag(nmos, "source", "Vss")
    tag(nmos, "gate", "Vcc")
    nmos_load = place("resistor", 27, 16, "1k")
    tag(nmos_load, "2", "Vcc")

    pmos = place("pmos", 28, 22, "BS250")
    tag(pmos, "source", "Vcc")
    tag(pmos, "gate", "Vss")
    link(pin(pmos, "drain"), point(29, 23))
    pmos_load = place("resistor", 29, 23, "1k")
    tag(pmos_load, "2", "Vss")

    timer = place("timer_555", 36, 4, "NE555")
    supply(timer)

    for name in ("TRIG", "OUT", "RESET"):
        row, column = _row_column(pin(timer, name))
        pulldown = place("resistor", row, column - 1, "1meg")
        tag(pulldown, "1", "Vss")

    for name in ("DISCH", "THRES", "CONT"):
        row, column = _row_column(pin(timer, name))
        pulldown = place("resistor", row, column, "1meg")
        tag(pulldown, "2", "Vss")

    marks["timer_control"] = pin(timer, "CONT")

    gate_inputs = {
        "gate_not": (("A", "Vss"),),
        "gate_buffer": (("A", "Vcc"),),
        "gate_and": (("A", "Vcc"), ("B", "Vcc")),
        "gate_or": (("A", "Vcc"), ("B", "Vss")),
        "gate_nand": (("A", "Vcc"), ("B", "Vcc")),
        "gate_nor": (("A", "Vss"), ("B", "Vss")),
        "gate_xor": (("A", "Vcc"), ("B", "Vss")),
    }

    for index, kind in enumerate(gate_inputs):
        gate = place(kind, 8 + index * 4, 28)
        supply(gate)

        for name, label in gate_inputs[kind]:
            tag(gate, name, label)

        output = pin(gate, "Y")
        row, column = _row_column(output)
        load_to_ground(row, column, "10k")
        marks[kind] = output

    amplifiers = (
        ("follower", 8, ""),
        ("noninverting_amp", 14, "2"),
        ("inverting_amp", 20, "2"),
    )

    for kind, row, value in amplifiers:
        block = place(kind, row, 22, value)
        supply(block)
        tag(block, "in", "IN")
        output = pin(block, "out")
        row, column = _row_column(output)
        load_to_ground(row, column, "10k")
        marks[kind] = output

    followers = (
        ("opamp_generic", 8, 34),
        ("opamp_741", 14, 34),
        ("opamp_lm358", 20, 34),
        ("opamp_tl072", 26, 34),
        ("opamp_ne5532", 32, 34),
        ("opamp_tl081", 8, 39),
        ("opamp_tl082", 14, 39),
        ("opamp_lm324", 20, 39),
    )

    for kind, row, column in followers:
        opamp = place(kind, row, column)
        supply(opamp)
        tag(opamp, "in+", "IN")
        follower_feedback(opamp)
        marks[kind] = pin(opamp, "out")

    comparator = place("comparator", 26, 39)
    supply(comparator)
    tag(comparator, "in+", "Vcc")
    tag(comparator, "in-", "Vss")
    output = pin(comparator, "out")
    row, column = _row_column(output)
    load_to_ground(row, column, "10k")
    marks["comparator"] = output

    probes.add_voltage(marks["input"], grid)
    probes.add_voltage(marks["lowpass"], grid)
    probes.add_voltage(marks["opamp_generic"], grid)
    probes.add_voltage(marks["follower"], grid)
    probes.add_voltage(marks["noninverting_amp"], grid)
    probes.add_voltage(marks["inverting_amp"], grid)
    probes.add_voltage(marks["divider"], grid)

    megohm = probes.add_voltage(marks["megohm"], grid)
    probes.set_method(megohm.reference, "megohm", parts.get_components())
    scope = probes.add_voltage(marks["scope_10x"], grid)
    probes.set_method(scope.reference, "scope_10x", parts.get_components())
    differential = probes.add_voltage(marks["divider_top"], grid)
    probes.set_method(
        differential.reference, "differential", parts.get_components()
    )
    probes.set_second_point(
        differential.reference, marks["divider"], grid
    )
    probes.add_current(parts.get_component(marks["divider_resistor"]))
    probes.add_current(parts.get_component(marks["led_resistor"]))

    placed = {component.kind for component in parts.get_components()}
    missing = sorted(set(COMPONENT_DEFINITIONS) - placed)

    if missing:
        raise RuntimeError(f"The example is missing {missing}.")

    workbook = Workbook(grid, parts, wires, probes)
    return workbook, marks


def save_example(path=None):
    """
    Write examples/all-features.json from the builder.

    :param path: Destination. Defaults to the file next to this module.
    :returns: None
    """
    workbook, _marks = build_all_features()
    save_project_file(
        EXAMPLE_PATH if path is None else path,
        workbook.connection_grid,
        workbook.component_collection,
        workbook.wire_collection,
        workbook.probe_collection,
    )


def _row_column(identifier):
    text = identifier.split("_")
    return int(text[1][1:]), int(text[2][1:])
