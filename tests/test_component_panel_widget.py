"""
Tests for gui.component_panel_widget (Step 8). Runs headless through the
qt_application fixture in tests/conftest.py.
"""

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

from core.components import COMPONENT_DEFINITIONS, Component
from core.exceptions import ComponentError
from gui.component_panel_widget import (
    NO_PART_SELECTED_TEXT,
    ComponentPanelWidget,
    describe_component,
)


@pytest.fixture
def panel(qt_application):
    return ComponentPanelWidget()


def select_kind(panel, kind):
    panel.kind_combo_box.setCurrentIndex(panel.kind_combo_box.findData(kind))


def recorder(signal):
    calls = []
    signal.connect(lambda *arguments: calls.append(arguments))
    return calls


# Plan tests.
def test_combo_lists_all_11_kinds_in_definition_order(panel):
    combo = panel.kind_combo_box

    assert combo.count() == len(COMPONENT_DEFINITIONS) == 11
    assert [combo.itemData(index) for index in range(combo.count())] == (
        list(COMPONENT_DEFINITIONS)
    )
    assert [combo.itemText(index) for index in range(combo.count())] == [
        definition["display_name"]
        for definition in COMPONENT_DEFINITIONS.values()
    ]


def test_selecting_capacitor_fills_100n(panel):
    select_kind(panel, "capacitor")

    assert panel.value_line_edit.text() == "100n"


def test_show_none_disables_rotate(panel):
    panel.show_component(None)

    assert not panel.rotate_button.isEnabled()


# More.
def test_starts_on_the_first_kind_with_its_default_and_no_selection(panel):
    first_kind = next(iter(COMPONENT_DEFINITIONS))

    assert panel.get_selected_kind() == first_kind
    assert panel.value_line_edit.text() == (
        COMPONENT_DEFINITIONS[first_kind]["default_value_text"]
    )
    assert panel.selected_component_label.text() == NO_PART_SELECTED_TEXT
    for button in (panel.rotate_button, panel.apply_value_button,
                   panel.delete_button):
        assert not button.isEnabled()
    assert panel.place_button.isEnabled()


@pytest.mark.parametrize("kind", list(COMPONENT_DEFINITIONS))
def test_every_kind_fills_its_default_value(panel, kind):
    select_kind(panel, kind)

    assert panel.value_line_edit.text() == (
        COMPONENT_DEFINITIONS[kind]["default_value_text"]
    )
    assert panel.value_line_edit.isEnabled() == (kind != "ground")


def test_ground_has_no_value_and_switching_back_re_enables(panel):
    select_kind(panel, "ground")
    assert panel.value_line_edit.text() == ""
    assert not panel.value_line_edit.isEnabled()

    select_kind(panel, "resistor")
    assert panel.value_line_edit.isEnabled()


def test_place_button_and_enter_emit_kind_and_typed_value(panel):
    calls = recorder(panel.place_requested)
    select_kind(panel, "resistor")
    panel.value_line_edit.setText("4k7")

    QTest.mouseClick(panel.place_button, Qt.LeftButton)
    QTest.keyClick(panel.value_line_edit, Qt.Key_Return)

    assert calls == [("resistor", "4k7", {}), ("resistor", "4k7", {})]


def test_place_ground_sends_an_empty_value(panel):
    calls = recorder(panel.place_requested)
    select_kind(panel, "ground")

    panel.place_button.click()

    assert calls == [("ground", "", {})]


def test_invalid_value_is_passed_on_unchanged(panel):
    # The panel never validates or rewrites; core reports the error.
    calls = recorder(panel.place_requested)
    panel.value_line_edit.setText(" 1M ")

    panel.place_button.click()

    assert calls[0][1] == " 1M "


def test_show_component_fills_the_selected_part_section(panel):
    component = Component("resistor", "R1", "4k7", 4, 4, 90)

    panel.show_component(component)

    assert panel.selected_component_label.text() == (
        "R1 (Resistor) at R4 C4, 90 deg"
    )
    assert panel.selected_value_line_edit.text() == "4k7"
    for widget in (panel.rotate_button, panel.apply_value_button,
                   panel.delete_button, panel.selected_value_line_edit):
        assert widget.isEnabled()


def test_showing_a_part_leaves_the_new_part_section_alone(panel):
    # Separate value boxes: selecting C1 must not change what Place uses.
    select_kind(panel, "resistor")
    panel.value_line_edit.setText("4k7")

    panel.show_component(Component("capacitor", "C1", "100n", 2, 2))

    assert panel.get_selected_kind() == "resistor"
    assert panel.value_line_edit.text() == "4k7"


def test_selected_ground_can_rotate_and_delete_but_not_take_a_value(panel):
    panel.show_component(Component("ground", "GND1", "", 3, 3))

    assert panel.rotate_button.isEnabled()
    assert panel.delete_button.isEnabled()
    assert not panel.apply_value_button.isEnabled()
    assert not panel.selected_value_line_edit.isEnabled()


def test_show_none_clears_everything_again(panel):
    panel.show_component(Component("resistor", "R1", "1k", 4, 4))
    panel.show_component(None)

    assert panel.selected_component_label.text() == NO_PART_SELECTED_TEXT
    assert panel.selected_value_line_edit.text() == ""
    for widget in (panel.rotate_button, panel.apply_value_button,
                   panel.delete_button, panel.selected_value_line_edit):
        assert not widget.isEnabled()


def test_selected_part_buttons_emit_requests(panel):
    rotations = recorder(panel.rotate_requested)
    deletions = recorder(panel.delete_requested)
    values = recorder(panel.value_change_requested)
    panel.show_component(Component("resistor", "R1", "1k", 4, 4))
    panel.selected_value_line_edit.setText("2k2")

    panel.rotate_button.click()
    panel.delete_button.click()
    panel.apply_value_button.click()
    QTest.keyClick(panel.selected_value_line_edit, Qt.Key_Return)

    assert rotations == [()]
    assert deletions == [()]
    assert values == [("2k2", {}), ("2k2", {})]


def test_enter_does_not_apply_a_value_without_a_part(panel):
    values = recorder(panel.value_change_requested)
    panel.selected_value_line_edit.setText("2k2")

    panel.emit_value_change_request()

    assert values == []


@pytest.mark.parametrize("bad", ["R1", 5, object()])
def test_show_component_rejects_non_components(panel, bad):
    with pytest.raises(ComponentError):
        panel.show_component(bad)


@pytest.mark.parametrize(
    "kind, reference, expected",
    [("capacitor_polarized", "C3",
      "C3 (Capacitor (polarized)) at R2 C5, 0 deg"),
     ("npn", "Q1", "Q1 (NPN transistor) at R2 C5, 0 deg"),
     ("ground", "GND2", "GND2 (Ground) at R2 C5, 0 deg")]
)
def test_describe_component_uses_the_display_name(kind, reference, expected):
    value_text = COMPONENT_DEFINITIONS[kind]["default_value_text"]
    component = Component(kind, reference, value_text, 2, 5)

    assert describe_component(component) == expected


# PR B: the AC source's Frequency row.
def frequency_row_hidden(panel):
    return (
        panel.parameter_labels["frequency"].isHidden(),
        panel.parameter_line_edits["frequency"].isHidden(),
    )


def selected_frequency_row_hidden(panel):
    return (
        panel.selected_parameter_labels["frequency"].isHidden(),
        panel.selected_parameter_line_edits["frequency"].isHidden(),
    )


def test_only_frequency_is_a_panel_setting(panel):
    assert list(panel.parameter_line_edits) == ["frequency"]
    assert list(panel.selected_parameter_line_edits) == ["frequency"]
    assert panel.parameter_labels["frequency"].text() == "Frequency (Hz):"


@pytest.mark.parametrize("kind", list(COMPONENT_DEFINITIONS))
def test_frequency_row_shows_only_for_the_ac_source(panel, kind):
    select_kind(panel, kind)

    is_ac = kind == "ac_source"
    assert frequency_row_hidden(panel) == (not is_ac, not is_ac)


def test_selecting_the_ac_source_fills_both_defaults(panel):
    select_kind(panel, "ac_source")

    assert panel.value_label.text() == "Peak amplitude (V):"
    assert panel.value_line_edit.text() == "1"
    assert panel.parameter_line_edits["frequency"].text() == "1k"


def test_value_label_follows_the_kind(panel):
    select_kind(panel, "dc_source")
    assert panel.value_label.text() == "Voltage (V):"
    assert panel.value_line_edit.text() == "5"

    select_kind(panel, "resistor")
    assert panel.value_label.text() == "Value:"


def test_placing_an_ac_source_sends_the_frequency(panel):
    calls = recorder(panel.place_requested)
    select_kind(panel, "ac_source")
    panel.value_line_edit.setText("2")
    panel.parameter_line_edits["frequency"].setText("50")

    panel.place_button.click()
    QTest.keyClick(panel.parameter_line_edits["frequency"], Qt.Key_Return)

    assert calls == [
        ("ac_source", "2", {"frequency": "50"}),
        ("ac_source", "2", {"frequency": "50"}),
    ]


def test_placing_a_dc_source_sends_no_settings(panel):
    calls = recorder(panel.place_requested)
    select_kind(panel, "ac_source")
    panel.parameter_line_edits["frequency"].setText("50")
    select_kind(panel, "dc_source")

    panel.place_button.click()

    assert calls == [("dc_source", "5", {})]


def test_selected_ac_source_shows_and_sends_its_frequency(panel):
    values = recorder(panel.value_change_requested)
    panel.show_component(
        Component("ac_source", "V2", "1", 4, 4, parameter_texts={
            "frequency": "60"
        })
    )

    assert selected_frequency_row_hidden(panel) == (False, False)
    assert panel.selected_value_label.text() == "Peak amplitude (V):"
    assert panel.selected_parameter_line_edits["frequency"].text() == "60"

    panel.selected_parameter_line_edits["frequency"].setText("400")
    panel.apply_value_button.click()
    QTest.keyClick(
        panel.selected_parameter_line_edits["frequency"], Qt.Key_Return
    )

    assert values == [("1", {"frequency": "400"}), ("1", {"frequency": "400"})]


@pytest.mark.parametrize("component", [
    None,
    Component("dc_source", "V1", "9", 4, 4),
    Component("resistor", "R1", "1k", 4, 4),
])
def test_selected_frequency_row_hides_for_other_parts(panel, component):
    panel.show_component(
        Component("ac_source", "V2", "1", 4, 4)
    )
    panel.show_component(component)

    assert selected_frequency_row_hidden(panel) == (True, True)
    assert panel.selected_parameter_line_edits["frequency"].text() == ""
