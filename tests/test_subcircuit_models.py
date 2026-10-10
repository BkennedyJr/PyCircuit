"""
Tests for core.subcircuit_models (pure Python, no Qt).
"""

import hashlib
import re
import subprocess
import sys

import pytest

from core import subcircuit_models
from core.exceptions import ComponentError
from core.subcircuit_models import (
    DEFAULT_SUBCIRCUIT_BY_KIND,
    LM741_SHA256,
    SPICE_LIBRARY_DIRECTORY,
    SUBCIRCUIT_MODELS,
    SUBCIRCUIT_PORT_ORDER,
    build_instance_line,
    get_subcircuit_model_name,
    get_subcircuit_text,
    read_lm741_file,
)

NODES = {"in+": "0", "in-": "N_R02_C03", "out": "N_R03_C05",
         "V+": "N_R01_C04", "V-": "N_R05_C04"}


def test_module_does_not_import_qt():
    code = (
        "import sys, core.subcircuit_models; "
        "print(any(name.startswith('PyQt') for name in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        check=True
    )
    assert result.stdout.strip() == "False"


def test_library_and_defaults():
    assert list(SUBCIRCUIT_MODELS)[:2] == ["OPAMP", "LM741"]
    assert {
        "LM358", "TL072", "NE5532", "COMP", "NOT", "BUF", "AND2", "OR2",
        "NAND2", "NOR2", "XOR2", "FOLLOW", "INVAMP", "NONINV",
    } <= set(SUBCIRCUIT_MODELS)
    assert DEFAULT_SUBCIRCUIT_BY_KIND["opamp_generic"] == "OPAMP"
    assert DEFAULT_SUBCIRCUIT_BY_KIND["opamp_741"] == "LM741"
    assert DEFAULT_SUBCIRCUIT_BY_KIND["gate_and"] == "AND2"
    assert DEFAULT_SUBCIRCUIT_BY_KIND["inverting_amp"] == "INVAMP"
    assert SUBCIRCUIT_PORT_ORDER == ("in+", "in-", "V+", "V-", "out")
    assert SUBCIRCUIT_MODELS["LM741"]["license"].startswith("CC BY 4.0")
    assert "logipipe.com/LM741.txt" in SUBCIRCUIT_MODELS["LM741"]["source"]


@pytest.mark.parametrize("name, expected", [
    ("OPAMP", "OPAMP"), ("opamp", "OPAMP"), ("lm741", "LM741"),
    (" LM741 ", "LM741"),
])
def test_names_ignore_case(name, expected):
    assert get_subcircuit_model_name(name) == expected


def test_unknown_name_lists_the_known_models():
    with pytest.raises(
        ComponentError,
        match=r"^No subcircuit model named 'LM324'\."
    ):
        get_subcircuit_model_name("LM324")


def test_name_must_be_text():
    with pytest.raises(ComponentError, match="must be text, not 741"):
        get_subcircuit_model_name(741)


def test_lm741_file_is_the_published_file_unchanged():
    data = (SPICE_LIBRARY_DIRECTORY / "LM741_logipipe.lib").read_bytes()

    assert hashlib.sha256(data).hexdigest() == LM741_SHA256
    assert b"\r" not in data
    text = read_lm741_file()
    assert "Creative Commons CC BY 4.0" in text
    assert "Copyright (c) 2018-2020 Logipipe, LLC" in text


def test_changed_lm741_file_is_refused(monkeypatch):
    monkeypatch.setattr(subcircuit_models, "LM741_SHA256", "0" * 64)

    with pytest.raises(ComponentError, match="was changed"):
        read_lm741_file()


def test_missing_lm741_file_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(subcircuit_models, "SPICE_LIBRARY_DIRECTORY", tmp_path)

    with pytest.raises(ComponentError, match="model file is missing"):
        read_lm741_file()


def test_generic_subcircuit_text():
    text = get_subcircuit_text("opamp")

    assert ".subckt OPAMP inp inn vp vn out" in text
    assert "RIN inp inn 1meg" in text
    assert "EGAIN gain_node 0 inp inn 100k" in text
    assert "ROUT gain_node out 75" in text
    assert "RVP vp 0 1T" in text and "RVN vn 0 1T" in text
    assert text.endswith(".ends OPAMP\n")


def test_lm741_text_wraps_the_published_model():
    text = get_subcircuit_text("LM741")

    assert ".subckt LM741 inp inn vp vn out" in text
    assert "XLOGIPIPE inp inn vp vn out U1$LM741.lcs" in text
    assert text.endswith(read_lm741_file())


def test_instance_line_uses_the_port_order():
    assert build_instance_line("X1", "opamp", NODES) == (
        "X1 0 N_R02_C03 N_R01_C04 N_R05_C04 N_R03_C05 OPAMP"
    )


def test_generic_supply_pins_are_optional():
    nodes = {"in+": "0", "in-": "N1", "out": "N2"}

    assert build_instance_line("X3", "OPAMP", nodes) == (
        "X3 0 N1 X3_VP_NC X3_VN_NC N2 OPAMP"
    )


@pytest.mark.parametrize("missing", ["V+", "V-"])
def test_lm741_needs_both_supplies(missing):
    nodes = dict(NODES)
    del nodes[missing]

    with pytest.raises(
        ComponentError,
        match=r"^X2 \(LM741\) needs both supply pins connected: wire V\+ "
              r"and V- to the supply rails\.$"
    ):
        build_instance_line("X2", "LM741", nodes)


@pytest.mark.parametrize("missing", ["in+", "in-", "out"])
def test_signal_pins_are_required(missing):
    nodes = dict(NODES)
    del nodes[missing]

    with pytest.raises(
        ComponentError, match=re.escape(f"pin {missing} is not connected")
    ):
        build_instance_line("X1", "OPAMP", nodes)


@pytest.mark.parametrize("reference", ["R1", "X", "", None, "x1"])
def test_reference_must_start_with_x(reference):
    with pytest.raises(ComponentError, match="must start with X"):
        build_instance_line(reference, "OPAMP", NODES)


def test_unknown_pin_is_refused():
    with pytest.raises(ComponentError, match="X1 has no pin 'gain'"):
        build_instance_line("X1", "OPAMP", {**NODES, "gain": "N9"})


@pytest.mark.parametrize("node", ["", "N 1", 5])
def test_nodes_must_be_net_names(node):
    with pytest.raises(ComponentError, match="must be a net name"):
        build_instance_line("X1", "OPAMP", {**NODES, "out": node})


def test_pin_nodes_must_be_a_dict():
    with pytest.raises(ComponentError, match="pin nodes must be a dict"):
        build_instance_line("X1", "OPAMP", [("out", "N1")])
