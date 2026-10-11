"""
Help and About for Circuit Workbench.

Help shows docs/help.txt. About shows the version from core.version.
"""

from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.version import APP_NAME, about_text


def help_file_path():
    """
    Path to the help text that ships next to the program.

    :rtype: pathlib.Path
    """
    return Path(__file__).resolve().parents[1] / "docs" / "help.txt"


def read_help_text(path=None):
    """
    Read the help file as text.

    :param path: File to read. The shipped help file is used when omitted.
    :type path: str or pathlib.Path or None
    :returns: Help file contents.
    :rtype: str
    :raises OSError: The file is missing or cannot be read.
    :raises UnicodeError: The file is not text.
    """
    help_path = help_file_path() if path is None else Path(path)
    if not help_path.is_file():
        raise OSError(
            f"The help file could not be opened ({help_path})."
        )
    return help_path.read_text(encoding="utf-8")


class HelpDialog(QDialog):
    """
    Scrollable view of the help text.

    :param help_text: Contents of the help file.
    :type help_text: str
    :param parent: Optional Qt parent.
    :type parent: QWidget or None
    """

    def __init__(self, help_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Help")
        self.resize(560, 420)

        self.help_text_edit = QPlainTextEdit()
        self.help_text_edit.setReadOnly(True)
        self.help_text_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.help_text_edit.setPlainText(help_text)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.help_text_edit)
        layout.addWidget(buttons)
        self.setLayout(layout)


def build_about_box(parent):
    """
    About box whose text is the application name and version.

    :param parent: Window that owns the box.
    :type parent: QWidget
    :rtype: QMessageBox
    """
    about_box = QMessageBox(parent)
    about_box.setIcon(QMessageBox.Information)
    about_box.setWindowTitle(f"About {APP_NAME}")
    about_box.setText(APP_NAME)
    about_box.setInformativeText(about_text())
    return about_box
