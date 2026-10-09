"""
Tests for the Step 7 scene integration in gui/grid_editor.py: component
items, refresh, component_selected, the growing sceneRect with headers kept
clear, and z-order (grid points above label patches, parts above both).
Runs headless through the qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QColor, QImage, QPainter

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from gui.component_item import (
    BACKGROUND_COLOR,
    COMPONENT_Z_VALUE,
    LABEL_DOT_CLEARANCE,
    LABEL_Z_VALUE,
    ComponentItem,
    ComponentLabelItem,
)
from gui.grid_editor import (
    CONNECTION_POINT_DIAMETER,
    CONNECTION_POINT_Z_VALUE,
    GRID_ORIGIN_X,
    GRID_ORIGIN_Y,
    HEADER_POSITION,
    SCENE_MARGIN,
    ConnectionGridScene,
    ConnectionPointItem,
    grid_point_to_scene_position,
)

DOT_FILL_COLOR = "#4f9ee3"
SELECTED_RING_COLOR = "#ffd166"


@pytest.fixture(autouse=True)
def use_qt(qt_application):
    return qt_application


def make_scene(row_count, column_count, parts):
    """parts: list of (kind, row, column, value_text, rotation)."""
    grid = ConnectionGrid(row_count, column_count)
    collection = ComponentCollection()

    for kind, row, column, value_text, rotation in parts:
        collection.add_component(kind, row, column, value_text, grid, rotation)

    scene = ConnectionGridScene(grid)
    scene.set_component_collection(collection)

    return grid, collection, scene


def items_of_type(scene, item_type):
    return [item for item in scene.items() if isinstance(item, item_type)]


def label_scene_rect(component_item):
    label = component_item.label_item

    return label.mapRectToScene(label.boundingRect())


def render(scene):
    scene_rect = scene.sceneRect()
    image = QImage(int(scene_rect.width()), int(scene_rect.height()),
                   QImage.Format_ARGB32)
    image.fill(QColor("#ff0000"))
    painter = QPainter(image)
    scene.render(painter, QRectF(image.rect()), scene_rect)
    painter.end()

    return image


def pixel(image, scene, scene_point):
    origin = scene.sceneRect().topLeft()

    return QColor(image.pixel(int(scene_point.x() - origin.x()),
                              int(scene_point.y() - origin.y()))).name()


# --- Plan test and basics --------------------------------------------------

def test_plan_example_survives_a_grid_rebuild():
    grid, _collection, scene = make_scene(
        8, 8, [("resistor", 4, 4, "4k7", 0)]
    )

    assert scene.component_items_by_reference["R1"].pos() == QPointF(270, 260)

    grid.configure(10, 10)
    scene.set_connection_grid(grid)

    item = scene.component_items_by_reference["R1"]
    assert item in scene.items()
    assert item.label_item in scene.items()


@pytest.mark.parametrize(
    "row, column, expected",
    [(1, 1, (90, 80)), (4, 4, (270, 260)), (2, 10, (630, 140))]
)
def test_grid_point_to_scene_position(row, column, expected):
    assert grid_point_to_scene_position(row, column) == QPointF(*expected)


def test_grid_point_position_matches_the_connection_point_items():
    _grid, _collection, scene = make_scene(5, 7, [])

    for item in items_of_type(scene, ConnectionPointItem):
        point = item.connection_point
        assert item.pos() == grid_point_to_scene_position(
            point.row_number, point.column_number
        )


def test_scene_without_a_collection_has_no_parts():
    scene = ConnectionGridScene(ConnectionGrid(4, 4))

    assert scene.component_collection is None
    assert scene.component_items_by_reference == {}
    assert items_of_type(scene, ComponentItem) == []


def test_every_part_gets_one_item_and_one_label():
    _grid, collection, scene = make_scene(
        8, 8,
        [("resistor", 2, 2, "1k", 0), ("capacitor", 4, 4, "100n", 90),
         ("ground", 6, 6, "", 0)]
    )

    assert sorted(scene.component_items_by_reference) == ["C1", "GND1", "R1"]
    assert len(items_of_type(scene, ComponentItem)) == 3
    assert len(items_of_type(scene, ComponentLabelItem)) == 3

    for reference, item in scene.component_items_by_reference.items():
        assert item.component is collection.get_component(reference)


def test_rebuild_and_collection_changes_leave_no_stale_items():
    grid, _collection, scene = make_scene(8, 8, [("resistor", 2, 2, "1k", 0)])

    # Rebuild twice through the grid, then once directly.
    scene.set_connection_grid(grid)
    scene.set_connection_grid(grid)
    scene.rebuild_component_items()
    assert len(items_of_type(scene, ComponentItem)) == 1
    assert len(items_of_type(scene, ComponentLabelItem)) == 1

    other = ComponentCollection()
    other.add_component("diode", 5, 5, "1N4148", grid)
    scene.set_component_collection(other)
    assert list(scene.component_items_by_reference) == ["D1"]
    assert len(items_of_type(scene, ComponentItem)) == 1
    assert len(items_of_type(scene, ComponentLabelItem)) == 1

    scene.set_component_collection(None)
    assert scene.component_items_by_reference == {}
    assert items_of_type(scene, ComponentItem) == []
    assert items_of_type(scene, ComponentLabelItem) == []


def test_parts_removed_after_a_shrink_disappear_on_rebuild():
    grid, collection, scene = make_scene(
        8, 8, [("resistor", 2, 2, "1k", 0), ("resistor", 7, 7, "1k", 0)]
    )

    grid.configure(5, 5)
    collection.remove_components_outside_grid(grid)
    scene.set_connection_grid(grid)

    assert list(scene.component_items_by_reference) == ["R1"]


def test_refresh_component_follows_rotation_and_value():
    grid, collection, scene = make_scene(8, 8, [("resistor", 4, 4, "1k", 0)])
    item = scene.component_items_by_reference["R1"]

    collection.rotate_component("R1", grid)
    collection.set_component_value("R1", "2k2")
    scene.refresh_component("R1")

    assert item.label_item.text() == "R1 2k2"
    assert item.label_side == "right"
    assert item.pos() == QPointF(270, 260)
    assert item.mapRectToScene(item.boundingRect()).contains(QPointF(270, 320))


def test_refresh_component_with_unknown_reference_does_nothing():
    _grid, _collection, scene = make_scene(4, 4, [])

    scene.refresh_component("R99")


def test_label_follows_its_part_and_leaves_with_it():
    _grid, _collection, scene = make_scene(
        8, 8, [("resistor", 4, 4, "1k", 0)]
    )
    item = scene.component_items_by_reference["R1"]
    label = item.label_item
    offset = label.pos() - item.pos()

    item.setPos(QPointF(390, 380))
    assert label.pos() == QPointF(390, 380) + offset

    scene.removeItem(item)
    assert label.scene() is None


# --- component_selected --------------------------------------------------------

def test_component_selected_reports_the_part_and_none():
    _grid, collection, scene = make_scene(
        8, 8, [("resistor", 4, 4, "1k", 0)]
    )
    parts = []
    points = []
    scene.component_selected.connect(parts.append)
    scene.connection_point_selected.connect(points.append)

    scene.component_items_by_reference["R1"].setSelected(True)
    assert parts[-1] is collection.get_component("R1")
    assert points[-1] is None

    scene.clearSelection()
    dot = scene.connection_point_items_by_identifier["NODE_R01_C01"]
    dot.setSelected(True)
    assert parts[-1] is None
    assert points[-1] is dot.connection_point


# --- (a) sceneRect grows; headers stay clear ----------------------------------

STEP6_LAYOUT = [
    ("voltage_source", 4, 2, "5", 0), ("resistor", 3, 3, "330", 0),
    ("led", 3, 5, "LED_RED", 0), ("resistor", 4, 6, "1k", 90),
    ("ground", 5, 2, "", 0), ("ground", 5, 6, "", 0),
    ("capacitor_polarized", 4, 8, "10u", 270), ("npn", 4, 11, "2N3904", 0),
    ("capacitor", 7, 2, "100n", 90), ("inductor", 7, 5, "10u", 0),
    ("current_source", 7, 8, "1m", 90), ("pnp", 7, 11, "2N3906", 180),
    ("diode", 9, 4, "1N4148", 180), ("npn", 9, 8, "2N3904", 90),
]

EDGE_PARTS = [
    # QC's case: labels 41 px left of and 31 px right of the old sceneRect.
    ("npn", 2, 1, "2N3904", 180),
    ("npn", 2, 8, "2N3904", 0),
    # Row 1 label above, next to the column headers.
    ("resistor", 1, 4, "4k7", 0),
    # Long label on the right edge.
    ("led", 5, 8, "LED_RED", 90),
]


def test_edge_labels_fit_inside_the_scene_rect_with_margin():
    _grid, _collection, scene = make_scene(6, 8, EDGE_PARTS)
    reachable = scene.sceneRect().adjusted(
        SCENE_MARGIN - 1, SCENE_MARGIN - 1, 1 - SCENE_MARGIN, 1 - SCENE_MARGIN
    )

    for item in scene.component_items_by_reference.values():
        assert reachable.contains(label_scene_rect(item))
        assert reachable.contains(item.mapRectToScene(item.boundingRect()))


def test_headers_never_overlap_parts_or_labels():
    _grid, _collection, scene = make_scene(6, 8, EDGE_PARTS)
    components_rect = scene.get_components_rect()

    for header in scene.column_header_items + scene.row_header_items:
        header_rect = header.mapRectToScene(header.boundingRect())
        for item in scene.component_items_by_reference.values():
            assert not header_rect.intersects(label_scene_rect(item))
            assert not header_rect.intersects(
                item.mapRectToScene(item.boundingRect())
            )

    # The headers moved out (left and up) only as far as needed.
    assert components_rect.left() < 0
    assert all(header.x() < HEADER_POSITION for header in scene.row_header_items)
    assert all(header.y() < HEADER_POSITION
               for header in scene.column_header_items)


def test_headers_and_scene_rect_return_to_default_without_edge_parts():
    _grid, _collection, scene = make_scene(6, 8, EDGE_PARTS)
    scene.set_component_collection(None)

    assert all(header.x() == HEADER_POSITION for header in scene.row_header_items)
    assert all(header.y() == HEADER_POSITION
               for header in scene.column_header_items)
    # The default from rebuild_connection_point_items: grid plus 100 px.
    assert scene.sceneRect() == QRectF(
        0, 0,
        GRID_ORIGIN_X + 7 * 60 + 100,
        GRID_ORIGIN_Y + 5 * 60 + 100,
    )


def test_scene_rect_grows_when_a_refresh_moves_a_label_out():
    grid, collection, scene = make_scene(6, 8, [("npn", 2, 2, "2N3904", 0)])
    left_before = scene.sceneRect().left()

    # Rotate twice to 180: the label moves to the left side.
    collection.rotate_component("Q1", grid)
    collection.rotate_component("Q1", grid)
    scene.refresh_component("Q1")

    item = scene.component_items_by_reference["Q1"]
    assert item.label_side == "left"
    assert scene.sceneRect().contains(label_scene_rect(item))
    assert scene.sceneRect().left() <= left_before


# --- (b) z-order: grid points above label patches -------------------------------

def test_z_order_is_label_then_points_then_parts():
    assert LABEL_Z_VALUE < CONNECTION_POINT_Z_VALUE < COMPONENT_Z_VALUE

    _grid, _collection, scene = make_scene(
        8, 8, [("resistor", 4, 4, "1k", 90)]
    )
    item = scene.component_items_by_reference["R1"]
    dot = scene.connection_point_items_by_identifier["NODE_R04_C05"]

    assert item.label_item.zValue() == LABEL_Z_VALUE
    assert item.label_item.parentItem() is None
    assert dot.zValue() == CONNECTION_POINT_Z_VALUE
    assert item.zValue() == COMPONENT_Z_VALUE


def move_label_over(component_item, scene_point):
    """Put the label's text so it covers scene_point (labels avoid dots
    on their own, so the z-order tests force the overlap)."""
    label = component_item.label_item
    text_rect = label.text_rect()
    label.setPos(scene_point - QPointF(10, text_rect.height() / 2)
                 - text_rect.topLeft())
    assert label.mapRectToScene(text_rect).contains(scene_point)


def test_selected_point_under_a_label_stays_visible():
    _grid, _collection, scene = make_scene(
        8, 8, [("resistor", 4, 4, "1k", 90)]
    )
    item = scene.component_items_by_reference["R1"]
    dot = scene.connection_point_items_by_identifier["NODE_R04_C05"]
    dot_center = dot.scenePos()
    move_label_over(item, dot_center)

    dot.setSelected(True)
    image = render(scene)

    assert pixel(image, scene, dot_center) == DOT_FILL_COLOR
    # The selection ring (3 px pen on the 8 px radius).
    assert pixel(image, scene, dot_center + QPointF(0, -8)) == (
        SELECTED_RING_COLOR
    )


def test_label_never_hides_another_parts_pin():
    # From the Step 6 preview: Q2's label (left side) covered I1's "out"
    # pin at R7 C9.
    _grid, _collection, scene = make_scene(
        10, 12,
        [("current_source", 7, 8, "1m", 90), ("pnp", 7, 11, "2N3906", 180)]
    )
    q2 = scene.component_items_by_reference["Q1"]
    pin_center = grid_point_to_scene_position(7, 9)

    # The label now sits between rows, clear of the pin...
    label = q2.label_item
    assert not label.mapRectToScene(label.text_rect()).contains(pin_center)
    # ...and even when forced over it, the pin's dot draws on top.
    move_label_over(q2, pin_center)
    image = render(scene)

    # Just below I1's lead, inside the dot: the dot shows, not the patch.
    assert pixel(image, scene, pin_center + QPointF(0, 5)) == DOT_FILL_COLOR


def test_label_dot_clearance_matches_the_grid_dot_size():
    # component_item cannot import grid_editor, so the size is repeated.
    assert LABEL_DOT_CLEARANCE == CONNECTION_POINT_DIAMETER / 2 + 1


def test_no_label_text_covers_any_grid_point_in_the_preview_layout():
    _grid, _collection, scene = make_scene(10, 12, STEP6_LAYOUT)
    dot_rects = [
        dot.mapRectToScene(dot.boundingRect())
        for dot in scene.connection_point_items_by_identifier.values()
    ]

    for item in scene.component_items_by_reference.values():
        label = item.label_item
        if not label.isVisible():
            continue
        text = label.mapRectToScene(label.text_rect())
        assert not any(text.intersects(dot_rect) for dot_rect in dot_rects)


def test_part_body_still_hides_the_dot_under_its_center():
    _grid, _collection, scene = make_scene(
        8, 8, [("capacitor", 4, 4, "100n", 0)]
    )
    image = render(scene)

    # Between the plates, at the R4 C4 point.
    assert pixel(image, scene, grid_point_to_scene_position(4, 4)) == (
        BACKGROUND_COLOR
    )


def test_label_patch_still_hides_the_guide_lines_behind_the_text():
    _grid, _collection, scene = make_scene(
        8, 8, [("resistor", 4, 4, "1k", 90)]
    )
    item = scene.component_items_by_reference["R1"]
    patch = label_scene_rect(item)
    image = render(scene)

    # The C5 guide line (x = 330) crosses the label, which sits between
    # rows R3 and R4. Sample it in the patch's top padding (no glyph).
    column_x = GRID_ORIGIN_X + 4 * 60
    guide_point = QPointF(column_x, patch.top() + 1)
    assert patch.contains(guide_point)
    assert pixel(image, scene, guide_point) == BACKGROUND_COLOR

    # Control: the same line just above the patch is drawn.
    assert pixel(image, scene, QPointF(column_x, patch.top() - 4)) != (
        BACKGROUND_COLOR
    )
