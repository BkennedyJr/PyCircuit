"""
Background DC operating point. The window draws the result.

The netlist is checked on the GUI thread. The solve runs here so the
window stays responsive. Resistors, capacitors, inductors and sources
are solved in Python. Any other part still uses ngspice. core/ does
not import this module.
"""

from PyQt5.QtCore import QObject, pyqtSignal

from core.exceptions import SimulationError


class DcOperatingPointRunner(QObject):
    """
    Run one circuit's DC operating point off the GUI thread.

    :param components: Placed parts, or a ComponentCollection.
    :param wire_collection: Wires of the same circuit.
    :param connection_grid: Grid whose net labels name nodes.
    """

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, components, wire_collection, connection_grid):
        super().__init__()
        self._components = components
        self._wires = wire_collection
        self._grid = connection_grid

    def run(self):
        """
        Emit the operating point, or the plain-English reason it failed.

        :returns: None
        """
        from sim.runner import run_operating_point

        try:
            result = run_operating_point(
                self._components, self._wires, self._grid
            )
        except SimulationError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # noqa: BLE001
            # The button has to come back even when the solver raises
            # something other than SimulationError.
            self.failed.emit(str(error) or "The DC operating point failed.")
            return

        self.succeeded.emit(result)
