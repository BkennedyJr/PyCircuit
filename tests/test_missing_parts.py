"""
MOSFET, switch, potentiometer, transformer, 555 and voltage regulator.

Hand checks, with pin 2 of the potentiometer at ground and 10 V on pin 1:
the wiper is 5 V at position 0.5, 0 V at position 0 and 10 V at position 1,
and the current into pin 1 is 1 mA. A closed switch in series with 1 k
from 10 V carries 10 mA. An ideal transformer with Ns/Np = 2 turns 10 V
into 20 V; a 1 k load on that secondary draws 20 mA and the primary draws
40 mA. A regulator set to 5 V holds 5 V across a 1 k load (5 mA) even
when the input is only 3 V.
"""

import pytest
import sympy

from core.components import Component
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.node_formula import build_node_formulas
from core.subcircuit_models import build_instance_line, get_subcircuit_text
from core.wires import WireCollection


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def circuit(parts, links):
    grid = ConnectionGrid(12, 12)
    wires = WireCollection()

    for (row_1, column_1), (row_2, column_2) in links:
        wires.add_wire(point(row_1, column_1), point(row_2, column_2), grid)

    return build_node_formulas(parts, wires, grid)


def same(expression, expected):
    assert expression is not None
    assert sympy.simplify(expression - expected) == 0


def test_labels():
    assert Component("switch", "S1", "", 4, 4).label_text() == "S1 open"
    assert Component(
        "switch", "S1", "", 4, 4, parameter_texts={"state": "closed"}
    ).label_text() == "S1 closed"
    assert Component(
        "potentiometer", "RV1", "10k", 4, 4
    ).label_text() == "RV1 10k 0.5"
    assert Component("transformer", "T1", "2", 4, 4).label_text() == "T1 2"
    assert Component(
        "voltage_regulator", "U1", "5", 4, 4
    ).label_text() == "U1 5V"
    assert Component("nmos", "M1", "2N7000", 4, 4).label_text() == "M1 2N7000"
    assert Component("timer_555", "X1", "NE555", 4, 4).label_text() == (
        "X1 NE555"
    )
    assert Component("ground", "GND1", "", 4, 4).label_text() == ""


def test_potentiometer_position_must_be_from_0_to_1():
    Component(
        "potentiometer", "RV1", "10k", 4, 4,
        parameter_texts={"position": "0"}
    )
    Component(
        "potentiometer", "RV1", "10k", 4, 4,
        parameter_texts={"position": "1"}
    )

    with pytest.raises(ComponentError, match="from 0 to 1"):
        Component(
            "potentiometer", "RV1", "10k", 4, 4,
            parameter_texts={"position": "1.1"}
        )


def test_switch_state_must_be_open_or_closed():
    with pytest.raises(ComponentError, match="open, closed"):
        Component(
            "switch", "S1", "", 4, 4, parameter_texts={"state": "half"}
        )


def test_closed_switch_in_series_with_1k_carries_10_milliamps():
    parts = [
        Component("ground", "GND1", "", 6, 2),
        Component("dc_source", "V1", "10", 4, 2),
        Component(
            "switch", "S1", "", 4, 3, parameter_texts={"state": "closed"}
        ),
        Component("resistor", "R1", "1k", 4, 4),
    ]
    result = circuit(parts, [
        ((5, 2), (6, 2)),
        ((4, 2), (4, 3)),
        ((4, 5), (6, 5)),
        ((6, 2), (6, 5)),
    ])

    same(result.expression_at(point(4, 4)), 10)
    same(result.current_expression(parts[2]), sympy.Rational(1, 100))
    same(result.current_expression(parts[3]), sympy.Rational(1, 100))
    assert result.current_text(parts[2]) == "I = 0.01 A"


def test_open_switch_leaves_the_load_at_zero():
    parts = [
        Component("ground", "GND1", "", 6, 2),
        Component("dc_source", "V1", "10", 4, 2),
        Component("switch", "S1", "", 4, 3),
        Component("resistor", "R1", "1k", 4, 4),
    ]
    result = circuit(parts, [
        ((5, 2), (6, 2)),
        ((4, 2), (4, 3)),
        ((4, 5), (6, 5)),
        ((6, 2), (6, 5)),
    ])

    same(result.expression_at(point(4, 2)), 10)
    same(result.expression_at(point(4, 4)), 0)
    same(result.current_expression(parts[2]), 0)
    assert result.current_text(parts[2]) == "I = 0 A"


def _divider(position):
    parts = [
        Component("ground", "GND1", "", 8, 2),
        Component("dc_source", "V1", "10", 4, 2),
        Component(
            "potentiometer", "RV1", "10k", 4, 3,
            parameter_texts={"position": position}
        ),
    ]
    result = circuit(parts, [
        ((5, 2), (8, 2)),
        ((4, 2), (4, 3)),
        ((4, 5), (8, 5)),
        ((8, 2), (8, 5)),
    ])

    return (parts, result)


def test_potentiometer_at_half_is_5_volts_and_1_milliamp():
    parts, result = _divider("0.5")

    same(result.expression_at(point(5, 4)), 5)
    same(result.current_expression(parts[2]), sympy.Rational(1, 1000))
    assert result.current_text(parts[2]) == "I = 0.001 A"


def test_potentiometer_at_the_ends():
    low_parts, at_pin_2 = _divider("0")
    high_parts, at_pin_1 = _divider("1")

    same(at_pin_2.expression_at(point(5, 4)), 0)
    same(at_pin_2.current_expression(low_parts[2]), sympy.Rational(1, 1000))
    same(at_pin_1.expression_at(point(5, 4)), 10)
    same(at_pin_1.current_expression(high_parts[2]), sympy.Rational(1, 1000))


def _transformer(turns, load):
    parts = [
        Component("ground", "GND1", "", 8, 2),
        Component("dc_source", "V1", "10", 3, 4),
        Component("transformer", "T1", turns, 3, 5),
    ]
    links = [
        ((4, 4), (4, 5)),
        ((3, 4), (3, 5)),
        ((4, 5), (8, 5)),
        ((8, 2), (8, 5)),
        ((4, 6), (8, 6)),
        ((8, 5), (8, 6)),
    ]

    if load:
        parts.append(Component("resistor", "R1", "1k", 3, 6))
        links.append(((3, 7), (4, 7)))
        links.append(((4, 6), (4, 7)))

    return (parts, circuit(parts, links))


def test_transformer_of_turns_2_is_20_volts_open():
    parts, result = _transformer("2", False)

    same(result.expression_at(point(3, 6)), 20)
    same(result.current_expression(parts[2]), 0)
    assert result.current_text(parts[2]) == "I = 0 A"


def test_loaded_transformer_draws_40_milliamps_on_the_primary():
    parts, result = _transformer("2", True)

    same(result.expression_at(point(3, 6)), 20)
    same(result.current_expression(parts[2]), sympy.Rational(1, 25))
    same(result.current_expression(parts[3]), sympy.Rational(1, 50))
    assert result.current_text(parts[2]) == "I = 0.04 A"


def _regulator(input_volts):
    parts = [
        Component("ground", "GND1", "", 8, 4),
        Component("dc_source", "V1", input_volts, 4, 2),
        Component("voltage_regulator", "U1", "5", 4, 4),
        Component("resistor", "R1", "1k", 4, 5),
    ]
    result = circuit(parts, [
        ((4, 2), (4, 3)),
        ((5, 2), (5, 4)),
        ((5, 4), (8, 4)),
        ((4, 6), (5, 6)),
        ((5, 4), (5, 6)),
    ])

    return (parts, result)


def test_regulator_holds_5_volts_and_5_milliamps():
    parts, result = _regulator("9")

    same(result.expression_at(point(4, 2)), 9)
    same(result.expression_at(point(4, 5)), 5)
    same(result.current_expression(parts[2]), sympy.Rational(1, 200))
    assert result.current_text(parts[2]) == "I = 0.005 A"


def test_regulator_ignores_dropout():
    _parts, result = _regulator("3")

    same(result.expression_at(point(4, 5)), 5)


def test_mosfet_and_555_have_no_formula():
    nmos = Component("nmos", "M1", "2N7000", 4, 4)
    timer = Component("timer_555", "X2", "NE555", 4, 6)
    result = circuit(
        [Component("ground", "GND1", "", 6, 2), nmos], []
    )

    # The gate is one column left of the anchor. The anchor itself is
    # the body centre, not a pin.
    assert result.text_at(point(4, 3)) == (
        "M1 is a MOSFET, so there is no s-domain formula for this circuit."
    )
    result = circuit(
        [Component("ground", "GND1", "", 6, 2), timer], []
    )
    assert result.text_at(point(3, 5)).startswith(
        "X2 is a 555 timer, so there is no s-domain formula"
    )


def test_ne555_subcircuit_is_the_divider_only():
    text = get_subcircuit_text("NE555")

    assert ".subckt NE555 GND TRIG OUT RESET CONT THRES DISCH VCC" in text
    assert "R1 VCC CONT 5k" in text
    assert "R2 CONT third 5k" in text
    assert "R3 third GND 5k" in text
    assert ".ends NE555" in text
    assert "latch" in text
    nodes = {
        "GND": "0", "TRIG": "N2", "OUT": "N3", "RESET": "N4",
        "CONT": "N5", "THRES": "N6", "DISCH": "N7", "VCC": "N8",
    }
    assert build_instance_line("X1", "NE555", nodes) == (
        "X1 0 N2 N3 N4 N5 N6 N7 N8 NE555"
    )

    with pytest.raises(ComponentError, match="wire VCC and GND"):
        build_instance_line("X1", "NE555", {"TRIG": "N2", "OUT": "N3"})
