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
"""

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
        "pins": [("1", -1, 0), ("2", 1, 0)],
        "value_kind": "positive",
        "default_value_text": "1k",
    },
    "capacitor": {
        "display_name": "Capacitor",
        "prefix": "C",
        "pins": [("1", -1, 0), ("2", 1, 0)],
        "value_kind": "positive",
        "default_value_text": "100n",
    },
    "capacitor_polarized": {
        "display_name": "Capacitor (polarized)",
        "prefix": "C",
        "pins": [("plus", -1, 0), ("minus", 1, 0)],
        "value_kind": "positive",
        "default_value_text": "10u",
    },
    "inductor": {
        "display_name": "Inductor",
        "prefix": "L",
        "pins": [("1", -1, 0), ("2", 1, 0)],
        "value_kind": "positive",
        "default_value_text": "10u",
    },
    "voltage_source": {
        "display_name": "Voltage source",
        "prefix": "V",
        "pins": [("plus", 0, -1), ("minus", 0, 1)],
        "value_kind": "any",
        "default_value_text": "5",
    },
    "current_source": {
        "display_name": "Current source",
        "prefix": "I",
        "pins": [("in", 0, 1), ("out", 0, -1)],
        "value_kind": "any",
        "default_value_text": "1m",
    },
    "diode": {
        "display_name": "Diode",
        "prefix": "D",
        "pins": [("anode", -1, 0), ("cathode", 1, 0)],
        "value_kind": "model",
        "default_value_text": "1N4148",
    },
    "led": {
        "display_name": "LED",
        "prefix": "D",
        "pins": [("anode", -1, 0), ("cathode", 1, 0)],
        "value_kind": "model",
        "default_value_text": "LED_RED",
    },
    "npn": {
        "display_name": "NPN transistor",
        "prefix": "Q",
        "pins": [("base", -1, 0), ("collector", 0, -1), ("emitter", 0, 1)],
        "value_kind": "model",
        "default_value_text": "2N3904",
    },
    "pnp": {
        "display_name": "PNP transistor",
        "prefix": "Q",
        "pins": [("base", -1, 0), ("emitter", 0, -1), ("collector", 0, 1)],
        "value_kind": "model",
        "default_value_text": "2N3906",
    },
    "ground": {
        "display_name": "Ground",
        "prefix": "GND",
        "pins": [("gnd", 0, 0)],
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


def get_component_definition(kind):
    """
    Return the definition dictionary for one component kind.

    :param kind: Component kind, for example "resistor".
    :type kind: str
    :returns: Definition from COMPONENT_DEFINITIONS.
    :rtype: dict
    :raises ComponentError: If the kind is not a known component kind.
    """
    if not isinstance(kind, str) or kind not in COMPONENT_DEFINITIONS:
        raise ComponentError(
            f"Unknown component kind {kind!r}. Known kinds: "
            f"{', '.join(COMPONENT_DEFINITIONS)}."
        )

    return COMPONENT_DEFINITIONS[kind]


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
    component_definition = get_component_definition(kind)
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
        component_definition = get_component_definition(kind)

        self.validate_reference(reference, component_definition)
        self.validate_anchor_number(row_number, "Row")
        self.validate_anchor_number(column_number, "Column")

        clean_text, value = validate_value_text(kind, value_text)

        self.kind = kind
        self.reference = reference
        self.value_text = clean_text
        self.value = value
        self.row_number = row_number
        self.column_number = column_number

        # The rotation property validates on every assignment.
        self.rotation = rotation

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
