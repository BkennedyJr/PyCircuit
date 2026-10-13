"""
How the wheel zooms a plot.

The wheel on the trace zooms both axes. The wheel on the bottom
numbers zooms only that axis. The wheel on the left numbers zooms
only that axis. pyqtgraph does the zoom; this text tells the user.
"""

ZOOM_TIP = (
    "Wheel on the trace zooms both axes. "
    "Wheel on the bottom numbers zooms that axis only. "
    "Wheel on the left numbers zooms that axis only."
)


def show_zoom_tip(plot):
    """
    Say how the wheel zooms this plot.

    :param plot: A pyqtgraph plot widget.
    :returns: None
    """
    plot.setToolTip(ZOOM_TIP)

    for name in ("bottom", "left"):
        plot.plotItem.getAxis(name).setToolTip(ZOOM_TIP)
