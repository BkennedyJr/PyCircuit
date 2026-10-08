"""
Main PyQt5 application window for Circuit Workbench.

This module coordinates GUI actions with the platform-independent core
connection-grid model and project-file services.
"""

from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QStandardPaths
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QAction
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QDockWidget
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QFormLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QToolBar
from PyQt5.QtWidgets import QWidget

from core.connection_grid import ConnectionGrid
from core.exceptions import GridConfigurationError
from core.exceptions import ProjectFileError
from core.project_io import load_project_file
from core.project_io import save_project_file
from gui.grid_configuration_widget import GridConfigurationWidget
from gui.grid_editor import ConnectionGridScene
from gui.grid_editor import ConnectionGridView


PROJECT_FILE_FILTER = "Circuit Workbench Project (*.json);;All Files (*)"


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

        self.connection_grid_scene = ConnectionGridScene(
            self.connection_grid,
            self
        )
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
        self.create_grid_configuration_dock()
        self.create_selected_node_dock()

        self.statusBar().showMessage(
            "Ready. Configure a grid or select a connection point."
        )

    def connect_application_signals(self):
        """
        Connect scene events to main-window display updates.

        :returns: None
        """
        self.connection_grid_scene.connection_point_selected.connect(
            self.handle_connection_point_selection
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

        self.toggle_pickoff_action = QAction(
            "Toggle Signal Pickoff",
            self
        )
        self.toggle_pickoff_action.triggered.connect(
            self.toggle_selected_signal_pickoff
        )
        self.toggle_pickoff_action.setEnabled(False)

        self.fit_grid_action = QAction("Fit Grid", self)
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
        file_menu.addAction(self.exit_action)

        node_menu = self.menuBar().addMenu("&Node")
        node_menu.addAction(self.toggle_pickoff_action)

        view_menu = self.menuBar().addMenu("&View")
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
        main_tool_bar.addSeparator()
        main_tool_bar.addAction(self.toggle_pickoff_action)
        main_tool_bar.addAction(self.fit_grid_action)

    def create_grid_configuration_dock(self):
        """
        Create the left-side connection-grid configuration dock.

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

        grid_configuration_dock = QDockWidget(
            "Grid Configuration",
            self
        )
        grid_configuration_dock.setWidget(self.grid_configuration_widget)

        self.addDockWidget(
            Qt.LeftDockWidgetArea,
            grid_configuration_dock
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

    def apply_grid_configuration(self, row_count, column_count):
        """
        Resize the connection grid using the selected configuration.

        :param row_count: Requested row count.
        :type row_count: int
        :param column_count: Requested column count.
        :type column_count: int
        :returns: None
        """
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

        # Rebuild the editor after the validated model update succeeds.
        self.connection_grid_scene.set_connection_grid(
            self.connection_grid
        )
        self.selected_connection_point_identifier = None
        self.is_project_modified = True

        self.update_window_title()

        QTimer.singleShot(
            0,
            self.connection_grid_view.fit_grid_in_view
        )

        if removed_pickoff_identifiers:
            self.statusBar().showMessage(
                "Grid updated. Removed {} signal pickoff(s) outside the "
                "new grid boundary.".format(
                    len(removed_pickoff_identifiers)
                ),
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

        self.toggle_pickoff_action.setEnabled(True)
        self.toggle_pickoff_button.setEnabled(True)

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
            loaded_connection_grid = load_project_file(
                selected_project_file_path
            )

        except ProjectFileError as error:
            self.show_error_message(
                "Project Load Failed",
                str(error),
                "Verify the file exists, is readable, and uses the expected "
                "Circuit Workbench project format."
            )
            return

        # Commit the loaded project only after successful file validation.
        self.connection_grid = loaded_connection_grid
        self.current_project_file_path = selected_project_file_path
        self.is_project_modified = False
        self.selected_connection_point_identifier = None

        self.connection_grid_scene.set_connection_grid(
            self.connection_grid
        )
        self.grid_configuration_widget.set_grid_configuration(
            self.connection_grid.row_count,
            self.connection_grid.column_count
        )
        self.update_window_title()

        QTimer.singleShot(
            0,
            self.connection_grid_view.fit_grid_in_view
        )

        self.statusBar().showMessage(
            "Loaded project '{}' with {} connection points."
            .format(
                selected_project_file_path.name,
                self.connection_grid.get_connection_point_count()
            ),
            5000
        )

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
                self.connection_grid
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
            "Saved project '{}'.".format(project_file_path.name),
            4000
        )

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
                self.connection_grid
            )

        except (OSError, ProjectFileError):
            return None

        return recovery_file_path