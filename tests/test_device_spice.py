"""
Editable SPICE card numbers for the diode, BJT, MOSFET and JFET.

An untouched part keeps the library card. A typed number changes that
card, and ngspice is checked against the hand calculation.

Diode, 1 mA, IS = 1e-14 A, N = 1, RS = 0:
  Vt = kT/q at 27 C = 0.0258649258 V
  V = N*Vt*ln(I/IS + 1) = 0.655118 V
  RS = 100 ohm adds I*RS, so 0.755118 V.

BJT, Ib = 10 uA, BF = 100, VAF = 1 megohm, Vce = 5 V:
  Early effect is 5/1e6, so Ic = BF*Ib = 1 mA.

MOSFET level 1, W/L = 1, VGS = 3 V, VDS = 5 V, VTO = 1 V, KP = 0.2:
  With no series resistance and lambda = 0,
  Id = (KP/2)*(VGS - VTO)^2 = 0.4 A.
  The 2N7000 card still has Rs = 1, Rd = 1 and lambda = 0.02, and
  that same square law solves to 0.310456 A.

JFET, VGS = 0, VDS = 5 V, VTO = -2 V, BETA = 1 mA/V^2, LAMBDA = 0:
  Id = BETA*(VGS - VTO)^2 = 4 mA.
"""

import math

import pytest

from core.components import Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.netlist import build_netlist, spice_node_map
from core.spice_models import device_model_line
from core.wires import WireCollection
from sim import runner
from sim.runner import run_op

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)

_K = 1.380649e-23
_Q = 1.602176634e-19
_VT = _K * (273.15 + 27.0) / _Q
_DIODE_CURRENT = 1e-3
_DIODE_IS = 1e-14
_DIODE_VOLTAGE = _VT * math.log(_DIODE_CURRENT / _DIODE_IS + 1.0)


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def connect(wires, grid, start, end):
    wires.add_wire(point(*start), point(*end), grid)


def new_circuit():
    return ConnectionGrid(12, 12), ComponentCollection(), WireCollection()


def place(parts, grid, kind, row, column, value="", parameters=None,
          rotation=0):
    return parts.add_component(
        kind, row, column, value, grid, rotation, parameter_texts=parameters
    )


def node_at(parts, wires, grid, row, column):
    names, _draw_at = spice_node_map(parts, wires, grid)
    return names[point(row, column)]


def test_a_new_diode_keeps_the_1n4148_card():
    diode = Component("diode", "D1", "1N4148", 4, 4)

    assert diode.parameter_texts["is"] == "2.52n"
    assert diode.parameter_texts["n"] == "1.752"
    assert diode.parameter_texts["rs"] == "568m"
    assert diode.parameter_texts["cjo"] == "4p"
    assert diode.parameter_texts["tt"] == "20n"
    assert diode.parameter_texts["bv"] == "100"
    assert diode.parameter_texts["ibv"] == "1m"
    assert diode.label_text() == "D1 1N4148"

    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "5")
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "diode", 4, 4, "1N4148")
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (6, 2), (6, 5))
    connect(wires, grid, (4, 5), (6, 5))
    text = build_netlist(parts, wires, grid)

    assert "D1 N002 0 1N4148" in text
    assert device_model_line("1N4148") in text
    assert text.count(".model 1N4148") == 1


def test_an_old_file_fills_the_model_numbers():
    grid = ConnectionGrid(8, 8)
    parts = ComponentCollection()
    loaded = parts.place_saved(
        "npn", "Q1", "2N2222", 4, 4, grid, parameter_texts={}
    )

    assert loaded.parameter_texts["bf"] == "256"
    assert loaded.parameter_texts["vaf"] == "74"


def test_renaming_an_untouched_transistor_picks_up_the_new_card():
    transistor = Component("npn", "Q1", "2N3904", 4, 4)
    transistor.set_values("2N2222", {})

    assert transistor.value_text == "2N2222"
    assert transistor.parameter_texts["bf"] == "256"
    assert transistor.parameter_texts["cje"] == "22p"


def test_a_typed_gain_is_kept_when_the_model_name_changes():
    transistor = Component("npn", "Q1", "2N3904", 4, 4)
    transistor.set_values("2N2222", {"bf": "50"})

    assert transistor.parameter_texts["bf"] == "50"


def test_a_bad_card_number_says_what_is_allowed():
    with pytest.raises(ComponentError, match="is must be greater than zero"):
        Component(
            "diode", "D1", "1N4148", 4, 4, parameter_texts={"is": "0"}
        )

    with pytest.raises(ComponentError, match="rs must be zero or greater"):
        Component(
            "diode", "D1", "1N4148", 4, 4, parameter_texts={"rs": "-1"}
        )

    with pytest.raises(
        ComponentError, match="level must be a whole number, 1 or greater"
    ):
        Component(
            "nmos", "M1", "2N7000", 4, 4, parameter_texts={"level": "1.5"}
        )


def test_two_diodes_with_different_is_get_two_cards():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 8, 2)
    place(parts, grid, "dc_source", 4, 2, "5")
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "diode", 4, 4, "1N4148")
    place(parts, grid, "resistor", 4, 6, "1k")
    place(parts, grid, "diode", 4, 7, "1N4148", {"is": "10f"})
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (5, 2), (8, 2))
    connect(wires, grid, (4, 5), (8, 5))
    connect(wires, grid, (8, 2), (8, 5))
    # The second diode leaves the source above the first one.
    connect(wires, grid, (4, 2), (2, 2))
    connect(wires, grid, (2, 2), (2, 6))
    connect(wires, grid, (2, 6), (4, 6))
    connect(wires, grid, (4, 8), (8, 8))
    connect(wires, grid, (8, 5), (8, 8))
    text = build_netlist(parts, wires, grid)

    assert "D1 N002 0 1N4148" in text
    assert "D2 N003 0 1N4148_D2" in text
    assert device_model_line("1N4148") in text
    assert ".model 1N4148_D2 D(" in text
    assert "Is=10f" in text


@needs_ngspice
def test_a_typed_diode_follows_the_shockley_equation():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "current_source", 4, 2, "1m")
    place(parts, grid, "diode", 4, 3, "1N4148", {"is": "10f", "n": "1", "rs": "0"})
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (4, 4), (6, 4))
    connect(wires, grid, (6, 2), (6, 4))
    result = run_op(build_netlist(parts, wires, grid))

    assert result.voltages[node_at(parts, wires, grid, 4, 3)] == pytest.approx(
        _DIODE_VOLTAGE, abs=1e-4
    )

    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "current_source", 4, 2, "1m")
    place(
        parts, grid, "diode", 4, 3, "1N4148",
        {"is": "10f", "n": "1", "rs": "100"},
    )
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (4, 4), (6, 4))
    connect(wires, grid, (6, 2), (6, 4))
    result = run_op(build_netlist(parts, wires, grid))

    assert result.voltages[node_at(parts, wires, grid, 4, 3)] == pytest.approx(
        _DIODE_VOLTAGE + _DIODE_CURRENT * 100.0, abs=1e-4
    )


@needs_ngspice
def test_a_typed_beta_sets_the_collector_current():
    # Base current into the base pin, collector at 5 V, emitter grounded.
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 8, 2)
    place(parts, grid, "current_source", 5, 2, "10u")
    place(parts, grid, "dc_source", 4, 7, "5")
    transistor = place(
        parts, grid, "npn", 5, 5, "2N3904", {"bf": "100", "vaf": "1meg"}
    )
    connect(wires, grid, (5, 2), pin_point(transistor, "base"))
    connect(wires, grid, (6, 2), (8, 2))
    connect(wires, grid, pin_point(transistor, "emitter"), (8, 5))
    connect(wires, grid, (8, 2), (8, 5))
    connect(wires, grid, (4, 7), pin_point(transistor, "collector"))
    connect(wires, grid, (5, 7), (8, 7))
    connect(wires, grid, (8, 5), (8, 7))
    text = build_netlist(parts, wires, grid)
    result = run_op(text)
    collector = node_at(
        parts, wires, grid, *pin_point(transistor, "collector")
    )

    assert "Bf=100" in text
    assert "Vaf=1meg" in text
    assert result.voltages[collector] == pytest.approx(5.0, abs=1e-6)
    # The collector supply current is Ic, into the collector.
    assert -result.currents["V1"] == pytest.approx(1e-3, abs=1e-6)


@needs_ngspice
def test_a_typed_mosfet_current_includes_the_2n7000_resistances():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 8, 2)
    place(parts, grid, "dc_source", 5, 2, "3")
    # Rotation 270 puts minus one column to the right of plus.
    place(parts, grid, "dc_source", 4, 8, "5", rotation=270)
    fet = place(parts, grid, "nmos", 5, 5, "2N7000", {"vto": "1", "kp": "0.2"})
    connect(wires, grid, (5, 2), pin_point(fet, "gate"))
    connect(wires, grid, (6, 2), (8, 2))
    connect(wires, grid, pin_point(fet, "source"), (8, 5))
    connect(wires, grid, (8, 2), (8, 5))
    connect(wires, grid, (4, 8), pin_point(fet, "drain"))
    connect(wires, grid, (4, 9), (8, 9))
    connect(wires, grid, (8, 5), (8, 9))
    result = run_op(build_netlist(parts, wires, grid))

    assert -result.currents["V2"] == pytest.approx(0.310456, abs=1e-4)


@needs_ngspice
def test_a_typed_jfet_is_beta_times_the_pinchoff_squared():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 8, 2)
    place(parts, grid, "dc_source", 4, 8, "5", rotation=270)
    fet = place(
        parts, grid, "njfet", 5, 5, "2N3819",
        {"vt0": "-2", "beta": "1m", "lambda": "0"},
    )
    connect(wires, grid, pin_point(fet, "gate"), (8, 4))
    connect(wires, grid, (8, 2), (8, 4))
    connect(wires, grid, pin_point(fet, "source"), (8, 5))
    connect(wires, grid, (8, 4), (8, 5))
    connect(wires, grid, (4, 8), pin_point(fet, "drain"))
    connect(wires, grid, (4, 9), (8, 9))
    connect(wires, grid, (8, 5), (8, 9))
    result = run_op(build_netlist(parts, wires, grid))

    assert -result.currents["V1"] == pytest.approx(4e-3, abs=1e-6)


def pin_point(component, name):
    for pin_name, row, column in component.get_pin_positions():
        if pin_name == name:
            return (row, column)

    raise KeyError(name)
