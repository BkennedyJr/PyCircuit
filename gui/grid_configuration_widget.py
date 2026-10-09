"""
Grid-configuration controls for the Circuit Workbench GUI.
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QFormLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QSpinBox
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QWidget

from core.connection_grid import MAXIMUM_GRID_DIMENSION
from core.connection_grid import MINIMUM_GRID_DIMENSION


class GridConfigurationWidget(QWidget):
    """
    User controls for selecting connection-grid rows and columns.

    :param parent: Optional Qt parent object.
    :type parent: QWidget or None
    """

    configuration_requested = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super(GridConfigurationWidget, self).__init__(parent)

        self.row_count_spin_box = QSpinBox()
        self.column_count_spin_box = QSpinBox()
        self.connection_point_count_label = QLabel()
        self.apply_configuration_button = QPushButton(
            "Apply Grid Configuration"
        )

        self.create_widget_layout()
        self.connect_widget_signals()

        # Establish the requested initial baseline: 8 rows by 8 columns.
        self.set_grid_configuration(8, 8)

    def create_widget_layout(self):
        """
        Create all configuration controls programmatically.

        :returns: None
        """
        self.row_count_spin_box.setRange(
            MINIMUM_GRID_DIMENSION,
            MAXIMUM_GRID_DIMENSION
        )
        self.column_count_spin_box.setRange(
            MINIMUM_GRID_DIMENSION,
            MAXIMUM_GRID_DIMENSION
        )

        form_layout = QFormLayout()
        form_layout.addRow("Rows:", self.row_count_spin_box)
        form_layout.addRow("Columns:", self.column_count_spin_box)
        form_layout.addRow(
            "Connection Points:",
            self.connection_point_count_label
        )

        main_layout = QVBoxLayout()
        main_layout.addWidget(
            QLabel(
                "Set the number of rows and columns in the editable "
                "connection-point grid."
            )
        )
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.apply_configuration_button)
        main_layout.addStretch(1)

        self.setLayout(main_layout)

    def connect_widget_signals(self):
        """
        Connect control changes to total-count display updates.

        :returns: None
        """
        self.row_count_spin_box.valueChanged.connect(
            self.update_connection_point_count_display
        )
        self.column_count_spin_box.valueChanged.connect(
            self.update_connection_point_count_display
        )
        self.apply_configuration_button.clicked.connect(
            self.emit_configuration_request
        )

    def set_grid_configuration(self, row_count, column_count):
        """
        Display an existing grid configuration in the controls.

        :param row_count: Current grid row count.
        :type row_count: int
        :param column_count: Current grid column count.
        :type column_count: int
        :returns: None
        """
        self.row_count_spin_box.setValue(row_count)
        self.column_count_spin_box.setValue(column_count)
        self.update_connection_point_count_display()

    def update_connection_point_count_display(self):
        """
        Show the total connection-point count implied by current controls.

        :returns: None
        """
        connection_point_count = (
            self.row_count_spin_box.value() *
            self.column_count_spin_box.value()
        )

        self.connection_point_count_label.setText(
            "{} total".format(connection_point_count)
        )

    def emit_configuration_request(self):
        """
        Request a grid rebuild using the selected row and column counts.

        :returns: None
        """
        self.configuration_requested.emit(
            self.row_count_spin_box.value(),
            self.column_count_spin_box.value()
        )