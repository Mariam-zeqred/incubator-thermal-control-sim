"""The simulation loop: plant + controller + disturbances + the firmware's interlock.

The loop runs at the plant's ``dt_s`` (1 s by default, the firmware's control period). The
controller is asked once per ``controller.period_s``. The sensor reading handed to the
controller is quantised to 0.01 °C like the SHT31 readings in the real export.

Interlock (applied outside the controller, as the firmware's Interlock module does):
* door open  -> heater off, controller told it is locked out (if it has ``lockout``);
* temp ≥ cutoff (40 °C, Config.h THERMAL_CUTOFF_C) -> heater off and latched until the
  chamber is ``cutoff_rearm`` below the cutoff (the real firmware also waits for an
  operator acknowledgement; the simulator re-arms on temperature alone).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from thermosim.controllers.base import Controller
from thermosim.disturbances import ConstantAmbient, DoorSchedule
from thermosim.plant import Plant


@dataclass
class Scenario:
    """What happens during a run. ``targets`` is a list of (from_s, target °C) steps."""

    name: str
    duration_s: float
    t0: float  # initial chamber temperature
    targets: list[tuple[float, float]]
    ambient: object = field(default_factory=ConstantAmbient)
    door: DoorSchedule = field(default_factory=DoorSchedule)
    description: str = ""

    def target_at(self, t_s: float) -> float:
        value = self.targets[0][1]
        for start, tgt in self.targets:
            if t_s >= start:
                value = tgt
        return value


def run(
    plant: Plant,
    controller: Controller,
    scenario: Scenario,
    cutoff_c: float = 40.0,
    cutoff_rearm_c: float = 0.5,
    sensor_step_c: float = 0.01,
) -> pd.DataFrame:
    """Simulate one scenario and return a tidy frame, one row per plant step."""
    plant.reset(scenario.t0)
    controller.reset()
    dt = plant.dt_s
    n = int(round(scenario.duration_s / dt))
    t = np.arange(n) * dt
    temp = np.empty(n)
    heater = np.zeros(n, dtype=np.int8)
    target = np.empty(n)
    t_out = np.empty(n)
    door = np.zeros(n, dtype=np.int8)
    locked = np.zeros(n, dtype=np.int8)

    next_decision = 0.0
    u = False
    latched = False
    for i in range(n):
        ti = float(t[i])
        tgt = scenario.target_at(ti)
        amb = scenario.ambient.at(ti)
        door_open = scenario.door.open(ti)
        reading = round(plant.temp / sensor_step_c) * sensor_step_c

        if reading >= cutoff_c:
            latched = True
        elif latched and reading <= cutoff_c - cutoff_rearm_c:
            latched = False
        blocked = door_open or latched

        if ti >= next_decision - 1e-9:
            if blocked:
                if hasattr(controller, "lockout"):
                    controller.lockout(ti)
                u = False
            else:
                u = bool(controller.decide(ti, reading, tgt))
            next_decision += controller.period_s
        elif blocked:
            u = False

        temp[i] = plant.temp
        heater[i] = int(u)
        target[i] = tgt
        t_out[i] = amb
        door[i] = int(door_open)
        locked[i] = int(blocked)
        plant.step(1.0 if u else 0.0, amb, scenario.door.gain(ti))

    return pd.DataFrame(
        {
            "t_s": t,
            "temp": temp,
            "target": target,
            "heater": heater,
            "t_out": t_out,
            "door": door,
            "locked": locked,
        }
    )
