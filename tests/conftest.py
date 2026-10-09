"""
Shared pytest setup.

Qt tests run headless: the "offscreen" platform is selected before any
QApplication is created, so no display is needed (CI, the box, or a
Windows machine without opening windows).
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_application():
    """
    Return the single QApplication, creating it on first use.

    PyQt5 is imported here, not at module level, so pure-Python tests do
    not need Qt at all.
    """
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
