"""
Schematic component definitions and placed-component model.

This module defines the standard part set (resistor, capacitors, inductor,
DC and AC voltage sources, a DC current source, diodes, transistors,
MOSFETs, a switch, a potentiometer, a transformer, op-amps, a comparator,
logic gates, a few small amplifier blocks, a 555 timer, a voltage
regulator and ground), their connection pins, and the Component class
that holds one placed part. It contains no PyQt5 imports so the same
objects can be used by the GUI label, the later SPICE netlist builder,
and the solver.

Pin offsets are measured in grid steps from the part's anchor grid point.
``dx`` is the column offset and ``dy`` is the row offset; a positive ``dy``
points down the screen, the same direction as Qt's y axis.

Two-pin parts span one grid step: the anchor is the first pin, the second
pin is on the neighbouring grid point, and the body sits halfway between
them. ``body_center_half_steps`` gives the body centre from the anchor in
half grid steps (so it stays a whole number that rotate_offset accepts):
(1, 0) is half a step to the right. Transistors keep their anchor at the
body centre with three pins around it; ground's single pin is its anchor.
Op-amps, the comparator and the logic gates are centred on their anchor
and point right at rotation 0. An op-amp has in- at (-1, -1) and in+ at
(-1, 1) on the left, out at (1, 0), V+ above and V- below. A two-input
gate uses that same footprint with A, B, Y, VCC and GND. A NOT gate, a
buffer gate and the amplifier blocks have one input at (-1, 0). Op-amps,
the comparator and the gates use the SPICE prefix X; the amplifier
blocks use A. The subcircuit text lives in core.subcircuit_models.

Besides the main value, a kind may define extra numeric ``parameters``,
for example the AC source's frequency. Each has a name, a unit, a value
kind and a default, and ``shown_in_panel`` says whether the GUI offers it
(the AC source's offset and phase are kept for the later SPICE SIN source
but have no field yet). ``value_unit`` is appended to the value in the
label ("V1 9V"), and ``value_label`` names the value field in the panel.

``covered_half_steps`` lists, in the same half-step units, the points a
body covers that are not pins: a two-pin body covers its centre; a
transistor covers its anchor and the half points toward its three pins;
ground's bars cover the half point below its pin. Two parts may share pins
(that is how they connect), but a part is refused when its covered points
meet another part's covered points or pins, or its pins meet another
part's covered points: one symbol would be drawn over the other.
"""

import copy
import re

from core.connection_grid import MAXIMUM_GRID_DIMENSION, ConnectionGrid
from core.exceptions import ComponentError
from core.units import parse_value

VALID_ROTATIONS = (0, 90, 180, 270)

# Value kinds: "positive" numbers (R, C, L), "any" number (sources),
# "model" names (diodes, LEDs, transistors), and "none" (ground). Settings
# (parameters) may also be a "choice" from a fixed list (LED color).
VALID_VALUE_KINDS = ("positive", "any", "model", "none")

MAXIMUM_MODEL_NAME_LENGTH = 32

# LED colors (Billie, Oct 9) and the default SPICE model of each. When an
# LED's color changes and its model is still the old color's default, the
# model follows the color; a model the user typed is kept.
LED_COLORS = ("red", "green", "blue", "yellow", "white", "orange")
LED_MODEL_BY_COLOR = {color: f"LED_{color.upper()}" for color in LED_COLORS}
_MODEL_MAPS = {"LED_MODEL_BY_COLOR": LED_MODEL_BY_COLOR}

# Points inside an op-amp triangle (left edge x = -0.6, apex x = 0.75, half
# height 1.2), in half steps: the anchor, the half points toward out, V+,
# V- and the left side, and the half points beside the two inputs. A part
# drawn on any of them would be hidden by the triangle.
OPAMP_COVERED_HALF_STEPS = [
    (0, 0), (-1, 0), (1, 0), (0, -1), (0, 1),
    (-1, -1), (-1, 1), (-1, -2), (-1, 2),
]

_OPAMP_PINS = [
    ("in+", -1, 1), ("in-", -1, -1), ("out", 1, 0),
    ("V+", 0, -1), ("V-", 0, 1),
]
_GATE_PINS = [
    ("A", -1, -1), ("B", -1, 1), ("Y", 1, 0),
    ("VCC", 0, -1), ("GND", 0, 1),
]
_SINGLE_INPUT_PINS = [
    ("A", -1, 0), ("Y", 1, 0), ("VCC", 0, -1), ("GND", 0, 1),
]
_AMP_PINS = [
    ("in", -1, 0), ("out", 1, 0), ("V+", 0, -1), ("V-", 0, 1),
]
# 555, notch at the top: pin 1 (GND) is the upper left and the pins
# number down the left side, then up the right. The four corner pins
# sit two rows from the anchor so the label can use the right side.
_TIMER_PINS = [
    ("GND", -1, -2), ("TRIG", -1, -1), ("OUT", -1, 1), ("RESET", -1, 2),
    ("CONT", 1, 2), ("THRES", 1, 1), ("DISCH", 1, -1), ("VCC", 1, -2),
]
_TIMER_COVERED = [
    (0, 0),
    (-1, 0), (1, 0), (0, -1), (0, 1),
    (-1, -1), (-1, 1), (1, -1), (1, 1),
    (0, -2), (0, 2),
    (-1, -2), (-1, 2), (1, -2), (1, 2),
]
_REGULATOR_PINS = [("in", -1, 0), ("gnd", 0, 1), ("out", 1, 0)]
_REGULATOR_COVERED = [(0, 0), (-1, 0), (1, 0), (0, 1)]
_MOSFET_COVERED = [(0, 0), (-1, 0), (0, -1), (0, 1)]
_POT_COVERED = [(1, 0), (2, 0), (3, 0), (2, 1)]
_TRANSFORMER_COVERED = [(1, 1), (0, 1), (2, 1), (1, 0), (1, 2)]
_SUPPLY_PIN_NAMES = ("V+", "V-", "VCC", "GND")
SWITCH_STATES = ("open", "closed")

# SPICE model names are kept to plain ASCII so later netlists stay valid.
_MODEL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.\-]+")


def _integrated(display_name, prefix, pins, default_value, **extra):
    """
    One multi-pin part centred on its anchor.

    The body covers the same half-steps as an op-amp, so two of these
    symbols cannot be drawn on top of each other. Supply pins are left
    out of the label placement.

    :returns: Definition dictionary for COMPONENT_DEFINITIONS.
    :rtype: dict
    """
    definition = {
        "display_name": display_name,
        "prefix": prefix,
        "pins": [tuple(pin) for pin in pins],
        "body_center_half_steps": (0, 0),
        "covered_half_steps": OPAMP_COVERED_HALF_STEPS,
        "label_ignores_pins": tuple(
            name for name, _dx, _dy in pins if name in _SUPPLY_PIN_NAMES
        ),
        "value_kind": "model",
        "default_value_text": default_value,
    }
    definition.update(extra)

    return definition


COMPONENT_DEFINITIONS = {
    "resistor": {
        "display_name": "Resistor",
        "prefix": "R",
        "pins": [("1", 0, 0), ("2", 1, 0)],
        "body_center_half_steps": (1, 0),
        "covered_half_steps": [(1, 0)],
        "value_kind": "positive",
        "default_value_text": "1k",
    },
    "capacitor": {
        "display_name": "Capacitor",
        "prefix": "C",
        "pins": [("1", 0, 0), ("2", 1, 0)],
        "body_center_half_steps": (1, 0),
        "covered_half_steps": [(1, 0)],
        "value_kind": "positive",
        "default_value_text": "100n",
    },
    "capacitor_polarized": {
        "display_name": "Capacitor (polarized)",
        "prefix": "C",
        "pins": [("plus", 0, 0), ("minus", 1, 0)],
        "body_center_half_steps": (1, 0),
        "covered_half_steps": [(1, 0)],
        "value_kind": "positive",
        "default_value_text": "10u",
    },
    "inductor": {
        "display_name": "Inductor",
        "prefix": "L",
        "pins": [("1", 0, 0), ("2", 1, 0)],
        "body_center_half_steps": (1, 0),
        "covered_half_steps": [(1, 0)],
        "value_kind": "positive",
        "default_value_text": "10u",
    },
    "dc_source": {
        "display_name": "DC voltage source",
        "prefix": "V",
        "pins": [("plus", 0, 0), ("minus", 0, 1)],
        "body_center_half_steps": (0, 1),
        "covered_half_steps": [(0, 1)],
        "value_kind": "any",
        "default_value_text": "5",
        "value_label": "Voltage",
        "value_unit": "V",
    },
    "ac_source": {
        "display_name": "AC voltage source",
        "prefix": "V",
        "pins": [("plus", 0, 0), ("minus", 0, 1)],
        "body_center_half_steps": (0, 1),
        "covered_half_steps": [(0, 1)],
        "value_kind": "any",
        "default_value_text": "1",
        "value_label": "Peak amplitude",
        "value_unit": "V",
        # Sine source: amplitude is the main value. Offset and phase are
        # ready for the SPICE SIN(offset amplitude frequency 0 0 phase)
        # source but are not shown in the panel yet.
        "parameters": (
            {
                "name": "frequency",
                "display_name": "Frequency",
                "unit": "Hz",
                "value_kind": "positive",
                "default_value_text": "1k",
                "shown_in_panel": True,
            },
            {
                "name": "offset",
                "display_name": "Offset",
                "unit": "V",
                "value_kind": "any",
                "default_value_text": "0",
                "shown_in_panel": False,
            },
            {
                "name": "phase",
                "display_name": "Phase",
                "unit": "deg",
                "value_kind": "any",
                "default_value_text": "0",
                "shown_in_panel": False,
            },
        ),
    },
    "current_source": {
        # SPICE "I1 in out <amps>": the source pushes its current out of
        # the "out" pin (where the arrow points) into the circuit and takes
        # it back at "in". The arrow points up at rotation 0.
        "display_name": "Current source",
        "prefix": "I",
        "pins": [("out", 0, 0), ("in", 0, 1)],
        "body_center_half_steps": (0, 1),
        "covered_half_steps": [(0, 1)],
        "value_kind": "any",
        "default_value_text": "1m",
        "value_label": "Current",
        "value_unit": "A",
    },
    "diode": {
        "display_name": "Diode",
        "prefix": "D",
        "pins": [("anode", 0, 0), ("cathode", 1, 0)],
        "body_center_half_steps": (1, 0),
        "covered_half_steps": [(1, 0)],
        "value_kind": "model",
        "default_value_text": "1N4148",
    },
    "led": {
        "display_name": "LED",
        "prefix": "D",
        "pins": [("anode", 0, 0), ("cathode", 1, 0)],
        "body_center_half_steps": (1, 0),
        "covered_half_steps": [(1, 0)],
        "value_kind": "model",
        "default_value_text": "LED_RED",
        # The color is not written to SPICE. It picks the default model
        # (LED_MODEL_BY_COLOR) and the GUI's lit color.
        "parameters": (
            {
                "name": "color",
                "display_name": "Color",
                "unit": "",
                "value_kind": "choice",
                "choices": LED_COLORS,
                "default_value_text": "red",
                "shown_in_panel": True,
                "shown_in_label": False,
            },
        ),
        "model_follows_choice": ("color", "LED_MODEL_BY_COLOR"),
    },
    "npn": {
        "display_name": "NPN transistor",
        "prefix": "Q",
        "pins": [("base", -1, 0), ("collector", 0, -1), ("emitter", 0, 1)],
        "body_center_half_steps": (0, 0),
        "covered_half_steps": [(0, 0), (-1, 0), (0, -1), (0, 1)],
        "value_kind": "model",
        "default_value_text": "2N3904",
    },
    "pnp": {
        "display_name": "PNP transistor",
        "prefix": "Q",
        "pins": [("base", -1, 0), ("emitter", 0, -1), ("collector", 0, 1)],
        "body_center_half_steps": (0, 0),
        "covered_half_steps": [(0, 0), (-1, 0), (0, -1), (0, 1)],
        "value_kind": "model",
        "default_value_text": "2N3906",
    },
    "nmos": {
        "display_name": "NMOS",
        "prefix": "M",
        "pins": [("gate", -1, 0), ("drain", 0, -1), ("source", 0, 1)],
        "body_center_half_steps": (0, 0),
        "covered_half_steps": list(_MOSFET_COVERED),
        "value_kind": "model",
        "default_value_text": "2N7000",
        "nonlinear_name": "MOSFET",
    },
    "pmos": {
        "display_name": "PMOS",
        "prefix": "M",
        "pins": [("gate", -1, 0), ("source", 0, -1), ("drain", 0, 1)],
        "body_center_half_steps": (0, 0),
        "covered_half_steps": list(_MOSFET_COVERED),
        "value_kind": "model",
        "default_value_text": "BS250",
        "nonlinear_name": "MOSFET",
    },
    "opamp_generic": _integrated(
        "Op-amp (generic)", "X", _OPAMP_PINS, "OPAMP", formula="ideal_opamp"
    ),
    "opamp_741": _integrated(
        "Op-amp (741)", "X", _OPAMP_PINS, "LM741", formula="ideal_opamp"
    ),
    "opamp_lm358": _integrated(
        "Op-amp (LM358)", "X", _OPAMP_PINS, "LM358", formula="ideal_opamp"
    ),
    "opamp_tl072": _integrated(
        "Op-amp (TL072)", "X", _OPAMP_PINS, "TL072", formula="ideal_opamp"
    ),
    "opamp_ne5532": _integrated(
        "Op-amp (NE5532)", "X", _OPAMP_PINS, "NE5532", formula="ideal_opamp"
    ),
    "comparator": _integrated(
        "Comparator", "X", _OPAMP_PINS, "COMP", nonlinear_name="comparator"
    ),
    "gate_not": _integrated(
        "NOT gate", "X", _SINGLE_INPUT_PINS, "NOT",
        nonlinear_name="NOT gate"
    ),
    "gate_buffer": _integrated(
        "Buffer gate", "X", _SINGLE_INPUT_PINS, "BUF",
        nonlinear_name="buffer gate"
    ),
    "gate_and": _integrated(
        "AND gate", "X", _GATE_PINS, "AND2",
        nonlinear_name="two-input AND gate"
    ),
    "gate_or": _integrated(
        "OR gate", "X", _GATE_PINS, "OR2",
        nonlinear_name="two-input OR gate"
    ),
    "gate_nand": _integrated(
        "NAND gate", "X", _GATE_PINS, "NAND2",
        nonlinear_name="two-input NAND gate"
    ),
    "gate_nor": _integrated(
        "NOR gate", "X", _GATE_PINS, "NOR2",
        nonlinear_name="two-input NOR gate"
    ),
    "gate_xor": _integrated(
        "XOR gate", "X", _GATE_PINS, "XOR2",
        nonlinear_name="two-input XOR gate"
    ),
    "follower": _integrated(
        "Voltage follower", "A", _AMP_PINS, "",
        value_kind="none", label_style="reference", formula="follower"
    ),
    "inverting_amp": _integrated(
        "Inverting amplifier", "A", _AMP_PINS, "10",
        value_kind="positive", value_label="Gain",
        label_style="signed_gain", gain_sign="-", formula="inverting"
    ),
    "noninverting_amp": _integrated(
        "Non-inverting amplifier", "A", _AMP_PINS, "2",
        value_kind="positive", value_label="Gain", minimum_value=1,
        label_style="signed_gain", gain_sign="", formula="noninverting"
    ),
    "switch": {
        # Drawn open. Closed is a perfect short; open carries no current.
        # The picture does not change with the state.
        "display_name": "Switch",
        "prefix": "S",
        "pins": [("1", 0, 0), ("2", 1, 0)],
        "body_center_half_steps": (1, 0),
        "covered_half_steps": [(1, 0)],
        "value_kind": "none",
        "default_value_text": "",
        "formula": "switch",
        "parameters": (
            {
                "name": "state",
                "display_name": "State",
                "unit": "",
                "value_kind": "choice",
                "choices": SWITCH_STATES,
                "default_value_text": "open",
                "shown_in_panel": True,
                "shown_in_label": True,
            },
        ),
    },
    "potentiometer": {
        # Three pins so the wiper sits on a grid point. The element spans
        # two steps: pin 1, then pin 2, with the wiper one row below the
        # middle. Position 0 puts the wiper on pin 2; position 1 puts it
        # on pin 1; 0.5 splits the resistance in half.
        "display_name": "Potentiometer",
        "prefix": "RV",
        "pins": [("1", 0, 0), ("2", 2, 0), ("wiper", 1, 1)],
        "body_center_half_steps": (2, 0),
        "covered_half_steps": list(_POT_COVERED),
        "value_kind": "positive",
        "default_value_text": "10k",
        "value_label": "Resistance",
        "formula": "potentiometer",
        "parameters": (
            {
                "name": "position",
                "display_name": "Position",
                "unit": "",
                "value_kind": "any",
                "default_value_text": "0.5",
                "minimum_value": 0,
                "maximum_value": 1,
                "shown_in_panel": True,
                "shown_in_label": True,
            },
        ),
    },
    "transformer": {
        # Ideal transformer. The value is Ns/Np. Dots are on p1 and s1.
        "display_name": "Transformer",
        "prefix": "T",
        "pins": [("p1", 0, 0), ("p2", 0, 1), ("s1", 1, 0), ("s2", 1, 1)],
        "body_center_half_steps": (1, 1),
        "covered_half_steps": list(_TRANSFORMER_COVERED),
        "value_kind": "positive",
        "default_value_text": "1",
        "value_label": "Turns",
        "formula": "transformer",
    },
    "timer_555": _integrated(
        "555 timer", "X", _TIMER_PINS, "NE555",
        nonlinear_name="555 timer",
        covered_half_steps=list(_TIMER_COVERED),
        label_ignores_pins=("GND", "RESET", "CONT", "VCC"),
    ),
    "voltage_regulator": _integrated(
        "Voltage regulator", "U", _REGULATOR_PINS, "5",
        value_kind="positive", value_label="Voltage", value_unit="V",
        formula="regulator",
        covered_half_steps=list(_REGULATOR_COVERED),
        label_ignores_pins=(),
    ),
    "ground": {
        "display_name": "Ground",
        "prefix": "GND",
        "pins": [("gnd", 0, 0)],
        "body_center_half_steps": (0, 0),
        "covered_half_steps": [(0, 1)],
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

        # Op-amps (prefix X) must name a bundled subcircuit, and the one
        # that matches their kind; checked here so a bad name is refused
        # when it is typed, not at netlist time (QC #16).
        if component_definition["prefix"] == "X":
            # Imported here to keep core.components importable on its own.
            from core.subcircuit_models import (
                DEFAULT_SUBCIRCUIT_BY_KIND,
                get_subcircuit_model_name,
            )

            clean_text = get_subcircuit_model_name(clean_text)
            expected_name = DEFAULT_SUBCIRCUIT_BY_KIND[kind]

            if clean_text != expected_name:
                other_kind = next(
                    other for other, name in DEFAULT_SUBCIRCUIT_BY_KIND.items()
                    if name == clean_text
                )
                other_display_name = COMPONENT_DEFINITIONS[other_kind][
                    "display_name"
                ]
                raise ComponentError(
                    f"{display_name} uses model {expected_name}; for the "
                    f"{clean_text} choose the {other_display_name} part."
                )

        return (clean_text, None)

    # Numeric parts: parse_value raises ComponentError for bad text.
    numeric_value = parse_value(clean_text)

    if value_kind == "positive" and not numeric_value > 0:
        raise ComponentError(
            f"{display_name} value must be greater than zero."
        )

    minimum_value = component_definition.get("minimum_value")

    if minimum_value is not None and numeric_value < minimum_value:
        raise ComponentError(
            f"{display_name} gain must be at least {minimum_value}."
        )

    return (clean_text, numeric_value)


def get_parameter_definitions(kind):
    """
    Return the extra parameter definitions of a kind, in display order.

    :param kind: Component kind.
    :type kind: str
    :returns: Tuple of parameter dictionaries (shared; do not modify);
        empty for kinds with only a main value.
    :rtype: tuple
    :raises ComponentError: If the kind is unknown.
    """
    return _lookup_component_definition(kind).get("parameters", ())


def get_panel_parameter_definitions(kind):
    """
    Return the parameters of a kind that the GUI panel shows.

    :param kind: Component kind.
    :type kind: str
    :returns: Tuple of parameter dictionaries with shown_in_panel True.
    :rtype: tuple
    :raises ComponentError: If the kind is unknown.
    """
    return tuple(
        parameter for parameter in get_parameter_definitions(kind)
        if parameter["shown_in_panel"]
    )


def validate_parameter_texts(kind, parameter_texts, current_texts=None):
    """
    Validate extra parameter values (for example an AC source frequency).

    Missing names keep current_texts, or the defaults when there are none.

    :param kind: Component kind.
    :type kind: str
    :param parameter_texts: Mapping of parameter name to value text, or
        None.
    :type parameter_texts: dict or None
    :param current_texts: Texts to keep for names not given, or None to
        use the defaults.
    :type current_texts: dict or None
    :returns: (texts, values): two dictionaries keyed by parameter name.
    :rtype: tuple
    :raises ComponentError: If the mapping, a name or a value is invalid.
    """
    component_definition = _lookup_component_definition(kind)
    display_name = component_definition["display_name"]
    parameter_definitions = get_parameter_definitions(kind)
    known_names = [parameter["name"] for parameter in parameter_definitions]

    if parameter_texts is None:
        parameter_texts = {}

    if not isinstance(parameter_texts, dict):
        raise ComponentError(
            f"{display_name} settings must be a dictionary, not "
            f"{parameter_texts!r}."
        )

    for name in parameter_texts:
        if name not in known_names:
            allowed_text = ", ".join(known_names) or "none"
            raise ComponentError(
                f"{display_name} has no setting {name!r}. Settings: "
                f"{allowed_text}."
            )

    texts = {}
    values = {}

    for parameter in parameter_definitions:
        name = parameter["name"]

        if name in parameter_texts:
            value_text = parameter_texts[name]
        elif current_texts is not None and name in current_texts:
            value_text = current_texts[name]
        else:
            value_text = parameter["default_value_text"]

        if not isinstance(value_text, str):
            raise ComponentError(
                f"{display_name} {parameter['display_name'].lower()} must "
                f"be text, not {value_text!r}."
            )

        clean_text = value_text.strip()
        name_lower = parameter["display_name"].lower()
        is_choice = parameter["value_kind"] == "choice"

        # For a new part an empty box means "use the default", like the
        # main value. When editing, an empty box is an error, so a stray
        # select-all + Enter cannot silently reset the setting.
        if not clean_text:
            if current_texts is not None and name in parameter_texts:
                if is_choice:
                    raise ComponentError(
                        f"{display_name} {name_lower} is empty. Pick one "
                        f"of: {', '.join(parameter['choices'])}."
                    )

                raise ComponentError(
                    f"{display_name} {name_lower} is "
                    "empty. Enter a number such as 50 or 1k."
                )

            clean_text = parameter["default_value_text"]

        # A choice is stored in lower case and has no number.
        if is_choice:
            choice = clean_text.lower()

            if choice not in parameter["choices"]:
                raise ComponentError(
                    f"{display_name} {name_lower} must be one of "
                    f"{', '.join(parameter['choices'])}, not {clean_text!r}."
                )

            texts[name] = choice
            values[name] = choice
            continue

        try:
            numeric_value = parse_value(clean_text)
        except ComponentError as error:
            raise ComponentError(
                f"{display_name} {parameter['display_name'].lower()}: {error}"
            ) from None

        if parameter["value_kind"] == "positive" and not numeric_value > 0:
            raise ComponentError(
                f"{display_name} {parameter['display_name'].lower()} must "
                "be greater than zero."
            )

        low = parameter.get("minimum_value")
        high = parameter.get("maximum_value")

        if (low is not None and high is not None and
                (numeric_value < low or numeric_value > high)):
            raise ComponentError(
                f"{display_name} {name_lower} must be from {low} to {high}."
            )

        if low is not None and numeric_value < low:
            raise ComponentError(
                f"{display_name} {name_lower} must be at least {low}."
            )

        if high is not None and numeric_value > high:
            raise ComponentError(
                f"{display_name} {name_lower} must be at most {high}."
            )

        texts[name] = clean_text
        values[name] = numeric_value

    return (texts, values)


def follow_choice_model(kind, value_text, old_texts, new_texts):
    """
    Return the model a part should use after its settings change.

    For a kind with "model_follows_choice" (the LED's color): when the
    choice changes and value_text is the old choice's default model (case
    ignored), the new choice's default model is returned. Any other model
    (one the user typed) is returned unchanged, and so is value_text when
    either settings dict lacks the choice or names a choice the map does
    not know.

    :param kind: Component kind.
    :type kind: str
    :param value_text: Validated model text.
    :type value_text: str
    :param old_texts: Settings before the change.
    :type old_texts: dict
    :param new_texts: Validated settings after the change.
    :type new_texts: dict
    :returns: Model text to store.
    :rtype: str
    """
    follow = COMPONENT_DEFINITIONS[kind].get("model_follows_choice")

    if follow is None:
        return value_text

    name, map_name = follow
    model_by_choice = _MODEL_MAPS[map_name]
    old_choice = old_texts.get(name)
    new_choice = new_texts.get(name)

    if old_choice not in model_by_choice or new_choice not in model_by_choice:
        return value_text

    if (old_choice != new_choice and
            value_text.upper() == model_by_choice[old_choice].upper()):
        return model_by_choice[new_choice]

    return value_text


def get_default_parameter_texts(kind):
    """
    Return the default settings texts of a kind.

    :param kind: Component kind.
    :type kind: str
    :returns: {setting name: default text}.
    :rtype: dict
    """
    return {
        parameter["name"]: parameter["default_value_text"]
        for parameter in get_parameter_definitions(kind)
    }


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
    :param parameter_texts: Extra settings by name, for example
        {"frequency": "50"} for an AC source; missing ones use defaults.
    :type parameter_texts: dict or None
    :raises ComponentError: If any argument is invalid.
    """

    def __init__(
            self,
            kind,
            reference,
            value_text,
            row_number,
            column_number,
            rotation=0,
            parameter_texts=None):
        component_definition = _lookup_component_definition(kind)

        self.validate_reference(reference, component_definition)
        clean_text, value = validate_value_text(kind, value_text)
        # The model is stored exactly as given (a saved LED_RED on a green
        # LED stays LED_RED); only add_component, given empty text, picks
        # the chosen color's default model.
        texts, values = validate_parameter_texts(kind, parameter_texts)

        # Extra settings such as an AC source's frequency: the text as
        # typed (shown in the label) and the parsed number.
        self.parameter_texts = texts
        self.parameter_values = values

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

    def set_values(self, value_text, parameter_texts=None):
        """
        Validate and store a new value and extra settings together.

        Nothing changes unless everything is valid.

        :param value_text: New user-entered value text.
        :type value_text: str
        :param parameter_texts: Settings to change by name; others keep
            their current value.
        :type parameter_texts: dict or None
        :returns: None
        :raises ComponentError: If the value or a setting is invalid.
        """
        clean_text, value = validate_value_text(self.kind, value_text)
        texts, values = validate_parameter_texts(
            self.kind,
            parameter_texts,
            self.parameter_texts
        )
        clean_text = follow_choice_model(
            self.kind, clean_text, self.parameter_texts, texts
        )

        self.value_text = clean_text
        self.value = value
        self.parameter_texts = texts
        self.parameter_values = values

    def to_dict(self):
        """
        Return this part as JSON-ready data.

        :rtype: dict
        """
        return {
            "kind": self.kind,
            "reference": self.reference,
            "value": self.value_text,
            "row": self.row_number,
            "column": self.column_number,
            "rotation": self.rotation,
            "parameters": dict(self.parameter_texts),
        }

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

    def get_covered_half_points(self):
        """
        Return the points this part's body covers, in doubled grid units.

        Doubled units make half points whole numbers: grid point (row,
        column) is (2 * row, 2 * column), and a body halfway between R2 C2
        and R2 C3 covers (4, 5).

        :returns: Set of (doubled_row, doubled_column).
        :rtype: set
        """
        covered_points = set()

        for half_dx, half_dy in COMPONENT_DEFINITIONS[self.kind][
                "covered_half_steps"]:
            rotated_dx, rotated_dy = rotate_offset(
                half_dx, half_dy, self.rotation
            )
            covered_points.add((
                2 * self.row_number + rotated_dy,
                2 * self.column_number + rotated_dx
            ))

        return covered_points

    def get_pin_half_points(self):
        """
        Return the pins' grid points in doubled grid units (see
        get_covered_half_points).

        :returns: Set of (2 * row, 2 * column).
        :rtype: set
        """
        return {
            (2 * row_number, 2 * column_number)
            for _pin_name, row_number, column_number in
            self.get_pin_positions()
        }

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

        Sources add their units and shown settings: "V1 9V",
        "V2 1V 1kHz".

        :returns: Reference and value text, or "" for ground. A part with
            no value still shows a setting, so a switch reads "S1 open".
        :rtype: str
        """
        component_definition = COMPONENT_DEFINITIONS[self.kind]
        label_style = component_definition.get("label_style")

        if label_style == "reference":
            return self.reference

        if label_style == "signed_gain":
            return (
                f"{self.reference} "
                f"{component_definition['gain_sign']}{self.value_text}"
            )

        if component_definition["value_kind"] == "none":
            extras = _shown_parameter_label_parts(self)

            if not extras:
                return ""

            return " ".join([self.reference, *extras])

        parts = [
            self.reference,
            self.value_text + component_definition.get("value_unit", "")
        ]

        parts.extend(_shown_parameter_label_parts(self))

        return " ".join(parts)


def _shown_parameter_label_parts(component):
    """
    Return the setting texts that belong on a part's label.

    :param component: Placed part.
    :type component: Component
    :rtype: list
    """
    parts = []

    for parameter in get_panel_parameter_definitions(component.kind):
        if not parameter.get("shown_in_label", True):
            continue

        parts.append(
            component.parameter_texts[parameter["name"]] + parameter["unit"]
        )

    return parts


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

    The collection assigns references, refuses placements, rotations and
    moves that would put a pin outside the grid or hide another part (the
    same pin points, any kind; the same body centre; or a body drawn over
    another part's body or pin), and removes parts that no longer fit after
    the grid shrinks. Parts may still share single pins: that is how they
    connect.
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
            rotation=0,
            parameter_texts=None):
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
        :param parameter_texts: Extra settings by name, for example
            {"frequency": "50"}; missing or empty ones use defaults.
        :type parameter_texts: dict or None
        :returns: The new component.
        :rtype: Component
        :raises ComponentError: If any argument is invalid or a pin would
            fall outside the grid.
        """
        _validate_connection_grid(connection_grid)
        component_definition = _lookup_component_definition(kind)

        # Empty text means "use the default", for example "1k". For an LED
        # the default follows the chosen color: green gives LED_GREEN. Text
        # the caller gave is never changed.
        if isinstance(value_text, str) and not value_text.strip():
            value_text = component_definition["default_value_text"]

            if component_definition.get("model_follows_choice"):
                texts, _values = validate_parameter_texts(
                    kind, parameter_texts
                )
                value_text = follow_choice_model(
                    kind,
                    value_text,
                    get_default_parameter_texts(kind),
                    texts
                )

        component = Component(
            kind,
            self.next_reference(kind),
            value_text,
            row_number,
            column_number,
            rotation,
            parameter_texts
        )

        self.ensure_pins_fit_grid(component, connection_grid)
        self.ensure_no_overlap(component)

        self.components_by_reference[component.reference] = component

        return component

    def place_saved(
            self,
            kind,
            reference,
            value_text,
            row_number,
            column_number,
            connection_grid,
            rotation=0,
            parameter_texts=None):
        """
        Put a part from a project file onto the circuit, keeping its name.

        :param reference: Saved reference, such as ``R1``.
        :rtype: Component
        :raises ComponentError: If the part is invalid, off the grid,
            overlapping, or the name is already used. Nothing is stored then.
        """
        if reference in self.components_by_reference:
            raise ComponentError(
                f"{reference} is already on this circuit."
            )

        component = Component(
            kind,
            reference,
            value_text,
            row_number,
            column_number,
            rotation,
            parameter_texts
        )
        self.ensure_pins_fit_grid(component, connection_grid)
        self.ensure_no_overlap(component)
        self.components_by_reference[reference] = component

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

    def find_component_drawn_over(self, component):
        """
        Return a stored part whose symbol this part's symbol would cover.

        That is a part whose covered points meet this part's covered
        points or pins, or whose pins meet this part's covered points (all
        in the doubled units of Component.get_covered_half_points). Shared
        pins alone do not count.

        :param component: Part to compare; it is skipped if it is stored.
        :type component: Component
        :returns: The first such part by reference, or None.
        :rtype: Component or None
        """
        covered_points = component.get_covered_half_points()
        pin_points = component.get_pin_half_points()

        for existing_component in self.get_components():
            if existing_component is component:
                continue

            existing_covered_points = (
                existing_component.get_covered_half_points()
            )

            if (covered_points & existing_covered_points or
                    pin_points & existing_covered_points or
                    covered_points &
                    existing_component.get_pin_half_points()):
                return existing_component

        return None

    def ensure_no_overlap(self, component):
        """
        Raise a clear error when a part would hide another one.

        Three checks, in order: the same pin points as another part (any
        kind, either order); the same body centre; and a body drawn over
        another part's body or pin, or a pin under another part's body
        (find_component_drawn_over). Sharing single pins is allowed.

        :param component: Part being placed, rotated or moved.
        :type component: Component
        :returns: None
        :raises ComponentError: If another part has the same pin points,
            the same body centre, or would be drawn over by this part (or
            draw over it).
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

        existing_component = self.find_component_drawn_over(component)

        if existing_component is not None:
            existing_display_name = COMPONENT_DEFINITIONS[
                existing_component.kind
            ]["display_name"]
            raise ComponentError(
                f"{existing_component.reference} ({existing_display_name}) "
                "is already drawn there, so one symbol would hide the other. "
                "Pick another grid point or rotation, or select "
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

    def move_component(self, reference, row_number, column_number,
                       connection_grid):
        """
        Move a part's anchor to another grid point, keeping its rotation.

        The move is checked like a placement: every pin must land on the
        grid and the part must not hide another one (same pin points or
        same body centre). Moving onto its own spot is allowed and changes
        nothing.

        :param reference: Reference of the part to move.
        :type reference: str
        :param row_number: New one-based anchor row.
        :type row_number: int
        :param column_number: New one-based anchor column.
        :type column_number: int
        :param connection_grid: Grid the part must fit on.
        :type connection_grid: ConnectionGrid
        :returns: The moved component.
        :rtype: Component
        :raises ComponentError: If the part is unknown, the position is not
            a valid grid point, a pin would leave the grid, or the part
            would overlap another one. The part then stays where it was.
        """
        _validate_connection_grid(connection_grid)
        component = self.get_component(reference)

        # A drag can end beyond the grid edge: say so plainly instead of
        # quoting the anchor range check.
        if (_is_plain_integer(row_number) and
                _is_plain_integer(column_number) and
                not (1 <= row_number <= connection_grid.row_count and
                     1 <= column_number <= connection_grid.column_count)):
            raise ComponentError(
                f"{reference} cannot be moved to row {row_number}, column "
                f"{column_number}: that is outside the "
                f"{connection_grid.row_count} x {connection_grid.column_count} "
                "grid."
            )

        old_row_number = component.row_number
        old_column_number = component.column_number

        def put_back():
            component.row_number = old_row_number
            component.column_number = old_column_number

        try:
            component.row_number = row_number
            component.column_number = column_number
        except ComponentError as error:
            put_back()
            raise ComponentError(
                f"{reference} cannot be moved there: {error}"
            ) from None

        target_text = (
            f"{reference} cannot be moved to row {row_number}, column "
            f"{column_number}"
        )

        if not component.pins_fit_grid(
                connection_grid.row_count,
                connection_grid.column_count):
            put_back()
            raise ComponentError(
                f"{target_text}: a pin would fall outside the "
                f"{connection_grid.row_count} x {connection_grid.column_count} "
                "grid."
            )

        try:
            self.ensure_no_overlap(component)
        except ComponentError as error:
            put_back()
            raise ComponentError(f"{target_text}: {error}") from None

        return component

    def check_move(self, reference, row_number, column_number,
                   connection_grid):
        """
        Say whether move_component would accept a move, without moving.

        Used while a part is dragged, to show a drop that would be refused.

        :param reference: Reference of the part.
        :type reference: str
        :param row_number: Candidate one-based anchor row.
        :type row_number: int
        :param column_number: Candidate one-based anchor column.
        :type column_number: int
        :param connection_grid: Grid the part must fit on.
        :type connection_grid: ConnectionGrid
        :returns: None if the move would be accepted, otherwise the reason
            move_component would give.
        :rtype: str or None
        :raises ComponentError: If the part is unknown or the grid is not a
            ConnectionGrid.
        """
        _validate_connection_grid(connection_grid)
        component = self.get_component(reference)
        old_row_number = component.row_number
        old_column_number = component.column_number

        try:
            self.move_component(
                reference, row_number, column_number, connection_grid
            )
        except ComponentError as error:
            return str(error)

        component.row_number = old_row_number
        component.column_number = old_column_number

        return None

    def set_component_value(self, reference, value_text, parameter_texts=None):
        """
        Change a component's value, and optionally its extra settings.

        :param reference: Reference of the part.
        :type reference: str
        :param value_text: New value text.
        :type value_text: str
        :param parameter_texts: Settings to change by name, for example
            {"frequency": "50"}; others are kept.
        :type parameter_texts: dict or None
        :returns: The updated component.
        :rtype: Component
        :raises ComponentError: If the part is unknown or the value or a
            setting is invalid. The old values are then all kept.
        """
        component = self.get_component(reference)
        component.set_values(value_text, parameter_texts)

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
