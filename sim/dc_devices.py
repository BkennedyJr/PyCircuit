"""
Nonlinear companions for the DC operating point.

Diodes, LEDs, BJTs, MOSFETs and JFETs are Newton companions. Logic
gates, the comparator and a limited op-amp are a voltage that depends
on the last solution. The thermal voltage is 0.02585 V. Series
resistance and the Early effect use the same numbers as the SPICE card.
"""

import math

_VT = 0.02585
_EXP_LIMIT = 80.0
_JUNCTION_STEP = 0.1
_VOLTAGE_TOLERANCE = 1e-7
_TINY_CONDUCTANCE = 1e-15


def _volts(voltages, node):
    if node == "0":
        return 0.0

    return float(voltages.get(node, 0.0))


def _shockley(voltage, saturation, emission):
    """
    Return ``(current, conductance)`` for one junction.

    The exponent stops at 80 so a wild guess cannot overflow. Past
    that voltage the current follows the slope at the limit. A red
    LED sits near 43, so the limit does not change its answer.
    """
    thermal = emission * _VT
    argument = voltage / thermal

    if argument < -_EXP_LIMIT:
        return -saturation, 0.0

    if argument > _EXP_LIMIT:
        exponential = math.exp(_EXP_LIMIT)
        conductance = saturation * exponential / thermal
        limited = _EXP_LIMIT * thermal
        current = saturation * (exponential - 1.0)
        current += conductance * (voltage - limited)

        return current, conductance

    exponential = math.exp(argument)
    current = saturation * (exponential - 1.0)
    conductance = saturation * exponential / thermal

    return current, conductance


def _step(target, previous, limit):
    delta = target - previous

    if delta > limit:
        return previous + limit

    if delta < -limit:
        return previous - limit

    return target


def _resistor(name, left, right, conductance):
    if conductance < _TINY_CONDUCTANCE:
        return None

    return ("R", name, left, right, 1.0 / conductance)


def _current(name, injected, extracted, amps):
    if amps == 0.0:
        return None

    return ("I", name, injected, extracted, amps)


class DiodeDevice:
    """
    Shockley diode. Positive current enters the anode.

    ``anode`` may be an internal node after a series resistor.
    """

    def __init__(self, reference, anode, cathode, saturation, emission):
        self.reference = reference
        self.anode = anode
        self.cathode = cathode
        self.saturation = saturation
        self.emission = emission
        self.vj = 0.0

    def companions(self):
        current, conductance = _shockley(
            self.vj, self.saturation, self.emission
        )
        stamps = []
        resistor = _resistor(
            f"@{self.reference}.g", self.anode, self.cathode, conductance
        )

        if resistor is not None:
            stamps.append(resistor)
            equivalent = current - conductance * self.vj
        else:
            equivalent = current

        source = _current(
            f"@{self.reference}.i", self.cathode, self.anode, equivalent
        )

        if source is not None:
            stamps.append(source)

        return stamps

    def converged(self, voltages):
        return abs(self._junction(voltages) - self.vj) < _VOLTAGE_TOLERANCE

    def update(self, voltages):
        target = self._junction(voltages)

        if target <= 0.0 and self.vj <= 0.0:
            self.vj = target
            return

        self.vj = _step(target, self.vj, _JUNCTION_STEP)

    def solved_current(self, voltages):
        current, _conductance = _shockley(
            self._junction(voltages), self.saturation, self.emission
        )

        return current

    def _junction(self, voltages):
        return _volts(voltages, self.anode) - _volts(voltages, self.cathode)


class BjtDevice:
    """
    Transport BJT. Positive current enters the collector.

    Polarity is +1 for NPN and -1 for PNP. Br is 1. The Early factor
    ``1 + Vce/Vaf`` is taken from the last junction voltages and held
    for that Newton step.
    """

    def __init__(
            self, reference, base, collector, emitter,
            saturation, beta, early, polarity):
        self.reference = reference
        self.base = base
        self.collector = collector
        self.emitter = emitter
        self.saturation = saturation
        self.beta = beta
        self.early_voltage = early
        self.polarity = polarity
        self.reverse_beta = 1.0
        self.vbe = 0.0
        self.vbc = 0.0

    def companions(self):
        forward, gbe = _shockley(self.vbe, self.saturation, 1.0)
        reverse, gbc = _shockley(self.vbc, self.saturation, 1.0)
        early = 1.0 + (self.vbe - self.vbc) / self.early_voltage

        early = max(early, 0.05)
        gpi = gbe / self.beta
        gmu = gbc / self.reverse_beta
        gm = early * gbe
        extra = early * gbc
        base_current = forward / self.beta + reverse / self.reverse_beta
        collector_current = (
            (forward - reverse) * early - reverse / self.reverse_beta
        )
        base_equivalent = base_current - gpi * self.vbe - gmu * self.vbc
        collector_equivalent = (
            collector_current
            - gm * self.vbe
            + (extra + gmu) * self.vbc
        )
        stamps = []
        resistor = _resistor(
            f"@{self.reference}.pi", self.base, self.emitter, gpi
        )

        if resistor is not None:
            stamps.append(resistor)

        resistor = _resistor(
            f"@{self.reference}.mu", self.base, self.collector, gmu
        )

        if resistor is not None:
            stamps.append(resistor)

        if gm >= _TINY_CONDUCTANCE:
            stamps.append((
                "G", f"@{self.reference}.gm",
                self.emitter, self.collector, self.base, self.emitter, gm,
            ))

        if extra >= _TINY_CONDUCTANCE:
            stamps.append((
                "G", f"@{self.reference}.x",
                self.emitter, self.collector,
                self.collector, self.base, extra,
            ))

        source = _current(
            f"@{self.reference}.b",
            self.emitter, self.base, self.polarity * base_equivalent,
        )

        if source is not None:
            stamps.append(source)

        source = _current(
            f"@{self.reference}.c",
            self.emitter, self.collector,
            self.polarity * collector_equivalent,
        )

        if source is not None:
            stamps.append(source)

        return stamps

    def converged(self, voltages):
        vbe, vbc = self._junctions(voltages)

        return (
            abs(vbe - self.vbe) < _VOLTAGE_TOLERANCE
            and abs(vbc - self.vbc) < _VOLTAGE_TOLERANCE
        )

    def update(self, voltages):
        vbe, vbc = self._junctions(voltages)
        self.vbe = self._move(vbe, self.vbe)
        self.vbc = self._move(vbc, self.vbc)

    def solved_current(self, voltages):
        _base, collector = self._currents(voltages)

        return collector

    def _junctions(self, voltages):
        vb = _volts(voltages, self.base)
        vc = _volts(voltages, self.collector)
        ve = _volts(voltages, self.emitter)

        return (
            self.polarity * (vb - ve),
            self.polarity * (vb - vc),
        )

    def _move(self, target, previous):
        if target <= 0.0 and previous <= 0.0:
            return target

        return _step(target, previous, _JUNCTION_STEP)

    def _currents(self, voltages):
        vbe, vbc = self._junctions(voltages)
        forward, _gbe = _shockley(vbe, self.saturation, 1.0)
        reverse, _gbc = _shockley(vbc, self.saturation, 1.0)
        early = 1.0 + (vbe - vbc) / self.early_voltage

        early = max(early, 0.05)
        base = forward / self.beta + reverse / self.reverse_beta
        collector = (
            (forward - reverse) * early - reverse / self.reverse_beta
        )

        return self.polarity * base, self.polarity * collector


def _mos_forward(vgs, vds, threshold, kp, channel_length):
    """
    Level-1 NMOS current into the drain, for ``vds >= 0``.

    :returns: ``(current, gm, gds)``.
    """
    if vds <= 0.0:
        return 0.0, 0.0, 0.0

    overdrive = vgs - threshold

    if overdrive <= 0.0:
        return 0.0, 0.0, 0.0

    boost = 1.0 + channel_length * vds

    if vds < overdrive:
        bare = kp * (overdrive * vds - 0.5 * vds * vds)
        current = bare * boost
        gm = kp * vds * boost
        gds = kp * (overdrive - vds) * boost + bare * channel_length

        return current, gm, gds

    bare = 0.5 * kp * overdrive * overdrive
    current = bare * boost
    gm = kp * overdrive * boost
    gds = bare * channel_length

    return current, gm, gds


def _jfet_forward(vgs, vds, threshold, beta, channel_length):
    """
    Shockley JFET current into the drain, for ``vds >= 0``.

    :returns: ``(current, gm, gds)``.
    """
    if vds <= 0.0 or vgs <= threshold:
        return 0.0, 0.0, 0.0

    overdrive = vgs - threshold
    boost = 1.0 + channel_length * vds

    if vds < overdrive:
        bare = beta * (2.0 * overdrive * vds - vds * vds)
        current = bare * boost
        gm = 2.0 * beta * vds * boost
        gds = (
            2.0 * beta * (overdrive - vds) * boost
            + bare * channel_length
        )

        return current, gm, gds

    bare = beta * overdrive * overdrive
    current = bare * boost
    gm = 2.0 * beta * overdrive * boost
    gds = bare * channel_length

    return current, gm, gds


class _ChannelDevice:
    """
    Shared Newton state for a three-terminal channel.

    Polarity is +1 for N and -1 for P. The stored voltages are the
    evaluation point. A P device flips those voltages before the
    forward equation and flips the current back.
    """

    def __init__(self, reference, gate, drain, source, polarity):
        self.reference = reference
        self.gate = gate
        self.drain = drain
        self.source = source
        self.polarity = polarity
        self.vg = 0.0
        self.vd = 0.0
        self.vs = 0.0

    def companions(self):
        drain_node, source_node, _amps, gm, gds, equivalent = (
            self._linear()
        )
        stamps = []
        resistor = _resistor(
            f"@{self.reference}.ds", drain_node, source_node, gds
        )

        if resistor is not None:
            stamps.append(resistor)

        if gm >= _TINY_CONDUCTANCE:
            stamps.append((
                "G", f"@{self.reference}.gm",
                source_node, drain_node, self.gate, source_node, gm,
            ))

        source = _current(
            f"@{self.reference}.id",
            source_node, drain_node, equivalent,
        )

        if source is not None:
            stamps.append(source)

        return stamps

    def converged(self, voltages):
        return (
            abs(_volts(voltages, self.gate) - self.vg) < _VOLTAGE_TOLERANCE
            and abs(_volts(voltages, self.drain) - self.vd)
            < _VOLTAGE_TOLERANCE
            and abs(_volts(voltages, self.source) - self.vs)
            < _VOLTAGE_TOLERANCE
        )

    def update(self, voltages):
        self.vg = _volts(voltages, self.gate)
        self.vd = _volts(voltages, self.drain)
        self.vs = _volts(voltages, self.source)

    def _linear(self):
        vgs = self.polarity * (self.vg - self.vs)
        vds = self.polarity * (self.vd - self.vs)
        drain_node = self.drain
        source_node = self.source

        if vds < 0.0:
            vgs = self.polarity * (self.vg - self.vd)
            vds = -vds
            drain_node = self.source
            source_node = self.drain

        current, gm, gds = self._forward(vgs, vds)
        equivalent = self.polarity * (
            current - gm * vgs - gds * vds
        )

        return drain_node, source_node, current, gm, gds, equivalent

    def _forward(self, vgs, vds):
        raise NotImplementedError


class MosfetDevice(_ChannelDevice):
    """
    Level-1 MOSFET. Bulk is the source. Positive current enters the drain.
    """

    def __init__(
            self, reference, gate, drain, source,
            threshold, kp, channel_length, polarity):
        super().__init__(reference, gate, drain, source, polarity)
        self.threshold = polarity * threshold
        self.kp = kp
        self.channel_length = channel_length

    def solved_current(self, voltages):
        saved = (self.vg, self.vd, self.vs)
        self.update(voltages)
        _drain_node, _source_node, current, _gm, _gds, _equivalent = (
            self._linear()
        )
        into_drain = self.polarity * current

        if _drain_node != self.drain:
            into_drain = -into_drain

        self.vg, self.vd, self.vs = saved

        return into_drain

    def _forward(self, vgs, vds):
        return _mos_forward(
            vgs, vds, self.threshold, self.kp, self.channel_length
        )


class JfetDevice(_ChannelDevice):
    """
    Shockley JFET plus the two gate junctions.

    Positive channel current enters the drain. The reported current
    includes the gate-drain junction.
    """

    def __init__(
            self, reference, gate, drain, source,
            threshold, beta, channel_length, saturation, polarity):
        super().__init__(reference, gate, drain, source, polarity)
        self.threshold = threshold
        self.beta = beta
        self.channel_length = channel_length
        self.saturation = saturation
        self.vgs = 0.0
        self.vgd = 0.0

    def companions(self):
        stamps = super().companions()
        stamps.extend(self._junction(self.source, self.vgs, "s"))
        stamps.extend(self._junction(self.drain, self.vgd, "d"))

        return stamps

    def converged(self, voltages):
        vgs, vgd = self._gates(voltages)

        return (
            super().converged(voltages)
            and abs(vgs - self.vgs) < _VOLTAGE_TOLERANCE
            and abs(vgd - self.vgd) < _VOLTAGE_TOLERANCE
        )

    def update(self, voltages):
        super().update(voltages)
        vgs, vgd = self._gates(voltages)
        self.vgs = self._move_gate(vgs, self.vgs)
        self.vgd = self._move_gate(vgd, self.vgd)

    def solved_current(self, voltages):
        saved = (self.vg, self.vd, self.vs, self.vgs, self.vgd)
        self.vg = _volts(voltages, self.gate)
        self.vd = _volts(voltages, self.drain)
        self.vs = _volts(voltages, self.source)
        drain_node, _source_node, current, _gm, _gds, _equivalent = (
            self._linear()
        )
        into_drain = self.polarity * current

        if drain_node != self.drain:
            into_drain = -into_drain

        _vgs, vgd = self._gates(voltages)
        diode, _conductance = _shockley(vgd, self.saturation, 1.0)
        into_gate = self.polarity * diode
        self.vg, self.vd, self.vs, self.vgs, self.vgd = saved

        return into_drain - into_gate

    def _forward(self, vgs, vds):
        return _jfet_forward(
            vgs, vds, self.threshold, self.beta, self.channel_length
        )

    def _gates(self, voltages):
        vg = _volts(voltages, self.gate)

        return (
            self.polarity * (vg - _volts(voltages, self.source)),
            self.polarity * (vg - _volts(voltages, self.drain)),
        )

    def _move_gate(self, target, previous):
        if target <= 0.0 and previous <= 0.0:
            return target

        return _step(target, previous, _JUNCTION_STEP)

    def _junction(self, other, voltage, suffix):
        current, conductance = _shockley(voltage, self.saturation, 1.0)
        stamps = []
        resistor = _resistor(
            f"@{self.reference}.g{suffix}",
            self.gate, other, conductance,
        )

        if resistor is not None:
            stamps.append(resistor)
            equivalent = current - conductance * voltage
        else:
            equivalent = current

        source = _current(
            f"@{self.reference}.j{suffix}",
            other, self.gate, self.polarity * equivalent,
        )

        if source is not None:
            stamps.append(source)

        return stamps


class LogicDevice:
    """
    Behavioural gate or comparator.

    The output is a voltage source to ground. A gate's high level is
    V(VCC) and its low level is 0 V, which is what the SPICE expression
    does. The comparator's high level is V+ and its low level is V-.
    Neither model draws supply current.
    """

    def __init__(self, reference, logic, output, nodes):
        self.reference = reference
        self.logic = logic
        self.output = output
        self.nodes = nodes
        self.level = 0.0

    def companions(self):
        return [("V", self.reference, self.output, "0", self.level)]

    def converged(self, voltages):
        return abs(self._level(voltages) - self.level) < 1e-6

    def update(self, voltages):
        self.level = self._level(voltages)

    def solved_current(self, voltages):
        return None

    def _level(self, voltages):
        if self.logic == "comp":
            if _volts(voltages, self.nodes["inp"]) > _volts(
                    voltages, self.nodes["inn"]):
                return _volts(voltages, self.nodes["vp"])

            return _volts(voltages, self.nodes["vn"])

        vcc = _volts(voltages, self.nodes["vcc"])
        gnd = _volts(voltages, self.nodes["gnd"])
        mid = 0.5 * (vcc + gnd)
        above_a = _volts(voltages, self.nodes["a"]) > mid
        above_b = _volts(voltages, self.nodes.get("b", "0")) > mid

        if self.logic == "not":
            return vcc if _volts(voltages, self.nodes["a"]) < mid else 0.0

        if self.logic == "buf":
            return vcc if above_a else 0.0

        if self.logic == "and":
            return vcc if above_a and above_b else 0.0

        if self.logic == "or":
            return vcc if above_a or above_b else 0.0

        if self.logic == "nand":
            return 0.0 if above_a and above_b else vcc

        if self.logic == "nor":
            return vcc if not above_a and not above_b else 0.0

        return vcc if above_a != above_b else 0.0


class ClampDevice:
    """
    Limited op-amp clamp. The unloaded voltage is held between the rails.

    Headroom is measured from V+ downward and from V- upward. The
    series output resistor is stamped separately.
    """

    def __init__(self, reference, pre, filt, vp, vn, head_high, head_low):
        self.reference = reference
        self.pre = pre
        self.filt = filt
        self.vp = vp
        self.vn = vn
        self.head_high = head_high
        self.head_low = head_low
        self.level = 0.0

    def companions(self):
        return [("V", self.reference, self.pre, "0", self.level)]

    def converged(self, voltages):
        return abs(self._clamp(voltages) - self.level) < 1e-6

    def update(self, voltages):
        self.level = self._clamp(voltages)

    def solved_current(self, voltages):
        return None

    def _clamp(self, voltages):
        low = _volts(voltages, self.vn) + self.head_low
        high = _volts(voltages, self.vp) - self.head_high
        filt = _volts(voltages, self.filt)

        if low > high:
            return 0.5 * (low + high)

        if filt < low:
            return low

        if filt > high:
            return high

        return filt
