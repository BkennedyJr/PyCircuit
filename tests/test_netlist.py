"""
The netlist is the circuit, written so LTspice can open it.

Ground is node 0. Other nets are N001, N002, ... by the top-left point,
unless the net has one name. File > Export Netlist writes that same text.
"""

import pytest
from PyQt5.QtWidgets import QFileDialog

from core.components import COMPONENT_DEFINITIONS, Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import SimulationError
from core.netlist import _element_lines, build_netlist, write_netlist_file
from core.spice_models import device_model_line
from core.wires import WireCollection
from gui.main_window import MainWindow


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def new_circuit():
    return ConnectionGrid(8, 8), ComponentCollection(), WireCollection()


def place(parts, grid, kind, row, column, value="", parameters=None):
    return parts.add_component(
        kind, row, column, value, grid, parameter_texts=parameters
    )


def connect(wires, grid, start, end):
    wires.add_wire(point(*start), point(*end), grid)


def build_divider(grid, parts, wires, top="10k", bottom="10k", source="10"):
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, source)
    place(parts, grid, "resistor", 4, 3, top)
    place(parts, grid, "resistor", 4, 4, bottom)
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))


DIVIDER = """\
* PyCircuit SPICE netlist
R1 N001 N002 10k
R2 N002 0 10k
V1 N001 0 DC 10
.end
"""


def test_a_divider_is_the_hand_checked_netlist():
    grid, parts, wires = new_circuit()
    build_divider(grid, parts, wires)

    assert build_netlist(parts, wires, grid) == DIVIDER


def test_a_named_midpoint_keeps_its_name():
    grid, parts, wires = new_circuit()
    build_divider(grid, parts, wires)
    grid.set_net_label(point(4, 4), "vout")

    assert "R1 N001 vout 10k" in build_netlist(parts, wires, grid)
    assert "R2 vout 0 10k" in build_netlist(parts, wires, grid)
    assert "N002" not in build_netlist(parts, wires, grid)


def test_spice_numbers_are_4_7k_and_1meg_never_a_lone_m():
    grid, parts, wires = new_circuit()
    build_divider(grid, parts, wires, top="4k7", bottom="1meg")
    text = build_netlist(parts, wires, grid)

    assert "R1 N001 N002 4.7k" in text
    assert "R2 N002 0 1meg" in text
    assert "4k7" not in text
    assert "1M" not in text


def test_an_rc_low_pass_uses_the_ac_source_sine():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "ac_source", 4, 2, "1", {"frequency": "1k"})
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "capacitor", 4, 4, "159n")
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))
    text = build_netlist(parts, wires, grid)

    assert "C1 N002 0 159n" in text
    assert "R1 N001 N002 1k" in text
    assert "V1 N001 0 DC 0 AC 1 SIN(0 1 1k 0 0 0)" in text


def test_an_led_uses_its_model_and_a_diode_name_is_canonical():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 5)
    place(parts, grid, "dc_source", 4, 1, "5")
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "led", 4, 4, "led_red")
    connect(wires, grid, (4, 1), (4, 3))
    connect(wires, grid, (5, 1), (6, 1))
    connect(wires, grid, (6, 1), (6, 5))
    connect(wires, grid, (4, 5), (6, 5))
    text = build_netlist(parts, wires, grid)

    assert "D1 N002 0 LED_RED" in text
    assert "R1 N001 N002 1k" in text
    assert device_model_line("LED_RED") in text
    assert text.count(".model LED_RED") == 1

    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 5)
    place(parts, grid, "dc_source", 4, 1, "5")
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "diode", 4, 4, "1n4148")
    connect(wires, grid, (4, 1), (4, 3))
    connect(wires, grid, (5, 1), (6, 1))
    connect(wires, grid, (6, 1), (6, 5))
    connect(wires, grid, (4, 5), (6, 5))
    text = build_netlist(parts, wires, grid)

    assert "D1 N002 0 1N4148" in text
    assert ".model 1N4148 " in text


def test_a_unity_gain_buffer_ties_the_output_back_to_the_minus_input():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 8, 2)
    place(parts, grid, "opamp_generic", 4, 4, "OPAMP")
    place(parts, grid, "dc_source", 5, 2, "1")
    place(parts, grid, "dc_source", 3, 6, "12")
    connect(wires, grid, (5, 2), (5, 3))
    connect(wires, grid, (6, 2), (8, 2))
    connect(wires, grid, (4, 5), (4, 3))
    connect(wires, grid, (4, 3), (3, 3))
    connect(wires, grid, (5, 4), (8, 4))
    connect(wires, grid, (8, 4), (8, 2))
    connect(wires, grid, (3, 4), (3, 6))
    connect(wires, grid, (4, 6), (4, 8))
    connect(wires, grid, (4, 8), (8, 8))
    connect(wires, grid, (8, 8), (8, 2))
    text = build_netlist(parts, wires, grid)

    assert "X1 N003 N001 N002 0 N001 OPAMP" in text
    assert "V1 N003 0 DC 1" in text
    assert "V2 N002 0 DC 12" in text
    assert text.count(".subckt OPAMP") == 1


def test_a_follower_includes_the_generic_opamp_once():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 7, 7)
    place(parts, grid, "follower", 4, 4)
    place(parts, grid, "dc_source", 4, 1, "1")
    place(parts, grid, "dc_source", 3, 7, "12")
    place(parts, grid, "resistor", 4, 6, "1k")
    connect(wires, grid, (4, 1), (4, 3))
    connect(wires, grid, (5, 1), (7, 1))
    connect(wires, grid, (7, 1), (7, 4))
    connect(wires, grid, (5, 4), (7, 4))
    connect(wires, grid, (7, 4), (7, 7))
    connect(wires, grid, (4, 5), (4, 6))
    connect(wires, grid, (4, 7), (7, 7))
    connect(wires, grid, (3, 4), (3, 7))
    text = build_netlist(parts, wires, grid)

    assert "XA1 N002 N003 N001 0 FOLLOW" in text
    assert text.count(".subckt OPAMP") == 1
    assert text.count(".subckt FOLLOW") == 1


def test_a_closed_switch_is_1n_and_an_open_switch_is_1g():
    def switched(state):
        grid, parts, wires = new_circuit()
        place(parts, grid, "ground", 6, 5)
        place(parts, grid, "dc_source", 4, 1, "5")
        place(parts, grid, "switch", 4, 3, parameters={"state": state})
        place(parts, grid, "resistor", 4, 4, "1k")
        connect(wires, grid, (4, 1), (4, 3))
        connect(wires, grid, (5, 1), (6, 1))
        connect(wires, grid, (6, 1), (6, 5))
        connect(wires, grid, (4, 5), (6, 5))
        return build_netlist(parts, wires, grid)

    closed = switched("closed")
    assert "* S1 closed" in closed
    assert "RS1 N001 N002 1n" in closed

    opened = switched("open")
    assert "* S1 open" in opened
    assert "RS1 N001 N002 1g" in opened


def test_a_pot_splits_into_two_resistors():
    def pot(position):
        grid, parts, wires = new_circuit()
        place(parts, grid, "ground", 7, 5)
        place(parts, grid, "dc_source", 4, 1, "10")
        place(
            parts, grid, "potentiometer", 4, 3, "10k",
            {"position": position}
        )
        place(parts, grid, "resistor", 5, 4, "1k")
        connect(wires, grid, (4, 1), (4, 3))
        connect(wires, grid, (5, 1), (7, 1))
        connect(wires, grid, (7, 1), (7, 5))
        connect(wires, grid, (4, 5), (7, 5))
        return build_netlist(parts, wires, grid)

    half = pot("0.5")
    assert "* RV1 10k position=0.5" in half
    assert "RRV1A N001 N002 5k" in half
    assert "RRV1B N002 0 5k" in half

    bottom = pot("0")
    assert "position=0" in bottom
    assert "RRV1A N001 N002 10k" in bottom
    assert "RRV1B N002 0 1n" in bottom

    top = pot("1")
    assert "RRV1A N001 N002 1n" in top
    assert "RRV1B N002 0 10k" in top


def test_a_loaded_transformer_uses_an_e_and_an_f_source():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 7, 4)
    place(parts, grid, "dc_source", 4, 2, "10")
    place(parts, grid, "transformer", 4, 4, "2")
    place(parts, grid, "resistor", 4, 6, "1k")
    connect(wires, grid, (4, 2), (4, 4))
    connect(wires, grid, (5, 2), (5, 4))
    connect(wires, grid, (5, 4), (7, 4))
    connect(wires, grid, (4, 5), (4, 6))
    connect(wires, grid, (5, 5), (7, 5))
    connect(wires, grid, (7, 5), (7, 4))
    connect(wires, grid, (4, 7), (7, 7))
    connect(wires, grid, (7, 7), (7, 5))
    text = build_netlist(parts, wires, grid)

    assert "* T1 turns=2 dots on p1 and s1" in text
    assert "ET1 N002 0 N001 0 2" in text
    assert "FT1 0 N001 ET1 2" in text
    assert "R1 N002 0 1k" in text
    assert "V1 N001 0 DC 10" in text


def test_an_open_secondary_is_a_floating_node():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 7, 4)
    place(parts, grid, "dc_source", 4, 2, "10")
    place(parts, grid, "transformer", 4, 4, "2")
    connect(wires, grid, (4, 2), (4, 4))
    connect(wires, grid, (5, 2), (5, 4))
    connect(wires, grid, (5, 4), (7, 4))

    with pytest.raises(SimulationError, match="only one connection"):
        build_netlist(parts, wires, grid)


def test_a_regulator_holds_the_typed_voltage():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 4)
    place(parts, grid, "dc_source", 4, 2, "9")
    place(parts, grid, "voltage_regulator", 4, 4, "5")
    place(parts, grid, "resistor", 4, 5, "1k")
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (5, 2), (5, 4))
    connect(wires, grid, (5, 4), (6, 4))
    connect(wires, grid, (4, 6), (6, 6))
    connect(wires, grid, (6, 6), (6, 4))
    text = build_netlist(parts, wires, grid)

    assert "* U1 5V" in text
    assert "XU1 N001 0 N002 REG voltage=5" in text
    assert "R1 N002 0 1k" in text
    assert "V1 N001 0 DC 9" in text
    assert ".subckt REG" in text


def test_a_555_netlist_includes_the_5k_divider():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 8, 8)
    place(parts, grid, "timer_555", 5, 5, "NE555")
    place(parts, grid, "dc_source", 3, 8, "5")
    connect(wires, grid, (3, 6), (3, 8))
    connect(wires, grid, (4, 8), (8, 8))
    connect(wires, grid, (3, 4), (7, 4))
    connect(wires, grid, (4, 6), (7, 6))
    connect(wires, grid, (7, 4), (7, 6))
    connect(wires, grid, (7, 6), (7, 8))
    text = build_netlist(parts, wires, grid)

    assert "X1 0 0 0 0 0 0 0 N001 NE555" in text
    assert "V1 N001 0 DC 5" in text
    assert ".subckt NE555" in text
    assert "R1 VCC CONT 5k" in text
    assert "R2 CONT third 5k" in text
    assert "R3 third GND 5k" in text


def test_a_mosfet_ties_the_bulk_to_the_source():
    def fet(kind, model):
        grid, parts, wires = new_circuit()
        place(parts, grid, "ground", 7, 4)
        place(parts, grid, kind, 4, 4, model)
        place(parts, grid, "dc_source", 4, 1, "2")
        place(parts, grid, "resistor", 3, 5, "1k")
        place(parts, grid, "dc_source", 3, 8, "5")
        connect(wires, grid, (4, 1), (4, 3))
        connect(wires, grid, (5, 1), (7, 1))
        connect(wires, grid, (7, 1), (7, 4))
        connect(wires, grid, (5, 4), (7, 4))
        connect(wires, grid, (3, 4), (3, 5))
        connect(wires, grid, (3, 6), (3, 8))
        connect(wires, grid, (4, 8), (7, 8))
        connect(wires, grid, (7, 8), (7, 4))
        return build_netlist(parts, wires, grid)

    nmos = fet("nmos", "2N7000")
    assert "M1 N001 N003 0 0 2N7000" in nmos
    assert ".model 2N7000 " in nmos

    pmos = fet("pmos", "BS250")
    assert "M1 0 N003 N001 N001 BS250" in pmos
    assert ".model BS250 " in pmos


def test_a_current_source_pushes_out_of_the_out_pin():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "current_source", 4, 2, "1m")
    place(parts, grid, "resistor", 4, 3, "1k")
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 4), (6, 4))
    connect(wires, grid, (6, 4), (6, 2))
    text = build_netlist(parts, wires, grid)

    assert "I1 0 N001 DC 1m" in text
    assert "R1 N001 0 1k" in text


def test_the_netlist_refuses_a_circuit_that_cannot_be_solved():
    grid, parts, wires = new_circuit()
    place(parts, grid, "dc_source", 4, 2, "5")

    with pytest.raises(SimulationError, match=r"Add a ground part\.$"):
        build_netlist(parts, wires, grid)

    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 4, 2)
    place(parts, grid, "resistor", 4, 3, "1k")

    with pytest.raises(SimulationError, match=r"Add a source before running\.$"):
        build_netlist(parts, wires, grid)

    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "5")
    connect(wires, grid, (5, 2), (6, 2))

    with pytest.raises(
            SimulationError,
            match=r"Node N001 has only one connection\."):
        build_netlist(parts, wires, grid)

    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "5")
    place(parts, grid, "resistor", 4, 4, "1k")
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 5))

    with pytest.raises(
            SimulationError,
            match=r"R1 is shorted: both pins are on the same net\."):
        build_netlist(parts, wires, grid)

    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 4, 2)
    place(parts, grid, "dc_source", 2, 2, "5")
    place(parts, grid, "diode", 4, 4, "ZZZ99")

    with pytest.raises(SimulationError, match="No model named 'ZZZ99'"):
        build_netlist(parts, wires, grid)

    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "5")
    place(parts, grid, "nmos", 4, 4, "2N3904")

    with pytest.raises(SimulationError, match="NPN") as error_info:
        build_netlist(parts, wires, grid)

    assert "NMOS" in str(error_info.value)


def test_one_part_is_not_a_circuit():
    grid, _parts, wires = new_circuit()
    component = Component("resistor", "R1", "1k", 2, 2)

    with pytest.raises(SimulationError, match="list of parts"):
        build_netlist(component, wires, grid)


def test_two_separate_grounds_are_both_node_0():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "ground", 6, 5)
    place(parts, grid, "dc_source", 4, 2, "5")
    place(parts, grid, "resistor", 4, 4, "1k")
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 4))
    connect(wires, grid, (4, 5), (6, 5))
    text = build_netlist(parts, wires, grid)

    assert "R1 N001 0 1k" in text
    assert "V1 N001 0 DC 5" in text


def test_r2_is_written_before_r10():
    grid, parts, wires = new_circuit()
    parts.place_saved("ground", "GND1", "", 6, 2, grid)
    parts.place_saved("dc_source", "V1", "10", 4, 2, grid)
    parts.place_saved("resistor", "R10", "10k", 4, 4, grid)
    parts.place_saved("resistor", "R2", "4k7", 4, 3, grid)
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))
    text = build_netlist(parts, wires, grid)

    assert text.index("R2 N001 N002 4.7k") < text.index("R10 N002 0 10k")


def test_every_placeable_kind_has_a_spice_line():
    expected = {
        "diode": "D1 n0 n1 1N4148",
        "led": "D1 n0 n1 LED_RED",
        "npn": "Q1 n1 n0 n2 2N3904",
        "pnp": "Q1 n2 n0 n1 2N3906",
        "nmos": "M1 n1 n0 n2 n2 2N7000",
        "pmos": "M1 n2 n0 n1 n1 BS250",
        "current_source": "I1 n1 n0 DC 1m",
        "switch": "RS1 n0 n1 1g",
        "opamp_generic": "X1 n0 n1 n3 n4 n2 OPAMP",
        "follower": "XA1 n0 n1 n2 n3 FOLLOW",
        "inverting_amp": "XA1 n0 n1 n2 n3 INVAMP gain=10",
        "noninverting_amp": "XA1 n0 n1 n2 n3 NONINV gain=2",
        "timer_555": "X1 n0 n1 n2 n3 n4 n5 n6 n7 NE555",
        "voltage_regulator": "XU1 n0 n1 n2 REG voltage=5",
        "capacitor_polarized": "C1 n0 n1 10u",
        "inductor": "L1 n0 n1 10u",
        "resistor": "R1 n0 n1 1k",
        "potentiometer": "RRV1A n0 n2 5k",
        "transformer": "FT1 n1 n0 ET1 1",
        "ac_source": "V1 n0 n1 DC 0 AC 1 SIN(0 1 1k 0 0 0)",
    }
    missing = []

    for kind, definition in COMPONENT_DEFINITIONS.items():
        if kind == "ground":
            continue

        reference = definition["prefix"] + "1"
        component = Component(
            kind, reference, definition["default_value_text"], 4, 4
        )
        node_of = {
            (reference, pin_name): f"n{index}"
            for index, (pin_name, _dx, _dy) in enumerate(definition["pins"])
        }

        try:
            lines = _element_lines(component, node_of)
        except SimulationError as error:
            missing.append(f"{kind}: {error}")
            continue

        if not lines:
            missing.append(kind)
            continue

        if kind in expected and expected[kind] not in lines:
            missing.append(f"{kind}: {lines}")

    assert missing == []


def test_write_netlist_file_replaces_the_destination(tmp_path):
    destination = tmp_path / "divider.cir"
    write_netlist_file(destination, DIVIDER)
    assert destination.read_text(encoding="utf-8") == DIVIDER

    write_netlist_file(destination, DIVIDER.replace("10k", "1k"))
    assert "1k" in destination.read_text(encoding="utf-8")
    assert list(tmp_path.glob("*.temporary")) == []

    with pytest.raises(SimulationError, match="folder does not exist"):
        write_netlist_file(tmp_path / "missing" / "divider.cir", DIVIDER)

    with pytest.raises(SimulationError, match="unfinished"):
        write_netlist_file(destination, "no newline")


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def file_menu_texts(window):
    file_menu = next(
        action.menu()
        for action in window.menuBar().actions()
        if action.text() == "&File"
    )

    return [action.text() for action in file_menu.actions()]


def test_export_writes_the_divider_and_ignores_a_probe(
        qt_application, tmp_path):
    window = MainWindow()

    try:
        build_divider(
            window.connection_grid,
            window.component_collection,
            window.wire_collection
        )
        probe = window.probe_collection.add_voltage(
            point(4, 4), window.connection_grid
        )
        window.probe_collection.set_method(probe.reference, "megohm")
        path = tmp_path / "divider.cir"

        assert window.export_netlist_to_path(path) is True
        assert path.read_text(encoding="utf-8") == DIVIDER
        assert "1meg" not in path.read_text(encoding="utf-8")
        assert window.statusBar().currentMessage() == (
            "Wrote netlist 'divider.cir'."
        )
        texts = file_menu_texts(window)
        assert texts.index("Save Project As...") < texts.index(
            "Export Netlist..."
        )
        assert texts.index("Export Netlist...") < texts.index("Print...")
    finally:
        close_window(window)


def test_export_adds_the_cir_suffix(qt_application, tmp_path, monkeypatch):
    window = MainWindow()

    try:
        build_divider(
            window.connection_grid,
            window.component_collection,
            window.wire_collection
        )
        chosen = tmp_path / "plain"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *args, **kwargs: (str(chosen), ""))
        )

        assert window.export_netlist() is True
        assert (tmp_path / "plain.cir").read_text(encoding="utf-8") == DIVIDER
    finally:
        close_window(window)


def test_export_without_ground_reports_the_reason_and_writes_nothing(
        qt_application, tmp_path, monkeypatch):
    window = MainWindow()
    recorded = []
    monkeypatch.setattr(
        window,
        "show_error_message",
        lambda title, reason, resolution: recorded.append((title, reason))
    )

    try:
        window.component_collection.add_component(
            "dc_source", 4, 2, "5", window.connection_grid
        )
        path = tmp_path / "open.cir"

        assert window.export_netlist_to_path(path) is False
        assert path.exists() is False
        assert recorded == [("Netlist Not Written", "Add a ground part.")]
    finally:
        close_window(window)
