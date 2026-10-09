"""
Schematic component definitions and placed-component model.

This module defines the standard part set (resistor, capacitors, inductor,
sources, diodes, transistors, and ground), their connection pins, and the
Component class that holds one placed part. It contains no PyQt5 imports so
the same objects can be used by the GUI label, the later SPICE netlist
builder, and the solver.

Pin offsets are measured in grid steps from the part's anchor grid point.
``dx`` is the column offset and ``dy`` is the row offset; a positive ``dy``
points down the screen, the same direction as Qt's y axis.

Two-pin parts span one grid step: the anchor is the first pin, the second
pin is on the neighbouring grid point, and the body sits halfway between
them. ``body_center_half_steps`` gives the body centre from the anchor in
half grid steps (so it stays a whole number that rotate_offset accepts):
(1, 0) is half a step to the right. Transistors keep their anchor at the
body centre with three pins around it; ground's single pin is its anchor.
"""

import copy
import re

from core.connection_grid import MAXIMUM_GRID_DIMENSION, ConnectionGrid
from core.exceptions import ComponentError
from core.units import parse_value

VALID_ROTATIONS = (0, 90, 180, 270)

# Value kinds: "positive" numbers (R, C, L), "any" number (sources),
# "model" names (diodes, LEDs, transistors), and "none" (ground).
VALID_VALUE_KINDS = ("positive", "any", "model", "none")

MAXIMUM_MODEL_NAME_LENGTH = 32

# SPICE model names are kept to plain ASCII so later netlists stay valid.
_MODEL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.\-]+")

COMPONENT_DEFINITIONS = {
    "resistor": {
        "display_name": "Resistor",
        "prefix": "R",
        "pins": [("1", 0, 0), ("2", 1, 0)],
        "body_center_half_steps": (1, 0),
        "value_kind": "positive",
        "default_value_text": "1k",
    },
    "capacitor": {
        "display_name": "Capacitor",
        "prefix": "C",
        "pins": [("1", 0, 0), ("2", 1, 0)],
        "body_center_half_steps": (1, 0),
        "value_kind": "positive",
        "default_value_text": "100n",
    },
    "capacitor_polarized": {
        "display_name": "Capacitor (polarized)",
        "prefix": "C",
        "pins": [("plus", 0, 0), ("minus", 1, 0)],
        "body_center_half_steps": (1, 0),
        "value_kind": "positive",
        "default_value_text": "10u",
    },
    "inductor": {
        "display_name": "Inductor",
        "prefix": "L",
        "pins": [("1", 0, 0), ("2", 1, 0)],
        "body_center_half_steps": (1, 0),
        "value_kind": "positive",
        "default_value_text": "10u",
    },
    "voltage_source": {
        "display_name": "Voltage source",
        "prefix": "V",
        "pins": [("plus", 0, 0), ("minus", 0, 1)],
        "body_center_half_steps": (0, 1),
        "value_kind": "any",
        "default_value_text": "5",
    },
    "current_source": {
        "display_name": "Current source",
        "prefix": "I",
        "pins": [("in", 0, 0), ("out", 0, 1)],
        "body_center_half_steps": (0, 1),
        "value_kind": "any",
        "default_value_text": "1m",
    },
    "diode": {
        "display_name": "Diode",
        "prefix": "D",
        "pins": [("anode", 0, 0), ("cathode", 1, 0)],
        "body_center_half_steps": (1, 0),
        "value_kind": "model",
        "default_value_text": "1N4148",
    },
    "led": {
        "display_name": "LED",
        "prefix": "D",
        "pins": [("anode", 0, 0), ("cathode", 1, 0)],
        "body_center_half_steps": (1, 0),
        "value_kind": "model",
        "default_value_text": "LED_RED",
    },
    "npn": {
        "display_name": "NPN transistor",
        "prefix": "Q",
        "pins": [("base", -1, 0), ("collector", 0, -1), ("emitter", 0, 1)],
        "body_center_half_steps": (0, 0),
        "value_kind": "model",
        "default_value_text": "2N3904",
    },
    "pnp": {
        "display_name": "PNP transistor",
        "prefix": "Q",
        "pins": [("base", -1, 0), ("emitter", 0, -1), ("collector", 0, 1)],
        "body_center_half_steps": (0, 0),
        "value_kind": "model",
        "default_value_text": "2N3906",
    },
    "ground": {
        "display_name": "Ground",
        "prefix": "GND",
        "pins": [("gnd", 0, 0)],
        "body_center_half_steps": (0, 0),
        "value_kind": "none",
        "default_value_text": "",
    },
}


def _is_plain_integer(candidate_value):
    """
    Return True for a real int, rejecting bool (which Python treats as int).

    :param candidate_value: Value to check.
    :type candidate_value: object
    :returns: Whether the value is a non-Boolean integer.
    :rtype: bool
    """
    return isinstance(candidate_value, int) and not isinstance(
        candidate_value, bool
    )


def _lookup_component_definition(kind):
    """
    Return the shared, read-only definition dictionary for one kind.

    Internal code uses this to avoid copying. Callers outside this module
    should use get_component_definition, which returns a private copy.

    :param kind: Component kind, for example "resistor".
    :type kind: str
    :returns: Definition from COMPONENT_DEFINITIONS (do not modify).
    :rtype: dict
    :raises ComponentError: If the kind is not a known component kind.
    """
    if not isinstance(kind, str) or kind not in COMPONENT_DEFINITIONS:
        raise ComponentError(
            f"Unknown component kind {kind!r}. Known kinds: "
            f"{', '.join(COMPONENT_DEFINITIONS)}."
        )

    return COMPONENT_DEFINITIONS[kind]


def get_component_definition(kind):
    """
    Return a copy of the definition dictionary for one component kind.

    The copy can be changed freely without affecting the shared
    COMPONENT_DEFINITIONS table.

    :param kind: Component kind, for example "resistor".
    :type kind: str
    :returns: Deep copy of the definition from COMPONENT_DEFINITIONS.
    :rtype: dict
    :raises ComponentError: If the kind is not a known component kind.
    """
    return copy.deepcopy(_lookup_component_definition(kind))


def validate_rotation(rotation):
    """
    Validate a rotation in degrees.

    :param rotation: Rotation in degrees, clockwise on screen.
    :type rotation: int
    :returns: The validated rotation.
    :rtype: int
    :raises ComponentError: If the rotation is not 0, 90, 180, or 270.
    """
    # Floats such as 90.0 and Booleans are rejected instead of coerced.
    if not _is_plain_integer(rotation) or rotation not in VALID_ROTATIONS:
        raise ComponentError(
            f"Rotation {rotation!r} is not allowed. Use one of "
            f"{', '.join(str(angle) for angle in VALID_ROTATIONS)} degrees."
        )

    return rotation


def rotate_offset(dx, dy, rotation):
    """
    Rotate a pin offset clockwise on screen (y points down).

    0: (dx, dy), 90: (-dy, dx), 180: (-dx, -dy), 270: (dy, -dx).

    :param dx: Column offset in grid steps.
    :type dx: int
    :param dy: Row offset in grid steps (positive is down).
    :type dy: int
    :param rotation: Rotation in degrees: 0, 90, 180, or 270.
    :type rotation: int
    :returns: Rotated (dx, dy) offset.
    :rtype: tuple
    :raises ComponentError: If an offset or the rotation is invalid.
    """
    if not _is_plain_integer(dx) or not _is_plain_integer(dy):
        raise ComponentError(
            f"Pin offsets must be whole grid steps, not ({dx!r}, {dy!r})."
        )

    validate_rotation(rotation)

    if rotation == 90:
        return (-dy, dx)

    if rotation == 180:
        return (-dx, -dy)

    if rotation == 270:
        return (dy, -dx)

    return (dx, dy)


def validate_value_text(kind, value_text):
    """
    Validate a user-entered value for one component kind.

    :param kind: Component kind, for example "resistor".
    :type kind: str
    :param value_text: User-entered value text.
    :type value_text: str
    :returns: (clean_text, value) where value is a float, or None for
        model-name parts and ground.
    :rtype: tuple
    :raises ComponentError: If the kind or the value is invalid.
    """
    component_definition = _lookup_component_definition(kind)
    value_kind = component_definition["value_kind"]
    display_name = component_definition["display_name"]

    # Ground has no value; any input is ignored, as the plan specifies.
    if value_kind == "none":
        return ("", None)

    if not isinstance(value_text, str):
        raise ComponentError(
            f"{display_name} value must be text, not {value_text!r}."
        )

    clean_text = value_text.strip()

    # Model-name parts (diodes, LEDs, transistors) store a SPICE model name.
    if value_kind == "model":
        if not clean_text:
            raise ComponentError(
                f"{display_name} needs a model name, for example "
                f"{component_definition['default_value_text']}."
            )

        if len(clean_text) > MAXIMUM_MODEL_NAME_LENGTH:
            raise ComponentError(
                f"{display_name} model name '{clean_text[:40]}' is longer "
                f"than {MAXIMUM_MODEL_NAME_LENGTH} characters."
            )

        if not _MODEL_NAME_PATTERN.fullmatch(clean_text):
            raise ComponentError(
                f"{display_name} model name '{clean_text}' may only use "
                "the letters A-Z, digits, '_', '.', and '-', with no spaces."
            )

        return (clean_text, None)

    # Numeric parts: parse_value raises ComponentError for bad text.
    numeric_value = parse_value(clean_text)

    if value_kind == "positive" and not numeric_value > 0:
        raise ComponentError(
            f"{display_name} value must be greater than zero."
        )

    return (clean_text, numeric_value)


class Component:
    """
    One placed schematic part.

    The GUI label, the later netlist builder, and the solver all read this
    same object, so the value is parsed once and stored here.

    :param kind: Component kind, a key of COMPONENT_DEFINITIONS.
    :type kind: str
    :param reference: Reference designator, for example "R1" or "GND1".
    :type reference: str
    :param value_text: User-entered value, for example "4k7" or "1N4148".
    :type value_text: str
    :param row_number: One-based grid row of the anchor point.
    :type row_number: int
    :param column_number: One-based grid column of the anchor point.
    :type column_number: int
    :param rotation: Rotation in degrees, clockwise on screen.
    :type rotation: int
    :raises ComponentError: If any argument is invalid.
    """

    def __init__(
            self,
            kind,
            reference,
            value_text,
            row_number,
            column_number,
            rotation=0):
        component_definition = _lookup_component_definition(kind)

        self.validate_reference(reference, component_definition)
        clean_text, value = validate_value_text(kind, value_text)

        # kind and reference are fixed for the life of the part; the
        # collection keys parts by reference and the prefix follows kind.
        self._kind = kind
        self._reference = reference
        self.value_text = clean_text
        self.value = value

        # These properties validate on every assignment, so a placed part
        # can never be moved or turned to an invalid position later.
        self.row_number = row_number
        self.column_number = column_number
        self.rotation = rotation

    @property
    def kind(self):
        """
        Component kind, for example "resistor". Read-only.

        :rtype: str
        """
        return self._kind

    @kind.setter
    def kind(self, unused_kind):
        raise ComponentError(
            f"The kind of {self._reference} cannot be changed. Delete the "
            "part and place a new one instead."
        )

    @property
    def reference(self):
        """
        Reference designator, for example "R1". Read-only.

        :rtype: str
        """
        return self._reference

    @reference.setter
    def reference(self, unused_reference):
        raise ComponentError(
            f"The reference of {self._reference} cannot be changed."
        )

    @property
    def row_number(self):
        """
        One-based grid row of the anchor point.

        :rtype: int
        """
        return self._row_number

    @row_number.setter
    def row_number(self, row_number):
        self.validate_anchor_number(row_number, "Row")
        self._row_number = row_number

    @property
    def column_number(self):
        """
        One-based grid column of the anchor point.

        :rtype: int
        """
        return self._column_number

    @column_number.setter
    def column_number(self, column_number):
        self.validate_anchor_number(column_number, "Column")
        self._column_number = column_number

    @property
    def rotation(self):
        """
        Rotation in degrees, clockwise on screen: 0, 90, 180, or 270.

        :rtype: int
        """
        return self._rotation

    @rotation.setter
    def rotation(self, rotation):
        self._rotation = validate_rotation(rotation)

    def set_value_text(self, value_text):
        """
        Validate and store a new value, keeping value_text and value in step.

        :param value_text: New user-entered value text.
        :type value_text: str
        :returns: None
        :raises ComponentError: If the value is invalid. The old value_text
            and value are then left unchanged.
        """
        # Validate first so a failure cannot leave a half-updated pair.
        clean_text, value = validate_value_text(self.kind, value_text)

        self.value_text = clean_text
        self.value = value

    @staticmethod
    def validate_reference(reference, component_definition):
        """
        Validate a reference designator such as "R1" for its kind.

        The reference must be the kind's prefix followed by a number from
        1 upward, because SPICE identifies device types by the first letter.

        :param reference: Reference designator to check.
        :type reference: str
        :param component_definition: Definition of the component kind.
        :type component_definition: dict
        :returns: None
        :raises ComponentError: If the reference is invalid.
        """
        prefix = component_definition["prefix"]

        if not isinstance(reference, str) or not re.fullmatch(
                re.escape(prefix) + r"[1-9][0-9]{0,5}", reference):
            raise ComponentError(
                f"Reference {reference!r} is not valid for a "
                f"{component_definition['display_name']}. Use '{prefix}' "
                f"followed by a number, for example {prefix}1."
            )

    @staticmethod
    def validate_anchor_number(grid_number, dimension_name):
        """
        Validate a one-based row or column number for the anchor point.

        :param grid_number: Row or column number to check.
        :type grid_number: int
        :param dimension_name: "Row" or "Column", used in the message.
        :type dimension_name: str
        :returns: None
        :raises ComponentError: If the number is not a valid grid index.
        """
        if (not _is_plain_integer(grid_number) or
                not 1 <= grid_number <= MAXIMUM_GRID_DIMENSION):
            raise ComponentError(
                f"{dimension_name} {grid_number!r} is not valid. Use a whole "
                f"number from 1 through {MAXIMUM_GRID_DIMENSION}."
            )

    def get_pin_offsets(self):
        """
        Return pin offsets after applying the component rotation.

        :returns: List of (pin_name, dx, dy).
        :rtype: list
        """
        pin_offsets = []

        for pin_name, dx, dy in COMPONENT_DEFINITIONS[self.kind]["pins"]:
            rotated_dx, rotated_dy = rotate_offset(dx, dy, self.rotation)
            pin_offsets.append((pin_name, rotated_dx, rotated_dy))

        return pin_offsets

    def get_pin_positions(self):
        """
        Return the grid row and column of every pin.

        :returns: List of (pin_name, row, column).
        :rtype: list
        """
        return [
            (pin_name, self.row_number + dy, self.column_number + dx)
            for pin_name, dx, dy in self.get_pin_offsets()
        ]

    def get_pin_identifiers(self):
        """
        Return the connection-point identifier under every pin.

        :returns: Identifiers such as "NODE_R04_C03", in pin order.
        :rtype: list
        """
        return [
            ConnectionGrid.build_connection_point_identifier(row, column)
            for unused_pin_name, row, column in self.get_pin_positions()
        ]

    def get_body_center_offset(self):
        """
        Return the body centre from the anchor, after rotation.

        :returns: (dx, dy) in grid steps; halves for two-pin parts, for
            example (0.5, 0) for a resistor at 0 deg.
        :rtype: tuple
        """
        half_dx, half_dy = COMPONENT_DEFINITIONS[self.kind][
            "body_center_half_steps"
        ]
        rotated_dx, rotated_dy = rotate_offset(half_dx, half_dy, self.rotation)

        return (rotated_dx / 2, rotated_dy / 2)

    def get_body_center_position(self):
        """
        Return the body centre as a (row, column) grid position.

        :returns: Row and column; a two-pin part's centre is halfway
            between two grid points, for example (2, 2.5).
        :rtype: tuple
        """
        dx, dy = self.get_body_center_offset()

        return (self.row_number + dy, self.column_number + dx)

    def pins_fit_grid(self, row_count, column_count):
        """
        Return whether every pin lies on a grid of the given size.

        :param row_count: Number of grid rows.
        :type row_count: int
        :param column_count: Number of grid columns.
        :type column_count: int
        :returns: True when all pins are inside rows 1..row_count and
            columns 1..column_count.
        :rtype: bool
        :raises ComponentError: If a grid size is not a whole number.
        """
        if (not _is_plain_integer(row_count) or
                not _is_plain_integer(column_count)):
            raise ComponentError(
                f"Grid size must be whole numbers, not "
                f"({row_count!r}, {column_count!r})."
            )

        return all(
            1 <= row <= row_count and 1 <= column <= column_count
            for unused_pin_name, row, column in self.get_pin_positions()
        )

    def label_text(self):
        """
        Return the text shown next to the symbol, for example "R1 4k7".

        :returns: Reference and value text, or "" for ground.
        :rtype: str
        """
        if COMPONENT_DEFINITIONS[self.kind]["value_kind"] == "none":
            return ""

        return f"{self.reference} {self.value_text}"


def _reference_sort_key(reference):
    """
    Sort key that orders references naturally: R2 before R10.

    :param reference: Reference designator such as "R10" or "GND1".
    :type reference: str
    :returns: (prefix, number) tuple.
    :rtype: tuple
    """
    prefix = reference.rstrip("0123456789")

    return (prefix, int(reference[len(prefix):]))


def _validate_connection_grid(connection_grid):
    """
    Confirm that a ConnectionGrid was supplied.

    :param connection_grid: Grid to check.
    :type connection_grid: ConnectionGrid
    :returns: None
    :raises ComponentError: If the argument is not a ConnectionGrid.
    """
    if not isinstance(connection_grid, ConnectionGrid):
        raise ComponentError(
            f"Expected a ConnectionGrid, not {type(connection_grid).__name__}."
        )


def _get_pin_grid_points(component):
    """
    Return the set of (row, column) grid points under a part's pins.

    :param component: Part to inspect.
    :type component: Component
    :returns: Grid points, without pin names.
    :rtype: set
    """
    return {
        (row_number, column_number)
        for _pin_name, row_number, column_number in
        component.get_pin_positions()
    }


class ComponentCollection:
    """
    All placed components of one project, keyed by reference designator.

    The collection assigns references, refuses placements and rotations
    that would put a pin outside the grid or hide another part (the same
    pin points, any kind, or the same body centre), and removes parts that
    no longer fit after the grid shrinks. Parts may still share single
    pins: that is how they connect.
    """

    def __init__(self):
        self.components_by_reference = {}

    def next_reference(self, kind):
        """
        Return the lowest unused reference for a kind, such as "R1".

        Diodes and LEDs share the "D" prefix, so they share numbering.

        :param kind: Component kind.
        :type kind: str
        :returns: Unused reference designator.
        :rtype: str
        :raises ComponentError: If the kind is unknown.
        """
        prefix = _lookup_component_definition(kind)["prefix"]
        reference_number = 1

        while f"{prefix}{reference_number}" in self.components_by_reference:
            reference_number += 1

        return f"{prefix}{reference_number}"

    def add_component(
            self,
            kind,
            row_number,
            column_number,
            value_text,
            connection_grid,
            rotation=0):
        """
        Create, validate, and store a new component.

        :param kind: Component kind.
        :type kind: str
        :param row_number: One-based anchor row.
        :type row_number: int
        :param column_number: One-based anchor column.
        :type column_number: int
        :param value_text: Value text; empty text means the kind's default.
        :type value_text: str
        :param connection_grid: Grid the part must fit on.
        :type connection_grid: ConnectionGrid
        :param rotation: Rotation in degrees.
        :type rotation: int
        :returns: The new component.
        :rtype: Component
        :raises ComponentError: If any argument is invalid or a pin would
            fall outside the grid.
        """
        _validate_connection_grid(connection_grid)
        component_definition = _lookup_component_definition(kind)

        # Empty text means "use the default", for example "1k".
        if isinstance(value_text, str) and not value_text.strip():
            value_text = component_definition["default_value_text"]

        component = Component(
            kind,
            self.next_reference(kind),
            value_text,
            row_number,
            column_number,
            rotation
        )

        self.ensure_pins_fit_grid(component, connection_grid)
        self.ensure_no_overlap(component)

        self.components_by_reference[component.reference] = component

        return component

    def find_component_with_same_pins(self, component):
        """
        Return a stored part whose pins sit on exactly the same grid points.

        Any kind counts, and the pin order does not matter: a resistor
        from R2 C2 to R2 C3 and a capacitor from R2 C3 to R2 C2 cover the
        same two points. Their bodies would be drawn on top of each other
        and the lower part would be hidden. Parts that share only some
        pins are fine; that is how parts connect.

        :param component: Part to compare; it is skipped if it is stored.
        :type component: Component
        :returns: The first such part by reference, or None.
        :rtype: Component or None
        """
        grid_points = _get_pin_grid_points(component)

        for existing_component in self.get_components():
            if existing_component is component:
                continue

            if _get_pin_grid_points(existing_component) == grid_points:
                return existing_component

        return None

    def find_component_with_body_center(self, component):
        """
        Return a stored part whose body centre is this part's body centre.

        Two-pin bodies sit halfway between their pins, so for them this
        only repeats the pin check. It still matters for transistors (body
        centre on a grid point between three pins) and ground: two of them
        on one centre would overlap even with different pins.

        :param component: Part to compare; it is skipped if it is stored.
        :type component: Component
        :returns: The first such part by reference, or None.
        :rtype: Component or None
        """
        body_center = component.get_body_center_position()

        for existing_component in self.get_components():
            if existing_component is component:
                continue

            if existing_component.get_body_center_position() == body_center:
                return existing_component

        return None

    def ensure_no_overlap(self, component):
        """
        Raise a clear error when a part would hide another one.

        :param component: Part being placed, rotated or moved.
        :type component: Component
        :returns: None
        :raises ComponentError: If another part has the same pin points,
            or the same body centre.
        """
        existing_component = self.find_component_with_same_pins(component)

        if existing_component is not None:
            existing_display_name = COMPONENT_DEFINITIONS[
                existing_component.kind
            ]["display_name"]
            point_text = ", ".join(
                ConnectionGrid.build_connection_point_identifier(row, column)
                for row, column in sorted(
                    _get_pin_grid_points(existing_component)
                )
            )
            raise ComponentError(
                f"{existing_component.reference} ({existing_display_name}) "
                f"already connects exactly these grid points: {point_text}. "
                "Pick other grid points or another rotation, or select "
                f"{existing_component.reference} to edit it."
            )

        existing_component = self.find_component_with_body_center(component)

        if existing_component is not None:
            existing_display_name = COMPONENT_DEFINITIONS[
                existing_component.kind
            ]["display_name"]
            center_row, center_column = (
                component.get_body_center_position()
            )
            raise ComponentError(
                f"{existing_component.reference} ({existing_display_name}) "
                f"already has its centre at row {center_row:g}, column "
                f"{center_column:g}. Pick another grid point, or select "
                f"{existing_component.reference} to edit it."
            )

    @staticmethod
    def ensure_pins_fit_grid(component, connection_grid):
        """
        Raise a clear error when a component has a pin off the grid.

        :param component: Component to check.
        :type component: Component
        :param connection_grid: Grid the part must fit on.
        :type connection_grid: ConnectionGrid
        :returns: None
        :raises ComponentError: If component is not a Component,
            connection_grid is not a ConnectionGrid, or any pin lies
            outside the grid.
        """
        # Check the argument types first so callers always get a
        # ComponentError, never an AttributeError.
        if not isinstance(component, Component):
            raise ComponentError(
                f"Expected a Component, not {type(component).__name__}."
            )

        _validate_connection_grid(connection_grid)

        if component.pins_fit_grid(
                connection_grid.row_count,
                connection_grid.column_count):
            return

        raise ComponentError(
            f"{component.reference} does not fit at row "
            f"{component.row_number}, column {component.column_number}: a "
            f"pin would fall outside the {connection_grid.row_count} x "
            f"{connection_grid.column_count} grid. Choose a point further "
            "inside the grid."
        )

    def get_component(self, reference):
        """
        Return a component by reference designator.

        :param reference: Reference such as "R1".
        :type reference: str
        :returns: The component.
        :rtype: Component
        :raises ComponentError: If no component has that reference.
        """
        if (not isinstance(reference, str) or
                reference not in self.components_by_reference):
            raise ComponentError(
                f"There is no part called {reference!r}."
            )

        return self.components_by_reference[reference]

    def get_components(self):
        """
        Return all components ordered by reference (R2 before R10).

        :returns: Components sorted by reference.
        :rtype: list
        """
        return [
            self.components_by_reference[reference]
            for reference in sorted(
                self.components_by_reference,
                key=_reference_sort_key
            )
        ]

    def rotate_component(self, reference, connection_grid):
        """
        Rotate a component 90 degrees clockwise if it still fits the grid.

        :param reference: Reference of the part to rotate.
        :type reference: str
        :param connection_grid: Grid the part must fit on.
        :type connection_grid: ConnectionGrid
        :returns: The new rotation in degrees.
        :rtype: int
        :raises ComponentError: If the part is unknown, a rotated pin
            would leave the grid, or the turn would put it on top of a
            part with the same pin points or body centre. The old
            rotation is then kept.
        """
        _validate_connection_grid(connection_grid)
        component = self.get_component(reference)

        old_rotation = component.rotation
        component.rotation = (old_rotation + 90) % 360

        try:
            self.ensure_pins_fit_grid(component, connection_grid)
        except ComponentError:
            # Undo the turn so the part stays exactly where it was.
            component.rotation = old_rotation
            raise ComponentError(
                f"{reference} cannot be rotated here: a pin would fall "
                f"outside the {connection_grid.row_count} x "
                f"{connection_grid.column_count} grid. Move it further "
                "inside the grid first."
            ) from None

        try:
            self.ensure_no_overlap(component)
        except ComponentError as error:
            component.rotation = old_rotation
            raise ComponentError(
                f"{reference} cannot be rotated to {(old_rotation + 90) % 360} "
                f"deg: {error}"
            ) from None

        return component.rotation

    def set_component_value(self, reference, value_text):
        """
        Change a component's value.

        :param reference: Reference of the part.
        :type reference: str
        :param value_text: New value text.
        :type value_text: str
        :returns: The updated component.
        :rtype: Component
        :raises ComponentError: If the part is unknown or the value is
            invalid. The old value is then kept.
        """
        component = self.get_component(reference)
        component.set_value_text(value_text)

        return component

    def remove_component(self, reference):
        """
        Remove a component.

        :param reference: Reference of the part to remove.
        :type reference: str
        :returns: None
        :raises ComponentError: If the part is unknown.
        """
        self.get_component(reference)
        del self.components_by_reference[reference]

    def remove_components_outside_grid(self, connection_grid):
        """
        Remove every component with a pin outside the grid.

        Used after the grid shrinks, like signal pickoffs in
        ConnectionGrid.configure.

        :param connection_grid: Grid after resizing.
        :type connection_grid: ConnectionGrid
        :returns: References of the removed parts, sorted (R2 before R10).
        :rtype: list
        """
        _validate_connection_grid(connection_grid)

        removed_references = [
            component.reference
            for component in self.get_components()
            if not component.pins_fit_grid(
                connection_grid.row_count,
                connection_grid.column_count
            )
        ]

        for reference in removed_references:
            del self.components_by_reference[reference]

        return removed_references
