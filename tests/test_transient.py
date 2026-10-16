"""
Transient run. The numbers are the hand calculation.

A 10 V step into 1k and 1u starts from 0 V (the capacitor is empty).
At 1 ms, one time constant, the capacitor is 10 * (1 - exp(-1)) = 6.321 V.

A unity-gain buffer copies its input. A 1 V peak, 1 kHz sine comes back
on the output within 1 percent.
"""

import math
import threading

import pytest

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import SimulationError
from core.netlist import append_shunt_loads, build_netlist, spice_node_map
from core.probes import ProbeCollection, shunt_loads
from core.wires import WireCollection
from sim import runner
from sim.runner import (
    _run_until_finished,
    default_transient_stop,
    lit_led_references,
    plotted_columns,
    probe_series,
    run_tran,
    sample_at,
    transient_step,
)

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)

# 10 * (1 - e^-1)
RC_STEP_AT_1MS = 10.0 * (1.0 - math.exp(-1.0))


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def place(parts, grid, kind, row, column, value="", parameter_texts=None):
    return parts.add_component(
        kind, row, column, value, grid, parameter_texts=parameter_texts
    )


def connect(wires, grid, start, end):
    wires.add_wire(point(*start), point(*end), grid)


def new_circuit():
    return ConnectionGrid(8, 8), ComponentCollection(), WireCollection()


def build_rc_step(grid, parts, wires):
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "10")
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "capacitor", 4, 4, "1u")
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))


def build_buffer(grid, parts, wires):
    place(parts, grid, "ground", 8, 2)
    place(parts, grid, "opamp_generic", 4, 4, "OPAMP")
    place(
        parts, grid, "ac_source", 5, 2, "1",
        parameter_texts={"frequency": "1k"},
    )
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


def test_the_default_run_is_five_periods_or_10_ms():
    grid, parts, wires = new_circuit()
    build_rc_step(grid, parts, wires)

    assert default_transient_stop(parts.get_components()) == pytest.approx(0.01)
    assert transient_step(0.01) == pytest.approx(5e-5)

    grid, parts, wires = new_circuit()
    build_buffer(grid, parts, wires)

    assert default_transient_stop(parts.get_components()) == pytest.approx(0.005)


def test_a_bad_run_time_is_refused():
    with pytest.raises(SimulationError, match="positive numbers"):
        run_tran("* just text\nR1 1 0 1k\n.end\n", 0, 1e-3)

    with pytest.raises(SimulationError, match="positive numbers"):
        run_tran("* just text\nR1 1 0 1k\n.end\n", 1e-3, 1e-3)


def test_probe_loads_are_added_before_end():
    grid, parts, wires = new_circuit()
    build_rc_step(grid, parts, wires)
    probes = ProbeCollection()
    probes.add_voltage(point(4, 4), grid)
    probes.set_method("P1", "scope_10x", parts.get_components())
    name_by_point, _draw_at = spice_node_map(parts, wires, grid)

    text = append_shunt_loads(
        build_netlist(parts, wires, grid),
        shunt_loads(probes.get_probes()),
        name_by_point,
    )

    assert "Rprobe1 N002 0 10meg" in text
    assert "Cprobe1 N002 0 10p" in text
    assert text.strip().endswith(".end")


@needs_ngspice
def test_an_rc_step_is_6_321_v_at_1_ms():
    grid, parts, wires = new_circuit()
    build_rc_step(grid, parts, wires)
    netlist = build_netlist(parts, wires, grid)
    name_by_point, _draw_at = spice_node_map(parts, wires, grid)
    node = name_by_point[point(4, 4)]

    result = run_tran(netlist, 10e-6, 5e-3, use_initial_conditions=True)
    volts = sample_at(result.time, result.voltages[node], 1e-3)

    assert volts == pytest.approx(RC_STEP_AT_1MS, abs=0.01)
    assert result.voltages["0"][0] == 0.0


@needs_ngspice
def test_a_unity_gain_buffer_copies_a_1_v_sine():
    grid, parts, wires = new_circuit()
    build_buffer(grid, parts, wires)
    netlist = build_netlist(parts, wires, grid)
    name_by_point, _draw_at = spice_node_map(parts, wires, grid)
    probes = ProbeCollection()
    probes.add_voltage(point(5, 3), grid)
    probes.add_voltage(point(4, 5), grid)
    stop = default_transient_stop(parts.get_components())

    result = run_tran(netlist, transient_step(stop), stop)
    input_series = probe_series(
        probes.get("P1"), result, name_by_point
    )
    output_series = probe_series(
        probes.get("P2"), result, name_by_point
    )

    assert input_series is not None
    assert output_series is not None
    input_peak = max(input_series[1])
    output_peak = max(output_series[1])
    assert input_peak == pytest.approx(1.0, rel=0.01)
    assert output_peak == pytest.approx(input_peak, rel=0.01)


def test_drawing_keeps_the_peak_and_the_trough():
    # Six samples, four drawn points, two buckets of three.
    # Bucket 0 is 0, 10, 0: keep 0 and 10. Bucket 1 is 0, -5, 0: keep 0 and -5.
    times = (0, 1, 2, 3, 4, 5)
    values = (0, 10, 0, 0, -5, 0)
    phase = (1, 2, 3, 4, 5, 6)

    drawn_time, drawn_values, drawn_phase = plotted_columns(
        times, values, phase, limit=4
    )

    assert list(drawn_time) == [0, 1, 3, 4]
    assert list(drawn_values) == [0, 10, 0, -5]
    assert list(drawn_phase) == [1, 2, 4, 5]


def test_a_short_trace_is_drawn_in_full():
    times = (0, 1, 2)
    values = (0, 10, 0)

    assert plotted_columns(times, values, limit=4) == (times, values)


def test_unequal_trace_columns_are_refused():
    with pytest.raises(SimulationError, match="not usable"):
        plotted_columns((0, 1), (0,))


class _Shared:
    """Stand-in for the ngspice library. No real run."""

    def __init__(self, finish_immediately=False):
        self.commands = []
        self._is_running = False
        self._background_started = False
        self._error_in_stdout = False
        self._error_in_stderr = False
        self.finish_immediately = finish_immediately
        self.halt_error = None

    def exec_command(self, command):
        self.commands.append(command)
        self._background_started = True
        self._is_running = not self.finish_immediately

    def halt(self):
        self.commands.append("bg_halt")

        if self.halt_error is not None:
            self._is_running = False
            raise self.halt_error

        self._is_running = False


def test_stop_halts_a_run_that_has_already_started():
    shared = _Shared()
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(SimulationError, match="Stopped"):
        _run_until_finished(shared, cancel)

    assert shared.commands == ["bg_run", "bg_halt"]


def test_a_finished_background_run_returns():
    shared = _Shared(finish_immediately=True)

    _run_until_finished(shared, None)

    assert shared.commands == ["bg_run"]


def test_a_halt_that_ngspice_rejects_still_stops():
    shared = _Shared()
    shared.halt_error = NameError("ngSpice_Command bg_halt returned 1")
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(SimulationError, match="Stopped"):
        _run_until_finished(shared, cancel)

    assert shared.commands == ["bg_run", "bg_halt"]


def test_a_run_that_ignores_halt_says_to_press_start(monkeypatch):
    clock = {"now": 0.0}

    def monotonic():
        clock["now"] += 1.0
        return clock["now"]

    monkeypatch.setattr("sim.runner.time.monotonic", monotonic)
    monkeypatch.setattr("sim.runner.time.sleep", lambda _seconds: None)
    shared = _Shared()

    def ignore_halt():
        shared.commands.append("bg_halt")

    shared.halt = ignore_halt
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(SimulationError, match="did not stop"):
        _run_until_finished(shared, cancel)

    assert shared.commands[0] == "bg_run"
    assert "bg_halt" in shared.commands


def test_a_run_that_fails_before_it_starts_returns():
    shared = _Shared()

    def fail(command):
        shared.commands.append(command)
        shared._error_in_stderr = True

    shared.exec_command = fail

    _run_until_finished(shared, None)

    assert shared.commands == ["bg_run"]


@needs_ngspice
def test_stopping_a_run_does_not_return_samples():
    grid, parts, wires = new_circuit()
    build_rc_step(grid, parts, wires)
    netlist = build_netlist(parts, wires, grid)
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(SimulationError, match="Stopped"):
        run_tran(netlist, 10e-6, 5e-3, cancel_event=cancel)


@needs_ngspice
def test_an_led_carrying_more_than_1_ma_is_lit():
    grid, parts, wires = new_circuit()
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "5")
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "led", 4, 4, "LED_RED")
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))

    result = run_tran(
        build_netlist(parts, wires, grid), 10e-6, 1e-3
    )

    assert max(abs(value) for value in result.currents["D1"]) > 0.001
    assert lit_led_references(parts.get_components(), result) == ["D1"]
