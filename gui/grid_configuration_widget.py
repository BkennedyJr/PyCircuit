"""
Grid-configuration controls for the Circuit Workbench toolbar.

Rows, columns, the point count they imply, and Apply. Enter on Apply
resizes the grid. Enter inside a spin box only accepts the typed number.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSpinBox, QWidget

from core.connection_grid import MAXIMUM_GRID_DIMENSION, MINIMUM_GRID_DIMENSION


class ApplyGridButton(QPushButton):
    """
    Apply button that treats Enter the same as a click.

    A focused push button answers Space, not Enter. On the grid toolbar
    the user tabs to Apply and presses Enter.
    """

    def keyPressEvent(self, event):
        """
        Apply on Enter or Return. Holding the key does not repeat.

        :param event: Key press sent to this button.
        :type event: QKeyEvent
        :returns: None
        """
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not event.isAutoRepeat():
                self.click()

            event.accept()
            return

        super().keyPressEvent(event)


class GridConfigurationWidget(QWidget):
    """
    Rows, columns and Apply, laid out for a toolbar.

    :param parent: Optional Qt parent object.
    :type parent: QWidget or None
    """

    configuration_requested = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.row_count_spin_box = QSpinBox()
        self.column_count_spin_box = QSpinBox()
        self.connection_point_count_label = QLabel()
        self.apply_configuration_button = ApplyGridButton("Apply")
        self.apply_configuration_button.setToolTip(
            "Apply these rows and columns. Enter does this too."
        )

        self.create_widget_layout()
        self.connect_widget_signals()

        # Establish the requested initial baseline: 8 rows by 8 columns.
        self.set_grid_configuration(8, 8)

    def create_widget_layout(self):
        """
        Lay the controls out in one row.

        :returns: None
        """
        for spin_box in (
                self.row_count_spin_box, self.column_count_spin_box):
            spin_box.setRange(
                MINIMUM_GRID_DIMENSION, MAXIMUM_GRID_DIMENSION
            )
            spin_box.setMinimumWidth(64)

        layout = QHBoxLayout()
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Rows"))
        layout.addWidget(self.row_count_spin_box)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Columns"))
        layout.addWidget(self.column_count_spin_box)
        layout.addSpacing(8)
        layout.addWidget(self.connection_point_count_label)
        layout.addSpacing(8)
        layout.addWidget(self.apply_configuration_button)

        self.setLayout(layout)

    def connect_widget_signals(self):
        """
        Connect control changes to the point-count display and Apply.

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
        Show the total connection-point count implied by the spin boxes.

        :returns: None
        """
        connection_point_count = (
            self.row_count_spin_box.value() *
            self.column_count_spin_box.value()
        )
        self.connection_point_count_label.setText(
            f"{connection_point_count} points"
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
