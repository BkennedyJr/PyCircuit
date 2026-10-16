"""
DC operating point without ngspice.

Hand calculation for the divider: 10 V across 10k + 10k is 5 V in the
middle, and 10 V / 20k = 0.5 mA. The source current leaves the positive
pin, so it is +0.5 mA. A 1 mA source into 1k is 1 V. An inductor is a
short, so the node after it is the source voltage. A capacitor is an
open, so a node that hangs on one is floating.
"""

import math

import pytest

from core.components import COMPONENT_DEFINITIONS, Component
from core.connection_grid import ConnectionGrid
from core.exceptions import SimulationError
from core.wires import WireCollection
from sim.dc_solver import solve_dc


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def solve(parts, wires=(), labels=(), size=8):
    grid = ConnectionGrid(size, size)
    collection = WireCollection()

    for start, end in wires:
        collection.add_wire(point(*start), point(*end), grid)

    for row, column, name in labels:
        grid.set_net_label(point(row, column), name)

    return solve_dc(parts, collection, grid)


def test_divider_midpoint_is_5_volts_and_current_is_half_a_milliamp():
    # 10 V / 20k = 0.5 mA. The middle of two equal resistors is 5 V.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("dc_source", "V1", "10", 4, 2),
            Component("resistor", "R1", "10k", 4, 3),
            Component("resistor", "R2", "10k", 4, 4),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (6, 2)),
            ((4, 5), (6, 5)),
            ((6, 2), (6, 5)),
        ],
    )

    assert result.voltage_at(point(4, 2)) == pytest.approx(10)
    assert result.voltage_at(point(4, 4)) == pytest.approx(5)
    assert result.voltage_at(point(6, 2)) == pytest.approx(0)
    assert result.current_through("V1") == pytest.approx(0.0005)
    assert result.current_through("R1") == pytest.approx(0.0005)
    assert result.current_through("R2") == pytest.approx(0.0005)


def test_one_milliamp_through_1k_is_1_volt():
    result = solve([
        Component("ground", "GND1", "", 3, 2),
        Component("current_source", "I1", "1m", 2, 2),
        Component("resistor", "R1", "1k", 2, 2, 90),
    ])

    assert result.voltage_at(point(2, 2)) == pytest.approx(1)
    assert result.current_through("I1") == pytest.approx(0.001)
    assert result.current_through("R1") == pytest.approx(0.001)


def test_an_inductor_is_a_short_at_dc():
    # 10 V across 2k is 5 mA. The inductor drops no voltage.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("dc_source", "V1", "10", 4, 2),
            Component("inductor", "L1", "10u", 4, 2),
            Component("resistor", "R1", "2k", 4, 3),
        ],
        wires=[((5, 2), (6, 2)), ((4, 4), (6, 4)), ((6, 2), (6, 4))],
    )

    assert result.voltage_at(point(4, 3)) == pytest.approx(10)
    assert result.current_through("L1") == pytest.approx(0.005)
    assert result.current_through("R1") == pytest.approx(0.005)
    assert result.current_through("V1") == pytest.approx(0.005)


def test_a_capacitor_across_a_resistor_draws_no_dc_current():
    # 10 V / 1k = 10 mA through the resistor. The capacitor is open.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("dc_source", "V1", "10", 4, 2),
            Component("resistor", "R1", "1k", 4, 2, 90),
            Component("capacitor", "C1", "1u", 4, 2, 90),
        ],
        wires=[((5, 2), (6, 2))],
    )

    assert result.voltage_at(point(4, 2)) == pytest.approx(10)
    assert result.current_through("R1") == pytest.approx(0.01)
    assert result.current_through("C1") == pytest.approx(0)


def test_a_node_on_only_a_capacitor_has_no_dc_solution():
    with pytest.raises(SimulationError) as caught:
        solve(
            [
                Component("ground", "GND1", "", 6, 2),
                Component("dc_source", "V1", "10", 4, 2),
                Component("capacitor", "C1", "1u", 4, 2),
            ],
            wires=[((5, 2), (6, 2))],
        )

    assert "no single DC solution" in str(caught.value)


def test_an_ac_source_uses_its_offset():
    # Offset 2 V across 1k is 2 mA. The 5 V peak is not the DC voltage.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("ac_source", "V1", "5", 4, 2, 0, {"offset": "2"}),
            Component("resistor", "R1", "1k", 4, 2, 90),
        ],
        wires=[((5, 2), (6, 2))],
    )

    assert result.voltage_at(point(4, 2)) == pytest.approx(2)
    assert result.current_through("V1") == pytest.approx(0.002)


def test_a_shared_net_name_joins_the_source_to_the_load():
    # 10 V / 1k = 10 mA. Vcc joins the source to the resistor.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("dc_source", "V1", "10", 4, 2),
            Component("resistor", "R1", "1k", 2, 5),
        ],
        wires=[((5, 2), (6, 2)), ((2, 6), (6, 6)), ((6, 2), (6, 6))],
        labels=[(4, 2, "Vcc"), (2, 5, "vcc")],
    )

    assert result.voltage_at(point(2, 5)) == pytest.approx(10)
    assert result.current_through("R1") == pytest.approx(0.01)
    assert result.current_through("V1") == pytest.approx(0.01)


def test_a_missing_ground_is_named():
    with pytest.raises(SimulationError) as caught:
        solve([
            Component("dc_source", "V1", "10", 4, 2),
            Component("resistor", "R1", "1k", 4, 2, 90),
        ])

    assert str(caught.value) == (
        "Add a ground part before the DC voltages can be found."
    )


def test_a_shorted_voltage_source_has_no_solution():
    with pytest.raises(SimulationError) as caught:
        solve(
            [
                Component("ground", "GND1", "", 6, 2),
                Component("dc_source", "V1", "10", 4, 2),
            ],
            wires=[((4, 2), (5, 2)), ((5, 2), (6, 2))],
        )

    assert "no single DC solution" in str(caught.value)


def _scalar_diode(volts, ohms, saturation, emission, series):
    """
    One-resistor diode drop from the Shockley equation.

    Id = Is * (exp(Vj / (N*Vt)) - 1), Vt = 0.02585, and the terminal
    drop is Vj + Id*Rs. Independent of the circuit matrix.
    """
    thermal = emission * 0.02585
    junction = 0.5

    for _step in range(80):
        argument = junction / thermal
        exponential = math.exp(argument)
        current = saturation * (exponential - 1.0)
        conductance = saturation * exponential / thermal
        mismatch = volts - junction - current * (series + ohms)
        slope = -(1.0 + (series + ohms) * conductance)
        delta = -mismatch / slope

        if delta > 0.1:
            delta = 0.1
        elif delta < -0.1:
            delta = -0.1

        junction += delta

    exponential = math.exp(junction / thermal)
    current = saturation * (exponential - 1.0)
    terminal = junction + current * series

    return terminal, current


def test_a_1n4148_drops_about_0_65_volts():
    # 5 V through 1k into a 1N4148 (Is 2.52 nA, N 1.752, Rs 0.568).
    # At 0.65 V the junction current is about 4.3 mA.
    drop, current = _scalar_diode(5.0, 1e3, 2.52e-9, 1.752, 0.568)
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("dc_source", "V1", "5", 4, 2),
            Component("resistor", "R1", "1k", 4, 2),
            Component("diode", "D1", "1N4148", 4, 3),
        ],
        wires=[((5, 2), (6, 2)), ((4, 4), (6, 4)), ((6, 2), (6, 4))],
    )

    assert drop == pytest.approx(0.65, abs=0.05)
    assert current == pytest.approx(0.0043, abs=2e-4)
    assert result.voltage_at(point(4, 3)) == pytest.approx(drop)
    assert result.current_through("D1") == pytest.approx(current)
    assert result.current_through("R1") == pytest.approx(current)
    assert result.current_through("V1") == pytest.approx(current)


def test_a_red_led_uses_its_card():
    drop, current = _scalar_diode(5.0, 1e3, 1e-21, 2.2, 4.0)
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("dc_source", "V1", "5", 4, 2),
            Component("resistor", "R1", "1k", 4, 2),
            Component("led", "D1", "LED_RED", 4, 3),
        ],
        wires=[((5, 2), (6, 2)), ((4, 4), (6, 4)), ((6, 2), (6, 4))],
    )

    assert result.voltage_at(point(4, 3)) == pytest.approx(drop)
    assert result.current_through("D1") == pytest.approx(current)


def test_a_closed_switch_is_a_short_and_an_open_switch_is_not():
    # 10 V into 1k. Closed is 1e-9 ohm, so the load is 10 V and 10 mA.
    # Open is 1e9 ohm, so the load is about 0 V.
    closed = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("dc_source", "V1", "10", 4, 2),
            Component(
                "switch", "S1", "", 4, 3, 0, {"state": "closed"}
            ),
            Component("resistor", "R1", "1k", 4, 4),
        ],
        wires=[
            ((5, 2), (6, 2)),
            ((4, 2), (4, 3)),
            ((4, 5), (6, 5)),
            ((6, 2), (6, 5)),
        ],
    )

    assert closed.voltage_at(point(4, 4)) == pytest.approx(10.0, abs=1e-6)
    assert closed.current_through("R1") == pytest.approx(0.01, abs=1e-6)

    opened = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("dc_source", "V1", "10", 4, 2),
            Component("switch", "S1", "", 4, 3),
            Component("resistor", "R1", "1k", 4, 4),
        ],
        wires=[
            ((5, 2), (6, 2)),
            ((4, 2), (4, 3)),
            ((4, 5), (6, 5)),
            ((6, 2), (6, 5)),
        ],
    )

    assert opened.voltage_at(point(4, 4)) == pytest.approx(0.0, abs=1e-4)


def test_a_pot_at_half_is_5_volts_and_at_a_quarter_is_2_5():
    # 10 V across 10k. Position 0.5 is 5 V. Position 0.25 is 2.5 V.
    # The 1 Tohm on the wiper does not move it. Current enters pin 1.
    half = _pot(0.5)
    quarter = _pot(0.25)

    assert half.voltage_at(point(5, 4)) == pytest.approx(5.0)
    assert half.current_through("RV1") == pytest.approx(0.001)
    assert "RV1.b" not in half.currents
    assert quarter.voltage_at(point(5, 4)) == pytest.approx(2.5)


def _pot(position):
    return solve(
        [
            Component("ground", "GND1", "", 8, 2),
            Component("dc_source", "V1", "10", 4, 2),
            Component(
                "potentiometer", "RV1", "10k", 4, 3, 0,
                {"position": str(position)},
            ),
            Component("resistor", "R1", "1t", 5, 4),
        ],
        wires=[
            ((5, 2), (8, 2)),
            ((4, 2), (4, 3)),
            ((4, 5), (8, 5)),
            ((8, 2), (8, 5)),
            ((5, 5), (8, 5)),
        ],
    )


def test_a_transformer_steps_12_volts_up_to_24():
    # n = 2. Secondary 24 V into 1k is 24 mA out of s1.
    # Primary current into the dot is 48 mA. 12*48 mA = 24*24 mA.
    result = solve(
        [
            Component("ground", "GND1", "", 5, 2),
            Component("dc_source", "V1", "12", 4, 2),
            Component("transformer", "T1", "2", 4, 2),
            Component("resistor", "R1", "1k", 4, 3),
        ],
        wires=[((5, 2), (5, 3)), ((4, 4), (5, 4)), ((5, 3), (5, 4))],
    )

    assert result.voltage_at(point(4, 3)) == pytest.approx(24.0)
    assert result.current_through("R1") == pytest.approx(0.024)
    assert result.current_through("T1") == pytest.approx(0.024)
    assert result.current_through("V1") == pytest.approx(0.048)


def test_a_regulator_holds_5_volts():
    # 5 V into 1k is 5 mA out of the output pin.
    result = solve(
        [
            Component("ground", "GND1", "", 5, 4),
            Component("dc_source", "V1", "12", 4, 2),
            Component("voltage_regulator", "U1", "5", 4, 4),
            Component("resistor", "R1", "1k", 4, 5),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (5, 4)),
            ((4, 6), (5, 6)),
            ((5, 4), (5, 6)),
        ],
    )

    assert result.voltage_at(point(4, 5)) == pytest.approx(5.0)
    assert result.current_through("U1") == pytest.approx(0.005)
    assert result.current_through("R1") == pytest.approx(0.005)


def test_a_555_divider_sits_at_two_thirds_of_vcc():
    # Three 5k resistors. Unloaded CONT is 8 V from a 12 V supply.
    # 12/15k = 0.8 mA. A 1 meg from CONT to ground makes
    # 2400/301 = 7.973... V.
    plain = _timer(None)

    assert plain.voltage_at(point(6, 5)) == pytest.approx(8.0)
    assert plain.current_through("X1") == pytest.approx(0.0008)

    loaded = _timer("1meg")

    assert loaded.voltage_at(point(6, 5)) == pytest.approx(2400.0 / 301.0)


def _timer(load):
    parts = [
        Component("ground", "GND1", "", 2, 3),
        Component("dc_source", "V1", "12", 2, 4),
        Component("timer_555", "X1", "NE555", 4, 4),
    ]
    wires = [((2, 4), (2, 5)), ((3, 4), (3, 3)), ((3, 3), (2, 3))]

    if load is not None:
        parts.append(Component("resistor", "R1", load, 6, 5))
        wires.extend([
            ((6, 6), (8, 6)),
            ((8, 6), (8, 3)),
            ((8, 3), (2, 3)),
        ])

    return solve(parts, wires=wires)


def test_a_2n3904_early_effect_sets_the_collector():
    # 10 uA into the base, Bf 300, so the transport current is 3 mA.
    # Ic = 3 mA * (1 + Vc/100) and Vc = 5 - Ic*1k, so Vc = 2/1.03.
    # The 1k joins the collector. A resistor's second pin is one
    # column to the right.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component("dc_source", "V1", "5", 2, 2),
            Component("resistor", "R1", "1k", 2, 3),
            Component("npn", "Q1", "2N3904", 4, 4),
            Component("current_source", "I1", "10u", 4, 3),
        ],
        wires=[
            ((2, 2), (2, 3)),
            ((2, 4), (3, 4)),
            ((3, 2), (6, 2)),
            ((6, 2), (6, 4)),
            ((5, 4), (6, 4)),
            ((5, 3), (6, 3)),
        ],
    )
    collector = 2.0 / 1.03

    assert result.voltage_at(point(3, 4)) == pytest.approx(collector, rel=1e-3)
    assert result.current_through("Q1") == pytest.approx(
        (5.0 - collector) / 1000.0, rel=1e-3
    )


def test_a_2n7000_in_saturation_matches_the_square_law():
    # Vgs starts at 3 V, Vto 2.1, Kp 0.17, Lambda 0.02, Rd = Rs = 1.
    # Drain resistor 100 ohm from 10 V. Binary search on the
    # saturation equation, including the two 1 ohm pins.
    expected = _nmos_saturation_current()
    result = solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component("dc_source", "V1", "10", 2, 2),
            Component("resistor", "R1", "100", 2, 3),
            Component("dc_source", "V2", "3", 4, 2),
            Component("nmos", "M1", "2N7000", 4, 4),
        ],
        wires=[
            ((2, 2), (2, 3)),
            ((2, 4), (3, 4)),
            ((3, 2), (3, 1)),
            ((3, 1), (6, 1)),
            ((6, 1), (6, 4)),
            ((5, 4), (6, 4)),
            ((4, 2), (4, 3)),
            ((5, 2), (5, 4)),
        ],
    )

    assert 0.04 < expected < 0.09
    assert result.current_through("M1") == pytest.approx(expected, rel=1e-3)
    assert result.current_through("R1") == pytest.approx(expected, rel=1e-3)


def _nmos_saturation_current():
    low = 0.0
    high = 0.1

    for _step in range(60):
        current = 0.5 * (low + high)
        source = current * 1.0
        drain = 10.0 - current * 100.0 - current * 1.0
        vgs = 3.0 - source
        vds = drain - source
        overdrive = vgs - 2.1
        guess = 0.5 * 0.17 * overdrive * overdrive * (1.0 + 0.02 * vds)

        if guess > current:
            low = current
        else:
            high = current

    return 0.5 * (low + high)


def test_a_2n3819_at_zero_vgs_is_its_idss():
    # Beta 1.3 mS, Vto -3, so Idss = 1.3e-3 * 9 = 11.7 mA.
    # Id = Idss * (1 + 0.0025 * Vds), Vds = 12 - Id*100.
    beta = 1.3e-3
    channel = 2.5e-3
    idss = beta * 9.0
    expected = idss * (1.0 + channel * 12.0) / (1.0 + idss * channel * 100.0)
    result = solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component("dc_source", "V1", "12", 2, 2),
            Component("resistor", "R1", "100", 2, 3),
            Component("njfet", "J1", "2N3819", 4, 4),
        ],
        wires=[
            ((2, 2), (2, 3)),
            ((2, 4), (3, 4)),
            ((3, 2), (6, 2)),
            ((6, 2), (6, 4)),
            ((5, 4), (6, 4)),
            ((4, 3), (6, 3)),
        ],
    )

    assert expected == pytest.approx(0.012016, abs=1e-6)
    assert result.voltage_at(point(3, 4)) == pytest.approx(
        12.0 - expected * 100.0, rel=1e-3
    )
    assert result.current_through("J1") == pytest.approx(expected, rel=1e-3)


def test_a_2n3906_early_effect_sets_the_collector():
    # 10 uA out of the base, Bf 180, so the transport current is 1.8 mA.
    # Ic = 1.8 mA * (1 + (5 - Vc)/20) and Vc = Ic * 1k, so Vc = 2.25/1.09.
    # Positive current enters the collector, so this reading is negative.
    collector = 2.25 / 1.09
    result = solve(
        [
            Component("ground", "GND1", "", 6, 6),
            Component("dc_source", "V1", "5", 3, 6),
            Component("pnp", "Q1", "2N3906", 4, 4),
            Component("resistor", "R1", "1k", 5, 4),
            Component("current_source", "I1", "10u", 3, 3),
        ],
        wires=[
            ((3, 4), (3, 6)),
            ((4, 6), (6, 6)),
            ((5, 5), (6, 5)),
            ((3, 3), (3, 1)),
            ((3, 1), (6, 1)),
            ((6, 1), (6, 6)),
        ],
    )

    assert result.voltage_at(point(5, 4)) == pytest.approx(collector, rel=1e-3)
    assert result.current_through("Q1") == pytest.approx(
        -collector / 1000.0, rel=1e-3
    )
    assert result.current_through("R1") == pytest.approx(
        collector / 1000.0, rel=1e-3
    )


def test_a_bs250_in_saturation_matches_the_square_law():
    # Source 10 V, gate 7 V, Vto -2.5, Kp 0.05, Lambda 0.02, Rd = Rs = 1.
    # Drain resistor 100 ohm to ground. Current leaves the drain.
    expected = _pmos_saturation_current()
    result = solve(
        [
            Component("ground", "GND1", "", 8, 4),
            Component("dc_source", "V1", "10", 3, 1),
            Component("dc_source", "V2", "7", 4, 5),
            Component("resistor", "R1", "100", 5, 4, 90),
            Component("pmos", "M1", "BS250", 4, 4),
        ],
        wires=[
            ((3, 1), (3, 4)),
            ((4, 1), (8, 1)),
            ((8, 1), (8, 4)),
            ((4, 3), (4, 5)),
            ((5, 5), (8, 5)),
            ((8, 4), (8, 5)),
            ((6, 4), (8, 4)),
        ],
    )

    assert 0.005 < expected < 0.02
    assert result.current_through("M1") == pytest.approx(-expected, rel=1e-3)
    assert result.current_through("R1") == pytest.approx(expected, rel=1e-3)


def _pmos_saturation_current():
    low = 0.0
    high = 0.05

    for _step in range(60):
        current = 0.5 * (low + high)
        source = 10.0 - current * 1.0
        drain = current * 100.0 + current * 1.0
        overdrive = (source - 7.0) - 2.5
        vsd = source - drain
        guess = 0.5 * 0.05 * overdrive * overdrive * (1.0 + 0.02 * vsd)

        if guess > current:
            low = current
        else:
            high = current

    return 0.5 * (low + high)


def test_a_2n5460_at_zero_vgs_is_its_idss():
    # Beta 1.5 mS, Vto -2, so Idss = 1.5e-3 * 4 = 6 mA.
    # Id = Idss * (1 + 0.005 * Vsd), Vsd = 12 - Id*100.
    # Current leaves the drain, so the reading is negative.
    beta = 1.5e-3
    channel = 5e-3
    idss = beta * 4.0
    expected = idss * (1.0 + channel * 12.0) / (1.0 + idss * channel * 100.0)
    result = solve(
        [
            Component("ground", "GND1", "", 8, 4),
            Component("dc_source", "V1", "12", 3, 1),
            Component("resistor", "R1", "100", 5, 4, 90),
            Component("pjfet", "J1", "2N5460", 4, 4),
        ],
        wires=[
            ((3, 1), (3, 4)),
            ((4, 1), (8, 1)),
            ((8, 1), (8, 4)),
            ((4, 3), (4, 2)),
            ((4, 2), (3, 2)),
            ((6, 4), (8, 4)),
        ],
    )

    assert expected == pytest.approx(0.006341, abs=1e-6)
    assert result.voltage_at(point(5, 4)) == pytest.approx(
        expected * 100.0, rel=1e-3
    )
    assert result.current_through("J1") == pytest.approx(-expected, rel=1e-3)


def test_a_follower_copies_1_volt():
    result = solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component("dc_source", "V1", "1", 4, 2),
            Component("dc_source", "V2", "12", 3, 1),
            Component("follower", "A1", "", 4, 4),
            Component("resistor", "R1", "1k", 4, 5),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (6, 2)),
            ((3, 1), (3, 4)),
            ((4, 1), (6, 1)),
            ((6, 1), (6, 4)),
            ((5, 4), (6, 4)),
            ((4, 6), (6, 6)),
            ((6, 4), (6, 6)),
        ],
    )

    assert result.voltage_at(point(4, 5)) == pytest.approx(1.0, abs=1e-3)
    assert result.current_through("A1") == pytest.approx(0.001, rel=1e-2)
    assert result.current_through("R1") == pytest.approx(0.001, rel=1e-2)


def test_a_limited_lm358_clamps_1_5_volts_below_the_rail():
    # Open loop, input 1 V, V+ 12 V, V- 0. The clamp holds the
    # unloaded pin at 10.5 V. Rout is 50 into 1k, so the output is
    # 10.5 * 1000/1050 = 10 V and the current is 10 mA.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component(
                "opamp_lm358", "X1", "LM358", 4, 4, 0, {"limits": "limited"}
            ),
            Component("dc_source", "V1", "12", 3, 4),
            Component("dc_source", "V2", "1", 5, 2),
            Component("resistor", "R1", "1k", 4, 5),
        ],
        wires=[
            ((4, 4), (6, 4)),
            ((3, 3), (3, 1)),
            ((3, 1), (6, 1)),
            ((6, 1), (6, 4)),
            ((5, 2), (5, 3)),
            ((4, 6), (6, 6)),
            ((6, 4), (6, 6)),
        ],
    )

    assert result.voltage_at(point(4, 5)) == pytest.approx(10.0, abs=1e-4)
    assert result.current_through("X1") == pytest.approx(0.01, rel=1e-3)


def test_an_inverting_amplifier_of_gain_10_makes_minus_10():
    result = solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component("dc_source", "V1", "1", 4, 2),
            Component("dc_source", "V2", "15", 3, 4),
            Component("inverting_amp", "A1", "10", 4, 4),
            Component("resistor", "R1", "1k", 4, 5),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (6, 2)),
            ((6, 2), (6, 4)),
            ((4, 4), (6, 4)),
            ((4, 6), (6, 6)),
            ((6, 6), (6, 4)),
        ],
    )

    assert result.voltage_at(point(4, 5)) == pytest.approx(-10.0, abs=0.05)


def test_a_noninverting_amplifier_of_gain_2_makes_2_volts():
    result = solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component("dc_source", "V1", "1", 4, 2),
            Component("dc_source", "V2", "12", 3, 4),
            Component("noninverting_amp", "A1", "2", 4, 4),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (6, 2)),
            ((6, 2), (6, 4)),
            ((4, 4), (6, 4)),
        ],
    )

    assert result.voltage_at(point(4, 5)) == pytest.approx(2.0, abs=0.01)


def test_an_and_gate_is_high_and_a_nand_gate_is_low():
    # Both inputs at 12 V. AND output is 12 V. NAND output is 0 V.
    assert _gate("gate_and").voltage_at(point(4, 5)) == pytest.approx(12.0)
    assert _gate("gate_nand").voltage_at(point(4, 5)) == pytest.approx(0.0)


def test_a_not_gate_with_a_low_input_is_high():
    result = solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component("dc_source", "V1", "12", 3, 4),
            Component("gate_not", "X1", "NOT", 4, 4),
            Component("resistor", "R1", "1k", 4, 5),
        ],
        wires=[
            ((4, 4), (6, 4)),
            ((4, 3), (6, 3)),
            ((6, 3), (6, 4)),
            ((4, 6), (6, 6)),
            ((6, 4), (6, 6)),
        ],
    )

    assert result.voltage_at(point(4, 5)) == pytest.approx(12.0)


def test_a_comparator_goes_to_the_positive_rail():
    result = solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component("dc_source", "V1", "12", 3, 4),
            Component("dc_source", "V2", "2", 5, 2),
            Component("dc_source", "V3", "1", 3, 2),
            Component("comparator", "X1", "COMP", 4, 4),
            Component("resistor", "R1", "1k", 4, 5),
        ],
        wires=[
            ((4, 4), (6, 4)),
            ((5, 2), (5, 3)),
            ((3, 2), (3, 3)),
            ((4, 2), (4, 1)),
            ((4, 1), (6, 1)),
            ((6, 1), (6, 4)),
            ((4, 6), (6, 6)),
            ((6, 4), (6, 6)),
        ],
    )

    assert result.voltage_at(point(4, 5)) == pytest.approx(12.0)


def _gate(kind):
    return solve(
        [
            Component("ground", "GND1", "", 6, 4),
            Component("dc_source", "V1", "12", 3, 4),
            Component(
                kind, "X1",
                COMPONENT_DEFINITIONS[kind]["default_value_text"], 4, 4,
            ),
            Component("resistor", "R1", "1k", 4, 5),
        ],
        wires=[
            ((4, 4), (6, 4)),
            ((3, 3), (3, 4)),
            ((5, 3), (5, 1)),
            ((5, 1), (3, 1)),
            ((3, 1), (3, 4)),
            ((4, 6), (6, 6)),
            ((6, 4), (6, 6)),
        ],
    )
