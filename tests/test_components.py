"""
Tests for core.components: definitions, rotation, pins, values, labels.
"""

import pytest

from core.components import (
    COMPONENT_DEFINITIONS,
    VALID_ROTATIONS,
    Component,
    get_component_definition,
    get_panel_parameter_definitions,
    get_parameter_definitions,
    rotate_offset,
    validate_value_text,
)
from core.exceptions import ComponentError

# rotate_offset ------------------------------------------------------------


@pytest.mark.parametrize(
    "dx, dy, rotation, expected_offset",
    [
        (1, 0, 0, (1, 0)),
        (1, 0, 90, (0, 1)),
        (1, 0, 180, (-1, 0)),
        (1, 0, 270, (0, -1)),
        (-1, 0, 180, (1, 0)),
        (0, -1, 90, (1, 0)),
        (2, 3, 90, (-3, 2)),
        (2, 3, 270, (3, -2)),
    ]
)
def test_rotate_offset(dx, dy, rotation, expected_offset):
    assert rotate_offset(dx, dy, rotation) == expected_offset


@pytest.mark.parametrize("rotation", [45, -90, 360, 90.0, "90", None, True])
def test_rotate_offset_rejects_bad_rotation(rotation):
    with pytest.raises(ComponentError):
        rotate_offset(1, 0, rotation)


@pytest.mark.parametrize("dx, dy", [(1.0, 0), (0, "1"), (True, 0)])
def test_rotate_offset_rejects_non_integer_offsets(dx, dy):
    with pytest.raises(ComponentError):
        rotate_offset(dx, dy, 0)


OPAMP_PINS = [
    ("in+", -1, 1), ("in-", -1, -1), ("out", 1, 0), ("V+", 0, -1), ("V-", 0, 1)
]
GATE_PINS = [
    ("A", -1, -1), ("B", -1, 1), ("Y", 1, 0), ("VCC", 0, -1), ("GND", 0, 1)
]
SINGLE_PINS = [
    ("A", -1, 0), ("Y", 1, 0), ("VCC", 0, -1), ("GND", 0, 1)
]
AMP_PINS = [
    ("in", -1, 0), ("out", 1, 0), ("V+", 0, -1), ("V-", 0, 1)
]
OPAMP_COVERED = [
    (0, 0), (-1, 0), (1, 0), (0, -1), (0, 1),
    (-1, -1), (-1, 1), (-1, -2), (-1, 2),
]

def test_four_rotations_return_to_start():
    offset = (2, -1)

    for unused_step in range(4):
        offset = rotate_offset(offset[0], offset[1], 90)

    assert offset == (2, -1)


# Definitions table -------------------------------------------------------


def test_valid_rotations():
    assert VALID_ROTATIONS == (0, 90, 180, 270)


def test_plan_definitions_are_exact():
    expected = {
        "resistor": ("R", [("1", 0, 0), ("2", 1, 0)], "positive", "1k"),
        "capacitor": ("C", [("1", 0, 0), ("2", 1, 0)], "positive", "100n"),
        "capacitor_polarized": (
            "C", [("plus", 0, 0), ("minus", 1, 0)], "positive", "10u"),
        "inductor": ("L", [("1", 0, 0), ("2", 1, 0)], "positive", "10u"),
        "dc_source": ("V", [("plus", 0, 0), ("minus", 0, 1)], "any", "5"),
        "ac_source": ("V", [("plus", 0, 0), ("minus", 0, 1)], "any", "1"),
        "current_source": ("I", [("out", 0, 0), ("in", 0, 1)], "any", "1m"),
        "diode": (
            "D", [("anode", 0, 0), ("cathode", 1, 0)], "model", "1N4148"),
        "led": (
            "D", [("anode", 0, 0), ("cathode", 1, 0)], "model", "LED_RED"),
        "npn": (
            "Q",
            [("base", -1, 0), ("collector", 0, -1), ("emitter", 0, 1)],
            "model",
            "2N3904",
        ),
        "pnp": (
            "Q",
            [("base", -1, 0), ("emitter", 0, -1), ("collector", 0, 1)],
            "model",
            "2N3906",
        ),
        "nmos": (
            "M",
            [("gate", -1, 0), ("drain", 0, -1), ("source", 0, 1)],
            "model",
            "2N7000",
        ),
        "pmos": (
            "M",
            [("gate", -1, 0), ("source", 0, -1), ("drain", 0, 1)],
            "model",
            "BS250",
        ),
        "ground": ("GND", [("gnd", 0, 0)], "none", ""),
        "opamp_generic": ("X", OPAMP_PINS, "model", "OPAMP"),
        "opamp_741": ("X", OPAMP_PINS, "model", "LM741"),
        "opamp_lm358": ("X", OPAMP_PINS, "model", "LM358"),
        "opamp_tl072": ("X", OPAMP_PINS, "model", "TL072"),
        "opamp_ne5532": ("X", OPAMP_PINS, "model", "NE5532"),
        "comparator": ("X", OPAMP_PINS, "model", "COMP"),
        "gate_not": ("X", SINGLE_PINS, "model", "NOT"),
        "gate_buffer": ("X", SINGLE_PINS, "model", "BUF"),
        "gate_and": ("X", GATE_PINS, "model", "AND2"),
        "gate_or": ("X", GATE_PINS, "model", "OR2"),
        "gate_nand": ("X", GATE_PINS, "model", "NAND2"),
        "gate_nor": ("X", GATE_PINS, "model", "NOR2"),
        "gate_xor": ("X", GATE_PINS, "model", "XOR2"),
        "follower": ("A", AMP_PINS, "none", ""),
        "inverting_amp": ("A", AMP_PINS, "positive", "10"),
        "noninverting_amp": ("A", AMP_PINS, "positive", "2"),
        "switch": ("S", [("1", 0, 0), ("2", 1, 0)], "none", ""),
        "potentiometer": (
            "RV",
            [("1", 0, 0), ("2", 2, 0), ("wiper", 1, 1)],
            "positive",
            "10k",
        ),
        "transformer": (
            "T",
            [("p1", 0, 0), ("p2", 0, 1), ("s1", 1, 0), ("s2", 1, 1)],
            "positive",
            "1",
        ),
        "timer_555": (
            "X",
            [
                ("GND", -1, -2), ("TRIG", -1, -1), ("OUT", -1, 1),
                ("RESET", -1, 2), ("CONT", 1, 2), ("THRES", 1, 1),
                ("DISCH", 1, -1), ("VCC", 1, -2),
            ],
            "model",
            "NE555",
        ),
        "voltage_regulator": (
            "U", [("in", -1, 0), ("gnd", 0, 1), ("out", 1, 0)],
            "positive", "5",
        ),
    }

    assert set(COMPONENT_DEFINITIONS) == set(expected)

    for kind, (prefix, pins, value_kind, default_text) in expected.items():
        definition = COMPONENT_DEFINITIONS[kind]
        assert definition["prefix"] == prefix
        assert definition["pins"] == pins
        assert definition["value_kind"] == value_kind
        assert definition["default_value_text"] == default_text
        assert definition["display_name"]


def test_body_centres_are_exact():
    expected = {
        "resistor": (1, 0), "capacitor": (1, 0),
        "capacitor_polarized": (1, 0), "inductor": (1, 0),
        "diode": (1, 0), "led": (1, 0),
        "dc_source": (0, 1), "ac_source": (0, 1), "current_source": (0, 1),
        "npn": (0, 0), "pnp": (0, 0),
        "nmos": (0, 0), "pmos": (0, 0), "ground": (0, 0),
        "opamp_generic": (0, 0), "opamp_741": (0, 0),
        "opamp_lm358": (0, 0), "opamp_tl072": (0, 0),
        "opamp_ne5532": (0, 0), "comparator": (0, 0),
        "gate_not": (0, 0), "gate_buffer": (0, 0),
        "gate_and": (0, 0), "gate_or": (0, 0), "gate_nand": (0, 0),
        "gate_nor": (0, 0), "gate_xor": (0, 0),
        "follower": (0, 0), "inverting_amp": (0, 0),
        "noninverting_amp": (0, 0),
        "switch": (1, 0), "potentiometer": (2, 0),
        "transformer": (1, 1), "timer_555": (0, 0),
        "voltage_regulator": (0, 0),
    }

    assert {
        kind: definition["body_center_half_steps"]
        for kind, definition in COMPONENT_DEFINITIONS.items()
    } == expected


TWO_PIN_KINDS = [
    kind for kind, definition in sorted(COMPONENT_DEFINITIONS.items())
    if len(definition["pins"]) == 2
]


def test_every_two_pin_part_is_listed():
    assert TWO_PIN_KINDS == [
        "ac_source", "capacitor", "capacitor_polarized", "current_source",
        "dc_source",
        "diode", "inductor", "led", "resistor", "switch",
    ]


@pytest.mark.parametrize("kind", TWO_PIN_KINDS)
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_two_pin_parts_span_one_step_from_the_anchor(kind, rotation):
    prefix = COMPONENT_DEFINITIONS[kind]["prefix"]
    default_text = COMPONENT_DEFINITIONS[kind]["default_value_text"]
    component = Component(kind, prefix + "1", default_text, 4, 4, rotation)

    (_first, row_1, column_1), (_second, row_2, column_2) = (
        component.get_pin_positions()
    )

    # The first pin is the anchor; the second is a neighbouring point.
    assert (row_1, column_1) == (4, 4)
    assert abs(row_2 - row_1) + abs(column_2 - column_1) == 1
    # The body centre is exactly halfway between the two pins.
    assert component.get_body_center_position() == (
        (row_1 + row_2) / 2, (column_1 + column_2) / 2
    )


@pytest.mark.parametrize(
    "rotation, expected_offset",
    [(0, (0.5, 0.0)), (90, (0.0, 0.5)), (180, (-0.5, 0.0)),
     (270, (0.0, -0.5))],
)
def test_resistor_body_center_offset(rotation, expected_offset):
    resistor = Component("resistor", "R1", "1k", 4, 4, rotation)

    assert resistor.get_body_center_offset() == expected_offset


@pytest.mark.parametrize("kind, value", [("npn", "2N3904"), ("ground", "")])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_transistor_and_ground_centre_stays_on_the_anchor(
        kind, value, rotation):
    prefix = COMPONENT_DEFINITIONS[kind]["prefix"]
    component = Component(kind, prefix + "1", value, 4, 4, rotation)

    assert component.get_body_center_offset() == (0.0, 0.0)
    assert component.get_body_center_position() == (4.0, 4.0)


@pytest.mark.parametrize("kind", sorted(COMPONENT_DEFINITIONS))
def test_every_default_value_is_valid(kind):
    default_text = COMPONENT_DEFINITIONS[kind]["default_value_text"]
    prefix = COMPONENT_DEFINITIONS[kind]["prefix"]

    component = Component(kind, prefix + "1", default_text, 4, 4)

    assert component.value_text == default_text


@pytest.mark.parametrize("kind", sorted(COMPONENT_DEFINITIONS))
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_pins_stay_on_distinct_grid_points(kind, rotation):
    prefix = COMPONENT_DEFINITIONS[kind]["prefix"]
    default_text = COMPONENT_DEFINITIONS[kind]["default_value_text"]
    component = Component(kind, prefix + "1", default_text, 4, 4, rotation)

    positions = [
        (row, column) for unused_name, row, column
        in component.get_pin_positions()
    ]

    assert len(set(positions)) == len(positions)
    assert all(type(value) is int for position in positions
               for value in position)


# Pin positions after rotation --------------------------------------------


@pytest.mark.parametrize(
    "rotation, expected_positions",
    [
        (0, [("1", 4, 4), ("2", 4, 5)]),
        (90, [("1", 4, 4), ("2", 5, 4)]),
        (180, [("1", 4, 4), ("2", 4, 3)]),
        (270, [("1", 4, 4), ("2", 3, 4)]),
    ]
)
def test_resistor_pin_positions(rotation, expected_positions):
    resistor = Component("resistor", "R1", "4k7", 4, 4, rotation)

    assert resistor.get_pin_positions() == expected_positions


def test_resistor_identifiers_value_and_label():
    resistor = Component("resistor", "R1", "4k7", 4, 4)

    assert resistor.get_pin_identifiers() == ["NODE_R04_C04", "NODE_R04_C05"]
    assert resistor.value == 4700.0
    assert resistor.label_text() == "R1 4k7"


def test_npn_pin_positions():
    transistor = Component("npn", "Q1", "2N3904", 4, 4)
    assert transistor.get_pin_positions() == [
        ("base", 4, 3), ("collector", 3, 4), ("emitter", 5, 4)
    ]

    transistor.rotation = 90
    assert transistor.get_pin_positions() == [
        ("base", 3, 4), ("collector", 4, 5), ("emitter", 4, 3)
    ]


def test_pnp_has_emitter_on_top():
    transistor = Component("pnp", "Q1", "2N3906", 4, 4)

    assert transistor.get_pin_positions() == [
        ("base", 4, 3), ("emitter", 3, 4), ("collector", 5, 4)
    ]


def test_dc_source_rotated_90():
    source = Component("dc_source", "V1", "5", 4, 4, 90)

    assert source.get_pin_positions() == [("plus", 4, 4), ("minus", 4, 3)]


def test_polarized_capacitor_pins():
    capacitor = Component("capacitor_polarized", "C1", "10u", 4, 4, 270)

    assert capacitor.get_pin_positions() == [("plus", 4, 4), ("minus", 3, 4)]
    assert capacitor.value == 1e-05


def test_ground():
    ground = Component("ground", "GND1", "", 8, 1)

    assert ground.get_pin_positions() == [("gnd", 8, 1)]
    assert ground.get_pin_identifiers() == ["NODE_R08_C01"]
    assert ground.label_text() == ""
    assert ground.value is None


@pytest.mark.parametrize(
    "rotation, expected_positions",
    [
        (0, [("plus", 4, 4), ("minus", 5, 4)]),
        (90, [("plus", 4, 4), ("minus", 4, 3)]),
        (180, [("plus", 4, 4), ("minus", 3, 4)]),
        (270, [("plus", 4, 4), ("minus", 4, 5)]),
    ]
)
def test_ac_source_pin_positions(rotation, expected_positions):
    source = Component("ac_source", "V1", "1", 4, 4, rotation)

    assert source.get_pin_positions() == expected_positions


@pytest.mark.parametrize("kind, model_name", [
    ("diode", "1N4148"),
    ("led", "LED_RED"),
])
@pytest.mark.parametrize(
    "rotation, expected_positions",
    [
        (0, [("anode", 4, 4), ("cathode", 4, 5)]),
        (90, [("anode", 4, 4), ("cathode", 5, 4)]),
        (180, [("anode", 4, 4), ("cathode", 4, 3)]),
        (270, [("anode", 4, 4), ("cathode", 3, 4)]),
    ]
)
def test_diode_and_led_pin_positions(
        kind, model_name, rotation, expected_positions):
    diode = Component(kind, "D1", model_name, 4, 4, rotation)

    assert diode.get_pin_positions() == expected_positions


@pytest.mark.parametrize(
    "rotation, expected_positions",
    [
        (0, [("plus", 4, 4), ("minus", 4, 5)]),
        (90, [("plus", 4, 4), ("minus", 5, 4)]),
        (180, [("plus", 4, 4), ("minus", 4, 3)]),
        (270, [("plus", 4, 4), ("minus", 3, 4)]),
    ]
)
def test_polarized_capacitor_pin_positions(rotation, expected_positions):
    capacitor = Component("capacitor_polarized", "C1", "10u", 4, 4, rotation)

    assert capacitor.get_pin_positions() == expected_positions


def test_get_component_definition_returns_a_copy():
    definition = get_component_definition("resistor")
    definition["pins"].append(("3", 0, 1))
    definition["prefix"] = "X"

    assert COMPONENT_DEFINITIONS["resistor"]["pins"] == [
        ("1", 0, 0), ("2", 1, 0)
    ]
    assert COMPONENT_DEFINITIONS["resistor"]["prefix"] == "R"
    assert get_component_definition("resistor")["prefix"] == "R"


def test_get_component_definition_rejects_unknown_kind():
    with pytest.raises(ComponentError):
        get_component_definition("transistor")


def test_pins_fit_grid():
    # One-step parts fit right up to the corner, pointing inward.
    assert Component("resistor", "R1", "1k", 1, 1).pins_fit_grid(8, 8)
    assert Component("resistor", "R1", "1k", 4, 4).pins_fit_grid(8, 8)
    assert not Component("resistor", "R1", "1k", 4, 8).pins_fit_grid(8, 8)
    assert Component("resistor", "R1", "1k", 4, 8, 180).pins_fit_grid(8, 8)
    assert not Component("resistor", "R1", "1k", 1, 1, 180).pins_fit_grid(
        8, 8
    )
    assert not Component("resistor", "R1", "1k", 8, 4, 90).pins_fit_grid(8, 8)
    assert not Component("resistor", "R1", "1k", 1, 4, 270).pins_fit_grid(
        8, 8
    )
    assert Component("ground", "GND1", "", 8, 8).pins_fit_grid(8, 8)


def test_pins_fit_grid_rejects_non_integer_size():
    resistor = Component("resistor", "R1", "1k", 4, 4)

    with pytest.raises(ComponentError):
        resistor.pins_fit_grid(8.0, 8)


# Values -------------------------------------------------------------------


@pytest.mark.parametrize("value_text", ["0", "-1k", "0.0", "-0"])
def test_resistor_rejects_non_positive_values(value_text):
    with pytest.raises(ComponentError) as error_info:
        Component("resistor", "R1", value_text, 4, 4)

    assert "greater than zero" in str(error_info.value)


def test_dc_source_accepts_negative_value():
    assert Component("dc_source", "V1", "-5", 4, 4).value == -5.0


def test_diode_model_value_is_none():
    diode = Component("diode", "D1", " 1N4148 ", 4, 4)

    assert diode.value is None
    assert diode.value_text == "1N4148"
    assert diode.label_text() == "D1 1N4148"


@pytest.mark.parametrize(
    "value_text", ["", "   ", "1N 4148", "A" * 33, "1N4148\u00b5", None, 5]
)
def test_model_name_rejects_bad_text(value_text):
    with pytest.raises(ComponentError):
        validate_value_text("diode", value_text)


@pytest.mark.parametrize("value_text", [4700, 4700.0, None, b"4k7"])
def test_numeric_value_must_be_text(value_text):
    with pytest.raises(ComponentError):
        validate_value_text("resistor", value_text)


def test_value_text_is_stripped_and_parsed():
    assert validate_value_text("capacitor", " 100n ") == ("100n", 1e-07)


def test_ground_ignores_value_input():
    assert validate_value_text("ground", "anything") == ("", None)


# Constructor validation --------------------------------------------------


@pytest.mark.parametrize("kind", ["transistor", "Resistor", "", None, 1])
def test_unknown_kind_raises(kind):
    with pytest.raises(ComponentError):
        Component(kind, "R1", "1k", 4, 4)


@pytest.mark.parametrize(
    "kind, reference",
    [
        ("resistor", "C1"),
        ("resistor", "R0"),
        ("resistor", "R"),
        ("resistor", "r1"),
        ("resistor", " R1"),
        ("resistor", "R01"),
        ("resistor", None),
        ("ground", "G1"),
    ]
)
def test_bad_reference_raises(kind, reference):
    with pytest.raises(ComponentError):
        Component(kind, reference, "1k", 4, 4)


@pytest.mark.parametrize(
    "row_number, column_number",
    [(0, 4), (4, 0), (51, 4), (4.0, 4), ("4", 4), (True, 4), (None, 4)]
)
def test_bad_anchor_raises(row_number, column_number):
    with pytest.raises(ComponentError):
        Component("resistor", "R1", "1k", row_number, column_number)


def test_bad_rotation_raises_in_constructor_and_setter():
    with pytest.raises(ComponentError):
        Component("resistor", "R1", "1k", 4, 4, 45)

    resistor = Component("resistor", "R1", "1k", 4, 4, 90)

    with pytest.raises(ComponentError):
        resistor.rotation = 90.0

    assert resistor.rotation == 90


# PR B: DC and AC sources -------------------------------------------------


def test_only_the_ac_source_and_the_led_have_settings():
    expected = {
        "ac_source": ["frequency", "offset", "phase"],
        "led": ["color"],
        "switch": ["state"],
        "potentiometer": ["position"],
    }

    for kind in COMPONENT_DEFINITIONS:
        names = [parameter["name"] for parameter in
                 get_parameter_definitions(kind)]
        assert names == expected.get(kind, [])


def test_ac_source_setting_definitions_are_exact():
    assert [
        (parameter["name"], parameter["unit"], parameter["value_kind"],
         parameter["default_value_text"], parameter["shown_in_panel"])
        for parameter in get_parameter_definitions("ac_source")
    ] == [
        ("frequency", "Hz", "positive", "1k", True),
        ("offset", "V", "any", "0", False),
        ("phase", "deg", "any", "0", False),
    ]
    assert [parameter["name"] for parameter in
            get_panel_parameter_definitions("ac_source")] == ["frequency"]


def test_source_value_labels_and_units():
    assert COMPONENT_DEFINITIONS["dc_source"]["value_label"] == "Voltage"
    assert COMPONENT_DEFINITIONS["ac_source"]["value_label"] == (
        "Peak amplitude"
    )
    assert COMPONENT_DEFINITIONS["dc_source"]["value_unit"] == "V"
    assert COMPONENT_DEFINITIONS["ac_source"]["value_unit"] == "V"


def test_dc_source_label_and_value():
    source = Component("dc_source", "V1", "9", 4, 4)

    assert source.label_text() == "V1 9V"
    assert source.value == 9.0
    assert source.parameter_texts == {}
    assert source.parameter_values == {}


def test_ac_source_defaults():
    source = Component("ac_source", "V2", "1", 4, 4)

    assert source.label_text() == "V2 1V 1kHz"
    assert source.value == 1.0
    assert source.parameter_texts == {
        "frequency": "1k", "offset": "0", "phase": "0"
    }
    assert source.parameter_values == {
        "frequency": 1000.0, "offset": 0.0, "phase": 0.0
    }


def test_ac_source_settings_are_parsed_with_parse_value():
    source = Component(
        "ac_source", "V1", "2.5", 4, 4,
        parameter_texts={"frequency": " 2k2 ", "offset": "-1", "phase": "90"}
    )

    assert source.label_text() == "V1 2.5V 2k2Hz"
    assert source.parameter_texts == {
        "frequency": "2k2", "offset": "-1", "phase": "90"
    }
    assert source.parameter_values == {
        "frequency": 2200.0, "offset": -1.0, "phase": 90.0
    }


def test_empty_frequency_means_the_default():
    source = Component(
        "ac_source", "V1", "1", 4, 4, parameter_texts={"frequency": "  "}
    )

    assert source.parameter_texts["frequency"] == "1k"


@pytest.mark.parametrize("empty_text", ["", "  "])
def test_clearing_a_setting_when_editing_is_an_error(empty_text):
    # QC #12 item 1: a stray select-all + Enter must not reset 60 Hz to 1k.
    source = Component(
        "ac_source", "V1", "1", 4, 4, parameter_texts={"frequency": "60"}
    )

    with pytest.raises(
        ComponentError,
        match=r"^AC voltage source frequency is empty\. Enter a number "
              r"such as 50 or 1k\.$"
    ):
        source.set_values("2", {"frequency": empty_text})

    assert source.value_text == "1"
    assert source.parameter_texts["frequency"] == "60"
    assert source.parameter_values["frequency"] == 60.0


def test_settings_not_given_when_editing_keep_their_text():
    source = Component(
        "ac_source", "V1", "1", 4, 4, parameter_texts={"frequency": "60"}
    )

    source.set_values("2", {})

    assert source.parameter_texts["frequency"] == "60"


@pytest.mark.parametrize("parameter_texts, message", [
    ({"frequency": "0"}, "frequency must be greater than zero"),
    ({"frequency": "-50"}, "frequency must be greater than zero"),
    ({"frequency": "1kHz"}, "frequency: Invalid value '1kHz'"),
    ({"frequency": "1M"}, "'M' is ambiguous"),
    ({"frequency": 50}, "frequency must be text"),
    ({"offset": "abc"}, "offset: Invalid value 'abc'"),
    ({"gain": "2"}, "has no setting 'gain'. Settings: frequency, offset"),
    (["frequency"], "settings must be a dictionary"),
])
def test_bad_ac_source_settings_raise(parameter_texts, message):
    with pytest.raises(ComponentError) as error_info:
        Component("ac_source", "V1", "1", 4, 4,
                  parameter_texts=parameter_texts)

    assert message in str(error_info.value)


def test_kinds_without_settings_refuse_any_setting():
    with pytest.raises(ComponentError, match="Settings: none"):
        Component("dc_source", "V1", "9", 4, 4,
                  parameter_texts={"frequency": "50"})


def test_set_values_changes_value_and_settings_together():
    source = Component("ac_source", "V1", "1", 4, 4)

    source.set_values("3", {"frequency": "50"})

    assert source.label_text() == "V1 3V 50Hz"
    assert source.value == 3.0
    assert source.parameter_values["frequency"] == 50.0


def test_set_values_keeps_settings_not_given():
    source = Component(
        "ac_source", "V1", "1", 4, 4,
        parameter_texts={"frequency": "60", "phase": "45"}
    )

    source.set_values("2")

    assert source.parameter_texts == {
        "frequency": "60", "offset": "0", "phase": "45"
    }


@pytest.mark.parametrize("value_text, parameter_texts", [
    ("abc", {"frequency": "50"}),
    ("3", {"frequency": "0"}),
])
def test_set_values_changes_nothing_on_error(value_text, parameter_texts):
    source = Component("ac_source", "V1", "1", 4, 4)

    with pytest.raises(ComponentError):
        source.set_values(value_text, parameter_texts)

    assert source.value_text == "1"
    assert source.value == 1.0
    assert source.parameter_texts["frequency"] == "1k"
    assert source.parameter_values["frequency"] == 1000.0


def test_old_voltage_source_kind_is_gone():
    # The current source came back as its own kind (Billie, Oct 9).
    for kind in ("voltage_source",):
        assert kind not in COMPONENT_DEFINITIONS

        with pytest.raises(ComponentError, match="Unknown component kind"):
            Component(kind, "V1", "5", 4, 4)


def test_setting_definitions_are_not_shared_through_copies():
    definition = get_component_definition("ac_source")
    definition["parameters"][0]["default_value_text"] = "50"

    assert get_parameter_definitions("ac_source")[0][
        "default_value_text"
    ] == "1k"


def test_covered_half_steps_are_exact():
    expected = {
        "resistor": [(1, 0)], "capacitor": [(1, 0)],
        "capacitor_polarized": [(1, 0)], "inductor": [(1, 0)],
        "diode": [(1, 0)], "led": [(1, 0)],
        "dc_source": [(0, 1)], "ac_source": [(0, 1)],
        "current_source": [(0, 1)],
        "npn": [(0, 0), (-1, 0), (0, -1), (0, 1)],
        "pnp": [(0, 0), (-1, 0), (0, -1), (0, 1)],
        "nmos": [(0, 0), (-1, 0), (0, -1), (0, 1)],
        "pmos": [(0, 0), (-1, 0), (0, -1), (0, 1)],
        "ground": [(0, 1)],
        # Inside the triangle (left x = -0.6, apex 0.75, half height 1.2):
        # anchor, half points to out / V+ / V- / left, beside each input.
        "opamp_generic": OPAMP_COVERED,
        "opamp_741": OPAMP_COVERED,
        "opamp_lm358": OPAMP_COVERED,
        "opamp_tl072": OPAMP_COVERED,
        "opamp_ne5532": OPAMP_COVERED,
        "comparator": OPAMP_COVERED,
        "gate_not": OPAMP_COVERED,
        "gate_buffer": OPAMP_COVERED,
        "gate_and": OPAMP_COVERED,
        "gate_or": OPAMP_COVERED,
        "gate_nand": OPAMP_COVERED,
        "gate_nor": OPAMP_COVERED,
        "gate_xor": OPAMP_COVERED,
        "follower": OPAMP_COVERED,
        "inverting_amp": OPAMP_COVERED,
        "noninverting_amp": OPAMP_COVERED,
        "switch": [(1, 0)],
        "potentiometer": [(1, 0), (2, 0), (3, 0), (2, 1)],
        "transformer": [(1, 1), (0, 1), (2, 1), (1, 0), (1, 2)],
        "timer_555": [
            (0, 0),
            (-1, 0), (1, 0), (0, -1), (0, 1),
            (-1, -1), (-1, 1), (1, -1), (1, 1),
            (0, -2), (0, 2),
            (-1, -2), (-1, 2), (1, -2), (1, 2),
        ],
        "voltage_regulator": [(0, 0), (-1, 0), (1, 0), (0, 1)],
    }

    assert {
        kind: definition["covered_half_steps"]
        for kind, definition in COMPONENT_DEFINITIONS.items()
    } == expected


def test_covered_half_points_of_a_turned_transistor():
    # At 90 deg rotate_offset maps (-1,0)->(0,-1), (0,-1)->(1,0) and
    # (0,1)->(-1,0); doubled anchor (8, 8) plus (dy, dx).
    transistor = Component("npn", "Q1", "2N3904", 4, 4, 90)

    assert transistor.get_covered_half_points() == {
        (8, 8), (7, 8), (8, 9), (8, 7)
    }


def test_covered_half_point_of_a_two_pin_body_and_pin_half_points():
    resistor = Component("resistor", "R1", "1k", 2, 2, 270)

    # Pins (2,2) and (1,2): body halfway at doubled (3, 4).
    assert resistor.get_covered_half_points() == {(3, 4)}
    assert resistor.get_pin_half_points() == {(4, 4), (2, 4)}
