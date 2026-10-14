"""Metrics computed on a simulation result (a DataFrame with columns
t_s, temp, target, heater, t_out, door).

Energy: the heater's electrical power is not known (incubator-telemetry-analysis could
only identify a = P/C), so energy is reported as ``heater_on_min`` and as ``heating_c``
= a × on-time, the temperature rise the heater delivered in °C, which is proportional to
energy. ``energy_kwh_at`` converts it for an *assumed* power; label it as such.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Metrics:
    time_to_target_min: float | None  # first time |T − target| ≤ band/2 after t_from
    overshoot_c: float  # max(T − target) after first reaching the band, 0 if never above
    undershoot_c: float  # max(target − T) after first reaching the band (door dips show here)
    heater_on_min: float
    heating_c: float  # a × on-time
    switches: int  # OFF→ON transitions
    rms_error_c: float  # over the evaluation span, after first reaching the band
    in_band_fraction: float  # share of the evaluation span inside ±band/2
    final_error_c: float  # mean error over the last ``tail_min`` minutes

    def as_dict(self) -> dict[str, float | int | None]:
        return asdict(self)


def switch_count(heater: pd.Series) -> int:
    h = heater.astype(bool).to_numpy()
    if h.size == 0:
        return 0
    return int(np.count_nonzero(h[1:] & ~h[:-1]) + (1 if h[0] else 0))


def compute(
    df: pd.DataFrame,
    a: float,
    band: float = 0.4,
    t_from_s: float = 0.0,
    tail_min: float = 30.0,
) -> Metrics:
    """Score one run from ``t_from_s`` onwards (use it to skip to a setpoint change)."""
    sub = df[df["t_s"] >= t_from_s].reset_index(drop=True)
    dt_s = float(sub["t_s"].iloc[1] - sub["t_s"].iloc[0]) if len(sub) > 1 else 1.0
    err = (sub["temp"] - sub["target"]).to_numpy()
    half = band / 2
    inside = np.abs(err) <= half
    first = int(np.argmax(inside)) if inside.any() else None
    ttt = None if first is None else float(sub["t_s"].iloc[first] - t_from_s) / 60.0
    if first is None:
        after = err
    else:
        after = err[first:]
    overshoot = float(max(after.max(), 0.0))
    undershoot = float(max(-after.min(), 0.0))
    on_min = float(sub["heater"].sum() * dt_s / 60.0)
    tail = sub[sub["t_s"] >= sub["t_s"].iloc[-1] - tail_min * 60.0]
    return Metrics(
        time_to_target_min=ttt,
        overshoot_c=round(overshoot, 3),
        undershoot_c=round(undershoot, 3),
        heater_on_min=round(on_min, 2),
        heating_c=round(a * on_min, 2),
        switches=switch_count(sub["heater"]),
        rms_error_c=round(float(np.sqrt(np.mean(after**2))), 3),
        in_band_fraction=round(float(inside.mean()), 3),
        final_error_c=round(float((tail["temp"] - tail["target"]).mean()), 3),
    )


def energy_kwh_at(heater_on_min: float, power_w: float) -> float:
    """kWh for an assumed heater power (illustrative; the real wattage is not in the data)."""
    return heater_on_min / 60.0 * power_w / 1000.0
