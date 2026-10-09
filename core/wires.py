"""
Wires between connection-grid points.

A wire is one straight segment from grid point A to grid point B along a
row or a column. Like a breadboard strip it connects EVERY grid point it
covers, ends and the points in between, so a part pin on any of them
joins the wire (Billie's decision, Oct 9). Diagonal wires are refused:
draw two straight wires that meet at a corner. Parts sharing a grid point
are connected with or without a wire.

Junction dots (find_junction_identifiers) mark the points where three or
more connections meet, for example a wire passing a part pin mid-span or
a wire ending on another wire.

This module contains no PyQt5 imports, so the later net builder and the
solver can use it directly.
"""

import re

from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError

WIRE_REFERENCE_PREFIX = "W"

_WIRE_REFERENCE_PATTERN = re.compile(r"W[1-9][0-9]{0,5}")
_POINT_IDENTIFIER_PATTERN = re.compile(r"NODE_R[0-9]{2,}_C[0-9]{2,}")


def _validate_connection_grid(connection_grid):
    """
    Confirm that a ConnectionGrid was supplied.

    :param connection_grid: Grid to check.
    :type connection_grid: ConnectionGrid
    :returns: None
    :raises ComponentError: If the argument is not a ConnectionGrid.
    """
    if not isinstance(connection_grid, ConnectionGrid):
        raise ComponentError(
            f"Expected a ConnectionGrid, not {type(connection_grid).__name__}."
        )


class Wire:
    """
    One wire: a reference such as "W1" and its two end points.

    Points are kept as connection-point identifiers ("NODE_R02_C03") and as
    (row, column) pairs. A wire never changes after it is made; to change
    one, delete it and draw a new one.

    :param reference: Wire reference, "W" followed by a number.
    :type reference: str
    :param start_point: (row, column) of end A, one-based.
    :type start_point: tuple
    :param end_point: (row, column) of end B, one-based.
    :type end_point: tuple
    :raises ComponentError: If an argument is invalid or both ends are the
        same point.
    """

    def __init__(self, reference, start_point, end_point):
        if (not isinstance(reference, str) or
                not _WIRE_REFERENCE_PATTERN.fullmatch(reference)):
            raise ComponentError(
                f"Wire reference {reference!r} is not valid. Use 'W' "
                "followed by a number, for example W1."
            )

        self._reference = reference
        self._start_point = self.validate_point(start_point, "start")
        self._end_point = self.validate_point(end_point, "end")

        if self._start_point == self._end_point:
            raise ComponentError(
                f"A wire needs two different grid points; both ends are "
                f"{self.start_identifier}."
            )

        if (self._start_point[0] != self._end_point[0] and
                self._start_point[1] != self._end_point[1]):
            raise ComponentError(
                f"A wire from {self.start_identifier} to "
                f"{self.end_identifier} would be diagonal. Wires run along "
                "a row or a column: draw two straight wires that meet at a "
                "corner."
            )

    @staticmethod
    def validate_point(point, end_name):
        """
        Check one end point: a (row, column) pair of whole numbers >= 1.

        :param point: Point to check.
        :type point: tuple
        :param end_name: "start" or "end", for the message.
        :type end_name: str
        :returns: The point as a tuple.
        :rtype: tuple
        :raises ComponentError: If the point is malformed.
        """
        if (isinstance(point, (tuple, list)) and len(point) == 2 and
                all(isinstance(number, int) and
                    not isinstance(number, bool) and number >= 1
                    for number in point)):
            return (point[0], point[1])

        raise ComponentError(
            f"Wire {end_name} {point!r} is not a grid point. Use (row, "
            "column) with whole numbers from 1."
        )

    @property
    def reference(self):
        """
        Wire reference, for example "W1". Read-only.

        :rtype: str
        """
        return self._reference

    @property
    def start_point(self):
        """
        (row, column) of end A. Read-only.

        :rtype: tuple
        """
        return self._start_point

    @property
    def end_point(self):
        """
        (row, column) of end B. Read-only.

        :rtype: tuple
        """
        return self._end_point

    @property
    def start_identifier(self):
        """
        Connection-point identifier of end A, for example "NODE_R02_C03".

        :rtype: str
        """
        return ConnectionGrid.build_connection_point_identifier(
            *self._start_point
        )

    @property
    def end_identifier(self):
        """
        Connection-point identifier of end B.

        :rtype: str
        """
        return ConnectionGrid.build_connection_point_identifier(
            *self._end_point
        )

    def get_end_points(self):
        """
        Return both ends as a frozenset, so A-B equals B-A.

        :rtype: frozenset
        """
        return frozenset((self._start_point, self._end_point))

    def get_points(self):
        """
        Return every grid point the wire covers, from end A to end B.

        :returns: (row, column) pairs, both ends included.
        :rtype: tuple
        """
        (start_row, start_column) = self._start_point
        (end_row, end_column) = self._end_point
        step_count = abs(end_row - start_row) + abs(end_column - start_column)
        row_step = (end_row > start_row) - (end_row < start_row)
        column_step = (end_column > start_column) - (end_column < start_column)

        return tuple(
            (start_row + row_step * index, start_column + column_step * index)
            for index in range(step_count + 1)
        )

    def get_point_identifiers(self):
        """
        Return the identifiers of every point the wire covers, A to B.

        :rtype: tuple
        """
        return tuple(
            ConnectionGrid.build_connection_point_identifier(row, column)
            for row, column in self.get_points()
        )

    def get_inner_point_identifiers(self):
        """
        Return the covered points between the two ends (mid-span).

        :rtype: tuple
        """
        return self.get_point_identifiers()[1:-1]

    def fits_grid(self, row_count, column_count):
        """
        Return whether both ends lie on a grid of the given size.

        :rtype: bool
        """
        return all(
            1 <= row <= row_count and 1 <= column <= column_count
            for row, column in (self._start_point, self._end_point)
        )

    def describe(self):
        """
        Return text such as "W1 from NODE_R02_C02 to NODE_R02_C04".

        :rtype: str
        """
        return (
            f"{self.reference} from {self.start_identifier} to "
            f"{self.end_identifier}"
        )


def _wire_sort_key(reference):
    """
    Natural sort key: W2 before W10.

    :rtype: int
    """
    return int(reference[len(WIRE_REFERENCE_PREFIX):])


class WireCollection:
    """
    All wires of one project, keyed by reference.

    The collection numbers new wires (lowest unused "W" number), refuses
    zero-length wires, wires with an end off the grid and duplicates (the
    same two points in either order), and removes wires that no longer fit
    after the grid shrinks.
    """

    def __init__(self):
        self.wires_by_reference = {}

    def next_reference(self):
        """
        Return the lowest unused wire reference, such as "W1".

        :rtype: str
        """
        number = 1

        while f"{WIRE_REFERENCE_PREFIX}{number}" in self.wires_by_reference:
            number += 1

        return f"{WIRE_REFERENCE_PREFIX}{number}"

    def add_wire(self, start_identifier, end_identifier, connection_grid):
        """
        Create, check and store a wire between two grid points.

        :param start_identifier: Point of end A, for example
            "NODE_R02_C02".
        :type start_identifier: str
        :param end_identifier: Point of end B.
        :type end_identifier: str
        :param connection_grid: Grid both ends must be on.
        :type connection_grid: ConnectionGrid
        :returns: The new wire.
        :rtype: Wire
        :raises ComponentError: If a point is not on the grid, both ends
            are the same point, the wire would be diagonal, or a wire
            already joins the two points. Nothing is stored then.
        """
        _validate_connection_grid(connection_grid)

        start_point = self.get_grid_point(start_identifier, connection_grid)
        end_point = self.get_grid_point(end_identifier, connection_grid)

        wire = Wire(self.next_reference(), start_point, end_point)
        existing_wire = self.find_wire_between(start_point, end_point)

        if existing_wire is not None:
            raise ComponentError(
                f"{existing_wire.reference} already joins "
                f"{existing_wire.start_identifier} and "
                f"{existing_wire.end_identifier}."
            )

        self.wires_by_reference[wire.reference] = wire

        return wire

    @staticmethod
    def get_grid_point(identifier, connection_grid):
        """
        Return the (row, column) of a connection point on the grid.

        :param identifier: Connection-point identifier.
        :type identifier: str
        :param connection_grid: Current grid.
        :type connection_grid: ConnectionGrid
        :returns: (row, column).
        :rtype: tuple
        :raises ComponentError: If the point is not on the grid.
        """
        if (not isinstance(identifier, str) or identifier not in
                connection_grid.connection_points_by_identifier):
            raise ComponentError(
                f"{identifier!r} is not a grid point of the "
                f"{connection_grid.row_count} x "
                f"{connection_grid.column_count} grid."
            )

        connection_point = connection_grid.connection_points_by_identifier[
            identifier
        ]

        return (connection_point.row_number, connection_point.column_number)

    def find_wire_between(self, first_point, second_point):
        """
        Return the wire joining two points (either order), or None.

        :param first_point: (row, column).
        :type first_point: tuple
        :param second_point: (row, column).
        :type second_point: tuple
        :rtype: Wire or None
        """
        end_points = frozenset((first_point, second_point))

        for wire in self.get_wires():
            if wire.get_end_points() == end_points:
                return wire

        return None

    def get_wire(self, reference):
        """
        Return a wire by reference.

        :raises ComponentError: If there is no such wire.
        """
        if (not isinstance(reference, str) or
                reference not in self.wires_by_reference):
            raise ComponentError(f"There is no wire called {reference!r}.")

        return self.wires_by_reference[reference]

    def get_wires(self):
        """
        Return all wires ordered by reference (W2 before W10).

        :rtype: list
        """
        return [
            self.wires_by_reference[reference]
            for reference in sorted(self.wires_by_reference, key=_wire_sort_key)
        ]

    def get_wires_at(self, identifier):
        """
        Return the wires that cover one grid point (at an end or mid-span).

        :param identifier: Connection-point identifier.
        :type identifier: str
        :rtype: list
        """
        return [
            wire for wire in self.get_wires()
            if identifier in wire.get_point_identifiers()
        ]

    def remove_wire(self, reference):
        """
        Remove a wire.

        :raises ComponentError: If there is no such wire.
        """
        self.get_wire(reference)
        del self.wires_by_reference[reference]

    def remove_wires_outside_grid(self, connection_grid):
        """
        Remove every wire with an end outside the grid (after a shrink).

        :param connection_grid: Grid after resizing.
        :type connection_grid: ConnectionGrid
        :returns: References of the removed wires, sorted.
        :rtype: list
        """
        _validate_connection_grid(connection_grid)

        removed_references = [
            wire.reference for wire in self.get_wires()
            if not wire.fits_grid(
                connection_grid.row_count,
                connection_grid.column_count
            )
        ]

        for reference in removed_references:
            del self.wires_by_reference[reference]

        return removed_references


class WireNets:
    """
    Which grid points the wires join, for the part tooltips.

    Wires connect only their two ends (see the module docstring), so two
    wires that share an end point are one net. This is a light stand-in
    for M2's NetMap: it knows only wires and the points ground pins sit
    on, not the parts. A net with a ground point is SPICE node "0".

    :param wire_collection: Wires to group.
    :type wire_collection: WireCollection
    :param ground_identifiers: Points that a ground pin sits on.
    :type ground_identifiers: iterable of str
    :raises ComponentError: If an argument has the wrong type.
    """

    def __init__(self, wire_collection, ground_identifiers=()):
        if not isinstance(wire_collection, WireCollection):
            raise ComponentError(
                f"Expected a WireCollection, not "
                f"{type(wire_collection).__name__}."
            )

        ground_identifiers = tuple(ground_identifiers)

        for identifier in ground_identifiers:
            _validate_identifier(identifier)

        self._ground_identifiers = frozenset(ground_identifiers)
        self._parent_by_point = {}
        self._point_by_identifier = {}

        for wire in wire_collection.get_wires():
            for identifier, point in (
                    (wire.start_identifier, wire.start_point),
                    (wire.end_identifier, wire.end_point)):
                self._point_by_identifier[identifier] = point
                self._parent_by_point.setdefault(identifier, identifier)

            self._union(wire.start_identifier, wire.end_identifier)

        self._points_by_root = {}
        self._wires_by_root = {}

        for identifier in self._parent_by_point:
            self._points_by_root.setdefault(
                self._find(identifier), []
            ).append(identifier)

        for wire in wire_collection.get_wires():
            self._wires_by_root.setdefault(
                self._find(wire.start_identifier), []
            ).append(wire.reference)

    def _find(self, identifier):
        """
        Return the representative point of a group (path halving).

        :rtype: str
        """
        parent_by_point = self._parent_by_point

        while parent_by_point[identifier] != identifier:
            parent_by_point[identifier] = parent_by_point[
                parent_by_point[identifier]
            ]
            identifier = parent_by_point[identifier]

        return identifier

    def _union(self, first_identifier, second_identifier):
        """
        Join the groups of two points.

        :returns: None
        """
        first_root = self._find(first_identifier)
        second_root = self._find(second_identifier)

        if first_root != second_root:
            self._parent_by_point[second_root] = first_root

    def get_points(self, identifier):
        """
        Return the points joined to one point by wires, in row-column order.

        :param identifier: Connection-point identifier.
        :type identifier: str
        :returns: The joined identifiers, including this one; just this
            one when no wire ends here.
        :rtype: tuple
        :raises ComponentError: If identifier is not an identifier.
        """
        _validate_identifier(identifier)

        if identifier not in self._parent_by_point:
            return (identifier,)

        return tuple(sorted(
            self._points_by_root[self._find(identifier)],
            key=self._point_by_identifier.__getitem__
        ))

    def get_wire_references(self, identifier):
        """
        Return the wires of the net through one point (W2 before W10).

        :param identifier: Connection-point identifier.
        :type identifier: str
        :returns: Wire references; empty when no wire ends here.
        :rtype: tuple
        :raises ComponentError: If identifier is not an identifier.
        """
        _validate_identifier(identifier)

        if identifier not in self._parent_by_point:
            return ()

        return tuple(sorted(
            self._wires_by_root[self._find(identifier)],
            key=_wire_sort_key
        ))

    def is_ground(self, identifier):
        """
        Return whether the net through one point holds a ground pin.

        :rtype: bool
        :raises ComponentError: If identifier is not an identifier.
        """
        return not self._ground_identifiers.isdisjoint(
            self.get_points(identifier)
        )

    def describe(self, identifier):
        """
        Describe the net through one point, for a tooltip.

        Examples: "NODE_R02_C02, NODE_R02_C05 via W1",
        "0 (ground): NODE_R02_C05, NODE_R06_C05 via W1, W2", "0 (ground)"
        (a ground pin on the point itself) and "no wires".

        :param identifier: Connection-point identifier.
        :type identifier: str
        :rtype: str
        :raises ComponentError: If identifier is not an identifier.
        """
        wire_references = self.get_wire_references(identifier)
        is_ground = self.is_ground(identifier)

        if not wire_references:
            return "0 (ground)" if is_ground else "no wires"

        text = (
            f"{', '.join(self.get_points(identifier))} via "
            f"{', '.join(wire_references)}"
        )

        return f"0 (ground): {text}" if is_ground else text


def _validate_identifier(identifier):
    """
    Confirm that a connection-point identifier was supplied.

    :param identifier: Value to check, for example "NODE_R02_C03".
    :returns: None
    :raises ComponentError: If it is not a valid identifier.
    """
    if (not isinstance(identifier, str) or
            not _POINT_IDENTIFIER_PATTERN.fullmatch(identifier)):
        raise ComponentError(
            f"Expected a grid point such as NODE_R02_C03, not "
            f"{identifier!r}."
        )


def find_junction_identifiers(wire_collection, pin_identifiers=()):
    """
    Return the grid points that need a junction dot.

    Each wire end at a point counts 1, a wire passing over it mid-span
    counts 2 (it leaves both ways) and each part pin on it counts 1. A
    point on a wire with 3 or more gets a dot: a wire passing a pin or
    meeting another wire mid-span (T or crossing), or three wire ends. A
    plain corner (two ends) or a wire ending on a pin (2) gets none.

    :param wire_collection: Wires of the project.
    :type wire_collection: WireCollection
    :param pin_identifiers: The point of every part pin, one entry per
        pin (a point with two pins appears twice).
    :type pin_identifiers: iterable of str
    :returns: Identifiers, sorted.
    :rtype: list
    :raises ComponentError: If wire_collection is not a WireCollection or
        a pin identifier is not a string.
    """
    if not isinstance(wire_collection, WireCollection):
        raise ComponentError(
            f"Expected a WireCollection, not "
            f"{type(wire_collection).__name__}."
        )

    counts = {}
    wired_points = set()

    for wire in wire_collection.get_wires():
        for identifier in (wire.start_identifier, wire.end_identifier):
            counts[identifier] = counts.get(identifier, 0) + 1
            wired_points.add(identifier)

        for identifier in wire.get_inner_point_identifiers():
            counts[identifier] = counts.get(identifier, 0) + 2
            wired_points.add(identifier)

    for identifier in pin_identifiers:
        if not isinstance(identifier, str):
            raise ComponentError(
                f"Pin points must be identifiers such as NODE_R02_C03, not "
                f"{identifier!r}."
            )

        counts[identifier] = counts.get(identifier, 0) + 1

    return sorted(
        identifier for identifier in wired_points if counts[identifier] >= 3
    )
