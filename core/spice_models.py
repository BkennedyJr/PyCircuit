"""
Small SPICE device models for diodes, LEDs and transistors.

These are stand-ins written for PyCircuit, not vendor models. The names
match the parts' defaults. Lookup ignores case, the same way SPICE does.

A diode, BJT, MOSFET or JFET can override the numbers on its card.
An untouched part keeps the library line. A typed number is written
into that same card.
"""

import math
import re

from core.exceptions import SimulationError
from core.units import format_spice_number, parse_value

# (device kind, parameter text). The kind must match the part: a diode
# model cannot be used on a MOSFET.
_DEVICE_MODELS = {
    "1N4148": ("D", "D(Is=2.52n Rs=0.568 N=1.752 Cjo=4p Tt=20n Bv=100)"),
    "LED_RED": ("D", "D(Is=1e-21 N=2.2 Rs=4)"),
    "LED_GREEN": ("D", "D(Is=1e-22 N=2.4 Rs=4)"),
    "LED_BLUE": ("D", "D(Is=1e-23 N=3.2 Rs=6)"),
    "LED_YELLOW": ("D", "D(Is=1e-21 N=2.3 Rs=4)"),
    "LED_WHITE": ("D", "D(Is=1e-23 N=3.4 Rs=6)"),
    "LED_ORANGE": ("D", "D(Is=1e-21 N=2.1 Rs=4)"),
    "2N3904": (
        "NPN",
        "NPN(Is=6.7f Bf=300 Vaf=100 Cje=4.5p Cjc=3.5p Tf=400p)",
    ),
    "2N2222": (
        "NPN",
        "NPN(Is=14.3f Bf=256 Vaf=74 Cje=22p Cjc=7.3p Tf=411p)",
    ),
    "2N3906": (
        "PNP",
        "PNP(Is=1.4f Bf=180 Vaf=20 Cje=10p Cjc=4p Tf=400p)",
    ),
    "2N7000": ("NMOS", "NMOS(Vto=2.1 Kp=0.17 Lambda=0.02 Rd=1 Rs=1)"),
    "BS250": ("PMOS", "PMOS(Vto=-2.5 Kp=0.05 Lambda=0.02 Rd=1 Rs=1)"),
    "2N3819": ("NJF", "NJF(Vto=-3 Beta=1.3m Lambda=2.5m Is=10f)"),
    "2N5460": ("PJF", "PJF(Vto=-2 Beta=1.5m Lambda=5m Is=10f)"),
}

# Editable card numbers, in panel order. fallback is the generic SPICE
# value used when a card does not list that number. It is left off the
# written card until the user types something else.
_DEVICE_PARAMETER_SPECS = {
    "diode": (
        ("is", "Is", "IS", "A", "positive", "10f"),
        ("n", "N", "N", "", "positive", "1"),
        ("rs", "Rs", "RS", "ohm", "nonnegative", "0"),
        ("cjo", "Cjo", "CJO", "F", "nonnegative", "0"),
        ("tt", "Tt", "TT", "s", "nonnegative", "0"),
        ("bv", "Bv", "BV", "V", "positive", "100"),
        ("ibv", "Ibv", "IBV", "A", "positive", "1m"),
    ),
    "npn": (
        ("bf", "Bf", "BF", "", "positive", "100"),
        ("vaf", "Vaf", "VAF", "V", "positive", "100"),
        ("cje", "Cje", "CJE", "F", "nonnegative", "0"),
        ("cjc", "Cjc", "CJC", "F", "nonnegative", "0"),
        ("tr", "Tr", "TR", "s", "nonnegative", "0"),
        ("tf", "Tf", "TF", "s", "nonnegative", "0"),
        ("rb", "Rb", "RB", "ohm", "nonnegative", "0"),
        ("re", "Re", "RE", "ohm", "nonnegative", "0"),
        ("rc", "Rc", "RC", "ohm", "nonnegative", "0"),
    ),
    "nmos": (
        ("level", "Level", "Level", "", "whole", "1"),
        ("vto", "Vto", "VTO", "V", "any", "0"),
        ("kp", "Kp", "KP", "", "positive", "20u"),
        ("tox", "Tox", "TOX", "m", "positive", "100n"),
        ("u0", "U0", "U0", "", "positive", "600"),
    ),
    "njfet": (
        ("vt0", "Vto", "VTO", "V", "any", "-2"),
        ("beta", "Beta", "BETA", "", "positive", "100u"),
        ("lambda", "Lambda", "LAMBDA", "", "nonnegative", "0"),
        ("is", "Is", "IS", "A", "positive", "10f"),
    ),
}
_DEVICE_PARAMETER_SPECS["pnp"] = _DEVICE_PARAMETER_SPECS["npn"]
_DEVICE_PARAMETER_SPECS["pmos"] = _DEVICE_PARAMETER_SPECS["nmos"]
_DEVICE_PARAMETER_SPECS["pjfet"] = _DEVICE_PARAMETER_SPECS["njfet"]

_PARAMETER_PATTERN = re.compile(r"([A-Za-z][A-Za-z0-9]*)=([^\s)]+)")

# Part kind to the device kind its model must be.
DEVICE_KIND_BY_PART = {
    "diode": "D",
    "led": "D",
    "npn": "NPN",
    "pnp": "PNP",
    "nmos": "NMOS",
    "pmos": "PMOS",
    "njfet": "NJF",
    "pjfet": "PJF",
}


def known_device_model_names():
    """
    Return the model names in display order.

    :rtype: tuple
    """
    return tuple(_DEVICE_MODELS)


def get_device_model(name):
    """
    Return (canonical name, device kind, parameter text) for one model.

    :param name: Model name, case ignored.
    :type name: str
    :rtype: tuple
    :raises SimulationError: If the name is not in the library.
    """
    if not isinstance(name, str):
        raise SimulationError(
            f"A model name must be text, not {name!r}."
        )

    for model_name, (device_kind, parameters) in _DEVICE_MODELS.items():
        if model_name.lower() == name.strip().lower():
            return (model_name, device_kind, parameters)

    known = ", ".join(_DEVICE_MODELS)
    raise SimulationError(
        f"No model named {name!r}. Known models: {known}."
    )


def device_model_line(name):
    """
    Return the ``.model`` line for one device.

    :param name: Model name, case ignored.
    :type name: str
    :rtype: str
    :raises SimulationError: If the name is not in the library.
    """
    model_name, _device_kind, parameters = get_device_model(name)

    return f".model {model_name} {parameters}"


def device_parameter_specs(kind):
    """
    Return the editable card numbers for one part kind.

    :param kind: Component kind, for example "diode".
    :type kind: str
    :returns: Tuples of (name, spice name, label, unit, value kind,
        generic fallback). Empty when this kind's card is fixed.
    :rtype: tuple
    """
    return _DEVICE_PARAMETER_SPECS.get(kind, ())


def default_parameter_text(model_name, spice_name, fallback):
    """
    Return the text to show for one card number.

    A known model uses the number on its card. A missing number, or a
    model that is not in the library, uses the generic fallback.

    :param model_name: Model name, case ignored.
    :type model_name: str
    :param spice_name: Card name, for example "Is".
    :type spice_name: str
    :param fallback: Generic text, for example "10f".
    :type fallback: str
    :rtype: str
    """
    library = _library_numbers(model_name)

    if library is None or spice_name.lower() not in library:
        return fallback

    return format_spice_number(library[spice_name.lower()])


def values_match_model(kind, model_name, values):
    """
    Return whether these numbers are still the model's own card.

    :param kind: Component kind.
    :type kind: str
    :param model_name: Model name, case ignored.
    :type model_name: str
    :param values: Parsed setting values by name.
    :type values: dict
    :rtype: bool
    """
    specs = device_parameter_specs(kind)

    if not specs:
        return True

    library = _library_numbers(model_name)

    if library is None:
        return False

    for name, spice_name, _label, _unit, _value_kind, fallback in specs:
        if spice_name.lower() in library:
            target = library[spice_name.lower()]
        else:
            target = parse_value(fallback)

        if not _close(values[name], target):
            return False

    return True


def cards_for_parts(parts):
    """
    Return the model name each part should use, and the ``.model`` lines.

    Every part that still has its library numbers shares that library
    line. A typed number rewrites the card. Two different sets of
    numbers for one model name become two cards; the changed one is
    named after the part, for example ``1N4148_D2``.

    :param parts: Placed parts.
    :type parts: iterable
    :returns: ``(name_by_reference, lines)``.
    :rtype: tuple
    """
    groups = {}
    order = []

    for part in parts:
        if part.kind not in DEVICE_KIND_BY_PART:
            continue

        canonical = get_device_model(part.value_text)[0]
        signature = _change_signature(part)
        key = (canonical, signature)

        if key not in groups:
            groups[key] = []
            order.append(key)

        groups[key].append(part)

    keys_for_name = {}

    for canonical, signature in order:
        keys_for_name.setdefault(canonical, []).append(
            (canonical, signature)
        )

    chosen_name = {}

    for canonical, keys in keys_for_name.items():
        if len(keys) == 1:
            chosen_name[keys[0]] = canonical
            continue

        for key in keys:
            if key[1] is None:
                chosen_name[key] = canonical
            else:
                chosen_name[key] = (
                    f"{canonical}_{groups[key][0].reference}"
                )

    names = {}
    lines = []

    for key in order:
        card_name = chosen_name[key]
        part = groups[key][0]

        if key[1] is None:
            lines.append(device_model_line(key[0]))
        else:
            lines.append(_rewritten_card(card_name, part))

        for member in groups[key]:
            names[member.reference] = card_name

    return names, lines


def _library_numbers(model_name):
    """
    Return the card numbers for one library model, or None.

    :rtype: dict or None
    """
    try:
        _model_name, _device_kind, parameter_text = get_device_model(
            model_name
        )
    except SimulationError:
        return None

    numbers = {}

    for spice_name, value_text in _PARAMETER_PATTERN.findall(parameter_text):
        numbers[spice_name.lower()] = parse_value(value_text)

    return numbers


def _close(left, right):
    """
    Return whether two card numbers are the same for this purpose.

    :rtype: bool
    """
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-30)


def _change_signature(part):
    """
    Return None when the part still matches its library card.

    Otherwise return the formatted numbers, so two parts with the same
    typed values share one card.

    :rtype: tuple or None
    """
    if values_match_model(part.kind, part.value_text, part.parameter_values):
        return None

    specs = device_parameter_specs(part.kind)

    return tuple(
        (spice_name, format_spice_number(part.parameter_values[name]))
        for name, spice_name, _label, _unit, _value_kind, _fallback in specs
    )


def _rewritten_card(card_name, part):
    """
    Return a ``.model`` line with this part's numbers filled in.

    Numbers the library card already has keep their place. A generic
    number that is still the fallback is left off.

    :rtype: str
    """
    _model_name, device_kind, parameter_text = get_device_model(
        part.value_text
    )
    pairs = _PARAMETER_PATTERN.findall(parameter_text)
    by_lower = {spice_name.lower(): index for index, (spice_name, _value)
                in enumerate(pairs)}
    rendered = [(spice_name, value_text) for spice_name, value_text in pairs]

    for name, spice_name, _label, _unit, _value_kind, fallback in (
            device_parameter_specs(part.kind)):
        value = part.parameter_values[name]
        text = format_spice_number(value)
        key = spice_name.lower()

        if key in by_lower:
            index = by_lower[key]
            rendered[index] = (rendered[index][0], text)
            continue

        if _close(value, parse_value(fallback)):
            continue

        rendered.append((spice_name, text))

    inside = " ".join(f"{spice_name}={value}" for spice_name, value in rendered)

    return f".model {card_name} {device_kind}({inside})"
