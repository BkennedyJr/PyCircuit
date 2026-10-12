"""
IC library: packaged parts, grouped by family.

The Type list keeps discrete parts and the functional blocks (the
follower and the two amplifier blocks). Those blocks are a function,
not a package. Every packaged kind lives in exactly one family here,
and the panel uses this table for its Family and Device lists.
"""

from core.components import COMPONENT_DEFINITIONS
from core.exceptions import ComponentError

# (family id, label, kinds in the order they are offered).
IC_FAMILIES = (
    (
        "opamps",
        "Op-amps",
        (
            "opamp_generic",
            "opamp_741",
            "opamp_lm358",
            "opamp_tl072",
            "opamp_ne5532",
            "opamp_tl081",
            "opamp_tl082",
            "opamp_lm324",
        ),
    ),
    ("comparators", "Comparators", ("comparator",)),
    (
        "logic",
        "Logic",
        (
            "gate_not",
            "gate_buffer",
            "gate_and",
            "gate_or",
            "gate_nand",
            "gate_nor",
            "gate_xor",
        ),
    ),
    ("timers", "Timers", ("timer_555",)),
    ("regulators", "Regulators", ("voltage_regulator",)),
)


def _validate_library():
    """
    Refuse a family entry that is not a real part, or is listed twice.

    :returns: None
    :raises ComponentError: If a kind is unknown or repeated.
    """
    seen = []

    for _family_id, label, kinds in IC_FAMILIES:
        if not kinds:
            raise ComponentError(f"IC family {label} has no devices.")

        for kind in kinds:
            if kind not in COMPONENT_DEFINITIONS:
                raise ComponentError(
                    f"IC library device {kind!r} is not a part. "
                    f"Known parts: {', '.join(COMPONENT_DEFINITIONS)}."
                )

            if kind in seen:
                raise ComponentError(
                    f"{kind} is listed twice in the IC library."
                )

            seen.append(kind)


_validate_library()


def library_kinds():
    """
    Return every packaged kind, one family after another.

    :returns: Kind names.
    :rtype: list
    """
    kinds = []

    for _family_id, _label, family_kinds in IC_FAMILIES:
        kinds.extend(family_kinds)

    return kinds


def part_kinds():
    """
    Return the kinds that stay in the Type list, in definition order.

    :returns: Kind names.
    :rtype: list
    """
    packaged = set(library_kinds())

    return [
        kind for kind in COMPONENT_DEFINITIONS if kind not in packaged
    ]


def is_library_kind(kind):
    """
    Return whether a kind is chosen from the IC library.

    :param kind: Component kind.
    :type kind: str
    :returns: True for a packaged part.
    :rtype: bool
    """
    return kind in set(library_kinds())


def family_for_kind(kind):
    """
    Return the family that offers one packaged kind.

    :param kind: Component kind.
    :type kind: str
    :returns: (family id, label), for example ("opamps", "Op-amps").
    :rtype: tuple
    :raises ComponentError: If the kind is not in the library.
    """
    for family_id, label, kinds in IC_FAMILIES:
        if kind in kinds:
            return family_id, label

    names = ", ".join(label for _family_id, label, _kinds in IC_FAMILIES)
    raise ComponentError(
        f"{kind!r} is not in the IC library. Families: {names}."
    )


def kinds_in_family(family_id):
    """
    Return the devices in one family, in offer order.

    :param family_id: Family id, for example "logic".
    :type family_id: str
    :returns: Kind names.
    :rtype: tuple
    :raises ComponentError: If the family id is unknown.
    """
    for stored_id, _label, kinds in IC_FAMILIES:
        if stored_id == family_id:
            return kinds

    names = ", ".join(label for _family_id, label, _kinds in IC_FAMILIES)
    raise ComponentError(
        f"Unknown IC family {family_id!r}. Families: {names}."
    )
