import math

import pytest

from thermosim.plant import (
    ChamberWallPlant,
    FirstOrderPlant,
    HeaterLagPlant,
    load_params,
    make_plant,
)


def _run(plant, u, t_out, minutes):
    for _ in range(int(minutes * 60 / plant.dt_s)):
        plant.step(u, t_out)
    return plant.temp


def test_params_file_has_both_fits():
    p = load_params()
    assert p["first_order"]["a_c_per_min"] == pytest.approx(0.5539)
    assert p["second_order"]["tau_h_min"] == pytest.approx(4.9175)


@pytest.mark.parametrize("name", ["first_order", "heater_lag", "chamber_wall"])
def test_full_power_steady_state_is_ambient_plus_gain(name):
    plant = make_plant(name, temp=27.0)
    final = _run(plant, 1.0, 27.0, 12 * 60)  # 12 h ≈ 7 time constants
    assert final == pytest.approx(27.0 + plant.a / plant.b, abs=0.1)


def test_first_order_cool_down_follows_time_constant():
    plant = FirstOrderPlant(a=0.5, b=0.01, dead_time_s=0.0, temp=37.0)
    _run(plant, 0.0, 27.0, 100.0)  # one time constant
    assert plant.temp - 27.0 == pytest.approx(10.0 * math.exp(-1.0), abs=0.02)


def test_first_order_dead_time_delays_the_heater():
    plant = FirstOrderPlant(a=0.5, b=0.0, dead_time_s=60.0, dt_s=1.0, temp=30.0)
    for _ in range(60):
        plant.step(1.0, 30.0)
    assert plant.temp == pytest.approx(30.0)  # nothing arrived yet
    plant.step(1.0, 30.0)
    assert plant.temp > 30.0


def test_heater_lag_rises_slowly_at_first():
    plant = HeaterLagPlant(temp=27.0)
    first_minute = _run(plant, 1.0, 27.0, 1.0) - 27.0
    before = _run(plant, 1.0, 27.0, 9.0)
    tenth_minute = _run(plant, 1.0, 27.0, 1.0) - before
    assert first_minute < 0.1  # element still cold
    assert tenth_minute > 3 * first_minute  # element warmed up
    plant.reset(27.0)
    assert plant.e == 0.0 and plant.temp == 27.0


def test_chamber_wall_rejects_impossible_parameters():
    with pytest.raises(ValueError):
        ChamberWallPlant(wall_fraction=1.0)
    with pytest.raises(ValueError):
        ChamberWallPlant(b=0.01, tau_cw_min=200.0)


def test_chamber_wall_air_responds_faster_than_first_order():
    fo = FirstOrderPlant(dead_time_s=0.0, temp=27.0)
    cw = ChamberWallPlant(temp=27.0)
    assert _run(cw, 1.0, 27.0, 2.0) > _run(fo, 1.0, 27.0, 2.0)


def test_door_loss_gain_cools_faster():
    slow = FirstOrderPlant(dead_time_s=0.0, temp=35.0)
    fast = FirstOrderPlant(dead_time_s=0.0, temp=35.0)
    for _ in range(600):
        slow.step(0.0, 27.0, 1.0)
        fast.step(0.0, 27.0, 10.0)
    assert fast.temp < slow.temp
