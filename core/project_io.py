"""
Circuit Workbench project-file input and output.

A project file is the workbook: the grid (including net labels and
signal pickoffs), the parts, the wires and the probes. Format version 1
is an older file that stored only the grid. New files are version 2.
"""

import json
import os
import tempfile
from pathlib import Path

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.exceptions import GridConfigurationError
from core.exceptions import ProjectFileError
from core.probes import ProbeCollection
from core.wires import WireCollection


PROJECT_FORMAT_IDENTIFIER = "circuit_workbench_project"
PROJECT_FORMAT_VERSION = 2
_READABLE_VERSIONS = (1, 2)


class Workbook:
    """
    One circuit sheet: the grid, the parts, the wires and the probes.
    """

    def __init__(self, connection_grid, component_collection,
                 wire_collection, probe_collection):
        self.connection_grid = connection_grid
        self.component_collection = component_collection
        self.wire_collection = wire_collection
        self.probe_collection = probe_collection


def save_project_file(project_file_path, connection_grid,
                      component_collection=None, wire_collection=None,
                      probe_collection=None):
    """
    Save the current connection-grid project using an atomic file update.

    Data is written to a temporary file first. The temporary file replaces
    the destination only after JSON writing completes successfully. This
    protects an existing project from partial writes caused by interruptions.

    :param project_file_path: Destination project file path.
    :type project_file_path: pathlib.Path
    :param connection_grid: Connection-grid state to persist.
    :type connection_grid: core.connection_grid.ConnectionGrid
    :param component_collection: Placed parts. None saves none.
    :param wire_collection: Wires. None saves none.
    :param probe_collection: Probes. None saves none.
    :returns: None
    :raises ProjectFileError: If the project cannot be saved.
    """
    if not isinstance(project_file_path, Path):
        project_file_path = Path(project_file_path)

    if not isinstance(connection_grid, ConnectionGrid):
        raise ProjectFileError(
            "The project save request did not receive a valid connection grid."
        )

    destination_directory = project_file_path.parent

    # Confirm that the selected save directory exists before creating a
    # temporary file. This provides a direct resolution for invalid paths.
    if not destination_directory.exists():
        raise ProjectFileError(
            "The selected project directory does not exist: {}"
            .format(destination_directory)
        )

    if not destination_directory.is_dir():
        raise ProjectFileError(
            "The selected project location is not a directory: {}"
            .format(destination_directory)
        )

    if component_collection is None:
        components = []
    else:
        components = [
            component.to_dict()
            for component in component_collection.get_components()
        ]

    if wire_collection is None:
        wires = []
    else:
        wires = [wire.to_dict() for wire in wire_collection.get_wires()]

    if probe_collection is None:
        probes = []
    else:
        probes = [probe.to_dict() for probe in probe_collection.get_probes()]

    project_data = {
        "format": PROJECT_FORMAT_IDENTIFIER,
        "format_version": PROJECT_FORMAT_VERSION,
        "connection_grid": connection_grid.to_dict(),
        "components": components,
        "wires": wires,
        "probes": probes,
    }

    temporary_file_path = None

    try:
        # Create a temporary file in the destination directory so the final
        # replacement remains as reliable as possible on both Windows/Linux.
        with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".temporary",
                prefix="circuit_workbench_",
                dir=str(destination_directory),
                delete=False) as temporary_file_handle:

            temporary_file_path = Path(temporary_file_handle.name)

            # Write readable, stable JSON so saved projects can be inspected
            # or version-controlled without requiring the GUI.
            json.dump(
                project_data,
                temporary_file_handle,
                indent=2,
                sort_keys=True
            )

            temporary_file_handle.flush()
            os.fsync(temporary_file_handle.fileno())

        # Replace the previous project only after temporary-file creation,
        # serialization, and disk flushing completed successfully.
        os.replace(
            str(temporary_file_path),
            str(project_file_path)
        )

    except (OSError, TypeError, ValueError) as error:
        raise ProjectFileError(
            "Unable to save project '{}'. Reason: {}"
            .format(project_file_path, error)
        )

    finally:
        # Remove any temporary file left behind after an unsuccessful write.
        if temporary_file_path is not None:
            if temporary_file_path.exists():
                try:
                    temporary_file_path.unlink()
                except OSError:
                    pass


def load_project_file(project_file_path):
    """
    Load and validate a saved Circuit Workbench project.

    The project is fully parsed and validated before the GUI receives it.
    This allows the GUI to preserve the currently open project if loading
    the requested project fails. Version 1 files restore the grid and an
    empty circuit.

    :param project_file_path: Project JSON file to load.
    :type project_file_path: pathlib.Path
    :returns: Validated workbook.
    :rtype: Workbook
    :raises ProjectFileError: If the file cannot be read or validated.
    """
    if not isinstance(project_file_path, Path):
        project_file_path = Path(project_file_path)

    # Validate file-system conditions before attempting JSON parsing.
    if not project_file_path.exists():
        raise ProjectFileError(
            "Project file was not found: {}"
            .format(project_file_path)
        )

    if not project_file_path.is_file():
        raise ProjectFileError(
            "Project path is not a file: {}"
            .format(project_file_path)
        )

    try:
        with project_file_path.open("r", encoding="utf-8") as file_handle:
            project_data = json.load(file_handle)

    except json.JSONDecodeError as error:
        raise ProjectFileError(
            "Project file '{}' contains invalid JSON at line {}, column {}: {}"
            .format(
                project_file_path.name,
                error.lineno,
                error.colno,
                error.msg
            )
        )

    except PermissionError:
        raise ProjectFileError(
            "Permission was denied while reading project file: {}"
            .format(project_file_path)
        )

    except OSError as error:
        raise ProjectFileError(
            "Unable to read project file '{}'. Reason: {}"
            .format(project_file_path, error)
        )

    # Validate the project-level format before attempting grid restoration.
    if not isinstance(project_data, dict):
        raise ProjectFileError(
            "Project file '{}' must contain a JSON object."
            .format(project_file_path.name)
        )

    if project_data.get("format") != PROJECT_FORMAT_IDENTIFIER:
        raise ProjectFileError(
            "Project file '{}' is not a Circuit Workbench project."
            .format(project_file_path.name)
        )

    if project_data.get("format_version") not in _READABLE_VERSIONS:
        raise ProjectFileError(
            "Project file '{}' uses unsupported format version '{}'."
            .format(
                project_file_path.name,
                project_data.get("format_version")
            )
        )

    if "connection_grid" not in project_data:
        raise ProjectFileError(
            "Project file '{}' does not contain connection-grid data."
            .format(project_file_path.name)
        )

    file_name = project_file_path.name

    try:
        connection_grid = ConnectionGrid.from_dict(
            project_data["connection_grid"]
        )

    except GridConfigurationError as error:
        raise ProjectFileError(
            "Project file '{}' has invalid connection-grid data. Reason: {}"
            .format(file_name, error)
        )

    component_collection = ComponentCollection()
    wire_collection = WireCollection()
    probe_collection = ProbeCollection()

    if project_data.get("format_version") == 1:
        return Workbook(
            connection_grid,
            component_collection,
            wire_collection,
            probe_collection
        )

    try:
        for component_data in _section(project_data, "components", file_name):
            _require_object(component_data, "part", file_name)
            component_collection.place_saved(
                component_data["kind"],
                component_data["reference"],
                component_data["value"],
                component_data["row"],
                component_data["column"],
                connection_grid,
                component_data.get("rotation", 0),
                component_data.get("parameters", {})
            )

        for wire_data in _section(project_data, "wires", file_name):
            _require_object(wire_data, "wire", file_name)
            wire_collection.place_saved(
                wire_data["reference"],
                wire_data["start"],
                wire_data["end"],
                connection_grid,
                wire_data.get("bridged", [])
            )

        for probe_data in _section(project_data, "probes", file_name):
            _require_object(probe_data, "probe", file_name)
            probe_collection.place_saved(
                probe_data["reference"],
                probe_data["method"],
                probe_data["color"],
                connection_grid,
                identifier=probe_data.get("point"),
                second_identifier=probe_data.get("second_point"),
                component_reference=probe_data.get("part"),
                components=component_collection.get_components()
            )
    except KeyError as error:
        raise ProjectFileError(
            f"Project file '{file_name}' is missing {error.args[0]}."
        )
    except ComponentError as error:
        raise ProjectFileError(
            f"Project file '{file_name}' has an invalid circuit. "
            f"Reason: {error}"
        )

    return Workbook(
        connection_grid,
        component_collection,
        wire_collection,
        probe_collection
    )


def _section(project_data, field_name, file_name):
    """
    Return one workbook list, or raise if it is missing or not a list.

    :rtype: list
    """
    if field_name not in project_data:
        raise ProjectFileError(
            f"Project file '{file_name}' does not contain {field_name}."
        )

    section = project_data[field_name]

    if not isinstance(section, list):
        raise ProjectFileError(
            f"Project file '{file_name}' {field_name} must be a list."
        )

    return section


def _require_object(data, kind_name, file_name):
    """
    Raise unless one saved part, wire or probe is a JSON object.

    :returns: None
    """
    if not isinstance(data, dict):
        raise ProjectFileError(
            f"Project file '{file_name}' has a {kind_name} that is not "
            "a JSON object."
        )