"""
A part waiting to be placed (Billie, Oct 9 12:07).

Place no longer drops a part straight onto the grid. It starts a
PendingPlacement at the selected point: the editor shows it as a
semi-transparent "ghost", the user turns it with the arrow keys (or
W/A/S/D) and commits it with Enter or a right-click. Until then the part
is not in the collection.

A direction names where the part points from its anchor, the selected
point:

- a two-pin part points from its first pin (the anchor) toward its second
  pin, so a polarized capacitor pointing Down at R7 C4 has its minus pin
  at R8 C4;
- a one-pin part (ground) points from its pin toward its body;
- transistors and op-amps point Right at rotation 0 (base or inputs on
  the left), and turn with the same rotation.

Sources stand upright at rotation 0, so for them Down is rotation 0 and
Right is rotation 270.

This module contains no PyQt5 imports.
"""

from core.components import (
    COMPONENT_DEFINITIONS,
    VALID_ROTATIONS,
    Component,
    ComponentCollection,
    rotate_offset,
)
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError

# Clockwise on screen, the same way rotations turn.
DIRECTIONS = ("right", "down", "left", "up")

_DIRECTION_BY_STEP = {
    (1, 0): "right",
    (0, 1): "down",
    (-1, 0): "left",
    (0, -1): "up",
}

# Largest grid (core.connection_grid allows up to 50 x 50); used to work
# out a new part's default texts away from any edge.
_SCRATCH_GRID_SIZE = 50


def _sign(number):
    return (number > 0) - (number < 0)


def _get_kind_definition(kind):
    if not isinstance(kind, str) or kind not in COMPONENT_DEFINITIONS:
        raise ComponentError(f"Unknown component kind {kind!r}.")

    return COMPONENT_DEFINITIONS[kind]


def get_direction_at_rotation_zero(kind):
    """
    Return where a kind points at rotation 0.

    :param kind: Component kind.
    :type kind: str
    :returns: "right", "down", "left" or "up".
    :rtype: str
    :raises ComponentError: If the kind is unknown.
    """
    definition = _get_kind_definition(kind)
    pins = definition["pins"]

    if len(pins) == 2:
        (_name_1, dx_1, dy_1), (_name_2, dx_2, dy_2) = pins
        step = (_sign(dx_2 - dx_1), _sign(dy_2 - dy_1))
    elif len(pins) == 1:
        # Ground: from the pin toward the body it draws.
        dx, dy = definition["covered_half_steps"][0]
        step = (_sign(dx), _sign(dy))
    else:
        # Transistors and op-amps are drawn facing right.
        step = (1, 0)

    return _DIRECTION_BY_STEP[step]


def get_rotation_for_direction(kind, direction):
    """
    Return the rotation that makes a kind point in a direction.

    :param kind: Component kind.
    :type kind: str
    :param direction: "right", "down", "left" or "up".
    :type direction: str
    :returns: 0, 90, 180 or 270.
    :rtype: int
    :raises ComponentError: If the kind or direction is unknown.
    """
    _validate_direction(direction)
    start = DIRECTIONS.index(get_direction_at_rotation_zero(kind))
    quarter_turns = (DIRECTIONS.index(direction) - start) % 4

    return VALID_ROTATIONS[quarter_turns]


def get_direction_for_rotation(kind, rotation):
    """
    Return where a kind points at a rotation.

    :param kind: Component kind.
    :type kind: str
    :param rotation: 0, 90, 180 or 270.
    :type rotation: int
    :returns: "right", "down", "left" or "up".
    :rtype: str
    :raises ComponentError: If the kind or rotation is invalid.
    """
    # rotate_offset validates the rotation.
    rotate_offset(0, 0, rotation)
    start = DIRECTIONS.index(get_direction_at_rotation_zero(kind))

    return DIRECTIONS[(start + VALID_ROTATIONS.index(rotation)) % 4]


def _validate_direction(direction):
    if direction not in DIRECTIONS:
        raise ComponentError(
            f"Direction must be one of {', '.join(DIRECTIONS)}, not "
            f"{direction!r}."
        )


class PendingPlacement:
    """
    A new part at a grid point and direction, not yet in the collection.

    The value and settings are checked when it is created, so a bad value
    is refused before a ghost appears. Where it may go is checked by
    check(); commit() adds it to the collection or raises.
    """

    def __init__(
            self,
            component_collection,
            connection_grid,
            kind,
            value_text,
            row_number,
            column_number,
            parameter_texts=None,
            direction=None):
        """
        :param component_collection: Parts already placed.
        :type component_collection: ComponentCollection
        :param connection_grid: Grid the part must fit on.
        :type connection_grid: ConnectionGrid
        :param kind: Component kind.
        :type kind: str
        :param value_text: Value as typed; empty means the default.
        :type value_text: str
        :param row_number: One-based anchor row.
        :type row_number: int
        :param column_number: One-based anchor column.
        :type column_number: int
        :param parameter_texts: Extra settings by name, or None.
        :type parameter_texts: dict or None
        :param direction: Starting direction; None means the kind's
            direction at rotation 0.
        :type direction: str or None
        :raises ComponentError: If an argument, the value or a setting is
            invalid, or the point is not on the grid.
        """
        if not isinstance(component_collection, ComponentCollection):
            raise ComponentError(
                f"Expected a ComponentCollection, not "
                f"{type(component_collection).__name__}."
            )

        if not isinstance(connection_grid, ConnectionGrid):
            raise ComponentError(
                f"Expected a ConnectionGrid, not "
                f"{type(connection_grid).__name__}."
            )

        self.component_collection = component_collection
        self.connection_grid = connection_grid
        self.kind = kind
        self.value_text, self.parameter_texts = self._resolve_texts(
            kind, value_text, parameter_texts
        )
        self.row_number = None
        self.column_number = None
        self.move_to(row_number, column_number)
        self.direction = get_direction_at_rotation_zero(kind)

        if direction is not None:
            self.set_direction(direction)

    @staticmethod
    def _resolve_texts(kind, value_text, parameter_texts):
        """
        Return the value and settings texts add_component would store.

        The part is added to an empty scratch collection on the largest
        grid, so empty text gets exactly the default add_component gives
        (an LED's model follows its color) and a bad value raises the same
        ComponentError.
        """
        _get_kind_definition(kind)
        middle = _SCRATCH_GRID_SIZE // 2
        scratch_part = ComponentCollection().add_component(
            kind,
            middle,
            middle,
            value_text,
            ConnectionGrid(_SCRATCH_GRID_SIZE, _SCRATCH_GRID_SIZE),
            parameter_texts=parameter_texts
        )

        return scratch_part.value_text, dict(scratch_part.parameter_texts)

    @property
    def rotation(self):
        """Rotation in degrees for the current direction."""
        return get_rotation_for_direction(self.kind, self.direction)

    @property
    def identifier(self):
        """Anchor point identifier, for example "NODE_R07_C04"."""
        return ConnectionGrid.build_connection_point_identifier(
            self.row_number, self.column_number
        )

    def move_to(self, row_number, column_number):
        """
        Move the anchor to another grid point.

        :param row_number: One-based row.
        :type row_number: int
        :param column_number: One-based column.
        :type column_number: int
        :returns: None
        :raises ComponentError: If the point is not on the grid.
        """
        if (isinstance(row_number, bool) or
                isinstance(column_number, bool) or
                not isinstance(row_number, int) or
                not isinstance(column_number, int) or
                not 1 <= row_number <= self.connection_grid.row_count or
                not 1 <= column_number <= self.connection_grid.column_count):
            raise ComponentError(
                f"Row {row_number!r}, column {column_number!r} is not a "
                f"point on the {self.connection_grid.row_count} x "
                f"{self.connection_grid.column_count} grid."
            )

        self.row_number = row_number
        self.column_number = column_number

    def set_direction(self, direction):
        """
        Point the part right, down, left or up.

        :param direction: "right", "down", "left" or "up".
        :type direction: str
        :returns: None
        :raises ComponentError: If the direction is unknown.
        """
        _validate_direction(direction)
        self.direction = direction

    def build_component(self, direction=None):
        """
        Return the part as it would be placed (not stored).

        :param direction: Direction to try; None means the current one.
        :type direction: str or None
        :returns: A Component with the next free reference.
        :rtype: Component
        """
        rotation = self.rotation

        if direction is not None:
            rotation = get_rotation_for_direction(self.kind, direction)

        return Component(
            self.kind,
            self.component_collection.next_reference(self.kind),
            self.value_text,
            self.row_number,
            self.column_number,
            rotation,
            dict(self.parameter_texts)
        )

    def check(self, direction=None):
        """
        Say whether the part may be placed here, pointing this way.

        :param direction: Direction to try; None means the current one.
        :type direction: str or None
        :returns: None if allowed, otherwise the reason it is refused.
        :rtype: str or None
        """
        component = self.build_component(direction)

        try:
            self.component_collection.ensure_pins_fit_grid(
                component, self.connection_grid
            )
            self.component_collection.ensure_no_overlap(component)
        except ComponentError as error:
            return str(error)

        return None

    def get_free_directions(self):
        """
        Return the directions the part may point at this grid point.

        :returns: Allowed directions, in the order right, down, left, up.
        :rtype: list
        """
        return [
            direction
            for direction in DIRECTIONS
            if self.check(direction) is None
        ]

    def describe_free_directions(self):
        """
        Return a sentence naming the free directions at this grid point.

        :returns: For example "Free directions at NODE_R07_C04: Down,
            Left." or "No direction is free at NODE_R07_C04; pick another
            grid point."
        :rtype: str
        """
        free_directions = self.get_free_directions()

        if not free_directions:
            return (
                f"No direction is free at {self.identifier}; pick another "
                "grid point."
            )

        return (
            f"Free directions at {self.identifier}: "
            f"{', '.join(direction.title() for direction in free_directions)}."
        )

    def commit(self):
        """
        Add the part to the collection where it now points.

        :returns: The stored component.
        :rtype: Component
        :raises ComponentError: If it is refused there. The message adds
            the free directions at this point, and nothing is stored.
        """
        reason = self.check()

        if reason is not None:
            raise ComponentError(f"{reason} {self.describe_free_directions()}")

        return self.component_collection.add_component(
            self.kind,
            self.row_number,
            self.column_number,
            self.value_text,
            self.connection_grid,
            self.rotation,
            dict(self.parameter_texts)
        )
