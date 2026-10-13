"""
Probes on the grid.

Direct reads a node voltage and adds nothing. 1 Mohm puts a 1 megohm
resistor from the point to ground. A 10x scope probe puts 10 megohm in
parallel with 10 pF to ground. Differential reads the first point minus
the second. Current reads the current through one part.

The numbers come from the s-domain formula. ngspice is not required.
"""

import math
import re

import sympy

from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError, GridConfigurationError

PROBE_REFERENCE_PREFIX = "P"

PROBE_METHODS = (
    "direct",
    "megohm",
    "scope_10x",
    "differential",
    "current",
)

PROBE_METHOD_LABELS = {
    "direct": "Direct",
    "megohm": "1 Mohm",
    "scope_10x": "10x scope",
    "differential": "Differential",
    "current": "Current",
}

# One colour per probe, then the list repeats. Bright enough to see on
# the dark grid, and each one is a flag rather than a recolour of a dot.
PROBE_COLORS = (
    "#ff6b6b",
    "#4ecdc4",
    "#ffd93d",
    "#c084fc",
    "#74c0fc",
    "#b2f2bb",
    "#ff922b",
    "#f783ac",
)

MEGOHM_OHMS = 1e6
SCOPE_OHMS = 10e6
SCOPE_FARADS = 10e-12

_VOLTAGE_METHODS = ("direct", "megohm", "scope_10x", "differential")


class Probe:
    """
    One probe.

    A voltage probe stores a grid-point identifier. A differential probe
    also stores the second point once it has been chosen. A current probe
    stores a part reference instead of a point.

    ``has_plot`` is false until a scope trace is drawing this probe. The
    flag keeps a parameter box (voltage, current, frequency, phase) either
    way, and a new part value updates that box. The Probe panel says the
    probe is on a plot instead of repeating the box.

    :param reference: Name such as ``P1``.
    :param method: One of ``PROBE_METHODS``.
    :param color: CSS colour used to draw the flag.
    """

    def __init__(self, reference, method, color, identifier=None,
                 second_identifier=None, component_reference=None):
        self.reference = reference
        self.method = method
        self.color = color
        self.identifier = identifier
        self.second_identifier = second_identifier
        self.component_reference = component_reference
        self.has_plot = False
        # Scene pixels from the measured point to where the flag was
        # released. (0, 0) is the usual place, up and to the left.
        self.flag_offset = (0.0, 0.0)
        self.second_flag_offset = (0.0, 0.0)

    def offset_for(self, which="primary"):
        """
        Return the flag shift for one end of this probe.

        :param which: ``"primary"`` or ``"second"``.
        :type which: str
        :returns: ``(across, down)`` in scene pixels.
        :rtype: tuple
        :raises ComponentError: If ``which`` is not an end of a probe.
        """
        if which == "primary":
            return self.flag_offset

        if which == "second":
            return self.second_flag_offset

        raise ComponentError(
            f"A probe flag must be 'primary' or 'second', not {which!r}."
        )

    def set_flag_offset(self, dx, dy, which="primary"):
        """
        Remember where one flag was released, relative to its point.

        A shift smaller than half a pixel is stored as the usual place.

        :param dx: Scene pixels to the right of the measured point.
        :param dy: Scene pixels down from the measured point.
        :param which: ``"primary"`` or ``"second"``.
        :returns: The offset that was stored.
        :rtype: tuple
        :raises ComponentError: If the numbers are not finite, or
            ``which`` is not an end of a probe.
        """
        pair = _flag_offset_pair(dx, dy)

        if which == "primary":
            self.flag_offset = pair
        elif which == "second":
            self.second_flag_offset = pair
        else:
            raise ComponentError(
                f"A probe flag must be 'primary' or 'second', not {which!r}."
            )

        return pair

    def reset_flag_position(self):
        """
        Put both flags back in the usual place beside their points.

        :returns: None
        """
        self.flag_offset = (0.0, 0.0)
        self.second_flag_offset = (0.0, 0.0)

    def flag_is_moved(self):
        """
        Return whether either flag has been dragged off its usual place.

        :rtype: bool
        """
        return (
            self.flag_offset != (0.0, 0.0)
            or self.second_flag_offset != (0.0, 0.0)
        )

    def to_dict(self):
        """
        Return this probe as JSON-ready data.

        A plot is not saved: opening the file shows the parameter box again.

        :rtype: dict
        """
        data = {
            "reference": self.reference,
            "method": self.method,
            "color": self.color,
        }

        if self.method == "current":
            data["part"] = self.component_reference
        else:
            data["point"] = self.identifier

            if self.second_identifier:
                data["second_point"] = self.second_identifier

        _store_flag_offset(data, "flag_x", "flag_y", self.flag_offset)

        if self.second_identifier:
            _store_flag_offset(
                data, "second_flag_x", "second_flag_y", self.second_flag_offset
            )

        return data


class ProbeCollection:
    """
    The probes on one circuit.

    References start at P1 and reuse the lowest free number.
    """

    def __init__(self):
        self.probes_by_reference = {}

    def next_reference(self):
        """
        Return the lowest unused probe reference, such as ``P1``.

        :rtype: str
        """
        number = 1

        while f"{PROBE_REFERENCE_PREFIX}{number}" in self.probes_by_reference:
            number += 1

        return f"{PROBE_REFERENCE_PREFIX}{number}"

    def get_probes(self):
        """
        Return every probe, P1 before P2 before P10.

        :rtype: list
        """
        return sorted(
            self.probes_by_reference.values(),
            key=lambda probe: _probe_sort_key(probe.reference)
        )

    def get(self, reference):
        """
        Return one probe.

        :param reference: Probe reference, such as ``P1``.
        :type reference: str
        :rtype: Probe
        :raises ComponentError: If there is no probe with that name.
        """
        probe = self.probes_by_reference.get(reference)

        if probe is None:
            raise ComponentError(f"There is no probe {reference}.")

        return probe

    def add_voltage(self, identifier, connection_grid):
        """
        Add a Direct probe on one grid point.

        :param identifier: Point such as ``NODE_R02_C03``.
        :type identifier: str
        :param connection_grid: Grid the point must belong to.
        :rtype: Probe
        :raises ComponentError: If the point is not on the grid.
        """
        _require_point(identifier, connection_grid)
        reference = self.next_reference()
        probe = Probe(
            reference,
            "direct",
            _color_for(reference),
            identifier=identifier
        )
        self.probes_by_reference[reference] = probe

        return probe

    def add_current(self, component):
        """
        Add a current probe on one part.

        :param component: Part whose current is measured.
        :rtype: Probe
        :raises ComponentError: If that part already has a current probe.
        """
        existing = self.current_probe_for(component.reference)

        if existing is not None:
            raise ComponentError(
                f"{component.reference} already has current probe "
                f"{existing.reference}."
            )

        reference = self.next_reference()
        probe = Probe(
            reference,
            "current",
            _color_for(reference),
            component_reference=component.reference
        )
        self.probes_by_reference[reference] = probe

        return probe

    def place_saved(self, reference, method, color, connection_grid,
                    identifier=None, second_identifier=None,
                    component_reference=None, components=(),
                    flag_offset=(0.0, 0.0), second_flag_offset=(0.0, 0.0)):
        """
        Put a probe from a project file onto the circuit, keeping its name.

        :rtype: Probe
        :raises ComponentError: If the probe is invalid or the name is
            already used. Nothing is stored then.
        """
        if reference in self.probes_by_reference:
            raise ComponentError(
                f"{reference} is already on this circuit."
            )

        if not _valid_probe_reference(reference):
            raise ComponentError(
                f"Probe reference {reference!r} is not valid. Use P "
                "followed by a number, for example P1."
            )

        if method not in PROBE_METHODS:
            raise ComponentError(
                f"{method!r} is not a probe method. Choose Direct, "
                "1 Mohm, 10x scope, Differential or Current."
            )

        if not _valid_probe_color(color):
            raise ComponentError(
                f"Probe colour {color!r} is not valid. Use a colour such "
                "as #ff6b6b."
            )

        if method == "current":
            if identifier or second_identifier:
                raise ComponentError(
                    f"{reference} measures current, so it sits on a part, "
                    "not a grid point."
                )

            component = _component_by_reference(
                components, component_reference
            )
            existing = self.current_probe_for(component.reference)

            if existing is not None:
                raise ComponentError(
                    f"{component.reference} already has current probe "
                    f"{existing.reference}."
                )

            probe = Probe(
                reference,
                "current",
                color,
                component_reference=component.reference
            )
        else:
            if component_reference:
                raise ComponentError(
                    f"{reference} measures a point, not a part's current."
                )

            _require_point(identifier, connection_grid)

            if method == "differential" and second_identifier:
                _require_point(second_identifier, connection_grid)

                if second_identifier == identifier:
                    raise ComponentError(
                        "The two points of a differential probe must be "
                        "different."
                    )
            elif second_identifier:
                raise ComponentError(
                    f"{reference} is not differential, so it has one point."
                )

            probe = Probe(
                reference,
                method,
                color,
                identifier=identifier,
                second_identifier=second_identifier
            )

        primary = _require_offset(flag_offset)
        second = _require_offset(second_flag_offset)

        if probe.second_identifier is None and second != (0.0, 0.0):
            raise ComponentError(
                f"{reference} has a position for a second flag, but it "
                "has only one point."
            )

        probe.flag_offset = primary
        probe.second_flag_offset = second
        self.probes_by_reference[reference] = probe

        return probe

    def voltage_probe_at(self, identifier):
        """
        Return the first voltage probe on a point, or None.

        :rtype: Probe or None
        """
        for probe in self.get_probes():
            if probe.method != "current" and probe.identifier == identifier:
                return probe

        return None

    def current_probe_for(self, component_reference):
        """
        Return the current probe on a part, or None.

        :rtype: Probe or None
        """
        for probe in self.get_probes():
            if (probe.method == "current" and
                    probe.component_reference == component_reference):
                return probe

        return None

    def set_method(self, reference, method, components=()):
        """
        Change how one probe measures.

        Switching to Current uses the single part on the probed point.
        Switching away from Current keeps that part's anchor as the point.
        A differential probe keeps its first point and drops the second
        when it becomes another voltage method.

        :param reference: Probe to change.
        :param method: One of ``PROBE_METHODS``.
        :param components: Placed parts, needed when moving to or from
            a current probe.
        :rtype: Probe
        :raises ComponentError: If the method is unknown, or Current has
            no single part to measure. The probe is left unchanged.
        """
        if method not in PROBE_METHODS:
            raise ComponentError(
                f"{method!r} is not a probe method. Choose Direct, "
                "1 Mohm, 10x scope, Differential or Current."
            )

        probe = self.get(reference)

        if probe.method == method:
            return probe

        if method == "current":
            component = _part_for_current(probe, components)
            probe.method = "current"
            probe.component_reference = component.reference
            probe.identifier = None
            probe.second_identifier = None
            probe.second_flag_offset = (0.0, 0.0)
            return probe

        if probe.method == "current":
            component = _component_by_reference(
                components, probe.component_reference
            )
            probe.identifier = ConnectionGrid.build_connection_point_identifier(
                component.row_number, component.column_number
            )
            probe.component_reference = None

        probe.method = method

        if method != "differential":
            probe.second_identifier = None
            probe.second_flag_offset = (0.0, 0.0)

        return probe

    def set_has_plot(self, reference, has_plot):
        """
        Remember whether a scope trace is drawing this probe.

        The flag still shows its parameter box. The Probe panel says
        the probe is on a plot.

        :param reference: Probe reference, such as ``P1``.
        :param has_plot: True when a plot shows this probe.
        :type has_plot: bool
        :rtype: Probe
        """
        probe = self.get(reference)
        probe.has_plot = bool(has_plot)

        return probe

    def set_second_point(self, reference, identifier, connection_grid):
        """
        Set the minus point of a differential probe.

        :raises ComponentError: If the probe is not differential, or the
            point is the same as the first point, or it is off the grid.
        """
        probe = self.get(reference)

        if probe.method != "differential":
            raise ComponentError(
                f"{reference} is not a differential probe."
            )

        _require_point(identifier, connection_grid)

        if identifier == probe.identifier:
            raise ComponentError(
                "The two points of a differential probe must be different."
            )

        probe.second_identifier = identifier

        return probe

    def move_point(self, reference, identifier, connection_grid, which="primary"):
        """
        Move a voltage probe's point, or a differential probe's second point.

        :param which: ``"primary"`` or ``"second"``.
        :rtype: Probe
        :raises ComponentError: If the point is off the grid, the probe
            measures current, or the two differential points would match.
        """
        probe = self.get(reference)
        _require_point(identifier, connection_grid)

        if probe.method == "current":
            raise ComponentError(
                f"{reference} measures current. Drop it on a part."
            )

        if which == "second":
            return self.set_second_point(reference, identifier, connection_grid)

        if which != "primary":
            raise ComponentError(
                f"A probe point must be 'primary' or 'second', not {which!r}."
            )

        if (probe.method == "differential" and
                identifier == probe.second_identifier):
            raise ComponentError(
                "The two points of a differential probe must be different."
            )

        probe.identifier = identifier

        return probe

    def move_current(self, reference, component):
        """
        Move a current probe onto another part.

        :rtype: Probe
        :raises ComponentError: If the probe is not a current probe, or
            the part already has a different current probe.
        """
        probe = self.get(reference)

        if probe.method != "current":
            raise ComponentError(
                f"{reference} measures a point, not a part's current."
            )

        existing = self.current_probe_for(component.reference)

        if existing is not None and existing.reference != reference:
            raise ComponentError(
                f"{component.reference} already has current probe "
                f"{existing.reference}."
            )

        probe.component_reference = component.reference

        return probe

    def remove(self, reference):
        """
        Remove one probe.

        :returns: The removed probe.
        :rtype: Probe
        :raises ComponentError: If the probe does not exist.
        """
        probe = self.get(reference)
        del self.probes_by_reference[reference]

        return probe

    def rename_part(self, old_reference, new_reference):
        """
        Point current probes at a part's new schematic name.

        :param old_reference: Name the part had, such as ``V1``.
        :type old_reference: str
        :param new_reference: Name the part has now, such as ``BATT``.
        :type new_reference: str
        :returns: None
        """
        for probe in self.probes_by_reference.values():
            if probe.component_reference == old_reference:
                probe.component_reference = new_reference

    def remove_for_components(self, component_references):
        """
        Remove current probes whose part is gone.

        :param component_references: References of deleted parts.
        :returns: Removed probe references, sorted.
        :rtype: list
        """
        gone = set(component_references)
        removed = [
            probe.reference
            for probe in self.get_probes()
            if probe.component_reference in gone
        ]

        for reference in removed:
            del self.probes_by_reference[reference]

        return removed

    def remove_outside_grid(self, connection_grid):
        """
        Remove probes whose point fell off a smaller grid.

        A differential probe whose second point fell off keeps its first
        point and forgets the second. A probe whose first point fell off
        is removed.

        :returns: Removed probe references, sorted.
        :rtype: list
        """
        removed = []

        for probe in self.get_probes():
            if probe.method == "current":
                continue

            if not _point_fits(probe.identifier, connection_grid):
                removed.append(probe.reference)
                continue

            if (probe.second_identifier is not None and
                    not _point_fits(probe.second_identifier, connection_grid)):
                probe.second_identifier = None
                probe.second_flag_offset = (0.0, 0.0)

        for reference in removed:
            del self.probes_by_reference[reference]

        return removed


def shunt_loads(probes):
    """
    Return the parts a probe adds from its point to ground.

    Direct, differential and current add nothing. 1 Mohm adds a 1 megohm
    resistor. A 10x scope probe adds 10 megohm in parallel with 10 pF.

    :param probes: Probes to read.
    :returns: ``(identifier, "resistor" or "capacitor", value)`` tuples.
    :rtype: tuple
    """
    loads = []

    for probe in probes:
        if probe.method == "megohm" and probe.identifier:
            loads.append((probe.identifier, "resistor", MEGOHM_OHMS))
        elif probe.method == "scope_10x" and probe.identifier:
            loads.append((probe.identifier, "resistor", SCOPE_OHMS))
            loads.append((probe.identifier, "capacitor", SCOPE_FARADS))

    return tuple(loads)


def describe_reading(probe, formulas, component=None):
    """
    Return the text shown for one probe.

    A 10x probe also gives the value at DC (s = 0), because the capacitor
    is open then.

    :param probe: Probe to describe.
    :param formulas: Solved ``NodeFormulas`` for the loaded circuit.
    :param component: The part under a current probe.
    :rtype: str
    """
    if probe.method == "current":
        if component is None:
            return "This current probe is not on a part."

        return formulas.current_text(component)

    if probe.method == "differential":
        return formulas.difference_text(
            probe.identifier, probe.second_identifier
        )

    if not probe.identifier:
        return "Not connected."

    text = formulas.text_at(probe.identifier)

    if probe.method == "scope_10x":
        expression = formulas.expression_at(probe.identifier)
        dc_line = _dc_line(expression)

        if dc_line is not None:
            return f"{text}\n{dc_line}"

    return text


def parameter_lines(probe, formulas, components, component=None):
    """
    Return the meter lines drawn in a probe's parameter box.

    A voltage probe reports voltage. A current probe reports current, and
    the voltage across a two-pin part. Frequency is ``DC`` when the
    reading has settled to a number, or the AC source frequency when the
    reading is a sine. Phase is the steady-state angle of that sine.
    Several AC frequencies are listed one by one.

    A probe on a plot still returns these lines. The grid box uses them.
    The Probe panel says the probe is on a plot instead.

    :param probe: Probe to read.
    :param formulas: Solved formulas for the loaded circuit.
    :param components: Placed parts, used for AC amplitude and frequency.
    :param component: The part under a current probe.
    :returns: ``(label, value)`` pairs, such as ``("Voltage", "5 V")``.
    :rtype: list
    """
    if probe.method == "current":
        if component is None:
            return []

        current_values, rhythm = _meter_parts(
            formulas.current_expression(component), components, "Current", "A"
        )
        voltage_values = []
        pins = component.get_pin_identifiers()

        if len(pins) == 2:
            first = formulas.expression_at(pins[0])
            second = formulas.expression_at(pins[1])

            if first is not None and second is not None:
                voltage_values, _ignored = _meter_parts(
                    sympy.simplify(first - second), components, "Voltage", "V"
                )

        return current_values + voltage_values + rhythm

    expression = _probe_voltage_expression(probe, formulas)

    if expression is None:
        return []

    values, rhythm = _meter_parts(expression, components, "Voltage", "V")

    return values + rhythm


def _probe_voltage_expression(probe, formulas):
    """
    Return the voltage a probe measures, or None when it is not ready.

    :rtype: sympy.Expr or None
    """
    if probe.method == "differential":
        if not probe.identifier or not probe.second_identifier:
            return None

        left = formulas.expression_at(probe.identifier)
        right = formulas.expression_at(probe.second_identifier)

        if left is None or right is None:
            return None

        return sympy.simplify(left - right)

    if not probe.identifier:
        return None

    return formulas.expression_at(probe.identifier)


def _meter_parts(expression, components, label, unit):
    """
    Split one reading into value lines and frequency/phase lines.

    :returns: ``(value_lines, rhythm_lines)``.
    :rtype: tuple
    """
    settled = _settle(expression, components)

    if settled is None:
        return [], []

    dc, tones = settled
    audible = [
        (frequency, value)
        for frequency, value in tones
        if abs(value) >= 5e-7
    ]
    dc_value = 0.0 if abs(dc) < 5e-7 else dc
    values = []

    if abs(dc) >= 5e-7 or not audible:
        values.append((label, f"{_format_number(dc_value)} {unit}"))

    if not audible:
        return values, [("Frequency", "DC")]

    if len(audible) == 1:
        frequency, value = audible[0]

        return values + [
            (label, f"{_format_number(abs(value))} {unit} peak"),
        ], [
            ("Frequency", _format_hertz(frequency)),
            ("Phase", _format_phase(value)),
        ]

    rhythm = []

    for frequency, value in audible:
        hertz = _format_hertz(frequency)
        values.append(
            (label, f"{_format_number(abs(value))} {unit} peak at {hertz}")
        )
        rhythm.append(("Phase", f"{_format_phase(value)} at {hertz}"))

    return values, rhythm


def _settle(expression, components):
    """
    Reduce a solved reading to a DC number and one phasor per frequency.

    AC source symbols are replaced by their offset for the DC part, and
    by their peak phasor at ``s = j*2*pi*f`` for each sine. Sources at
    another frequency contribute nothing to that sine.

    :returns: ``(dc, [(frequency, complex), ...])`` or None.
    :rtype: tuple or None
    """
    if expression is None:
        return None

    expression = sympy.simplify(expression)
    laplace = sympy.symbols("s")
    sources = []

    for component in components:
        if component.kind != "ac_source":
            continue

        symbol = sympy.Symbol(component.reference)

        if symbol in expression.free_symbols:
            sources.append((component, symbol))

    source_symbols = {symbol for _component, symbol in sources}

    for symbol in expression.free_symbols:
        if symbol != laplace and symbol not in source_symbols:
            return None

    dc_map = {
        symbol: _exact_parameter(component.parameter_values.get("offset", 0))
        for component, symbol in sources
    }
    dc_number = _as_complex(
        sympy.simplify(expression.subs(dc_map).subs(laplace, 0))
    )

    if dc_number is None or abs(dc_number.imag) > 1e-6:
        return None

    tones = []

    for frequency, members in _group_by_frequency(sources):
        member_ids = {id(component) for component, _symbol in members}
        phasor_map = {}

        for component, symbol in sources:
            if id(component) in member_ids:
                amplitude = _exact_parameter(component.value)
                phase = component.parameter_values.get("phase", 0)
                phasor_map[symbol] = amplitude * sympy.exp(
                    sympy.I * _exact_parameter(phase) * sympy.pi / 180
                )
            else:
                phasor_map[symbol] = 0

        omega = 2 * sympy.pi * frequency
        tone = _as_complex(sympy.simplify(
            expression.subs(phasor_map).subs(laplace, sympy.I * omega)
        ))

        if tone is None:
            return None

        tones.append((frequency, tone))

    return dc_number.real, tones


def _group_by_frequency(sources):
    """
    Group AC sources that share one frequency.

    :returns: ``(frequency, [(component, symbol), ...])`` pairs.
    :rtype: list
    """
    groups = []

    for component, symbol in sources:
        frequency = float(component.parameter_values["frequency"])

        for group_frequency, members in groups:
            span = max(abs(frequency), abs(group_frequency), 1.0)

            if abs(frequency - group_frequency) <= 1e-6 * span:
                members.append((component, symbol))
                break
        else:
            groups.append((frequency, [(component, symbol)]))

    return sorted(groups, key=lambda group: group[0])


def _as_complex(expression):
    """
    Return a finite complex number, or None.

    :rtype: complex or None
    """
    if expression is None or expression.free_symbols:
        return None

    if expression.has(sympy.zoo, sympy.oo, -sympy.oo, sympy.nan):
        return None

    number = sympy.N(expression)
    real = float(sympy.re(number))
    imag = float(sympy.im(number))

    if not math.isfinite(real) or not math.isfinite(imag):
        return None

    return complex(real, imag)


def _exact_parameter(number):
    """
    Turn a part setting into an exact value for the meter.

    :rtype: sympy.Expr
    """
    if number == 0:
        return sympy.Integer(0)

    tolerance = abs(float(number)) * 1e-9

    return sympy.nsimplify(number, rational=True, tolerance=tolerance)


def _format_number(number):
    """
    Return a short decimal such as ``5`` or ``4.975124``.

    :rtype: str
    """
    text = f"{float(number):.6f}".rstrip("0").rstrip(".")

    if text in ("", "-0", "-"):
        return "0"

    return text


def _format_hertz(frequency):
    """
    Return a frequency such as ``1 kHz`` or ``60 Hz``.

    :rtype: str
    """
    frequency = float(frequency)

    if frequency >= 1e6:
        return f"{_format_number(frequency / 1e6)} MHz"

    if frequency >= 1e3:
        return f"{_format_number(frequency / 1e3)} kHz"

    return f"{_format_number(frequency)} Hz"


def _format_phase(value):
    """
    Return the angle of a phasor, such as ``-80.96 deg``.

    :rtype: str
    """
    degrees = math.degrees(math.atan2(value.imag, value.real))

    if abs(degrees) < 0.005:
        degrees = 0.0

    text = f"{degrees:.2f}".rstrip("0").rstrip(".")

    if text in ("", "-0", "-"):
        text = "0"

    return f"{text} deg"


def _dc_line(expression):
    """
    Return ``"At DC: 4.997501 V"`` when the formula depends on s.

    :rtype: str or None
    """
    if expression is None:
        return None

    simplified = sympy.simplify(expression)
    laplace = sympy.symbols("s")

    if laplace not in simplified.free_symbols:
        return None

    dc_value = sympy.simplify(simplified.subs(laplace, 0))

    if dc_value.free_symbols:
        return None

    number = float(dc_value)
    text = f"{number:.6f}".rstrip("0").rstrip(".")

    return f"At DC: {text} V"


def _part_for_current(probe, components):
    """
    Return the one part a voltage probe can measure current through.

    :rtype: core.components.Component
    :raises ComponentError: If there is not exactly one part on the point.
    """
    if probe.identifier is None:
        raise ComponentError(
            "Click a part to measure its current."
        )

    matches = [
        component for component in components
        if probe.identifier in component.get_pin_identifiers()
    ]

    if not matches:
        raise ComponentError(
            "Click a part to measure its current. Nothing is on this point."
        )

    if len(matches) > 1:
        names = ", ".join(component.reference for component in matches)
        raise ComponentError(
            f"More than one part is on this point ({names}). "
            "Click the part whose current you want."
        )

    return matches[0]


def _component_by_reference(components, reference):
    """
    Return the part with one reference.

    :raises ComponentError: If the part is not in the list.
    """
    for component in components:
        if component.reference == reference:
            return component

    raise ComponentError(f"There is no part {reference}.")


_POINT_TEXT_HELP = (
    "Type a grid point such as NODE_R04_C03, a row and column such as "
    "4 3 or R4 C3, or a net name such as Vcc."
)
_NODE_TEXT = re.compile(r"^NODE_R0*(\d+)_C0*(\d+)$", re.IGNORECASE)
_COMPACT_POINT_TEXT = re.compile(r"^R(\d+)C(\d+)$", re.IGNORECASE)
_ROW_COLUMN_TEXT = re.compile(
    r"^(?:R\s*)?(\d+)\s*[, ]\s*(?:C\s*)?(\d+)$",
    re.IGNORECASE,
)


def point_for_text(text, connection_grid):
    """
    Return the grid point named by text typed in the Probe panel.

    ``NODE_R04_C03`` ignores case. ``4 3``, ``4,3``, ``R4 C3`` and
    ``R4C3`` are a row and a column. A net name such as ``Vcc`` ignores
    case; when several points share it, the top-left one is used so the
    arrow has one place to point.

    :param text: What was typed.
    :type text: str
    :param connection_grid: Grid the point must lie on.
    :type connection_grid: ConnectionGrid
    :rtype: str
    :raises ComponentError: If the text is empty, not a point on this
        grid, or not a net name. The message says what is allowed.
    """
    if not isinstance(connection_grid, ConnectionGrid):
        raise ComponentError(
            "Expected a connection grid, not "
            f"{type(connection_grid).__name__}."
        )

    if not isinstance(text, str) or not text.strip():
        raise ComponentError(_POINT_TEXT_HELP)

    raw = text.strip()
    parsed = _row_and_column(raw)

    if parsed is not None:
        row_number, column_number = parsed
        identifier = ConnectionGrid.build_connection_point_identifier(
            row_number, column_number
        )
        _require_point(identifier, connection_grid)
        return identifier

    folded = raw.casefold()
    matches = sorted(
        identifier
        for identifier, label in connection_grid.get_net_labels().items()
        if label.casefold() == folded
    )

    if not matches:
        raise ComponentError(
            f"'{raw}' is not a point on this grid. {_POINT_TEXT_HELP}"
        )

    return matches[0]


def _row_and_column(text):
    """
    Return ``(row, column)`` when text is a point, or None.

    :rtype: tuple or None
    """
    for pattern in (_NODE_TEXT, _COMPACT_POINT_TEXT, _ROW_COLUMN_TEXT):
        match = pattern.fullmatch(text)

        if match is not None:
            return (int(match.group(1)), int(match.group(2)))

    return None


def _require_point(identifier, connection_grid):
    """
    Raise ComponentError unless the identifier is on the grid.

    :returns: None
    """
    if not isinstance(connection_grid, ConnectionGrid):
        raise ComponentError(
            "Expected a connection grid, not "
            f"{type(connection_grid).__name__}."
        )

    try:
        connection_grid.get_connection_point(identifier)
    except GridConfigurationError:
        raise ComponentError(
            f"A probe must sit on a grid point such as NODE_R02_C03, "
            f"not {identifier!r}."
        )


def _point_fits(identifier, connection_grid):
    """
    Return whether a stored point is still on the grid.

    :rtype: bool
    """
    try:
        connection_grid.get_connection_point(identifier)
    except GridConfigurationError:
        return False

    return True


def _color_for(reference):
    """
    Return the flag colour for a probe reference.

    :rtype: str
    """
    number = int(reference[len(PROBE_REFERENCE_PREFIX):])

    return PROBE_COLORS[(number - 1) % len(PROBE_COLORS)]


def _valid_probe_reference(reference):
    """
    Return whether ``reference`` is P1, P2, P10 and not P0 or P01.

    :rtype: bool
    """
    if not isinstance(reference, str) or not reference.startswith("P"):
        return False

    number = reference[1:]

    return number.isdigit() and not number.startswith("0")


def _valid_probe_color(color):
    """
    Return whether ``color`` is a ``#`` RGB colour such as ``#ff6b6b``.

    :rtype: bool
    """
    if not isinstance(color, str) or len(color) != 7 or color[0] != "#":
        return False

    return all(character in "0123456789abcdefABCDEF" for character in color[1:])


def flag_offset_from_saved(data, x_key, y_key):
    """
    Read one saved flag position, or the usual place when it was not saved.

    :param data: One probe object from a project file.
    :type data: dict
    :param x_key: Key for the across distance, such as ``"flag_x"``.
    :param y_key: Key for the down distance.
    :returns: ``(across, down)``.
    :rtype: tuple
    :raises ComponentError: If only one of the two numbers is present, or
        a number is not finite.
    """
    has_x = x_key in data
    has_y = y_key in data

    if has_x != has_y:
        raise ComponentError(
            "A saved probe position needs both the across and down "
            "numbers, or neither."
        )

    if not has_x:
        return (0.0, 0.0)

    return _flag_offset_pair(data[x_key], data[y_key])


def _store_flag_offset(data, x_key, y_key, offset):
    """
    Write a flag position when it is not the usual place.

    :returns: None
    """
    if offset == (0.0, 0.0):
        return

    data[x_key] = offset[0]
    data[y_key] = offset[1]


def _require_offset(offset):
    """
    Return a stored ``(across, down)`` pair.

    :raises ComponentError: If the value is not two numbers.
    """
    if (
        isinstance(offset, (tuple, list))
        and not isinstance(offset, str)
        and len(offset) == 2
    ):
        return _flag_offset_pair(offset[0], offset[1])

    raise ComponentError(
        "A probe position must be two numbers: how far across, and how "
        "far down, from the point it measures."
    )


def _flag_offset_pair(dx, dy):
    """
    Return a finite ``(across, down)`` pair, or the usual place.

    :raises ComponentError: If either value is not a finite number.
    """
    if not _is_real_number(dx) or not _is_real_number(dy):
        raise ComponentError(
            "A probe position must be two numbers: how far across, and "
            "how far down, from the point it measures."
        )

    x_position = float(dx)
    y_position = float(dy)

    if not math.isfinite(x_position) or not math.isfinite(y_position):
        raise ComponentError(
            "A probe position must be a finite distance from the point "
            "it measures."
        )

    if abs(x_position) < 0.5 and abs(y_position) < 0.5:
        return (0.0, 0.0)

    return (x_position, y_position)


def _is_real_number(value):
    """
    Return True for an int or float, and False for bool and other types.

    :rtype: bool
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _probe_sort_key(reference):
    """
    Sort key so P2 comes before P10.

    :rtype: int
    """
    return int(reference[len(PROBE_REFERENCE_PREFIX):])
