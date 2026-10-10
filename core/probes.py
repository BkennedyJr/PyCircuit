"""
Probes on the grid.

Direct reads a node voltage and adds nothing. 1 Mohm puts a 1 megohm
resistor from the point to ground. A 10x scope probe puts 10 megohm in
parallel with 10 pF to ground. Differential reads the first point minus
the second. Current reads the current through one part.

The numbers come from the s-domain formula. ngspice is not required.
"""

import math

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

    ``has_plot`` is false until a scope trace is drawing this probe. A
    probe with no plot shows a parameter box (voltage, current, frequency,
    phase). A probe on a plot does not: the trace is the reading.

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

        return probe

    def set_has_plot(self, reference, has_plot):
        """
        Remember whether a scope trace is drawing this probe.

        A probe on a plot has no parameter box.

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
    Return the meter lines for a probe that is not on a plot.

    A voltage probe reports voltage. A current probe reports current, and
    the voltage across a two-pin part. Frequency is ``DC`` when the
    reading has settled to a number, or the AC source frequency when the
    reading is a sine. Phase is the steady-state angle of that sine.
    Several AC frequencies are listed one by one.

    A probe with ``has_plot`` returns no lines: the plot shows it.

    :param probe: Probe to read.
    :param formulas: Solved formulas for the loaded circuit.
    :param components: Placed parts, used for AC amplitude and frequency.
    :param component: The part under a current probe.
    :returns: ``(label, value)`` pairs, such as ``("Voltage", "5 V")``.
    :rtype: list
    """
    if probe.has_plot:
        return []

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


def _probe_sort_key(reference):
    """
    Sort key so P2 comes before P10.

    :rtype: int
    """
    return int(reference[len(PROBE_REFERENCE_PREFIX):])
