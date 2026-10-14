"""Thermal models of the incubator chamber.

All three plants expose the same interface: ``step(u, t_out, loss_gain)`` advances the
model by ``dt_s`` seconds with heater command ``u`` in [0, 1] (1 = relay on), ambient
``t_out`` in °C and a multiplier on the heat-loss term (1 = door shut), and returns the
new chamber temperature. ``temp`` is the current chamber temperature.

Units follow ``data/model_params.json`` from incubator-telemetry-analysis: temperatures in
°C, rates per *minute*, so the models are integrated with ``dt_s / 60``.

* :class:`FirstOrderPlant`   dT/dt = a·u(t − d) − b·(T − T_out)              fitted, dead time d
* :class:`HeaterLagPlant`    dE/dt = (a·u − E)/τ_h ; dT/dt = E − b·(T − T_out)  fitted, second order
* :class:`ChamberWallPlant`  chamber + wall, two capacities                   DERIVED, not fitted

Only ``a = P/C`` and ``b = 1/(RC)`` are identifiable from the temperature trace; the heater
power P is unknown, so "energy" elsewhere in this repo is reported as heater-on time and as
the heating a·(on time) in °C, which is proportional to energy.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

PARAMS_PATH = Path(__file__).resolve().parents[2] / "data" / "model_params.json"


def load_params(path: Path = PARAMS_PATH) -> dict:
    """Read the fitted parameters exported by incubator-telemetry-analysis."""
    return json.loads(Path(path).read_text())


class Plant(Protocol):
    temp: float
    dt_s: float

    def step(self, u: float, t_out: float, loss_gain: float = 1.0) -> float: ...

    def reset(self, temp: float) -> None: ...


@dataclass
class FirstOrderPlant:
    """Lumped chamber with a pure dead time on the heater input.

    Default values are the first-order fit on 2026-10-03 (RMSE 0.29 °C, R² 0.993).
    """

    a: float = 0.5539  # °C/min at full heater power
    b: float = 0.0101  # 1/min, inverse time constant (τ ≈ 99 min)
    dead_time_s: float = 210.0
    dt_s: float = 1.0
    temp: float = 27.0
    _queue: deque[float] = field(default_factory=deque, repr=False)

    def __post_init__(self) -> None:
        self.reset(self.temp)

    @property
    def tau_min(self) -> float:
        return 1.0 / self.b

    def reset(self, temp: float) -> None:
        self.temp = temp
        n = max(int(round(self.dead_time_s / self.dt_s)), 0)
        self._queue = deque([0.0] * n, maxlen=n or None)
        self._n_delay = n

    def step(self, u: float, t_out: float, loss_gain: float = 1.0) -> float:
        if self._n_delay:
            u_eff = self._queue[0]  # what was commanded dead_time_s ago
            self._queue.append(u)
        else:
            u_eff = u
        dt_min = self.dt_s / 60.0
        self.temp += dt_min * (self.a * u_eff - self.b * loss_gain * (self.temp - t_out))
        return self.temp

    @classmethod
    def from_params(cls, params: dict, **kw: float) -> FirstOrderPlant:
        p = params["first_order"]
        return cls(a=p["a_c_per_min"], b=p["b_per_min"], dead_time_s=p["dead_time_s"], **kw)


@dataclass
class HeaterLagPlant:
    """Second-order "heater-lag" model: the heater element warms with time constant τ_h,
    the chamber follows. Default values are the fit on 2026-10-03 (RMSE 0.16 °C, R² 0.998);
    the element's lag reproduces the 3–4 minute post-switch rise without a dead time.
    """

    a: float = 0.5908
    tau_h_min: float = 4.9175
    b: float = 0.0111
    dt_s: float = 1.0
    temp: float = 27.0
    e: float = 0.0  # heating rate currently delivered by the element, °C/min

    def __post_init__(self) -> None:
        self.reset(self.temp)

    @property
    def tau_min(self) -> float:
        return 1.0 / self.b

    def reset(self, temp: float) -> None:
        self.temp = temp
        self.e = 0.0

    def step(self, u: float, t_out: float, loss_gain: float = 1.0) -> float:
        dt_min = self.dt_s / 60.0
        # exact update of the element state over one step (linear first-order filter)
        k = math.exp(-dt_min / self.tau_h_min)
        self.e = self.a * u + (self.e - self.a * u) * k
        self.temp += dt_min * (self.e - self.b * loss_gain * (self.temp - t_out))
        return self.temp

    @classmethod
    def from_params(cls, params: dict, **kw: float) -> HeaterLagPlant:
        p = params["second_order"]
        return cls(a=p["a_c_per_min"], tau_h_min=p["tau_h_min"], b=p["b_per_min"], **kw)


@dataclass
class ChamberWallPlant:
    """Chamber air + wall, two thermal capacities (total capacity normalised to 1).

        (1−f)·dT/dt  = a·u − k_cw·(T − T_w) − b·(g−1)·(T − T_out)
        f·dT_w/dt    = k_cw·(T − T_w) − k_wo·(T_w − T_out)

    ``f`` is the wall's share of the capacity, ``k_cw = 1/tau_cw_min`` the air↔wall
    exchange, ``g`` the door loss multiplier, and ``k_wo`` is chosen so the steady-state
    gain equals the fitted a/b. The parameters are NOT fitted: the real trace identifies
    only a and b, and incubator-telemetry-analysis found that its second time constant
    belongs to the heater element, not the wall. This model is a robustness check: the air
    responds faster (initial rate a/(1−f)) and the wall drags behind, which is what a
    controller tuned on the simple model must survive. Values are illustrative.
    """

    a: float = 0.5539
    b: float = 0.0101
    wall_fraction: float = 0.7
    tau_cw_min: float = 8.0
    dt_s: float = 1.0
    temp: float = 27.0
    t_wall: float = 27.0

    def __post_init__(self) -> None:
        if not 0.0 < self.wall_fraction < 1.0:
            raise ValueError("wall_fraction must be in (0, 1)")
        if self.tau_cw_min * self.b >= 1.0:
            raise ValueError("tau_cw_min must be shorter than the fitted time constant 1/b")
        self.reset(self.temp)

    @property
    def tau_min(self) -> float:
        return 1.0 / self.b

    @property
    def k_cw(self) -> float:
        return 1.0 / self.tau_cw_min

    @property
    def k_wo(self) -> float:
        return 1.0 / (1.0 / self.b - self.tau_cw_min)

    def reset(self, temp: float) -> None:
        self.temp = temp
        self.t_wall = temp

    def step(self, u: float, t_out: float, loss_gain: float = 1.0) -> float:
        dt_min = self.dt_s / 60.0
        c_air = 1.0 - self.wall_fraction
        direct = self.b * (loss_gain - 1.0) * (self.temp - t_out)
        flow_cw = self.k_cw * (self.temp - self.t_wall)
        d_temp = (self.a * u - flow_cw - direct) / c_air
        d_wall = (flow_cw - self.k_wo * (self.t_wall - t_out)) / self.wall_fraction
        self.temp += dt_min * d_temp
        self.t_wall += dt_min * d_wall
        return self.temp

    @classmethod
    def from_params(cls, params: dict, **kw: float) -> ChamberWallPlant:
        p = params["first_order"]
        return cls(a=p["a_c_per_min"], b=p["b_per_min"], **kw)


PLANTS = {
    "first_order": FirstOrderPlant,
    "heater_lag": HeaterLagPlant,
    "chamber_wall": ChamberWallPlant,
}


def make_plant(name: str, params: dict | None = None, **kw: float) -> Plant:
    """Build a plant by name from the fitted parameter file."""
    params = params or load_params()
    return PLANTS[name].from_params(params, **kw)
