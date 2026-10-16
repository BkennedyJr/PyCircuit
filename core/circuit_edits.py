"""
Snapshots of parts, wires and probes, and copy and paste of a chunk.

A snapshot is the three collections only. The grid size and the net
labels stay where they are when a snapshot is put back. Copy keeps the
selected parts and a wire whose two ends are both pins of those parts.
Paste gives every part and wire a new name.
"""

import re

from core.components import Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.probes import ProbeCollection
from core.wires import WireCollection

_POINT_IDENTIFIER = re.compile(r"NODE_R([0-9]{2,})_C([0-9]{2,})")


def capture_circuit(component_collection, wire_collection, probe_collection):
    """
    Return the parts, wires and probes as plain data.

    :rtype: dict
    """
    return {
        "components": [
            component.to_dict()
            for component in component_collection.get_components()
        ],
        "wires": [wire.to_dict() for wire in wire_collection.get_wires()],
        "probes": [probe.to_dict() for probe in probe_collection.get_probes()],
    }


def collections_from_snapshot(snapshot, connection_grid):
    """
    Build new collections from a snapshot.

    The grid is only checked. Its size and net labels are not changed.
    Nothing is stored if any part, wire or probe is refused.

    :param snapshot: Data from :func:`capture_circuit`.
    :type snapshot: dict
    :param connection_grid: Grid the parts must fit on.
    :type connection_grid: ConnectionGrid
    :returns: ``(components, wires, probes)``.
    :rtype: tuple
    :raises ComponentError: If the snapshot cannot be placed. No
        collection is then half-filled for the caller to keep.
    """
    components = ComponentCollection()
    wires = WireCollection()
    probes = ProbeCollection()

    for data in snapshot["components"]:
        components.place_saved(
            data["kind"],
            data["reference"],
            data["value"],
            data["row"],
            data["column"],
            connection_grid,
            data.get("rotation", 0),
            data.get("parameters")
        )

    for data in snapshot["wires"]:
        wires.place_saved(
            data["reference"],
            data["start"],
            data["end"],
            connection_grid,
            data.get("bridged", ())
        )

    placed = components.get_components()

    for data in snapshot["probes"]:
        probes.place_saved(
            data["reference"],
            data["method"],
            data["color"],
            connection_grid,
            identifier=data.get("point"),
            second_identifier=data.get("second_point"),
            component_reference=data.get("part"),
            components=placed,
            flag_offset=(data.get("flag_x", 0.0), data.get("flag_y", 0.0)),
            second_flag_offset=(
                data.get("second_flag_x", 0.0),
                data.get("second_flag_y", 0.0)
            )
        )

    return (components, wires, probes)


def copy_chunk(parts, wires):
    """
    Return a clipboard for the given parts, or None when there are none.

    A wire is included when both of its ends are pins of these parts.
    A wire that runs off to some other point is left out. The origin is
    the lowest anchor row and the lowest anchor column.

    :param parts: Parts to copy, in the order they should be pasted.
    :type parts: list
    :param wires: Wires to choose from.
    :type wires: iterable
    :rtype: dict or None
    :raises ComponentError: If an entry is not a part.
    """
    if not parts:
        return None

    pin_identifiers = set()

    for part in parts:
        if not isinstance(part, Component):
            raise ComponentError(
                f"Expected a Component, not {part!r}."
            )

        pin_identifiers.update(part.get_pin_identifiers())

    copied_wires = []

    for wire in wires:
        if (wire.start_identifier in pin_identifiers and
                wire.end_identifier in pin_identifiers):
            copied_wires.append(wire.to_dict())

    return {
        "origin_row": min(part.row_number for part in parts),
        "origin_column": min(part.column_number for part in parts),
        "components": [part.to_dict() for part in parts],
        "wires": copied_wires,
    }


def paste_chunk(clipboard, anchor_row, anchor_column, component_collection,
                wire_collection, connection_grid):
    """
    Place a copied chunk so its origin lands on the anchor point.

    Each part and wire gets the next free name. A failure removes
    anything this call already added.

    :param clipboard: Data from :func:`copy_chunk`.
    :type clipboard: dict
    :param anchor_row: Row the origin moves to.
    :type anchor_row: int
    :param anchor_column: Column the origin moves to.
    :type anchor_column: int
    :returns: References of the new parts, in clipboard order.
    :rtype: list
    :raises ComponentError: If the chunk does not fit. Nothing is
        added then.
    """
    if not clipboard or not clipboard.get("components"):
        raise ComponentError(
            "There is nothing to paste. Copy one or more parts first."
        )

    row_delta = anchor_row - clipboard["origin_row"]
    column_delta = anchor_column - clipboard["origin_column"]
    added_parts = []
    added_wires = []

    try:
        for data in clipboard["components"]:
            component = component_collection.add_component(
                data["kind"],
                data["row"] + row_delta,
                data["column"] + column_delta,
                data["value"],
                connection_grid,
                data.get("rotation", 0),
                dict(data.get("parameters") or {})
            )
            added_parts.append(component.reference)

        for data in clipboard["wires"]:
            wire = wire_collection.add_wire(
                _shift_identifier(
                    data["start"], row_delta, column_delta
                ),
                _shift_identifier(data["end"], row_delta, column_delta),
                connection_grid,
                [
                    _shift_identifier(
                        identifier, row_delta, column_delta
                    )
                    for identifier in data.get("bridged", ())
                ]
            )
            added_wires.append(wire.reference)
    except ComponentError:
        for reference in added_wires:
            wire_collection.remove_wire(reference)

        for reference in added_parts:
            component_collection.remove_component(reference)

        raise

    return added_parts


def _shift_identifier(identifier, row_delta, column_delta):
    """
    Move a grid-point name by a row and column offset.

    :rtype: str
    :raises ComponentError: If the name is not a grid point, or the
        point would be off the top or the left of the grid.
    """
    match = _POINT_IDENTIFIER.fullmatch(identifier)

    if match is None:
        raise ComponentError(
            f"{identifier!r} is not a grid point. Use a name such as "
            "NODE_R04_C03."
        )

    row_number = int(match.group(1)) + row_delta
    column_number = int(match.group(2)) + column_delta

    if row_number < 1 or column_number < 1:
        raise ComponentError(
            "That paste would put a pin off the grid. Pick a point "
            "farther from the top and the left."
        )

    return ConnectionGrid.build_connection_point_identifier(
        row_number, column_number
    )
