"""Disturbances: ambient temperature over time and door openings.

``Ambient`` objects answer ``at(t_s) -> °C``. ``DoorSchedule`` answers ``open(t_s) -> bool``
and supplies the loss multiplier used while the door is open.
"""

from __future__ import annotations

import csv
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

TRACE_PATH = Path(__file__).resolve().parents[2] / "data" / "incubator_2026-10-03.csv"


@dataclass(frozen=True)
class ConstantAmbient:
    value: float = 27.2

    def at(self, t_s: float) -> float:
        return self.value


@dataclass
class TraceAmbient:
    """Ambient from the real ``tempOut`` column of the 2026-10-03 export (15 s samples,
    5.7 h, 27.2–28.3 °C). Values are held between samples; past the end the last value is
    held. ``scale`` multiplies the deviation from the first sample to make the drift
    larger than the one the real day had (labelled as such wherever it is used).
    """

    times: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    scale: float = 1.0
    offset: float = 0.0

    @classmethod
    def from_csv(cls, path: Path = TRACE_PATH, scale: float = 1.0, offset: float = 0.0):
        times: list[float] = []
        values: list[float] = []
        with Path(path).open() as fh:
            for row in csv.DictReader(fh):
                times.append(float(row["t_s"]))
                values.append(float(row["temp_out"]))
        return cls(times, values, scale, offset)

    @property
    def duration_s(self) -> float:
        return self.times[-1] if self.times else 0.0

    def at(self, t_s: float) -> float:
        i = bisect_right(self.times, t_s) - 1
        i = min(max(i, 0), len(self.values) - 1)
        base = self.values[0]
        return base + self.scale * (self.values[i] - base) + self.offset


def load_trace(path: Path = TRACE_PATH) -> list[dict[str, float]]:
    """The whole real trace as a list of rows (t_s, temp, temp_out, target, heater, door)."""
    with Path(path).open() as fh:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(fh)]


@dataclass(frozen=True)
class DoorSchedule:
    """Door openings as (start_s, duration_s) pairs.

    ``loss_gain`` multiplies the chamber's heat-loss coefficient while open. The value is
    illustrative: no door-open data exists in the real trace (the door stayed shut), the
    firmware README only says door recoveries took 17–43 minutes.
    """

    openings: tuple[tuple[float, float], ...] = ()
    loss_gain: float = 10.0

    def open(self, t_s: float) -> bool:
        return any(s <= t_s < s + d for s, d in self.openings)

    def gain(self, t_s: float) -> float:
        return self.loss_gain if self.open(t_s) else 1.0
