"""
Tests for the IC family table. No Qt: the panel tests cover the lists.
"""

import pytest

from core.components import COMPONENT_DEFINITIONS
from core.exceptions import ComponentError
from core.ic_library import (
    IC_FAMILIES,
    family_for_kind,
    is_library_kind,
    kinds_in_family,
    library_kinds,
    part_kinds,
)


def test_every_part_is_either_a_type_list_part_or_one_library_device():
    packaged = set(library_kinds())

    assert part_kinds() == [
        kind for kind in COMPONENT_DEFINITIONS if kind not in packaged
    ]
    assert set(part_kinds()) & packaged == set()
    assert len(library_kinds()) == 18
    assert len(part_kinds()) == 22


def test_families_group_like_devices():
    assert [family_id for family_id, _label, _kinds in IC_FAMILIES] == [
        "opamps", "comparators", "logic", "timers", "regulators",
    ]
    assert kinds_in_family("opamps") == (
        "opamp_generic",
        "opamp_741",
        "opamp_lm358",
        "opamp_tl072",
        "opamp_ne5532",
        "opamp_tl081",
        "opamp_tl082",
        "opamp_lm324",
    )
    assert kinds_in_family("logic") == (
        "gate_not",
        "gate_buffer",
        "gate_and",
        "gate_or",
        "gate_nand",
        "gate_nor",
        "gate_xor",
    )
    assert kinds_in_family("comparators") == ("comparator",)
    assert kinds_in_family("timers") == ("timer_555",)
    assert kinds_in_family("regulators") == ("voltage_regulator",)


def test_blocks_stay_with_the_other_parts():
    for kind in ("follower", "inverting_amp", "noninverting_amp"):
        assert kind in part_kinds()
        assert not is_library_kind(kind)


def test_family_for_an_opamp():
    assert family_for_kind("opamp_tl081") == ("opamps", "Op-amps")
    assert is_library_kind("timer_555")
    assert not is_library_kind("resistor")


def test_a_discrete_part_is_not_in_the_library():
    with pytest.raises(ComponentError, match="not in the IC library"):
        family_for_kind("resistor")


def test_unknown_family_names_the_real_ones():
    with pytest.raises(ComponentError, match="Unknown IC family"):
        kinds_in_family("memory")
