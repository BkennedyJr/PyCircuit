"""
Helpers that drive a QGraphicsView with real mouse events in tests.

QTest.mouseMove cannot carry a held button in PyQt5, so moves are sent as
QMouseEvents straight to the viewport, with explicit screen positions (the
item's drag check uses them).
"""

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication


def send_mouse(view, event_type, scene_position, button=Qt.LeftButton,
               buttons=Qt.LeftButton, modifiers=Qt.NoModifier):
    """
    Send one mouse event to the view's viewport at a scene position.

    :returns: The viewport position used.
    :rtype: QPoint
    """
    viewport = view.viewport()
    local_position = view.mapFromScene(scene_position)
    screen_position = viewport.mapToGlobal(local_position)
    event = QMouseEvent(
        event_type,
        QPointF(local_position),
        QPointF(local_position),
        QPointF(screen_position),
        button,
        buttons,
        modifiers,
    )
    QApplication.sendEvent(viewport, event)
    return local_position


def drag(view, start, end, steps=5, button=Qt.LeftButton,
         modifiers=Qt.NoModifier):
    """
    Press at start, move in steps to end, and release, in scene positions.
    """
    send_mouse(view, QEvent.MouseButtonPress, start, button, button,
               modifiers)

    for step in range(1, steps + 1):
        fraction = step / steps
        position = start + (end - start) * fraction
        send_mouse(view, QEvent.MouseMove, position, Qt.NoButton, button,
                   modifiers)

    send_mouse(view, QEvent.MouseButtonRelease, end, button, Qt.NoButton,
               modifiers)


def click(view, position, button=Qt.LeftButton, modifiers=Qt.NoModifier):
    """
    Press and release at one scene position.
    """
    send_mouse(view, QEvent.MouseButtonPress, position, button, button,
               modifiers)
    send_mouse(view, QEvent.MouseButtonRelease, position, button,
               Qt.NoButton, modifiers)


def viewport_point(view, scene_position):
    """
    Return the viewport pixel of a scene position.

    :rtype: QPoint
    """
    return QPoint(view.mapFromScene(scene_position))
