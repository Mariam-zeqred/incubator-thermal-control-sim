"""PID with anti-windup, quantised to relay duty by time-proportioning.

The PID runs once per ``window_s`` and outputs a duty in [0, 1]. The relay is then held ON
for ``duty · window_s`` seconds at the start of the window, rounded to the controller
period and to ``min_pulse_s`` (a pulse shorter than that is dropped, a gap shorter than
that is filled), which is how a slow relay-driven heater gets a "proportional" output.

Anti-windup is conditional integration: the integral stops accumulating while the output
is saturated and the error pushes further into saturation. The derivative acts on the
measurement, not the error, so a setpoint step does not kick the relay.

``tune_pid_simc`` gives Skogestad's SIMC rules for a first-order plant with dead time,
which is exactly the model incubator-telemetry-analysis fitted (K = a/b, τ = 1/b, θ = d).
"""

from __future__ import annotations

from dataclasses import dataclass, field


def tune_pid_simc(a: float, b: float, dead_time_s: float, tau_c_min: float | None = None):
    """SIMC PI tuning for dT/dt = a·u − b·(T − T_out), dead time d.

    Plant: gain K = a/b (°C per unit duty), time constant τ = 1/b (min), delay θ = d (min).
    Kc = τ / (K (τ_c + θ)),  Ti = min(τ, 4 (τ_c + θ)),  with τ_c = θ (the "tight" choice)
    unless given. Returns (kp, ti_min, td_min) with td = 0 (PI), as SIMC recommends for a
    first-order plant.
    """
    k = a / b
    tau = 1.0 / b
    theta = max(dead_time_s / 60.0, 1e-6)
    tau_c = theta if tau_c_min is None else tau_c_min
    kp = tau / (k * (tau_c + theta))
    ti = min(tau, 4.0 * (tau_c + theta))
    return kp, ti, 0.0


@dataclass
class PIDRelay:
    kp: float = 0.26  # duty per °C  (SIMC on the first-order fit)
    ti_min: float = 28.0  # integral time, min
    td_min: float = 0.0  # derivative time, min
    window_s: float = 120.0  # time-proportioning window
    min_pulse_s: float = 10.0
    period_s: float = 1.0
    name: str = "PID relay"

    _integral: float = field(default=0.0, repr=False)
    _prev_temp: float | None = field(default=None, repr=False)
    _window_start: float = field(default=0.0, repr=False)
    _on_until: float = field(default=0.0, repr=False)
    _initialised: bool = field(default=False, repr=False)
    last_duty: float = field(default=0.0, repr=False)

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_temp = None
        self._window_start = 0.0
        self._on_until = 0.0
        self._initialised = False
        self.last_duty = 0.0

    def compute_duty(self, t_s: float, temp: float, target: float) -> float:
        """One PID evaluation; returns the duty for the next window."""
        err = target - temp
        dt_min = self.window_s / 60.0
        p = self.kp * err
        d = 0.0
        if self.td_min > 0 and self._prev_temp is not None:
            d = -self.kp * self.td_min * (temp - self._prev_temp) / dt_min
        self._prev_temp = temp
        unsat = p + self._integral + d
        saturated_high = unsat >= 1.0 and err > 0
        saturated_low = unsat <= 0.0 and err < 0
        if self.ti_min > 0 and not (saturated_high or saturated_low):
            self._integral += self.kp * err * dt_min / self.ti_min
            self._integral = min(max(self._integral, 0.0), 1.0)
        duty = p + self._integral + d
        return min(max(duty, 0.0), 1.0)

    def quantise(self, duty: float) -> float:
        """Seconds of relay ON in the window, respecting the minimum pulse and gap."""
        on_s = round(duty * self.window_s / self.period_s) * self.period_s
        if on_s < self.min_pulse_s:
            on_s = 0.0
        elif self.window_s - on_s < self.min_pulse_s:
            on_s = self.window_s
        return on_s

    def decide(self, t_s: float, temp: float, target: float) -> bool:
        if not self._initialised or t_s - self._window_start >= self.window_s - 1e-9:
            self._initialised = True
            self._window_start = t_s
            self.last_duty = self.compute_duty(t_s, temp, target)
            self._on_until = t_s + self.quantise(self.last_duty)
        return t_s < self._on_until - 1e-9
