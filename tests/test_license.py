"""
The program license keeps every right with Billie Kennedy.

The Logipipe LM741 file stays under its own CC BY 4.0 licence.
"""

from pathlib import Path

from core.version import COPYRIGHT_NOTICE

ROOT = Path(__file__).resolve().parents[1]
LICENSE_PATH = ROOT / "LICENSE.txt"


def test_license_file_reserves_all_rights():
    text = LICENSE_PATH.read_text(encoding="utf-8")
    assert COPYRIGHT_NOTICE in text
    assert "not an open-source license" in text
    assert "No right is given unless Billie Kennedy agrees" in text
    assert "Permission is hereby granted" not in text
    assert "MIT License" not in text
    assert "GNU General Public License" not in text


def test_license_file_leaves_the_logipipe_model_under_cc_by():
    text = LICENSE_PATH.read_text(encoding="utf-8")
    assert "core/spice_library/LM741_logipipe.lib" in text
    assert "Copyright (c) 2018-2020 Logipipe, LLC" in text
    assert "CC BY 4.0" in text
    assert "https://creativecommons.org/licenses/by/4.0/" in text


def test_help_text_states_the_copyright():
    help_text = (ROOT / "docs" / "help.txt").read_text(encoding="utf-8")
    assert COPYRIGHT_NOTICE in help_text
