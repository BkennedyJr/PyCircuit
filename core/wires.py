"""
Wires between connection-grid points.

A wire is one straight segment from grid point A to grid point B along a
row or a column. Like a breadboard strip it connects EVERY grid point it
covers, ends and the points in between, so a part pin on any of them
joins the wire (Billie's decision, Oct 9). A bridge is the exception: the
wire hops that point and does not connect there, so it can cross another
wire (Billie, Oct 9). Diagonal wires are refused: draw two straight wires
that meet at a corner. Parts sharing a grid point are connected with or
without a wire.

Junction dots (find_junction_identifiers) mark the points where three or
more connections meet, for example a wire passing a part pin mid-span or
a wire ending on another wire.

This module contains no PyQt5 imports, so the later net builder and the
solver can use it directly.
"""

import itertools
import re

from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError

WIRE_REFERENCE_PREFIX = "W"

_WIRE_REFERENCE_PATTERN = re.compile(r"W[1-9][0-9]{0,5}")
_POINT_IDENTIFIER_PATTERN = re.compile(r"NODE_R([0-9]{2,})_C([0-9]{2,})")


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
    :param bridged_points: Interior points this wire hops and does not
        connect. Empty means the breadboard strip: every point joins.
    :type bridged_points: iterable of tuple
    :raises ComponentError: If an argument is invalid, both ends are the
        same point, or a bridge is not between the ends.
    """

    def __init__(self, reference, start_point, end_point,
                 bridged_points=()):
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

        self._bridged_points = self.validate_bridged_points(bridged_points)

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

    def validate_bridged_points(self, bridged_points):
        """
        Check the points a wire hops: each must lie strictly between the ends.

        :param bridged_points: Points to hop, as (row, column) pairs.
        :type bridged_points: iterable
        :returns: Those points, duplicates collapsed.
        :rtype: frozenset
        :raises ComponentError: If the argument is not a collection of
            interior grid points.
        """
        if (isinstance(bridged_points, (str, bytes)) or
                not isinstance(bridged_points, (tuple, list, set, frozenset))):
            raise ComponentError(
                f"Bridged points {bridged_points!r} must be grid points "
                "between the wire's ends."
            )

        interior = set(self.get_points()[1:-1])
        cleaned = []

        for point in bridged_points:
            point = self.validate_point(point, "bridge")

            if point not in interior:
                identifier = ConnectionGrid.build_connection_point_identifier(
                    *point
                )
                raise ComponentError(
                    f"A bridge has to be a grid point between the wire's "
                    f"ends. {identifier} is not between "
                    f"{self.start_identifier} and {self.end_identifier}."
                )

            cleaned.append(point)

        return frozenset(cleaned)

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

    @property
    def bridged_points(self):
        """
        Interior (row, column) points this wire hops. Read-only.

        :rtype: frozenset
        """
        return self._bridged_points

    @property
    def bridged_identifiers(self):
        """
        Identifiers of the hopped points, row then column.

        :rtype: tuple
        """
        return tuple(
            ConnectionGrid.build_connection_point_identifier(row, column)
            for row, column in sorted(self._bridged_points)
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

    def get_joined_identifiers(self):
        """
        Return the points this wire electrically joins, from A to B.

        THE connection rule, in one place: every other piece of code that
        asks what a wire connects (get_wires_at, junction dots, the net
        builder) goes through this method. Billie's rule (Oct 9) is the
        breadboard strip: every grid point the wire covers, except a bridge.
        A bridged point is hopped, so it is not joined, but the points on
        either side of the hop stay one wire. That rule is why diagonal
        wires are refused in __init__.

        :rtype: tuple
        """
        bridged_points = self._bridged_points

        return tuple(
            ConnectionGrid.build_connection_point_identifier(row, column)
            for row, column in self.get_points()
            if (row, column) not in bridged_points
        )

    def get_inner_point_identifiers(self):
        """
        Return the joined points between the two ends (mid-span).

        :rtype: tuple
        """
        return self.get_joined_identifiers()[1:-1]

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
        text = (
            f"{self.reference} from {self.start_identifier} to "
            f"{self.end_identifier}"
        )

        if self._bridged_points:
            text += f", bridging {', '.join(self.bridged_identifiers)}"

        return text

    def to_dict(self):
        """
        Return this wire as JSON-ready data.

        :rtype: dict
        """
        return {
            "reference": self.reference,
            "start": self.start_identifier,
            "end": self.end_identifier,
            "bridged": list(self.bridged_identifiers),
        }


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

    def add_wire(self, start_identifier, end_identifier, connection_grid,
                 bridged_identifiers=()):
        """
        Create, check and store a wire between two grid points.

        :param start_identifier: Point of end A, for example
            "NODE_R02_C02".
        :type start_identifier: str
        :param end_identifier: Point of end B.
        :type end_identifier: str
        :param connection_grid: Grid both ends must be on.
        :type connection_grid: ConnectionGrid
        :param bridged_identifiers: Interior points to hop, for example
            ("NODE_R02_C04",). Empty joins every point on the span.
        :type bridged_identifiers: iterable of str
        :returns: The new wire.
        :rtype: Wire
        :raises ComponentError: If a point is not on the grid, both ends
            are the same point, the wire would be diagonal, a bridge is
            not between the ends, or a wire already joins the two points.
            Nothing is stored then.
        """
        _validate_connection_grid(connection_grid)

        start_point = self.get_grid_point(start_identifier, connection_grid)
        end_point = self.get_grid_point(end_identifier, connection_grid)
        self.refuse_duplicate(start_point, end_point)

        if isinstance(bridged_identifiers, str):
            raise ComponentError(
                f"Bridged points {bridged_identifiers!r} must be grid "
                "points between the wire's ends."
            )

        bridged_points = [
            self.get_grid_point(identifier, connection_grid)
            for identifier in bridged_identifiers
        ]
        wire = Wire(
            self.next_reference(), start_point, end_point, bridged_points
        )
        self.wires_by_reference[wire.reference] = wire

        return wire

    def place_saved(self, reference, start_identifier, end_identifier,
                    connection_grid, bridged_identifiers=()):
        """
        Put a wire from a project file onto the circuit, keeping its name.

        :param reference: Saved reference, such as ``W1``.
        :rtype: Wire
        :raises ComponentError: If the wire is invalid or the name is
            already used. Nothing is stored then.
        """
        if reference in self.wires_by_reference:
            raise ComponentError(
                f"{reference} is already on this circuit."
            )

        _validate_connection_grid(connection_grid)
        start_point = self.get_grid_point(start_identifier, connection_grid)
        end_point = self.get_grid_point(end_identifier, connection_grid)
        self.refuse_duplicate(start_point, end_point)

        if isinstance(bridged_identifiers, str):
            raise ComponentError(
                f"Bridged points {bridged_identifiers!r} must be grid "
                "points between the wire's ends."
            )

        bridged_points = [
            self.get_grid_point(identifier, connection_grid)
            for identifier in bridged_identifiers
        ]
        wire = Wire(reference, start_point, end_point, bridged_points)
        self.wires_by_reference[reference] = wire

        return wire

    def refuse_duplicate(self, start_point, end_point):
        """
        Refuse a second wire between the same two points, either order.

        :param start_point: (row, column) of end A.
        :type start_point: tuple
        :param end_point: (row, column) of end B.
        :type end_point: tuple
        :returns: None
        :raises ComponentError: If a wire already joins the two points.
        """
        existing_wire = self.find_wire_between(start_point, end_point)

        if existing_wire is not None:
            raise ComponentError(
                f"{existing_wire.reference} already joins "
                f"{existing_wire.start_identifier} and "
                f"{existing_wire.end_identifier}."
            )

    def find_crossings(self, start_identifier, end_identifier,
                       connection_grid):
        """
        Return interior points of a new wire that another wire already joins.

        An end landing on a wire is a connection, not a crossing, so it is
        not listed. The wire is not stored.

        :param start_identifier: Point of end A.
        :type start_identifier: str
        :param end_identifier: Point of end B.
        :type end_identifier: str
        :param connection_grid: Grid both ends must be on.
        :type connection_grid: ConnectionGrid
        :returns: (identifier, wire references) from end A toward end B.
        :rtype: list
        :raises ComponentError: If the span is illegal or a duplicate.
        """
        _validate_connection_grid(connection_grid)

        start_point = self.get_grid_point(start_identifier, connection_grid)
        end_point = self.get_grid_point(end_identifier, connection_grid)
        self.refuse_duplicate(start_point, end_point)

        # "W1" is only so the temporary wire can be built. It is not stored,
        # and it is not the reference the collection would assign.
        span = Wire("W1", start_point, end_point)
        crossings = []

        for identifier in span.get_inner_point_identifiers():
            others = self.get_wires_at(identifier)

            if others:
                crossings.append(
                    (identifier, [wire.reference for wire in others])
                )

        return crossings

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
            if identifier in wire.get_joined_identifiers()
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
    Which grid points and part pins are connected, for the part tooltips.

    A wire joins every point it covers (breadboard strip) except a bridge,
    which is hopped and left out. Points on either side of a hop stay one
    net. Wires that share any joined point are one net, and part pins on
    the same point are connected with or without a wire. This is a light
    stand-in for M2's NetMap. A net with a ground pin is SPICE node "0".
    Points that share a net label (Vcc and vcc count as the same name)
    are one net even when no wire joins them.

    :param wire_collection: Wires to group.
    :type wire_collection: WireCollection
    :param ground_identifiers: Points that a ground pin sits on.
    :type ground_identifiers: iterable of str
    :param pin_labels: (point, label) for every part pin, for example
        ("NODE_R02_C03", "R1.2").
    :type pin_labels: iterable of tuple
    :param net_labels: (point, name) for every named point, for example
        ("NODE_R02_C05", "Vcc").
    :type net_labels: iterable of tuple
    :raises ComponentError: If an argument has the wrong type.
    """

    def __init__(self, wire_collection, ground_identifiers=(),
                 pin_labels=(), net_labels=()):
        if not isinstance(wire_collection, WireCollection):
            raise ComponentError(
                f"Expected a WireCollection, not "
                f"{type(wire_collection).__name__}."
            )

        ground_identifiers = tuple(ground_identifiers)

        for identifier in ground_identifiers:
            _validate_identifier(identifier)

        pin_labels = tuple(pin_labels)

        for pin_label in pin_labels:
            if (not isinstance(pin_label, tuple) or len(pin_label) != 2 or
                    not isinstance(pin_label[1], str)):
                raise ComponentError(
                    f"Pin labels must be (point, label) pairs such as "
                    f"('NODE_R02_C03', 'R1.2'), not {pin_label!r}."
                )

            _validate_identifier(pin_label[0])

        net_labels = tuple(net_labels)
        names_by_key = {}
        points_by_key = {}

        for net_label in net_labels:
            if (not isinstance(net_label, tuple) or len(net_label) != 2 or
                    not isinstance(net_label[1], str) or net_label[1] == ""):
                raise ComponentError(
                    "Net labels must be (point, name) pairs such as "
                    f"('NODE_R02_C03', 'Vcc'), not {net_label!r}."
                )

            _validate_identifier(net_label[0])
            key = net_label[1].casefold()
            names_by_key.setdefault(key, net_label[1])
            points_by_key.setdefault(key, []).append(net_label[0])

        self._ground_identifiers = frozenset(ground_identifiers)
        self._parent_by_point = {}

        for wire in wire_collection.get_wires():
            identifiers = wire.get_joined_identifiers()

            for first, second in itertools.pairwise(identifiers):
                self._union(first, second)

        for identifiers in points_by_key.values():
            self._find(identifiers[0])

            for identifier in identifiers[1:]:
                self._union(identifiers[0], identifier)

        self._names_by_root = {}
        seen_names = {}

        for key, identifiers in points_by_key.items():
            root = self._find(identifiers[0])
            folded = names_by_key[key].casefold()

            if folded in seen_names.setdefault(root, set()):
                continue

            seen_names[root].add(folded)
            self._names_by_root.setdefault(root, []).append(
                names_by_key[key]
            )

        for names in self._names_by_root.values():
            names.sort(key=str.casefold)

        self._points_by_root = {}
        self._wires_by_root = {}
        self._labels_by_root = {}

        for identifier in list(self._parent_by_point):
            self._points_by_root.setdefault(
                self._find(identifier), []
            ).append(identifier)

        for wire in wire_collection.get_wires():
            self._wires_by_root.setdefault(
                self._find(wire.start_identifier), []
            ).append(wire.reference)

        for identifier, label in pin_labels:
            self._labels_by_root.setdefault(
                self._find(identifier), []
            ).append(label)

    def _find(self, identifier):
        """
        Return the representative point of a group (path halving).

        A point no wire covers is its own group.

        :rtype: str
        """
        parent_by_point = self._parent_by_point
        parent_by_point.setdefault(identifier, identifier)

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

    def _root_of(self, identifier):
        """
        Return the group of a valid identifier without adding it.

        :rtype: str or None
        """
        _validate_identifier(identifier)

        if identifier not in self._parent_by_point:
            return None

        return self._find(identifier)

    def get_points(self, identifier):
        """
        Return the points of the net through one point, row-column order.

        :param identifier: Connection-point identifier.
        :type identifier: str
        :returns: The joined identifiers, including this one; just this
            one when no wire covers it.
        :rtype: tuple
        :raises ComponentError: If identifier is not an identifier.
        """
        root = self._root_of(identifier)

        if root is None:
            return (identifier,)

        return tuple(sorted(
            set(self._points_by_root.get(root, [])) | {identifier},
            key=_point_sort_key
        ))

    def get_wire_references(self, identifier):
        """
        Return the wires of the net through one point (W2 before W10).

        :param identifier: Connection-point identifier.
        :type identifier: str
        :returns: Wire references; empty when no wire covers the net.
        :rtype: tuple
        :raises ComponentError: If identifier is not an identifier.
        """
        root = self._root_of(identifier)

        return tuple(sorted(
            self._wires_by_root.get(root, []), key=_wire_sort_key
        ))

    def get_pin_labels(self, identifier):
        """
        Return the labels of every part pin on the net, naturally sorted.

        :param identifier: Connection-point identifier.
        :type identifier: str
        :returns: Labels such as ("C1.1", "R1.2", "R10.1").
        :rtype: tuple
        :raises ComponentError: If identifier is not an identifier.
        """
        root = self._root_of(identifier)

        return tuple(sorted(
            self._labels_by_root.get(root, []), key=_natural_sort_key
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

    def get_net_names(self, identifier):
        """
        Return the names on the net through one point, such as ("Vcc",).

        Two names that differ only by case count as one, and the first
        spelling is kept. A wire that joins Vcc to Vss lists both.

        :param identifier: Connection-point identifier.
        :type identifier: str
        :rtype: tuple
        :raises ComponentError: If identifier is not an identifier.
        """
        root = self._root_of(identifier)

        if root is None:
            return ()

        return tuple(self._names_by_root.get(root, ()))

    def describe(self, identifier, own_label=None):
        """
        Describe the net through one point, for a pin's tooltip line.

        Examples: "to C1.1 via W2, W3", "to C1.1" (two parts on one point,
        no wire), "node 0 (ground) to GND1.gnd via W4", "Vcc to R1.1"
        and "not connected".

        :param identifier: Connection-point identifier.
        :type identifier: str
        :param own_label: The asking pin's label, left out of the list.
        :type own_label: str or None
        :rtype: str
        :raises ComponentError: If identifier is not an identifier.
        """
        other_labels = [
            label for label in self.get_pin_labels(identifier)
            if label != own_label
        ]
        wire_references = self.get_wire_references(identifier)
        pieces = []
        heading = []

        if self.get_net_names(identifier):
            heading.append(", ".join(self.get_net_names(identifier)))

        if self.is_ground(identifier):
            heading.append("node 0 (ground)")

        if heading:
            pieces.append(", ".join(heading))

        if other_labels:
            pieces.append(f"to {', '.join(other_labels)}")

        if wire_references:
            pieces.append(f"via {', '.join(wire_references)}")

        return " ".join(pieces) if pieces else "not connected"


def _point_sort_key(identifier):
    """
    Sort key for identifiers: row, then column, as numbers.

    :rtype: tuple
    """
    match = _POINT_IDENTIFIER_PATTERN.fullmatch(identifier)

    return (int(match.group(1)), int(match.group(2)))


def _natural_sort_key(text):
    """
    Natural sort key: "R2.1" before "R10.1".

    :rtype: list
    """
    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"([0-9]+)", text)
    ]


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


def describe_crossings(crossings):
    """
    Describe the wires a new wire would cross, for the Connect / Bridge choice.

    :param crossings: (identifier, wire references) from find_crossings.
    :type crossings: list
    :returns: Text such as "This wire crosses NODE_R02_C04 (W1)."
    :rtype: str
    """
    pieces = [
        f"{identifier} ({', '.join(references)})"
        for identifier, references in crossings
    ]

    if len(pieces) == 1:
        return f"This wire crosses {pieces[0]}."

    return (
        "This wire crosses " + ", ".join(pieces[:-1]) + " and " +
        pieces[-1] + "."
    )


def find_junction_identifiers(wire_collection, pin_identifiers=()):
    """
    Return the grid points that need a junction dot.

    Each wire end at a point counts 1, a wire passing over it mid-span
    counts 2 (it leaves both ways) and each part pin on it counts 1. A
    bridge does not meet that point, so the hopping wire adds nothing
    there and a pure crossing has no dot. A point on a wire with 3 or
    more gets a dot: a wire passing a pin or meeting another wire
    mid-span (T or crossing), or three wire ends. A plain corner (two
    ends) or a wire ending on a pin (2) gets none.

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
