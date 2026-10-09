"""
Tests for core.units.parse_value.
"""

import time

import pytest

from core.exceptions import CircuitWorkbenchError, ComponentError
from core.units import SI_PREFIX_EXPONENTS, parse_value


@pytest.mark.parametrize(
    "value_text, expected_value",
    [
        ("4k7", 4700.0),
        ("10u", 1e-05),
        ("100n", 1e-07),
        ("1meg", 1e6),
        ("1MEG", 1e6),
        ("2.2m", 0.0022),
        ("1k", 1000.0),
        ("1K", 1000.0),
        ("47", 47.0),
        ("0.5", 0.5),
        ("-5", -5.0),
        ("1e3", 1000.0),
        ("2u2", 2.2e-06),
        ("4r7", 4.7),
        ("10p", 1e-11),
        (" 3.3k ", 3300.0),
        ("10\u00b5", 1e-05),
        ("10\u03bc", 1e-05),
        ("2\u03bc2", 2.2e-06),
        ("1Meg", 1e6),
        ("-4k7", -4700.0),
        ("4R7", 4.7),
        ("1e3k", 1e6),
        (".5", 0.5),
    ]
)
def test_parse_value_accepts_valid_text(value_text, expected_value):
    # Exact comparison is intended: the parser converts one decimal string.
    assert parse_value(value_text) == expected_value


@pytest.mark.parametrize(
    "value_text",
    [
        "", "abc", "k", "1M", "4k7k", "1.2.3", "10uF", "5V", "1kk",
        # float() would accept these, the parser must not.
        "nan", "inf", "-inf", "1_000", "1 k",
        # Ambiguous "M" in the 4k7 form, and Greek capital Mu (U+039C),
        # which looks exactly like "M".
        "4M7", "1\u039c", "4\u039c7",
        # Non-ASCII digits: Arabic-Indic 1 and fullwidth 1.
        "\u0661k", "\uff11k",
        # Overflow and underflow.
        "1e400", "1e999t", "1e-400",
        # Too long, including an exponent past Python's int() digit limit.
        "1e" + "1" * 5000, "1" * 100,
    ],
    ids=lambda value_text: repr(value_text)[:30]
)
def test_parse_value_rejects_invalid_text(value_text):
    with pytest.raises(ComponentError):
        parse_value(value_text)


def test_error_message_quotes_input_and_explains_format():
    with pytest.raises(ComponentError) as error_info:
        parse_value("10uF")

    assert "'10uF'" in str(error_info.value)
    assert "meg" in str(error_info.value)


def test_uppercase_m_message_suggests_alternatives():
    with pytest.raises(ComponentError) as error_info:
        parse_value("1M")

    assert "'meg'" in str(error_info.value)


def test_component_error_uses_application_base_class():
    assert issubclass(ComponentError, CircuitWorkbenchError)


def test_prefix_table_has_expected_exponents():
    assert SI_PREFIX_EXPONENTS["k"] == 3
    assert SI_PREFIX_EXPONENTS["meg"] == 6
    assert SI_PREFIX_EXPONENTS["m"] == -3
    assert SI_PREFIX_EXPONENTS["u"] == -6


@pytest.mark.parametrize("value_object", [None, 5, 5.0, b"1k", True])
def test_parse_value_rejects_non_text(value_object):
    with pytest.raises(ComponentError):
        parse_value(value_object)


def test_long_input_is_rejected_quickly():
    # A pasted long string must not freeze the GUI thread.
    start_time = time.perf_counter()

    with pytest.raises(ComponentError):
        parse_value("1" * 20000 + "x")

    assert time.perf_counter() - start_time < 0.5


def test_error_message_lists_both_micro_characters():
    with pytest.raises(ComponentError) as error_info:
        parse_value("abc")

    assert "\u00b5" in str(error_info.value)
    assert "\u03bc" in str(error_info.value)


def test_underflow_message_says_too_small():
    with pytest.raises(ComponentError) as error_info:
        parse_value("1e-400")

    assert "too small" in str(error_info.value)


def test_zero_is_still_accepted():
    assert parse_value("0") == 0.0
    assert parse_value("0e-400") == 0.0


def test_greek_capital_mu_gets_the_ambiguous_m_advice():
    with pytest.raises(ComponentError) as error_info:
        parse_value("1\u039c")

    assert "'meg'" in str(error_info.value)
