"""
Circuit Workbench version.

About reads APP_VERSION. Change the number here and nowhere else.
"""

APP_NAME = "Circuit Workbench"
APP_VERSION = "0.1.0"


def about_text():
    """
    Version line shown by Help > About.

    :rtype: str
    """
    return f"Version {APP_VERSION}"
