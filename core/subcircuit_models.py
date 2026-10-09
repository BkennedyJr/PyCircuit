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

SUBCIRCUIT_MODELS = {
    "OPAMP": {
        "description": "Generic op-amp: gain 100k, Rin 1meg, Rout 75",
        "supply_pins_required": False,
        "source": "PyCircuit (behavioural VCVS model)",
        "license": "same as PyCircuit",
    },
    "LM741": {
        "description": "741 op-amp (Logipipe LM741 model)",
        "supply_pins_required": True,
        "source": (
            "Logipipe, LLC, LM741 SPICE Model (2020), "
            "https://www.logipipe.com/LM741.txt; reference: Fairchild "
            "Semiconductor LM741 data sheet, Rev 1.0.1 (2001)"
        ),
        "license": "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
    },
}

DEFAULT_SUBCIRCUIT_BY_KIND = {
    "opamp_generic": "OPAMP",
    "opamp_741": "LM741",
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
        f"No op-amp model named {name!r}. Known models: "
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

    lm741_text = read_lm741_file()

    if not lm741_text.endswith("\n"):
        lm741_text += "\n"

    return _LM741_WRAPPER_TEXT + lm741_text


def build_instance_line(reference, model_name, node_by_pin):
    """
    Build the SPICE instance line of one op-amp part.

    :param reference: Part reference starting with X, for example "X1".
    :type reference: str
    :param model_name: Subcircuit model name (case ignored).
    :type model_name: str
    :param node_by_pin: Net name of each connected pin, keyed by pin name
        ("in+", "in-", "out", "V+", "V-"). Supply pins may be missing for
        a model that does not need them; they then get their own unused
        node, "<reference>_<pin>_NC".
    :type node_by_pin: dict
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

    if not isinstance(node_by_pin, dict):
        raise ComponentError(
            f"{reference} pin nodes must be a dict, not {node_by_pin!r}."
        )

    unknown_pins = sorted(set(node_by_pin) - set(SUBCIRCUIT_PORT_ORDER))

    if unknown_pins:
        raise ComponentError(
            f"{reference} has no pin {unknown_pins[0]!r}. Pins: "
            f"{', '.join(SUBCIRCUIT_PORT_ORDER)}."
        )

    nodes = []

    for pin_name in SUBCIRCUIT_PORT_ORDER:
        node = node_by_pin.get(pin_name)

        if node is None:
            if pin_name in SUPPLY_PINS and not model["supply_pins_required"]:
                safe_pin = pin_name.replace("+", "P").replace("-", "N")
                nodes.append(f"{reference}_{safe_pin}_NC")
                continue

            if pin_name in SUPPLY_PINS:
                raise ComponentError(
                    f"{reference} ({model_name}) needs both supply pins "
                    "connected: wire V+ and V- to the supply rails."
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

    return f"{reference} {' '.join(nodes)} {model_name}"
