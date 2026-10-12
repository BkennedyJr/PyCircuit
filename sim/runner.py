"""
DC operating point, transient, and frequency sweep through the ngspice
shared library. The spectrum is the FFT of a transient waveform.

``run_op``, ``run_tran`` and ``run_ac`` take the netlist text from
``core.netlist.build_netlist``. Ground is node 0. ngspice hands node
names back in lowercase; they are mapped to the spelling in the netlist
(Vcc stays Vcc).

Current is in amps. For a resistor it is from the first pin toward the
second. For a voltage source it is into the positive pin, so a source
that is powering the circuit has a negative current.
"""

import ctypes.util
import logging
import math
import os
import re
import threading
from pathlib import Path

import numpy

from core.exceptions import SimulationError
from core.netlist import build_netlist
from core.units import format_spice_number

NGSPICE_MISSING = (
    "ngspice is not installed. See README: Installing ngspice."
)

_LOCK = threading.Lock()
_SHARED = None
_ELEMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEVICE_CURRENT = re.compile(r"^@([^[]+)\[(i|id|current)\]$")


class OperatingPoint:
    """
    DC voltages and currents for one circuit.

    :param voltages: Node name to volts. Includes ``"0"`` at 0 V.
    :type voltages: dict
    :param currents: Part reference to amps.
    :type currents: dict
    """

    def __init__(self, voltages, currents):
        self.voltages = voltages
        self.currents = currents


class Transient:
    """
    One transient run.

    :param time: Sample times, in seconds.
    :type time: tuple
    :param voltages: Node name to a tuple of volts, one per sample.
        Includes ``"0"`` at 0 V.
    :type voltages: dict
    :param currents: Part reference to a tuple of amps, one per sample.
    :type currents: dict
    """

    def __init__(self, time_seconds, voltages, currents):
        self.time = time_seconds
        self.voltages = voltages
        self.currents = currents


# Five periods of the slowest sine, otherwise 10 ms. Two hundred samples.
DEFAULT_TRANSIENT_STOP = 0.01
TRANSIENT_SAMPLES = 200
LED_LIT_AMPS = 0.001


def ngspice_is_installed():
    """
    True when PySpice can be imported and an ngspice library is on disk.

    :rtype: bool
    """
    try:
        import PySpice  # noqa: F401
    except ImportError:
        return False
    return _library_path() is not None


def run_operating_point(components, wire_collection, connection_grid=None):
    """
    Build the netlist and run its DC operating point.

    :param components: Placed parts, or a ComponentCollection.
    :param wire_collection: Wires of the same circuit.
    :param connection_grid: Grid whose net labels name nodes.
    :rtype: OperatingPoint
    :raises SimulationError: The same messages as build_netlist, or a
        circuit ngspice could not solve.
    """
    return run_op(build_netlist(components, wire_collection, connection_grid))


def run_op(netlist):
    """
    Run a DC operating point on one SPICE netlist.

    :param netlist: Text from build_netlist.
    :type netlist: str
    :rtype: OperatingPoint
    :raises SimulationError: ngspice is missing, the circuit has no
        ground, or the operating point did not solve.
    """
    if not isinstance(netlist, str) or not netlist.strip():
        raise SimulationError(
            "The netlist text is empty, so it was not run."
        )
    if not _has_ground(netlist):
        raise SimulationError("Add a ground part.")

    with _LOCK:
        return _run_op(netlist)


def default_transient_stop(components):
    """
    Return the run length for a circuit: five periods of its slowest
    sine, or 10 ms when there is no AC source.

    :param components: Placed parts.
    :rtype: float
    """
    lowest = None

    for component in components:
        if getattr(component, "kind", None) != "ac_source":
            continue

        frequency = component.parameter_values["frequency"]

        if frequency > 0 and (lowest is None or frequency < lowest):
            lowest = frequency

    if lowest is None:
        return DEFAULT_TRANSIENT_STOP

    return 5.0 / lowest


def transient_step(stop):
    """
    Return a step that gives ``TRANSIENT_SAMPLES`` points across ``stop``.

    :param stop: Run length in seconds.
    :type stop: float
    :rtype: float
    :raises SimulationError: If ``stop`` is not a positive finite number.
    """
    if not _positive_number(stop):
        raise SimulationError(
            "The run time must be a positive number, such as 10m."
        )

    return stop / TRANSIENT_SAMPLES


def run_tran(netlist, step, stop, use_initial_conditions=False,
             cancel_event=None):
    """
    Run a transient on one SPICE netlist.

    ``use_initial_conditions`` starts capacitors at 0 V instead of the
    DC operating point. That is how a DC source becomes a step.

    :param netlist: Text from build_netlist.
    :type netlist: str
    :param step: Maximum time step, in seconds.
    :type step: float
    :param stop: Run length, in seconds.
    :type stop: float
    :param use_initial_conditions: True to skip the operating point.
    :type use_initial_conditions: bool
    :param cancel_event: Set this to stop the run.
    :type cancel_event: threading.Event or None
    :rtype: Transient
    :raises SimulationError: ngspice is missing, the times are not
        usable, the run was stopped, or the circuit did not solve.
    """
    if not isinstance(netlist, str) or not netlist.strip():
        raise SimulationError(
            "The netlist text is empty, so it was not run."
        )

    if not _has_ground(netlist):
        raise SimulationError("Add a ground part.")

    if not _positive_number(step) or not _positive_number(stop) or step >= stop:
        raise SimulationError(
            "The time step and the run time must be positive numbers, "
            "and the step must be shorter than the run."
        )

    if not isinstance(use_initial_conditions, bool):
        raise SimulationError("The transient option must be true or false.")

    with _LOCK:
        return _run_tran(
            netlist, step, stop, use_initial_conditions, cancel_event
        )


def sample_at(time_seconds, values, when):
    """
    Return the linearly interpolated sample at ``when`` seconds.

    :param time_seconds: Sample times.
    :param values: Sample values, one per time.
    :param when: Time to read, in seconds.
    :rtype: float
    :raises SimulationError: If ``when`` is outside the run.
    """
    if len(time_seconds) != len(values) or not time_seconds:
        raise SimulationError("The transient samples are not usable.")

    if when < time_seconds[0] or when > time_seconds[-1]:
        raise SimulationError("That time is outside the transient run.")

    for index, instant in enumerate(time_seconds):
        if instant == when:
            return values[index]

        if instant > when:
            earlier = time_seconds[index - 1]
            span = instant - earlier

            if span == 0:
                return values[index - 1]

            fraction = (when - earlier) / span

            return (
                values[index - 1]
                + fraction * (values[index] - values[index - 1])
            )

    return values[-1]


def probe_series(probe, transient, name_by_point):
    """
    Return ``(time, values)`` for one probe, or None if this run has
    no sample for it.

    A differential probe is the first point minus the second. A current
    probe is the part current. Any other probe is the node voltage.

    :param probe: Probe to read.
    :param transient: Result from ``run_tran``.
    :param name_by_point: Grid point to SPICE node name.
    :rtype: tuple or None
    """
    if probe.method == "current":
        values = transient.currents.get(probe.component_reference)

        if values is None:
            return None

        return transient.time, values

    if probe.method == "differential":
        first = _voltage_for_point(
            transient, name_by_point, probe.identifier
        )
        second = _voltage_for_point(
            transient, name_by_point, probe.second_identifier
        )

        if first is None or second is None:
            return None

        return transient.time, tuple(
            left - right for left, right in zip(first, second)
        )

    values = _voltage_for_point(transient, name_by_point, probe.identifier)

    if values is None:
        return None

    return transient.time, values


def amplitude_spectrum(time_seconds, values):
    """
    Return ``(frequency, peak)`` for one real waveform.

    The record runs from the first sample to the last. The last instant
    is the end of the record, not an extra sample, because a repeating
    waveform meets itself there. The samples used for the FFT are spaced
    evenly across that record.

    Bin k is ``k / duration`` hertz. The height is the peak of that
    sine. A 1 V sine that fits a whole number of cycles is a 1 V line.
    The average is the line at 0 Hz. The Nyquist line is not doubled.

    :param time_seconds: Sample times, in seconds.
    :param values: Sample values, one per time.
    :rtype: tuple
    :raises SimulationError: If the samples are too few, unevenly
        paired, or do not move forward in time.
    """
    times, samples = _spectrum_samples(time_seconds, values)
    duration = times[-1] - times[0]
    count = len(times) - 1
    step = duration / count
    waveform = [
        sample_at(times, samples, times[0] + index * step)
        for index in range(count)
    ]
    coefficients = numpy.fft.rfft(waveform)
    frequencies = []
    peaks = []

    for bin_index, coefficient in enumerate(coefficients):
        frequencies.append(bin_index / duration)
        peak = abs(coefficient) / count

        if 0 < bin_index < count / 2.0:
            peak *= 2.0

        peaks.append(float(peak))

    return tuple(frequencies), tuple(peaks)


def probe_spectrum(probe, transient, name_by_point):
    """
    Return ``(frequency, peak)`` for one probe, or None if this run has
    no sample for it.

    The peak is volts for a voltage probe and amps for a current probe.

    :param probe: Probe to read.
    :param transient: Result from ``run_tran``.
    :param name_by_point: Grid point to SPICE node name.
    :rtype: tuple or None
    :raises SimulationError: If the samples cannot make a spectrum.
    """
    series = probe_series(probe, transient, name_by_point)

    if series is None:
        return None

    return amplitude_spectrum(series[0], series[1])


class FrequencySweep:
    """
    One AC sweep.

    :param frequency: Sample frequencies, in hertz.
    :type frequency: tuple
    :param voltages: Node name to a tuple of complex volts.
        Includes ``"0"`` at 0 V.
    :type voltages: dict
    :param currents: Part reference to a tuple of complex amps.
    :type currents: dict
    """

    def __init__(self, frequency, voltages, currents):
        self.frequency = frequency
        self.voltages = voltages
        self.currents = currents


def ac_source_peak(components):
    """
    Return the peak of the one AC source a sweep is measured against.

    Magnitude on the Bode plot is relative to this peak, so a 1 V
    source and a 2 V source draw the same gain.

    :param components: Placed parts.
    :rtype: float
    :raises SimulationError: If there is not exactly one AC source, or
        its peak is not above zero.
    """
    sources = [
        component for component in components
        if getattr(component, "kind", None) == "ac_source"
    ]

    if not sources:
        raise SimulationError(
            "Add an AC source before running a frequency sweep."
        )

    if len(sources) > 1:
        names = ", ".join(component.reference for component in sources)
        raise SimulationError(
            "A frequency sweep uses one AC source. "
            f"This circuit has {names}."
        )

    peak = sources[0].value

    if not _positive_number(peak):
        raise SimulationError(
            f"{sources[0].reference} needs a peak above zero for a "
            "frequency sweep."
        )

    return peak


def run_ac(netlist, start, stop, points_per_decade, cancel_event=None):
    """
    Run a decade frequency sweep on one SPICE netlist.

    :param netlist: Text from build_netlist.
    :type netlist: str
    :param start: First frequency, in hertz.
    :type start: float
    :param stop: Last frequency, in hertz.
    :type stop: float
    :param points_per_decade: Whole number of points in each decade.
    :type points_per_decade: int
    :param cancel_event: Set this to stop the run.
    :type cancel_event: threading.Event or None
    :rtype: FrequencySweep
    :raises SimulationError: ngspice is missing, the sweep settings are
        not usable, the run was stopped, or the circuit did not solve.
    """
    if not isinstance(netlist, str) or not netlist.strip():
        raise SimulationError(
            "The netlist text is empty, so it was not run."
        )

    if not _has_ground(netlist):
        raise SimulationError("Add a ground part.")

    if (not _positive_number(start) or not _positive_number(stop)
            or stop <= start):
        raise SimulationError(
            "The start and stop frequencies must be positive numbers, "
            "and the stop must be higher than the start."
        )

    if (isinstance(points_per_decade, bool)
            or not isinstance(points_per_decade, int)
            or not 1 <= points_per_decade <= 100):
        raise SimulationError(
            "Points per decade must be a whole number from 1 to 100, "
            "such as 20."
        )

    with _LOCK:
        return _run_ac(
            netlist, start, stop, points_per_decade, cancel_event
        )


def probe_bode(probe, sweep, name_by_point, reference_peak):
    """
    Return ``(frequency, magnitude_db, phase_degrees)`` for one probe.

    A voltage probe is gain against ``reference_peak``. A current probe
    is dB relative to 1 A. None means this sweep has no sample for it.

    :param probe: Probe to read.
    :param sweep: Result from ``run_ac``.
    :param name_by_point: Grid point to SPICE node name.
    :param reference_peak: AC source peak, in volts.
    :type reference_peak: float
    :rtype: tuple or None
    """
    if probe.method == "current":
        values = sweep.currents.get(probe.component_reference)
        scale = 1.0
    elif probe.method == "differential":
        first = _complex_for_point(sweep, name_by_point, probe.identifier)
        second = _complex_for_point(
            sweep, name_by_point, probe.second_identifier
        )

        if first is None or second is None:
            return None

        values = tuple(left - right for left, right in zip(first, second))
        scale = reference_peak
    else:
        values = _complex_for_point(sweep, name_by_point, probe.identifier)
        scale = reference_peak

    if values is None:
        return None

    return (
        sweep.frequency,
        magnitude_db(values, scale),
        phase_degrees(values, scale),
    )


def magnitude_db(values, scale):
    """
    Return 20 log10 of each magnitude, relative to ``scale``.

    A zero sample is minus infinity.

    :param values: Complex samples.
    :param scale: Positive reference, in volts or amps.
    :rtype: tuple
    """
    result = []

    for value in values:
        magnitude = abs(value) / scale

        if magnitude <= 0:
            result.append(float("-inf"))
        else:
            result.append(20.0 * math.log10(magnitude))

    return tuple(result)


def phase_degrees(values, scale):
    """
    Return the unwrapped phase of each sample, in degrees.

    ``scale`` is real and positive, so it does not change the phase.

    :param values: Complex samples.
    :param scale: Positive reference.
    :rtype: tuple
    """
    del scale
    wrapped = [
        math.degrees(math.atan2(value.imag, value.real)) for value in values
    ]
    return tuple(_unwrap_degrees(wrapped))


def sample_at_frequency(frequency, values, when):
    """
    Return the sample at ``when`` hertz, interpolated on a log axis.

    :param frequency: Sample frequencies, in hertz.
    :param values: One number per frequency.
    :param when: Frequency to read, in hertz.
    :rtype: float
    :raises SimulationError: If ``when`` is outside the sweep.
    """
    if len(frequency) != len(values) or not frequency:
        raise SimulationError("The sweep samples are not usable.")

    if when < frequency[0] or when > frequency[-1]:
        raise SimulationError("That frequency is outside the sweep.")

    for index, hertz in enumerate(frequency):
        if hertz == when:
            return values[index]

        if hertz > when:
            earlier = frequency[index - 1]
            span = math.log(hertz) - math.log(earlier)

            if span == 0:
                return values[index - 1]

            fraction = (math.log(when) - math.log(earlier)) / span

            return (
                values[index - 1]
                + fraction * (values[index] - values[index - 1])
            )

    return values[-1]


def lit_led_references(components, transient):
    """
    Return LED references whose current exceeds 1 mA at any sample.

    :param components: Placed parts.
    :param transient: Result from ``run_tran``.
    :rtype: list
    """
    lit = []

    for component in components:
        if getattr(component, "kind", None) != "led":
            continue

        series = transient.currents.get(component.reference)

        if series and max(abs(value) for value in series) > LED_LIT_AMPS:
            lit.append(component.reference)

    return lit


def _run_op(netlist):
    from PySpice.Spice.NgSpice.Shared import (
        NgSpiceCircuitError,
        NgSpiceCommandError,
    )

    shared = _shared_library()
    prepared = _with_operating_point(netlist)
    try:
        shared.destroy()
    except NgSpiceCommandError:
        shared.clear_output()
    try:
        shared.load_circuit(prepared)
        shared.run()
    except (NgSpiceCommandError, NgSpiceCircuitError, NameError):
        _raise_plain_failure(shared)
    plot_name = shared.last_plot
    if not plot_name or plot_name == "const":
        _raise_plain_failure(shared)
    plot = shared.plot(None, plot_name)
    return _read_operating_point(plot, netlist)


def _has_ground(netlist):
    depth = 0
    for line in netlist.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        lowered = stripped.lower()
        if lowered.startswith(".subckt"):
            depth += 1
            continue
        if lowered.startswith(".ends"):
            depth = max(0, depth - 1)
            continue
        if depth or stripped.startswith("."):
            continue
        if "0" in stripped.split():
            return True
    return False


def _with_operating_point(netlist):
    lines = [line for line in netlist.splitlines() if line.strip()]
    if lines and lines[-1].strip().lower() == ".end":
        lines.pop()
    lines.append(".options savecurrents")
    lines.append(".op")
    lines.append(".end")
    return "\n".join(lines) + "\n"


def _run_tran(netlist, step, stop, use_initial_conditions, cancel_event):
    from PySpice.Spice.NgSpice.Shared import (
        NgSpiceCircuitError,
        NgSpiceCommandError,
    )

    shared = _shared_library()
    prepared = _with_transient(
        netlist, step, stop, use_initial_conditions
    )

    try:
        shared.destroy()
    except NgSpiceCommandError:
        shared.clear_output()

    if cancel_event is not None and cancel_event.is_set():
        raise SimulationError("Stopped.")

    try:
        shared.load_circuit(prepared)
        shared.run()
    except (NgSpiceCommandError, NgSpiceCircuitError, NameError):
        _raise_plain_failure(shared)

    if cancel_event is not None and cancel_event.is_set():
        raise SimulationError("Stopped.")

    plot_name = shared.last_plot

    if not plot_name or plot_name == "const":
        _raise_plain_failure(shared)

    plot = shared.plot(None, plot_name)

    return _read_transient(plot, netlist)


def _with_transient(netlist, step, stop, use_initial_conditions):
    lines = [line for line in netlist.splitlines() if line.strip()]

    if lines and lines[-1].strip().lower() == ".end":
        lines.pop()

    command = (
        f".tran {format_spice_number(step)} {format_spice_number(stop)}"
    )

    if use_initial_conditions:
        command += " uic"

    lines.append(".options savecurrents")
    lines.append(command)
    lines.append(".end")

    return "\n".join(lines) + "\n"


def _spectrum_samples(time_seconds, values):
    if len(time_seconds) != len(values) or not time_seconds:
        raise SimulationError("The transient samples are not usable.")

    if len(time_seconds) < 4:
        raise SimulationError(
            "A spectrum needs at least 4 samples from a transient run."
        )

    times = []
    samples = []
    previous = None

    for instant, sample in zip(time_seconds, values):
        if not _finite_number(instant) or not _finite_number(sample):
            raise SimulationError("The transient samples are not usable.")

        if previous is not None and not instant > previous:
            raise SimulationError(
                "The transient times must move forward."
            )

        times.append(float(instant))
        samples.append(float(sample))
        previous = instant

    return tuple(times), tuple(samples)


def _finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _positive_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _run_ac(netlist, start, stop, points_per_decade, cancel_event):
    from PySpice.Spice.NgSpice.Shared import (
        NgSpiceCircuitError,
        NgSpiceCommandError,
    )

    shared = _shared_library()
    prepared = _with_ac(netlist, start, stop, points_per_decade)

    try:
        shared.destroy()
    except NgSpiceCommandError:
        shared.clear_output()

    if cancel_event is not None and cancel_event.is_set():
        raise SimulationError("Stopped.")

    try:
        shared.load_circuit(prepared)
        shared.run()
    except (NgSpiceCommandError, NgSpiceCircuitError, NameError):
        _raise_plain_failure(shared)

    if cancel_event is not None and cancel_event.is_set():
        raise SimulationError("Stopped.")

    plot_name = shared.last_plot

    if not plot_name or plot_name == "const":
        _raise_plain_failure(shared)

    plot = shared.plot(None, plot_name)

    return _read_frequency(plot, netlist)


def _with_ac(netlist, start, stop, points_per_decade):
    lines = [line for line in netlist.splitlines() if line.strip()]

    if lines and lines[-1].strip().lower() == ".end":
        lines.pop()

    lines.append(".options savecurrents")
    lines.append(
        f".ac dec {points_per_decade} {format_spice_number(start)} "
        f"{format_spice_number(stop)}"
    )
    lines.append(".end")

    return "\n".join(lines) + "\n"


def _complex_for_point(sweep, name_by_point, identifier):
    if not identifier:
        return None

    node = name_by_point.get(identifier)

    if node is None:
        return None

    return sweep.voltages.get(node)


def _unwrap_degrees(wrapped):
    unwrapped = []
    previous = None

    for value in wrapped:
        if previous is not None:
            while value - previous > 180:
                value -= 360

            while value - previous < -180:
                value += 360

        unwrapped.append(value)
        previous = value

    return unwrapped


def _voltage_for_point(transient, name_by_point, identifier):
    if not identifier:
        return None

    node = name_by_point.get(identifier)

    if node is None:
        return None

    return transient.voltages.get(node)


def _series(vector):
    return tuple(float(value) for value in vector._data)


def _read_transient(plot, netlist):
    spellings = _spellings(netlist)
    part_names = {
        name.lower(): _restore(name, spellings)
        for name in _top_level_parts(netlist)
    }
    time_seconds = None
    voltages = {}
    branch_currents = {}
    device_currents = {}

    for name, vector in plot.items():
        if name.lower() == "time":
            time_seconds = _series(vector)
            continue

        if vector.is_voltage_node:
            node = name[2:-1] if name.lower().startswith("v(") else name
            voltages[_restore(node, spellings)] = _series(vector)
            continue

        if name.endswith("#branch"):
            reference = name[:-len("#branch")]
            original = part_names.get(reference.lower())

            if original is not None:
                branch_currents[original] = _series(vector)

            continue

        match = _DEVICE_CURRENT.match(name)

        if match is None:
            continue

        original = part_names.get(match.group(1).lower())

        if original is not None:
            device_currents[original] = _series(vector)

    if not time_seconds:
        raise SimulationError("The transient did not return a time axis.")

    count = len(time_seconds)
    voltages = {
        name: values for name, values in voltages.items()
        if len(values) == count
    }
    voltages["0"] = tuple(0.0 for _ in time_seconds)
    currents = {
        name: values for name, values in device_currents.items()
        if len(values) == count
    }
    currents.update({
        name: values for name, values in branch_currents.items()
        if len(values) == count
    })

    return Transient(time_seconds, voltages, currents)


def _complex_series(vector):
    return tuple(complex(value) for value in vector._data)


def _read_frequency(plot, netlist):
    spellings = _spellings(netlist)
    part_names = {
        name.lower(): _restore(name, spellings)
        for name in _top_level_parts(netlist)
    }
    frequency = None
    voltages = {}
    branch_currents = {}
    device_currents = {}

    for name, vector in plot.items():
        if name.lower() == "frequency":
            frequency = tuple(float(value.real) for value in vector._data)
            continue

        if vector.is_voltage_node:
            node = name[2:-1] if name.lower().startswith("v(") else name
            voltages[_restore(node, spellings)] = _complex_series(vector)
            continue

        if name.endswith("#branch"):
            reference = name[:-len("#branch")]
            original = part_names.get(reference.lower())

            if original is not None:
                branch_currents[original] = _complex_series(vector)

            continue

        match = _DEVICE_CURRENT.match(name)

        if match is None:
            continue

        original = part_names.get(match.group(1).lower())

        if original is not None:
            device_currents[original] = _complex_series(vector)

    if not frequency:
        raise SimulationError(
            "The frequency sweep did not return a frequency axis."
        )

    count = len(frequency)
    voltages = {
        name: values for name, values in voltages.items()
        if len(values) == count
    }
    voltages["0"] = tuple(0j for _ in frequency)
    currents = {
        name: values for name, values in device_currents.items()
        if len(values) == count
    }
    currents.update({
        name: values for name, values in branch_currents.items()
        if len(values) == count
    })

    return FrequencySweep(frequency, voltages, currents)


def _library_path():
    configured = os.environ.get("NGSPICE_LIBRARY_PATH")
    if configured:
        return configured if Path(configured).is_file() else None

    found = ctypes.util.find_library("ngspice")
    if found and Path(found).is_file():
        return found
    if found:
        return found

    conda_prefix = os.environ.get("CONDA_PREFIX")
    candidates = []
    if conda_prefix:
        root = Path(conda_prefix)
        candidates.extend((
            root / "Library" / "bin" / "ngspice.dll",
            root / "lib" / "libngspice.so",
            root / "lib" / "libngspice.so.0",
        ))
    candidates.extend((
        Path("/usr/lib/x86_64-linux-gnu/libngspice.so.0"),
        Path("/usr/lib/x86_64-linux-gnu/libngspice.so"),
        Path("/usr/lib/libngspice.so.0"),
        Path("/lib/x86_64-linux-gnu/libngspice.so.0"),
    ))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _spellings(netlist):
    found = {}
    for line in netlist.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        for token in stripped.replace("(", " ").replace(")", " ").split():
            if not _ELEMENT_NAME.match(token):
                continue
            found.setdefault(token.lower(), set()).add(token)
    found.setdefault("0", set()).add("0")
    return found


def _restore(name, spellings):
    choices = spellings.get(name.lower())
    if not choices:
        return name
    if len(choices) == 1:
        return next(iter(choices))
    listed = " and ".join(sorted(choices))
    raise SimulationError(
        f"The names {listed} are the same to ngspice. Use one spelling."
    )


def _top_level_parts(netlist):
    names = []
    depth = 0
    for line in netlist.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        lowered = stripped.lower()
        if lowered.startswith(".subckt"):
            depth += 1
            continue
        if lowered.startswith(".ends"):
            depth = max(0, depth - 1)
            continue
        if depth or stripped.startswith("."):
            continue
        names.append(stripped.split()[0])
    return names


def _scalar(vector):
    return float(vector._data[0])


def _read_operating_point(plot, netlist):
    spellings = _spellings(netlist)
    part_names = {
        name.lower(): _restore(name, spellings)
        for name in _top_level_parts(netlist)
    }
    voltages = {"0": 0.0}
    branch_currents = {}
    device_currents = {}

    for name, vector in plot.items():
        if vector.is_voltage_node:
            node = name[2:-1] if name.startswith("V(") else name
            voltages[_restore(node, spellings)] = _scalar(vector)
            continue
        if name.endswith("#branch"):
            reference = name[:-len("#branch")]
            original = part_names.get(reference.lower())
            if original is not None:
                branch_currents[original] = _scalar(vector)
            continue
        match = _DEVICE_CURRENT.match(name)
        if match is None:
            continue
        original = part_names.get(match.group(1).lower())
        if original is not None:
            device_currents[original] = _scalar(vector)

    currents = dict(device_currents)
    currents.update(branch_currents)
    return OperatingPoint(voltages, currents)


def _failure_text(shared):
    return "\n".join(part for part in (shared.stderr, shared.stdout) if part)


def _raise_plain_failure(shared):
    text = _failure_text(shared).lower()
    if "singular matrix" in text and "#branch" in text:
        raise SimulationError(
            "The circuit did not solve. The voltage sources form a loop. "
            "Put a resistor in series with one of them."
        )
    if "floating" in text:
        raise SimulationError(
            "The circuit did not solve. A node is floating. "
            "Each node needs two connections."
        )
    raise SimulationError(
        "The circuit did not solve. Check the ground and the "
        "voltage sources."
    )


def _install_quiet_ngspice():
    from PySpice.Spice.NgSpice.Shared import NgSpiceShared, ffi, ffi_string_utf8

    class QuietNgSpice(NgSpiceShared):
        """ngspice shared library that does not treat notes as failures."""

        @staticmethod
        def _send_char(message_c, ngspice_id, user_data):
            self = ffi.from_handle(user_data)
            message = ffi_string_utf8(message_c)
            prefix, _, content = message.partition(" ")
            lowered = content.lower()
            if prefix == "stderr":
                self._stderr.append(content)
                note = lowered.startswith(("warning", "note", "using "))
                failed = (
                    "error" in lowered
                    or "fatal" in lowered
                    or "fail" in lowered
                )
                if not note and failed:
                    self._error_in_stderr = True
            else:
                self._stdout.append(content)
                if "error" in lowered:
                    self._error_in_stdout = True
            return self.send_char(message, ngspice_id)

    return QuietNgSpice


_QuietNgSpice = None


def _shared_library():
    global _SHARED, _QuietNgSpice
    if _SHARED is not None:
        return _SHARED

    path = _library_path()
    if path is None:
        raise SimulationError(NGSPICE_MISSING)

    try:
        if _QuietNgSpice is None:
            _QuietNgSpice = _install_quiet_ngspice()
    except ImportError as error:
        raise SimulationError(NGSPICE_MISSING) from error

    logging.getLogger("PySpice").setLevel(logging.ERROR)
    _QuietNgSpice.LIBRARY_PATH = path
    try:
        _SHARED = _QuietNgSpice.new_instance()
    except Exception as error:
        raise SimulationError(NGSPICE_MISSING) from error
    return _SHARED
