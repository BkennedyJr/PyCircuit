"""
PyQt5 graphics-scene classes for the connection-grid editor.

This module draws and manages selectable connection points, the placed
parts and the wires. In Wire mode a left press on a grid point starts a
wire: a dashed rubber-band line follows the mouse, and releasing on another
grid point adds a straight wire between the two points (Esc cancels). Out
of Wire mode, a left-drag on the board pans the view (the middle button
does the same). Shift+left-drag rubber-band selects. A click selects, and
a drag on a part moves that part. It remains separate from the core data
model so future command-line or test workflows can use the connection-grid
model without importing PyQt5.
"""

import math

from PyQt5 import sip
from PyQt5.QtCore import QEvent
from PyQt5.QtCore import QPoint
from PyQt5.QtCore import QPointF
from PyQt5.QtCore import QRectF
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtGui import QFont
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtGui import QPainter
from PyQt5.QtGui import QPen
from PyQt5.QtGui import QTransform
from PyQt5.QtCore import QLineF
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QGraphicsEllipseItem
from PyQt5.QtWidgets import QGraphicsLineItem
from PyQt5.QtWidgets import QGraphicsScene
from PyQt5.QtWidgets import QGraphicsSimpleTextItem
from PyQt5.QtWidgets import QGraphicsView

from core.components import COMPONENT_DEFINITIONS
from core.exceptions import ComponentError
from core.exceptions import GridConfigurationError
from core.placement import PendingPlacement
from core.wires import WireNets
from core.wires import find_junction_identifiers
from gui.probe_item import ProbeItem
from gui.component_item import (
    LABEL_PATCH_PADDING,
    LABEL_SIDES,
    ComponentItem,
    text_touches_a_grid_dot,
)
from gui.wire_item import WIRE_COLOR, WireItem, build_preview_pen

GRID_POINT_SPACING = 60
GRID_ORIGIN_X = 90
GRID_ORIGIN_Y = 80
CONNECTION_POINT_DIAMETER = 16
# Grid points stack above component labels (-0.5) and below parts (1).
CONNECTION_POINT_Z_VALUE = 0
# Default header positions: column headers at this y, row headers at this x.
HEADER_POSITION = 25
# Space kept between the headers and any part or label.
HEADER_GAP = 8
# Extra room around everything when the scene grows to fit the parts.
SCENE_MARGIN = 20
# In Wire mode a press or release counts as "on" a grid point within this
# distance of its centre (a third of a step: generous, never ambiguous).
WIRE_SNAP_DISTANCE = 20
# The rubber-band line draws above everything while a wire is drawn.
WIRE_PREVIEW_Z_VALUE = 3
# Zoom factors: 1.0 shows a grid step as GRID_POINT_SPACING pixels. One
# wheel notch or one Zoom In/Out is ZOOM_STEP. MINIMUM_ZOOM still shows a
# 50 x 50 grid in a small window; MAXIMUM_ZOOM makes one step 480 pixels.
ZOOM_STEP = 1.25
MINIMUM_ZOOM = 0.1
MAXIMUM_ZOOM = 8.0
ZOOM_TOLERANCE = 1e-6
# Junction dots (core.wires.find_junction_identifiers) sit on top of the
# grid dot, in the wire color, below the parts.
# While a part waits to be placed, these keys turn it (arrows and
# W/A/S/D, Billie Oct 9 12:07-12:08), Enter or Return places it and Esc
# cancels it. Keypad arrows and Enter count too; other modifiers do not.
PENDING_DIRECTION_BY_KEY = {
    Qt.Key_Right: "right",
    Qt.Key_D: "right",
    Qt.Key_Down: "down",
    Qt.Key_S: "down",
    Qt.Key_Left: "left",
    Qt.Key_A: "left",
    Qt.Key_Up: "up",
    Qt.Key_W: "up",
}
PENDING_COMMIT_KEYS = (Qt.Key_Return, Qt.Key_Enter)

JUNCTION_DIAMETER = 14
JUNCTION_Z_VALUE = 0.5


def grid_point_to_scene_position(row_number, column_number):
    """
    Return the scene position of a grid point (1-based row and column).

    Same formula as ConnectionGridScene.rebuild_connection_point_items.

    :param row_number: Row of the grid point.
    :type row_number: int
    :param column_number: Column of the grid point.
    :type column_number: int
    :returns: Scene position of the point's center.
    :rtype: QPointF
    """
    return QPointF(
        GRID_ORIGIN_X + ((column_number - 1) * GRID_POINT_SPACING),
        GRID_ORIGIN_Y + ((row_number - 1) * GRID_POINT_SPACING)
    )


def scene_position_to_grid_point(scene_position):
    """
    Return the (row, column) of the grid point nearest a scene position.

    The result may lie outside the grid (for example row 0); callers check.
    Halves round up, so the result does not depend on banker's rounding.

    :param scene_position: Position in scene coordinates.
    :type scene_position: QPointF
    :returns: One-based (row, column).
    :rtype: tuple
    """
    column_number = math.floor(
        (scene_position.x() - GRID_ORIGIN_X) / GRID_POINT_SPACING + 0.5
    ) + 1
    row_number = math.floor(
        (scene_position.y() - GRID_ORIGIN_Y) / GRID_POINT_SPACING + 0.5
    ) + 1

    return (row_number, column_number)


class ConnectionPointItem(QGraphicsEllipseItem):
    """
    Graphical representation of one selectable connection point.

    :param connection_point: Core-model connection point to display.
    :type connection_point: core.connection_grid.ConnectionPoint
    """

    def __init__(self, connection_point):
        radius = CONNECTION_POINT_DIAMETER / 2.0

        super(ConnectionPointItem, self).__init__(
            -radius,
            -radius,
            CONNECTION_POINT_DIAMETER,
            CONNECTION_POINT_DIAMETER
        )

        self.connection_point = connection_point

        # Enable normal Qt selection behavior while preventing accidental
        # movement of fixed grid points.
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemIsMovable, False)
        self.setZValue(CONNECTION_POINT_Z_VALUE)

        # The name sits above and to the right of the dot. It does not
        # take mouse clicks, so the point underneath stays selectable.
        self.net_label_item = QGraphicsSimpleTextItem(self)
        label_font = QFont()
        label_font.setPointSize(11)
        label_font.setBold(True)
        self.net_label_item.setFont(label_font)
        self.net_label_item.setBrush(QColor("#ffd166"))
        self.net_label_item.setPos(12, -22)
        self.net_label_item.setAcceptedMouseButtons(Qt.NoButton)
        self.refresh_from_point()

    def refresh_from_point(self):
        """
        Match the tooltip and the drawn name to the core point.

        :returns: None
        """
        connection_point = self.connection_point
        lines = [
            connection_point.identifier,
            f"Row: {connection_point.row_number}",
            f"Column: {connection_point.column_number}",
        ]

        if connection_point.net_label:
            lines.append(f"Net: {connection_point.net_label}")

        self.setToolTip("\n".join(lines))
        self.net_label_item.setText(connection_point.net_label)
        self.net_label_item.setVisible(bool(connection_point.net_label))
        self.update()

    def paint(self, painter, option, widget=None):
        """
        Draw the connection point according to its selection state.

        Blue points are available grid nodes. Green points are selected as
        signal pickoffs. Yellow outlines indicate the actively selected node.

        :param painter: Painter used to draw this item.
        :type painter: QPainter
        :param option: Qt style option for the graphics item.
        :type option: QStyleOptionGraphicsItem
        :param widget: Optional containing widget.
        :type widget: QWidget or None
        :returns: None
        """
        painter.save()

        # Highlight a selected point without changing its underlying pickoff
        # status. This distinguishes inspection from analysis selection.
        if self.isSelected():
            painter.setPen(QPen(QColor("#ffd166"), 3))
        else:
            painter.setPen(QPen(QColor("#102a43"), 2))

        # Use green to indicate that simulation output should later be
        # collected from this connection point.
        if self.connection_point.is_signal_pickoff:
            painter.setBrush(QColor("#4caf50"))
        else:
            painter.setBrush(QColor("#4f9ee3"))

        painter.drawEllipse(self.rect())
        painter.restore()


class ConnectionGridScene(QGraphicsScene):
    """
    Graphics scene that displays the configurable connection-point grid.

    :param connection_grid: Core-model grid to display.
    :type connection_grid: core.connection_grid.ConnectionGrid
    :param parent: Optional Qt parent object.
    :type parent: QObject or None
    """

    connection_point_selected = pyqtSignal(object)
    component_selected = pyqtSignal(object)
    # A dragged part was moved (reference), or its move was refused
    # (reference, reason); in both cases it is already drawn in place.
    component_moved = pyqtSignal(str)
    component_move_refused = pyqtSignal(str, str)
    # A wire was drawn (reference) or refused (reason). wires_selected
    # carries the references of the selected wires (possibly empty).
    wire_added = pyqtSignal(str)
    wire_refused = pyqtSignal(str)
    wires_selected = pyqtSignal(object)
    # A probe was added or moved (reference), refused (reason), or the
    # selection changed (references, possibly empty). Esc while choosing
    # the second point of a differential probe cancels that choice.
    probe_added = pyqtSignal(str)
    probe_moved = pyqtSignal(str)
    probe_refused = pyqtSignal(str)
    probes_selected = pyqtSignal(object)
    differential_cancelled = pyqtSignal()
    # A part waiting to be placed (core.placement.PendingPlacement):
    # status text after each change, the reference once placed, the
    # refusal message when Enter or a right-click is refused (it stays
    # pending), and Esc.
    pending_placement_changed = pyqtSignal(str)
    pending_placement_committed = pyqtSignal(str)
    pending_placement_refused = pyqtSignal(str)
    pending_placement_cancelled = pyqtSignal()

    def __init__(self, connection_grid, parent=None):
        super(ConnectionGridScene, self).__init__(parent)

        self.connection_grid = None
        self.connection_point_items_by_identifier = {}
        self.component_collection = None
        self.component_items_by_reference = {}
        self.wire_collection = None
        self.wire_items_by_reference = {}
        self.junction_items_by_identifier = {}
        self.probe_collection = None
        self.probe_items = []
        self.probe_readouts = {}
        # Probe mode places a probe on a click. While this reference is
        # set, the next grid click is the minus point of that differential
        # probe instead of a new probe.
        self.is_probe_mode = False
        self.pending_differential_reference = None
        self.column_header_items = []
        self.row_header_items = []

        # Wire drawing: the mode flag, the grid point where the current
        # drag started (None when not drawing) and the rubber-band line.
        self.is_wire_mode = False
        self.wire_start_identifier = None
        self.wire_preview_item = None
        # Set by the main window. Called with (start, end, crossings) when
        # a new wire passes a point another wire already joins. Returns
        # "connect", "bridge" or "cancel". None means connect, so a scene
        # used without the window keeps the old breadboard behaviour.
        self.crossing_chooser = None

        # A part waiting to be placed, and the ghost item that shows it
        # (not in component_items_by_reference).
        self.pending_placement = None
        self.pending_item = None

        # Report selection changes to the main window so it can update the
        # selected-node panel and signal-pickoff controls.
        self.selectionChanged.connect(
            self.handle_connection_point_selection_change
        )

        self.set_connection_grid(connection_grid)

    def set_connection_grid(self, connection_grid):
        """
        Replace the displayed connection grid with a validated model.

        :param connection_grid: New grid model to display.
        :type connection_grid: core.connection_grid.ConnectionGrid
        :returns: None
        """
        # A new grid (resize, new or opened project) drops a waiting part.
        self.clear_pending_placement()
        self.connection_grid = connection_grid
        self.rebuild_connection_point_items()

    def rebuild_connection_point_items(self):
        """
        Rebuild graphical labels and points from the active grid model.

        The previous graphical items are cleared only after the core model
        has already been validated by the caller.

        :returns: None
        """
        self.clear()
        self.connection_point_items_by_identifier = {}
        self.column_header_items = []
        self.row_header_items = []

        row_count = self.connection_grid.row_count
        column_count = self.connection_grid.column_count

        grid_width = (column_count - 1) * GRID_POINT_SPACING
        grid_height = (row_count - 1) * GRID_POINT_SPACING

        # Define a scene rectangle large enough for labels, points, and
        # future components that will be placed adjacent to the grid.
        self.setSceneRect(
            0,
            0,
            GRID_ORIGIN_X + grid_width + 100,
            GRID_ORIGIN_Y + grid_height + 100
        )

        # Add column labels to make the point-coordinate system readable.
        for column_number in range(1, column_count + 1):
            column_label = QGraphicsSimpleTextItem(
                "C{}".format(column_number)
            )
            column_label.setBrush(QColor("#d9e2ec"))
            column_label.setPos(
                GRID_ORIGIN_X +
                ((column_number - 1) * GRID_POINT_SPACING) - 10,
                25
            )
            self.addItem(column_label)
            self.column_header_items.append(column_label)

        # Add row labels to make point selection understandable without
        # requiring users to infer grid coordinates from visual location.
        for row_number in range(1, row_count + 1):
            row_label = QGraphicsSimpleTextItem(
                "R{}".format(row_number)
            )
            row_label.setBrush(QColor("#d9e2ec"))
            row_label.setPos(
                25,
                GRID_ORIGIN_Y +
                ((row_number - 1) * GRID_POINT_SPACING) - 10
            )
            self.addItem(row_label)
            self.row_header_items.append(row_label)

        # Create one visible selectable item for every core-model point.
        for connection_point in (
                self.connection_grid.connection_points_by_identifier.values()):
            point_x_position = (
                GRID_ORIGIN_X +
                ((connection_point.column_number - 1) * GRID_POINT_SPACING)
            )
            point_y_position = (
                GRID_ORIGIN_Y +
                ((connection_point.row_number - 1) * GRID_POINT_SPACING)
            )

            connection_point_item = ConnectionPointItem(connection_point)
            connection_point_item.setPos(
                QPointF(point_x_position, point_y_position)
            )

            self.addItem(connection_point_item)

            self.connection_point_items_by_identifier[
                connection_point.identifier
            ] = connection_point_item

        # clear() above already deleted the old component items, labels,
        # wires and any rubber-band line.
        self.component_items_by_reference = {}
        self.wire_items_by_reference = {}
        self.junction_items_by_identifier = {}
        self.probe_items = []
        self.wire_start_identifier = None
        self.wire_preview_item = None
        self.rebuild_wire_items()
        self.rebuild_component_items()
        self.rebuild_probe_items()

        # Clear the selected-node display after a rebuild because old item
        # references are no longer valid once the scene has been cleared.
        self.connection_point_selected.emit(None)

    def set_component_collection(self, component_collection):
        """
        Show the parts of a component collection on the grid.

        :param component_collection: Parts to display, or None for none.
        :type component_collection: core.components.ComponentCollection
        :returns: None
        """
        self.clear_pending_placement()
        self.component_collection = component_collection
        self.rebuild_component_items()

    def rebuild_component_items(self):
        """
        Replace every component item with fresh ones from the collection.

        :returns: None
        """
        for component_item in self.component_items_by_reference.values():
            # Skip items Qt already deleted (for example by clear()).
            if (not sip.isdeleted(component_item) and
                    component_item.scene() is self):
                self.removeItem(component_item)

        self.component_items_by_reference = {}

        if self.component_collection is not None:
            for component in self.component_collection.get_components():
                component_item = ComponentItem(component, GRID_POINT_SPACING)
                component_item.setPos(
                    grid_point_to_scene_position(
                        component.row_number,
                        component.column_number
                    )
                )
                self.addItem(component_item)

                self.component_items_by_reference[
                    component.reference
                ] = component_item

        self.layout_component_labels()
        self.update_wire_nets()
        self.rebuild_junction_items()
        self.update_scene_extent()
        # A part added, removed or moved can free or block the ghost's spot.
        self.update_pending_item(report=False)

    def refresh_component(self, reference):
        """
        Redraw one part after its rotation, value or position changed.

        :param reference: Reference of the part, for example "R1".
        :type reference: str
        :returns: None
        """
        component_item = self.component_items_by_reference.get(reference)

        if component_item is None:
            return

        component_item.refresh_from_component()
        component_item.setPos(
            grid_point_to_scene_position(
                component_item.component.row_number,
                component_item.component.column_number
            )
        )
        # A turn or a longer value can change the best spot for the
        # neighbours' labels too, so lay out every label again.
        self.layout_component_labels()
        # A moved ground pin can change which net is node 0.
        self.update_wire_nets()
        # A moved or turned pin can start or stop meeting a wire.
        self.rebuild_junction_items()
        self.update_scene_extent()
        self.update_pending_item(report=False)

    def set_wire_collection(self, wire_collection):
        """
        Show the wires of a wire collection on the grid.

        :param wire_collection: Wires to display, or None for none.
        :type wire_collection: core.wires.WireCollection
        :returns: None
        """
        self.wire_collection = wire_collection
        self.rebuild_wire_items()

    def rebuild_wire_items(self):
        """
        Replace every wire item with fresh ones from the collection.

        :returns: None
        """
        for wire_item in self.wire_items_by_reference.values():
            if not sip.isdeleted(wire_item) and wire_item.scene() is self:
                self.removeItem(wire_item)

        self.wire_items_by_reference = {}

        if self.wire_collection is not None:
            for wire in self.wire_collection.get_wires():
                wire_item = WireItem(
                    wire,
                    grid_point_to_scene_position(*wire.start_point),
                    grid_point_to_scene_position(*wire.end_point)
                )
                self.addItem(wire_item)
                self.wire_items_by_reference[wire.reference] = wire_item

        self.update_wire_nets()
        self.rebuild_junction_items()

    def rebuild_junction_items(self):
        """
        Draw a junction dot wherever three or more connections meet.

        Wires connect every point they cover (breadboard strips), so a dot
        shows where a wire passes a part pin or meets another wire
        mid-span. The dots ignore the mouse: a click reaches the grid
        point underneath.

        :returns: None
        """
        for junction_item in self.junction_items_by_identifier.values():
            if (not sip.isdeleted(junction_item) and
                    junction_item.scene() is self):
                self.removeItem(junction_item)

        self.junction_items_by_identifier = {}

        if self.wire_collection is None:
            return

        pin_identifiers = []

        if self.component_collection is not None:
            for component in self.component_collection.get_components():
                pin_identifiers.extend(component.get_pin_identifiers())

        # Junctions are always on a wire, so the wires give their points.
        point_by_identifier = {}

        for wire in self.wire_collection.get_wires():
            point_by_identifier.update(
                zip(wire.get_point_identifiers(), wire.get_points())
            )

        for identifier in find_junction_identifiers(
                self.wire_collection, pin_identifiers):
            center = grid_point_to_scene_position(
                *point_by_identifier[identifier]
            )
            radius = JUNCTION_DIAMETER / 2
            junction_item = QGraphicsEllipseItem(
                center.x() - radius, center.y() - radius,
                JUNCTION_DIAMETER, JUNCTION_DIAMETER
            )
            junction_item.setBrush(QColor(WIRE_COLOR))
            junction_item.setPen(QPen(Qt.NoPen))
            junction_item.setZValue(JUNCTION_Z_VALUE)
            junction_item.setAcceptedMouseButtons(Qt.NoButton)
            self.addItem(junction_item)
            self.junction_items_by_identifier[identifier] = junction_item

    def update_wire_nets(self):
        """
        Give every part item the current nets for its tooltip.

        The nets know every pin ("R1.2"), so parts sharing a point show as
        connected even without a wire.

        Without a wire collection the items get None and their tooltips
        have no net lines.

        :returns: None
        """
        wire_nets = None

        if self.wire_collection is not None:
            ground_identifiers = []
            pin_labels = []

            if self.component_collection is not None:
                for component in self.component_collection.get_components():
                    pin_identifiers = component.get_pin_identifiers()

                    if component.kind == "ground":
                        ground_identifiers.extend(pin_identifiers)

                    for (pin_name, unused_dx, unused_dy), identifier in zip(
                            component.get_pin_offsets(), pin_identifiers):
                        pin_labels.append(
                            (identifier, f"{component.reference}.{pin_name}")
                        )

            net_labels = []

            if self.connection_grid is not None:
                net_labels = list(
                    self.connection_grid.get_net_labels().items()
                )

            wire_nets = WireNets(
                self.wire_collection,
                ground_identifiers,
                pin_labels,
                net_labels
            )

        for component_item in self.component_items_by_reference.values():
            component_item.set_wire_nets(wire_nets)

    def set_wire_mode(self, is_wire_mode):
        """
        Switch Wire mode on or off; switching off cancels a wire in progress.

        :param is_wire_mode: True to draw wires on press-drag.
        :type is_wire_mode: bool
        :returns: None
        """
        self.is_wire_mode = bool(is_wire_mode)

        if not self.is_wire_mode:
            self.cancel_wire_drawing()
        elif self.pending_placement is not None:
            # A click in Wire mode starts a wire, not a ghost move.
            self.cancel_pending_placement()

    def set_probe_collection(self, probe_collection):
        """
        Show the probes of a collection on the grid.

        :param probe_collection: Probes to display, or None for none.
        :type probe_collection: core.probes.ProbeCollection
        :returns: None
        """
        self.probe_collection = probe_collection
        self.pending_differential_reference = None
        self.rebuild_probe_items()

    def set_probe_mode(self, is_probe_mode):
        """
        Switch Probe mode on or off.

        Switching on cancels a part that is waiting to be placed. Switching
        off forgets a differential probe that is still waiting for its
        second point.

        :param is_probe_mode: True to place probes by clicking.
        :type is_probe_mode: bool
        :returns: None
        """
        self.is_probe_mode = bool(is_probe_mode)

        if self.is_probe_mode:
            if self.pending_placement is not None:
                self.cancel_pending_placement()
        else:
            self.pending_differential_reference = None

    def rebuild_probe_items(self):
        """
        Replace every probe flag with fresh ones from the collection.

        :returns: None
        """
        for probe_item in self.probe_items:
            if not sip.isdeleted(probe_item) and probe_item.scene() is self:
                self.removeItem(probe_item)

        self.probe_items = []

        if self.probe_collection is None or self.connection_grid is None:
            return

        slots = {}

        for probe in self.probe_collection.get_probes():
            if probe.method == "current":
                anchor = self._current_probe_anchor(probe)

                if anchor is None:
                    continue

                self._add_probe_item(probe, "primary", anchor, slots)
                continue

            if probe.identifier:
                self._add_probe_item(
                    probe, "primary", self._identifier_point(probe.identifier),
                    slots
                )

            if probe.second_identifier:
                self._add_probe_item(
                    probe, "second",
                    self._identifier_point(probe.second_identifier),
                    slots
                )

    def finish_probe_drag(self, probe_item, scene_position):
        """
        Snap a dragged flag to the point or part under the cursor.

        A miss puts the flag back where it was.

        :param probe_item: Flag that was dragged.
        :type probe_item: gui.probe_item.ProbeItem
        :param scene_position: Cursor position when the button was released.
        :type scene_position: QPointF
        :returns: None
        """
        probe = probe_item.probe

        try:
            if probe.method == "current" and probe_item.role == "primary":
                component = self._component_for_probe_drop(scene_position)

                if component is None:
                    raise ComponentError("Drop the current probe on a part.")

                self.probe_collection.move_current(probe.reference, component)
            else:
                identifier = self.find_grid_point_near(scene_position)

                if identifier is None:
                    raise ComponentError("Drop the probe on a grid point.")

                which = "second" if probe_item.role == "second" else "primary"
                self.probe_collection.move_point(
                    probe.reference,
                    identifier,
                    self.connection_grid,
                    which
                )
        except ComponentError as error:
            self.rebuild_probe_items()
            self.probe_refused.emit(str(error))
            return

        self.rebuild_probe_items()
        self.select_probe(probe.reference)
        self.probe_moved.emit(probe.reference)

    def select_probe(self, reference):
        """
        Select the flags of one probe.

        :param reference: Probe reference, such as ``P1``.
        :type reference: str
        :returns: None
        """
        self.clearSelection()

        for probe_item in self.probe_items:
            if probe_item.probe.reference == reference:
                probe_item.setSelected(True)

    def _add_probe_item(self, probe, role, point, slots):
        """
        Add one flag at a grid point.

        :param point: ``(row, column)`` or None when the point is gone.
        :returns: None
        """
        if point is None:
            return

        slot = slots.get(point, 0)
        slots[point] = slot + 1
        probe_item = ProbeItem(probe, role, slot)

        if role == "primary":
            probe_item.set_readout(
                self.probe_readouts.get(probe.reference, ())
            )

        probe_item.setPos(grid_point_to_scene_position(*point))
        self.addItem(probe_item)
        self.probe_items.append(probe_item)

    def set_probe_readouts(self, lines_by_reference):
        """
        Show a parameter box on each probe that has meter lines.

        A probe with no lines (not ready, or drawn on a plot) keeps its
        flag and hides the box.

        :param lines_by_reference: Probe reference to ``(label, value)``
            pairs.
        :returns: None
        """
        self.probe_readouts = {
            reference: tuple(tuple(line) for line in lines)
            for reference, lines in lines_by_reference.items()
        }

        for probe_item in self.probe_items:
            if probe_item.role != "primary":
                continue

            probe_item.set_readout(
                self.probe_readouts.get(probe_item.probe.reference, ())
            )

    def _identifier_point(self, identifier):
        """
        Return ``(row, column)`` for a point that is still on the grid.

        :rtype: tuple or None
        """
        try:
            connection_point = self.connection_grid.get_connection_point(
                identifier
            )
        except GridConfigurationError:
            return None

        return (connection_point.row_number, connection_point.column_number)

    def _current_probe_anchor(self, probe):
        """
        Return the anchor ``(row, column)`` of a current probe's part.

        :rtype: tuple or None
        """
        if self.component_collection is None or not probe.component_reference:
            return None

        try:
            component = self.component_collection.get_component(
                probe.component_reference
            )
        except ComponentError:
            return None

        return (component.row_number, component.column_number)

    def _component_at(self, scene_position):
        """
        Return the part drawn under a scene position, or None.

        :rtype: core.components.Component or None
        """
        for item in self.items(scene_position):
            if isinstance(item, ComponentItem):
                return item.component

        return None

    def _component_for_probe_drop(self, scene_position):
        """
        Return the part a current probe was dropped on.

        A drop on a grid point that holds exactly one part uses that part.

        :rtype: core.components.Component or None
        """
        component = self._component_at(scene_position)

        if component is not None:
            return component

        identifier = self.find_grid_point_near(scene_position)

        if identifier is None or self.component_collection is None:
            return None

        matches = [
            part for part in self.component_collection.get_components()
            if identifier in part.get_pin_identifiers()
        ]

        if len(matches) == 1:
            return matches[0]

        return None

    def _probe_item_at(self, scene_position):
        """
        Return the probe flag under a scene position, or None.

        :rtype: gui.probe_item.ProbeItem or None
        """
        for item in self.items(scene_position):
            if isinstance(item, ProbeItem):
                return item

        return None

    def _place_probe_at(self, scene_position):
        """
        Place or extend a probe from a click in Probe mode.

        :returns: None
        """
        if self.probe_collection is None:
            return

        if self.pending_differential_reference:
            identifier = self.find_grid_point_near(scene_position)

            if identifier is None:
                self.probe_refused.emit(
                    "Click a grid point for the other end of the "
                    "differential probe."
                )
                return

            try:
                self.probe_collection.set_second_point(
                    self.pending_differential_reference,
                    identifier,
                    self.connection_grid
                )
            except ComponentError as error:
                self.probe_refused.emit(str(error))
                return

            reference = self.pending_differential_reference
            self.pending_differential_reference = None
            self.rebuild_probe_items()
            self.select_probe(reference)
            self.probe_moved.emit(reference)
            return

        component = self._component_at(scene_position)
        identifier = self.find_grid_point_near(scene_position)

        # A click on a part that is not also a bare grid point places a
        # current probe. A click on a grid point places a Direct probe.
        # The part wins when the cursor is on the body rather than a pin
        # dot; a pin dot is a grid point and stays a voltage probe.
        if component is not None and identifier is None:
            existing = self.probe_collection.current_probe_for(
                component.reference
            )

            if existing is not None:
                self.select_probe(existing.reference)
                return

            try:
                probe = self.probe_collection.add_current(component)
            except ComponentError as error:
                self.probe_refused.emit(str(error))
                return

            self.rebuild_probe_items()
            self.select_probe(probe.reference)
            self.probe_added.emit(probe.reference)
            return

        if identifier is None:
            return

        existing = self.probe_collection.voltage_probe_at(identifier)

        if existing is not None:
            self.select_probe(existing.reference)
            return

        try:
            probe = self.probe_collection.add_voltage(
                identifier, self.connection_grid
            )
        except ComponentError as error:
            self.probe_refused.emit(str(error))
            return

        self.rebuild_probe_items()
        self.select_probe(probe.reference)
        self.probe_added.emit(probe.reference)

    def find_grid_point_near(self, scene_position):
        """
        Return the identifier of the grid point within WIRE_SNAP_DISTANCE.

        :param scene_position: Position in scene coordinates.
        :type scene_position: QPointF
        :returns: Identifier such as "NODE_R02_C03", or None when no grid
            point of the current grid is that close.
        :rtype: str or None
        """
        row_number, column_number = scene_position_to_grid_point(
            scene_position
        )

        if not (1 <= row_number <= self.connection_grid.row_count and
                1 <= column_number <= self.connection_grid.column_count):
            return None

        center = grid_point_to_scene_position(row_number, column_number)

        if QLineF(center, scene_position).length() > WIRE_SNAP_DISTANCE:
            return None

        return self.connection_grid.build_connection_point_identifier(
            row_number,
            column_number
        )

    def get_connection_point_position(self, identifier):
        """
        Return the scene position of a grid point by identifier.

        :rtype: QPointF
        """
        connection_point = self.connection_grid.get_connection_point(
            identifier
        )

        return grid_point_to_scene_position(
            connection_point.row_number,
            connection_point.column_number
        )

    def start_wire_drawing(self, identifier):
        """
        Begin a wire at a grid point and show the rubber-band line.

        :param identifier: Start grid point.
        :type identifier: str
        :returns: None
        """
        self.cancel_wire_drawing()
        start_position = self.get_connection_point_position(identifier)

        self.wire_start_identifier = identifier
        self.wire_preview_item = QGraphicsLineItem(
            QLineF(start_position, start_position)
        )
        self.wire_preview_item.setPen(build_preview_pen())
        self.wire_preview_item.setZValue(WIRE_PREVIEW_Z_VALUE)
        # The preview never takes clicks.
        self.wire_preview_item.setAcceptedMouseButtons(Qt.NoButton)
        self.addItem(self.wire_preview_item)

    def update_wire_drawing(self, scene_position):
        """
        Stretch the rubber-band line to the mouse.

        :param scene_position: Mouse position in scene coordinates.
        :type scene_position: QPointF
        :returns: None
        """
        if self.wire_preview_item is None:
            return

        line = self.wire_preview_item.line()
        self.wire_preview_item.setLine(QLineF(line.p1(), scene_position))

    def cancel_wire_drawing(self):
        """
        Stop drawing and remove the rubber-band line, if any.

        :returns: None
        """
        if (self.wire_preview_item is not None and
                not sip.isdeleted(self.wire_preview_item) and
                self.wire_preview_item.scene() is self):
            self.removeItem(self.wire_preview_item)

        self.wire_preview_item = None
        self.wire_start_identifier = None

    def finish_wire_drawing(self, scene_position):
        """
        Add a wire from the start point to the grid point under the mouse.

        Releasing on the start point (a click) cancels quietly. Releasing
        away from any grid point, or a wire the collection refuses, emits
        wire_refused with the reason.

        :param scene_position: Release position in scene coordinates.
        :type scene_position: QPointF
        :returns: None
        """
        start_identifier = self.wire_start_identifier
        self.cancel_wire_drawing()

        if start_identifier is None or self.wire_collection is None:
            return

        end_identifier = self.find_grid_point_near(scene_position)

        if end_identifier == start_identifier:
            return

        if end_identifier is None:
            self.wire_refused.emit(
                f"release on a grid point to finish the wire from "
                f"{start_identifier}."
            )
            return

        self.add_drawn_wire(start_identifier, end_identifier)

    def add_drawn_wire(self, start_identifier, end_identifier):
        """
        Store a wire the user just drew.

        When it crosses another wire, crossing_chooser decides whether
        those points connect, hop, or the wire is dropped.

        :param start_identifier: Grid point where the drag started.
        :type start_identifier: str
        :param end_identifier: Grid point where the drag ended.
        :type end_identifier: str
        :returns: None
        """
        try:
            crossings = self.wire_collection.find_crossings(
                start_identifier,
                end_identifier,
                self.connection_grid
            )
        except ComponentError as error:
            self.wire_refused.emit(str(error))
            return

        bridged_identifiers = ()

        if crossings and self.crossing_chooser is not None:
            choice = self.crossing_chooser(
                start_identifier, end_identifier, crossings
            )

            if choice == "bridge":
                bridged_identifiers = tuple(
                    identifier for identifier, _references in crossings
                )
            elif choice != "connect":
                return

        try:
            wire = self.wire_collection.add_wire(
                start_identifier,
                end_identifier,
                self.connection_grid,
                bridged_identifiers
            )
        except ComponentError as error:
            self.wire_refused.emit(str(error))
            return

        self.rebuild_wire_items()
        self.wire_added.emit(wire.reference)

    def mousePressEvent(self, event):
        """
        In Wire mode, a left press on a grid point starts a wire.

        While a part waits to be placed, a right press places it. Every
        other press goes to the items as usual: select, rubber-band select
        or drag a part (a left click on a grid point also moves the
        waiting part there, see handle_connection_point_selection_change).

        :param event: Scene mouse event.
        :type event: QGraphicsSceneMouseEvent
        :returns: None
        """
        if (self.pending_placement is not None and
                event.button() == Qt.RightButton):
            # Mid-drag, a right press neither places the ghost nor
            # disturbs the drag (placing would rebuild the dragged item).
            if not self.is_part_drag_in_progress():
                self.commit_pending_placement()

            event.accept()
            return

        if (self.is_probe_mode and event.button() == Qt.LeftButton and
                self._probe_item_at(event.scenePos()) is None):
            self._place_probe_at(event.scenePos())
            event.accept()
            return

        if self.is_wire_mode and event.button() == Qt.LeftButton:
            identifier = self.find_grid_point_near(event.scenePos())

            if identifier is not None:
                self.start_wire_drawing(identifier)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Stretch the rubber-band line while a wire is being drawn.
        """
        if self.wire_start_identifier is not None:
            self.update_wire_drawing(event.scenePos())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """
        Finish a wire on left release.

        A right release while a part is held is swallowed: the held part
        would take any release as its drop (the right press went to a
        waiting ghost, or nowhere).
        """
        if (event.button() == Qt.RightButton and
                self.is_part_drag_in_progress()):
            event.accept()
            return

        if (self.wire_start_identifier is not None and
                event.button() == Qt.LeftButton):
            self.finish_wire_drawing(event.scenePos())
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def check_component_drop(self, reference, anchor_position):
        """
        Say whether dropping a dragged part here would be refused.

        :param reference: Part being dragged.
        :type reference: str
        :param anchor_position: Current anchor position, scene coordinates.
        :type anchor_position: QPointF
        :returns: None if the drop would be accepted (or puts the part
            back on its own point), otherwise the reason.
        :rtype: str or None
        """
        if self.component_collection is None:
            return None

        row_number, column_number = scene_position_to_grid_point(
            anchor_position
        )
        component = self.component_collection.get_component(reference)

        if (row_number, column_number) == (
                component.row_number, component.column_number):
            return None

        return self.component_collection.check_move(
            reference, row_number, column_number, self.connection_grid
        )

    def get_pending_key_action(self, event):
        """
        Return what a key does to the waiting part, or None.

        :param event: Key event (KeyPress or ShortcutOverride).
        :type event: QKeyEvent
        :returns: A direction ("right", ...), "commit", "cancel", or None
            when no part is waiting or the key is not one of its keys.
        :rtype: str or None
        """
        if self.pending_placement is None:
            return None

        # Shift+W, Ctrl+S and the like keep their usual meaning.
        if event.modifiers() & ~Qt.KeypadModifier:
            return None

        key = event.key()

        if key in PENDING_DIRECTION_BY_KEY:
            return PENDING_DIRECTION_BY_KEY[key]

        if key in PENDING_COMMIT_KEYS:
            return "commit"

        if key == Qt.Key_Escape:
            return "cancel"

        return None

    def event(self, event):
        """
        Keep W (Wire Mode) and the other placing keys for a waiting part.

        QGraphicsView passes ShortcutOverride on to the scene. Accepting it
        makes Qt deliver the key as a key press instead of firing the
        window shortcut with the same key.

        :param event: Any scene event.
        :type event: QEvent
        :returns: Whether the event was handled.
        :rtype: bool
        """
        if (event.type() == event.ShortcutOverride and
                self.get_pending_key_action(event) is not None):
            event.accept()
            return True

        return super().event(event)

    def keyPressEvent(self, event):
        """
        Esc cancels a part drag or a wire being drawn.

        While a part waits to be placed, the arrow keys and W/A/S/D turn
        it, Enter or Return places it and Esc cancels it.

        Other keys go to the items as usual.

        :param event: Key event.
        :type event: QKeyEvent
        :returns: None
        """
        if event.key() == Qt.Key_Escape:
            grabber = self.mouseGrabberItem()

            if isinstance(grabber, ComponentItem) and grabber.is_dragging:
                grabber.cancel_drag()
                event.accept()
                return

            if self.wire_start_identifier is not None:
                self.cancel_wire_drawing()
                event.accept()
                return

            if self.pending_differential_reference is not None:
                self.pending_differential_reference = None
                self.differential_cancelled.emit()
                event.accept()
                return

        action = self.get_pending_key_action(event)

        if action is not None:
            event.accept()

            if action == "commit":
                # Enter waits until a part drag ends, like a right press.
                if not self.is_part_drag_in_progress():
                    self.commit_pending_placement()
            elif action == "cancel":
                self.cancel_pending_placement()
            else:
                self.pending_placement.set_direction(action)
                self.update_pending_item()

            return

        super().keyPressEvent(event)

    def is_part_drag_in_progress(self):
        """
        Return True while the left button holds a part (pressed or dragged).

        :rtype: bool
        """
        grabber = self.mouseGrabberItem()

        return isinstance(grabber, ComponentItem) and (
            grabber.is_dragging or grabber.drag_start_position is not None
        )

    def get_pending_status(self):
        """
        Return the current "Placing ..." status text, or None.

        Used by the main window to keep the text in the status bar after
        an edit (delete, move, rotate) while a part waits.

        :rtype: str or None
        """
        if self.pending_placement is None:
            return None

        return self.describe_pending_placement(self.pending_placement.check())

    def start_pending_placement(self, kind, value_text, parameter_texts,
                                identifier):
        """
        Show a new part as a ghost at a grid point, waiting to be placed.

        A part already waiting is replaced; when it is the same kind, the
        new one keeps its direction.

        :param kind: Component kind.
        :type kind: str
        :param value_text: Value as typed; empty means the default.
        :type value_text: str
        :param parameter_texts: Extra settings by name, or None.
        :type parameter_texts: dict or None
        :param identifier: Anchor grid point, for example "NODE_R07_C04".
        :type identifier: str
        :returns: None
        :raises ComponentError: If the value or a setting is invalid, or
            the point is not on the grid. A waiting part is then kept.
        """
        connection_point = self.connection_grid.get_connection_point(
            identifier
        )
        direction = None

        if (self.pending_placement is not None and
                self.pending_placement.kind == kind):
            direction = self.pending_placement.direction

        pending_placement = PendingPlacement(
            self.component_collection,
            self.connection_grid,
            kind,
            value_text,
            connection_point.row_number,
            connection_point.column_number,
            parameter_texts,
            direction
        )
        self.clear_pending_placement()
        self.pending_placement = pending_placement
        self.update_pending_item()

    def update_pending_item(self, report=True):
        """
        Redraw the ghost for the waiting part's point and direction.

        :param report: True to emit pending_placement_changed with the
            new status text.
        :type report: bool
        :returns: None
        """
        self.remove_pending_item()

        if self.pending_placement is None:
            return

        reason = self.pending_placement.check()
        self.pending_item = ComponentItem(
            self.pending_placement.build_component(), GRID_POINT_SPACING
        )
        self.pending_item.setPos(
            grid_point_to_scene_position(
                self.pending_placement.row_number,
                self.pending_placement.column_number
            )
        )
        self.addItem(self.pending_item)
        self.pending_item.make_pending(reason is None)

        if report:
            self.pending_placement_changed.emit(
                self.describe_pending_placement(reason)
            )

    def describe_pending_placement(self, reason):
        """
        Return the status text for the waiting part.

        :param reason: Why it would be refused here, or None.
        :type reason: str or None
        :rtype: str
        """
        pending_placement = self.pending_placement
        component = pending_placement.build_component()
        display_name = COMPONENT_DEFINITIONS[component.kind]["display_name"]
        text = (
            f"Placing {component.reference} ({display_name}) at "
            f"{pending_placement.identifier}, pointing "
            f"{pending_placement.direction.title()}: "
        )

        if reason is None:
            text += "Enter or right-click places it."
        else:
            text += (
                "it can't go here. "
                f"{pending_placement.describe_free_directions()}"
            )

        return text + " Arrows or W/A/S/D turn it; Esc cancels."

    def commit_pending_placement(self):
        """
        Place the waiting part, or report why not and keep it waiting.

        :returns: The new part, or None if it was refused.
        :rtype: core.components.Component or None
        """
        if self.pending_placement is None:
            return None

        try:
            component = self.pending_placement.commit()
        except ComponentError as error:
            self.update_pending_item()
            self.pending_placement_refused.emit(str(error))
            return None

        self.clear_pending_placement()
        self.pending_placement_committed.emit(component.reference)

        return component

    def cancel_pending_placement(self):
        """
        Drop the waiting part (Esc) and say so.

        :returns: None
        """
        if self.pending_placement is None:
            return

        self.clear_pending_placement()
        self.pending_placement_cancelled.emit()

    def clear_pending_placement(self):
        """
        Drop the waiting part without a signal.

        :returns: None
        """
        self.pending_placement = None
        self.remove_pending_item()

    def remove_pending_item(self):
        """
        Take the ghost item out of the scene.

        :returns: None
        """
        pending_item = self.pending_item
        self.pending_item = None

        # Qt may already have deleted it (for example by clear()).
        if (pending_item is not None and
                not sip.isdeleted(pending_item) and
                pending_item.scene() is self):
            self.removeItem(pending_item)

    def handle_component_drop(self, reference, anchor_position):
        """
        Finish a part drag: snap to the nearest grid point, or put it back.

        The move goes through ComponentCollection.move_component, which
        refuses off-grid and overlapping moves. Dropping on the part's own
        grid point just puts it back, with no signal.

        :param reference: Part that was dragged.
        :type reference: str
        :param anchor_position: Where the part's anchor was dropped, in
            scene coordinates.
        :type anchor_position: QPointF
        :returns: None
        """
        if self.component_collection is None:
            return

        row_number, column_number = scene_position_to_grid_point(
            anchor_position
        )
        component = self.component_collection.get_component(reference)

        if (row_number, column_number) == (
                component.row_number, component.column_number):
            self.refresh_component(reference)
            return

        try:
            self.component_collection.move_component(
                reference,
                row_number,
                column_number,
                self.connection_grid
            )
        except ComponentError as error:
            # refresh_component puts the item back at the model position.
            self.refresh_component(reference)
            self.component_move_refused.emit(reference, str(error))
            return

        self.refresh_component(reference)
        self.component_moved.emit(reference)

    def layout_component_labels(self):
        """
        Place every part's label where it is easiest to read.

        One-step parts sit side by side, so a label wider than a grid step
        would run into its neighbour's label or symbol. Each label (in
        reference order) takes the lowest-scoring candidate from
        ComponentItem.get_label_candidates(), compared worst problem first:

        1. the text crosses a part's symbol or body (unreadable, because
           parts draw above labels);
        2. the text, with its patch, overlaps a label placed before it;
        3. the text touches a grid dot (a few letters under a dot);
        4. how far it was moved from the side's normal spot;
        5. side order: above, right, below, left.

        With no neighbours this gives the single-part rule of
        ComponentItem.refresh_label().

        :returns: None
        """
        component_items = [
            component_item
            for component_item in self.component_items_by_reference.values()
            if component_item.scene() is self
        ]
        obstacles = [
            component_item.obstacle_path.translated(component_item.pos())
            for component_item in component_items
        ]
        obstacle_rects = [path.boundingRect() for path in obstacles]
        placed_label_rects = []

        for component_item in component_items:
            if not component_item.label_item.isVisible():
                continue

            text_size = component_item.label_item.text_rect().size()
            best_score = None
            best_placement = None

            for side, nudge, top_left in (
                    component_item.get_label_candidates()):
                item_rect = QRectF(top_left, text_size)
                scene_rect = item_rect.translated(component_item.pos())
                patch_rect = scene_rect.adjusted(
                    -LABEL_PATCH_PADDING, -LABEL_PATCH_PADDING,
                    LABEL_PATCH_PADDING, LABEL_PATCH_PADDING
                )

                crosses_a_part = any(
                    obstacle_rect.intersects(scene_rect) and
                    obstacle.intersects(scene_rect)
                    for obstacle, obstacle_rect in zip(
                        obstacles, obstacle_rects
                    )
                )
                overlaps_a_label = any(
                    patch_rect.intersects(placed_rect)
                    for placed_rect in placed_label_rects
                )
                touches_a_dot = text_touches_a_grid_dot(
                    item_rect, component_item.grid_spacing
                )
                score = (
                    crosses_a_part,
                    overlaps_a_label,
                    touches_a_dot,
                    abs(nudge),
                    LABEL_SIDES.index(side),
                )

                if best_score is None or score < best_score:
                    best_score = score
                    best_placement = (side, top_left, patch_rect)

            side, top_left, patch_rect = best_placement
            component_item.apply_label_placement(side, top_left)
            placed_label_rects.append(patch_rect)

    def get_grid_rect(self):
        """
        Return the scene area covered by the grid points.

        :returns: Rectangle around every grid point.
        :rtype: QRectF
        """
        radius = CONNECTION_POINT_DIAMETER / 2.0
        grid_width = (self.connection_grid.column_count - 1) * GRID_POINT_SPACING
        grid_height = (self.connection_grid.row_count - 1) * GRID_POINT_SPACING

        return QRectF(
            GRID_ORIGIN_X - radius,
            GRID_ORIGIN_Y - radius,
            grid_width + CONNECTION_POINT_DIAMETER,
            grid_height + CONNECTION_POINT_DIAMETER
        )

    def get_components_rect(self):
        """
        Return the scene area painted by the parts and their labels.

        :returns: United rectangle; empty when there are no parts.
        :rtype: QRectF
        """
        components_rect = QRectF()

        for component_item in self.component_items_by_reference.values():
            components_rect = components_rect.united(
                component_item.mapRectToScene(component_item.boundingRect())
            )

            label_item = component_item.label_item

            if label_item.isVisible():
                components_rect = components_rect.united(
                    label_item.mapRectToScene(label_item.boundingRect())
                )

        return components_rect

    def update_scene_extent(self):
        """
        Keep the headers clear of the parts and the scene big enough.

        Column headers move up and row headers move left when a part or
        label reaches past the grid edge, so they are never covered. Then
        the sceneRect grows to hold everything plus SCENE_MARGIN, so a view
        can scroll to labels outside the grid. It never shrinks below the
        default rectangle set in rebuild_connection_point_items().

        :returns: None
        """
        content_rect = self.get_grid_rect().united(self.get_components_rect())

        for column_header in self.column_header_items:
            header_height = column_header.boundingRect().height()
            column_header.setY(min(
                HEADER_POSITION,
                content_rect.top() - HEADER_GAP - header_height
            ))

        for row_header in self.row_header_items:
            header_width = row_header.boundingRect().width()
            row_header.setX(min(
                HEADER_POSITION,
                content_rect.left() - HEADER_GAP - header_width
            ))

        grid_width = (self.connection_grid.column_count - 1) * GRID_POINT_SPACING
        grid_height = (self.connection_grid.row_count - 1) * GRID_POINT_SPACING
        default_rect = QRectF(
            0,
            0,
            GRID_ORIGIN_X + grid_width + 100,
            GRID_ORIGIN_Y + grid_height + 100
        )

        scene_rect = default_rect.united(
            self.itemsBoundingRect().adjusted(
                -SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN
            )
        )
        self.setSceneRect(scene_rect)

    def refresh_connection_point(self, connection_point_identifier):
        """
        Redraw one point after a model-state change.

        :param connection_point_identifier: Point whose appearance changed.
        :type connection_point_identifier: str
        :returns: None
        """
        connection_point_item = self.connection_point_items_by_identifier.get(
            connection_point_identifier
        )

        if connection_point_item is not None:
            connection_point_item.refresh_from_point()
            self.update_scene_extent()

    def handle_connection_point_selection_change(self):
        """
        Report the selected connection point and selected part.

        Both signals fire on every selection change, with None when nothing
        of that type is selected.

        :returns: None
        """
        selected_connection_point = None
        selected_component = None
        selected_wire_references = [
            selected_item.wire.reference
            for selected_item in self.selectedItems()
            if isinstance(selected_item, WireItem)
        ]

        for selected_item in self.selectedItems():
            if isinstance(selected_item, ConnectionPointItem):
                selected_connection_point = (
                    selected_item.connection_point
                )
                break

        # Clicking another grid point moves a waiting part there.
        if (self.pending_placement is not None and
                selected_connection_point is not None):
            self.pending_placement.move_to(
                selected_connection_point.row_number,
                selected_connection_point.column_number
            )
            self.update_pending_item()

        for selected_item in self.selectedItems():
            if isinstance(selected_item, ComponentItem):
                selected_component = selected_item.component
                break

        selected_probe_references = []

        for selected_item in self.selectedItems():
            if isinstance(selected_item, ProbeItem):
                reference = selected_item.probe.reference

                if reference not in selected_probe_references:
                    selected_probe_references.append(reference)

        self.connection_point_selected.emit(selected_connection_point)
        self.component_selected.emit(selected_component)
        self.wires_selected.emit(selected_wire_references)
        self.probes_selected.emit(selected_probe_references)

    def drawBackground(self, painter, rectangle):
        """
        Draw the editor background and visible grid guide lines.

        :param painter: Painter used to draw the scene background.
        :type painter: QPainter
        :param rectangle: Updated portion of the scene.
        :type rectangle: QRectF
        :returns: None
        """
        painter.fillRect(rectangle, QColor("#1f2933"))

        painter.save()
        painter.setPen(QPen(QColor("#334e68"), 1))

        row_count = self.connection_grid.row_count
        column_count = self.connection_grid.column_count

        grid_width = (column_count - 1) * GRID_POINT_SPACING
        grid_height = (row_count - 1) * GRID_POINT_SPACING

        # Draw horizontal guides to show the future wire-routing geometry.
        for row_number in range(row_count):
            y_position = GRID_ORIGIN_Y + (row_number * GRID_POINT_SPACING)

            painter.drawLine(
                GRID_ORIGIN_X,
                y_position,
                GRID_ORIGIN_X + grid_width,
                y_position
            )

        # Draw vertical guides to complete the visual connection-point grid.
        for column_number in range(column_count):
            x_position = (
                GRID_ORIGIN_X +
                (column_number * GRID_POINT_SPACING)
            )

            painter.drawLine(
                x_position,
                GRID_ORIGIN_Y,
                x_position,
                GRID_ORIGIN_Y + grid_height
            )

        painter.restore()


class ConnectionGridView(QGraphicsView):
    """
    Interactive view for the connection-grid scene.

    The mouse wheel zooms around the point under the cursor, with or without
    Ctrl; Shift+wheel keeps Qt's normal scrolling. Zoom In, Zoom Out and
    Zoom to Fit work around the middle of the view. Every zoom is kept
    between MINIMUM_ZOOM and MAXIMUM_ZOOM (1.0 shows a grid step as 60
    pixels). Drag the board with the left button to move it, or use the
    middle button; the cursor turns into a closed hand while it is held.
    A click still selects. Shift+left-drag rubber-band selects. Scrollbars
    stay available as well.

    :param connection_grid_scene: Scene shown by the view.
    :type connection_grid_scene: ConnectionGridScene
    :param parent: Optional Qt parent object.
    :type parent: QWidget or None
    """

    zoom_changed = pyqtSignal(float)

    def __init__(self, connection_grid_scene, parent=None):
        super(ConnectionGridView, self).__init__(
            connection_grid_scene,
            parent
        )

        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(self.RubberBandDrag)
        # Zooms place the anchor point themselves (see zoom_by).
        self.setTransformationAnchor(self.NoAnchor)
        self.setResizeAnchor(self.AnchorViewCenter)
        self.pan_start_position = None
        self.pan_button = None
        self.cursor_before_pan = None
        # A left press that may become a pan. A short release is replayed
        # as a click; a longer move pans and the press is never delivered.
        self.held_left_press = None
        connection_grid_scene.sceneRectChanged.connect(
            self.update_scroll_area
        )
        self.update_scroll_area()

    def update_scroll_area(self, *_unused):
        """
        Let the view scroll one full viewport past every edge of the scene.

        Without this margin Qt centres a scene smaller than the view and
        a zoom could not keep the point under the cursor still. Half a
        viewport was not enough: zooming out near the scene edge hit the
        scroll limit (QC #15). Called when
        the scene grows, the zoom changes or the view is resized.

        :returns: None
        """
        zoom = self.get_zoom()
        margin_x = self.viewport().width() / zoom
        margin_y = self.viewport().height() / zoom
        self.setSceneRect(
            self.scene().sceneRect().adjusted(
                -margin_x, -margin_y, margin_x, margin_y
            )
        )

    def resizeEvent(self, event):
        """
        Keep the scroll margin at one full new viewport size.

        :param event: Resize event.
        :type event: QResizeEvent
        :returns: None
        """
        super().resizeEvent(event)
        self.update_scroll_area()

    def get_zoom(self):
        """
        Return the current zoom factor (1.0 = 60 pixels per grid step).

        :returns: Zoom factor.
        :rtype: float
        """
        return self.transform().m11()

    @staticmethod
    def clamp_zoom(zoom):
        """
        Keep a zoom factor between MINIMUM_ZOOM and MAXIMUM_ZOOM.

        :param zoom: Wanted zoom factor.
        :type zoom: float
        :returns: The nearest allowed zoom factor.
        :rtype: float
        """
        return min(MAXIMUM_ZOOM, max(MINIMUM_ZOOM, zoom))

    def can_zoom_in(self):
        """
        :returns: True when the view is below MAXIMUM_ZOOM.
        :rtype: bool
        """
        return self.get_zoom() < MAXIMUM_ZOOM - ZOOM_TOLERANCE

    def can_zoom_out(self):
        """
        :returns: True when the view is above MINIMUM_ZOOM.
        :rtype: bool
        """
        return self.get_zoom() > MINIMUM_ZOOM + ZOOM_TOLERANCE

    def zoom_by(self, factor, viewport_position=None):
        """
        Multiply the zoom by a factor, keeping one point of the view still.

        The scene point under viewport_position (the middle of the view
        when None) stays under that position, as far as the scrollbars
        allow. The result is clamped; nothing happens when the clamped zoom
        equals the current one.

        :param factor: Zoom multiplier, above 1 to zoom in.
        :type factor: float
        :param viewport_position: Anchor point in viewport coordinates.
        :type viewport_position: QPoint or QPointF or None
        :returns: True when the zoom changed.
        :rtype: bool
        """
        current_zoom = self.get_zoom()
        new_zoom = self.clamp_zoom(current_zoom * factor)

        if abs(new_zoom - current_zoom) <= ZOOM_TOLERANCE:
            return False

        if viewport_position is None:
            viewport_position = QPointF(self.viewport().rect().center())

        viewport_position = QPointF(viewport_position)
        anchor_scene_position = self.mapToScene(viewport_position.toPoint())
        self.set_zoom(new_zoom)
        self.keep_scene_point_at(anchor_scene_position, viewport_position)
        return True

    def set_zoom(self, zoom):
        """
        Set the zoom factor directly (clamped) and report the change.

        :param zoom: Wanted zoom factor.
        :type zoom: float
        :returns: None
        """
        zoom = self.clamp_zoom(zoom)
        self.setTransform(QTransform.fromScale(zoom, zoom))
        self.update_scroll_area()
        self.zoom_changed.emit(zoom)

    def keep_scene_point_at(self, scene_position, viewport_position):
        """
        Scroll so a scene point appears at a viewport position.

        :param scene_position: Scene point to move.
        :type scene_position: QPointF
        :param viewport_position: Where it should appear in the viewport.
        :type viewport_position: QPointF
        :returns: None
        """
        offset = self.mapFromScene(scene_position) - viewport_position.toPoint()
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + offset.x()
        )
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + offset.y()
        )

    def zoom_in(self):
        """
        Zoom in one step around the middle of the view.

        :returns: True when the zoom changed.
        :rtype: bool
        """
        return self.zoom_by(ZOOM_STEP)

    def zoom_out(self):
        """
        Zoom out one step around the middle of the view.

        :returns: True when the zoom changed.
        :rtype: bool
        """
        return self.zoom_by(1.0 / ZOOM_STEP)

    def fit_grid_in_view(self):
        """
        Fit the complete connection grid into the visible editor area.

        The fitted zoom is clamped like any other zoom, so a 50 x 50 grid
        in a small window may still need scrolling.

        :returns: None
        """
        scene_rectangle = self.scene().itemsBoundingRect()

        if scene_rectangle.isNull():
            return

        scene_rectangle = scene_rectangle.adjusted(-25, -25, 25, 25)
        self.fitInView(scene_rectangle, Qt.KeepAspectRatio)
        fitted_zoom = self.get_zoom()
        self.set_zoom(fitted_zoom)
        self.centerOn(scene_rectangle.center())

    def wheelEvent(self, event):
        """
        Zoom around the cursor; Shift+wheel scrolls as usual.

        One notch (120 eighths of a degree) is one ZOOM_STEP; touchpads
        that send smaller deltas zoom by the matching fraction.

        :param event: Mouse-wheel event.
        :type event: QWheelEvent
        :returns: None
        """
        delta = event.angleDelta().y()

        if event.modifiers() & Qt.ShiftModifier or delta == 0:
            super(ConnectionGridView, self).wheelEvent(event)
            return

        self.zoom_by(ZOOM_STEP ** (delta / 120.0), event.posF())
        event.accept()

    def mousePressEvent(self, event):
        """
        Start a pan, or hold a left press until it is a drag or a click.

        The middle button pans at once. A left press on the board is held:
        moving past the drag distance pans, and releasing without that
        movement is delivered as a click (select a point, move a ghost).
        A left press in Wire mode, with Shift held, or on a placed part
        goes straight to the scene, so wires, rubber-band selection and
        part drags are unchanged.

        :param event: Mouse press event.
        :type event: QMouseEvent
        :returns: None
        """
        if event.button() == Qt.MiddleButton:
            self.begin_pan(event.pos(), Qt.MiddleButton)
            event.accept()
            return

        if (event.button() == Qt.LeftButton and
                not self.left_press_goes_to_the_scene(event)):
            self.held_left_press = {
                "pos": QPoint(event.pos()),
                "global": QPoint(event.globalPos()),
                "modifiers": event.modifiers(),
            }
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Pan while the board is grabbed.

        :param event: Mouse move event.
        :type event: QMouseEvent
        :returns: None
        """
        if self.pan_button is not None:
            self.scroll_pan(event.pos())
            event.accept()
            return

        if (self.held_left_press is not None and
                event.buttons() & Qt.LeftButton):
            moved = (
                event.pos() - self.held_left_press["pos"]
            ).manhattanLength()

            if moved >= QApplication.startDragDistance():
                origin = self.held_left_press["pos"]
                self.held_left_press = None
                self.begin_pan(origin, Qt.LeftButton)
                self.scroll_pan(event.pos())

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """
        End a pan, or deliver a held left press as a click.

        :param event: Mouse release event.
        :type event: QMouseEvent
        :returns: None
        """
        if event.button() == self.pan_button:
            self.end_pan()
            self.held_left_press = None
            event.accept()
            return

        if (event.button() == Qt.LeftButton and
                self.held_left_press is not None):
            self.replay_held_left_click(event)
            return

        super().mouseReleaseEvent(event)

    def left_press_goes_to_the_scene(self, event):
        """
        Return True when this left press must not be turned into a pan.

        :param event: Mouse press event.
        :type event: QMouseEvent
        :rtype: bool
        """
        scene = self.scene()

        if scene is not None and (
                getattr(scene, "is_wire_mode", False) or
                getattr(scene, "is_probe_mode", False)):
            return True

        if event.modifiers() & Qt.ShiftModifier:
            return True

        item = self.itemAt(event.pos())

        if isinstance(item, ProbeItem):
            return True

        return self.is_draggable_part(item)

    def is_draggable_part(self, item):
        """
        Return True when a left drag on this item should move the part.

        A ghost is not draggable: it takes no clicks, so a drag there pans
        the board and a click falls through to the grid point underneath.

        :param item: Topmost item under the cursor, or None.
        :type item: QGraphicsItem or None
        :rtype: bool
        """
        if not isinstance(item, ComponentItem):
            return False

        return (
            bool(item.flags() & item.ItemIsSelectable) and
            bool(item.acceptedMouseButtons() & Qt.LeftButton)
        )

    def begin_pan(self, viewport_pos, button):
        """
        Grab the board. The cursor is a closed hand until end_pan.

        :param viewport_pos: Viewport pixel the grab started at.
        :type viewport_pos: QPoint
        :param button: Mouse button that is dragging.
        :type button: Qt.MouseButton
        :returns: None
        """
        self.pan_button = button
        self.pan_start_position = QPoint(viewport_pos)

        if self.cursor_before_pan is None:
            self.cursor_before_pan = self.viewport().cursor()

        self.viewport().setCursor(Qt.ClosedHandCursor)
        self.viewport().grabMouse()

    def scroll_pan(self, viewport_pos):
        """
        Move the board so the grabbed point follows the cursor.

        :param viewport_pos: Current viewport pixel.
        :type viewport_pos: QPoint
        :returns: None
        """
        offset = viewport_pos - self.pan_start_position
        self.pan_start_position = QPoint(viewport_pos)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() - offset.x()
        )
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - offset.y()
        )

    def end_pan(self):
        """
        Let go of the board and restore the cursor.

        :returns: None
        """
        self.pan_button = None
        self.pan_start_position = None

        if self.cursor_before_pan is not None:
            self.viewport().setCursor(self.cursor_before_pan)
            self.cursor_before_pan = None

        self.viewport().releaseMouse()

    def replay_held_left_click(self, release_event):
        """
        Deliver a left press that never became a pan, then this release.

        :param release_event: The release that ended the press.
        :type release_event: QMouseEvent
        :returns: None
        """
        held = self.held_left_press
        self.held_left_press = None
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(held["pos"]),
            QPointF(held["pos"]),
            QPointF(held["global"]),
            Qt.LeftButton,
            Qt.LeftButton,
            held["modifiers"],
        )
        super().mousePressEvent(press)
        super().mouseReleaseEvent(release_event)
