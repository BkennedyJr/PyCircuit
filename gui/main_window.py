"""
Main PyQt5 application window for Circuit Workbench.

This module coordinates GUI actions with the platform-independent core
connection-grid model and project-file services.
"""

import re
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QRectF
from PyQt5.QtCore import QStandardPaths
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtGui import QPainter
from PyQt5.QtPrintSupport import QPrintDialog
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtWidgets import QAction
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QDialog
from PyQt5.QtWidgets import QDockWidget
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QFormLayout
from PyQt5.QtWidgets import QGroupBox
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QToolBar
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QWidget

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.exceptions import GridConfigurationError
from core.exceptions import ProjectFileError
from core.project_io import load_project_file
from core.project_io import save_project_file
from core.node_formula import build_node_formulas
from core.probes import PROBE_METHOD_LABELS
from core.probes import PROBE_METHODS
from core.probes import ProbeCollection
from core.probes import describe_reading
from core.probes import parameter_lines
from core.probes import shunt_loads
from core.wires import WireCollection
from core.wires import describe_crossings
from gui.component_panel_widget import ComponentPanelWidget
from gui.grid_configuration_widget import ApplyGridButton
from gui.grid_configuration_widget import GridConfigurationWidget
from gui.grid_editor import ConnectionGridScene
from gui.grid_editor import ConnectionGridView


PROJECT_FILE_FILTER = "Circuit Workbench Project (*.json);;All Files (*)"



def natural_sort_key(reference):
    """
    Natural sort key for references: "R2" before "R10", "C1" before "R1".

    :param reference: Reference such as "R10" or "W2".
    :type reference: str
    :rtype: list
    """
    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"([0-9]+)", reference)
    ]

class MainWindow(QMainWindow):
    """
    Main application window for configuring and selecting grid nodes.

    :param parent: Optional Qt parent object.
    :type parent: QWidget or None
    """

    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)

        self.connection_grid = ConnectionGrid(8, 8)
        self.current_project_file_path = None
        self.is_project_modified = False
        self.selected_connection_point_identifier = None
        self.component_collection = ComponentCollection()
        self.selected_component_reference = None
        self.wire_collection = WireCollection()
        self.selected_wire_references = []
        self.probe_collection = ProbeCollection()
        self.selected_probe_reference = None
        self._probe_parameter_lines = {}

        self.connection_grid_scene = ConnectionGridScene(
            self.connection_grid,
            self
        )
        self.connection_grid_scene.set_component_collection(
            self.component_collection
        )
        self.connection_grid_scene.set_wire_collection(self.wire_collection)
        self.connection_grid_scene.set_probe_collection(self.probe_collection)
        self.connection_grid_view = ConnectionGridView(
            self.connection_grid_scene,
            self
        )

        self.create_main_window()
        self.connect_application_signals()

        # Queue grid fitting until the window has a valid rendered size.
        QTimer.singleShot(
            0,
            self.connection_grid_view.fit_grid_in_view
        )

    def create_main_window(self):
        """
        Build menus, docks, central editor, and status display.

        :returns: None
        """
        self.setWindowTitle("Circuit Workbench - Untitled")
        self.resize(1300, 850)
        self.setCentralWidget(self.connection_grid_view)

        self.create_actions()
        self.create_menu_bar()
        self.create_tool_bar()
        self.create_grid_configuration_toolbar()
        self.create_component_dock()
        self.create_selected_node_dock()
        self.create_probe_dock()

        self.zoom_label = QLabel(self)
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.update_zoom_display(self.connection_grid_view.get_zoom())

        self.statusBar().showMessage(
            "Ready. Configure a grid or select a connection point."
        )

    def update_zoom_display(self, zoom):
        """
        Show the zoom in the status bar and grey out Zoom In/Out at a limit.

        :param zoom: Current zoom factor (1.0 = 100 %).
        :type zoom: float
        :returns: None
        """
        self.zoom_label.setText(f"Zoom {round(zoom * 100)}%")

        self.zoom_in_action.setEnabled(self.connection_grid_view.can_zoom_in())
        self.zoom_out_action.setEnabled(
            self.connection_grid_view.can_zoom_out()
        )

    def connect_application_signals(self):
        """
        Connect scene events to main-window display updates.

        :returns: None
        """
        self.connection_grid_scene.connection_point_selected.connect(
            self.handle_connection_point_selection
        )
        self.connection_grid_scene.component_selected.connect(
            self.handle_component_selection
        )
        self.connection_grid_scene.component_moved.connect(
            self.handle_component_moved
        )
        self.connection_grid_scene.component_move_refused.connect(
            self.handle_component_move_refused
        )
        self.connection_grid_scene.wire_added.connect(self.handle_wire_added)
        self.connection_grid_scene.pending_placement_changed.connect(
            self.handle_pending_placement_changed
        )
        self.connection_grid_scene.pending_placement_committed.connect(
            self.handle_pending_placement_committed
        )
        self.connection_grid_scene.pending_placement_refused.connect(
            self.handle_pending_placement_refused
        )
        self.connection_grid_scene.pending_placement_cancelled.connect(
            self.handle_pending_placement_cancelled
        )
        self.connection_grid_scene.wire_refused.connect(
            self.handle_wire_refused
        )
        # Look the method up on each crossing, so a test can replace
        # choose_wire_crossing without the scene keeping the old one.
        self.connection_grid_scene.crossing_chooser = (
            lambda start, end, crossings: self.choose_wire_crossing(
                start, end, crossings
            )
        )
        self.connection_grid_scene.wires_selected.connect(
            self.handle_wire_selection
        )
        self.connection_grid_scene.probe_added.connect(self.handle_probe_added)
        self.connection_grid_scene.probe_moved.connect(self.handle_probe_moved)
        self.connection_grid_scene.probe_refused.connect(
            self.handle_probe_refused
        )
        self.connection_grid_scene.probes_selected.connect(
            self.handle_probe_selection
        )
        self.connection_grid_scene.differential_cancelled.connect(
            self.handle_differential_cancelled
        )
        self.connection_grid_view.zoom_changed.connect(
            self.update_zoom_display
        )

    def create_actions(self):
        """
        Create menu and toolbar actions.

        :returns: None
        """
        self.new_project_action = QAction("New Grid Project", self)
        self.new_project_action.triggered.connect(self.create_new_project)

        self.open_project_action = QAction("Open Project...", self)
        self.open_project_action.triggered.connect(self.open_project)

        self.save_project_action = QAction("Save Project", self)
        self.save_project_action.triggered.connect(self.save_current_project)

        self.save_project_as_action = QAction("Save Project As...", self)
        self.save_project_as_action.triggered.connect(
            self.save_project_as
        )

        self.print_action = QAction("Print...", self)
        self.print_action.setShortcut(QKeySequence.Print)
        self.print_action.setToolTip("Print the circuit")
        self.print_action.triggered.connect(self.print_circuit)

        self.toggle_pickoff_action = QAction(
            "Toggle Signal Pickoff",
            self
        )
        self.toggle_pickoff_action.triggered.connect(
            self.toggle_selected_signal_pickoff
        )
        self.toggle_pickoff_action.setEnabled(False)

        self.rotate_component_action = QAction("Rotate Part", self)
        self.rotate_component_action.setShortcut(QKeySequence("R"))
        self.rotate_component_action.triggered.connect(
            self.rotate_selected_component
        )
        self.rotate_component_action.setEnabled(False)

        # Deletes the selected part and any selected wires.
        self.delete_component_action = QAction("Delete", self)
        self.delete_component_action.setShortcut(QKeySequence.Delete)
        self.delete_component_action.triggered.connect(self.delete_selection)
        self.delete_component_action.setEnabled(False)

        # Wire mode: a press-drag from one grid point to another draws a
        # wire. Off, the same press-drag selects as before.
        self.wire_mode_action = QAction("Wire Mode", self)
        self.wire_mode_action.setCheckable(True)
        self.wire_mode_action.setShortcut(QKeySequence("W"))
        self.wire_mode_action.setToolTip(
            "Wire Mode (W): press on a grid point and drag to another to "
            "draw a wire"
        )
        self.wire_mode_action.toggled.connect(self.set_wire_mode)

        self.probe_mode_action = QAction("Probe Mode", self)
        self.probe_mode_action.setCheckable(True)
        self.probe_mode_action.setShortcut(QKeySequence("P"))
        self.probe_mode_action.setToolTip(
            "Probe Mode (P): click a grid point for a voltage probe, "
            "or a part for a current probe"
        )
        self.probe_mode_action.toggled.connect(self.set_probe_mode)

        # R, Delete and W act only while the grid view has focus, so they
        # never fire from a dock widget (combo box, line edit, button).
        # The menu and toolbar entries still work from anywhere.
        for component_action in (
                self.rotate_component_action,
                self.delete_component_action,
                self.wire_mode_action,
                self.probe_mode_action):
            component_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.connection_grid_view.addAction(component_action)

        # Zoom shortcuts work from anywhere in the window. Ctrl+= is the
        # same key as Ctrl++ without Shift on most keyboards.
        self.zoom_in_action = QAction("Zoom In", self)
        self.zoom_in_action.setShortcuts(
            [QKeySequence.ZoomIn, QKeySequence("Ctrl+=")]
        )
        self.zoom_in_action.triggered.connect(
            self.connection_grid_view.zoom_in
        )

        self.zoom_out_action = QAction("Zoom Out", self)
        self.zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        self.zoom_out_action.triggered.connect(
            self.connection_grid_view.zoom_out
        )

        self.fit_grid_action = QAction("Zoom to Fit", self)
        self.fit_grid_action.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_grid_action.triggered.connect(
            self.connection_grid_view.fit_grid_in_view
        )

        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)

    def create_menu_bar(self):
        """
        Create the programmatic application menu bar.

        :returns: None
        """
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.new_project_action)
        file_menu.addAction(self.open_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_project_action)
        file_menu.addAction(self.save_project_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.print_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        node_menu = self.menuBar().addMenu("&Node")
        node_menu.addAction(self.toggle_pickoff_action)

        component_menu = self.menuBar().addMenu("&Component")
        component_menu.addAction(self.rotate_component_action)
        component_menu.addAction(self.delete_component_action)
        component_menu.addSeparator()
        component_menu.addAction(self.wire_mode_action)
        component_menu.addAction(self.probe_mode_action)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.fit_grid_action)

    def create_tool_bar(self):
        """
        Create a concise toolbar for common project operations.

        :returns: None
        """
        main_tool_bar = QToolBar("Main Toolbar", self)
        self.addToolBar(main_tool_bar)

        main_tool_bar.addAction(self.new_project_action)
        main_tool_bar.addAction(self.open_project_action)
        main_tool_bar.addAction(self.save_project_action)
        main_tool_bar.addAction(self.print_action)
        main_tool_bar.addSeparator()
        main_tool_bar.addAction(self.toggle_pickoff_action)
        main_tool_bar.addSeparator()
        main_tool_bar.addAction(self.rotate_component_action)
        main_tool_bar.addAction(self.delete_component_action)
        main_tool_bar.addAction(self.wire_mode_action)
        main_tool_bar.addAction(self.probe_mode_action)
        main_tool_bar.addSeparator()
        main_tool_bar.addAction(self.zoom_in_action)
        main_tool_bar.addAction(self.zoom_out_action)
        main_tool_bar.addAction(self.fit_grid_action)

    def create_grid_configuration_toolbar(self):
        """
        Put rows, columns and Apply on their own toolbar at the top.

        The bar sits on the line under the main toolbar. Enter on Apply
        resizes the grid (see ApplyGridButton).

        :returns: None
        """
        self.grid_configuration_widget = GridConfigurationWidget(self)
        self.grid_configuration_widget.set_grid_configuration(
            self.connection_grid.row_count,
            self.connection_grid.column_count
        )
        self.grid_configuration_widget.configuration_requested.connect(
            self.apply_grid_configuration
        )

        self.addToolBarBreak(Qt.TopToolBarArea)
        self.grid_tool_bar = QToolBar("Grid", self)
        self.grid_tool_bar.addWidget(self.grid_configuration_widget)
        self.addToolBar(Qt.TopToolBarArea, self.grid_tool_bar)

    def create_component_dock(self):
        """
        Create the left-side Components dock for placing and editing parts.

        :returns: None
        """
        self.component_panel_widget = ComponentPanelWidget(self)
        # Place shows the part as a ghost first (Billie, Oct 9 12:07).
        self.component_panel_widget.place_requested.connect(
            self.start_pending_placement
        )
        self.component_panel_widget.rotate_requested.connect(
            self.rotate_selected_component
        )
        self.component_panel_widget.value_change_requested.connect(
            self.apply_component_value
        )
        self.component_panel_widget.delete_requested.connect(
            self.delete_selected_component
        )

        self.component_dock = QDockWidget("Components", self)
        self.component_dock.setWidget(self.component_panel_widget)

        self.addDockWidget(
            Qt.LeftDockWidgetArea,
            self.component_dock
        )

    def create_selected_node_dock(self):
        """
        Create the right-side selected-connection-point information dock.

        :returns: None
        """
        selected_node_widget = QWidget()
        selected_node_layout = QFormLayout()

        self.selected_node_identifier_label = QLabel("No point selected")
        self.selected_node_row_label = QLabel("-")
        self.selected_node_column_label = QLabel("-")
        self.selected_node_pickoff_label = QLabel("-")
        self.net_label_line_edit = QLineEdit()
        self.net_label_line_edit.setPlaceholderText("Vcc")
        self.net_label_line_edit.setToolTip(
            "Name this point, for example Vcc. Every point with that "
            "name shares one source."
        )
        self.net_label_line_edit.returnPressed.connect(
            self.apply_selected_net_label
        )
        self.net_label_line_edit.setEnabled(False)
        self.apply_net_label_button = ApplyGridButton("Apply")
        self.apply_net_label_button.setToolTip(
            "Apply this net label. Enter does this too."
        )
        self.apply_net_label_button.clicked.connect(
            self.apply_selected_net_label
        )
        self.apply_net_label_button.setEnabled(False)
        net_label_row = QWidget()
        net_label_layout = QHBoxLayout()
        net_label_layout.setContentsMargins(0, 0, 0, 0)
        net_label_layout.addWidget(self.net_label_line_edit)
        net_label_layout.addWidget(self.apply_net_label_button)
        net_label_row.setLayout(net_label_layout)
        self.selected_node_formula_label = QLabel("-")
        self.selected_node_formula_label.setWordWrap(True)
        self.selected_node_formula_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        self._node_formula_book = None

        self.toggle_pickoff_button = QPushButton(
            "Toggle Signal Pickoff"
        )
        self.toggle_pickoff_button.clicked.connect(
            self.toggle_selected_signal_pickoff
        )
        self.toggle_pickoff_button.setEnabled(False)

        selected_node_layout.addRow(
            "Identifier:",
            self.selected_node_identifier_label
        )
        selected_node_layout.addRow(
            "Row:",
            self.selected_node_row_label
        )
        selected_node_layout.addRow(
            "Column:",
            self.selected_node_column_label
        )
        selected_node_layout.addRow(
            "Signal Pickoff:",
            self.selected_node_pickoff_label
        )
        selected_node_layout.addRow("Label:", net_label_row)
        selected_node_layout.addRow(
            "Formula:",
            self.selected_node_formula_label
        )
        selected_node_layout.addRow(self.toggle_pickoff_button)

        selected_node_widget.setLayout(selected_node_layout)

        selected_node_dock = QDockWidget(
            "Selected Connection Point",
            self
        )
        selected_node_dock.setWidget(selected_node_widget)

        self.addDockWidget(
            Qt.RightDockWidgetArea,
            selected_node_dock
        )

    def create_probe_dock(self):
        """
        Create the dock that shows the selected probe and its method.

        :returns: None
        """
        probe_widget = QWidget()
        probe_layout = QFormLayout()

        self.probe_name_label = QLabel("No probe selected")
        self.probe_method_combo = QComboBox()
        self.probe_method_combo.setEnabled(False)

        for method in PROBE_METHODS:
            self.probe_method_combo.addItem(
                PROBE_METHOD_LABELS[method], method
            )

        self.probe_method_combo.currentIndexChanged[int].connect(
            self.apply_probe_method
        )
        self.probe_where_label = QLabel("-")
        self.probe_where_label.setWordWrap(True)
        self.probe_reading_label = QLabel("-")
        self.probe_reading_label.setWordWrap(True)
        self.probe_reading_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        self.probe_parameter_box = QGroupBox("Parameters")
        self.probe_parameter_label = QLabel("-")
        self.probe_parameter_label.setWordWrap(True)
        self.probe_parameter_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        parameter_layout = QVBoxLayout()
        parameter_layout.addWidget(self.probe_parameter_label)
        self.probe_parameter_box.setLayout(parameter_layout)
        self.probe_note_label = QLabel(
            "Probe Mode (P): click a grid point, or click a part for current."
        )
        self.probe_note_label.setWordWrap(True)

        probe_layout.addRow("Probe:", self.probe_name_label)
        probe_layout.addRow("Method:", self.probe_method_combo)
        probe_layout.addRow("Where:", self.probe_where_label)
        probe_layout.addRow("Reading:", self.probe_reading_label)
        probe_layout.addRow(self.probe_parameter_box)
        probe_layout.addRow(self.probe_note_label)
        probe_widget.setLayout(probe_layout)

        probe_dock = QDockWidget("Probe", self)
        probe_dock.setWidget(probe_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, probe_dock)

    def apply_grid_configuration(self, row_count, column_count):
        """
        Resize the connection grid using the selected configuration.

        :param row_count: Requested row count.
        :type row_count: int
        :param column_count: Requested column count.
        :type column_count: int
        :returns: None
        """
        labels_before = set(self.connection_grid.get_net_labels())

        try:
            # Update the core model first. The GUI is rebuilt only after
            # validation and grid construction complete successfully.
            removed_pickoff_identifiers = self.connection_grid.configure(
                row_count,
                column_count
            )

        except GridConfigurationError as error:
            self.show_error_message(
                "Grid Configuration Failed",
                str(error),
                "Select a row and column count within the allowed range."
            )
            return

        removed_label_identifiers = sorted(
            labels_before.difference(self.connection_grid.get_net_labels())
        )

        # Drop the parts that no longer fit, before the scene is rebuilt
        # from the collection.
        removed_component_references = (
            self.component_collection.remove_components_outside_grid(
                self.connection_grid
            )
        )
        removed_wire_references = (
            self.wire_collection.remove_wires_outside_grid(
                self.connection_grid
            )
        )
        removed_probe_references = (
            self.probe_collection.remove_for_components(
                removed_component_references
            )
        )
        removed_probe_references.extend(
            self.probe_collection.remove_outside_grid(self.connection_grid)
        )

        # Rebuild the editor after the validated model update succeeds.
        # The rebuild drops the part selection, so restore it afterwards.
        selected_component_reference = self.selected_component_reference
        self.connection_grid_scene.set_connection_grid(
            self.connection_grid
        )
        self.select_component_by_reference(selected_component_reference)
        self.selected_connection_point_identifier = None
        self._node_formula_book = None
        self.refresh_selected_node_formula()
        self.is_project_modified = True

        self.update_window_title()

        QTimer.singleShot(
            0,
            self.connection_grid_view.fit_grid_in_view
        )

        if (removed_pickoff_identifiers or removed_component_references or
                removed_wire_references or removed_label_identifiers or
                removed_probe_references):
            removed_descriptions = []

            if removed_pickoff_identifiers:
                removed_descriptions.append(
                    f"{len(removed_pickoff_identifiers)} signal pickoff(s)"
                )

            if removed_component_references:
                removed_references_text = ", ".join(
                    removed_component_references
                )
                removed_descriptions.append(
                    f"{len(removed_component_references)} part(s) "
                    f"({removed_references_text})"
                )

            if removed_wire_references:
                removed_descriptions.append(
                    f"{len(removed_wire_references)} wire(s) "
                    f"({', '.join(removed_wire_references)})"
                )

            if removed_label_identifiers:
                removed_descriptions.append(
                    f"{len(removed_label_identifiers)} net label(s)"
                )

            if removed_probe_references:
                removed_descriptions.append(
                    f"{len(removed_probe_references)} probe(s)"
                )

            removed_text = " and ".join(removed_descriptions)
            self.statusBar().showMessage(
                f"Grid updated. Removed {removed_text} outside the new grid "
                "boundary.",
                7000
            )
        else:
            self.statusBar().showMessage(
                "Grid updated: {} rows x {} columns = {} connection points."
                .format(
                    row_count,
                    column_count,
                    self.connection_grid.get_connection_point_count()
                ),
                5000
            )

    def handle_connection_point_selection(self, connection_point):
        """
        Update the selected-node dock after a grid selection change.

        :param connection_point: Selected point, or None when no point is selected.
        :type connection_point: core.connection_grid.ConnectionPoint or None
        :returns: None
        """
        if connection_point is None:
            self.selected_connection_point_identifier = None

            self.selected_node_identifier_label.setText(
                "No point selected"
            )
            self.selected_node_row_label.setText("-")
            self.selected_node_column_label.setText("-")
            self.selected_node_pickoff_label.setText("-")
            self.selected_node_formula_label.setText("-")
            self.net_label_line_edit.clear()
            self.net_label_line_edit.setEnabled(False)
            self.apply_net_label_button.setEnabled(False)

            self.toggle_pickoff_action.setEnabled(False)
            self.toggle_pickoff_button.setEnabled(False)
            return

        self.selected_connection_point_identifier = (
            connection_point.identifier
        )

        self.selected_node_identifier_label.setText(
            connection_point.identifier
        )
        self.selected_node_row_label.setText(
            str(connection_point.row_number)
        )
        self.selected_node_column_label.setText(
            str(connection_point.column_number)
        )

        if connection_point.is_signal_pickoff:
            self.selected_node_pickoff_label.setText("Enabled")
        else:
            self.selected_node_pickoff_label.setText("Disabled")

        self.net_label_line_edit.setText(connection_point.net_label)
        self.net_label_line_edit.setEnabled(True)
        self.apply_net_label_button.setEnabled(True)

        self.toggle_pickoff_action.setEnabled(True)
        self.toggle_pickoff_button.setEnabled(True)
        self.refresh_selected_node_formula()

    def refresh_selected_node_formula(self):
        """
        Show the s-domain voltage at the selected grid point.

        The same formula is shared by every point on that node. A bridge
        does not join the point it hops. Points with the same net label do.

        :returns: None
        """
        identifier = self.selected_connection_point_identifier

        if identifier is None:
            self.selected_node_formula_label.setText("-")
            return

        self.selected_node_formula_label.setText(
            self.formula_book().text_at(identifier)
        )

    def formula_book(self):
        """
        Return the solved formulas, including probe loads.

        A 1 Mohm probe and a 10x probe add their parts to ground. Direct,
        differential and current probes do not.

        :rtype: core.node_formula.NodeFormulas
        """
        if self._node_formula_book is None:
            self._node_formula_book = build_node_formulas(
                self.component_collection.get_components(),
                self.wire_collection,
                self.connection_grid,
                shunt_loads(self.probe_collection.get_probes())
            )

        return self._node_formula_book

    def apply_selected_net_label(self):
        """
        Store the name typed for the selected point.

        The same name on another point, ignoring case, makes both points
        one node. A blank name clears the label. Enter in the box and
        Enter on Apply both do this.

        :returns: None
        """
        identifier = self.selected_connection_point_identifier

        if identifier is None:
            self.show_error_message(
                "No Connection Point Selected",
                "A net label needs a selected connection point.",
                "Select one grid point, type a name such as Vcc, and "
                "press Apply."
            )
            return

        previous_label = self.connection_grid.get_connection_point(
            identifier
        ).net_label

        try:
            label = self.connection_grid.set_net_label(
                identifier,
                self.net_label_line_edit.text()
            )
        except GridConfigurationError as error:
            self.show_error_message(
                "Net Label Not Applied",
                str(error),
                "Use a name such as Vcc, Vss or Vdd, or leave the box "
                "blank to clear the name."
            )
            return

        self.net_label_line_edit.setText(label)

        if label == previous_label:
            return

        self.connection_grid_scene.refresh_connection_point(identifier)
        self.connection_grid_scene.update_wire_nets()

        if label:
            message = f"{identifier} is net {label}."
        else:
            message = f"{identifier} has no net label."

        self.mark_project_modified(message)

    def handle_component_selection(self, component):
        """
        Update the Components dock and part actions after a selection change.

        :param component: Selected part, or None when no part is selected.
        :type component: core.components.Component or None
        :returns: None
        """
        if component is None:
            self.selected_component_reference = None
        else:
            self.selected_component_reference = component.reference

        self.component_panel_widget.show_component(component)
        self.rotate_component_action.setEnabled(component is not None)
        self.update_delete_action()

    def handle_wire_selection(self, wire_references):
        """
        Remember the selected wires so Delete can remove them.

        :param wire_references: References of the selected wires.
        :type wire_references: list
        :returns: None
        """
        self.selected_wire_references = list(wire_references)
        self.update_delete_action()

    def update_delete_action(self):
        """
        Enable Delete when a part or a wire is selected.

        :returns: None
        """
        self.delete_component_action.setEnabled(
            self.selected_component_reference is not None or
            bool(self.selected_wire_references) or
            self.selected_probe_reference is not None
        )

    def set_wire_mode(self, is_wire_mode):
        """
        Turn Wire mode on or off (the toolbar and menu action calls this).

        :param is_wire_mode: True to draw wires by press-dragging.
        :type is_wire_mode: bool
        :returns: None
        """
        if self.wire_mode_action.isChecked() != bool(is_wire_mode):
            # Keep the action in step; its toggled signal calls back here.
            self.wire_mode_action.setChecked(bool(is_wire_mode))
            return

        if is_wire_mode and self.probe_mode_action.isChecked():
            self.probe_mode_action.setChecked(False)

        self.connection_grid_scene.set_wire_mode(is_wire_mode)
        self.connection_grid_view.viewport().setCursor(
            Qt.CrossCursor if is_wire_mode else Qt.ArrowCursor
        )

        if is_wire_mode:
            self.statusBar().showMessage(
                "Wire mode: press on a grid point and drag to another grid "
                "point. If the wire crosses another wire, choose Connect "
                "or Bridge. Esc cancels a wire; W leaves Wire mode.",
                7000
            )
        else:
            self.statusBar().showMessage("Wire mode off.", 3000)

    def set_probe_mode(self, is_probe_mode):
        """
        Turn Probe mode on or off.

        Probe mode and Wire mode are not on together. A click on a grid
        point places a Direct probe. A click on a part places a current
        probe. P or Esc leaves the mode; Esc also drops a half-chosen
        differential second point.

        :param is_probe_mode: True to place probes by clicking.
        :type is_probe_mode: bool
        :returns: None
        """
        if self.probe_mode_action.isChecked() != bool(is_probe_mode):
            self.probe_mode_action.setChecked(bool(is_probe_mode))
            return

        if is_probe_mode and self.wire_mode_action.isChecked():
            self.wire_mode_action.setChecked(False)

        self.connection_grid_scene.set_probe_mode(is_probe_mode)
        self.connection_grid_view.viewport().setCursor(
            Qt.CrossCursor if is_probe_mode else Qt.ArrowCursor
        )

        if is_probe_mode:
            self.statusBar().showMessage(
                "Probe mode: click a grid point for a voltage probe, or a "
                "part for a current probe. Choose the method in the Probe "
                "panel. P leaves Probe mode.",
                7000
            )
        else:
            self.statusBar().showMessage("Probe mode off.", 3000)

    def handle_probe_added(self, reference):
        """
        Report a new probe and show its reading.

        :param reference: Probe reference, such as ``P1``.
        :type reference: str
        :returns: None
        """
        self.selected_probe_reference = reference
        self.mark_project_modified(f"Added probe {reference}.")
        self.show_probe(self.probe_collection.get(reference))

    def handle_probe_moved(self, reference):
        """
        Report a probe that moved or gained its second point.

        :param reference: Probe reference.
        :type reference: str
        :returns: None
        """
        self.selected_probe_reference = reference
        self.mark_project_modified(f"Updated probe {reference}.")
        self.show_probe(self.probe_collection.get(reference))

    def handle_probe_refused(self, reason):
        """
        Tell the user why a probe was not placed or moved.

        :param reason: Plain-English explanation.
        :type reason: str
        :returns: None
        """
        self.statusBar().showMessage(reason, 7000)

    def handle_probe_selection(self, references):
        """
        Show the first selected probe in the Probe dock.

        :param references: Selected probe references.
        :type references: list
        :returns: None
        """
        self.selected_probe_reference = references[0] if references else None
        self.update_delete_action()

        if self.selected_probe_reference is None:
            self.show_probe(None)
            return

        try:
            probe = self.probe_collection.get(self.selected_probe_reference)
        except ComponentError:
            # Delete removes the probe, then the scene drops the flag and
            # reports the selection change. The probe is already gone.
            self.selected_probe_reference = None
            self.show_probe(None)
            return

        self.show_probe(probe)

    def handle_differential_cancelled(self):
        """
        Report that the second point of a differential probe was cancelled.

        :returns: None
        """
        self.statusBar().showMessage(
            "Differential probe left on one point. Click the other point "
            "when you are ready.",
            5000
        )

    def show_probe(self, probe):
        """
        Fill the Probe dock from one probe, or clear it.

        :param probe: Selected probe, or None.
        :type probe: core.probes.Probe or None
        :returns: None
        """
        if probe is None:
            self.probe_name_label.setText("No probe selected")
            self.probe_method_combo.blockSignals(True)
            self.probe_method_combo.setCurrentIndex(0)
            self.probe_method_combo.blockSignals(False)
            self.probe_method_combo.setEnabled(False)
            self.probe_where_label.setText("-")
            self.probe_reading_label.setText("-")
            self.probe_parameter_label.setText("-")
            return

        self.probe_name_label.setText(probe.reference)
        self.probe_method_combo.blockSignals(True)
        method_index = self.probe_method_combo.findData(probe.method)
        if method_index >= 0:
            self.probe_method_combo.setCurrentIndex(method_index)
        self.probe_method_combo.blockSignals(False)
        self.probe_method_combo.setEnabled(True)
        self.probe_where_label.setText(self._probe_where_text(probe))
        self.probe_reading_label.setText(self._probe_reading(probe))
        self._fill_parameter_box(probe)

    def apply_probe_method(self, index):
        """
        Change the selected probe's method from the combo box.

        Differential with no second point waits for the next grid click.

        :param index: Combo index.
        :type index: int
        :returns: None
        """
        if self.selected_probe_reference is None or index < 0:
            return

        method = self.probe_method_combo.itemData(index)

        try:
            probe = self.probe_collection.set_method(
                self.selected_probe_reference,
                method,
                self.component_collection.get_components()
            )
        except ComponentError as error:
            self.show_probe(self.probe_collection.get(
                self.selected_probe_reference
            ))
            self.show_error_message(
                "Probe Method Not Changed",
                str(error),
                "Choose another method, or click the part you want to measure."
            )
            return

        if probe.method == "differential" and probe.second_identifier is None:
            self.connection_grid_scene.pending_differential_reference = (
                probe.reference
            )

            if not self.probe_mode_action.isChecked():
                self.probe_mode_action.setChecked(True)

            status = (
                f"{probe.reference} is differential. Click the other point."
            )
        else:
            self.connection_grid_scene.pending_differential_reference = None
            status = (
                f"{probe.reference} is "
                f"{PROBE_METHOD_LABELS[probe.method]}."
            )

        self.connection_grid_scene.rebuild_probe_items()
        self.connection_grid_scene.select_probe(probe.reference)
        self._node_formula_book = None
        self.mark_project_modified(status)
        self.show_probe(probe)

    def _probe_where_text(self, probe):
        """
        Return the short location line for the Probe dock.

        :rtype: str
        """
        if probe.method == "current":
            return probe.component_reference or "-"

        if probe.method == "differential":
            second = probe.second_identifier or "click the other point"

            return f"{probe.identifier} minus {second}"

        return probe.identifier or "-"

    def refresh_probe_parameters(self):
        """
        Fill every unplotted probe's parameter box from the formula.

        The selected probe's box is in the Probe dock. Every probe also
        draws its box on the grid, beside its flag.

        :returns: None
        """
        if not hasattr(self, "probe_parameter_label"):
            return

        components = self.component_collection.get_components()
        book = self.formula_book()
        lines_by_reference = {}

        for probe in self.probe_collection.get_probes():
            lines_by_reference[probe.reference] = parameter_lines(
                probe,
                book,
                components,
                self._probe_component(probe)
            )

        self._probe_parameter_lines = lines_by_reference
        self.connection_grid_scene.set_probe_readouts(lines_by_reference)

        if self.selected_probe_reference is None:
            self.probe_parameter_label.setText("-")
            return

        try:
            probe = self.probe_collection.get(self.selected_probe_reference)
        except ComponentError:
            self.probe_parameter_label.setText("-")
            return

        self._fill_parameter_box(probe)

    def _fill_parameter_box(self, probe):
        """
        Put one probe's meter lines in the Parameters box.

        :param probe: Selected probe, or None.
        :returns: None
        """
        if probe is None:
            self.probe_parameter_label.setText("-")
            return

        if probe.has_plot:
            self.probe_parameter_label.setText("On a plot.")
            return

        lines = self._probe_parameter_lines.get(probe.reference, ())

        if not lines:
            self.probe_parameter_label.setText("-")
            return

        self.probe_parameter_label.setText(
            "\n".join(f"{label}: {value}" for label, value in lines)
        )

    def _probe_component(self, probe):
        """
        Return the part a current probe sits on, or None.

        :rtype: core.components.Component or None
        """
        if not probe.component_reference:
            return None

        try:
            return self.component_collection.get_component(
                probe.component_reference
            )
        except ComponentError:
            return None

    def _probe_reading(self, probe):
        """
        Return the formula or current shown for one probe.

        :rtype: str
        """
        return describe_reading(
            probe, self.formula_book(), self._probe_component(probe)
        )

    def choose_wire_crossing(self, start_identifier, end_identifier,
                             crossings):
        """
        Ask whether a wire that crosses another wire should join or hop.

        :param start_identifier: Where the new wire starts.
        :type start_identifier: str
        :param end_identifier: Where the new wire ends.
        :type end_identifier: str
        :param crossings: (identifier, wire references) from the collection.
        :type crossings: list
        :returns: "connect", "bridge" or "cancel".
        :rtype: str
        """
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Question)
        message.setWindowTitle("Wire Crossing")
        message.setText(
            f"From {start_identifier} to {end_identifier}. "
            + describe_crossings(crossings)
        )
        message.setInformativeText(
            "Connect joins those points. Bridge hops over them, so this "
            "wire does not connect there."
        )
        connect_button = message.addButton(
            "Connect", QMessageBox.AcceptRole
        )
        bridge_button = message.addButton("Bridge", QMessageBox.AcceptRole)
        message.addButton(QMessageBox.Cancel)
        message.setDefaultButton(connect_button)
        message.exec_()
        clicked = message.clickedButton()

        if clicked is bridge_button:
            return "bridge"

        if clicked is connect_button:
            return "connect"

        return "cancel"

    def handle_wire_added(self, reference):
        """
        Report a new wire.

        :param reference: The new wire.
        :type reference: str
        :returns: None
        """
        wire = self.wire_collection.get_wire(reference)
        self.mark_project_modified(f"Added {wire.describe()}.")

    def handle_wire_refused(self, reason):
        """
        Say why no wire was added.

        :param reason: Message from the scene or the collection.
        :type reason: str
        :returns: None
        """
        self.statusBar().showMessage(f"Wire not added: {reason}", 10000)

    def select_component_by_reference(self, reference):
        """
        Select a part's item again after the scene rebuilt every item.

        A rebuild drops the selection, which clears the Components dock;
        selecting the new item by reference shows the part again.

        :param reference: Part to select, or None for no change.
        :type reference: str or None
        :returns: None
        """
        if reference is None:
            return

        component_item = (
            self.connection_grid_scene.component_items_by_reference.get(
                reference
            )
        )

        if component_item is not None:
            component_item.setSelected(True)

    def get_selected_component(self):
        """
        Return the selected part, or None.

        :returns: Selected part.
        :rtype: core.components.Component or None
        """
        if self.selected_component_reference is None:
            return None

        try:
            return self.component_collection.get_component(
                self.selected_component_reference
            )

        except ComponentError:
            return None

    def mark_project_modified(self, status_message):
        """
        Flag unsaved changes, refresh the title, and report what changed.

        :param status_message: Status-bar text.
        :type status_message: str
        :returns: None
        """
        self.is_project_modified = True
        self._node_formula_book = None
        self.refresh_selected_node_formula()
        self.refresh_probe_parameters()
        self.update_window_title()
        pending_status = self.connection_grid_scene.get_pending_status()

        if pending_status is not None:
            # A part still waits to be placed: keep its "Placing ..." text
            # (with the up-to-date fits / can't-go-here wording) in view.
            self.statusBar().showMessage(f"{status_message} {pending_status}")
            return

        self.statusBar().showMessage(status_message, 5000)

    def start_pending_placement(self, kind, value_text, parameter_texts=None):
        """
        Show a new part as a ghost on the selected grid point (Place).

        The part is not placed yet: the arrow keys or W/A/S/D turn it,
        clicking another grid point moves it, Enter or a right-click
        places it and Esc cancels it (see ConnectionGridScene). Wire mode
        is turned off so a click moves the ghost instead of drawing.

        :param kind: Component kind, for example "resistor".
        :type kind: str
        :param value_text: Value as typed, for example "4k7".
        :type value_text: str
        :param parameter_texts: Extra settings as typed, or None.
        :type parameter_texts: dict or None
        :returns: None
        """
        if self.selected_connection_point_identifier is None:
            self.show_error_message(
                "No Connection Point Selected",
                "A part is placed on the selected connection point, and no "
                "point is selected.",
                "Click a grid point first, then place the part."
            )
            return

        if self.wire_mode_action.isChecked():
            self.set_wire_mode(False)

        try:
            self.connection_grid_scene.start_pending_placement(
                kind,
                value_text,
                parameter_texts,
                self.selected_connection_point_identifier
            )
        except ComponentError as error:
            self.statusBar().showMessage(f"Part not placed: {error}", 10000)
            self.show_error_message(
                "Part Not Placed",
                str(error),
                "Check the value and settings, then press Place again."
            )
            return

        # The placing keys work while the grid view has focus.
        self.connection_grid_view.setFocus(Qt.OtherFocusReason)

    def handle_pending_placement_changed(self, status_text):
        """
        Show where the waiting part is and whether it may go there.

        :param status_text: Text from the scene.
        :type status_text: str
        :returns: None
        """
        # No timeout: it stays while the part waits.
        self.statusBar().showMessage(status_text)

    def handle_pending_placement_committed(self, reference):
        """
        Finish placing a part that was waiting (Enter or right-click).

        :param reference: The new part.
        :type reference: str
        :returns: None
        """
        component = self.component_collection.get_component(reference)
        self.finish_placing_component(component)

    def handle_pending_placement_refused(self, message):
        """
        Say why the waiting part can't go here; it keeps waiting.

        :param message: Refusal with the free directions at this point.
        :type message: str
        :returns: None
        """
        self.statusBar().showMessage(f"Part not placed: {message}")
        self.show_error_message(
            "Part Not Placed",
            message,
            "Turn it with the arrow keys or W/A/S/D, click another grid "
            "point, or press Esc to cancel."
        )
        self.connection_grid_view.setFocus(Qt.OtherFocusReason)

    def handle_pending_placement_cancelled(self):
        """
        Report that the waiting part was dropped (Esc).

        :returns: None
        """
        self.statusBar().showMessage("Placing cancelled.", 3000)

    def place_component(self, kind, value_text, parameter_texts=None,
                        rotation=0):
        """
        Place a new part on the selected grid point at once (no ghost).

        Place in the panel goes through start_pending_placement instead;
        this is the direct path used by scripts and tests.

        :param kind: Component kind, for example "resistor".
        :type kind: str
        :param value_text: Value as typed, for example "4k7".
        :type value_text: str
        :param parameter_texts: Extra settings as typed, for example
            {"frequency": "50"} for an AC source.
        :type parameter_texts: dict or None
        :param rotation: Rotation in degrees.
        :type rotation: int
        :returns: None
        """
        if self.selected_connection_point_identifier is None:
            self.show_error_message(
                "No Connection Point Selected",
                "A part is placed on the selected connection point, and no "
                "point is selected.",
                "Click a grid point first, then place the part."
            )
            return

        connection_point = self.connection_grid.get_connection_point(
            self.selected_connection_point_identifier
        )

        try:
            component = self.component_collection.add_component(
                kind,
                connection_point.row_number,
                connection_point.column_number,
                value_text,
                self.connection_grid,
                rotation,
                parameter_texts
            )

        except ComponentError as error:
            self.statusBar().showMessage(f"Part not placed: {error}", 10000)
            self.show_error_message(
                "Part Not Placed",
                str(error),
                "Check the value, or pick a point where every pin lands "
                "on the grid and no other part is drawn there."
            )
            return

        self.finish_placing_component(component)

    def finish_placing_component(self, component):
        """
        Show a part that was just stored, select it and report it.

        :param component: The new part.
        :type component: core.components.Component
        :returns: None
        """
        # The rebuild drops the selection; select the new part so it can be
        # rotated (R) or edited at once.
        self.connection_grid_scene.rebuild_component_items()
        self.select_component_by_reference(component.reference)
        self.reveal_component(component.reference)

        # R and Delete are scoped to the grid view, so give it focus.
        self.connection_grid_view.setFocus(Qt.OtherFocusReason)

        placed_text = component.label_text() or component.reference
        anchor_identifier = ConnectionGrid.build_connection_point_identifier(
            component.row_number, component.column_number
        )
        self.mark_project_modified(
            f"Placed {placed_text} at {anchor_identifier}."
        )

    def reveal_component(self, reference):
        """
        Make sure a part and its label are inside the visible editor area.

        A label can grow the scene past the area that was fitted (for
        example at the last column). If the whole grid was in view, the
        view is fitted again; if the user had zoomed in, it only scrolls.

        :param reference: Part to reveal.
        :type reference: str
        :returns: None
        """
        component_item = (
            self.connection_grid_scene.component_items_by_reference.get(
                reference
            )
        )

        if component_item is None:
            return

        part_rect = component_item.sceneBoundingRect()

        if component_item.label_item.isVisible():
            part_rect = part_rect.united(
                component_item.label_item.sceneBoundingRect()
            )

        visible_rect = self.connection_grid_view.mapToScene(
            self.connection_grid_view.viewport().rect()
        ).boundingRect()

        if visible_rect.contains(part_rect):
            return

        if visible_rect.contains(self.connection_grid_scene.get_grid_rect()):
            self.connection_grid_view.fit_grid_in_view()
        else:
            self.connection_grid_view.ensureVisible(part_rect, 10, 10)

    def rotate_selected_component(self):
        """
        Rotate the selected part 90 degrees clockwise.

        :returns: None
        """
        component = self.get_selected_component()

        if component is None:
            return

        try:
            self.component_collection.rotate_component(
                component.reference,
                self.connection_grid
            )

        except ComponentError as error:
            self.statusBar().showMessage(f"Part not rotated: {error}", 10000)
            self.show_error_message(
                "Part Not Rotated",
                str(error),
                "Move the part away from the grid edge or from the other "
                "part, or enlarge the grid."
            )
            return

        # refresh_component keeps the item and its selection, but the
        # panel text must be refreshed by hand. A turn can move the label
        # to another side, past the visible area.
        self.connection_grid_scene.refresh_component(component.reference)
        self.component_panel_widget.show_component(component)
        self.reveal_component(component.reference)
        self.mark_project_modified(
            f"Rotated {component.reference} to {component.rotation} degrees."
        )

    def apply_component_value(self, value_text, parameter_texts=None):
        """
        Change the value (and settings) of the selected part.

        :param value_text: New value as typed, for example "2k2".
        :type value_text: str
        :param parameter_texts: New settings as typed, for example
            {"frequency": "50"}; settings not given are kept.
        :type parameter_texts: dict or None
        :returns: None
        """
        component = self.get_selected_component()

        if component is None:
            return

        try:
            self.component_collection.set_component_value(
                component.reference,
                value_text,
                parameter_texts
            )

        except ComponentError as error:
            self.show_error_message(
                "Part Value Not Changed",
                str(error),
                "Enter a number with an optional prefix, for example 4k7, "
                "100n, 1m or 1k, or a model name for diodes, LEDs and "
                "transistors."
            )
            # Put the unchanged value back in the box.
            self.component_panel_widget.show_component(component)
            return

        self.connection_grid_scene.refresh_component(component.reference)
        self.component_panel_widget.show_component(component)
        self.mark_project_modified(
            f"Set {component.reference} to "
            f"{component.label_text().partition(' ')[2]}."
        )

    def handle_component_moved(self, reference):
        """
        Report a part that was dragged to a new grid point.

        :param reference: Part that moved.
        :type reference: str
        :returns: None
        """
        component = self.component_collection.get_component(reference)

        # The moved part becomes the panel's part, even when several parts
        # are selected.
        self.handle_component_selection(component)

        self.reveal_component(reference)
        self.mark_project_modified(
            f"Moved {reference} to "
            + ConnectionGrid.build_connection_point_identifier(
                component.row_number,
                component.column_number
            )
            + "."
        )

    def handle_component_move_refused(self, reference, reason):
        """
        Tell the user why a dragged part went back to where it was.

        :param reference: Part that was dragged.
        :type reference: str
        :param reason: Message from the collection.
        :type reason: str
        :returns: None
        """
        self.statusBar().showMessage(f"Part not moved: {reason}", 10000)

    def delete_selected_component(self):
        """
        Delete the selected part.

        :returns: None
        """
        component = self.get_selected_component()

        if component is None:
            return

        self.component_collection.remove_component(component.reference)

        # The rebuild clears the selection, which clears the panel.
        self.connection_grid_scene.rebuild_component_items()
        self.mark_project_modified(f"Deleted {component.reference}.")

    def delete_selection(self):
        """
        Delete every selected part, probe and wire (Delete key).

        The status reads, for example, "Deleted C1, R1, P1, W2.": parts,
        then probes, then wires, each naturally sorted. Deleting a part
        also deletes a current probe on that part. A part's wires stay
        where they are.

        :returns: None
        """
        scene = self.connection_grid_scene
        component_references = {
            item.component.reference
            for item in scene.component_items_by_reference.values()
            if item.isSelected()
        }
        panel_component = self.get_selected_component()

        if panel_component is not None:
            component_references.add(panel_component.reference)

        component_references = sorted(
            component_references, key=natural_sort_key
        )
        wire_references = sorted(
            (
                reference for reference in self.selected_wire_references
                if reference in self.wire_collection.wires_by_reference
            ),
            key=natural_sort_key
        )
        probe_references = {
            item.probe.reference
            for item in scene.probe_items
            if item.isSelected()
        }

        if self.selected_probe_reference in self.probe_collection.probes_by_reference:
            probe_references.add(self.selected_probe_reference)

        probe_references.update(
            self.probe_collection.remove_for_components(component_references)
        )
        probe_references = sorted(probe_references, key=natural_sort_key)

        if (not component_references and not wire_references and
                not probe_references):
            return

        for reference in wire_references:
            self.wire_collection.remove_wire(reference)

        for reference in component_references:
            self.component_collection.remove_component(reference)

        for reference in list(probe_references):
            if reference in self.probe_collection.probes_by_reference:
                self.probe_collection.remove(reference)

        deleted_references = (
            component_references + probe_references + wire_references
        )

        if component_references:
            self.selected_component_reference = None
            scene.rebuild_component_items()

        scene.rebuild_wire_items()
        scene.rebuild_probe_items()
        self.selected_wire_references = []
        self.selected_probe_reference = None
        self.update_delete_action()
        self.mark_project_modified(
            f"Deleted {', '.join(deleted_references)}."
        )

    def reset_component_collection(self):
        """
        Start with no parts, wires or probes.

        :returns: None
        """
        self.component_collection = ComponentCollection()
        self.selected_component_reference = None
        self.connection_grid_scene.set_component_collection(
            self.component_collection
        )
        self.wire_collection = WireCollection()
        self.selected_wire_references = []
        self.probe_collection = ProbeCollection()
        self.selected_probe_reference = None
        self._probe_parameter_lines = {}
        self.connection_grid_scene.pending_differential_reference = None
        self._node_formula_book = None
        self.connection_grid_scene.set_wire_collection(self.wire_collection)
        self.connection_grid_scene.set_probe_collection(self.probe_collection)
        self.show_probe(None)
        self.refresh_selected_node_formula()
        self.refresh_probe_parameters()

    def toggle_selected_signal_pickoff(self):
        """
        Toggle future-analysis signal capture at the selected grid point.

        :returns: None
        """
        if self.selected_connection_point_identifier is None:
            self.show_error_message(
                "No Connection Point Selected",
                "A signal pickoff cannot be changed until a connection "
                "point is selected.",
                "Select one blue or green connection point in the grid."
            )
            return

        try:
            is_signal_pickoff = self.connection_grid.toggle_signal_pickoff(
                self.selected_connection_point_identifier
            )

        except GridConfigurationError as error:
            self.show_error_message(
                "Signal Pickoff Update Failed",
                str(error),
                "Select a valid connection point and try again."
            )
            return

        # Refresh only the changed graphical item instead of rebuilding the
        # entire grid for one signal-pickoff state change.
        self.connection_grid_scene.refresh_connection_point(
            self.selected_connection_point_identifier
        )

        selected_connection_point = self.connection_grid.get_connection_point(
            self.selected_connection_point_identifier
        )
        self.handle_connection_point_selection(
            selected_connection_point
        )

        self.is_project_modified = True
        self.update_window_title()

        if is_signal_pickoff:
            self.statusBar().showMessage(
                "{} is now a signal pickoff."
                .format(self.selected_connection_point_identifier),
                4000
            )
        else:
            self.statusBar().showMessage(
                "{} is no longer a signal pickoff."
                .format(self.selected_connection_point_identifier),
                4000
            )

    def create_new_project(self):
        """
        Create a new default 8x8 connection-grid project.

        :returns: None
        """
        if not self.confirm_project_replacement():
            return

        # Reset the in-memory project only after the user addresses unsaved
        # work through save, discard, or cancellation.
        self.connection_grid = ConnectionGrid(8, 8)
        self.current_project_file_path = None
        self.is_project_modified = False
        self.selected_connection_point_identifier = None
        self.reset_component_collection()

        self.connection_grid_scene.set_connection_grid(
            self.connection_grid
        )
        self.grid_configuration_widget.set_grid_configuration(8, 8)
        self.update_window_title()

        QTimer.singleShot(
            0,
            self.connection_grid_view.fit_grid_in_view
        )

        self.statusBar().showMessage(
            "Created a new 8 x 8 grid with 64 connection points.",
            5000
        )

    def open_project(self):
        """
        Load a connection-grid project selected through a file dialog.

        :returns: None
        """
        if not self.confirm_project_replacement():
            return

        selected_file_name, unused_filter = QFileDialog.getOpenFileName(
            self,
            "Open Circuit Workbench Project",
            "",
            PROJECT_FILE_FILTER
        )

        if not selected_file_name:
            return

        selected_project_file_path = Path(selected_file_name)

        try:
            # Fully load and validate into temporary state so a failed load
            # does not overwrite the project currently displayed in the GUI.
            workbook = load_project_file(selected_project_file_path)

        except ProjectFileError as error:
            self.show_error_message(
                "Project Load Failed",
                str(error),
                "Verify the file exists, is readable, and uses the expected "
                "Circuit Workbench project format."
            )
            return

        # Commit the loaded project only after successful file validation.
        self.current_project_file_path = selected_project_file_path
        self.is_project_modified = False
        self.selected_connection_point_identifier = None
        self.show_workbook(workbook)
        self.update_window_title()

        QTimer.singleShot(
            0,
            self.connection_grid_view.fit_grid_in_view
        )

        part_count = len(self.component_collection.get_components())
        wire_count = len(self.wire_collection.get_wires())
        probe_count = len(self.probe_collection.get_probes())
        self.statusBar().showMessage(
            f"Loaded project '{selected_project_file_path.name}': "
            f"{self.connection_grid.row_count} x "
            f"{self.connection_grid.column_count} grid, "
            f"{part_count} parts, {wire_count} wires, {probe_count} probes.",
            5000
        )

    def show_workbook(self, workbook):
        """
        Replace the open circuit with a loaded workbook.

        :param workbook: Grid, parts, wires and probes.
        :type workbook: core.project_io.Workbook
        :returns: None
        """
        self.connection_grid = workbook.connection_grid
        self.component_collection = workbook.component_collection
        self.selected_component_reference = None
        self.wire_collection = workbook.wire_collection
        self.selected_wire_references = []
        self.probe_collection = workbook.probe_collection
        self.selected_probe_reference = None
        self._probe_parameter_lines = {}
        self._node_formula_book = None
        self.connection_grid_scene.component_collection = (
            self.component_collection
        )
        self.connection_grid_scene.wire_collection = self.wire_collection
        self.connection_grid_scene.probe_collection = self.probe_collection
        self.connection_grid_scene.pending_differential_reference = None
        self.connection_grid_scene.set_connection_grid(self.connection_grid)
        self.grid_configuration_widget.set_grid_configuration(
            self.connection_grid.row_count,
            self.connection_grid.column_count
        )
        self.show_probe(None)
        self.refresh_selected_node_formula()
        self.refresh_probe_parameters()

    def save_current_project(self):
        """
        Save the active project to its current location.

        If the project has not been saved previously, prompt for a path.

        :returns: True when a save succeeds; otherwise False.
        :rtype: bool
        """
        if self.current_project_file_path is None:
            return self.save_project_as()

        return self.save_project_to_path(
            self.current_project_file_path
        )

    def save_project_as(self):
        """
        Prompt for a new project path and save the active project.

        :returns: True when a save succeeds; otherwise False.
        :rtype: bool
        """
        suggested_file_name = "untitled_circuit_project.json"

        if self.current_project_file_path is not None:
            suggested_file_name = str(self.current_project_file_path)

        selected_file_name, unused_filter = QFileDialog.getSaveFileName(
            self,
            "Save Circuit Workbench Project",
            suggested_file_name,
            PROJECT_FILE_FILTER
        )

        if not selected_file_name:
            return False

        selected_project_file_path = Path(selected_file_name)

        # Add the expected suffix when a user enters a name without one.
        if selected_project_file_path.suffix.lower() != ".json":
            selected_project_file_path = selected_project_file_path.with_suffix(
                ".json"
            )

        return self.save_project_to_path(selected_project_file_path)

    def save_project_to_path(self, project_file_path):
        """
        Save the active project to a specified destination.

        :param project_file_path: Project destination.
        :type project_file_path: pathlib.Path
        :returns: True when saved; otherwise False.
        :rtype: bool
        """
        try:
            save_project_file(
                project_file_path,
                self.connection_grid,
                self.component_collection,
                self.wire_collection,
                self.probe_collection
            )

        except ProjectFileError as error:
            self.show_error_message(
                "Project Save Failed",
                str(error),
                "Confirm the destination directory exists and that you have "
                "permission to create or replace the selected file."
            )
            return False

        self.current_project_file_path = project_file_path
        self.is_project_modified = False
        self.update_window_title()

        self.statusBar().showMessage(
            f"Saved project '{project_file_path.name}'.",
            5000
        )

        return True

    def print_circuit(self):
        """
        Ask for a printer and print the circuit on one page.

        :returns: None
        """
        printer = QPrinter(QPrinter.HighResolution)
        source = self.connection_grid_scene.itemsBoundingRect()

        if source.width() > source.height():
            printer.setOrientation(QPrinter.Landscape)

        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Print Circuit")

        if dialog.exec_() != QDialog.Accepted:
            return

        if self.render_circuit(printer):
            self.statusBar().showMessage("Printed the circuit.", 5000)
            return

        self.show_error_message(
            "Print Failed",
            "The printer did not start.",
            "Check the printer and try again."
        )

    def render_circuit(self, printer):
        """
        Draw the grid, parts, wires and probes onto one printer page.

        The drawing keeps its shape. A wide circuit is rotated to
        landscape before the print dialog when Print calls this.

        :param printer: Printer or a PDF printer.
        :type printer: QPrinter
        :returns: True when the page was drawn.
        :rtype: bool
        """
        painter = QPainter(printer)

        try:
            if not painter.isActive():
                return False

            painter.setRenderHint(QPainter.Antialiasing)
            page = QRectF(printer.pageRect())
            source = self.connection_grid_scene.itemsBoundingRect()

            if source.isNull():
                source = self.connection_grid_scene.sceneRect()

            source = source.adjusted(-24, -24, 24, 24)
            self.connection_grid_scene.render(painter, page, source)
        finally:
            painter.end()

        return True

    def confirm_project_replacement(self):
        """
        Confirm how unsaved work should be handled before replacement.

        :returns: True when replacement may continue; otherwise False.
        :rtype: bool
        """
        if not self.is_project_modified:
            return True

        confirmation_message = QMessageBox(self)
        confirmation_message.setIcon(QMessageBox.Warning)
        confirmation_message.setWindowTitle("Unsaved Project Changes")
        confirmation_message.setText(
            "The current project contains unsaved changes."
        )
        confirmation_message.setInformativeText(
            "Save the project before opening or creating another project?"
        )

        confirmation_message.setStandardButtons(
            QMessageBox.Save |
            QMessageBox.Discard |
            QMessageBox.Cancel
        )
        confirmation_message.setDefaultButton(QMessageBox.Save)

        selected_button = confirmation_message.exec_()

        if selected_button == QMessageBox.Save:
            return self.save_current_project()

        if selected_button == QMessageBox.Discard:
            return True

        return False

    def closeEvent(self, close_event):
        """
        Provide a graceful shutdown path for unsaved work.

        :param close_event: Qt close event.
        :type close_event: QCloseEvent
        :returns: None
        """
        if not self.is_project_modified:
            close_event.accept()
            return

        if self.confirm_project_replacement():
            close_event.accept()
        else:
            close_event.ignore()

    def update_window_title(self):
        """
        Display project identity and unsaved-change state in the title bar.

        :returns: None
        """
        if self.current_project_file_path is None:
            project_display_name = "Untitled"
        else:
            project_display_name = self.current_project_file_path.name

        if self.is_project_modified:
            modification_indicator = " *"
        else:
            modification_indicator = ""

        self.setWindowTitle(
            "Circuit Workbench - {}{}".format(
                project_display_name,
                modification_indicator
            )
        )

    def show_error_message(self, title, reason, resolution):
        """
        Display an understandable error and recommended corrective action.

        :param title: Short action-oriented error title.
        :type title: str
        :param reason: Specific reason the operation failed.
        :type reason: str
        :param resolution: Recommended user action.
        :type resolution: str
        :returns: None
        """
        error_message = QMessageBox(self)
        error_message.setIcon(QMessageBox.Critical)
        error_message.setWindowTitle(title)
        error_message.setText(reason)
        error_message.setInformativeText(
            "Recommended action: {}".format(resolution)
        )
        error_message.exec_()

    def save_recovery_copy(self):
        """
        Save a timestamped recovery copy in the Qt application-data location.

        This method is available for later top-level unexpected-exception
        handling. Normal save failure currently leaves the GUI open so the
        user can choose another location through Save Project As.

        :returns: Recovery file path when saved; otherwise None.
        :rtype: pathlib.Path or None
        """
        application_data_directory = QStandardPaths.writableLocation(
            QStandardPaths.AppDataLocation
        )

        if not application_data_directory:
            return None

        recovery_directory = (
            Path(application_data_directory) / "recovery"
        )

        try:
            recovery_directory.mkdir(parents=True, exist_ok=True)

            recovery_file_name = "recovery_{}.json".format(
                datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            recovery_file_path = recovery_directory / recovery_file_name

            save_project_file(
                recovery_file_path,
                self.connection_grid,
                self.component_collection,
                self.wire_collection,
                self.probe_collection
            )

        except (OSError, ProjectFileError):
            return None

        return recovery_file_path