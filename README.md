PyCircuit (Circuit Workbench)
=============================

A desktop circuit workbench written in Python with PyQt5. Today it shows a
grid of connection points (8 x 8 by default, resizable up to 50 x 50). You
can select points, mark points as "signal pickoffs" for later analysis
plots, and save or open the whole circuit as a JSON project file. File >
Print prints that circuit on one page. File > Export Netlist writes a
SPICE netlist (.cir) you can open in LTspice.

Planned next: the oscilloscope, then Bode and FFT.


Requirements
------------

- Anaconda or Miniconda
- Python (tested on Python 3.13)
- PyQt5 5.15 and sympy, installed with pip from requirements.txt


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

    git clone https://github.com/BkennedyJr/PyCircuit.git
    cd PyCircuit
    conda create -n pycircuit python=3.13
    conda activate pycircuit
    pip install -r requirements.txt

Install PyQt5 with pip only (from requirements.txt). Do not also run
"conda install pyqt" in the same environment, because the two copies of Qt
can conflict.


Installing ngspice
------------------

The DC operating point uses ngspice. In the Anaconda Prompt, with the
pycircuit environment active:

    conda install -c conda-forge ngspice

That install provides ngspice and the shared library (ngspice.dll).
PySpice and numpy are already in requirements.txt, so the pip install
above is what brings them in. Do not conda install pyqt.


Run
---

In the Anaconda Prompt, from the repository folder:

    conda activate pycircuit
    python main.py


Using it
--------

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
  frequency and phase, on the grid and in the Probe panel. Drag a flag
  to another point. Delete removes the selected probe.
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
  opens. File > Print (Ctrl+P) prints the circuit on one page. File >
  Export Netlist writes a .cir file of the same circuit, without probe
  loads. The same netlist is what ngspice uses for the DC operating
  point. Simulate > DC Operating Point draws those voltages on the
  nodes and those currents on the parts. The selected point shows the
  DC voltage next to V(s). Editing the circuit clears the numbers.
- Help > Help (F1) opens the help text. That text is docs/help.txt,
  which will be filled in later. Help > About Circuit Workbench shows
  the version. That number goes up by one on the last digit each time
  a change is merged (0.1.0, then 0.1.1, then 0.1.2, then 0.1.3).


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
it is not in requirements.txt. Install it once, then run the tests:

    conda activate pycircuit
    pip install pytest
    python -m pytest -q
