import numpy as np
import pytest

from thermosim.controllers import (
    FirmwareHysteresis,
    MPCSketch,
    PIDRelay,
    PlainHysteresis,
    tune_pid_simc,
)

# ---------------------------------------------------------------- firmware on/off


def test_firmware_thresholds_match_config_h_defaults():
    c = FirmwareHysteresis()
    lo, hi = c.thresholds(34.5)
    assert lo == pytest.approx(34.3)  # target − 0.4/2
    assert hi == pytest.approx(34.6)  # target + 0.2 − 0.1 anticipation


def test_firmware_threshold_gap_is_kept():
    c = FirmwareHysteresis(band=0.2, anticipation=0.3)
    lo, hi = c.thresholds(34.5)
    assert hi == pytest.approx(lo + 0.05)


def test_rise_rate_zero_until_twenty_samples_and_never_negative():
    c = FirmwareHysteresis()
    for i in range(20):
        assert c.rise_rate(30.0 + 0.01 * i) == 0.0
    # 20 samples stored: span 20, oldest = 30.00, now 30.20 -> 0.01 °C/s
    assert c.rise_rate(30.20) == pytest.approx(0.20 / 20)
    c.reset()
    for i in range(30):
        c.rise_rate(35.0 - 0.01 * i)
    assert c.rise_rate(34.0) == 0.0


def test_firmware_switches_on_below_band_and_off_at_anticipated_edge():
    c = FirmwareHysteresis()
    assert c.decide(0.0, 34.0, 34.5) is True
    assert c.decide(1.0, 34.55, 34.5) is True  # inside the band: keep state
    assert c.decide(2.0, 34.61, 34.5) is False  # above hi = 34.6 (no rise history yet)


def test_coast_lead_switches_off_early_when_rising():
    c = FirmwareHysteresis()
    t = 0.0
    temp = 33.0
    states = []
    while t < 200:
        states.append(c.decide(t, temp, 34.5))
        temp += 0.005  # 0.3 °C/min, like a real heat-up
        t += 1.0
    # projected = temp + 0.005 °C/s × 200 s = temp + 1.0, so it turns off ≈1 °C early
    temps = np.arange(33.0, 34.0, 0.005)
    off_at = next(temp_ for temp_, s in zip(temps, states, strict=False) if not s)
    assert 33.3 < off_at <= 33.65  # measured 33.6 when hi = 34.6: one degree early


def test_min_off_time_refuses_quick_restart():
    c = FirmwareHysteresis()
    assert c.decide(0.0, 33.0, 34.5) is True
    assert c.decide(1.0, 35.0, 34.5) is False  # off at t=1
    assert c.decide(10.0, 33.0, 34.5) is False  # too soon
    assert c.decide(31.0, 33.0, 34.5) is True  # 30 s elapsed


def test_duty_cycle_rest_after_ten_minutes():
    c = FirmwareHysteresis()
    states = [c.decide(float(t), 30.0, 34.5) for t in range(1400)]
    assert all(states[:600])
    assert not any(states[600:660])  # 60 s forced rest
    assert all(states[660:1260])  # second pulse
    assert not any(states[1260:1320])


def test_duty_limit_can_be_disabled():
    c = FirmwareHysteresis(duty_on_s=0)
    assert all(c.decide(float(t), 30.0, 34.5) for t in range(2000))


def test_lockout_clears_state():
    c = FirmwareHysteresis()
    for t in range(700):
        c.decide(float(t), 30.0, 34.5)
    assert c.lockout(700.0) is False
    assert c.decide(701.0, 30.0, 34.5) is True  # fresh pulse, not mid-rest


def test_plain_hysteresis():
    c = PlainHysteresis(band=0.4)
    assert c.decide(0, 34.2, 34.5) is True
    assert c.decide(1, 34.5, 34.5) is True
    assert c.decide(2, 34.71, 34.5) is False
    assert c.decide(3, 34.5, 34.5) is False


# ---------------------------------------------------------------- PID


def test_simc_tuning_on_the_fitted_plant():
    kp, ti, td = tune_pid_simc(0.5539, 0.0101, 210.0)
    # K = 54.8 °C, τ = 99 min, θ = 3.5 min, τc = θ -> Kc = 99/(54.8·7) ≈ 0.258, Ti = 4·7 = 28 min
    assert kp == pytest.approx(0.258, abs=0.005)
    assert ti == pytest.approx(28.0, abs=0.01)
    assert td == 0.0


def test_pid_saturates_and_does_not_wind_up():
    pid = PIDRelay(kp=0.5, ti_min=10.0, window_s=60.0)
    for _ in range(200):
        duty = pid.compute_duty(0.0, 33.5, 34.5)  # 1 °C below target: P = 0.5, I grows
    assert duty == 1.0
    assert pid._integral == pytest.approx(0.5, abs=0.06)  # stopped when the output saturated
    # 1 °C above target: P = −0.5 cancels the integral at once, no long tail
    assert pid.compute_duty(0.0, 35.5, 34.5) < 0.1


def test_pid_quantiser_respects_minimum_pulse():
    pid = PIDRelay(window_s=120.0, min_pulse_s=10.0, period_s=1.0)
    assert pid.quantise(0.0) == 0.0
    assert pid.quantise(0.05) == 0.0  # 6 s < 10 s minimum pulse: dropped
    assert pid.quantise(0.5) == 60.0
    assert pid.quantise(0.97) == 120.0  # 3.6 s gap: filled


def test_pid_decide_holds_the_pulse_for_the_window():
    pid = PIDRelay(kp=1.0, ti_min=0.0, window_s=100.0, min_pulse_s=1.0)
    states = [pid.decide(float(t), 34.0, 34.5) for t in range(100)]  # duty 0.5 -> 50 s on
    assert sum(states) == 50 and all(states[:50]) and not any(states[50:])


# ---------------------------------------------------------------- MPC


def test_mpc_full_duty_when_far_below_and_zero_when_above():
    mpc = MPCSketch(horizon=3, levels=3)
    assert mpc.plan(25.0, 34.5) == 1.0
    assert mpc.plan(36.0, 34.5) == 0.0


def test_mpc_bias_tracks_model_error():
    mpc = MPCSketch(horizon=2, levels=2, window_s=60.0)
    mpc.decide(0.0, 30.0, 34.5)
    predicted = mpc._predicted
    assert predicted is not None
    mpc.decide(60.0, predicted + 1.0, 34.5)  # chamber 1 °C warmer than the model said
    assert mpc._bias == pytest.approx(0.5)  # low-passed half way


def test_mpc_duties_come_from_the_grid():
    mpc = MPCSketch(horizon=2, levels=5)
    grid = {0.0, 0.25, 0.5, 0.75, 1.0}
    for temp in (30.0, 34.0, 34.4, 34.6, 36.0):
        assert mpc.plan(temp, 34.5) in grid
