"""
PR F check in ngspice: both op-amp models in an inverting amplifier.

Rin 10k, Rf 100k (gain -10), +/-15 V supplies, 0.1 V peak sine at 1 kHz.
The netlist uses core.subcircuit_models, as the M3 builder will. Skipped
when ngspice is not installed (it is on the box: ngspice 44.2).
"""

import re
import shutil
import subprocess

import pytest

from core.subcircuit_models import build_instance_line, get_subcircuit_text

pytestmark = pytest.mark.skipif(
    shutil.which("ngspice") is None, reason="ngspice is not installed"
)


def run_inverting_amplifier(model_name, input_peak="0.1", tmp_path=None):
    instance = build_instance_line(
        "X1", model_name,
        {"in+": "0", "in-": "inm", "out": "out", "V+": "vp", "V-": "vn"}
    )
    netlist = f"""Inverting amplifier, gain -10, {model_name}
{get_subcircuit_text(model_name)}
VCC vp 0 DC 15
VEE vn 0 DC -15
VIN in 0 DC 0 AC 1 SIN(0 {input_peak} 1k 0 0 0)
RIN in inm 10k
RF out inm 100k
{instance}
.control
op
print v(out)
ac lin 1 1k 1k
print vm(out) vp(out)
tran 2u 5m
meas tran outmax max v(out) from=3m to=5m
meas tran outmin min v(out) from=3m to=5m
meas tran inmax max v(in) from=3m to=5m
meas tran outq find v(out) at=3.25m
.endc
.end
"""
    path = tmp_path / f"inverting_{model_name}.cir"
    path.write_text(netlist)
    result = subprocess.run(
        ["ngspice", "-b", str(path)], capture_output=True, text=True,
        check=False,
        timeout=60
    )
    output = result.stdout + result.stderr
    assert "error" not in output.lower(), output

    def number(name):
        match = re.search(rf"^{name}\s*=\s*(\S+)", output, re.MULTILINE)
        assert match, output
        return float(match.group(1))

    return {
        "op_out": number(r"v\(out\)"),
        "ac_magnitude": number(r"vm\(out\)"),
        "ac_phase": number(r"vp\(out\)"),
        "out_max": number("outmax"),
        "out_min": number("outmin"),
        "in_max": number("inmax"),
        "out_at_input_peak": number("outq"),
    }


@pytest.mark.parametrize("model_name", ["OPAMP", "LM741"])
def test_inverting_gain_is_minus_ten_at_1khz(model_name, tmp_path):
    result = run_inverting_amplifier(model_name, tmp_path=tmp_path)

    # Operating point: the output sits near 0 V.
    assert abs(result["op_out"]) < 0.05
    # Small-signal at 1 kHz: |gain| 10 within 1 %, phase 180 degrees.
    assert result["ac_magnitude"] == pytest.approx(10, rel=0.01)
    assert abs(abs(result["ac_phase"]) - 3.14159) < 0.02
    # Transient: 0.1 V peak in gives about 1 V peak out, inverted.
    gain = (result["out_min"] - result["out_max"]) / (2 * result["in_max"])
    assert gain == pytest.approx(-10, rel=0.01)
    assert result["out_at_input_peak"] == pytest.approx(-1.0, rel=0.02)


def test_lm741_clips_at_its_supplies_and_the_generic_does_not(tmp_path):
    # 3 V peak in asks for 30 V peak out.
    lm741 = run_inverting_amplifier("LM741", "3", tmp_path)
    generic = run_inverting_amplifier("OPAMP", "3", tmp_path)

    assert 12 < lm741["out_max"] < 15
    assert -15 < lm741["out_min"] < -12
    assert generic["out_max"] == pytest.approx(30, rel=0.01)
