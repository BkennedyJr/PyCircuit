"""
Snapshots, copy and paste. No Qt.

Two 1k resistors joined by a wire paste as a new pair. A wire that
leaves the chunk stays behind. A paste that hits another part adds
nothing.
"""

import pytest

from core.circuit_edits import (
    capture_circuit,
    collections_from_snapshot,
    copy_chunk,
    paste_chunk,
)
from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.probes import ProbeCollection
from core.wires import WireCollection


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def build():
    grid = ConnectionGrid(8, 8)
    parts = ComponentCollection()
    wires = WireCollection()
    probes = ProbeCollection()
    return grid, parts, wires, probes


def place(parts, grid, kind, row, column, value="1k", rotation=0):
    return parts.add_component(
        kind, row, column, value, grid, rotation
    )


def test_a_snapshot_round_trip_keeps_names_values_and_a_probe():
    grid, parts, wires, probes = build()
    resistor = place(parts, grid, "resistor", 2, 2, "4k7")
    wires.add_wire(point(2, 3), point(2, 6), grid, [point(2, 4)])
    probes.add_current(resistor)
    grid.set_net_label(point(1, 1), "Vcc")
    snapshot = capture_circuit(parts, wires, probes)

    restored = collections_from_snapshot(snapshot, grid)
    restored_parts, restored_wires, restored_probes = restored

    assert grid.get_net_labels()[point(1, 1)] == "Vcc"
    assert grid.row_count == 8
    assert restored_parts.get_component("R1").value_text == "4k7"
    wire = restored_wires.get_wire("W1")
    assert wire.start_identifier == point(2, 3)
    assert list(wire.bridged_identifiers) == [point(2, 4)]
    assert restored_probes.get("P1").component_reference == "R1"
    # The live circuit was not replaced by the restore.
    assert parts.get_component("R1").value_text == "4k7"


def test_copy_keeps_the_wire_between_parts_and_drops_one_that_leaves():
    grid, parts, wires, _probes = build()
    first = place(parts, grid, "resistor", 2, 2, "1k")
    second = place(parts, grid, "resistor", 2, 4, "2k2")
    place(parts, grid, "resistor", 6, 2, "10k")
    wires.add_wire(point(2, 3), point(2, 4), grid)
    wires.add_wire(point(2, 3), point(2, 6), grid)
    wires.add_wire(
        point(2, 3), point(2, 5), grid, [point(2, 4)]
    )

    # The third resistor is not selected. The wire from the first
    # pair out to column 6 is not part of the chunk. The hop between
    # the two selected pins is.
    chunk = copy_chunk([first, second], wires.get_wires())

    assert chunk["origin_row"] == 2
    assert chunk["origin_column"] == 2
    assert [data["reference"] for data in chunk["components"]] == [
        "R1", "R2"
    ]
    assert len(chunk["wires"]) == 2
    assert copy_chunk([], wires.get_wires()) is None


def test_paste_shifts_parts_and_a_bridged_wire_and_uses_new_names():
    grid, parts, wires, _probes = build()
    first = place(parts, grid, "resistor", 2, 2, "1k")
    second = place(parts, grid, "resistor", 2, 6, "2k2")
    wires.add_wire(point(2, 3), point(2, 6), grid, [point(2, 4)])
    chunk = copy_chunk([first, second], wires.get_wires())

    added = paste_chunk(chunk, 4, 2, parts, wires, grid)

    assert added == ["R3", "R4"]
    assert parts.get_component("R3").value_text == "1k"
    assert (parts.get_component("R3").row_number,
            parts.get_component("R3").column_number) == (4, 2)
    assert (parts.get_component("R4").row_number,
            parts.get_component("R4").column_number) == (4, 6)
    pasted = wires.get_wire("W2")
    assert pasted.start_identifier == point(4, 3)
    assert pasted.end_identifier == point(4, 6)
    assert list(pasted.bridged_identifiers) == [point(4, 4)]


def test_a_paste_that_hits_a_part_adds_nothing():
    grid, parts, wires, _probes = build()
    first = place(parts, grid, "resistor", 2, 2, "1k")
    second = place(parts, grid, "resistor", 2, 4, "2k2")
    place(parts, grid, "capacitor", 5, 4, "100n")
    chunk = copy_chunk([first, second], wires.get_wires())

    with pytest.raises(ComponentError, match="already"):
        paste_chunk(chunk, 5, 2, parts, wires, grid)

    references = [
        component.reference for component in parts.get_components()
    ]
    assert references == ["C1", "R1", "R2"]
    assert wires.get_wires() == []


def test_a_paste_off_the_grid_adds_nothing():
    grid, parts, wires, _probes = build()
    resistor = place(parts, grid, "resistor", 2, 2, "1k")
    chunk = copy_chunk([resistor], wires.get_wires())

    with pytest.raises(ComponentError, match="outside the 8 x 8 grid"):
        paste_chunk(chunk, 2, 8, parts, wires, grid)

    assert [component.reference for component in parts.get_components()
            ] == ["R1"]
