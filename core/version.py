"""
Circuit Workbench version.

About reads APP_VERSION. This is the only copy of the number.
Each merge to main after 0.1.0 adds 1 to the last number here
(0.1.0 becomes 0.1.1) and in the test that checks it.
"""

APP_NAME = "Circuit Workbench"
APP_VERSION = "0.1.24"


def about_text():
    """
    Version line shown by Help > About.

    :rtype: str
    """
    return f"Version {APP_VERSION}"
