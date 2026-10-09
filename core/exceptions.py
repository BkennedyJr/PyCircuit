"""
Application-specific exception classes.

This module defines clear exception types used by the circuit-workbench
core logic. The GUI catches these expected exceptions and presents an
actionable explanation without terminating the application.
"""


class CircuitWorkbenchError(Exception):
    """
    Base exception for expected Circuit Workbench failures.

    :param message: Human-readable explanation of the failure.
    :type message: str
    """

    def __init__(self, message):
        super(CircuitWorkbenchError, self).__init__(message)


class GridConfigurationError(CircuitWorkbenchError):
    """
    Raised when a requested connection-grid configuration is invalid.
    """


class ProjectFileError(CircuitWorkbenchError):
    """
    Raised when a project file cannot be loaded, validated, or saved.
    """


class ComponentError(CircuitWorkbenchError):
    """
    Raised when a component definition, value, or placement is invalid.
    """
