import numpy as np
import pandas as pd
import pytest

from thermosim import metrics, scenarios, simulate
from thermosim.controllers import FirmwareHysteresis, PlainHysteresis
from thermosim.disturbances import DoorSchedule, TraceAmbient, load_trace
from thermosim.plant import FirstOrderPlant, HeaterLagPlant, load_params, make_plant
from thermosim.simulate import Scenario


def test_cold_start_reaches_band_without_big_overshoot():
    df = simulate.run(HeaterLagPlant(), FirmwareHysteresis(), scenarios.cold_start(2 * 3600))
    m = metrics.compute(df, 0.59)
    assert m.time_to_target_min is not None and m.time_to_target_min < 40
    assert m.overshoot_c < 0.3
    assert df["heater"].iloc[0] == 1


def test_plain_thermostat_overshoots_on_the_lagging_plant():
    df = simulate.run(HeaterLagPlant(), PlainHysteresis(), scenarios.cold_start(2 * 3600))
    assert metrics.compute(df, 0.59).overshoot_c > 1.0


def test_door_open_blocks_the_heater_and_raises_loss():
    sc = Scenario(
        name="door",
        duration_s=1800,
        t0=34.4,
        targets=[(0.0, 34.5)],
        door=DoorSchedule(openings=((600.0, 300.0),), loss_gain=10.0),
    )
    df = simulate.run(FirstOrderPlant(), FirmwareHysteresis(), sc)
    while_open = df[(df.t_s >= 600) & (df.t_s < 900)]
    assert while_open["heater"].sum() == 0
    assert while_open["locked"].all()
    assert df.loc[df.t_s == 899, "temp"].item() < df.loc[df.t_s == 600, "temp"].item() - 1.0
    assert df.loc[df.t_s > 900, "heater"].sum() > 0  # recovery starts


def test_thermal_cutoff_latches_at_40_degrees():
    sc = Scenario(name="hot", duration_s=4 * 3600, t0=30.0, targets=[(0.0, 45.0)])
    df = simulate.run(FirstOrderPlant(dead_time_s=0.0), PlainHysteresis(), sc)
    assert df["temp"].max() < 40.2
    assert df["locked"].sum() > 0
    # heater is off while latched and comes back only after cooling 0.5 °C
    hot = df[df.temp >= 40.0]
    assert hot["heater"].sum() == 0


def test_target_schedule_steps():
    sc = scenarios.setpoint_step(2 * 3600)
    assert sc.target_at(0.0) == 34.5 and sc.target_at(3599.0) == 34.5
    assert sc.target_at(3600.0) == 36.5


def test_trace_ambient_holds_values_and_scales():
    amb = TraceAmbient.from_csv()
    assert amb.at(-5.0) == amb.values[0]
    assert amb.at(1e9) == amb.values[-1]
    assert amb.at(7.0) == amb.values[0]  # held between 0 s and 15 s
    doubled = TraceAmbient.from_csv(scale=2.0)
    dev = amb.at(10_000.0) - amb.values[0]
    assert doubled.at(10_000.0) - amb.values[0] == pytest.approx(2 * dev)


def test_switch_count_and_metrics_on_synthetic_frame():
    assert metrics.switch_count(pd.Series([0, 1, 1, 0, 1, 0])) == 2
    assert metrics.switch_count(pd.Series([1, 0, 1])) == 2
    t = np.arange(0, 600, 1.0)
    temp = np.where(t < 100, 34.0, 34.8)
    df = pd.DataFrame({"t_s": t, "temp": temp, "target": 34.5, "heater": (t < 100).astype(int)})
    m = metrics.compute(df, a=0.6, band=0.4)
    assert m.time_to_target_min is None  # never inside ±0.2
    assert m.heater_on_min == pytest.approx(100 / 60, abs=0.01)
    assert m.heating_c == pytest.approx(1.0, abs=0.01)
    assert m.switches == 1
    assert metrics.energy_kwh_at(60.0, 100.0) == pytest.approx(0.1)


def test_replay_of_the_real_day_matches_the_measured_trace():
    """Firmware logic + fitted plant, fed the real day's targets and ambient, should land
    close to what the device actually did. In-sample (the plant was fitted on this day)."""
    rows = load_trace()
    sc = scenarios.replay()
    plant = make_plant("heater_lag", load_params())
    df = simulate.run(plant, FirmwareHysteresis(), sc)
    sim = df.set_index("t_s")["temp"].reindex([r["t_s"] for r in rows]).to_numpy()
    real = np.array([r["temp"] for r in rows])
    rmse = float(np.sqrt(np.nanmean((sim - real) ** 2)))
    assert rmse < 1.0
    real_on = np.mean([r["heater"] for r in rows])
    sim_on = df["heater"].mean()
    assert abs(sim_on - real_on) < 0.1
