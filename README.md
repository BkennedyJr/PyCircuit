PyCircuit (Circuit Workbench)
=============================

A desktop circuit workbench written in Python with PyQt5. Today it shows a
grid of connection points (8 x 8 by default, resizable up to 50 x 50). You
can select points, mark points as "signal pickoffs" for later analysis
plots, and save or open the grid as a JSON project file.

Planned next: schematic parts with values (R, C, L, sources, diodes, LEDs,
transistors), wires, a SPICE netlist, ngspice simulation, probes, and Bode,
oscilloscope and FFT plots.


Requirements
------------

- Anaconda or Miniconda
- Python (tested on Python 3.13)
- PyQt5 5.15, installed with pip from requirements.txt


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


Run
---

In the Anaconda Prompt, from the repository folder:

    conda activate pycircuit
    python main.py


Using it
--------

- Click a grid point to select it. The right-hand panel shows its
  identifier (for example NODE_R03_C05), row and column.
- Node > Toggle Signal Pickoff marks the selected point green.
- Use the Grid Configuration panel to change the rows and columns, then
  click Apply Grid Configuration.
- Placing a part: click a grid point, pick the part in the Components
  panel and press Place at Selected Point. The part appears
  see-through at that point: the arrow keys or W/A/S/D point it right,
  down, left or up (cyan where it fits, red where it would clash),
  clicking another grid point moves it, Enter or a right-click places
  it, and Esc cancels.
- Ctrl + mouse wheel zooms. View > Fit Grid fits the grid to the window.
- File > Save Project / Open Project stores the grid as a .json file.


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
