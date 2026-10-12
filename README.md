PyCircuit (Circuit Workbench)
=============================

A desktop circuit workbench written in Python with PyQt5. Today it shows a
grid of connection points (8 x 8 by default, resizable up to 50 x 50). You
can select points, mark points as "signal pickoffs" for later analysis
plots, and save or open the whole circuit as a JSON project file. File >
Print prints that circuit on one page. File > Export Netlist writes a
SPICE netlist (.cir) you can open in LTspice.

Planned next: real op-amp output swing and gain-bandwidth.


Requirements
------------

- Anaconda. Spyder's IPython uses this Python (base).
- Python (tested on Python 3.13)
- PyQt5 and sympy, already in Anaconda
- PySpice and the ngspice library, installed into that same Python


Project layout
--------------

    main.py                          entry point
    core/                            plain Python, no Qt
        connection_grid.py           grid data model
        exceptions.py                error classes
        project_io.py                save and load project files
        units.py                     parse component values (4k7, 10u, 1meg)
    gui/                             PyQt5 user interface
        main_window.py               main window, menus, docks
        grid_editor.py               grid drawing (QGraphicsScene/View)
        grid_configuration_widget.py rows and columns controls
    tests/                           pytest tests
        test_smoke.py                grid model smoke test
        test_units.py                value parser tests


Install (Windows, Anaconda Prompt)
----------------------------------

The Anaconda Prompt uses Anaconda base. Install new packages there.
Spyder uses that same Python when it is running. Do not install them
only in a separate environment. An older pycircuit environment is not
this Python.

    git clone https://github.com/BkennedyJr/PyCircuit.git
    cd PyCircuit
    conda activate base
    python -c "import sys; print(sys.executable)"
    pip install PySpice
    pip install pyqtgraph
    conda install -c conda-forge ngspice-lib

python.exe should be C:\Users\danni\anaconda3\python.exe before those
installs. conda-forge has no PySpice build for Python 3.11 or newer
(its newest Windows build is Python 3.10), so "conda install pyspice"
cannot succeed here. pip install PySpice puts the module in base. In
Python the name is PySpice. pyqtgraph draws the oscilloscope. Install
it with pip. Do not conda install pyqtgraph: that package also
installs PyQt.

ngspice-lib is the shared library (ngspice.dll). Read the plan conda
prints. If it would remove Spyder or replace PyQt, stop and do not
press y.

Anaconda already has PyQt5. Do not pip install PyQt5 into base, and do
not run "conda install pyqt" on top of a pip copy of PyQt. Do not
"pip install -r requirements.txt" into base: that file also lists
PyQt5. When conda-forge has a build for this Python, use conda for
that one package. PySpice is the exception, and it uses pip.

In the Anaconda Prompt, with base active:

    python -c "import PySpice; print(PySpice.__file__)"

That path should be under
C:\Users\danni\anaconda3\Lib\site-packages\PySpice. The same import
works in Spyder's IPython once Spyder is using this base Python.


Installing ngspice
------------------

The DC operating point needs the ngspice shared library. The
ngspice-lib install above provides ngspice.dll. ngspice is not a
Python module, so "import ngspice" fails, and that is expected.

With base active, this file should exist:

    C:\Users\danni\anaconda3\Library\bin\ngspice.dll


Run
---

From the Anaconda Prompt, in the repository folder:

    conda activate base
    python main.py

That starts the program from the Prompt. Standalone Spyder (not the
Spyder that comes with Anaconda) also runs it: open main.py and use
Debug.


Using it
--------

- The Type list is resistors, sources, and the other discrete parts,
  plus the follower and the amplifier blocks. Packaged ICs are in the
  IC library next to that list, grouped as op-amps, comparators,
  logic, timers, and regulators. Place uses whichever of those two
  lists you picked last.
- Click a grid point to select it. The right-hand panel shows its
  identifier (for example NODE_R03_C05), row and column, and the
  s-domain voltage formula at that node, such as V(s) = 5 V. A bridge
  is not a connection. Diodes, transistors and logic gates have no
  formula. An op-amp uses the ideal rule that its two inputs match.
  The generic op-amp, the 741 and the TL081 show the 741 DIP pin
  numbers (2 in-, 3 in+, 4 V-, 6 out, 7 V+). The LM358, TL072,
  NE5532 and TL082 show amplifier A of the dual DIP (1 out, 2 in-,
  3 in+, 4 V-, 8 V+). The LM324 shows amplifier A of the quad
  (1 out, 2 in-, 3 in+, 4 V+, 11 V-). The part list also has an
  LM358, a TL072, an NE5532, a TL081, a TL082, an LM324, a comparator,
  the standard gates, a voltage follower, and inverting and
  non-inverting amplifiers (the gain is the value). NMOS and PMOS,
  and the 555 timer, have no formula. A switch is open or closed, a
  potentiometer splits its resistance by a position from 0 to 1, a
  transformer uses its turns ratio, and a voltage regulator holds
  its output at the voltage you type (it ignores dropout).
- Probe Mode (Component menu, toolbar, or P): click a grid point to
  place a probe, or click a part to measure its current. The Probe
  panel sets the method: Direct (no load), 1 Mohm to ground, 10x scope
  (10 Mohm and 10 pF to ground), Differential (click the other point;
  the reading is the first point minus the second), or Current. A probe
  that is not on a plot shows a box of readings: voltage, current,
  frequency and phase, on the grid and in the Probe panel. Drag a
  probe and it stays where you release it. A line and an arrow show
  the point it is reading. Release it on another point to read that
  point (a current probe, on another part). Reset position in the
  Probe panel puts the picture back beside that point. Delete removes
  the selected probe.
- Type a name such as Vcc in that panel and press Apply (or Enter).
  Every point with the same name is one node, so a DC source wired to
  one of them sets the voltage at the others. Vcc and vcc match.
  Leave the name blank and Apply to clear it. The name is drawn beside
  the point and is saved with the grid.
- Node > Toggle Signal Pickoff marks the selected point green.
- The Grid toolbar at the top sets the rows and columns. Press Apply,
  or tab to Apply and press Enter.
- Placing a part: click a grid point, pick the part in the Components
  panel and press Place at Selected Point. The part appears
  see-through at that point: the arrow keys or W/A/S/D point it right,
  down, left or up (cyan where it fits, red where it would clash),
  clicking another grid point moves it, Enter or a right-click places
  it, and Esc cancels.
- Wire mode (Component > Wire Mode, or W): press a grid point and drag
  to another point on the same row or column. If that wire crosses
  another wire, choose Connect or Bridge. Bridge hops over the crossing
  and does not connect there. Esc cancels a wire.
- Ctrl + mouse wheel zooms. Drag the board with the left button to
  move it (the middle button does the same). Hold Shift and drag to
  select several points or parts. View > Fit Grid fits the grid to the
  window.
- File > Save Project / Open Project stores the grid, parts, wires and
  probes as a .json file. An older file that only has the grid still
  opens. examples/all-features.json is one sheet with every part.
  examples/all-features.txt says what each number should be. File >
  Print (Ctrl+P) prints the circuit on one page. File >
  Export Netlist writes a .cir file of the same circuit, without probe
  loads. The same netlist is what ngspice uses for the DC operating
  point. Simulate > DC Operating Point draws those voltages on the
  nodes and those currents on the parts. The selected point shows the
  DC voltage next to V(s). Change a resistor, a source, a pot
  position, or a switch and those numbers run again. Moving or
  deleting a part clears them.
- Drag a panel by its title bar. Drop it on an edge to dock it, drop
  it on another panel to put them in tabs, or float it. View shows a
  closed panel again. The scope starts under the circuit, so it does
  not cover the part buttons. That arrangement is remembered the next
  time the program opens.
- View > Oscilloscope opens the scope dock (it can float). The run
  time, time per division, and volts per division sit beside the
  trace. Start runs a transient and draws each checked probe. Stop
  drops that run. The run is five periods of the slowest sine, or
  10 ms. Time per division and volts per division set the grid; leave
  volts blank for Auto.
  Moving a probe redraws it from the last run when that point was in
  the run. An LED lights when its current is above 1 mA. Change a
  value and the trace runs again, and the spectrum follows it. The
  exact V(s) stays next to the DC number.
- View > Bode opens the frequency-sweep dock (it can float, and it
  starts as a tab on the oscilloscope). Start sweeps from the start
  frequency to the stop frequency. Magnitude is dB relative to the
  one AC source, and phase is degrees. A checked probe is a curve.
  Change a value and the curves run again. Moving or deleting a
  part clears them.
- View > FFT opens the spectrum of the oscilloscope waveform (it can
  float, and it starts as a tab on the oscilloscope). The height is
  the peak of that wave. A 1 V sine that lasts a whole number of
  cycles is a 1 V line at its frequency. Run the oscilloscope to
  draw it. Editing the circuit clears it.
- The oscilloscope, Bode, and FFT each have two cursors, A and B.
  Drag the dashed lines. The box under the controls reads both and
  the difference, B minus A. On Bode that difference is frequency,
  decibels, and degrees. A trace chooser appears when more than one
  probe is drawn.
- Help > Help (F1) opens the help text. That text is docs/help.txt,
  which will be filled in later. Help > About Circuit Workbench shows
  the version. That number goes up by one on the last digit each time
  a change is merged (0.1.0, then 0.1.1, then 0.1.2, then 0.1.3, then 0.1.4, then 0.1.5, then 0.1.6, then 0.1.7, then 0.1.8, then 0.1.9, then 0.1.10, then 0.1.11, then 0.1.12, then 0.1.13).


Third-party files
-----------------

core/spice_library/LM741_logipipe.lib is the LM741 op-amp model by
Logipipe, LLC (https://www.logipipe.com/LM741.txt), used under the
Creative Commons Attribution 4.0 International licence (CC BY 4.0,
https://creativecommons.org/licenses/by/4.0/). It is bundled unchanged
(a test checks its SHA-256); the Op-amp (741) part wraps it in the
five-pin subcircuit LM741. Full attribution is in
core/spice_library/README.txt. The rest of PyCircuit does not yet carry
its own licence file.


Tests
-----

pytest is only needed for running the tests, not for running the app, so
it is not in requirements.txt. Install it once into Anaconda base, then
run the tests:

    conda activate base
    conda install -c conda-forge pytest
    python -m pytest -q
