"""
DC operating point. The numbers are the hand calculation.

A 10 V source across two 10k resistors splits to 5 V in the middle.
The current is 10 V / 20k = 0.5 mA. ngspice's voltage-source current
is into the positive pin, so the source current is -0.5 mA.

A 1 mA source into 1k to ground is 1 V.
"""

import pytest

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import SimulationError
from core.netlist import build_netlist
from core.wires import WireCollection
from sim import runner
from sim.runner import run_op, run_operating_point

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def place(parts, grid, kind, row, column, value=""):
    return parts.add_component(kind, row, column, value, grid)


def connect(wires, grid, start, end):
    wires.add_wire(point(*start), point(*end), grid)


def new_circuit():
    return ConnectionGrid(8, 8), ComponentCollection(), WireCollection()


def build_divider(grid, parts, wires):
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "10")
    place(parts, grid, "resistor", 4, 3, "10k")
    place(parts, grid, "resistor", 4, 4, "10k")
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))


def test_a_10k_divider_from_10_v_is_5_v_and_half_a_milliamp():
    # 10 V / 20k = 0.5 mA. The source current is into the positive pin.
    grid, parts, wires = new_circuit()
    build_divider(grid, parts, wires)

    result = run_operating_point(parts, wires, grid)

    assert result.voltages["N001"] == pytest.approx(10)
    assert result.voltages["N002"] == pytest.approx(5)
    assert result.voltages["0"] == pytest.approx(0)
    assert result.currents["R1"] == pytest.approx(0.0005)
    assert result.currents["R2"] == pytest.approx(0.0005)
    assert result.currents["V1"] == pytest.approx(-0.0005)


@needs_ngspice
def test_ngspice_agrees_on_the_divider():
    grid, parts, wires = new_circuit()
    build_divider(grid, parts, wires)

    result = run_op(build_netlist(parts, wires, grid))

    assert result.voltages["N002"] == pytest.approx(5)
    assert result.currents["V1"] == pytest.approx(-0.0005)


def test_a_named_node_keeps_its_spelling():
    grid, parts, wires = new_circuit()
    build_divider(grid, parts, wires)
    grid.set_net_label(point(4, 2), "Vcc")

    result = run_operating_point(parts, wires, grid)

    assert result.voltages["Vcc"] == pytest.approx(10)
    assert "vcc" not in result.voltages
    assert "n001" not in result.voltages


def test_one_milliamp_into_1k_is_one_volt():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 5, 2)
    place(parts, grid, "current_source", 3, 2, "1m")
    place(parts, grid, "resistor", 3, 3, "1k")
    connect(wires, grid, (3, 2), (3, 3))
    connect(wires, grid, (3, 4), (4, 4))
    connect(wires, grid, (4, 4), (4, 2))
    connect(wires, grid, (4, 2), (5, 2))

    result = run_operating_point(parts, wires, grid)
    netlist = build_netlist(parts, wires, grid)

    assert "DC 1m" in netlist
    assert result.voltages["N001"] == pytest.approx(1)
    assert result.currents["R1"] == pytest.approx(0.001)
    assert result.currents["I1"] == pytest.approx(0.001)


def test_voltage_sources_in_a_loop_say_so():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 4, 2)
    place(parts, grid, "dc_source", 2, 2, "5")
    place(parts, grid, "dc_source", 2, 4, "10")
    connect(wires, grid, (2, 2), (2, 4))
    connect(wires, grid, (3, 2), (3, 4))
    connect(wires, grid, (3, 2), (4, 2))

    with pytest.raises(SimulationError, match="voltage sources form a loop"):
        run_operating_point(parts, wires, grid)


def test_a_missing_ground_says_to_add_one():
    with pytest.raises(SimulationError, match="Add a ground part."):
        run_op(
            "* no ground\n"
            "V1 N001 N002 DC 5\n"
            "R1 N001 N002 1k\n"
            ".end\n"
        )


def test_a_floating_node_says_each_node_needs_two_connections():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "10")
    place(parts, grid, "resistor", 4, 4, "10k")
    connect(wires, grid, (5, 2), (6, 2))

    with pytest.raises(SimulationError, match="only one connection"):
        run_operating_point(parts, wires, grid)


def test_a_diode_without_ngspice_says_what_is_covered(monkeypatch):
    monkeypatch.setattr(runner, "ngspice_is_installed", lambda: False)
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 5)
    place(parts, grid, "dc_source", 4, 1, "5")
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "diode", 4, 4, "1N4148")
    connect(wires, grid, (4, 1), (4, 3))
    connect(wires, grid, (5, 1), (6, 1))
    connect(wires, grid, (6, 1), (6, 5))
    connect(wires, grid, (4, 5), (6, 5))

    with pytest.raises(SimulationError, match="does not cover a diode"):
        run_operating_point(parts, wires, grid)


def test_a_diode_still_uses_ngspice_when_it_is_installed(monkeypatch):
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 5)
    place(parts, grid, "dc_source", 4, 1, "5")
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "diode", 4, 4, "1N4148")
    connect(wires, grid, (4, 1), (4, 3))
    connect(wires, grid, (5, 1), (6, 1))
    connect(wires, grid, (6, 1), (6, 5))
    connect(wires, grid, (4, 5), (6, 5))
    seen = {}

    def fake_run(netlist):
        seen["netlist"] = netlist
        return runner.OperatingPoint(
            {"N001": 5.0, "N002": 0.7, "0": 0.0},
            {"R1": 0.0043, "D1": 0.0043, "V1": -0.0043},
        )

    monkeypatch.setattr(runner, "ngspice_is_installed", lambda: True)
    monkeypatch.setattr(runner, "run_op", fake_run)

    result = run_operating_point(parts, wires, grid)

    assert "D1" in seen["netlist"]
    assert result.voltages["N002"] == pytest.approx(0.7)


def test_an_ac_source_uses_its_offset():
    # Offset 2 V across 1k is 2 mA. The 5 V peak is not the DC voltage.
    # The source current is into the positive pin, so it is -2 mA.
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    parts.add_component(
        "ac_source", 4, 2, "5", grid, parameter_texts={"offset": "2"}
    )
    place(parts, grid, "resistor", 4, 3, "1k")
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 4), (6, 4))
    connect(wires, grid, (6, 2), (6, 4))

    result = run_operating_point(parts, wires, grid)

    assert result.voltages["N001"] == pytest.approx(2)
    assert result.currents["R1"] == pytest.approx(0.002)
    assert result.currents["V1"] == pytest.approx(-0.002)


def test_missing_ngspice_names_the_readme(monkeypatch):
    monkeypatch.setattr(runner, "_library_path", lambda: None)
    monkeypatch.setattr(runner, "_SHARED", None)

    with pytest.raises(SimulationError) as caught:
        run_op("* probe\nV1 N001 0 DC 1\nR1 N001 0 1k\n.end\n")

    assert str(caught.value) == runner.NGSPICE_MISSING
    assert "Installing ngspice" in str(caught.value)
