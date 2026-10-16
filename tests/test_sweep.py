import json
from pathlib import Path

import numpy as np
import pytest

from thermosim import scenarios
from thermosim.controllers import FirmwareHysteresis
from thermosim.sweep import sweep_firmware

RESULTS = Path(__file__).resolve().parents[1] / "figures" / "results.json"


@pytest.fixture(scope="module")
def sweep():
    return sweep_firmware(
        scenarios.cold_start(), anticipations=(0.0, 0.1, 0.3), coast_leads_s=(0.0, 200.0, 400.0)
    )


def test_sweep_shapes_and_lookup(sweep):
    assert sweep.overshoot_c.shape == (3, 3)
    assert sweep.switches.dtype.kind == "i"
    cell = sweep.at(0.1, 200.0)
    assert set(cell) == {"overshoot_c", "final_error_c", "time_to_target_min", "switches"}
    d = sweep.as_dict()
    assert d["anticipations_c"] == [0.0, 0.1, 0.3] and len(d["overshoot_c"]) == 3


def test_shipped_constants_reproduce_the_cold_start_row(sweep):
    """The (0.1 °C, 200 s) cell is the firmware controller as run in the main matrix."""
    fw = FirmwareHysteresis()
    cell = sweep.at(fw.anticipation, fw.coast_lead_s)
    row = json.loads(RESULTS.read_text())["matrix"]["heater_lag"]["cold start"]["on/off firmware"]
    assert cell["overshoot_c"] == pytest.approx(row["overshoot_c"], abs=1e-3)
    assert cell["final_error_c"] == pytest.approx(row["final_error_c"], abs=1e-3)
    assert cell["switches"] == row["switches"]


def test_coast_lead_removes_the_overshoot_and_costs_bias(sweep):
    """More coast lead -> less overshoot but a more negative final error, at every anticipation."""
    over, final = sweep.overshoot_c, sweep.final_error_c
    assert np.all(np.diff(over, axis=1) <= 1e-9)
    assert np.all(np.diff(final, axis=1) <= 1e-9)
    assert over[1, 0] > 1.0  # no coast lead: the thermostat-like overshoot
    assert over[1, 1] < 0.2 and final[1, 1] < 0.0  # the shipped pair


def test_anticipation_alone_cannot_fix_the_lagging_plant(sweep):
    """Without a coast lead, 0.3 °C of anticipation still leaves > 1 °C of overshoot."""
    assert sweep.overshoot_c[2, 0] > 1.0
