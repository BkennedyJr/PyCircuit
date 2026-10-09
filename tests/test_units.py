"""
Tests for core.units.parse_value.
"""

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
    ]
)
def test_parse_value_accepts_valid_text(value_text, expected_value):
    # Exact comparison is intended: the parser converts one decimal string.
    assert parse_value(value_text) == expected_value


@pytest.mark.parametrize(
    "value_text",
    ["", "abc", "k", "1M", "4k7k", "1.2.3", "10uF", "5V", "1kk"]
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
