"""
Help and About: the menu, the version, and the help file.
"""

from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QDialog, QMessageBox

from core.version import APP_NAME, APP_VERSION, about_text
from gui.help_dialog import HelpDialog, read_help_text
from gui.main_window import MainWindow


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def menu_by_title(window, title):
    return next(
        action.menu()
        for action in window.menuBar().actions()
        if action.text() == title
    )


def test_about_text_is_the_version():
    assert APP_VERSION == "0.1.2"
    assert about_text() == "Version 0.1.2"


def test_help_menu_is_last_and_opens_help_and_about(qt_application):
    window = MainWindow()

    try:
        titles = [action.text() for action in window.menuBar().actions()]
        assert titles[-1] == "&Help"
        help_menu = menu_by_title(window, "&Help")
        entries = list(help_menu.actions())
        assert [action.text() for action in entries] == [
            "Help...",
            "",
            "About Circuit Workbench",
        ]
        assert entries[1].isSeparator()
        assert window.help_action.shortcut() == QKeySequence(
            QKeySequence.HelpContents
        )
    finally:
        close_window(window)


def test_about_box_shows_the_version(qt_application):
    window = MainWindow()

    try:
        about_box = window.create_about_box()
        assert about_box.windowTitle() == f"About {APP_NAME}"
        assert about_box.text() == APP_NAME
        assert about_box.informativeText() == f"Version {APP_VERSION}"
    finally:
        close_window(window)


def test_help_shows_the_help_file(qt_application, monkeypatch):
    window = MainWindow()
    shown = {}

    def remember_dialog(dialog):
        shown["title"] = dialog.windowTitle()
        shown["text"] = dialog.help_text_edit.toPlainText()
        return QDialog.Accepted

    monkeypatch.setattr(HelpDialog, "exec_", remember_dialog)

    try:
        window.help_action.trigger()
        assert shown["title"] == "Circuit Workbench Help"
        assert shown["text"] == read_help_text()
        assert "filled in later" in shown["text"]
    finally:
        close_window(window)


def test_a_missing_help_file_says_what_to_restore(
        qt_application, monkeypatch, tmp_path):
    window = MainWindow()
    shown = {}

    def remember_error(message_box):
        shown["title"] = message_box.windowTitle()
        shown["text"] = message_box.text()
        shown["detail"] = message_box.informativeText()
        return QMessageBox.Ok

    monkeypatch.setattr(
        "gui.help_dialog.help_file_path",
        lambda: tmp_path / "missing-help.txt"
    )
    monkeypatch.setattr(QMessageBox, "exec_", remember_error)

    try:
        window.show_help()
        assert shown["title"] == "Help"
        assert shown["text"] == "The help file could not be opened."
        assert "docs/help.txt" in shown["detail"]
    finally:
        close_window(window)
