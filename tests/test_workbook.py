"""
Save and load keep the whole circuit. Print draws that circuit to a page.
"""

import json

import pytest
from PyQt5.QtGui import QKeySequence
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtWidgets import QFileDialog

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ProjectFileError
from core.probes import ProbeCollection
from core.project_io import load_project_file, save_project_file
from core.wires import WireCollection
from gui.main_window import MainWindow


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def sample_circuit():
    grid = ConnectionGrid(8, 8)
    grid.set_net_label(point(2, 2), "Vcc")
    parts = ComponentCollection()
    resistor = parts.add_component("resistor", 2, 2, "10k", grid, 90)
    parts.add_component(
        "ac_source", 4, 2, "1", grid,
        parameter_texts={"frequency": "2k"}
    )
    wires = WireCollection()
    wires.add_wire(
        point(3, 2), point(3, 6), grid, (point(3, 4),)
    )
    probes = ProbeCollection()
    voltage = probes.add_voltage(point(3, 2), grid)
    probes.set_method(voltage.reference, "differential")
    probes.set_second_point(voltage.reference, point(4, 2), grid)
    probes.add_current(resistor)

    return grid, parts, wires, probes, voltage


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def test_a_saved_circuit_loads_with_the_same_parts_wires_and_probes(tmp_path):
    grid, parts, wires, probes, voltage = sample_circuit()
    path = tmp_path / "circuit.json"
    save_project_file(path, grid, parts, wires, probes)
    loaded = load_project_file(path)

    assert loaded.connection_grid.get_connection_point(
        point(2, 2)
    ).net_label == "Vcc"
    resistor = loaded.component_collection.get_component("R1")
    assert resistor.value_text == "10k"
    assert resistor.rotation == 90
    source = loaded.component_collection.get_component("V1")
    assert source.parameter_texts["frequency"] == "2k"
    assert source.parameter_values["frequency"] == 2000
    wire = loaded.wire_collection.get_wires()[0]
    assert wire.reference == "W1"
    assert wire.bridged_identifiers == (point(3, 4),)
    restored = loaded.probe_collection.get("P1")
    assert restored.method == "differential"
    assert restored.identifier == point(3, 2)
    assert restored.second_identifier == point(4, 2)
    assert restored.color == voltage.color
    current = loaded.probe_collection.get("P2")
    assert current.method == "current"
    assert current.component_reference == "R1"


def test_an_old_grid_only_file_opens_with_no_parts(tmp_path):
    grid = ConnectionGrid(6, 4)
    path = tmp_path / "old.json"
    path.write_text(json.dumps({
        "format": "circuit_workbench_project",
        "format_version": 1,
        "connection_grid": grid.to_dict(),
    }), encoding="utf-8")
    loaded = load_project_file(path)

    assert loaded.connection_grid.row_count == 6
    assert loaded.connection_grid.column_count == 4
    assert loaded.component_collection.get_components() == []
    assert loaded.wire_collection.get_wires() == []
    assert loaded.probe_collection.get_probes() == []


def test_a_part_off_the_grid_is_refused_and_nothing_is_returned(tmp_path):
    grid, parts, wires, probes, _voltage = sample_circuit()
    path = tmp_path / "bad.json"
    save_project_file(path, grid, parts, wires, probes)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["components"][0]["row"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ProjectFileError, match="invalid circuit"):
        load_project_file(path)


def test_the_window_saves_and_opens_the_circuit(qt_application, tmp_path):
    window = MainWindow()

    try:
        grid, parts, wires, probes, _voltage = sample_circuit()
        window.connection_grid = grid
        window.component_collection = parts
        window.wire_collection = wires
        window.probe_collection = probes
        window.connection_grid_scene.component_collection = parts
        window.connection_grid_scene.wire_collection = wires
        window.connection_grid_scene.probe_collection = probes
        window.connection_grid_scene.set_connection_grid(grid)
        window.refresh_probe_parameters()
        path = tmp_path / "circuit.json"
        assert window.save_project_to_path(path) is True
        window.create_new_project()
        assert window.component_collection.get_components() == []
        window.show_workbook(load_project_file(path))

        assert window.component_collection.get_component("R1").value_text == (
            "10k"
        )
        assert window.wire_collection.get_wires()[0].bridged_identifiers == (
            point(3, 4),
        )
        assert window.probe_collection.get("P1").method == "differential"
        assert "R1" in window.connection_grid_scene.component_items_by_reference
        assert any(
            item.probe.reference == "P2"
            for item in window.connection_grid_scene.probe_items
        )
        assert window.connection_grid.get_connection_point(
            point(2, 2)
        ).net_label == "Vcc"
    finally:
        close_window(window)


def test_a_bad_file_leaves_the_open_circuit_alone(qt_application, tmp_path,
                                                  monkeypatch):
    window = MainWindow()
    window.recorded_errors = []
    monkeypatch.setattr(
        window,
        "show_error_message",
        lambda title, reason, resolution: window.recorded_errors.append(reason)
    )
    monkeypatch.setattr(window, "confirm_project_replacement", lambda: True)

    try:
        grid = window.connection_grid
        window.component_collection.add_component(
            "resistor", 2, 2, "4k7", grid
        )
        window.connection_grid_scene.rebuild_component_items()
        path = tmp_path / "bad.json"
        path.write_text("{", encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *args, **kwargs: (str(path), ""))
        )
        window.open_project()

        assert window.component_collection.get_component("R1").value_text == (
            "4k7"
        )
        assert window.recorded_errors
    finally:
        close_window(window)


def test_print_writes_a_pdf_of_the_circuit(qt_application, tmp_path):
    window = MainWindow()

    try:
        grid = window.connection_grid
        window.component_collection.add_component(
            "resistor", 2, 2, "10k", grid
        )
        window.connection_grid_scene.rebuild_component_items()
        window.show()
        path = tmp_path / "circuit.pdf"
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(path))

        assert window.render_circuit(printer) is True
        contents = path.read_bytes()
        assert contents.startswith(b"%PDF")
        assert len(contents) > 1000
        file_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "&File"
        )
        assert "Print..." in [action.text() for action in file_menu.actions()]
        assert window.print_action.shortcut() == QKeySequence(
            QKeySequence.Print
        )
    finally:
        close_window(window)
