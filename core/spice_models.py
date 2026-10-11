"""
Small SPICE device models for diodes, LEDs and transistors.

These are stand-ins written for PyCircuit, not vendor models. The names
match the parts' defaults. Lookup ignores case, the same way SPICE does.
"""

from core.exceptions import SimulationError

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
}

# Part kind to the device kind its model must be.
DEVICE_KIND_BY_PART = {
    "diode": "D",
    "led": "D",
    "npn": "NPN",
    "pnp": "PNP",
    "nmos": "NMOS",
    "pmos": "PMOS",
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
