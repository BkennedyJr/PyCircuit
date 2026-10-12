"""
Snapshot or Continuous, shared by the oscilloscope, Bode, and FFT.

Snapshot keeps one reading. Continuous runs it again when a value
changes. The window owns the choice. These boxes only show it.
"""

from PyQt5.QtWidgets import QComboBox

UPDATE_MODE_TOOLTIP = (
    "Snapshot keeps one reading. A new value clears the DC numbers "
    "and the plots. Continuous runs them again when a value changes."
)


def update_mode_combo():
    """
    A Snapshot / Continuous box. Continuous is the usual choice.

    :rtype: QComboBox
    """
    combo = QComboBox()
    combo.addItem("Snapshot")
    combo.addItem("Continuous")
    combo.setCurrentIndex(1)
    combo.setToolTip(UPDATE_MODE_TOOLTIP)
    return combo
