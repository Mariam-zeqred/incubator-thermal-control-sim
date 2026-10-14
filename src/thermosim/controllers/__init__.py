"""Heater controllers. Each one implements :class:`Controller`:

    decide(t_s, temp, target) -> bool      heater relay on/off for the next control period
    reset()                                 forget all internal state

The simulator calls ``decide`` once per ``period_s`` and applies the interlock (door open,
over-temperature cut-off) *outside* the controller, exactly as the firmware's Interlock
module does, so every controller is compared under the same safety rules.
"""

from thermosim.controllers.base import Controller
from thermosim.controllers.mpc import MPCSketch
from thermosim.controllers.onoff import FirmwareHysteresis, PlainHysteresis
from thermosim.controllers.pid import PIDRelay, tune_pid_simc

__all__ = [
    "Controller",
    "FirmwareHysteresis",
    "MPCSketch",
    "PIDRelay",
    "PlainHysteresis",
    "tune_pid_simc",
]
