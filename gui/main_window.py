"""
Main PyQt5 application window for Circuit Workbench.

This module coordinates GUI actions with the platform-independent core
connection-grid model and project-file services.
"""

import os
import re
import threading
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QRectF
from PyQt5.QtCore import QSettings
from PyQt5.QtCore import QStandardPaths
from PyQt5.QtCore import QThread
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtGui import QPainter
from PyQt5.QtPrintSupport import QPrintDialog
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtWidgets import QAction
from PyQt5.QtWidgets import QActionGroup
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
from PyQt5.QtWidgets import QScrollArea
from PyQt5.QtWidgets import QTabBar
from PyQt5.QtWidgets import QTabWidget
from PyQt5.QtWidgets import QToolBar
from PyQt5.QtWidgets import QToolButton
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QWidget

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.exceptions import GridConfigurationError
from core.exceptions import ProjectFileError
from core.exceptions import SimulationError
from core.netlist import append_shunt_loads
from core.netlist import build_netlist
from core.netlist import spice_node_map
from core.netlist import write_netlist_file
from core.project_io import load_project_file
from core.project_io import save_project_file
from core.node_formula import build_node_formulas
from core.probes import PROBE_METHOD_LABELS
from core.probes import PROBE_METHODS
from core.probes import ProbeCollection
from core.probes import describe_reading
from core.probes import parameter_lines
from core.probes import shunt_loads
from core.units import format_dc_reading
from core.wires import WireCollection
from core.wires import describe_crossings
from gui.bode_widget import BodeDock
from gui.bode_widget import BodeRunner
from gui.component_panel_widget import ComponentPanelWidget
from gui.dc_numbers import DcOperatingPointRunner
from gui.fft_widget import FftDock
from gui.help_dialog import HelpDialog
from gui.help_dialog import build_about_box
from gui.help_dialog import read_help_text
from gui.grid_configuration_widget import ApplyGridButton
from gui.grid_configuration_widget import GridConfigurationWidget
from gui.grid_editor import ConnectionGridScene
from gui.grid_editor import ConnectionGridView
from gui.scope_widget import OscilloscopeDock
from gui.scope_widget import TransientRunner
from sim.runner import ac_source_peak
from sim.runner import lit_led_references
from sim.runner import probe_bode
from sim.runner import probe_series
from sim.runner import probe_spectrum
from sim.runner import transient_step


PROJECT_FILE_FILTER = "Circuit Workbench Project (*.json);;All Files (*)"
NETLIST_FILE_FILTER = "SPICE Netlist (*.cir);;All Files (*)"
_NETLIST_SUFFIXES = (".cir", ".net", ".sp")
# Commands that already live in the menus. The user shows or hides each
# one on the main toolbar. Zoom stays in the View menu: it has shortcuts
# and Ctrl plus the wheel.
_TOOLBAR_GROUPS = (
    (
        "new_project_action",
        "open_project_action",
        "save_project_action",
        "print_action",
    ),
    ("toggle_pickoff_action",),
    (
        "rotate_component_action",
        "delete_component_action",
        "wire_mode_action",
        "probe_mode_action",
        "dc_operating_point_action",
    ),
)
_DEFAULT_TOOLBAR = (
    "delete_component_action",
    "wire_mode_action",
    "probe_mode_action",
    "dc_operating_point_action",
)
# The first toolbar choice included Save. File already has it, so that
# exact saved set drops Save and keeps the rest.
_PREVIOUS_DEFAULT_TOOLBAR = (
    "save_project_action",
) + _DEFAULT_TOOLBAR
_TOOLBAR_COMMANDS = tuple(
    name for group in _TOOLBAR_GROUPS for name in group
)



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
        self._toolbar_shown = set(_DEFAULT_TOOLBAR)
        self._toolbar_toggles = {}
        self.selected_connection_point_identifier = None
        self.component_collection = ComponentCollection()
        self.selected_component_reference = None
        self.wire_collection = WireCollection()
        self.selected_wire_references = []
        self.probe_collection = ProbeCollection()
        self.selected_probe_reference = None
        self._probe_parameter_lines = {}
        self._dc_thread = None
        self._dc_runner = None
        self._dc_run_id = 0
        self._dc_active_run_id = 0
        self._dc_name_by_point = {}
        self._dc_volts_by_node = {}
        self._dc_rerun = False
        self._tran_thread = None
        self._tran_runner = None
        self._tran_run_id = 0
        self._tran_active_run_id = 0
        self._tran_cancel = None
        self._tran_stop_requested = False
        self._tran_result = None
        self._tran_name_by_point = {}
        self._tran_rerun = False
        self._ac_thread = None
        self._ac_runner = None
        self._ac_run_id = 0
        self._ac_active_run_id = 0
        self._ac_cancel = None
        self._ac_stop_requested = False
        self._ac_result = None
        self._ac_name_by_point = {}
        self._ac_reference_peak = None
        self._ac_rerun = False
        # A closed plot is left alone. Opening it runs the missed update.
        self._tran_stale = False
        self._ac_stale = False
        self._fft_dirty = False
        # Continuous runs a showing result again when a value changes.
        # Snapshot keeps that one reading and clears it on the next edit.
        self._continuous = True

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
        self.create_oscilloscope_dock()
        self.create_bode_dock()
        self.create_fft_dock()
        self.create_tool_bar()
        self.create_grid_configuration_toolbar()
        self.create_component_dock()
        self.create_selected_node_dock()
        self.create_probe_dock()
        self.configure_docks()
        self.create_menu_bar()

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

        self.export_netlist_action = QAction("Export Netlist...", self)
        self.export_netlist_action.setToolTip(
            "Write a SPICE netlist you can open in LTspice"
        )
        self.export_netlist_action.triggered.connect(self.export_netlist)

        self.dc_operating_point_action = QAction("DC Operating Point", self)
        self.dc_operating_point_action.setToolTip(
            "Run ngspice and draw the DC voltages and currents"
        )
        self.dc_operating_point_action.triggered.connect(
            self.run_dc_operating_point
        )

        self.snapshot_action = QAction("Snapshot", self)
        self.snapshot_action.setCheckable(True)
        self.snapshot_action.setToolTip(
            "Keep one reading. A new value clears the DC numbers and "
            "the plots."
        )
        self.continuous_action = QAction("Continuous", self)
        self.continuous_action.setCheckable(True)
        self.continuous_action.setChecked(True)
        self.continuous_action.setToolTip(
            "A new value updates the DC numbers and any plot already "
            "showing."
        )
        self._update_mode_group = QActionGroup(self)
        self._update_mode_group.setExclusive(True)
        self._update_mode_group.addAction(self.snapshot_action)
        self._update_mode_group.addAction(self.continuous_action)
        self._update_mode_group.triggered.connect(
            self._on_update_mode_action
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

        self.help_action = QAction("Help...", self)
        self.help_action.setShortcut(QKeySequence.HelpContents)
        self.help_action.setToolTip("Open the help text")
        self.help_action.triggered.connect(self.show_help)

        self.about_action = QAction("About Circuit Workbench", self)
        self.about_action.setToolTip("Show the Circuit Workbench version")
        self.about_action.triggered.connect(self.show_about)

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
        file_menu.addAction(self.export_netlist_action)
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

        simulate_menu = self.menuBar().addMenu("&Simulate")
        simulate_menu.addAction(self.dc_operating_point_action)
        simulate_menu.addSeparator()
        simulate_menu.addAction(self.snapshot_action)
        simulate_menu.addAction(self.continuous_action)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.fit_grid_action)
        view_menu.addSeparator()
        toolbar_menu = view_menu.addMenu("Toolbar")
        toolbar_menu.setToolTip(
            "Choose which menu commands sit on the main toolbar"
        )

        for name in _TOOLBAR_COMMANDS:
            command = getattr(self, name)
            toggle = QAction(command.text(), self)
            toggle.setCheckable(True)
            toggle.setChecked(name in self._toolbar_shown)
            toggle.toggled.connect(
                lambda checked, command_name=name:
                self.set_toolbar_command(command_name, checked)
            )
            toolbar_menu.addAction(toggle)
            self._toolbar_toggles[name] = toggle

        view_menu.addSeparator()
        view_menu.addAction(self.component_dock.toggleViewAction())
        view_menu.addAction(self.selected_node_dock.toggleViewAction())
        view_menu.addAction(self.probe_dock.toggleViewAction())
        view_menu.addAction(self.oscilloscope_dock.toggleViewAction())
        view_menu.addAction(self.bode_dock.toggleViewAction())
        view_menu.addAction(self.fft_dock.toggleViewAction())

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self.help_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)

    def create_tool_bar(self):
        """
        Create the one top toolbar. Commands and the grid size share it.

        View > Toolbar shows or hides each command. Zoom is not on
        this bar. Save stays in the File menu.

        :returns: None
        """
        self.main_tool_bar = QToolBar("Toolbar", self)
        self.main_tool_bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        # Rows and columns sit on this same bar.
        self.grid_tool_bar = self.main_tool_bar
        self.addToolBar(Qt.TopToolBarArea, self.main_tool_bar)

    def rebuild_main_toolbar(self):
        """
        Put the chosen commands on the toolbar, then the grid size.

        :returns: None
        """
        self.main_tool_bar.clear()
        started = False

        for group in _TOOLBAR_GROUPS:
            chosen = [
                getattr(self, name)
                for name in group
                if name in self._toolbar_shown
            ]

            if not chosen:
                continue

            if started:
                self.main_tool_bar.addSeparator()

            started = True

            for action in chosen:
                self._add_toolbar_command(action)

        if started:
            self.main_tool_bar.addSeparator()

        self.main_tool_bar.addWidget(self.grid_configuration_widget)

    def _add_toolbar_command(self, action):
        """
        Put one command on the toolbar without taking its shortcut.

        Delete, R, W and P belong to the grid. A button on this bar
        must not make them fire while rows or Apply has focus.

        :param action: Menu command to show.
        :type action: QAction
        :returns: None
        """
        button = QToolButton(self.main_tool_bar)
        button.setDefaultAction(action)
        self.main_tool_bar.addWidget(button)

    def set_toolbar_command(self, name, shown):
        """
        Show or hide one menu command on the main toolbar.

        :param name: Attribute name of the command, such as
            ``save_project_action``.
        :type name: str
        :param shown: True to put it on the toolbar.
        :type shown: bool
        :returns: None
        """
        if name not in _TOOLBAR_COMMANDS:
            return

        if shown:
            self._toolbar_shown.add(name)
        else:
            self._toolbar_shown.discard(name)

        self.rebuild_main_toolbar()
        self.save_toolbar_choice()

    def save_toolbar_choice(self):
        """
        Remember which commands are on the main toolbar.

        Tests skip this so a test run does not change a real machine.

        :returns: None
        """
        if "PYTEST_CURRENT_TEST" in os.environ:
            return

        ordered = [
            name
            for name in _TOOLBAR_COMMANDS
            if name in self._toolbar_shown
        ]
        settings = QSettings("CircuitWorkbench", "CircuitWorkbench")
        settings.setValue("toolbar-v1", "|".join(ordered))

    def restore_toolbar_choice(self):
        """
        Put the saved commands back on the main toolbar.

        A missing setting keeps the short default set. Zoom is never
        restored onto this bar.

        :returns: None
        """
        settings = QSettings("CircuitWorkbench", "CircuitWorkbench")
        stored = settings.value("toolbar-v1")

        if stored is None:
            return

        names = [
            part for part in str(stored).split("|")
            if part in _TOOLBAR_COMMANDS
        ]

        if tuple(names) == _PREVIOUS_DEFAULT_TOOLBAR:
            names = list(_DEFAULT_TOOLBAR)

        self._toolbar_shown = set(names)
        self.rebuild_main_toolbar()

    def create_grid_configuration_toolbar(self):
        """
        Put rows, columns and Apply on the same toolbar as the commands.

        Enter on Apply resizes the grid (see ApplyGridButton).

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
        self.rebuild_main_toolbar()

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

        # A short or narrow dock scrolls. The part names stay whole.
        self.component_scroll = QScrollArea()
        self.component_scroll.setWidgetResizable(True)
        self.component_scroll.setFrameShape(QScrollArea.NoFrame)
        self.component_scroll.setWidget(self.component_panel_widget)

        self.component_dock = QDockWidget("Components", self)
        self.component_dock.setWidget(self.component_scroll)
        # The scroll area's own minimum is tiny, so a wide scope would
        # squash the part names. Keep the dock wide enough for them.
        self.component_dock.setMinimumWidth(
            self.component_panel_widget.sizeHint().width()
        )

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
        self.selected_node_dc_label = QLabel("-")
        self.selected_node_dc_label.setWordWrap(True)
        self.selected_node_dc_label.setTextInteractionFlags(
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
        selected_node_layout.addRow(
            "DC:",
            self.selected_node_dc_label
        )
        selected_node_layout.addRow(self.toggle_pickoff_button)

        selected_node_widget.setLayout(selected_node_layout)

        self.selected_node_dock = QDockWidget(
            "Selected Connection Point",
            self
        )
        self.selected_node_dock.setWidget(selected_node_widget)

        self.addDockWidget(
            Qt.RightDockWidgetArea,
            self.selected_node_dock
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
        self.reset_probe_position_button = QPushButton("Reset position")
        self.reset_probe_position_button.setToolTip(
            "Put the probe back beside the point it is reading."
        )
        self.reset_probe_position_button.setEnabled(False)
        self.reset_probe_position_button.clicked.connect(
            self.reset_selected_probe_position
        )
        self.probe_note_label = QLabel(
            "Probe Mode (P): click a grid point, or click a part for "
            "current. Drag a probe to move it. The arrow shows the "
            "point it reads."
        )
        self.probe_note_label.setWordWrap(True)

        probe_layout.addRow("Probe:", self.probe_name_label)
        probe_layout.addRow("Method:", self.probe_method_combo)
        probe_layout.addRow("Where:", self.probe_where_label)
        probe_layout.addRow("Reading:", self.probe_reading_label)
        probe_layout.addRow(self.reset_probe_position_button)
        probe_layout.addRow(self.probe_parameter_box)
        probe_layout.addRow(self.probe_note_label)
        probe_widget.setLayout(probe_layout)

        self.probe_dock = QDockWidget("Probe", self)
        self.probe_dock.setWidget(probe_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.probe_dock)

    def create_oscilloscope_dock(self):
        """
        Create the oscilloscope dock along the bottom of the window.

        View > Oscilloscope shows or hides it. Drag the title bar to
        move it. It starts under the circuit, not over the part buttons.

        :returns: None
        """
        self.oscilloscope_dock = OscilloscopeDock(self)
        self.oscilloscope_dock.start_requested.connect(self.run_transient)
        self.oscilloscope_dock.stop_requested.connect(self.stop_transient)
        self.oscilloscope_dock.channels_changed.connect(self.replot_transient)
        self.oscilloscope_dock.update_mode_combo.activated.connect(
            self._on_update_mode_combo
        )
        self.oscilloscope_dock.visibilityChanged.connect(
            self._on_scope_visibility
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self.oscilloscope_dock)
        self.oscilloscope_dock.refresh_automatic_times(
            self.component_collection.get_components()
        )

    def create_bode_dock(self):
        """
        Create the Bode dock. It starts as a tab on the oscilloscope.

        View > Bode shows or hides it. Drag the title bar to move it.

        :returns: None
        """
        self.bode_dock = BodeDock(self)
        self.bode_dock.start_requested.connect(self.run_frequency_sweep)
        self.bode_dock.stop_requested.connect(self.stop_frequency_sweep)
        self.bode_dock.channels_changed.connect(self.replot_bode)
        self.bode_dock.update_mode_combo.activated.connect(
            self._on_update_mode_combo
        )
        self.bode_dock.visibilityChanged.connect(self._on_bode_visibility)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.bode_dock)

    def create_fft_dock(self):
        """
        Create the FFT dock. It starts as a tab on the oscilloscope.

        View > FFT shows or hides it. The curves are the spectrum of
        the last oscilloscope run.

        :returns: None
        """
        self.fft_dock = FftDock(self)
        self.fft_dock.channels_changed.connect(self.replot_fft)
        self.fft_dock.update_mode_combo.activated.connect(
            self._on_update_mode_combo
        )
        self.fft_dock.visibilityChanged.connect(self._on_fft_visibility)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.fft_dock)

    def configure_docks(self):
        """
        Make every panel drag, float, and dock.

        The bottom corners belong to the side panels, so the
        oscilloscope stays under the circuit and does not cover the
        part buttons. The right-hand panels start as tabs. The last
        arrangement comes back the next time the program opens, except
        while tests run.

        :returns: None
        """
        dock_features = (
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        named_docks = (
            (self.component_dock, "components"),
            (self.selected_node_dock, "selected_connection_point"),
            (self.probe_dock, "probe"),
            (self.oscilloscope_dock, "oscilloscope"),
            (self.bode_dock, "bode"),
            (self.fft_dock, "fft"),
        )

        for dock, object_name in named_docks:
            dock.setObjectName(object_name)
            dock.setFeatures(dock_features)

        self.setDockOptions(
            QMainWindow.AnimatedDocks
            | QMainWindow.AllowNestedDocks
            | QMainWindow.AllowTabbedDocks
            | QMainWindow.GroupedDragging
        )
        # Side panels own the corners. A bottom dock would otherwise
        # paint over the bottom of the Components panel.
        self.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.TopRightCorner, Qt.RightDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        self.tabifyDockWidget(self.selected_node_dock, self.probe_dock)
        self.selected_node_dock.raise_()
        self.selected_node_dock.setMinimumWidth(
            max(
                self.selected_node_dock.sizeHint().width(),
                self.probe_dock.sizeHint().width(),
            )
        )
        # Tabs sit at the top of a panel. The default puts them at the
        # bottom, beside the scope.
        for area in (
            Qt.LeftDockWidgetArea,
            Qt.RightDockWidgetArea,
            Qt.TopDockWidgetArea,
            Qt.BottomDockWidgetArea,
        ):
            self.setTabPosition(area, QTabWidget.North)

        self.main_tool_bar.setObjectName("main_toolbar")
        self.main_tool_bar.setMovable(True)
        self.main_tool_bar.setFloatable(True)
        self.tabifyDockWidget(self.oscilloscope_dock, self.bode_dock)
        self.tabifyDockWidget(self.oscilloscope_dock, self.fft_dock)
        self.oscilloscope_dock.raise_()
        # Tall enough for the trace, with the controls beside it.
        # A saved arrangement replaces this.
        self.resizeDocks(
            [self.oscilloscope_dock],
            [400],
            Qt.Vertical,
        )
        self.restore_window_arrangement()

    def save_window_arrangement(self):
        """
        Remember where the panels and toolbars are.

        Tests skip this so they always see the default layout, and so
        a test run does not change the arrangement on a real machine.

        :returns: None
        """
        if "PYTEST_CURRENT_TEST" in os.environ:
            return

        settings = QSettings("CircuitWorkbench", "CircuitWorkbench")
        settings.setValue("geometry-v2", self.saveGeometry())
        settings.setValue("state-v2", self.saveState())

    def restore_window_arrangement(self):
        """
        Put the panels and toolbars back where they were last time.

        :returns: None
        """
        if "PYTEST_CURRENT_TEST" in os.environ:
            return

        settings = QSettings("CircuitWorkbench", "CircuitWorkbench")
        # v2 drops the short scope that hid its controls under the grid.
        geometry = settings.value("geometry-v2")
        state = settings.value("state-v2")

        if geometry is not None:
            self.restoreGeometry(geometry)

        if state is not None:
            self.restoreState(state)

        self.restore_toolbar_choice()

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
        self.clear_dc_numbers()
        self.clear_scope_run()
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
            self.selected_node_dc_label.setText("-")
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
            self.selected_node_dc_label.setText("-")
            return

        self.selected_node_formula_label.setText(
            self.formula_book().text_at(identifier)
        )
        self.selected_node_dc_label.setText(self.dc_text_at(identifier))

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
        self.mark_project_modified(
            f"Added probe {reference}.", keep_scope=True
        )
        self.show_probe(self.probe_collection.get(reference))
        self.refresh_scope_channels()
        self.refresh_bode_channels()
        self.refresh_fft_channels()
        self.replot_transient()
        self.replot_bode()
        self.replot_fft()

    def handle_probe_moved(self, reference):
        """
        Report a probe that moved or gained its second point.

        :param reference: Probe reference.
        :type reference: str
        :returns: None
        """
        self.selected_probe_reference = reference
        self.mark_project_modified(
            f"Updated probe {reference}.", keep_scope=True
        )
        self.show_probe(self.probe_collection.get(reference))
        self.refresh_scope_channels()
        self.refresh_bode_channels()
        self.refresh_fft_channels()
        self.replot_transient()
        self.replot_bode()
        self.replot_fft()

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
            self.reset_probe_position_button.setEnabled(False)
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
        self.reset_probe_position_button.setEnabled(probe.flag_is_moved())
        self._fill_parameter_box(probe)

    def reset_selected_probe_position(self):
        """
        Put the selected probe's picture back beside the point it reads.

        The point it reads does not change.

        :returns: None
        """
        reference = self.selected_probe_reference

        if reference is None:
            return

        try:
            probe = self.probe_collection.get(reference)
        except ComponentError:
            return

        if not probe.flag_is_moved():
            return

        self.connection_grid_scene.reset_probe_position(reference)
        self.mark_project_modified(f"Reset probe {reference}.")
        self.show_probe(probe)

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
        self.mark_project_modified(status, keep_scope=True)
        self.show_probe(probe)
        self.refresh_scope_channels()
        self.refresh_bode_channels()
        self.refresh_fft_channels()
        self.replot_transient()
        self.replot_bode()
        self.replot_fft()

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

    def mark_project_modified(self, status_message, keep_scope=False,
                              refresh_results=False):
        """
        Flag unsaved changes, refresh the title, and report what changed.

        Moving a probe keeps the last oscilloscope run so the trace can
        follow that point. Moving or deleting a part drops the DC
        numbers and the plots. In Continuous, a new value runs them
        again. Snapshot keeps one reading and the next edit clears it.

        :param status_message: Status-bar text.
        :type status_message: str
        :param keep_scope: True to leave the last transient on the scope.
        :type keep_scope: bool
        :param refresh_results: True to run DC and each open plot again
            when that plot is already showing a result.
        :type refresh_results: bool
        :returns: None
        """
        self.is_project_modified = True
        self._node_formula_book = None

        if not refresh_results:
            self.clear_dc_numbers()

            if not keep_scope:
                self.clear_scope_run()

        self.refresh_selected_node_formula()
        self.refresh_probe_parameters()
        self.update_window_title()
        pending_status = self.connection_grid_scene.get_pending_status()

        if pending_status is not None:
            # A part still waits to be placed: keep its "Placing ..." text
            # (with the up-to-date fits / can't-go-here wording) in view.
            self.statusBar().showMessage(f"{status_message} {pending_status}")
        else:
            self.statusBar().showMessage(status_message, 5000)

        if refresh_results:
            self.refresh_shown_results()

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
        Change the name and the value (and settings) of the selected part.

        The name comes from the Selected Part name box. A bad name or a
        bad value leaves both as they were.

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

        old_reference = component.reference
        new_reference = (
            self.component_panel_widget.selected_name_line_edit.text().strip()
        )
        old_value_text = component.value_text
        old_parameters = dict(component.parameter_texts)

        if new_reference != old_reference:
            try:
                self.component_collection.rename_component(
                    old_reference, new_reference
                )
            except ComponentError as error:
                self.show_error_message(
                    "Part Not Changed",
                    str(error),
                    "The name and the value were left as they were."
                )
                self.component_panel_widget.show_component(component)
                return

        try:
            self.component_collection.set_component_value(
                component.reference,
                value_text,
                parameter_texts
            )
        except ComponentError as error:
            if component.reference != old_reference:
                self.component_collection.rename_component(
                    component.reference, old_reference
                )

            self.show_error_message(
                "Part Value Not Changed",
                str(error),
                "Enter a number with an optional prefix, for example 4k7, "
                "100n, 1m or 1k, or a model name for diodes, LEDs and "
                "transistors."
            )
            # Put the unchanged name and value back in the boxes.
            self.component_panel_widget.show_component(component)
            return

        renamed = component.reference != old_reference

        if renamed:
            self.probe_collection.rename_part(
                old_reference, component.reference
            )
            scene = self.connection_grid_scene
            item = scene.component_items_by_reference.pop(
                old_reference, None
            )

            if item is not None:
                scene.component_items_by_reference[
                    component.reference
                ] = item

            self.selected_component_reference = component.reference

        value_changed = (
            component.value_text != old_value_text or
            component.parameter_texts != old_parameters
        )
        self.connection_grid_scene.refresh_component(component.reference)
        self.component_panel_widget.show_component(component)

        if not renamed and not value_changed:
            return

        shown = component.label_text().partition(" ")[2]

        if renamed and value_changed:
            status = (
                f"Renamed {old_reference} to {component.reference} "
                f"and set it to {shown}."
            )
        elif renamed:
            status = f"Renamed {old_reference} to {component.reference}."
        else:
            status = f"Set {component.reference} to {shown}."

        self.mark_project_modified(
            status,
            refresh_results=value_changed and self._continuous,
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
            f"Deleted {', '.join(deleted_references)}.",
            keep_scope=not (component_references or wire_references),
        )

        if component_references or wire_references:
            self.clear_scope_run()
        else:
            self.refresh_scope_channels()
            self.refresh_bode_channels()
            self.refresh_fft_channels()
            self.replot_transient()
            self.replot_bode()
            self.replot_fft()

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
        self.clear_dc_numbers()
        self.clear_scope_run()
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
        self.clear_dc_numbers()
        self.clear_scope_run()
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

    def export_netlist(self):
        """
        Ask for a path and write the SPICE netlist of the open circuit.

        :returns: True when a file is written; otherwise False.
        :rtype: bool
        """
        selected = QFileDialog.getSaveFileName(
            self,
            "Export SPICE Netlist",
            "untitled_circuit.cir",
            NETLIST_FILE_FILTER
        )

        if not selected[0]:
            return False

        netlist_file_path = Path(selected[0])

        if netlist_file_path.suffix.lower() not in _NETLIST_SUFFIXES:
            netlist_file_path = netlist_file_path.with_suffix(".cir")

        return self.export_netlist_to_path(netlist_file_path)

    def export_netlist_to_path(self, netlist_file_path):
        """
        Write the open circuit's netlist to a path. No dialog.

        :param netlist_file_path: Destination, for example ``divider.cir``.
        :type netlist_file_path: pathlib.Path
        :returns: True when the file is written; otherwise False.
        :rtype: bool
        """
        try:
            netlist_text = build_netlist(
                self.component_collection,
                self.wire_collection,
                self.connection_grid
            )
            write_netlist_file(netlist_file_path, netlist_text)

        except SimulationError as error:
            self.show_error_message(
                "Netlist Not Written",
                str(error),
                "Fix the circuit, then export the netlist again."
            )
            return False

        self.statusBar().showMessage(
            f"Wrote netlist '{Path(netlist_file_path).name}'.",
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

    def dc_text_at(self, identifier):
        """
        Return the drawn DC voltage at one grid point, or "-".

        The same number is shown for every point on that node. A point
        with no formula still gets this number when the last run had one.

        :param identifier: Connection-point identifier, or None.
        :type identifier: str or None
        :rtype: str
        """
        if identifier is None:
            return "-"

        node_name = self._dc_name_by_point.get(identifier)

        if node_name is None:
            return "-"

        volts = self._dc_volts_by_node.get(node_name)

        if volts is None:
            return "-"

        return format_dc_reading(volts, "V")

    def clear_dc_numbers(self):
        """
        Drop the DC voltages and currents. An in-flight run is ignored.

        :returns: None
        """
        self._dc_rerun = False
        self._dc_run_id += 1
        self._dc_name_by_point = {}
        self._dc_volts_by_node = {}
        self.connection_grid_scene.clear_dc_numbers()
        self.selected_node_dc_label.setText("-")

    def show_dc_operating_point(self, operating_point):
        """
        Draw one operating point on the current circuit.

        Voltages use the same node names as the netlist. Currents are
        drawn on the parts. The selected point's DC line updates too.

        :param operating_point: Result from ``run_op``.
        :type operating_point: sim.runner.OperatingPoint
        :returns: None
        """
        name_by_point, draw_at = spice_node_map(
            self.component_collection.get_components(),
            self.wire_collection,
            self.connection_grid
        )
        self._dc_name_by_point = name_by_point
        self._dc_volts_by_node = dict(operating_point.voltages)
        voltage_text = {}

        for node_name, identifier in draw_at.items():
            volts = operating_point.voltages.get(node_name)

            if volts is None:
                continue

            voltage_text[identifier] = format_dc_reading(volts, "V")

        current_text = {
            reference: format_dc_reading(amps, "A")
            for reference, amps in operating_point.currents.items()
        }
        self.connection_grid_scene.show_dc_numbers(
            voltage_text, current_text
        )
        self.refresh_selected_node_formula()
        self.statusBar().showMessage("DC operating point is drawn.", 5000)

    def set_continuous(self, continuous):
        """
        Choose whether a new value updates the readings.

        Continuous runs the DC numbers and any plot already showing.
        Snapshot leaves the current reading until the next edit, which
        clears it. The Simulate menu and the plot boxes stay together.

        :param continuous: True for Continuous, False for Snapshot.
        :type continuous: bool
        :returns: None
        """
        continuous = bool(continuous)
        changed = continuous != self._continuous
        self._continuous = continuous

        if continuous:
            self.continuous_action.setChecked(True)
        else:
            self.snapshot_action.setChecked(True)

        index = 1 if continuous else 0

        for dock in (
                self.oscilloscope_dock, self.bode_dock, self.fft_dock):
            dock.update_mode_combo.setCurrentIndex(index)

        if not changed:
            return

        if continuous:
            message = (
                "Continuous: a new value updates the DC numbers and "
                "the plots."
            )
        else:
            message = (
                "Snapshot: a new value clears the DC numbers and the plots."
            )

        self.statusBar().showMessage(message, 5000)

    def _on_update_mode_action(self, action):
        """
        Follow a Snapshot or Continuous choice from the Simulate menu.

        :param action: The menu action the user chose.
        :type action: QAction
        :returns: None
        """
        self.set_continuous(action is self.continuous_action)

    def _on_update_mode_combo(self, index):
        """
        Follow a Snapshot or Continuous choice on a plot.

        :param index: 0 is Snapshot, 1 is Continuous.
        :type index: int
        :returns: None
        """
        self.set_continuous(index == 1)

    def refresh_shown_results(self):
        """
        Run again each analysis whose window is open.

        A resistor, a source, a pot position, or a switch does this.
        Nothing starts when that analysis has not been run. A closed
        oscilloscope, Bode, or FFT window is left for when it opens.
        The spectrum needs the oscilloscope run, so that run also
        starts while FFT is open. A run that is still going is dropped
        and replaced by this one.

        :returns: None
        """
        if self._dc_volts_by_node or self._dc_thread is not None:
            self._request_dc_refresh()

        scope_open = self.plot_is_open(self.oscilloscope_dock)
        fft_open = self.plot_is_open(self.fft_dock)

        if self._tran_result is not None or self._tran_thread is not None:
            if scope_open or fft_open:
                self._tran_stale = False
                self._request_tran_refresh()
            else:
                self._tran_stale = True
                self._fft_dirty = True
                self._drop_closed_tran_run()

        if self._ac_result is not None or self._ac_thread is not None:
            if self.plot_is_open(self.bode_dock):
                self._ac_stale = False
                self._request_ac_refresh()
            else:
                self._ac_stale = True
                self._drop_closed_ac_run()

    def _drop_closed_tran_run(self):
        """
        Ignore an oscilloscope run that is still going after its window
        closed and the circuit changed.

        Opening the window starts the new run. This one is not restarted
        when the thread stops.

        :returns: None
        """
        if self._tran_thread is None:
            return

        self._tran_rerun = False
        self._tran_run_id += 1

        if self._tran_cancel is not None:
            self._tran_cancel.set()

    def _drop_closed_ac_run(self):
        """
        Ignore a frequency sweep that is still going after Bode closed
        and the circuit changed.

        :returns: None
        """
        if self._ac_thread is None:
            return

        self._ac_rerun = False
        self._ac_run_id += 1

        if self._ac_cancel is not None:
            self._ac_cancel.set()

    def _request_dc_refresh(self):
        """
        Start a DC operating point, or queue one if a run is busy.

        :returns: None
        """
        if self._dc_thread is not None:
            self._dc_rerun = True
            self._dc_run_id += 1
            return

        self.run_dc_operating_point()

        if self._dc_thread is None:
            self.clear_dc_numbers()

    def _request_tran_refresh(self):
        """
        Start a transient, or queue one if a run is busy.

        The spectrum is drawn from that same transient.

        :returns: None
        """
        if self._tran_thread is not None:
            self._tran_rerun = True
            self._tran_run_id += 1

            if self._tran_cancel is not None:
                self._tran_cancel.set()

            return

        self.run_transient()

        if self._tran_thread is None and self._tran_result is not None:
            self.clear_transient_result()

    def _request_ac_refresh(self):
        """
        Start a frequency sweep, or queue one if a run is busy.

        :returns: None
        """
        if self._ac_thread is not None:
            self._ac_rerun = True
            self._ac_run_id += 1

            if self._ac_cancel is not None:
                self._ac_cancel.set()

            return

        self.run_frequency_sweep()

        if self._ac_thread is None and self._ac_result is not None:
            self.clear_bode_run()

    def run_dc_operating_point(self):
        """
        Build the netlist, then run it in a background thread.

        Probe loads are not included. That is the same netlist File >
        Export Netlist writes. Moving or deleting a part clears the
        numbers. A new value runs this again when the numbers are
        already drawn.

        :returns: None
        """
        if self._dc_thread is not None:
            return

        try:
            netlist = build_netlist(
                self.component_collection.get_components(),
                self.wire_collection,
                self.connection_grid
            )
        except SimulationError as error:
            self.show_error_message(
                "DC Operating Point",
                str(error),
                "Fix the circuit, then run DC Operating Point again."
            )
            return

        self._dc_run_id += 1
        run_id = self._dc_run_id
        thread = QThread(self)
        runner = DcOperatingPointRunner(netlist)
        runner.moveToThread(thread)
        thread.started.connect(runner.run)
        runner.succeeded.connect(self._on_dc_succeeded)
        runner.failed.connect(self._on_dc_failed)
        runner.succeeded.connect(thread.quit)
        runner.failed.connect(thread.quit)
        thread.finished.connect(self._on_dc_thread_finished)
        self._dc_thread = thread
        self._dc_runner = runner
        self._dc_active_run_id = run_id
        self.dc_operating_point_action.setEnabled(False)
        self.statusBar().showMessage("Running the DC operating point...")
        thread.start()

    def _on_dc_succeeded(self, result):
        """
        Draw a finished operating point when the circuit has not changed.

        :param result: Operating point from the background run.
        :returns: None
        """
        if self._dc_active_run_id != self._dc_run_id:
            return

        self.show_dc_operating_point(result)

    def _on_dc_failed(self, reason):
        """
        Show why the background run failed, if that run is still current.

        :param reason: Plain-English message.
        :type reason: str
        :returns: None
        """
        if self._dc_active_run_id != self._dc_run_id:
            return

        if self._dc_volts_by_node:
            self.clear_dc_numbers()

        self.show_error_message(
            "DC Operating Point",
            reason,
            "Fix the circuit, then run DC Operating Point again."
        )

    def _on_dc_thread_finished(self):
        """
        Allow another DC run once the background thread has stopped.

        :returns: None
        """
        rerun = self._dc_rerun
        self._dc_thread = None
        self._dc_runner = None
        self._dc_rerun = False
        self.dc_operating_point_action.setEnabled(True)

        if rerun:
            self._request_dc_refresh()

    def _stop_dc_thread(self):
        """
        Wait for a background DC run to stop.

        :returns: None
        """
        thread = self._dc_thread

        if thread is None:
            return

        thread.quit()
        thread.wait(3000)

    def refresh_scope_channels(self):
        """
        Rebuild the oscilloscope's probe checkboxes.

        :returns: None
        """
        self.oscilloscope_dock.set_channels(self.probe_collection.get_probes())

    def clear_scope_run(self):
        """
        Drop the last transient, the spectrum, and the Bode plot.

        An in-flight run is ignored. LEDs go dark. Probe checkboxes stay.

        :returns: None
        """
        self.clear_transient_result()
        self.clear_bode_run()

    def clear_transient_result(self):
        """
        Drop the oscilloscope run and the spectrum. Bode stays.

        :returns: None
        """
        self._tran_rerun = False
        self._tran_run_id += 1

        if self._tran_cancel is not None:
            self._tran_cancel.set()

        self._tran_result = None
        self._tran_name_by_point = {}
        self._tran_stale = False
        self._fft_dirty = False
        self.oscilloscope_dock.clear_traces()
        self.connection_grid_scene.set_led_lights(set())
        self._set_probe_plots(set())
        self.oscilloscope_dock.refresh_automatic_times(
            self.component_collection.get_components()
        )
        self.refresh_scope_channels()
        self.clear_fft_run()

    def refresh_bode_channels(self):
        """
        Rebuild the Bode plot's probe checkboxes.

        :returns: None
        """
        self.bode_dock.set_channels(self.probe_collection.get_probes())

    def clear_bode_run(self):
        """
        Drop the last frequency sweep. An in-flight run is ignored.

        Probe checkboxes stay.

        :returns: None
        """
        self._ac_rerun = False
        self._ac_run_id += 1

        if self._ac_cancel is not None:
            self._ac_cancel.set()

        self._ac_result = None
        self._ac_name_by_point = {}
        self._ac_reference_peak = None
        self._ac_stale = False
        self.bode_dock.clear_traces()
        self.refresh_bode_channels()

    def refresh_fft_channels(self):
        """
        Rebuild the spectrum's probe checkboxes.

        :returns: None
        """
        self.fft_dock.set_channels(self.probe_collection.get_probes())

    def clear_fft_run(self):
        """
        Drop the spectrum. Probe checkboxes stay.

        The oscilloscope run is cleared by the caller. This does not
        start a new analysis.

        :returns: None
        """
        self.fft_dock.clear_traces()
        self.refresh_fft_channels()

    def showEvent(self, event):
        """
        Watch the plot tabs once the window is on screen.

        :param event: Show event.
        :type event: QShowEvent
        :returns: None
        """
        super().showEvent(event)
        self._watch_plot_tabs()

    def plot_is_open(self, dock):
        """
        Return whether a plot window is the one on screen.

        A tab behind the oscilloscope is not open. A floating plot is
        open while its window is showing. A closed dock is not open.

        :param dock: Oscilloscope, Bode, or FFT dock.
        :type dock: QDockWidget
        :returns: True when that plot should be calculated.
        :rtype: bool
        """
        if not dock.toggleViewAction().isChecked():
            return False

        if dock.isFloating():
            return dock.isVisible()

        self._watch_plot_tabs()
        current = self._plot_tab_is_current(dock.windowTitle())

        if current is None:
            return False

        return current

    def _plot_tab_is_current(self, title):
        """
        Return whether a plot's tab is the one in front.

        :param title: Dock title, for example ``FFT``.
        :type title: str
        :returns: True or False, or None when that title is not tabbed.
        :rtype: bool or None
        """
        found = []

        for bar in self.findChildren(QTabBar):
            for index in range(bar.count()):
                if bar.tabText(index) == title:
                    found.append((bar, index))
                    break

        if not found:
            return None

        visible = [item for item in found if item[0].isVisible()]
        bar, index = max(visible or found, key=lambda item: item[0].count())
        return bar.currentIndex() == index

    def _watch_plot_tabs(self):
        """
        Calculate a plot when the user brings its tab to the front.

        :returns: None
        """
        for bar in self.findChildren(QTabBar):
            if bar.property("watched_plot_tabs"):
                continue

            titles = {bar.tabText(index) for index in range(bar.count())}

            if not titles.intersection(("Oscilloscope", "Bode", "FFT")):
                continue

            bar.setProperty("watched_plot_tabs", True)
            bar.currentChanged.connect(self._calculate_opened_plots)

    def _on_scope_visibility(self, visible):
        """
        Run a missed oscilloscope update when that window opens.

        :param visible: True when the dock is shown.
        :type visible: bool
        :returns: None
        """
        self._calculate_opened_plots()

    def _on_bode_visibility(self, visible):
        """
        Run a missed frequency sweep when the Bode window opens.

        :param visible: True when the dock is shown.
        :type visible: bool
        :returns: None
        """
        self._calculate_opened_plots()

    def _on_fft_visibility(self, visible):
        """
        Draw a missed spectrum when the FFT window opens.

        :param visible: True when the dock is shown.
        :type visible: bool
        :returns: None
        """
        self._calculate_opened_plots()

    def _calculate_opened_plots(self):
        """
        Run a plot that was skipped while its window was closed.

        The spectrum uses the oscilloscope waveform, so opening FFT
        after a new value runs that waveform first.

        :returns: None
        """
        scope_open = self.plot_is_open(self.oscilloscope_dock)
        fft_open = self.plot_is_open(self.fft_dock)

        if (scope_open or fft_open) and self._tran_stale:
            self._tran_stale = False
            self._request_tran_refresh()
        elif fft_open and self._fft_dirty:
            self.replot_fft()

        if self.plot_is_open(self.bode_dock) and self._ac_stale:
            self._ac_stale = False
            self._request_ac_refresh()

    def replot_fft(self):
        """
        Draw the checked probes from the last oscilloscope run.

        A closed FFT window is not calculated. Opening it draws this.

        :returns: None
        """
        result = self._tran_result

        if result is None:
            return

        if not self.plot_is_open(self.fft_dock):
            self._fft_dirty = True
            return

        self._fft_dirty = False
        enabled = set(self.fft_dock.enabled_references())
        traces = []
        missing = []

        try:
            for probe in self.probe_collection.get_probes():
                series = None

                if probe.reference in enabled:
                    series = probe_spectrum(
                        probe, result, self._tran_name_by_point
                    )

                if probe.reference in enabled and series is None:
                    missing.append(probe.reference)

                if series is None:
                    continue

                name = probe.reference

                if probe.method == "current":
                    name = f"{probe.reference} (A)"

                traces.append((name, probe.color, series[0], series[1]))
        except SimulationError as error:
            self.show_error_message(
                "FFT",
                str(error),
                "Run the oscilloscope again."
            )
            return

        self.fft_dock.show_traces(traces)

        if missing:
            names = ", ".join(missing)
            self.statusBar().showMessage(
                f"Press Start again. {names} is not in the last run.",
                7000,
            )

    def replot_bode(self):
        """
        Draw the checked probes from the last frequency sweep.

        :returns: None
        """
        result = self._ac_result

        if result is None:
            return

        enabled = set(self.bode_dock.enabled_references())
        traces = []
        missing = []

        for probe in self.probe_collection.get_probes():
            series = None

            if probe.reference in enabled:
                series = probe_bode(
                    probe,
                    result,
                    self._ac_name_by_point,
                    self._ac_reference_peak,
                )

            if probe.reference in enabled and series is None:
                missing.append(probe.reference)

            if series is None:
                continue

            name = probe.reference

            if probe.method == "current":
                name = f"{probe.reference} (dB A)"

            traces.append((name, probe.color, series[0], series[1], series[2]))

        self.bode_dock.show_traces(traces)

        if missing:
            names = ", ".join(missing)
            self.statusBar().showMessage(
                f"Press Start again. {names} is not in the last sweep.",
                7000,
            )

    def run_frequency_sweep(self):
        """
        Build the netlist, including probe loads, and sweep it in the
        background.

        :returns: None
        """
        if self._ac_thread is not None:
            return

        try:
            parts = self.component_collection.get_components()
            peak = ac_source_peak(parts)
            start = self.bode_dock.start_hertz()
            stop = self.bode_dock.stop_hertz()
            points = self.bode_dock.points_per_decade()
            netlist = build_netlist(
                parts, self.wire_collection, self.connection_grid
            )
            name_by_point, _draw_at = spice_node_map(
                parts, self.wire_collection, self.connection_grid
            )
            netlist = append_shunt_loads(
                netlist,
                shunt_loads(self.probe_collection.get_probes()),
                name_by_point,
            )
        except (SimulationError, ComponentError) as error:
            self.show_error_message(
                "Bode",
                str(error),
                "Fix the circuit or the frequency settings, then press "
                "Start again."
            )
            return

        self._ac_run_id += 1
        run_id = self._ac_run_id
        cancel = threading.Event()
        thread = QThread(self)
        runner = BodeRunner(netlist, start, stop, points, cancel)
        runner.moveToThread(thread)
        thread.started.connect(runner.run)
        runner.succeeded.connect(self._on_ac_succeeded)
        runner.failed.connect(self._on_ac_failed)
        runner.succeeded.connect(thread.quit)
        runner.failed.connect(thread.quit)
        thread.finished.connect(self._on_ac_thread_finished)
        self._ac_thread = thread
        self._ac_runner = runner
        self._ac_cancel = cancel
        self._ac_stop_requested = False
        self._ac_active_run_id = run_id
        self._ac_name_by_point = name_by_point
        self._ac_reference_peak = peak
        self.bode_dock.set_running(True)
        self.statusBar().showMessage("Running the frequency sweep...")
        thread.start()

    def stop_frequency_sweep(self):
        """
        Ask the running sweep to drop its result.

        :returns: None
        """
        if self._ac_thread is None:
            return

        self._ac_rerun = False
        self._ac_stop_requested = True
        self._ac_run_id += 1

        if self._ac_cancel is not None:
            self._ac_cancel.set()

        self.statusBar().showMessage("Stopping the Bode plot...")

    def _on_ac_succeeded(self, result):
        """
        Draw a finished sweep when the circuit has not changed.

        :param result: FrequencySweep from the background run.
        :returns: None
        """
        if self._ac_active_run_id != self._ac_run_id:
            return

        self._ac_result = result
        self._ac_stale = False
        self.replot_bode()
        self.statusBar().showMessage("Bode plot updated.", 5000)

    def _on_ac_failed(self, reason):
        """
        Show why the sweep failed, if that run is still current.

        :param reason: Plain-English message.
        :type reason: str
        :returns: None
        """
        if self._ac_active_run_id != self._ac_run_id:
            return

        if reason == "Stopped.":
            self.statusBar().showMessage("Stopped.", 5000)
            return

        if self._ac_result is not None:
            self.clear_bode_run()

        self.show_error_message(
            "Bode",
            reason,
            "Fix the circuit, then press Start again."
        )

    def _on_ac_thread_finished(self):
        """
        Allow another sweep once the background thread has stopped.

        :returns: None
        """
        stopped = self._ac_stop_requested
        rerun = self._ac_rerun
        self._ac_thread = None
        self._ac_runner = None
        self._ac_cancel = None
        self._ac_stop_requested = False
        self._ac_rerun = False
        self.bode_dock.set_running(False)

        if rerun:
            self._request_ac_refresh()
            return

        if stopped:
            self.statusBar().showMessage("Stopped.", 5000)

    def _stop_ac_thread(self):
        """
        Wait for a background sweep to stop.

        :returns: None
        """
        if self._ac_cancel is not None:
            self._ac_cancel.set()

        thread = self._ac_thread

        if thread is None:
            return

        thread.quit()
        thread.wait(3000)

    def replot_transient(self):
        """
        Draw the checked probes from the last run.

        A probe whose node is not in that run is left off the plot, and
        the status bar asks for Start.

        :returns: None
        """
        result = self._tran_result

        if result is None:
            return

        enabled = set(self.oscilloscope_dock.enabled_references())
        traces = []
        missing = []
        plotted = set()

        for probe in self.probe_collection.get_probes():
            series = None

            if probe.reference in enabled:
                series = probe_series(
                    probe, result, self._tran_name_by_point
                )

            if probe.reference in enabled and series is None:
                missing.append(probe.reference)

            if series is None:
                continue

            plotted.add(probe.reference)
            name = probe.reference

            if probe.method == "current":
                name = f"{probe.reference} (A)"

            traces.append((name, probe.color, series[0], series[1]))

        self._set_probe_plots(plotted)

        try:
            time_per_division = (
                self.oscilloscope_dock.time_per_division_seconds()
            )
            volts_per_division = self.oscilloscope_dock.volts_per_division()
        except ComponentError as error:
            self.show_error_message(
                "Oscilloscope",
                str(error),
                "Use a number such as 1m, or leave volts per division blank."
            )
            return

        self.oscilloscope_dock.show_traces(
            traces, time_per_division, volts_per_division
        )

        if missing:
            names = ", ".join(missing)
            self.statusBar().showMessage(
                f"Press Start again. {names} is not in the last run.",
                7000,
            )

    def _set_probe_plots(self, references):
        """
        Mark which probes have a trace, and redraw their flags.

        :param references: Probe names currently drawn.
        :type references: set
        :returns: None
        """
        for probe in self.probe_collection.get_probes():
            self.probe_collection.set_has_plot(
                probe.reference, probe.reference in references
            )

        self.connection_grid_scene.rebuild_probe_items()

        if self.selected_probe_reference is None:
            return

        try:
            probe = self.probe_collection.get(self.selected_probe_reference)
        except ComponentError:
            return

        self.show_probe(probe)

    def run_transient(self):
        """
        Build the netlist, including probe loads, and run it in the
        background.

        :returns: None
        """
        if self._tran_thread is not None:
            return

        self.oscilloscope_dock.refresh_automatic_times(
            self.component_collection.get_components()
        )

        try:
            stop = self.oscilloscope_dock.run_time_seconds()
            step = transient_step(stop)
            parts = self.component_collection.get_components()
            netlist = build_netlist(
                parts, self.wire_collection, self.connection_grid
            )
            name_by_point, _draw_at = spice_node_map(
                parts, self.wire_collection, self.connection_grid
            )
            netlist = append_shunt_loads(
                netlist,
                shunt_loads(self.probe_collection.get_probes()),
                name_by_point,
            )
        except (SimulationError, ComponentError) as error:
            self.show_error_message(
                "Oscilloscope",
                str(error),
                "Fix the circuit or the time settings, then press Start "
                "again."
            )
            return

        self._tran_run_id += 1
        run_id = self._tran_run_id
        cancel = threading.Event()
        thread = QThread(self)
        runner = TransientRunner(netlist, step, stop, cancel)
        runner.moveToThread(thread)
        thread.started.connect(runner.run)
        runner.succeeded.connect(self._on_tran_succeeded)
        runner.failed.connect(self._on_tran_failed)
        runner.succeeded.connect(thread.quit)
        runner.failed.connect(thread.quit)
        thread.finished.connect(self._on_tran_thread_finished)
        self._tran_thread = thread
        self._tran_runner = runner
        self._tran_cancel = cancel
        self._tran_stop_requested = False
        self._tran_active_run_id = run_id
        self._tran_name_by_point = name_by_point
        self.oscilloscope_dock.set_running(True)
        self.statusBar().showMessage("Running the transient...")
        thread.start()

    def stop_transient(self):
        """
        Ask the running transient to drop its result.

        :returns: None
        """
        if self._tran_thread is None:
            return

        self._tran_rerun = False
        self._tran_stop_requested = True
        self._tran_run_id += 1

        if self._tran_cancel is not None:
            self._tran_cancel.set()

        self.statusBar().showMessage("Stopping the oscilloscope...")

    def _on_tran_succeeded(self, result):
        """
        Draw a finished transient when the circuit has not changed.

        :param result: Transient from the background run.
        :returns: None
        """
        if self._tran_active_run_id != self._tran_run_id:
            return

        self._tran_result = result
        self._tran_stale = False
        self.replot_transient()
        self.replot_fft()
        self.connection_grid_scene.set_led_lights(lit_led_references(
            self.component_collection.get_components(), result
        ))
        self.statusBar().showMessage("Oscilloscope updated.", 5000)

    def _on_tran_failed(self, reason):
        """
        Show why the transient failed, if that run is still current.

        :param reason: Plain-English message.
        :type reason: str
        :returns: None
        """
        if self._tran_active_run_id != self._tran_run_id:
            return

        if reason == "Stopped.":
            self.statusBar().showMessage("Stopped.", 5000)
            return

        if self._tran_result is not None:
            self.clear_transient_result()

        self.show_error_message(
            "Oscilloscope",
            reason,
            "Fix the circuit, then press Start again."
        )

    def _on_tran_thread_finished(self):
        """
        Allow another transient once the background thread has stopped.

        :returns: None
        """
        stopped = self._tran_stop_requested
        rerun = self._tran_rerun
        self._tran_thread = None
        self._tran_runner = None
        self._tran_cancel = None
        self._tran_stop_requested = False
        self._tran_rerun = False
        self.oscilloscope_dock.set_running(False)

        if rerun:
            self._request_tran_refresh()
            return

        if stopped:
            self.statusBar().showMessage("Stopped.", 5000)

    def _stop_tran_thread(self):
        """
        Wait for a background transient to stop.

        :returns: None
        """
        if self._tran_cancel is not None:
            self._tran_cancel.set()

        thread = self._tran_thread

        if thread is None:
            return

        thread.quit()
        thread.wait(3000)

    def closeEvent(self, close_event):
        """
        Provide a graceful shutdown path for unsaved work.

        :param close_event: Qt close event.
        :type close_event: QCloseEvent
        :returns: None
        """
        self._dc_run_id += 1
        self._tran_run_id += 1
        self._ac_run_id += 1
        self._stop_dc_thread()
        self._stop_tran_thread()
        self._stop_ac_thread()

        if not self.is_project_modified:
            self.save_window_arrangement()
            close_event.accept()
            return

        if self.confirm_project_replacement():
            self.save_window_arrangement()
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

    def show_help(self):
        """
        Open the help text. A missing file is reported in plain words.

        :returns: None
        """
        try:
            help_text = read_help_text()
        except (OSError, UnicodeError):
            self.show_error_message(
                "Help",
                "The help file could not be opened.",
                "Restore docs/help.txt next to the program, then "
                "choose Help again."
            )
            return

        HelpDialog(help_text, self).exec_()

    def create_about_box(self):
        """
        Build the About box. The caller shows it.

        :rtype: QMessageBox
        """
        return build_about_box(self)

    def show_about(self):
        """
        Show the application name and version.

        :returns: None
        """
        self.create_about_box().exec_()

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