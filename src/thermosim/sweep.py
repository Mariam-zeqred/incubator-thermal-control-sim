"""Parameter sweep for the firmware's two anticipation constants.

The real firmware switches the heater off when the *projected* temperature
(reading + rise rate × ``coast_lead_s``) exceeds ``target + band/2 − anticipation``. Both
numbers live in ``Config.h`` (0.1 °C and 200 s in FW 1.1.x). This module runs the firmware
logic on a cold start for a grid of the two constants and records the overshoot and the
final bias of each run, so the two constants have a figure behind them instead of a guess.

Only the firmware controller is swept; the plant, scenario and interlock are the ones used
everywhere else in the repo.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from thermosim import metrics, simulate
from thermosim.controllers import FirmwareHysteresis
from thermosim.plant import load_params, make_plant
from thermosim.simulate import Scenario

ANTICIPATIONS = (0.0, 0.05, 0.1, 0.2, 0.3)
COAST_LEADS_S = (0.0, 100.0, 200.0, 300.0, 400.0)


@dataclass(frozen=True)
class SweepResult:
    anticipations: tuple[float, ...]
    coast_leads_s: tuple[float, ...]
    overshoot_c: np.ndarray  # [i_anticipation, j_coast]
    final_error_c: np.ndarray
    time_to_target_min: np.ndarray
    switches: np.ndarray

    def as_dict(self) -> dict:
        return {
            "anticipations_c": list(self.anticipations),
            "coast_leads_s": list(self.coast_leads_s),
            "overshoot_c": np.round(self.overshoot_c, 3).tolist(),
            "final_error_c": np.round(self.final_error_c, 3).tolist(),
            "time_to_target_min": np.round(self.time_to_target_min, 1).tolist(),
            "switches": self.switches.tolist(),
        }

    def at(self, anticipation: float, coast_lead_s: float) -> dict[str, float]:
        i = self.anticipations.index(anticipation)
        j = self.coast_leads_s.index(coast_lead_s)
        return {
            "overshoot_c": float(self.overshoot_c[i, j]),
            "final_error_c": float(self.final_error_c[i, j]),
            "time_to_target_min": float(self.time_to_target_min[i, j]),
            "switches": int(self.switches[i, j]),
        }


def sweep_firmware(
    scenario: Scenario,
    plant_name: str = "heater_lag",
    params: dict | None = None,
    anticipations: tuple[float, ...] = ANTICIPATIONS,
    coast_leads_s: tuple[float, ...] = COAST_LEADS_S,
    t_from_s: float = 0.0,
) -> SweepResult:
    """Run ``FirmwareHysteresis`` with every (anticipation, coast lead) pair on one scenario."""
    params = params or load_params()
    shape = (len(anticipations), len(coast_leads_s))
    over = np.empty(shape)
    final = np.empty(shape)
    ttt = np.full(shape, np.nan)
    sw = np.empty(shape, dtype=int)
    for i, antic in enumerate(anticipations):
        for j, coast in enumerate(coast_leads_s):
            plant = make_plant(plant_name, params)
            ctl = FirmwareHysteresis(anticipation=antic, coast_lead_s=coast)
            df = simulate.run(plant, ctl, scenario)
            m = metrics.compute(df, plant.a, t_from_s=t_from_s)
            over[i, j] = m.overshoot_c
            final[i, j] = m.final_error_c
            if m.time_to_target_min is not None:
                ttt[i, j] = m.time_to_target_min
            sw[i, j] = m.switches
    return SweepResult(tuple(anticipations), tuple(coast_leads_s), over, final, ttt, sw)
