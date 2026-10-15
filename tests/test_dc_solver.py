"""
DC operating point without ngspice.

Hand calculation for the divider: 10 V across 10k + 10k is 5 V in the
middle, and 10 V / 20k = 0.5 mA. The source current leaves the positive
pin, so it is +0.5 mA. A 1 mA source into 1k is 1 V. An inductor is a
short, so the node after it is the source voltage. A capacitor is an
open, so a node that hangs on one is floating.
"""

import pytest

from core.components import Component
from core.connection_grid import ConnectionGrid
from core.exceptions import SimulationError
from core.wires import WireCollection
from sim.dc_solver import solve_dc


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def solve(parts, wires=(), labels=()):
    grid = ConnectionGrid(8, 8)
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


def test_a_diode_is_not_covered_yet():
    with pytest.raises(SimulationError) as caught:
        solve([
            Component("ground", "GND1", "", 6, 2),
            Component("diode", "D1", "1N4148", 4, 2),
        ])

    assert "does not cover a diode yet" in str(caught.value)
