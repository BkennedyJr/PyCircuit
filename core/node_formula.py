"""
s-domain voltage formula for each electrical node.

This is V(s), the Laplace-domain voltage at a node, not an RF scattering
parameter (S11, S21). ngspice does not write this formula; it will later
give numbers to compare with it.

Resistors, capacitors, inductors and sources are stamped as impedances
(R, 1/(sC), sL). A bridge is not a connection: only the points a wire
joins are one node. Points that share a net label are also one node, and
Vcc matches vcc. An op-amp is ideal here: its two inputs are held at
the same voltage, and its supply pins are not part of the formula. A
diode, LED or transistor has no formula.
"""

import itertools

import sympy

from core.components import Component
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.wires import WireCollection

_LAPLACE = sympy.symbols("s")

_LINEAR_KINDS = (
    "resistor",
    "capacitor",
    "capacitor_polarized",
    "inductor",
    "dc_source",
    "ac_source",
    "current_source",
    "opamp_generic",
    "opamp_741",
    "ground",
)

_NONLINEAR_NAMES = {
    "diode": "diode",
    "led": "LED",
    "npn": "transistor",
    "pnp": "transistor",
}

_NO_GROUND = "Add a ground part before a formula can be written."
_NO_FORMULA = (
    "This circuit has no single formula. A node may be floating, or "
    "voltage sources may form a loop."
)
_NOT_CONNECTED = "Not connected."
_SUPPLY_PIN = (
    "No s-domain formula at this supply pin. The ideal op-amp uses the "
    "inputs and the output."
)
_IDEAL_OPAMP = "Ideal op-amp: the two inputs are at the same voltage."


class _Nets:
    """Union-find over grid-point identifiers. A bridge is not joined."""

    def __init__(self):
        self._parent = {}

    def add(self, identifier):
        self._parent.setdefault(identifier, identifier)

    def find(self, identifier):
        self.add(identifier)
        parent = self._parent

        while parent[identifier] != identifier:
            parent[identifier] = parent[parent[identifier]]
            identifier = parent[identifier]

        return identifier

    def union(self, first, second):
        first_root = self.find(first)
        second_root = self.find(second)

        if first_root != second_root:
            self._parent[second_root] = first_root

    def known(self, identifier):
        return identifier in self._parent


def _exact(number):
    """
    Turn a parsed part value into an exact rational.

    :param number: Value from the part, such as 10000.0 or 1e-6.
    :type number: float
    :rtype: sympy.Expr
    """
    return sympy.nsimplify(number, rational=True, tolerance=1e-9)


def _pin_identifier(component, pin_name):
    """
    Return the grid-point identifier under one named pin.

    :rtype: str
    """
    for name, row_number, column_number in component.get_pin_positions():
        if name == pin_name:
            return ConnectionGrid.build_connection_point_identifier(
                row_number, column_number
            )

    raise ComponentError(
        f"{component.reference} has no pin {pin_name!r}."
    )


def _format_voltage(expression):
    """
    Return the user-facing formula, such as "V(s) = 5 V".

    :param expression: Solved node voltage.
    :type expression: sympy.Expr
    :rtype: str
    """
    simplified = sympy.simplify(sympy.together(expression))

    if simplified.free_symbols:
        return f"V(s) = {sympy.sstr(simplified)}"

    number = float(simplified)
    text = f"{number:.6f}".rstrip("0").rstrip(".")

    return f"V(s) = {text} V"


def _format_current(expression):
    """
    Return the user-facing current, such as "I = 0.01 A".

    :param expression: Solved part current.
    :type expression: sympy.Expr
    :rtype: str
    """
    simplified = sympy.simplify(sympy.together(expression))

    if simplified.free_symbols:
        return f"I = {sympy.sstr(simplified)} A"

    number = float(simplified)
    text = f"{number:.6f}".rstrip("0").rstrip(".")

    return f"I = {text} A"


def _validate_shunts(shunts):
    """
    Check probe loads before they are stamped.

    :param shunts: (point, "resistor" or "capacitor", value) tuples.
    :rtype: tuple
    :raises ComponentError: If a load is not a positive resistor or capacitor.
    """
    validated = []

    for shunt in shunts:
        if not isinstance(shunt, tuple) or len(shunt) != 3:
            raise ComponentError(
                "A probe load must be (point, kind, value), "
                f"not {shunt!r}."
            )

        identifier, kind, value = shunt

        if not isinstance(identifier, str) or identifier == "":
            raise ComponentError(
                f"A probe load needs a grid point, not {identifier!r}."
            )

        if kind not in ("resistor", "capacitor"):
            raise ComponentError(
                "A probe load must be a resistor or a capacitor, "
                f"not {kind!r}."
            )

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ComponentError(
                f"A probe load value must be a number, not {value!r}."
            )

        if value <= 0:
            raise ComponentError("A probe load must be greater than zero.")

        validated.append((identifier, kind, float(value)))

    return tuple(validated)


class NodeFormulas:
    """
    The s-domain voltage at every grid point of one circuit.

    :param components: Placed parts.
    :type components: iterable of Component
    :param wire_collection: Wires. A bridged point is not joined.
    :type wire_collection: WireCollection
    :param connection_grid: Grid whose net labels join same-named points.
        None means no labels.
    :type connection_grid: ConnectionGrid or None
    :param shunts: Loads from a point to ground. Each entry is
        ``(identifier, "resistor" or "capacitor", value)``.
    :type shunts: iterable of tuple
    """

    def __init__(self, components, wire_collection, connection_grid=None,
                 shunts=()):
        if not isinstance(wire_collection, WireCollection):
            raise ComponentError(
                "Expected a WireCollection, not "
                f"{type(wire_collection).__name__}."
            )

        if (connection_grid is not None and
                not isinstance(connection_grid, ConnectionGrid)):
            raise ComponentError(
                "Expected a ConnectionGrid, not "
                f"{type(connection_grid).__name__}."
            )

        self._components = []

        for component in components:
            if not isinstance(component, Component):
                raise ComponentError(
                    f"Expected a Component, not {component!r}."
                )

            self._components.append(component)

        self._wires = wire_collection
        self._grid = connection_grid
        self._shunts = _validate_shunts(shunts)
        self._nets = _Nets()
        self._current_by_reference = {}
        self._text_by_root = {}
        self._expression_by_root = {}
        self._supply_roots = set()
        self._ideal_opamp = False
        self._build()

    def text_at(self, identifier):
        """
        Return the formula shown for one grid point.

        :param identifier: Connection-point identifier.
        :type identifier: str
        :rtype: str
        """
        if not self._nets.known(identifier):
            return _NOT_CONNECTED

        root = self._nets.find(identifier)
        text = self._text_by_root.get(root)

        if text is None:
            if root in self._supply_roots:
                return _SUPPLY_PIN

            return _NOT_CONNECTED

        if self._ideal_opamp and text.startswith("V(s)"):
            return f"{text}\n{_IDEAL_OPAMP}"

        return text

    def expression_at(self, identifier):
        """
        Return the solved sympy voltage, or None when there is no formula.

        :param identifier: Connection-point identifier.
        :type identifier: str
        :rtype: sympy.Expr or None
        """
        if not self._nets.known(identifier):
            return None

        return self._expression_by_root.get(self._nets.find(identifier))

    def difference_text(self, first_identifier, second_identifier):
        """
        Return the voltage at the first point minus the voltage at the second.

        :param first_identifier: Plus point of a differential probe.
        :param second_identifier: Minus point, or None until it is chosen.
        :rtype: str
        """
        if not second_identifier:
            return "Click the other point for this differential probe."

        left = self.expression_at(first_identifier)
        right = self.expression_at(second_identifier)

        if left is None or right is None:
            for identifier in (first_identifier, second_identifier):
                text = self.text_at(identifier)

                if not text.startswith("V(s)"):
                    return text

            return _NOT_CONNECTED

        return _format_voltage(sympy.simplify(left - right))

    def current_text(self, component):
        """
        Return the current through one part.

        Positive current enters a resistor at pin 1 and leaves at pin 2.
        For a source it leaves the positive terminal. For an op-amp it
        leaves the output pin. For a current source it leaves the out pin.

        :param component: Part the probe sits on.
        :rtype: str
        """
        if component.kind in _NONLINEAR_NAMES:
            return _nonlinear_text([component])

        expression = self.current_expression(component)

        if expression is None:
            identifiers = component.get_pin_identifiers()

            if identifiers:
                return self.text_at(identifiers[0])

            return _NO_FORMULA

        return _format_current(expression)

    def current_expression(self, component):
        """
        Return the solved current through one part, or None.

        :rtype: sympy.Expr or None
        """
        if component.kind in _NONLINEAR_NAMES:
            return None

        stored = self._current_by_reference.get(component.reference)

        if stored is not None:
            return stored

        if component.kind not in (
                "resistor", "capacitor", "capacitor_polarized", "inductor"):
            return None

        first_name, second_name = _passive_pins(component.kind)
        first = self.expression_at(_pin_identifier(component, first_name))
        second = self.expression_at(_pin_identifier(component, second_name))

        if first is None or second is None:
            return None

        return sympy.simplify(
            (first - second) * _admittance(component.kind, component.value)
        )

    def _build(self):
        nonlinear = [
            component for component in self._components
            if component.kind in _NONLINEAR_NAMES
        ]
        grounds = [
            component for component in self._components
            if component.kind == "ground"
        ]

        for component in self._components:
            for identifier in component.get_pin_identifiers():
                self._nets.add(identifier)

        for wire in self._wires.get_wires():
            for first, second in itertools.pairwise(
                    wire.get_joined_identifiers()):
                self._nets.union(first, second)

        ground_identifiers = []

        for component in grounds:
            ground_identifiers.extend(component.get_pin_identifiers())

        for identifier in ground_identifiers[1:]:
            self._nets.union(ground_identifiers[0], identifier)

        self._union_named_nets()

        if nonlinear:
            text = _nonlinear_text(nonlinear)
            self._blame_every_part(text)
            return

        if not grounds:
            if self._components:
                self._blame_every_part(_NO_GROUND)

            return

        self._solve(self._nets.find(ground_identifiers[0]))

    def _union_named_nets(self):
        """
        Join every grid point that carries the same net label.

        ``Vcc`` and ``vcc`` are one name. A labeled point with no part and
        no wire is still part of that node, so a source on one Vcc point
        sets the voltage at the others.

        :returns: None
        """
        if self._grid is None:
            return

        identifiers_by_name = {}

        for point in self._grid.connection_points_by_identifier.values():
            if not point.net_label:
                continue

            identifiers_by_name.setdefault(
                point.net_label.casefold(), []
            ).append(point.identifier)

        for identifiers in identifiers_by_name.values():
            self._nets.add(identifiers[0])

            for identifier in identifiers[1:]:
                self._nets.union(identifiers[0], identifier)

    def _blame_every_part(self, text):
        for component in self._components:
            for identifier in component.get_pin_identifiers():
                self._text_by_root[self._nets.find(identifier)] = text

    def _solve(self, ground_root):
        stamped_roots = set()
        supply_identifiers = []
        equations = []
        unknowns = []
        voltage_of = {}
        currents = {}
        branch_symbols = []
        fixed_currents = {}
        self._current_by_reference = {}

        def voltage(root):
            if root == ground_root:
                return sympy.Integer(0)

            return voltage_of[root]

        def leave(root, amount):
            if root == ground_root or amount == 0:
                return

            currents[root] = currents.get(root, 0) + amount

        def touch(identifier):
            root = self._nets.find(identifier)
            stamped_roots.add(root)

            if root != ground_root and root not in voltage_of:
                voltage_of[root] = sympy.Symbol(f"v_{len(voltage_of)}")

            return root

        for component in self._components:
            kind = component.kind

            if kind in ("ground",):
                continue

            if kind in ("opamp_generic", "opamp_741"):
                self._ideal_opamp = True
                plus = touch(_pin_identifier(component, "in+"))
                minus = touch(_pin_identifier(component, "in-"))
                output = touch(_pin_identifier(component, "out"))
                current = sympy.Symbol(f"I_{component.reference}")
                unknowns.append(current)
                # The symbol is the current pushed out of the output pin.
                branch_symbols.append((component.reference, 1))
                leave(output, -current)
                equations.append(voltage(plus) - voltage(minus))

                for pin_name in ("V+", "V-"):
                    supply_identifiers.append(
                        _pin_identifier(component, pin_name)
                    )

                continue

            if kind == "dc_source":
                plus = touch(_pin_identifier(component, "plus"))
                minus = touch(_pin_identifier(component, "minus"))
                current = sympy.Symbol(f"I_{component.reference}")
                unknowns.append(current)
                # The symbol enters the source at plus. The probe reports
                # the current leaving the positive terminal, which is minus that.
                branch_symbols.append((component.reference, -1))
                leave(plus, current)
                leave(minus, -current)
                equations.append(
                    voltage(plus) - voltage(minus) - _exact(component.value)
                )
                continue

            if kind == "ac_source":
                plus = touch(_pin_identifier(component, "plus"))
                minus = touch(_pin_identifier(component, "minus"))
                current = sympy.Symbol(f"I_{component.reference}")
                unknowns.append(current)
                branch_symbols.append((component.reference, -1))
                leave(plus, current)
                leave(minus, -current)
                source = sympy.Symbol(component.reference)
                equations.append(
                    voltage(plus) - voltage(minus) - source
                )
                continue

            if kind == "current_source":
                outgoing = touch(_pin_identifier(component, "out"))
                incoming = touch(_pin_identifier(component, "in"))
                amps = _exact(component.value)
                fixed_currents[component.reference] = amps
                leave(outgoing, -amps)
                leave(incoming, amps)
                continue

            if kind in (
                    "resistor", "capacitor", "capacitor_polarized",
                    "inductor"):
                first = touch(_pin_identifier(component, _passive_pins(kind)[0]))
                second = touch(
                    _pin_identifier(component, _passive_pins(kind)[1])
                )
                admittance = _admittance(kind, component.value)
                leave(first, (voltage(first) - voltage(second)) * admittance)
                leave(second, (voltage(second) - voltage(first)) * admittance)

        for identifier, kind, value in self._shunts:
            root = touch(identifier)
            leave(root, voltage(root) * _admittance(kind, value))

        for identifier in supply_identifiers:
            root = self._nets.find(identifier)

            if root not in stamped_roots:
                self._supply_roots.add(root)

        ordered_roots = [
            root for root in voltage_of
            if root != ground_root
        ]
        unknowns = [voltage_of[root] for root in ordered_roots] + unknowns

        for root in ordered_roots:
            equations.insert(0, currents.get(root, 0))

        self._text_by_root[ground_root] = _format_voltage(sympy.Integer(0))
        self._expression_by_root[ground_root] = sympy.Integer(0)
        self._current_by_reference = dict(fixed_currents)

        if not ordered_roots and not unknowns:
            return

        try:
            matrix, constants = sympy.linear_eq_to_matrix(
                equations, unknowns
            )

            if matrix.rank() < len(unknowns):
                self._blame_stamped(stamped_roots, _NO_FORMULA)
                return

            solved = matrix.LUsolve(constants)
        except (ValueError, sympy.matrices.exceptions.NonInvertibleMatrixError):
            self._blame_stamped(stamped_roots, _NO_FORMULA)
            return

        for root, symbol in zip(ordered_roots, solved):
            expression = sympy.simplify(symbol)
            self._expression_by_root[root] = expression
            self._text_by_root[root] = _format_voltage(expression)

        self._current_by_reference = dict(fixed_currents)
        branch_values = list(solved[len(ordered_roots):])

        for (reference, sign), value in zip(branch_symbols, branch_values):
            self._current_by_reference[reference] = sympy.simplify(value * sign)

    def _blame_stamped(self, roots, text):
        for root in roots:
            if root not in self._text_by_root:
                self._text_by_root[root] = text


def _passive_pins(kind):
    if kind == "capacitor_polarized":
        return ("plus", "minus")

    return ("1", "2")


def _admittance(kind, value):
    exact = _exact(value)

    if kind == "resistor":
        return 1 / exact

    if kind in ("capacitor", "capacitor_polarized"):
        return _LAPLACE * exact

    return 1 / (_LAPLACE * exact)


def _nonlinear_text(components):
    component = components[0]
    kind_name = _NONLINEAR_NAMES[component.kind]
    extra = len(components) - 1

    if extra:
        return (
            f"{component.reference} is a {kind_name}, so there is no "
            f"s-domain formula for this circuit ({extra} more)."
        )

    return (
        f"{component.reference} is a {kind_name}, so there is no "
        "s-domain formula for this circuit."
    )


def build_node_formulas(components, wire_collection, connection_grid=None,
                         shunts=()):
    """
    Solve the s-domain voltage at each node of a circuit.

    :param components: Placed parts.
    :type components: iterable of Component
    :param wire_collection: Wires of the same circuit.
    :type wire_collection: WireCollection
    :param connection_grid: Grid whose net labels join same-named points.
    :type connection_grid: ConnectionGrid or None
    :param shunts: Loads from a point to ground, each
        ``(identifier, "resistor" or "capacitor", value)``.
    :type shunts: iterable of tuple
    :rtype: NodeFormulas
    """
    return NodeFormulas(
        components, wire_collection, connection_grid, shunts
    )
