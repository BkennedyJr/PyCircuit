"""
Connection-grid data model.

This module defines the platform-independent data model for a rectangular
grid of circuit connection points. The model contains no PyQt5 imports so
it can later be used by the GUI, command-line scripts, test code, and the
SPICE netlist-generation layer.
"""

import re

from core.exceptions import GridConfigurationError


MINIMUM_GRID_DIMENSION = 1
MAXIMUM_GRID_DIMENSION = 50
# Vcc, Vss, Vdd and similar names. The first character is a letter so a
# value such as 5V is not stored as a name. Matching ignores case.
NET_LABEL_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,15}$")


class ConnectionPoint(object):
    """
    One selectable electrical connection point in the circuit workspace.

    A connection point is identified by a stable row-and-column identifier.
    For example, the point in row 1 and column 1 is named ``NODE_R01_C01``.

    :param identifier: Stable connection-point identifier.
    :type identifier: str
    :param row_number: One-based row number in the connection grid.
    :type row_number: int
    :param column_number: One-based column number in the connection grid.
    :type column_number: int
    """

    def __init__(self, identifier, row_number, column_number):
        self.identifier = identifier
        self.row_number = row_number
        self.column_number = column_number

        # Signal-pickoff state will later identify nodes for Bode plotting
        # and other analysis outputs.
        self.is_signal_pickoff = False
        # A name such as Vcc. Every point with the same name, ignoring
        # case, is one electrical node. Empty means this point has no name.
        self.net_label = ""


class ConnectionGrid(object):
    """
    Data model for a configurable rectangular grid of connection points.

    The initial implementation provides selectable connection points and
    signal-pickoff selection. Future versions will associate reusable
    circuit nodes, components, wires, and electrical nets with these points.

    :param row_count: Number of connection-point rows.
    :type row_count: int
    :param column_count: Number of connection-point columns.
    :type column_count: int
    """

    def __init__(self, row_count=8, column_count=8):
        self.row_count = 0
        self.column_count = 0
        self.connection_points_by_identifier = {}

        # Build the initial grid only after input validation succeeds.
        self.configure(row_count, column_count)

    @staticmethod
    def build_connection_point_identifier(row_number, column_number):
        """
        Build a stable identifier for one connection point.

        :param row_number: One-based connection-grid row number.
        :type row_number: int
        :param column_number: One-based connection-grid column number.
        :type column_number: int
        :returns: Stable connection-point identifier.
        :rtype: str
        """
        return "NODE_R{0:02d}_C{1:02d}".format(
            row_number,
            column_number
        )

    @staticmethod
    def validate_grid_dimension(grid_dimension, dimension_name):
        """
        Validate one requested row or column dimension.

        :param grid_dimension: Requested grid dimension.
        :type grid_dimension: int
        :param dimension_name: User-facing name of the dimension.
        :type dimension_name: str
        :returns: Validated integer grid dimension.
        :rtype: int
        :raises GridConfigurationError: If the dimension is invalid.
        """
        # Reject Boolean values because Python treats them as integers, but
        # they do not represent a meaningful grid size.
        if isinstance(grid_dimension, bool):
            raise GridConfigurationError(
                "{0} must be an integer from {1} through {2}."
                .format(
                    dimension_name,
                    MINIMUM_GRID_DIMENSION,
                    MAXIMUM_GRID_DIMENSION
                )
            )

        # Confirm that the caller supplied an integer before range checking.
        if not isinstance(grid_dimension, int):
            raise GridConfigurationError(
                "{0} must be an integer from {1} through {2}."
                .format(
                    dimension_name,
                    MINIMUM_GRID_DIMENSION,
                    MAXIMUM_GRID_DIMENSION
                )
            )

        # Limit dimensions to protect GUI performance and prevent accidental
        # creation of an impractically large number of connection points.
        if grid_dimension < MINIMUM_GRID_DIMENSION:
            raise GridConfigurationError(
                "{0} must be at least {1}."
                .format(dimension_name, MINIMUM_GRID_DIMENSION)
            )

        if grid_dimension > MAXIMUM_GRID_DIMENSION:
            raise GridConfigurationError(
                "{0} cannot exceed {1}."
                .format(dimension_name, MAXIMUM_GRID_DIMENSION)
            )

        return grid_dimension

    @staticmethod
    def normalize_net_label(net_label):
        """
        Return a net label ready to store, or an empty string to clear it.

        Leading and trailing spaces are removed. ``Vcc`` and ``vcc`` are
        kept as typed; callers compare them without regard to case.

        :param net_label: Requested name, such as ``Vcc``.
        :type net_label: str
        :returns: The stored name, or ``""`` when the label is cleared.
        :rtype: str
        :raises GridConfigurationError: If the name is not allowed.
        """
        if not isinstance(net_label, str):
            raise GridConfigurationError(
                "A net label must be text, such as Vcc."
            )

        net_label = net_label.strip()

        if net_label == "":
            return ""

        if NET_LABEL_PATTERN.fullmatch(net_label) is None:
            raise GridConfigurationError(
                "A net label must start with a letter and use only "
                "letters, digits and underscores, up to 16 characters. "
                f"'{net_label}' is not allowed."
            )

        return net_label

    def configure(self, row_count, column_count):
        """
        Create or resize the connection-point grid.

        Signal pickoffs and net labels that still exist after a resize are
        preserved. For example, a pickoff or a Vcc label at row 2, column 3
        remains when changing from an 8x8 grid to a 10x10 grid. Anything
        outside a reduced grid is removed.

        :param row_count: Requested number of rows.
        :type row_count: int
        :param column_count: Requested number of columns.
        :type column_count: int
        :returns: Identifiers of pickoffs removed by grid reduction.
        :rtype: list
        :raises GridConfigurationError: If rows or columns are invalid.
        """
        validated_row_count = self.validate_grid_dimension(
            row_count,
            "Row count"
        )
        validated_column_count = self.validate_grid_dimension(
            column_count,
            "Column count"
        )

        # Record existing signal-pickoff identifiers before rebuilding the
        # grid so compatible pickoffs can survive a non-destructive resize.
        existing_pickoff_identifiers = set(
            self.get_signal_pickoff_identifiers()
        )
        existing_net_labels = self.get_net_labels()

        new_connection_points_by_identifier = {}

        # Build all connection points in temporary storage first. The active
        # grid state is changed only after construction completes successfully.
        for row_number in range(1, validated_row_count + 1):
            for column_number in range(1, validated_column_count + 1):
                connection_point_identifier = (
                    self.build_connection_point_identifier(
                        row_number,
                        column_number
                    )
                )

                connection_point = ConnectionPoint(
                    connection_point_identifier,
                    row_number,
                    column_number
                )

                new_connection_points_by_identifier[
                    connection_point_identifier
                ] = connection_point

        # Restore prior pickoff selections only where the corresponding point
        # remains available in the newly requested grid dimensions.
        for pickoff_identifier in existing_pickoff_identifiers:
            if pickoff_identifier in new_connection_points_by_identifier:
                new_connection_points_by_identifier[
                    pickoff_identifier
                ].is_signal_pickoff = True

        for identifier, net_label in existing_net_labels.items():
            if identifier in new_connection_points_by_identifier:
                new_connection_points_by_identifier[
                    identifier
                ].net_label = net_label

        removed_pickoff_identifiers = sorted(
            existing_pickoff_identifiers.difference(
                set(new_connection_points_by_identifier.keys())
            )
        )

        # Commit the validated replacement grid as one coherent state update.
        self.row_count = validated_row_count
        self.column_count = validated_column_count
        self.connection_points_by_identifier = (
            new_connection_points_by_identifier
        )

        return removed_pickoff_identifiers

    def get_connection_point_count(self):
        """
        Return the total number of available connection points.

        :returns: Total connection-point count.
        :rtype: int
        """
        return len(self.connection_points_by_identifier)

    def get_connection_point(self, connection_point_identifier):
        """
        Return a connection point by stable identifier.

        :param connection_point_identifier: Identifier to locate.
        :type connection_point_identifier: str
        :returns: Requested connection point.
        :rtype: ConnectionPoint
        :raises GridConfigurationError: If the identifier is unknown.
        """
        if connection_point_identifier not in (
                self.connection_points_by_identifier):
            raise GridConfigurationError(
                "Connection point '{}' does not exist in the current grid."
                .format(connection_point_identifier)
            )

        return self.connection_points_by_identifier[
            connection_point_identifier
        ]

    def toggle_signal_pickoff(self, connection_point_identifier):
        """
        Toggle signal-pickoff selection for one connection point.

        Signal pickoffs are the foundation for selecting arbitrary signal
        locations for future Bode plots and other simulation outputs.

        :param connection_point_identifier: Point to toggle.
        :type connection_point_identifier: str
        :returns: New signal-pickoff state.
        :rtype: bool
        :raises GridConfigurationError: If the identifier is unknown.
        """
        connection_point = self.get_connection_point(
            connection_point_identifier
        )

        connection_point.is_signal_pickoff = (
            not connection_point.is_signal_pickoff
        )

        return connection_point.is_signal_pickoff

    def set_net_label(self, connection_point_identifier, net_label):
        """
        Name one connection point, or clear its name.

        Points that share a name, ignoring case, are the same electrical
        node. An empty name clears the label. A refused name leaves the
        previous one in place.

        :param connection_point_identifier: Point to name.
        :type connection_point_identifier: str
        :param net_label: Name such as ``Vcc``, or blank to clear.
        :type net_label: str
        :returns: The stored name, or ``""`` when cleared.
        :rtype: str
        :raises GridConfigurationError: If the point or the name is invalid.
        """
        connection_point = self.get_connection_point(
            connection_point_identifier
        )
        normalized_net_label = self.normalize_net_label(net_label)
        connection_point.net_label = normalized_net_label

        return normalized_net_label

    def get_net_labels(self):
        """
        Return the name of every labeled connection point.

        :returns: Identifier to name, for example
            ``{"NODE_R02_C05": "Vcc"}``.
        :rtype: dict
        """
        net_labels = {}

        for connection_point in self.connection_points_by_identifier.values():
            if connection_point.net_label:
                net_labels[connection_point.identifier] = (
                    connection_point.net_label
                )

        return net_labels

    def get_signal_pickoff_identifiers(self):
        """
        Return all selected signal-pickoff identifiers.

        :returns: Sorted signal-pickoff identifiers.
        :rtype: list
        """
        signal_pickoff_identifiers = []

        for connection_point in self.connection_points_by_identifier.values():
            if connection_point.is_signal_pickoff:
                signal_pickoff_identifiers.append(
                    connection_point.identifier
                )

        return sorted(signal_pickoff_identifiers)

    def to_dict(self):
        """
        Convert the connection-grid state into JSON-compatible data.

        :returns: Serializable connection-grid data.
        :rtype: dict
        """
        return {
            "row_count": self.row_count,
            "column_count": self.column_count,
            "signal_pickoff_identifiers": (
                self.get_signal_pickoff_identifiers()
            ),
            "net_labels": self.get_net_labels()
        }

    @classmethod
    def from_dict(cls, connection_grid_data):
        """
        Build a validated connection grid from JSON-compatible data.

        :param connection_grid_data: Serialized connection-grid data.
        :type connection_grid_data: dict
        :returns: Validated connection grid.
        :rtype: ConnectionGrid
        :raises GridConfigurationError: If the data is incomplete or invalid.
        """
        if not isinstance(connection_grid_data, dict):
            raise GridConfigurationError(
                "Connection-grid data must be a JSON object."
            )

        required_field_names = [
            "row_count",
            "column_count",
            "signal_pickoff_identifiers"
        ]

        # Confirm all required settings exist before attempting to construct
        # a grid. This produces a direct explanation for incomplete projects.
        for required_field_name in required_field_names:
            if required_field_name not in connection_grid_data:
                raise GridConfigurationError(
                    "Connection-grid data is missing required field '{}'."
                    .format(required_field_name)
                )

        connection_grid = cls(
            connection_grid_data["row_count"],
            connection_grid_data["column_count"]
        )

        signal_pickoff_identifiers = connection_grid_data[
            "signal_pickoff_identifiers"
        ]

        if not isinstance(signal_pickoff_identifiers, list):
            raise GridConfigurationError(
                "'signal_pickoff_identifiers' must be a JSON list."
            )

        # Restore requested pickoffs only after confirming that every saved
        # identifier belongs to the configured connection grid.
        for pickoff_identifier in signal_pickoff_identifiers:
            if not isinstance(pickoff_identifier, str):
                raise GridConfigurationError(
                    "Each signal-pickoff identifier must be text."
                )

            connection_point = connection_grid.get_connection_point(
                pickoff_identifier
            )
            connection_point.is_signal_pickoff = True

        # Older project files have no net labels. A missing field means
        # every point is unnamed.
        net_labels = connection_grid_data.get("net_labels", {})

        if not isinstance(net_labels, dict):
            raise GridConfigurationError(
                "'net_labels' must be a JSON object mapping a point "
                "such as NODE_R02_C03 to a name such as Vcc."
            )

        for identifier, net_label in net_labels.items():
            if not isinstance(identifier, str):
                raise GridConfigurationError(
                    "Each net-label point must be text."
                )

            normalized_net_label = cls.normalize_net_label(net_label)

            if normalized_net_label == "":
                raise GridConfigurationError(
                    "A saved net label cannot be blank."
                )

            connection_grid.set_net_label(
                identifier,
                normalized_net_label
            )

        return connection_grid