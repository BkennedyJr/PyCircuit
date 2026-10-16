"""
AC phasors at one frequency, without ngspice.

Hand calculation: 1 V peak across 1k is 1 mA at 0 degrees. A 1k
resistor and a 159 nF capacitor is a low-pass. At 1 kHz,
2*pi*f*R*C is 0.999, so

    1 / (1 + j*0.999) = 0.707 at -45 degrees.

A DC voltage source is a short at AC, so that 10 V source drops
nothing. An inductor of 1 mH at 1 kHz has reactance 2*pi ohms.
"""

import math

import pytest

from core.components import Component
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError, SimulationError
from core.wires import WireCollection
from sim.ac_solver import solve_ac


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def solve(parts, frequency_hz=1000.0, wires=()):
    grid = ConnectionGrid(8, 8)
    collection = WireCollection()

    for start, end in wires:
        collection.add_wire(point(*start), point(*end), grid)

    return solve_ac(parts, collection, grid, frequency_hz)


def test_one_volt_across_1k_is_one_milliamp_at_zero_degrees():
    # 1 V / 1k = 1 mA. Phase 0, so the phasor is real.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("ac_source", "V1", "1", 4, 2),
            Component("resistor", "R1", "1k", 4, 3),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (6, 2)),
            ((4, 4), (6, 4)),
            ((6, 2), (6, 4)),
        ],
    )

    assert result.voltage_at(point(4, 3)) == pytest.approx(1 + 0j)
    assert result.voltage_at(point(6, 2)) == pytest.approx(0j)
    assert result.current_through("R1") == pytest.approx(0.001 + 0j)
    assert result.current_through("V1") == pytest.approx(0.001 + 0j)


def test_a_90_degree_phase_is_an_imaginary_phasor():
    # Peak 1 V at 90 degrees is j*1 V. Current is j*1 mA.
    result = solve([
        Component(
            "ac_source", "V1", "1", 2, 2, 0, {"phase": "90"}
        ),
        Component("resistor", "R1", "1k", 2, 2, 90),
        Component("ground", "GND1", "", 3, 2),
    ])

    assert result.voltage_at(point(2, 2)) == pytest.approx(1j)
    assert result.current_through("R1") == pytest.approx(0.001j)


def test_the_offset_is_not_part_of_the_ac_voltage():
    # Offset is the DC part. The AC peak stays 1 V.
    result = solve([
        Component(
            "ac_source", "V1", "1", 2, 2, 0, {"offset": "5"}
        ),
        Component("resistor", "R1", "1k", 2, 2, 90),
        Component("ground", "GND1", "", 3, 2),
    ])

    assert result.voltage_at(point(2, 2)) == pytest.approx(1 + 0j)


def test_lowpass_is_0_707_volts_at_minus_45_degrees():
    # 1 / (1 + j*2*pi*1e3*1e3*159e-9)
    gain = 1.0 / complex(1.0, 2.0 * math.pi * 1e3 * 1e3 * 159e-9)
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component(
                "ac_source", "V1", "1", 4, 2, 0, {"frequency": "1k"}
            ),
            Component("resistor", "R1", "1k", 4, 3),
            Component("capacitor", "C1", "159n", 4, 4),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (6, 2)),
            ((4, 5), (6, 5)),
            ((6, 2), (6, 5)),
        ],
    )
    output = result.voltage_at(point(4, 4))

    assert abs(output) == pytest.approx(0.707, abs=0.001)
    assert math.degrees(cmath_phase(output)) == pytest.approx(-45.0, abs=0.2)
    assert output == pytest.approx(gain)
    assert result.current_through("R1") == pytest.approx((1 - gain) / 1000)
    assert result.current_through("C1") == pytest.approx(
        gain * 1j * 2.0 * math.pi * 1e3 * 159e-9
    )


def test_a_dc_source_is_a_short_at_ac():
    # 10 V DC is 0 V at 1 kHz, so the resistor current is 0.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("dc_source", "V1", "10", 4, 2),
            Component("resistor", "R1", "1k", 4, 3),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (6, 2)),
            ((4, 4), (6, 4)),
            ((6, 2), (6, 4)),
        ],
    )

    assert result.voltage_at(point(4, 2)) == pytest.approx(0j)
    assert result.current_through("R1") == pytest.approx(0j)
    assert result.current_through("V1") == pytest.approx(0j)


def test_an_inductor_at_1_khz_has_reactance_2_pi():
    # 1 mH at 1 kHz: X = 2*pi ohms. I = 1 / (j*2*pi).
    expected = 1.0 / (1j * 2.0 * math.pi)
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("ac_source", "V1", "1", 4, 2),
            Component("inductor", "L1", "1m", 4, 3),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (6, 2)),
            ((4, 4), (6, 4)),
            ((6, 2), (6, 4)),
        ],
    )

    assert result.voltage_at(point(4, 3)) == pytest.approx(1 + 0j)
    assert result.current_through("L1") == pytest.approx(expected)
    assert result.current_through("V1") == pytest.approx(expected)


def test_a_dc_current_source_is_open_at_ac():
    # 5 mA DC would pull the far end of the 1k down to -4 V. At AC
    # that source is an open, so the far end stays at 1 V.
    result = solve(
        [
            Component("ground", "GND1", "", 6, 2),
            Component("ac_source", "V1", "1", 4, 2),
            Component("resistor", "R1", "1k", 4, 3),
            Component("current_source", "I1", "5m", 4, 4),
        ],
        wires=[
            ((4, 2), (4, 3)),
            ((5, 2), (6, 2)),
            ((5, 4), (6, 4)),
            ((6, 2), (6, 4)),
        ],
    )

    assert result.voltage_at(point(4, 4)) == pytest.approx(1 + 0j)
    assert result.current_through("R1") == pytest.approx(0j)
    assert result.current_through("I1") == pytest.approx(0j)


def test_a_missing_ground_is_refused():
    with pytest.raises(SimulationError, match="Add a ground"):
        solve([Component("ac_source", "V1", "1", 2, 2)])


def test_a_diode_is_not_covered():
    with pytest.raises(SimulationError, match="does not cover a diode"):
        solve([
            Component("ground", "GND1", "", 3, 2),
            Component("diode", "D1", "1N4148", 2, 2),
        ])


def test_frequency_must_be_a_number_of_hertz_above_zero():
    parts = [Component("ground", "GND1", "", 2, 2)]

    with pytest.raises(ComponentError, match="greater than 0"):
        solve(parts, frequency_hz=0)

    with pytest.raises(ComponentError, match="not a number of hertz"):
        solve(parts, frequency_hz="1k")


def test_a_floating_node_has_no_ac_solution():
    # The current source is an open, so its top node goes nowhere.
    with pytest.raises(SimulationError, match="no single AC solution"):
        solve([
            Component("ground", "GND1", "", 3, 2),
            Component("current_source", "I1", "1m", 2, 2),
        ])


def cmath_phase(value):
    return math.atan2(value.imag, value.real)
