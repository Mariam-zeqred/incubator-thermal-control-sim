"""On/off (relay) controllers.

:class:`FirmwareHysteresis` re-implements the heater decision of the queen-bee-incubator
firmware (``firmware/QueenBeeIncubator_V2/Control.cpp``, constants from ``Config.h``, read
from the public repo on 2026-10-14). Per control tick (1 s):

1. thresholds: ``lo = target − band/2``; ``hi = target + band/2 − anticipation`` (``hi`` is
   kept at least 0.05 °C above ``lo``);
2. rate of rise from a 60-sample window of readings: ``(T_now − T_oldest) / span``, zero
   until 20 samples exist, clamped to ≥ 0 (falls are ignored);
3. ``projected = T + rate · coast_lead_s`` (the "coast" the chamber will still make);
4. logical state: ON if ``projected < lo``, OFF if ``projected > hi``, else unchanged;
5. minimum OFF time: an OFF→ON change is refused for ``min_off_s`` after switching off;
   switching off is never delayed;
6. duty-cycle limit: after ``duty_on_s`` of continuous ON the relay rests for
   ``duty_rest_s`` (the logical state stays ON, so the pulse resumes after the rest).

Defaults are the firmware's Config.h values (FW 1.1.x): band 0.4 °C, anticipation 0.1 °C,
coast lead 200 s, min off 30 s, duty 600 s on / 60 s rest.

:class:`PlainHysteresis` is the textbook thermostat (steps 1 and 4 only, no anticipation),
kept for the comparison.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class PlainHysteresis:
    """Textbook thermostat: ON below target − band/2, OFF above target + band/2."""

    band: float = 0.4
    period_s: float = 1.0
    name: str = "on/off plain"
    _on: bool = field(default=False, repr=False)

    def reset(self) -> None:
        self._on = False

    def decide(self, t_s: float, temp: float, target: float) -> bool:
        lo = target - self.band / 2
        hi = target + self.band / 2
        if temp < lo:
            self._on = True
        elif temp > hi:
            self._on = False
        return self._on


@dataclass
class FirmwareHysteresis:
    """The incubator firmware's heater decision (see module docstring)."""

    band: float = 0.4
    anticipation: float = 0.1
    coast_lead_s: float = 200.0
    min_off_s: float = 30.0
    duty_on_s: float = 600.0
    duty_rest_s: float = 60.0
    rate_window: int = 60  # samples
    rate_min_span: int = 20  # samples
    min_gap: float = 0.05
    period_s: float = 1.0
    name: str = "on/off firmware"

    _buf: deque[float] = field(default_factory=deque, repr=False)
    _logical_on: bool = field(default=False, repr=False)
    _logical_off_at: float | None = field(default=None, repr=False)
    _on_since: float | None = field(default=None, repr=False)
    _resting: bool = field(default=False, repr=False)
    _rest_start: float = field(default=0.0, repr=False)
    last_rate: float = field(default=0.0, repr=False)
    last_projected: float = field(default=0.0, repr=False)

    def reset(self) -> None:
        self._buf = deque(maxlen=self.rate_window)
        self._logical_on = False
        self._logical_off_at = None
        self._on_since = None
        self._resting = False
        self._rest_start = 0.0
        self.last_rate = 0.0
        self.last_projected = 0.0

    def __post_init__(self) -> None:
        self.reset()

    # -- pieces, each testable on its own -------------------------------------------
    def thresholds(self, target: float) -> tuple[float, float]:
        lo = target - self.band / 2
        hi = target + self.band / 2 - self.anticipation
        if hi < lo + self.min_gap:
            hi = lo + self.min_gap
        return lo, hi

    def rise_rate(self, temp: float) -> float:
        """°C/s over the stored window, 0 until ``rate_min_span`` samples exist, never < 0."""
        span = len(self._buf)
        oldest = self._buf[0] if span else temp
        self._buf.append(temp)
        if span < self.rate_min_span:
            return 0.0
        rate = (temp - oldest) / (span * self.period_s)
        return rate if rate > 0.0 else 0.0

    def lockout(self, t_s: float) -> bool:
        """What the firmware does while the Interlock blocks the heater."""
        self._logical_on = False
        self._resting = False
        self._on_since = None
        return False

    # -- the decision --------------------------------------------------------------
    def decide(self, t_s: float, temp: float, target: float) -> bool:
        lo, hi = self.thresholds(target)
        rate = self.rise_rate(temp)
        projected = temp + rate * self.coast_lead_s
        self.last_rate, self.last_projected = rate, projected

        nxt = self._logical_on
        if projected < lo:
            nxt = True
        elif projected > hi:
            nxt = False

        # minimum OFF time applies to switching ON only
        if (
            nxt
            and not self._logical_on
            and self._logical_off_at is not None
            and (t_s - self._logical_off_at) < self.min_off_s
        ):
            nxt = False
        if not nxt and self._logical_on:
            self._logical_off_at = t_s
        self._logical_on = nxt
        desired = nxt

        # duty-cycle gate: forced rest after duty_on_s of continuous relay ON
        if self.duty_on_s > 0:
            if desired:
                if self._resting:
                    if t_s - self._rest_start < self.duty_rest_s:
                        desired = False
                    else:
                        self._resting = False
                elif self._on_since is not None and (t_s - self._on_since) >= self.duty_on_s:
                    self._resting = True
                    self._rest_start = t_s
                    desired = False
            else:
                self._resting = False

        # relay on-time tracking (Heater::onDurationMs)
        if desired:
            if self._on_since is None:
                self._on_since = t_s
        else:
            self._on_since = None
        return desired
