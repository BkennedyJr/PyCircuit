"""
Tests for gui.component_item (Step 6). Runs headless through the
qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
)

from core.components import COMPONENT_DEFINITIONS, Component
from core.exceptions import ComponentError
from gui.component_item import (
    BACKGROUND_COLOR,
    LABEL_GAP,
    LABEL_PATCH_PADDING,
    MIN_LABEL_GAP,
    SELECTED_COLOR,
    SYMBOL_COLOR,
    ComponentItem,
    choose_label_side,
    fit_between_rows,
    free_label_sides,
    pin_direction,
    snap_between_rows,
    text_touches_a_grid_dot,
)

SPACING = 60


@pytest.fixture(autouse=True)
def use_qt(qt_application):
    return qt_application


def make_item(kind, rotation=0, value_text=None, reference=None):
    definition = COMPONENT_DEFINITIONS[kind]

    if value_text is None:
        value_text = definition["default_value_text"]

    if reference is None:
        reference = definition["prefix"] + "1"

    component = Component(kind, reference, value_text, 4, 4, rotation)

    return ComponentItem(component, SPACING)


def label_text_rect_in_item(item):
    label = item.label_item

    return label.mapRectToParent(label.text_rect())


def subpath_end_points(path):
    end_points = set()

    for polygon in path.toSubpathPolygons():
        for point in (polygon[0], polygon[polygon.count() - 1]):
            end_points.add((round(point.x(), 6) + 0.0, round(point.y(), 6) + 0.0))

    return end_points


# Plan test (components-plan Step 6).
def test_plan_resistor_example():
    component = Component("resistor", "R1", "4k7", 4, 4, 90)
    item = ComponentItem(component, 60)

    assert item.label_item.text() == "R1 4k7"
    assert item.boundingRect().contains(QPointF(0, -60))
    assert item.boundingRect().contains(QPointF(0, 60))
    assert not item.shape().boundingRect().contains(QPointF(0, -60))

    component.rotation = 0
    item.refresh_from_component()

    assert item.boundingRect().contains(QPointF(-60, 0))
    assert item.boundingRect().contains(QPointF(60, 0))


def test_paths_are_scaled_to_pixels():
    item = make_item("resistor")

    # Pitch-unit extents (-1, -0.2, 2, 0.4) times 60 px.
    stroke_rect = item.stroke_path.boundingRect()
    assert (stroke_rect.x(), stroke_rect.y(), stroke_rect.width(),
            stroke_rect.height()) == pytest.approx((-60, -12, 120, 24), abs=1e-9)

    # Body (-0.65, -0.25, 1.3, 0.5) times 60 px, and a 3 px margin outside.
    body_rect = item.body_path.boundingRect()
    assert (body_rect.x(), body_rect.y(), body_rect.width(),
            body_rect.height()) == pytest.approx((-39, -15, 78, 30), abs=1e-9)
    bounding_rect = item.boundingRect()
    assert (bounding_rect.x(), bounding_rect.y(), bounding_rect.width(),
            bounding_rect.height()) == pytest.approx((-63, -18, 126, 36), abs=1e-9)


def test_other_grid_spacing_scales_the_drawing():
    component = Component("resistor", "R1", "1k", 4, 4, 0)
    item = ComponentItem(component, 40.0)

    assert item.stroke_path.boundingRect().width() == pytest.approx(80.0)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("kind", list(COMPONENT_DEFINITIONS))
def test_leads_end_on_the_model_pins_at_every_rotation(kind, rotation):
    item = make_item(kind, rotation)
    end_points = subpath_end_points(item.stroke_path)

    for unused_name, dx, dy in item.component.get_pin_offsets():
        assert (float(dx * SPACING), float(dy * SPACING)) in end_points


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_item_itself_is_never_rotated_so_the_label_stays_upright(rotation):
    item = make_item("npn", rotation)

    assert item.rotation() == 0
    assert item.transform().isIdentity()
    assert item.label_item.rotation() == 0
    assert item.label_item.transform().isIdentity()


@pytest.mark.parametrize(
    "dx, dy, expected",
    [
        (0, -1, "above"), (1, 0, "right"), (0, 1, "below"), (-1, 0, "left"),
        (1, -1, "above"), (-1, 1, "below"), (2, 1, "right"), (0, 0, None),
    ]
)
def test_pin_direction(dx, dy, expected):
    assert pin_direction(dx, dy) == expected


def test_choose_label_side_falls_back_to_above_when_every_side_has_a_pin():
    pins = [("a", 0, -1), ("b", 1, 0), ("c", 0, 1), ("d", -1, 0)]

    assert choose_label_side(pins) == "above"


@pytest.mark.parametrize(
    "kind, rotation, expected_side",
    [
        ("resistor", 0, "above"),
        ("resistor", 90, "right"),
        ("capacitor", 0, "above"),        # not on the right lead (old rule)
        ("voltage_source", 0, "right"),
        ("voltage_source", 90, "above"),
        # NPN pins after rotation: 0 -> left, up, down; 90 -> up, right,
        # left; 180 -> right, down, up; 270 -> down, left, right.
        ("npn", 0, "right"),
        ("npn", 90, "below"),
        ("npn", 180, "left"),
        ("npn", 270, "above"),
        # Above is free, but the LED arrows push an above label onto the
        # row of dots; right has the cathode pin; below fits between rows.
        ("led", 0, "below"),
    ]
)
def test_label_goes_on_the_first_side_without_a_pin(kind, rotation, expected_side):
    item = make_item(kind, rotation)

    assert item.label_side == expected_side


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("kind", list(COMPONENT_DEFINITIONS))
def test_label_position_rules(kind, rotation):
    item = make_item(kind, rotation)

    if not item.label_item.isVisible():
        return

    body = item.body_path.boundingRect()
    text = label_text_rect_in_item(item)

    if item.label_side in ("above", "below"):
        # Centered on the body, 2..6 px from it.
        assert text.center().x() == pytest.approx(body.center().x())
        if item.label_side == "above":
            gap = body.top() - text.bottom()
        else:
            gap = text.top() - body.bottom()
        assert MIN_LABEL_GAP - 1e-9 <= gap <= LABEL_GAP + 1e-9
    else:
        # 6 px from the body, centered on a gap between rows (an odd
        # multiple of half a step from the anchor).
        if item.label_side == "right":
            assert text.left() == pytest.approx(body.right() + LABEL_GAP)
        else:
            assert text.right() == pytest.approx(body.left() - LABEL_GAP)
        assert (text.center().y() / (SPACING / 2)) % 2 == pytest.approx(1)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("kind", list(COMPONENT_DEFINITIONS))
def test_label_text_stays_off_grid_dots_and_its_own_body(kind, rotation):
    item = make_item(kind, rotation)
    text = label_text_rect_in_item(item)

    assert not text_touches_a_grid_dot(text, SPACING)
    assert not text.intersects(item.body_path.boundingRect())


@pytest.mark.parametrize(
    "center_y, expected",
    [(0, -30), (1.5, 30), (-1.5, -30), (-28.5, -30), (44, 30), (60, 30),
     (61, 90), (-89, -90)]
)
def test_snap_between_rows(center_y, expected):
    assert snap_between_rows(center_y, 60) == expected


@pytest.mark.parametrize(
    "center_y, low, high, expected",
    [
        # Already clear of the dots (band -51..-9 for a 21 px text).
        (-30, None, None, -30),
        # Top would be at -54: pushed down to -40.5 (top on -51).
        (-43.5, None, None, -40.5),
        # Same, but the body allows no lower than -42: not moved.
        (-43.5, None, -42, -43.5),
        # Below the body: pushed up so the bottom is on +51.
        (43.5, None, None, 40.5),
        (43.5, 42, None, 43.5),
    ]
)
def test_fit_between_rows(center_y, low, high, expected):
    assert fit_between_rows(center_y, 21, 60, low=low, high=high) == expected


def test_fit_between_rows_leaves_text_taller_than_the_gap():
    assert fit_between_rows(-30, 50, 60) == -30


@pytest.mark.parametrize(
    "rect, expected",
    [
        (QRectF(10, -50, 40, 40), False),     # inside one cell
        (QRectF(10, -50, 60, 45), True),      # reaches the dot at (60, 0)
        (QRectF(-200, -51, 400, 42), False),  # long, between rows
        (QRectF(-15, -5, 10, 10), True),      # on the anchor dot
        (QRectF(9, -51, 42, 42), False),      # touching edges only
    ]
)
def test_text_touches_a_grid_dot(rect, expected):
    assert text_touches_a_grid_dot(rect, 60) == expected


def test_free_label_sides_order_and_fallback():
    assert free_label_sides([("1", -1, 0), ("2", 1, 0)]) == ["above", "below"]
    assert free_label_sides(
        [("a", 0, -1), ("b", 1, 0), ("c", 0, 1), ("d", -1, 0)]
    ) == ["above"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("kind", list(COMPONENT_DEFINITIONS))
def test_label_patch_never_covers_a_pin(kind, rotation):
    item = make_item(kind, rotation)
    label = item.label_item
    patch = label.mapRectToParent(label.boundingRect())

    for unused_name, dx, dy in item.component.get_pin_offsets():
        assert not patch.contains(QPointF(dx * SPACING, dy * SPACING))


def test_label_patch_is_the_text_plus_padding():
    item = make_item("resistor")   # keep the parent alive: it owns the label
    label = item.label_item
    text = label.text_rect()
    patch = label.boundingRect()

    assert patch == text.adjusted(
        -LABEL_PATCH_PADDING, -LABEL_PATCH_PADDING,
        LABEL_PATCH_PADDING, LABEL_PATCH_PADDING
    )


def test_ground_has_no_visible_label():
    item = make_item("ground")

    assert item.label_item.text() == ""
    assert not item.label_item.isVisible()


def test_click_area_is_only_the_body():
    item = make_item("resistor")
    shape = item.shape()

    assert shape.contains(QPointF(0, 0))
    assert not shape.contains(QPointF(-60, 0))
    assert not shape.contains(QPointF(60, 0))
    assert not shape.contains(label_text_rect_in_item(item).center())
    assert item.label_item.acceptedMouseButtons() == Qt.NoButton


def test_flags_and_z_value():
    item = make_item("resistor")

    assert item.flags() & QGraphicsItem.ItemIsSelectable
    assert not item.flags() & QGraphicsItem.ItemIsMovable
    assert item.zValue() == 1


def test_tool_tip_lists_kind_reference_value_and_pin_nodes():
    tool_tip = make_item("resistor", 90, "4k7").toolTip()

    # Anchor R4 C4 rotated 90: pin 1 at R3 C4, pin 2 at R5 C4.
    assert tool_tip.splitlines() == [
        "R1 (Resistor)",
        "Value: 4k7",
        "1: NODE_R03_C04",
        "2: NODE_R05_C04",
    ]


def test_ground_tool_tip_has_no_value_line():
    tool_tip = make_item("ground", reference="GND1").toolTip()

    assert "Value" not in tool_tip
    assert "gnd: NODE_R04_C04" in tool_tip


def test_refresh_repaints_the_item_in_the_scene(qt_application):
    # update() was removed after prepareGeometryChange(); check the scene
    # still gets a repaint of the changed area.
    scene = QGraphicsScene()
    item = make_item("resistor", 0)
    scene.addItem(item)
    qt_application.processEvents()

    changed_regions = []
    scene.changed.connect(changed_regions.extend)
    item.component.rotation = 90
    item.refresh_from_component()
    qt_application.processEvents()

    repainted = QRectF()
    for region in changed_regions:
        repainted = repainted.united(region)

    assert repainted.contains(item.mapRectToScene(item.boundingRect()))


def test_refresh_picks_up_value_and_rotation_changes():
    item = make_item("resistor", 0, "1k")
    item.component.set_value_text("2k2")
    item.component.rotation = 90
    item.refresh_from_component()

    assert item.label_item.text() == "R1 2k2"
    assert item.label_side == "right"
    assert "Value: 2k2" in item.toolTip()
    assert item.boundingRect().contains(QPointF(0, 60))


@pytest.mark.parametrize("component", [None, "resistor", 5, object()])
def test_non_component_raises_component_error(component):
    with pytest.raises(ComponentError):
        ComponentItem(component, SPACING)


@pytest.mark.parametrize(
    "spacing",
    [0, -60, True, "60", None, float("nan"), float("inf"), float("-inf")]
)
def test_bad_grid_spacing_raises_component_error(spacing):
    component = Component("resistor", "R1", "1k", 4, 4, 0)

    with pytest.raises(ComponentError):
        ComponentItem(component, spacing)


# --- Rendering and clicking in a real scene --------------------------------

def render_scene(scene, scene_rect):
    image = QImage(int(scene_rect.width()), int(scene_rect.height()),
                   QImage.Format_ARGB32)
    image.fill(QColor("#ff0000"))
    painter = QPainter(image)
    scene.render(painter, QRectF(image.rect()), scene_rect)
    painter.end()

    return image


def pixel_at(image, scene_rect, scene_point):
    return QColor(image.pixel(int(scene_point.x() - scene_rect.x()),
                              int(scene_point.y() - scene_rect.y()))).name()


def test_body_hides_what_is_underneath_and_selection_turns_yellow():
    scene = QGraphicsScene()
    scene_rect = QRectF(-100, -100, 200, 200)
    # A red "grid dot" under the capacitor's center, between the plates.
    red_dot = QGraphicsEllipseItem(-8, -8, 16, 16)
    red_dot.setBrush(QColor("#ff0000"))
    scene.addItem(red_dot)
    item = make_item("capacitor")
    scene.addItem(item)

    image = render_scene(scene, scene_rect)
    assert pixel_at(image, scene_rect, QPointF(0, 0)) == BACKGROUND_COLOR
    # A point on the left lead, halfway to the pin.
    assert pixel_at(image, scene_rect, QPointF(-30, 0)) == SYMBOL_COLOR

    item.setSelected(True)
    image = render_scene(scene, scene_rect)
    assert pixel_at(image, scene_rect, QPointF(-30, 0)) == SELECTED_COLOR


def test_label_patch_hides_what_is_behind_the_label():
    scene = QGraphicsScene()
    scene_rect = QRectF(-100, -100, 200, 200)
    # Stand-in for the guide lines, which the scene draws in its background
    # (below every item, including the label at z -0.5).
    red_block = scene.addRect(QRectF(-100, -100, 200, 200))
    red_block.setBrush(QColor("#ff0000"))
    red_block.setZValue(-1)
    item = make_item("resistor")
    scene.addItem(item)

    image = render_scene(scene, scene_rect)
    patch = item.label_item.mapRectToScene(item.label_item.boundingRect())
    # Just inside the patch corner: no glyph there, so it is the patch color.
    assert pixel_at(image, scene_rect, patch.topLeft() + QPointF(1, 1)) == (
        BACKGROUND_COLOR
    )


@pytest.fixture
def click_scene():
    """A part over selectable stand-in grid dots, shown in a view."""
    scene = QGraphicsScene(-200, -200, 400, 400)
    dots = {}

    for x in (-60, 0, 60):
        for y in (-60, 0, 60):
            dot = QGraphicsEllipseItem(-8, -8, 16, 16)
            dot.setFlag(QGraphicsItem.ItemIsSelectable, True)
            dot.setPos(x, y)
            scene.addItem(dot)
            dots[(x, y)] = dot

    item = make_item("resistor", 90)   # vertical, label on the right
    scene.addItem(item)

    view = QGraphicsView(scene)
    view.resize(500, 500)
    view.show()
    QTest.qWaitForWindowExposed(view)

    yield scene, view, item, dots

    view.close()


def click(view, scene_point):
    view_point = view.mapFromScene(scene_point)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                     QPoint(view_point.x(), view_point.y()))


def test_clicking_the_body_selects_the_part(click_scene):
    scene, view, item, _dots = click_scene
    click(view, QPointF(0, 20))

    assert scene.selectedItems() == [item]


def test_clicking_a_pin_selects_the_grid_point_not_the_part(click_scene):
    scene, view, _item, dots = click_scene
    click(view, QPointF(0, -60))

    assert scene.selectedItems() == [dots[(0, -60)]]


def test_clicking_the_label_does_not_select_the_part(click_scene):
    scene, view, item, _dots = click_scene
    label = item.label_item
    click(view, label.mapRectToScene(label.text_rect()).center())

    assert scene.selectedItems() == []


def test_clicking_a_label_over_a_grid_point_selects_the_point(click_scene):
    scene, view, item, dots = click_scene
    # Labels avoid the dots, so move this one over the (60, 0) dot.
    label = item.label_item
    label.setPos(QPointF(40, -10) - label.text_rect().topLeft())
    assert label.mapRectToScene(label.boundingRect()).contains(QPointF(60, 0))

    click(view, QPointF(60, 0))

    assert scene.selectedItems() == [dots[(60, 0)]]
