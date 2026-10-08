"""
Circuit Workbench project-file input and output.

The initial project format persists connection-grid dimensions and selected
signal-pickoff points. Component instances, wires, reusable nodes, and
simulation settings will be added to this format in later increments.
"""

import json
import os
import tempfile
from pathlib import Path

from core.connection_grid import ConnectionGrid
from core.exceptions import GridConfigurationError
from core.exceptions import ProjectFileError


PROJECT_FORMAT_IDENTIFIER = "circuit_workbench_project"
PROJECT_FORMAT_VERSION = 1


def save_project_file(project_file_path, connection_grid):
    """
    Save the current connection-grid project using an atomic file update.

    Data is written to a temporary file first. The temporary file replaces
    the destination only after JSON writing completes successfully. This
    protects an existing project from partial writes caused by interruptions.

    :param project_file_path: Destination project file path.
    :type project_file_path: pathlib.Path
    :param connection_grid: Connection-grid state to persist.
    :type connection_grid: core.connection_grid.ConnectionGrid
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

    project_data = {
        "format": PROJECT_FORMAT_IDENTIFIER,
        "format_version": PROJECT_FORMAT_VERSION,
        "connection_grid": connection_grid.to_dict()
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
    the requested project fails.

    :param project_file_path: Project JSON file to load.
    :type project_file_path: pathlib.Path
    :returns: Validated connection-grid state.
    :rtype: core.connection_grid.ConnectionGrid
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

    if project_data.get("format_version") != PROJECT_FORMAT_VERSION:
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

    try:
        validated_connection_grid = ConnectionGrid.from_dict(
            project_data["connection_grid"]
        )

    except GridConfigurationError as error:
        raise ProjectFileError(
            "Project file '{}' has invalid connection-grid data. Reason: {}"
            .format(project_file_path.name, error)
        )

    return validated_connection_grid