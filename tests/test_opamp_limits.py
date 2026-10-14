"""
Output swing and gain-bandwidth on the six behavioural op-amps.

The numbers are the model's chosen typicals, checked by hand.

Supplies are +15 V and -15 V. The part is a unity-gain follower, so
the ideal output is the input. Limited holds it inside the rails:

  LM358 and LM324: 1.5 V below the positive rail, and the output can
  sit on the negative rail. 14 V becomes 13.5 V. -14 V stays -14 V.
  -16 V becomes -15 V.
  TL072, TL081 and TL082: 1.5 V inside both rails. -14 V becomes
  -13.5 V, and 14 V becomes 13.5 V.
  NE5532: 2 V inside both rails. 14 V becomes 13 V, and -14 V becomes
  -13 V.
  1 V stays 1 V. The DC gain error is about 1/100000.

At the gain-bandwidth frequency the open-loop gain is 1 at -90
degrees. A unity-gain follower of a 1 V source is then (1 - j) / 2:
magnitude 1/sqrt(2) and phase -45 degrees. The flat model at that
same frequency stays at 1 V and 0 degrees. V(s) stays the ideal rule
either way.
"""

import math

import pytest

from core.components import Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.netlist import build_netlist, spice_node_map
from core.node_formula import build_node_formulas
from core.subcircuit_models import get_subcircuit_text
from core.wires import WireCollection
from sim import runner
from sim.runner import run_ac, run_op

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)

# |1 / (1 + j)| when the open-loop gain is 1 at -90 degrees.
_AT_GBW = 1.0 / math.sqrt(2.0)
_LIMITED = {"limits": "limited"}


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def connect(wires, grid, start, end):
    wires.add_wire(point(*start), point(*end), grid)


def pin(component, name):
    for pin_name, row, column in component.get_pin_positions():
        if pin_name == name:
            return (row, column)

    raise KeyError(name)


def follower(kind, value, input_value, limits="flat", alternating=False,
            extra=None, closed=True):
    """
    Unity-gain follower on +/- 15 V.

    The op-amp anchor is (6, 6): in+ (7, 5), in- (5, 5), out (6, 7),
    V+ (5, 6), V- (7, 6). Feedback leaves out to the right, crosses
    above the symbol, and comes down to in-. The supplies lie beside
    V+ and V- so their other pin is not on that wire.

    :returns: grid, parts, wires, the op-amp, the output point.
    :rtype: tuple
    """
    grid = ConnectionGrid(12, 12)
    parts = ComponentCollection()
    wires = WireCollection()
    texts = {"limits": limits}

    if extra:
        texts.update(extra)

    opamp = parts.add_component(
        kind, 6, 6, value, grid, parameter_texts=texts
    )
    source_kind = "ac_source" if alternating else "dc_source"
    parameters = {"frequency": "1k"} if alternating else None
    parts.add_component(
        source_kind, 7, 2, input_value, grid, parameter_texts=parameters
    )
    # Rotation 270 puts minus one column to the right of plus.
    parts.add_component("dc_source", 5, 8, "15", grid, rotation=270)
    parts.add_component("dc_source", 8, 6, "-15", grid, rotation=270)
    parts.add_component("ground", 12, 12, "", grid)

    if closed:
        connect(wires, grid, (6, 7), (6, 11))
        connect(wires, grid, (6, 11), (1, 11))
        connect(wires, grid, (1, 11), (1, 5))
        connect(wires, grid, (1, 5), (5, 5))
    else:
        # in- sits on ground. Column 1 stays clear of the +15 V wire.
        connect(wires, grid, (5, 1), (5, 5))
        connect(wires, grid, (5, 1), (12, 1))
        connect(wires, grid, (12, 1), (12, 2))
        # 1 megohm on column 10, above the output, then across to the
        # ground wire on column 1. Rout is 50 ohm, so the output is
        # 1e6 / (1e6 + 50) of the open-circuit voltage.
        load = parts.add_component(
            "resistor", 4, 10, "1meg", grid, rotation=90
        )
        by_name = {
            name: (row, column)
            for name, row, column in load.get_pin_positions()
        }
        connect(wires, grid, pin(opamp, "out"), (6, 10))
        connect(wires, grid, (6, 10), by_name["2"])
        connect(wires, grid, by_name["1"], (4, 1))
        connect(wires, grid, (4, 1), (12, 1))

    connect(wires, grid, (5, 8), (5, 6))
    connect(wires, grid, (8, 6), (7, 6))
    connect(wires, grid, (7, 2), (7, 5))
    # The +15 V return crosses the feedback on row 6 and hops over it.
    wires.add_wire(
        point(5, 9), point(9, 9), grid,
        bridged_identifiers=(point(6, 9),),
    )
    connect(wires, grid, (9, 9), (12, 9))
    connect(wires, grid, (12, 9), (12, 12))
    connect(wires, grid, (8, 7), (12, 7))
    connect(wires, grid, (12, 7), (12, 12))
    connect(wires, grid, (8, 2), (12, 2))
    connect(wires, grid, (12, 2), (12, 12))

    return grid, parts, wires, opamp, pin(opamp, "out")


def output_node(parts, wires, grid, output):
    names, _draw_at = spice_node_map(parts, wires, grid)
    return names[point(*output)]


def test_flat_text_is_unchanged_and_limited_text_is_separate():
    flat = get_subcircuit_text("LM358")

    assert ".subckt LM358 inp inn vp vn out" in flat
    assert "gain=100k rin=1meg rout=50" in flat
    assert "EGAIN gain_node 0 inp inn {gain}" in flat
    assert "ROUT gain_node out {rout}" in flat
    assert "BCLAMP" not in flat
    assert "LIM" not in flat

    limited = get_subcircuit_text("LM358LIM")

    assert ".subckt LM358LIM inp inn vp vn out" in limited
    assert "gain=100k rin=1meg rout=50 gbw=1meg head_high=1.5 head_low=0" in (
        limited
    )
    assert "RIN inp inn {rin}" in limited
    assert "RPOLE filt 0 {gain}" in limited
    assert "CPOLE filt 0 {1/(6.283185307179586*gbw)}" in limited
    assert "ROUT pre out {rout}" in limited
    assert (
        "BCLAMP pre 0 V = min(max(V(filt), V(vn)+{head_low}), "
        "V(vp)-{head_high})"
        in limited
    )
    assert "EGAIN" not in limited
    assert "1meg Hz" in limited

    tl072 = get_subcircuit_text("TL072LIM")
    assert "gain=200k" in tl072
    assert "rin=1T" in tl072
    assert "rout=75" in tl072
    assert "gbw=3meg" in tl072
    assert "head_high=1.5" in tl072 and "head_low=1.5" in tl072
    assert "3meg Hz" in tl072

    ne5532 = get_subcircuit_text("NE5532LIM")
    assert "gain=100k" in ne5532
    assert "rin=300k" in ne5532
    assert "rout=10" in ne5532
    assert "gbw=10meg" in ne5532
    assert "head_high=2" in ne5532 and "head_low=2" in ne5532
    assert "10meg Hz" in ne5532

    for name in ("TL081", "TL082"):
        text = get_subcircuit_text(f"{name}LIM")
        assert "gbw=3meg" in text
        assert "head_low=1.5" in text

    lm324 = get_subcircuit_text("LM324LIM")
    assert "gbw=1meg" in lm324
    assert "head_low=0" in lm324


def test_a_new_opamp_is_flat_and_an_old_file_stays_flat():
    fresh = Component("opamp_lm358", "X1", "LM358", 4, 4)

    assert fresh.parameter_texts == {
        "limits": "flat",
        "gain": "100k",
        "rin": "1meg",
        "rout": "50",
        "gbw": "1meg",
        "head_high": "1.5",
        "head_low": "0",
    }
    assert fresh.label_text() == "X1 LM358"

    grid = ConnectionGrid(8, 8)
    parts = ComponentCollection()
    loaded = parts.place_saved(
        "opamp_lm358", "X1", "LM358", 4, 4, grid, parameter_texts={}
    )

    assert loaded.parameter_texts == fresh.parameter_texts

    limited = Component(
        "opamp_lm358", "X2", "LM358", 4, 4, parameter_texts=_LIMITED
    )

    assert limited.parameter_texts["limits"] == "limited"
    assert limited.parameter_texts["gain"] == "100k"
    assert limited.label_text() == "X2 LM358"
    assert Component("opamp_generic", "X3", "OPAMP", 4, 4).parameter_texts == {}
    assert Component("opamp_741", "X4", "LM741", 4, 4).parameter_texts == {}


def test_the_limited_model_name_is_not_a_part_value():
    with pytest.raises(ComponentError, match="Limits setting, flat or limited"):
        Component("opamp_lm358", "X1", "LM358LIM", 4, 4)

    with pytest.raises(ComponentError, match="must be one of flat, limited"):
        Component(
            "opamp_tl072", "X1", "TL072", 4, 4,
            parameter_texts={"limits": "both"},
        )


def test_the_formula_stays_ideal_when_limits_are_on():
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire(point(4, 5), point(4, 6), grid)
    wires.add_wire(point(4, 6), point(2, 6), grid)
    wires.add_wire(point(2, 6), point(2, 3), grid)
    wires.add_wire(point(2, 3), point(3, 3), grid)
    result = build_node_formulas(
        [
            Component(
                "opamp_lm358", "X1", "LM358", 4, 4, parameter_texts=_LIMITED
            ),
            Component("dc_source", "V1", "1", 5, 3),
            Component("ground", "GND1", "", 6, 3),
        ],
        wires,
        grid,
    )

    assert result.expression_at(point(4, 5)) == 1
    assert "Ideal op-amp" in result.text_at(point(4, 5))


def test_flat_writes_lm358_and_limited_writes_lm358lim():
    _grid, parts, wires, _opamp, _output = follower(
        "opamp_lm358", "LM358", "1", limits="flat"
    )
    flat = build_netlist(parts, wires, _grid)

    assert " LM358" in flat
    assert "LM358LIM" not in flat
    assert flat.count(".subckt LM358 ") == 1

    grid, parts, wires, _opamp, _output = follower(
        "opamp_lm358", "LM358", "1", limits="limited"
    )
    limited = build_netlist(parts, wires, grid)

    assert " LM358LIM" in limited
    assert ".subckt LM358 " not in limited
    assert limited.count(".subckt LM358LIM ") == 1
    assert "BCLAMP" in limited


@pytest.mark.parametrize("kind, value, volts, expected", [
    ("opamp_lm358", "LM358", "1", 1.0),
    ("opamp_lm358", "LM358", "14", 13.5),
    ("opamp_lm358", "LM358", "-14", -14.0),
    ("opamp_lm358", "LM358", "-16", -15.0),
    ("opamp_lm324", "LM324", "14", 13.5),
    ("opamp_tl072", "TL072", "14", 13.5),
    ("opamp_tl072", "TL072", "-14", -13.5),
    ("opamp_tl081", "TL081", "-14", -13.5),
    ("opamp_tl082", "TL082", "14", 13.5),
    ("opamp_ne5532", "NE5532", "14", 13.0),
    ("opamp_ne5532", "NE5532", "-14", -13.0),
])
@needs_ngspice
def test_a_limited_follower_clips_at_the_chosen_headroom(
        kind, value, volts, expected):
    grid, parts, wires, _opamp, output = follower(
        kind, value, volts, limits="limited"
    )
    result = run_op(build_netlist(parts, wires, grid))

    assert result.voltages[output_node(parts, wires, grid, output)] == (
        pytest.approx(expected, abs=0.02)
    )


@pytest.mark.parametrize("kind, value, hertz", [
    ("opamp_lm358", "LM358", 1e6),
    ("opamp_tl072", "TL072", 3e6),
    ("opamp_ne5532", "NE5532", 10e6),
])
@needs_ngspice
def test_a_limited_follower_is_one_over_root_two_at_the_gain_bandwidth(
        kind, value, hertz):
    grid, parts, wires, _opamp, output = follower(
        kind, value, "1", limits="limited", alternating=True
    )
    sweep = run_ac(build_netlist(parts, wires, grid), hertz, hertz * 10, 1)
    sample = sweep.voltages[output_node(parts, wires, grid, output)][0]

    assert sweep.frequency[0] == pytest.approx(hertz)
    assert abs(sample) == pytest.approx(_AT_GBW, abs=0.01)
    assert math.degrees(math.atan2(sample.imag, sample.real)) == (
        pytest.approx(-45.0, abs=1.0)
    )


def test_a_bad_spice_number_says_what_is_allowed():
    with pytest.raises(ComponentError, match="gain must be greater than zero"):
        Component(
            "opamp_lm358", "X1", "LM358", 4, 4, parameter_texts={"gain": "0"}
        )

    with pytest.raises(
        ComponentError, match="high headroom must be zero or greater"
    ):
        Component(
            "opamp_lm358", "X1", "LM358", 4, 4,
            parameter_texts={"head_high": "-1"},
        )


@needs_ngspice
def test_an_open_loop_gain_of_10_makes_0_1_v_into_1_v():
    # Flat model: V(open) = gain * (in+ - in-). in- is ground, so
    # 10 * 0.1 V is 1 V. A 1 megohm load with Rout 50 ohm is
    # 1e6 / (1e6 + 50) of that, which is 0.99995 V.
    grid, parts, wires, _opamp, output = follower(
        "opamp_lm358", "LM358", "0.1", limits="flat",
        extra={"gain": "10"}, closed=False,
    )
    result = run_op(build_netlist(parts, wires, grid))

    assert result.voltages[output_node(parts, wires, grid, output)] == (
        pytest.approx(1.0, abs=0.001)
    )


@needs_ngspice
def test_a_typed_headroom_of_3_v_clips_14_v_to_12_v():
    # +15 V rail, high headroom 3 V, so the output stops at 12 V.
    grid, parts, wires, _opamp, output = follower(
        "opamp_lm358", "LM358", "14", limits="limited",
        extra={"head_high": "3"},
    )
    result = run_op(build_netlist(parts, wires, grid))

    assert result.voltages[output_node(parts, wires, grid, output)] == (
        pytest.approx(12.0, abs=0.02)
    )


@needs_ngspice
def test_a_flat_follower_stays_at_one_volt_at_1_megahertz():
    grid, parts, wires, _opamp, output = follower(
        "opamp_lm358", "LM358", "1", limits="flat", alternating=True
    )
    sweep = run_ac(build_netlist(parts, wires, grid), 1e6, 10e6, 1)
    sample = sweep.voltages[output_node(parts, wires, grid, output)][0]

    assert abs(sample) == pytest.approx(1.0, abs=0.01)
    assert math.degrees(math.atan2(sample.imag, sample.real)) == (
        pytest.approx(0.0, abs=1.0)
    )
