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
- Python 3.13 (made with 3.13; 3.9 or newer should work)
- PyQt5 5.15, installed with pip from requirements.txt


Project layout
--------------

    main.py                          entry point
    core/                            plain Python, no Qt
        connection_grid.py           grid data model
        exceptions.py                error classes
        project_io.py                save and load project files
    gui/                             PyQt5 user interface
        main_window.py               main window, menus, docks
        grid_editor.py               grid drawing (QGraphicsScene/View)
        grid_configuration_widget.py rows and columns controls
    tests/                           pytest tests


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
  click Apply.
- Ctrl + mouse wheel zooms. View > Fit Grid fits the grid to the window.
- File > Save Project / Open Project stores the grid as a .json file.


Tests
-----

    conda activate pycircuit
    pip install pytest
    python -m pytest -q
