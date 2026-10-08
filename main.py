"""
Circuit Workbench application entry point.

This module intentionally remains small. GUI implementation resides in the
``gui`` package, while platform-independent data and project-file logic
resides in the ``core`` package.
"""

import sys
import traceback

from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QMessageBox

from gui.main_window import MainWindow


def install_unhandled_exception_handler():
    """
    Install a user-visible handler for unexpected Python exceptions.

    Expected errors are handled by specific GUI actions. This fallback keeps
    unexpected errors visible in the Spyder console or terminal and provides
    a clear GUI message instead of silently terminating the application.

    :returns: None
    """
    def handle_unhandled_exception(
            exception_type,
            exception_value,
            exception_traceback):
        # Preserve the full traceback in Spyder or the command-line console
        # so a developer can identify the precise source-code location.
        traceback.print_exception(
            exception_type,
            exception_value,
            exception_traceback
        )

        # Inform the user that the active operation failed unexpectedly.
        # The GUI remains available when the Qt event loop can continue.
        QMessageBox.critical(
            None,
            "Unexpected Application Error",
            "An unexpected error occurred.\n\n"
            "Reason: {}\n\n"
            "The full technical traceback was written to the active "
            "Spyder console or command-line window. If the application "
            "remains responsive, save your work immediately."
            .format(exception_value)
        )

    sys.excepthook = handle_unhandled_exception


def main():
    """
    Create and run the PyQt5 Circuit Workbench application.

    :returns: Application exit code.
    :rtype: int
    """
    application = QApplication(sys.argv)

    application.setOrganizationName("CircuitWorkbench")
    application.setApplicationName("CircuitWorkbench")

    # Install unexpected-error reporting before constructing the main window.
    install_unhandled_exception_handler()

    main_window = MainWindow()
    main_window.show()

    return application.exec_()


if __name__ == "__main__":
    sys.exit(main())