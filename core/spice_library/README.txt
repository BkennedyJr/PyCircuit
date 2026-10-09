SPICE subcircuit files used by core/subcircuit_models.py.

LM741_logipipe.lib
  LM741 op-amp model, Copyright (c) 2018-2020 Logipipe, LLC,
  https://www.logipipe.com/LM741.txt (downloaded 2026-10-09).
  Licensed under Creative Commons Attribution 4.0 International
  (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/.
  Kept byte-for-byte as published (tests/test_subcircuit_models.py checks
  its SHA-256). PyCircuit does not change it; it only wraps it in the
  five-port subcircuit LM741 (in+ in- V+ V- out) in
  core/subcircuit_models.py.
  Logipipe's own reference: Fairchild Semiconductor Corporation (2001),
  LM741 Single Operational Amplifier, Rev 1.0.1.
