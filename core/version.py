"""
Circuit Workbench version and copyright.

About reads APP_VERSION and COPYRIGHT_NOTICE. This is the only copy
of the version number. Each merge to main after 0.1.0 adds 1 to the
last number here (0.1.0 becomes 0.1.1) and in the test that checks it.

COPYRIGHT_NOTICE is the short line. The full statement is LICENSE.txt.
"""

APP_NAME = "Circuit Workbench"
APP_VERSION = "0.1.36"
COPYRIGHT_NOTICE = "Copyright (c) 2026 Billie Kennedy. All rights reserved."
PROGRAM_LICENSE = "All rights reserved"


def about_text():
    """
    Version and copyright lines shown by Help > About.

    The copyright sentence is two lines so the About box does not
    wrap it through the name.

    :rtype: str
    """
    return (
        f"Version {APP_VERSION}\n"
        "Copyright (c) 2026 Billie Kennedy.\n"
        "All rights reserved."
    )
