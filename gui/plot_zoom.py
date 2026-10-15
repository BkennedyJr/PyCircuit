"""
How a plot is zoomed.

Drag a box on the trace and the view becomes that box. The wheel on
the trace zooms both axes. The wheel on the bottom numbers zooms only
that axis. The wheel on the left numbers zooms only that axis.
pyqtgraph does the zoom; this text tells the user.
"""

import pyqtgraph as pg

ZOOM_TIP = (
    "Drag a box on the trace to zoom to that box. "
    "Wheel on the trace zooms both axes. "
    "Wheel on the bottom numbers zooms that axis only. "
    "Wheel on the left numbers zooms that axis only."
)


def show_zoom_tip(plot):
    """
    Turn on box zoom and say how the wheel zooms this plot.

    The left button draws the box. pyqtgraph then shows just that
    rectangle.

    :param plot: A pyqtgraph plot widget.
    :returns: None
    """
    plot.getViewBox().setMouseMode(pg.ViewBox.RectMode)
    plot.setToolTip(ZOOM_TIP)

    for name in ("bottom", "left"):
        plot.plotItem.getAxis(name).setToolTip(ZOOM_TIP)
