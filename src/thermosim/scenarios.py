"""The scenarios the README and the Streamlit page use, plus the default controller set.

Numbers that come from the real data: ambient 27.2 °C (first reading of 2026-10-03), the
targets 32.0 / 34.5 / 38.8 °C the firmware actually used that day (34.5 is Config.h's
default, 38.8 its maximum), and the ``tempOut`` trace. The door scenario's loss multiplier
and the hotter-day offset are illustrative.
"""

from __future__ import annotations

from thermosim.controllers import FirmwareHysteresis, MPCSketch, PIDRelay, PlainHysteresis
from thermosim.controllers.base import Controller
from thermosim.disturbances import ConstantAmbient, DoorSchedule, TraceAmbient, load_trace
from thermosim.plant import load_params
from thermosim.simulate import Scenario

AMBIENT = 27.2
TARGET = 34.5
STEADY_START = 34.4  # just inside the band: "already running" scenarios begin here


def cold_start(duration_s: float = 4 * 3600) -> Scenario:
    return Scenario(
        name="cold start",
        duration_s=duration_s,
        t0=AMBIENT,
        targets=[(0.0, TARGET)],
        description="Chamber at ambient 27.2 °C, target 34.5 °C from t = 0.",
    )


def setpoint_step(duration_s: float = 5 * 3600) -> Scenario:
    return Scenario(
        name="setpoint step",
        duration_s=duration_s,
        t0=STEADY_START,
        targets=[(0.0, TARGET), (3600.0, 36.5)],
        description="Holding 34.5 °C, target raised to 36.5 °C after one hour.",
    )


def door_opening(
    duration_s: float = 4 * 3600, open_s: float = 600.0, loss_gain: float = 10.0
) -> Scenario:
    return Scenario(
        name="door opening",
        duration_s=duration_s,
        t0=STEADY_START,
        targets=[(0.0, TARGET)],
        door=DoorSchedule(openings=((3600.0, open_s),), loss_gain=loss_gain),
        description=(
            f"Holding 34.5 °C, door open for {open_s / 60:.0f} min after one hour "
            f"(loss ×{loss_gain:g}, illustrative); heater interlocked off while open."
        ),
    )


def ambient_drift(scale: float = 1.0, offset: float = 0.0) -> Scenario:
    amb = TraceAmbient.from_csv(scale=scale, offset=offset)
    label = "real tempOut trace of 2026-10-03"
    if scale != 1.0 or offset != 0.0:
        label += f" (deviation ×{scale:g}, offset {offset:+g} °C, illustrative)"
    return Scenario(
        name="ambient drift",
        duration_s=amb.duration_s,
        t0=STEADY_START,
        targets=[(0.0, TARGET)],
        ambient=amb,
        description=f"Holding 34.5 °C while ambient follows the {label}.",
    )


def replay() -> Scenario:
    """The real day: its target changes and its ambient, from its first reading."""
    rows = load_trace()
    targets: list[tuple[float, float]] = []
    for r in rows:
        if not targets or r["target"] != targets[-1][1]:
            targets.append((r["t_s"], r["target"]))
    return Scenario(
        name="replay 2026-10-03",
        duration_s=rows[-1]["t_s"] + 1.0,  # include the last reading
        t0=rows[0]["temp"],
        targets=targets,
        ambient=TraceAmbient.from_csv(),
        description="The real day's target schedule and ambient, fed to the fitted plant.",
    )


def default_controllers(params: dict | None = None, t_out: float = AMBIENT) -> list[Controller]:
    """The four controllers compared everywhere, tuned once from the fitted parameters."""
    params = params or load_params()
    fo = params["first_order"]
    so = params["second_order"]
    pid = PIDRelay()
    pid.kp, pid.ti_min, pid.td_min = _simc(fo)
    return [
        FirmwareHysteresis(),
        PlainHysteresis(),
        pid,
        # the MPC predicts with the heater-lag fit (a, tau_h, b), the better of the two
        # fitted models; the PID is tuned on the first-order fit because SIMC wants a dead time
        MPCSketch(
            a=so["a_c_per_min"],
            tau_h_min=so["tau_h_min"],
            b=so["b_per_min"],
            t_out_assumed=t_out,
        ),
    ]


def _simc(fo: dict) -> tuple[float, float, float]:
    from thermosim.controllers import tune_pid_simc

    return tune_pid_simc(fo["a_c_per_min"], fo["b_per_min"], fo["dead_time_s"])


def all_scenarios() -> list[Scenario]:
    return [cold_start(), setpoint_step(), door_opening(), ambient_drift()]


__all__ = [
    "ConstantAmbient",
    "all_scenarios",
    "ambient_drift",
    "cold_start",
    "default_controllers",
    "door_opening",
    "replay",
    "setpoint_step",
]
