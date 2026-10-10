"""
Tests for PR F: the op-amp kinds in core.components and their triangle
symbol in gui.component_symbols / gui.component_item. The Qt tests use the
qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QTransform

from core.components import COMPONENT_DEFINITIONS, Component, ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.subcircuit_models import SUBCIRCUIT_MODELS
from gui.component_item import ComponentItem
from gui.component_symbols import (
    OPAMP_APEX_X,
    OPAMP_HALF_HEIGHT,
    OPAMP_LEFT_X,
    build_symbol_paths,
    get_body_path,
    opamp_edge_y,
)

OPAMP_KINDS = [
    "opamp_generic", "opamp_741", "opamp_lm358", "opamp_tl072",
    "opamp_ne5532", "comparator",
]
SPACING = 60
GRID_DOT_RADIUS_IN_PITCH = 8.0 / 60.0


@pytest.fixture
def grid():
    return ConnectionGrid(8, 8)


# ----- Core definitions --------------------------------------------------------


@pytest.mark.parametrize("kind, display_name, default", [
    ("opamp_generic", "Op-amp (generic)", "OPAMP"),
    ("opamp_741", "Op-amp (741)", "LM741"),
    ("opamp_lm358", "Op-amp (LM358)", "LM358"),
    ("opamp_tl072", "Op-amp (TL072)", "TL072"),
    ("opamp_ne5532", "Op-amp (NE5532)", "NE5532"),
    ("comparator", "Comparator", "COMP"),
])
def test_opamp_definitions(kind, display_name, default):
    definition = COMPONENT_DEFINITIONS[kind]

    assert definition["display_name"] == display_name
    assert definition["prefix"] == "X"
    assert [pin[0] for pin in definition["pins"]] == [
        "in+", "in-", "out", "V+", "V-"
    ]
    assert definition["default_value_text"] == default
    assert definition["label_ignores_pins"] == ("V+", "V-")


# Anchor (4, 4). Rotation turns clockwise on screen: (dx, dy) -> (-dy, dx).
@pytest.mark.parametrize("rotation, expected", [
    (0, ["NODE_R05_C03", "NODE_R03_C03", "NODE_R04_C05", "NODE_R03_C04",
         "NODE_R05_C04"]),
    (90, ["NODE_R03_C03", "NODE_R03_C05", "NODE_R05_C04", "NODE_R04_C05",
          "NODE_R04_C03"]),
    (180, ["NODE_R03_C05", "NODE_R05_C05", "NODE_R04_C03", "NODE_R05_C04",
           "NODE_R03_C04"]),
    (270, ["NODE_R05_C05", "NODE_R05_C03", "NODE_R03_C04", "NODE_R04_C03",
           "NODE_R04_C05"]),
])
@pytest.mark.parametrize("kind", OPAMP_KINDS)
def test_pins_land_on_grid_points_at_every_rotation(kind, rotation, expected):
    opamp = Component(
        kind, "X1", COMPONENT_DEFINITIONS[kind]["default_value_text"], 4, 4,
        rotation
    )

    assert opamp.get_pin_identifiers() == expected


def test_opamps_number_as_x_and_label_with_the_model(grid):
    collection = ComponentCollection()
    first = collection.add_component("opamp_generic", 3, 3, "", grid)
    second = collection.add_component("opamp_741", 3, 6, "", grid)

    assert (first.reference, second.reference) == ("X1", "X2")
    assert first.label_text() == "X1 OPAMP"
    assert second.label_text() == "X2 LM741"


def test_opamp_must_fit_the_grid(grid):
    collection = ComponentCollection()

    with pytest.raises(ComponentError):
        collection.add_component("opamp_generic", 1, 4, "", grid)

    assert collection.get_components() == []


@pytest.mark.parametrize("kind, row, column, rotation", [
    # A resistor between in- (3, 3) and V+ (3, 4) would cross the triangle.
    ("resistor", 3, 3, 0),
    # Anything on the anchor (inside the triangle).
    ("ground", 4, 4, 0),
    # A diode from the anchor to out.
    ("diode", 4, 4, 0),
    # A second op-amp on the same anchor, turned.
    ("opamp_741", 4, 4, 90),
    # Ground on V+ (3, 4): its bars would reach into the triangle.
    ("ground", 3, 4, 0),
])
def test_parts_drawn_over_the_triangle_are_refused(grid, kind, row, column,
                                                   rotation):
    collection = ComponentCollection()
    collection.add_component("opamp_generic", 4, 4, "", grid)
    value = COMPONENT_DEFINITIONS[kind]["default_value_text"]

    with pytest.raises(ComponentError, match=r"^X1 \(Op-amp \(generic\)\) "):
        collection.add_component(kind, row, column, value, grid, rotation)


@pytest.mark.parametrize("kind, row, column, rotation", [
    # Feedback resistor from out (4, 5) to the right.
    ("resistor", 4, 5, 0),
    # Input resistor ending on in- (3, 3) from the left.
    ("resistor", 3, 2, 0),
    # Ground on in+ (5, 3).
    ("ground", 5, 3, 0),
    # Supply source hanging off V+ (3, 4) upward: plus (2, 4), minus (3, 4).
    ("dc_source", 2, 4, 0),
])
def test_parts_that_only_share_a_pin_are_allowed(grid, kind, row, column,
                                                 rotation):
    collection = ComponentCollection()
    collection.add_component("opamp_generic", 4, 4, "", grid)
    value = COMPONENT_DEFINITIONS[kind]["default_value_text"]

    collection.add_component(kind, row, column, value, grid, rotation)

    assert len(collection.get_components()) == 2


# ----- Symbol ------------------------------------------------------------------


@pytest.fixture
def qt(qt_application):
    return qt_application


def test_triangle_constants_and_edge(qt):
    assert (OPAMP_LEFT_X, OPAMP_APEX_X, OPAMP_HALF_HEIGHT) == (-0.6, 0.75, 1.2)
    # 1.2 * 0.75 / 1.35
    assert opamp_edge_y(0.0) == pytest.approx(2.0 / 3.0)
    assert opamp_edge_y(OPAMP_LEFT_X) == pytest.approx(1.2)
    assert opamp_edge_y(OPAMP_APEX_X) == pytest.approx(0.0)


@pytest.mark.parametrize("kind", OPAMP_KINDS)
def test_symbol_extents_and_leads(qt, kind):
    stroke_path, fill_path = build_symbol_paths(kind)
    bounds = stroke_path.boundingRect()

    assert fill_path.isEmpty()
    # Leads reach x = -1 and 1; the triangle is 2.4 tall.
    assert (bounds.left(), bounds.top(), bounds.width(),
            bounds.height()) == pytest.approx((-1.0, -1.2, 2.0, 2.4))

    segments = {
        (round(p[0].x(), 6), round(p[0].y(), 6), round(p[1].x(), 6),
         round(p[1].y(), 6))
        for p in stroke_path.toSubpathPolygons() if p.count() == 2
    }
    supply = round(2.0 / 3.0, 6)
    assert (-1.0, -1.0, -0.6, -1.0) in segments   # in-
    assert (-1.0, 1.0, -0.6, 1.0) in segments     # in+
    assert (0.75, 0.0, 1.0, 0.0) in segments      # out
    assert (0.0, -1.0, 0.0, -supply) in segments  # V+
    assert (0.0, 1.0, 0.0, supply) in segments    # V-


def pin_dot(dx, dy):
    radius = GRID_DOT_RADIUS_IN_PITCH
    return QRectF(dx - radius, dy - radius, 2 * radius, 2 * radius)


@pytest.mark.parametrize("kind", OPAMP_KINDS)
def test_triangle_body_hides_the_anchor_dot_but_no_pin_dot(qt, kind):
    body = get_body_path(kind)

    assert body.contains(pin_dot(0, 0))

    for unused_name, dx, dy in COMPONENT_DEFINITIONS[kind]["pins"]:
        assert not body.intersects(pin_dot(dx, dy))

    # Neighbouring dots that are not pins stay clear as well.
    for dx, dy in [(-1, 0), (1, -1), (1, 1)]:
        assert not body.intersects(pin_dot(dx, dy))


def test_body_path_of_other_kinds_is_their_rect(qt):
    from gui.component_symbols import get_body_rect

    assert get_body_path("resistor").boundingRect() == get_body_rect(
        "resistor"
    )
    assert get_body_path("resistor").elementCount() == 5


def sign_segments_on_screen(kind, rotation):
    """Short (0.2 long) segments after the item's rotation, as drawn."""
    stroke_path = build_symbol_paths(kind, rotation)[0]
    to_screen = QTransform().rotate(rotation)
    segments = []

    for polygon in stroke_path.toSubpathPolygons():
        if polygon.count() != 2:
            continue
        start, end = to_screen.map(polygon[0]), to_screen.map(polygon[1])
        if abs((end - start).manhattanLength() - 0.2) < 1e-9:
            segments.append((start, end))

    return segments


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("kind", OPAMP_KINDS)
def test_input_marks_stay_upright_next_to_their_inputs(qt, kind, rotation):
    segments = sign_segments_on_screen(kind, rotation)
    horizontal = [s for s in segments if abs(s[0].y() - s[1].y()) < 1e-9]
    vertical = [s for s in segments if abs(s[0].x() - s[1].x()) < 1e-9]

    # "-" is one horizontal bar; "+" is a horizontal and a vertical bar.
    assert (len(horizontal), len(vertical)) == (2, 1)

    plus_center = (vertical[0][0] + vertical[0][1]) / 2
    minus_bar = [
        s for s in horizontal
        if (s[0] + s[1]) / 2 != plus_center
    ]
    assert len(minus_bar) == 1
    minus_center = (minus_bar[0][0] + minus_bar[0][1]) / 2

    to_screen = QTransform().rotate(rotation)
    in_plus = to_screen.map(QPointF(-1, 1))
    in_minus = to_screen.map(QPointF(-1, -1))

    # Each mark is nearer its own input than the other input.
    def distance(a, b):
        return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5

    assert distance(plus_center, in_plus) < distance(plus_center, in_minus)
    assert distance(minus_center, in_minus) < distance(minus_center, in_plus)


@pytest.mark.parametrize("rotation, side", [
    (0, "left"), (90, "right"), (180, "right"), (270, "right"),
])
@pytest.mark.parametrize("kind", OPAMP_KINDS)
def test_label_side_ignores_the_supply_pins(qt, kind, rotation, side):
    component = Component(
        kind, "X1", COMPONENT_DEFINITIONS[kind]["default_value_text"], 4, 4,
        rotation
    )
    item = ComponentItem(component, SPACING)

    assert item.label_side == side
    assert [pin[0] for pin in item.get_label_steering_pin_offsets()] == [
        "in+", "in-", "out"
    ]


def test_other_kinds_steer_the_label_with_every_pin(qt):
    component = Component("npn", "Q1", "2N3904", 4, 4)
    item = ComponentItem(component, SPACING)

    assert item.get_label_steering_pin_offsets() == component.get_pin_offsets()


@pytest.mark.parametrize("kind", OPAMP_KINDS)
def test_click_area_is_the_triangle(qt, kind):
    component = Component(
        kind, "X1", COMPONENT_DEFINITIONS[kind]["default_value_text"], 4, 4
    )
    item = ComponentItem(component, SPACING)

    assert item.shape().contains(QPointF(0, 0))
    # Inside the bounding box but outside the triangle (top-right corner).
    assert not item.shape().contains(QPointF(0.6 * SPACING, -0.6 * SPACING))


# ----- QC #16: model names are checked when they are set ---------------------


def test_opamp_value_must_be_a_known_model():
    with pytest.raises(ComponentError) as error:
        Component("opamp_generic", "X1", "LM324", 4, 4)

    assert str(error.value) == (
        "No subcircuit model named 'LM324'. Known models: "
        + ", ".join(SUBCIRCUIT_MODELS)
        + "."
    )


def test_opamp_value_must_match_the_kind():
    with pytest.raises(ComponentError) as error:
        Component("opamp_generic", "X1", "LM741", 4, 4)

    assert str(error.value) == (
        "Op-amp (generic) uses model OPAMP; for the LM741 choose the "
        "Op-amp (741) part."
    )

    with pytest.raises(ComponentError) as error:
        Component("opamp_741", "X1", "OPAMP", 4, 4)

    assert str(error.value) == (
        "Op-amp (741) uses model LM741; for the OPAMP choose the "
        "Op-amp (generic) part."
    )


def test_opamp_model_name_is_stored_in_library_spelling():
    opamp = Component("opamp_741", "X1", "lm741", 4, 4)

    assert opamp.value_text == "LM741"
    assert opamp.label_text() == "X1 LM741"


def test_refused_opamp_value_edit_keeps_the_old_value():
    collection = ComponentCollection()
    collection.add_component("opamp_generic", 4, 4, "", ConnectionGrid(8, 8))

    with pytest.raises(ComponentError):
        collection.set_component_value("X1", "LM324")

    assert collection.get_component("X1").value_text == "OPAMP"
