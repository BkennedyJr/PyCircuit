"""
Background DC operating point. The window draws the result.

The netlist is built on the GUI thread. ngspice runs here so the window
stays responsive. core/ does not import this module.
"""

from PyQt5.QtCore import QObject, pyqtSignal

from core.exceptions import SimulationError


class DcOperatingPointRunner(QObject):
    """
    Run one netlist's DC operating point off the GUI thread.

    :param netlist: Text from ``build_netlist``.
    :type netlist: str
    """

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, netlist):
        super().__init__()
        self._netlist = netlist

    def run(self):
        """
        Emit the operating point, or the plain-English reason it failed.

        :returns: None
        """
        from sim.runner import run_op

        try:
            result = run_op(self._netlist)
        except SimulationError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # noqa: BLE001
            # The button has to come back even when ngspice raises
            # something other than SimulationError.
            self.failed.emit(str(error) or "The DC operating point failed.")
            return

        self.succeeded.emit(result)
