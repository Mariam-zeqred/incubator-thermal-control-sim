"""Model-predictive control *sketch*.

Every ``window_s`` the controller enumerates every duty sequence over a horizon of ``horizon``
windows with ``levels`` duty levels (e.g. 5⁴ = 625 sequences), predicts the chamber with the
first-order model it was given, scores

    J = Σ (T_k − target)²  +  λ_u · Σ u_k  +  λ_sw · Σ |u_k − u_{k−1}|

and applies the first duty of the best sequence by time-proportioning (same quantiser as
the PID). A bias term (measured − predicted) is carried forward so that a wrong ambient or
a wrong gain is corrected like an integrator would, which is the usual cheap trick in
practice.

The internal model is the heater-lag fit (element state E tracked from the duties the
controller itself applied, so no state estimator is needed); set ``tau_h_min = 0`` for a plain
first-order model. It is a sketch: exhaustive enumeration instead of a QP solver, no
constraints beyond 0 ≤ u ≤ 1, no noise model. It is here to show what a
controller that *knows the model* can do with the same relay, not as a deployable design.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class MPCSketch:
    a: float = 0.5908
    b: float = 0.0111
    tau_h_min: float = 4.9175  # heater element lag; 0 = first-order internal model
    t_out_assumed: float = 27.2
    substeps: int = 12  # integration sub-steps per window
    horizon: int = 4
    levels: int = 5
    lambda_u: float = 0.02  # cost per unit duty-window ("energy")
    lambda_sw: float = 0.05  # cost per unit change of duty ("switching")
    window_s: float = 120.0
    min_pulse_s: float = 10.0
    period_s: float = 1.0
    name: str = "MPC sketch"

    _window_start: float = field(default=0.0, repr=False)
    _on_until: float = field(default=0.0, repr=False)
    _initialised: bool = field(default=False, repr=False)
    _predicted: float | None = field(default=None, repr=False)
    _bias: float = field(default=0.0, repr=False)
    _prev_duty: float = field(default=0.0, repr=False)
    _e: float = field(default=0.0, repr=False)  # element state, °C/min
    _seqs: np.ndarray = field(default=None, repr=False)
    last_duty: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        grid = np.linspace(0.0, 1.0, self.levels)
        self._seqs = np.array(list(itertools.product(grid, repeat=self.horizon)))
        self.reset()

    def reset(self) -> None:
        self._window_start = 0.0
        self._on_until = 0.0
        self._initialised = False
        self._predicted = None
        self._bias = 0.0
        self._prev_duty = 0.0
        self._e = 0.0
        self.last_duty = 0.0

    def _advance(self, temps: np.ndarray, e: np.ndarray, duties: np.ndarray):
        """One window of the internal model for every candidate (Euler sub-steps)."""
        h = self.window_s / 60.0 / self.substeps
        k_e = math.exp(-h / self.tau_h_min) if self.tau_h_min > 0 else 0.0
        for _ in range(self.substeps):
            e = self.a * duties + (e - self.a * duties) * k_e
            temps = temps + h * (e - self.b * (temps - self.t_out_assumed))
        return temps, e

    def predict(self, temp: float, duties: np.ndarray) -> np.ndarray:
        """Chamber temperature at the end of each window, for every candidate sequence."""
        temps = np.full(duties.shape[0], temp, dtype=float)
        e = np.full(duties.shape[0], self._e, dtype=float)
        out = np.empty_like(duties)
        for k in range(duties.shape[1]):
            temps, e = self._advance(temps, e, duties[:, k])
            temps = temps + self._bias
            out[:, k] = temps
        return out

    def plan(self, temp: float, target: float) -> float:
        preds = self.predict(temp, self._seqs)
        tracking = ((preds - target) ** 2).sum(axis=1)
        energy = self.lambda_u * self._seqs.sum(axis=1)
        switching = self.lambda_sw * (
            np.abs(self._seqs[:, 0] - self._prev_duty)
            + np.abs(np.diff(self._seqs, axis=1)).sum(axis=1)
        )
        best = int(np.argmin(tracking + energy + switching))
        duty = float(self._seqs[best, 0])
        # one-step bias update: what the model said would happen vs what did
        self._predicted = float(preds[best, 0]) - self._bias
        return duty

    def quantise(self, duty: float) -> float:
        on_s = round(duty * self.window_s / self.period_s) * self.period_s
        if on_s < self.min_pulse_s:
            on_s = 0.0
        elif self.window_s - on_s < self.min_pulse_s:
            on_s = self.window_s
        return on_s

    def decide(self, t_s: float, temp: float, target: float) -> bool:
        if not self._initialised or t_s - self._window_start >= self.window_s - 1e-9:
            if self._initialised and self._predicted is not None:
                # low-pass the bias so one noisy window does not swing the plan
                self._bias = 0.5 * self._bias + 0.5 * (temp - self._predicted)
            self._initialised = True
            self._window_start = t_s
            if self._initialised:
                # roll the element state forward with the duty actually applied
                _, e = self._advance(np.zeros(1), np.array([self._e]), np.array([self._prev_duty]))
                self._e = float(e[0])
            self.last_duty = self.plan(temp, target)
            self._prev_duty = self.last_duty
            self._on_until = t_s + self.quantise(self.last_duty)
        return t_s < self._on_until - 1e-9
