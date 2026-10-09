"""
PyQt5 graphics-scene classes for the connection-grid editor.

This module draws and manages selectable connection points. It remains
separate from the core data model so future command-line or test workflows
can use the connection-grid model without importing PyQt5.
"""

from PyQt5.QtCore import QPointF
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtGui import QPainter
from PyQt5.QtGui import QPen
from PyQt5.QtWidgets import QGraphicsEllipseItem
from PyQt5.QtWidgets import QGraphicsScene
from PyQt5.QtWidgets import QGraphicsSimpleTextItem
from PyQt5.QtWidgets import QGraphicsView


GRID_POINT_SPACING = 60
GRID_ORIGIN_X = 90
GRID_ORIGIN_Y = 80
CONNECTION_POINT_DIAMETER = 16


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

        self.setToolTip(
            "{}\nRow: {}\nColumn: {}".format(
                connection_point.identifier,
                connection_point.row_number,
                connection_point.column_number
            )
        )

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

    def __init__(self, connection_grid, parent=None):
        super(ConnectionGridScene, self).__init__(parent)

        self.connection_grid = None
        self.connection_point_items_by_identifier = {}

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

        # Clear the selected-node display after a rebuild because old item
        # references are no longer valid once the scene has been cleared.
        self.connection_point_selected.emit(None)

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
            connection_point_item.update()

    def handle_connection_point_selection_change(self):
        """
        Report the currently selected connection point to the main window.

        :returns: None
        """
        selected_connection_point = None

        for selected_item in self.selectedItems():
            if isinstance(selected_item, ConnectionPointItem):
                selected_connection_point = (
                    selected_item.connection_point
                )
                break

        self.connection_point_selected.emit(selected_connection_point)

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

    Ctrl+mouse-wheel zoom is available for large grids. Standard scrollbars
    allow navigation without introducing platform-specific mouse handling.

    :param connection_grid_scene: Scene shown by the view.
    :type connection_grid_scene: ConnectionGridScene
    :param parent: Optional Qt parent object.
    :type parent: QWidget or None
    """

    def __init__(self, connection_grid_scene, parent=None):
        super(ConnectionGridView, self).__init__(
            connection_grid_scene,
            parent
        )

        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(self.RubberBandDrag)
        self.setTransformationAnchor(self.AnchorUnderMouse)

    def fit_grid_in_view(self):
        """
        Fit the complete connection grid into the visible editor area.

        :returns: None
        """
        scene_rectangle = self.scene().itemsBoundingRect()

        if not scene_rectangle.isNull():
            self.fitInView(
                scene_rectangle.adjusted(-25, -25, 25, 25),
                Qt.KeepAspectRatio
            )

    def wheelEvent(self, event):
        """
        Zoom when Ctrl is held; otherwise preserve normal scrolling.

        :param event: Mouse-wheel event.
        :type event: QWheelEvent
        :returns: None
        """
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.scale(1.15, 1.15)
            else:
                self.scale(1.0 / 1.15, 1.0 / 1.15)

            event.accept()
            return

        super(ConnectionGridView, self).wheelEvent(event)