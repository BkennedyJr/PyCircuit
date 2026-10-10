"""
SPICE subcircuit models for parts with the prefix X (the op-amps).

Pure Python, no Qt. Each model is a five-port subcircuit with the ports in
SUBCIRCUIT_PORT_ORDER (in+ in- V+ V- out, the usual op-amp order) and the
text that defines it. The later netlist builder (M3) writes one instance
line per part with build_instance_line() and each used model's text once
with get_subcircuit_text().

Models:

OPAMP (opamp_generic): behavioural. Input resistance 1 Mohm between in+ and
in-, a voltage-controlled voltage source with gain 100k, and 75 ohm output
resistance. It has no supply limits, so the output can swing past the
rails. V+ and V- are optional: each is tied to ground through 1 Tohm inside
the subcircuit, so an unconnected supply pin does not float.

LM741 (opamp_741): the LM741 model published by Logipipe, LLC under
CC BY 4.0 (https://www.logipipe.com/LM741.txt; see
core/spice_library/README.txt). The file is kept unchanged and wrapped in
a subcircuit named LM741 with the standard port order. It needs both
supplies: V+ and V- must be connected.

LM358, TL072 and NE5532 are behavioural stand-ins written for PyCircuit
(gain, input resistance and output resistance in the neighbourhood of the
real parts). They are not transistor-level manufacturer models, and they
need both supplies.

Logic gates and the comparator are behavioural too: the output sits on
one rail or the other. Gates use ports A, B, Y, VCC and GND (a NOT gate
and a buffer have no B). FOLLOW, INVAMP and NONINV wrap the generic
OPAMP as a voltage follower, an inverting amplifier and a non-inverting
amplifier. INVAMP and NONINV take a gain parameter.
"""

import hashlib
from pathlib import Path

from core.exceptions import ComponentError

SUBCIRCUIT_PORT_ORDER = ("in+", "in-", "V+", "V-", "out")
SUPPLY_PINS = ("V+", "V-")

SPICE_LIBRARY_DIRECTORY = Path(__file__).resolve().parent / "spice_library"
LM741_FILE_NAME = "LM741_logipipe.lib"
LM741_SHA256 = (
    "a32985cf78ac579c344ebe64e3b159b922728258c9dad366da598f51f25edea8"
)
LM741_INNER_SUBCIRCUIT = "U1$LM741.lcs"

GENERIC_OPAMP_GAIN = 100e3
GENERIC_OPAMP_INPUT_RESISTANCE = 1e6
GENERIC_OPAMP_OUTPUT_RESISTANCE = 75.0

_GENERIC_OPAMP_TEXT = """\
* OPAMP: PyCircuit generic op-amp (behavioural, no supply limits).
* Ports: in+ in- V+ V- out. Open-loop gain 100k, Rin 1meg, Rout 75.
* V+ and V- are optional: 1T to ground keeps them from floating.
.subckt OPAMP inp inn vp vn out
RIN inp inn 1meg
EGAIN gain_node 0 inp inn 100k
ROUT gain_node out 75
RVP vp 0 1T
RVN vn 0 1T
.ends OPAMP
"""

_LM741_WRAPPER_TEXT = """\
* LM741: five-port wrapper (in+ in- V+ V- out) around the Logipipe model.
* LM741 SPICE model Copyright (c) 2018-2020 Logipipe, LLC, CC BY 4.0,
* https://www.logipipe.com/LM741.txt, included unchanged below.
.subckt LM741 inp inn vp vn out
XLOGIPIPE inp inn vp vn out U1$LM741.lcs
.ends LM741
"""


def _behavioral_opamp(name, gain, rin, rout, blurb):
    """
    A flat-gain op-amp subcircuit. Supplies must be wired by the caller.

    :rtype: str
    """
    return (
        f"* {name}: {blurb} PyCircuit behavioural model, not a vendor netlist.\n"
        f"* Ports: in+ in- V+ V- out.\n"
        f".subckt {name} inp inn vp vn out\n"
        f"RIN inp inn {rin}\n"
        f"EGAIN gain_node 0 inp inn {gain}\n"
        f"ROUT gain_node out {rout}\n"
        f".ends {name}\n"
    )


def _logic_gate(name, ports, expression, blurb):
    """
    A behavioural gate. ``expression`` is the output voltage.

    :rtype: str
    """
    port_text = " ".join(port.lower() for port in ports)

    return (
        f"* {name}: {blurb}\n"
        f"* Output sits on VCC or GND. Threshold is halfway between them.\n"
        f".subckt {name} {port_text}\n"
        f"BY y 0 V = {expression}\n"
        f".ends {name}\n"
    )


_MID = "(V(vcc)+V(gnd))/2"
_HIGH = "V(gnd)+(V(vcc)-V(gnd))"
_ABOVE_A = f"u(V(a)-{_MID})"
_ABOVE_B = f"u(V(b)-{_MID})"

_SUBCIRCUIT_TEXT = {
    "LM358": _behavioral_opamp(
        "LM358", "100k", "1meg", "50",
        "General-purpose stand-in (gain 100k, Rin 1meg, Rout 50)."
    ),
    "TL072": _behavioral_opamp(
        "TL072", "200k", "1T", "75",
        "JFET-input stand-in (gain 200k, Rin 1T, Rout 75)."
    ),
    "NE5532": _behavioral_opamp(
        "NE5532", "100k", "300k", "10",
        "Audio stand-in (gain 100k, Rin 300k, Rout 10)."
    ),
    "COMP": """\
* COMP: comparator. Output is V+ when in+ is above in-, otherwise V-.
* Ports: in+ in- V+ V- out. Behavioural, no vendor model.
.subckt COMP inp inn vp vn out
BOUT out 0 V = V(vn)+(V(vp)-V(vn))*u(V(inp)-V(inn))
.ends COMP
""",
    "NOT": _logic_gate(
        "NOT", ("A", "Y", "VCC", "GND"),
        f"{_HIGH}*u({_MID}-V(a))",
        "NOT gate."
    ),
    "BUF": _logic_gate(
        "BUF", ("A", "Y", "VCC", "GND"),
        f"{_HIGH}*{_ABOVE_A}",
        "Non-inverting buffer gate."
    ),
    "AND2": _logic_gate(
        "AND2", ("A", "B", "Y", "VCC", "GND"),
        f"{_HIGH}*{_ABOVE_A}*{_ABOVE_B}",
        "2-input AND gate."
    ),
    "OR2": _logic_gate(
        "OR2", ("A", "B", "Y", "VCC", "GND"),
        f"{_HIGH}*(1-(1-{_ABOVE_A})*(1-{_ABOVE_B}))",
        "2-input OR gate."
    ),
    "NAND2": _logic_gate(
        "NAND2", ("A", "B", "Y", "VCC", "GND"),
        f"{_HIGH}*(1-{_ABOVE_A}*{_ABOVE_B})",
        "2-input NAND gate."
    ),
    "NOR2": _logic_gate(
        "NOR2", ("A", "B", "Y", "VCC", "GND"),
        f"{_HIGH}*(1-{_ABOVE_A})*(1-{_ABOVE_B})",
        "2-input NOR gate."
    ),
    "XOR2": _logic_gate(
        "XOR2", ("A", "B", "Y", "VCC", "GND"),
        f"{_HIGH}*({_ABOVE_A}+{_ABOVE_B}-2*{_ABOVE_A}*{_ABOVE_B})",
        "2-input XOR gate."
    ),
    "FOLLOW": """\
* FOLLOW: voltage follower. The generic OPAMP is defined above this block.
* Ports: in out V+ V-.
.subckt FOLLOW inp out vp vn
XAMP inp out vp vn out OPAMP
.ends FOLLOW
""",
    "INVAMP": """\
* INVAMP: inverting amplifier. gain defaults to 10 (Rf/Rin, Rin = 10k).
* Pass gain= on the instance line. The generic OPAMP is defined above.
* Ports: in out V+ V-.
.subckt INVAMP inp out vp vn gain=10
RIN inp inn 10k
RF out inn {10k*gain}
XAMP 0 inn vp vn out OPAMP
.ends INVAMP
""",
    "NONINV": """\
* NONINV: non-inverting amplifier. gain defaults to 2 (1 + Rf/Rg, Rg = 10k).
* gain must be at least 1. The generic OPAMP is defined above.
* Ports: in out V+ V-.
.subckt NONINV inp out vp vn gain=2
RG inn 0 10k
RF out inn {10k*(gain-1)}
XAMP inp inn vp vn out OPAMP
.ends NONINV
""",
    "NE555": """\
* NE555: simplified timer for a later netlist. The three 5k resistors
* are the real divider: CONT sits at 2/3 of VCC, and the internal
* node "third" sits at 1/3. The latch, the output driver and the
* discharge transistor are not in this text. Do not treat it as a
* full 555 until a transient simulator is wired up.
* Ports: GND TRIG OUT RESET CONT THRES DISCH VCC.
.subckt NE555 GND TRIG OUT RESET CONT THRES DISCH VCC
R1 VCC CONT 5k
R2 CONT third 5k
R3 third GND 5k
.ends NE555
""",
    "REG": """\
* REG: ideal regulator. V(out) is the voltage parameter, measured from
* gnd. Dropout is ignored. The s-domain formula sets the input current
* equal to the output current; this text only holds the output voltage.
* Ports: in gnd out. Pass voltage= on the instance line.
.subckt REG inp gnd out voltage=5
VOUT out gnd {voltage}
RIN inp gnd 1T
.ends REG
""",
}

def _opamp_model(description):
    """
    A five-pin op-amp that needs both supplies.

    :rtype: dict
    """
    return {
        "description": description,
        "ports": SUBCIRCUIT_PORT_ORDER,
        "supply_pins": SUPPLY_PINS,
        "supply_pins_required": True,
        "source": "PyCircuit (behavioural VCVS model, not a vendor netlist)",
        "license": "same as PyCircuit",
    }


def _gate_model(description, ports):
    """
    A logic gate. The output is one supply rail or the other.

    :rtype: dict
    """
    return {
        "description": description,
        "ports": ports,
        "supply_pins": ("VCC", "GND"),
        "supply_pins_required": True,
        "source": "PyCircuit (behavioural logic model)",
        "license": "same as PyCircuit",
    }


_GATE_PORTS = ("A", "B", "Y", "VCC", "GND")
_INVERTER_PORTS = ("A", "Y", "VCC", "GND")
_AMP_PORTS = ("in", "out", "V+", "V-")

SUBCIRCUIT_MODELS = {
    "OPAMP": {
        "description": "Generic op-amp: gain 100k, Rin 1meg, Rout 75",
        "ports": SUBCIRCUIT_PORT_ORDER,
        "supply_pins": SUPPLY_PINS,
        "supply_pins_required": False,
        "source": "PyCircuit (behavioural VCVS model)",
        "license": "same as PyCircuit",
    },
    "LM741": {
        "description": "741 op-amp (Logipipe LM741 model)",
        "ports": SUBCIRCUIT_PORT_ORDER,
        "supply_pins": SUPPLY_PINS,
        "supply_pins_required": True,
        "source": (
            "Logipipe, LLC, LM741 SPICE Model (2020), "
            "https://www.logipipe.com/LM741.txt; reference: Fairchild "
            "Semiconductor LM741 data sheet, Rev 1.0.1 (2001)"
        ),
        "license": "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
    },
    "LM358": _opamp_model(
        "LM358 stand-in: gain 100k, Rin 1meg, Rout 50"
    ),
    "TL072": _opamp_model(
        "TL072 stand-in: gain 200k, Rin 1T, Rout 75"
    ),
    "NE5532": _opamp_model(
        "NE5532 stand-in: gain 100k, Rin 300k, Rout 10"
    ),
    "COMP": _opamp_model("Comparator: output swings to the nearer rail"),
    "NOT": _gate_model("NOT gate", _INVERTER_PORTS),
    "BUF": _gate_model("Non-inverting buffer gate", _INVERTER_PORTS),
    "AND2": _gate_model("2-input AND gate", _GATE_PORTS),
    "OR2": _gate_model("2-input OR gate", _GATE_PORTS),
    "NAND2": _gate_model("2-input NAND gate", _GATE_PORTS),
    "NOR2": _gate_model("2-input NOR gate", _GATE_PORTS),
    "XOR2": _gate_model("2-input XOR gate", _GATE_PORTS),
    "FOLLOW": {
        "description": "Voltage follower built from the generic op-amp",
        "ports": _AMP_PORTS,
        "supply_pins": SUPPLY_PINS,
        "supply_pins_required": True,
        "source": "PyCircuit",
        "license": "same as PyCircuit",
    },
    "INVAMP": {
        "description": "Inverting amplifier, gain parameter, default 10",
        "ports": _AMP_PORTS,
        "supply_pins": SUPPLY_PINS,
        "supply_pins_required": True,
        "source": "PyCircuit",
        "license": "same as PyCircuit",
    },
    "NONINV": {
        "description": "Non-inverting amplifier, gain parameter, default 2",
        "ports": _AMP_PORTS,
        "supply_pins": SUPPLY_PINS,
        "supply_pins_required": True,
        "source": "PyCircuit",
        "license": "same as PyCircuit",
    },
    "NE555": {
        "description": (
            "555 timer stand-in: the 5k divider only; latch not modelled"
        ),
        "ports": (
            "GND", "TRIG", "OUT", "RESET", "CONT", "THRES", "DISCH", "VCC"
        ),
        "supply_pins": ("VCC", "GND"),
        "supply_pins_required": True,
        "source": "PyCircuit (divider only, not a vendor 555 model)",
        "license": "same as PyCircuit",
    },
    "REG": {
        "description": "Ideal voltage regulator, voltage parameter, default 5",
        "ports": ("in", "gnd", "out"),
        "supply_pins": (),
        "supply_pins_required": False,
        "source": "PyCircuit",
        "license": "same as PyCircuit",
    },
}

DEFAULT_SUBCIRCUIT_BY_KIND = {
    "opamp_generic": "OPAMP",
    "opamp_741": "LM741",
    "opamp_lm358": "LM358",
    "opamp_tl072": "TL072",
    "opamp_ne5532": "NE5532",
    "comparator": "COMP",
    "gate_not": "NOT",
    "gate_buffer": "BUF",
    "gate_and": "AND2",
    "gate_or": "OR2",
    "gate_nand": "NAND2",
    "gate_nor": "NOR2",
    "gate_xor": "XOR2",
    "follower": "FOLLOW",
    "inverting_amp": "INVAMP",
    "noninverting_amp": "NONINV",
    "timer_555": "NE555",
    "voltage_regulator": "REG",
}


def get_subcircuit_model_name(name):
    """
    Return the library spelling of a subcircuit model name.

    The lookup ignores case, like SPICE: "lm741" finds LM741.

    :param name: Model name, for example a part's value text.
    :type name: str
    :returns: The name as spelled in SUBCIRCUIT_MODELS.
    :rtype: str
    :raises ComponentError: If the name is not text or not in the library.
    """
    if not isinstance(name, str):
        raise ComponentError(
            f"A subcircuit model name must be text, not {name!r}."
        )

    for model_name in SUBCIRCUIT_MODELS:
        if model_name.lower() == name.strip().lower():
            return model_name

    raise ComponentError(
        f"No subcircuit model named {name!r}. Known models: "
        f"{', '.join(SUBCIRCUIT_MODELS)}."
    )


def read_lm741_file():
    """
    Return the Logipipe LM741 file exactly as published.

    :returns: File text.
    :rtype: str
    :raises ComponentError: If the file is missing or was changed.
    """
    path = SPICE_LIBRARY_DIRECTORY / LM741_FILE_NAME

    try:
        data = path.read_bytes()
    except OSError as error:
        raise ComponentError(
            f"The LM741 model file is missing: {path} ({error.strerror})."
        ) from None

    if hashlib.sha256(data).hexdigest() != LM741_SHA256:
        raise ComponentError(
            f"The LM741 model file {path} was changed; restore the "
            "published Logipipe file."
        )

    return data.decode("ascii")


def get_subcircuit_text(name):
    """
    Return the SPICE text that defines one subcircuit model.

    Write it once per netlist, however many parts use it.

    :param name: Model name (case ignored).
    :type name: str
    :returns: Text ending in a newline, with .subckt ... .ends blocks.
    :rtype: str
    :raises ComponentError: If the model is unknown or its file is bad.
    """
    model_name = get_subcircuit_model_name(name)

    if model_name == "OPAMP":
        return _GENERIC_OPAMP_TEXT

    if model_name == "LM741":
        lm741_text = read_lm741_file()

        if not lm741_text.endswith("\n"):
            lm741_text += "\n"

        return _LM741_WRAPPER_TEXT + lm741_text

    text = _SUBCIRCUIT_TEXT[model_name]

    if model_name in ("FOLLOW", "INVAMP", "NONINV"):
        text = _GENERIC_OPAMP_TEXT + text

    if not text.endswith("\n"):
        text += "\n"

    return text


def build_instance_line(reference, model_name, node_by_pin, parameters=None):
    """
    Build the SPICE instance line of one subcircuit part.

    :param reference: Part reference starting with X, for example "X1".
    :type reference: str
    :param model_name: Subcircuit model name (case ignored).
    :type model_name: str
    :param node_by_pin: Net name of each connected pin, keyed by pin name.
        Supply pins may be missing for a model that does not need them;
        they then get their own unused node, "<reference>_<pin>_NC".
    :type node_by_pin: dict
    :param parameters: Extra values on the instance line, for example
        {"gain": "10"} for an inverting amplifier.
    :type parameters: dict or None
    :returns: For example "X1 0 N_R02_C03 N_R01_C04 N_R03_C04 N_R02_C05 OPAMP".
    :rtype: str
    :raises ComponentError: If the reference, model or nodes are not valid.
    """
    if (not isinstance(reference, str) or len(reference) < 2 or
            not reference.startswith("X")):
        raise ComponentError(
            f"An op-amp reference must start with X, not {reference!r}."
        )

    model_name = get_subcircuit_model_name(model_name)
    model = SUBCIRCUIT_MODELS[model_name]
    ports = model["ports"]
    supply_pins = model["supply_pins"]

    if not isinstance(node_by_pin, dict):
        raise ComponentError(
            f"{reference} pin nodes must be a dict, not {node_by_pin!r}."
        )

    unknown_pins = sorted(set(node_by_pin) - set(ports))

    if unknown_pins:
        raise ComponentError(
            f"{reference} has no pin {unknown_pins[0]!r}. Pins: "
            f"{', '.join(ports)}."
        )

    nodes = []

    for pin_name in ports:
        node = node_by_pin.get(pin_name)

        if node is None:
            if pin_name in supply_pins and not model["supply_pins_required"]:
                safe_pin = pin_name.replace("+", "P").replace("-", "N")
                nodes.append(f"{reference}_{safe_pin}_NC")
                continue

            if pin_name in supply_pins:
                joined = " and ".join(supply_pins)
                raise ComponentError(
                    f"{reference} ({model_name}) needs both supply pins "
                    f"connected: wire {joined} to the supply rails."
                )

            raise ComponentError(
                f"{reference} pin {pin_name} is not connected."
            )

        if not isinstance(node, str) or not node or " " in node:
            raise ComponentError(
                f"{reference} pin {pin_name} node must be a net name, not "
                f"{node!r}."
            )

        nodes.append(node)

    line = f"{reference} {' '.join(nodes)} {model_name}"

    if not parameters:
        return line

    if not isinstance(parameters, dict):
        raise ComponentError(
            f"{reference} parameters must be a dict, not {parameters!r}."
        )

    for name, value in parameters.items():
        if not isinstance(name, str) or not name:
            raise ComponentError(
                f"{reference} parameter name must be text, not {name!r}."
            )

        line += f" {name}={value}"

    return line
