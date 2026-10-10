"""
Standard op-amps, logic gates and small amplifier blocks.

Hand checks: a follower copies 1 V, an inverting gain of 10 makes -10 V,
and a non-inverting gain of 2 makes 2 V. A logic gate has no formula.
"""

import pytest
import sympy

from core.components import Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.node_formula import build_node_formulas
from core.subcircuit_models import (
    build_instance_line,
    get_subcircuit_text,
)
from core.wires import WireCollection


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def book(*parts):
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire(point(5, 2), point(6, 2), grid)
    wires.add_wire(point(4, 2), point(4, 3), grid)

    return build_node_formulas(parts, wires, grid)


def driven(kind, value):
    parts = [
        Component("ground", "GND1", "", 6, 2),
        Component("dc_source", "V1", "1", 4, 2),
        Component(kind, "A1", value, 4, 4),
    ]

    return book(*parts)


def same(expression, expected):
    assert expression is not None
    assert sympy.simplify(expression - expected) == 0


def test_follower_copies_the_input():
    result = driven("follower", "")

    same(result.expression_at(point(4, 5)), 1)
    same(result.expression_at(point(4, 3)), 1)
    assert result.text_at(point(3, 4)).startswith("No s-domain formula")


def test_inverting_amplifier_of_gain_10_is_minus_10_volts():
    result = driven("inverting_amp", "10")

    same(result.expression_at(point(4, 5)), -10)
    assert Component("inverting_amp", "A1", "10", 4, 4).label_text() == (
        "A1 -10"
    )


def test_noninverting_amplifier_of_gain_2_is_2_volts():
    result = driven("noninverting_amp", "2")

    same(result.expression_at(point(4, 5)), 2)
    assert Component(
        "noninverting_amp", "A1", "2", 4, 4
    ).label_text() == "A1 2"


def test_noninverting_gain_below_one_is_refused():
    with pytest.raises(ComponentError, match="at least 1"):
        Component("noninverting_amp", "A1", "0.5", 4, 4)


def test_an_and_gate_has_no_formula():
    result = book(
        Component("ground", "GND1", "", 6, 2),
        Component("gate_and", "X1", "AND2", 4, 4),
    )

    assert result.text_at(point(4, 5)) == (
        "X1 is a two-input AND gate, so there is no s-domain formula "
        "for this circuit."
    )


def test_lm358_is_an_ideal_opamp_in_the_formula():
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire(point(4, 5), point(4, 6), grid)
    wires.add_wire(point(4, 6), point(2, 6), grid)
    wires.add_wire(point(2, 6), point(2, 3), grid)
    wires.add_wire(point(2, 3), point(3, 3), grid)
    result = build_node_formulas(
        [
            Component("opamp_lm358", "X1", "LM358", 4, 4),
            Component("dc_source", "V1", "1", 5, 3),
            Component("ground", "GND1", "", 6, 3),
        ],
        wires,
        grid,
    )

    same(result.expression_at(point(4, 5)), 1)
    assert "Ideal op-amp" in result.text_at(point(4, 5))


def test_new_models_have_subcircuit_text():
    lm358 = get_subcircuit_text("lm358")
    assert ".subckt LM358 inp inn vp vn out" in lm358
    assert "EGAIN gain_node 0 inp inn 100k" in lm358

    and_gate = get_subcircuit_text("AND2")
    assert ".subckt AND2 a b y vcc gnd" in and_gate
    assert and_gate.endswith(".ends AND2\n")

    follower = get_subcircuit_text("FOLLOW")
    assert follower.startswith("* OPAMP:")
    assert ".subckt FOLLOW inp out vp vn" in follower

    assert build_instance_line(
        "X1", "AND2",
        {"A": "a", "B": "b", "Y": "y", "VCC": "vp", "GND": "0"},
    ) == "X1 a b y vp 0 AND2"
    assert build_instance_line(
        "X2", "INVAMP",
        {"in": "in", "out": "out", "V+": "vp", "V-": "vn"},
        {"gain": "10"},
    ) == "X2 in out vp vn INVAMP gain=10"


def test_a_gate_needs_its_supplies():
    with pytest.raises(ComponentError, match="wire VCC and GND"):
        build_instance_line(
            "X1", "NOT", {"A": "a", "Y": "y"}
        )


def test_amplifier_references_use_the_a_prefix():
    collection = ComponentCollection()
    grid = ConnectionGrid(8, 8)
    first = collection.add_component("follower", 4, 4, "", grid)
    second = collection.add_component("inverting_amp", 4, 7, "", grid)

    assert first.reference == "A1"
    assert first.label_text() == "A1"
    assert second.reference == "A2"
    assert second.value == 10
