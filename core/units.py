"""
Engineering-value parsing for component values.

This module converts user-entered component values such as ``4k7``,
``10u``, ``100n``, ``1meg``, or ``2.2m`` into floating-point numbers. It
contains no PyQt5 imports so the same parser can be used by the GUI, the
netlist writer, and the later solver.
"""

import math
import re

from core.exceptions import ComponentError

# Decimal exponent for each accepted SI prefix. Prefix matching is
# case-insensitive, except that a lone uppercase "M" is rejected because
# SPICE reads it as milli while most people mean mega.
SI_PREFIX_EXPONENTS = {
    "f": -15,
    "p": -12,
    "n": -9,
    "u": -6,
    "\u00b5": -6,
    "\u03bc": -6,
    "m": -3,
    "k": 3,
    "meg": 6,
    "g": 9,
    "t": 12,
}

# Longest accepted value text after stripping whitespace. Real values are
# short; the cap keeps pasted garbage from reaching the regular expressions.
MAXIMUM_VALUE_TEXT_LENGTH = 64

# Letter used in the "4r7" form to mark the decimal point with a scale of 1.
RKM_UNITY_LETTER = "r"

ALLOWED_VALUE_DESCRIPTION = (
    "Use a number with an optional SI prefix, for example 4700, 4.7k, 4k7, "
    "10u, 100n, 2.2m, or 1meg. Accepted prefixes: f, p, n, "
    "u (or \u00b5 or \u03bc), m, k, meg, g, t. Do not add unit letters "
    "such as F, H, V, A, or Ohm."
)

# Plain number: optional sign, ASCII digits with an optional decimal point,
# an optional exponent of at most four digits, then an optional SI prefix.
# Case variants are listed explicitly instead of using re.IGNORECASE,
# because Unicode case folding would map Greek capital Mu (U+039C, which
# looks exactly like "M") onto the micro sign. "meg" is listed before the
# single letters so that "1meg" is not read as "1m" followed by "eg". The
# mantissa alternatives do not overlap, which keeps failed matches fast.
_PLAIN_VALUE_PATTERN = re.compile(
    r"(?P<sign>[+-]?)"
    r"(?P<mantissa>[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
    r"(?:[eE](?P<exponent>[+-]?[0-9]{1,4}))?"
    r"(?P<prefix>[mM][eE][gG]|[fFpPnNuUmMkKgGtT\u00b5\u03bc])?"
)

# "4k7" form: ASCII digits, one prefix letter (or "r") in place of the
# decimal point, then ASCII digits.
_RKM_VALUE_PATTERN = re.compile(
    r"(?P<sign>[+-]?)"
    r"(?P<whole>[0-9]+)"
    r"(?P<letter>[fFpPnNuUmMkKgGtTrR\u00b5\u03bc])"
    r"(?P<fraction>[0-9]+)"
)


def _build_value_error(value_text, reason):
    """
    Build a ComponentError that quotes the input and explains the format.

    :param value_text: Original user-entered value text.
    :type value_text: str
    :param reason: Short explanation of what is wrong.
    :type reason: str
    :returns: Exception ready to raise.
    :rtype: ComponentError
    """
    return ComponentError(
        f"Invalid value '{value_text}': {reason} "
        f"{ALLOWED_VALUE_DESCRIPTION}"
    )


def _convert_decimal_text(value_text, decimal_text):
    """
    Convert a decimal string such as "4.7e3" into a finite float.

    Building one decimal string and converting it once keeps results exact
    where possible: float("4.7e3") == 4700.0, whereas 4.7 * 1000 and
    10 * 1e-6 can carry rounding errors.

    :param value_text: Original user-entered value text, for messages.
    :type value_text: str
    :param decimal_text: Decimal string to convert.
    :type decimal_text: str
    :returns: Converted value.
    :rtype: float
    :raises ComponentError: If the value is too large or too small.
    """
    converted_value = float(decimal_text)

    # Reject overflow such as "1e999t" instead of returning infinity.
    if not math.isfinite(converted_value):
        raise _build_value_error(value_text, "the value is out of range.")

    # Reject underflow such as "1e-400": a nonzero mantissa that converts
    # to 0.0 would otherwise silently become zero.
    mantissa_text = decimal_text.lower().split("e")[0]

    if converted_value == 0.0 and any(
            digit in mantissa_text for digit in "123456789"):
        raise _build_value_error(value_text, "the value is too small.")

    return converted_value


def parse_value(value_text):
    """
    Parse a component value with an optional SI prefix into a float.

    Accepted examples: "4k7" -> 4700.0, "10u" -> 1e-05, "100n" -> 1e-07,
    "1meg" -> 1000000.0, "2.2m" -> 0.0022, "4r7" -> 4.7, "-5" -> -5.0,
    "1e3" -> 1000.0.

    :param value_text: User-entered value text.
    :type value_text: str
    :returns: Parsed numeric value.
    :rtype: float
    :raises ComponentError: If the text is empty, ambiguous, or invalid.
    """
    if not isinstance(value_text, str):
        raise ComponentError(
            f"Invalid value {value_text!r}: the value must be text. "
            f"{ALLOWED_VALUE_DESCRIPTION}"
        )

    cleaned_text = value_text.strip()

    if not cleaned_text:
        raise _build_value_error(value_text, "the value is empty.")

    # Refuse very long text before any pattern matching runs.
    if len(cleaned_text) > MAXIMUM_VALUE_TEXT_LENGTH:
        raise _build_value_error(
            value_text[:40] + "...",
            "the value is too long."
        )

    # Greek capital Mu (U+039C) looks exactly like "M", for example in text
    # pasted from a PDF. Reject it with the same advice as a plain "M".
    if "\u039c" in cleaned_text:
        raise _build_value_error(
            value_text,
            "'\u039c' (Greek capital Mu) looks like 'M', which is ambiguous. "
            "Use 'm' for milli, 'meg' for mega, or 'u' for micro."
        )

    # Try the ordinary "number plus optional prefix" form first.
    plain_match = _PLAIN_VALUE_PATTERN.fullmatch(cleaned_text)

    if plain_match is not None:
        prefix_text = plain_match.group("prefix") or ""

        # SPICE reads "M" as milli, while most people mean mega. Refuse to
        # guess so that a 1 megohm resistor never silently becomes 1 milliohm.
        if prefix_text == "M":
            raise _build_value_error(
                value_text,
                "'M' is ambiguous. Use 'm' for milli or 'meg' for mega."
            )

        total_exponent = (
            int(plain_match.group("exponent") or "0") +
            SI_PREFIX_EXPONENTS.get(prefix_text.lower(), 0)
        )

        sign_text = plain_match.group("sign")
        mantissa_text = plain_match.group("mantissa")

        return _convert_decimal_text(
            value_text,
            f"{sign_text}{mantissa_text}e{total_exponent}"
        )

    # Then try the "4k7" form, where the letter is the decimal point.
    rkm_match = _RKM_VALUE_PATTERN.fullmatch(cleaned_text)

    if rkm_match is not None:
        letter_text = rkm_match.group("letter")

        if letter_text == "M":
            raise _build_value_error(
                value_text,
                "'M' is ambiguous. Use 'm' for milli or 'meg' for mega."
            )

        if letter_text.lower() == RKM_UNITY_LETTER:
            letter_exponent = 0
        else:
            letter_exponent = SI_PREFIX_EXPONENTS[letter_text.lower()]

        sign_text = rkm_match.group("sign")
        whole_text = rkm_match.group("whole")
        fraction_text = rkm_match.group("fraction")

        return _convert_decimal_text(
            value_text,
            f"{sign_text}{whole_text}.{fraction_text}e{letter_exponent}"
        )

    raise _build_value_error(
        value_text,
        "it is not a number with an optional SI prefix."
    )


# SPICE suffix for each power of 1000. Mega is "meg", never "M" (SPICE
# reads a lone M as milli).
_SPICE_PREFIXES = (
    (-15, "f"),
    (-12, "p"),
    (-9, "n"),
    (-6, "u"),
    (-3, "m"),
    (0, ""),
    (3, "k"),
    (6, "meg"),
    (9, "g"),
    (12, "t"),
)


def format_spice_number(number):
    """
    Format a parsed value the way SPICE expects it.

    4700 becomes ``4.7k``, 1e-7 becomes ``100n``, and 1e6 becomes
    ``1meg``. A lone ``M`` is never used.

    :param number: Parsed value, such as 4700.0 or 1e-7.
    :type number: int or float
    :returns: SPICE number text.
    :rtype: str
    :raises ComponentError: If number is not a finite int or float.
    """
    if (isinstance(number, bool) or
            not isinstance(number, (int, float)) or
            not math.isfinite(number)):
        raise ComponentError(
            f"A SPICE number must be a finite number, not {number!r}."
        )

    if number == 0:
        return "0"

    sign = "-" if number < 0 else ""
    magnitude = abs(float(number))
    # A hair over the exact power of ten keeps 1000 from landing in the
    # bucket below because of a float such as 999.999999999.
    exponent = math.floor(math.log10(magnitude * (1 + 1e-12)))
    prefix_exponent = math.floor(exponent / 3.0) * 3
    prefix_exponent = max(-15, min(12, prefix_exponent))
    mantissa = magnitude / (10 ** prefix_exponent)

    if mantissa >= 999.9995 and prefix_exponent < 12:
        mantissa /= 1000.0
        prefix_exponent += 3

    prefix = dict(_SPICE_PREFIXES)[prefix_exponent]
    text = f"{mantissa:.6g}"

    return f"{sign}{text}{prefix}"
