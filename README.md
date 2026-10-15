PyCircuit (Circuit Workbench)
=============================

A desktop circuit workbench written in Python with PyQt5. Today it shows a
grid of connection points (8 x 8 by default, resizable up to 50 x 50). You
can select points, mark points as "signal pickoffs" for later analysis
plots, and save or open the whole circuit as a JSON project file. File >
Print prints that circuit on one page. File > Export Netlist writes a
SPICE netlist (.cir) you can open in LTspice.

Planned next: a Python solver for DC, AC and transient, so those runs
do not have to load ngspice.dll.


Requirements
------------

- Python 3.13 (this is the version the tests use)
- The packages in requirements.txt: PyQt5, sympy, PySpice, numpy
  and pyqtgraph
- The ngspice shared library, for the DC operating point, the
  oscilloscope, Bode and the FFT. On Windows that file is
  ngspice.dll. On Linux it is libngspice.so. A Python solver is
  planned so those runs can work on a machine that will not load
  that library. Until then, the window, the netlist and V(s) still
  work without it.


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


Install
-------

From a terminal, in the folder where you want the project:

    git clone https://github.com/BkennedyJr/PyCircuit.git
    cd PyCircuit
    python -m pip install -r requirements.txt
    python main.py


Installing ngspice
------------------

The DC operating point, the oscilloscope, Bode and the FFT call the
ngspice shared library through PySpice. ngspice is not a Python
module, so "import ngspice" fails, and that is expected.

Put the library where the program can find it:

- Linux: install the libngspice package. A usual file is
  libngspice.so.0 under /usr/lib or /usr/lib/x86_64-linux-gnu.
- Windows, when conda is allowed: the Anaconda section below
  installs ngspice.dll into that environment.
- Any machine: set NGSPICE_LIBRARY_PATH to the full path of
  ngspice.dll or libngspice.so.

If the machine will not run ngspice or its library, skip this step.
The program still opens. Simulate reports that ngspice is not
installed.


Install (Anaconda)
------------------

Anaconda is optional. Use it when that is already your Python.
Open the Anaconda Prompt and use the base environment, so Spyder
sees the same packages. Change to the folder where you cloned the
repository.

    conda activate base
    python -c "import sys; print(sys.executable)"
    pip install PySpice
    pip install pyqtgraph
    conda install -c conda-forge ngspice-lib

conda-forge has no PySpice build for Python 3.11 or newer, so
"conda install pyspice" cannot succeed. pip install PySpice puts
the module in base. In Python the name is PySpice. pyqtgraph draws
the oscilloscope. Do not conda install pyqtgraph: that package also
installs PyQt.

Read the plan conda prints. If it would remove Spyder or replace
PyQt, stop and do not press y.

Anaconda already has PyQt5. Do not pip install PyQt5 into base, and
do not run "conda install pyqt" on top of a pip copy of PyQt. Do not
"pip install -r requirements.txt" into base: that file also lists
PyQt5.

With base active, ngspice.dll is in that environment's Library\bin
folder.

Check the install:

    python -c "import PySpice; print(PySpice.__file__)"

That path should be under the base environment's site-packages.
The same import works in Spyder's IPython once Spyder is using
this base Python.

Start the program from the Anaconda Prompt, in the repository folder:

    conda activate base
    python main.py

Standalone Spyder also runs it: open main.py and use Debug.


Using it
--------

- The Type list is resistors, sources, and the other discrete parts,
  plus the follower and the amplifier blocks, and IC. The IC library
  (op-amps, comparators, logic, timers, and regulators) turns on only
  when Type is IC, and Place uses the device shown there.
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
  non-inverting amplifiers (the gain is the value). Those six op-amps
  have a Limits choice. Flat is the old stand-in: gain only, so the
  output can swing past the rails. Limited holds the output between
  the rails and rolls the gain off with one pole. Each of those six
  also has Gain, Rin, Rout, GBW, and two headrooms. Gain, Rin and
  Rout are used either way. GBW and the headrooms are used when
  Limits is limited. High headroom is how far the output stays below
  V+. Low headroom is how far it stays above V-. Leave a box blank
  to keep that model's usual number. The LM358 and LM324 start at
  gain 100,000, Rin 1 megohm, Rout 50 ohm and 1 MHz; the output can
  sit on the negative rail and stops 1.5 V below the positive rail.
  The TL072, TL081 and TL082 start at gain 200,000, Rin 1 terohm,
  Rout 75 ohm and 3 MHz, 1.5 V inside both rails. The NE5532 starts
  at gain 100,000, Rin 300 kilohm, Rout 10 ohm and 10 MHz, 2 V inside
  both rails. The generic op-amp and the 741 keep their fixed models.
  A new part, and an old file that has no choice saved, stays Flat.
  V(s) stays the ideal rule next to the simulator number. A diode,
  NPN, PNP, NMOS, PMOS, NJFET and PJFET have boxes for the usual
  SPICE card numbers. The boxes start at that model's numbers, so a
  1N4148 stays a 1N4148 until you type a new one. Leave a box blank
  to put that model's number back. The diode has IS, N, RS, CJO, TT,
  BV and IBV. The transistor has BF, VAF, CJE, CJC, TR, TF, RB, RE
  and RC. The MOSFET has Level, VTO, KP, TOX and U0. Level 1 is the
  simple model, and level 8 is BSIM3 in ngspice. The JFET has VTO,
  BETA, LAMBDA and IS. NMOS, PMOS, the JFETs and the 555 timer
  have no formula. A switch is open or closed, a
  potentiometer splits its resistance by a position from 0 to 1, a
  transformer uses its turns ratio, and a voltage regulator holds
  its output at the voltage you type (it ignores dropout).
- Probe Mode (Component menu, toolbar, or P): click a grid point to
  place a probe, or click a part to measure its current. The Probe
  panel sets the method: Direct (no load), 1 Mohm to ground, 10x scope
  (10 Mohm and 10 pF to ground), Differential (click the other point;
  the reading is the first point minus the second), or Current. Each
  probe shows a box of readings beside its flag. The first line is
  the formula, V(s) or I, when the circuit has one. Then voltage,
  current, frequency and phase. A gate, a 555, or a diode has no
  formula, so that line is left off. Changing a part updates that box. The Probe
  panel shows the same readings, or "On a plot." when a trace is
  drawing that probe. Drag the
  flag to move the readings; the point it reads stays the same. Drag
  the arrow to choose a point (the nearest grid point; a current
  probe, the part you drop it on). Or type the point in the Probe
  panel and press Enter: NODE_R04_C03, a row and column such as 4 3
  or R4 C3, or a net name such as Vcc. A differential probe has a
  Point and a Minus. Reset position puts the picture back beside
  that point. Delete removes the selected probe.
- Type a name such as Vcc in that panel and press Apply (or Enter).
  Every point with the same name is one node, so a DC source wired to
  one of them sets the voltage at the others. Vcc and vcc match.
  Leave the name blank and Apply to clear it. The name is drawn beside
  the point and is saved with the grid.
- Node > Toggle Signal Pickoff marks the selected point green.
- The top toolbar starts with Delete, Wire Mode, Probe Mode, and
  DC Operating Point, then the grid size (rows, columns, and Apply).
  Save stays in the File menu. View > Toolbar shows or hides any
  other command that is also in a menu. That choice is remembered.
  Zoom is not on the toolbar: View > Zoom In, Zoom Out, and Zoom to
  Fit, or Ctrl and the wheel. Press Apply, or tab to Apply and
  press Enter, to resize the grid.
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
  probes as a .json file. File > Close Project drops that circuit and
  leaves a blank 8 x 8 grid. The window stays open. File > Exit closes
  the program. An older file that only has the grid still
  opens. examples/all-features.json is one sheet with every part.
  examples/all-features.txt says what each number should be. File >
  Examples is separate: a voltage divider (5 V in the middle), an
  RC low-pass (1k and 159 nF), a unity-gain buffer (a 1 V, 1 kHz
  sine copied to the output), or an AND gate (both inputs at 5 V,
  so the output is 5 V). Each one opens as a circuit you can edit,
  and Save asks for a new file. File >
  Print (Ctrl+P) prints the circuit on one page. File >
  Export Netlist writes a .cir file of the same circuit, without probe
  loads. The same netlist is what ngspice uses for the DC operating
  point. When a node has only one connection, that node is drawn
  with an orange ring and the message names it. The ring stays
  after you close the message, and the next edit clears it.
  Simulate > DC Operating Point draws those voltages on the
  nodes and those currents on the parts. The selected point shows the
  DC voltage next to V(s). Simulate > Continuous is the usual
  choice: change a resistor, a source, a pot position, or a switch
  and those numbers run again, along with any plot already showing.
  Simulate > Snapshot keeps one reading, and a new value clears it.
  The same choice is on the oscilloscope, Bode, and FFT. Moving or
  deleting a part clears them either way.
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
  volts blank for Auto. The wheel on the trace zooms both axes. The
  wheel on the time numbers zooms only time, and the wheel on the
  volts numbers zooms only volts. The division boxes follow. Type a
  division to use the box again.
  Moving a probe redraws it from the last run when that point was in
  the run. An LED lights when its current is above 1 mA. In
  Continuous, a new value runs the trace again while this window is
  open. The exact V(s) stays next to the DC number.
- View > Bode opens the frequency-sweep dock (it can float, and it
  starts as a tab on the oscilloscope). Start sweeps from the start
  frequency to the stop frequency. Magnitude is dB relative to the
  one AC source, and phase is degrees. The wheel on a trace zooms
  both axes. The wheel on the frequency numbers zooms only frequency,
  and the wheel on the left numbers zooms only that axis. A checked
  probe is a curve.
  In Continuous, a new value runs the curves again while this window
  is open. A closed Bode window waits until you open it. Snapshot,
  or moving or deleting a part, clears them.
- View > FFT opens the spectrum of the oscilloscope waveform (it can
  float, and it starts as a tab on the oscilloscope). The height is
  the peak of that wave. The wheel on the trace zooms both axes. The
  wheel on the frequency numbers zooms only frequency, and the wheel
  on the left numbers zooms only the height. A 1 V sine that lasts a
  whole number of cycles is a 1 V line at its frequency. It is calculated when this
  window is open, from the oscilloscope run. With only the
  oscilloscope open, the spectrum is not calculated. Opening FFT
  draws it from that run. In Continuous, a new value runs it again
  while this window is open. Snapshot, or moving or deleting a
  part, clears it.
- The oscilloscope, Bode, and FFT each have two cursors, A and B.
  Drag the dashed lines. The box under the controls reads both and
  the difference, B minus A. On Bode that difference is frequency,
  decibels, and degrees. A trace chooser appears when more than one
  probe is drawn.
- Help > Help (F1) opens the help text. That text is docs/help.txt,
  which will be filled in later. Help > About Circuit Workbench shows
  the version. That number goes up by one on the last digit each time
  a change is merged (0.1.0, then 0.1.1, then 0.1.2, then 0.1.3, then 0.1.4, then 0.1.5, then 0.1.6, then 0.1.7, then 0.1.8, then 0.1.9, then 0.1.10, then 0.1.11, then 0.1.12, then 0.1.13, then 0.1.14, then 0.1.15, then 0.1.16, then 0.1.17, then 0.1.18, then 0.1.19, then 0.1.20, then 0.1.21, then 0.1.22, then 0.1.23, then 0.1.24, then 0.1.25, then 0.1.26, then 0.1.27, then 0.1.28, then 0.1.29, then 0.1.30).


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
it is not in requirements.txt. From the repository folder:

    python -m pip install pytest
    python -m pytest -q

Anaconda users install it into base instead:

    conda activate base
    conda install -c conda-forge pytest
    python -m pytest -q
