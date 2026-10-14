"""Controller protocol shared by every heater controller."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Controller(Protocol):
    name: str
    period_s: float

    def decide(self, t_s: float, temp: float, target: float) -> bool:
        """Return True to switch the heater relay on for the next period."""
        ...

    def reset(self) -> None: ...
