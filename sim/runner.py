"""
DC operating point through the ngspice shared library.

``run_op`` takes the netlist text from ``core.netlist.build_netlist``.
Ground is node 0. ngspice hands node names back in lowercase; they are
mapped to the spelling in the netlist (Vcc stays Vcc).

Current is in amps. For a resistor it is from the first pin toward the
second. For a voltage source it is into the positive pin, so a source
that is powering the circuit has a negative current.
"""

import ctypes.util
import logging
import os
import re
import threading
from pathlib import Path

from core.exceptions import SimulationError
from core.netlist import build_netlist

NGSPICE_MISSING = (
    "ngspice is not installed. See README: Installing ngspice."
)

_LOCK = threading.Lock()
_SHARED = None
_ELEMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEVICE_CURRENT = re.compile(r"^@([^[]+)\[(i|current)\]$")


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
